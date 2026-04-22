import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .motion_patterns import MotionPattern, PATTERNS, PatternAction, normalize_actions


SCHEMA_VERSION = 1
PATTERN_FILE_SUFFIX = ".strokegpt-pattern.json"
MAX_PATTERN_ACTIONS = 2000
MAX_PATTERN_DURATION_MS = 300_000
ALLOWED_IMPORT_EXTENSIONS = {".json", ".funscript"}
ALLOWED_INTERPOLATIONS = {"linear", "cosine", "cubic"}
ALLOWED_SOURCES = {"fixed", "generated", "imported", "trained", "user"}


class PatternValidationError(ValueError):
    pass


def _clamp_float(value, low, high, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _clamp_int(value, low, high, default):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def slugify_pattern_id(value, fallback="pattern"):
    cleaned = str(value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    return cleaned[:64] or fallback


def _safe_text(value, default="", max_length=240):
    text = " ".join(str(value or "").split())
    if not text:
        text = default
    return text[:max_length]


def _safe_tags(value):
    if not isinstance(value, list):
        return ()
    tags = []
    for item in value[:20]:
        tag = _safe_text(item, max_length=40)
        if tag and tag not in tags:
            tags.append(tag)
    return tuple(tags)


def _safe_feedback(value):
    if not isinstance(value, dict):
        value = {}
    return {
        "thumbs_up": _clamp_int(value.get("thumbs_up"), 0, 1_000_000, 0),
        "neutral": _clamp_int(value.get("neutral"), 0, 1_000_000, 0),
        "thumbs_down": _clamp_int(value.get("thumbs_down"), 0, 1_000_000, 0),
    }


def _coerce_actions(actions):
    if not isinstance(actions, list):
        raise PatternValidationError("Pattern actions must be a list.")
    if len(actions) > MAX_PATTERN_ACTIONS:
        raise PatternValidationError(f"Pattern has too many actions. Limit is {MAX_PATTERN_ACTIONS}.")

    cleaned = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        try:
            at = int(action["at"])
            pos = float(action["pos"])
        except (KeyError, TypeError, ValueError):
            continue
        if at < 0:
            continue
        if at > MAX_PATTERN_DURATION_MS:
            raise PatternValidationError(
                f"Pattern duration is too long. Limit is {MAX_PATTERN_DURATION_MS // 1000} seconds."
            )
        cleaned.append({"at": at, "pos": pos})

    normalized = normalize_actions(cleaned)
    if len(normalized) < 2:
        raise PatternValidationError("Pattern must contain at least two valid actions.")
    if normalized[-1].at - normalized[0].at <= 0:
        raise PatternValidationError("Pattern actions must cover a non-zero duration.")
    return normalized


@dataclass(frozen=True)
class PatternRecord:
    pattern_id: str
    name: str
    description: str
    source: str
    enabled: bool
    readonly: bool
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
    tags: tuple[str, ...] = ()
    feedback: dict[str, int] | None = None

    @property
    def duration_ms(self):
        return max(0, self.actions[-1].at - self.actions[0].at) if self.actions else 0

    @property
    def action_count(self):
        return len(self.actions)

    def to_motion_pattern(self):
        return MotionPattern(
            self.name,
            self.actions,
            window_scale=self.window_scale,
            speed_scale=self.speed_scale,
            tempo_scale=self.tempo_scale,
            depth_jitter=self.depth_jitter,
            range_jitter=self.range_jitter,
            repeat=self.repeat,
            min_interval_ms=self.min_interval_ms,
            interpolation_ms=self.interpolation_ms,
            interpolation=self.interpolation,
            max_step_delta=self.max_step_delta,
        )

    def to_export_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "actions",
            "id": self.pattern_id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "enabled": self.enabled,
            "style": {
                "window_scale": self.window_scale,
                "speed_scale": self.speed_scale,
                "tempo_scale": self.tempo_scale,
                "depth_jitter": self.depth_jitter,
                "range_jitter": self.range_jitter,
                "repeat": self.repeat,
                "min_interval_ms": self.min_interval_ms,
                "interpolation_ms": self.interpolation_ms,
                "interpolation": self.interpolation,
                "max_step_delta": self.max_step_delta,
            },
            "actions": [{"at": action.at, "pos": action.pos} for action in self.actions],
            "tags": list(self.tags),
            "feedback": self.feedback or _safe_feedback({}),
        }

    def to_summary_dict(self, include_actions=False):
        payload = {
            "id": self.pattern_id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "enabled": self.enabled,
            "readonly": self.readonly,
            "duration_ms": self.duration_ms,
            "action_count": self.action_count,
            "tags": list(self.tags),
            "style": self.to_export_dict()["style"],
            "feedback": self.feedback or _safe_feedback({}),
        }
        if include_actions:
            payload["actions"] = [{"at": action.at, "pos": action.pos} for action in self.actions]
        return payload

    def with_enabled(self, enabled):
        return replace(self, enabled=bool(enabled))

    def with_feedback(self, feedback):
        return replace(self, feedback=_safe_feedback(feedback))


def _style_from_payload(payload):
    style = payload.get("style") if isinstance(payload.get("style"), dict) else {}
    interpolation = _safe_text(
        style.get("interpolation", payload.get("interpolation", "cosine")),
        default="cosine",
        max_length=16,
    ).lower()
    if interpolation not in ALLOWED_INTERPOLATIONS:
        interpolation = "cosine"
    return {
        "window_scale": _clamp_float(style.get("window_scale", payload.get("window_scale")), 0.05, 1.0, 0.3),
        "speed_scale": _clamp_float(style.get("speed_scale", payload.get("speed_scale")), 0.1, 2.0, 1.0),
        "tempo_scale": _clamp_float(style.get("tempo_scale", payload.get("tempo_scale")), 0.25, 4.0, 1.0),
        "depth_jitter": _clamp_float(style.get("depth_jitter", payload.get("depth_jitter")), 0.0, 30.0, 0.0),
        "range_jitter": _clamp_float(style.get("range_jitter", payload.get("range_jitter")), 0.0, 30.0, 0.0),
        "repeat": _clamp_int(style.get("repeat", payload.get("repeat")), 1, 20, 1),
        "min_interval_ms": _clamp_int(style.get("min_interval_ms", payload.get("min_interval_ms")), 0, 1000, 60),
        "interpolation_ms": _clamp_int(style.get("interpolation_ms", payload.get("interpolation_ms")), 0, 1000, 0),
        "interpolation": interpolation,
        "max_step_delta": _clamp_float(
            style.get("max_step_delta", payload.get("max_step_delta")),
            0.0,
            100.0,
            0.0,
        ),
    }


def record_from_motion_pattern(pattern_id, pattern):
    return PatternRecord(
        pattern_id=slugify_pattern_id(pattern_id),
        name=pattern.name,
        description="Built-in motion pattern.",
        source="fixed",
        enabled=True,
        readonly=True,
        actions=tuple(pattern.actions),
        window_scale=pattern.window_scale,
        speed_scale=pattern.speed_scale,
        tempo_scale=pattern.tempo_scale,
        depth_jitter=pattern.depth_jitter,
        range_jitter=pattern.range_jitter,
        repeat=pattern.repeat,
        min_interval_ms=pattern.min_interval_ms,
        interpolation_ms=pattern.interpolation_ms,
        interpolation=pattern.interpolation,
        max_step_delta=pattern.max_step_delta,
        tags=("built-in",),
        feedback=_safe_feedback({}),
    )


def record_from_payload(payload, *, fallback_id="pattern", source_override=None, readonly=False):
    if not isinstance(payload, dict):
        raise PatternValidationError("Pattern file must contain a JSON object.")
    if payload.get("kind", "actions") not in {"actions", "funscript"}:
        raise PatternValidationError("Only action-based pattern files are supported.")

    name = _safe_text(payload.get("name"), default=fallback_id, max_length=80)
    pattern_id = slugify_pattern_id(payload.get("id") or name or fallback_id, fallback=fallback_id)
    source = _safe_text(source_override or payload.get("source") or "imported", default="imported", max_length=32).lower()
    if source not in ALLOWED_SOURCES:
        source = "imported"
    style = _style_from_payload(payload)
    return PatternRecord(
        pattern_id=pattern_id,
        name=name,
        description=_safe_text(payload.get("description"), max_length=240),
        source=source,
        enabled=bool(payload.get("enabled", True)),
        readonly=readonly,
        actions=_coerce_actions(payload.get("actions")),
        tags=_safe_tags(payload.get("tags")),
        feedback=_safe_feedback(payload.get("feedback")),
        **style,
    )


class PatternLibrary:
    def __init__(self, user_pattern_dir, builtins=None):
        self.user_pattern_dir = Path(user_pattern_dir)
        self.builtins = builtins if builtins is not None else PATTERNS

    def builtin_records(self):
        return tuple(record_from_motion_pattern(pattern_id, pattern) for pattern_id, pattern in self.builtins.items())

    def user_pattern_files(self):
        if not self.user_pattern_dir.exists():
            return ()
        files = [
            path
            for path in self.user_pattern_dir.iterdir()
            if path.is_file() and (path.name.endswith(PATTERN_FILE_SUFFIX) or path.suffix.lower() in ALLOWED_IMPORT_EXTENSIONS)
        ]
        return tuple(sorted(files, key=lambda path: path.name.lower()))

    def load_user_patterns(self):
        records = []
        errors = []
        try:
            files = self.user_pattern_files()
        except OSError as exc:
            return (), [{"file": str(self.user_pattern_dir), "message": str(exc)}]

        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                records.append(record_from_payload(payload, fallback_id=path.stem, readonly=False))
            except (OSError, json.JSONDecodeError, PatternValidationError) as exc:
                errors.append({"file": path.name, "message": str(exc)})
        return tuple(records), errors

    def _apply_overrides(self, records, enabled_overrides=None, feedback_overrides=None):
        enabled_overrides = enabled_overrides or {}
        feedback_overrides = feedback_overrides or {}
        updated = []
        for record in records:
            if record.pattern_id in enabled_overrides:
                record = record.with_enabled(enabled_overrides[record.pattern_id])
            if record.pattern_id in feedback_overrides:
                record = record.with_feedback(feedback_overrides[record.pattern_id])
            updated.append(record)
        return tuple(updated)

    def catalog(self, enabled_overrides=None, feedback_overrides=None):
        records = list(self.builtin_records())
        user_records, errors = self.load_user_patterns()
        records.extend(user_records)
        records = self._apply_overrides(records, enabled_overrides, feedback_overrides)
        return {
            "schema_version": SCHEMA_VERSION,
            "pattern_dir": str(self.user_pattern_dir),
            "patterns": [record.to_summary_dict() for record in records],
            "errors": errors,
        }

    def get_record(self, pattern_id, enabled_overrides=None, feedback_overrides=None):
        requested = slugify_pattern_id(pattern_id)
        records = self._apply_overrides(self.builtin_records(), enabled_overrides, feedback_overrides)
        for record in records:
            if record.pattern_id == requested:
                return record
        records = self._apply_overrides(self.load_user_patterns()[0], enabled_overrides, feedback_overrides)
        for record in records:
            if record.pattern_id == requested:
                return record
        return None

    def _path_for_id(self, pattern_id):
        return self.user_pattern_dir / f"{slugify_pattern_id(pattern_id)}{PATTERN_FILE_SUFFIX}"

    def _unique_id(self, pattern_id):
        candidate = slugify_pattern_id(pattern_id)
        if not self._path_for_id(candidate).exists():
            return candidate
        for index in range(2, 1000):
            suffixed = f"{candidate}-{index}"
            if not self._path_for_id(suffixed).exists():
                return suffixed
        raise PatternValidationError("Could not create a unique pattern id.")

    def save_user_pattern(self, record):
        if record.readonly:
            raise PatternValidationError("Built-in patterns cannot be overwritten.")
        try:
            self.user_pattern_dir.mkdir(parents=True, exist_ok=True)
            path = self._path_for_id(record.pattern_id)
            tmp_path = path.with_name(f"{path.name}.tmp")
            tmp_path.write_text(json.dumps(record.to_export_dict(), indent=2) + "\n", encoding="utf-8")
            tmp_path.replace(path)
        except OSError as exc:
            raise PatternValidationError(f"Could not save pattern file: {exc}") from exc
        return path

    def import_payload(self, payload, *, filename="pattern.json", source_override="imported"):
        fallback = slugify_pattern_id(Path(filename or "pattern").stem, fallback="pattern")
        record = record_from_payload(payload, fallback_id=fallback, source_override=source_override, readonly=False)
        unique_id = self._unique_id(record.pattern_id)
        if unique_id != record.pattern_id:
            export = record.to_export_dict()
            export["id"] = unique_id
            record = record_from_payload(export, fallback_id=unique_id, source_override=source_override, readonly=False)
        self.save_user_pattern(record)
        return record
