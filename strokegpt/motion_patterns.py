import math
import random
from dataclasses import dataclass
from functools import lru_cache
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
            PatternAction(0, 76),
            PatternAction(90, 6),
            PatternAction(430, 64),
        ),
        window_scale=0.18,
        speed_scale=1.1,
        depth_jitter=1.2,
        range_jitter=1.0,
        min_interval_ms=70,
        interpolation_ms=80,
        max_step_delta=26,
    ),
    "milk": MotionPattern(
        "milk",
        (
            PatternAction(0, 4),
            PatternAction(320, 94),
            PatternAction(640, 8),
            PatternAction(960, 100),
            PatternAction(1280, 6),
        ),
        window_scale=0.92,
        speed_scale=1.02,
        interpolation_ms=130,
        max_step_delta=34,
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
    "milking-pressure-build": MotionPattern(
        "Milking Pressure Build",
        (
            PatternAction(0, 12),
            PatternAction(300, 34),
            PatternAction(650, 62),
            PatternAction(1000, 92),
        ),
        window_scale=0.48,
        speed_scale=0.95,
        interpolation_ms=150,
        max_step_delta=28,
    ),
    "milking-wide-pressure": MotionPattern(
        "Milking Wide Pressure",
        (
            PatternAction(0, 6),
            PatternAction(340, 72),
            PatternAction(680, 96),
            PatternAction(1020, 28),
            PatternAction(1360, 92),
        ),
        window_scale=0.55,
        speed_scale=1.0,
        interpolation_ms=140,
        max_step_delta=32,
    ),
    "milking-deep-pulse": MotionPattern(
        "Milking Deep Pulse",
        (
            PatternAction(0, 62),
            PatternAction(180, 92),
            PatternAction(360, 68),
            PatternAction(540, 96),
            PatternAction(720, 70),
        ),
        window_scale=0.24,
        speed_scale=1.1,
        repeat=2,
        interpolation_ms=90,
        max_step_delta=24,
    ),
    "milking-fast-middle": MotionPattern(
        "Milking Fast Middle",
        (
            PatternAction(0, 35),
            PatternAction(120, 65),
            PatternAction(240, 42),
            PatternAction(360, 70),
            PatternAction(480, 38),
        ),
        window_scale=0.26,
        speed_scale=1.18,
        repeat=2,
        min_interval_ms=55,
        max_step_delta=24,
    ),
    "milking-deep-finish": MotionPattern(
        "Milking Deep Finish",
        (
            PatternAction(0, 52),
            PatternAction(260, 88),
            PatternAction(520, 72),
            PatternAction(780, 100),
            PatternAction(1040, 60),
        ),
        window_scale=0.28,
        speed_scale=1.05,
        interpolation_ms=120,
        max_step_delta=28,
    ),
    "milking-recover": MotionPattern(
        "Milking Recover",
        (
            PatternAction(0, 70),
            PatternAction(420, 38),
            PatternAction(840, 18),
            PatternAction(1260, 32),
        ),
        window_scale=0.2,
        speed_scale=0.72,
        interpolation_ms=180,
        max_step_delta=24,
    ),
    "milking-steady-press": MotionPattern(
        "Milking Steady Press",
        (
            PatternAction(0, 18),
            PatternAction(380, 54),
            PatternAction(760, 78),
            PatternAction(1140, 48),
            PatternAction(1520, 82),
        ),
        window_scale=0.38,
        speed_scale=0.95,
        interpolation_ms=150,
        max_step_delta=28,
    ),
    "milking-short-burst": MotionPattern(
        "Milking Short Burst",
        (
            PatternAction(0, 42),
            PatternAction(90, 80),
            PatternAction(180, 48),
            PatternAction(270, 86),
            PatternAction(360, 44),
        ),
        window_scale=0.18,
        speed_scale=1.2,
        repeat=2,
        min_interval_ms=50,
        max_step_delta=24,
    ),
    "milking-full-drive": MotionPattern(
        "Milking Full Drive",
        (
            PatternAction(0, 4),
            PatternAction(360, 94),
            PatternAction(720, 10),
            PatternAction(1080, 100),
            PatternAction(1440, 8),
        ),
        window_scale=0.6,
        speed_scale=1.0,
        interpolation_ms=130,
        max_step_delta=34,
    ),
    "milking-deep-squeeze": MotionPattern(
        "Milking Deep Squeeze",
        (
            PatternAction(0, 72),
            PatternAction(260, 96),
            PatternAction(520, 82),
            PatternAction(900, 100),
        ),
        window_scale=0.18,
        speed_scale=0.95,
        interpolation_ms=170,
        max_step_delta=22,
    ),
    "milking-final-wave": MotionPattern(
        "Milking Final Wave",
        (
            PatternAction(0, 12),
            PatternAction(280, 60),
            PatternAction(560, 96),
            PatternAction(840, 42),
            PatternAction(1120, 100),
            PatternAction(1400, 18),
        ),
        window_scale=0.5,
        speed_scale=1.02,
        interpolation_ms=130,
        max_step_delta=30,
    ),
    "edge-build-low": MotionPattern(
        "Edge Build Low",
        (
            PatternAction(0, 10),
            PatternAction(360, 34),
            PatternAction(720, 18),
            PatternAction(1080, 42),
        ),
        window_scale=0.28,
        speed_scale=0.8,
        interpolation_ms=160,
        max_step_delta=22,
    ),
    "edge-build-mid": MotionPattern(
        "Edge Build Mid",
        (
            PatternAction(0, 18),
            PatternAction(380, 48),
            PatternAction(760, 70),
            PatternAction(1140, 36),
        ),
        window_scale=0.34,
        speed_scale=0.9,
        interpolation_ms=150,
        max_step_delta=26,
    ),
    "edge-hold": MotionPattern(
        "Edge Hold",
        (
            PatternAction(0, 42),
            PatternAction(380, 58),
            PatternAction(760, 48),
            PatternAction(1140, 64),
        ),
        window_scale=0.18,
        speed_scale=0.68,
        interpolation_ms=180,
        max_step_delta=18,
    ),
    "edge-tip-tease": MotionPattern(
        "Edge Tip Tease",
        (
            PatternAction(0, 12),
            PatternAction(240, 34),
            PatternAction(480, 8),
            PatternAction(720, 30),
            PatternAction(960, 14),
        ),
        window_scale=0.18,
        speed_scale=0.88,
        interpolation_ms=150,
        max_step_delta=20,
    ),
    "edge-recover": MotionPattern(
        "Edge Recover",
        (
            PatternAction(0, 82),
            PatternAction(420, 54),
            PatternAction(840, 70),
            PatternAction(1260, 48),
        ),
        window_scale=0.15,
        speed_scale=0.62,
        interpolation_ms=200,
        max_step_delta=18,
    ),
    "edge-slow-wide": MotionPattern(
        "Edge Slow Wide",
        (
            PatternAction(0, 8),
            PatternAction(520, 82),
            PatternAction(1040, 18),
            PatternAction(1560, 88),
        ),
        window_scale=0.46,
        speed_scale=0.74,
        interpolation_ms=180,
        max_step_delta=26,
    ),
    "edge-shallow-snap": MotionPattern(
        "Edge Shallow Snap",
        (
            PatternAction(0, 20),
            PatternAction(110, 58),
            PatternAction(220, 24),
            PatternAction(330, 62),
            PatternAction(440, 22),
        ),
        window_scale=0.18,
        speed_scale=1.12,
        repeat=2,
        min_interval_ms=55,
        max_step_delta=22,
    ),
    "edge-middle-hold": MotionPattern(
        "Edge Middle Hold",
        (
            PatternAction(0, 42),
            PatternAction(420, 54),
            PatternAction(840, 46),
            PatternAction(1260, 58),
        ),
        window_scale=0.2,
        speed_scale=0.76,
        interpolation_ms=190,
        max_step_delta=18,
    ),
    "edge-deeper-risk": MotionPattern(
        "Edge Deeper Risk",
        (
            PatternAction(0, 40),
            PatternAction(320, 78),
            PatternAction(640, 56),
            PatternAction(960, 88),
        ),
        window_scale=0.24,
        speed_scale=0.98,
        interpolation_ms=140,
        max_step_delta=24,
    ),
    "edge-pull-back": MotionPattern(
        "Edge Pull Back",
        (
            PatternAction(0, 82),
            PatternAction(260, 96),
            PatternAction(520, 88),
        ),
        window_scale=0.14,
        speed_scale=0.6,
        interpolation_ms=160,
        max_step_delta=20,
    ),
    "edge-restart": MotionPattern(
        "Edge Restart",
        (
            PatternAction(0, 12),
            PatternAction(320, 34),
            PatternAction(640, 52),
            PatternAction(960, 26),
        ),
        window_scale=0.22,
        speed_scale=0.82,
        interpolation_ms=160,
        max_step_delta=20,
    ),
}


def pattern_names() -> tuple[str, ...]:
    return tuple(PATTERNS.keys())


def _actions_to_frames(
    actions: tuple[PatternAction, ...],
    current: MotionTarget,
    target: MotionTarget,
    style: FrameStyle,
    *,
    rng: random.Random,
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
    tempo_scale = _clamp(style.tempo_scale, 0.25, 4.0)
    for index, action in enumerate(actions):
        if index == 0:
            delay_factor = 0.4
        else:
            interval_ratio = max(0.05, (action.at - previous_at) / duration_ms)
            delay_factor = _clamp(interval_ratio * 3.0, 0.15, 1.1)
        previous_at = action.at
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

        frames.append(
            PatternFrame(
                MotionTarget(
                    speed=target.speed * style.speed_scale,
                    depth=depth,
                    stroke_range=local_range,
                    label=f"{base_label} {index + 1}",
                ).clamped(),
                delay_factor=delay_factor,
                phase="pattern",
            )
        )
    frames = _blend_from_current(current, frames, style.name)
    return _blend_direction_changes(frames, style.name)


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
