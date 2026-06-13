"""Regenerate ``strokegpt/builtin_patterns.json`` from parametric waypoints.

Design contract (from real-device testing and the project motion notes):

- Motion should feel like sliding between soft targets -- slow into a
  target, never stop dead between them. The runtime sampler is a
  time-parameterized monotone cubic (PCHIP), so the waypoints emitted here
  ARE those soft targets: a reversal waypoint gets an exact zero-velocity
  instant, and a "shoulder" waypoint placed off-center inside a travel
  segment skews the velocity profile (fast-in / slow-out) without any
  baked interpolation points.
- Variation must come from changing targets (multi-lobe cycles, drifting
  centers, amplitude breathing), never from vibration-style high-frequency
  oscillation in a tight range, and never from injected jitter.
- Patterns are authored at their real timescale. No ``duration_scale``
  stretching, no ``interpolation_ms`` cosine baking, no ``repeat``
  duplication, no ``depth_jitter``/``range_jitter``.
- Wall-clock smoothness budgets are enforced below by simulating the real
  sampling path: routine patterns must stay under ``ROUTINE_MAX_ACCEL``
  at speed 50, burst-class patterns under ``BURST_MAX_ACCEL``, and no
  routine pattern may reverse direction faster than
  ``ROUTINE_MIN_REVERSAL_GAP_SECONDS``.

Run from the repo root:

    python scripts/generate_builtin_patterns.py            # regenerate + verify
    python scripts/generate_builtin_patterns.py --check    # verify only
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

OUTPUT_PATH = REPO_ROOT / "strokegpt" / "builtin_patterns.json"

ROUTINE_MAX_ACCEL = 700.0
BURST_MAX_ACCEL = 2600.0
ROUTINE_MIN_REVERSAL_GAP_SECONDS = 0.45
PROFILE_SPEED = 50

BURST_CLASS = frozenset({
    "flick",
    "flutter",
    "milking-short-burst",
    "milking-fast-middle",
    "edge-shallow-snap",
})


def _wp(points):
    """Round and validate a waypoint list into action dicts."""
    actions = []
    for t, pos in points:
        actions.append({"at": int(round(t)), "pos": round(max(0.0, min(100.0, pos)), 1)})
    deduped = []
    for action in actions:
        if deduped and action["at"] <= deduped[-1]["at"]:
            action = {"at": deduped[-1]["at"] + 1, "pos": action["pos"]}
        deduped.append(action)
    return deduped


def lobe(t0, duration, start, peak, *, skew=0.5, shoulder=None):
    """One travel-out-and-back lobe: start -> peak -> start.

    ``skew`` places the peak inside the lobe (0.5 = symmetric). ``shoulder``
    optionally adds velocity-shaping points: a pair of fractions
    ``(out_frac, back_frac)`` placing one shoulder on each leg at 60% of the
    travel, which makes the approach to the peak decelerate earlier (the
    inertia feel) without ever flattening to a stop.
    """
    peak_t = t0 + duration * skew
    points = [(t0, start)]
    if shoulder:
        out_frac, back_frac = shoulder
        points.append((t0 + (peak_t - t0) * out_frac, start + (peak - start) * 0.6))
    points.append((peak_t, peak))
    if shoulder:
        out_frac, back_frac = shoulder
        points.append((peak_t + (t0 + duration - peak_t) * back_frac, peak - (peak - start) * 0.6))
    return points


def multi_lobe(total_ms, lobes):
    """Sequence lobes back-to-back. Each lobe: (weight, start, peak, skew[, shoulder]).

    Weights are normalized against the total duration. The cycle closes back
    to the first lobe's start position for a clean loop.
    """
    weight_sum = float(sum(entry[0] for entry in lobes))
    points = []
    cursor = 0.0
    for entry in lobes:
        weight, start, peak, skew = entry[0], entry[1], entry[2], entry[3]
        shoulder = entry[4] if len(entry) > 4 else None
        duration = total_ms * (weight / weight_sum)
        points.extend(lobe(cursor, duration, start, peak, skew=skew, shoulder=shoulder))
        cursor += duration
    points.append((total_ms, lobes[0][1]))
    return _wp(points)


def normalize_span(actions):
    """Rescale positions so every pattern spans the full 0-100 range.

    The projection pipeline treats pattern positions as *relative*: the
    sampler maps ``pos`` onto the live target window
    (``depth +/- stroke_range/2``), so depth-band character must come from
    cue defaults and mode-arc targets, never from the authored positions.
    Band-authored patterns get windowed twice and collapse to a few units
    of real motion -- the "barely moves, just twitches" failure observed
    on-device in patterned modes.
    """
    positions = [action["pos"] for action in actions]
    low, high = min(positions), max(positions)
    span = max(1.0, high - low)
    return [
        {"at": action["at"], "pos": round((action["pos"] - low) * 100.0 / span, 1)}
        for action in actions
    ]


def pattern(name, actions, *, window_scale=0.3, speed_scale=1.0):
    return {
        "name": name,
        "actions": normalize_span(actions),
        "window_scale": window_scale,
        "speed_scale": speed_scale,
        "min_interval_ms": 0,
    }


def build_catalog():
    catalog = {}

    # ── general strokes ────────────────────────────────────────────────
    catalog["stroke"] = pattern(
        "stroke",
        multi_lobe(4500, [
            (1.0, 10, 90, 0.55, (0.55, 0.45)),
        ]),
        window_scale=0.42,
    )
    catalog["glide"] = pattern(
        "glide",
        multi_lobe(8000, [
            (1.0, 8, 92, 0.5, (0.4, 0.4)),
        ]),
        window_scale=0.46,
        speed_scale=0.9,
    )
    catalog["wave"] = pattern(
        "wave",
        multi_lobe(6500, [
            (1.0, 18, 78, 0.5),
            (1.2, 8, 92, 0.5, (0.5, 0.5)),
            (0.9, 26, 70, 0.5),
        ]),
        window_scale=0.4,
    )
    catalog["surge"] = pattern(
        "surge",
        multi_lobe(7000, [
            # slow accelerating push deep, quicker rebound, settling echo
            (1.5, 12, 88, 0.62, (0.3, 0.6)),
            (1.0, 20, 72, 0.45),
        ]),
        window_scale=0.38,
        speed_scale=1.05,
    )
    catalog["sway"] = pattern(
        "sway",
        multi_lobe(7500, [
            (1.0, 32, 66, 0.5),
            (1.1, 36, 72, 0.5),
            (1.0, 28, 62, 0.5),
        ]),
        window_scale=0.42,
        speed_scale=0.9,
    )
    catalog["milk"] = pattern(
        "milk",
        multi_lobe(6400, [
            # quick drop deep, slow draw back up: base-weighted milking pull
            (1.0, 15, 88, 0.38, (0.5, 0.45)),
            (1.0, 12, 92, 0.38, (0.5, 0.45)),
        ]),
        window_scale=0.5,
        speed_scale=1.02,
    )
    catalog["tease"] = pattern(
        "tease",
        multi_lobe(8200, [
            (1.0, 12, 34, 0.5),
            (0.9, 15, 38, 0.5),
            (1.3, 10, 70, 0.55, (0.5, 0.5)),
            (0.8, 14, 32, 0.5),
        ]),
        window_scale=0.3,
        speed_scale=0.78,
    )
    catalog["feather"] = pattern(
        "feather",
        multi_lobe(6000, [
            (1.0, 8, 26, 0.5),
            (1.1, 10, 30, 0.5),
            (0.9, 6, 22, 0.5),
        ]),
        window_scale=0.24,
        speed_scale=0.72,
    )
    catalog["flick"] = pattern(
        "flick",
        multi_lobe(5600, [
            (1.3, 15, 40, 0.5),
            (0.6, 18, 56, 0.45),
            (1.2, 14, 38, 0.5),
            (0.6, 16, 58, 0.45),
        ]),
        window_scale=0.3,
        speed_scale=1.1,
    )
    catalog["pulse"] = pattern(
        "pulse",
        multi_lobe(5800, [
            (1.0, 35, 72, 0.5),
            (1.0, 38, 75, 0.5),
            (1.3, 30, 88, 0.5, (0.5, 0.5)),
        ]),
        window_scale=0.34,
    )
    catalog["hold"] = pattern(
        "hold",
        multi_lobe(7000, [
            # deep slow small rolls: pressure without a dead stop
            (1.0, 62, 86, 0.5),
            (1.1, 58, 82, 0.5),
            (1.0, 64, 88, 0.5),
        ]),
        window_scale=0.32,
        speed_scale=0.8,
    )
    catalog["plunge"] = pattern(
        "plunge",
        multi_lobe(6000, [
            # long slow traverse near base, easy lift
            (1.0, 12, 95, 0.6, (0.35, 0.55)),
        ]),
        window_scale=0.46,
    )
    catalog["ramp"] = pattern(
        "ramp",
        multi_lobe(9000, [
            (1.0, 35, 58, 0.5),
            (1.0, 28, 72, 0.5),
            (1.2, 16, 90, 0.5, (0.5, 0.5)),
            (0.8, 30, 55, 0.5),
        ]),
        window_scale=0.36,
    )
    catalog["crest"] = pattern(
        "crest",
        multi_lobe(8000, [
            (1.0, 25, 65, 0.5),
            (1.5, 18, 84, 0.5),
            (2.0, 10, 90, 0.5),
            (1.0, 22, 60, 0.5),
        ]),
        window_scale=0.4,
    )
    catalog["ladder"] = pattern(
        "ladder",
        _wp([
            (0, 25),
            (900, 48), (1500, 38),
            (2400, 62), (3000, 50),
            (3900, 78), (4500, 64),
            (5400, 90),
            (6600, 45),
            (8000, 25),
        ]),
        window_scale=0.36,
    )
    catalog["flutter"] = pattern(
        "flutter",
        multi_lobe(4500, [
            (1.0, 20, 40, 0.5),
            (0.9, 22, 42, 0.5),
            (1.0, 18, 38, 0.5),
            (0.9, 24, 44, 0.5),
            (1.0, 20, 40, 0.5),
        ]),
        window_scale=0.26,
        speed_scale=1.08,
    )

    # ── milking mode ───────────────────────────────────────────────────
    catalog["milking-pressure-build"] = pattern(
        "Milking Pressure Build",
        multi_lobe(7000, [
            (1.0, 35, 65, 0.5),
            (1.0, 30, 78, 0.5),
            (1.2, 25, 90, 0.5, (0.5, 0.45)),
        ]),
        window_scale=0.44,
    )
    catalog["milking-wide-pressure"] = pattern(
        "Milking Wide Pressure",
        multi_lobe(8000, [
            (1.0, 10, 92, 0.55, (0.5, 0.4)),
            (1.0, 14, 95, 0.55, (0.5, 0.4)),
        ]),
        window_scale=0.52,
    )
    catalog["milking-deep-pulse"] = pattern(
        "Milking Deep Pulse",
        multi_lobe(5800, [
            (1.0, 55, 88, 0.5),
            (1.0, 52, 90, 0.5),
            (1.0, 58, 92, 0.5),
        ]),
        window_scale=0.36,
    )
    catalog["milking-fast-middle"] = pattern(
        "Milking Fast Middle",
        multi_lobe(4000, [
            (1.0, 30, 68, 0.5),
            (1.0, 32, 72, 0.5),
            (1.0, 28, 70, 0.5),
        ]),
        window_scale=0.34,
        speed_scale=1.1,
    )
    catalog["milking-deep-finish"] = pattern(
        "Milking Deep Finish",
        multi_lobe(6000, [
            (1.4, 20, 95, 0.6, (0.4, 0.5)),
            (1.0, 35, 88, 0.45),
        ]),
        window_scale=0.48,
    )
    catalog["milking-recover"] = pattern(
        "Milking Recover",
        multi_lobe(8500, [
            (1.0, 35, 62, 0.5),
            (1.1, 38, 58, 0.5),
            (1.2, 40, 54, 0.5),
        ]),
        window_scale=0.3,
        speed_scale=0.75,
    )
    catalog["milking-steady-press"] = pattern(
        "Milking Steady Press",
        multi_lobe(7500, [
            (1.0, 50, 85, 0.5),
            (1.0, 48, 84, 0.5),
            (1.0, 52, 86, 0.5),
        ]),
        window_scale=0.4,
    )
    catalog["milking-short-burst"] = pattern(
        "Milking Short Burst",
        multi_lobe(4200, [
            (1.0, 35, 78, 0.45),
            (0.9, 38, 80, 0.45),
            (1.0, 34, 76, 0.45),
        ]),
        window_scale=0.36,
        speed_scale=1.12,
    )
    catalog["milking-full-drive"] = pattern(
        "Milking Full Drive",
        multi_lobe(6500, [
            (1.0, 8, 94, 0.55, (0.5, 0.4)),
            (1.0, 12, 92, 0.55, (0.5, 0.4)),
        ]),
        window_scale=0.52,
        speed_scale=1.05,
    )
    catalog["milking-deep-squeeze"] = pattern(
        "Milking Deep Squeeze",
        multi_lobe(6000, [
            (1.0, 70, 92, 0.5),
            (1.2, 66, 90, 0.5),
        ]),
        window_scale=0.26,
        speed_scale=0.8,
    )
    catalog["milking-final-wave"] = pattern(
        "Milking Final Wave",
        multi_lobe(7800, [
            (1.0, 30, 72, 0.5),
            (1.1, 20, 86, 0.5),
            (1.3, 10, 96, 0.55, (0.5, 0.5)),
        ]),
        window_scale=0.5,
    )

    # ── edge mode (close-signal / explicit edge feedback only) ─────────
    catalog["edge-build-low"] = pattern(
        "Edge Build Low",
        multi_lobe(6500, [
            (1.0, 58, 78, 0.5),
            (1.1, 55, 82, 0.5),
        ]),
        window_scale=0.3,
        speed_scale=0.8,
    )
    catalog["edge-build-mid"] = pattern(
        "Edge Build Mid",
        multi_lobe(6000, [
            (1.0, 40, 62, 0.5),
            (1.0, 38, 66, 0.5),
            (1.0, 42, 68, 0.5),
        ]),
        window_scale=0.3,
    )
    catalog["edge-hold"] = pattern(
        "Edge Hold",
        multi_lobe(7000, [
            (1.0, 55, 70, 0.5),
            (1.2, 52, 68, 0.5),
        ]),
        window_scale=0.24,
        speed_scale=0.72,
    )
    catalog["edge-tip-tease"] = pattern(
        "Edge Tip Tease",
        multi_lobe(6000, [
            (1.0, 10, 28, 0.5),
            (1.0, 12, 32, 0.5),
            (1.2, 8, 46, 0.55),
        ]),
        window_scale=0.24,
        speed_scale=0.8,
    )
    catalog["edge-recover"] = pattern(
        "Edge Recover",
        multi_lobe(8000, [
            (1.0, 40, 60, 0.5),
            (1.1, 42, 56, 0.5),
            (1.2, 44, 54, 0.5),
        ]),
        window_scale=0.26,
        speed_scale=0.7,
    )
    catalog["edge-slow-wide"] = pattern(
        "Edge Slow Wide",
        multi_lobe(10000, [
            (1.0, 15, 85, 0.5, (0.45, 0.45)),
            (1.1, 18, 82, 0.5, (0.45, 0.45)),
        ]),
        window_scale=0.46,
        speed_scale=0.8,
    )
    catalog["edge-shallow-snap"] = pattern(
        "Edge Shallow Snap",
        multi_lobe(5600, [
            (1.3, 14, 30, 0.5),
            (0.7, 12, 38, 0.45),
            (1.2, 15, 28, 0.5),
            (0.8, 13, 36, 0.45),
        ]),
        window_scale=0.24,
        speed_scale=1.0,
    )
    catalog["edge-middle-hold"] = pattern(
        "Edge Middle Hold",
        multi_lobe(7000, [
            (1.0, 45, 60, 0.5),
            (1.2, 44, 58, 0.5),
        ]),
        window_scale=0.22,
        speed_scale=0.7,
    )
    catalog["edge-deeper-risk"] = pattern(
        "Edge Deeper Risk",
        multi_lobe(7000, [
            (1.0, 50, 74, 0.5),
            (1.0, 48, 80, 0.5),
            (1.1, 52, 86, 0.5),
        ]),
        window_scale=0.32,
        speed_scale=0.85,
    )
    catalog["edge-pull-back"] = pattern(
        "Edge Pull Back",
        _wp([
            (0, 85),
            (1400, 45),
            (2600, 22),
            (3600, 32),
            (4600, 20),
            (6000, 85),
        ]),
        window_scale=0.3,
        speed_scale=0.75,
    )
    catalog["edge-restart"] = pattern(
        "Edge Restart",
        multi_lobe(6000, [
            (1.0, 42, 58, 0.5),
            (1.0, 36, 66, 0.5),
            (1.1, 28, 76, 0.5),
        ]),
        window_scale=0.32,
        speed_scale=0.85,
    )

    return catalog


def profile_catalog(catalog):
    """Simulate the real sampling path and enforce smoothness budgets."""
    from strokegpt.motion import MotionTarget
    from strokegpt.motion_patterns import (
        MotionPattern,
        PatternAction,
        continuous_motion_plan_from_pattern,
        sample_continuous_motion,
    )

    failures = []
    rows = []
    for pattern_id, payload in catalog.items():
        actions = tuple(PatternAction(a["at"], a["pos"]) for a in payload["actions"])
        motion_pattern = MotionPattern(
            payload["name"],
            actions,
            window_scale=payload.get("window_scale", 0.3),
            speed_scale=payload.get("speed_scale", 1.0),
            min_interval_ms=payload.get("min_interval_ms", 0),
        )
        plan = continuous_motion_plan_from_pattern(motion_pattern)
        if plan is None:
            failures.append(f"{pattern_id}: no continuous plan")
            continue
        target = MotionTarget(PROFILE_SPEED, 50, 80, "catalog profile")
        duration = plan.duration_seconds
        sample_count = max(240, int(duration * 100))
        dt = duration / sample_count
        depths = [
            sample_continuous_motion(plan, target, duration * index / sample_count).target.depth
            for index in range(sample_count + 1)
        ]
        velocities = [(depths[i + 1] - depths[i]) / dt for i in range(sample_count)]
        max_accel = max(
            abs(velocities[i + 1] - velocities[i]) / dt for i in range(sample_count - 1)
        )
        reversals = []
        last_direction = 0
        for index in range(sample_count):
            direction = 1 if velocities[index] > 2 else (-1 if velocities[index] < -2 else 0)
            if direction and last_direction and direction != last_direction:
                reversals.append(index * dt)
            if direction:
                last_direction = direction
        gaps = [reversals[i + 1] - reversals[i] for i in range(len(reversals) - 1)] or [duration]
        min_gap = min(gaps)
        burst = pattern_id in BURST_CLASS
        accel_budget = BURST_MAX_ACCEL if burst else ROUTINE_MAX_ACCEL
        rows.append((pattern_id, duration, max_accel, min_gap, burst))
        if max_accel > accel_budget:
            failures.append(
                f"{pattern_id}: max accel {max_accel:.0f} > {accel_budget:.0f}"
            )
        if not burst and min_gap < ROUTINE_MIN_REVERSAL_GAP_SECONDS:
            failures.append(
                f"{pattern_id}: reversal gap {min_gap:.2f}s < {ROUTINE_MIN_REVERSAL_GAP_SECONDS}s"
            )
        # Mirror the catalog guardrail test: fixed 25ms sampling, so the
        # step budget is a uniform velocity cap (120 pos/s routine,
        # 300 pos/s burst) instead of a per-cycle cap that loosens for
        # short twitchy cycles and strangles long luxurious sweeps.
        step_count = max(2, int(round(duration / 0.025)))
        coarse = [
            sample_continuous_motion(plan, target, duration * index / step_count).target.depth
            for index in range(step_count + 1)
        ]
        max_step = max(abs(coarse[i + 1] - coarse[i]) for i in range(step_count))
        step_budget = 7.5 if burst else 3.0
        if max_step >= step_budget:
            failures.append(
                f"{pattern_id}: 25ms step {max_step:.2f} >= {step_budget}"
            )
        positions = [action["pos"] for action in payload["actions"]]
        if min(positions) > 0.1 or max(positions) < 99.9:
            failures.append(
                f"{pattern_id}: positions {min(positions)}-{max(positions)} must span 0-100"
            )

    print(f"{'pattern':26s} {'cyc_s':>6s} {'maxA':>6s} {'minRev':>7s}  class")
    for pattern_id, duration, max_accel, min_gap, burst in sorted(rows, key=lambda r: -r[2]):
        print(
            f"{pattern_id:26s} {duration:6.2f} {max_accel:6.0f} {min_gap:7.2f}  "
            f"{'burst' if burst else 'routine'}"
        )
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the existing file only")
    args = parser.parse_args()

    catalog = build_catalog()
    failures = profile_catalog(catalog)
    if failures:
        print("\nBUDGET FAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    if args.check:
        existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        if existing != catalog:
            print("\nbuiltin_patterns.json is out of date; rerun without --check")
            return 1
        print("\nbuiltin_patterns.json matches the generator output")
        return 0

    OUTPUT_PATH.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUTPUT_PATH} ({len(catalog)} patterns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
