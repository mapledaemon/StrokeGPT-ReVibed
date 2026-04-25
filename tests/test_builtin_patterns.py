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
    _load_builtin_patterns,
)


EXPECTED_PATTERN_IDS = frozenset({
    "stroke",
    "flick",
    "milk",
    "pulse",
    "hold",
    "wave",
    "ramp",
    "tease",
    "flutter",
    "ladder",
    "surge",
    "sway",
    "milking-pressure-build",
    "milking-wide-pressure",
    "milking-deep-pulse",
    "milking-fast-middle",
    "milking-deep-finish",
    "milking-recover",
    "milking-steady-press",
    "milking-short-burst",
    "milking-full-drive",
    "milking-deep-squeeze",
    "milking-final-wave",
    "edge-build-low",
    "edge-build-mid",
    "edge-hold",
    "edge-tip-tease",
    "edge-recover",
    "edge-slow-wide",
    "edge-shallow-snap",
    "edge-middle-hold",
    "edge-deeper-risk",
    "edge-pull-back",
    "edge-restart",
})


ALLOWED_STYLE_FIELDS = frozenset({
    "name",
    "actions",
    "window_scale",
    "speed_scale",
    "tempo_scale",
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

    def test_stroke_pattern_endpoints_match_expected_shape(self):
        stroke = PATTERNS["stroke"]
        self.assertEqual(stroke.name, "stroke")
        self.assertEqual(len(stroke.actions), 3)
        self.assertEqual((stroke.actions[0].at, stroke.actions[0].pos), (0, 0.0))
        self.assertEqual((stroke.actions[-1].at, stroke.actions[-1].pos), (900, 0.0))
        self.assertEqual(stroke.window_scale, 0.35)
        self.assertEqual(stroke.interpolation_ms, 160)

    def test_milk_pattern_endpoints_match_expected_shape(self):
        milk = PATTERNS["milk"]
        self.assertEqual(len(milk.actions), 5)
        self.assertEqual(milk.actions[0].at, 0)
        self.assertEqual(milk.actions[-1].at, 1280)
        self.assertEqual(milk.actions[0].pos, 4.0)
        self.assertEqual(milk.actions[-1].pos, 6.0)
        self.assertEqual(milk.window_scale, 0.92)

    def test_edge_build_low_pattern_endpoints_match_expected_shape(self):
        pattern = PATTERNS["edge-build-low"]
        self.assertGreaterEqual(len(pattern.actions), 2)
        self.assertEqual(pattern.actions[0].at, 0)
        self.assertGreater(pattern.actions[-1].at, pattern.actions[0].at)

    def test_motion_pattern_duration_ms_uses_prepared_actions(self):
        # ``MotionPattern.duration_ms`` runs ``prepare_pattern_actions``
        # against the JSON-materialized catalog. Pin a couple of values
        # so future tweaks to the loader path cannot silently shift
        # pattern duration.
        self.assertEqual(PATTERNS["stroke"].duration_ms, 900)
        self.assertEqual(PATTERNS["milk"].duration_ms, 1280)

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


if __name__ == "__main__":
    unittest.main()
