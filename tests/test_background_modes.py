import random
import threading
import time
import unittest
from collections import deque
from unittest import mock

from strokegpt import background_modes, freestyle, mode_decisions
from strokegpt.background_modes import AutoModeThread, _sleep_with_stop
from strokegpt.mode_contracts import ModeCallbacks, ModeServices
from strokegpt.motion import MotionTarget
from strokegpt.motion_patterns import MotionPattern, PatternAction


class FakeMotionController:
    def __init__(self):
        self.stopped = False
        self.applied = []
        self.generated = []
        self.hamp_frames = []
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

    def apply_generated_target(self, target, source="generated"):
        self.generated.append((target, source))
        self.applied.append(target)

    def apply_frames(self, frames, *, stop_after=False, source="pattern"):
        self.hamp_frames.extend(frames)
        if frames:
            self.applied.append(frames[-1].target)
        return True

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


class ModeContractTests(unittest.TestCase):
    def test_mode_contracts_document_runtime_keys(self):
        self.assertEqual({"llm", "handy", "motion"}, set(ModeServices.__annotations__))

        callback_keys = set(ModeCallbacks.__annotations__)
        self.assertTrue({
            "send_message",
            "send_chat",
            "get_context",
            "get_timings",
            "on_stop",
            "update_mood",
            "user_signal_event",
            "message_event",
            "message_queue",
            "remember_pattern",
            "remember_pattern_id",
            "freestyle_candidates",
            "allow_llm_edge_in_freestyle",
            "autospeak_enabled",
            "autospeak_range",
            "consume_autospeak_wake",
            "set_mode_name",
            "mode_decision",
            "pause_event",
        }.issubset(callback_keys))


class BackgroundModeShimTests(unittest.TestCase):
    def test_split_private_helpers_are_not_reexported_from_background_modes(self):
        self.assertIs(background_modes.ModeDecision, mode_decisions.ModeDecision)
        self.assertIs(background_modes.FreestyleChoice, freestyle.FreestyleChoice)
        self.assertEqual(background_modes.MODE_DECISION_ACTIONS, mode_decisions.MODE_DECISION_ACTIONS)
        self.assertEqual(background_modes.FREESTYLE_CHAIN_LENGTH, freestyle.FREESTYLE_CHAIN_LENGTH)

        for helper_name in (
            "_choose_freestyle_pattern",
            "_apply_freestyle_choices",
            "_coerce_mode_decision",
            "_request_mode_decision",
        ):
            with self.subTest(helper_name=helper_name):
                self.assertFalse(hasattr(background_modes, helper_name))


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

    def test_autospeak_zero_cadence_uses_natural_floor_without_cutting_wait_short(self):
        chat_messages = []
        decision_events = []

        def mode_decision(**kwargs):
            decision_events.append(kwargs["event"])
            if kwargs["event"] == "start":
                return {
                    "action": "continue",
                    "autospeak_seconds": 0,
                }
            return {
                "action": "continue",
                "autospeak_seconds": 0,
                "chat": "Still with you.",
            }

        callbacks = {
            "send_chat": chat_messages.append,
            "autospeak_enabled": lambda: True,
            "mode_decision": mode_decision,
        }

        started = time.monotonic()
        background_modes._sleep_with_autospeak(
            threading.Event(),
            0.55,
            callbacks,
            "freestyle",
            0,
            time.monotonic(),
            current_target=lambda: MotionTarget(20, 30, 40),
        )
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.5)
        self.assertIn("autospeak", decision_events)
        self.assertEqual(len(chat_messages), 1)
        self.assertEqual(set(chat_messages), {"Still with you."})

    def test_initial_autospeak_schedule_respects_minimum_when_enabled(self):
        interval, next_due = background_modes._initial_autospeak_schedule({
            "autospeak_enabled": lambda: True,
            "autospeak_range": lambda: (20, 45),
        })

        self.assertEqual(interval, 45.0)
        self.assertGreaterEqual(next_due - time.monotonic(), 19.5)

    def test_zero_initial_autospeak_schedule_uses_natural_floor(self):
        interval, next_due = background_modes._initial_autospeak_schedule({
            "autospeak_enabled": lambda: True,
            "autospeak_range": lambda: (0, 45),
        })

        self.assertEqual(interval, 45.0)
        self.assertGreaterEqual(next_due - time.monotonic(), 7.5)

    def test_autospeak_wake_moves_deadline_to_natural_pause_before_existing_deadline(self):
        chat_messages = []
        decision_events = []
        wake_consumed = []

        def consume_wake():
            if wake_consumed:
                return False
            wake_consumed.append(True)
            return True

        callbacks = {
            "send_chat": chat_messages.append,
            "autospeak_enabled": lambda: True,
            "consume_autospeak_wake": consume_wake,
            "mode_decision": lambda **kwargs: (
                decision_events.append(kwargs["event"]) or {
                    "action": "continue",
                    "autospeak_seconds": 30,
                    "chat": "Still here.",
                }
            ),
        }

        interval, next_due = background_modes._maybe_send_autospeak(
            callbacks,
            "freestyle",
            45,
            time.monotonic() + 45,
            current_target=MotionTarget(20, 30, 40),
        )

        self.assertEqual(decision_events, [])
        self.assertEqual(chat_messages, [])
        self.assertEqual(interval, 45.0)
        self.assertGreater(next_due, time.monotonic())
        self.assertLess(next_due - time.monotonic(), 9.0)

    def test_autospeak_future_deadline_does_not_poll_without_wake(self):
        decision_events = []
        callbacks = {
            "autospeak_enabled": lambda: True,
            "mode_decision": lambda **kwargs: decision_events.append(kwargs["event"]),
        }

        background_modes._maybe_send_autospeak(
            callbacks,
            "freestyle",
            45,
            time.monotonic() + 45,
            current_target=MotionTarget(20, 30, 40),
        )

        self.assertEqual(decision_events, [])

    def test_autospeak_enabled_decision_chat_uses_chat_channel(self):
        status_messages = []
        chat_messages = []
        decision = mode_decisions.ModeDecision(
            chat="Stay with me.",
            autospeak_seconds=6,
            source="llm",
        )
        callbacks = {
            "send_chat": chat_messages.append,
            "autospeak_enabled": lambda: True,
        }

        sent = background_modes._send_background_decision_message(
            callbacks,
            status_messages.append,
            decision,
        )

        self.assertTrue(sent)
        self.assertEqual(chat_messages, ["Stay with me."])
        self.assertEqual(status_messages, [])

    def test_autospeak_disabled_decision_chat_stays_status_only(self):
        status_messages = []
        chat_messages = []
        decision = mode_decisions.ModeDecision(
            chat="Status only.",
            autospeak_seconds=6,
            source="llm",
        )
        callbacks = {
            "send_chat": chat_messages.append,
            "autospeak_enabled": lambda: False,
        }

        sent = background_modes._send_background_decision_message(
            callbacks,
            status_messages.append,
            decision,
        )

        self.assertTrue(sent)
        self.assertEqual(status_messages, ["Status only."])
        self.assertEqual(chat_messages, [])

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
        self.assertTrue(any("Freestyle" in message for message in messages))
        self.assertFalse(any("Freestyle selecting" in message for message in messages))
        self.assertFalse(any("weight" in message.lower() for message in messages))

    def test_freestyle_continuous_trace_metadata_describes_choice_and_sleep(self):
        motion = FakeMotionController()
        motion.backend = "continuous"
        motion.continuous_calls = []

        def apply_continuous_target(target, source="continuous pattern", trace_metadata=None):
            motion.applied.append(target)
            motion.continuous_calls.append((source, trace_metadata or {}))
            return True

        motion.apply_continuous_target = apply_continuous_target
        stop_event = threading.Event()
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
        callbacks = {
            "get_timings": lambda _mode: (1.25, 1.25),
            "message_queue": deque(),
            "message_event": threading.Event(),
            "send_message": lambda _message: None,
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

        self.assertEqual(sleep_seconds, [1.25])
        self.assertEqual(remembered, ["sway"])
        self.assertEqual(len(motion.continuous_calls), 1)
        source, metadata = motion.continuous_calls[0]
        self.assertEqual(source, "freestyle planner")
        self.assertEqual(metadata["mode"], "freestyle")
        self.assertEqual(metadata["freestyle_step"], 0)
        self.assertEqual(metadata["freestyle_pattern_id"], "sway")
        self.assertEqual(metadata["freestyle_pattern_name"], "Sway")
        self.assertEqual(metadata["freestyle_planner_sleep_ms"], 1250.0)
        self.assertFalse(metadata["freestyle_feedback"])

    def test_scripted_position_mode_routes_patterns_through_generated_target(self):
        motion = FakeMotionController()
        motion.backend = "position"
        target = MotionTarget(64, 58, 70, label="Milking Pressure Build")

        background_modes._apply_mode_motion(motion, target, source="milking mode")

        self.assertEqual(motion.generated, [(target, "milking mode")])
        self.assertEqual(motion.position_frames, [])

    def test_freestyle_position_uses_timed_position_frames(self):
        motion = FakeMotionController()
        motion.backend = "position"
        choices = [
            freestyle.FreestyleChoice(
                "sway",
                "Sway",
                FakePatternRecord("sway", "Sway"),
                MotionTarget(56, 50, 80, label="Freestyle: Sway"),
                10.0,
                "Playful",
                "Swaying.",
            )
        ]

        self.assertTrue(freestyle._apply_freestyle_choices(motion, choices, random.Random(5)))

        self.assertTrue(motion.position_frames)
        self.assertFalse(motion.hamp_frames)
        self.assertTrue(all(str(getattr(frame, "phase", "")).startswith("timed") for frame in motion.position_frames))
        self.assertEqual(motion.position_final_stop_on_target, [False])

    def test_freestyle_hamp_uses_legacy_frame_playback(self):
        motion = FakeMotionController()
        motion.backend = "hamp"
        choices = [
            freestyle.FreestyleChoice(
                "sway",
                "Sway",
                FakePatternRecord("sway", "Sway"),
                MotionTarget(56, 50, 80, label="Freestyle: Sway"),
                10.0,
                "Playful",
                "Swaying.",
            )
        ]

        self.assertTrue(freestyle._apply_freestyle_choices(motion, choices, random.Random(5)))

        self.assertTrue(motion.hamp_frames)
        self.assertFalse(motion.position_frames)

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
        self.assertTrue(any("Backing off for a moment." in message for message in messages))
        self.assertFalse(any("Edge count" in message for message in messages))

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

        choice = freestyle._choose_freestyle_pattern(
            [
                {"id": "flick", "name": "Flick", "source": "fixed", "enabled": True, "weight": 30, "record": flick},
                {"id": "sway", "name": "Sway", "source": "fixed", "enabled": True, "weight": 80, "record": sway},
            ],
            current,
            feedback_target=feedback_target,
            rng=random.Random(1),
        )

        self.assertEqual(choice.pattern_id, "flick")
        self.assertEqual(choice.reason, "Following that direction in Freestyle.")
        self.assertIn("Flick", choice.debug_reason)
        self.assertNotIn("weight", choice.reason.lower())

    def test_freestyle_selector_skips_staccato_patterns_without_feedback(self):
        current = MotionTarget(30, 50, 55)
        flick = FakePatternRecord("flick", "Flick")
        flutter = FakePatternRecord("flutter", "Flutter")
        sway = FakePatternRecord("sway", "Sway")

        choice = freestyle._choose_freestyle_pattern(
            [
                {
                    "id": "flick",
                    "name": "Flick",
                    "source": "fixed",
                    "enabled": True,
                    "weight": 100,
                    "record": flick,
                },
                {
                    "id": "flutter",
                    "name": "Flutter",
                    "source": "fixed",
                    "enabled": True,
                    "weight": 100,
                    "record": flutter,
                },
                {
                    "id": "sway",
                    "name": "Sway",
                    "source": "fixed",
                    "enabled": True,
                    "weight": 10,
                    "record": sway,
                },
            ],
            current,
            rng=random.Random(2),
        )

        self.assertIsNotNone(choice)
        self.assertEqual(choice.pattern_id, "sway")

    def test_freestyle_selector_skips_edge_patterns_without_feedback(self):
        current = MotionTarget(30, 50, 55)
        edge = FakePatternRecord("edge-middle-hold", "Edge Middle Hold")
        sway = FakePatternRecord("sway", "Sway")

        choice = freestyle._choose_freestyle_pattern(
            [
                {"id": "edge-middle-hold", "name": "Edge Middle Hold", "source": "fixed", "enabled": True, "weight": 100, "record": edge},
                {"id": "sway", "name": "Sway", "source": "fixed", "enabled": True, "weight": 10, "record": sway},
            ],
            current,
            rng=random.Random(2),
        )

        self.assertIsNotNone(choice)
        self.assertEqual(choice.pattern_id, "sway")

    def test_freestyle_selector_allows_edge_patterns_for_edge_feedback(self):
        current = MotionTarget(30, 50, 55)
        feedback_target = MotionTarget(35, 50, 25, label="edge middle hold")
        edge = FakePatternRecord("edge-middle-hold", "Edge Middle Hold")
        sway = FakePatternRecord("sway", "Sway")

        choice = freestyle._choose_freestyle_pattern(
            [
                {"id": "edge-middle-hold", "name": "Edge Middle Hold", "source": "fixed", "enabled": True, "weight": 30, "record": edge},
                {"id": "sway", "name": "Sway", "source": "fixed", "enabled": True, "weight": 80, "record": sway},
            ],
            current,
            feedback_target=feedback_target,
            rng=random.Random(2),
        )

        self.assertIsNotNone(choice)
        self.assertEqual(choice.pattern_id, "edge-middle-hold")

    def test_freestyle_selector_skips_non_dict_and_recordless_candidates(self):
        current = MotionTarget(30, 40, 50)
        usable_record = FakePatternRecord("sway", "Sway")
        bare_record = FakePatternRecord("flick", "Flick")

        choice = freestyle._choose_freestyle_pattern(
            [
                bare_record,  # historical record-like shape, no longer accepted
                {"id": "ghost", "name": "Ghost", "source": "fixed", "enabled": True, "weight": 80},  # missing record
                {"id": "sway", "name": "Sway", "source": "fixed", "enabled": True, "weight": 60, "record": usable_record},
            ],
            current,
            rng=random.Random(0),
        )

        self.assertIsNotNone(choice)
        self.assertEqual(choice.pattern_id, "sway")


class CoerceModeDecisionTests(unittest.TestCase):
    def test_start_event_drops_stop_action_for_milking(self):
        decision = mode_decisions._coerce_mode_decision(
            {"action": "stop"},
            mode="milking",
            event="start",
        )
        self.assertEqual(decision.action, "continue")

    def test_start_event_drops_stop_action_for_freestyle(self):
        decision = mode_decisions._coerce_mode_decision(
            {"action": "stop"},
            mode="freestyle",
            event="start",
        )
        self.assertEqual(decision.action, "continue")

    def test_start_event_drops_stop_action_for_edging(self):
        decision = mode_decisions._coerce_mode_decision(
            {"action": "stop"},
            mode="edging",
            event="start",
        )
        self.assertEqual(decision.action, "continue")

    def test_progress_event_still_allows_stop_for_freestyle(self):
        decision = mode_decisions._coerce_mode_decision(
            {"action": "stop"},
            mode="freestyle",
            event="progress",
        )
        self.assertEqual(decision.action, "stop")

    def test_very_short_duration_is_clamped_up(self):
        decision = mode_decisions._coerce_mode_decision(
            {"action": "continue", "duration_seconds": 5},
            mode="edging",
            event="close_signal",
        )
        self.assertEqual(decision.duration_seconds, 10.0)

    def test_autospeak_seconds_can_be_zero(self):
        decision = mode_decisions._coerce_mode_decision(
            {"action": "continue", "autospeak_seconds": 0, "chat": "Still here."},
            mode="freestyle",
            event="autospeak",
        )
        self.assertEqual(decision.autospeak_seconds, 0.0)
        self.assertEqual(decision.chat, "Still here.")

    def test_autospeak_seconds_clamps_high_values(self):
        decision = mode_decisions._coerce_mode_decision(
            {"action": "continue", "autospeak_seconds": 999},
            mode="freestyle",
            event="autospeak",
        )
        self.assertEqual(decision.autospeak_seconds, 300.0)

    def test_autospeak_seconds_clamps_to_configured_range(self):
        decision = mode_decisions._coerce_mode_decision_with_autospeak_range(
            {"action": "continue", "autospeak_seconds": 999},
            mode="freestyle",
            event="autospeak",
            autospeak_min_seconds=6,
            autospeak_max_seconds=14,
        )
        self.assertEqual(decision.autospeak_seconds, 14.0)

        decision = mode_decisions._coerce_mode_decision_with_autospeak_range(
            {"action": "continue", "autospeak_seconds": 1},
            mode="freestyle",
            event="autospeak",
            autospeak_min_seconds=6,
            autospeak_max_seconds=14,
        )
        self.assertEqual(decision.autospeak_seconds, 6.0)

    def test_mode_decision_request_uses_configured_autospeak_range(self):
        callbacks = {
            "autospeak_range": lambda: (2, 8),
            "mode_decision": lambda **_kwargs: {
                "action": "continue",
                "autospeak_seconds": 99,
                "chat": "Still here.",
            },
        }

        decision = mode_decisions._request_mode_decision(
            callbacks,
            "freestyle",
            "autospeak",
        )

        self.assertEqual(decision.autospeak_seconds, 8.0)
        self.assertEqual(decision.chat, "Still here.")

    def test_autospeak_interval_preserves_zero_current_interval(self):
        interval = mode_decisions._autospeak_interval_from_decision(
            mode_decisions.ModeDecision(),
            current_interval=0,
            min_seconds=0,
            max_seconds=300,
        )

        self.assertEqual(interval, 0.0)


if __name__ == "__main__":
    unittest.main()
