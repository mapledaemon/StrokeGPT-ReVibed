import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _as_number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MotionTarget:
    speed: float
    depth: float
    stroke_range: float
    label: str = "custom"

    def clamped(self) -> "MotionTarget":
        return MotionTarget(
            speed=_clamp(self.speed),
            depth=_clamp(self.depth),
            stroke_range=_clamp(self.stroke_range, 5.0, 100.0),
            label=self.label,
        )

    def rounded(self) -> "MotionTarget":
        target = self.clamped()
        return MotionTarget(
            speed=round(target.speed),
            depth=round(target.depth),
            stroke_range=round(target.stroke_range),
            label=target.label,
        )


@dataclass(frozen=True)
class ParsedIntent:
    kind: str
    target: Optional[MotionTarget] = None
    matched: str = ""


@dataclass(frozen=True)
class TransitionLimits:
    max_speed_delta: float = 12.0
    max_depth_delta: float = 10.0
    max_range_delta: float = 14.0


class IntentMatcher:
    """Deterministic natural-language controls that take precedence over LLM output."""

    STOP_PATTERNS = (
        r"\bstop\b",
        r"\bpause\b",
        r"\bhalt\b",
        r"\bfreeze\b",
        r"\bhold\b",
        r"\bwait\b",
    )
    STOP_NEGATIONS = (
        r"\bdon'?t\s+stop\b",
        r"\bdo\s+not\s+stop\b",
        r"\bkeep\s+going\b",
        r"\bcontinue\b",
    )
    CONTROL_PATTERNS = (
        ("auto_on", (r"\btake\s+over\b", r"\byou\s+drive\b", r"\bauto\s+mode\b")),
        ("auto_off", (r"\bstop\s+auto\b", r"\bmanual\b", r"\bmy\s+turn\b")),
        ("edging", (r"\bedge\s+me\b", r"\bstart\s+edging\b", r"\btease\s+and\s+deny\b")),
        ("milking", (r"\bi'?m\s+close\b", r"\bfinish\s+me\b")),
    )

    def parse(self, text: str, current: MotionTarget) -> ParsedIntent:
        clean_text = self._normalize(text)
        if not clean_text:
            return ParsedIntent("none")

        for kind, patterns in self.CONTROL_PATTERNS:
            if self._matches_any(clean_text, patterns):
                return ParsedIntent(kind, matched=kind)

        if self._matches_any(clean_text, self.STOP_PATTERNS) and not self._matches_any(clean_text, self.STOP_NEGATIONS):
            return ParsedIntent("stop", matched="stop")

        target = self._motion_target(clean_text, current)
        if target:
            return ParsedIntent("move", target=target.clamped(), matched=target.label)
        return ParsedIntent("none")

    def _motion_target(self, text: str, current: MotionTarget) -> Optional[MotionTarget]:
        speed = current.speed
        depth = current.depth
        stroke_range = current.stroke_range
        labels = []

        if self._matches_any(text, (r"\bfaster\b", r"\bspeed\s+up\b", r"\bmore\s+speed\b")):
            speed += 18
            labels.append("faster")
        if self._matches_any(text, (r"\bslower\b", r"\bslow\s+down\b", r"\bease\s+up\b")):
            speed -= 18
            labels.append("slower")
        if self._matches_any(text, (r"\bharder\b", r"\bstronger\b", r"\bmore\s+intense\b")):
            speed += 15
            stroke_range += 10
            labels.append("harder")
        if self._matches_any(text, (r"\bgentle\b", r"\bsofter\b", r"\blighter\b")):
            speed -= 12
            stroke_range -= 8
            labels.append("gentle")
        if self._matches_any(text, (r"\bdeeper\b", r"\bgo\s+deep\b", r"\bmore\s+depth\b")):
            depth += 18
            labels.append("deeper")
        if self._matches_any(text, (r"\bshallower\b", r"\bnot\s+so\s+deep\b")):
            depth -= 18
            labels.append("shallower")
        if self._matches_any(text, (r"\btip\b", r"\bshallow\b")):
            depth = min(depth, 15)
            stroke_range = min(stroke_range, 25)
            speed = min(max(speed, 22), 45)
            labels.append("tip")
        if self._matches_any(text, (r"\bfull\s+stroke", r"\bfull\s+range\b", r"\bwhole\b", r"\ball\s+the\s+way\b")):
            depth = 50
            stroke_range = 95
            speed = max(speed, 38)
            labels.append("full")
        if self._matches_any(text, (r"\bshort\s+stroke", r"\bsmall\s+stroke", r"\btight\s+stroke")):
            stroke_range = min(stroke_range, 28)
            labels.append("short")
        if self._matches_any(text, (r"\blong\s+stroke", r"\bbig\s+stroke")):
            stroke_range = max(stroke_range, 75)
            labels.append("long")
        if self._matches_any(text, (r"\bsteady\b", r"\bconsistent\b", r"\bconstant\b")):
            labels.append("steady")

        if not labels:
            return None
        return MotionTarget(speed, depth, stroke_range, "+".join(labels))

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower()).strip()

    def _matches_any(self, text: str, patterns: Iterable[str]) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)


class MotionSanitizer:
    """Turns untrusted LLM move JSON into a bounded target."""

    def __init__(self, limits: Optional[TransitionLimits] = None):
        self.limits = limits or TransitionLimits()

    def from_llm_move(self, move: Any, current: MotionTarget) -> Optional[MotionTarget]:
        if not isinstance(move, dict):
            return None

        speed = self._read_field(move, ("sp", "speed"))
        depth = self._read_field(move, ("dp", "depth"))
        stroke_range = self._read_field(move, ("rng", "range", "stroke_range"))
        if speed is None and depth is None and stroke_range is None:
            return None

        target = MotionTarget(
            current.speed if speed is None else speed,
            current.depth if depth is None else depth,
            current.stroke_range if stroke_range is None else stroke_range,
            label="llm",
        ).clamped()
        return target

    def transition_path(self, current: MotionTarget, target: MotionTarget) -> list[MotionTarget]:
        target = target.clamped()
        current = current.clamped()
        steps = max(
            1,
            math.ceil(abs(target.speed - current.speed) / self.limits.max_speed_delta),
            math.ceil(abs(target.depth - current.depth) / self.limits.max_depth_delta),
            math.ceil(abs(target.stroke_range - current.stroke_range) / self.limits.max_range_delta),
        )

        path = []
        for index in range(1, steps + 1):
            amount = index / steps
            path.append(
                MotionTarget(
                    speed=current.speed + (target.speed - current.speed) * amount,
                    depth=current.depth + (target.depth - current.depth) * amount,
                    stroke_range=current.stroke_range + (target.stroke_range - current.stroke_range) * amount,
                    label=target.label,
                ).rounded()
            )
        return path

    def _read_field(self, move: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
        for key in keys:
            value = _as_number(move.get(key))
            if value is not None:
                return value
        return None


class MotionController:
    """Single gateway for all physical movement."""

    def __init__(self, handy, sanitizer: Optional[MotionSanitizer] = None, step_delay: float = 0.25):
        self.handy = handy
        self.sanitizer = sanitizer or MotionSanitizer()
        self.step_delay = step_delay
        self._lock = threading.Lock()
        self._generation = 0

    def current_target(self) -> MotionTarget:
        return MotionTarget(
            self.handy.last_relative_speed,
            self.handy.last_depth_pos,
            getattr(self.handy, "last_stroke_range", 50),
            label="current",
        ).clamped()

    def apply_target(self, target: MotionTarget, smooth: bool = True) -> None:
        if target.speed <= 0:
            self.stop()
            return

        with self._lock:
            self._generation += 1
            generation = self._generation
            current = self.current_target()

        if not smooth:
            self._apply_step(target)
            return

        for step in self.sanitizer.transition_path(current, target):
            with self._lock:
                if generation != self._generation:
                    return
            self._apply_step(step)
            time.sleep(self.step_delay)

    def apply_llm_move(self, move: Any) -> Optional[MotionTarget]:
        target = self.sanitizer.from_llm_move(move, self.current_target())
        if target:
            self.apply_target(target)
        return target

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
        self.handy.stop()

    def _apply_step(self, target: MotionTarget) -> None:
        target = target.rounded()
        self.handy.move(target.speed, target.depth, target.stroke_range)
