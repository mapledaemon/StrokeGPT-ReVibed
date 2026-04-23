import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional

from .motion_anchors import coerce_anchor_program_dict


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


POSITION_MAX_DEPTH_STEP = 9.0
POSITION_BLEND_DELAY_FACTOR = 0.16
POSITION_TURN_DELAY_FACTOR = 0.2
TURN_BRAKE_SPEED_FACTOR = 0.45
POSITION_PASS_THROUGH_MIN_SECONDS = 0.35


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
        self.backend = "hamp"
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

    def set_backend(self, backend: str) -> None:
        normalized = "position" if str(backend or "").lower() == "position" else "hamp"
        if normalized != self.backend:
            self.backend = normalized
            self._record_current_state(source="settings", label=f"{self.backend} backend")
        else:
            self.backend = normalized

    def current_target(self) -> MotionTarget:
        return MotionTarget(
            self.handy.last_relative_speed,
            self.handy.last_depth_pos,
            getattr(self.handy, "last_stroke_range", 50),
            label="current",
        ).clamped()

    def apply_target(self, target: MotionTarget, smooth: bool = True, source: str = "target") -> None:
        if target.speed <= 0:
            self.stop()
            return

        with self._lock:
            self._generation += 1
            generation = self._generation
            current = self.current_target()

        if not smooth:
            self._apply_step(target, source=source)
            return

        for step in self.sanitizer.transition_path(current, target):
            with self._lock:
                if generation != self._generation:
                    return
            self._apply_step(step, source=source)
            time.sleep(self.step_delay)

    def apply_llm_move(self, move: Any) -> Optional[MotionTarget]:
        target = self.sanitizer.from_llm_move(move, self.current_target())
        if target:
            self.apply_generated_target(target, source="llm")
        return target

    def apply_generated_target(self, target: MotionTarget, source: str = "generated") -> None:
        frames = self._expanded_frames(target)
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
        self._set_frame_playback_active(False)
        self.handy.stop()
        self._record_current_state(source="stop", label="stopped")

    def _apply_step(self, target: MotionTarget, source: str = "target") -> None:
        target = target.rounded()
        self.handy.move(target.speed, target.depth, target.stroke_range)
        self._record_target(target, source=source)

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
        for step in range(1, steps + 1):
            amount = step / (steps + 1)
            transition_speed = min(
                previous.speed + (target.speed - previous.speed) * amount,
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
                    delay_factor=POSITION_BLEND_DELAY_FACTOR,
                    phase="blend",
                )
            )
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
        source: str = "position",
    ) -> None:
        target = target.rounded()
        if hasattr(self.handy, "move_to_depth"):
            self.handy.move_to_depth(
                target.speed,
                target.depth,
                stop_on_target=stop_on_target,
                velocity=velocity,
            )
        else:
            self.handy.move(target.speed, target.depth, target.stroke_range)
        self._record_target(target, source=source)

    def apply_frames(self, frames: list[Any], *, stop_after: bool = False, source: str = "pattern") -> bool:
        if not frames:
            return False

        with self._lock:
            self._generation += 1
            generation = self._generation
        self._set_frame_playback_active(True)

        try:
            for frame in frames:
                with self._lock:
                    if generation != self._generation:
                        return False

                for step in self.sanitizer.transition_path(self.current_target(), frame.target):
                    with self._lock:
                        if generation != self._generation:
                            return False
                    self._apply_step(step, source=source)
                    time.sleep(self.step_delay)

                if self.step_delay > 0:
                    time.sleep(self.step_delay * frame.delay_factor)

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
                delay_seconds = self.step_delay * frame.delay_factor if self.step_delay > 0 else 0
                is_last_frame = index == frame_count - 1
                is_pass_through_final = is_last_frame and not final_stop_on_target and not stop_after
                velocity_seconds = delay_seconds
                if is_pass_through_final:
                    velocity_seconds = max(velocity_seconds, POSITION_PASS_THROUGH_MIN_SECONDS)
                velocity = self._position_velocity(previous_target, frame.target, velocity_seconds)
                send_started_at = time.monotonic()
                self._apply_position_step(
                    frame.target,
                    stop_on_target=is_last_frame and final_stop_on_target and not stop_after,
                    velocity=velocity,
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
                    )
                )
                previous_command_ended_at = send_ended_at
                previous_target = frame.target
                should_sleep = not is_pass_through_final
                if self.step_delay > 0 and should_sleep:
                    time.sleep(delay_seconds)

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
    ) -> dict[str, Any]:
        extras: dict[str, Any] = {
            "frame_index": index,
            "frame_count": frame_count,
            "command_ms": round((send_ended_at - send_started_at) * 1000.0, 1),
            "is_pass_through_final": bool(is_pass_through_final),
        }
        if previous_command_ended_at is not None:
            extras["gap_ms"] = round((send_started_at - previous_command_ended_at) * 1000.0, 1)
        if index == 0 and batch_gap_ms is not None:
            extras["batch_gap_ms"] = batch_gap_ms
        return extras

    def _expanded_frames(self, target: MotionTarget) -> list[Any]:
        current = self.current_target()
        if target.motion_program:
            from .motion_patterns import expand_anchor_program

            return expand_anchor_program(current, target, target.motion_program)

        pattern = self._pattern_from_label(target.label)
        if pattern:
            from .motion_patterns import expand_pattern

            return expand_pattern(pattern, current, target)
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
