"""Contract tests for the built-in motion pattern catalog.

The catalog data lives in ``strokegpt/builtin_patterns.json`` and is
materialized into the in-memory ``PATTERNS`` dict by
``motion_patterns._load_builtin_patterns()`` at import time. These tests
lock the JSON shape, the loader output, and the representative pattern
endpoints so future edits cannot silently change pattern IDs, action
timing, or position values that the runtime relies on.
"""

import json
import unittest
from pathlib import Path

from strokegpt import motion_patterns
from strokegpt.motion_patterns import (
    PATTERNS,
    MotionPattern,
    PatternAction,
    continuous_motion_plan,
    continuous_plan_phase_points,
    continuous_plan_timed_phase_points,
    sample_continuous_motion,
    _load_builtin_patterns,
)
from strokegpt.motion import MotionTarget


EXPECTED_PATTERN_IDS = frozenset({"stroke", "pulse", "tease"})


ALLOWED_STYLE_FIELDS = frozenset({
    "name",
    "description",
    "tags",
    "actions",
    "window_scale",
    "speed_scale",
    "tempo_profile",
    "tempo_scale",
    "duration_scale",
    "depth_jitter",
    "range_jitter",
    "repeat",
    "min_interval_ms",
    "interpolation_ms",
    "interpolation",
    "max_step_delta",
})


def _data_path() -> Path:
    return Path(motion_patterns.__file__).parent / "builtin_patterns.json"


class BuiltinPatternCatalogTests(unittest.TestCase):
    def test_pattern_id_set_is_locked(self):
        self.assertEqual(set(PATTERNS.keys()), EXPECTED_PATTERN_IDS)

    def test_every_pattern_has_at_least_two_actions(self):
        for pattern_id, pattern in PATTERNS.items():
            with self.subTest(pattern_id=pattern_id):
                self.assertGreaterEqual(len(pattern.actions), 2)
                for action in pattern.actions:
                    self.assertIsInstance(action, PatternAction)

    def test_loader_returns_a_fresh_dict_each_call(self):
        first = _load_builtin_patterns()
        second = _load_builtin_patterns()

        # The cached module-level PATTERNS is the eager import-time
        # materialization; each explicit loader call returns its own
        # fresh dict so callers can safely mutate test copies without
        # disturbing the runtime catalog.
        self.assertIsNot(first, second)
        self.assertIsNot(first, PATTERNS)
        self.assertEqual(set(first.keys()), set(PATTERNS.keys()))
        for pattern_id, pattern in PATTERNS.items():
            self.assertEqual(first[pattern_id], pattern)

    def test_patterns_match_magic_handy_source_definitions(self):
        expected = {
            "stroke": [0, 100, 0, 100, 0, 100, 0, 100, 0, 100, 0, 100, 0],
            "pulse": [15, 100, 25, 85, 15, 100, 25, 85, 15, 100, 25, 85, 15],
            "tease": [20, 45, 20, 60, 20, 80, 20, 100, 20, 75, 20, 55, 20],
        }
        metadata = {
            "stroke": ("Stroke", "Even full-span reversals.", ("steady", "full", "balanced")),
            "pulse": ("Pulse", "Alternating deep and shorter peaks.", ("rhythmic", "varied", "peaks")),
            "tease": ("Tease", "Progressive peaks with a consistent return.", ("progressive", "varied", "build")),
        }
        for pattern_id, positions in expected.items():
            with self.subTest(pattern_id=pattern_id):
                pattern = PATTERNS[pattern_id]
                self.assertEqual(pattern.name, metadata[pattern_id][0])
                self.assertEqual(pattern.description, metadata[pattern_id][1])
                self.assertEqual(pattern.tags, metadata[pattern_id][2])
                self.assertEqual([action.at for action in pattern.actions], list(range(0, 6601, 550)))
                self.assertEqual([action.pos for action in pattern.actions], positions)
                self.assertEqual(pattern.window_scale, 1.0)
                self.assertEqual(pattern.tempo_profile, "magic_handy")
                self.assertEqual(pattern.min_interval_ms, 0)

    def test_motion_pattern_duration_ms_uses_prepared_actions(self):
        # ``MotionPattern.duration_ms`` runs ``prepare_pattern_actions``
        # against the JSON-materialized catalog. Pin a couple of values
        # so future tweaks to the loader path cannot silently shift
        # pattern duration.
        self.assertEqual(PATTERNS["stroke"].duration_ms, 6600)
        self.assertEqual(PATTERNS["pulse"].duration_ms, 6600)

    def test_json_data_file_only_uses_known_fields(self):
        # The loader silently skips unknown fields, so this test catches
        # accidental misspellings (e.g. ``windowscale`` vs
        # ``window_scale``) before they reach production by failing
        # loudly when the JSON gains an unrecognized key.
        with _data_path().open(encoding="utf-8") as handle:
            raw = json.load(handle)

        for pattern_id, payload in raw.items():
            with self.subTest(pattern_id=pattern_id):
                extra = set(payload.keys()) - ALLOWED_STYLE_FIELDS
                self.assertEqual(extra, set(), f"unknown field(s) in {pattern_id}: {extra}")
                self.assertIn("actions", payload)
                self.assertGreaterEqual(len(payload["actions"]), 2)
                for action in payload["actions"]:
                    self.assertIn("at", action)
                    self.assertIn("pos", action)

    def test_json_data_file_pattern_ids_match_loader_output(self):
        with _data_path().open(encoding="utf-8") as handle:
            raw = json.load(handle)

        self.assertEqual(set(raw.keys()), set(PATTERNS.keys()))

    def test_continuous_builtin_loops_have_no_visible_sample_seam(self):
        target = MotionTarget(50, 50, 80, "catalog guard")
        for pattern_id in PATTERNS:
            with self.subTest(pattern_id=pattern_id):
                plan = continuous_motion_plan(pattern_id)
                self.assertIsNotNone(plan)
                first = sample_continuous_motion(plan, target, 0.0).target.depth
                last = sample_continuous_motion(
                    plan,
                    target,
                    max(0.0, plan.duration_seconds - 0.001),
                ).target.depth
                self.assertLess(abs(first - last), 1.0)

    def test_continuous_builtin_samples_do_not_have_abrupt_depth_steps(self):
        # Fixed 25ms sampling catches source or sampler changes that would make
        # one of the baseline loops jump between transport points.
        target = MotionTarget(50, 50, 80, "catalog guard")
        for pattern_id in PATTERNS:
            with self.subTest(pattern_id=pattern_id):
                plan = continuous_motion_plan(pattern_id)
                sample_count = max(2, int(round(plan.duration_seconds / 0.025)))
                depths = [
                    sample_continuous_motion(
                        plan,
                        target,
                        plan.duration_seconds * index / sample_count,
                    ).target.depth
                    for index in range(sample_count + 1)
                ]
                largest_step = max(
                    abs(depths[index + 1] - depths[index])
                    for index in range(sample_count)
                )
                self.assertLess(largest_step, 6.0)

    def test_continuous_timed_phase_points_keep_dense_transport_spacing(self):
        for pattern_id in PATTERNS:
            with self.subTest(pattern_id=pattern_id):
                plan = continuous_motion_plan(pattern_id)
                phase_points = continuous_plan_phase_points(plan)
                timed_points = continuous_plan_timed_phase_points(plan, plan.duration_seconds)
                self.assertGreaterEqual(len(timed_points), len(phase_points))
                self.assertTrue(timed_points[0]["authored"])
                self.assertTrue(timed_points[-1]["authored"])
                largest_gap = max(
                    (timed_points[index + 1]["phase"] - timed_points[index]["phase"])
                    * plan.duration_seconds
                    for index in range(len(timed_points) - 1)
                )
                self.assertLessEqual(largest_gap, 0.121)


if __name__ == "__main__":
    unittest.main()
