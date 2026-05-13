import json
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from .motion_anchors import AnchorProgram, coerce_anchor_program
from .motion import MotionTarget


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def _clean_label(value: str) -> str:
    return " ".join(str(value or "").split()).strip().lower()


@dataclass(frozen=True)
class PatternAction:
    at: int
    pos: float


@dataclass(frozen=True)
class MotionPattern:
    name: str
    actions: tuple[PatternAction, ...]
    window_scale: float = 0.3
    speed_scale: float = 1.0
    tempo_scale: float = 1.0
    depth_jitter: float = 0.0
    range_jitter: float = 0.0
    repeat: int = 1
    min_interval_ms: int = 60
    interpolation_ms: int = 0
    interpolation: str = "cosine"
    max_step_delta: float = 0.0

    @property
    def duration_ms(self) -> int:
        actions = prepare_pattern_actions(self)
        if not actions:
            return 0
        return _duration_ms(actions)


@dataclass(frozen=True)
class PatternFrame:
    target: MotionTarget
    delay_factor: float
    phase: str = "pattern"


@dataclass(frozen=True)
class FrameStyle:
    name: str
    window_scale: float = 0.3
    speed_scale: float = 1.0
    tempo_scale: float = 1.0
    depth_jitter: float = 0.0
    range_jitter: float = 0.0


@dataclass(frozen=True)
class ContinuousMotionPlan:
    """Phase-domain motion basis for live controller sampling."""

    name: str
    actions: tuple[PatternAction, ...]
    style: FrameStyle
    duration_seconds: float
    normalized_range: tuple[float, float] = (0.0, 100.0)


def _duration_ms(actions: tuple[PatternAction, ...]) -> int:
    if not actions:
        return 0
    return max(1, actions[-1].at - actions[0].at)


def _coerce_action(action: Any) -> Optional[PatternAction]:
    if isinstance(action, PatternAction):
        return PatternAction(int(action.at), _clamp(float(action.pos)))
    if isinstance(action, dict):
        try:
            return PatternAction(int(action["at"]), _clamp(float(action["pos"])))
        except (KeyError, TypeError, ValueError):
            return None
    return None


def normalize_actions(actions: Iterable[Any], min_interval_ms: int = 0) -> tuple[PatternAction, ...]:
    coerced = [action for action in (_coerce_action(action) for action in actions) if action is not None]
    if not coerced:
        return ()

    coerced.sort(key=lambda action: action.at)
    unique = [coerced[0]]
    for action in coerced[1:]:
        if action.at == unique[-1].at:
            unique[-1] = action
        else:
            unique.append(action)

    if min_interval_ms <= 0 or len(unique) <= 2:
        return tuple(unique)

    filtered = [unique[0]]
    for action in unique[1:-1]:
        if action.at - filtered[-1].at >= min_interval_ms:
            filtered.append(action)

    if unique[-1].at != filtered[-1].at:
        filtered.append(unique[-1])
    return tuple(filtered)


def repeat_actions(actions: Iterable[Any], repeats: int = 1, pause_ms: int = 0) -> tuple[PatternAction, ...]:
    source = normalize_actions(actions)
    repeats = max(1, int(repeats or 1))
    if not source or repeats <= 1:
        return source

    start = source[0].at
    duration = _duration_ms(source)
    pause_ms = max(0, int(pause_ms or 0))
    repeated: list[PatternAction] = []
    for repeat_index in range(repeats):
        offset = repeat_index * (duration + pause_ms)
        for action_index, action in enumerate(source):
            if repeat_index and action_index == 0 and pause_ms == 0:
                continue
            repeated.append(PatternAction(action.at - start + offset, action.pos))
    return tuple(repeated)


def _interpolate(start: float, end: float, amount: float, method: str = "cosine") -> float:
    amount = _clamp(amount, 0.0, 1.0)
    if method == "cosine":
        amount = (1.0 - math.cos(amount * math.pi)) / 2.0
    elif method == "cubic":
        amount = amount * amount * (3.0 - 2.0 * amount)
    return start + (end - start) * amount


def minimum_jerk(amount: float) -> float:
    amount = _clamp(amount, 0.0, 1.0)
    return 10.0 * amount**3 - 15.0 * amount**4 + 6.0 * amount**5


def _catmull_rom(p0: float, p1: float, p2: float, p3: float, amount: float) -> float:
    amount = _clamp(amount, 0.0, 1.0)
    amount2 = amount * amount
    amount3 = amount2 * amount
    return 0.5 * (
        2.0 * p1
        + (-p0 + p2) * amount
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * amount2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * amount3
    )


def inject_intermediate_actions(
    actions: Iterable[Any],
    target_interval_ms: int = 0,
    *,
    interpolation: str = "cosine",
    speed_adaptive: bool = True,
) -> tuple[PatternAction, ...]:
    source = normalize_actions(actions)
    target_interval_ms = int(target_interval_ms or 0)
    if len(source) < 2 or target_interval_ms <= 0:
        return source

    result = [source[0]]
    for start, end in zip(source, source[1:]):
        dt = end.at - start.at
        if dt <= target_interval_ms:
            result.append(end)
            continue

        effective_interval = float(target_interval_ms)
        if speed_adaptive and dt > 0:
            speed = abs(end.pos - start.pos) / dt * 1000.0
            effective_interval /= max(0.75, min(2.0, speed / 180.0))

        injections = max(0, math.ceil(dt / max(1.0, effective_interval)) - 1)
        for index in range(1, injections + 1):
            amount = index / (injections + 1)
            result.append(
                PatternAction(
                    int(round(start.at + dt * amount)),
                    _clamp(_interpolate(start.pos, end.pos, amount, interpolation)),
                )
            )
        result.append(end)
    return normalize_actions(result)


def limit_action_delta(
    actions: Iterable[Any],
    max_step_delta: float,
    *,
    interpolation: str = "linear",
) -> tuple[PatternAction, ...]:
    source = normalize_actions(actions)
    if len(source) < 2 or max_step_delta <= 0:
        return source

    result = [source[0]]
    for end in source[1:]:
        start = result[-1]
        dt = end.at - start.at
        if dt <= 0:
            continue

        delta = abs(end.pos - start.pos)
        if delta > max_step_delta:
            segments = max(1, math.ceil(delta / max_step_delta))
            for index in range(1, segments):
                amount = index / segments
                result.append(
                    PatternAction(
                        int(round(start.at + dt * amount)),
                        _clamp(_interpolate(start.pos, end.pos, amount, interpolation)),
                    )
                )
        result.append(end)
    return normalize_actions(result)


def simplify_collinear_actions(
    actions: Iterable[Any],
    *,
    position_tolerance: float = 0.75,
) -> tuple[PatternAction, ...]:
    source = normalize_actions(actions)
    if len(source) < 3:
        return source

    simplified = [source[0]]
    for index, action in enumerate(source[1:-1], start=1):
        previous = simplified[-1]
        following = source[index + 1]
        duration = following.at - previous.at
        if duration <= 0:
            simplified.append(action)
            continue

        progress = (action.at - previous.at) / duration
        projected = previous.pos + (following.pos - previous.pos) * progress
        is_extremum = (
            action.pos > max(previous.pos, following.pos)
            or action.pos < min(previous.pos, following.pos)
        )
        if is_extremum or abs(action.pos - projected) > position_tolerance:
            simplified.append(action)

    simplified.append(source[-1])
    return tuple(simplified)


@lru_cache(maxsize=256)
def prepare_pattern_actions(pattern: MotionPattern) -> tuple[PatternAction, ...]:
    """Normalize, repeat, interpolate, and simplify a pattern's actions.

    The result depends only on the immutable MotionPattern dataclass, so it is
    safe to memoize. Pattern preparation can run multiple times per playback
    batch (once per expansion call plus once per `duration_ms` lookup), and
    the underlying numerical work is non-trivial.
    """
    actions = normalize_actions(pattern.actions, pattern.min_interval_ms)
    actions = repeat_actions(actions, pattern.repeat)
    actions = normalize_actions(actions, pattern.min_interval_ms)
    if pattern.interpolation_ms:
        actions = inject_intermediate_actions(
            actions,
            pattern.interpolation_ms,
            interpolation=pattern.interpolation,
            speed_adaptive=True,
        )
    actions = simplify_collinear_actions(actions)
    if pattern.max_step_delta:
        actions = limit_action_delta(
            actions,
            pattern.max_step_delta,
            interpolation="linear",
        )
    return actions


def _anchor_segment_pos(
    values: tuple[float, ...],
    index: int,
    amount: float,
    *,
    curve: str,
    softness: float,
    closed: bool,
) -> float:
    current = values[index]
    next_index = (index + 1) % len(values)
    following = values[next_index]

    eased = _interpolate(current, following, minimum_jerk(amount), "linear")
    if curve == "cosine":
        return _interpolate(current, following, amount, "cosine")
    if curve != "catmull" or len(values) < 3:
        return eased

    if closed:
        previous = values[(index - 1) % len(values)]
        after = values[(index + 2) % len(values)]
    else:
        previous = values[index - 1] if index > 0 else current
        after = values[index + 2] if index + 2 < len(values) else following

    spline = _clamp(_catmull_rom(previous, current, following, after, amount))
    return _interpolate(eased, spline, softness, "linear")


def prepare_anchor_actions(program: Any, rng: Optional[random.Random] = None) -> tuple[PatternAction, ...]:
    anchor_program = coerce_anchor_program(program, require_request=False)
    if anchor_program is None or len(anchor_program.anchors) < 2:
        return ()

    rng = rng or random.Random()
    values = tuple(anchor.pos for anchor in anchor_program.anchors)
    segment_count = len(values) if anchor_program.closed else len(values) - 1
    if segment_count <= 0:
        return ()

    segment_ms = int(round(620 / max(0.25, anchor_program.tempo)))
    sample_interval_ms = anchor_program.sample_interval_ms
    actions = [PatternAction(0, values[0])]
    current_time = 0

    for repeat_index in range(anchor_program.repeats):
        for segment_index in range(segment_count):
            start_time = current_time
            sample_count = max(2, math.ceil(segment_ms / sample_interval_ms))
            for sample_index in range(1, sample_count + 1):
                amount = sample_index / sample_count
                pos = _anchor_segment_pos(
                    values,
                    segment_index,
                    amount,
                    curve=anchor_program.curve,
                    softness=anchor_program.softness,
                    closed=anchor_program.closed,
                )
                if anchor_program.variation:
                    pos += rng.uniform(-anchor_program.variation * 6.0, anchor_program.variation * 6.0)
                actions.append(PatternAction(start_time + int(round(segment_ms * amount)), _clamp(pos)))
            current_time += segment_ms

        if repeat_index + 1 < anchor_program.repeats and anchor_program.closed:
            actions.append(PatternAction(current_time, values[0]))

    actions = normalize_actions(actions, min_interval_ms=50)
    actions = simplify_collinear_actions(actions, position_tolerance=0.45)
    return limit_action_delta(actions, anchor_program.max_step_delta, interpolation="linear")


_BUILTIN_PATTERNS_PATH = Path(__file__).parent / "builtin_patterns.json"


def _load_builtin_patterns() -> dict[str, MotionPattern]:
    """Materialize the built-in motion pattern catalog from JSON.

    The catalog data lives in ``builtin_patterns.json`` next to this
    module. Keeping the data in JSON (and not as a Python literal) keeps
    the data file free of Python imports, which avoids the circular
    dependency a sibling Python data module would create with this
    module's ``MotionPattern``/``PatternAction`` dataclasses. The loader
    runs once at import time so callers see a stable dict on every
    access, matching the previous in-line dict behavior.
    """

    with _BUILTIN_PATTERNS_PATH.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    catalog: dict[str, MotionPattern] = {}
    for pattern_id, payload in raw.items():
        actions = tuple(
            PatternAction(int(action["at"]), float(action["pos"]))
            for action in payload["actions"]
        )
        fields: dict[str, Any] = {"name": payload.get("name", pattern_id), "actions": actions}
        for field in (
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
        ):
            if field in payload:
                fields[field] = payload[field]
        catalog[pattern_id] = MotionPattern(**fields)
    return catalog


PATTERNS: dict[str, MotionPattern] = _load_builtin_patterns()


def pattern_names() -> tuple[str, ...]:
    return tuple(PATTERNS.keys())


def _actions_to_frames(
    actions: tuple[PatternAction, ...],
    current: MotionTarget,
    target: MotionTarget,
    style: FrameStyle,
    *,
    rng: random.Random,
    preserve_timing: bool = False,
    base_step_seconds: float = 0.25,
) -> list[PatternFrame]:
    if not actions:
        return []

    target = target.clamped()
    half_range = target.stroke_range / 2.0
    shallow = _clamp(target.depth - half_range)
    deep = _clamp(target.depth + half_range)
    if deep - shallow < 5:
        shallow = _clamp(target.depth - 2.5)
        deep = _clamp(target.depth + 2.5)

    frames = []
    duration_ms = _duration_ms(actions)
    previous_at = actions[0].at
    previous_pos = actions[0].pos
    tempo_scale = _clamp(style.tempo_scale, 0.25, 4.0)
    for index, action in enumerate(actions):
        interval_ms = max(0, action.at - previous_at)
        if preserve_timing:
            interval_seconds = (interval_ms / 1000.0) / tempo_scale
            delay_factor = 0.0 if index == 0 else interval_seconds / max(0.01, base_step_seconds)
        elif index == 0:
            delay_factor = 0.4
        else:
            interval_ratio = max(0.05, interval_ms / duration_ms)
            delay_factor = _clamp(interval_ratio * 3.0, 0.15, 1.1)
        previous_at = action.at
        if not preserve_timing:
            delay_factor = _clamp(delay_factor / tempo_scale, 0.08, 1.8)

        normalized_pos = _clamp(action.pos) / 100.0
        depth = shallow + (deep - shallow) * normalized_pos
        range_wave = 0.75 + abs(normalized_pos - 0.5) * 0.5
        local_range = max(5.0, min(target.stroke_range, target.stroke_range * style.window_scale * range_wave))
        if style.range_jitter:
            local_range += rng.uniform(-style.range_jitter, style.range_jitter)
        local_range = _clamp(local_range, 5.0, target.stroke_range)
        if style.depth_jitter:
            depth += rng.uniform(-style.depth_jitter, style.depth_jitter)

        base_label = str(target.label or style.name or "pattern").strip()
        style_label = str(style.name or "").strip()
        if style_label and _clean_label(style_label) not in _clean_label(base_label):
            base_label = f"{base_label} {style_label}".strip()

        speed = target.speed * style.speed_scale
        if preserve_timing and index > 0 and interval_ms > 0:
            position_delta = abs(action.pos - previous_pos)
            position_per_second = position_delta / max(0.05, interval_ms / 1000.0)
            segment_speed = _clamp((position_per_second / 160.0) * 100.0, 8.0, 100.0)
            speed = max(speed, segment_speed * style.speed_scale)
        previous_pos = action.pos

        frames.append(
            PatternFrame(
                MotionTarget(
                    speed=speed,
                    depth=depth,
                    stroke_range=local_range,
                    label=f"{base_label} {index + 1}",
                ).clamped(),
                delay_factor=delay_factor,
                phase="timed-pattern" if preserve_timing else "pattern",
            )
        )
    frames = _blend_from_current(current, frames, style.name)
    return _blend_direction_changes(frames, style.name)


def _wrap_segment_ms(actions: tuple[PatternAction, ...]) -> int:
    """How long the implicit wrap segment from ``actions[-1]`` back to
    ``actions[0]`` should take.

    Scales linearly with the position delta so closed patterns
    (``actions[-1].pos`` near ``actions[0].pos``) wrap quickly through a
    near-flat segment, while open patterns (e.g., ``ramp`` going 20 ->
    100) get a wrap segment long enough that the live controller glides
    through the gap instead of slewing. The 50 ms floor keeps closed
    patterns from collapsing the wrap to a one-sample step.

    Audit of the built-in catalog: 30 of 34 patterns have
    ``actions[-1].pos != actions[0].pos``, which is why this wrap
    segment matters at all -- without it the previous cosine sampler
    snapped from the last position back to the first on every cycle.
    """
    if len(actions) < 2:
        return 0
    pos_delta = abs(actions[0].pos - actions[-1].pos)
    return max(50, int(pos_delta * 10))


def _continuous_cycle_ms(actions: tuple[PatternAction, ...]) -> int:
    if not actions:
        return 0
    return _duration_ms(actions) + _wrap_segment_ms(actions)


def _continuous_duration_seconds(actions: tuple[PatternAction, ...], style: FrameStyle) -> float:
    tempo_scale = _clamp(style.tempo_scale, 0.25, 4.0)
    return _clamp((_continuous_cycle_ms(actions) / 1000.0) / tempo_scale, 0.45, 6.0)


def _sample_action_position(
    actions: tuple[PatternAction, ...],
    phase: float,
) -> float:
    """Phase-cyclic Catmull-Rom sample of an action list.

    Treats the action sequence as a closed loop with an implicit wrap
    segment from ``actions[-1]`` back to ``actions[0]``. The wrap span
    scales with the position delta so the cycle glides through any open
    gap instead of snapping. Catmull-Rom across four cyclic neighbors
    keeps the phase-domain curve smooth at every segment boundary,
    including the wraparound -- the live controller no longer sees a
    per-cycle position step at phase=1.0 -> 0.0 that the previous cosine
    sampler used to leave behind on the 30 of 34 asymmetric built-in
    patterns. Unequal segment durations can still change wall-clock
    velocity at a boundary, but not the commanded position itself.

    Catmull-Rom can overshoot by ~12.5% of a segment range when control
    points are extreme; the returned value is clamped to [0, 100]. The
    clamp can flatten a brief overshoot at the very top/bottom of a
    stroke, but never adds discontinuity, and is preferable to the
    cosine sampler's per-cycle step.
    """
    if not actions:
        return 50.0
    if len(actions) == 1:
        return actions[0].pos

    n = len(actions)
    wrap_ms = _wrap_segment_ms(actions)
    total_cycle_ms = _continuous_cycle_ms(actions)

    phase = phase % 1.0
    sample_at = phase * total_cycle_ms

    # Cumulative time at each action's index. Segments[i] runs from
    # ``cumulative[i]`` to ``cumulative[i+1]``. Segment ``n-1`` is the
    # wrap segment from ``actions[-1]`` to ``actions[0]`` whose length is
    # ``wrap_ms``. ``cumulative[n] == total_cycle_ms``.
    cumulative = [0]
    for index in range(n - 1):
        cumulative.append(cumulative[-1] + (actions[index + 1].at - actions[index].at))
    cumulative.append(cumulative[-1] + wrap_ms)

    segment_index = n - 1
    for i in range(n):
        if sample_at < cumulative[i + 1]:
            segment_index = i
            break

    segment_start = cumulative[segment_index]
    segment_end = cumulative[segment_index + 1]
    segment_span = max(1, segment_end - segment_start)
    amount = (sample_at - segment_start) / segment_span

    # Four cyclic control points for Catmull-Rom across the full closed
    # cycle (including the wrap segment).
    p1_idx = segment_index % n
    p2_idx = (segment_index + 1) % n
    p0_idx = (p1_idx - 1) % n
    p3_idx = (p2_idx + 1) % n

    return _clamp(_catmull_rom(
        actions[p0_idx].pos,
        actions[p1_idx].pos,
        actions[p2_idx].pos,
        actions[p3_idx].pos,
        amount,
    ))


def _continuous_normalized_range(
    actions: tuple[PatternAction, ...],
    sample_count: int = 25,
) -> tuple[float, float]:
    if not actions:
        return (50.0, 50.0)
    sample_count = max(2, int(sample_count or 2))
    positions = [
        _sample_action_position(actions, index / (sample_count - 1))
        for index in range(sample_count)
    ]
    return (min(positions), max(positions))


def _smooth_jitter(jitter_phase: float, amount: float, axis_seed: float = 0.0) -> float:
    """Return a value in approximately ``[-amount, +amount]`` that varies
    smoothly with ``jitter_phase`` (expected 0..1).

    Two sine waves at near-irrational frequency ratio are summed so the
    result never perfectly repeats over the lifetime of a single plan
    run. ``axis_seed`` decorrelates depth from range so the two jitter
    streams do not drift in lockstep, which would still feel mechanical.
    Returns ``0.0`` when ``amount`` is non-positive so plans without
    jitter pay no cost.
    """
    if amount is None or amount <= 0:
        return 0.0
    angle_a = (jitter_phase * 2.3 + axis_seed) * math.tau
    angle_b = (jitter_phase * 3.7 + axis_seed * 1.61803) * math.tau
    return amount * (math.sin(angle_a) + math.sin(angle_b)) * 0.5


def _motion_target_for_sample(
    normalized_pos: float,
    target: MotionTarget,
    style: FrameStyle,
    *,
    label: str,
    jitter_phase: float = 0.0,
) -> MotionTarget:
    """Project the sampled normalized position onto the live target window.

    Adds two organic perturbations on top of the deterministic depth /
    range mapping so the controller does not feel mechanically periodic:

    - ``style.depth_jitter`` perturbs depth by a smooth time-based
      offset bounded to that amount. The offset uses ``jitter_phase``
      (typically a slow 0..1 cycle over several seconds) so adjacent
      samples drift together rather than chattering.
    - ``style.range_jitter`` similarly perturbs the local stroke range
      with a decorrelated seed so depth and range do not jitter in
      lockstep.

    Both perturbations are no-ops when the relevant jitter amount is
    zero or negative, so patterns that opt out of jitter cost nothing.
    """
    target = target.clamped()
    half_range = target.stroke_range / 2.0
    shallow = _clamp(target.depth - half_range)
    deep = _clamp(target.depth + half_range)
    if deep - shallow < 5:
        shallow = _clamp(target.depth - 2.5)
        deep = _clamp(target.depth + 2.5)

    normalized_pos = _clamp(normalized_pos) / 100.0
    depth = shallow + (deep - shallow) * normalized_pos
    range_wave = 0.75 + abs(normalized_pos - 0.5) * 0.5
    local_range = max(5.0, min(target.stroke_range, target.stroke_range * style.window_scale * range_wave))

    depth_offset = _smooth_jitter(jitter_phase, style.depth_jitter, axis_seed=0.0)
    range_offset = _smooth_jitter(jitter_phase, style.range_jitter, axis_seed=0.5)
    depth = depth + depth_offset
    local_range = max(5.0, local_range + range_offset)

    return MotionTarget(
        speed=target.speed * style.speed_scale,
        depth=depth,
        stroke_range=local_range,
        label=label,
    ).clamped()


def _depth_for_normalized_position(normalized_pos: float, target: MotionTarget) -> float:
    target = target.clamped()
    half_range = target.stroke_range / 2.0
    shallow = _clamp(target.depth - half_range)
    deep = _clamp(target.depth + half_range)
    if deep - shallow < 5:
        shallow = _clamp(target.depth - 2.5)
        deep = _clamp(target.depth + 2.5)
    return shallow + (deep - shallow) * (_clamp(normalized_pos) / 100.0)


def continuous_plan_depth_range(
    plan: ContinuousMotionPlan,
    target: MotionTarget,
) -> Optional[dict[str, int]]:
    normalized_range = getattr(plan, "normalized_range", None)
    if normalized_range is None:
        normalized_range = _continuous_normalized_range(tuple(getattr(plan, "actions", ()) or ()))
    if not normalized_range:
        return None

    low_pos, high_pos = sorted((float(normalized_range[0]), float(normalized_range[1])))
    low_depth = _depth_for_normalized_position(low_pos, target)
    high_depth = _depth_for_normalized_position(high_pos, target)
    depth_jitter = max(0.0, float(getattr(plan.style, "depth_jitter", 0.0) or 0.0))
    return {
        "min": int(round(_clamp(min(low_depth, high_depth) - depth_jitter))),
        "max": int(round(_clamp(max(low_depth, high_depth) + depth_jitter))),
    }


def continuous_motion_plan(pattern_name: str) -> Optional[ContinuousMotionPlan]:
    pattern = PATTERNS.get((pattern_name or "").lower())
    if not pattern:
        return None
    return continuous_motion_plan_from_pattern(pattern)


def continuous_motion_plan_from_pattern(pattern: MotionPattern) -> Optional[ContinuousMotionPlan]:
    actions = prepare_pattern_actions(pattern)
    if not actions:
        return None
    style = FrameStyle(
        name=pattern.name,
        window_scale=pattern.window_scale,
        speed_scale=pattern.speed_scale,
        tempo_scale=pattern.tempo_scale,
        depth_jitter=pattern.depth_jitter,
        range_jitter=pattern.range_jitter,
    )
    return ContinuousMotionPlan(
        name=pattern.name,
        actions=actions,
        style=style,
        duration_seconds=_continuous_duration_seconds(actions, style),
        normalized_range=_continuous_normalized_range(actions),
    )


def continuous_anchor_motion_plan(
    program: Any,
    rng: Optional[random.Random] = None,
) -> Optional[ContinuousMotionPlan]:
    anchor_program = coerce_anchor_program(program, require_request=False)
    if anchor_program is None:
        return None
    actions = prepare_anchor_actions(anchor_program, rng=rng)
    if not actions:
        return None
    style = FrameStyle(
        name="anchor_loop",
        window_scale=0.22 + (1.0 - anchor_program.softness) * 0.18,
        speed_scale=0.85 + anchor_program.tempo * 0.18,
        depth_jitter=anchor_program.variation * 4.0,
        range_jitter=anchor_program.variation * 2.5,
    )
    return ContinuousMotionPlan(
        name="anchor_loop",
        actions=actions,
        style=style,
        duration_seconds=_continuous_duration_seconds(actions, style),
        normalized_range=_continuous_normalized_range(actions),
    )


JITTER_CYCLE_SECONDS = 5.0


def sample_continuous_plan(
    plan: ContinuousMotionPlan,
    target: MotionTarget,
    elapsed_seconds: float,
) -> MotionTarget:
    """Sample the plan at ``elapsed_seconds`` into the target window.

    Position is sampled phase-cyclically with Catmull-Rom across four
    cyclic neighbors, so consecutive cycles do not produce a per-cycle
    step at phase wraparound. Depth and range jitter (when the plan's
    style declares any) ride on a slow ``JITTER_CYCLE_SECONDS`` cycle
    independent of the pattern cycle, so jitter does not synchronize
    with the stroke -- the result feels organic rather than periodic.
    """
    elapsed = max(0.0, float(elapsed_seconds or 0.0))
    duration_seconds = max(0.1, float(plan.duration_seconds or 0.1))
    phase = (elapsed / duration_seconds) % 1.0
    pos = _sample_action_position(plan.actions, phase)
    base_label = str(target.label or plan.name or "pattern").strip()
    style_label = str(plan.name or "").strip()
    if style_label and _clean_label(style_label) not in _clean_label(base_label):
        base_label = f"{base_label} {style_label}".strip()
    jitter_phase = (elapsed % JITTER_CYCLE_SECONDS) / JITTER_CYCLE_SECONDS
    return _motion_target_for_sample(
        pos,
        target,
        plan.style,
        label=f"{base_label} continuous",
        jitter_phase=jitter_phase,
    )


def _blend_from_current(
    current: MotionTarget,
    frames: list[PatternFrame],
    label: str,
) -> list[PatternFrame]:
    if not frames:
        return frames

    current = current.clamped()
    first = frames[0].target.clamped()
    blend_frames = []
    start = current
    blend_label = label or first.label

    if abs(first.depth - current.depth) > 14.0 and first.speed > 8.0:
        start = MotionTarget(
            max(8.0, min(first.speed, current.speed) * 0.62),
            current.depth,
            current.stroke_range,
            label=f"{blend_label} blend settle",
        ).clamped()
        blend_frames.append(PatternFrame(start, delay_factor=0.14, phase="blend"))

    if first.speed + 10.0 < current.speed:
        start = MotionTarget(
            first.speed,
            start.depth,
            start.stroke_range,
            label=f"{blend_label} blend speed",
        ).clamped()
        blend_frames.append(PatternFrame(start, delay_factor=0.1, phase="blend"))

    speed_delta = abs(first.speed - start.speed)
    depth_delta = abs(first.depth - start.depth)
    range_delta = abs(first.stroke_range - start.stroke_range)
    steps = max(
        math.ceil(speed_delta / 12.0),
        math.ceil(depth_delta / 8.0),
        math.ceil(range_delta / 16.0),
    )
    steps = max(0, min(10, steps))
    if steps <= 1 and speed_delta < 10 and depth_delta < 10 and range_delta < 12:
        return blend_frames + frames

    for index in range(1, steps + 1):
        amount = minimum_jerk(index / (steps + 1))
        blend_frames.append(
            PatternFrame(
                MotionTarget(
                    speed=_interpolate(start.speed, first.speed, amount, "linear"),
                    depth=_interpolate(start.depth, first.depth, amount, "linear"),
                    stroke_range=_interpolate(start.stroke_range, first.stroke_range, amount, "linear"),
                    label=f"{blend_label} blend {index}",
                ).clamped(),
                delay_factor=0.16,
                phase="blend",
            )
        )
    return blend_frames + frames


def _depth_direction(start: MotionTarget, end: MotionTarget, threshold: float = 7.0) -> int:
    delta = end.depth - start.depth
    if abs(delta) < threshold:
        return 0
    return 1 if delta > 0 else -1


def _turn_speed(previous: MotionTarget, target: MotionTarget) -> float:
    base_speed = min(previous.speed, target.speed)
    if base_speed <= 8.0:
        return base_speed
    return max(8.0, base_speed * 0.45)


def _is_turn_apex(frames: list[PatternFrame], index: int) -> bool:
    if index <= 0 or index >= len(frames) - 1:
        return False
    previous = frames[index - 1]
    current = frames[index]
    following = frames[index + 1]
    if previous.phase != "pattern" or current.phase != "pattern" or following.phase != "pattern":
        return False
    into_turn = _depth_direction(previous.target, current.target, threshold=5.0)
    out_of_turn = _depth_direction(current.target, following.target, threshold=5.0)
    return bool(into_turn and out_of_turn and into_turn != out_of_turn)


def _turn_apex_frame(frames: list[PatternFrame], index: int) -> PatternFrame:
    previous = frames[index - 1].target.clamped()
    current = frames[index].target.clamped()
    following = frames[index + 1].target.clamped()
    turn_speed = min(_turn_speed(previous, current), _turn_speed(current, following))
    return PatternFrame(
        MotionTarget(
            turn_speed,
            current.depth,
            current.stroke_range,
            label=f"{current.label or 'pattern'} turn apex",
        ).clamped(),
        delay_factor=max(frames[index].delay_factor, 0.2),
        phase="pattern",
    )


def _turn_exit_frames(apex: PatternFrame, following: PatternFrame, label: str) -> list[PatternFrame]:
    apex_target = apex.target.clamped()
    following_target = following.target.clamped()
    depth_delta = following_target.depth - apex_target.depth
    if abs(depth_delta) < 6.0:
        return []
    blend_label = label or following_target.label or "pattern"
    frames = [
        PatternFrame(
            MotionTarget(
                _interpolate(apex_target.speed, following_target.speed, 0.35, "linear"),
                apex_target.depth + depth_delta * 0.18,
                _interpolate(apex_target.stroke_range, following_target.stroke_range, 0.25, "linear"),
                label=f"{blend_label} turn exit",
            ).clamped(),
            delay_factor=0.14,
            phase="blend",
        )
    ]
    if abs(depth_delta) >= 18.0:
        frames.append(
            PatternFrame(
                MotionTarget(
                    _interpolate(apex_target.speed, following_target.speed, 0.55, "linear"),
                    apex_target.depth + depth_delta * 0.38,
                    _interpolate(apex_target.stroke_range, following_target.stroke_range, 0.45, "linear"),
                    label=f"{blend_label} turn recover",
                ).clamped(),
                delay_factor=0.14,
                phase="blend",
            )
        )
    return frames


def _blend_direction_changes(frames: list[PatternFrame], label: str) -> list[PatternFrame]:
    if len(frames) < 3:
        return frames

    result = []
    for index, frame in enumerate(frames):
        if _is_turn_apex(frames, index):
            frame = _turn_apex_frame(frames, index)
        result.append(frame)
        if _is_turn_apex(frames, index):
            result.extend(_turn_exit_frames(frame, frames[index + 1], label))
    return result


def expand_pattern(
    pattern_name: str,
    current: MotionTarget,
    target: MotionTarget,
    rng: Optional[random.Random] = None,
) -> list[PatternFrame]:
    pattern = PATTERNS.get((pattern_name or "").lower())
    if not pattern:
        return []

    return expand_motion_pattern(pattern, current, target, rng=rng)


def expand_motion_pattern(
    pattern: MotionPattern,
    current: MotionTarget,
    target: MotionTarget,
    rng: Optional[random.Random] = None,
    *,
    preserve_timing: bool = False,
    base_step_seconds: float = 0.25,
) -> list[PatternFrame]:
    actions = prepare_pattern_actions(pattern)
    if not actions:
        return []

    return _actions_to_frames(
        actions,
        current,
        target,
        FrameStyle(
            name=pattern.name,
            window_scale=pattern.window_scale,
            speed_scale=pattern.speed_scale,
            tempo_scale=pattern.tempo_scale,
            depth_jitter=pattern.depth_jitter,
            range_jitter=pattern.range_jitter,
        ),
        rng=rng or random.Random(),
        preserve_timing=preserve_timing,
        base_step_seconds=base_step_seconds,
    )


def expand_anchor_program(
    current: MotionTarget,
    target: MotionTarget,
    program: Any,
    rng: Optional[random.Random] = None,
) -> list[PatternFrame]:
    anchor_program = coerce_anchor_program(program, require_request=False)
    if anchor_program is None:
        return []

    actions = prepare_anchor_actions(anchor_program, rng=rng)
    if not actions:
        return []

    window_scale = 0.22 + (1.0 - anchor_program.softness) * 0.18
    speed_scale = 0.85 + anchor_program.tempo * 0.18
    return _actions_to_frames(
        actions,
        current,
        target,
        FrameStyle(
            name="anchor_loop",
            window_scale=window_scale,
            speed_scale=speed_scale,
            depth_jitter=anchor_program.variation * 4.0,
            range_jitter=anchor_program.variation * 2.5,
        ),
        rng=rng or random.Random(),
    )
