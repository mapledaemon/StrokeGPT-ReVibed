import threading
import time
import unittest
from collections import deque
from unittest import mock

from strokegpt import background_modes
from strokegpt.background_modes import AutoModeThread, _sleep_with_stop
from strokegpt.motion import MotionTarget
from strokegpt.motion_patterns import MotionPattern, PatternAction


class FakeMotionController:
    def __init__(self):
        self.stopped = False
        self.applied = []
        self.position_frames = []
        self.position_sources = []
        self.position_final_stop_on_target = []

    def stop(self):
        self.stopped = True

    def current_target(self):
        if self.applied:
            return self.applied[-1]
        return MotionTarget(20, 30, 40)

    def apply_target(self, target, source="target"):
        self.applied.append(target)

    def apply_position_frames(
        self,
        frames,
        *,
        stop_after=False,
        source="pattern preview",
        final_stop_on_target=True,
    ):
        self.position_frames.extend(frames)
        self.position_sources.append(source)
        self.position_final_stop_on_target.append(final_stop_on_target)
        if frames:
            self.applied.append(frames[-1].target)
        return True


class FakePatternRecord:
    def __init__(self, pattern_id, name=None, source="fixed", enabled=True):
        self.pattern_id = pattern_id
        self.name = name or pattern_id
        self.source = source
        self.enabled = enabled
        self.feedback = {"thumbs_up": 0, "neutral": 0, "thumbs_down": 0}

    def to_motion_pattern(self):
        return MotionPattern(
            self.name,
            (
                PatternAction(0, 20),
                PatternAction(240, 80),
                PatternAction(480, 30),
            ),
            interpolation_ms=80,
        )


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

    def test_sleep_waits_while_paused(self):
        stop_event = threading.Event()
        pause_event = threading.Event()
        finished = threading.Event()
        pause_event.set()

        def sleeper():
            _sleep_with_stop(stop_event, 0.01, pause_event=pause_event)
            finished.set()

        thread = threading.Thread(target=sleeper)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(finished.is_set())

        pause_event.clear()
        self.assertTrue(finished.wait(0.5))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_sleep_allows_zero_duration_yield_without_interval_floor(self):
        started = time.monotonic()

        _sleep_with_stop(threading.Event(), 0)

        self.assertLess(time.monotonic() - started, 0.05)

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

    def test_auto_mode_thread_pause_and_resume_stop_motion_without_stopping_thread(self):
        motion = FakeMotionController()
        entered = threading.Event()
        pause_seen = threading.Event()
        release = threading.Event()
        messages = []
        stop_seen = []

        def mode_func(stop_event, _services, callbacks):
            entered.set()
            callbacks["pause_event"].wait(0.5)
            stop_seen.append(stop_event.is_set())
            pause_seen.set()
            while not stop_event.is_set() and not release.is_set():
                time.sleep(0.01)

        thread = AutoModeThread(
            mode_func,
            "Starting.",
            {"motion": motion},
            {"send_message": messages.append},
            initial_delay=0,
        )

        thread.start()
        self.assertTrue(entered.wait(0.5))
        thread.pause()

        self.assertTrue(thread.is_paused())
        self.assertTrue(motion.stopped)
        self.assertTrue(pause_seen.wait(0.5))
        self.assertEqual(stop_seen, [False])

        thread.resume()
        self.assertFalse(thread.is_paused())
        release.set()
        thread.stop()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(messages, ["Starting.", "Okay, you're in control now."])

    def test_milking_close_signal_extends_bounded_sequence(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        signal_event = threading.Event()
        signal_event.set()
        messages = []
        remembered = []
        callbacks = {
            "get_timings": lambda _mode: (0, 0),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": signal_event,
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern": remembered.append,
        }

        def stop_after_five_steps(event, *_args, **_kwargs):
            if len(motion.applied) >= 5:
                event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_five_steps):
            background_modes.milking_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertEqual(len(motion.applied), 5)
        self.assertTrue(any("Staying with it" in message for message in messages))
        self.assertFalse(any("Finishing the sequence" in message for message in messages))
        self.assertEqual(len(remembered), len(motion.applied))
        self.assertTrue(any(target.label.startswith("Milking ") for target in motion.applied))

    def test_milking_close_signal_uses_llm_duration_and_intensity(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        signal_event = threading.Event()
        signal_event.set()
        messages = []
        decisions = []

        def mode_decision(**kwargs):
            decisions.append((kwargs["mode"], kwargs["event"]))
            if kwargs["event"] == "start":
                return {"action": "continue", "duration_seconds": 5, "intensity": 20}
            return {
                "action": "continue",
                "duration_seconds": 5,
                "intensity": 100,
                "chat": "Keeping the finish going.",
            }

        callbacks = {
            "get_timings": lambda _mode: (1, 1),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": signal_event,
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern": lambda _target: None,
            "mode_decision": mode_decision,
        }

        def stop_after_ten_steps(event, *_args, **_kwargs):
            if len(motion.applied) >= 10:
                event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_ten_steps):
            background_modes.milking_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertEqual(decisions, [("milking", "start"), ("milking", "close_signal")])
        self.assertEqual(len(motion.applied), 10)
        self.assertTrue(any("Keeping the finish going" in message for message in messages))
        self.assertFalse(any("Finishing the sequence" in message for message in messages))
        self.assertTrue(all(target.speed >= 0 for target in motion.applied))

    def test_milking_start_duration_does_not_finish_the_mode(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        messages = []
        decisions = []

        def mode_decision(**kwargs):
            decisions.append((kwargs["mode"], kwargs["event"]))
            return {
                "action": "continue",
                "duration_seconds": 5,
                "intensity": 55,
                "chat": "Starting milk.",
            }

        callbacks = {
            "get_timings": lambda _mode: (1, 1),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": threading.Event(),
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern": lambda _target: None,
            "mode_decision": mode_decision,
        }

        def stop_after_twelve_steps(event, *_args, **_kwargs):
            if len(motion.applied) >= 12:
                event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_twelve_steps):
            background_modes.milking_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertEqual(decisions, [("milking", "start")])
        self.assertEqual(len(motion.applied), 12)
        self.assertTrue(any("Starting milk" in message for message in messages))
        self.assertFalse(any("Finishing the sequence" in message for message in messages))

    def test_edging_start_duration_cannot_finish_immediately(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        messages = []

        callbacks = {
            "get_timings": lambda _mode: (5, 8),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": threading.Event(),
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern": lambda _target: None,
            "mode_decision": lambda **_kwargs: {
                "action": "continue",
                "duration_seconds": 5,
                "intensity": 40,
            },
        }

        def stop_after_three_steps(event, *_args, **_kwargs):
            if len(motion.applied) >= 3:
                event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_three_steps):
            background_modes.edging_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertEqual(len(motion.applied), 3)
        self.assertFalse(any("Session complete" in message for message in messages))

    def test_edging_progress_checkpoint_extends_instead_of_completing(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        messages = []
        decisions = []

        def mode_decision(**kwargs):
            decisions.append((kwargs["mode"], kwargs["event"], kwargs["edge_count"]))
            return {
                "action": "continue",
                "intensity": 45,
                "chat": "Holding the edge.",
            }

        callbacks = {
            "get_timings": lambda _mode: (1, 1),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": threading.Event(),
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern": lambda _target: None,
            "mode_decision": mode_decision,
        }

        def stop_after_five_steps(event, *_args, **_kwargs):
            if len(motion.applied) >= 5:
                event.set()

        with mock.patch.object(background_modes, "EDGE_START_MIN_STEPS", 2):
            with mock.patch.object(background_modes, "EDGE_PROGRESS_MIN_STEPS", 2):
                with mock.patch.object(background_modes.random, "randint", return_value=2):
                    with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_five_steps):
                        background_modes.edging_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertIn(("edging", "start", 0), decisions)
        self.assertIn(("edging", "progress", 0), decisions)
        self.assertGreaterEqual(len(motion.applied), 5)
        self.assertTrue(any("Holding the edge" in message for message in messages))
        self.assertFalse(any("Session complete" in message for message in messages))

    def test_edging_close_signal_can_switch_to_milking_from_llm_decision(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        signal_event = threading.Event()
        signal_event.set()
        messages = []
        mode_names = []
        decisions = []

        def mode_decision(**kwargs):
            decisions.append((kwargs["mode"], kwargs["event"], kwargs["edge_count"]))
            if kwargs["event"] == "start":
                return {"action": "continue", "duration_seconds": 6, "intensity": 40}
            return {
                "action": "switch_to_milk",
                "duration_seconds": 5,
                "intensity": 80,
                "chat": "Switching to milk.",
            }

        callbacks = {
            "get_timings": lambda _mode: (1, 1),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": signal_event,
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern": lambda _target: None,
            "mode_decision": mode_decision,
            "set_mode_name": mode_names.append,
        }

        def stop_after_milk_starts(event, *_args, **_kwargs):
            if mode_names and mode_names[-1] == "milking" and len(motion.applied) >= 8:
                event.set()

        with mock.patch.object(background_modes.random, "randint", return_value=2):
            with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_milk_starts):
                background_modes.edging_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertIn(("edging", "start", 0), decisions)
        self.assertIn(("edging", "close_signal", 1), decisions)
        self.assertIn("milking", mode_names)
        self.assertTrue(any("Switching to milk" in message for message in messages))
        self.assertFalse(any("Holding there" in message for message in messages))
        self.assertTrue(any(target.label.startswith("Milking ") for target in motion.applied))

    def test_freestyle_mode_plays_enabled_pattern_with_position_frames(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        messages = []
        remembered = []
        candidates = [
            {
                "id": "disabled-flick",
                "name": "Disabled Flick",
                "source": "fixed",
                "enabled": False,
                "weight": 100,
                "record": FakePatternRecord("disabled-flick", "Disabled Flick", enabled=False),
            },
            {
                "id": "sway",
                "name": "Sway",
                "source": "fixed",
                "enabled": True,
                "weight": 80,
                "record": FakePatternRecord("sway", "Sway"),
            },
        ]
        callbacks = {
            "get_timings": lambda _mode: (0, 0),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern_id": remembered.append,
            "freestyle_candidates": lambda: candidates,
        }
        sleep_seconds = []

        def stop_after_iteration(event, seconds, *_args, **_kwargs):
            sleep_seconds.append(seconds)
            event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_iteration):
            background_modes.freestyle_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertEqual(remembered, ["sway", "sway", "sway", "sway"])
        self.assertEqual(motion.position_sources, ["freestyle planner"])
        self.assertEqual(motion.position_final_stop_on_target, [False])
        self.assertTrue(motion.position_frames)
        self.assertEqual(sleep_seconds, [0])
        self.assertTrue(any("Freestyle selecting Sway" in message for message in messages))

    def test_freestyle_close_signal_asks_llm_for_milk_style(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        signal_event = threading.Event()
        signal_event.set()
        messages = []
        remembered = []
        decisions = []
        candidates = [
            {
                "id": "sway",
                "name": "Sway",
                "source": "fixed",
                "enabled": True,
                "weight": 80,
                "record": FakePatternRecord("sway", "Sway"),
            },
            {
                "id": "milking-pressure-build",
                "name": "Milking Pressure Build",
                "source": "fixed",
                "enabled": True,
                "weight": 50,
                "record": FakePatternRecord("milking-pressure-build", "Milking Pressure Build"),
            },
        ]

        def mode_decision(**kwargs):
            decisions.append((kwargs["mode"], kwargs["event"], kwargs["edge_count"]))
            return {
                "action": "switch_to_milk",
                "duration_seconds": 12,
                "intensity": 84,
                "chat": "Choosing milk style.",
            }

        callbacks = {
            "get_timings": lambda _mode: (0, 0),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": signal_event,
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern_id": remembered.append,
            "freestyle_candidates": lambda: candidates,
            "mode_decision": mode_decision,
        }

        def stop_after_iteration(event, *_args, **_kwargs):
            event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_iteration):
            background_modes.freestyle_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertEqual(decisions, [("freestyle", "close_signal", 1)])
        self.assertEqual(remembered[0], "milking-pressure-build")
        self.assertEqual(motion.position_final_stop_on_target, [False])
        self.assertTrue(any("Choosing milk style" in message for message in messages))

    def test_freestyle_close_signal_runs_edge_reaction_then_resumes_freestyle(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        signal_event = threading.Event()
        signal_event.set()
        messages = []
        remembered = []
        decisions = []
        candidates = [
            {
                "id": "sway",
                "name": "Sway",
                "source": "fixed",
                "enabled": True,
                "weight": 80,
                "record": FakePatternRecord("sway", "Sway"),
            },
        ]

        def mode_decision(**kwargs):
            decisions.append((kwargs["mode"], kwargs["event"], kwargs["edge_count"]))
            return {
                "action": "hold_then_resume",
                "duration_seconds": 12,
                "intensity": 30,
                "chat": "Holding the edge.",
            }

        callbacks = {
            "get_timings": lambda _mode: (0, 0),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": signal_event,
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern_id": remembered.append,
            "freestyle_candidates": lambda: candidates,
            "mode_decision": mode_decision,
        }
        freestyle_iterations = []

        def stop_after_freestyle_resume(event, *_args, **_kwargs):
            freestyle_iterations.append(True)
            event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_freestyle_resume):
            background_modes.freestyle_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertEqual(decisions, [("freestyle", "close_signal", 1)])
        self.assertEqual(motion.position_sources[0], "freestyle edge reaction")
        self.assertEqual(motion.position_sources[1], "freestyle planner")
        self.assertEqual(motion.position_final_stop_on_target, [False, False])
        self.assertEqual(remembered, ["sway", "sway", "sway", "sway", "sway", "sway"])
        self.assertTrue(freestyle_iterations)
        self.assertTrue(any("Holding the edge" in message for message in messages))
        self.assertTrue(any("Backing off. Edge count: 1." in message for message in messages))

    def test_freestyle_close_signal_keeps_motion_running_while_llm_decides(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        signal_event = threading.Event()
        signal_event.set()
        bridge_started = threading.Event()
        release_decision = threading.Event()
        remembered = []
        candidates = [
            {
                "id": "sway",
                "name": "Sway",
                "source": "fixed",
                "enabled": True,
                "weight": 80,
                "record": FakePatternRecord("sway", "Sway"),
            },
        ]

        original_apply_position_frames = motion.apply_position_frames

        def apply_position_frames(frames, **kwargs):
            if kwargs.get("source") == "freestyle edge reaction":
                bridge_started.set()
                release_decision.set()
            return original_apply_position_frames(frames, **kwargs)

        def mode_decision(**_kwargs):
            bridge_started.wait(timeout=1)
            release_decision.wait(timeout=1)
            return {
                "action": "hold_then_resume",
                "duration_seconds": 12,
                "intensity": 30,
                "chat": "Holding the edge.",
            }

        motion.apply_position_frames = apply_position_frames
        callbacks = {
            "get_timings": lambda _mode: (0, 0),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": signal_event,
            "send_message": lambda _message: None,
            "update_mood": lambda _mood: None,
            "remember_pattern_id": remembered.append,
            "freestyle_candidates": lambda: candidates,
            "mode_decision": mode_decision,
        }

        def stop_after_resume(event, *_args, **_kwargs):
            event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_resume):
            background_modes.freestyle_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertTrue(bridge_started.is_set())
        self.assertEqual(motion.position_sources[0], "freestyle edge reaction")
        self.assertEqual(motion.position_final_stop_on_target[0], False)
        self.assertGreaterEqual(len(remembered), 2)

    def test_freestyle_close_signal_uses_milk_style_when_edge_permission_disabled(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        signal_event = threading.Event()
        signal_event.set()
        messages = []
        remembered = []
        candidates = [
            {
                "id": "sway",
                "name": "Sway",
                "source": "fixed",
                "enabled": True,
                "weight": 80,
                "record": FakePatternRecord("sway", "Sway"),
            },
            {
                "id": "milking-pressure-build",
                "name": "Milking Pressure Build",
                "source": "fixed",
                "enabled": True,
                "weight": 50,
                "record": FakePatternRecord("milking-pressure-build", "Milking Pressure Build"),
            },
        ]

        callbacks = {
            "get_timings": lambda _mode: (0, 0),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": signal_event,
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern_id": remembered.append,
            "freestyle_candidates": lambda: candidates,
            "allow_llm_edge_in_freestyle": lambda: False,
            "mode_decision": lambda **_kwargs: {
                "action": "hold_then_resume",
                "duration_seconds": 12,
                "intensity": 84,
                "chat": "Choosing edge style.",
            },
        }

        def stop_after_iteration(event, *_args, **_kwargs):
            event.set()

        with mock.patch.object(background_modes, "_sleep_with_stop", stop_after_iteration):
            background_modes.freestyle_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertEqual(motion.position_sources, ["freestyle planner"])
        self.assertEqual(remembered[0], "milking-pressure-build")
        self.assertTrue(any("Switching to milk-style Freestyle" in message for message in messages))

    def test_freestyle_close_signal_stops_only_when_llm_requests_stop(self):
        motion = FakeMotionController()
        stop_event = threading.Event()
        signal_event = threading.Event()
        signal_event.set()
        messages = []

        callbacks = {
            "get_timings": lambda _mode: (0, 0),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "user_signal_event": signal_event,
            "send_message": messages.append,
            "update_mood": lambda _mood: None,
            "remember_pattern_id": lambda _pattern_id: None,
            "freestyle_candidates": lambda: (),
            "mode_decision": lambda **_kwargs: {
                "action": "stop",
                "duration_seconds": 5,
                "intensity": 0,
                "chat": "Stopping now.",
            },
        }

        background_modes.freestyle_mode_logic(stop_event, {"motion": motion}, callbacks)

        self.assertTrue(stop_event.is_set())
        self.assertFalse(motion.position_frames)
        self.assertEqual(messages, ["Stopping now."])

    def test_freestyle_selector_uses_chat_feedback_target(self):
        current = MotionTarget(28, 42, 48)
        feedback_target = MotionTarget(70, 14, 20, label="tip flick fast")
        flick = FakePatternRecord("flick", "Flick")
        sway = FakePatternRecord("sway", "Sway")

        choice = background_modes._choose_freestyle_pattern(
            [
                {"id": "flick", "name": "Flick", "source": "fixed", "enabled": True, "weight": 30, "record": flick},
                {"id": "sway", "name": "Sway", "source": "fixed", "enabled": True, "weight": 80, "record": sway},
            ],
            current,
            feedback_target=feedback_target,
            rng=background_modes.random.Random(1),
        )

        self.assertEqual(choice.pattern_id, "flick")
        self.assertIn("Flick", choice.reason)


class CoerceModeDecisionTests(unittest.TestCase):
    def test_start_event_drops_stop_action_for_milking(self):
        decision = background_modes._coerce_mode_decision(
            {"action": "stop"},
            mode="milking",
            event="start",
        )
        self.assertEqual(decision.action, "continue")

    def test_start_event_drops_stop_action_for_freestyle(self):
        decision = background_modes._coerce_mode_decision(
            {"action": "stop"},
            mode="freestyle",
            event="start",
        )
        self.assertEqual(decision.action, "continue")

    def test_start_event_drops_stop_action_for_edging(self):
        decision = background_modes._coerce_mode_decision(
            {"action": "stop"},
            mode="edging",
            event="start",
        )
        self.assertEqual(decision.action, "continue")

    def test_progress_event_still_allows_stop_for_freestyle(self):
        decision = background_modes._coerce_mode_decision(
            {"action": "stop"},
            mode="freestyle",
            event="progress",
        )
        self.assertEqual(decision.action, "stop")

    def test_very_short_duration_is_clamped_up(self):
        decision = background_modes._coerce_mode_decision(
            {"action": "continue", "duration_seconds": 5},
            mode="edging",
            event="close_signal",
        )
        self.assertEqual(decision.duration_seconds, 10.0)


if __name__ == "__main__":
    unittest.main()
