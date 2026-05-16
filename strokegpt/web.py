import os
import sys
import json
import re
import atexit
import socket
import threading
import time
import types
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import Flask, Response, request, jsonify, render_template_string, send_from_directory, stream_with_context
from werkzeug.utils import secure_filename

from .app_state import APP_STATE_EXPORTS, AppState
from .settings import SettingsManager, normalize_ollama_model
from .handy import HandyController
from .llm import LLMService
from .audio import AudioService
from .asr import VoiceInputService
from .diagnostics import (
    diagnostics_latency_payload as build_diagnostics_latency_payload,
    diagnostics_system_status_payload as build_diagnostics_system_status_payload,
)
from .server_tls import ServerTlsError, resolve_server_tls
from .background_modes import AutoModeThread, auto_mode_logic, milking_mode_logic, edging_mode_logic, freestyle_mode_logic
from .mode_contracts import FreestyleCandidate, ModeCallbacks, ModeLogic, ModeServices
from .motion import IntentMatcher, MotionController, MotionTarget
from .motion_patterns import PATTERNS, PatternFrame
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
from .program_library import MAX_PROGRAM_IMPORT_BYTES, ProgramLibrary, ProgramValidationError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VOICE_SAMPLE_DIR = PROJECT_ROOT / "voice_samples"
USER_DATA_DIR = PROJECT_ROOT / "user_data"
VOICE_INPUT_UPLOAD_DIR = USER_DATA_DIR / "voice_input"
VOICE_INPUT_MODEL_DIR = USER_DATA_DIR / "voice_input_hf_cache"
DIAGNOSTICS_DIR = USER_DATA_DIR / "diagnostics"
MOTION_PATTERN_DIR = USER_DATA_DIR / "patterns"
MOTION_PROGRAM_DIR = USER_DATA_DIR / "programs"
HTTPS_CERT_DIR = USER_DATA_DIR / "https"
ALLOWED_VOICE_SAMPLE_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
ALLOWED_VOICE_INPUT_EXTENSIONS = {".webm", ".wav", ".mp3", ".ogg", ".m4a", ".aac", ".flac"}
ALLOWED_VOICE_INPUT_MIMETYPES = {
    "audio/aac",
    "audio/flac",
    "audio/m4a",
    "audio/mp3",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "video/webm",
}
MAX_VOICE_INPUT_BYTES = 12_000_000
MAX_PATTERN_IMPORT_BYTES = 1_000_000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
MOTION_FEEDBACK_HISTORY_LIMIT = 20
STANDALONE_AUTOSPEAK_WAKE_FLOOR_SECONDS = 8.0


@dataclass(frozen=True)
class HttpsTrustHelper:
    server: ThreadingHTTPServer
    thread: threading.Thread
    port: int
    cert_url: str
    info_url: str


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


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


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


def _server_url(scheme, host, port):
    return f"{scheme}://{_display_host(host)}:{port}"


def _external_url_hint(scheme, host, port):
    display_host = "<PC-LAN-IP>" if host in {"0.0.0.0", "::"} else _display_host(host)
    return f"{scheme}://{display_host}:{port}"


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception as exc:
        print(f"[WARN] Could not open browser automatically: {exc}")


def _start_https_trust_helper(host, https_port, trust_cert_path):
    if not trust_cert_path or not _env_flag("STROKEGPT_HTTPS_CERT_HELPER", default=True):
        return None
    trust_cert_path = Path(trust_cert_path)
    if not trust_cert_path.is_file():
        return None

    cert_bytes = trust_cert_path.read_bytes()
    cert_name = trust_cert_path.name
    requested_port = _env_int("STROKEGPT_HTTPS_CERT_PORT", min(https_port + 1, 65535))
    helper_port = _select_bind_port(host, requested_port)

    class TrustCertificateHandler(BaseHTTPRequestHandler):
        server_version = "StrokeGPTTrustHelper/1.0"

        def do_GET(self):
            path = urlparse(self.path).path
            if path in {"", "/"}:
                body = (
                    "<!doctype html><title>StrokeGPT HTTPS certificate</title>"
                    "<h1>StrokeGPT HTTPS certificate</h1>"
                    f"<p>Install this local CA certificate on Android, then open "
                    f"the StrokeGPT HTTPS LAN URL again.</p>"
                    f'<p><a href="/{cert_name}">Download {cert_name}</a></p>'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path in {f"/{cert_name}", "/ca.crt"}:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-x509-ca-cert")
                self.send_header("Content-Disposition", f'attachment; filename="{cert_name}"')
                self.send_header("Content-Length", str(len(cert_bytes)))
                self.end_headers()
                self.wfile.write(cert_bytes)
                return
            self.send_error(404)

        def log_message(self, format, *args):
            print(f"[CERT-HELPER] {self.address_string()} - {format % args}")

    try:
        server = ThreadingHTTPServer((host, helper_port), TrustCertificateHandler)
    except OSError as exc:
        print(f"[WARN] HTTPS certificate helper could not start: {exc}")
        return None
    thread = threading.Thread(target=server.serve_forever, name="https-cert-helper", daemon=True)
    thread.start()
    cert_url = f"{_external_url_hint('http', host, helper_port)}/{cert_name}"
    info_url = _external_url_hint("http", host, helper_port)
    return HttpsTrustHelper(server=server, thread=thread, port=helper_port, cert_url=cert_url, info_url=info_url)


def _stop_https_trust_helper(helper):
    helper.server.shutdown()
    helper.server.server_close()


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

handy = HandyController(
    settings.handy_key,
    api_v3_key=settings.handy_api_v3_key,
    firmware_version=settings.handy_firmware_version,
)
handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
motion = MotionController(handy)
intent_matcher = IntentMatcher()
motion_pattern_library = PatternLibrary(MOTION_PATTERN_DIR)
motion_program_library = ProgramLibrary(MOTION_PROGRAM_DIR)
motion_transport_capture_session = None

ollama_model = normalize_ollama_model(os.getenv("STROKEGPT_OLLAMA_MODEL", settings.ollama_model)) or settings.ollama_model
llm = LLMService(
    url=LLM_URL,
    model=ollama_model,
    thinking_enabled=settings.ollama_thinking_enabled,
)
llm.set_custom_prompt_set(settings.selected_llm_custom_prompt_set())
audio = AudioService()
voice_input = VoiceInputService(model_cache_dir=VOICE_INPUT_MODEL_DIR)
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
voice_input.configure(
    provider=settings.voice_input_provider,
    enabled=settings.voice_input_enabled,
    model=settings.voice_input_model,
    language=settings.voice_input_language,
    mode=settings.voice_input_mode,
    submit_mode=settings.voice_input_submit_mode,
    hands_free_sensitivity=settings.voice_input_hands_free_sensitivity,
    hands_free_silence_ms=settings.voice_input_hands_free_silence_ms,
    min_recording_ms=settings.voice_input_min_recording_ms,
    max_recording_ms=settings.voice_input_max_recording_ms,
    noise_suppression=settings.voice_input_noise_suppression,
    echo_cancellation=settings.voice_input_echo_cancellation,
    auto_gain_control=settings.voice_input_auto_gain_control,
    noise_floor_rms=settings.voice_input_noise_floor_rms,
    audio_preprocessing=settings.voice_input_audio_preprocessing,
    silence_trim=settings.voice_input_silence_trim,
    beam_size=settings.voice_input_beam_size,
    condition_on_previous_text=settings.voice_input_condition_on_previous_text,
    vad_threshold=settings.voice_input_vad_threshold,
    vad_min_silence_ms=settings.voice_input_vad_min_silence_ms,
    vad_speech_pad_ms=settings.voice_input_vad_speech_pad_ms,
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

def _ollama_running_models():
    response = requests.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=0.5)
    response.raise_for_status()
    data = response.json()
    models = []
    for item in data.get("models", []):
        name = normalize_ollama_model(item.get("model") or item.get("name") or "")
        if not name:
            continue
        size = int(item.get("size") or 0)
        size_vram_reported = "size_vram" in item
        size_vram = int(item.get("size_vram") or 0)
        models.append({
            "name": name,
            "size": size,
            "size_label": _format_bytes(size),
            "size_vram": size_vram,
            "size_vram_label": _format_bytes(size_vram),
            "size_vram_reported": size_vram_reported,
            "processor": str(item.get("processor") or item.get("processor_label") or "").strip(),
        })
    models.sort(key=lambda item: item["name"].lower())
    return models


def _ollama_load_model_for_status(model):
    model = normalize_ollama_model(model)
    if not model:
        return {"ok": False, "error": "Model name is required."}
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": "5m",
            "options": {"num_predict": 0},
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "ok": True,
        "model": normalize_ollama_model(data.get("model") or model),
        "done_reason": data.get("done_reason") or "",
    }


def _ollama_status_payload(live=True):
    # Service-bound adapter for ``payloads.ollama_status_payload()``: binds the
    # live ``settings``/``llm`` services and the local pull/installation helpers
    # so blueprint routes (and tests via ``mock.patch`` on the canonical
    # ``strokegpt.payloads.ollama_status_payload``) can reuse one entry point.
    # Do not add new ``web.*`` payload wrappers; extend ``strokegpt.payloads``
    # instead and bind services here.
    if not live:
        return payloads.ollama_status_pending_payload(
            settings=settings,
            llm=llm,
            base_url=OLLAMA_BASE_URL,
            pull_snapshot=_ollama_pull_snapshot,
        )
    return payloads.ollama_status_payload(
        settings=settings,
        llm=llm,
        base_url=OLLAMA_BASE_URL,
        pull_snapshot=_ollama_pull_snapshot,
        installed_models=_ollama_installed_models,
        running_models=_ollama_running_models,
        load_model_for_status=_ollama_load_model_for_status,
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

def settings_payload(*, include_live_ollama_status=True, include_motion_preferences=True):
    # Service-bound adapter for ``payloads.settings_payload()``: bundles the
    # runtime ``settings``/``llm``/``audio`` services and composed helpers so
    # blueprint routes can fetch the full settings dialog payload in one call.
    # Do not add new ``web.*`` payload wrappers; extend ``strokegpt.payloads``
    # instead and bind services here.
    return payloads.settings_payload(
        settings=settings,
        llm=llm,
        audio=audio,
        use_long_term_memory=app_state.use_long_term_memory,
        persona_prompts=get_persona_prompts_for_ui(),
        ollama_models=get_ollama_models_for_ui(),
        ollama_status=_ollama_status_payload(live=include_live_ollama_status),
        motion_patterns=_motion_pattern_catalog_payload(),
        motion_programs=motion_program_library.catalog(),
        motion_preferences=_motion_preference_payload() if include_motion_preferences else None,
        diagnostics_levels=_diagnostics_level_options(),
        voice_input_status=voice_input_status_payload(),
    )

def voice_input_status_payload(status="success"):
    payload = voice_input.status()
    payload["status"] = status
    payload["hands_free_mode_actions"] = bool(settings.voice_input_hands_free_mode_actions)
    return payload

def setup_check_payload():
    return payloads.setup_check_payload(
        configured=bool(settings.handy_key and settings.min_depth < settings.max_depth),
        handy_key=settings.handy_key,
        ollama_status=_ollama_status_payload(),
        voice_input_setup=voice_input.setup_status(),
        local_tts_status=audio.local_status(),
        audio_provider=settings.audio_provider,
        audio_enabled=settings.audio_enabled,
        elevenlabs_key=settings.elevenlabs_api_key,
    )

def diagnostics_latency_payload():
    return build_diagnostics_latency_payload(
        base_url=OLLAMA_BASE_URL,
        llm_url=LLM_URL,
        llm=llm,
        voice_input=voice_input,
        audio=audio,
        diagnostics_dir=DIAGNOSTICS_DIR,
        ollama_status=_ollama_status_payload,
    )


def diagnostics_system_status_payload():
    return build_diagnostics_system_status_payload(
        settings=settings,
        llm=llm,
        audio=audio,
        voice_input=voice_input,
        ollama_status=_ollama_status_payload,
        app_state=app_state,
        motion=motion,
    )


def _motion_transport_run_settings():
    return {
        "backend": motion.backend,
        "firmware": settings.handy_firmware_version,
        "api_v3_key_configured": bool(settings.handy_api_v3_key),
        "min_speed": settings.min_speed,
        "max_speed": settings.max_speed,
        "min_depth": settings.min_depth,
        "max_depth": settings.max_depth,
        "motion_style": settings.motion_style,
        "motion_reverse_direction": settings.motion_reverse_direction,
        "active_mode": app_state.active_mode_name,
    }


def _motion_transport_snapshot():
    diagnostics = handy.diagnostics()
    observability = motion.observability_snapshot(diagnostics)
    handy_diagnostics = dict(diagnostics)
    command_history = list(handy_diagnostics.pop("command_history", []) or [])
    return {
        "captured_at": time.time(),
        "run": _motion_transport_run_settings(),
        "motion": {
            "backend": observability.get("backend"),
            "source": observability.get("source"),
            "label": observability.get("label"),
            "playback_active": bool(observability.get("playback_active")),
            "last_command_time": observability.get("last_command_time"),
        },
        "handy_diagnostics": handy_diagnostics,
        "motion_trace": list(observability.get("trace") or []),
        "handy_command_history": command_history,
    }


def _motion_transport_summary(motion_trace, command_history, diagnostics=None):
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    paths = [str(command.get("path") or "") for command in command_history if isinstance(command, dict)]
    path_counts = {}
    for path in paths:
        path_counts[path] = path_counts.get(path, 0) + 1

    hsp_count = sum(count for path, count in path_counts.items() if path.startswith("hsp/"))
    hdsp_count = sum(count for path, count in path_counts.items() if path.startswith("hdsp/"))
    hamp_count = sum(
        count
        for path, count in path_counts.items()
        if path.startswith("hamp/") or path in {"slide", "mode", "mode2"}
    )
    failed_count = sum(
        1
        for command in command_history
        if isinstance(command, dict) and command.get("ok") is False
    )
    schemas = sorted(
        {
            str(point.get("continuous_schema"))
            for point in motion_trace
            if isinstance(point, dict) and point.get("continuous_schema")
        }
    )

    if failed_count:
        status = "error"
        message = f"Captured {failed_count} failed Handy command(s)."
    elif hsp_count:
        status = "ok"
        message = "Captured HSP timed-point transport."
    elif hdsp_count:
        status = "warning"
        reason = diagnostics.get("api_v3_unavailable_reason")
        if reason == "missing_api_v3_key":
            message = "Captured HDSP fallback because no Handy API v3 Application ID is configured."
        elif reason == "api_v3_auth_failed":
            auth_path = diagnostics.get("api_v3_auth_failed_path") or "API v3"
            auth_error = diagnostics.get("api_v3_auth_error") or "authentication failed"
            message = f"Captured HDSP fallback because {auth_path} failed API v3 auth: {auth_error}."
        elif reason:
            message = f"Captured HDSP fallback because HSP is unavailable: {reason}."
        else:
            message = "Captured HDSP position transport; HSP was not used in this capture."
    elif hamp_count:
        status = "warning"
        message = "Captured HAMP or mode/slide commands; continuous HSP was not used."
    elif motion_trace:
        status = "warning"
        message = "Captured motion trace rows but no Handy command history."
    else:
        status = "warning"
        message = "No motion commands were captured."

    return {
        "status": status,
        "message": message,
        "trace_rows": len(motion_trace),
        "command_rows": len(command_history),
        "path_counts": path_counts,
        "hsp_commands": hsp_count,
        "hdsp_commands": hdsp_count,
        "hamp_or_mode_commands": hamp_count,
        "failed_commands": failed_count,
        "continuous_schemas": schemas,
        "api_v3_enabled": bool(diagnostics.get("api_v3_enabled")),
        "api_v3_key_configured": bool(diagnostics.get("api_v3_key_configured")),
        "api_v3_auth_failed": bool(diagnostics.get("api_v3_auth_failed")),
        "api_v3_unavailable_reason": diagnostics.get("api_v3_unavailable_reason") or "",
    }


def _slice_from_index(items, start_index):
    try:
        start = max(0, int(start_index))
    except (TypeError, ValueError):
        start = 0
    if start > len(items):
        start = 0
    return items[start:]


def motion_transport_capture_payload(action="snapshot"):
    global motion_transport_capture_session

    action = str(action or "snapshot").strip().lower()
    snapshot = _motion_transport_snapshot()

    if action == "start":
        with app_state.lock:
            motion_transport_capture_session = {
                "started_at": snapshot["captured_at"],
                "trace_count": len(snapshot["motion_trace"]),
                "command_count": len(snapshot["handy_command_history"]),
                "before": snapshot,
            }
        return {
            "status": "started",
            "message": "Motion transport capture started.",
            "active": True,
            "capture": {
                "started_at": snapshot["captured_at"],
                "run": snapshot["run"],
                "before": snapshot["handy_diagnostics"],
                "summary": {
                    "status": "info",
                    "message": "Run motion now, then stop the capture.",
                    "trace_rows": 0,
                    "command_rows": 0,
                    "path_counts": {},
                    "hsp_commands": 0,
                    "hdsp_commands": 0,
                    "hamp_or_mode_commands": 0,
                    "failed_commands": 0,
                    "continuous_schemas": [],
                },
            },
        }

    if action == "cancel":
        with app_state.lock:
            motion_transport_capture_session = None
        return {
            "status": "success",
            "message": "Motion transport capture cleared.",
            "active": False,
        }

    with app_state.lock:
        session = motion_transport_capture_session
        if action == "finish":
            motion_transport_capture_session = None

    if action == "finish" and session:
        motion_trace = _slice_from_index(snapshot["motion_trace"], session.get("trace_count", 0))
        command_history = _slice_from_index(snapshot["handy_command_history"], session.get("command_count", 0))
        capture = {
            "started_at": session.get("started_at"),
            "finished_at": snapshot["captured_at"],
            "run": snapshot["run"],
            "before": session.get("before", {}).get("handy_diagnostics", {}),
            "after": snapshot["handy_diagnostics"],
            "motion": snapshot["motion"],
            "motion_trace": motion_trace,
            "handy_command_history": command_history,
        }
        capture["summary"] = _motion_transport_summary(motion_trace, command_history, capture["after"])
        return {
            "status": "success",
            "message": capture["summary"]["message"],
            "active": False,
            "capture": capture,
        }

    capture = {
        "started_at": snapshot["captured_at"],
        "finished_at": snapshot["captured_at"],
        "run": snapshot["run"],
        "after": snapshot["handy_diagnostics"],
        "motion": snapshot["motion"],
        "motion_trace": snapshot["motion_trace"],
        "handy_command_history": snapshot["handy_command_history"],
    }
    capture["summary"] = _motion_transport_summary(
        capture["motion_trace"],
        capture["handy_command_history"],
        capture["after"],
    )
    return {
        "status": "success",
        "message": capture["summary"]["message"],
        "active": bool(motion_transport_capture_session),
        "capture": capture,
    }


def apply_settings_to_services():
    handy.set_api_key(settings.handy_key)
    handy.set_firmware_version(settings.handy_firmware_version)
    handy.set_handy_api_key(settings.handy_api_v3_key)
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    motion.set_backend(settings.motion_backend)
    motion.set_reverse_direction(settings.motion_reverse_direction)
    llm.set_model(settings.ollama_model)
    llm.set_thinking_enabled(settings.ollama_thinking_enabled)
    llm.set_custom_prompt_set(settings.selected_llm_custom_prompt_set())

    audio.set_provider(settings.audio_provider, settings.audio_enabled)
    voice_input.configure(
        provider=settings.voice_input_provider,
        enabled=settings.voice_input_enabled,
        model=settings.voice_input_model,
        language=settings.voice_input_language,
        mode=settings.voice_input_mode,
        submit_mode=settings.voice_input_submit_mode,
        hands_free_sensitivity=settings.voice_input_hands_free_sensitivity,
        hands_free_silence_ms=settings.voice_input_hands_free_silence_ms,
        min_recording_ms=settings.voice_input_min_recording_ms,
        max_recording_ms=settings.voice_input_max_recording_ms,
        noise_suppression=settings.voice_input_noise_suppression,
        echo_cancellation=settings.voice_input_echo_cancellation,
        auto_gain_control=settings.voice_input_auto_gain_control,
        noise_floor_rms=settings.voice_input_noise_floor_rms,
        audio_preprocessing=settings.voice_input_audio_preprocessing,
        silence_trim=settings.voice_input_silence_trim,
        beam_size=settings.voice_input_beam_size,
        condition_on_previous_text=settings.voice_input_condition_on_previous_text,
        vad_threshold=settings.voice_input_vad_threshold,
        vad_min_silence_ms=settings.voice_input_vad_min_silence_ms,
        vad_speech_pad_ms=settings.voice_input_vad_speech_pad_ms,
    )
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
    # Service-bound adapter for ``payloads.motion_pattern_catalog_payload()``:
    # binds the live ``motion_pattern_library`` and ``settings`` so blueprint
    # routes can compose the catalog without rethreading services. Do not add
    # new ``web.*`` payload wrappers; extend ``strokegpt.payloads`` instead and
    # bind services here.
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

def _motion_program_catalog_payload():
    return motion_program_library.catalog()

def _motion_program_record(program_id):
    return motion_program_library.get_record(program_id)

def _motion_pattern_summary(record, include_actions=False):
    # Service-bound adapter for ``payloads.motion_pattern_summary()``: binds
    # the live ``settings.motion_pattern_weights`` so internal feedback-history
    # appenders can summarize a record without threading the override map.
    # Blueprint routes call ``payloads.motion_pattern_summary`` directly via
    # the local ``_pattern_summary(web, ...)`` helper and do not need this
    # wrapper. Do not add new ``web.*`` payload wrappers; extend
    # ``strokegpt.payloads`` instead and bind services here.
    return payloads.motion_pattern_summary(
        record,
        settings.motion_pattern_weights,
        include_actions=include_actions,
    )

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
    if (
        (context.get("mode_actions_enabled") or context.get("handsfree_mode_actions_enabled"))
        and _normalize_llm_mode_action(response.get("mode_action"))
    ):
        return response, False
    target = _target_from_llm_response_move(response, current)
    if context.get("autospeak_event") and not _chat_claims_motion_change(response.get("chat")):
        return response, False
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
            entry["weight"] = payloads.motion_pattern_summary(
                updated_pattern, settings.motion_pattern_weights
            ).get("weight", 50)
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

def _training_target_for_record(record, current=None):
    current = current or motion.current_target()
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

def _training_preserves_pattern_timing(record):
    return str(getattr(record, "source", "") or "").lower() in {"imported", "trained", "user"}

def _target_for_program_action(action, base_target, speed, label):
    base_target = base_target.clamped()
    stroke_range = base_target.stroke_range if base_target.stroke_range >= 5 else 50
    half_range = stroke_range / 2.0
    shallow = max(0.0, min(100.0, base_target.depth - half_range))
    deep = max(0.0, min(100.0, base_target.depth + half_range))
    if deep - shallow < 5:
        shallow = max(0.0, min(100.0, base_target.depth - 2.5))
        deep = max(0.0, min(100.0, base_target.depth + 2.5))
    position = max(0.0, min(100.0, float(action.pos))) / 100.0
    depth = shallow + ((deep - shallow) * position)
    return MotionTarget(
        speed=speed,
        depth=depth,
        stroke_range=stroke_range,
        label=label,
    ).clamped()

def _program_playback_frames(record, *, start_ms=None, end_ms=None):
    actions = record.section_actions(start_ms, end_ms)
    if len(actions) < 2:
        return []
    current = motion.current_target()
    speed = current.speed if current.speed > 0 else 35
    if settings.min_speed >= settings.max_speed:
        speed = max(10, min(45, speed))
    step_delay = max(0.01, float(getattr(motion, "step_delay", 0.25) or 0.25))
    frames = []
    previous_at = None
    for action in actions:
        interval_seconds = 0.0 if previous_at is None else max(0.001, (action.at - previous_at) / 1000.0)
        frames.append(PatternFrame(
            _target_for_program_action(action, current, speed, f"program {record.program_id}"),
            delay_factor=interval_seconds / step_delay,
            phase="timed-pattern",
        ))
        previous_at = action.at
    return frames

def _program_section_message(record, start_ms=None, end_ms=None):
    lower, upper = record.section_bounds(start_ms, end_ms)
    if lower <= 0 and upper >= record.duration_ms:
        return record.name
    return f"{record.name} section {round(lower / 1000, 1)}-{round(upper / 1000, 1)}s"

def _run_motion_training_pattern(record, *, preview=False):
    try:
        current = motion.current_target()
        target = _training_target_for_record(record, current)
        _set_motion_training_state(
            state="playing",
            pattern_id=record.pattern_id,
            pattern_name=record.name,
            message=f"Playing {'edited preview' if preview else record.name}.",
            preview=preview,
        )
        completed = motion.apply_motion_pattern(
            record.to_motion_pattern(),
            target,
            preserve_timing=_training_preserves_pattern_timing(record),
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

def _run_motion_program(record, *, start_ms=None, end_ms=None):
    section_name = _program_section_message(record, start_ms, end_ms)
    try:
        frames = _program_playback_frames(record, start_ms=start_ms, end_ms=end_ms)
        if not frames:
            _set_motion_training_state(
                state="error",
                pattern_id=record.program_id,
                pattern_name=section_name,
                message=f"Program {section_name} has no playable frames.",
                preview=True,
            )
            return
        _set_motion_training_state(
            state="playing",
            pattern_id=record.program_id,
            pattern_name=section_name,
            message=f"Playing {section_name}.",
            preview=True,
        )
        completed = motion.apply_position_frames(
            frames,
            stop_after=True,
            source="program playback",
        )
        if app_state.motion_training_stop_event.is_set():
            _set_motion_training_state(
                state="stopped",
                pattern_id=record.program_id,
                pattern_name=section_name,
                message=f"Stopped {section_name}.",
                preview=True,
            )
        elif not completed:
            _set_motion_training_state(
                state="stopped",
                pattern_id=record.program_id,
                pattern_name=section_name,
                message=f"Interrupted {section_name}.",
                preview=True,
            )
        else:
            _set_motion_training_state(
                state="idle",
                pattern_id=record.program_id,
                pattern_name=section_name,
                message=f"Finished {section_name}.",
                preview=True,
            )
    except Exception as exc:
        _set_motion_training_state(
            state="error",
            pattern_id=record.program_id,
            pattern_name=section_name,
            message=f"Program playback failed: {exc}",
            preview=True,
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

def _start_motion_program_record(record, *, start_ms=None, end_ms=None):
    if not handy.handy_key:
        return jsonify({"status": "error", "message": "Set a Handy connection key before playing Programs."}), 400
    if app_state.auto_mode_active_task:
        return jsonify({"status": "error", "message": "Stop the active mode before playing a Program."}), 409
    section_name = _program_section_message(record, start_ms, end_ms)

    with app_state.lock:
        if app_state.motion_training_thread and app_state.motion_training_thread.is_alive():
            return jsonify({"status": "error", "message": "A motion training pattern or Program is already playing."}), 409
        app_state.motion_training_stop_event.clear()
        app_state.motion_training_state.update({
            "state": "starting",
            "pattern_id": record.program_id,
            "pattern_name": section_name,
            "message": f"Starting {section_name}.",
            "preview": True,
        })
        app_state.motion_training_thread = threading.Thread(
            target=_run_motion_program,
            args=(record,),
            kwargs={"start_ms": start_ms, "end_ms": end_ms},
            daemon=True,
        )
        app_state.motion_training_thread.start()
        snapshot = dict(app_state.motion_training_state)
    return jsonify({"status": "started", "motion_training": snapshot})

def _save_motion_program_section_pattern(record, data):
    name = str(data.get("name") or "").strip()
    payload = record.section_pattern_payload(
        data.get("start_ms"),
        data.get("end_ms"),
        name=name,
    )
    filename_source = name or payload.get("id") or payload.get("name") or "program-section"
    filename = secure_filename(f"{filename_source}.json")
    return motion_pattern_library.import_payload(
        payload,
        filename=filename,
        source_override="trained",
    )

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
        app_state.mode_status_message = ""
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
        active_mode_name = _active_mode_name()
    context = {
        'persona_desc': settings.persona_desc, 'current_mood': current_mood,
        'user_profile': settings.user_profile, 'patterns': settings.patterns,
        'llm_prompt_mode': settings.llm_prompt_mode,
        'user_genitalia': settings.user_genitalia,
        'user_genitalia_custom': settings.user_genitalia_custom,
        'motion_preferences': _motion_preference_payload()["prompt"],
        'motion_style': settings.motion_style,
        'motion_reverse_direction': settings.motion_reverse_direction,
        'rules': settings.rules, 'last_stroke_speed': handy.last_relative_speed,
        'last_depth_pos': handy.last_depth_pos, 'last_stroke_range': handy.last_stroke_range,
        'min_speed': settings.min_speed, 'max_speed': settings.max_speed,
        'use_long_term_memory': use_long_term_memory,
        'allow_llm_edge_in_chat': settings.allow_llm_edge_in_chat,
        'allow_llm_edge_in_freestyle': settings.allow_llm_edge_in_freestyle,
        'autospeak_enabled': settings.autospeak_enabled,
        'autospeak_min_seconds': settings.autospeak_min_seconds,
        'autospeak_max_seconds': settings.autospeak_max_seconds,
        'active_mode': active_mode_name,
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

def _is_llm_transport_error_text(text):
    clean = str(text or "").strip().lower()
    return clean.startswith(("llm connection error:", "llm request failed:"))

def add_message_to_queue(text, add_to_history=True, queue_message=True, generate_audio=True, streamed_to_client=False):
    if queue_message:
        app_state.messages_for_ui.append(text)
    if add_to_history:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text:
            app_state.chat_history.append({"role": "assistant", "content": clean_text})
    if generate_audio:
        # Bug-triage diagnostic for KNOWN_PROBLEMS
        # "Local LLM Chat Text Sometimes Missing While Voice Plays". The
        # chat-emit path (queue_message + messages_for_ui) and the
        # TTS-enqueue path (generate_audio) should run in lockstep for any
        # user-visible reply. If we are spawning a TTS payload without a
        # matching chat-emit, log it so the missing-line case is easy to
        # reproduce and triage. Two divergence shapes:
        #   1. queue_message=False: caller intentionally enqueued TTS
        #      without queuing a chat bubble. No production caller does this
        #      today, so a hit suggests a regression or a new caller that
        #      forgot the chat side.
        #   2. text strips to empty: a chat bubble would render blank and
        #      the front-end may visibly drop it; the TTS layer ignores
        #      empty text downstream so the user hears nothing either, but
        #      the divergence is still worth surfacing.
        clean_for_log = re.sub(r'<[^>]+>', '', str(text or "")).strip()
        warning_for_ui = ""
        if not queue_message and not streamed_to_client:
            print(
                f"[WARN] TTS enqueued without chat-emit "
                f"(queue_message=False, text_len={len(clean_for_log)}, "
                f"preview={clean_for_log[:60]!r})"
            )
            warning_for_ui = (
                "Voice output was queued without a matching chat message. "
                "Check the app terminal for the TTS/chat path warning."
            )
        elif not clean_for_log:
            print(
                f"[WARN] TTS enqueued with empty chat text; UI bubble "
                f"will render blank (raw_text={text!r})"
            )
            warning_for_ui = (
                "Voice output was requested with empty chat text. "
                "Check the local model response and app terminal."
            )
        if warning_for_ui:
            with app_state.lock:
                app_state.chat_audio_warning = warning_for_ui
        threading.Thread(target=audio.generate_audio_for_text, args=(text,), daemon=True).start()

def add_mode_status_message(text):
    clean_text = re.sub(r'<[^>]+>', '', str(text or "")).strip()
    if not clean_text:
        return
    with app_state.lock:
        app_state.mode_status_message = clean_text


def _autospeak_timing_pair():
    return settings._autospeak_timing_pair(
        settings.autospeak_min_seconds,
        settings.autospeak_max_seconds,
    )


def _coerce_autospeak_delay(value=None):
    min_seconds, max_seconds = _autospeak_timing_pair()
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = max_seconds
    return max(min_seconds, min(max_seconds, seconds))


def _cancel_standalone_autospeak():
    with app_state.lock:
        app_state.autospeak_generation += 1
        app_state.autospeak_thread = None


def _standalone_autospeak_current(token):
    with app_state.lock:
        return (
            token == app_state.autospeak_generation
            and bool(settings.autospeak_enabled)
            and app_state.auto_mode_active_task is None
        )


def _standalone_autospeak_user_message():
    min_seconds, max_seconds = _autospeak_timing_pair()
    return (
        "Autospeak is due. Keep the conversation going with one short "
        "in-character chat line. Use move:null when no motion change is "
        "needed, or include move only if you deliberately want to change "
        "motion. Choose autospeak_seconds between "
        f"{min_seconds:g} and {max_seconds:g}. If the range allows 0, "
        "0 means the shortest natural pause, not an immediate loop."
    )


def _run_standalone_autospeak_turn(token):
    if not _standalone_autospeak_current(token):
        return False
    with app_state.lock:
        history_snapshot = list(app_state.chat_history)
    if not history_snapshot or not handy.handy_key:
        return False

    context = get_current_context()
    context["autospeak_event"] = True
    current_before_llm = motion.current_target()
    autospeak_user_input = _standalone_autospeak_user_message()
    messages = history_snapshot + [{"role": "user", "content": autospeak_user_input}]
    request_started = time.perf_counter()
    timings = {}
    try:
        llm_started = time.perf_counter()
        llm_response = llm.get_chat_response(messages, context, temperature=0.35)
        timings["llm_ms"] = int((time.perf_counter() - llm_started) * 1000)
    except Exception as exc:
        timings["llm_ms"] = int((time.perf_counter() - llm_started) * 1000) if "llm_started" in locals() else 0
        print(f"[ERROR] Autospeak LLM request failed: {exc}")
        llm_response = {
            "chat": f"LLM request failed: {exc}",
            "move": None,
            "new_mood": None,
        }

    if not _standalone_autospeak_current(token):
        return False

    _finalize_llm_chat_response(
        user_input=autospeak_user_input,
        llm_response=llm_response,
        context=context,
        current_before_llm=current_before_llm,
        request_started=request_started,
        timings=timings,
    )
    return True


def _standalone_autospeak_worker(token, wait_seconds):
    wait_seconds = max(STANDALONE_AUTOSPEAK_WAKE_FLOOR_SECONDS, float(wait_seconds or 0.0))
    time.sleep(wait_seconds)
    _run_standalone_autospeak_turn(token)


def _schedule_standalone_autospeak(delay_seconds=None):
    if not settings.autospeak_enabled or app_state.auto_mode_active_task or not handy.handy_key:
        return False
    delay_seconds = _coerce_autospeak_delay(delay_seconds)
    with app_state.lock:
        if not app_state.chat_history:
            return False
        app_state.autospeak_generation += 1
        token = app_state.autospeak_generation
    thread = threading.Thread(
        target=_standalone_autospeak_worker,
        args=(token, delay_seconds),
        daemon=True,
        name="autospeak-chat-loop",
    )
    with app_state.lock:
        app_state.autospeak_thread = thread
    thread.start()
    return True


def start_background_mode(mode_logic: ModeLogic, initial_message, mode_name):
    _cancel_standalone_autospeak()
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
    def consume_autospeak_wake() -> bool:
        with app_state.lock:
            requested = bool(app_state.autospeak_wake_requested)
            app_state.autospeak_wake_requested = False
        return requested
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
        'send_message': add_mode_status_message, 'get_context': get_current_context,
        'get_timings': get_timings, 'on_stop': on_stop, 'update_mood': update_mood,
        'user_signal_event': app_state.user_signal_event,
        'message_event': app_state.mode_message_event,
        'message_queue': app_state.mode_message_queue,
        'remember_pattern': _remember_motion_pattern_from_target,
        'remember_pattern_id': _remember_live_motion_pattern_id,
        'freestyle_candidates': _freestyle_candidate_patterns,
        'allow_llm_edge_in_freestyle': lambda: settings.allow_llm_edge_in_freestyle,
        'autospeak_enabled': lambda: settings.autospeak_enabled,
        'autospeak_range': lambda: (settings.autospeak_min_seconds, settings.autospeak_max_seconds),
        'consume_autospeak_wake': consume_autospeak_wake,
        'set_mode_name': set_mode_name,
        'mode_decision': mode_decision,
        'send_chat': add_message_to_queue,
    }
    task = AutoModeThread(mode_logic, initial_message, services, callbacks, mode_name=mode_name)
    with app_state.lock:
        app_state.auto_mode_active_task = task
    task.start()

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────────────────────────────────
@app.route('/')
def home_page():
    with open(resource_path('index.html'), 'r', encoding='utf-8') as f:
        response = Response(render_template_string(f.read()), mimetype="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Connection"] = "close"
    return response

@app.route('/static/<path:path>')
def send_static(path):
    response = send_from_directory(resource_path('static'), path)
    response.headers.setdefault("Cache-Control", "no-cache")
    response.headers["Connection"] = "close"
    return response

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
        add_mode_status_message("Stopping.")
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
    if intent.kind == "milking" and _active_mode_can_receive_close_signal():
        ok, mode_name, message = _signal_active_mode_close()
        if ok:
            return True, jsonify({
                "status": "close_signaled",
                "mode": mode_name,
                "message": message,
            })
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
        add_mode_status_message("Adjusting.")
        return True, jsonify({"status": "move_applied", "matched": intent.matched})
    return False, None

def _queue_message_to_active_mode(user_input):
    app_state.mode_message_queue.append(user_input)
    app_state.mode_message_event.set()

def _relay_message_to_active_mode(user_input):
    _queue_message_to_active_mode(user_input)
    return jsonify({"status": "message_relayed_to_active_mode"})

def _active_mode_name():
    active_task = app_state.auto_mode_active_task
    return str(getattr(active_task, "name", "") or "") if active_task else ""

def _active_mode_can_receive_close_signal():
    return _active_mode_name() in {"edging", "milking", "freestyle"}

def _signal_active_mode_close():
    mode_name = _active_mode_name()
    if mode_name in {"edging", "milking", "freestyle"}:
        app_state.user_signal_event.set()
        app_state.mode_message_event.set()
        label = {
            "edging": "Edging",
            "milking": "Milking",
            "freestyle": "Freestyle",
        }.get(mode_name, "Mode")
        return True, mode_name, f"{label} close signal sent."
    return False, mode_name, "Edge, milking, or Freestyle mode not active."

def _normalize_request_source(value):
    cleaned = re.sub(r"[^a-z0-9_:-]+", "_", str(value or "chat").strip().lower()).strip("_")
    return cleaned or "chat"

def _request_allows_handsfree_mode_actions(data):
    return (
        bool(settings.voice_input_hands_free_mode_actions)
        and settings.voice_input_mode == "hands_free"
        and _normalize_request_source(data.get("source")) == "voice_hands_free"
    )

def _request_mode_action_context(data):
    source = _normalize_request_source(data.get("source"))
    if _request_allows_handsfree_mode_actions(data):
        return True, "hands-free voice input"
    if bool(settings.allow_llm_mode_actions_in_chat) and source == "chat":
        return True, "typed chat"
    return False, ""

LLM_MODE_ACTION_ALIASES = {
    "continue": "continue_mode",
    "continue_mode": "continue_mode",
    "keep_going": "continue_mode",
    "keep-going": "continue_mode",
    "relay": "continue_mode",
    "close": "close_signal",
    "close_signal": "close_signal",
    "im_close": "close_signal",
    "i_m_close": "close_signal",
    "i'm_close": "close_signal",
    "edge_signal": "close_signal",
    "freestyle": "start_freestyle",
    "start_freestyle": "start_freestyle",
    "adaptive": "start_freestyle",
    "adaptive_motion": "start_freestyle",
    "edging": "start_edging",
    "edge": "start_edging",
    "edge_me": "start_edging",
    "start_edging": "start_edging",
    "milking": "start_milking",
    "milk": "start_milking",
    "milk_me": "start_milking",
    "finish": "start_milking",
    "finish_me": "start_milking",
    "start_milking": "start_milking",
    "auto": "start_legacy_auto",
    "auto_mode": "start_legacy_auto",
    "legacy_auto": "start_legacy_auto",
    "start_auto": "start_legacy_auto",
    "start_auto_mode": "start_legacy_auto",
    "start_legacy_auto": "start_legacy_auto",
    "take_over": "start_legacy_auto",
    "stop": "stop_mode",
    "stop_mode": "stop_mode",
    "manual": "stop_mode",
    "manual_control": "stop_mode",
}

def _normalize_llm_mode_action(value):
    if value is None:
        return ""
    cleaned = str(value or "").strip().lower()
    if not cleaned or cleaned in {"none", "null", "false", "no_action"}:
        return ""
    cleaned = re.sub(r"[^a-z0-9']+", "_", cleaned).strip("_")
    return LLM_MODE_ACTION_ALIASES.get(cleaned, "")

def _start_mode_for_llm_action(action):
    mode_map = {
        "start_freestyle": (freestyle_mode_logic, "Starting adaptive Freestyle.", "freestyle", "Freestyle started."),
        "start_edging": (edging_mode_logic, "Let's play an edging game...", "edging", "Edging mode started."),
        "start_milking": (milking_mode_logic, "You're so close... I'm taking over completely now.", "milking", "Milking mode started."),
        "start_legacy_auto": (auto_mode_logic, "Starting legacy Auto.", "auto", "Legacy Auto started."),
    }
    entry = mode_map.get(action)
    if not entry:
        return False, ""
    mode_logic, initial_message, mode_name, message = entry
    if _active_mode_name() == mode_name:
        app_state.mode_message_event.set()
        return True, f"{message} Already active."
    start_background_mode(mode_logic, initial_message, mode_name=mode_name)
    return True, message

def _apply_llm_mode_action(response):
    if not isinstance(response, dict):
        return "", False, ""
    action = _normalize_llm_mode_action(response.get("mode_action"))
    if not action:
        return "", False, ""
    if action == "continue_mode":
        if app_state.auto_mode_active_task:
            app_state.mode_message_event.set()
            return action, True, "Continuing active mode."
        return action, False, "No active mode to continue."
    if action == "close_signal":
        ok, _mode_name, message = _signal_active_mode_close()
        if ok:
            return action, True, message
        ok, message = _start_mode_for_llm_action("start_milking")
        return action, ok, message
    if action == "stop_mode":
        _clear_motion_pause_state()
        if app_state.auto_mode_active_task:
            app_state.auto_mode_active_task.stop()
        _stop_motion_training()
        return action, True, "Stopping active mode."
    ok, message = _start_mode_for_llm_action(action)
    return action, ok, message

CHAT_FIELD_RE = re.compile(r'"chat"\s*:\s*"')
JSON_ESCAPE_MAP = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _json_string_prefix(text, opening_quote_index):
    output = []
    index = opening_quote_index + 1
    while index < len(text):
        ch = text[index]
        if ch == '"':
            return "".join(output), True
        if ch != "\\":
            output.append(ch)
            index += 1
            continue
        index += 1
        if index >= len(text):
            break
        escaped = text[index]
        if escaped == "u":
            digits = text[index + 1:index + 5]
            if len(digits) < 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                break
            output.append(chr(int(digits, 16)))
            index += 5
            continue
        output.append(JSON_ESCAPE_MAP.get(escaped, escaped))
        index += 1
    return "".join(output), False


def _streamed_chat_text_prefix(raw_content):
    match = CHAT_FIELD_RE.search(raw_content or "")
    if not match:
        return "", False
    return _json_string_prefix(raw_content, match.end() - 1)


class _StreamingChatTextExtractor:
    """Incrementally extracts the ``chat`` string from streamed LLM JSON."""

    def __init__(self):
        self._raw_parts = []
        self._search_text = ""
        self._streamed_chars = []
        self._found_chat = False
        self._complete = False
        self._escape_pending = False
        self._unicode_digits = None
        self._stalled = False

    def append(self, chunk):
        text = str(chunk or "")
        if not text:
            return ""
        self._raw_parts.append(text)
        if self._complete or self._stalled:
            return ""

        if not self._found_chat:
            self._search_text += text
            match = CHAT_FIELD_RE.search(self._search_text)
            if not match:
                return ""
            text = self._search_text[match.end():]
            self._search_text = ""
            self._found_chat = True

        return self._append_chat_text(text)

    def _append_chat_text(self, text):
        start_index = len(self._streamed_chars)
        for ch in text:
            if self._unicode_digits is not None:
                if not re.fullmatch(r"[0-9a-fA-F]", ch):
                    self._stalled = True
                    break
                self._unicode_digits += ch
                if len(self._unicode_digits) == 4:
                    self._streamed_chars.append(chr(int(self._unicode_digits, 16)))
                    self._unicode_digits = None
                    self._escape_pending = False
                continue

            if self._escape_pending:
                if ch == "u":
                    self._unicode_digits = ""
                    continue
                self._streamed_chars.append(JSON_ESCAPE_MAP.get(ch, ch))
                self._escape_pending = False
                continue

            if ch == '"':
                self._complete = True
                break
            if ch == "\\":
                self._escape_pending = True
                continue
            self._streamed_chars.append(ch)
        return "".join(self._streamed_chars[start_index:])

    def raw_content(self):
        return "".join(self._raw_parts)

    def has_streamed_text(self):
        return bool(self._streamed_chars)


def _chat_stream_event(event_type, **payload):
    body = {"type": event_type, **payload}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"


def _coerce_llm_response(llm_response):
    if isinstance(llm_response, dict):
        return llm_response
    print(f"[WARN] LLM returned non-dict response: {llm_response!r}")
    return {
        "chat": "The local model returned an unreadable response. Check Ollama model status and try again.",
        "move": None,
        "new_mood": None,
    }


def _finalize_llm_chat_response(
    *,
    user_input,
    llm_response,
    context,
    current_before_llm,
    request_started,
    timings,
    streamed_to_client=False,
    mode_actions_allowed=False,
    relay_active_mode_on_no_action=False,
):
    motion_repaired = False
    llm_response = _coerce_llm_response(llm_response)
    if not _is_llm_transport_error_text(llm_response.get("chat")):
        repair_started = time.perf_counter()
        llm_response, motion_repaired = _repair_llm_motion_response_if_needed(
            user_input,
            llm_response,
            context,
            current_before_llm,
        )
        timings["motion_repair_ms"] = int((time.perf_counter() - repair_started) * 1000)

    raw_chat_text = llm_response.get("chat")
    chat_text = str(raw_chat_text or "").strip()
    if not chat_text:
        print(f"[WARN] LLM response did not include chat text: {llm_response!r}")
        chat_text = "The local model returned movement data but no chat text. Check Ollama model status and try again."
    is_llm_transport_error = _is_llm_transport_error_text(chat_text)

    if is_llm_transport_error:
        timings["request_ms"] = int((time.perf_counter() - request_started) * 1000)
        return {
            "status": "model_error",
            "message": "Model request failed. Check Ollama status and try again.",
            "chat": chat_text,
            "chat_queued": False,
            "chat_streamed": bool(streamed_to_client),
            "motion_applied": False,
            "motion_repaired": False,
            "timings": timings,
        }

    should_revert_persona = False
    with app_state.lock:
        if app_state.special_persona_mode is not None:
            app_state.special_persona_interactions_left -= 1
            should_revert_persona = app_state.special_persona_interactions_left <= 0
            if should_revert_persona:
                app_state.special_persona_mode = None
    if should_revert_persona:
        add_message_to_queue("(Personality core reverted to standard operation.)", add_to_history=False)

    add_message_to_queue(
        chat_text,
        add_to_history=bool(str(raw_chat_text or "").strip()),
        queue_message=not streamed_to_client,
        generate_audio=True,
        streamed_to_client=streamed_to_client,
    )
    if new_mood := llm_response.get("new_mood"):
        with app_state.lock:
            app_state.current_mood = new_mood
    mode_action = ""
    mode_action_applied = False
    mode_action_message = ""
    if mode_actions_allowed:
        mode_action_started = time.perf_counter()
        mode_action, mode_action_applied, mode_action_message = _apply_llm_mode_action(llm_response)
        timings["mode_action_ms"] = int((time.perf_counter() - mode_action_started) * 1000)
    active_mode_message_relayed = False
    if (
        relay_active_mode_on_no_action
        and app_state.auto_mode_active_task
        and (not mode_action or mode_action == "continue_mode")
    ):
        _queue_message_to_active_mode(user_input)
        active_mode_message_relayed = True
    motion_applied = False
    if not app_state.auto_mode_active_task and not mode_action_applied:
        motion_started = time.perf_counter()
        target = _apply_llm_response_move(
            llm_response,
            current_before_llm,
            source="llm repair" if motion_repaired else "llm",
        )
        motion_applied = target is not None
        _remember_motion_pattern_from_target(target)
        timings["motion_apply_ms"] = int((time.perf_counter() - motion_started) * 1000)
    autospeak_scheduled = False
    if settings.autospeak_enabled and not app_state.auto_mode_active_task:
        autospeak_scheduled = _schedule_standalone_autospeak(llm_response.get("autospeak_seconds"))
    timings["request_ms"] = int((time.perf_counter() - request_started) * 1000)
    return {
        "status": "ok",
        "chat": chat_text,
        "chat_queued": not streamed_to_client,
        "chat_streamed": bool(streamed_to_client),
        "motion_applied": motion_applied,
        "motion_repaired": motion_repaired,
        "mode_action": mode_action,
        "mode_action_applied": mode_action_applied,
        "mode_action_message": mode_action_message,
        "active_mode_message_relayed": active_mode_message_relayed,
        "autospeak_scheduled": autospeak_scheduled,
        "timings": timings,
    }


@app.route('/send_message', methods=['POST'])
def handle_user_message():
    request_started = time.perf_counter()
    data = _request_json()
    user_input = data.get('message', '').strip()
    mode_actions_allowed, mode_action_source = _request_mode_action_context(data)
    handsfree_mode_actions_allowed = _request_allows_handsfree_mode_actions(data)

    if (p := data.get('persona_desc')) and p != settings.persona_desc:
        settings.set_persona_prompt(p); settings.save()
    if (k := data.get('key')) and k != settings.handy_key:
        handy.set_api_key(k); settings.handy_key = k; settings.save()

    if not handy.handy_key: return jsonify({"status": "no_key_set"})
    if not user_input: return jsonify({"status": "empty_message"})

    _cancel_standalone_autospeak()
    app_state.chat_history.append({"role": "user", "content": user_input})

    handled, response = _handle_chat_commands(
        user_input.lower(),
        allow_motion=not app_state.auto_mode_active_task,
    )
    if handled: return response

    active_mode_before_llm = bool(app_state.auto_mode_active_task)
    if active_mode_before_llm and not mode_actions_allowed:
        return _relay_message_to_active_mode(user_input)

    context = get_current_context()
    context["mode_actions_enabled"] = mode_actions_allowed
    context["mode_action_request_source"] = mode_action_source
    context["handsfree_mode_actions_enabled"] = handsfree_mode_actions_allowed
    current_before_llm = motion.current_target()
    timings = {}
    try:
        llm_started = time.perf_counter()
        llm_response = llm.get_chat_response(app_state.chat_history, context)
        timings["llm_ms"] = int((time.perf_counter() - llm_started) * 1000)
    except Exception as exc:
        timings["llm_ms"] = int((time.perf_counter() - llm_started) * 1000)
        print(f"[ERROR] LLM request failed: {exc}")
        llm_response = {
            "chat": f"LLM request failed: {exc}",
            "move": None,
            "new_mood": None,
        }
    return jsonify(_finalize_llm_chat_response(
        user_input=user_input,
        llm_response=llm_response,
        context=context,
        current_before_llm=current_before_llm,
        request_started=request_started,
        timings=timings,
        mode_actions_allowed=mode_actions_allowed,
        relay_active_mode_on_no_action=active_mode_before_llm,
    ))


@app.route('/send_message_stream', methods=['POST'])
def handle_user_message_stream():
    request_started = time.perf_counter()
    data = _request_json()
    user_input = data.get('message', '').strip()
    mode_actions_allowed, mode_action_source = _request_mode_action_context(data)
    handsfree_mode_actions_allowed = _request_allows_handsfree_mode_actions(data)

    def generate():
        if (p := data.get('persona_desc')) and p != settings.persona_desc:
            settings.set_persona_prompt(p); settings.save()
        if (k := data.get('key')) and k != settings.handy_key:
            handy.set_api_key(k); settings.handy_key = k; settings.save()

        if not handy.handy_key:
            yield _chat_stream_event("final", data={"status": "no_key_set"})
            return
        if not user_input:
            yield _chat_stream_event("final", data={"status": "empty_message"})
            return

        _cancel_standalone_autospeak()
        app_state.chat_history.append({"role": "user", "content": user_input})

        handled, response = _handle_chat_commands(
            user_input.lower(),
            allow_motion=not app_state.auto_mode_active_task,
        )
        if handled:
            yield _chat_stream_event("final", data=response.get_json(silent=True) or {"status": "ok"})
            return

        active_mode_before_llm = bool(app_state.auto_mode_active_task)
        if active_mode_before_llm and not mode_actions_allowed:
            response = _relay_message_to_active_mode(user_input)
            yield _chat_stream_event("final", data=response.get_json(silent=True) or {"status": "message_relayed_to_active_mode"})
            return

        context = get_current_context()
        context["mode_actions_enabled"] = mode_actions_allowed
        context["mode_action_request_source"] = mode_action_source
        context["handsfree_mode_actions_enabled"] = handsfree_mode_actions_allowed
        current_before_llm = motion.current_target()
        timings = {}
        stream_extractor = _StreamingChatTextExtractor()
        try:
            yield _chat_stream_event("status", status="generating")
            llm_started = time.perf_counter()
            for chunk in llm.iter_chat_response_content(app_state.chat_history, context):
                delta = stream_extractor.append(chunk)
                if delta:
                    yield _chat_stream_event("delta", text=delta)
            timings["llm_ms"] = int((time.perf_counter() - llm_started) * 1000)
            raw_content = stream_extractor.raw_content()
            try:
                llm_response = json.loads(raw_content)
            except json.JSONDecodeError as exc:
                print(f"[WARN] LLM streamed invalid JSON: {exc}")
                llm_response = {
                    "chat": "The local model returned an unreadable response. Check Ollama model status and try again.",
                    "move": None,
                    "new_mood": None,
                }
        except Exception as exc:
            timings["llm_ms"] = int((time.perf_counter() - llm_started) * 1000) if "llm_started" in locals() else 0
            print(f"[ERROR] LLM stream failed: {exc}")
            llm_response = {
                "chat": f"LLM Connection Error: {exc}",
                "move": None,
                "new_mood": None,
            }

        final_payload = _finalize_llm_chat_response(
            user_input=user_input,
            llm_response=llm_response,
            context=context,
            current_before_llm=current_before_llm,
            request_started=request_started,
            timings=timings,
            streamed_to_client=stream_extractor.has_streamed_text(),
            mode_actions_allowed=mode_actions_allowed,
            relay_active_mode_on_no_action=active_mode_before_llm,
        )
        yield _chat_stream_event("final", data=final_payload)

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
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

def _read_uploaded_program_payload(upload):
    filename = secure_filename(upload.filename or "program.funscript")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMPORT_EXTENSIONS:
        raise ProgramValidationError("Program imports must be .json or .funscript files.")
    raw = upload.read(MAX_PROGRAM_IMPORT_BYTES + 1)
    if len(raw) > MAX_PROGRAM_IMPORT_BYTES:
        raise ProgramValidationError("Program import is too large.")
    try:
        return filename, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProgramValidationError(f"Program file is not valid JSON: {exc}") from exc

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
    with app_state.lock:
        mode_status_message = app_state.mode_status_message
        app_state.mode_status_message = ""
        chat_audio_warning = app_state.chat_audio_warning
        app_state.chat_audio_warning = ""
    return jsonify({
        "messages": messages,
        "audio_ready": audio.has_audio(),
        "audio_error": audio.consume_last_error(),
        "mode_status_message": mode_status_message,
        "chat_audio_warning": chat_audio_warning,
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

# ─── APP STARTUP ───────────────────────────────────────────────────────────────────────────────────
def on_exit():
    print("[INFO] Saving settings on exit...")
    settings.save(llm, app_state.chat_history)
    try:
        voice_input.close()
    except Exception as exc:
        print(f"[WARN] Voice input shutdown failed: {exc}")
    print("[OK] Settings saved.")

def main():
    atexit.register(on_exit)
    host = os.getenv("STROKEGPT_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    requested_port = _env_int("STROKEGPT_PORT", DEFAULT_PORT)
    try:
        tls_config = resolve_server_tls(os.environ, HTTPS_CERT_DIR, host)
    except ServerTlsError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
    try:
        port = _select_bind_port(host, requested_port)
    except OSError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
    if port != requested_port:
        print(f"[WARN] Port {requested_port} is unavailable; using {port} instead.")
    print(f"[INFO] Starting Handy AI app at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
    if tls_config.enabled:
        print(f"[INFO] HTTPS enabled using {tls_config.source}.")
        if tls_config.cert_path:
            print(f"[INFO] HTTPS certificate: {tls_config.cert_path}")
        if getattr(tls_config, "trust_cert_path", None):
            print(f"[INFO] Mobile trust certificate: {tls_config.trust_cert_path}")
            trust_helper = _start_https_trust_helper(host, port, tls_config.trust_cert_path)
            if trust_helper:
                print(f"[INFO] Android Chrome certificate helper: {trust_helper.info_url}")
                print(f"[INFO] Android Chrome CA download: {trust_helper.cert_url}")
                atexit.register(_stop_https_trust_helper, trust_helper)
    url = _server_url(tls_config.scheme, host, port)
    print(f"[INFO] Open {url}")
    if _env_flag("STROKEGPT_OPEN_BROWSER"):
        threading.Timer(1.0, _open_browser, args=(url,)).start()
    app.run(
        host=host,
        port=port,
        debug=False,
        ssl_context=tls_config.ssl_context,
        threaded=True,
        use_reloader=False,
    )


if __name__ == '__main__':
    main()
