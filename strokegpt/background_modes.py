"""Background mode orchestration.

This module is the scheduling and pacing layer for Auto, Edge, Milk, and
Freestyle modes. Decision parsing lives in :mod:`strokegpt.mode_decisions`
and the Freestyle planner helpers live in :mod:`strokegpt.freestyle`;
this module imports from both and wires them into the long-running mode
loops. The `random` binding and public type/constant compatibility exports
are kept only where the compatibility surface still needs them.
"""

import random
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
from .motion_scripts import MotionScriptPlanner


INTENT_MATCHER = IntentMatcher()

EDGE_START_MIN_STEPS = 12
EDGE_PROGRESS_MIN_STEPS = 10


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
            if motion_controller:
                motion_controller.stop()

            stop_callback = self._callbacks.get("on_stop")
            if stop_callback:
                stop_callback()

            if message_callback:
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


def _feedback_target(stop_event, motion_controller, user_message):
    if not user_message:
        return None
    intent = INTENT_MATCHER.parse(user_message, motion_controller.current_target())
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


def _set_active_mode(callbacks: ModeCallbacks, mode_name):
    setter = callbacks.get("set_mode_name")
    if setter:
        setter(mode_name)
    try:
        threading.current_thread().name = mode_name
    except Exception:
        pass


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
    planner = MotionScriptPlanner(mode)
    step_count = 0
    mode_intensity = initial_intensity

    if allow_mode_decisions:
        min_time, max_time = get_timings(mode)
        decision = mode_decision_helpers._request_mode_decision(
            callbacks,
            mode,
            "start",
            current_target=motion_controller.current_target(),
        )
        mode_decision_helpers._send_mode_decision_message(send_message, decision)
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
        if mode == "milking" and user_signal_event and user_signal_event.is_set():
            user_signal_event.clear()
            decision = mode_decision_helpers._request_mode_decision(
                callbacks,
                mode,
                "close_signal",
                current_target=motion_controller.current_target(),
            )
            mode_decision_helpers._send_mode_decision_message(send_message, decision)
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

        step = planner.next_step(motion_controller.current_target(), feedback_target=feedback_target)
        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        target = mode_decision_helpers._target_with_intensity(step.target, mode_intensity)
        motion_controller.apply_target(target, source=f"{mode} mode")
        remember_pattern(target)
        step_count += 1
        _sleep_with_stop(stop_event, random.uniform(min_time, max_time) * step.delay_factor, message_event, pause_event)


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
    rng = random.Random()
    recent_ids = []
    step_count = 0
    next_message_at = 0
    close_count = 0
    close_style_target = None
    close_style_until = 0.0

    while not stop_event.is_set():
        if _wait_while_paused(stop_event, pause_event):
            break
        min_time, max_time = get_timings("freestyle")
        if user_signal_event and user_signal_event.is_set():
            user_signal_event.clear()
            close_count += 1
            decision_thread, decision_result = mode_decision_helpers._start_mode_decision_request(
                callbacks,
                "freestyle",
                "close_signal",
                edge_count=close_count,
                current_target=motion_controller.current_target(),
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
            mode_decision_helpers._send_mode_decision_message(send_message, decision)
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

        choices = freestyle_helpers._freestyle_choice_chain(
            tuple(freestyle_candidates()),
            motion_controller.current_target(),
            feedback_target,
            tuple(recent_ids),
            rng,
        )
        if not choices:
            send_message("Freestyle needs at least one enabled motion pattern.")
            stop_event.set()
            break

        choice = choices[0]
        if feedback_target or step_count >= next_message_at:
            send_message(choice.reason)
            next_message_at = step_count + rng.randint(3, 5)

        if freestyle_helpers._apply_freestyle_choices(motion_controller, choices, rng):
            update_mood(choices[-1].mood)
            for played_choice in choices:
                remember_pattern_id(played_choice.pattern_id)
                recent_ids.append(played_choice.pattern_id)
            recent_ids[:] = recent_ids[-8:]

        step_count += len(choices)
        _sleep_with_stop(stop_event, 0, message_event, pause_event)


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
    planner = MotionScriptPlanner("edging")
    edge_count = 0
    step_count = 0
    max_steps = random.randint(56, 78)
    mode_intensity = None
    reaction_steps_remaining = None

    edging_min, edging_max = get_timings("edging")
    start_decision = mode_decision_helpers._request_mode_decision(
        callbacks,
        "edging",
        "start",
        edge_count=edge_count,
        current_target=motion_controller.current_target(),
    )
    mode_decision_helpers._send_mode_decision_message(send_message, start_decision)
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
        step = None

        if step_count >= max_steps:
            decision = mode_decision_helpers._request_mode_decision(
                callbacks,
                "edging",
                "progress",
                edge_count=edge_count,
                current_target=motion_controller.current_target(),
            )
            mode_decision_helpers._send_mode_decision_message(send_message, decision)
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
                    motion_controller.current_target(),
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
                    current_target=motion_controller.current_target(),
                )
                mode_decision_helpers._send_mode_decision_message(send_message, decision)
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
                step = planner.next_step(motion_controller.current_target(), edge_count=edge_count)
                if decision.duration_seconds is not None:
                    reaction_steps_remaining = max(
                        0,
                        mode_decision_helpers._step_limit_for_duration(decision, edging_min, edging_max, len(planner.steps) + 1) - 1,
                    )
            else:
                step = planner.next_step(motion_controller.current_target(), feedback_target=feedback_target)

        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        target = mode_decision_helpers._target_with_intensity(step.target, mode_intensity)
        motion_controller.apply_target(target, source="edging mode")
        remember_pattern(target)
        step_count += 1
        _sleep_with_stop(stop_event, random.uniform(edging_min, edging_max) * step.delay_factor, message_event, pause_event)
        if reaction_steps_remaining is not None:
            reaction_steps_remaining -= 1
            if reaction_steps_remaining < 0:
                planner.steps.clear()
                reaction_steps_remaining = None
