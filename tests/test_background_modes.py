import threading
import time
import unittest

from strokegpt.background_modes import AutoModeThread, _sleep_with_stop


class FakeMotionController:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class AutoModeThreadTests(unittest.TestCase):
    def test_mode_starts_without_full_second_delay(self):
        mode_called = threading.Event()
        motion = FakeMotionController()

        def mode_func(stop_event, _services, _callbacks):
            mode_called.set()
            stop_event.set()

        thread = AutoModeThread(
            mode_func,
            "Starting.",
            {"motion": motion},
            {"send_message": lambda _message: None},
        )

        thread.start()

        self.assertTrue(mode_called.wait(0.5))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_sleep_wakes_for_feedback_event(self):
        stop_event = threading.Event()
        wake_event = threading.Event()
        finished = threading.Event()

        def sleeper():
            _sleep_with_stop(stop_event, 5, wake_event)
            finished.set()

        thread = threading.Thread(target=sleeper)
        thread.start()
        time.sleep(0.05)
        wake_event.set()

        self.assertTrue(finished.wait(0.5))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_stop_during_initial_delay_runs_cleanup_without_mode_step(self):
        messages = []
        cleanup_called = []
        mode_called = []
        motion = FakeMotionController()

        def mode_func(_stop_event, _services, _callbacks):
            mode_called.append(True)

        thread = AutoModeThread(
            mode_func,
            "Starting.",
            {"motion": motion},
            {
                "send_message": messages.append,
                "on_stop": lambda: cleanup_called.append(True),
            },
        )

        thread.start()
        thread.stop()
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertFalse(mode_called)
        self.assertTrue(motion.stopped)
        self.assertTrue(cleanup_called)
        self.assertEqual(messages, ["Starting.", "Okay, you're in control now."])


if __name__ == "__main__":
    unittest.main()
