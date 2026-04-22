import random
import threading
import time

from .motion import IntentMatcher
from .motion_scripts import MotionScriptPlanner


INTENT_MATCHER = IntentMatcher()


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


def _run_scripted_mode(stop_event, services, callbacks, mode, max_steps=None):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    send_message = callbacks["send_message"]
    update_mood = callbacks.get("update_mood", lambda mood: None)
    planner = MotionScriptPlanner(mode)
    step_count = 0

    while not stop_event.is_set() and (max_steps is None or step_count < max_steps):
        min_time, max_time = get_timings(mode)
        user_message = _check_for_user_message(message_queue, message_event)
        feedback_target = _feedback_target(stop_event, motion_controller, user_message)
        if stop_event.is_set():
            break

        step = planner.next_step(motion_controller.current_target(), feedback_target=feedback_target)
        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        motion_controller.apply_target(step.target)
        step_count += 1
        _sleep_with_stop(stop_event, random.uniform(min_time, max_time) * step.delay_factor, message_event)


def auto_mode_logic(stop_event, services, callbacks):
    _run_scripted_mode(stop_event, services, callbacks, "auto")


def milking_mode_logic(stop_event, services, callbacks):
    _run_scripted_mode(stop_event, services, callbacks, "milking", max_steps=random.randint(14, 22))
    if not stop_event.is_set():
        callbacks["send_message"]("Finishing the sequence.")
        _sleep_with_stop(stop_event, 2)


def edging_mode_logic(stop_event, services, callbacks):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    update_mood = callbacks["update_mood"]
    send_message = callbacks["send_message"]
    user_signal_event = callbacks["user_signal_event"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    planner = MotionScriptPlanner("edging")
    edge_count = 0

    while not stop_event.is_set():
        edging_min, edging_max = get_timings("edging")
        user_message = _check_for_user_message(message_queue, message_event)
        feedback_target = _feedback_target(stop_event, motion_controller, user_message)
        if stop_event.is_set():
            break

        if user_signal_event.is_set():
            user_signal_event.clear()
            edge_count += 1
            step = planner.next_step(motion_controller.current_target(), edge_count=edge_count)
        else:
            step = planner.next_step(motion_controller.current_target(), feedback_target=feedback_target)

        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        motion_controller.apply_target(step.target)
        _sleep_with_stop(stop_event, random.uniform(edging_min, edging_max) * step.delay_factor, message_event)

    if not stop_event.is_set():
        send_message(f"Session complete. Edge count: {edge_count}.")
        update_mood("Afterglow")
