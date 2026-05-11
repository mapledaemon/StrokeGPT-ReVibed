import threading
import time
import unittest
from types import SimpleNamespace

from strokegpt.motion import (
    CONTINUOUS_MAX_MORPH_SECONDS,
    IntentMatcher,
    MotionController,
    MotionSanitizer,
    MotionTarget,
    POSITION_PASS_THROUGH_MIN_SECONDS,
)


class FakeHandy:
    def __init__(self):
        self.last_relative_speed = 20
        self.last_depth_pos = 30
        self.last_stroke_range = 40
        self.moves = []
        self.position_moves = []
        self.velocity_intervals = []
        self.stopped = False

    def move(self, speed, depth, stroke_range):
        self.moves.append((speed, depth, stroke_range))
        self.last_relative_speed = speed
        self.last_depth_pos = depth
        self.last_stroke_range = stroke_range

    def move_to_depth(self, speed, depth, *, stop_on_target=True, velocity=None):
        self.position_moves.append((speed, depth, stop_on_target, velocity))
        self.last_relative_speed = speed
        self.last_depth_pos = depth
        return True

    def velocity_for_depth_interval(self, speed, start_depth, end_depth, duration_seconds):
        self.velocity_intervals.append((speed, start_depth, end_depth, duration_seconds))
        return int(round(speed + abs(end_depth - start_depth) + duration_seconds * 10))

    def stop(self):
        self.stopped = True
        self.last_relative_speed = 0


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

    def test_continuous_backend_routes_plain_chat_targets_through_position_smoothing(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)

        controller.apply_generated_target(MotionTarget(70, 90, 80, "plain chat"), source="llm")

        self.assertEqual(handy.moves, [])
        self.assertGreater(len(handy.position_moves), 3)
        self.assertEqual(handy.position_moves[-1][1], 90)
        self.assertEqual(handy.position_moves[-1][2], True)

    def test_position_backend_routes_generated_frames_to_position_moves(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.set_backend("position")
        intent = IntentMatcher().parse("soft bounce between tip middle and base", controller.current_target())

        controller.apply_generated_target(intent.target)

        self.assertGreater(len(handy.position_moves), 4)
        self.assertEqual(handy.moves, [])
        self.assertGreater(len({depth for _, depth, _, _ in handy.position_moves}), 3)

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


if __name__ == "__main__":
    unittest.main()
