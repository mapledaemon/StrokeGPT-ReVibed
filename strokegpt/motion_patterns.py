import random
from dataclasses import dataclass
from typing import Optional

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

    @property
    def duration_ms(self) -> int:
        if not self.actions:
            return 0
        return max(1, self.actions[-1].at - self.actions[0].at)


@dataclass(frozen=True)
class PatternFrame:
    target: MotionTarget
    delay_factor: float


PATTERNS = {
    "stroke": MotionPattern(
        "stroke",
        (
            PatternAction(0, 0),
            PatternAction(450, 100),
            PatternAction(900, 0),
        ),
        window_scale=0.35,
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

    rng = rng or random.Random()
    target = target.clamped()
    half_range = target.stroke_range / 2.0
    shallow = _clamp(target.depth - half_range)
    deep = _clamp(target.depth + half_range)
    if deep - shallow < 5:
        shallow = _clamp(target.depth - 2.5)
        deep = _clamp(target.depth + 2.5)

    frames = []
    previous_at = pattern.actions[0].at
    for index, action in enumerate(pattern.actions):
        if index == 0:
            delay_factor = 0.4
        else:
            interval_ratio = max(0.05, (action.at - previous_at) / pattern.duration_ms)
            delay_factor = _clamp(interval_ratio * 3.0, 0.35, 1.1)
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
