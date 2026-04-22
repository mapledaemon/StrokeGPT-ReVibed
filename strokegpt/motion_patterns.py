import math
import random
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .motion import MotionTarget


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


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


def prepare_pattern_actions(pattern: MotionPattern) -> tuple[PatternAction, ...]:
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


PATTERNS = {
    "stroke": MotionPattern(
        "stroke",
        (
            PatternAction(0, 0),
            PatternAction(450, 100),
            PatternAction(900, 0),
        ),
        window_scale=0.35,
        interpolation_ms=160,
    ),
    "flick": MotionPattern(
        "flick",
        (
            PatternAction(0, 35),
            PatternAction(90, 100),
            PatternAction(180, 55),
            PatternAction(270, 100),
            PatternAction(360, 40),
        ),
        window_scale=0.18,
        speed_scale=1.1,
        depth_jitter=2.0,
        range_jitter=1.5,
        min_interval_ms=70,
    ),
    "pulse": MotionPattern(
        "pulse",
        (
            PatternAction(0, 55),
            PatternAction(250, 82),
            PatternAction(500, 58),
            PatternAction(750, 88),
            PatternAction(1000, 55),
        ),
        window_scale=0.25,
        speed_scale=1.0,
        depth_jitter=3.0,
        range_jitter=2.0,
        interpolation_ms=150,
    ),
    "hold": MotionPattern(
        "hold",
        (
            PatternAction(0, 72),
            PatternAction(350, 88),
            PatternAction(700, 76),
            PatternAction(1050, 90),
            PatternAction(1400, 74),
        ),
        window_scale=0.16,
        speed_scale=0.8,
        depth_jitter=1.0,
        interpolation_ms=175,
    ),
    "wave": MotionPattern(
        "wave",
        (
            PatternAction(0, 0),
            PatternAction(250, 55),
            PatternAction(500, 100),
            PatternAction(750, 45),
            PatternAction(1000, 0),
        ),
        window_scale=0.4,
        speed_scale=0.95,
        interpolation_ms=125,
    ),
    "ramp": MotionPattern(
        "ramp",
        (
            PatternAction(0, 20),
            PatternAction(350, 45),
            PatternAction(700, 70),
            PatternAction(1000, 100),
        ),
        window_scale=0.35,
        speed_scale=0.95,
        interpolation_ms=150,
    ),
    "tease": MotionPattern(
        "tease",
        (
            PatternAction(0, 15),
            PatternAction(350, 35),
            PatternAction(650, 10),
            PatternAction(1000, 30),
        ),
        window_scale=0.22,
        speed_scale=0.75,
        depth_jitter=3.0,
        range_jitter=2.0,
        interpolation_ms=175,
    ),
    "flutter": MotionPattern(
        "flutter",
        (
            PatternAction(0, 45),
            PatternAction(80, 80),
            PatternAction(160, 52),
            PatternAction(240, 86),
            PatternAction(320, 48),
        ),
        window_scale=0.14,
        speed_scale=1.15,
        depth_jitter=1.5,
        range_jitter=1.0,
        repeat=2,
        min_interval_ms=55,
        max_step_delta=28,
    ),
    "ladder": MotionPattern(
        "ladder",
        (
            PatternAction(0, 20),
            PatternAction(260, 42),
            PatternAction(520, 62),
            PatternAction(780, 82),
            PatternAction(1040, 100),
            PatternAction(1320, 35),
        ),
        window_scale=0.32,
        speed_scale=1.0,
        interpolation_ms=150,
        max_step_delta=30,
    ),
    "surge": MotionPattern(
        "surge",
        (
            PatternAction(0, 8),
            PatternAction(420, 28),
            PatternAction(880, 70),
            PatternAction(1250, 100),
            PatternAction(1600, 18),
        ),
        window_scale=0.38,
        speed_scale=1.05,
        interpolation_ms=140,
        max_step_delta=32,
    ),
    "sway": MotionPattern(
        "sway",
        (
            PatternAction(0, 12),
            PatternAction(380, 58),
            PatternAction(760, 92),
            PatternAction(1140, 42),
            PatternAction(1520, 12),
        ),
        window_scale=0.42,
        speed_scale=0.9,
        interpolation_ms=140,
    ),
}


def pattern_names() -> tuple[str, ...]:
    return tuple(PATTERNS.keys())


def expand_pattern(
    pattern_name: str,
    current: MotionTarget,
    target: MotionTarget,
    rng: Optional[random.Random] = None,
) -> list[PatternFrame]:
    pattern = PATTERNS.get((pattern_name or "").lower())
    if not pattern:
        return []

    actions = prepare_pattern_actions(pattern)
    if not actions:
        return []

    rng = rng or random.Random()
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
    for index, action in enumerate(actions):
        if index == 0:
            delay_factor = 0.4
        else:
            interval_ratio = max(0.05, (action.at - previous_at) / duration_ms)
            delay_factor = _clamp(interval_ratio * 3.0, 0.15, 1.1)
        previous_at = action.at

        normalized_pos = _clamp(action.pos) / 100.0
        depth = shallow + (deep - shallow) * normalized_pos
        range_wave = 0.75 + abs(normalized_pos - 0.5) * 0.5
        local_range = max(5.0, min(target.stroke_range, target.stroke_range * pattern.window_scale * range_wave))
        if pattern.range_jitter:
            local_range += rng.uniform(-pattern.range_jitter, pattern.range_jitter)
        local_range = _clamp(local_range, 5.0, target.stroke_range)
        if pattern.depth_jitter:
            depth += rng.uniform(-pattern.depth_jitter, pattern.depth_jitter)

        frames.append(
            PatternFrame(
                MotionTarget(
                    speed=target.speed * pattern.speed_scale,
                    depth=depth,
                    stroke_range=local_range,
                    label=f"{target.label} {pattern.name} {index + 1}",
                ).clamped(),
                delay_factor=delay_factor,
            )
        )
    return frames
