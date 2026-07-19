"""Regenerate the built-in catalog from MagicHandy's three baseline loops.

The source definitions are intentionally transcribed without position
normalization, interpolation points, or style transforms. StrokeGPT's runtime
uses the same wall-time monotone cubic sampler as MagicHandy, so these sparse
control points are the complete authored pattern contract.

Run from the repo root:

    python scripts/generate_builtin_patterns.py
    python scripts/generate_builtin_patterns.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

OUTPUT_PATH = REPO_ROOT / "strokegpt" / "builtin_patterns.json"
CYCLE_MS = 6600
KNOT_INTERVAL_MS = 550
EXPECTED_IDS = ("stroke", "pulse", "tease")
MAX_25MS_DEPTH_STEP = 7.0


def _actions(positions):
    return [
        {"at": index * KNOT_INTERVAL_MS, "pos": float(position)}
        for index, position in enumerate(positions)
    ]


def _pattern(name, description, tags, positions):
    return {
        "name": name,
        "description": description,
        "tags": tags,
        "actions": _actions(positions),
        "window_scale": 1.0,
        "speed_scale": 1.0,
        "tempo_profile": "magic_handy",
        "min_interval_ms": 0,
    }


def build_catalog():
    return {
        "stroke": _pattern(
            "Stroke",
            "Even full-span reversals.",
            ["steady", "full", "balanced"],
            [0, 100, 0, 100, 0, 100, 0, 100, 0, 100, 0, 100, 0],
        ),
        "pulse": _pattern(
            "Pulse",
            "Alternating deep and shorter peaks.",
            ["rhythmic", "varied", "peaks"],
            [15, 100, 25, 85, 15, 100, 25, 85, 15, 100, 25, 85, 15],
        ),
        "tease": _pattern(
            "Tease",
            "Progressive peaks with a consistent return.",
            ["progressive", "varied", "build"],
            [20, 45, 20, 60, 20, 80, 20, 100, 20, 75, 20, 55, 20],
        ),
    }


def profile_catalog(catalog):
    """Verify exact source knots through StrokeGPT's playback sampler."""
    from strokegpt.motion import MotionTarget
    from strokegpt.motion_patterns import (
        MotionPattern,
        PatternAction,
        continuous_motion_plan_from_pattern,
        sample_continuous_motion,
    )

    failures = []
    target = MotionTarget(100, 50, 100, "catalog profile")
    if tuple(catalog) != EXPECTED_IDS:
        failures.append(f"catalog IDs must be exactly {EXPECTED_IDS!r}")

    for pattern_id, payload in catalog.items():
        actions = tuple(PatternAction(action["at"], action["pos"]) for action in payload["actions"])
        if len(actions) != 13:
            failures.append(f"{pattern_id}: expected 13 source knots")
        if actions[0].at != 0 or actions[-1].at != CYCLE_MS:
            failures.append(f"{pattern_id}: expected exact 0..{CYCLE_MS}ms timing")
        if actions[0].pos != actions[-1].pos:
            failures.append(f"{pattern_id}: loop is not closed")
        if any(right.at - left.at != KNOT_INTERVAL_MS for left, right in zip(actions, actions[1:])):
            failures.append(f"{pattern_id}: source knots must stay {KNOT_INTERVAL_MS}ms apart")

        plan = continuous_motion_plan_from_pattern(
            MotionPattern(
                payload["name"],
                actions,
                description=payload["description"],
                tags=tuple(payload["tags"]),
                window_scale=payload["window_scale"],
                speed_scale=payload["speed_scale"],
                tempo_profile=payload["tempo_profile"],
                min_interval_ms=payload["min_interval_ms"],
            )
        )
        if plan is None:
            failures.append(f"{pattern_id}: playback plan is unavailable")
            continue
        sample = sample_continuous_motion(plan, target, 0.0)
        if abs(sample.effective_duration_seconds - 6.6) > 1e-9:
            failures.append(f"{pattern_id}: playback plan must preserve the 6.6s cycle")
            continue
        sample_count = 264
        depths = [
            sample_continuous_motion(
                plan,
                target,
                sample.effective_duration_seconds * index / sample_count,
            ).target.depth
            for index in range(sample_count + 1)
        ]
        largest_step = max(abs(right - left) for left, right in zip(depths, depths[1:]))
        if largest_step >= MAX_25MS_DEPTH_STEP:
            failures.append(f"{pattern_id}: 25ms depth step {largest_step:.2f} is too large")
        dt = sample.effective_duration_seconds / sample_count
        velocities = [(right - left) / dt for left, right in zip(depths, depths[1:])]
        max_acceleration = max(
            abs(right - left) / dt for left, right in zip(velocities, velocities[1:])
        )
        if max_acceleration > 3000.0:
            failures.append(f"{pattern_id}: acceleration {max_acceleration:.0f} exceeds 3000")

    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the existing file only")
    args = parser.parse_args()

    catalog = build_catalog()
    failures = profile_catalog(catalog)
    if failures:
        print("CATALOG FAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    if args.check:
        existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        if existing != catalog:
            print("builtin_patterns.json is out of date; rerun without --check")
            return 1
        print("builtin_patterns.json matches the MagicHandy source definitions")
        return 0

    OUTPUT_PATH.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({len(catalog)} patterns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
