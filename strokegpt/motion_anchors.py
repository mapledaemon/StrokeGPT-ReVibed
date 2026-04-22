import re
from dataclasses import dataclass
from typing import Any, Optional


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _as_number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


ANCHOR_POSITIONS = {
    "tip": 8.0,
    "upper": 28.0,
    "shaft": 50.0,
    "middle": 50.0,
    "mid": 50.0,
    "lower": 72.0,
    "base": 92.0,
}

ANCHOR_PROGRAM_NAMES = {
    "anchor_loop",
    "anchor loop",
    "soft_anchor",
    "soft anchor",
    "soft_bounce",
    "soft bounce",
    "bounce",
    "spline",
}


@dataclass(frozen=True)
class MotionAnchor:
    pos: float
    label: str = "point"

    def to_dict(self) -> dict[str, Any]:
        return {"pos": _clamp(self.pos), "label": self.label}


@dataclass(frozen=True)
class AnchorProgram:
    anchors: tuple[MotionAnchor, ...]
    curve: str = "catmull"
    tempo: float = 0.75
    softness: float = 0.75
    variation: float = 0.0
    repeats: int = 1
    sample_interval_ms: int = 120
    max_step_delta: float = 24.0
    closed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "anchor_loop",
            "anchors": [anchor.to_dict() for anchor in self.anchors],
            "curve": self.curve,
            "tempo": self.tempo,
            "softness": self.softness,
            "variation": self.variation,
            "repeats": self.repeats,
            "sample_interval_ms": self.sample_interval_ms,
            "max_step_delta": self.max_step_delta,
            "closed": self.closed,
        }


def _clean_label(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _anchor_from_label(label: Any) -> Optional[MotionAnchor]:
    clean_label = _clean_label(label)
    if clean_label in ANCHOR_POSITIONS:
        return MotionAnchor(ANCHOR_POSITIONS[clean_label], clean_label)
    return None


def _anchor_from_item(item: Any) -> Optional[MotionAnchor]:
    if isinstance(item, MotionAnchor):
        return MotionAnchor(_clamp(item.pos), item.label)
    if isinstance(item, str):
        return _anchor_from_label(item)
    if not isinstance(item, dict):
        return None

    label = item.get("label") or item.get("zone") or item.get("anchor") or item.get("name")
    position = None
    for key in ("pos", "position", "dp", "depth"):
        position = _as_number(item.get(key))
        if position is not None:
            break

    if position is None and label:
        return _anchor_from_label(label)
    if position is None:
        return None
    return MotionAnchor(_clamp(position), _clean_label(label) or "point")


def anchors_from_items(items: Any, *, max_anchors: int = 6) -> tuple[MotionAnchor, ...]:
    if not isinstance(items, (list, tuple)):
        return ()

    anchors = []
    for item in items[:max_anchors]:
        anchor = _anchor_from_item(item)
        if anchor is not None:
            anchors.append(anchor)
    return tuple(anchors)


def anchors_from_text(text: str, *, max_anchors: int = 6) -> tuple[MotionAnchor, ...]:
    clean_text = _clean_label(text).replace("_", " ")
    found = []
    for label in ("tip", "upper", "shaft", "middle", "mid", "lower", "base"):
        for match in re.finditer(rf"\b{re.escape(label)}\b", clean_text):
            found.append((match.start(), label))
    found.sort()
    return tuple(anchor for _, label in found[:max_anchors] if (anchor := _anchor_from_label(label)) is not None)


def default_anchor_items(zone: Optional[str] = None, length: Optional[str] = None) -> tuple[str, ...]:
    if zone == "tip":
        return ("tip", "upper", "tip", "middle")
    if zone == "base":
        return ("middle", "base", "lower", "base")
    if zone == "upper":
        return ("tip", "upper", "middle", "upper")
    if zone == "middle":
        return ("upper", "shaft", "lower", "shaft")
    if zone == "full" or length == "full":
        return ("tip", "shaft", "base", "shaft")
    return ("upper", "shaft", "lower", "shaft")


def _read_curve(value: Any) -> str:
    curve = _clean_label(value)
    if curve in {"catmull", "catmull_rom", "spline"}:
        return "catmull"
    if curve in {"minimum_jerk", "min_jerk", "minjerk", "smoothstep"}:
        return "minimum_jerk"
    if curve == "cosine":
        return "cosine"
    return "catmull"


def _read_int(value: Any, default: int, low: int, high: int) -> int:
    number = _as_number(value)
    if number is None:
        return default
    return int(_clamp(round(number), low, high))


def _read_float(value: Any, default: float, low: float, high: float) -> float:
    number = _as_number(value)
    if number is None:
        return default
    return _clamp(number, low, high)


def _program_requested(data: dict[str, Any]) -> bool:
    if data.get("anchors"):
        return True
    for key in ("motion", "program", "shape", "pattern"):
        value = data.get(key)
        if value is not None and _clean_label(value) in {name.replace(" ", "_") for name in ANCHOR_PROGRAM_NAMES}:
            return True
    return False


def coerce_anchor_program(
    data: Any,
    *,
    zone: Optional[str] = None,
    length: Optional[str] = None,
    text: str = "",
    require_request: bool = True,
) -> Optional[AnchorProgram]:
    if isinstance(data, AnchorProgram):
        return data
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None
    if require_request and not _program_requested(data):
        return None

    anchors = anchors_from_items(data.get("anchors"))
    if len(anchors) < 2 and text:
        anchors = anchors_from_text(text)
    if len(anchors) < 2:
        anchors = anchors_from_items(default_anchor_items(zone, length))
    if len(anchors) < 2:
        return None

    return AnchorProgram(
        anchors=anchors,
        curve=_read_curve(data.get("curve")),
        tempo=_read_float(data.get("tempo") or data.get("pace"), 0.75, 0.25, 1.5),
        softness=_read_float(data.get("softness"), 0.75, 0.0, 1.0),
        variation=_read_float(data.get("variation"), 0.0, 0.0, 0.35),
        repeats=_read_int(data.get("repeats") or data.get("repeat"), 1, 1, 4),
        sample_interval_ms=_read_int(data.get("sample_interval_ms"), 120, 70, 220),
        max_step_delta=_read_float(data.get("max_step_delta"), 24.0, 8.0, 40.0),
        closed=bool(data.get("closed", True)),
    )


def coerce_anchor_program_dict(
    data: Any,
    *,
    zone: Optional[str] = None,
    length: Optional[str] = None,
    text: str = "",
    require_request: bool = True,
) -> Optional[dict[str, Any]]:
    program = coerce_anchor_program(
        data,
        zone=zone,
        length=length,
        text=text,
        require_request=require_request,
    )
    if program is None:
        return None
    return program.to_dict()
