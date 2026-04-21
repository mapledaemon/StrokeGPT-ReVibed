import random
import unittest

from strokegpt.motion import MotionTarget
from strokegpt.motion_patterns import expand_pattern, pattern_names
from strokegpt.motion_scripts import MotionScriptPlanner


class MotionScriptPlannerTests(unittest.TestCase):
    def test_auto_plan_generates_varied_multi_step_arc(self):
        planner = MotionScriptPlanner("auto", rng=random.Random(3))
        current = MotionTarget(20, 30, 40)
        steps = [planner.next_step(current) for _ in range(8)]

        labels = {step.target.label for step in steps}
        self.assertGreaterEqual(len(labels), 5)
        self.assertTrue(all(0 <= step.target.speed <= 100 for step in steps))
        self.assertTrue(all(0 <= step.target.depth <= 100 for step in steps))
        self.assertTrue(all(5 <= step.target.stroke_range <= 100 for step in steps))

    def test_feedback_replaces_plan_with_response_sequence(self):
        planner = MotionScriptPlanner("auto", rng=random.Random(4))
        current = MotionTarget(25, 25, 25)
        planner.next_step(current)

        feedback = MotionTarget(60, 70, 35, "deeper")
        step = planner.next_step(current, feedback_target=feedback)

        self.assertEqual(step.message, "Adjusting.")
        self.assertIn("deeper", step.target.label)

    def test_edge_reaction_builds_pullback_sequence(self):
        planner = MotionScriptPlanner("edging", rng=random.Random(5))
        step = planner.next_step(MotionTarget(50, 80, 40), edge_count=2)

        self.assertEqual(step.mood, "Dominant")
        self.assertIn("Edge count: 2", step.message)
        self.assertLessEqual(step.target.speed, 10)

    def test_pattern_palette_uses_funscript_style_actions(self):
        self.assertIn("flick", pattern_names())

        frames = expand_pattern(
            "flick",
            MotionTarget(30, 40, 50),
            MotionTarget(55, 10, 18, "tip+flick"),
            rng=random.Random(7),
        )

        self.assertGreaterEqual(len(frames), 4)
        self.assertGreater(len({round(frame.target.depth) for frame in frames}), 2)
        self.assertTrue(all(frame.target.stroke_range <= 18 for frame in frames))

    def test_hold_pattern_still_alternates_position(self):
        frames = expand_pattern(
            "hold",
            MotionTarget(30, 40, 50),
            MotionTarget(30, 10, 12, "tip+hold"),
            rng=random.Random(9),
        )

        self.assertGreater(len({round(frame.target.depth) for frame in frames}), 2)
        self.assertTrue(all(frame.target.speed > 0 for frame in frames))

    def test_feedback_pattern_expands_to_smooth_sequence(self):
        planner = MotionScriptPlanner("auto", rng=random.Random(8))
        current = MotionTarget(30, 40, 50)
        feedback = MotionTarget(58, 12, 18, "tip+flick")

        steps = [planner.next_step(current, feedback_target=feedback)]
        steps.extend(planner.next_step(current) for _ in range(4))

        self.assertEqual(steps[0].message, "Adjusting.")
        self.assertGreater(len({round(step.target.depth) for step in steps[1:]}), 2)
        self.assertTrue(all("flick" in step.target.label for step in steps[1:]))


if __name__ == "__main__":
    unittest.main()
