import unittest
from types import SimpleNamespace

from strokegpt.motion import IntentMatcher, MotionController, MotionSanitizer, MotionTarget


class FakeHandy:
    def __init__(self):
        self.last_relative_speed = 20
        self.last_depth_pos = 30
        self.last_stroke_range = 40
        self.moves = []
        self.position_moves = []
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
    def test_controller_routes_motion_through_smooth_path(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.apply_target(MotionTarget(70, 60, 80))
        self.assertGreater(len(handy.moves), 1)
        self.assertEqual(handy.moves[-1], (70, 60, 80))

    def test_controller_expands_llm_anchor_program(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
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

    def test_controller_expands_direct_anchor_target(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        intent = IntentMatcher().parse("soft bounce between tip middle and base", controller.current_target())

        controller.apply_generated_target(intent.target)

        self.assertGreater(len(handy.moves), 4)
        self.assertGreater(len({depth for _, depth, _ in handy.moves}), 3)

    def test_stop_cancels_and_stops_handy(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0)
        controller.stop()
        self.assertTrue(handy.stopped)

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

    def test_apply_position_frames_uses_exact_pattern_positions(self):
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
        self.assertEqual([move[:3] for move in handy.position_moves], [(45, 20, False), (45, 80, False), (30, 35, False)])
        self.assertTrue(all(move[3] is not None for move in handy.position_moves))
        self.assertEqual(handy.last_stroke_range, 40)
        self.assertTrue(handy.stopped)

    def test_apply_position_frames_uses_final_stop_on_target_without_stop_after(self):
        handy = FakeHandy()
        controller = MotionController(handy, step_delay=0.1)
        frames = [
            SimpleNamespace(target=MotionTarget(40, 25, 10), delay_factor=0),
            SimpleNamespace(target=MotionTarget(40, 75, 10), delay_factor=0),
        ]

        completed = controller.apply_position_frames(frames, stop_after=False)

        self.assertTrue(completed)
        self.assertEqual([move[2] for move in handy.position_moves], [False, True])
        self.assertFalse(handy.stopped)


if __name__ == "__main__":
    unittest.main()
