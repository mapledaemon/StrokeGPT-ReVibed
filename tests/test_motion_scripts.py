import random
import unittest

from strokegpt.motion import MotionTarget
from strokegpt.motion_patterns import (
    PATTERNS,
    MotionPattern,
    PatternAction,
    expand_anchor_program,
    expand_motion_pattern,
    expand_pattern,
    inject_intermediate_actions,
    limit_action_delta,
    minimum_jerk,
    normalize_actions,
    pattern_names,
    prepare_anchor_actions,
    prepare_pattern_actions,
    repeat_actions,
)
from strokegpt.motion_scripts import EDGING_ARCS, MILKING_ARCS, MotionScriptPlanner


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
        current = MotionTarget(50, 80, 40)
        step = planner.next_step(current, edge_count=2)
        steps = [step]
        steps.extend(planner.next_step(current) for _ in range(5))

        self.assertEqual(step.mood, "Dominant")
        self.assertIn("Edge count: 2", step.message)
        self.assertLessEqual(step.target.speed, 10)
        self.assertIn("Edge Pull Back", step.target.label)
        pullback_steps = [item for item in steps if item.target.label.startswith("Edge Pull Back")]
        self.assertTrue(any(item.target.depth >= 84 for item in pullback_steps))
        self.assertTrue(any(item.target.stroke_range <= 20 for item in pullback_steps))

    def test_mode_specific_patterns_are_cataloged(self):
        names = pattern_names()

        self.assertIn("milking-pressure-build", names)
        self.assertIn("milking-final-wave", names)
        self.assertIn("edge-build-low", names)
        self.assertIn("edge-pull-back", names)

    def test_milking_plan_uses_catalog_pattern_labels(self):
        planner = MotionScriptPlanner("milking", rng=random.Random(2))
        current = MotionTarget(20, 30, 40)
        steps = [planner.next_step(current) for _ in range(8)]
        labels = [step.target.label for step in steps]

        self.assertTrue(any(label.startswith("Milking ") for label in labels))
        self.assertFalse(any(label == "current" for label in labels))
        self.assertFalse(any(label.startswith("pressure build") for label in labels))

    def test_mode_arcs_start_base_mid_before_tip(self):
        for arc in EDGING_ARCS:
            early_depths = [depth for _pattern_id, _mood, _speed, depth, _stroke_range in arc[:2]]
            self.assertTrue(all(depth >= 50 for depth in early_depths))
            tip_indices = [
                index
                for index, (pattern_id, *_rest) in enumerate(arc)
                if "tip" in pattern_id or "shallow" in pattern_id
            ]
            self.assertTrue(all(index >= 3 for index in tip_indices))

        for arc in MILKING_ARCS:
            early_depths = [depth for _pattern_id, _mood, _speed, depth, _stroke_range in arc[:2]]
            self.assertTrue(all(depth >= 50 for depth in early_depths))

    def test_edge_reaction_ramps_down_then_recovers_to_hold(self):
        planner = MotionScriptPlanner("edging", rng=random.Random(5))
        current = MotionTarget(50, 80, 40)

        steps = [planner.next_step(current, edge_count=3)]
        steps.extend(planner.next_step(current) for _ in range(24))
        reaction_labels = [step.target.label for step in steps]

        pullback_index = next(
            index for index, label in enumerate(reaction_labels)
            if label.startswith("Edge Pull Back")
        )
        recover_index = next(
            index for index, label in enumerate(reaction_labels)
            if label.startswith("Edge Recover")
        )
        hold_index = next(
            index for index, label in enumerate(reaction_labels)
            if label.startswith("Edge Hold")
        )

        self.assertLess(pullback_index, recover_index)
        self.assertLess(recover_index, hold_index)

    def test_edge_patterns_use_expected_regions(self):
        hold_frames = expand_pattern(
            "edge-hold",
            MotionTarget(30, 40, 50),
            MotionTarget(34, 32, 46, "Edge Hold"),
            rng=random.Random(17),
        )
        recover_frames = expand_pattern(
            "edge-recover",
            MotionTarget(30, 40, 50),
            MotionTarget(18, 68, 48, "Edge Recover"),
            rng=random.Random(18),
        )
        pullback_frames = expand_pattern(
            "edge-pull-back",
            MotionTarget(30, 40, 50),
            MotionTarget(14, 88, 18, "Edge Pull Back"),
            rng=random.Random(19),
        )

        self.assertTrue(hold_frames)
        hold_depths = [frame.target.depth for frame in hold_frames if frame.phase == "pattern"]
        self.assertTrue(all(depth <= 55 for depth in hold_depths))
        self.assertGreater(max(hold_depths), 35)

        self.assertTrue(recover_frames)
        recover_depths = [frame.target.depth for frame in recover_frames if frame.phase == "pattern"]
        self.assertTrue(all(60 <= depth <= 88 for depth in recover_depths))
        self.assertGreater(max(recover_depths), 80)

        self.assertTrue(pullback_frames)
        pullback_depths = [frame.target.depth for frame in pullback_frames if frame.phase == "pattern"]
        self.assertTrue(all(depth >= 88 for depth in pullback_depths))
        self.assertGreater(max(pullback_depths), 94)

    def test_pattern_palette_uses_funscript_style_actions(self):
        self.assertIn("flick", pattern_names())

        frames = expand_pattern(
            "flick",
            MotionTarget(30, 40, 50),
            MotionTarget(55, 10, 18, "tip+flick"),
            rng=random.Random(7),
        )

        self.assertGreaterEqual(len(frames), 4)
        pattern_frames = [frame for frame in frames if frame.phase == "pattern"]
        self.assertGreater(len({round(frame.target.depth) for frame in pattern_frames}), 2)
        self.assertTrue(all(frame.target.stroke_range <= 18 for frame in pattern_frames))

    def test_pattern_expansion_blends_from_previous_motion_state(self):
        current = MotionTarget(70, 92, 85, "previous")
        frames = expand_pattern(
            "flick",
            current,
            MotionTarget(36, 12, 18, "tip+flick"),
            rng=random.Random(21),
        )

        self.assertEqual([frame.phase for frame in frames[:2]], ["blend", "blend"])
        self.assertEqual(frames[-1].phase, "pattern")
        depth_steps = [current.depth] + [frame.target.depth for frame in frames[:3]]
        self.assertTrue(
            all(abs(a - b) <= 25 for a, b in zip(depth_steps, depth_steps[1:])),
            depth_steps,
        )
        self.assertIn("blend", frames[0].target.label)

    def test_pattern_expansion_blends_direction_changes(self):
        pattern = MotionPattern(
            "Turn Test",
            (
                PatternAction(0, 20),
                PatternAction(220, 82),
                PatternAction(440, 18),
            ),
            window_scale=1.0,
            speed_scale=1.0,
        )

        frames = expand_motion_pattern(
            pattern,
            MotionTarget(40, 32, 60, "current"),
            MotionTarget(40, 50, 60, "turn test"),
            rng=random.Random(11),
        )

        turn_frames = [frame for frame in frames if "turn" in frame.target.label]
        self.assertGreaterEqual(len(turn_frames), 2)
        turn_apex = next(frame for frame in turn_frames if "apex" in frame.target.label)
        self.assertEqual(turn_apex.phase, "pattern")
        self.assertLess(turn_apex.target.speed, 22)
        pattern_depths = [round(frame.target.depth) for frame in frames if frame.phase == "pattern"]
        self.assertEqual(pattern_depths[:3], [32, 69, 31])

    def test_flick_pattern_is_quick_out_then_slower_return(self):
        actions = PATTERNS["flick"].actions

        self.assertGreaterEqual(len(actions), 3)
        start, outward, returned = actions[:3]
        self.assertLess(outward.pos, start.pos)
        self.assertGreater(returned.pos, outward.pos)
        self.assertLessEqual(outward.at - start.at, 110)
        self.assertGreater(returned.at - outward.at, outward.at - start.at)

    def test_milk_pattern_is_available_and_full_range(self):
        self.assertIn("milk", pattern_names())

        pattern = PATTERNS["milk"]
        actions = prepare_pattern_actions(pattern)
        positions = [action.pos for action in actions]

        self.assertGreaterEqual(pattern.window_scale, 0.9)
        self.assertLessEqual(min(positions), 8)
        self.assertGreaterEqual(max(positions), 94)

    def test_arbitrary_motion_pattern_expands_to_frames(self):
        pattern = MotionPattern(
            "custom-loop",
            (
                PatternAction(0, 10),
                PatternAction(200, 90),
                PatternAction(400, 10),
            ),
            window_scale=0.3,
            interpolation_ms=120,
        )

        frames = expand_motion_pattern(
            pattern,
            MotionTarget(20, 50, 40),
            MotionTarget(45, 50, 60, "training custom-loop"),
            rng=random.Random(15),
        )

        self.assertGreater(len(frames), 3)
        self.assertGreater(len({round(frame.target.depth) for frame in frames}), 2)
        self.assertTrue(all(frame.target.motion_program is None for frame in frames))

    def test_motion_pattern_tempo_scale_changes_frame_cadence(self):
        actions = (
            PatternAction(0, 10),
            PatternAction(200, 90),
            PatternAction(400, 10),
        )
        target = MotionTarget(45, 50, 60, "training tempo")

        normal_frames = expand_motion_pattern(
            MotionPattern("normal", actions, tempo_scale=1.0),
            MotionTarget(20, 50, 40),
            target,
            rng=random.Random(16),
        )
        faster_frames = expand_motion_pattern(
            MotionPattern("faster", actions, tempo_scale=2.0),
            MotionTarget(20, 50, 40),
            target,
            rng=random.Random(16),
        )
        slower_frames = expand_motion_pattern(
            MotionPattern("slower", actions, tempo_scale=0.5),
            MotionTarget(20, 50, 40),
            target,
            rng=random.Random(16),
        )

        self.assertEqual(
            [round(frame.target.depth, 2) for frame in faster_frames],
            [round(frame.target.depth, 2) for frame in normal_frames],
        )
        normal_delay = sum(frame.delay_factor for frame in normal_frames)
        self.assertLess(sum(frame.delay_factor for frame in faster_frames), normal_delay)
        self.assertGreater(sum(frame.delay_factor for frame in slower_frames), normal_delay)

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

    def test_minimum_jerk_easing_keeps_endpoints_and_midpoint(self):
        self.assertEqual(minimum_jerk(0), 0)
        self.assertEqual(minimum_jerk(1), 1)
        self.assertAlmostEqual(minimum_jerk(0.5), 0.5)

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

    def test_anchor_program_generates_bounded_soft_targets(self):
        actions = prepare_anchor_actions(
            {
                "motion": "anchor_loop",
                "anchors": ["tip", "middle", "base", "upper"],
                "tempo": 0.9,
                "softness": 0.85,
                "sample_interval_ms": 140,
                "max_step_delta": 22,
            },
            rng=random.Random(12),
        )

        self.assertGreater(len(actions), 10)
        self.assertEqual(actions[0].pos, 8)
        self.assertTrue(all(0 <= action.pos <= 100 for action in actions))
        self.assertEqual(len({action.at for action in actions}), len(actions))
        self.assertTrue(all(abs(end.pos - start.pos) <= 22 for start, end in zip(actions, actions[1:])))

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
                self.assertLessEqual(sum(frame.delay_factor for frame in frames), 5.5)

    def test_anchor_program_expands_to_motion_frames(self):
        frames = expand_anchor_program(
            MotionTarget(30, 40, 50),
            MotionTarget(
                45,
                50,
                70,
                "llm+anchor_loop",
                motion_program={
                    "type": "anchor_loop",
                    "anchors": [
                        {"label": "tip", "pos": 8},
                        {"label": "middle", "pos": 50},
                        {"label": "base", "pos": 92},
                    ],
                    "tempo": 0.8,
                    "softness": 0.9,
                    "sample_interval_ms": 160,
                    "max_step_delta": 24,
                },
            ),
            {
                "type": "anchor_loop",
                "anchors": ["tip", "middle", "base"],
                "tempo": 0.8,
                "softness": 0.9,
            },
            rng=random.Random(13),
        )

        self.assertGreater(len(frames), 8)
        self.assertTrue(all(frame.target.motion_program is None for frame in frames))
        self.assertGreater(len({round(frame.target.depth) for frame in frames}), 3)
        self.assertLessEqual(sum(frame.delay_factor for frame in frames), 4.5)

    def test_feedback_pattern_expands_to_smooth_sequence(self):
        planner = MotionScriptPlanner("auto", rng=random.Random(8))
        current = MotionTarget(30, 40, 50)
        feedback = MotionTarget(58, 12, 18, "tip+flick")

        steps = [planner.next_step(current, feedback_target=feedback)]
        steps.extend(planner.next_step(current) for _ in range(4))

        self.assertEqual(steps[0].message, "Adjusting.")
        self.assertGreater(len({round(step.target.depth) for step in steps[1:]}), 2)
        self.assertTrue(all("flick" in step.target.label for step in steps[1:]))

    def test_feedback_anchor_program_expands_to_smooth_sequence(self):
        planner = MotionScriptPlanner("auto", rng=random.Random(14))
        current = MotionTarget(30, 40, 50)
        feedback = MotionTarget(
            44,
            50,
            70,
            "llm+anchor_loop",
            motion_program={
                "type": "anchor_loop",
                "anchors": ["tip", "middle", "base"],
                "tempo": 0.8,
                "softness": 0.85,
                "sample_interval_ms": 180,
            },
        )

        steps = [planner.next_step(current, feedback_target=feedback)]
        steps.extend(planner.next_step(current) for _ in range(5))

        self.assertEqual(steps[0].message, "Adjusting.")
        self.assertGreater(len({round(step.target.depth) for step in steps[1:]}), 3)
        self.assertTrue(all("anchor_loop" in step.target.label for step in steps[1:]))


if __name__ == "__main__":
    unittest.main()
