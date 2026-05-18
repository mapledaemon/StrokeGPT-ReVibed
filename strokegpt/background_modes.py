"""Background mode orchestration.

This module is the scheduling and pacing layer for Auto, Edge, Milk, and
Freestyle modes. Decision parsing lives in :mod:`strokegpt.mode_decisions`
and the Freestyle planner helpers live in :mod:`strokegpt.freestyle`;
this module imports from both and wires them into the long-running mode
loops. The `random` binding and public type/constant compatibility exports
are kept only where the compatibility surface still needs them.

``auto_mode_logic`` is the legacy scripted Auto takeover loop. Keep the
``auto`` route/state names for compatibility, but do not treat this path as
Freestyle legacy or expand it toward adaptive Freestyle behavior.
"""

import random
import re
import threading
import time
from typing import cast

from . import freestyle as freestyle_helpers
from . import mode_decisions as mode_decision_helpers
from .freestyle import (
    FREESTYLE_CHAIN_LENGTH,
    FREESTYLE_DECISION_GRACE_SECONDS,
    FREESTYLE_EDGE_RESUME_CHAIN_LENGTH,
    FreestyleChoice,
)
from .mode_decisions import (
    MODE_DECISION_ACTIONS,
    ModeDecision,
)
from .mode_contracts import ModeCallbacks, ModeLogic, ModeServices
from .motion import IntentMatcher
from .motion_patterns import PATTERNS
from .motion_scripts import MotionScriptPlanner, ScriptStep


INTENT_MATCHER = IntentMatcher()

EDGE_START_MIN_STEPS = 12
EDGE_PROGRESS_MIN_STEPS = 10
AUTOSPEAK_RESCHEDULE_FLOOR_SECONDS = 8.0
MODE_TARGET_NOISE_SPEED_DELTA = 3.0
MODE_TARGET_NOISE_DEPTH_DELTA = 5.0
MODE_TARGET_NOISE_RANGE_DELTA = 5.0


__all__ = [
    # Public mode entry points used by web.py.
    "AutoModeThread",
    "auto_mode_logic",
    "edging_mode_logic",
    "freestyle_mode_logic",
    "milking_mode_logic",
    # Constants kept at this layer for orchestration.
    "INTENT_MATCHER",
    "EDGE_START_MIN_STEPS",
    "EDGE_PROGRESS_MIN_STEPS",
    # Compatibility shim - do not extend. These names keep historical
    # ``background_modes`` imports working while callers migrate.
    "ModeDecision",
    "MODE_DECISION_ACTIONS",
    "FreestyleChoice",
    "FREESTYLE_CHAIN_LENGTH",
    "FREESTYLE_DECISION_GRACE_SECONDS",
    "FREESTYLE_EDGE_RESUME_CHAIN_LENGTH",
    "ModeCallbacks",
    "ModeLogic",
    "ModeServices",
]


class AutoModeThread(threading.Thread):
    def __init__(
        self,
        mode_func: ModeLogic,
        initial_message: str,
        services: ModeServices,
        callbacks: ModeCallbacks,
        mode_name: str = "auto",
        initial_delay: float = 0.1,
    ):
        super().__init__()
        self.name = mode_name
        self._mode_func: ModeLogic = mode_func
        self._initial_message = initial_message
        self._services: ModeServices = services
        self._pause_event = threading.Event()
        self._callbacks = cast(ModeCallbacks, dict(callbacks))
        self._callbacks["pause_event"] = self._pause_event
        self._initial_delay = initial_delay
        self._stop_event = threading.Event()
        self.daemon = True

    def run(self):
        message_callback = self._callbacks.get("send_message")
        motion_controller = self._services.get("motion")

        if message_callback:
            message_callback(self._initial_message)

        try:
            if self._stop_event.wait(self._initial_delay):
                return
            self._mode_func(self._stop_event, self._services, self._callbacks)
        except Exception as e:
            print(f"Auto mode crashed: {e}")
        finally:
            finalize_callback = self._callbacks.get("should_finalize_on_exit")
            should_finalize = True
            if finalize_callback:
                try:
                    should_finalize = bool(finalize_callback())
                except Exception:
                    should_finalize = True

            if motion_controller and should_finalize:
                motion_controller.stop()

            stop_callback = self._callbacks.get("on_stop")
            if stop_callback and should_finalize:
                stop_callback()

            if message_callback and should_finalize:
                message_callback("Okay, you're in control now.")

    def stop(self):
        self._stop_event.set()
        self._pause_event.clear()
        motion_controller = self._services.get("motion")
        if motion_controller and hasattr(motion_controller, "stop"):
            motion_controller.stop()

    def pause(self):
        self._pause_event.set()
        motion_controller = self._services.get("motion")
        if motion_controller and hasattr(motion_controller, "pause"):
            motion_controller.pause()
        elif motion_controller and hasattr(motion_controller, "stop"):
            motion_controller.stop()

    def resume(self):
        motion_controller = self._services.get("motion")
        if motion_controller and hasattr(motion_controller, "resume"):
            motion_controller.resume()
        self._pause_event.clear()

    def is_paused(self):
        return self._pause_event.is_set()


def _check_for_user_message(queue, message_event=None):
    if queue:
        try:
            return queue.popleft()
        except IndexError:
            pass
    if message_event and not queue:
        message_event.clear()
    return None


def _semantic_target(motion_controller):
    getter = getattr(motion_controller, "semantic_target", None)
    return getter() if callable(getter) else motion_controller.current_target()


def _feedback_target(stop_event, motion_controller, user_message):
    if not user_message:
        return None
    intent = INTENT_MATCHER.parse(user_message, _semantic_target(motion_controller))
    if intent.kind == "stop":
        stop_event.set()
        return None
    if intent.kind == "move":
        return intent.target
    return None


def _wait_while_paused(stop_event, pause_event=None):
    if not pause_event:
        return False
    while pause_event.is_set() and not stop_event.is_set():
        stop_event.wait(0.05)
    return stop_event.is_set()


def _sleep_with_stop(stop_event, seconds, wake_event=None, pause_event=None):
    seconds = max(0.0, float(seconds or 0.0))
    if _wait_while_paused(stop_event, pause_event):
        return
    if seconds <= 0:
        time.sleep(0)
        return
    deadline = time.monotonic() + seconds
    while not stop_event.is_set():
        if pause_event and pause_event.is_set():
            paused_at = time.monotonic()
            if _wait_while_paused(stop_event, pause_event):
                return
            deadline += time.monotonic() - paused_at
            if wake_event and wake_event.is_set():
                return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        wait_time = min(0.1, remaining)
        if stop_event.wait(wait_time):
            return
        if wake_event and wake_event.is_set():
            return


def _autospeak_enabled(callbacks: ModeCallbacks):
    enabled = callbacks.get("autospeak_enabled")
    if not enabled:
        return False
    try:
        return bool(enabled())
    except Exception:
        return False


def _autospeak_range(callbacks: ModeCallbacks):
    return mode_decision_helpers._autospeak_range_from_callbacks(callbacks)


def _autospeak_interval_from_decision(callbacks: ModeCallbacks, decision, current_interval=None):
    min_seconds, max_seconds = _autospeak_range(callbacks)
    return mode_decision_helpers._autospeak_interval_from_decision(
        decision,
        current_interval,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
    )


def _default_autospeak_interval(callbacks: ModeCallbacks):
    return _autospeak_interval_from_decision(callbacks, ModeDecision(), None)


def _initial_autospeak_schedule(callbacks: ModeCallbacks):
    interval = _default_autospeak_interval(callbacks)
    min_seconds, _max_seconds = _autospeak_range(callbacks)
    first_interval = min_seconds if _autospeak_enabled(callbacks) else interval
    return interval, _next_autospeak_at(first_interval)


def _consume_autospeak_wake(callbacks: ModeCallbacks):
    consumer = callbacks.get("consume_autospeak_wake")
    if not consumer:
        return False
    try:
        return bool(consumer())
    except Exception:
        return False


def _send_background_decision_message(callbacks: ModeCallbacks, send_message, decision):
    if not decision.chat or decision.source != "llm":
        return False
    if _autospeak_enabled(callbacks) and mode_decision_helpers._send_autospeak_message(callbacks, decision):
        return True
    mode_decision_helpers._send_mode_decision_message(send_message, decision)
    return True


def _next_autospeak_at(interval_seconds):
    interval = max(0.0, float(interval_seconds or 0.0))
    return time.monotonic() + max(AUTOSPEAK_RESCHEDULE_FLOOR_SECONDS, interval)


def _maybe_send_autospeak(
    callbacks: ModeCallbacks,
    mode,
    autospeak_interval,
    next_autospeak_at,
    *,
    edge_count=0,
    current_target=None,
):
    autospeak_interval = max(0.0, float(autospeak_interval or 0.0))
    next_autospeak_at = float(next_autospeak_at or 0.0)
    force_due = _consume_autospeak_wake(callbacks)
    if not _autospeak_enabled(callbacks):
        autospeak_interval = _autospeak_interval_from_decision(callbacks, ModeDecision(), autospeak_interval)
        return autospeak_interval, _next_autospeak_at(autospeak_interval)
    if force_due:
        min_seconds, _max_seconds = _autospeak_range(callbacks)
        next_autospeak_at = _next_autospeak_at(min_seconds)
    if time.monotonic() < next_autospeak_at:
        return autospeak_interval, next_autospeak_at

    decision = mode_decision_helpers._request_mode_decision(
        callbacks,
        mode,
        "autospeak",
        edge_count=edge_count,
        current_target=current_target,
    )
    sent = mode_decision_helpers._send_autospeak_message(callbacks, decision)
    autospeak_interval = _autospeak_interval_from_decision(callbacks, decision, autospeak_interval)
    if not sent:
        min_seconds, _max_seconds = _autospeak_range(callbacks)
        autospeak_interval = min_seconds
    return autospeak_interval, _next_autospeak_at(autospeak_interval)


def _sleep_with_autospeak(
    stop_event,
    seconds,
    callbacks: ModeCallbacks,
    mode,
    autospeak_interval,
    next_autospeak_at,
    *,
    wake_event=None,
    pause_event=None,
    edge_count=0,
    current_target=None,
):
    if not _autospeak_enabled(callbacks):
        _sleep_with_stop(stop_event, seconds, wake_event, pause_event)
        return autospeak_interval, next_autospeak_at

    seconds = max(0.0, float(seconds or 0.0))
    deadline = time.monotonic() + seconds
    while not stop_event.is_set():
        if pause_event and pause_event.is_set():
            paused_at = time.monotonic()
            if _wait_while_paused(stop_event, pause_event):
                break
            deadline += time.monotonic() - paused_at
            if wake_event and wake_event.is_set():
                break

        autospeak_interval, next_autospeak_at = _maybe_send_autospeak(
            callbacks,
            mode,
            autospeak_interval,
            next_autospeak_at,
            edge_count=edge_count,
            current_target=current_target() if callable(current_target) else current_target,
        )
        if wake_event and wake_event.is_set():
            break

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        next_wait = max(0.0, next_autospeak_at - time.monotonic())
        wait_time = min(0.1, remaining, next_wait)
        if wait_time <= 0:
            continue
        if stop_event.wait(wait_time):
            break
    return autospeak_interval, next_autospeak_at


def _set_active_mode(callbacks: ModeCallbacks, mode_name):
    setter = callbacks.get("set_mode_name")
    if setter:
        setter(mode_name)
    try:
        threading.current_thread().name = mode_name
    except Exception:
        pass


def _uses_continuous_motion(motion_controller) -> bool:
    return getattr(motion_controller, "backend", "") == "continuous"


def _uses_timed_pattern_motion(motion_controller) -> bool:
    return getattr(motion_controller, "backend", "") in {"continuous", "position"}


def _mode_pattern_id_from_target(target) -> str:
    label = getattr(target, "label", "") or ""
    parts = set(re.split(r"[^a-z0-9_-]+", label.lower()))
    slug_label = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-_")
    for pattern_id in sorted(PATTERNS, key=len, reverse=True):
        if (
            pattern_id in parts
            or slug_label == pattern_id
            or slug_label.startswith(f"{pattern_id}-")
        ):
            return pattern_id
    return ""


def _mode_target_is_redundant(current, target) -> bool:
    if not current or not target:
        return False
    if getattr(target, "motion_program", None):
        return False
    current_pattern = _mode_pattern_id_from_target(current)
    target_pattern = _mode_pattern_id_from_target(target)
    if current_pattern or target_pattern:
        if current_pattern != target_pattern:
            return False
    try:
        current = current.rounded()
        target = target.rounded()
        return (
            abs(current.speed - target.speed) <= MODE_TARGET_NOISE_SPEED_DELTA
            and abs(current.depth - target.depth) <= MODE_TARGET_NOISE_DEPTH_DELTA
            and abs(current.stroke_range - target.stroke_range) <= MODE_TARGET_NOISE_RANGE_DELTA
        )
    except Exception:
        return False


def _apply_mode_motion(motion_controller, target, source):
    if _mode_target_is_redundant(_semantic_target(motion_controller), target):
        return False
    if _uses_timed_pattern_motion(motion_controller):
        motion_controller.apply_generated_target(target, source=source)
        return True
    else:
        motion_controller.apply_target(target, source=source)
        return True


def _mode_step_sleep_seconds(base_seconds: float, step: ScriptStep, motion_controller) -> float:
    sleep_seconds = max(0.0, float(base_seconds or 0.0))
    if not _uses_continuous_motion(motion_controller):
        return sleep_seconds
    try:
        hold_floor = max(0.0, float(getattr(step, "hold_seconds_floor", 0.0) or 0.0))
    except (TypeError, ValueError):
        hold_floor = 0.0
    return max(sleep_seconds, hold_floor)


def _run_scripted_mode(
    stop_event: threading.Event,
    services: ModeServices,
    callbacks: ModeCallbacks,
    mode: str,
    max_steps=None,
    *,
    allow_mode_decisions=False,
    initial_intensity=None,
):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    pause_event = callbacks.get("pause_event")
    user_signal_event = callbacks.get("user_signal_event")
    send_message = callbacks["send_message"]
    update_mood = callbacks.get("update_mood", lambda mood: None)
    remember_pattern = callbacks.get("remember_pattern", lambda target: None)
    planner = MotionScriptPlanner(mode, continuous_patterns=_uses_timed_pattern_motion(motion_controller))
    step_count = 0
    mode_intensity = initial_intensity
    autospeak_interval, next_autospeak_at = _initial_autospeak_schedule(callbacks)

    if allow_mode_decisions:
        min_time, max_time = get_timings(mode)
        decision = mode_decision_helpers._request_mode_decision(
            callbacks,
            mode,
            "start",
            current_target=_semantic_target(motion_controller),
        )
        _send_background_decision_message(callbacks, send_message, decision)
        autospeak_interval = _autospeak_interval_from_decision(callbacks, decision, autospeak_interval)
        next_autospeak_at = _next_autospeak_at(autospeak_interval)
        if decision.intensity is not None:
            mode_intensity = decision.intensity
        if max_steps is not None:
            max_steps = mode_decision_helpers._step_limit_for_duration(decision, min_time, max_time, max_steps)
        if decision.action == "stop":
            stop_event.set()
            return

    while not stop_event.is_set() and (max_steps is None or step_count < max_steps):
        if _wait_while_paused(stop_event, pause_event):
            break
        min_time, max_time = get_timings(mode)
        autospeak_interval, next_autospeak_at = _maybe_send_autospeak(
            callbacks,
            mode,
            autospeak_interval,
            next_autospeak_at,
            current_target=_semantic_target(motion_controller),
        )
        if mode == "milking" and user_signal_event and user_signal_event.is_set():
            user_signal_event.clear()
            decision = mode_decision_helpers._request_mode_decision(
                callbacks,
                mode,
                "close_signal",
                current_target=_semantic_target(motion_controller),
            )
            _send_background_decision_message(callbacks, send_message, decision)
            autospeak_interval = _autospeak_interval_from_decision(callbacks, decision, autospeak_interval)
            next_autospeak_at = _next_autospeak_at(autospeak_interval)
            if decision.action == "stop":
                stop_event.set()
                break
            if decision.intensity is not None:
                mode_intensity = decision.intensity
            if max_steps is not None:
                default_extension = random.randint(10, 16)
                max_steps += mode_decision_helpers._step_limit_for_duration(decision, min_time, max_time, default_extension)
            if not decision.chat:
                send_message("Staying with it a little longer.")
        user_message = _check_for_user_message(message_queue, message_event)
        feedback_target = _feedback_target(stop_event, motion_controller, user_message)
        if stop_event.is_set():
            break

        step = planner.next_step(_semantic_target(motion_controller), feedback_target=feedback_target)
        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        target = mode_decision_helpers._target_with_intensity(step.target, mode_intensity)
        applied_motion = _apply_mode_motion(motion_controller, target, source=f"{mode} mode")
        if applied_motion:
            remember_pattern(target)
        step_count += 1
        sleep_seconds = _mode_step_sleep_seconds(
            random.uniform(min_time, max_time) * step.delay_factor,
            step,
            motion_controller,
        )
        autospeak_interval, next_autospeak_at = _sleep_with_autospeak(
            stop_event,
            sleep_seconds,
            callbacks,
            mode,
            autospeak_interval,
            next_autospeak_at,
            wake_event=message_event,
            pause_event=pause_event,
            current_target=lambda: _semantic_target(motion_controller),
        )


def auto_mode_logic(stop_event: threading.Event, services: ModeServices, callbacks: ModeCallbacks):
    _run_scripted_mode(stop_event, services, callbacks, "auto")


def freestyle_mode_logic(stop_event: threading.Event, services: ModeServices, callbacks: ModeCallbacks):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    pause_event = callbacks.get("pause_event")
    user_signal_event = callbacks.get("user_signal_event")
    send_message = callbacks["send_message"]
    update_mood = callbacks.get("update_mood", lambda mood: None)
    remember_pattern_id = callbacks.get("remember_pattern_id", lambda pattern_id: None)
    freestyle_candidates = callbacks.get("freestyle_candidates", lambda: ())
    pattern_library_enabled = callbacks.get("motion_pattern_library_enabled_in_freestyle", lambda: False)
    rng = random.Random()
    recent_ids = []
    step_count = 0
    next_message_at = 0
    close_count = 0
    close_style_target = None
    close_style_until = 0.0
    repeat_choice = None
    repeat_steps_remaining = 0
    autospeak_interval, next_autospeak_at = _initial_autospeak_schedule(callbacks)

    while not stop_event.is_set():
        if _wait_while_paused(stop_event, pause_event):
            break
        min_time, max_time = get_timings("freestyle")
        autospeak_interval, next_autospeak_at = _maybe_send_autospeak(
            callbacks,
            "freestyle",
            autospeak_interval,
            next_autospeak_at,
            edge_count=close_count,
            current_target=_semantic_target(motion_controller),
        )
        if user_signal_event and user_signal_event.is_set():
            repeat_choice = None
            repeat_steps_remaining = 0
            user_signal_event.clear()
            close_count += 1
            decision_thread, decision_result = mode_decision_helpers._start_mode_decision_request(
                callbacks,
                "freestyle",
                "close_signal",
                edge_count=close_count,
                current_target=_semantic_target(motion_controller),
            )
            decision_thread.join(timeout=FREESTYLE_DECISION_GRACE_SECONDS)
            candidates = tuple(freestyle_candidates())
            edge_buffer_played = False
            edge_buffer_steps = []
            edge_buffer_resume_choices = []
            decision = None
            while not stop_event.is_set():
                if _wait_while_paused(stop_event, pause_event):
                    break
                decision = mode_decision_helpers._poll_mode_decision_request(decision_thread, decision_result)
                if decision is not None:
                    break
                completed, edge_steps, resume_choices = freestyle_helpers._apply_freestyle_edge_reaction(
                    motion_controller,
                    close_count,
                    rng=rng,
                    resume_candidates=candidates,
                    recent_ids=tuple(recent_ids),
                )
                if not completed:
                    break
                edge_buffer_played = True
                edge_buffer_steps = edge_steps
                edge_buffer_resume_choices = resume_choices
                step_count += freestyle_helpers._record_freestyle_edge_playback(
                    edge_steps,
                    resume_choices,
                    remember_pattern_id,
                    recent_ids,
                    update_mood,
                )
            if decision is None:
                decision = mode_decision_helpers._poll_mode_decision_request(decision_thread, decision_result) or ModeDecision()
            decision = freestyle_helpers._freestyle_decision_with_permissions(decision, callbacks)
            _send_background_decision_message(callbacks, send_message, decision)
            autospeak_interval = _autospeak_interval_from_decision(callbacks, decision, autospeak_interval)
            next_autospeak_at = _next_autospeak_at(autospeak_interval)
            if decision.action == "stop":
                stop_event.set()
                break
            if decision.action == "switch_to_milk":
                close_style_target = freestyle_helpers._freestyle_milk_style_target(decision)
                close_style_until = time.monotonic() + freestyle_helpers._freestyle_close_style_duration(decision, min_time, max_time)
            else:
                close_style_target = None
                close_style_until = 0.0
                if edge_buffer_played:
                    for step in edge_buffer_steps:
                        if step.message:
                            send_message(step.message)
                    continue
                completed, edge_steps, resume_choices = freestyle_helpers._apply_freestyle_edge_reaction(
                    motion_controller,
                    close_count,
                    intensity=decision.intensity,
                    rng=rng,
                    resume_candidates=candidates,
                    recent_ids=tuple(recent_ids),
                )
                for step in edge_steps:
                    if step.message:
                        send_message(step.message)
                if completed and edge_steps:
                    step_count += freestyle_helpers._record_freestyle_edge_playback(
                        edge_steps,
                        resume_choices,
                        remember_pattern_id,
                        recent_ids,
                        update_mood,
                    )
                continue

        user_message = _check_for_user_message(message_queue, message_event)
        feedback_target = _feedback_target(stop_event, motion_controller, user_message)
        if stop_event.is_set():
            break
        if not feedback_target and close_style_target and time.monotonic() < close_style_until:
            feedback_target = close_style_target
        elif close_style_target and time.monotonic() >= close_style_until:
            close_style_target = None

        continuous_freestyle = _uses_continuous_motion(motion_controller)
        repeat_active = False
        current_target = _semantic_target(motion_controller)
        if (
            continuous_freestyle
            and not feedback_target
            and repeat_choice is not None
            and repeat_steps_remaining > 0
        ):
            choices = [freestyle_helpers._freestyle_repeat_choice(repeat_choice, current_target, rng)]
            repeat_steps_remaining -= 1
            repeat_active = True
        else:
            if feedback_target:
                repeat_choice = None
                repeat_steps_remaining = 0
            choices = freestyle_helpers._freestyle_choice_chain(
                tuple(freestyle_candidates()),
                current_target,
                feedback_target,
                tuple(recent_ids),
                rng,
                length=1 if continuous_freestyle else freestyle_helpers.FREESTYLE_CHAIN_LENGTH,
            )
        if not choices:
            send_message("Freestyle needs at least one enabled motion pattern.")
            stop_event.set()
            break

        choice = choices[0]
        if feedback_target or step_count >= next_message_at:
            send_message(choice.reason)
            next_message_at = step_count + rng.randint(3, 5)

        sleep_seconds = (
            freestyle_helpers._freestyle_continuous_hold_seconds(choice, min_time, max_time, rng)
            if continuous_freestyle else 0
        )
        trace_metadata = None
        if continuous_freestyle:
            trace_metadata = {
                "mode": "freestyle",
                "freestyle_step": step_count,
                "freestyle_pattern_id": choice.pattern_id,
                "freestyle_pattern_name": choice.pattern_name,
                "freestyle_score": round(choice.score, 1),
                "freestyle_mood": choice.mood,
                "freestyle_feedback": bool(feedback_target),
                "freestyle_repeat": repeat_active,
                "freestyle_close_style": bool(close_style_target),
                "freestyle_planner_sleep_ms": round(sleep_seconds * 1000.0, 1),
            }

        use_pattern_library = pattern_library_enabled() if callable(pattern_library_enabled) else pattern_library_enabled
        if freestyle_helpers._apply_freestyle_choices(
            motion_controller,
            choices,
            rng,
            trace_metadata=trace_metadata,
            use_pattern_library=bool(use_pattern_library),
        ):
            update_mood(choices[-1].mood)
            played_choices = choices[:1] if continuous_freestyle else choices
            for played_choice in played_choices:
                remember_pattern_id(played_choice.pattern_id)
                recent_ids.append(played_choice.pattern_id)
            recent_ids[:] = recent_ids[-8:]
            if continuous_freestyle:
                if repeat_active:
                    if repeat_steps_remaining <= 0:
                        repeat_choice = None
                elif (
                    not feedback_target
                    and freestyle_helpers._freestyle_choice_can_repeat(choice)
                    and freestyle_helpers.FREESTYLE_CONTINUOUS_PATTERN_REPEAT_STEPS > 1
                ):
                    repeat_choice = choice
                    repeat_steps_remaining = freestyle_helpers.FREESTYLE_CONTINUOUS_PATTERN_REPEAT_STEPS - 1
                else:
                    repeat_choice = None
                    repeat_steps_remaining = 0

        step_count += 1 if continuous_freestyle else len(choices)
        autospeak_interval, next_autospeak_at = _sleep_with_autospeak(
            stop_event,
            sleep_seconds,
            callbacks,
            "freestyle",
            autospeak_interval,
            next_autospeak_at,
            wake_event=message_event,
            pause_event=pause_event,
            edge_count=close_count,
            current_target=lambda: _semantic_target(motion_controller),
        )


def milking_mode_logic(stop_event: threading.Event, services: ModeServices, callbacks: ModeCallbacks):
    _run_scripted_mode(
        stop_event,
        services,
        callbacks,
        "milking",
        max_steps=None,
        allow_mode_decisions=True,
    )


def edging_mode_logic(stop_event: threading.Event, services: ModeServices, callbacks: ModeCallbacks):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    update_mood = callbacks["update_mood"]
    send_message = callbacks["send_message"]
    remember_pattern = callbacks.get("remember_pattern", lambda target: None)
    user_signal_event = callbacks["user_signal_event"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    pause_event = callbacks.get("pause_event")
    planner = MotionScriptPlanner("edging", continuous_patterns=_uses_timed_pattern_motion(motion_controller))
    edge_count = 0
    step_count = 0
    max_steps = random.randint(56, 78)
    mode_intensity = None
    reaction_steps_remaining = None
    autospeak_interval, next_autospeak_at = _initial_autospeak_schedule(callbacks)

    edging_min, edging_max = get_timings("edging")
    start_decision = mode_decision_helpers._request_mode_decision(
        callbacks,
        "edging",
        "start",
        edge_count=edge_count,
        current_target=_semantic_target(motion_controller),
    )
    _send_background_decision_message(callbacks, send_message, start_decision)
    autospeak_interval = _autospeak_interval_from_decision(callbacks, start_decision, autospeak_interval)
    next_autospeak_at = _next_autospeak_at(autospeak_interval)
    if start_decision.intensity is not None:
        mode_intensity = start_decision.intensity
    max_steps = max(
        EDGE_START_MIN_STEPS,
        mode_decision_helpers._step_limit_for_duration(start_decision, edging_min, edging_max, max_steps),
    )
    if start_decision.action == "stop":
        stop_event.set()
        return
    if start_decision.action == "switch_to_milk":
        _set_active_mode(callbacks, "milking")
        _run_scripted_mode(
            stop_event,
            services,
            callbacks,
            "milking",
            max_steps=None,
            initial_intensity=mode_intensity,
        )
        return

    while not stop_event.is_set():
        if _wait_while_paused(stop_event, pause_event):
            break
        edging_min, edging_max = get_timings("edging")
        autospeak_interval, next_autospeak_at = _maybe_send_autospeak(
            callbacks,
            "edging",
            autospeak_interval,
            next_autospeak_at,
            edge_count=edge_count,
            current_target=_semantic_target(motion_controller),
        )
        step = None

        if step_count >= max_steps:
            decision = mode_decision_helpers._request_mode_decision(
                callbacks,
                "edging",
                "progress",
                edge_count=edge_count,
                current_target=_semantic_target(motion_controller),
            )
            _send_background_decision_message(callbacks, send_message, decision)
            autospeak_interval = _autospeak_interval_from_decision(callbacks, decision, autospeak_interval)
            next_autospeak_at = _next_autospeak_at(autospeak_interval)
            if decision.intensity is not None:
                mode_intensity = decision.intensity
            if decision.action == "stop":
                stop_event.set()
                break
            if decision.action == "switch_to_milk":
                _set_active_mode(callbacks, "milking")
                _run_scripted_mode(
                    stop_event,
                    services,
                    callbacks,
                    "milking",
                    max_steps=None,
                    initial_intensity=mode_intensity,
                )
                return
            extension_default = random.randint(10, 16)
            max_steps = step_count + max(
                EDGE_PROGRESS_MIN_STEPS,
                mode_decision_helpers._step_limit_for_duration(decision, edging_min, edging_max, extension_default),
            )
            if decision.action in {"hold_then_resume", "pull_back"}:
                step = planner.next_step(
                    _semantic_target(motion_controller),
                    edge_count=max(1, edge_count),
                )
                if decision.duration_seconds is not None:
                    reaction_steps_remaining = max(
                        0,
                        mode_decision_helpers._step_limit_for_duration(decision, edging_min, edging_max, len(planner.steps) + 1) - 1,
                    )
            else:
                continue

        if step is None:
            user_message = _check_for_user_message(message_queue, message_event)
            feedback_target = _feedback_target(stop_event, motion_controller, user_message)
            if stop_event.is_set():
                break

            if user_signal_event.is_set():
                user_signal_event.clear()
                edge_count += 1
                decision = mode_decision_helpers._request_mode_decision(
                    callbacks,
                    "edging",
                    "close_signal",
                    edge_count=edge_count,
                    current_target=_semantic_target(motion_controller),
                )
                _send_background_decision_message(callbacks, send_message, decision)
                autospeak_interval = _autospeak_interval_from_decision(callbacks, decision, autospeak_interval)
                next_autospeak_at = _next_autospeak_at(autospeak_interval)
                if decision.intensity is not None:
                    mode_intensity = decision.intensity
                if decision.action == "stop":
                    stop_event.set()
                    break
                if decision.action == "switch_to_milk":
                    _set_active_mode(callbacks, "milking")
                    _run_scripted_mode(
                        stop_event,
                        services,
                        callbacks,
                        "milking",
                        max_steps=None,
                        initial_intensity=mode_intensity,
                    )
                    return
                step = planner.next_step(_semantic_target(motion_controller), edge_count=edge_count)
                if decision.duration_seconds is not None:
                    reaction_steps_remaining = max(
                        0,
                        mode_decision_helpers._step_limit_for_duration(decision, edging_min, edging_max, len(planner.steps) + 1) - 1,
                    )
            else:
                step = planner.next_step(_semantic_target(motion_controller), feedback_target=feedback_target)

        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        target = mode_decision_helpers._target_with_intensity(step.target, mode_intensity)
        _apply_mode_motion(motion_controller, target, source="edging mode")
        remember_pattern(target)
        step_count += 1
        sleep_seconds = _mode_step_sleep_seconds(
            random.uniform(edging_min, edging_max) * step.delay_factor,
            step,
            motion_controller,
        )
        autospeak_interval, next_autospeak_at = _sleep_with_autospeak(
            stop_event,
            sleep_seconds,
            callbacks,
            "edging",
            autospeak_interval,
            next_autospeak_at,
            wake_event=message_event,
            pause_event=pause_event,
            edge_count=edge_count,
            current_target=lambda: _semantic_target(motion_controller),
        )
        if reaction_steps_remaining is not None:
            reaction_steps_remaining -= 1
            if reaction_steps_remaining < 0:
                planner.steps.clear()
                reaction_steps_remaining = None
