import os
import sys
import json
import re
import atexit
import socket
import threading
import time
import types
from pathlib import Path
import requests
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from werkzeug.utils import secure_filename

from .app_state import APP_STATE_EXPORTS, AppState
from .settings import SettingsManager, normalize_ollama_model
from .handy import HandyController
from .llm import LLMService
from .audio import AudioService
from .background_modes import AutoModeThread, auto_mode_logic, milking_mode_logic, edging_mode_logic, freestyle_mode_logic
from .mode_contracts import FreestyleCandidate, ModeCallbacks, ModeLogic, ModeServices
from .motion import IntentMatcher, MotionController, MotionTarget
from .motion_patterns import PATTERNS, expand_motion_pattern
from .motion_preferences import (
    THUMBS_DOWN_DISABLE_THRESHOLD,
    adjust_weight_for_feedback,
    clamp_weight,
    feedback_weight,
    should_auto_disable,
)
from . import payloads
from .pattern_library import (
    ALLOWED_IMPORT_EXTENSIONS,
    PatternLibrary,
    PatternValidationError,
    record_from_payload,
    slugify_pattern_id,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VOICE_SAMPLE_DIR = PROJECT_ROOT / "voice_samples"
USER_DATA_DIR = PROJECT_ROOT / "user_data"
MOTION_PATTERN_DIR = USER_DATA_DIR / "patterns"
ALLOWED_VOICE_SAMPLE_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
MAX_PATTERN_IMPORT_BYTES = 1_000_000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
MOTION_FEEDBACK_HISTORY_LIMIT = 20


def resource_path(*parts):
    base_path = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else PROJECT_ROOT
    return base_path.joinpath(*parts)


def _env_int(name, default):
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    if not 1 <= value <= 65535:
        return default
    return value


def _port_candidates(start_port, fallback_count=10):
    return [port for port in range(start_port, min(65535, start_port + fallback_count) + 1)]


def _can_bind(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
            return True
        except OSError:
            return False


def _select_bind_port(host, start_port, fallback_count=10, can_bind=_can_bind):
    for port in _port_candidates(start_port, fallback_count):
        if can_bind(host, port):
            return port
    raise OSError(f"No available local port found from {start_port} to {start_port + fallback_count}.")


def _display_host(host):
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def _request_json():
    return request.get_json(silent=True) or {}


def _request_int(data, key, default):
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default

# ─── INITIALIZATION ───────────────────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=None)
OLLAMA_BASE_URL = os.getenv("STROKEGPT_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
LLM_URL = f"{OLLAMA_BASE_URL}/api/chat"
settings = SettingsManager(settings_file_path="my_settings.json")
settings.load()

handy = HandyController(settings.handy_key)
handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
motion = MotionController(handy)
intent_matcher = IntentMatcher()
motion_pattern_library = PatternLibrary(MOTION_PATTERN_DIR)

ollama_model = normalize_ollama_model(os.getenv("STROKEGPT_OLLAMA_MODEL", settings.ollama_model)) or settings.ollama_model
llm = LLMService(url=LLM_URL, model=ollama_model)
audio = AudioService()
audio.set_provider(settings.audio_provider, settings.audio_enabled)
if settings.elevenlabs_api_key:
    if audio.set_api_key(settings.elevenlabs_api_key):
        audio.fetch_available_voices()
        if settings.audio_provider == "elevenlabs":
            audio.configure_voice(settings.elevenlabs_voice_id, settings.audio_enabled)
if settings.audio_provider == "local":
    audio.configure_local_voice(
        settings.audio_enabled,
        settings.local_tts_prompt_path,
        settings.local_tts_exaggeration,
        settings.local_tts_cfg_weight,
        settings.local_tts_style,
        settings.local_tts_temperature,
        settings.local_tts_top_p,
        settings.local_tts_min_p,
        settings.local_tts_repetition_penalty,
        settings.local_tts_engine,
    )

# In-Memory State
app_state = AppState()


# Compatibility shim - do not extend. Legacy callers may still access the old
# ``strokegpt.web`` runtime attributes; new code should use ``app_state``.
class _WebModule(types.ModuleType):
    def __getattr__(self, name):
        if name in APP_STATE_EXPORTS:
            return getattr(app_state, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in APP_STATE_EXPORTS:
            with app_state.lock:
                setattr(app_state, name, value)
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _WebModule


def _set_runtime_active_mode(mode_name, *, reset_timer=False):
    mode_name = str(mode_name or "").strip()
    with app_state.lock:
        changed = app_state.active_mode_name != mode_name
        app_state.active_mode_name = mode_name

        if not mode_name:
            app_state.active_mode_started_at = None
            app_state.active_mode_paused_at = None
            app_state.active_mode_paused_total = 0.0
            app_state.motion_pause_active = False
            app_state.edging_start_time = None
            return

        should_resume = reset_timer or changed or app_state.active_mode_started_at is None
        if should_resume:
            app_state.active_mode_started_at = time.time()
            app_state.active_mode_paused_at = None
            app_state.active_mode_paused_total = 0.0
            app_state.motion_pause_active = False

        if mode_name == "edging":
            app_state.edging_start_time = app_state.active_mode_started_at
        else:
            app_state.edging_start_time = None

        active_task = app_state.auto_mode_active_task
        if active_task:
            active_task.name = mode_name

    if should_resume and hasattr(motion, "resume"):
        motion.resume()


def _active_mode_snapshot():
    with app_state.lock:
        mode_name = (
            app_state.auto_mode_active_task.name
            if app_state.auto_mode_active_task
            else app_state.active_mode_name
        )
        motion_pause_active = app_state.motion_pause_active
        active_mode_started_at = app_state.active_mode_started_at
        active_mode_paused_at = app_state.active_mode_paused_at
        active_mode_paused_total = app_state.active_mode_paused_total
    paused = bool(motion_pause_active or getattr(motion, "is_paused", lambda: False)())
    if not mode_name:
        return {
            "active_mode": "",
            "active_mode_elapsed_seconds": None,
            "active_mode_paused": False,
            "motion_paused": paused,
        }
    elapsed = None
    if active_mode_started_at:
        now = active_mode_paused_at if active_mode_paused_at is not None else time.time()
        elapsed = max(0, int(now - active_mode_started_at - active_mode_paused_total))
    return {
        "active_mode": mode_name,
        "active_mode_elapsed_seconds": elapsed,
        "active_mode_paused": paused,
        "motion_paused": paused,
    }


def _clear_motion_pause_state():
    with app_state.lock:
        app_state.active_mode_paused_at = None
        app_state.active_mode_paused_total = 0.0
        app_state.motion_pause_active = False
    if hasattr(motion, "resume"):
        motion.resume()


def _set_motion_paused(paused):
    paused = bool(paused)
    now = time.time()
    with app_state.lock:
        active_task = app_state.auto_mode_active_task
        if paused:
            if not app_state.motion_pause_active:
                app_state.motion_pause_active = True
                if app_state.active_mode_name and app_state.active_mode_paused_at is None:
                    app_state.active_mode_paused_at = now
        else:
            if app_state.motion_pause_active and app_state.active_mode_paused_at is not None:
                app_state.active_mode_paused_total += max(0.0, now - app_state.active_mode_paused_at)
            app_state.active_mode_paused_at = None
            app_state.motion_pause_active = False
    if paused:
        if active_task and hasattr(active_task, "pause"):
            active_task.pause()
        elif hasattr(motion, "pause"):
            motion.pause()
    else:
        if active_task and hasattr(active_task, "resume"):
            active_task.resume()
        elif hasattr(motion, "resume"):
            motion.resume()
    return _active_mode_snapshot()

def get_ollama_models_for_ui():
    return payloads.ollama_models_for_ui(settings, llm)

def _format_bytes(value):
    return payloads.format_bytes(value)

def _set_ollama_pull_state(**updates):
    return app_state.set_ollama_pull_state(**updates)

def _ollama_pull_snapshot():
    return app_state.ollama_pull_snapshot()

def _diagnostics_level_options():
    return payloads.diagnostics_level_options()

def _ollama_installed_models():
    response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=0.5)
    response.raise_for_status()
    data = response.json()
    models = []
    for item in data.get("models", []):
        name = normalize_ollama_model(item.get("model") or item.get("name") or "")
        if not name:
            continue
        models.append({
            "name": name,
            "size": int(item.get("size") or 0),
            "size_label": _format_bytes(item.get("size")),
        })
    models.sort(key=lambda item: item["name"].lower())
    return models

def _ollama_status_payload():
    # Compatibility shim - do not extend. The canonical payload builder lives
    # in ``strokegpt.payloads``; this wrapper preserves old ``web.*`` patch
    # points while route blueprints still compose through ``web.py`` services.
    return payloads.ollama_status_payload(
        settings=settings,
        llm=llm,
        base_url=OLLAMA_BASE_URL,
        pull_snapshot=_ollama_pull_snapshot,
        installed_models=_ollama_installed_models,
    )

def _run_ollama_pull(model):
    _set_ollama_pull_state(
        state="downloading",
        model=model,
        message=f"Downloading {model} with Ollama. This can be several GB.",
        completed=0,
        total=0,
        percent=None,
    )
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/pull",
            json={"name": model, "stream": True},
            stream=True,
            timeout=(3, None),
        )
        response.raise_for_status()
        last_status = "Downloading"
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            event = json.loads(line)
            if event.get("error"):
                raise RuntimeError(event["error"])
            last_status = event.get("status") or last_status
            completed = int(event.get("completed") or 0)
            total = int(event.get("total") or 0)
            percent = round((completed / total) * 100, 1) if total else None
            detail = ""
            if completed and total:
                detail = f" ({_format_bytes(completed)} / {_format_bytes(total)}, {percent}%)"
            _set_ollama_pull_state(
                state="downloading",
                model=model,
                message=f"{last_status}{detail}",
                completed=completed,
                total=total,
                percent=percent,
            )
        _set_ollama_pull_state(
            state="ready",
            model=model,
            message=f"{model} is downloaded and ready.",
            completed=0,
            total=0,
            percent=100,
        )
    except Exception as exc:
        _set_ollama_pull_state(
            state="error",
            model=model,
            message=f"Download failed for {model}: {exc}",
            completed=0,
            total=0,
            percent=None,
        )

def _start_ollama_pull(model):
    model = normalize_ollama_model(model)
    if not model:
        return False, "Model name is required."

    status = _ollama_status_payload()
    if model in status.get("installed_model_names", []):
        _set_ollama_pull_state(
            state="ready",
            model=model,
            message=f"{model} is already installed.",
            completed=0,
            total=0,
            percent=100,
        )
        return True, "Model is already installed."
    if not status.get("available"):
        return False, status.get("message", "Ollama is not reachable.")

    with app_state.lock:
        if app_state.ollama_pull_thread and app_state.ollama_pull_thread.is_alive():
            return False, f"Already downloading {app_state.ollama_pull_state.get('model') or 'a model'}."
        app_state.ollama_pull_state.update({
            "state": "downloading",
            "model": model,
            "message": f"Queued download for {model}.",
            "completed": 0,
            "total": 0,
            "percent": None,
        })
        app_state.ollama_pull_thread = threading.Thread(target=_run_ollama_pull, args=(model,), daemon=True)
        app_state.ollama_pull_thread.start()
    return True, f"Started downloading {model}."

def get_persona_prompts_for_ui():
    return payloads.persona_prompts_for_ui(settings)

def settings_payload():
    # Compatibility shim - do not extend. The canonical payload builder lives
    # in ``strokegpt.payloads``; this wrapper preserves old ``web.*`` patch
    # points while route blueprints still compose through ``web.py`` services.
    return payloads.settings_payload(
        settings=settings,
        llm=llm,
        audio=audio,
        use_long_term_memory=app_state.use_long_term_memory,
        persona_prompts=get_persona_prompts_for_ui(),
        ollama_models=get_ollama_models_for_ui(),
        ollama_status=_ollama_status_payload(),
        motion_patterns=_motion_pattern_catalog_payload(),
        motion_preferences=_motion_preference_payload(),
        diagnostics_levels=_diagnostics_level_options(),
    )

def apply_settings_to_services():
    handy.set_api_key(settings.handy_key)
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    motion.set_backend(settings.motion_backend)
    llm.set_model(settings.ollama_model)

    audio.set_provider(settings.audio_provider, settings.audio_enabled)
    audio.api_key = ""
    audio.voice_id = ""
    audio.client = None
    audio.available_voices = {}
    audio.audio_output_queue.clear()
    audio.last_error = ""
    if settings.elevenlabs_api_key:
        if audio.set_api_key(settings.elevenlabs_api_key):
            audio.fetch_available_voices()
            if settings.audio_provider == "elevenlabs":
                audio.configure_voice(settings.elevenlabs_voice_id, settings.audio_enabled)
    if settings.audio_provider == "local":
        audio.configure_local_voice(
            settings.audio_enabled,
            settings.local_tts_prompt_path,
            settings.local_tts_exaggeration,
            settings.local_tts_cfg_weight,
            settings.local_tts_style,
            settings.local_tts_temperature,
            settings.local_tts_top_p,
            settings.local_tts_min_p,
            settings.local_tts_repetition_penalty,
            settings.local_tts_engine,
        )

def _motion_pattern_catalog_payload():
    # Compatibility shim - do not extend. The canonical payload builder lives
    # in ``strokegpt.payloads``; this wrapper preserves old ``web.*`` patch
    # points while route blueprints still compose through ``web.py`` services.
    return payloads.motion_pattern_catalog_payload(
        motion_pattern_library,
        settings,
        MOTION_FEEDBACK_HISTORY_LIMIT,
    )

def _edge_pattern_ids():
    return {pattern_id for pattern_id in PATTERNS if pattern_id.startswith("edge-")}

def _motion_preference_payload():
    excluded = set()
    if not settings.allow_llm_edge_in_chat:
        excluded.update(_edge_pattern_ids())
    return payloads.motion_preference_payload(_motion_pattern_catalog_payload(), excluded)

def _motion_pattern_record(pattern_id):
    return motion_pattern_library.get_record(
        pattern_id,
        settings.motion_pattern_enabled,
        settings.motion_pattern_feedback,
    )

def _motion_pattern_summary(record, include_actions=False):
    summary = record.to_summary_dict(include_actions=include_actions)
    catalog = _motion_pattern_catalog_payload()
    for pattern in catalog.get("patterns", []):
        if pattern.get("id") == record.pattern_id:
            for key, value in pattern.items():
                if key != "actions":
                    summary[key] = value
            break
    return summary

def _fixed_pattern_id_from_target(target):
    label = getattr(target, "label", "") or ""
    parts = set(re.split(r"[^a-z0-9_-]+", label.lower()))
    slug_label = slugify_pattern_id(label, fallback="")
    for pattern_id in sorted(PATTERNS, key=len, reverse=True):
        if (
            pattern_id in parts
            or slug_label == pattern_id
            or slug_label.startswith(f"{pattern_id}-")
        ):
            return pattern_id
    return ""

def _remember_motion_pattern_from_target(target):
    pattern_id = _fixed_pattern_id_from_target(target)
    if pattern_id:
        with app_state.lock:
            app_state.last_live_motion_pattern_id = pattern_id
    return pattern_id

def _remember_live_motion_pattern_id(pattern_id):
    record = _motion_pattern_record(pattern_id)
    if record:
        with app_state.lock:
            app_state.last_live_motion_pattern_id = record.pattern_id
        return record.pattern_id
    return ""

def _freestyle_candidate_patterns() -> list[FreestyleCandidate]:
    catalog = _motion_pattern_catalog_payload()
    candidates = []
    for summary in catalog.get("patterns", []):
        if not summary.get("enabled", True):
            continue
        if summary.get("source") == "fixed" and int(summary.get("weight") or 0) <= 0:
            continue
        record = _motion_pattern_record(summary.get("id", ""))
        if not record:
            continue
        candidates.append({
            "id": record.pattern_id,
            "name": record.name,
            "source": record.source,
            "enabled": record.enabled,
            "weight": summary.get("weight"),
            "feedback": summary.get("feedback", {}),
            "record": record,
        })
    return candidates

def _llm_visible_fixed_pattern(pattern_id):
    catalog = _motion_pattern_catalog_payload()
    if not settings.allow_llm_edge_in_chat and pattern_id in _edge_pattern_ids():
        return False
    return any(
        pattern.get("id") == pattern_id
        and pattern.get("source") == "fixed"
        and pattern.get("llm_visible")
        for pattern in catalog.get("patterns", [])
    )

def _sanitize_llm_move_for_disabled_patterns(move):
    if not isinstance(move, dict):
        return move
    pattern_id = slugify_pattern_id(move.get("pattern") or "")
    if pattern_id in PATTERNS and not _llm_visible_fixed_pattern(pattern_id):
        sanitized = dict(move)
        sanitized.pop("pattern", None)
        return sanitized
    return move

MOTION_DIRECT_REQUEST_PATTERNS = (
    r"\b(?:faster|slower|slowly|harder|softer|gentler|deeper|shallower)\b",
    r"\b(?:speed\s+up|slow\s+down|ease\s+up)\b",
    r"\b(?:stroke|strokes|stroking|suck|flick|flutter|pulse|wave|ramp|sway|tease|edge|hold)\b",
    r"\b(?:go|move|use|try|switch|change|shift|adjust|make|keep|stay)\b.*\b(?:tip|upper|middle|base|deep|shallow|full|range|length|pattern|rhythm|motion|move|stroke|mode)\b",
    r"\b(?:change|switch|mix)\s+it\s+up\b",
    r"\b(?:something|anything)\s+(?:different|new)\b",
    r"\b(?:another|new|different)\s+(?:motion|move|pattern|rhythm|stroke|mode)\b",
)

NON_ACTION_INFO_PATTERNS = (
    r"\b(?:what|why|how)\b.*\b(?:mean|means|meaning|work|works|explain|describe)\b",
    r"\b(?:explain|describe|define|what is|what are|tell me about)\b",
)

CHAT_MOTION_CLAIM_PATTERNS = (
    r"\b(?:i(?:'ll| will| am|'m)|let me|now|okay|ok)\b.*\b(?:move|stroke|switch|change|adjust|speed|slow|deepen|tip|base|pattern|rhythm|motion)\b",
    r"\b(?:switching|changing|adjusting|moving|stroking|speeding|slowing)\b",
)

def _looks_like_motion_request(text):
    clean = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    if not clean:
        return False
    if any(re.search(pattern, clean) for pattern in NON_ACTION_INFO_PATTERNS):
        if not any(re.search(pattern, clean) for pattern in MOTION_DIRECT_REQUEST_PATTERNS[:3]):
            return False
    return any(re.search(pattern, clean) for pattern in MOTION_DIRECT_REQUEST_PATTERNS)

def _chat_claims_motion_change(text):
    clean = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    return any(re.search(pattern, clean) for pattern in CHAT_MOTION_CLAIM_PATTERNS)

def _target_has_motion_effect(current, target):
    if not target:
        return False
    if target.motion_program:
        return True
    if _fixed_pattern_id_from_target(target):
        return True
    current = current.rounded()
    target = target.rounded()
    return (
        current.speed != target.speed
        or current.depth != target.depth
        or current.stroke_range != target.stroke_range
    )

def _target_from_llm_response_move(response, current):
    if not isinstance(response, dict):
        return None
    move = response.get("move")
    if not move:
        return None
    sanitized = _sanitize_llm_move_for_disabled_patterns(move)
    return motion.sanitizer.from_llm_move(sanitized, current)

def _repair_llm_motion_response_if_needed(user_input, response, context, current):
    if not isinstance(response, dict):
        return response, False
    target = _target_from_llm_response_move(response, current)
    needs_repair = (
        (_looks_like_motion_request(user_input) or _chat_claims_motion_change(response.get("chat")))
        and not _target_has_motion_effect(current, target)
    )
    if not needs_repair:
        return response, False
    try:
        repaired = llm.repair_motion_response(user_input, response, context)
    except Exception as exc:
        print(f"[WARN] LLM motion repair failed: {exc}")
        return response, False
    if not isinstance(repaired, dict):
        print(f"[WARN] LLM motion repair returned non-dict response: {repaired!r}")
        return response, False
    return repaired, True

def _apply_llm_response_move(response, current, source="llm"):
    target = _target_from_llm_response_move(response, current)
    if not _target_has_motion_effect(current, target):
        return None
    motion.apply_generated_target(target, source=source)
    return target

def _append_motion_feedback_history(record, rating, source, updated_pattern):
    entry = {
        "pattern_id": record.pattern_id,
        "pattern_name": record.name,
        "rating": rating,
        "source": source or "feedback",
        "at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    }
    if updated_pattern:
        entry["enabled"] = bool(getattr(updated_pattern, "enabled", True))
        if updated_pattern.source == "fixed":
            entry["weight"] = _motion_pattern_summary(updated_pattern).get("weight", 50)
    settings.motion_pattern_feedback_history = (
        [entry] + list(settings.motion_pattern_feedback_history or [])
    )[:MOTION_FEEDBACK_HISTORY_LIMIT]

def _record_motion_pattern_feedback(pattern_id, rating, source="feedback"):
    record = _motion_pattern_record(pattern_id)
    if not record:
        return None
    old_feedback = dict(settings.motion_pattern_feedback.get(record.pattern_id) or {
        "thumbs_up": 0,
        "neutral": 0,
        "thumbs_down": 0,
    })
    feedback = dict(old_feedback)
    feedback[rating] = int(feedback.get(rating, 0)) + 1
    settings.motion_pattern_feedback[record.pattern_id] = feedback
    auto_disabled = False
    if record.source == "fixed":
        current_weight = settings.motion_pattern_weights.get(record.pattern_id, feedback_weight(old_feedback))
        adjusted_weight = adjust_weight_for_feedback(
            current_weight,
            rating,
            feedback,
        )
        if rating == "thumbs_down" and not settings.motion_feedback_auto_disable:
            adjusted_weight = max(1, adjusted_weight)
        settings.motion_pattern_weights[record.pattern_id] = adjusted_weight
    if settings.motion_feedback_auto_disable and rating == "thumbs_down" and should_auto_disable(feedback):
        settings.motion_pattern_enabled[record.pattern_id] = False
        if record.source == "fixed":
            settings.motion_pattern_weights[record.pattern_id] = 0
        auto_disabled = True
    updated = _motion_pattern_record(record.pattern_id)
    _append_motion_feedback_history(record, rating, source, updated)
    settings.save()
    return {
        "pattern": updated,
        "auto_disabled": auto_disabled,
        "motion_patterns": _motion_pattern_catalog_payload(),
        "motion_preferences": _motion_preference_payload(),
    }

def _motion_training_snapshot():
    return app_state.motion_training_snapshot()

def _set_motion_training_state(**updates):
    return app_state.set_motion_training_state(**updates)

def _training_target_for_record(record):
    current = motion.current_target()
    speed = current.speed if current.speed > 0 else 35
    if settings.min_speed >= settings.max_speed:
        speed = max(10, min(45, speed))
    depth = current.depth if current.depth > 0 else 50
    stroke_range = current.stroke_range if current.stroke_range >= 30 else 50
    return MotionTarget(
        speed=speed,
        depth=depth,
        stroke_range=stroke_range,
        label=f"training {record.pattern_id}",
    ).clamped()

def _run_motion_training_pattern(record, *, preview=False):
    try:
        target = _training_target_for_record(record)
        frames = expand_motion_pattern(record.to_motion_pattern(), motion.current_target(), target)
        if not frames:
            _set_motion_training_state(
                state="error",
                pattern_id=record.pattern_id,
                pattern_name=record.name,
                message=f"Pattern {record.name} has no playable frames.",
                preview=preview,
            )
            return
        _set_motion_training_state(
            state="playing",
            pattern_id=record.pattern_id,
            pattern_name=record.name,
            message=f"Playing {'edited preview' if preview else record.name}.",
            preview=preview,
        )
        completed = motion.apply_position_frames(
            frames,
            stop_after=True,
            source="motion training preview" if preview else "motion training",
        )
        if app_state.motion_training_stop_event.is_set():
            _set_motion_training_state(
                state="stopped",
                pattern_id=record.pattern_id,
                pattern_name=record.name,
                message=f"Stopped {record.name}.",
                preview=preview,
            )
        elif not completed:
            _set_motion_training_state(
                state="stopped",
                pattern_id=record.pattern_id,
                pattern_name=record.name,
                message=f"Interrupted {record.name}.",
                preview=preview,
            )
        else:
            _set_motion_training_state(
                state="idle",
                pattern_id=record.pattern_id,
                pattern_name=record.name,
                message=f"Finished {record.name}.",
                preview=preview,
            )
    except Exception as exc:
        _set_motion_training_state(
            state="error",
            pattern_id=record.pattern_id,
            pattern_name=record.name,
            message=f"Pattern playback failed: {exc}",
            preview=preview,
        )
    finally:
        app_state.motion_training_stop_event.clear()

def _training_payload_record(data):
    payload = data.get("pattern") if isinstance(data.get("pattern"), dict) else data
    if not isinstance(payload, dict):
        raise PatternValidationError("Motion training preview requires a pattern object.")
    return record_from_payload(
        payload,
        fallback_id="edited-preview",
        source_override="trained",
        readonly=False,
    )

def _start_motion_training_record(record, *, preview=False):
    if not handy.handy_key:
        return jsonify({"status": "error", "message": "Set a Handy connection key before playing motion training patterns."}), 400
    if app_state.auto_mode_active_task:
        return jsonify({"status": "error", "message": "Stop the active mode before playing a training pattern."}), 409

    with app_state.lock:
        if app_state.motion_training_thread and app_state.motion_training_thread.is_alive():
            return jsonify({"status": "error", "message": "A motion training pattern is already playing."}), 409
        app_state.motion_training_stop_event.clear()
        app_state.motion_training_state.update({
            "state": "starting",
            "pattern_id": record.pattern_id,
            "pattern_name": record.name,
            "message": f"Starting {'edited preview' if preview else record.name}.",
            "preview": preview,
        })
        app_state.motion_training_thread = threading.Thread(
            target=_run_motion_training_pattern,
            args=(record,),
            kwargs={"preview": preview},
            daemon=True,
        )
        app_state.motion_training_thread.start()
        snapshot = dict(app_state.motion_training_state)
    return jsonify({"status": "started", "motion_training": snapshot})

def _stop_motion_training():
    app_state.motion_training_stop_event.set()
    snapshot = _motion_training_snapshot()
    if snapshot.get("state") in {"playing", "starting"}:
        _set_motion_training_state(
            state="stopped",
            message=f"Stopped {snapshot.get('pattern_name') or 'motion training'}.",
            preview=bool(snapshot.get("preview")),
        )
    motion.stop()
    return _motion_training_snapshot()

def reset_runtime_state():
    with app_state.lock:
        active_task = app_state.auto_mode_active_task

    if active_task:
        active_task.stop()
        active_task.join(timeout=5)
        with app_state.lock:
            if app_state.auto_mode_active_task is active_task:
                app_state.auto_mode_active_task = None

    _stop_motion_training()
    _clear_motion_pause_state()
    settings.reset_to_defaults(save=True)
    apply_settings_to_services()
    with app_state.lock:
        app_state.chat_history.clear()
        app_state.messages_for_ui.clear()
        app_state.mode_message_queue.clear()
        app_state.user_signal_event.clear()
        app_state.mode_message_event.clear()
        app_state.current_mood = "Curious"
        app_state.calibration_pos_mm = 0.0
        app_state.active_mode_name = ""
        app_state.active_mode_started_at = None
        app_state.active_mode_paused_at = None
        app_state.active_mode_paused_total = 0.0
        app_state.motion_pause_active = False
        app_state.edging_start_time = None
        app_state.use_long_term_memory = True
        app_state.special_persona_mode = None
        app_state.special_persona_interactions_left = 0
    _set_motion_training_state(
        state="idle",
        pattern_id="",
        pattern_name="",
        message="Motion training idle.",
        last_feedback="",
        preview=False,
    )

SNAKE_ASCII = """
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⠟⠛⠛⠋⠉⠛⠟⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⡏⠉⠹⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⠀⢸⣧⡀⠀⠰⣦⡀⠀⠀⢀⠀⠀⠈⣻⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⡇⢨⣿⣿⣖⡀⢡⠉⠄⣀⢀⣀⡀⠀⠼⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⠀⠀⠘⠋⢏⢀⣰⣖⣿⣿⣿⠟⡡⠀⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣯⠁⢀⠂⡆⠉⠘⠛⠿⣿⢿⠟⢁⣬⡶⢠⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⡯⠀⢀⡀⠝⠀⠀⠀⠀⢀⠠⣩⣤⣠⣆⣾⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⡅⠀⠊⠇⢈⣴⣦⣤⣆⠈⢀⠋⠹⣿⣇⣻⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⡄⠥⡇⠀⠀⠚⠺⠯⠀⠀⠒⠛⠒⢪⢿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⡿⠿⠛⠋⠀⠘⣿⡄⠀⠀⠀⠋⠉⡉⠙⠂⢰⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿
⠀⠈⠉⠀⠀⠀⠀⠀⠀⠀⠙⠷⢐⠀⠀⠀⠀⢀⢴⣿⠊⠀⠉⠉⠉⠈⠙⠉⠛⠿
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠰⣖⣴⣾⡃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠁⠀⠀⠀⠀⠀⢀⠀⠀⠀⠀⠁⠀⠨
"""

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────────────────────────────

def get_current_context():
    with app_state.lock:
        current_mood = app_state.current_mood
        use_long_term_memory = app_state.use_long_term_memory
        edging_start_time = app_state.edging_start_time
        special_persona_mode = app_state.special_persona_mode
    context = {
        'persona_desc': settings.persona_desc, 'current_mood': current_mood,
        'user_profile': settings.user_profile, 'patterns': settings.patterns,
        'motion_preferences': _motion_preference_payload()["prompt"],
        'rules': settings.rules, 'last_stroke_speed': handy.last_relative_speed,
        'last_depth_pos': handy.last_depth_pos, 'last_stroke_range': handy.last_stroke_range,
        'min_speed': settings.min_speed, 'max_speed': settings.max_speed,
        'use_long_term_memory': use_long_term_memory,
        'allow_llm_edge_in_chat': settings.allow_llm_edge_in_chat,
        'allow_llm_edge_in_freestyle': settings.allow_llm_edge_in_freestyle,
        'edging_elapsed_time': None, 'special_persona_mode': special_persona_mode
    }
    if edging_start_time:
        elapsed_seconds = int(time.time() - edging_start_time)
        minutes, seconds = divmod(elapsed_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            context['edging_elapsed_time'] = f"{hours}h {minutes}m {seconds}s"
        else:
            context['edging_elapsed_time'] = f"{minutes}m {seconds}s"
    return context

def add_message_to_queue(text, add_to_history=True, queue_message=True):
    if queue_message:
        app_state.messages_for_ui.append(text)
    if add_to_history:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text:
            app_state.chat_history.append({"role": "assistant", "content": clean_text})
    threading.Thread(target=audio.generate_audio_for_text, args=(text,), daemon=True).start()

def start_background_mode(mode_logic: ModeLogic, initial_message, mode_name):
    with app_state.lock:
        active_task = app_state.auto_mode_active_task
    if active_task:
        active_task.stop()
        active_task.join(timeout=5)
    _stop_motion_training()
    _clear_motion_pause_state()

    app_state.user_signal_event.clear()
    app_state.mode_message_event.clear()
    app_state.mode_message_queue.clear()
    _set_runtime_active_mode(mode_name, reset_timer=True)

    def on_stop():
        with app_state.lock:
            app_state.auto_mode_active_task = None
        _set_runtime_active_mode("")

    def update_mood(m: str) -> None:
        with app_state.lock:
            app_state.current_mood = m
    def get_timings(n: str) -> tuple[float, float]:
        return {
            'auto': (settings.auto_min_time, settings.auto_max_time),
            'freestyle': (settings.auto_min_time, settings.auto_max_time),
            'milking': (settings.milking_min_time, settings.milking_max_time),
            'edging': (settings.edging_min_time, settings.edging_max_time)
        }.get(n, (3, 5))
    def set_mode_name(n: str) -> None:
        _set_runtime_active_mode(n)
    def mode_decision(**kwargs) -> object:
        context = get_current_context()
        target = kwargs.get("current_target")
        current_target = {
            "speed": getattr(target, "speed", None),
            "depth": getattr(target, "depth", None),
            "stroke_range": getattr(target, "stroke_range", None),
        }
        return llm.get_mode_decision(
            app_state.chat_history,
            context,
            mode=kwargs.get("mode", mode_name),
            event=kwargs.get("event", "start"),
            edge_count=kwargs.get("edge_count", 0),
            current_target=current_target,
        )

    services: ModeServices = {'llm': llm, 'handy': handy, 'motion': motion}
    callbacks: ModeCallbacks = {
        'send_message': add_message_to_queue, 'get_context': get_current_context,
        'get_timings': get_timings, 'on_stop': on_stop, 'update_mood': update_mood,
        'user_signal_event': app_state.user_signal_event,
        'message_event': app_state.mode_message_event,
        'message_queue': app_state.mode_message_queue,
        'remember_pattern': _remember_motion_pattern_from_target,
        'remember_pattern_id': _remember_live_motion_pattern_id,
        'freestyle_candidates': _freestyle_candidate_patterns,
        'allow_llm_edge_in_freestyle': lambda: settings.allow_llm_edge_in_freestyle,
        'set_mode_name': set_mode_name,
        'mode_decision': mode_decision,
    }
    task = AutoModeThread(mode_logic, initial_message, services, callbacks, mode_name=mode_name)
    with app_state.lock:
        app_state.auto_mode_active_task = task
    task.start()

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────────────────────────────────
@app.route('/')
def home_page():
    with open(resource_path('index.html'), 'r', encoding='utf-8') as f:
        return render_template_string(f.read())

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory(resource_path('static'), path)

def _konami_code_action():
    def pattern_thread():
        motion.apply_target(MotionTarget(speed=100, depth=50, stroke_range=100, label="konami"), source="konami")
        time.sleep(5)
        motion.stop()
    threading.Thread(target=pattern_thread, daemon=True).start()
    message = f"Kept you waiting, huh?<pre>{SNAKE_ASCII}</pre>"
    add_message_to_queue(message)

def _handle_chat_commands(text, allow_motion=True):
    intent = intent_matcher.parse(text, motion.current_target())
    if intent.kind == "stop":
        _clear_motion_pause_state()
        if app_state.auto_mode_active_task:
            app_state.auto_mode_active_task.stop()
        _stop_motion_training()
        add_message_to_queue("Stopping.", add_to_history=False)
        return True, jsonify({"status": "stopped"})
    if "up up down down left right left right b a" in text:
        _konami_code_action()
        return True, jsonify({"status": "konami_code_activated"})
    if intent.kind == "auto_on" and not app_state.auto_mode_active_task:
        start_background_mode(auto_mode_logic, "Okay, I'll take over...", mode_name='auto')
        return True, jsonify({"status": "auto_started"})
    if intent.kind == "freestyle" and not app_state.auto_mode_active_task:
        start_background_mode(freestyle_mode_logic, "Starting adaptive Freestyle.", mode_name='freestyle')
        return True, jsonify({"status": "freestyle_started"})
    if intent.kind == "auto_off" and app_state.auto_mode_active_task:
        _clear_motion_pause_state()
        app_state.auto_mode_active_task.stop()
        return True, jsonify({"status": "auto_stopped"})
    if intent.kind == "edging":
        start_background_mode(edging_mode_logic, "Let's play an edging game...", mode_name='edging')
        return True, jsonify({"status": "edging_started"})
    if intent.kind == "milking":
        start_background_mode(milking_mode_logic, "You're so close... I'm taking over completely now.", mode_name='milking')
        return True, jsonify({"status": "milking_started"})
    if intent.kind == "move" and intent.target:
        if not allow_motion:
            return False, None
        motion.apply_generated_target(intent.target, source=f"chat command: {intent.matched or 'move'}")
        _remember_motion_pattern_from_target(intent.target)
        add_message_to_queue("Adjusting.", add_to_history=False)
        return True, jsonify({"status": "move_applied", "matched": intent.matched})
    return False, None

def _relay_message_to_active_mode(user_input):
    app_state.mode_message_queue.append(user_input)
    app_state.mode_message_event.set()
    return jsonify({"status": "message_relayed_to_active_mode"})

@app.route('/send_message', methods=['POST'])
def handle_user_message():
    data = _request_json()
    user_input = data.get('message', '').strip()

    if (p := data.get('persona_desc')) and p != settings.persona_desc:
        settings.set_persona_prompt(p); settings.save()
    if (k := data.get('key')) and k != settings.handy_key:
        handy.set_api_key(k); settings.handy_key = k; settings.save()
    
    if not handy.handy_key: return jsonify({"status": "no_key_set"})
    if not user_input: return jsonify({"status": "empty_message"})

    app_state.chat_history.append({"role": "user", "content": user_input})

    handled, response = _handle_chat_commands(
        user_input.lower(),
        allow_motion=not app_state.auto_mode_active_task,
    )
    if handled: return response

    if app_state.auto_mode_active_task:
        return _relay_message_to_active_mode(user_input)

    context = get_current_context()
    current_before_llm = motion.current_target()
    motion_repaired = False
    try:
        llm_response = llm.get_chat_response(app_state.chat_history, context)
    except Exception as exc:
        print(f"[ERROR] LLM request failed: {exc}")
        llm_response = {
            "chat": f"LLM request failed: {exc}",
            "move": None,
            "new_mood": None,
        }
    if not isinstance(llm_response, dict):
        print(f"[WARN] LLM returned non-dict response: {llm_response!r}")
        llm_response = {
            "chat": "The local model returned an unreadable response. Check Ollama model status and try again.",
            "move": None,
            "new_mood": None,
        }
    llm_response, motion_repaired = _repair_llm_motion_response_if_needed(
        user_input,
        llm_response,
        context,
        current_before_llm,
    )
    
    with app_state.lock:
        if app_state.special_persona_mode is not None:
            app_state.special_persona_interactions_left -= 1
            should_revert_persona = app_state.special_persona_interactions_left <= 0
            if should_revert_persona:
                app_state.special_persona_mode = None
        else:
            should_revert_persona = False
    if should_revert_persona:
        add_message_to_queue("(Personality core reverted to standard operation.)", add_to_history=False)

    raw_chat_text = llm_response.get("chat")
    chat_text = str(raw_chat_text or "").strip()
    if not chat_text:
        print(f"[WARN] LLM response did not include chat text: {llm_response!r}")
        chat_text = "The local model returned movement data but no chat text. Check Ollama model status and try again."
    add_message_to_queue(
        chat_text,
        add_to_history=bool(str(raw_chat_text or "").strip()),
        queue_message=True,
    )
    if new_mood := llm_response.get("new_mood"):
        with app_state.lock:
            app_state.current_mood = new_mood
    motion_applied = False
    if not app_state.auto_mode_active_task:
        target = _apply_llm_response_move(
            llm_response,
            current_before_llm,
            source="llm repair" if motion_repaired else "llm",
        )
        motion_applied = target is not None
        _remember_motion_pattern_from_target(target)
    return jsonify({
        "status": "ok",
        "chat": chat_text,
        "chat_queued": True,
        "motion_applied": motion_applied,
        "motion_repaired": motion_repaired,
    })

def _read_uploaded_pattern_payload(upload):
    filename = secure_filename(upload.filename or "pattern.json")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMPORT_EXTENSIONS:
        raise PatternValidationError("Pattern imports must be .json or .funscript files.")
    raw = upload.read(MAX_PATTERN_IMPORT_BYTES + 1)
    if len(raw) > MAX_PATTERN_IMPORT_BYTES:
        raise PatternValidationError("Pattern import is too large.")
    try:
        return filename, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PatternValidationError(f"Pattern file is not valid JSON: {exc}") from exc

def persist_local_voice_settings():
    settings.audio_provider = "local"
    settings.audio_enabled = bool(audio.is_on)
    settings.local_tts_engine = audio.local_engine
    settings.local_tts_style = audio.local_style
    settings.local_tts_prompt_path = audio.local_prompt_path
    settings.local_tts_exaggeration = audio.local_exaggeration
    settings.local_tts_cfg_weight = audio.local_cfg_weight
    settings.local_tts_temperature = audio.local_temperature
    settings.local_tts_top_p = audio.local_top_p
    settings.local_tts_min_p = audio.local_min_p
    settings.local_tts_repetition_penalty = audio.local_repetition_penalty
    settings.save()

@app.route('/get_updates')
def get_ui_updates_route():
    messages = [app_state.messages_for_ui.popleft() for _ in range(len(app_state.messages_for_ui))]
    return jsonify({
        "messages": messages,
        "audio_ready": audio.has_audio(),
        "audio_error": audio.consume_last_error(),
    })

def _request_bool_value(data, key, default):
    if key not in data:
        return bool(default)
    value = data.get(key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)

def _timing_pair(data, min_key, max_key, default_min, default_max):
    try:
        first = float(data.get(min_key, default_min))
        second = float(data.get(max_key, default_max))
    except (TypeError, ValueError):
        first, second = default_min, default_max
    first = max(1.0, min(60.0, first))
    second = max(1.0, min(60.0, second))
    return min(first, second), max(first, second)

def _rate_last_live_motion_pattern(rating, source="chat feedback"):
    if rating not in {"thumbs_up", "neutral", "thumbs_down"}:
        return None
    with app_state.lock:
        pattern_id = app_state.last_live_motion_pattern_id
    if not pattern_id:
        return None
    return _record_motion_pattern_feedback(pattern_id, rating, source=source)


from .blueprints import audio as audio_routes
from .blueprints import modes as modes_routes
from .blueprints import motion as motion_routes
from .blueprints import register_blueprints
from .blueprints import settings as settings_routes


register_blueprints(app)

# Compatibility shim - do not extend. Preserve old ``strokegpt.web``
# route-function names for tests and direct imports; new code should import
# route handlers from ``strokegpt.blueprints.*``.
check_settings_route = settings_routes.check_settings_route
reset_settings_route = settings_routes.reset_settings_route
set_persona_prompt_route = settings_routes.set_persona_prompt_route
set_ollama_model_route = settings_routes.set_ollama_model_route
ollama_status_route = settings_routes.ollama_status_route
set_diagnostics_levels_route = settings_routes.set_diagnostics_levels_route
pull_ollama_model_route = settings_routes.pull_ollama_model_route
set_ai_name_route = settings_routes.set_ai_name_route
toggle_memory_route = settings_routes.toggle_memory_route
set_pfp_route = settings_routes.set_pfp_route
set_handy_key_route = settings_routes.set_handy_key_route

motion_patterns_route = motion_routes.motion_patterns_route
motion_preferences_route = motion_routes.motion_preferences_route
reset_motion_preferences_route = motion_routes.reset_motion_preferences_route
set_motion_feedback_options_route = motion_routes.set_motion_feedback_options_route
motion_pattern_detail_route = motion_routes.motion_pattern_detail_route
export_motion_pattern_route = motion_routes.export_motion_pattern_route
import_motion_pattern_route = motion_routes.import_motion_pattern_route
save_generated_motion_pattern_route = motion_routes.save_generated_motion_pattern_route
set_motion_pattern_enabled_route = motion_routes.set_motion_pattern_enabled_route
set_motion_pattern_weight_route = motion_routes.set_motion_pattern_weight_route
reset_motion_pattern_feedback_route = motion_routes.reset_motion_pattern_feedback_route
motion_training_status_route = motion_routes.motion_training_status_route
start_motion_training_route = motion_routes.start_motion_training_route
preview_motion_training_route = motion_routes.preview_motion_training_route
stop_motion_training_route = motion_routes.stop_motion_training_route
motion_training_feedback_route = motion_routes.motion_training_feedback_route
nudge_route = motion_routes.nudge_route
test_depth_range_route = motion_routes.test_depth_range_route
get_status_route = motion_routes.get_status_route
set_depth_limits_route = motion_routes.set_depth_limits_route
set_speed_limits_route = motion_routes.set_speed_limits_route
set_motion_backend_route = motion_routes.set_motion_backend_route
set_llm_edge_permissions_route = motion_routes.set_llm_edge_permissions_route
like_last_move_route = motion_routes.like_last_move_route
dislike_last_move_route = motion_routes.dislike_last_move_route
rate_last_motion_pattern_route = motion_routes.rate_last_motion_pattern_route

elevenlabs_setup_route = audio_routes.elevenlabs_setup_route
set_elevenlabs_voice_route = audio_routes.set_elevenlabs_voice_route
set_audio_provider_route = audio_routes.set_audio_provider_route
local_tts_status_route = audio_routes.local_tts_status_route
preload_local_tts_model_route = audio_routes.preload_local_tts_model_route
set_local_tts_voice_route = audio_routes.set_local_tts_voice_route
upload_local_tts_sample_route = audio_routes.upload_local_tts_sample_route
test_local_tts_voice_route = audio_routes.test_local_tts_voice_route
get_audio_route = audio_routes.get_audio_route

signal_edge_route = modes_routes.signal_edge_route
toggle_motion_pause_route = modes_routes.toggle_motion_pause_route
set_mode_timings_route = modes_routes.set_mode_timings_route
start_edging_route = modes_routes.start_edging_route
start_milking_route = modes_routes.start_milking_route
start_freestyle_route = modes_routes.start_freestyle_route
stop_auto_route = modes_routes.stop_auto_route

# ─── APP STARTUP ───────────────────────────────────────────────────────────────────────────────────
def on_exit():
    print("[INFO] Saving settings on exit...")
    settings.save(llm, app_state.chat_history)
    print("[OK] Settings saved.")

def main():
    atexit.register(on_exit)
    host = os.getenv("STROKEGPT_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    requested_port = _env_int("STROKEGPT_PORT", DEFAULT_PORT)
    try:
        port = _select_bind_port(host, requested_port)
    except OSError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
    if port != requested_port:
        print(f"[WARN] Port {requested_port} is unavailable; using {port} instead.")
    print(f"[INFO] Starting Handy AI app at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
    print(f"[INFO] Open http://{_display_host(host)}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    main()
