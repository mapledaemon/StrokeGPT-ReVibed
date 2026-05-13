import inspect
import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional

from .motion_anchors import coerce_anchor_program_dict


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _minimum_jerk(amount: float) -> float:
    amount = _clamp(amount, 0.0, 1.0)
    return 10.0 * amount**3 - 15.0 * amount**4 + 6.0 * amount**5


def _lerp(start: float, end: float, amount: float) -> float:
    return start + (end - start) * _clamp(amount, 0.0, 1.0)


POSITION_MAX_DEPTH_STEP = 9.0
POSITION_BLEND_DELAY_FACTOR = 0.16
POSITION_TURN_DELAY_FACTOR = 0.2
TURN_BRAKE_SPEED_FACTOR = 0.45
POSITION_PASS_THROUGH_MIN_SECONDS = 0.35
CONTINUOUS_SAMPLE_INTERVAL_SECONDS = 0.16
CONTINUOUS_MIN_COMMAND_INTERVAL_SECONDS = 0.08
CONTINUOUS_MAX_COMMAND_INTERVAL_SECONDS = 0.28
CONTINUOUS_STREAM_INITIAL_BUFFER_SECONDS = 2.4
CONTINUOUS_STREAM_TARGET_BUFFER_SECONDS = 2.4
CONTINUOUS_STREAM_APPEND_THRESHOLD_SECONDS = 1.0
CONTINUOUS_STREAM_MAX_POINTS_PER_COMMAND = 80
CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS = 0.12
CONTINUOUS_MORPH_SECONDS = 0.65
CONTINUOUS_MIN_MORPH_SECONDS = 0.32
CONTINUOUS_MAX_MORPH_SECONDS = 1.15


def _depth_direction(start: "MotionTarget", end: "MotionTarget", threshold: float = 7.0) -> int:
    delta = end.depth - start.depth
    if abs(delta) < threshold:
        return 0
    return 1 if delta > 0 else -1


def _turn_slowdown_speed(start: "MotionTarget", end: "MotionTarget") -> float:
    base_speed = min(start.speed, end.speed)
    if base_speed <= 8.0:
        return base_speed
    return max(8.0, base_speed * TURN_BRAKE_SPEED_FACTOR)


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
    motion_program: Optional[dict[str, Any]] = None

    def clamped(self) -> "MotionTarget":
        return MotionTarget(
            speed=_clamp(self.speed),
            depth=_clamp(self.depth),
            stroke_range=_clamp(self.stroke_range, 5.0, 100.0),
            label=self.label,
            motion_program=self.motion_program,
        )

    def rounded(self) -> "MotionTarget":
        target = self.clamped()
        return MotionTarget(
            speed=round(target.speed),
            depth=round(target.depth),
            stroke_range=round(target.stroke_range),
            label=target.label,
            motion_program=target.motion_program,
        )


@dataclass(frozen=True)
class ParsedIntent:
    kind: str
    target: Optional[MotionTarget] = None
    matched: str = ""


@dataclass(frozen=True)
class PositionFrame:
    target: MotionTarget
    delay_factor: float
    phase: str = "pattern"


@dataclass(frozen=True)
class TransitionLimits:
    max_speed_delta: float = 25.0
    max_depth_delta: float = 25.0
    max_range_delta: float = 30.0


@dataclass(frozen=True)
class ContinuousPhaseState:
    key: tuple[Any, ...]
    generation: int
    started_at: float
    offset_seconds: float = 0.0
    phase_rate: float = 1.0
    plan: Any = None
    target: Optional[MotionTarget] = None


@dataclass(frozen=True)
class MotionCues:
    zone: Optional[str] = None
    length: Optional[str] = None
    pattern: Optional[str] = None
    speed_hint: Optional[str] = None

    def labels(self) -> list[str]:
        return [part for part in (self.zone, self.length, self.pattern, self.speed_hint) if part]


ZONE_DEFAULTS = {
    "tip": {"depth": 10.0, "range": 36.0, "speed": 30.0},
    "upper": {"depth": 25.0, "range": 48.0, "speed": 34.0},
    "middle": {"depth": 50.0, "range": 62.0, "speed": 38.0},
    "base": {"depth": 88.0, "range": 40.0, "speed": 42.0},
    "full": {"depth": 50.0, "range": 95.0, "speed": 46.0},
}

LENGTH_DEFAULTS = {
    "tiny": 12.0,
    "short": 24.0,
    "half": 50.0,
    "long": 75.0,
    "full": 95.0,
}

SPEED_DEFAULTS = {
    "crawl": 16.0,
    "slow": 24.0,
    "medium": 42.0,
    "fast": 64.0,
    "max": 86.0,
}

def _compile_patterns(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in patterns)


def _compile_groups(
    *groups: tuple[str, tuple[str, ...]],
) -> tuple[tuple[str, tuple[re.Pattern[str], ...]], ...]:
    return tuple((name, _compile_patterns(*patterns)) for name, patterns in groups)


# Module-level regex constants are pre-compiled once at import time so the
# detection helpers below can match against pattern objects directly instead of
# recompiling source strings on every chat turn / playback frame.
ZONE_PATTERNS = _compile_groups(
    ("full", (r"\bbase\s+to\s+tip\b", r"\btip\s+to\s+base\b", r"\bwhole\s+(?:thing|length)\b", r"\bentire\s+length\b")),
    ("base", (r"\bbase\b", r"\broot\b", r"\bbottom\b", r"\bdeepthroat\b", r"\bgag\b", r"\bdeep\s+(?:only|strokes?|position)\b")),
    ("tip", (r"\btip\b", r"\bhead\b", r"\bshallow\b", r"\btop\b")),
    ("upper", (r"\bupper\b", r"\bnear\s+the\s+tip\b", r"\bfront\b")),
    ("middle", (r"\bmiddle\b", r"\bmid(?:dle)?\s+shaft\b", r"\bshaft\b", r"\bcenter\b", r"\bcentre\b")),
)

LENGTH_PATTERNS = _compile_groups(
    ("full", (r"\bfull\s+(?:stroke|range|length|sweep|travel|strokes)\b", r"\ball\s+the\s+way\b", r"\bwhole\s+(?:thing|length)\b")),
    ("half", (r"\bhalf\b(?:\s+(?:stroke|range|length|way))?", r"\bhalfway\b")),
    ("tiny", (r"\btiny\b", r"\bmicro\b", r"\btwitch(?:y|ing)?\b")),
    ("short", (r"\bshort\s+(?:stroke|range|strokes)?\b", r"\bsmall\s+(?:stroke|range|strokes)?\b", r"\btight\s+(?:stroke|range|strokes)?\b")),
    ("long", (r"\blong\s+(?:stroke|range|strokes)?\b", r"\bbig\s+(?:stroke|range|strokes)?\b", r"\bwide\s+(?:stroke|range|strokes)?\b")),
)

PATTERN_PATTERNS = _compile_groups(
    ("anchor_loop", (r"\bsoft\s+bounce\b", r"\bbounce\b", r"\banchor\s+loop\b", r"\bspline\b")),
    ("milk", (r"\bmilk(?:ing)?\b",)),
    ("flutter", (r"\bflutter\b", r"\bstutter\b", r"\bquick\s+little\s+pulses?\b")),
    ("flick", (r"\bflicks?\b", r"\bsnap\b")),
    ("pulse", (r"\bpuls(?:e|ing)\b", r"\bpump(?:ing)?\b")),
    ("hold", (r"\bhold\b", r"\bpress\b", r"\bgrind\b")),
    ("wave", (r"\bwave\b", r"\brolling\b", r"\boscillat(?:e|ing)\b")),
    ("ramp", (r"\bramp\b", r"\bclimb\b", r"\bbuild\b")),
    ("ladder", (r"\bladder\b", r"\bstep(?:ped|s)?\b")),
    ("surge", (r"\bsurge\b", r"\bswell\b", r"\bcrescendo\b")),
    ("sway", (r"\bsway\b", r"\balternat(?:e|ing)\b", r"\bsmooth\s+alternation\b")),
    ("tease", (r"\btease\b", r"\bedge\b")),
    ("stroke", (r"\bstroke\b", r"\bstroking\b")),
)

SPEED_PATTERNS = _compile_groups(
    ("max", (r"\bmaximum\b", r"\bmax\b", r"\bvery\s+fast\b")),
    ("fast", (r"\bfast\b", r"\bquick\b", r"\brapid\b")),
    ("crawl", (r"\bcrawl\b", r"\bvery\s+slow\b")),
    ("slow", (r"\bslow(?:ly)?\b", r"\bgentle\b", r"\bsoft\b")),
    ("medium", (r"\bmedium\b", r"\bsteady\b", r"\bconsistent\b")),
)


_WHITESPACE_RE = re.compile(r"\s+")
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9_-]+")
_SLUG_DASH_RUN_RE = re.compile(r"-{2,}")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value).lower()).strip()


def _slugify_motion_pattern_id(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    cleaned = _SLUG_INVALID_RE.sub("-", cleaned)
    cleaned = _SLUG_DASH_RUN_RE.sub("-", cleaned).strip("-_")
    return cleaned[:64]


def _matches_any(text: str, patterns: Iterable[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _detect_from_patterns(
    text: str,
    pattern_groups: Iterable[tuple[str, tuple[re.Pattern[str], ...]]],
) -> Optional[str]:
    clean_text = _normalize_text(text)
    if not clean_text:
        return None
    for name, patterns in pattern_groups:
        if name == clean_text or _matches_any(clean_text, patterns):
            return name
    return None


def _detect_motion_cues(text: str) -> MotionCues:
    return MotionCues(
        zone=_detect_from_patterns(text, ZONE_PATTERNS),
        length=_detect_from_patterns(text, LENGTH_PATTERNS),
        pattern=_detect_from_patterns(text, PATTERN_PATTERNS),
        speed_hint=_detect_from_patterns(text, SPEED_PATTERNS),
    )


def _depth_for_zone_and_length(zone: str, length: Optional[str]) -> float:
    if zone == "full" or length == "full":
        return 50.0
    if length == "half":
        if zone == "tip":
            return 25.0
        if zone == "base":
            return 75.0
    return ZONE_DEFAULTS[zone]["depth"]


def _is_endpoint_depth(depth: float) -> bool:
    return depth <= 18.0 or depth >= 82.0


def _explicit_tight_request(cues: MotionCues) -> bool:
    return cues.length in {"tiny", "short"} or cues.pattern in {"flick", "flutter", "hold"}


def _range_with_broad_default(current: MotionTarget, depth: float, stroke_range: float, cues: MotionCues) -> float:
    if _explicit_tight_request(cues):
        return stroke_range
    if cues.length in {"half", "long", "full"} or cues.zone == "full":
        return stroke_range
    if _is_endpoint_depth(depth):
        floor = 48.0 if current.stroke_range <= 30.0 and _is_endpoint_depth(current.depth) else 36.0
        return max(stroke_range, floor)
    return max(stroke_range, 50.0)


def _regional_motion_program(cues: MotionCues, existing_program: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if existing_program or not cues.zone or cues.zone == "full" or _explicit_tight_request(cues):
        return existing_program
    return coerce_anchor_program_dict(
        {
            "motion": "anchor_loop",
            "tempo": 0.75,
            "softness": 0.86,
            "variation": 0.06,
            "max_step_delta": 28,
        },
        zone=cues.zone,
        length=cues.length,
        require_request=False,
    )


def _cue_base_speed(current_speed: float, cues: MotionCues, *, preserve_current_speed: bool) -> float:
    next_speed = current_speed if preserve_current_speed else None
    if cues.zone:
        zone_speed = ZONE_DEFAULTS[cues.zone]["speed"]
        next_speed = max(next_speed, zone_speed) if next_speed is not None else zone_speed
    if cues.speed_hint:
        next_speed = SPEED_DEFAULTS[cues.speed_hint]
    if next_speed is None:
        next_speed = current_speed
    return next_speed


def _target_from_cues(
    current: MotionTarget,
    cues: MotionCues,
    *,
    speed: Optional[float] = None,
    depth: Optional[float] = None,
    stroke_range: Optional[float] = None,
    label_prefix: Optional[str] = None,
    motion_program: Optional[dict[str, Any]] = None,
    preserve_current_speed: bool = False,
) -> MotionTarget:
    next_speed = _cue_base_speed(current.speed, cues, preserve_current_speed=preserve_current_speed)
    next_depth = current.depth
    next_range = current.stroke_range

    if cues.zone:
        zone_defaults = ZONE_DEFAULTS[cues.zone]
        next_depth = _depth_for_zone_and_length(cues.zone, cues.length)
        next_range = zone_defaults["range"]

    if cues.length:
        next_range = LENGTH_DEFAULTS[cues.length]
        if cues.length == "full":
            next_depth = 50.0
        elif cues.zone:
            next_depth = _depth_for_zone_and_length(cues.zone, cues.length)

    if cues.pattern == "flutter":
        next_speed = max(next_speed, 58.0)
        next_range = min(next_range, 16.0)
    elif cues.pattern == "flick":
        next_speed = max(next_speed, 55.0)
        next_range = min(next_range, 18.0)
    elif cues.pattern == "milk":
        next_speed = max(next_speed, 52.0)
        if not cues.zone or cues.zone == "full":
            next_depth = 50.0
        if (not cues.zone or cues.zone == "full") and cues.length not in {"tiny", "short", "half"}:
            next_range = max(next_range, 92.0)
    elif cues.pattern == "pulse":
        next_speed = max(next_speed, 44.0)
        next_range = min(next_range, 34.0)
    elif cues.pattern == "hold":
        next_speed = min(max(next_speed, 16.0), 30.0)
        next_range = min(next_range, 12.0)
    elif cues.pattern == "wave":
        next_range = max(next_range, 55.0)
    elif cues.pattern == "ramp":
        next_speed = max(next_speed, 38.0)
        next_range = max(next_range, 50.0)
    elif cues.pattern == "ladder":
        next_speed = max(next_speed, 40.0)
        next_range = max(next_range, 45.0)
    elif cues.pattern == "surge":
        next_speed = max(next_speed, 46.0)
        next_range = max(next_range, 60.0)
    elif cues.pattern == "sway":
        next_speed = max(next_speed, 34.0)
        next_range = max(next_range, 55.0)
    elif cues.pattern == "anchor_loop":
        next_speed = max(next_speed, 36.0)
        next_range = max(next_range, 55.0)
    elif cues.pattern == "tease":
        next_speed = min(max(next_speed, 22.0), 38.0)
        next_range = min(next_range, 34.0)

    if motion_program and cues.pattern != "anchor_loop":
        next_speed = max(next_speed, 36.0)
        next_range = max(next_range, 55.0)

    if speed is not None:
        next_speed = speed
    if depth is not None:
        next_depth = depth
    if stroke_range is not None:
        next_range = stroke_range

    if stroke_range is None:
        next_range = _range_with_broad_default(current, next_depth, next_range, cues)

    motion_program = _regional_motion_program(cues, motion_program)

    labels = cues.labels()
    if label_prefix:
        labels.insert(0, label_prefix)
    return MotionTarget(
        next_speed,
        next_depth,
        next_range,
        "+".join(labels) or "custom",
        motion_program=motion_program,
    ).clamped()


_INTENT_FASTER_PATTERNS = _compile_patterns(r"\bfaster\b", r"\bspeed\s+up\b", r"\bmore\s+speed\b")
_INTENT_SLOWER_PATTERNS = _compile_patterns(r"\bslower\b", r"\bslowly\b", r"\bslow\s+down\b", r"\bease\s+up\b")
_INTENT_HARDER_PATTERNS = _compile_patterns(r"\bharder\b", r"\bstronger\b", r"\bmore\s+intense\b")
_INTENT_GENTLE_PATTERNS = _compile_patterns(r"\bgentle\b", r"\bsofter\b", r"\blighter\b")
_INTENT_DEEPER_PATTERNS = _compile_patterns(r"\bdeeper\b", r"\bgo\s+deep\b", r"\bmore\s+depth\b")
_INTENT_SHALLOWER_PATTERNS = _compile_patterns(r"\bshallower\b", r"\bnot\s+so\s+deep\b")
_INTENT_ANCHOR_PROGRAM_PATTERNS = _compile_patterns(
    r"\bsoft\s+bounce\b", r"\bbounce\b", r"\banchor\s+loop\b", r"\bspline\b"
)


class IntentMatcher:
    """Deterministic natural-language controls that take precedence over LLM output."""

    STOP_PATTERNS = _compile_patterns(
        r"\bstop\b",
        r"\bpause\b",
        r"\bhalt\b",
        r"\bfreeze\b",
        r"\bhold\s+(?:on|still|up)\b",
        r"\bwait\b",
    )
    STOP_NEGATIONS = _compile_patterns(
        r"\bdon'?t\s+stop\b",
        r"\bdo\s+not\s+stop\b",
        r"\bkeep\s+going\b",
        r"\bcontinue\b",
    )
    CONTROL_PATTERNS = _compile_groups(
        ("auto_on", (r"\btake\s+over\b", r"\byou\s+drive\b", r"\bauto\s+mode\b")),
        ("auto_off", (r"\bstop\s+auto\b", r"\bmanual\b", r"\bmy\s+turn\b")),
        ("freestyle", (r"\bfreestyle\b", r"\badaptive\s+motion\b", r"\bneural\s+style\b")),
        ("edging", (r"\bedge\s+me\b", r"\bstart\s+edging\b", r"\btease\s+and\s+deny\b")),
        ("milking", (r"\bi'?m\s+close\b", r"\bfinish\s+me\b")),
    )
    INFORMATIONAL_PATTERNS = _compile_patterns(
        r"\bwhat\s+(?:does|do|is|are)\b.*\b(?:mean|means|meaning)\b",
        r"\b(?:explain|describe|define|tell\s+me\s+about)\b",
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

        if self._matches_any(clean_text, self.INFORMATIONAL_PATTERNS):
            return ParsedIntent("none")

        target = self._motion_target(clean_text, current)
        if target:
            return ParsedIntent("move", target=target.clamped(), matched=target.label)
        return ParsedIntent("none")

    def _motion_target(self, text: str, current: MotionTarget) -> Optional[MotionTarget]:
        speed = current.speed
        depth = current.depth
        stroke_range = current.stroke_range
        labels = []
        cues = _detect_motion_cues(text)
        motion_program = self._motion_program_from_text(text, cues)

        if self._matches_any(text, _INTENT_FASTER_PATTERNS):
            speed += 22
            labels.append("faster")
        if self._matches_any(text, _INTENT_SLOWER_PATTERNS):
            speed -= 22
            labels.append("slower")
        if self._matches_any(text, _INTENT_HARDER_PATTERNS):
            speed += 20
            stroke_range += 12
            labels.append("harder")
        if self._matches_any(text, _INTENT_GENTLE_PATTERNS):
            speed -= 15
            stroke_range -= 10
            labels.append("gentle")
        if self._matches_any(text, _INTENT_DEEPER_PATTERNS):
            depth += 20
            labels.append("deeper")
        if self._matches_any(text, _INTENT_SHALLOWER_PATTERNS):
            depth -= 20
            labels.append("shallower")

        if cues.labels():
            cue_target = _target_from_cues(
                MotionTarget(speed, depth, stroke_range),
                cues,
                label_prefix="+".join(labels) if labels else None,
                motion_program=motion_program,
                preserve_current_speed=bool(labels),
            )
            return cue_target

        if motion_program:
            return _target_from_cues(
                MotionTarget(speed, depth, stroke_range),
                MotionCues(pattern="anchor_loop"),
                label_prefix="+".join(labels) if labels else None,
                motion_program=motion_program,
                preserve_current_speed=bool(labels),
            )

        if not labels:
            return None
        if stroke_range < 35.0:
            stroke_range = 45.0
        return MotionTarget(speed, depth, stroke_range, "+".join(labels))

    def _motion_program_from_text(self, text: str, cues: MotionCues) -> Optional[dict[str, Any]]:
        if not self._matches_any(text, _INTENT_ANCHOR_PROGRAM_PATTERNS):
            return None
        return coerce_anchor_program_dict(
            {"motion": "anchor_loop"},
            zone=cues.zone,
            length=cues.length,
            text=text,
            require_request=False,
        )

    def _normalize(self, text: str) -> str:
        return _WHITESPACE_RE.sub(" ", text.lower()).strip()

    def _matches_any(self, text: str, patterns: Iterable[re.Pattern[str]]) -> bool:
        return any(pattern.search(text) for pattern in patterns)


class MotionSanitizer:
    """Normalizes LLM move JSON into a reliable Handy target."""

    def __init__(self, limits: Optional[TransitionLimits] = None):
        self.limits = limits or TransitionLimits()

    def from_llm_move(self, move: Any, current: MotionTarget) -> Optional[MotionTarget]:
        if not isinstance(move, dict):
            return None

        cue_text = " ".join(
            str(move.get(key))
            for key in (
                "zone",
                "area",
                "anchor",
                "position",
                "pattern",
                "shape",
                "style",
                "motion",
                "length",
                "range",
                "stroke_range",
                "rng",
                "speed",
                "tempo",
                "pace",
                "sp",
            )
            if move.get(key) is not None and _as_number(move.get(key)) is None
        )
        cues = _detect_motion_cues(cue_text)
        explicit_pattern = self._explicit_pattern_id(move.get("pattern"))
        if explicit_pattern:
            cues = MotionCues(
                zone=cues.zone,
                length=cues.length,
                pattern=explicit_pattern,
                speed_hint=cues.speed_hint,
            )
        motion_program = coerce_anchor_program_dict(
            move,
            zone=cues.zone,
            length=cues.length,
            text=cue_text,
        )
        speed_keys = ("sp", "speed", "intensity") if motion_program else ("sp", "speed", "tempo", "pace", "intensity")
        speed = self._read_field(move, speed_keys)
        depth = self._read_field(move, ("dp", "depth", "position", "center", "centre", "anchor"))
        stroke_range = self._read_field(move, ("rng", "range", "stroke_range", "length", "amplitude", "span"))

        if speed is None and depth is None and stroke_range is None and not cues.labels() and not motion_program:
            return None

        label_prefix = "llm+anchor_loop" if motion_program and not cues.labels() else "llm"
        return _target_from_cues(
            current,
            cues,
            speed=speed,
            depth=depth,
            stroke_range=stroke_range,
            label_prefix=label_prefix,
            motion_program=motion_program,
        )

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

    def _explicit_pattern_id(self, value: Any) -> Optional[str]:
        pattern_id = _slugify_motion_pattern_id(value)
        if not pattern_id:
            return None
        from .motion_patterns import PATTERNS

        return pattern_id if pattern_id in PATTERNS else None


class MotionController:
    """Single gateway for all physical movement."""

    def __init__(self, handy, sanitizer: Optional[MotionSanitizer] = None, step_delay: float = 0.25):
        self.handy = handy
        self.sanitizer = sanitizer or MotionSanitizer()
        self.step_delay = step_delay
        self.backend = "continuous"
        self._lock = threading.Lock()
        self._generation = 0
        self._observability_lock = threading.Lock()
        self._trace = deque(maxlen=180)
        self._last_source = "idle"
        self._last_label = "idle"
        self._last_command_time = None
        self._frame_playback_active = False
        self._last_position_command_ended_at = None
        self._last_position_batch_ended_at = None
        self._continuous_phase_state: Optional[ContinuousPhaseState] = None
        self._move_to_depth_accepts_intent_speed: Optional[bool] = None
        self._move_to_depth_accepts_duration_ms: Optional[bool] = None
        self._pause_event = threading.Event()

    def set_backend(self, backend: str) -> None:
        normalized = self._normalize_backend(backend)
        if normalized != self.backend:
            with self._lock:
                self._generation += 1
            self._set_frame_playback_active(False)
            self.backend = normalized
            self._record_current_state(source="settings", label=f"{self.backend} backend")
        else:
            self.backend = normalized

    def _normalize_backend(self, backend: str) -> str:
        cleaned = str(backend or "").strip().lower().replace("-", "_")
        if cleaned in {"continuous", "continuous_position", "pattern", "pattern_position", "position_continuous"}:
            return "continuous"
        if cleaned in {"position", "position_script", "flexible_position", "flexible"}:
            return "position"
        return "hamp"

    def current_target(self) -> MotionTarget:
        estimated = self._estimated_continuous_target()
        if estimated is not None:
            return estimated.clamped()
        return MotionTarget(
            self.handy.last_relative_speed,
            self.handy.last_depth_pos,
            getattr(self.handy, "last_stroke_range", 50),
            label="current",
        ).clamped()

    def _estimated_continuous_target(self) -> Optional[MotionTarget]:
        try:
            state = self._continuous_phase_state
            generation = self._generation
            active = self._frame_playback_active
            if (
                not active
                or state is None
                or state.generation != generation
                or state.plan is None
                or state.target is None
            ):
                return None
            from .motion_patterns import sample_continuous_motion

            elapsed = state.offset_seconds + max(0.0, time.monotonic() - state.started_at)
            sample = self._sample_continuous_motion(
                state.plan,
                state.target,
                elapsed,
                sample_continuous_motion,
            )
            return MotionTarget(
                sample.intent_speed,
                sample.target.depth,
                sample.target.stroke_range,
                label=sample.target.label,
                motion_program=sample.target.motion_program,
            )
        except Exception:
            return None

    def apply_target(self, target: MotionTarget, smooth: bool = True, source: str = "target") -> None:
        if target.speed <= 0:
            self.stop()
            return

        if smooth and self.backend == "position":
            self.apply_position_frames(self._direct_position_frames(target), source=source)
            return

        with self._lock:
            self._generation += 1
            generation = self._generation
            current = self.current_target()

        if not smooth:
            if not self._wait_for_resume(generation):
                return
            self._apply_step(target, source=source)
            return

        for step in self.sanitizer.transition_path(current, target):
            with self._lock:
                if generation != self._generation:
                    return
            if not self._wait_for_resume(generation):
                return
            self._apply_step(step, source=source)
            if not self._sleep_with_pause(self.step_delay, generation):
                return

    def apply_llm_move(self, move: Any) -> Optional[MotionTarget]:
        target = self.sanitizer.from_llm_move(move, self.current_target())
        if target:
            self.apply_generated_target(target, source="llm")
        return target

    def apply_generated_target(self, target: MotionTarget, source: str = "generated") -> None:
        if target.speed <= 0:
            self.stop()
            return

        if self.backend == "continuous":
            if self.apply_continuous_target(target, source=source):
                return
            self.apply_target(target, source=source)
            return

        frames = self._expanded_frames(target, preserve_timing=self.backend == "position")
        if frames:
            if self.backend == "position":
                self.apply_position_frames(frames, source=source)
            else:
                self.apply_frames(frames, source=source)
        elif self.backend == "position":
            self.apply_position_frames(self._direct_position_frames(target), source=source)
        else:
            self.apply_target(target, source=source)

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
        self._pause_event.clear()
        self._set_frame_playback_active(False)
        self.handy.stop()
        self._record_current_state(source="stop", label="stopped")

    def pause(self) -> None:
        self._pause_event.set()
        self._set_frame_playback_active(False)
        self.handy.stop()

    def resume(self) -> None:
        self._pause_event.clear()

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def _wait_for_resume(self, generation: int) -> bool:
        while self._pause_event.is_set():
            with self._lock:
                if generation != self._generation:
                    return False
            time.sleep(0.05)
        with self._lock:
            return generation == self._generation

    def _sleep_with_pause(self, seconds: float, generation: int) -> bool:
        seconds = max(0.0, float(seconds or 0.0))
        deadline = time.monotonic() + seconds
        while True:
            with self._lock:
                if generation != self._generation:
                    return False
            if self._pause_event.is_set():
                paused_at = time.monotonic()
                if not self._wait_for_resume(generation):
                    return False
                deadline += time.monotonic() - paused_at
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.05, remaining))

    def _apply_step(self, target: MotionTarget, source: str = "target") -> None:
        target = target.rounded()
        result = self.handy.move(target.speed, target.depth, target.stroke_range)
        self._record_target(target, source=source)
        self._augment_last_trace(self._handy_command_trace_extras(result))

    def _handy_command_trace_extras(self, result: Any) -> dict[str, Any]:
        last_command = None
        if hasattr(self.handy, "last_command_result"):
            try:
                last_command = self.handy.last_command_result()
            except Exception:
                last_command = None

        extras: dict[str, Any] = {"handy_ok": result is not False}
        if not isinstance(last_command, dict):
            return extras

        path = str(last_command.get("path") or "").strip()
        if path:
            extras["handy_path"] = path
        if "status_code" in last_command:
            extras["handy_status"] = last_command.get("status_code")
        if "elapsed_ms" in last_command:
            extras["handy_elapsed_ms"] = last_command.get("elapsed_ms")
        body = last_command.get("body")
        if isinstance(body, dict):
            if "velocity" in body:
                extras["handy_velocity"] = body.get("velocity")
            if "duration" in body:
                extras["handy_duration_ms"] = body.get("duration")
            if "t" in body:
                extras["handy_duration_ms"] = body.get("t")
            if "xp" in body:
                extras["handy_xp"] = body.get("xp")
            if "stopOnTarget" in body:
                extras["handy_stop_on_target"] = bool(body.get("stopOnTarget"))
            if "stop_on_target" in body:
                extras["handy_stop_on_target"] = bool(body.get("stop_on_target"))
        error = str(last_command.get("error") or "").strip()
        if error:
            extras["handy_error"] = error
        if last_command.get("ok") is False:
            extras["handy_ok"] = False
        return extras

    def _depth_range_for_targets(self, targets: Iterable[Any]) -> Optional[dict[str, int]]:
        depths: list[float] = []
        for raw in targets:
            target = raw
            if not isinstance(target, MotionTarget):
                target = getattr(raw, "target", None)
            if isinstance(target, MotionTarget):
                depths.append(target.clamped().depth)
        if not depths:
            return None
        return {
            "min": int(round(_clamp(min(depths)))),
            "max": int(round(_clamp(max(depths)))),
        }

    def _position_velocity_cap(self, target: MotionTarget) -> int | None:
        if hasattr(self.handy, "max_velocity_for_relative_speed"):
            try:
                return int(round(self.handy.max_velocity_for_relative_speed(target.speed)))
            except (TypeError, ValueError):
                return None
        if hasattr(self.handy, "_relative_speed_to_velocity"):
            try:
                velocity = int(round(self.handy._relative_speed_to_velocity(target.speed)))
                max_velocity = getattr(self.handy, "max_user_speed", None)
                if max_velocity is not None:
                    velocity = min(velocity, int(round(max_velocity)))
                return velocity
            except (TypeError, ValueError):
                return None
        try:
            return max(0, int(round(target.speed)))
        except (TypeError, ValueError):
            return None

    def _position_velocity(self, start: MotionTarget, target: MotionTarget, duration_seconds: float) -> int | None:
        velocity = None
        if hasattr(self.handy, "velocity_for_depth_interval"):
            velocity = self.handy.velocity_for_depth_interval(
                target.speed,
                start.depth,
                target.depth,
                duration_seconds,
            )
        cap = self._position_velocity_cap(target)
        if velocity is None:
            return cap
        try:
            velocity = int(round(velocity))
        except (TypeError, ValueError):
            return cap
        if cap is not None:
            velocity = min(velocity, cap)
        return max(0, velocity)

    def _minimum_position_duration_seconds(self, start: MotionTarget, target: MotionTarget) -> float:
        if abs(target.depth - start.depth) <= 0.001:
            return 0.0

        velocity = self._position_velocity_cap(target)
        if velocity is None or velocity <= 0:
            return 0.0

        if hasattr(self.handy, "duration_ms_for_depth_interval"):
            try:
                duration_ms = self.handy.duration_ms_for_depth_interval(velocity, start.depth, target.depth)
                return max(0.0, float(duration_ms) / 1000.0)
            except (TypeError, ValueError):
                return 0.0

        relative_to_mm = getattr(self.handy, "_relative_depth_to_mm", None)
        if callable(relative_to_mm):
            try:
                distance_mm = abs(float(relative_to_mm(target.depth)) - float(relative_to_mm(start.depth)))
                return distance_mm / max(1.0, float(velocity))
            except (TypeError, ValueError):
                return 0.0

        return 0.0

    def _coerce_position_frame(self, frame: Any) -> Optional[PositionFrame]:
        target = getattr(frame, "target", None)
        if not isinstance(target, MotionTarget):
            return None
        delay_factor = getattr(frame, "delay_factor", 1.0)
        try:
            delay_factor = max(0.0, float(delay_factor))
        except (TypeError, ValueError):
            delay_factor = 1.0
        return PositionFrame(
            target.clamped(),
            delay_factor=delay_factor,
            phase=str(getattr(frame, "phase", "pattern") or "pattern"),
        )

    def _direct_position_frames(self, target: MotionTarget) -> list[PositionFrame]:
        return [
            PositionFrame(step, delay_factor=1.0, phase="pattern")
            for step in self.sanitizer.transition_path(self.current_target(), target)
        ]

    def _is_turn_apex(self, frames: list[PositionFrame], index: int) -> bool:
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

    def _turn_apex_frame(self, frames: list[PositionFrame], index: int) -> PositionFrame:
        previous = frames[index - 1].target
        current = frames[index].target
        following = frames[index + 1].target
        turn_speed = min(
            _turn_slowdown_speed(previous, current),
            _turn_slowdown_speed(current, following),
        )
        label = current.label or "position"
        return PositionFrame(
            MotionTarget(
                turn_speed,
                current.depth,
                current.stroke_range,
                label=f"{label} turn apex",
            ).clamped(),
            delay_factor=max(frames[index].delay_factor, POSITION_TURN_DELAY_FACTOR),
            phase=frames[index].phase,
        )

    def _append_limited_position_frame(self, result: list[PositionFrame], frame: PositionFrame) -> None:
        if not result:
            result.append(frame)
            return

        previous = result[-1].target
        target = frame.target
        depth_delta = target.depth - previous.depth
        steps = max(0, math.ceil(abs(depth_delta) / POSITION_MAX_DEPTH_STEP) - 1)
        preserves_timing = frame.phase == "timed-pattern"
        split_delay_factor = frame.delay_factor
        if preserves_timing and steps > 0:
            split_delay_factor = frame.delay_factor / (steps + 1)
        for step in range(1, steps + 1):
            amount = step / (steps + 1)
            transition_speed = previous.speed + (target.speed - previous.speed) * amount
            if not preserves_timing:
                transition_speed = min(
                    transition_speed,
                    max(8.0, min(previous.speed, target.speed) * 0.82),
                )
            result.append(
                PositionFrame(
                    MotionTarget(
                        transition_speed,
                        previous.depth + depth_delta * amount,
                        previous.stroke_range + (target.stroke_range - previous.stroke_range) * amount,
                        label=f"{target.label or 'position'} transition blend {step}",
                    ).clamped(),
                    delay_factor=split_delay_factor if preserves_timing else POSITION_BLEND_DELAY_FACTOR,
                    phase="timed-blend" if preserves_timing else "blend",
                )
            )
        if preserves_timing and steps > 0:
            frame = PositionFrame(frame.target, delay_factor=split_delay_factor, phase=frame.phase)
        result.append(frame)

    def _position_playback_frames(self, frames: list[Any]) -> list[PositionFrame]:
        coerced = [frame for raw in frames if (frame := self._coerce_position_frame(raw)) is not None]
        if not coerced:
            return []
        # Seed with the controller's current state so the same depth-jump
        # splitter that smooths between frames also bridges from the device's
        # last commanded position into frames[0]. The seed is dropped before
        # the playback list is returned so it never gets sent to the device.
        seed = PositionFrame(self.current_target(), delay_factor=0.0, phase="seed")
        result: list[PositionFrame] = [seed]
        for index, frame in enumerate(coerced):
            if self._is_turn_apex(coerced, index):
                frame = self._turn_apex_frame(coerced, index)
            self._append_limited_position_frame(result, frame)
        return result[1:]

    def _apply_position_step(
        self,
        target: MotionTarget,
        *,
        stop_on_target: bool = True,
        velocity: int | None = None,
        intent_speed: float | None = None,
        duration_ms: int | None = None,
        source: str = "position",
    ) -> bool:
        target = target.rounded()
        if hasattr(self.handy, "move_to_depth"):
            kwargs: dict[str, Any] = {
                "stop_on_target": stop_on_target,
                "velocity": velocity,
            }
            if intent_speed is not None and self._supports_move_to_depth_intent_speed():
                kwargs["intent_speed"] = intent_speed
            if duration_ms is not None and self._supports_move_to_depth_duration_ms():
                kwargs["duration_ms"] = duration_ms
            result = self.handy.move_to_depth(
                target.speed,
                target.depth,
                **kwargs,
            )
        else:
            result = self.handy.move(target.speed, target.depth, target.stroke_range)
        self._record_target(target, source=source)
        self._augment_last_trace(self._handy_command_trace_extras(result))
        return result is not False

    def _supports_move_to_depth_intent_speed(self) -> bool:
        supported = self._move_to_depth_accepts_intent_speed
        if supported is not None:
            return supported
        supported = False
        if hasattr(self.handy, "move_to_depth"):
            try:
                parameters = inspect.signature(self.handy.move_to_depth).parameters
            except (TypeError, ValueError):
                parameters = {}
            supported = "intent_speed" in parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        self._move_to_depth_accepts_intent_speed = supported
        return supported

    def _supports_move_to_depth_duration_ms(self) -> bool:
        supported = self._move_to_depth_accepts_duration_ms
        if supported is not None:
            return supported
        supported = False
        if hasattr(self.handy, "move_to_depth"):
            try:
                parameters = inspect.signature(self.handy.move_to_depth).parameters
            except (TypeError, ValueError):
                parameters = {}
            supported = "duration_ms" in parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        self._move_to_depth_accepts_duration_ms = supported
        return supported

    def _effective_speed_for_timing(self, speed: float) -> float:
        effective = None
        if hasattr(self.handy, "effective_speed_for_relative"):
            try:
                effective = self.handy.effective_speed_for_relative(speed)
            except (TypeError, ValueError):
                effective = None
        if effective is None:
            effective = speed
        try:
            return _clamp(float(effective))
        except (TypeError, ValueError):
            return _clamp(speed)

    def _continuous_timing_target(self, target: MotionTarget) -> MotionTarget:
        return MotionTarget(
            self._effective_speed_for_timing(target.speed),
            target.depth,
            target.stroke_range,
            label=target.label,
            motion_program=target.motion_program,
        ).clamped()

    def _sample_continuous_motion(
        self,
        plan,
        target: MotionTarget,
        elapsed_seconds: float,
        sample_continuous_motion,
    ):
        sample = sample_continuous_motion(plan, self._continuous_timing_target(target), elapsed_seconds)
        if sample.intent_speed != target.speed:
            sample = replace(sample, intent_speed=target.speed)
        return sample

    def apply_continuous_target(
        self,
        target: MotionTarget,
        source: str = "continuous pattern",
        trace_metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        plan = self._continuous_plan(target)
        if plan is None:
            return False

        started_at = time.monotonic()
        plan_key = self._continuous_plan_key(plan)
        clamped_target = target.clamped()
        start_target = self.current_target()
        with self._lock:
            phase_offset_seconds = self._continuous_phase_offset_seconds(plan, plan_key, started_at)
            self._generation += 1
            generation = self._generation
            self._continuous_phase_state = ContinuousPhaseState(
                key=plan_key,
                generation=generation,
                started_at=started_at,
                offset_seconds=phase_offset_seconds,
                plan=plan,
                target=clamped_target,
            )
        self._set_frame_playback_active(True)

        thread = threading.Thread(
            target=self._run_continuous_plan,
            args=(
                plan,
                clamped_target,
                source,
                generation,
                started_at,
                phase_offset_seconds,
                start_target,
                trace_metadata,
            ),
            daemon=True,
        )
        thread.start()
        return True

    def _continuous_plan(self, target: MotionTarget):
        if target.motion_program:
            from .motion_patterns import continuous_anchor_motion_plan

            return continuous_anchor_motion_plan(target.motion_program)

        pattern = self._pattern_from_label(target.label)
        if not pattern:
            return None
        from .motion_patterns import continuous_motion_plan

        return continuous_motion_plan(pattern)

    def _continuous_plan_key(self, plan) -> tuple[Any, ...]:
        duration = round(float(getattr(plan, "duration_seconds", 0.0) or 0.0), 4)
        return (
            str(getattr(plan, "name", "") or ""),
            tuple(getattr(plan, "actions", ()) or ()),
            duration,
        )

    def _continuous_phase_offset_seconds(self, plan, plan_key: tuple[Any, ...], now: float) -> float:
        state = self._continuous_phase_state
        if state is None or state.generation != self._generation or state.key != plan_key:
            return 0.0
        try:
            phase_rate = max(0.0, float(state.phase_rate))
        except (TypeError, ValueError):
            phase_rate = 1.0
        return state.offset_seconds + max(0.0, now - state.started_at) * phase_rate

    def _continuous_sample_interval(self) -> float:
        if self.step_delay <= 0:
            return CONTINUOUS_MIN_COMMAND_INTERVAL_SECONDS
        return _clamp(self.step_delay, CONTINUOUS_MIN_COMMAND_INTERVAL_SECONDS, CONTINUOUS_SAMPLE_INTERVAL_SECONDS)

    def _continuous_command_interval(self, tempo_scale: float, base_interval: float | None = None) -> float:
        if base_interval is None:
            base_interval = self._continuous_sample_interval()
        try:
            tempo_scale = float(tempo_scale or 1.0)
        except (TypeError, ValueError):
            tempo_scale = 1.0
        tempo_scale = _clamp(tempo_scale, 0.5, 1.5)
        return _clamp(
            float(base_interval) / tempo_scale,
            CONTINUOUS_MIN_COMMAND_INTERVAL_SECONDS,
            CONTINUOUS_MAX_COMMAND_INTERVAL_SECONDS,
        )

    def _continuous_transport_interval(
        self,
        previous_target: MotionTarget,
        sample_target: MotionTarget,
        phase_interval_seconds: float,
    ) -> float:
        try:
            phase_interval = max(0.001, float(phase_interval_seconds))
        except (TypeError, ValueError):
            phase_interval = self._continuous_sample_interval()

        max_velocity = getattr(self.handy, "max_velocity_for_relative_speed", None)
        duration_for_depth = getattr(self.handy, "duration_ms_for_depth_interval", None)
        if callable(max_velocity) and callable(duration_for_depth):
            try:
                velocity = max_velocity(sample_target.speed)
                duration_ms = duration_for_depth(velocity, previous_target.depth, sample_target.depth)
                return max(phase_interval, max(0.001, float(duration_ms) / 1000.0))
            except Exception:
                pass
        return phase_interval

    def _refresh_continuous_phase_state(
        self,
        *,
        plan,
        target: MotionTarget,
        plan_key: tuple[Any, ...],
        generation: int,
        phase_offset_seconds: float,
        phase_rate: float = 1.0,
    ) -> None:
        try:
            phase_rate = max(0.0, float(phase_rate))
        except (TypeError, ValueError):
            phase_rate = 1.0
        with self._lock:
            if generation != self._generation:
                return
            self._continuous_phase_state = ContinuousPhaseState(
                key=plan_key,
                generation=generation,
                started_at=time.monotonic(),
                offset_seconds=max(0.0, float(phase_offset_seconds or 0.0)),
                phase_rate=phase_rate,
                plan=plan,
                target=target,
            )

    def _interpolate_target(self, start: MotionTarget, end: MotionTarget, amount: float, label: str) -> MotionTarget:
        return MotionTarget(
            _lerp(start.speed, end.speed, amount),
            _lerp(start.depth, end.depth, amount),
            _lerp(start.stroke_range, end.stroke_range, amount),
            label=label,
        ).clamped()

    def _interpolate_continuous_spatial_target(
        self,
        start: MotionTarget,
        end: MotionTarget,
        amount: float,
        label: str,
    ) -> MotionTarget:
        return MotionTarget(
            end.speed,
            _lerp(start.depth, end.depth, amount),
            _lerp(start.stroke_range, end.stroke_range, amount),
            label=label,
            motion_program=end.motion_program,
        ).clamped()

    def _limit_continuous_step(self, previous: MotionTarget, target: MotionTarget) -> MotionTarget:
        deltas = (
            (abs(target.depth - previous.depth), POSITION_MAX_DEPTH_STEP),
            (abs(target.stroke_range - previous.stroke_range), self.sanitizer.limits.max_range_delta),
        )
        amount = 1.0
        for delta, limit in deltas:
            if delta > limit > 0:
                amount = min(amount, limit / delta)
        if amount >= 1.0:
            return target
        return MotionTarget(
            target.speed,
            previous.depth + (target.depth - previous.depth) * amount,
            previous.stroke_range + (target.stroke_range - previous.stroke_range) * amount,
            label=f"{target.label or 'continuous'} step limited",
            motion_program=target.motion_program,
        ).clamped()

    def _continuous_morph_seconds(self, start: MotionTarget, target: MotionTarget) -> float:
        start = start.clamped()
        target = target.clamped()
        motion_delta = max(
            abs(target.depth - start.depth) / 70.0,
            abs(target.stroke_range - start.stroke_range) / 70.0,
        )
        return _clamp(
            CONTINUOUS_MIN_MORPH_SECONDS + motion_delta * CONTINUOUS_MORPH_SECONDS,
            CONTINUOUS_MIN_MORPH_SECONDS,
            CONTINUOUS_MAX_MORPH_SECONDS,
        )

    def _run_continuous_plan(
        self,
        plan,
        target: MotionTarget,
        source: str,
        generation: int,
        started_at: float,
        phase_offset_seconds: float,
        start_target: MotionTarget,
        trace_metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        if self._supports_continuous_streaming():
            started = self._run_continuous_stream_plan(
                plan,
                target,
                source,
                generation,
                started_at,
                phase_offset_seconds,
                start_target,
                trace_metadata=trace_metadata,
            )
            if started:
                return
        self._run_continuous_hdsp_plan(
            plan,
            target,
            source,
            generation,
            started_at,
            phase_offset_seconds,
            start_target,
            trace_metadata=trace_metadata,
        )

    def _supports_continuous_streaming(self) -> bool:
        supports = getattr(self.handy, "supports_continuous_streaming", None)
        if not callable(supports):
            return False
        try:
            return bool(supports())
        except Exception:
            return False

    def _hsp_stream_phase_points(
        self,
        phase_points: tuple[tuple[float, float], ...],
        effective_duration_seconds: float,
    ) -> tuple[dict[str, Any], ...]:
        """Keep authored HSP endpoints while filling long gaps with curve samples."""
        if not phase_points:
            return ()
        duration = max(0.001, float(effective_duration_seconds or 0.001))
        target_interval = max(0.001, CONTINUOUS_HSP_TARGET_POINT_INTERVAL_SECONDS)
        dense: list[dict[str, Any]] = [{"phase": float(phase_points[0][0]), "authored": True}]
        previous_phase = float(phase_points[0][0])
        for raw_phase, _pos in phase_points[1:]:
            phase = float(raw_phase)
            segment_seconds = max(0.0, (phase - previous_phase) * duration)
            if segment_seconds > target_interval:
                intermediate_count = max(0, int(round(segment_seconds / target_interval)) - 1)
                for step in range(1, intermediate_count + 1):
                    amount = step / (intermediate_count + 1)
                    dense.append(
                        {
                            "phase": previous_phase + (phase - previous_phase) * amount,
                            "authored": False,
                        }
                    )
            dense.append({"phase": phase, "authored": True})
            previous_phase = phase
        return tuple(dense)

    def _run_continuous_stream_plan(
        self,
        plan,
        target: MotionTarget,
        source: str,
        generation: int,
        started_at: float,
        phase_offset_seconds: float,
        start_target: MotionTarget,
        trace_metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        from .motion_patterns import (
            continuous_plan_depth_range,
            continuous_plan_phase_points,
            sample_continuous_motion,
        )

        start_stream = getattr(self.handy, "start_continuous_stream", None)
        append_stream = getattr(self.handy, "append_continuous_stream", None)
        if not callable(start_stream) or not callable(append_stream):
            return False

        base_interval = self._continuous_sample_interval()
        phase_points = continuous_plan_phase_points(plan)
        if not phase_points:
            return False
        phase_offset_seconds = max(0.0, float(phase_offset_seconds or 0.0))
        initial_sample = self._sample_continuous_motion(
            plan,
            target,
            phase_offset_seconds,
            sample_continuous_motion,
        )
        effective_duration_seconds = max(0.1, float(initial_sample.effective_duration_seconds or 0.1))
        hsp_phase_points = self._hsp_stream_phase_points(phase_points, effective_duration_seconds)
        stream_duration_seconds = effective_duration_seconds
        play_start_seconds = phase_offset_seconds % effective_duration_seconds
        play_start_stream_seconds = play_start_seconds
        morph_seconds = self._continuous_morph_seconds(start_target, initial_sample.target)
        stream_seconds = play_start_stream_seconds
        sample_index = 0
        stream_index = 0
        batch_index = 0
        previous_command_ended_at = None
        previous_recorded_point = None
        previous_point_time_seconds = None
        previous_phase_time_seconds = None
        previous_output_target = start_target
        phase_schedule: deque[tuple[float, float]] = deque()
        stream_wall_zero = None
        program_range = continuous_plan_depth_range(plan, target)
        plan_name = str(getattr(plan, "name", "") or "continuous")
        plan_key = self._continuous_plan_key(plan)
        cycle_ms = round(plan.duration_seconds * 1000.0, 1)
        phase_offset_ms = round(play_start_seconds * 1000.0, 1)
        play_start_ms = round(play_start_stream_seconds * 1000.0, 1)
        stream_cycle_ms = round(stream_duration_seconds * 1000.0, 1)
        morph_ms = round(morph_seconds * 1000.0, 1)
        start_phase = play_start_seconds / effective_duration_seconds
        phase_epsilon = 0.000001
        start_point_authored = any(
            bool(point.get("authored")) and abs(float(point["phase"]) - start_phase) <= phase_epsilon
            for point in hsp_phase_points
        )
        start_point_pending = True
        next_cycle_index = 0
        next_phase_index = 0
        for index, point in enumerate(hsp_phase_points):
            if float(point["phase"]) > start_phase + phase_epsilon:
                next_phase_index = index
                break
        else:
            next_cycle_index = 1
            next_phase_index = 1 if len(hsp_phase_points) > 1 and hsp_phase_points[0]["phase"] <= 0.0 else 0

        def advance_phase_cursor() -> None:
            nonlocal next_cycle_index, next_phase_index
            next_phase_index += 1
            if next_phase_index >= len(hsp_phase_points):
                next_cycle_index += 1
                next_phase_index = 1 if len(hsp_phase_points) > 1 and hsp_phase_points[0]["phase"] <= 0.0 else 0

        def sample_stream_point(
            point_seconds: float,
            point_stream_seconds: float,
        ):
            sample = self._sample_continuous_motion(
                plan,
                target,
                point_seconds,
                sample_continuous_motion,
            )
            stream_elapsed = max(0.0, point_stream_seconds - play_start_stream_seconds)
            if stream_elapsed < morph_seconds:
                amount = _minimum_jerk(stream_elapsed / morph_seconds)
                sample = sample.with_target(
                    self._interpolate_continuous_spatial_target(
                        start_target,
                        sample.target,
                        amount,
                        f"{sample.target.label or plan_name} morph",
                    )
                )
            return sample

        def append_stream_point(
            points: list[dict[str, Any]],
            point_seconds: float,
            point_stream_seconds: float,
            authored_point: bool,
            sample,
            phase_interval: float,
        ) -> None:
            nonlocal previous_point_time_seconds, previous_phase_time_seconds, previous_output_target
            nonlocal sample_index, stream_index, stream_seconds
            command_interval = (
                base_interval
                if previous_point_time_seconds is None
                else max(0.001, point_stream_seconds - previous_point_time_seconds)
            )
            stream_index += 1
            point = {
                "t": int(round(point_stream_seconds * 1000.0)),
                "logical_t": int(round(point_seconds * 1000.0)),
                "x": sample.target.depth,
                "speed": sample.target.speed,
                "intent_speed": sample.intent_speed,
                "range": sample.target.stroke_range,
                "label": sample.target.label or plan_name,
                "sample_index": sample_index,
                "stream_index": stream_index,
                "phase": sample.phase,
                "position_per_second": sample.position_per_second,
                "tempo_scale": sample.tempo_scale,
                "effective_duration_seconds": sample.effective_duration_seconds,
                "phase_interval_seconds": phase_interval,
                "sample_interval_seconds": command_interval,
                "authored_point": authored_point,
            }
            phase_schedule.append((point_stream_seconds, point_seconds))
            points.append(point)
            previous_point_time_seconds = point_stream_seconds
            previous_phase_time_seconds = point_seconds
            previous_output_target = sample.target
            sample_index += 1
            stream_seconds = point_stream_seconds

        def phase_at_stream_time(elapsed_seconds: float) -> tuple[float, float]:
            if not phase_schedule:
                return play_start_seconds, 1.0
            elapsed_seconds = max(0.0, float(elapsed_seconds or 0.0))
            while len(phase_schedule) > 2 and phase_schedule[1][0] <= elapsed_seconds:
                phase_schedule.popleft()
            previous_stream, previous_phase = phase_schedule[0]
            for next_stream, next_phase in list(phase_schedule)[1:]:
                stream_delta = max(0.0, next_stream - previous_stream)
                phase_delta = next_phase - previous_phase
                if elapsed_seconds <= next_stream:
                    if stream_delta <= 0:
                        return previous_phase, 0.0
                    amount = _clamp((elapsed_seconds - previous_stream) / stream_delta, 0.0, 1.0)
                    return previous_phase + phase_delta * amount, phase_delta / stream_delta
                previous_stream, previous_phase = next_stream, next_phase
            if len(phase_schedule) >= 2:
                prior_stream, prior_phase = phase_schedule[-2]
                last_stream, last_phase = phase_schedule[-1]
                stream_delta = max(0.0, last_stream - prior_stream)
                phase_delta = last_phase - prior_phase
                rate = phase_delta / stream_delta if stream_delta > 0 else 0.0
                return last_phase + max(0.0, elapsed_seconds - last_stream) * rate, rate
            return previous_phase, 1.0

        def build_batch(until_seconds: float, *, min_points: int = 1) -> list[dict[str, Any]]:
            nonlocal start_point_pending
            points: list[dict[str, Any]] = []
            if start_point_pending:
                start_point_pending = False
                sample = sample_stream_point(play_start_seconds, play_start_stream_seconds)
                append_stream_point(
                    points,
                    play_start_seconds,
                    play_start_stream_seconds,
                    start_point_authored,
                    sample,
                    base_interval,
                )
            while len(points) < CONTINUOUS_STREAM_MAX_POINTS_PER_COMMAND:
                phase_point = hsp_phase_points[next_phase_index]
                phase = phase_point["phase"]
                point_seconds = (next_cycle_index * effective_duration_seconds) + (
                    phase * effective_duration_seconds
                )
                phase_interval = (
                    base_interval
                    if previous_phase_time_seconds is None
                    else max(0.001, point_seconds - previous_phase_time_seconds)
                )
                provisional_stream_seconds = (
                    stream_seconds if previous_point_time_seconds is None else previous_point_time_seconds
                ) + phase_interval
                sample = sample_stream_point(point_seconds, provisional_stream_seconds)
                transport_interval = self._continuous_transport_interval(
                    previous_output_target,
                    sample.target,
                    phase_interval,
                )
                for _attempt in range(3):
                    candidate_stream_seconds = (
                        stream_seconds if previous_point_time_seconds is None else previous_point_time_seconds
                    ) + transport_interval
                    sample = sample_stream_point(point_seconds, candidate_stream_seconds)
                    adjusted_interval = self._continuous_transport_interval(
                        previous_output_target,
                        sample.target,
                        phase_interval,
                    )
                    if abs(adjusted_interval - transport_interval) <= 0.001:
                        break
                    transport_interval = adjusted_interval
                point_stream_seconds = (
                    stream_seconds if previous_point_time_seconds is None else previous_point_time_seconds
                ) + transport_interval
                if point_stream_seconds > until_seconds and len(points) >= min_points:
                    break

                sample = sample_stream_point(point_seconds, point_stream_seconds)
                append_stream_point(
                    points,
                    point_seconds,
                    point_stream_seconds,
                    phase_point["authored"],
                    sample,
                    phase_interval,
                )
                advance_phase_cursor()
            return points

        def record_batch(
            points: list[dict[str, Any]],
            *,
            result: Any,
            kind: str,
            send_started_at: float,
            send_ended_at: float,
        ) -> None:
            nonlocal previous_command_ended_at, previous_recorded_point, stream_wall_zero
            command_extras = self._handy_command_trace_extras(result)
            batch_gap_ms = None
            if previous_command_ended_at is not None:
                batch_gap_ms = round((send_started_at - previous_command_ended_at) * 1000.0, 1)
            previous_command_ended_at = send_ended_at
            wall_now = time.time()
            mono_now = time.monotonic()
            send_ended_wall = wall_now - max(0.0, mono_now - send_ended_at)
            if stream_wall_zero is None:
                stream_wall_zero = send_ended_wall - play_start_stream_seconds
            for point in points:
                scheduled_wall_time = stream_wall_zero + (point["t"] / 1000.0)
                stream_target = MotionTarget(
                    point["speed"],
                    point["x"],
                    point["range"],
                    label=point.get("label") or plan_name,
                    motion_program=target.motion_program,
                )
                self._record_target(stream_target, source=source)
                extras = {
                    "t": round(scheduled_wall_time, 3),
                    "continuous": True,
                    "continuous_schema": "hsp",
                    "hsp_batch": kind,
                    "hsp_batch_index": batch_index,
                    "hsp_point_time_ms": point["t"],
                    "hsp_point_logical_time_ms": point["logical_t"],
                    "hsp_stream_index": point["stream_index"],
                    "cycle_ms": cycle_ms,
                    "phase_offset_ms": phase_offset_ms,
                    "hsp_play_start_ms": play_start_ms,
                    "hsp_stream_cycle_ms": stream_cycle_ms,
                    "hsp_transport_time_scale": round(
                        point["sample_interval_seconds"] / max(0.001, point["phase_interval_seconds"]),
                        3,
                    ),
                    "hsp_authored_point": bool(point.get("authored_point")),
                    "morph_ms": morph_ms,
                    "intent_speed": int(round(point["intent_speed"])),
                    "sample_speed": int(round(point["speed"])),
                    "sample_phase": round(point["phase"], 4),
                    "sample_position_per_second": round(point["position_per_second"], 1),
                    "sample_tempo_scale": round(point["tempo_scale"], 3),
                    "effective_cycle_ms": round(point["effective_duration_seconds"] * 1000.0, 1),
                    "base_interval_ms": round(base_interval * 1000.0, 1),
                    "phase_interval_ms": round(point["phase_interval_seconds"] * 1000.0, 1),
                    "sample_interval_ms": round(point["sample_interval_seconds"] * 1000.0, 1),
                    "transport_interval_ms": round(point["sample_interval_seconds"] * 1000.0, 1),
                    "command_ms": round((send_ended_at - send_started_at) * 1000.0, 1),
                }
                if previous_recorded_point is not None:
                    dt_seconds = (point["t"] - previous_recorded_point["t"]) / 1000.0
                    if dt_seconds > 0:
                        depth_delta = point["x"] - previous_recorded_point["x"]
                        extras["hsp_segment_depth_delta"] = round(depth_delta, 1)
                        extras["hsp_segment_depth_per_second"] = round(abs(depth_delta) / dt_seconds, 1)
                        relative_to_mm = getattr(self.handy, "_relative_depth_to_mm", None)
                        if callable(relative_to_mm):
                            try:
                                distance_mm = abs(
                                    float(relative_to_mm(point["x"]))
                                    - float(relative_to_mm(previous_recorded_point["x"]))
                                )
                                physical_speed = distance_mm / dt_seconds
                                extras["hsp_segment_mm_per_second"] = round(physical_speed, 1)
                                extras["physical_speed"] = int(round(physical_speed))
                            except (TypeError, ValueError):
                                pass
                if program_range is not None:
                    extras["program_range"] = program_range
                if batch_gap_ms is not None:
                    extras["gap_ms"] = batch_gap_ms
                if trace_metadata:
                    for key, value in trace_metadata.items():
                        extras.setdefault(str(key), value)
                extras.update(command_extras)
                self._augment_last_trace(extras)
                previous_recorded_point = point

        try:
            initial_points = build_batch(
                play_start_stream_seconds + CONTINUOUS_STREAM_INITIAL_BUFFER_SECONDS,
                min_points=min(3, CONTINUOUS_STREAM_MAX_POINTS_PER_COMMAND),
            )
            if not initial_points:
                return False
            send_started_at = time.monotonic()
            started = start_stream(
                initial_points,
                start_time_ms=int(round(play_start_stream_seconds * 1000.0)),
                tail_point_stream_index=initial_points[-1]["stream_index"],
                tail_point_threshold=max(0, initial_points[-1]["stream_index"] - 2),
            )
            send_ended_at = time.monotonic()
            record_batch(
                initial_points,
                result=started,
                kind="play",
                send_started_at=send_started_at,
                send_ended_at=send_ended_at,
            )
            if started is False:
                return False

            while True:
                with self._lock:
                    if generation != self._generation:
                        return True
                if not self._wait_for_resume(generation):
                    return True
                self._set_frame_playback_active(True)

                elapsed = max(0.0, time.monotonic() - started_at)
                hsp_elapsed = play_start_stream_seconds + elapsed
                current_phase_seconds, phase_rate = phase_at_stream_time(hsp_elapsed)
                self._refresh_continuous_phase_state(
                    plan=plan,
                    target=target,
                    plan_key=plan_key,
                    generation=generation,
                    phase_offset_seconds=current_phase_seconds,
                    phase_rate=phase_rate,
                )
                buffer_remaining = stream_seconds - hsp_elapsed
                if buffer_remaining <= CONTINUOUS_STREAM_APPEND_THRESHOLD_SECONDS:
                    until = hsp_elapsed + CONTINUOUS_STREAM_TARGET_BUFFER_SECONDS
                    points = build_batch(until)
                    if points:
                        batch_index += 1
                        send_started_at = time.monotonic()
                        appended = append_stream(
                            points,
                            tail_point_stream_index=points[-1]["stream_index"],
                            tail_point_threshold=max(0, points[-1]["stream_index"] - 2),
                        )
                        send_ended_at = time.monotonic()
                        record_batch(
                            points,
                            result=appended,
                            kind="add",
                            send_started_at=send_started_at,
                            send_ended_at=send_ended_at,
                        )
                        if appended is False:
                            return True

                sleep_seconds = max(0.02, min(0.08, buffer_remaining - CONTINUOUS_STREAM_APPEND_THRESHOLD_SECONDS))
                if not self._sleep_with_pause(sleep_seconds, generation):
                    return True
        finally:
            with self._lock:
                current_generation = generation == self._generation
            if current_generation:
                self._set_frame_playback_active(False)

        return True

    def _run_continuous_hdsp_plan(
        self,
        plan,
        target: MotionTarget,
        source: str,
        generation: int,
        started_at: float,
        phase_offset_seconds: float,
        start_target: MotionTarget,
        trace_metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        from .motion_patterns import continuous_plan_depth_range, sample_continuous_motion

        base_interval = self._continuous_sample_interval()
        next_tick = started_at
        phase_offset_seconds = max(0.0, float(phase_offset_seconds or 0.0))
        initial_sample = self._sample_continuous_motion(
            plan,
            target,
            phase_offset_seconds,
            sample_continuous_motion,
        )
        morph_seconds = self._continuous_morph_seconds(start_target, initial_sample.target)
        previous_target = start_target
        previous_command_ended_at = None
        sample_index = 0
        program_range = continuous_plan_depth_range(plan, target)
        plan_name = str(getattr(plan, "name", "") or "continuous")
        cycle_ms = round(plan.duration_seconds * 1000.0, 1)
        phase_offset_ms = round(phase_offset_seconds * 1000.0, 1)
        morph_ms = round(morph_seconds * 1000.0, 1)

        try:
            while True:
                with self._lock:
                    if generation != self._generation:
                        return
                if not self._wait_for_resume(generation):
                    return
                self._set_frame_playback_active(True)

                now = time.monotonic()
                elapsed = max(0.0, now - started_at)
                sample_elapsed = phase_offset_seconds + elapsed
                sample = self._sample_continuous_motion(plan, target, sample_elapsed, sample_continuous_motion)
                if elapsed < morph_seconds:
                    amount = _minimum_jerk(elapsed / morph_seconds)
                    sample = sample.with_target(
                        self._interpolate_continuous_spatial_target(
                            start_target,
                            sample.target,
                            amount,
                            f"{sample.target.label or plan_name} morph",
                        )
                    )
                sample = sample.with_target(self._limit_continuous_step(previous_target, sample.target))
                command_interval = self._continuous_command_interval(sample.tempo_scale, base_interval)
                velocity = self._position_velocity(previous_target, sample.target, command_interval)

                send_started_at = time.monotonic()
                self._apply_position_step(
                    sample.target,
                    stop_on_target=False,
                    velocity=velocity,
                    intent_speed=sample.intent_speed,
                    source=source,
                )
                send_ended_at = time.monotonic()
                extras = {
                    "continuous": True,
                    "sample_index": sample_index,
                    "cycle_ms": cycle_ms,
                    "phase_offset_ms": phase_offset_ms,
                    "morph_ms": morph_ms,
                    "intent_speed": int(round(sample.intent_speed)),
                    "sample_speed": int(round(sample.target.speed)),
                    "sample_phase": round(sample.phase, 4),
                    "sample_position_per_second": round(sample.position_per_second, 1),
                    "sample_tempo_scale": round(sample.tempo_scale, 3),
                    "effective_cycle_ms": round(sample.effective_duration_seconds * 1000.0, 1),
                    "base_interval_ms": round(base_interval * 1000.0, 1),
                    "sample_interval_ms": round(command_interval * 1000.0, 1),
                    "command_ms": round((send_ended_at - send_started_at) * 1000.0, 1),
                }
                if program_range is not None:
                    extras["program_range"] = program_range
                if previous_command_ended_at is not None:
                    extras["gap_ms"] = round((send_started_at - previous_command_ended_at) * 1000.0, 1)
                if trace_metadata:
                    for key, value in trace_metadata.items():
                        extras.setdefault(str(key), value)
                self._augment_last_trace(extras)

                previous_command_ended_at = send_ended_at
                previous_target = sample.target
                sample_index += 1
                next_tick += command_interval
                if not self._sleep_with_pause(max(0.0, next_tick - time.monotonic()), generation):
                    return
        finally:
            with self._lock:
                current_generation = generation == self._generation
            if current_generation:
                self._set_frame_playback_active(False)

    def apply_frames(self, frames: list[Any], *, stop_after: bool = False, source: str = "pattern") -> bool:
        if not frames:
            return False
        program_range = self._depth_range_for_targets(frames)

        with self._lock:
            self._generation += 1
            generation = self._generation
        self._set_frame_playback_active(True)

        try:
            for frame in frames:
                with self._lock:
                    if generation != self._generation:
                        return False
                if not self._wait_for_resume(generation):
                    return False

                for step in self.sanitizer.transition_path(self.current_target(), frame.target):
                    with self._lock:
                        if generation != self._generation:
                            return False
                    if not self._wait_for_resume(generation):
                        return False
                    self._apply_step(step, source=source)
                    if program_range is not None:
                        self._augment_last_trace({"program_range": program_range})
                    if not self._sleep_with_pause(self.step_delay, generation):
                        return False

                if self.step_delay > 0:
                    if not self._sleep_with_pause(self.step_delay * frame.delay_factor, generation):
                        return False

            if stop_after:
                with self._lock:
                    if generation != self._generation:
                        return False
                    self._generation += 1
                self.handy.stop()
                self._record_current_state(source=source, label="preview stopped")
            return True
        finally:
            self._set_frame_playback_active(False)

    def apply_position_frames(
        self,
        frames: list[Any],
        *,
        stop_after: bool = False,
        source: str = "pattern preview",
        final_stop_on_target: bool = True,
    ) -> bool:
        if not frames:
            return False
        playback_frames = self._position_playback_frames(frames)
        if not playback_frames:
            return False
        program_range = self._depth_range_for_targets(playback_frames)

        with self._lock:
            self._generation += 1
            generation = self._generation
        self._set_frame_playback_active(True)

        batch_started_at = time.monotonic()
        with self._observability_lock:
            prior_batch_ended_at = self._last_position_batch_ended_at
        batch_gap_ms = None
        if prior_batch_ended_at is not None:
            batch_gap_ms = round((batch_started_at - prior_batch_ended_at) * 1000.0, 1)

        try:
            previous_target = self.current_target()
            frame_count = len(playback_frames)
            previous_command_ended_at = None
            for index, frame in enumerate(playback_frames):
                with self._lock:
                    if generation != self._generation:
                        return False
                if not self._wait_for_resume(generation):
                    return False
                delay_seconds = self.step_delay * frame.delay_factor if self.step_delay > 0 else 0
                if frame.phase.startswith("timed"):
                    delay_seconds = max(
                        delay_seconds,
                        self._minimum_position_duration_seconds(previous_target, frame.target),
                    )
                is_last_frame = index == frame_count - 1
                is_pass_through_final = is_last_frame and not final_stop_on_target and not stop_after
                velocity_seconds = delay_seconds
                if is_pass_through_final:
                    velocity_seconds = max(velocity_seconds, POSITION_PASS_THROUGH_MIN_SECONDS)
                velocity = self._position_velocity(previous_target, frame.target, velocity_seconds)
                duration_ms = None
                if frame.phase.startswith("timed") and velocity_seconds > 0:
                    duration_ms = max(1, int(round(velocity_seconds * 1000.0)))
                send_started_at = time.monotonic()
                self._apply_position_step(
                    frame.target,
                    stop_on_target=is_last_frame and final_stop_on_target and not stop_after,
                    velocity=velocity,
                    duration_ms=duration_ms,
                    source=source,
                )
                send_ended_at = time.monotonic()
                self._augment_last_trace(
                    self._position_trace_extras(
                        index=index,
                        frame_count=frame_count,
                        send_started_at=send_started_at,
                        send_ended_at=send_ended_at,
                        previous_command_ended_at=previous_command_ended_at,
                        batch_gap_ms=batch_gap_ms,
                        is_pass_through_final=is_pass_through_final,
                        program_range=program_range,
                    )
                )
                previous_command_ended_at = send_ended_at
                previous_target = frame.target
                should_sleep = not is_pass_through_final
                if self.step_delay > 0 and should_sleep:
                    if not self._sleep_with_pause(delay_seconds, generation):
                        return False

            with self._observability_lock:
                self._last_position_batch_ended_at = time.monotonic()
                self._last_position_command_ended_at = previous_command_ended_at

            if stop_after:
                with self._lock:
                    if generation != self._generation:
                        return False
                    self._generation += 1
                self.handy.stop()
                self._record_current_state(source=source, label="preview stopped")
            return True
        finally:
            self._set_frame_playback_active(False)

    def observability_snapshot(self, handy_diagnostics: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if handy_diagnostics is None:
            if hasattr(self.handy, "diagnostics"):
                handy_diagnostics = self.handy.diagnostics()
            else:
                handy_diagnostics = {
                    "relative_speed": getattr(self.handy, "last_relative_speed", 0),
                    "physical_speed": getattr(self.handy, "last_stroke_speed", 0),
                    "depth": getattr(self.handy, "last_depth_pos", 50),
                    "range": getattr(self.handy, "last_stroke_range", 50),
                }
        with self._observability_lock:
            trace = list(self._trace)
            source = self._last_source
            label = self._last_label
            last_command_time = self._last_command_time
            playback_active = self._frame_playback_active
        return {
            "backend": self.backend,
            "source": source,
            "label": label,
            "last_command_time": last_command_time,
            "playback_active": playback_active,
            "diagnostics": handy_diagnostics,
            "trace": trace,
        }

    def _set_frame_playback_active(self, active: bool) -> None:
        with self._observability_lock:
            self._frame_playback_active = bool(active)

    def _record_target(self, target: MotionTarget, source: str = "target", label: Optional[str] = None) -> None:
        target = target.rounded()
        now = time.time()
        point = {
            "t": now,
            "speed": int(round(target.speed)),
            "physical_speed": int(round(getattr(self.handy, "last_stroke_speed", target.speed))),
            "depth": int(round(target.depth)),
            "range": int(round(target.stroke_range)),
            "backend": self.backend,
            "source": source,
            "label": label or target.label or source,
        }
        with self._observability_lock:
            self._trace.append(point)
            self._last_source = source
            self._last_label = point["label"]
            self._last_command_time = now

    def _record_current_state(self, source: str = "status", label: str = "current") -> None:
        self._record_target(self.current_target(), source=source, label=label)

    def _augment_last_trace(self, extras: Optional[dict[str, Any]]) -> None:
        if not extras:
            return
        with self._observability_lock:
            if not self._trace:
                return
            point = dict(self._trace[-1])
            point.update(extras)
            self._trace[-1] = point

    def _position_trace_extras(
        self,
        *,
        index: int,
        frame_count: int,
        send_started_at: float,
        send_ended_at: float,
        previous_command_ended_at: Optional[float],
        batch_gap_ms: Optional[float],
        is_pass_through_final: bool,
        program_range: Optional[dict[str, int]] = None,
    ) -> dict[str, Any]:
        extras: dict[str, Any] = {
            "frame_index": index,
            "frame_count": frame_count,
            "command_ms": round((send_ended_at - send_started_at) * 1000.0, 1),
            "is_pass_through_final": bool(is_pass_through_final),
        }
        if program_range is not None:
            extras["program_range"] = program_range
        if previous_command_ended_at is not None:
            extras["gap_ms"] = round((send_started_at - previous_command_ended_at) * 1000.0, 1)
        if index == 0 and batch_gap_ms is not None:
            extras["batch_gap_ms"] = batch_gap_ms
        return extras

    def _expanded_frames(self, target: MotionTarget, *, preserve_timing: bool = False) -> list[Any]:
        current = self.current_target()
        if target.motion_program:
            from .motion_patterns import expand_anchor_program

            return expand_anchor_program(current, target, target.motion_program)

        pattern = self._pattern_from_label(target.label)
        if pattern:
            from .motion_patterns import expand_pattern

            return expand_pattern(
                pattern,
                current,
                target,
                preserve_timing=preserve_timing,
                base_step_seconds=self.step_delay,
            )
        return []

    def _pattern_from_label(self, label: str) -> Optional[str]:
        return _pattern_from_label_cached(label or "")


@lru_cache(maxsize=512)
def _pattern_from_label_cached(label: str) -> Optional[str]:
    """Resolve a free-form motion label to a known pattern id.

    Cached because labels are reused across every generated target and the
    PATTERNS dict is static after import. The cached path also avoids the
    per-call `sorted(PATTERNS, key=len)` allocation by relying on a one-time
    sorted snapshot.
    """
    if not label:
        return None
    clean_label = label.lower()
    slug_label = _slugify_motion_pattern_id(label)
    for pattern in _patterns_sorted_by_length():
        if (
            pattern in clean_label
            or slug_label == pattern
            or slug_label.startswith(f"{pattern}-")
        ):
            return pattern
    return None


@lru_cache(maxsize=1)
def _patterns_sorted_by_length() -> tuple[str, ...]:
    from .motion_patterns import PATTERNS

    return tuple(sorted(PATTERNS, key=len, reverse=True))
