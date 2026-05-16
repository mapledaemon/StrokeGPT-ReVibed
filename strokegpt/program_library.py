import json
from dataclasses import dataclass
from pathlib import Path

from .motion_patterns import PatternAction, normalize_actions
from .pattern_library import ALLOWED_IMPORT_EXTENSIONS, PatternValidationError, slugify_pattern_id


PROGRAM_SCHEMA_VERSION = 1
PROGRAM_FILE_SUFFIX = ".strokegpt-program.json"
MAX_PROGRAM_ACTIONS = 120_000
MAX_PROGRAM_DURATION_MS = 7_200_000
MAX_PROGRAM_IMPORT_BYTES = 24_000_000


class ProgramValidationError(PatternValidationError):
    pass


def _safe_text(value, default="", max_length=240):
    text = " ".join(str(value or "").split())
    if not text:
        text = default
    return text[:max_length]


def _safe_tags(value):
    if not isinstance(value, list):
        return ()
    tags = []
    for item in value[:30]:
        tag = _safe_text(item, max_length=40)
        if tag and tag not in tags:
            tags.append(tag)
    return tuple(tags)


def _title_from_payload(payload, fallback_id):
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return _safe_text(
        payload.get("name")
        or payload.get("title")
        or metadata.get("title")
        or metadata.get("name"),
        default=fallback_id,
        max_length=100,
    )


def _coerce_program_actions(actions):
    if not isinstance(actions, list):
        raise ProgramValidationError("Program actions must be a list.")
    if len(actions) > MAX_PROGRAM_ACTIONS:
        raise ProgramValidationError(f"Program has too many actions. Limit is {MAX_PROGRAM_ACTIONS}.")

    normalized = normalize_actions(actions)
    if len(normalized) < 2:
        raise ProgramValidationError("Program must contain at least two valid actions.")
    duration = normalized[-1].at - normalized[0].at
    if duration <= 0:
        raise ProgramValidationError("Program actions must cover a non-zero duration.")
    if duration > MAX_PROGRAM_DURATION_MS:
        raise ProgramValidationError(
            f"Program duration is too long. Limit is {MAX_PROGRAM_DURATION_MS // 60_000} minutes."
        )

    start = normalized[0].at
    return tuple(PatternAction(action.at - start, action.pos) for action in normalized)


@dataclass(frozen=True)
class ProgramRecord:
    program_id: str
    name: str
    description: str
    source: str
    readonly: bool
    actions: tuple[PatternAction, ...]
    tags: tuple[str, ...] = ()

    @property
    def duration_ms(self):
        return max(0, self.actions[-1].at - self.actions[0].at) if self.actions else 0

    @property
    def action_count(self):
        return len(self.actions)

    def to_export_dict(self):
        return {
            "schema_version": PROGRAM_SCHEMA_VERSION,
            "kind": "funscript_program",
            "id": self.program_id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "actions": [{"at": action.at, "pos": action.pos} for action in self.actions],
            "tags": list(self.tags),
        }

    def to_summary_dict(self, include_actions=False):
        payload = {
            "id": self.program_id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "readonly": self.readonly,
            "duration_ms": self.duration_ms,
            "action_count": self.action_count,
            "tags": list(self.tags),
        }
        if include_actions:
            payload["actions"] = [{"at": action.at, "pos": action.pos} for action in self.actions]
        return payload


def record_from_payload(payload, *, fallback_id="program", source_override=None, readonly=False):
    if not isinstance(payload, dict):
        raise ProgramValidationError("Program file must contain a JSON object.")
    if payload.get("kind", "funscript") not in {"actions", "funscript", "program", "funscript_program"}:
        raise ProgramValidationError("Only action-based funscript programs are supported.")

    name = _title_from_payload(payload, fallback_id)
    program_id = slugify_pattern_id(payload.get("id") or name or fallback_id, fallback=fallback_id)
    source = _safe_text(source_override or payload.get("source") or "imported", default="imported", max_length=32).lower()
    if source not in {"imported", "user"}:
        source = "imported"
    tags = list(_safe_tags(payload.get("tags")))
    if "program" not in tags:
        tags.append("program")
    if payload.get("kind") == "funscript" and "funscript" not in tags:
        tags.append("funscript")
    return ProgramRecord(
        program_id=program_id,
        name=name,
        description=_safe_text(payload.get("description"), default="Long-form funscript program.", max_length=300),
        source=source,
        readonly=readonly,
        actions=_coerce_program_actions(payload.get("actions")),
        tags=tuple(tags),
    )


class ProgramLibrary:
    def __init__(self, user_program_dir):
        self.user_program_dir = Path(user_program_dir)

    def user_program_files(self):
        if not self.user_program_dir.exists():
            return ()
        files = [
            path
            for path in self.user_program_dir.iterdir()
            if path.is_file() and (path.name.endswith(PROGRAM_FILE_SUFFIX) or path.suffix.lower() in ALLOWED_IMPORT_EXTENSIONS)
        ]
        return tuple(sorted(files, key=lambda path: path.name.lower()))

    def load_programs(self):
        records = []
        errors = []
        try:
            files = self.user_program_files()
        except OSError as exc:
            return (), [{"file": str(self.user_program_dir), "message": str(exc)}]

        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                records.append(record_from_payload(payload, fallback_id=path.stem, readonly=False))
            except (OSError, json.JSONDecodeError, ProgramValidationError) as exc:
                errors.append({"file": path.name, "message": str(exc)})
        return tuple(records), errors

    def catalog(self):
        records, errors = self.load_programs()
        return {
            "schema_version": PROGRAM_SCHEMA_VERSION,
            "program_dir": str(self.user_program_dir),
            "programs": [record.to_summary_dict() for record in records],
            "errors": errors,
        }

    def get_record(self, program_id):
        requested = slugify_pattern_id(program_id)
        records, _errors = self.load_programs()
        for record in records:
            if record.program_id == requested:
                return record
        return None

    def _path_for_id(self, program_id):
        return self.user_program_dir / f"{slugify_pattern_id(program_id)}{PROGRAM_FILE_SUFFIX}"

    def _unique_id(self, program_id):
        candidate = slugify_pattern_id(program_id, fallback="program")
        if not self._path_for_id(candidate).exists():
            return candidate
        for index in range(2, 1000):
            suffixed = f"{candidate}-{index}"
            if not self._path_for_id(suffixed).exists():
                return suffixed
        raise ProgramValidationError("Could not create a unique program id.")

    def save_program(self, record):
        if record.readonly:
            raise ProgramValidationError("Read-only programs cannot be overwritten.")
        try:
            self.user_program_dir.mkdir(parents=True, exist_ok=True)
            path = self._path_for_id(record.program_id)
            tmp_path = path.with_name(f"{path.name}.tmp")
            tmp_path.write_text(json.dumps(record.to_export_dict(), indent=2) + "\n", encoding="utf-8")
            tmp_path.replace(path)
        except OSError as exc:
            raise ProgramValidationError(f"Could not save program file: {exc}") from exc
        return path

    def delete_program(self, program_id):
        requested = slugify_pattern_id(program_id)
        try:
            files = self.user_program_files()
        except OSError as exc:
            raise ProgramValidationError(f"Could not read program directory: {exc}") from exc

        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = record_from_payload(payload, fallback_id=path.stem, readonly=False)
            except (OSError, json.JSONDecodeError, ProgramValidationError):
                continue
            if record.program_id != requested:
                continue
            try:
                path.unlink()
            except OSError as exc:
                raise ProgramValidationError(f"Could not delete program file: {exc}") from exc
            return record
        return None

    def import_payload(self, payload, *, filename="program.funscript", source_override="imported"):
        fallback = slugify_pattern_id(Path(filename or "program").stem, fallback="program")
        record = record_from_payload(payload, fallback_id=fallback, source_override=source_override, readonly=False)
        unique_id = self._unique_id(record.program_id)
        if unique_id != record.program_id:
            export = record.to_export_dict()
            export["id"] = unique_id
            record = record_from_payload(export, fallback_id=unique_id, source_override=source_override, readonly=False)
        self.save_program(record)
        return record
