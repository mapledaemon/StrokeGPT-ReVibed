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
    CONTINUOUS_HSP_MIN_POINT_INTERVAL_SECONDS,
    CONTINUOUS_HSP_AREA_FOCUS_POINT_INTERVAL_SECONDS,
    CONTINUOUS_HSP_AREA_FOCUS_REPLACEMENT_LEAD_SECONDS,
    CONTINUOUS_HSP_AREA_FOCUS_TARGET_BUFFER_SECONDS,
    CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS,
    CONTINUOUS_HSP_DUPLICATE_KEEPALIVE_SECONDS,
    CONTINUOUS_HSP_DUPLICATE_POSITION_EPSILON,
    CONTINUOUS_HSP_REPLACEMENT_BRIDGE_MIN_LATENCY_SECONDS,
    CONTINUOUS_HSP_TAIL_THRESHOLD_LEAD_SECONDS,
    CONTINUOUS_HSP_REPLACEMENT_MAX_LEAD_SECONDS,
    CONTINUOUS_SAMPLE_INTERVAL_SECONDS,
    CONTINUOUS_STREAM_APPEND_THRESHOLD_SECONDS,
    CONTINUOUS_STREAM_MAX_POINTS_PER_COMMAND,
    CONTINUOUS_STREAM_TARGET_BUFFER_SECONDS,
    ContinuousPhaseState,
    IntentMatcher,
    MotionController,
    MotionSanitizer,
    MotionTarget,
    MOTION_PATTERN_PREVIEW_MIN_SECONDS,
    PositionFrame,
    POSITION_PASS_THROUGH_MIN_SECONDS,
)
from strokegpt.motion_patterns import (
    CONTINUOUS_HIGH_SPEED_MULTI_TURN_EASE_MIN_CYCLE_SECONDS,
    CONTINUOUS_HIGH_SPEED_TURN_EASE_MIN_CYCLE_SECONDS,
    CONTINUOUS_MIN_EFFECTIVE_CYCLE_SECONDS,
    MotionPattern,
    PatternAction,
    continuous_motion_plan,
    continuous_plan_timed_points,
    continuous_plan_timed_phase_points,
    continuous_motion_plan_from_pattern,
    sample_continuous_motion,
)


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
        self.stream_replacements = []
        self.stream_appends = []
        self.stream_syncs = []
        self._hsp_streaming = False
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
        event = {
            "points": [dict(point) for point in points],
            "stream_id": stream_id,
            "start_time_ms": start_time_ms,
            "tail_point_stream_index": tail_point_stream_index,
            "tail_point_threshold": tail_point_threshold,
        }
        replacing = self._hsp_streaming
        if replacing:
            self.stream_replacements.append(event)
        else:
            self.stream_starts.append(event)
        self._last_command = {
            "path": "hsp/add" if replacing else "hsp/play",
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
        self._hsp_streaming = True
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
        force_resume=False,
    ):
        self.stream_appends.append(
            {
                "points": [dict(point) for point in points],
                "tail_point_stream_index": tail_point_stream_index,
                "tail_point_threshold": tail_point_threshold,
                "force_resume": bool(force_resume),
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

    def stop(self):
        super().stop()
        self._hsp_streaming = False


class PausedHspStreamingFakeHandy(StreamingFakeHandy):
    def __init__(self):
        super().__init__()
        self.hsp_state = None
        self.hsp_state_sse_event_type = ""

    def diagnostics(self, *args, **kwargs):
        return {
            "relative_speed": self.last_relative_speed,
            "depth": self.last_depth_pos,
            "range": self.last_stroke_range,
            "hsp_state": dict(self.hsp_state) if isinstance(self.hsp_state, dict) else None,
            "hsp_state_sse_event_type": self.hsp_state_sse_event_type,
        }


class AppendFailStreamingFakeHandy(StreamingFakeHandy):
    def append_continuous_stream(
        self,
        points,
        *,
        tail_point_stream_index,
        tail_point_threshold=None,
        force_resume=False,
    ):
        super().append_continuous_stream(
            points,
            tail_point_stream_index=tail_point_stream_index,
            tail_point_threshold=tail_point_threshold,
            force_resume=force_resume,
        )
        self._last_command = {
            "path": "hsp/add",
            "ok": False,
            "status_code": 503,
            "elapsed_ms": 5.0,
            "error": "append failed",
        }
        return False


class StartRaiseStreamingFakeHandy(StreamingFakeHandy):
    def start_continuous_stream(
        self,
        points,
        *,
        stream_id=None,
        start_time_ms=0,
        tail_point_stream_index=None,
        tail_point_threshold=None,
    ):
        raise RuntimeError("start failed")


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
        self.assertEqual(tip_intent.target.depth, 34)
        self.assertEqual(base_intent.target.depth, 66)
        self.assertGreaterEqual(tip_intent.target.stroke_range, 82)
        self.assertGreaterEqual(base_intent.target.stroke_range, 82)
        self.assertIsNotNone(tip_intent.target.motion_program)
        self.assertIsNotNone(base_intent.target.motion_program)
        self.assertTrue(tip_intent.target.motion_program["generated_area_focus"])
        self.assertTrue(base_intent.target.motion_program["generated_area_focus"])

    def test_area_focus_does_not_inherit_max_speed(self):
        current = MotionTarget(100, 50, 80)

        tip_intent = self.matcher.parse("focus on the tip", current)
        shaft_intent = self.matcher.parse("focus on the shaft", current)
        base_intent = self.matcher.parse("focus on the base", current)

        self.assertEqual(tip_intent.target.speed, 30)
        self.assertEqual(shaft_intent.target.speed, 38)
        self.assertEqual(base_intent.target.speed, 42)
        self.assertGreaterEqual(tip_intent.target.stroke_range, 82)
        self.assertGreaterEqual(shaft_intent.target.stroke_range, 86)
        self.assertGreaterEqual(base_intent.target.stroke_range, 82)

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
        self.assertEqual(intent.target.depth, 34)
        self.assertGreaterEqual(intent.target.stroke_range, 82)
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
            ["tip", "shaft", "base", "shaft"],
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
        self.assertGreaterEqual(intent.target.stroke_range, 70)

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

    def test_lick_base_maps_to_tight_deep_area_focus_target(self):
        intent = self.matcher.parse("lick the base", self.current)

        self.assertEqual(intent.kind, "move")
        self.assertIn("base", intent.matched)
        self.assertIn("short", intent.matched)
        self.assertEqual(intent.target.depth, 88)
        self.assertEqual(intent.target.stroke_range, 24)
        self.assertIsNone(intent.target.motion_program)

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
        self.assertEqual(target.stroke_range, 70)

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

    def test_llm_broad_milk_ignores_noisy_depth_center(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(26, 36, 90, "llm+milk")
        target = sanitizer.from_llm_move({"pattern": "milk", "sp": 26, "dp": 96, "rng": 90}, current)

        self.assertIsNotNone(target)
        self.assertIn("milk", target.label)
        self.assertEqual(target.speed, 26)
        self.assertEqual(target.depth, 50)
        self.assertEqual(target.stroke_range, 90)

    def test_llm_area_milk_preserves_area_depth(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 50, 90, "llm+milk")
        target = sanitizer.from_llm_move(
            {"pattern": "milk", "zone": "base", "dp": 75, "rng": 70},
            current,
        )

        self.assertIsNotNone(target)
        self.assertIn("milk", target.label)
        self.assertEqual(target.depth, 75)
        self.assertEqual(target.stroke_range, 70)

    def test_llm_bare_endpoint_cues_keep_more_range(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)

        target = sanitizer.from_llm_move({"zone": "tip", "pattern": "tease"}, current)
        base_target = sanitizer.from_llm_move({"zone": "base", "pattern": "pulse"}, current)
        shaft_target = sanitizer.from_llm_move({"zone": "shaft", "pattern": "sway"}, current)

        self.assertGreaterEqual(target.stroke_range, 65)
        self.assertGreaterEqual(base_target.stroke_range, 65)
        self.assertIsNotNone(target.motion_program)
        self.assertIsNotNone(base_target.motion_program)
        self.assertEqual(shaft_target.depth, 50)
        self.assertGreaterEqual(shaft_target.stroke_range, 70)

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

    def test_llm_middle_area_focus_ignores_noisy_depth_and_range(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)

        target = sanitizer.from_llm_move({"zone": "middle", "sp": 17, "dp": 71, "rng": 80}, current)
        noisy_target = sanitizer.from_llm_move({"zone": "middle", "sp": 17, "dp": 40, "rng": 46}, current)

        self.assertIsNotNone(target)
        self.assertIn("middle", target.label)
        self.assertEqual(target.speed, 17)
        self.assertEqual(target.depth, 50)
        self.assertEqual(target.stroke_range, 86)
        self.assertTrue(target.motion_program.get("generated_area_focus"))
        self.assertEqual(noisy_target.depth, target.depth)
        self.assertEqual(noisy_target.stroke_range, target.stroke_range)

    def test_default_middle_anchor_loop_uses_area_focus_transport(self):
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)

        target = sanitizer.from_llm_move(
            {"motion": "anchor_loop", "zone": "middle", "dp": 68, "rng": 80},
            current,
        )

        self.assertIsNotNone(target)
        self.assertEqual(target.depth, 50)
        self.assertEqual(target.stroke_range, 86)
        self.assertTrue(target.motion_program.get("generated_area_focus"))

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

    def wait_for_hsp_trace(self, controller, predicate=None, timeout=1.0):
        points = []

        def trace_matches():
            nonlocal points
            points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            if predicate is None:
                return bool(points)
            return any(predicate(point) for point in points)

        self.assertTrue(self.wait_until(trace_matches, timeout=timeout), controller.observability_snapshot()["trace"])
        return points

    def hsp_rapid_duplicate_integer_intervals(self, points):
        rapid = []
        keepalive_ms = int(round(CONTINUOUS_HSP_DUPLICATE_KEEPALIVE_SECONDS * 1000.0))
        for previous, current in zip(points, points[1:]):
            previous_x = int(round(float(previous["x"])))
            current_x = int(round(float(current["x"])))
            interval_ms = int(current["t"]) - int(previous["t"])
            if previous_x == current_x and interval_ms < keepalive_ms:
                rapid.append((current_x, interval_ms))
        return rapid

    def hsp_rapid_near_duplicate_intervals(self, points):
        rapid = []
        keepalive_ms = int(round(CONTINUOUS_HSP_DUPLICATE_KEEPALIVE_SECONDS * 1000.0))
        for previous, current in zip(points, points[1:]):
            interval_ms = int(current["t"]) - int(previous["t"])
            delta = abs(float(current["x"]) - float(previous["x"]))
            if delta < CONTINUOUS_HSP_DUPLICATE_POSITION_EPSILON and interval_ms < keepalive_ms:
                rapid.append((round(delta, 3), interval_ms))
        return rapid

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
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0)
        intent = IntentMatcher().parse("milk me", controller.current_target())

        controller.apply_generated_target(intent.target, source="unit test")

        self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
        self.assertTrue(
            self.wait_until(
                lambda: any(
                    point.get("continuous")
                    for point in controller.observability_snapshot()["trace"]
                )
            ),
            controller.observability_snapshot()["trace"],
        )
        snapshot = controller.observability_snapshot()
        self.assertEqual(snapshot["backend"], "continuous")
        self.assertTrue(snapshot["playback_active"])
        self.assertEqual(handy.moves, [])
        self.assertEqual(handy.position_moves, [])
        self.assertGreater(len({round(point["x"], 1) for point in handy.stream_starts[0]["points"]}), 1)
        self.assertTrue(any(point.get("continuous") for point in snapshot["trace"]))
        continuous_points = [
            point for point in snapshot["trace"] if point.get("continuous_schema") == "hsp"
        ]
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

            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous_schema") == "hsp"
                        for point in controller.observability_snapshot()["trace"]
                    )
                ),
                controller.observability_snapshot()["trace"],
            )
            snapshot = controller.observability_snapshot()
            hsp_points = [point for point in snapshot["trace"] if point.get("continuous_schema") == "hsp"]
            play_points = [point for point in hsp_points if point.get("hsp_batch") == "play"]
            self.assertTrue(play_points)
            self.assertEqual(play_points[-1]["handy_path"], "hsp/play")
            self.assertTrue(all(point["intent_speed"] == 40 for point in hsp_points))
        finally:
            controller.stop()

    def test_motion_pattern_preview_uses_continuous_hsp_stream(self):
        handy = StreamingFakeHandy()
        handy.last_relative_speed = 50
        handy.last_depth_pos = 46
        handy.last_stroke_range = 80
        controller = MotionController(handy, step_delay=0.16)
        pattern = MotionPattern(
            "Small Shape",
            (
                PatternAction(0, 45),
                PatternAction(300, 55),
                PatternAction(600, 45),
            ),
        )

        started_at = time.monotonic()
        completed = controller.apply_motion_pattern(
            pattern,
            MotionTarget(50, 50, 80, "motion training preview"),
            preserve_timing=True,
            stop_after=True,
            source="motion training preview",
        )
        elapsed = time.monotonic() - started_at

        self.assertTrue(completed)
        self.assertEqual(handy.moves, [])
        self.assertEqual(handy.position_moves, [])
        self.assertEqual(len(handy.stream_starts), 1)
        self.assertEqual(handy.stream_appends, [])
        points = handy.stream_starts[0]["points"]
        self.assertGreater(len(points), 2)
        self.assertEqual(points[0]["t"], 0)
        self.assertGreaterEqual(points[-1]["t"], int(MOTION_PATTERN_PREVIEW_MIN_SECONDS * 1000) - 1)
        self.assertGreaterEqual(elapsed, MOTION_PATTERN_PREVIEW_MIN_SECONDS - 0.1)
        depths = [point["x"] for point in points]
        self.assertGreater(min(depths), 40)
        self.assertLess(max(depths), 60)
        self.assertTrue(handy.stopped)
        self.assertFalse(controller.observability_snapshot()["playback_active"])

    def test_position_motion_pattern_preview_repeats_short_frames(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        controller.set_backend("position")
        pattern = MotionPattern(
            "Short Shape",
            (
                PatternAction(0, 45),
                PatternAction(300, 55),
                PatternAction(600, 45),
            ),
        )

        completed = controller.apply_motion_pattern(
            pattern,
            MotionTarget(50, 50, 80, "motion training preview"),
            preserve_timing=True,
            stop_after=True,
            source="motion training preview",
        )

        self.assertTrue(completed)
        self.assertGreaterEqual(
            sum((duration or 0) for duration in handy.position_durations),
            int(MOTION_PATTERN_PREVIEW_MIN_SECONDS * 1000) - 50,
        )
        self.assertTrue(handy.stopped)

    def test_short_motion_pattern_preview_cycles_cover_minimum_duration(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        pattern = MotionPattern(
            "Short Shape",
            (
                PatternAction(0, 45),
                PatternAction(300, 55),
                PatternAction(600, 45),
            ),
        )
        target = MotionTarget(50, 50, 80, "motion training preview")
        plan = continuous_motion_plan_from_pattern(pattern)
        duration = sample_continuous_motion(plan, target, 0.0).effective_duration_seconds

        cycles = controller._finite_pattern_cycles(plan, target)

        self.assertGreater(cycles, 1)
        self.assertGreaterEqual(cycles * duration, MOTION_PATTERN_PREVIEW_MIN_SECONDS)
        self.assertLess(cycles * duration, MOTION_PATTERN_PREVIEW_MIN_SECONDS + duration)

    def test_fast_continuous_short_patterns_keep_high_speed_turn_floor(self):
        plan = continuous_motion_plan("flick")
        sample = sample_continuous_motion(plan, MotionTarget(100, 50, 80, "flick"), 0.0)

        self.assertGreaterEqual(
            sample.effective_duration_seconds,
            CONTINUOUS_HIGH_SPEED_TURN_EASE_MIN_CYCLE_SECONDS,
        )
        self.assertLess(sample.effective_duration_seconds, CONTINUOUS_MIN_EFFECTIVE_CYCLE_SECONDS)

    def test_continuous_hsp_points_report_intent_range_and_sample_range(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            target = MotionTarget(40, 50, 80, "stroke")
            controller.apply_continuous_target(target, source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            first_batch = handy.stream_starts[0]["points"]
            self.assertTrue(all(point["range"] == target.stroke_range for point in first_batch))
            self.assertTrue(all("sample_range" in point for point in first_batch))
            self.assertTrue(any(point["sample_range"] < target.stroke_range for point in first_batch))

            hsp_points = self.wait_for_hsp_trace(controller)
            self.assertTrue(hsp_points)
            self.assertTrue(all(point["range"] == target.stroke_range for point in hsp_points))
            self.assertTrue(any(point["sample_range"] < target.stroke_range for point in hsp_points))
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
                int(
                    round(
                        (
                            CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS
                            + CONTINUOUS_HSP_MIN_POINT_INTERVAL_SECONDS
                        )
                        * 1000.0
                    )
                ),
            )

            hsp_points = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("hsp_authored_point") is True,
            )
            self.assertTrue(any(point.get("hsp_authored_point") is True for point in hsp_points))
        finally:
            controller.stop()

    def test_continuous_hsp_long_patterns_keep_smooth_point_cadence(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(47, 50, 66, "surge"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_appends) == 1), handy.stream_appends)

            points = sorted(
                handy.stream_starts[0]["points"] + handy.stream_appends[0]["points"],
                key=lambda point: point["t"],
            )
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]
            depth_deltas = [abs(right["x"] - left["x"]) for left, right in zip(points, points[1:])]
            depths = [point["x"] for point in points]

            self.assertGreater(len(points), 30)
            self.assertLessEqual(
                max(intervals),
                int(
                    round(
                        (
                            CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS
                            + CONTINUOUS_HSP_MIN_POINT_INTERVAL_SECONDS
                        )
                        * 1000.0
                    )
                ),
            )
            self.assertLessEqual(max(depth_deltas), 8.0)
            self.assertGreater(max(depths) - min(depths), 20.0)
        finally:
            controller.stop()

    def test_continuous_hsp_stream_preserves_timed_pattern_slopes(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            plan = continuous_motion_plan_from_pattern(MotionPattern(
                "fast transport test",
                (
                    PatternAction(0, 0),
                    PatternAction(180, 100),
                    PatternAction(360, 0),
                ),
                window_scale=1.0,
            ))
            controller._apply_continuous_plan(
                plan,
                MotionTarget(50, 50, 80, "fast transport test"),
                source="unit test",
            )
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            def hsp_trace_rows():
                return [
                    point
                    for point in controller.observability_snapshot()["trace"]
                    if point.get("continuous_schema") == "hsp"
                ]

            self.assertTrue(
                self.wait_until(lambda: len(hsp_trace_rows()) >= len(points)),
                hsp_trace_rows(),
            )
            segment_rates = [
                abs(right["x"] - left["x"]) / ((right["t"] - left["t"]) / 1000.0)
                for left, right in zip(points, points[1:])
                if right["t"] > left["t"]
            ]

            self.assertGreater(max(segment_rates), 120.0)
            trace_rates = [
                point["hsp_segment_depth_per_second"]
                for point in hsp_trace_rows()
                if "hsp_segment_depth_per_second" in point
            ]
            self.assertGreater(max(trace_rates), 120.0)
        finally:
            controller.stop()

    def test_continuous_hsp_preserves_fractional_high_frequency_transport_points(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(70, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]
            fractional_depths = [
                point["x"]
                for point in points
                if abs(float(point["x"]) - round(float(point["x"]))) > 0.001
            ]
            same_integer_fractional_steps = [
                (left, right)
                for left, right in zip(points, points[1:])
                if int(round(float(left["x"]))) == int(round(float(right["x"])))
                and abs(float(left["x"]) - float(right["x"])) > 0.001
            ]

            self.assertTrue(intervals)
            self.assertLessEqual(
                max(intervals),
                int(
                    round(
                        (
                            CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS
                            + CONTINUOUS_HSP_MIN_POINT_INTERVAL_SECONDS
                        )
                        * 1000.0
                    )
                ),
            )
            self.assertTrue(fractional_depths)
            self.assertTrue(same_integer_fractional_steps)

            hsp_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            self.assertFalse(any("hsp_twitch_filtered_points" in point for point in hsp_points))
        finally:
            controller.stop()

    def test_continuous_hsp_slow_patterns_keep_fractional_sweep_points(self):
        """Regression: slow built-ins can spend many samples inside the same
        integer bucket. Those points still carry fractional movement and should
        be streamed so firmware can interpolate a continuous sweep instead of a
        sparse hold-then-step sequence.
        """

        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(
                MotionTarget(20, 50, 80, "tease"),
                source="unit test",
            )
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]
            same_integer_fractional_steps = [
                (left, right)
                for left, right in zip(points, points[1:])
                if int(round(float(left["x"]))) == int(round(float(right["x"])))
                and abs(float(left["x"]) - float(right["x"])) > 0.001
            ]

            self.assertTrue(intervals)
            self.assertLessEqual(
                max(intervals),
                int(
                    round(
                        (
                            CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS
                            + CONTINUOUS_HSP_MIN_POINT_INTERVAL_SECONDS
                        )
                        * 1000.0
                    )
                ),
            )
            self.assertTrue(same_integer_fractional_steps)

            hsp_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            self.assertFalse(any("hsp_twitch_filtered_points" in point for point in hsp_points))
        finally:
            controller.stop()

    def test_continuous_hsp_generated_streams_keep_dense_fractional_cadence(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(
                MotionTarget(25, 50, 80, "stroke"),
                source="unit test",
            )
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_appends) == 1), handy.stream_appends)

            points = sorted(
                handy.stream_starts[0]["points"] + handy.stream_appends[0]["points"],
                key=lambda point: point["t"],
            )
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]
            fractional_depths = [
                point["x"]
                for point in points
                if abs(float(point["x"]) - round(float(point["x"]))) > 0.001
            ]
            self.assertGreater(len(points), 60)
            self.assertTrue(intervals)
            self.assertLessEqual(
                max(intervals),
                int(
                    round(
                        (
                            CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS
                            + CONTINUOUS_HSP_MIN_POINT_INTERVAL_SECONDS
                        )
                        * 1000.0
                    )
                ),
            )
            self.assertTrue(fractional_depths)

            hsp_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            self.assertFalse(any("hsp_twitch_filtered_points" in point for point in hsp_points))
        finally:
            controller.stop()

    def test_continuous_hsp_generated_streams_preserve_same_integer_fractional_steps(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(70, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            for left, right in zip(points, points[1:]):
                if int(round(float(left["x"]))) == int(round(float(right["x"]))):
                    self.assertNotEqual(float(left["x"]), float(right["x"]))
                    break
            else:
                self.fail("expected at least one generated fractional step inside the same integer bucket")

            hsp_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            self.assertFalse(any("hsp_twitch_filtered_points" in point for point in hsp_points))
        finally:
            controller.stop()

    def test_continuous_hsp_tail_threshold_keeps_refill_margin(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(70, 50, 80, "milk"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            start = handy.stream_starts[0]
            points = start["points"]
            threshold = start["tail_point_threshold"]
            tail = start["tail_point_stream_index"]
            by_index = {point["stream_index"]: point for point in points}

            self.assertLess(threshold, tail - 2)
            self.assertIn(threshold, by_index)
            refill_margin_ms = points[-1]["t"] - by_index[threshold]["t"]
            self.assertGreaterEqual(
                refill_margin_ms + 1,
                int(round(CONTINUOUS_HSP_TAIL_THRESHOLD_LEAD_SECONDS * 1000.0)),
            )
        finally:
            controller.stop()

    def test_continuous_hsp_start_uses_short_buffer_then_appends_reserve(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(70, 50, 80, "milk"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            self.assertLessEqual(len(points), 60)
            self.assertLessEqual(len(points), 100)
            self.assertGreaterEqual(points[-1]["t"] - points[0]["t"], 2200)
            self.assertLessEqual(points[-1]["t"] - points[0]["t"], 2800)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_appends) == 1), handy.stream_appends)
            append_points = handy.stream_appends[0]["points"]
            self.assertGreaterEqual(append_points[-1]["t"] - points[0]["t"], 5000)

            hsp_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            self.assertTrue(hsp_points)
            append_trace = [point for point in hsp_points if point.get("hsp_batch") == "add"]
            self.assertTrue(append_trace)
            self.assertGreaterEqual(append_trace[-1]["hsp_buffer_after_command_ms"], 4400.0)
        finally:
            controller.stop()

    def test_continuous_hsp_stream_filters_authored_subsample_chatter(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(50, 50, 80, "flick"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]

            self.assertGreater(points[-1]["t"], 2000)
            self.assertGreaterEqual(
                min(intervals),
                int(round(CONTINUOUS_HSP_MIN_POINT_INTERVAL_SECONDS * 1000.0)),
            )
            self.assertLess(min(intervals), CONTINUOUS_SAMPLE_INTERVAL_SECONDS * 1000)
        finally:
            controller.stop()

    def test_continuous_hsp_fast_patterns_keep_shape_detail(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        plan = continuous_motion_plan("flutter")
        target = MotionTarget(70, 50, 80, "flutter")
        duration = sample_continuous_motion(plan, target, 0.0).effective_duration_seconds

        phase_points = controller._hsp_stream_phase_points(plan, duration)
        times = [point["phase"] * duration for point in phase_points]
        intervals = [right - left for left, right in zip(times, times[1:])]

        self.assertGreaterEqual(len(phase_points), 9)
        self.assertGreaterEqual(min(intervals) + 0.001, CONTINUOUS_HSP_MIN_POINT_INTERVAL_SECONDS)
        self.assertLessEqual(min(intervals), CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS)

    def test_continuous_hsp_milk_keeps_intermediate_points_at_high_speed(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        plan = continuous_motion_plan("milk")
        target = MotionTarget(80, 50, 80, "milk")
        duration = sample_continuous_motion(plan, target, 0.0).effective_duration_seconds

        phase_points = controller._hsp_stream_phase_points(plan, duration)
        samples = [
            sample_continuous_motion(plan, target, point["phase"] * duration).target
            for point in phase_points
        ]
        depth_steps = [
            abs(right.depth - left.depth)
            for left, right in zip(samples, samples[1:])
        ]

        self.assertGreaterEqual(len(phase_points), 18)
        self.assertLessEqual(max(depth_steps), 28.0)

    def test_continuous_hsp_generated_stream_preserves_fractional_integer_bucket_points(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(28, 50, 95, "milk"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            intervals = [
                right["t"] - left["t"]
                for left, right in zip(points, points[1:])
            ]
            rapid_duplicates = self.hsp_rapid_duplicate_integer_intervals(points)

            trace = controller.observability_snapshot()["trace"]
            self.assertTrue(any(point.get("hsp_duplicate_suppressed_points") for point in trace))
            self.assertTrue(rapid_duplicates)
            self.assertFalse(self.hsp_rapid_near_duplicate_intervals(points))
            self.assertLessEqual(max(intervals), 150)
        finally:
            controller.stop()

    def test_continuous_hsp_area_focus_coalesces_fractional_chatter(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        intent = IntentMatcher().parse("focus on the tip", controller.semantic_target())

        try:
            controller.apply_generated_target(intent.target, source="llm")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            intervals = [
                right["t"] - left["t"]
                for left, right in zip(points, points[1:])
            ]
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("continuous_plan_kind") == "area_focus",
            )

            self.assertFalse(self.hsp_rapid_duplicate_integer_intervals(points))
            self.assertFalse(self.hsp_rapid_near_duplicate_intervals(points))
            self.assertGreaterEqual(min(intervals), 80)
            self.assertLessEqual(max(intervals), 200)
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
            self.assertEqual(fast_tempo, {12.0})
            self.assertGreater(min(slow_cycle), max(fast_cycle) * 6.0)
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
        self.assertGreater(fast.tempo_scale, 3.8)
        self.assertLess(fast.tempo_scale, 4.1)
        self.assertGreater(fast.tempo_scale - slow.tempo_scale, 3.1)

    def test_high_continuous_speed_reaches_near_position_transport_cap(self):
        plan = continuous_motion_plan("stroke")
        target = MotionTarget(100, 50, 100, "stroke")
        points = continuous_plan_timed_points(plan, target, target_interval_seconds=0.05)

        segment_rates = [
            abs(right.target.depth - left.target.depth) / (right.at_seconds - left.at_seconds)
            for left, right in zip(points, points[1:])
            if right.at_seconds > left.at_seconds
        ]

        self.assertLessEqual(points[-1].at_seconds, 0.6)
        self.assertGreaterEqual(max(segment_rates), 400.0)

    def test_max_continuous_speed_compresses_long_fixed_pattern_cadence(self):
        plan = continuous_motion_plan("milk")
        target = MotionTarget(100, 50, 100, "milk")

        sample = sample_continuous_motion(plan, target, 0.0)

        self.assertLessEqual(sample.effective_duration_seconds, 0.75)
        self.assertAlmostEqual(sample.tempo_scale, 12.0)

    def test_turn_heavy_high_speed_patterns_scale_turn_ease_floor(self):
        stroke_mid = sample_continuous_motion(
            continuous_motion_plan("stroke"),
            MotionTarget(80, 50, 100, "stroke"),
            0.0,
        )
        stroke_max = sample_continuous_motion(
            continuous_motion_plan("stroke"),
            MotionTarget(100, 50, 100, "stroke"),
            0.0,
        )
        flutter_mid = sample_continuous_motion(
            continuous_motion_plan("flutter"),
            MotionTarget(80, 50, 100, "flutter"),
            0.0,
        )
        flutter_high = sample_continuous_motion(
            continuous_motion_plan("flutter"),
            MotionTarget(93, 50, 100, "flutter"),
            0.0,
        )
        flutter_max = sample_continuous_motion(
            continuous_motion_plan("flutter"),
            MotionTarget(100, 50, 100, "flutter"),
            0.0,
        )

        self.assertGreater(stroke_mid.effective_duration_seconds, stroke_max.effective_duration_seconds)
        self.assertGreater(flutter_mid.effective_duration_seconds, flutter_high.effective_duration_seconds)
        self.assertGreater(flutter_high.effective_duration_seconds, flutter_max.effective_duration_seconds)
        self.assertAlmostEqual(
            stroke_max.effective_duration_seconds,
            CONTINUOUS_HIGH_SPEED_TURN_EASE_MIN_CYCLE_SECONDS,
            places=3,
        )
        self.assertAlmostEqual(
            flutter_max.effective_duration_seconds,
            CONTINUOUS_HIGH_SPEED_MULTI_TURN_EASE_MIN_CYCLE_SECONDS,
            places=3,
        )
        self.assertLess(stroke_max.effective_duration_seconds, flutter_max.effective_duration_seconds)

    def test_closed_continuous_patterns_do_not_emit_flat_wrap_pause(self):
        plan = continuous_motion_plan("stroke")
        target = MotionTarget(100, 50, 100, "stroke")
        duration = sample_continuous_motion(plan, target, 0.0).effective_duration_seconds

        phase_points = continuous_plan_timed_phase_points(
            plan,
            duration,
            target_interval_seconds=CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS,
        )
        authored_tail = [point for point in phase_points if point.get("authored") and point["phase"] >= 0.9]

        self.assertEqual(len(authored_tail), 1)

    def test_speed_limit_refresh_replaces_active_continuous_stream_at_new_cap(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(80, 50, 80, "stroke"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            refreshed = controller.refresh_speed_limits(10, 80, 10, 100)

            self.assertTrue(refreshed)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            replacement = handy.stream_replacements[0]
            replacement_speeds = {
                round(point["intent_speed"])
                for point in replacement["points"]
                if not point.get("hsp_replacement_bridge")
            }
            self.assertEqual(replacement_speeds, {100})
            refresh_points = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("settings_speed_limit_refresh") is True
                and round(point.get("settings_next_target_speed", 0)) == 100,
            )
            self.assertTrue(refresh_points)
        finally:
            controller.stop()

    def test_speed_limit_refresh_updates_active_hamp_motion(self):
        handy = FakeHandy()
        handy._hamp_started = True
        controller = MotionController(handy, step_delay=0.16)
        controller._set_semantic_target(MotionTarget(80, 60, 70, "active hamp"))

        refreshed = controller.refresh_speed_limits(10, 80, 10, 100)

        self.assertTrue(refreshed)
        self.assertEqual(handy.moves[-1], (100, 60, 70))
        trace = controller.observability_snapshot()["trace"]
        self.assertTrue(trace[-1]["settings_speed_limit_refresh"])
        self.assertEqual(round(trace[-1]["settings_next_target_speed"]), 100)

    def test_reverse_orientation_does_not_flip_semantic_phase(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        plan = continuous_motion_plan("ramp")
        target = MotionTarget(50, 50, 80, "ramp")
        elapsed = 0.22

        forward = controller._sample_continuous_motion(plan, target, elapsed, sample_continuous_motion)
        controller.set_reverse_direction(True)
        reversed_sample = controller._sample_continuous_motion(plan, target, elapsed, sample_continuous_motion)

        self.assertAlmostEqual(reversed_sample.phase, forward.phase, places=4)
        self.assertAlmostEqual(reversed_sample.target.depth, forward.target.depth, places=3)

    def test_reverse_orientation_flips_direct_hamp_output_depth(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.set_reverse_direction(True)

        controller.apply_target(MotionTarget(40, 88, 24, "base focus"), smooth=False, source="unit test")

        self.assertEqual(handy.moves[-1], (40, 12, 24))
        self.assertEqual(controller.current_target().depth, 88)
        trace = controller.observability_snapshot()["trace"]
        self.assertEqual(trace[-1]["depth"], 88)
        self.assertEqual(trace[-1]["output_depth"], 12)

    def test_reverse_orientation_flips_position_output_depth(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.set_backend("position")
        controller.set_reverse_direction(True)

        controller.apply_position_frames(
            [PositionFrame(MotionTarget(40, 88, 24, "base focus"), delay_factor=0.0)],
            source="unit test",
        )

        self.assertEqual(handy.position_moves[-1][1], 12)
        self.assertEqual(controller.current_target().depth, 88)
        trace = controller.observability_snapshot()["trace"]
        self.assertEqual(trace[-1]["depth"], 88)
        self.assertEqual(trace[-1]["output_depth"], 12)

    def test_reverse_orientation_flips_hsp_area_focus_points(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        controller.set_reverse_direction(True)

        try:
            controller.apply_generated_target(MotionTarget(70, 90, 20, "plain chat"), source="llm")

            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            points = handy.stream_starts[0]["points"]
            self.assertLessEqual(max(point["x"] for point in points), 35)
            self.assertLess(min(point["x"] for point in points), 5)
            trace = controller.observability_snapshot()["trace"]
            self.assertTrue(any(point.get("output_depth", 100) <= 35 for point in trace), trace)
            self.assertTrue(any(point.get("depth", 0) >= 65 for point in trace), trace)
        finally:
            controller.stop()

    def test_reverse_orientation_flips_authored_hsp_points(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        controller.set_reverse_direction(True)

        try:
            applied = controller.apply_authored_actions(
                (
                    PatternAction(0, 20),
                    PatternAction(1000, 80),
                ),
                MotionTarget(50, 50, 100, "authored"),
                source="unit test",
            )

            self.assertTrue(applied)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            points = handy.stream_starts[0]["points"]
            self.assertEqual([round(point["x"]) for point in points[:2]], [80, 20])
            self.assertEqual([round(point["semantic_x"]) for point in points[:2]], [20, 80])
        finally:
            controller.stop()

    def test_hsp_area_focus_start_morph_respects_velocity_cap(self):
        handy = VelocityCappedStreamingFakeHandy(max_velocity=25)
        handy.last_relative_speed = 40
        handy.last_depth_pos = 50
        handy.last_stroke_range = 80
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_generated_target(MotionTarget(40, 90, 80, "base focus"), source="llm")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            hsp_points = self.wait_for_hsp_trace(controller)
            first = hsp_points[0]
            self.assertEqual(first["continuous_plan_kind"], "area_focus")
            self.assertTrue(first["morph_phase_frozen"])
            self.assertGreater(first["morph_speed_cap_ms"], CONTINUOUS_MAX_MORPH_SECONDS * 1000.0)

            morph_end_ms = first["hsp_play_start_ms"] + first["morph_ms"]
            transition_points = [
                point for point in handy.stream_starts[0]["points"] if point["t"] <= morph_end_ms
            ]
            self.assertGreater(len(transition_points), 3)
            self.assertEqual(
                {point["logical_t"] for point in transition_points[:-1]},
                {transition_points[0]["logical_t"]},
            )

            transition_rates = [
                abs(right["x"] - left["x"]) / ((right["t"] - left["t"]) / 1000.0)
                for left, right in zip(transition_points, transition_points[1:])
                if right["t"] > left["t"]
            ]
            self.assertTrue(transition_rates)
            self.assertLessEqual(max(transition_rates), handy.max_velocity + 1.0)
        finally:
            controller.stop()

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
            with (
                mock.patch("strokegpt.motion.CONTINUOUS_STREAM_INITIAL_BUFFER_SECONDS", 0.32),
                mock.patch("strokegpt.motion.CONTINUOUS_STREAM_TARGET_BUFFER_SECONDS", 0.32),
                mock.patch("strokegpt.motion.CONTINUOUS_STREAM_APPEND_THRESHOLD_SECONDS", 0.12),
            ):
                controller.apply_continuous_target(MotionTarget(80, 50, 80, "stroke"), source="unit test")
                self.assertTrue(self.wait_until(lambda: len(handy.stream_appends) >= 1, timeout=0.8), handy.stream_appends)

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

    def test_continuous_hsp_append_failure_stops_without_hdsp_fallback(self):
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

            failure_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
                and point.get("hsp_batch") == "add"
                and point.get("handy_ok") is False
            ]
            self.assertTrue(failure_points)
            self.assertEqual(handy.position_moves, [])
            self.assertTrue(self.wait_until(lambda: not controller.observability_snapshot()["playback_active"]))
        finally:
            controller.stop()

    def test_continuous_hsp_start_exception_records_failed_trace(self):
        handy = StartRaiseStreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(80, 50, 80, "stroke"), source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous_error") == "continuous_hsp_start_failed"
                        for point in controller.observability_snapshot()["trace"]
                    )
                ),
                controller.observability_snapshot()["trace"],
            )

            point = next(
                point
                for point in reversed(controller.observability_snapshot()["trace"])
                if point.get("continuous_error") == "continuous_hsp_start_failed"
            )
            self.assertFalse(point["handy_ok"])
            self.assertIn("start failed", point["handy_error"])
            self.assertEqual(handy.position_moves, [])
            self.assertTrue(self.wait_until(lambda: not controller.observability_snapshot()["playback_active"]))
        finally:
            controller.stop()

    def test_continuous_stream_command_skips_superseded_generation(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        lock_ready = threading.Event()
        release_lock = threading.Event()
        called = []

        def hold_command_lock():
            with controller._continuous_stream_command_lock:
                lock_ready.set()
                release_lock.wait(timeout=1)

        holder = threading.Thread(target=hold_command_lock)
        holder.start()
        self.assertTrue(lock_ready.wait(timeout=1))
        with controller._lock:
            stale_generation = controller._generation
            controller._generation += 1
        release_lock.set()

        sent, result = controller._send_continuous_stream_command(
            stale_generation,
            lambda: called.append(True) or True,
        )
        holder.join(timeout=1)

        self.assertFalse(sent)
        self.assertIsNone(result)
        self.assertEqual(called, [])

    def test_continuous_hsp_periodically_syncs_firmware_clock(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            with mock.patch("strokegpt.motion.CONTINUOUS_HSP_INITIAL_SYNC_SECONDS", 0.12):
                controller.apply_continuous_target(MotionTarget(80, 50, 80, "stroke"), source="unit test")
                self.assertTrue(self.wait_until(lambda: len(handy.stream_syncs) >= 1, timeout=0.8), handy.stream_syncs)

            first_sync = handy.stream_syncs[0]
            self.assertGreater(first_sync["current_time_ms"], 0)
            self.assertAlmostEqual(first_sync["filter"], 0.35)

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

    def test_continuous_hsp_replacement_stream_starts_at_buffered_phase_time(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(50, 50, 80, "stroke"), source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            time.sleep(0.22)
            controller.apply_continuous_target(MotionTarget(50, 56, 80, "stroke"), source="second")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "second"
                and point.get("hsp_batch") == "replace"
                and not point.get("hsp_replacement_bridge"),
            )

            replacement = handy.stream_replacements[0]
            start_time_ms = replacement["start_time_ms"]
            self.assertGreater(start_time_ms, 0)
            point_times = [point["t"] for point in replacement["points"]]
            self.assertIn(start_time_ms, point_times)
            self.assertTrue(any(point_time < start_time_ms for point_time in point_times))

            second_points = [
                point
                for point in trace
                if point.get("continuous_schema") == "hsp"
                and point.get("source") == "second"
                and point.get("hsp_batch") == "replace"
            ]
            self.assertTrue(second_points)
            self.assertTrue(second_points[0]["hsp_replacement_bridge"])
            self.assertEqual(second_points[0]["handy_path"], "hsp/add")
            first_replacement_point = next(
                point for point in second_points if not point.get("hsp_replacement_bridge")
            )
            self.assertGreater(first_replacement_point["hsp_replacement_lead_ms"], 0.0)
            self.assertAlmostEqual(
                first_replacement_point["hsp_point_time_ms"],
                first_replacement_point["hsp_play_start_ms"],
                delta=1.0,
            )
        finally:
            controller.stop()

    def test_continuous_hsp_replacement_uses_bounded_latency_lead(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(50, 50, 80, "stroke"), source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            handy._last_command["elapsed_ms"] = 700.0

            controller.apply_continuous_target(MotionTarget(50, 56, 80, "stroke"), source="second")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "second"
                and point.get("hsp_batch") == "replace",
            )

            second_points = [
                point
                for point in trace
                if point.get("continuous_schema") == "hsp"
                and point.get("source") == "second"
                and point.get("hsp_batch") == "replace"
            ]
            self.assertTrue(second_points)
            self.assertGreater(second_points[0]["hsp_replacement_lead_ms"], 0.0)
            self.assertEqual(second_points[0]["hsp_replacement_kind"], "drift")
            self.assertLessEqual(
                second_points[0]["hsp_replacement_lead_ms"],
                CONTINUOUS_HSP_REPLACEMENT_MAX_LEAD_SECONDS * 1000.0,
            )
            replacement = handy.stream_replacements[0]
            point_times = [point["t"] for point in replacement["points"]]
            self.assertIn(replacement["start_time_ms"], point_times)
            self.assertTrue(any(point_time < replacement["start_time_ms"] for point_time in point_times))
        finally:
            controller.stop()

    def test_continuous_hsp_same_pattern_speed_update_uses_speed_replacement_lead(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        plan = continuous_motion_plan("stroke")
        first = MotionTarget(20, 50, 80, "stroke")
        second = MotionTarget(85, 50, 80, "stroke")
        old_duration = sample_continuous_motion(plan, first, 0.0).effective_duration_seconds
        new_duration = sample_continuous_motion(plan, second, 0.0).effective_duration_seconds

        try:
            controller.apply_continuous_target(first, source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            controller._observe_hsp_command_seconds(2.296)

            controller.apply_continuous_target(second, source="second")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "second"
                and point.get("hsp_batch") == "replace",
            )

            replacement_points = [
                point
                for point in trace
                if point.get("continuous_schema") == "hsp"
                and point.get("source") == "second"
                and point.get("hsp_batch") == "replace"
            ]
            self.assertTrue(replacement_points)
            self.assertEqual(replacement_points[0]["hsp_replacement_kind"], "speed")
            self.assertGreaterEqual(replacement_points[0]["hsp_replacement_lead_ms"], 2600.0)
            self.assertLess(replacement_points[0]["hsp_replacement_lead_ms"], 3000.0)
            first_replacement_point = next(
                point for point in replacement_points if not point.get("hsp_replacement_bridge")
            )
            self.assertLess(first_replacement_point["effective_cycle_ms"], old_duration * 1000.0)
            self.assertAlmostEqual(
                first_replacement_point["effective_cycle_ms"],
                new_duration * 1000.0,
                delta=1.0,
            )
        finally:
            controller.stop()

    def test_continuous_hsp_replacement_lead_uses_controller_observed_command_latency(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(50, 50, 80, "stroke"), source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_appends) == 1), handy.stream_appends)
            handy._last_command["elapsed_ms"] = 5.0
            controller._observe_hsp_command_seconds(2.296)

            controller.apply_continuous_target(MotionTarget(50, 56, 80, "stroke"), source="second")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "second"
                and point.get("hsp_batch") == "replace",
            )

            second_points = [
                point
                for point in trace
                if point.get("continuous_schema") == "hsp"
                and point.get("source") == "second"
                and point.get("hsp_batch") == "replace"
            ]
            self.assertTrue(second_points)
            self.assertEqual(second_points[0]["hsp_replacement_kind"], "drift")
            self.assertGreaterEqual(second_points[0]["hsp_replacement_lead_ms"], 2700.0)
            self.assertGreaterEqual(second_points[0]["hsp_replacement_lead_ms"], 3200.0)
            self.assertEqual(second_points[0]["hsp_first_point_late_estimate_ms"], 0.0)
            replacement = handy.stream_replacements[0]
            point_times = [point["t"] for point in replacement["points"]]
            self.assertIn(replacement["start_time_ms"], point_times)
            self.assertTrue(any(point_time < replacement["start_time_ms"] for point_time in point_times))
        finally:
            controller.stop()

    def test_continuous_hsp_replacement_keeps_latency_lead_when_old_buffer_is_low(self):
        handy = StreamingFakeHandy()
        handy._hsp_streaming = True
        controller = MotionController(handy, step_delay=0.16)
        old_plan = continuous_motion_plan("stroke")
        new_plan = continuous_motion_plan("wave")
        old_target = MotionTarget(80, 50, 80, "stroke")
        new_target = MotionTarget(80, 50, 80, "wave")
        stream_offset_seconds = 180.0
        old_state = ContinuousPhaseState(
            key=controller._continuous_plan_key(old_plan),
            generation=controller._generation,
            started_at=time.monotonic(),
            offset_seconds=stream_offset_seconds,
            stream_offset_seconds=stream_offset_seconds,
            stream_tail_seconds=stream_offset_seconds + 0.18,
            phase_rate=1.0,
            plan=old_plan,
            target=old_target,
        )

        result = controller._run_continuous_stream_plan(
            new_plan,
            new_target,
            "unit test",
            controller._generation,
            time.monotonic(),
            0.0,
            stream_offset_seconds,
            True,
            False,
            MotionTarget(80, 50, 80, "current"),
            old_state,
            finite_cycles=0.04,
        )

        self.assertTrue(result)
        self.assertEqual(len(handy.stream_replacements), 1)
        trace = [
            point
            for point in controller.observability_snapshot()["trace"]
            if point.get("continuous_schema") == "hsp"
            and point.get("source") == "unit test"
            and point.get("hsp_batch") == "replace"
        ]
        self.assertTrue(trace)
        self.assertTrue(any(point.get("hsp_replacement_bridge") for point in trace))
        first_replacement_point = next(point for point in trace if not point.get("hsp_replacement_bridge"))
        self.assertEqual(first_replacement_point["hsp_replacement_kind"], "intent")
        self.assertGreaterEqual(first_replacement_point["hsp_replacement_lead_ms"], 800.0)
        self.assertAlmostEqual(
            first_replacement_point["hsp_point_time_ms"],
            first_replacement_point["hsp_play_start_ms"],
            delta=1.0,
        )

    def test_continuous_hsp_append_threshold_scales_with_observed_command_latency(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)

        controller._observe_hsp_command_seconds(2.5)

        threshold = controller._continuous_append_threshold_seconds()
        self.assertGreater(threshold, CONTINUOUS_STREAM_APPEND_THRESHOLD_SECONDS)
        self.assertGreaterEqual(threshold, 3.6)

    def test_continuous_hsp_append_threshold_avoids_normal_latency_churn(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)

        controller._observe_hsp_command_seconds(1.4)

        threshold = controller._continuous_append_threshold_seconds()
        self.assertGreaterEqual(threshold, 2.5)
        self.assertLess(threshold, 3.0)

    def test_continuous_hsp_latency_spike_decays_after_next_normal_sample(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)

        controller._observe_hsp_command_seconds(4.0)
        self.assertGreaterEqual(controller._recent_hsp_command_latency_seconds(), 4.0)

        controller._observe_hsp_command_seconds(0.12)
        self.assertLess(controller._recent_hsp_command_latency_seconds(), 1.0)

    def test_continuous_hsp_append_threshold_uses_peak_latency_spike(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)

        controller._observe_hsp_command_seconds(4.0)
        controller._observe_hsp_command_seconds(0.12)

        self.assertLess(controller._recent_hsp_command_latency_seconds(), 1.0)
        self.assertGreaterEqual(controller._continuous_append_threshold_seconds(), 5.0)

    def test_continuous_hsp_buffer_expands_without_sparsening_points(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)

        controller._observe_hsp_command_seconds(5.0)

        target_buffer = controller._continuous_target_buffer_seconds()
        threshold = controller._continuous_append_threshold_seconds()
        point_interval = controller._continuous_hsp_point_interval_seconds()

        self.assertGreaterEqual(target_buffer, CONTINUOUS_STREAM_TARGET_BUFFER_SECONDS)
        self.assertGreaterEqual(threshold, CONTINUOUS_STREAM_APPEND_THRESHOLD_SECONDS)
        self.assertEqual(point_interval, CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS)

    def test_late_risk_hsp_append_requests_resume(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        controller._observe_hsp_command_seconds(4.0)

        try:
            controller.apply_continuous_target(MotionTarget(70, 50, 80, "milk"), source="unit test")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_appends) == 1), handy.stream_appends)

            self.assertTrue(handy.stream_appends[0]["force_resume"])
            add_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp" and point.get("hsp_batch") == "add"
            ]
            self.assertTrue(add_points)
            self.assertTrue(add_points[-1]["hsp_append_force_resume"])
        finally:
            controller.stop()

    def test_continuous_area_focus_uses_longer_lower_density_hsp_buffer(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        plan = controller._hsp_area_focus_plan(MotionTarget(17, 50, 80, "llm+middle"))

        self.assertGreaterEqual(
            controller._continuous_target_buffer_seconds(plan),
            CONTINUOUS_HSP_AREA_FOCUS_TARGET_BUFFER_SECONDS,
        )
        self.assertEqual(
            controller._continuous_hsp_point_interval_seconds(plan),
            CONTINUOUS_HSP_AREA_FOCUS_POINT_INTERVAL_SECONDS,
        )

    def test_continuous_middle_area_focus_initial_play_keeps_hsp_reserve(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        target = MotionSanitizer().from_llm_move(
            {"zone": "middle", "sp": 17, "dp": 71, "rng": 80},
            MotionTarget(35, 45, 55),
        )

        try:
            controller.apply_generated_target(target, source="llm")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]
            self.assertLessEqual(len(points), CONTINUOUS_STREAM_MAX_POINTS_PER_COMMAND)
            self.assertGreaterEqual(points[-1]["t"] - points[0]["t"], 8500)
            self.assertGreaterEqual(min(intervals), 80)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "llm"
                and point.get("hsp_batch") == "play"
                and point.get("continuous_plan_kind") == "area_focus",
            )
            play_points = [point for point in trace if point.get("hsp_batch") == "play"]
            self.assertTrue(play_points)
            self.assertEqual({point.get("continuous_area_focus_zone") for point in play_points}, {"middle"})
            self.assertEqual({point.get("continuous_area_focus_transport_depth") for point in play_points}, {50.0})
            self.assertGreaterEqual(play_points[-1]["hsp_target_buffer_ms"], 9000.0)
            self.assertGreaterEqual(play_points[-1]["hsp_buffer_after_command_ms"], 8400.0)
        finally:
            controller.stop()

    def test_continuous_duplicate_area_focus_target_keeps_active_stream(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        sanitizer = MotionSanitizer()
        current = MotionTarget(35, 45, 55)
        first = sanitizer.from_llm_move(
            {"zone": "middle", "sp": 17, "dp": 71, "rng": 80},
            current,
        )
        duplicate = sanitizer.from_llm_move(
            {"zone": "middle", "sp": 17, "dp": 40, "rng": 46},
            current,
        )

        try:
            controller.apply_generated_target(first, source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            controller.apply_generated_target(duplicate, source="duplicate")

            self.assertFalse(
                self.wait_until(lambda: len(handy.stream_replacements) > 0, timeout=0.25),
                handy.stream_replacements,
            )
            self.assertEqual(len(handy.stream_starts), 1)
        finally:
            controller.stop()

    def test_continuous_hsp_replacement_uses_default_latency_reserve(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(50, 50, 80, "stroke"), source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            controller.apply_continuous_target(MotionTarget(70, 50, 80, "wave"), source="second")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)

            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "second"
                and point.get("hsp_batch") == "replace",
            )
            replacement_points = [
                point
                for point in trace
                if point.get("continuous_schema") == "hsp"
                and point.get("source") == "second"
                and point.get("hsp_batch") == "replace"
            ]
            self.assertTrue(replacement_points)
            self.assertEqual(replacement_points[0]["hsp_replacement_kind"], "intent")
            self.assertGreaterEqual(replacement_points[0]["hsp_replacement_lead_ms"], 800.0)
            self.assertLess(replacement_points[0]["hsp_replacement_lead_ms"], 1100.0)
        finally:
            controller.stop()

    def test_continuous_transition_phase_starts_new_pattern_near_current_depth(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        plan = continuous_motion_plan("stroke")
        target = MotionTarget(50, 50, 80, "stroke")
        start_target = MotionTarget(50, 90, 80, "current high point")
        duration = sample_continuous_motion(plan, target, 0.0).effective_duration_seconds

        transition_seconds = controller._continuous_transition_phase_seconds(
            plan,
            target,
            start_target,
            duration,
            sample_continuous_motion,
        )

        transition_sample = sample_continuous_motion(plan, target, transition_seconds)
        zero_sample = sample_continuous_motion(plan, target, 0.0)
        self.assertLess(
            abs(transition_sample.target.depth - start_target.depth),
            abs(zero_sample.target.depth - start_target.depth),
        )

    def test_continuous_replacement_morph_uses_selected_phase_sample(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        plan = continuous_motion_plan("stroke")
        target = MotionTarget(50, 50, 80, "stroke")
        start_target = MotionTarget(50, 90, 80, "current high point")
        duration = sample_continuous_motion(plan, target, 0.0).effective_duration_seconds
        selected_seconds = controller._continuous_transition_phase_seconds(
            plan,
            target,
            start_target,
            duration,
            sample_continuous_motion,
        )
        selected_morph = controller._continuous_morph_seconds(
            start_target,
            sample_continuous_motion(plan, target, selected_seconds).target,
        )
        stale_morph = controller._continuous_morph_seconds(
            start_target,
            sample_continuous_motion(plan, target, 0.0).target,
        )
        self.assertNotAlmostEqual(selected_morph, stale_morph, places=2)

        result = controller._run_continuous_stream_plan(
            plan,
            target,
            "unit test",
            controller._generation,
            time.monotonic(),
            0.0,
            0.0,
            True,
            False,
            start_target,
            None,
            finite_cycles=0.04,
        )

        self.assertTrue(result)
        hsp_points = [
            point
            for point in controller.observability_snapshot()["trace"]
            if point.get("continuous_schema") == "hsp"
        ]
        self.assertTrue(hsp_points)
        self.assertAlmostEqual(hsp_points[0]["phase_offset_ms"], selected_seconds * 1000.0, delta=1.0)
        self.assertAlmostEqual(hsp_points[0]["morph_ms"], selected_morph * 1000.0, delta=1.0)

    def test_continuous_replacement_morph_uses_predicted_stream_start_target(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        old_plan = continuous_motion_plan("stroke")
        new_plan = continuous_motion_plan("wave")
        old_target = MotionTarget(50, 50, 80, "stroke")
        new_target = MotionTarget(50, 50, 80, "wave")
        apply_start = sample_continuous_motion(old_plan, old_target, 0.0).target
        old_duration = sample_continuous_motion(old_plan, old_target, 0.0).effective_duration_seconds
        replacement_lead = old_duration * 0.25
        predicted_start = sample_continuous_motion(old_plan, old_target, replacement_lead).target
        self.assertGreater(abs(predicted_start.depth - apply_start.depth), 5.0)
        old_state = ContinuousPhaseState(
            key=controller._continuous_plan_key(old_plan),
            generation=controller._generation,
            started_at=time.monotonic(),
            offset_seconds=0.0,
            stream_offset_seconds=0.0,
            phase_rate=1.0,
            plan=old_plan,
            target=old_target,
        )

        with mock.patch.object(
            controller,
            "_continuous_replacement_lead_seconds",
            return_value=replacement_lead,
        ):
            result = controller._run_continuous_stream_plan(
                new_plan,
                new_target,
                "unit test",
                controller._generation,
                time.monotonic(),
                0.0,
                0.0,
                True,
                False,
                apply_start,
                old_state,
                finite_cycles=0.04,
            )

        self.assertTrue(result)
        hsp_points = [
            point
            for point in controller.observability_snapshot()["trace"]
            if point.get("continuous_schema") == "hsp"
        ]
        self.assertTrue(hsp_points)
        self.assertTrue(any(point.get("hsp_replacement_bridge") for point in hsp_points))
        first = next(point for point in hsp_points if not point.get("hsp_replacement_bridge"))
        expected_phase = controller._continuous_transition_phase_seconds(
            new_plan,
            new_target,
            predicted_start,
            sample_continuous_motion(new_plan, new_target, 0.0).effective_duration_seconds,
            sample_continuous_motion,
        )
        self.assertEqual(first["morph_start_source"], "predicted_active_stream")
        self.assertAlmostEqual(first["morph_start_depth"], predicted_start.depth, delta=0.1)
        self.assertAlmostEqual(first["depth"], predicted_start.depth, delta=0.5)
        self.assertAlmostEqual(
            first["morph_start_delta_from_apply_depth"],
            predicted_start.depth - apply_start.depth,
            delta=0.1,
        )
        self.assertAlmostEqual(first["morph_start_prediction_lead_ms"], replacement_lead * 1000.0, delta=1.0)
        self.assertAlmostEqual(first["hsp_selected_phase_ms"], expected_phase * 1000.0, delta=1.0)

    def test_continuous_backend_keeps_sample_speed_out_of_current_intent(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0)
        target = MotionTarget(20, 50, 80, "stroke")

        try:
            controller.apply_continuous_target(target, source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous_schema") == "hsp"
                        and point.get("sample_speed", 0) > target.speed
                        for point in controller.observability_snapshot()["trace"]
                    )
                ),
                controller.observability_snapshot()["trace"],
            )

            self.assertEqual(round(controller.current_target().speed), 20)
            points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            ]
            self.assertTrue(points)
            self.assertTrue(all(point["intent_speed"] == 20 for point in points))
            self.assertTrue(any(point["sample_speed"] > point["intent_speed"] for point in points))
            self.assertLessEqual(max(point["sample_speed"] for point in points), 40)
        finally:
            controller.stop()

    def test_continuous_low_speed_is_not_smoothed_from_previous_fast_state(self):
        handy = StreamingFakeHandy()
        handy.last_relative_speed = 80
        handy.last_depth_pos = 50
        handy.last_stroke_range = 80
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(20, 50, 80, "stroke"), source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous_schema") == "hsp"
                        for point in controller.observability_snapshot()["trace"]
                    )
                ),
                controller.observability_snapshot()["trace"],
            )

            first_point = next(
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp"
            )
            self.assertEqual(first_point["intent_speed"], 20)
            self.assertLessEqual(first_point["sample_speed"], 40)
            self.assertEqual({round(point["intent_speed"]) for point in handy.stream_starts[0]["points"]}, {20})
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

    def test_continuous_hsp_trace_uses_intent_tempo_without_velocity_budget(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(20, 50, 80, "stroke"), source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous_schema") == "hsp"
                        for point in controller.observability_snapshot()["trace"]
                    )
                ),
                controller.observability_snapshot()["trace"],
            )

            point = next(
                point
                for point in reversed(controller.observability_snapshot()["trace"])
                if point.get("continuous_schema") == "hsp"
            )
            self.assertEqual(handy.velocity_intervals, [])
            self.assertAlmostEqual(point["sample_tempo_scale"], 0.7)
            self.assertEqual(point["hsp_transport_time_scale"], 1.0)
        finally:
            controller.stop()

    def test_continuous_without_hsp_records_unavailable_instead_of_hdsp_fallback(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_continuous_target(MotionTarget(80, 50, 80, "flick"), source="unit test")
            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous_schema") == "hsp_unavailable"
                        for point in controller.observability_snapshot()["trace"]
                    )
                ),
                controller.observability_snapshot()["trace"],
            )

            self.assertEqual(handy.position_moves, [])
            self.assertEqual(handy.moves, [])
            point = next(
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp_unavailable"
            )
            self.assertEqual(point["deprecated_fallback"], "hdsp")
        finally:
            controller.stop()

    def test_generated_pattern_falls_back_to_live_move_when_hsp_is_unavailable(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)

        try:
            controller.apply_generated_target(MotionTarget(80, 50, 80, "flick"), source="unit test")

            trace = controller.observability_snapshot()["trace"]
            self.assertTrue(
                any(point.get("continuous_schema") == "hsp_unavailable" for point in trace),
                trace,
            )
            self.assertTrue(handy.moves)
            self.assertEqual(handy.moves[-1], (80, 50, 80))
            self.assertEqual(handy.position_moves, [])
        finally:
            controller.stop()

    def test_continuous_backend_preserves_same_pattern_phase_on_update(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0)
        intent = IntentMatcher().parse("milk me", controller.current_target())

        try:
            controller.apply_generated_target(intent.target, source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            time.sleep(0.05)

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
                        and point.get("hsp_batch") == "replace"
                        for point in controller.observability_snapshot()["trace"]
                    )
                )
            )

            second_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp" and point.get("source") == "second"
            ]
            self.assertTrue(second_points)
            self.assertGreater(second_points[0]["phase_offset_ms"], 0)
            self.assertLess(second_points[0]["phase_offset_ms"], second_points[0]["cycle_ms"])
        finally:
            controller.stop()

    def test_continuous_backend_preserves_phase_ratio_on_same_pattern_speed_update(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0)
        plan = continuous_motion_plan("milk")
        first = MotionTarget(80, 50, 82, "milk")
        second = MotionTarget(20, 50, 82, "milk")
        old_duration = sample_continuous_motion(plan, first, 0.0).effective_duration_seconds

        try:
            controller.apply_generated_target(first, source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            with (
                mock.patch("strokegpt.motion.CONTINUOUS_HSP_INTENT_REPLACEMENT_LEAD_SECONDS", 1.0),
                mock.patch("strokegpt.motion.CONTINUOUS_HSP_INTENT_REPLACEMENT_LATENCY_PADDING_SECONDS", 1.0),
            ):
                controller.apply_generated_target(second, source="second")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)

            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "second"
                and not point.get("hsp_replacement_bridge"),
            )
            second_points = [
                point
                for point in trace
                if point.get("continuous_schema") == "hsp" and point.get("source") == "second"
            ]
            self.assertTrue(second_points)
            self.assertTrue(any(point.get("hsp_replacement_bridge") for point in second_points))
            first_point = next(point for point in second_points if not point.get("hsp_replacement_bridge"))
            replacement_lead = first_point["hsp_replacement_lead_ms"] / 1000.0
            expected_phase = replacement_lead / old_duration

            self.assertEqual(first_point["hsp_replacement_kind"], "speed")
            self.assertAlmostEqual(first_point["sample_phase"], expected_phase, delta=0.04)
            self.assertAlmostEqual(first_point["output_depth"], first_point["morph_start_depth"], delta=2.0)
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

    def test_continuous_morph_amount_starts_moving_without_flat_spot(self):
        controller = MotionController(FakeHandy(), step_delay=0)

        self.assertEqual(controller._continuous_morph_amount(0.0), 0.0)
        self.assertGreater(controller._continuous_morph_amount(0.2), 0.1)
        self.assertEqual(controller._continuous_morph_amount(1.0), 1.0)

    def test_continuous_trace_includes_supplied_mode_metadata(self):
        handy = StreamingFakeHandy()
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
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "freestyle planner",
            )

            point = next(
                point
                for point in trace
                if point.get("continuous_schema") == "hsp" and point.get("source") == "freestyle planner"
            )
            self.assertEqual(point["mode"], "freestyle")
            self.assertEqual(point["freestyle_pattern_id"], "stroke")
            self.assertEqual(point["freestyle_planner_sleep_ms"], 1200.0)
            self.assertEqual(point["sample_index"], 0)
        finally:
            controller.stop()

    def test_continuous_backend_routes_plain_chat_targets_through_hsp_area_focus(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_generated_target(MotionTarget(70, 90, 80, "plain chat"), source="llm")

            self.assertEqual(handy.moves, [])
            self.assertEqual(handy.position_moves, [])
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            points = handy.stream_starts[0]["points"]
            self.assertGreater(max(point["x"] for point in points), 95)
            self.assertLess(min(point["x"] for point in points), 55)
            self.assertTrue(
                self.wait_until(
                    lambda: any(
                        point.get("continuous_schema") == "hsp"
                        and point.get("continuous_plan_kind") == "area_focus"
                        and point.get("continuous_area_focus")
                        for point in controller.observability_snapshot()["trace"]
                    )
                ),
                controller.observability_snapshot()["trace"],
            )
        finally:
            controller.stop()

    def test_hsp_area_focus_mid_speed_changes_affect_effective_cycle(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        slow = MotionTarget(30, 50, 82, "freestyle flow")
        mid = MotionTarget(60, 50, 82, "freestyle flow")
        fast = MotionTarget(70, 50, 82, "freestyle flow")
        slow_plan = controller._hsp_area_focus_plan(slow)
        mid_plan = controller._hsp_area_focus_plan(mid)
        fast_plan = controller._hsp_area_focus_plan(fast)

        slow_sample = sample_continuous_motion(slow_plan, slow, 0.0)
        mid_sample = sample_continuous_motion(mid_plan, mid, 0.0)
        fast_sample = sample_continuous_motion(fast_plan, fast, 0.0)

        self.assertGreater(slow_sample.effective_duration_seconds, mid_sample.effective_duration_seconds)
        self.assertGreater(mid_sample.effective_duration_seconds, fast_sample.effective_duration_seconds)
        self.assertGreater(slow_sample.effective_duration_seconds, fast_sample.effective_duration_seconds)
        self.assertLess(fast_sample.effective_duration_seconds, 0.6)

    def test_generated_area_focus_trace_includes_supplied_mode_metadata(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_generated_target(
                MotionTarget(54, 50, 78, "freestyle flow"),
                source="freestyle planner",
                trace_metadata={
                    "mode": "freestyle",
                    "freestyle_pattern_id": "sway",
                    "freestyle_fixed_pattern_transport": "area_focus",
                    "sample_index": 999,
                },
            )

            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("continuous_plan_kind") == "area_focus"
                and point.get("source") == "freestyle planner",
            )
            point = next(
                point
                for point in trace
                if point.get("continuous_schema") == "hsp"
                and point.get("continuous_plan_kind") == "area_focus"
                and point.get("source") == "freestyle planner"
            )
            self.assertEqual(point["mode"], "freestyle")
            self.assertEqual(point["freestyle_pattern_id"], "sway")
            self.assertEqual(point["freestyle_fixed_pattern_transport"], "area_focus")
            self.assertEqual(point["sample_index"], 0)
        finally:
            controller.stop()

    def test_freestyle_area_focus_replacement_bridges_transition_lead(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_generated_target(
                MotionTarget(54, 50, 78, "freestyle flow"),
                source="freestyle planner",
                trace_metadata={"mode": "freestyle", "freestyle_pattern_id": "sway"},
            )
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            time.sleep(0.12)
            controller.apply_generated_target(
                MotionTarget(62, 58, 70, "freestyle flow"),
                source="freestyle planner",
                trace_metadata={"mode": "freestyle", "freestyle_pattern_id": "wave"},
            )

            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            replacement = handy.stream_replacements[0]
            start_time_ms = replacement["start_time_ms"]
            point_times = [point["t"] for point in replacement["points"]]
            self.assertTrue(any(point_time < start_time_ms for point_time in point_times))
            self.assertIn(start_time_ms, point_times)

            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("hsp_replacement_bridge")
                and point.get("source") == "freestyle planner"
                and point.get("mode") == "freestyle",
            )
            bridge_points = [
                point
                for point in trace
                if point.get("hsp_replacement_bridge")
                and point.get("source") == "freestyle planner"
            ]
            self.assertTrue(bridge_points)
            self.assertLess(bridge_points[0]["hsp_point_time_ms"], bridge_points[0]["hsp_play_start_ms"])
        finally:
            controller.stop()

    def test_freestyle_area_focus_replacement_bridge_skips_stale_apply_time_points(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_generated_target(
                MotionTarget(54, 50, 78, "freestyle flow"),
                source="freestyle planner",
                trace_metadata={"mode": "freestyle", "freestyle_pattern_id": "sway"},
            )
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            controller._observe_hsp_command_seconds(0.42)

            controller.apply_generated_target(
                MotionTarget(62, 58, 70, "freestyle flow"),
                source="freestyle planner",
                trace_metadata={"mode": "freestyle", "freestyle_pattern_id": "wave"},
            )

            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            replacement = handy.stream_replacements[0]
            bridge_points = [point for point in replacement["points"] if point.get("hsp_replacement_bridge")]
            self.assertTrue(bridge_points)

            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("hsp_replacement_bridge")
                and point.get("source") == "freestyle planner"
                and point.get("freestyle_pattern_id") == "wave",
                timeout=2.0,
            )
            first_bridge = next(
                point
                for point in trace
                if point.get("hsp_replacement_bridge")
                and point.get("source") == "freestyle planner"
                and point.get("freestyle_pattern_id") == "wave"
            )
            hsp_clock_start_ms = first_bridge["hsp_play_start_ms"] - first_bridge["hsp_replacement_lead_ms"]

            self.assertLessEqual(
                bridge_points[0]["t"] - hsp_clock_start_ms,
                (CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS * 1000.0) + 5.0,
            )
            self.assertGreaterEqual(bridge_points[1]["t"] - hsp_clock_start_ms, 420.0)
            self.assertLess(bridge_points[0]["t"], replacement["start_time_ms"])
            self.assertAlmostEqual(first_bridge["hsp_replacement_bridge_start_ms"], bridge_points[0]["t"], delta=1.0)
            self.assertLessEqual(first_bridge["hsp_replacement_latency_bridge_start_ms"], bridge_points[1]["t"])
            self.assertAlmostEqual(
                first_bridge["hsp_replacement_latency_bridge_start_ms"] - hsp_clock_start_ms,
                420.0,
                delta=1.0,
            )
            self.assertGreaterEqual(first_bridge["hsp_replacement_bridge_latency_ms"], 420.0)
        finally:
            controller.stop()

    def test_area_focus_replacement_batch_keeps_post_morph_reserve(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            controller.apply_generated_target(MotionTarget(54, 50, 78, "freestyle flow"), source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            controller.apply_generated_target(MotionTarget(62, 58, 70, "freestyle flow"), source="second")

            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "second"
                and point.get("hsp_batch") == "replace"
                and not point.get("hsp_replacement_bridge"),
            )
            replacement_points = [
                point
                for point in trace
                if point.get("source") == "second"
                and point.get("hsp_batch") == "replace"
                and not point.get("hsp_replacement_bridge")
            ]
            self.assertTrue(replacement_points)
            first_replacement = replacement_points[0]

            self.assertGreaterEqual(first_replacement["hsp_replacement_bridge_interval_ms"], 400.0)
            self.assertGreaterEqual(first_replacement["hsp_batch_post_start_buffer_ms"], 7000.0)
            self.assertGreater(first_replacement["hsp_batch_post_morph_buffer_ms"], 5000.0)
        finally:
            controller.stop()

    def test_duplicate_area_focus_target_recovers_paused_hsp_stream(self):
        handy = PausedHspStreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        target = MotionTarget(54, 50, 78, "freestyle flow")

        try:
            controller.apply_generated_target(target, source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            handy.hsp_state = {
                "play_state": "paused",
                "current_time_ms": 900,
                "last_point_time_ms": 4800,
            }
            controller.apply_generated_target(target, source="keepalive")

            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "keepalive"
                and point.get("hsp_batch") == "replace",
            )
            self.assertTrue(any(point.get("hsp_replacing_active_stream") for point in trace))
        finally:
            controller.stop()

    def test_freestyle_area_focus_replacement_preserves_phase_when_duration_changes(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        first = MotionTarget(20, 50, 84, "freestyle flow")
        second = MotionTarget(80, 62, 36, "freestyle flow")
        first_clean, _first_zone = controller._area_focus_transport_target(first)
        second_clean, _second_zone = controller._area_focus_transport_target(second)
        old_plan = controller._hsp_area_focus_plan(first_clean)
        new_plan = controller._hsp_area_focus_plan(second_clean)
        self.assertNotEqual(round(old_plan.duration_seconds, 3), round(new_plan.duration_seconds, 3))
        old_duration = sample_continuous_motion(old_plan, first_clean, 0.0).effective_duration_seconds

        try:
            controller.apply_generated_target(
                first,
                source="freestyle planner",
                trace_metadata={"mode": "freestyle", "freestyle_pattern_id": "slow-wide"},
            )
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            with mock.patch("strokegpt.motion.CONTINUOUS_HSP_INTENT_REPLACEMENT_LEAD_SECONDS", 1.0):
                controller.apply_generated_target(
                    second,
                    source="freestyle planner",
                    trace_metadata={"mode": "freestyle", "freestyle_pattern_id": "fast-tight"},
                )

            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            second_points = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("source") == "freestyle planner"
                and point.get("freestyle_pattern_id") == "fast-tight"
                and not point.get("hsp_replacement_bridge"),
            )
            second_points = [
                point
                for point in second_points
                if point.get("source") == "freestyle planner"
                and point.get("freestyle_pattern_id") == "fast-tight"
            ]
            self.assertTrue(any(point.get("hsp_replacement_bridge") for point in second_points))
            first_point = next(point for point in second_points if not point.get("hsp_replacement_bridge"))
            expected_phase = ((first_point["hsp_replacement_lead_ms"] / 1000.0) / old_duration) % 1.0

            self.assertEqual(first_point["hsp_replacement_kind"], "speed")
            self.assertAlmostEqual(first_point["sample_phase"], expected_phase, delta=0.08)
            self.assertAlmostEqual(first_point["output_depth"], first_point["morph_start_depth"], delta=2.0)
        finally:
            controller.stop()

    def test_continuous_backend_routes_regional_focus_program_through_hsp_area_focus(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        intent = IntentMatcher().parse("focus on the base", controller.current_target())

        try:
            self.assertTrue(intent.target.motion_program["generated_area_focus"])

            controller.apply_generated_target(intent.target, source="chat command: base")

            self.assertEqual(handy.moves, [])
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            points = handy.stream_starts[0]["points"]
            self.assertGreater(max(point["x"] for point in points), 90)
            steady_points = [point for point in points if point["t"] >= 1800]
            self.assertTrue(steady_points, points)
            self.assertGreater(min(point["semantic_x"] for point in steady_points), 60)
            self.wait_for_hsp_trace(
                controller,
                lambda point: (
                    point.get("continuous_plan_kind") == "area_focus"
                    and point.get("continuous_area_focus")
                    and point.get("continuous_area_focus_localized")
                    and point.get("continuous_area_focus_zone") == "base"
                ),
            )
            trace = controller.observability_snapshot()["trace"]
            self.assertTrue(all(point.get("continuous_schema") != "hamp_live_anchor" for point in trace))
        finally:
            controller.stop()

    def test_chat_area_focus_zone_change_retargets_instead_of_preserving_old_phase(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        matcher = IntentMatcher()

        try:
            tip_intent = matcher.parse("focus on the tip", controller.semantic_target())
            controller.apply_generated_target(tip_intent.target, source="llm")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            time.sleep(0.12)
            base_intent = matcher.parse("focus on the base", controller.semantic_target())
            controller.apply_generated_target(base_intent.target, source="llm")

            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            replacement = handy.stream_replacements[0]
            bridge_points = [point for point in replacement["points"] if point.get("hsp_replacement_bridge")]
            self.assertTrue(bridge_points)
            point_times = [point["t"] for point in replacement["points"]]
            self.assertIn(replacement["start_time_ms"], point_times)

            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: (
                    point.get("continuous_plan_kind") == "area_focus"
                    and point.get("continuous_area_focus_zone") == "base"
                    and not point.get("hsp_replacement_bridge")
                ),
            )
            base_points = [
                point
                for point in trace
                if point.get("continuous_plan_kind") == "area_focus"
                and point.get("continuous_area_focus_zone") == "base"
            ]
            first_bridge = next(point for point in base_points if point.get("hsp_replacement_bridge"))
            first_retarget = next(point for point in base_points if not point.get("hsp_replacement_bridge"))
            hsp_clock_start_ms = first_bridge["hsp_play_start_ms"] - first_bridge["hsp_replacement_lead_ms"]

            self.assertLessEqual(
                first_bridge["hsp_point_time_ms"] - hsp_clock_start_ms,
                (CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS * 1000.0) + 5.0,
            )
            self.assertGreaterEqual(
                first_bridge["hsp_replacement_latency_bridge_start_ms"] - hsp_clock_start_ms,
                (CONTINUOUS_HSP_REPLACEMENT_BRIDGE_MIN_LATENCY_SECONDS * 1000.0) - 5.0,
            )
            self.assertEqual(first_retarget["hsp_replacement_kind"], "intent")
            self.assertGreaterEqual(first_retarget["hsp_replacement_lead_ms"], 800.0)
            self.assertEqual(first_retarget["morph_start_source"], "predicted_active_stream")
            self.assertAlmostEqual(
                first_retarget["output_depth"],
                first_retarget["morph_start_depth"],
                delta=2.0,
            )
        finally:
            controller.stop()

    def test_area_focus_replacement_lead_keeps_bridge_points_after_slow_add_latency(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        matcher = IntentMatcher()

        try:
            tip_intent = matcher.parse("focus on the tip", controller.semantic_target())
            controller.apply_generated_target(tip_intent.target, source="llm")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            base_intent = matcher.parse("focus on the base", controller.semantic_target())
            controller.apply_generated_target(base_intent.target, source="llm")

            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            replacement = handy.stream_replacements[0]
            bridge_points = [point for point in replacement["points"] if point.get("hsp_replacement_bridge")]
            self.assertTrue(bridge_points)

            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: (
                    point.get("continuous_plan_kind") == "area_focus"
                    and point.get("continuous_area_focus_zone") == "base"
                    and not point.get("hsp_replacement_bridge")
                ),
            )
            base_points = [
                point
                for point in trace
                if point.get("continuous_plan_kind") == "area_focus"
                and point.get("continuous_area_focus_zone") == "base"
            ]
            first_bridge = next(point for point in base_points if point.get("hsp_replacement_bridge"))
            first_retarget = next(point for point in base_points if not point.get("hsp_replacement_bridge"))
            hsp_clock_start_ms = first_retarget["hsp_play_start_ms"] - first_retarget["hsp_replacement_lead_ms"]

            self.assertGreaterEqual(
                first_retarget["hsp_replacement_lead_ms"],
                CONTINUOUS_HSP_AREA_FOCUS_REPLACEMENT_LEAD_SECONDS * 1000.0,
            )
            self.assertGreaterEqual(
                first_retarget["hsp_replacement_lead_ms"],
                8000.0,
            )
            self.assertTrue(
                any(
                    point["t"] - hsp_clock_start_ms >= 4800.0
                    and point["t"] < replacement["start_time_ms"]
                    for point in bridge_points
                ),
                bridge_points,
            )
            self.assertLess(first_bridge["hsp_point_time_ms"], first_retarget["hsp_point_time_ms"])
        finally:
            controller.stop()

    def test_continuous_backend_localizes_tip_anchor_loop_area_focus(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            target = controller.sanitizer.from_llm_move(
                {
                    "zone": "tip",
                    "pattern": "pulse",
                    "motion": "anchor_loop",
                    "anchors": ["tip", "upper", "lower", "upper"],
                    "sp": 33,
                    "rng": 75,
                },
                controller.semantic_target(),
            )
            self.assertIsNotNone(target)
            self.assertTrue(controller._should_use_hsp_area_focus_for_generated_target(target))
            self.assertFalse(controller._should_use_live_stroke_for_generated_target(target))

            controller.apply_generated_target(target, source="llm")

            self.assertEqual(handy.moves, [])
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            points = handy.stream_starts[0]["points"]
            steady_points = [point for point in points if point["t"] >= 1800]
            self.assertTrue(steady_points, points)
            self.assertLessEqual(max(point["semantic_x"] for point in steady_points), 38)
            self.assertLessEqual(min(point["semantic_x"] for point in steady_points), 5)
            trace = controller.observability_snapshot()["trace"]
            self.assertTrue(
                any(
                    point.get("continuous_schema") == "hsp"
                    and point.get("continuous_plan_kind") == "area_focus"
                    and point.get("continuous_area_focus_localized")
                    and point.get("continuous_area_focus_zone") == "tip"
                    and point.get("continuous_area_focus_requested_range") == 75
                    and point.get("continuous_area_focus_transport_range") < 36
                    for point in trace
                ),
                trace,
            )
            self.assertTrue(all(point.get("continuous_schema") != "hamp_live_anchor" for point in trace))
        finally:
            controller.stop()

    def test_continuous_pattern_chat_restarts_from_stopped_state(self):
        handy = StreamingFakeHandy()
        handy.last_relative_speed = 0
        controller = MotionController(handy, step_delay=0.16)

        try:
            target = controller.sanitizer.from_llm_move(
                {"pattern": "stroke"},
                controller.current_target(),
            )
            self.assertIsNotNone(target)
            self.assertGreater(target.speed, 0)

            controller.apply_generated_target(target, source="llm")

            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            self.assertTrue(controller.observability_snapshot()["playback_active"])
        finally:
            controller.stop()

    def test_llm_anchor_loop_uses_semantic_target_not_sampled_phase(self):
        controller = MotionController(StreamingFakeHandy(), step_delay=0.16)
        semantic = MotionTarget(42, 50, 70, "semantic anchor")
        sampled = MotionTarget(42, 16, 70, "sampled anchor floor")
        controller._set_semantic_target(semantic)

        with (
            mock.patch.object(controller, "current_target", return_value=sampled) as current_target,
            mock.patch.object(controller, "apply_generated_target") as apply_generated_target,
        ):
            target = controller.apply_llm_move(
                {
                    "motion": "anchor_loop",
                    "anchors": ["tip", "shaft", "base", "shaft"],
                    "rng": 70,
                }
            )

        current_target.assert_not_called()
        apply_generated_target.assert_called_once()
        self.assertIsNotNone(target)
        self.assertEqual(target.depth, 50)
        self.assertEqual(target.stroke_range, 70)

    def test_continuous_anchor_loop_prefers_area_focus_hsp_when_available(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            target = controller.sanitizer.from_llm_move(
                {
                    "motion": "anchor_loop",
                    "anchors": ["tip", "shaft", "base", "shaft"],
                    "dp": 50,
                    "rng": 70,
                },
                controller.semantic_target(),
            )
            self.assertIsNotNone(target)

            controller.apply_generated_target(target, source="llm")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            semantic = controller.semantic_target()
            self.assertEqual(semantic.depth, 50)
            self.assertEqual(semantic.stroke_range, 70)
            self.assertEqual(semantic.motion_program, target.motion_program)
            self.assertEqual(handy.moves, [])
            self.assertEqual(handy.stream_replacements, [])
            self.assertTrue(controller.observability_snapshot()["playback_active"])
            hsp_points = self.wait_for_hsp_trace(controller)
            self.assertTrue(
                any(
                    point.get("continuous_plan_kind") == "area_focus"
                    and point.get("requested_motion_program") == "localized_anchor_loop"
                    for point in hsp_points
                ),
                hsp_points,
            )
            self.assertGreater(
                len({round(point["x"], 1) for point in handy.stream_starts[0]["points"]}),
                2,
            )
            self.assertTrue(
                all(
                    point.get("continuous_schema") != "hamp_live_anchor"
                    for point in controller.observability_snapshot()["trace"]
                )
            )
        finally:
            controller.stop()

    def test_continuous_anchor_loop_keeps_live_stroke_fallback_without_hsp(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            target = controller.sanitizer.from_llm_move(
                {
                    "motion": "anchor_loop",
                    "anchors": ["tip", "shaft", "base", "shaft"],
                    "dp": 50,
                    "rng": 70,
                },
                controller.semantic_target(),
            )
            self.assertIsNotNone(target)

            controller.apply_generated_target(target, source="llm")
            self.assertTrue(self.wait_until(lambda: bool(handy.moves)), handy.moves)

            live_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hamp_live_anchor"
            ]
            self.assertTrue(live_points)
            self.assertTrue(all(point["continuous_hsp_bypassed"] for point in live_points))
        finally:
            controller.stop()

    def test_repeated_llm_anchor_loop_replacement_does_not_collapse_to_sampled_phase(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            first = controller.sanitizer.from_llm_move(
                {
                    "motion": "anchor_loop",
                    "anchors": ["tip", "shaft", "base", "shaft"],
                    "dp": 50,
                    "rng": 70,
                },
                controller.semantic_target(),
            )
            self.assertIsNotNone(first)
            controller.apply_generated_target(first, source="first")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            second = controller.apply_llm_move(
                {
                    "motion": "anchor_loop",
                    "anchors": ["base", "shaft", "tip", "shaft"],
                    "rng": 70,
                }
            )
            self.assertIsNotNone(second)
            self.assertEqual(second.depth, 50)
            self.assertEqual(handy.moves, [])
            self.assertEqual(handy.stream_replacements, [])
            hsp_points = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("continuous_plan_kind") == "area_focus",
            )
            self.assertTrue(any(point.get("requested_motion_program") == "localized_anchor_loop" for point in hsp_points))
            self.assertTrue(
                all(point.get("continuous_schema") != "hamp_live_anchor" for point in hsp_points)
            )
        finally:
            controller.stop()

    def test_anchor_loop_to_middle_area_focus_uses_hsp_replacement(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            anchor_target = controller.sanitizer.from_llm_move(
                {
                    "motion": "anchor_loop",
                    "anchors": ["tip", "shaft", "base", "shaft"],
                    "sp": 19,
                    "rng": 70,
                },
                controller.semantic_target(),
            )
            self.assertIsNotNone(anchor_target)
            controller.apply_generated_target(anchor_target, source="llm")
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            middle_target = controller.sanitizer.from_llm_move(
                {"zone": "middle", "sp": 19},
                controller.semantic_target(),
            )
            self.assertIsNotNone(middle_target)
            controller.apply_generated_target(middle_target, source="llm")

            self.assertEqual(handy.moves, [])
            self.assertTrue(self.wait_until(lambda: len(handy.stream_replacements) == 1), handy.stream_replacements)
            replacement = handy.stream_replacements[0]
            self.assertTrue(any(point.get("hsp_replacement_bridge") for point in replacement["points"]))
            trace = self.wait_for_hsp_trace(
                controller,
                lambda point: point.get("continuous_plan_kind") == "area_focus"
                and point.get("continuous_area_focus_zone") == "middle"
                and not point.get("hsp_replacement_bridge"),
            )
            middle_points = [
                point
                for point in trace
                if point.get("continuous_plan_kind") == "area_focus"
                and point.get("continuous_area_focus_zone") == "middle"
                and not point.get("hsp_replacement_bridge")
            ]
            self.assertTrue(middle_points)
            self.assertEqual(middle_points[0]["hsp_replacement_kind"], "intent")
            self.assertEqual(middle_points[0]["morph_start_source"], "predicted_active_stream")
            self.assertGreaterEqual(
                middle_points[0]["hsp_replacement_lead_ms"],
                CONTINUOUS_HSP_AREA_FOCUS_REPLACEMENT_LEAD_SECONDS * 1000.0,
            )
        finally:
            controller.stop()

    def test_authored_hsp_pattern_preserves_long_authored_timestamps(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)
        pattern = MotionPattern(
            "Long Authored",
            (
                PatternAction(0, 0),
                PatternAction(150_000, 100),
                PatternAction(300_000, 0),
            ),
        )

        try:
            applied = controller.apply_motion_pattern(
                pattern,
                MotionTarget(50, 50, 100, "long authored"),
                preserve_timing=True,
                source="unit test",
            )
            self.assertTrue(applied)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            self.assertEqual([point["t"] for point in points[:2]], [0, 150_000])
            self.assertEqual([point["x"] for point in points[:2]], [0, 100])
            self.assertEqual(points[1]["stream_index"], 2)
            hsp_points = [
                point
                for point in controller.observability_snapshot()["trace"]
                if point.get("continuous_schema") == "hsp_authored"
            ]
            self.assertTrue(hsp_points)
            self.assertFalse(any(point.get("hsp_twitch_filtered_points") for point in hsp_points))
            self.assertEqual(hsp_points[1]["hsp_point_time_ms"], 150_000)
        finally:
            controller.stop()

    def test_authored_hsp_keeps_same_integer_points(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            applied = controller.apply_authored_actions(
                (
                    PatternAction(0, 50.1),
                    PatternAction(80, 50.2),
                    PatternAction(160, 51.0),
                ),
                MotionTarget(45, 50, 100, "same integer authored"),
                source="unit test",
            )
            self.assertTrue(applied)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)

            points = handy.stream_starts[0]["points"]
            self.assertEqual([point["t"] for point in points], [0, 80, 160])
            self.assertEqual(int(round(points[0]["x"])), int(round(points[1]["x"])))
        finally:
            controller.stop()

    def test_authored_hsp_current_target_uses_active_time_not_future_buffer(self):
        handy = StreamingFakeHandy()
        controller = MotionController(handy, step_delay=0.16)

        try:
            applied = controller.apply_authored_actions(
                (
                    PatternAction(0, 0),
                    PatternAction(10_000, 100),
                    PatternAction(20_000, 100),
                ),
                MotionTarget(45, 50, 100, "long authored"),
                source="unit test",
            )
            self.assertTrue(applied)
            self.assertTrue(self.wait_until(lambda: len(handy.stream_starts) == 1), handy.stream_starts)
            self.assertEqual(handy.last_depth_pos, 100)

            current = controller.current_target()

            self.assertLess(current.depth, 5)
            self.assertEqual(current.stroke_range, 100)
        finally:
            controller.stop()

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

        controller.apply_motion_pattern(
            MotionPattern(
                "fast position test",
                (
                    PatternAction(0, 76),
                    PatternAction(90, 6),
                    PatternAction(430, 64),
                ),
                window_scale=0.18,
                speed_scale=1.1,
                interpolation_ms=80,
                max_step_delta=26,
            ),
            MotionTarget(80, 50, 80, "fast position test"),
            source="unit test",
        )

        timed = [frame for frame in captured if getattr(frame, "phase", "") == "timed-pattern"]
        self.assertTrue(timed)
        self.assertGreater(max(frame.target.speed for frame in timed), 90)
        self.assertTrue(any(frame.delay_factor < 0.25 for frame in timed[1:]))

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
