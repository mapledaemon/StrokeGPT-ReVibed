import os
import sys
import io
import json
import re
import atexit
import socket
import threading
import time
from collections import deque
from pathlib import Path
import requests
from flask import Flask, request, jsonify, render_template_string, send_file, send_from_directory
from werkzeug.utils import secure_filename

from .settings import DIAGNOSTICS_LEVELS, SettingsManager, normalize_ollama_model
from .handy import HandyController
from .llm import LLMService
from .audio import AudioService
from .background_modes import AutoModeThread, auto_mode_logic, milking_mode_logic, edging_mode_logic
from .motion import IntentMatcher, MotionController, MotionTarget
from .motion_patterns import PATTERNS, expand_motion_pattern
from .motion_preferences import (
    THUMBS_DOWN_DISABLE_THRESHOLD,
    adjust_weight_for_feedback,
    build_motion_preference_payload,
    clamp_weight,
    enrich_catalog,
    feedback_weight,
    should_auto_disable,
)
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
chat_history = deque(maxlen=20)
messages_for_ui = deque()
auto_mode_active_task = None
current_mood = "Curious"
use_long_term_memory = True
calibration_pos_mm = 0.0
user_signal_event = threading.Event()
mode_message_event = threading.Event()
mode_message_queue = deque(maxlen=5)
edging_start_time = None
depth_test_lock = threading.Lock()
ollama_pull_lock = threading.Lock()
ollama_pull_thread = None
ollama_pull_state = {
    "state": "idle",
    "model": "",
    "message": "No model download running.",
    "completed": 0,
    "total": 0,
    "percent": None,
}
motion_training_lock = threading.Lock()
motion_training_thread = None
motion_training_stop_event = threading.Event()
motion_training_state = {
    "state": "idle",
    "pattern_id": "",
    "pattern_name": "",
    "message": "Motion training idle.",
    "last_feedback": "",
    "preview": False,
}
last_live_motion_pattern_id = ""

# Easter Egg State
special_persona_mode = None
special_persona_interactions_left = 0

def get_ollama_models_for_ui():
    models = list(settings.ollama_models)
    if llm.model not in models:
        models.insert(0, llm.model)
    return models

def _format_bytes(value):
    try:
        value = int(value or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"

def _set_ollama_pull_state(**updates):
    with ollama_pull_lock:
        ollama_pull_state.update(updates)

def _ollama_pull_snapshot():
    with ollama_pull_lock:
        return dict(ollama_pull_state)

def _diagnostics_level_options():
    labels = {
        "compact": "Compact",
        "status": "Status",
        "debug": "Debug",
    }
    return [
        {"id": level, "label": labels[level]}
        for level in ("compact", "status", "debug")
        if level in DIAGNOSTICS_LEVELS
    ]

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
    current_model = normalize_ollama_model(llm.model)
    diagnostics_level = settings.ollama_diagnostics_level
    payload = {
        "available": False,
        "base_url": OLLAMA_BASE_URL,
        "current_model": current_model,
        "current_model_installed": False,
        "installed_models": [],
        "installed_model_names": [],
        "download": _ollama_pull_snapshot(),
        "diagnostics_level": diagnostics_level,
        "llm_diagnostics": llm.diagnostics(include_raw=diagnostics_level == "debug"),
        "message": "Ollama is not reachable. Start Ollama before downloading or using local models.",
    }
    try:
        installed_models = _ollama_installed_models()
    except requests.exceptions.RequestException as exc:
        payload["error"] = str(exc)
        return payload
    except Exception as exc:
        payload["error"] = str(exc)
        return payload

    names = [item["name"] for item in installed_models]
    payload.update({
        "available": True,
        "installed_models": installed_models,
        "installed_model_names": names,
        "current_model_installed": current_model in names,
        "message": (
            f"Current model is installed: {current_model}"
            if current_model in names
            else f"Current model is not installed: {current_model}. Click Download Model before chatting."
        ),
    })
    return payload

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
    global ollama_pull_thread

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

    with ollama_pull_lock:
        if ollama_pull_thread and ollama_pull_thread.is_alive():
            return False, f"Already downloading {ollama_pull_state.get('model') or 'a model'}."
        ollama_pull_state.update({
            "state": "downloading",
            "model": model,
            "message": f"Queued download for {model}.",
            "completed": 0,
            "total": 0,
            "percent": None,
        })
        ollama_pull_thread = threading.Thread(target=_run_ollama_pull, args=(model,), daemon=True)
        ollama_pull_thread.start()
    return True, f"Started downloading {model}."

def get_persona_prompts_for_ui():
    return settings.persona_prompt_options()

def settings_payload():
    local_tts_status = audio.local_status()
    return {
        "configured": bool(settings.handy_key and settings.min_depth < settings.max_depth),
        "persona": settings.persona_desc,
        "persona_prompts": get_persona_prompts_for_ui(),
        "handy_key": settings.handy_key,
        "ai_name": settings.ai_name,
        "elevenlabs_key": settings.elevenlabs_api_key,
        "ollama_model": llm.model,
        "ollama_models": get_ollama_models_for_ui(),
        "ollama_status": _ollama_status_payload(),
        "audio_provider": settings.audio_provider,
        "audio_enabled": settings.audio_enabled,
        "elevenlabs_voice_id": settings.elevenlabs_voice_id,
        "local_tts_status": local_tts_status,
        "local_tts_engine": audio.local_engine,
        "local_tts_engines": local_tts_status.get("engines", []),
        "local_tts_style_presets": audio.CHATTERBOX_STYLE_PRESETS,
        "local_tts_style": settings.local_tts_style,
        "local_tts_prompt_path": settings.local_tts_prompt_path,
        "local_tts_exaggeration": settings.local_tts_exaggeration,
        "local_tts_cfg_weight": settings.local_tts_cfg_weight,
        "local_tts_temperature": settings.local_tts_temperature,
        "local_tts_top_p": settings.local_tts_top_p,
        "local_tts_min_p": settings.local_tts_min_p,
        "local_tts_repetition_penalty": settings.local_tts_repetition_penalty,
        "min_depth": settings.min_depth,
        "max_depth": settings.max_depth,
        "min_speed": settings.min_speed,
        "max_speed": settings.max_speed,
        "motion_backend": settings.motion_backend,
        "motion_diagnostics_level": settings.motion_diagnostics_level,
        "ollama_diagnostics_level": settings.ollama_diagnostics_level,
        "motion_feedback_auto_disable": settings.motion_feedback_auto_disable,
        "diagnostics_levels": _diagnostics_level_options(),
        "motion_backends": [
            {
                "id": "hamp",
                "label": "HAMP continuous",
                "description": "Recommended default for smooth ongoing app motion.",
                "experimental": False,
            },
            {
                "id": "position",
                "label": "Flexible position/script",
                "description": "Experimental path for pattern fidelity and spatial scripts.",
                "experimental": True,
            },
        ],
        "motion_patterns": _motion_pattern_catalog_payload(),
        "motion_preferences": _motion_preference_payload(),
        "pfp": settings.profile_picture_b64,
        "timings": {
            "auto_min": settings.auto_min_time,
            "auto_max": settings.auto_max_time,
            "milking_min": settings.milking_min_time,
            "milking_max": settings.milking_max_time,
            "edging_min": settings.edging_min_time,
            "edging_max": settings.edging_max_time,
        },
    }

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
    payload = enrich_catalog(
        motion_pattern_library.catalog(settings.motion_pattern_enabled, settings.motion_pattern_feedback),
        settings.motion_pattern_weights,
    )
    payload["feedback_history"] = list(settings.motion_pattern_feedback_history[:MOTION_FEEDBACK_HISTORY_LIMIT])
    return payload

def _motion_preference_payload():
    return build_motion_preference_payload(_motion_pattern_catalog_payload())

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
    global last_live_motion_pattern_id
    pattern_id = _fixed_pattern_id_from_target(target)
    if pattern_id:
        last_live_motion_pattern_id = pattern_id
    return pattern_id

def _llm_visible_fixed_pattern(pattern_id):
    catalog = _motion_pattern_catalog_payload()
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
    with motion_training_lock:
        return dict(motion_training_state)

def _set_motion_training_state(**updates):
    with motion_training_lock:
        motion_training_state.update(updates)
        return dict(motion_training_state)

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
        if motion_training_stop_event.is_set():
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
        motion_training_stop_event.clear()

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
    global motion_training_thread
    if not handy.handy_key:
        return jsonify({"status": "error", "message": "Set a Handy connection key before playing motion training patterns."}), 400
    if auto_mode_active_task:
        return jsonify({"status": "error", "message": "Stop the active mode before playing a training pattern."}), 409

    with motion_training_lock:
        if motion_training_thread and motion_training_thread.is_alive():
            return jsonify({"status": "error", "message": "A motion training pattern is already playing."}), 409
        motion_training_stop_event.clear()
        motion_training_state.update({
            "state": "starting",
            "pattern_id": record.pattern_id,
            "pattern_name": record.name,
            "message": f"Starting {'edited preview' if preview else record.name}.",
            "preview": preview,
        })
        motion_training_thread = threading.Thread(
            target=_run_motion_training_pattern,
            args=(record,),
            kwargs={"preview": preview},
            daemon=True,
        )
        motion_training_thread.start()
        snapshot = dict(motion_training_state)
    return jsonify({"status": "started", "motion_training": snapshot})

def _stop_motion_training():
    motion_training_stop_event.set()
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
    global auto_mode_active_task, current_mood, calibration_pos_mm, edging_start_time
    global special_persona_mode, special_persona_interactions_left

    if auto_mode_active_task:
        auto_mode_active_task.stop()
        auto_mode_active_task.join(timeout=5)
        auto_mode_active_task = None

    _stop_motion_training()
    settings.reset_to_defaults(save=True)
    apply_settings_to_services()
    chat_history.clear()
    messages_for_ui.clear()
    mode_message_queue.clear()
    user_signal_event.clear()
    current_mood = "Curious"
    calibration_pos_mm = 0.0
    edging_start_time = None
    special_persona_mode = None
    special_persona_interactions_left = 0
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
    global edging_start_time, special_persona_mode
    context = {
        'persona_desc': settings.persona_desc, 'current_mood': current_mood,
        'user_profile': settings.user_profile, 'patterns': settings.patterns,
        'motion_preferences': _motion_preference_payload()["prompt"],
        'rules': settings.rules, 'last_stroke_speed': handy.last_relative_speed,
        'last_depth_pos': handy.last_depth_pos, 'last_stroke_range': handy.last_stroke_range,
        'min_speed': settings.min_speed, 'max_speed': settings.max_speed,
        'use_long_term_memory': use_long_term_memory,
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
        messages_for_ui.append(text)
    if add_to_history:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text: chat_history.append({"role": "assistant", "content": clean_text})
    threading.Thread(target=audio.generate_audio_for_text, args=(text,), daemon=True).start()

def start_background_mode(mode_logic, initial_message, mode_name):
    global auto_mode_active_task, edging_start_time
    if auto_mode_active_task:
        auto_mode_active_task.stop()
        auto_mode_active_task.join(timeout=5)
    _stop_motion_training()
    
    user_signal_event.clear()
    mode_message_event.clear()
    mode_message_queue.clear()
    if mode_name == 'edging':
        edging_start_time = time.time()
    
    def on_stop():
        global auto_mode_active_task, edging_start_time
        auto_mode_active_task = None
        edging_start_time = None

    def update_mood(m): global current_mood; current_mood = m
    def get_timings(n):
        return {
            'auto': (settings.auto_min_time, settings.auto_max_time),
            'milking': (settings.milking_min_time, settings.milking_max_time),
            'edging': (settings.edging_min_time, settings.edging_max_time)
        }.get(n, (3, 5))

    services = {'llm': llm, 'handy': handy, 'motion': motion}
    callbacks = {
        'send_message': add_message_to_queue, 'get_context': get_current_context,
        'get_timings': get_timings, 'on_stop': on_stop, 'update_mood': update_mood,
        'user_signal_event': user_signal_event,
        'message_event': mode_message_event,
        'message_queue': mode_message_queue,
        'remember_pattern': _remember_motion_pattern_from_target,
    }
    auto_mode_active_task = AutoModeThread(mode_logic, initial_message, services, callbacks, mode_name=mode_name)
    auto_mode_active_task.start()

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
        if auto_mode_active_task: auto_mode_active_task.stop()
        _stop_motion_training()
        add_message_to_queue("Stopping.", add_to_history=False)
        return True, jsonify({"status": "stopped"})
    if "up up down down left right left right b a" in text:
        _konami_code_action()
        return True, jsonify({"status": "konami_code_activated"})
    if intent.kind == "auto_on" and not auto_mode_active_task:
        start_background_mode(auto_mode_logic, "Okay, I'll take over...", mode_name='auto')
        return True, jsonify({"status": "auto_started"})
    if intent.kind == "auto_off" and auto_mode_active_task:
        auto_mode_active_task.stop()
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
    mode_message_queue.append(user_input)
    mode_message_event.set()
    return jsonify({"status": "message_relayed_to_active_mode"})

@app.route('/send_message', methods=['POST'])
def handle_user_message():
    global special_persona_mode, special_persona_interactions_left
    data = _request_json()
    user_input = data.get('message', '').strip()

    if (p := data.get('persona_desc')) and p != settings.persona_desc:
        settings.set_persona_prompt(p); settings.save()
    if (k := data.get('key')) and k != settings.handy_key:
        handy.set_api_key(k); settings.handy_key = k; settings.save()
    
    if not handy.handy_key: return jsonify({"status": "no_key_set"})
    if not user_input: return jsonify({"status": "empty_message"})

    chat_history.append({"role": "user", "content": user_input})
    
    handled, response = _handle_chat_commands(user_input.lower(), allow_motion=not auto_mode_active_task)
    if handled: return response

    if auto_mode_active_task:
        return _relay_message_to_active_mode(user_input)

    context = get_current_context()
    current_before_llm = motion.current_target()
    motion_repaired = False
    try:
        llm_response = llm.get_chat_response(chat_history, context)
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
    
    if special_persona_mode is not None:
        special_persona_interactions_left -= 1
        if special_persona_interactions_left <= 0:
            special_persona_mode = None
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
    if new_mood := llm_response.get("new_mood"): global current_mood; current_mood = new_mood
    motion_applied = False
    if not auto_mode_active_task:
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

@app.route('/check_settings')
def check_settings_route():
    return jsonify(settings_payload())

@app.route('/motion_patterns')
def motion_patterns_route():
    return jsonify(_motion_pattern_catalog_payload())

@app.route('/motion_preferences')
def motion_preferences_route():
    payload = _motion_preference_payload()
    payload["status"] = "success"
    return jsonify(payload)

@app.route('/motion_preferences/reset', methods=['POST'])
def reset_motion_preferences_route():
    settings.motion_pattern_feedback = {}
    settings.motion_pattern_weights = {}
    settings.save()
    payload = _motion_preference_payload()
    payload["status"] = "success"
    return jsonify(payload)

@app.route('/motion_feedback_options', methods=['POST'])
def set_motion_feedback_options_route():
    data = _request_json()
    settings.motion_feedback_auto_disable = bool(data.get("auto_disable", False))
    settings.save()
    return jsonify({
        "status": "success",
        "motion_feedback_auto_disable": settings.motion_feedback_auto_disable,
        "motion_patterns": _motion_pattern_catalog_payload(),
        "motion_preferences": _motion_preference_payload(),
    })

@app.route('/motion_patterns/<pattern_id>')
def motion_pattern_detail_route(pattern_id):
    record = _motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    return jsonify({"status": "success", "pattern": _motion_pattern_summary(record, include_actions=True)})

@app.route('/motion_patterns/<pattern_id>/export')
def export_motion_pattern_route(pattern_id):
    record = _motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    payload = json.dumps(record.to_export_dict(), indent=2).encode("utf-8")
    return send_file(
        io.BytesIO(payload),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"{record.pattern_id}.strokegpt-pattern.json",
    )

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

@app.route('/import_motion_pattern', methods=['POST'])
def import_motion_pattern_route():
    try:
        if "pattern" in request.files:
            filename, payload = _read_uploaded_pattern_payload(request.files["pattern"])
        else:
            payload = _request_json()
            filename = (
                secure_filename(payload.get("filename") or "pattern.json")
                if isinstance(payload, dict)
                else "pattern.json"
            )
        record = motion_pattern_library.import_payload(payload, filename=filename)
    except PatternValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({"status": "success", "pattern": _motion_pattern_summary(record, include_actions=True)})

@app.route('/motion_patterns/save_generated', methods=['POST'])
def save_generated_motion_pattern_route():
    data = _request_json()
    payload = data.get("pattern") if isinstance(data.get("pattern"), dict) else {}
    filename_source = (
        data.get("filename")
        or payload.get("id")
        or payload.get("name")
        or "trained-pattern"
    )
    filename = secure_filename(f"{filename_source}.json")
    try:
        record = motion_pattern_library.import_payload(
            payload,
            filename=filename,
            source_override="trained",
        )
    except PatternValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({
        "status": "success",
        "pattern": _motion_pattern_summary(record, include_actions=True),
        "motion_patterns": _motion_pattern_catalog_payload(),
        "motion_preferences": _motion_preference_payload(),
    })

@app.route('/motion_patterns/<pattern_id>/enabled', methods=['POST'])
def set_motion_pattern_enabled_route(pattern_id):
    data = _request_json()
    record = _motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    settings.motion_pattern_enabled[record.pattern_id] = bool(data.get("enabled", True))
    settings.save()
    updated = _motion_pattern_record(record.pattern_id)
    return jsonify({
        "status": "success",
        "pattern": _motion_pattern_summary(updated, include_actions=True),
        "motion_patterns": _motion_pattern_catalog_payload(),
        "motion_preferences": _motion_preference_payload(),
    })

@app.route('/motion_patterns/<pattern_id>/weight', methods=['POST'])
def set_motion_pattern_weight_route(pattern_id):
    data = _request_json()
    record = _motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    if record.source != "fixed":
        return jsonify({"status": "error", "message": "Only fixed patterns have LLM weights."}), 400
    settings.motion_pattern_weights[record.pattern_id] = clamp_weight(data.get("weight"))
    settings.save()
    updated = _motion_pattern_record(record.pattern_id)
    return jsonify({
        "status": "success",
        "pattern": _motion_pattern_summary(updated, include_actions=True),
        "motion_patterns": _motion_pattern_catalog_payload(),
        "motion_preferences": _motion_preference_payload(),
    })

@app.route('/motion_patterns/<pattern_id>/feedback/reset', methods=['POST'])
def reset_motion_pattern_feedback_route(pattern_id):
    record = _motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    settings.motion_pattern_feedback.pop(record.pattern_id, None)
    if record.source == "fixed":
        settings.motion_pattern_weights.pop(record.pattern_id, None)
    updated = _motion_pattern_record(record.pattern_id)
    _append_motion_feedback_history(record, "reset", "settings reset", updated)
    settings.save()
    return jsonify({
        "status": "success",
        "message": f"Reset feedback for {updated.name}.",
        "pattern": _motion_pattern_summary(updated, include_actions=True),
        "motion_patterns": _motion_pattern_catalog_payload(),
        "motion_preferences": _motion_preference_payload(),
    })

@app.route('/motion_training/status')
def motion_training_status_route():
    return jsonify({"status": "success", "motion_training": _motion_training_snapshot()})

@app.route('/motion_training/start', methods=['POST'])
def start_motion_training_route():
    data = _request_json()
    pattern_id = data.get("pattern_id", "")
    record = _motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    return _start_motion_training_record(record, preview=False)

@app.route('/motion_training/preview', methods=['POST'])
def preview_motion_training_route():
    data = _request_json()
    try:
        record = _training_payload_record(data)
    except PatternValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return _start_motion_training_record(record, preview=True)

@app.route('/motion_training/stop', methods=['POST'])
def stop_motion_training_route():
    snapshot = _stop_motion_training()
    return jsonify({"status": "stopped", "motion_training": snapshot})

@app.route('/motion_training/<pattern_id>/feedback', methods=['POST'])
def motion_training_feedback_route(pattern_id):
    data = _request_json()
    rating = str(data.get("rating", "")).strip().lower()
    if rating not in {"thumbs_up", "neutral", "thumbs_down"}:
        return jsonify({"status": "error", "message": "Feedback must be thumbs_up, neutral, or thumbs_down."}), 400
    result = _record_motion_pattern_feedback(pattern_id, rating, source="motion training")
    if not result:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    updated = result["pattern"]
    suffix = ""
    if result["auto_disabled"]:
        suffix = f" Disabled after {THUMBS_DOWN_DISABLE_THRESHOLD} thumbs down ratings."
    _set_motion_training_state(
        pattern_id=updated.pattern_id,
        pattern_name=updated.name,
        last_feedback=rating,
        message=f"Saved {rating.replace('_', ' ')} feedback for {updated.name}.{suffix}",
        preview=False,
    )
    return jsonify({
        "status": "success",
        "pattern": _motion_pattern_summary(updated, include_actions=True),
        "motion_patterns": result["motion_patterns"],
        "motion_preferences": result["motion_preferences"],
        "motion_training": _motion_training_snapshot(),
        "auto_disabled": result["auto_disabled"],
    })

@app.route('/reset_settings', methods=['POST'])
def reset_settings_route():
    data = _request_json()
    if data.get("confirm") != "RESET":
        return jsonify({"status": "error", "message": "Reset confirmation is required."}), 400
    reset_runtime_state()
    payload = settings_payload()
    payload["status"] = "success"
    return jsonify(payload)

@app.route('/set_persona_prompt', methods=['POST'])
def set_persona_prompt_route():
    data = _request_json()
    prompt = data.get('persona_desc', '')
    save_prompt = data.get('save_prompt', True)
    if not settings.set_persona_prompt(prompt, save_prompt=save_prompt):
        return jsonify({"status": "error", "message": "Persona prompt is required."}), 400
    settings.save()
    return jsonify({
        "status": "success",
        "persona": settings.persona_desc,
        "persona_prompts": get_persona_prompts_for_ui(),
    })

@app.route('/set_ollama_model', methods=['POST'])
def set_ollama_model_route():
    data = _request_json()
    model = normalize_ollama_model(data.get('model', ''))
    if not model:
        return jsonify({"status": "error", "message": "Model name is required."}), 400
    if not llm.set_model(model):
        return jsonify({"status": "error", "message": "Invalid model name."}), 400
    settings.set_ollama_model(model)
    settings.save()
    return jsonify({
        "status": "success",
        "ollama_model": llm.model,
        "ollama_models": get_ollama_models_for_ui(),
        "ollama_status": _ollama_status_payload(),
    })

@app.route('/ollama_status')
def ollama_status_route():
    return jsonify(_ollama_status_payload())

@app.route('/set_diagnostics_levels', methods=['POST'])
def set_diagnostics_levels_route():
    data = _request_json()
    motion_level = settings._normalize_diagnostics_level(
        data.get("motion_diagnostics_level", settings.motion_diagnostics_level)
    )
    ollama_level = settings._normalize_diagnostics_level(
        data.get("ollama_diagnostics_level", settings.ollama_diagnostics_level)
    )
    settings.motion_diagnostics_level = motion_level
    settings.ollama_diagnostics_level = ollama_level
    settings.save()
    return jsonify({
        "status": "success",
        "motion_diagnostics_level": motion_level,
        "ollama_diagnostics_level": ollama_level,
        "diagnostics_levels": _diagnostics_level_options(),
        "ollama_status": _ollama_status_payload(),
    })

@app.route('/pull_ollama_model', methods=['POST'])
def pull_ollama_model_route():
    data = _request_json()
    model = normalize_ollama_model(data.get('model') or llm.model)
    if not model:
        return jsonify({"status": "error", "message": "Model name is required."}), 400

    settings.set_ollama_model(model)
    llm.set_model(model)
    settings.save()
    ok, message = _start_ollama_pull(model)
    return jsonify({
        "status": "started" if ok else "error",
        "message": message,
        "ollama_model": llm.model,
        "ollama_models": get_ollama_models_for_ui(),
        "ollama_status": _ollama_status_payload(),
    })

@app.route('/set_ai_name', methods=['POST'])
def set_ai_name_route():
    global special_persona_mode, special_persona_interactions_left
    data = _request_json()
    name = data.get('name', 'BOT').strip()
    if not name: name = 'BOT'
    
    if name.lower() == 'glados':
        special_persona_mode = "GLaDOS"
        special_persona_interactions_left = 5
        settings.ai_name = "GLaDOS"
        settings.save()
        return jsonify({"status": "special_persona_activated", "persona": "GLaDOS", "message": "Oh, it's *you*."})

    settings.ai_name = name; settings.save()
    return jsonify({"status": "success", "name": name})

@app.route('/signal_edge', methods=['POST'])
def signal_edge_route():
    if auto_mode_active_task and auto_mode_active_task.name in {'edging', 'milking'}:
        user_signal_event.set()
        mode_message_event.set()
        return jsonify({"status": "signaled", "mode": auto_mode_active_task.name})
    return jsonify({"status": "ignored", "message": "Edge or milking mode not active."}), 400

@app.route('/set_profile_picture', methods=['POST'])
def set_pfp_route():
    b64_data = _request_json().get('pfp_b64')
    if not b64_data: return jsonify({"status": "error", "message": "Missing image data"}), 400
    settings.profile_picture_b64 = b64_data; settings.save()
    return jsonify({"status": "success"})

@app.route('/set_handy_key', methods=['POST'])
def set_handy_key_route():
    key = _request_json().get('key')
    if not key: return jsonify({"status": "error", "message": "Key is missing"}), 400
    handy.set_api_key(key); settings.handy_key = key; settings.save()
    return jsonify({"status": "success"})

@app.route('/nudge', methods=['POST'])
def nudge_route():
    global calibration_pos_mm
    if calibration_pos_mm == 0.0 and (pos := handy.get_position_mm()):
        calibration_pos_mm = pos
    direction = _request_json().get('direction')
    calibration_pos_mm = handy.nudge(direction, 0, 100, calibration_pos_mm)
    return jsonify({"status": "ok", "depth_percent": handy.mm_to_percent(calibration_pos_mm)})

@app.route('/test_depth_range', methods=['POST'])
def test_depth_range_route():
    data = _request_json()
    depth1 = _request_int(data, 'min_depth', 5)
    depth2 = _request_int(data, 'max_depth', 100)
    min_depth = max(0, min(100, min(depth1, depth2)))
    max_depth = max(0, min(100, max(depth1, depth2)))
    if not depth_test_lock.acquire(blocking=False):
        return jsonify({"status": "busy", "min_depth": min_depth, "max_depth": max_depth})
    motion.stop()

    def run_depth_test():
        try:
            handy.test_depth_range(min_depth, max_depth)
        finally:
            depth_test_lock.release()

    threading.Thread(
        target=run_depth_test,
        daemon=True,
    ).start()
    return jsonify({"status": "testing", "min_depth": min_depth, "max_depth": max_depth})

@app.route('/setup_elevenlabs', methods=['POST'])
def elevenlabs_setup_route():
    api_key = _request_json().get('api_key')
    if not api_key or not audio.set_api_key(api_key): return jsonify({"status": "error"}), 400
    settings.elevenlabs_api_key = api_key; settings.save()
    return jsonify(audio.fetch_available_voices())

@app.route('/set_elevenlabs_voice', methods=['POST'])
def set_elevenlabs_voice_route():
    data = _request_json()
    voice_id, enabled = data.get('voice_id'), data.get('enabled', False)
    ok, message = audio.configure_voice(voice_id, enabled)
    if ok:
        settings.audio_provider = "elevenlabs"
        settings.audio_enabled = bool(enabled)
        settings.elevenlabs_voice_id = voice_id
        settings.save()
    return jsonify({"status": "ok" if ok else "error", "message": message})

@app.route('/set_audio_provider', methods=['POST'])
def set_audio_provider_route():
    data = _request_json()
    provider = data.get('provider', 'elevenlabs')
    enabled = data.get('enabled', settings.audio_enabled)
    ok, message = audio.set_provider(provider, enabled)
    if ok:
        settings.audio_provider = provider
        settings.audio_enabled = bool(enabled)
        settings.save()
    return jsonify({"status": "ok" if ok else "error", "message": message, "local_tts_status": audio.local_status()})

@app.route('/local_tts_status')
def local_tts_status_route():
    return jsonify(audio.local_status())

@app.route('/preload_local_tts_model', methods=['POST'])
def preload_local_tts_model_route():
    started = audio.preload_local_model_async(force=True)
    message = "Local voice model download/load started." if started else "Local voice model could not be started."
    return jsonify({"status": "started" if started else "error", "message": message, "local_tts_status": audio.local_status()})

@app.route('/set_local_tts_voice', methods=['POST'])
def set_local_tts_voice_route():
    data = _request_json()
    enabled = data.get('enabled', False)
    prompt_path = data.get('prompt_path', '')
    style = data.get('style', settings.local_tts_style)
    engine = data.get('engine', settings.local_tts_engine)
    exaggeration = data.get('exaggeration', 0.65)
    cfg_weight = data.get('cfg_weight', 0.35)
    temperature = data.get('temperature', settings.local_tts_temperature)
    top_p = data.get('top_p', settings.local_tts_top_p)
    min_p = data.get('min_p', settings.local_tts_min_p)
    repetition_penalty = data.get('repetition_penalty', settings.local_tts_repetition_penalty)
    ok, message = audio.configure_local_voice(
        enabled,
        prompt_path,
        exaggeration,
        cfg_weight,
        style,
        temperature,
        top_p,
        min_p,
        repetition_penalty,
        engine,
    )
    if ok:
        persist_local_voice_settings()
    return jsonify({"status": "ok" if ok else "error", "message": message, "local_tts_status": audio.local_status()})

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

@app.route('/upload_local_tts_sample', methods=['POST'])
def upload_local_tts_sample_route():
    uploaded = request.files.get('sample')
    if not uploaded or not uploaded.filename:
        return jsonify({"status": "error", "message": "Choose an audio file first."}), 400

    original_name = secure_filename(uploaded.filename)
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_VOICE_SAMPLE_EXTENSIONS:
        return jsonify({
            "status": "error",
            "message": "Sample must be WAV, MP3, FLAC, M4A, OGG, or AAC.",
        }), 400

    VOICE_SAMPLE_DIR.mkdir(exist_ok=True)
    stem = Path(original_name).stem or "voice-sample"
    filename = f"{int(time.time())}-{stem}{extension}"
    target = (VOICE_SAMPLE_DIR / filename).resolve()
    sample_root = VOICE_SAMPLE_DIR.resolve()
    try:
        target.relative_to(sample_root)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid sample filename."}), 400

    uploaded.save(target)
    audio.configure_local_voice(
        audio.is_on,
        str(target),
        audio.local_exaggeration,
        audio.local_cfg_weight,
        audio.local_style,
        audio.local_temperature,
        audio.local_top_p,
        audio.local_min_p,
        audio.local_repetition_penalty,
        audio.local_engine,
    )
    persist_local_voice_settings()
    return jsonify({
        "status": "success",
        "prompt_path": str(target),
        "message": "Sample audio saved.",
        "local_tts_status": audio.local_status(),
    })

@app.route('/test_local_tts_voice', methods=['POST'])
def test_local_tts_voice_route():
    if not audio.local_model_loaded():
        return jsonify({
            "status": "needs_download",
            "message": "Download / load the local Chatterbox model before testing voice. First use may download several GB.",
            "local_tts_status": audio.local_status(),
        })
    threading.Thread(
        target=audio.generate_audio_for_text,
        args=("Local voice test.",),
        kwargs={"force": True},
        daemon=True,
    ).start()
    return jsonify({
        "status": "queued",
        "message": "Local voice test queued.",
        "local_tts_status": audio.local_status(),
    })

@app.route('/get_updates')
def get_ui_updates_route():
    messages = [messages_for_ui.popleft() for _ in range(len(messages_for_ui))]
    return jsonify({
        "messages": messages,
        "audio_ready": audio.has_audio(),
        "audio_error": audio.consume_last_error(),
    })

@app.route('/get_audio')
def get_audio_route():
    audio_chunk = audio.get_next_audio_chunk()
    if not audio_chunk:
        return ("", 204)
    return send_file(io.BytesIO(audio_chunk["bytes"]), mimetype=audio_chunk["mimetype"])

@app.route('/get_status')
def get_status_route():
    diagnostics = handy.diagnostics()
    motion_observability = motion.observability_snapshot(diagnostics)
    motion_observability["diagnostics_level"] = settings.motion_diagnostics_level
    return jsonify({
        "mood": current_mood,
        "speed": diagnostics["physical_speed"],
        "relative_speed": diagnostics["relative_speed"],
        "depth": diagnostics["depth"],
        "range": diagnostics["range"],
        "active_mode": auto_mode_active_task.name if auto_mode_active_task else "",
        "motion_diagnostics_level": settings.motion_diagnostics_level,
        "motion_training": _motion_training_snapshot(),
        "motion_observability": motion_observability,
    })

@app.route('/set_depth_limits', methods=['POST'])
def set_depth_limits_route():
    data = _request_json()
    depth1 = _request_int(data, 'min_depth', 5)
    depth2 = _request_int(data, 'max_depth', 100)
    settings.min_depth = min(depth1, depth2); settings.max_depth = max(depth1, depth2)
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    settings.save()
    return jsonify({"status": "success"})

@app.route('/set_speed_limits', methods=['POST'])
def set_speed_limits_route():
    data = _request_json()
    speed1 = _request_int(data, 'min_speed', 10)
    speed2 = _request_int(data, 'max_speed', 80)
    settings.min_speed = max(0, min(100, min(speed1, speed2)))
    settings.max_speed = max(0, min(100, max(speed1, speed2)))
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    settings.save()
    return jsonify({
        "status": "success",
        "min_speed": settings.min_speed,
        "max_speed": settings.max_speed,
    })

@app.route('/set_motion_backend', methods=['POST'])
def set_motion_backend_route():
    data = _request_json()
    settings.motion_backend = settings._normalize_motion_backend(data.get("motion_backend"))
    motion.set_backend(settings.motion_backend)
    settings.save()
    return jsonify({
        "status": "success",
        "motion_backend": settings.motion_backend,
    })

def _timing_pair(data, min_key, max_key, default_min, default_max):
    try:
        first = float(data.get(min_key, default_min))
        second = float(data.get(max_key, default_max))
    except (TypeError, ValueError):
        first, second = default_min, default_max
    first = max(1.0, min(60.0, first))
    second = max(1.0, min(60.0, second))
    return min(first, second), max(first, second)

@app.route('/set_mode_timings', methods=['POST'])
def set_mode_timings_route():
    data = _request_json()
    settings.auto_min_time, settings.auto_max_time = _timing_pair(data, 'auto_min', 'auto_max', 4.0, 7.0)
    settings.edging_min_time, settings.edging_max_time = _timing_pair(data, 'edging_min', 'edging_max', 5.0, 8.0)
    settings.milking_min_time, settings.milking_max_time = _timing_pair(data, 'milking_min', 'milking_max', 2.5, 4.5)
    settings.save()
    return jsonify({
        "status": "success",
        "timings": {
            "auto_min": settings.auto_min_time,
            "auto_max": settings.auto_max_time,
            "edging_min": settings.edging_min_time,
            "edging_max": settings.edging_max_time,
            "milking_min": settings.milking_min_time,
            "milking_max": settings.milking_max_time,
        },
    })

def _rate_last_live_motion_pattern(rating, source="chat feedback"):
    if rating not in {"thumbs_up", "neutral", "thumbs_down"}:
        return None
    if not last_live_motion_pattern_id:
        return None
    return _record_motion_pattern_feedback(last_live_motion_pattern_id, rating, source=source)

@app.route('/like_last_move', methods=['POST'])
def like_last_move_route():
    last_speed = handy.last_relative_speed; last_depth = handy.last_depth_pos
    pattern_name = llm.name_this_move(last_speed, last_depth, current_mood)
    sp_range = [max(0, last_speed - 5), min(100, last_speed + 5)]; dp_range = [max(0, last_depth - 5), min(100, last_depth + 5)]
    new_pattern = {"name": pattern_name, "sp_range": [int(p) for p in sp_range], "dp_range": [int(p) for p in dp_range], "moods": [current_mood], "score": 1}
    settings.session_liked_patterns.append(new_pattern)
    result = _rate_last_live_motion_pattern("thumbs_up", source="chat thumbs up")
    add_message_to_queue(f"(I'll remember that you like '{pattern_name}')", add_to_history=False)
    response = {"status": "boosted", "name": pattern_name}
    if result:
        response.update({
            "pattern": _motion_pattern_summary(result["pattern"]),
            "motion_patterns": result["motion_patterns"],
            "motion_preferences": result["motion_preferences"],
        })
    return jsonify(response)

@app.route('/dislike_last_move', methods=['POST'])
def dislike_last_move_route():
    result = _rate_last_live_motion_pattern("thumbs_down", source="chat thumbs down")
    if not result:
        return jsonify({
            "status": "no_pattern",
            "message": "No fixed motion pattern is active to rate.",
            "motion_preferences": _motion_preference_payload(),
        })
    pattern = result["pattern"]
    message = f"Saved thumbs down feedback for {pattern.name}."
    if result["auto_disabled"]:
        message += f" Disabled after {THUMBS_DOWN_DISABLE_THRESHOLD} thumbs down ratings."
    add_message_to_queue(f"({message})", add_to_history=False)
    return jsonify({
        "status": "success",
        "message": message,
        "pattern": _motion_pattern_summary(pattern),
        "motion_patterns": result["motion_patterns"],
        "motion_preferences": result["motion_preferences"],
        "auto_disabled": result["auto_disabled"],
    })

@app.route('/motion_feedback/last', methods=['POST'])
def rate_last_motion_pattern_route():
    data = _request_json()
    rating = str(data.get("rating", "")).strip().lower()
    result = _rate_last_live_motion_pattern(rating, source="chat feedback")
    if not result:
        return jsonify({"status": "error", "message": "No fixed motion pattern is active to rate."}), 400
    pattern = result["pattern"]
    return jsonify({
        "status": "success",
        "pattern": _motion_pattern_summary(pattern),
        "motion_patterns": result["motion_patterns"],
        "motion_preferences": result["motion_preferences"],
        "auto_disabled": result["auto_disabled"],
    })

@app.route('/start_edging_mode', methods=['POST'])
def start_edging_route():
    start_background_mode(edging_mode_logic, "Let's play an edging game...", mode_name='edging')
    return jsonify({"status": "edging_started"})

@app.route('/start_milking_mode', methods=['POST'])
def start_milking_route():
    start_background_mode(milking_mode_logic, "You're so close... I'm taking over completely now.", mode_name='milking')
    return jsonify({"status": "milking_started"})

@app.route('/stop_auto_mode', methods=['POST'])
def stop_auto_route():
    if auto_mode_active_task: auto_mode_active_task.stop()
    return jsonify({"status": "auto_mode_stopped"})

# ─── APP STARTUP ───────────────────────────────────────────────────────────────────────────────────
def on_exit():
    print("[INFO] Saving settings on exit...")
    settings.save(llm, chat_history)
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
