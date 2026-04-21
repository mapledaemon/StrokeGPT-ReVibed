import unittest

from strokegpt.background_modes import AutoModeThread


class FakeMotionController:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class AutoModeThreadTests(unittest.TestCase):
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
