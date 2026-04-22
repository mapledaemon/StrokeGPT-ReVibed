import random
import unittest

from strokegpt.motion import MotionTarget
from strokegpt.motion_patterns import (
    PATTERNS,
    PatternAction,
    expand_pattern,
    inject_intermediate_actions,
    limit_action_delta,
    normalize_actions,
    pattern_names,
    prepare_pattern_actions,
    repeat_actions,
)
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

    def test_pattern_action_normalizer_sorts_dedupes_and_preserves_endpoint(self):
        actions = normalize_actions(
            (
                {"at": 100, "pos": 10},
                {"at": 0, "pos": -20},
                {"at": 100, "pos": 20},
                {"at": 130, "pos": 30},
                {"at": 250, "pos": 120},
            ),
            min_interval_ms=80,
        )

        self.assertEqual(actions, (PatternAction(0, 0), PatternAction(100, 20), PatternAction(250, 100)))

    def test_dynamic_injection_adds_eased_intermediate_actions(self):
        actions = inject_intermediate_actions(
            (PatternAction(0, 100), PatternAction(400, 0)),
            target_interval_ms=100,
            interpolation="cosine",
            speed_adaptive=False,
        )

        self.assertEqual(actions[0], PatternAction(0, 100))
        self.assertEqual(actions[-1], PatternAction(400, 0))
        self.assertEqual([action.at for action in actions], [0, 100, 200, 300, 400])
        self.assertLess(actions[1].pos, 100)
        self.assertGreater(actions[1].pos, actions[2].pos)

    def test_repeat_actions_extends_shape_without_duplicate_seam(self):
        actions = repeat_actions(
            (PatternAction(0, 10), PatternAction(50, 80), PatternAction(100, 10)),
            repeats=2,
        )

        self.assertEqual([action.at for action in actions], [0, 50, 100, 150, 200])
        self.assertEqual([action.pos for action in actions], [10, 80, 10, 80, 10])

    def test_action_delta_limiter_softens_large_jumps(self):
        actions = limit_action_delta((PatternAction(0, 0), PatternAction(100, 100)), max_step_delta=25)

        deltas = [abs(end.pos - start.pos) for start, end in zip(actions, actions[1:])]
        self.assertGreater(len(actions), 2)
        self.assertTrue(all(delta <= 25 for delta in deltas))

    def test_prepared_patterns_keep_large_step_limiter_points(self):
        for name in ("flutter", "ladder", "surge"):
            with self.subTest(name=name):
                pattern = PATTERNS[name]
                actions = prepare_pattern_actions(pattern)
                deltas = [abs(end.pos - start.pos) for start, end in zip(actions, actions[1:])]

                self.assertTrue(deltas)
                self.assertTrue(all(delta <= pattern.max_step_delta for delta in deltas))

    def test_hold_pattern_still_alternates_position(self):
        frames = expand_pattern(
            "hold",
            MotionTarget(30, 40, 50),
            MotionTarget(30, 10, 12, "tip+hold"),
            rng=random.Random(9),
        )

        self.assertGreater(len({round(frame.target.depth) for frame in frames}), 2)
        self.assertTrue(all(frame.target.speed > 0 for frame in frames))

    def test_new_smooth_patterns_expand_to_multi_frame_sequences(self):
        for name in ("flutter", "ladder", "surge", "sway"):
            with self.subTest(name=name):
                self.assertIn(name, pattern_names())
                frames = expand_pattern(
                    name,
                    MotionTarget(30, 40, 50),
                    MotionTarget(50, 50, 60, name),
                    rng=random.Random(11),
                )
                self.assertGreater(len(frames), 4)
                self.assertGreater(len({round(frame.target.depth) for frame in frames}), 2)
                self.assertLessEqual(sum(frame.delay_factor for frame in frames), 3.75)

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
