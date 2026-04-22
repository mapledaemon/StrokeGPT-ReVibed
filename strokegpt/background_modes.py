import math
import random
import threading
import time

from dataclasses import dataclass

from .motion import IntentMatcher, MotionTarget
from .motion_scripts import MotionScriptPlanner


INTENT_MATCHER = IntentMatcher()
MODE_DECISION_ACTIONS = {"continue", "hold_then_resume", "pull_back", "switch_to_milk", "stop"}


@dataclass(frozen=True)
class ModeDecision:
    action: str = "continue"
    duration_seconds: float | None = None
    intensity: int | None = None
    chat: str = ""
    source: str = "fallback"


class AutoModeThread(threading.Thread):
    def __init__(self, mode_func, initial_message, services, callbacks, mode_name="auto", initial_delay=0.1):
        super().__init__()
        self.name = mode_name
        self._mode_func = mode_func
        self._initial_message = initial_message
        self._services = services
        self._callbacks = callbacks
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


def _sleep_with_stop(stop_event, seconds, wake_event=None):
    deadline = time.monotonic() + max(0.1, seconds)
    while not stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        wait_time = min(0.1, remaining)
        if stop_event.wait(wait_time):
            return
        if wake_event and wake_event.is_set():
            return


def _coerce_mode_decision(raw, *, mode, event):
    if not isinstance(raw, dict):
        return ModeDecision()
    if not any(key in raw for key in ("action", "duration_seconds", "duration", "seconds", "intensity")):
        return ModeDecision()

    action = str(raw.get("action") or "").strip().lower().replace("-", "_").replace(" ", "_")
    action_aliases = {
        "": "continue",
        "resume": "hold_then_resume",
        "hold": "hold_then_resume",
        "hold_resume": "hold_then_resume",
        "hold_then_continue": "hold_then_resume",
        "milk": "switch_to_milk",
        "switch_milk": "switch_to_milk",
        "finish": "switch_to_milk",
        "end": "stop",
    }
    action = action_aliases.get(action, action)
    if action not in MODE_DECISION_ACTIONS:
        action = "continue"
    if mode == "milking" and action == "switch_to_milk":
        action = "continue"
    if event == "start" and mode == "milking" and action in {"pull_back", "hold_then_resume"}:
        action = "continue"

    duration = None
    for key in ("duration_seconds", "duration", "seconds"):
        try:
            duration = float(raw.get(key))
            break
        except (TypeError, ValueError):
            duration = None
    if duration is not None:
        duration = max(5.0, min(180.0, duration))

    intensity = None
    try:
        intensity = int(round(float(raw.get("intensity"))))
    except (TypeError, ValueError):
        intensity = None
    if intensity is not None:
        intensity = max(0, min(100, intensity))

    chat = str(raw.get("chat") or raw.get("message") or "").strip()
    if chat.lower().startswith("llm connection error"):
        chat = ""
    if len(chat) > 240:
        chat = chat[:237].rstrip() + "..."

    return ModeDecision(action=action, duration_seconds=duration, intensity=intensity, chat=chat, source="llm")


def _request_mode_decision(callbacks, mode, event, *, edge_count=0, current_target=None):
    provider = callbacks.get("mode_decision")
    if not provider:
        return ModeDecision()
    try:
        raw = provider(
            mode=mode,
            event=event,
            edge_count=edge_count,
            current_target=current_target,
        )
    except Exception as exc:
        print(f"Mode decision failed: {exc}")
        return ModeDecision()
    return _coerce_mode_decision(raw, mode=mode, event=event)


def _step_limit_for_duration(decision, min_time, max_time, default_steps):
    if decision.duration_seconds is None:
        return default_steps
    average_step_time = max(0.1, (float(min_time) + float(max_time)) / 2.0)
    return max(1, min(180, int(math.ceil(decision.duration_seconds / average_step_time))))


def _target_with_intensity(target, intensity):
    if intensity is None:
        return target
    speed_factor = 0.75 + (intensity / 100.0) * 0.5
    range_factor = 0.85 + (intensity / 100.0) * 0.3
    return MotionTarget(
        target.speed * speed_factor,
        target.depth,
        target.stroke_range * range_factor,
        target.label,
        target.motion_program,
    ).clamped()


def _set_active_mode(callbacks, mode_name):
    setter = callbacks.get("set_mode_name")
    if setter:
        setter(mode_name)
    try:
        threading.current_thread().name = mode_name
    except Exception:
        pass


def _send_mode_decision_message(send_message, decision):
    if decision.chat and decision.source == "llm":
        send_message(decision.chat)


def _run_scripted_mode(stop_event, services, callbacks, mode, max_steps=None, *, allow_mode_decisions=False, initial_intensity=None):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    user_signal_event = callbacks.get("user_signal_event")
    send_message = callbacks["send_message"]
    update_mood = callbacks.get("update_mood", lambda mood: None)
    remember_pattern = callbacks.get("remember_pattern", lambda target: None)
    planner = MotionScriptPlanner(mode)
    step_count = 0
    mode_intensity = initial_intensity

    if allow_mode_decisions:
        min_time, max_time = get_timings(mode)
        decision = _request_mode_decision(
            callbacks,
            mode,
            "start",
            current_target=motion_controller.current_target(),
        )
        _send_mode_decision_message(send_message, decision)
        if decision.intensity is not None:
            mode_intensity = decision.intensity
        if max_steps is not None:
            max_steps = _step_limit_for_duration(decision, min_time, max_time, max_steps)
        if decision.action == "stop":
            stop_event.set()
            return

    while not stop_event.is_set() and (max_steps is None or step_count < max_steps):
        min_time, max_time = get_timings(mode)
        if mode == "milking" and user_signal_event and user_signal_event.is_set():
            user_signal_event.clear()
            decision = _request_mode_decision(
                callbacks,
                mode,
                "close_signal",
                current_target=motion_controller.current_target(),
            )
            _send_mode_decision_message(send_message, decision)
            if decision.action == "stop":
                stop_event.set()
                break
            if decision.intensity is not None:
                mode_intensity = decision.intensity
            if max_steps is not None:
                default_extension = random.randint(10, 16)
                max_steps += _step_limit_for_duration(decision, min_time, max_time, default_extension)
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
        target = _target_with_intensity(step.target, mode_intensity)
        motion_controller.apply_target(target, source=f"{mode} mode")
        remember_pattern(target)
        step_count += 1
        _sleep_with_stop(stop_event, random.uniform(min_time, max_time) * step.delay_factor, message_event)


def auto_mode_logic(stop_event, services, callbacks):
    _run_scripted_mode(stop_event, services, callbacks, "auto")


def milking_mode_logic(stop_event, services, callbacks):
    _run_scripted_mode(
        stop_event,
        services,
        callbacks,
        "milking",
        max_steps=random.randint(34, 48),
        allow_mode_decisions=True,
    )
    if not stop_event.is_set():
        callbacks["send_message"]("Finishing the sequence.")
        _sleep_with_stop(stop_event, 2)


def edging_mode_logic(stop_event, services, callbacks):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    update_mood = callbacks["update_mood"]
    send_message = callbacks["send_message"]
    remember_pattern = callbacks.get("remember_pattern", lambda target: None)
    user_signal_event = callbacks["user_signal_event"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    planner = MotionScriptPlanner("edging")
    edge_count = 0
    step_count = 0
    max_steps = random.randint(56, 78)
    stop_after_reaction_steps = None
    completed_after_signal = False
    mode_intensity = None
    reaction_steps_remaining = None

    edging_min, edging_max = get_timings("edging")
    start_decision = _request_mode_decision(
        callbacks,
        "edging",
        "start",
        edge_count=edge_count,
        current_target=motion_controller.current_target(),
    )
    _send_mode_decision_message(send_message, start_decision)
    if start_decision.intensity is not None:
        mode_intensity = start_decision.intensity
    max_steps = _step_limit_for_duration(start_decision, edging_min, edging_max, max_steps)
    if start_decision.action == "stop":
        stop_event.set()
        return
    if start_decision.action == "switch_to_milk":
        _set_active_mode(callbacks, "milking")
        milk_min, milk_max = get_timings("milking")
        milk_steps = _step_limit_for_duration(start_decision, milk_min, milk_max, random.randint(18, 30))
        _run_scripted_mode(
            stop_event,
            services,
            callbacks,
            "milking",
            max_steps=milk_steps,
            initial_intensity=mode_intensity,
        )
        return

    while not stop_event.is_set() and step_count < max_steps:
        edging_min, edging_max = get_timings("edging")
        user_message = _check_for_user_message(message_queue, message_event)
        feedback_target = _feedback_target(stop_event, motion_controller, user_message)
        if stop_event.is_set():
            break

        if user_signal_event.is_set():
            user_signal_event.clear()
            edge_count += 1
            decision = _request_mode_decision(
                callbacks,
                "edging",
                "close_signal",
                edge_count=edge_count,
                current_target=motion_controller.current_target(),
            )
            _send_mode_decision_message(send_message, decision)
            if decision.intensity is not None:
                mode_intensity = decision.intensity
            if decision.action == "stop":
                stop_event.set()
                break
            if decision.action == "switch_to_milk":
                _set_active_mode(callbacks, "milking")
                milk_min, milk_max = get_timings("milking")
                milk_steps = _step_limit_for_duration(decision, milk_min, milk_max, random.randint(18, 30))
                _run_scripted_mode(
                    stop_event,
                    services,
                    callbacks,
                    "milking",
                    max_steps=milk_steps,
                    initial_intensity=mode_intensity,
                )
                completed_after_signal = True
                break
            step = planner.next_step(motion_controller.current_target(), edge_count=edge_count)
            if decision.source == "fallback" and edge_count >= 3:
                stop_after_reaction_steps = len(planner.steps)
            elif decision.duration_seconds is not None:
                reaction_steps_remaining = max(
                    0,
                    _step_limit_for_duration(decision, edging_min, edging_max, len(planner.steps) + 1) - 1,
                )
        else:
            step = planner.next_step(motion_controller.current_target(), feedback_target=feedback_target)

        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        target = _target_with_intensity(step.target, mode_intensity)
        motion_controller.apply_target(target, source="edging mode")
        remember_pattern(target)
        step_count += 1
        _sleep_with_stop(stop_event, random.uniform(edging_min, edging_max) * step.delay_factor, message_event)
        if reaction_steps_remaining is not None:
            reaction_steps_remaining -= 1
            if reaction_steps_remaining < 0:
                planner.steps.clear()
                reaction_steps_remaining = None
        if stop_after_reaction_steps is not None:
            stop_after_reaction_steps -= 1
            if stop_after_reaction_steps < 0:
                completed_after_signal = True
                break

    if completed_after_signal:
        send_message(f"Holding there. Edge count: {edge_count}.")
        update_mood("Afterglow")
    elif not stop_event.is_set():
        send_message(f"Session complete. Edge count: {edge_count}.")
        update_mood("Afterglow")
