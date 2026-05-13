import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from strokegpt.motion import (
    CONTINUOUS_MAX_MORPH_SECONDS,
    CONTINUOUS_MIN_MORPH_SECONDS,
    CONTINUOUS_MAX_COMMAND_INTERVAL_SECONDS,
    CONTINUOUS_MIN_COMMAND_INTERVAL_SECONDS,
    CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS,
    CONTINUOUS_SAMPLE_INTERVAL_SECONDS,
    IntentMatcher,
    MotionController,
    MotionSanitizer,
    MotionTarget,
    PositionFrame,
    POSITION_MAX_DEPTH_STEP,
    POSITION_PASS_THROUGH_MIN_SECONDS,
)
from strokegpt.motion_patterns import continuous_motion_plan, sample_continuous_motion


class FakeHandy:
    def __init__(self):
        self.last_relative_speed = 20
        self.last_depth_pos = 30
        self.last_stroke_range = 40
        self.moves = []
        self.position_moves = []
        self.position_intent_speeds = []
        self.position_durations = []
        self.velocity_intervals = []
        self.stopped = False

    def move(self, speed, depth, stroke_range):
        self.moves.append((speed, depth, stroke_range))
        self.last_relative_speed = speed
        self.last_depth_pos = depth
        self.last_stroke_range = stroke_range

    def move_to_depth(self, speed, depth, *, stop_on_target=True, velocity=None, intent_speed=None, duration_ms=None):
        self.position_moves.append((speed, depth, stop_on_target, velocity))
        self.position_intent_speeds.append(speed if intent_speed is None else intent_speed)
        self.position_durations.append(duration_ms)
        self.last_relative_speed = speed if intent_speed is None else intent_speed
        self.last_depth_pos = depth
        return True

    def velocity_for_depth_interval(self, speed, start_depth, end_depth, duration_seconds):
        self.velocity_intervals.append((speed, start_depth, end_depth, duration_seconds))
        return int(round(speed + abs(end_depth - start_depth) + duration_seconds * 10))

    def stop(self):
        self.stopped = True
        self.last_relative_speed = 0


class StreamingFakeHandy(FakeHandy):
    def __init__(self):
        super().__init__()
        self.stream_starts = []
        self.stream_appends = []
        self.stream_syncs = []
        self._last_command = None

    def supports_continuous_streaming(self):
        return True

    def start_continuous_stream(
        self,
        points,
        *,
        stream_id=None,
        start_time_ms=0,
        tail_point_stream_index=None,
        tail_point_threshold=None,
    ):
        self.stream_starts.append(
            {
                "points": [dict(point) for point in points],
                "stream_id": stream_id,
                "start_time_ms": start_time_ms,
                "tail_point_stream_index": tail_point_stream_index,
                "tail_point_threshold": tail_point_threshold,
            }
        )
        self._last_command = {
            "path": "hsp/play",
            "ok": True,
            "status_code": 200,
            "elapsed_ms": 5.0,
            "body": {
                "start_time": start_time_ms,
                "add": {
                    "points": len(points),
                    "flush": True,
                    "tail_point_stream_index": tail_point_stream_index,
                },
            },
        }
        if points:
            last = points[-1]
            self.last_relative_speed = last.get("intent_speed", last.get("speed", self.last_relative_speed))
            self.last_depth_pos = last.get("x", self.last_depth_pos)
        return True

    def sync_continuous_stream_time(self, current_time_ms, *, filter=0.5):
        self.stream_syncs.append({"current_time_ms": current_time_ms, "filter": filter})
        self._last_command = {
            "path": "hsp/synctime",
            "ok": True,
            "status_code": 200,
            "elapsed_ms": 3.0,
            "body": {"current_time": current_time_ms, "filter": filter},
            "response": {
                "hsp_state": {
                    "play_state": "playing",
                    "current_time_ms": current_time_ms,
                    "current_point": 2,
                    "points": 24,
                    "stream_id": 1,
                },
            },
        }
        return True

    def append_continuous_stream(
        self,
        points,
        *,
        tail_point_stream_index,
        tail_point_threshold=None,
    ):
        self.stream_appends.append(
            {
                "points": [dict(point) for point in points],
                "tail_point_stream_index": tail_point_stream_index,
                "tail_point_threshold": tail_point_threshold,
            }
        )
        self._last_command = {
            "path": "hsp/add",
            "ok": True,
            "status_code": 200,
            "elapsed_ms": 4.0,
            "body": {
                "points": len(points),
                "flush": False,
                "tail_point_stream_index": tail_point_stream_index,
            },
        }
        if points:
            last = points[-1]
            self.last_relative_speed = last.get("intent_speed", last.get("speed", self.last_relative_speed))
            self.last_depth_pos = last.get("x", self.last_depth_pos)
        return True

    def last_command_result(self):
        return dict(self._last_command) if self._last_command else None


class AppendFailStreamingFakeHandy(StreamingFakeHandy):
    def append_continuous_stream(
        self,
        points,
        *,
        tail_point_stream_index,
        tail_point_threshold=None,
    ):
        super().append_continuous_stream(
            points,
            tail_point_stream_index=tail_point_stream_index,
            tail_point_threshold=tail_point_threshold,
        )
        self._last_command = {
            "path": "hsp/add",
            "ok": False,
            "status_code": 503,
            "elapsed_ms": 5.0,
            "error": "append failed",
        }
        return False


class SpeedLimitStreamingFakeHandy(StreamingFakeHandy):
    def __init__(self, min_speed, max_speed):
        super().__init__()
        self.min_speed = min_speed
        self.max_speed = max_speed
        self.min_user_speed = min_speed
        self.max_user_speed = max_speed
        self.min_absolute_user_speed = min_speed * 4
        self.max_absolute_user_speed = max_speed * 4
        self.effective_speed_calls = 0

    def effective_speed_for_relative(self, speed):
        self.effective_speed_calls += 1
        return self.min_speed + (self.max_speed - self.min_speed) * (float(speed) / 100.0)

    def max_velocity_for_relative_speed(self, speed):
        return self.effective_speed_for_relative(speed)

    def duration_ms_for_depth_interval(self, velocity, start_depth, end_depth):
        distance = abs(float(end_depth) - float(start_depth))
        return max(1, int(round((distance / max(1.0, float(velocity))) * 1000.0)))


class VelocityCappedStreamingFakeHandy(StreamingFakeHandy):
    def __init__(self, max_velocity):
        super().__init__()
        self.max_velocity = max_velocity
        self.max_user_speed = max_velocity
        self.max_absolute_user_speed = max_velocity

    def max_velocity_for_relative_speed(self, _speed):
        return self.max_velocity

    def duration_ms_for_depth_interval(self, velocity, start_depth, end_depth):
        distance = abs(float(end_depth) - float(start_depth))
        return max(1, int(round((distance / max(1.0, float(velocity))) * 1000.0)))


class CappedPositionFakeHandy(FakeHandy):
    def __init__(self, max_velocity):
        super().__init__()
        self.max_velocity = max_velocity

    def max_velocity_for_relative_speed(self, _speed):
        return self.max_velocity

    def duration_ms_for_depth_interval(self, velocity, start_depth, end_depth):
        distance = abs(float(end_depth) - float(start_depth))
        return max(1, int(round((distance / max(1.0, float(velocity))) * 1000.0)))


class FailingPositionHandy(FakeHandy):
    def __init__(self):
        super().__init__()
        self._last_command = None

    def move_to_depth(self, speed, depth, *, stop_on_target=True, velocity=None, intent_speed=None, duration_ms=None):
        self.position_moves.append((speed, depth, stop_on_target, velocity))
        self.position_intent_speeds.append(speed if intent_speed is None else intent_speed)
        self.position_durations.append(duration_ms)
        self._last_command = {
            "path": "hdsp/xava",
            "ok": False,
            "status_code": 503,
            "elapsed_ms": 12.5,
            "body": {"velocity": velocity, "stopOnTarget": stop_on_target},
            "error": "device offline",
        }
        return False

    def last_command_result(self):
        return dict(self._last_command) if self._last_command else None


class IntentMatcherTests(unittest.TestCase):
    def setUp(self):
        self.matcher = IntentMatcher()
        self.current = MotionTarget(30, 40, 50)

    def test_stop_negation_does_not_stop(self):
        intent = self.matcher.parse("don't stop now", self.current)
        self.assertEqual(intent.kind, "none")

    def test_stop_auto_is_not_emergency_stop(self):
        intent = self.matcher.parse("stop auto", self.current)
        self.assertEqual(intent.kind, "auto_off")

    def test_freestyle_is_control_mode(self):
        intent = self.matcher.parse("start freestyle", self.current)
        self.assertEqual(intent.kind, "freestyle")

    def test_relative_motion_request(self):
        intent = self.matcher.parse("go faster and deeper", self.current)
        self.assertEqual(intent.kind, "move")
        self.assertGreater(intent.target.speed, self.current.speed)
        self.assertGreater(intent.target.depth, self.current.depth)

    def test_full_range_pattern(self):
        intent = self.matcher.parse("use the full range", self.current)
        self.assertEqual(intent.kind, "move")
        self.assertEqual(intent.target.depth, 50)
        self.assertEqual(intent.target.stroke_range, 95)

    def test_milk_uses_full_safe_range_by_default(self):
        intent = self.matcher.parse("milk me", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("milk", intent.matched)
        self.assertEqual(intent.target.depth, 50)
        self.assertGreaterEqual(intent.target.stroke_range, 92)
        self.assertGreaterEqual(intent.target.speed, 52)

    def test_milk_honors_explicit_short_constraint(self):
        intent = self.matcher.parse("short milk strokes", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("milk", intent.matched)
        self.assertLessEqual(intent.target.stroke_range, 24)

    def test_tip_only_maps_to_shallow_short_motion(self):
        intent = self.matcher.parse("stay on the tip with short flicks", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertLessEqual(intent.target.depth, 12)
        self.assertLessEqual(intent.target.stroke_range, 18)
        self.assertGreaterEqual(intent.target.speed, 55)

    def test_tip_flutter_maps_to_tight_fast_variation(self):
        intent = self.matcher.parse("flutter at the tip", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("flutter", intent.matched)
        self.assertLessEqual(intent.target.depth, 12)
        self.assertLessEqual(intent.target.stroke_range, 16)
        self.assertGreaterEqual(intent.target.speed, 58)

    def test_bare_endpoint_cues_keep_more_range(self):
        tip_intent = self.matcher.parse("focus on the tip", self.current)
        base_intent = self.matcher.parse("go to the base", self.current)

        self.assertEqual(tip_intent.kind, "move")
        self.assertEqual(base_intent.kind, "move")
        self.assertGreaterEqual(tip_intent.target.stroke_range, 36)
        self.assertGreaterEqual(base_intent.target.stroke_range, 40)
        self.assertIsNotNone(tip_intent.target.motion_program)
        self.assertIsNotNone(base_intent.target.motion_program)

    def test_area_focus_does_not_inherit_max_speed(self):
        current = MotionTarget(100, 50, 80)

        tip_intent = self.matcher.parse("focus on the tip", current)
        shaft_intent = self.matcher.parse("focus on the shaft", current)
        base_intent = self.matcher.parse("focus on the base", current)

        self.assertEqual(tip_intent.target.speed, 30)
        self.assertEqual(shaft_intent.target.speed, 38)
        self.assertEqual(base_intent.target.speed, 42)

    def test_relative_area_focus_preserves_requested_speed_change(self):
        current = MotionTarget(30, 50, 80)
        intent = self.matcher.parse("go faster at the tip", current)

        self.assertEqual(intent.kind, "move")
        self.assertGreater(intent.target.speed, current.speed)
        self.assertGreaterEqual(intent.target.speed, 52)

    def test_slowly_area_focus_applies_slow_speed_hint(self):
        current = MotionTarget(70, 50, 80)
        intent = self.matcher.parse("slowly focus on the tip", current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("slower", intent.matched)
        self.assertIn("slow", intent.matched)
        self.assertEqual(intent.target.depth, 10)
        self.assertEqual(intent.target.speed, 24)

    def test_shaft_maps_to_in_between_region(self):
        intent = self.matcher.parse("stroke the shaft", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("middle", intent.matched)
        self.assertEqual(intent.target.depth, 50)
        self.assertGreaterEqual(intent.target.stroke_range, 50)
        self.assertIsNotNone(intent.target.motion_program)
        self.assertEqual(
            [anchor["label"] for anchor in intent.target.motion_program["anchors"]],
            ["upper", "shaft", "lower", "shaft"],
        )

    def test_relative_motion_from_tight_range_broadens(self):
        current = MotionTarget(30, 10, 18)
        intent = self.matcher.parse("go faster", current)

        self.assertEqual(intent.kind, "move")
        self.assertGreater(intent.target.speed, current.speed)
        self.assertGreaterEqual(intent.target.stroke_range, 45)

    def test_smooth_alternation_maps_to_wide_sway(self):
        intent = self.matcher.parse("smoothly alternate across the middle", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("sway", intent.matched)
        self.assertEqual(intent.target.depth, 50)
        self.assertGreaterEqual(intent.target.stroke_range, 55)

    def test_soft_bounce_maps_to_anchor_program(self):
        intent = self.matcher.parse("soft bounce between tip middle and base", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("anchor_loop", intent.matched)
        self.assertIsNotNone(intent.target.motion_program)
        self.assertEqual(
            [anchor["label"] for anchor in intent.target.motion_program["anchors"]],
            ["tip", "middle", "base"],
        )
        self.assertGreaterEqual(intent.target.stroke_range, 55)

    def test_soft_bounce_accepts_shaft_as_midpoint_anchor(self):
        intent = self.matcher.parse("soft bounce between tip shaft and base", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("anchor_loop", intent.matched)
        self.assertIsNotNone(intent.target.motion_program)
        self.assertEqual(
            [anchor["label"] for anchor in intent.target.motion_program["anchors"]],
            ["tip", "shaft", "base"],
        )
        self.assertEqual(
            [anchor["pos"] for anchor in intent.target.motion_program["anchors"]],
            [8.0, 50.0, 92.0],
        )

    def test_base_half_maps_to_deep_half_length(self):
        intent = self.matcher.parse("use the base half", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertEqual(intent.target.depth, 75)
        self.assertEqual(intent.target.stroke_range, 50)

    def test_hold_at_tip_is_motion_pattern_not_stop(self):
        intent = self.matcher.parse("hold at the tip", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("tip", intent.matched)
        self.assertLessEqual(intent.target.stroke_range, 12)

    def test_motion_term_question_does_not_trigger_motion(self):
        intent = self.matcher.parse("what does tip mean?", self.current)

        self.assertEqual(intent.kind, "none")


class MotionSanitizerTests(unittest.TestCase):
    def test_llm_move_is_clamped_and_filled(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)
        target = sanitizer.from_llm_move({"sp": 140, "dp": -10, "rng": None}, current)
        self.assertEqual(target.speed, 100)
        self.assertEqual(target.depth, 0)
        self.assertEqual(target.stroke_range, 55)

    def test_llm_move_accepts_zone_and_length_aliases(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)
        target = sanitizer.from_llm_move({"zone": "base", "length": "half", "tempo": "fast"}, current)

        self.assertEqual(target.speed, 64)
        self.assertEqual(target.depth, 75)
        self.assertEqual(target.stroke_range, 50)

    def test_llm_move_named_pattern_fills_missing_numeric_values(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)
        target = sanitizer.from_llm_move({"position": "tip", "pattern": "flick"}, current)

        self.assertGreaterEqual(target.speed, 55)
        self.assertEqual(target.depth, 10)
        self.assertEqual(target.stroke_range, 18)

    def test_llm_move_accepts_mode_pattern_ids(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)
        target = sanitizer.from_llm_move({"pattern": "milking-pressure-build"}, current)

        self.assertIsNotNone(target)
        self.assertIn("milking-pressure-build", target.label)

    def test_llm_move_accepts_milk_pattern_as_full_range(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)
        target = sanitizer.from_llm_move({"pattern": "milk"}, current)

        self.assertIsNotNone(target)
        self.assertIn("milk", target.label)
        self.assertEqual(target.depth, 50)
        self.assertGreaterEqual(target.stroke_range, 92)

    def test_llm_bare_endpoint_cues_keep_more_range(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)

        target = sanitizer.from_llm_move({"zone": "tip", "pattern": "tease"}, current)
        base_target = sanitizer.from_llm_move({"zone": "base", "pattern": "pulse"}, current)
        shaft_target = sanitizer.from_llm_move({"zone": "shaft", "pattern": "sway"}, current)

        self.assertGreaterEqual(target.stroke_range, 36)
        self.assertGreaterEqual(base_target.stroke_range, 36)
        self.assertIsNotNone(target.motion_program)
        self.assertIsNotNone(base_target.motion_program)
        self.assertEqual(shaft_target.depth, 50)
        self.assertGreaterEqual(shaft_target.stroke_range, 55)

    def test_llm_area_focus_without_speed_does_not_inherit_max_speed(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(100, 45, 55)

        target = sanitizer.from_llm_move({"zone": "tip"}, current)
        base_target = sanitizer.from_llm_move({"zone": "base", "pattern": "pulse"}, current)

        self.assertEqual(target.speed, 30)
        self.assertEqual(base_target.speed, 44)

    def test_llm_area_focus_honors_explicit_speed(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(100, 45, 55)

        target = sanitizer.from_llm_move({"zone": "tip", "sp": 72}, current)

        self.assertEqual(target.speed, 72)

    def test_llm_move_accepts_anchor_program(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)
        target = sanitizer.from_llm_move(
            {
                "motion": "anchor_loop",
                "anchors": ["tip", "middle", "base", "upper"],
                "tempo": 0.85,
                "softness": 0.9,
                "rng": 70,
            },
            current,
        )

        self.assertEqual(target.stroke_range, 70)
        self.assertGreaterEqual(target.speed, 36)
        self.assertIn("anchor_loop", target.label)
        self.assertEqual(target.motion_program["curve"], "catmull")
        self.assertEqual([anchor["label"] for anchor in target.motion_program["anchors"]], ["tip", "middle", "base", "upper"])

    def test_llm_move_accepts_shaft_anchor_program(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)
        target = sanitizer.from_llm_move(
            {
                "motion": "anchor_loop",
                "anchors": ["tip", "shaft", "base", "shaft"],
                "tempo": 0.85,
                "softness": 0.9,
                "rng": 70,
            },
            current,
        )

        self.assertIsNotNone(target)
        self.assertEqual(target.stroke_range, 70)
        self.assertEqual(
            [anchor["label"] for anchor in target.motion_program["anchors"]],
            ["tip", "shaft", "base", "shaft"],
        )
        self.assertEqual(
            [anchor["pos"] for anchor in target.motion_program["anchors"]],
            [8.0, 50.0, 92.0, 50.0],
        )

    def test_transition_path_respects_step_limits(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(0, 0, 10)
        path = sanitizer.transition_path(current, MotionTarget(60, 50, 80))
        previous = current
        for step in path:
            self.assertLessEqual(abs(step.speed - previous.speed), sanitizer.limits.max_speed_delta)
            self.assertLessEqual(abs(step.depth - previous.depth), sanitizer.limits.max_depth_delta)
            self.assertLessEqual(abs(step.stroke_range - previous.stroke_range), sanitizer.limits.max_range_delta)
            previous = step
        self.assertEqual(path[-1], MotionTarget(60, 50, 80))


class MotionControllerTests(unittest.TestCase):
    def wait_until(self, predicate, timeout=1.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    def test_controller_routes_motion_through_smooth_path(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.set_backend("hamp")
        controller.apply_target(MotionTarget(70, 60, 80))
        self.assertGreater(len(handy.moves), 1)
        self.assertEqual(handy.moves[-1], (70, 60, 80))

    def test_controller_records_observability_trace(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)

        controller.apply_target(MotionTarget(70, 60, 80, label="wide stroke"), source="unit test")

        snapshot = controller.observability_snapshot()
        self.assertEqual(snapshot["backend"], "continuous")
        self.assertEqual(snapshot["source"], "unit test")
        self.assertEqual(snapshot["label"], "wide stroke")
        self.assertGreater(len(snapshot["trace"]), 1)
        self.assertEqual(snapshot["trace"][-1]["depth"], 60)
        self.assertEqual(snapshot["trace"][-1]["range"], 80)
        self.assertEqual(snapshot["trace"][-1]["physical_speed"], 70)
        self.assertFalse(snapshot["playback_active"])

    def test_controller_expands_llm_anchor_program(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.set_backend("hamp")
        target = controller.apply_llm_move(
            {
                "motion": "anchor_loop",
                "anchors": ["tip", "middle", "base"],
                "sp": 45,
                "rng": 70,
                "tempo": 1.0,
                "sample_interval_ms": 220,
                "max_step_delta": 40,
            }
        )

        self.assertIsNotNone(target.motion_program)
        self.assertGreater(len(handy.moves), 4)
        self.assertGreater(len({depth for _, depth, _ in handy.moves}), 3)
        ranges = [
            point["program_range"]
            for point in controller.observability_snapshot()["trace"]
            if "program_range" in point
        ]
        self.assertTrue(ranges)
        self.assertLess(ranges[-1]["min"], ranges[-1]["max"])

    def test_controller_expands_direct_anchor_target(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.set_backend("hamp")
        intent = IntentMatcher().parse("soft bounce between tip middle and base", controller.current_target())

        controller.apply_generated_target(intent.target)

        self.assertGreater(len(handy.moves), 4)
        self.assertGreater(len({depth for _, depth, _ in handy.moves}), 3)

    def test_continuous_backend_runs_fixed_pattern_until_interrupted(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        intent = IntentMatcher().parse("milk me", controller.current_target())

        controller.apply_generated_target(intent.target, source="unit test")

        self.assertTrue(self.wait_until(lambda: len(handy.position_moves) >= 3), handy.position_moves)
        snapshot = controller.observability_snapshot()
        self.assertEqual(snapshot["backend"], "continuous")
        self.assertTrue(snapshot["playback_active"])
        self.assertEqual(handy.moves, [])
        self.assertTrue(all(not move[2] for move in handy.position_moves))
        self.assertGreater(len({depth for _, depth, _, _ in handy.position_moves}), 1)
        self.assertTrue(any(point.get("continuous") for point in snapshot["trace"]))
        continuous_points = [point for point in snapshot["trace"] if point.get("continuous")]
        self.assertTrue(all("program_range" in point for point in continuous_points))
        self.assertLess(continuous_points[-1]["program_range"]["min"], continuous_points[-1]["program_range"]["max"])

        controller.stop()
        self.assertTrue(handy.stopped)
        self.assertFalse(controller.observability_snapshot()["playback_active"])

    def test_continuous_backend_prefers_hsp_timed_point_stream_when_available(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(40, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            self.assertEqual(handy.position_moves, [])
            first_batch = handy.stream_starts[0]["points"]
            self.assertIsNone(handy.stream_starts[0]["stream_id"])
            self.assertGreater(len(first_batch), 3)
            self.assertEqual(first_batch[0]["t"], 0)
            self.assertTrue(all(a["t"] < b["t"] for a, b in zip(first_batch, first_batch[1:])))
            self.assertGreater(len({round(point["x"], 1) for point in first_batch}), 2)

            snapshot = controller.observability_snapshot()
            hsp_points = [point for point in snapshot["trace"] if point.get("continuous_schema") == "hsp"]
            self.assertTrue(hsp_points)
            self.assertEqual(hsp_points[-1]["handy_path"], "hsp/play")
            self.assertEqual(hsp_points[-1]["hsp_batch"], "play")
            self.assertTrue(all(point["intent_speed"] == 40 for point in hsp_points))
        finally:
            controller.stop()

    def test_continuous_hsp_stream_encodes_variable_segment_velocity_in_timed_points(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(40, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            segment_rates = []
            for left, right in zip(points, points[1:]):
                dt = (right["t"] - left["t"]) / 1000.0
                if dt > 0:
                    segment_rates.append(abs(right["x"] - left["x"]) / dt)

            self.assertGreater(len(segment_rates), 2)
            self.assertGreater(max(segment_rates), min(segment_rates) * 1.25)
        finally:
            controller.stop()

    def test_continuous_hsp_densifies_sparse_authored_segments(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(50, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]

            self.assertGreater(len(points), 12)
            self.assertLessEqual(
                max(intervals),
                int(round(CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS * 1000.0 * 1.6)),
            )

            hsp_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            self.assertTrue(any(point.get("hsp_authored_point") is False for point in hsp_points))
            self.assertTrue(any(point.get("hsp_authored_point") is True for point in hsp_points))
        finally:
            controller.stop()

    def test_continuous_hsp_stream_preserves_timed_pattern_slopes(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(
                MotionTarget(50, 50, 80, "milk"),
                source="unit test",
            )
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            segment_depths = [abs(right["x"] - left["x"]) for left, right in zip(points, points[1:])]
            segment_rates = [
                abs(right["x"] - left["x"]) / ((right["t"] - left["t"]) / 1000.0)
                for left, right in zip(points, points[1:])
                if right["t"] > left["t"]
            ]

            self.assertGreater(max(segment_depths), POSITION_MAX_DEPTH_STEP * 2.0)
            self.assertGreater(max(segment_rates), 120.0)
            trace_rates = [
                point["hsp_segment_depth_per_second"]
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp" and "hsp_segment_depth_per_second" in point
            ]
            self.assertGreater(max(trace_rates), 120.0)
        finally:
            controller.stop()

    def test_continuous_hsp_stream_preserves_authored_subsample_timing(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(50, 50, 80, "flick"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]

            self.assertGreater(points[-1]["t"], 2000)
            self.assertLess(min(intervals), CONTINUOUS_SAMPLE_INTERVAL_SECONDS * 1000 * 0.5)
        finally:
            controller.stop()

    def test_continuous_hsp_trace_uses_scheduled_point_times(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(80, 50, 80, "flick"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            first_batch_last_index = handy.stream_starts[0]["points"][-1]["stream_index"]
            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous_schema") == "hsp"
                        and point.get("hsp_stream_index") == first_batch_last_index
                        for point in controller.observability_snapshot()["trace"]
                    )
                )
            )
            hsp_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            self.assertGreater(len(hsp_points), 3)
            trace_span = hsp_points[-1]["t"] - hsp_points[0]["t"]
            stream_span = (
                hsp_points[-1]["hsp_point_time_ms"] - hsp_points[0]["hsp_point_time_ms"]
            ) / 1000.0
            self.assertGreater(stream_span, 1.0)
            self.assertAlmostEqual(trace_span, stream_span, delta=0.1)
        finally:
            controller.stop()

    def test_continuous_hsp_preserves_relative_tempo_span_with_configured_speed_limits(self):
        slow_handy = SpeedLimitStreamingFakeHandy(50, 80)
        fast_handy = SpeedLimitStreamingFakeHandy(50, 80)
        slow_controller = MotionController(slow_handy, step_delay=0.16)
        fast_controller = MotionController(fast_handy, step_delay=0.16)

        try:
            slow_controller.apply_continuous_target(MotionTarget(0, 50, 80, "stroke"), source="unit test")
            fast_controller.apply_continuous_target(MotionTarget(100, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: slow_handy.stream_starts and fast_handy.stream_starts))

            slow_points = slow_handy.stream_starts[0]["points"]
            fast_points = fast_handy.stream_starts[0]["points"]
            slow_tempo = {round(point["tempo_scale"], 3) for point in slow_points}
            fast_tempo = {round(point["tempo_scale"], 3) for point in fast_points}
            slow_cycle = {round(point["effective_duration_seconds"], 3) for point in slow_points}
            fast_cycle = {round(point["effective_duration_seconds"], 3) for point in fast_points}

            self.assertEqual(slow_handy.effective_speed_calls, 0)
            self.assertEqual(fast_handy.effective_speed_calls, 0)
            self.assertEqual(slow_tempo, {0.5})
            self.assertEqual(fast_tempo, {1.5})
            self.assertGreater(min(slow_cycle), max(fast_cycle) * 2.5)
            self.assertEqual({round(point["intent_speed"]) for point in slow_points}, {0})
            self.assertEqual({round(point["intent_speed"]) for point in fast_points}, {100})
        finally:
            slow_controller.stop()
            fast_controller.stop()

    def test_continuous_sampler_keeps_relative_speed_before_transport_limits(self):
        handy = SpeedLimitStreamingFakeHandy(10, 30)
        controller = MotionController(handy, step_delay=0.16)
        plan = continuous_motion_plan("stroke")
        slow_target = MotionTarget(20, 50, 80, "stroke")
        fast_target = MotionTarget(80, 50, 80, "stroke")

        slow = controller._sample_continuous_motion(plan, slow_target, 0.25, sample_continuous_motion)
        fast = controller._sample_continuous_motion(plan, fast_target, 0.25, sample_continuous_motion)

        self.assertEqual(round(slow.intent_speed), 20)
        self.assertEqual(round(fast.intent_speed), 80)
        self.assertAlmostEqual(slow.tempo_scale, 0.7, places=3)
        self.assertAlmostEqual(fast.tempo_scale, 1.3, places=3)
        self.assertGreater(fast.tempo_scale - slow.tempo_scale, 0.5)

    def test_continuous_hsp_preserves_point_timing_without_velocity_stretch(self):
        class HspVelocityTrapHandy(VelocityCappedStreamingFakeHandy):
            def __init__(self):
                super().__init__(max_velocity=45)
                self.duration_calls = []

            def duration_ms_for_depth_interval(self, velocity, start_depth, end_depth):
                self.duration_calls.append((velocity, start_depth, end_depth))
                return super().duration_ms_for_depth_interval(velocity, start_depth, end_depth)

        handy = HspVelocityTrapHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(80, 50, 80, "flick"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            self.assertGreaterEqual(len(points), 3)
            rates = [
                abs(right["x"] - left["x"]) / ((right["t"] - left["t"]) / 1000.0)
                for left, right in zip(points, points[1:])
                if right["t"] > left["t"] and abs(right["x"] - left["x"]) > 0.01
            ]
            self.assertTrue(rates)
            self.assertGreater(max(rates), handy.max_velocity * 2)
            self.assertGreater(max(rates) - min(rates), 40.0)
            self.assertEqual(handy.duration_calls, [])

            scales = [
                point["hsp_transport_time_scale"]
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp" and "hsp_transport_time_scale" in point
            ]
            self.assertTrue(scales)
            self.assertEqual(set(scales), {1.0})
        finally:
            controller.stop()

    def test_continuous_hsp_trace_records_append_batches(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(80, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_appends) >= 1, timeout=1.5), handy.stream_appends)

            snapshot = controller.observability_snapshot()
            append_points = [
                point
                for point in snapshot["trace"]
                if point.get("continuous_schema") == "hsp" and point.get("hsp_batch") == "add"
            ]
            self.assertTrue(append_points)
            self.assertEqual(append_points[-1]["handy_path"], "hsp/add")
            self.assertGreater(append_points[-1]["hsp_stream_index"], len(handy.stream_starts[0]["points"]))
        finally:
            controller.stop()

    def test_continuous_hsp_append_failure_falls_back_to_hdsp(self):
        handy = AppendFailStreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.08)

        try:
            with (
                mock.patch("strokegpt.motion.CONTINUOUS_STREAM_INITIAL_BUFFER_SECONDS", 0.24),
                mock.patch("strokegpt.motion.CONTINUOUS_STREAM_TARGET_BUFFER_SECONDS", 0.24),
                mock.patch("strokegpt.motion.CONTINUOUS_STREAM_APPEND_THRESHOLD_SECONDS", 0.08),
            ):
                controller.apply_continuous_target(MotionTarget(80, 50, 80, "stroke"), source="unit test")
                self.assertTrue(self.wait_until(lambda: len(handy.stream_appends) >= 1, timeout=0.5), handy.stream_appends)
                self.assertTrue(self.wait_until(lambda: len(handy.position_moves) >= 1, timeout=0.5), handy.position_moves)

            failure_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
                and point.get("hsp_batch") == "add"
                and point.get("handy_ok") is False
            ]
            self.assertTrue(failure_points)
        finally:
            controller.stop()

    def test_continuous_hsp_periodically_syncs_firmware_clock(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(80, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_syncs) >= 1, timeout=1.4), handy.stream_syncs)

            first_sync = handy.stream_syncs[0]
            self.assertGreater(first_sync["current_time_ms"], 0)
            self.assertAlmostEqual(first_sync["filter"], 0.9)

            sync_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("hsp_clock_sync")
            ]
            self.assertTrue(sync_points)
            self.assertEqual(sync_points[-1]["handy_path"], "hsp/synctime")
            self.assertEqual(sync_points[-1]["hsp_state_current_time_ms"], first_sync["current_time_ms"])
        finally:
            controller.stop()

    def test_continuous_hsp_replacement_stream_starts_at_current_phase_time(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(50, 50, 80, "stroke"), source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            time.sleep(0.22)
            controller.apply_continuous_target(MotionTarget(70, 50, 80, "stroke"), source="second")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 2), handy.stream_starts)

            replacement = handy.stream_starts[1]
            start_time_ms = replacement["start_time_ms"]
            self.assertGreater(start_time_ms, 0)
            self.assertEqual(replacement["points"][0]["t"], start_time_ms)
            self.assertTrue(all(point["t"] >= start_time_ms for point in replacement["points"]))

            second_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
                and point.get("source") == "second"
                and point.get("hsp_batch") == "play"
            ]
            self.assertTrue(second_points)
            self.assertAlmostEqual(
                second_points[0]["hsp_point_time_ms"],
                second_points[0]["hsp_play_start_ms"],
                delta=1.0,
            )
        finally:
            controller.stop()

    def test_continuous_backend_keeps_sample_speed_out_of_current_intent(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        target = MotionTarget(20, 50, 80, "stroke")

        try:
            controller.apply_continuous_target(target, source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: len(handy.position_moves) >= 4
                    and any(move[0] > target.speed for move in handy.position_moves)
                ),
                handy.position_moves,
            )

            self.assertTrue(all(round(speed) == 20 for speed in handy.position_intent_speeds))
            self.assertEqual(round(controller.current_target().speed), 20)
            points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous")
            ]
            self.assertTrue(points)
            self.assertTrue(all(point["intent_speed"] == 20 for point in points))
            self.assertTrue(any(point["sample_speed"] > point["intent_speed"] for point in points))
            self.assertLessEqual(max(point["sample_speed"] for point in points), 40)
        finally:
            controller.stop()

    def test_continuous_low_speed_is_not_smoothed_from_previous_fast_state(self):
        handy = FakeHandy()
        handy.last_relative_speed = 80
        handy.last_depth_pos = 50
        handy.last_stroke_range = 80
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(20, 50, 80, "stroke"), source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: len(handy.position_moves) >= 1
                    and any(point.get("continuous") for point in controller.observability_snapshot()["trace"])
                ),
                handy.position_moves,
            )

            first_point = next(
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous")
            )
            first_move = handy.position_moves[0]
            self.assertEqual(first_point["intent_speed"], 20)
            self.assertLessEqual(first_point["sample_speed"], 40)
            self.assertLessEqual(round(first_move[0]), 40)
            self.assertEqual(round(handy.position_intent_speeds[0]), 20)
        finally:
            controller.stop()

    def test_continuous_step_limiter_does_not_smooth_command_speed_budget(self):
        controller = MotionController(FakeHandy(), step_delay=0)

        limited = controller._limit_continuous_step(
            MotionTarget(95, 50, 80, "previous"),
            MotionTarget(20, 92, 20, "target"),
        )

        self.assertEqual(round(limited.speed), 20)
        self.assertLessEqual(abs(limited.depth - 50), 9)
        self.assertLessEqual(abs(limited.stroke_range - 80), controller.sanitizer.limits.max_range_delta)

    def test_continuous_backend_scales_command_interval_from_intent_tempo(self):
        controller = MotionController(FakeHandy(), step_delay=0.16)
        base_interval = controller._continuous_sample_interval()

        slow_interval = controller._continuous_command_interval(0.7, base_interval)
        neutral_interval = controller._continuous_command_interval(1.0, base_interval)
        fast_interval = controller._continuous_command_interval(1.3, base_interval)

        self.assertEqual(neutral_interval, base_interval)
        self.assertGreater(slow_interval, base_interval)
        self.assertLess(fast_interval, base_interval)
        self.assertGreaterEqual(slow_interval, CONTINUOUS_MIN_COMMAND_INTERVAL_SECONDS)
        self.assertLessEqual(slow_interval, CONTINUOUS_MAX_COMMAND_INTERVAL_SECONDS)
        self.assertGreaterEqual(fast_interval, CONTINUOUS_MIN_COMMAND_INTERVAL_SECONDS)
        self.assertLessEqual(fast_interval, CONTINUOUS_MAX_COMMAND_INTERVAL_SECONDS)

    def test_continuous_trace_uses_scaled_interval_for_velocity_planning(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(20, 50, 80, "stroke"), source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: len(handy.velocity_intervals) >= 1
                    and any(point.get("continuous") for point in controller.observability_snapshot()["trace"])
                ),
                handy.velocity_intervals,
            )

            speed, _start, _end, duration_seconds = handy.velocity_intervals[-1]
            point = next(
                point
                for point in reversed(controller.observability_snapshot()["trace"])
                if point.get("continuous")
            )
            self.assertGreater(point["sample_interval_ms"], point["base_interval_ms"])
            self.assertAlmostEqual(point["sample_interval_ms"], round(duration_seconds * 1000.0, 1))
            self.assertLessEqual(round(speed), 40)
        finally:
            controller.stop()

    def test_continuous_hdsp_fallback_keeps_duration_under_velocity_budget(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(80, 50, 80, "flick"), source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: len(handy.position_durations) >= 4
                    and len({move[3] for move in handy.position_moves if move[3] is not None}) > 1
                ),
                handy.position_moves,
            )

            self.assertTrue(all(duration is None for duration in handy.position_durations))
            self.assertGreater(len({move[3] for move in handy.position_moves if move[3] is not None}), 1)
        finally:
            controller.stop()

    def test_continuous_backend_preserves_same_pattern_phase_on_update(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        intent = IntentMatcher().parse("milk me", controller.current_target())

        try:
            controller.apply_generated_target(intent.target, source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.position_moves) >= 2), handy.position_moves)

            updated_target = MotionTarget(
                intent.target.speed + 6,
                intent.target.depth,
                intent.target.stroke_range,
                intent.target.label,
                motion_program=intent.target.motion_program,
            )
            controller.apply_generated_target(updated_target, source="second")
            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous")
                        and point.get("source") == "second"
                        and point.get("sample_index") == 0
                        for point in controller.observability_snapshot()["trace"]
                    )
                )
            )

            second_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous") and point.get("source") == "second"
            ]
            self.assertTrue(second_points)
            self.assertGreater(second_points[0]["phase_offset_ms"], 0)
            self.assertLess(second_points[0]["phase_offset_ms"], second_points[0]["cycle_ms"])
        finally:
            controller.stop()

    def test_continuous_morph_duration_scales_with_target_gap(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        start = MotionTarget(40, 50, 50)

        small = controller._continuous_morph_seconds(start, MotionTarget(42, 54, 52))
        large = controller._continuous_morph_seconds(start, MotionTarget(85, 96, 95))

        self.assertLess(small, large)
        self.assertGreaterEqual(small, 0.32)
        self.assertLessEqual(large, CONTINUOUS_MAX_MORPH_SECONDS)
        self.assertGreater(large, 0.65)

    def test_continuous_morph_duration_ignores_speed_only_gap(self):
        controller = MotionController(FakeHandy(), step_delay=0)

        speed_only = controller._continuous_morph_seconds(
            MotionTarget(95, 50, 80),
            MotionTarget(20, 50, 80),
        )

        self.assertEqual(speed_only, CONTINUOUS_MIN_MORPH_SECONDS)

    def test_continuous_trace_includes_supplied_mode_metadata(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)

        try:
            applied = controller.apply_continuous_target(
                MotionTarget(50, 50, 70, "stroke"),
                source="freestyle planner",
                trace_metadata={
                    "mode": "freestyle",
                    "freestyle_pattern_id": "stroke",
                    "freestyle_planner_sleep_ms": 1200.0,
                    "sample_index": 999,
                },
            )
            self.assertTrue(applied)
            self.assertTrue(self.wait_until(lambda: len(handy.position_moves) >= 1), handy.position_moves)

            point = next(
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous") and point.get("source") == "freestyle planner"
            )
            self.assertEqual(point["mode"], "freestyle")
            self.assertEqual(point["freestyle_pattern_id"], "stroke")
            self.assertEqual(point["freestyle_planner_sleep_ms"], 1200.0)
            self.assertEqual(point["sample_index"], 0)
        finally:
            controller.stop()

    def test_continuous_backend_routes_plain_chat_targets_through_live_stroke_control(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)

        controller.apply_generated_target(MotionTarget(70, 90, 80, "plain chat"), source="llm")

        self.assertEqual(handy.position_moves, [])
        self.assertGreater(len(handy.moves), 1)
        self.assertEqual(handy.moves[-1], (70, 90, 80))

    def test_position_backend_routes_generated_frames_to_position_moves(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.set_backend("position")
        intent = IntentMatcher().parse("soft bounce between tip middle and base", controller.current_target())

        controller.apply_generated_target(intent.target)

        self.assertGreater(len(handy.position_moves), 4)
        self.assertEqual(handy.moves, [])
        self.assertGreater(len({depth for _, depth, _, _ in handy.position_moves}), 3)

    def test_position_backend_uses_authored_pattern_timing(self):
        controller = MotionController(FakeHandy(), step_delay=0.16)
        controller.set_backend("position")
        captured = []

        def capture_position_frames(frames, **_kwargs):
            captured.extend(frames)
            return True

        controller.apply_position_frames = capture_position_frames

        controller.apply_generated_target(MotionTarget(80, 50, 80, "flick"), source="unit test")

        timed = [frame for frame in captured if getattr(frame, "phase", "") == "timed-pattern"]
        self.assertTrue(timed)
        self.assertGreater(max(frame.target.speed for frame in timed), 90)
        self.assertTrue(any(frame.delay_factor < 0.2 for frame in timed[1:]))

    def test_position_backend_stretches_timed_frames_to_velocity_cap(self):
        handy = CappedPositionFakeHandy(max_velocity=25)
        controller = MotionController(handy, step_delay=0.16)
        controller.set_backend("position")

        controller.apply_generated_target(MotionTarget(80, 50, 80, "flick"), source="unit test")

        previous_depth = 30
        checked = 0
        for move, duration_ms in zip(handy.position_moves, handy.position_durations):
            _speed, depth, _stop_on_target, _velocity = move
            if duration_ms is not None:
                required = handy.duration_ms_for_depth_interval(
                    handy.max_velocity,
                    previous_depth,
                    depth,
                )
                self.assertGreaterEqual(duration_ms + 50, required)
                checked += 1
            previous_depth = depth
        self.assertGreater(checked, 0)

    def test_position_backend_routes_plain_chat_targets_through_position_smoothing(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.set_backend("position")

        controller.apply_generated_target(MotionTarget(70, 90, 80, "plain chat"), source="llm")

        self.assertEqual(handy.moves, [])
        self.assertGreater(len(handy.position_moves), 3)
        depths = [move[1] for move in handy.position_moves]
        self.assertEqual(depths[-1], 90)
        self.assertTrue(all(abs(a - b) <= 9 for a, b in zip(depths, depths[1:])), depths)
        self.assertEqual(handy.position_moves[-1][2], True)

    def test_position_playback_passes_duration_for_timed_frames_only(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.25)
        controller.set_backend("position")

        controller.apply_position_frames(
            [PositionFrame(MotionTarget(40, 35, 40, "timed"), delay_factor=2.0, phase="timed-pattern")],
            final_stop_on_target=False,
        )

        self.assertEqual(handy.position_durations[-1], 500)

        controller.apply_position_frames(
            [PositionFrame(MotionTarget(40, 60, 40, "pattern"), delay_factor=2.0, phase="pattern")],
            final_stop_on_target=False,
        )

        self.assertIsNone(handy.position_durations[-1])

    def test_stop_cancels_and_stops_handy(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.stop()
        self.assertTrue(handy.stopped)

    def test_pause_stops_handy_without_replacing_observability_label(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.apply_target(MotionTarget(45, 55, 65, label="active pattern"), source="unit test")

        controller.pause()
        snapshot = controller.observability_snapshot()

        self.assertTrue(handy.stopped)
        self.assertTrue(controller.is_paused())
        self.assertEqual(snapshot["label"], "active pattern")
        self.assertNotEqual(snapshot["source"], "stop")

        controller.resume()
        self.assertFalse(controller.is_paused())

    def test_position_playback_waits_for_resume(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.03)
        controller.pause()
        finished = threading.Event()

        def run_playback():
            controller.apply_position_frames(
                [
                    SimpleNamespace(target=MotionTarget(35, 45, 50, "paused frame"), delay_factor=1),
                ],
                source="unit test",
            )
            finished.set()

        thread = threading.Thread(target=run_playback)
        thread.start()
        time.sleep(0.05)

        self.assertFalse(finished.is_set())
        self.assertEqual(handy.position_moves, [])

        controller.resume()
        self.assertTrue(finished.wait(1))
        thread.join(timeout=1)
        self.assertTrue(handy.position_moves)

    def test_apply_frames_can_stop_handy_after_preview_completion(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        frames = [
            SimpleNamespace(target=MotionTarget(45, 55, 65), delay_factor=0),
            SimpleNamespace(target=MotionTarget(35, 25, 30), delay_factor=0),
        ]

        completed = controller.apply_frames(frames, stop_after=True)

        self.assertTrue(completed)
        self.assertEqual(handy.moves[-1], (35, 25, 30))
        self.assertTrue(handy.stopped)

    def test_apply_position_frames_limits_large_position_jumps(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        frames = [
            SimpleNamespace(target=MotionTarget(45, 20, 10), delay_factor=0),
            SimpleNamespace(target=MotionTarget(45, 80, 10), delay_factor=0),
            SimpleNamespace(target=MotionTarget(30, 35, 10), delay_factor=0),
        ]

        completed = controller.apply_position_frames(frames, stop_after=True)

        self.assertTrue(completed)
        self.assertEqual(handy.moves, [])
        depths = [move[1] for move in handy.position_moves]
        self.assertIn(20, depths)
        self.assertEqual(depths[-1], 35)
        self.assertIn(80, depths)
        # First emitted depth bridges from the controller's starting depth (30)
        # so it must stay within the per-step depth budget of 9.
        self.assertLessEqual(abs(depths[0] - 30), 9)
        self.assertTrue(all(abs(a - b) <= 9 for a, b in zip(depths, depths[1:])), depths)
        self.assertTrue(all(move[3] is not None and move[3] <= move[0] for move in handy.position_moves))
        self.assertEqual(handy.last_stroke_range, 40)
        self.assertTrue(handy.stopped)
        snapshot = controller.observability_snapshot()
        self.assertEqual(snapshot["source"], "pattern preview")
        self.assertEqual(snapshot["trace"][-1]["label"], "preview stopped")

    def test_timed_position_frames_preserve_split_segment_delay(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.25)
        frames = [
            SimpleNamespace(
                target=MotionTarget(90, 90, 10, "fast timed segment"),
                delay_factor=0.4,
                phase="timed-pattern",
            ),
        ]

        playback_frames = controller._position_playback_frames(frames)

        self.assertGreater(len(playback_frames), 1)
        self.assertAlmostEqual(sum(frame.delay_factor for frame in playback_frames), 0.4)
        self.assertEqual(playback_frames[-1].phase, "timed-pattern")
        self.assertTrue(all(frame.phase in {"timed-blend", "timed-pattern"} for frame in playback_frames))

    def test_apply_position_frames_keeps_timed_speed_variation_after_splitting(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.25)
        frames = [
            SimpleNamespace(
                target=MotionTarget(90, 90, 10, "fast timed segment"),
                delay_factor=0.4,
                phase="timed-pattern",
            ),
            SimpleNamespace(
                target=MotionTarget(24, 20, 10, "slow timed segment"),
                delay_factor=3.2,
                phase="timed-pattern",
            ),
        ]

        completed = controller.apply_position_frames(
            frames,
            stop_after=False,
            final_stop_on_target=False,
        )

        self.assertTrue(completed)
        durations = [interval[3] for interval in handy.velocity_intervals]
        velocities = [move[3] for move in handy.position_moves if move[3] is not None]
        self.assertGreater(max(durations), min(durations) * 4)
        self.assertGreater(max(velocities), min(velocities) * 2)

    def test_apply_position_frames_softens_direction_reversals(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        frames = [
            SimpleNamespace(target=MotionTarget(45, 20, 10), delay_factor=0),
            SimpleNamespace(target=MotionTarget(45, 80, 10), delay_factor=0),
            SimpleNamespace(target=MotionTarget(30, 35, 10), delay_factor=0),
        ]

        completed = controller.apply_position_frames(frames, stop_after=False)

        self.assertTrue(completed)
        depths = [move[1] for move in handy.position_moves]
        speeds = [move[0] for move in handy.position_moves]
        self.assertIn(20, depths)
        self.assertEqual(depths[-1], 35)
        self.assertIn(80, depths)
        self.assertLessEqual(abs(depths[0] - 30), 9)
        apex_index = depths.index(80)
        self.assertLess(speeds[apex_index], 45)
        self.assertTrue(all(speed <= 30 for speed in speeds[apex_index:]), speeds)
        self.assertTrue(all(move[3] <= move[0] for move in handy.position_moves))
        self.assertEqual(handy.position_moves[-1][2], True)

    def test_apply_position_frames_uses_final_stop_on_target_without_stop_after(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.1)
        frames = [
            SimpleNamespace(target=MotionTarget(40, 25, 10), delay_factor=0),
            SimpleNamespace(target=MotionTarget(40, 75, 10), delay_factor=0),
        ]

        completed = controller.apply_position_frames(frames, stop_after=False)

        self.assertTrue(completed)
        self.assertEqual(handy.position_moves[-1][2], True)
        self.assertTrue(all(not move[2] for move in handy.position_moves[:-1]))
        self.assertFalse(handy.stopped)

    def test_apply_position_frames_can_pass_through_final_target(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.1)
        frames = [
            SimpleNamespace(target=MotionTarget(40, 25, 10), delay_factor=0),
            SimpleNamespace(target=MotionTarget(40, 75, 10), delay_factor=0),
        ]

        completed = controller.apply_position_frames(
            frames,
            stop_after=False,
            final_stop_on_target=False,
        )

        self.assertTrue(completed)
        self.assertTrue(all(not move[2] for move in handy.position_moves))
        self.assertFalse(handy.stopped)

    def test_apply_position_frames_cushions_final_pass_through_velocity(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.1)
        frames = [
            SimpleNamespace(target=MotionTarget(40, 25, 10), delay_factor=0.1),
            SimpleNamespace(target=MotionTarget(40, 75, 10), delay_factor=0.1),
        ]

        completed = controller.apply_position_frames(
            frames,
            stop_after=False,
            final_stop_on_target=False,
        )

        self.assertTrue(completed)
        self.assertGreaterEqual(handy.velocity_intervals[-1][3], POSITION_PASS_THROUGH_MIN_SECONDS)
        self.assertFalse(handy.position_moves[-1][2])
        self.assertFalse(handy.stopped)

    def test_apply_position_frames_bridges_from_current_target_into_first_frame(self):
        # Starting depth is 30 (FakeHandy default); first frame is 80, a 50-unit
        # jump that exceeds the per-step depth budget of 9. The bridge should
        # split that jump into intermediate steps before reaching 80.
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        frames = [
            SimpleNamespace(target=MotionTarget(45, 80, 10), delay_factor=0),
        ]

        completed = controller.apply_position_frames(frames, stop_after=False)

        self.assertTrue(completed)
        depths = [move[1] for move in handy.position_moves]
        self.assertGreater(len(depths), 1, depths)
        self.assertLessEqual(abs(depths[0] - 30), 9)
        self.assertEqual(depths[-1], 80)
        self.assertTrue(all(abs(a - b) <= 9 for a, b in zip(depths, depths[1:])), depths)

    def test_apply_position_frames_records_per_frame_timing_in_trace(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        frames = [
            SimpleNamespace(target=MotionTarget(40, 25, 10), delay_factor=0),
            SimpleNamespace(target=MotionTarget(40, 28, 10), delay_factor=0),
        ]

        completed = controller.apply_position_frames(frames, stop_after=False)

        self.assertTrue(completed)
        snapshot = controller.observability_snapshot()
        position_points = [point for point in snapshot["trace"] if "frame_index" in point]
        self.assertGreaterEqual(len(position_points), 2)
        for point in position_points:
            self.assertIn("command_ms", point)
            self.assertIn("frame_count", point)
            self.assertIn("is_pass_through_final", point)
            self.assertEqual(point["program_range"], {"min": 25, "max": 28})
            self.assertGreaterEqual(point["command_ms"], 0)
        # Every emitted point after the first one should report the gap from the
        # previous command, so the operator can spot starvation between frames.
        self.assertTrue(any("gap_ms" in point for point in position_points[1:]))

        completed = controller.apply_position_frames(frames, stop_after=False)
        self.assertTrue(completed)
        snapshot = controller.observability_snapshot()
        position_points = [point for point in snapshot["trace"] if "frame_index" in point]
        # The first frame of a follow-up batch carries the inter-batch gap so we
        # can tell the planner-side wait apart from per-frame stalls.
        first_frame_points = [point for point in position_points if point.get("frame_index") == 0]
        self.assertTrue(any("batch_gap_ms" in point for point in first_frame_points))

    def test_position_trace_records_failed_handy_command(self):
        controller = MotionController(FailingPositionHandy(), step_delay=0)
        frames = [
            SimpleNamespace(target=MotionTarget(50, 35, 40, label="one"), delay_factor=0.0, phase="pattern"),
        ]

        completed = controller.apply_position_frames(frames, stop_after=False)

        self.assertTrue(completed)
        snapshot = controller.observability_snapshot()
        point = next(point for point in snapshot["trace"] if "frame_index" in point)
        self.assertFalse(point["handy_ok"])
        self.assertEqual(point["handy_path"], "hdsp/xava")
        self.assertEqual(point["handy_status"], 503)
        self.assertEqual(point["handy_elapsed_ms"], 12.5)
        self.assertEqual(point["handy_velocity"], 50)
        self.assertTrue(point["handy_stop_on_target"])
        self.assertEqual(point["handy_error"], "device offline")


if __name__ == "__main__":
    unittest.main()
