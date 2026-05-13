import random
import unittest

from strokegpt.motion import MotionTarget
from strokegpt.motion_patterns import (
    PATTERNS,
    JITTER_CYCLE_SECONDS,
    FrameStyle,
    MotionPattern,
    PatternAction,
    expand_anchor_program,
    expand_motion_pattern,
    expand_pattern,
    continuous_plan_depth_range,
    continuous_motion_plan,
    sample_continuous_motion,
    sample_continuous_plan,
    inject_intermediate_actions,
    limit_action_delta,
    minimum_jerk,
    normalize_actions,
    pattern_names,
    prepare_anchor_actions,
    prepare_pattern_actions,
    repeat_actions,
    _motion_target_for_sample,
    _sample_action_position,
    _smooth_jitter,
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
        self.assertEqual(step.message, "Backing off for a moment.")
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

    def test_continuous_planner_keeps_fixed_pattern_as_single_control_basis(self):
        planner = MotionScriptPlanner("milking", rng=random.Random(2), continuous_patterns=True)
        current = MotionTarget(20, 30, 40)

        steps = planner._pattern_cluster(current, "milking-full-drive", "Passionate", 66, 52, 88)

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].target.label, PATTERNS["milking-full-drive"].name)
        self.assertGreater(steps[0].delay_factor, 0)

    def test_continuous_feedback_bridge_does_not_restart_pattern_basis(self):
        planner = MotionScriptPlanner("auto", rng=random.Random(4), continuous_patterns=True)
        current = MotionTarget(25, 25, 25)
        feedback = MotionTarget(60, 70, 35, "milk")

        steps = planner._pattern_feedback_steps(current, feedback, "milk")

        self.assertEqual(steps[0].target.label, "feedback bridge")
        self.assertEqual(steps[1].target.label, "milk")

    def test_continuous_motion_plan_samples_pattern_as_cycle(self):
        plan = continuous_motion_plan("stroke")
        target = MotionTarget(50, 50, 80, "stroke")

        first = sample_continuous_plan(plan, target, 0.0)
        later = sample_continuous_plan(plan, target, plan.duration_seconds * 0.35)

        self.assertIn("continuous", first.label)
        self.assertNotEqual(round(first.depth), round(later.depth))
        self.assertGreaterEqual(first.stroke_range, 5)

    def test_continuous_motion_plan_duration_includes_wrap_segment(self):
        # ``ramp`` is strongly asymmetric (20 -> 100). Its implicit wrap
        # segment must contribute real cycle time; otherwise the sampler
        # glides through the gap only by compressing the authored ramp.
        ramp = continuous_motion_plan("ramp")
        self.assertIsNotNone(ramp)
        self.assertAlmostEqual(ramp.duration_seconds, 1.8)

        # Symmetric patterns still get the small 50 ms wrap floor so the
        # closed loop has an explicit nonzero segment at phase wraparound.
        stroke = continuous_motion_plan("stroke")
        self.assertIsNotNone(stroke)
        self.assertAlmostEqual(stroke.duration_seconds, 0.95)

    def test_continuous_plan_caches_projectable_normalized_range(self):
        plan = continuous_motion_plan("ramp")
        target = MotionTarget(60, 50, 80, "ramp")

        self.assertIsNotNone(plan)
        self.assertLessEqual(plan.normalized_range[0], 20.0)
        self.assertGreaterEqual(plan.normalized_range[1], 100.0)

        legacy_range = {
            "min": round(min(
                sample_continuous_plan(plan, target, plan.duration_seconds * index / 24.0).depth
                for index in range(25)
            )),
            "max": round(max(
                sample_continuous_plan(plan, target, plan.duration_seconds * index / 24.0).depth
                for index in range(25)
            )),
        }

        self.assertEqual(continuous_plan_depth_range(plan, target), legacy_range)

    def test_sample_action_position_is_phase_cyclic(self):
        # A closed pattern: positions at the same depth at start and end.
        actions = (
            PatternAction(0, 20),
            PatternAction(250, 80),
            PatternAction(500, 80),
            PatternAction(750, 20),
        )
        # The wraparound segment (from actions[-1] back to actions[0]) is
        # sampled at phase~1.0. With the old cosine sampler this returned
        # actions[-1].pos and produced a step on the next cycle's phase=0
        # sample. With cyclic Catmull-Rom the value at phase very close to
        # 1.0 should be near phase=0's value: a small fraction of a unit,
        # not the 60-unit jump the cosine sampler could leave behind.
        edge = _sample_action_position(actions, 0.9995)
        start = _sample_action_position(actions, 0.0005)
        self.assertLess(abs(edge - start), 1.5)

    def test_sample_action_position_smooths_per_cycle_step(self):
        # An asymmetric closed pattern: actions[-1].pos != actions[0].pos
        # is the case that historically created the per-cycle position
        # jump in cosine sampling. Catmull-Rom across cyclic neighbors
        # should keep adjacent samples close even right across the wrap.
        actions = (
            PatternAction(0, 40),
            PatternAction(400, 80),
            PatternAction(800, 60),
        )
        # Sample densely around the cycle boundary and confirm no large
        # per-step jump.
        samples = [_sample_action_position(actions, phase / 200.0) for phase in range(0, 201)]
        deltas = [abs(samples[i + 1] - samples[i]) for i in range(len(samples) - 1)]
        self.assertLess(
            max(deltas),
            6.0,
            "no single phase step should jump more than ~6 units on a 200-sample sweep",
        )

    def test_sample_action_position_clamps_to_zero_hundred(self):
        # Catmull-Rom can overshoot up to ~12.5% of a segment range with
        # extreme control points. The sampler must clamp the result so a
        # spike at the top/bottom of a stroke never produces an
        # out-of-range depth that would later confuse the controller.
        actions = (
            PatternAction(0, 0),
            PatternAction(100, 100),
            PatternAction(200, 0),
            PatternAction(300, 100),
        )
        for phase in (i / 99 for i in range(100)):
            value = _sample_action_position(actions, phase)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)

    def test_smooth_jitter_is_bounded_and_zero_when_amount_zero(self):
        self.assertEqual(_smooth_jitter(0.0, 0.0), 0.0)
        self.assertEqual(_smooth_jitter(0.5, 0.0), 0.0)
        self.assertEqual(_smooth_jitter(0.0, -5.0), 0.0)
        for phase in (i / 99 for i in range(100)):
            value = _smooth_jitter(phase, 4.0)
            # Two summed sines averaged at 0.5; magnitude bounded by amount.
            self.assertLessEqual(abs(value), 4.0 + 1e-9)

    def test_smooth_jitter_axes_are_decorrelated(self):
        # Depth and range use different ``axis_seed`` values so a single
        # phase produces different perturbations on each axis. Without
        # decorrelation depth and range would drift in lockstep.
        depth_track = [_smooth_jitter(phase / 49, 5.0, axis_seed=0.0) for phase in range(50)]
        range_track = [_smooth_jitter(phase / 49, 5.0, axis_seed=0.5) for phase in range(50)]
        self.assertNotEqual(depth_track, range_track)
        # Confirm samples co-occur at the same phase but differ in value.
        mismatches = sum(1 for d, r in zip(depth_track, range_track) if abs(d - r) > 0.5)
        self.assertGreater(mismatches, 25, "axes should diverge across half the sweep")

    def test_smooth_jitter_is_deterministic(self):
        self.assertEqual(_smooth_jitter(0.42, 3.0), _smooth_jitter(0.42, 3.0))
        self.assertEqual(_smooth_jitter(0.0, 2.0), _smooth_jitter(0.0, 2.0))

    def test_motion_target_for_sample_applies_jitter(self):
        # With non-zero depth/range jitter the projected target should
        # differ across two ``jitter_phase`` values that map to distinct
        # smooth-jitter outputs, while the deterministic position mapping
        # itself stays the same. With zero jitter the result is identical.
        target = MotionTarget(60, 50, 70, "stroke")
        style = FrameStyle(name="stroke", depth_jitter=4.0, range_jitter=3.0)
        a = _motion_target_for_sample(50.0, target, style, label="stroke", jitter_phase=0.10)
        b = _motion_target_for_sample(50.0, target, style, label="stroke", jitter_phase=0.30)
        self.assertNotEqual((a.depth, a.stroke_range), (b.depth, b.stroke_range))
        self.assertEqual(a.label, "stroke")

        style_no_jitter = FrameStyle(name="stroke", depth_jitter=0.0, range_jitter=0.0)
        c = _motion_target_for_sample(50.0, target, style_no_jitter, label="stroke", jitter_phase=0.10)
        d = _motion_target_for_sample(50.0, target, style_no_jitter, label="stroke", jitter_phase=0.30)
        self.assertEqual((c.depth, c.stroke_range), (d.depth, d.stroke_range))

    def test_sample_continuous_plan_uses_independent_jitter_cycle(self):
        # The jitter cycle is decoupled from the pattern cycle so jitter
        # does not synchronize with the stroke. Verify by sampling the
        # same plan-cycle phase at two different elapsed times that fall
        # at distinct jitter-cycle phases.
        plan = continuous_motion_plan("stroke")
        # FrameStyles on PATTERNS may or may not declare jitter; force a
        # jitter-bearing style for this test to isolate the new path.
        styled_plan = plan.__class__(
            name=plan.name,
            actions=plan.actions,
            style=FrameStyle(
                name=plan.style.name,
                window_scale=plan.style.window_scale,
                speed_scale=plan.style.speed_scale,
                tempo_scale=plan.style.tempo_scale,
                depth_jitter=5.0,
                range_jitter=3.0,
            ),
            duration_seconds=plan.duration_seconds,
        )
        target = MotionTarget(50, 50, 80, "stroke")
        same_phase_a = sample_continuous_plan(styled_plan, target, 0.25 * styled_plan.duration_seconds)
        same_phase_b = sample_continuous_plan(
            styled_plan,
            target,
            0.25 * styled_plan.duration_seconds + JITTER_CYCLE_SECONDS / 4.0,
        )
        # Same plan-phase, different jitter-phase => same nominal sampled
        # position but different jittered depth/range.
        self.assertNotEqual(
            (round(same_phase_a.depth, 2), round(same_phase_a.stroke_range, 2)),
            (round(same_phase_b.depth, 2), round(same_phase_b.stroke_range, 2)),
        )

    def test_motion_target_for_sample_boosts_speed_from_position_rate(self):
        # Without a ``position_per_second`` hint the sample target uses
        # the LLM-supplied base speed verbatim. With a hint, the per-
        # sample command budget is lifted relative to that base. Slow
        # segments fall back to the base speed; fast segments should not
        # turn a low user speed into an uncapped maximum-speed chase.
        target = MotionTarget(40, 50, 80, "stroke")
        style = FrameStyle(name="stroke")

        base = _motion_target_for_sample(50.0, target, style, label="stroke")
        slow = _motion_target_for_sample(
            50.0, target, style, label="stroke", position_per_second=20.0,
        )
        fast = _motion_target_for_sample(
            50.0, target, style, label="stroke", position_per_second=240.0,
        )

        self.assertEqual(round(base.speed), 40)
        # A slow rate of change should not lower the LLM base speed.
        self.assertGreaterEqual(round(slow.speed), 40)
        # A fast rate of change boosts the per-sample speed above base.
        self.assertGreater(fast.speed, base.speed)
        # The boost is bounded around the user's requested speed instead
        # of jumping directly to the absolute 100% relative ceiling.
        self.assertLessEqual(round(fast.speed), 54)

    def test_motion_target_for_sample_speed_scale_applies_to_segment_boost(self):
        # When the pattern's style declares a non-unit ``speed_scale``,
        # the base speed and relative per-sample boost scale together.
        target = MotionTarget(30, 50, 80, "fast-style")
        style = FrameStyle(name="fast-style", speed_scale=1.5)

        boosted = _motion_target_for_sample(
            50.0, target, style, label="fast-style", position_per_second=160.0,
        )

        # speed_scale=1.5 lifts the base speed to 45, then the tangent
        # multiplier adds per-sample headroom without replacing the user
        # intent with an absolute derivative-derived speed.
        self.assertGreaterEqual(round(boosted.speed), 45)
        self.assertLess(round(boosted.speed), 100)

    def test_sample_continuous_plan_speed_varies_inside_one_cycle(self):
        # A pattern with sharp climbs should produce per-sample command
        # budgets that differ across the cycle, instead of broadcasting
        # a single ``target.speed`` to every HDSP frame. The budget must
        # remain tied to the intent speed, though; otherwise low speed
        # settings still collapse back to maximum XAVA velocity.
        plan = continuous_motion_plan("ramp")
        target = MotionTarget(40, 50, 80, "ramp")

        speeds = [
            round(
                sample_continuous_plan(
                    plan, target, plan.duration_seconds * index / 16.0
                ).speed
            )
            for index in range(16)
        ]

        self.assertGreater(max(speeds) - min(speeds), 5)
        self.assertLessEqual(max(speeds), 54)

    def test_sample_continuous_motion_scales_cadence_from_intent_speed(self):
        plan = continuous_motion_plan("stroke")
        slow_target = MotionTarget(20, 50, 80, "stroke")
        fast_target = MotionTarget(80, 50, 80, "stroke")
        elapsed = plan.duration_seconds * 0.25

        slow = sample_continuous_motion(plan, slow_target, elapsed)
        fast = sample_continuous_motion(plan, fast_target, elapsed)

        self.assertGreater(slow.effective_duration_seconds, fast.effective_duration_seconds)
        self.assertLess(slow.tempo_scale, fast.tempo_scale)
        self.assertNotEqual(round(slow.target.depth), round(fast.target.depth))
        self.assertEqual(round(slow.intent_speed), 20)
        self.assertEqual(round(fast.intent_speed), 80)

    def test_sample_continuous_plan_keeps_base_speed_on_flat_segments(self):
        # A symmetric pattern like ``hold`` spends a meaningful fraction
        # of its cycle near the flat region. Those samples must keep
        # at least the LLM-supplied base speed instead of dropping
        # below it, otherwise quiet segments would feel slower than
        # the user explicitly asked for.
        plan = continuous_motion_plan("hold")
        target = MotionTarget(55, 50, 80, "hold")
        base = target.speed * plan.style.speed_scale

        for index in range(20):
            sampled = sample_continuous_plan(
                plan, target, plan.duration_seconds * index / 20.0
            )
            with self.subTest(index=index):
                self.assertGreaterEqual(round(sampled.speed), round(base))

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

    def test_timing_preserving_motion_pattern_uses_action_intervals(self):
        actions = (
            PatternAction(0, 50),
            PatternAction(100, 95),
            PatternAction(900, 100),
        )
        target = MotionTarget(35, 50, 80, "timed import")

        frames = expand_motion_pattern(
            MotionPattern("timed", actions, tempo_scale=1.0),
            MotionTarget(35, 50, 80),
            target,
            rng=random.Random(17),
            preserve_timing=True,
            base_step_seconds=0.25,
        )
        pattern_frames = [frame for frame in frames if frame.phase == "timed-pattern"]

        self.assertEqual([round(frame.delay_factor, 2) for frame in pattern_frames], [0.0, 0.4, 3.2])
        self.assertGreater(pattern_frames[1].target.speed, pattern_frames[2].target.speed)

    def test_normal_motion_pattern_keeps_existing_normalized_cadence(self):
        actions = (
            PatternAction(0, 50),
            PatternAction(100, 95),
            PatternAction(900, 100),
        )
        target = MotionTarget(35, 50, 80, "normalized")

        frames = expand_motion_pattern(
            MotionPattern("normalized", actions, tempo_scale=1.0),
            MotionTarget(35, 50, 80),
            target,
            rng=random.Random(18),
        )
        pattern_frames = [frame for frame in frames if frame.phase == "pattern"]

        self.assertEqual([round(frame.delay_factor, 2) for frame in pattern_frames], [0.4, 0.33, 1.1])
        self.assertTrue(all(round(frame.target.speed) == 35 for frame in pattern_frames))

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
