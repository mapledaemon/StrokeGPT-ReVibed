import time
from pathlib import Path

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from ..asr import VoiceInputError, VoiceInputUnavailable


voice_input_blueprint = Blueprint("voice_input", __name__)


def _web():
    from .. import web

    return web


def _voice_input_payload(web, status="success"):
    payload = web.voice_input.status()
    payload["status"] = status
    return payload


def _browse_directory(title):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        return filedialog.askdirectory(title=title, mustexist=True)
    finally:
        root.destroy()


@voice_input_blueprint.route('/voice_input_status')
def voice_input_status_route():
    web = _web()
    return jsonify(_voice_input_payload(web))


@voice_input_blueprint.route('/set_voice_input', methods=['POST'])
def set_voice_input_route():
    web = _web()
    data = web._request_json()
    provider = web.settings._normalize_voice_input_provider(
        data.get("provider", web.settings.voice_input_provider)
    )
    mode = web.settings._normalize_voice_input_mode(
        data.get("mode", web.settings.voice_input_mode)
    )
    submit_mode = web.settings._normalize_voice_input_submit_mode(
        data.get("submit_mode", web.settings.voice_input_submit_mode)
    )
    enabled = web._request_bool_value(data, "enabled", web.settings.voice_input_enabled)
    if provider == "disabled":
        enabled = False
    model = str(data.get("model", web.settings.voice_input_model) or "").strip() or web.settings.voice_input_model
    language = str(data.get("language", web.settings.voice_input_language) or "auto").strip() or "auto"
    hands_free_sensitivity = web.settings._normalize_voice_input_hands_free_sensitivity(
        data.get("hands_free_sensitivity", web.settings.voice_input_hands_free_sensitivity)
    )
    hands_free_silence_ms = web.settings._normalize_voice_input_silence_ms(
        data.get("hands_free_silence_ms", web.settings.voice_input_hands_free_silence_ms)
    )
    min_recording_ms = web.settings._normalize_voice_input_min_recording_ms(
        data.get("min_recording_ms", web.settings.voice_input_min_recording_ms)
    )
    max_recording_ms = web.settings._normalize_voice_input_max_recording_ms(
        data.get("max_recording_ms", web.settings.voice_input_max_recording_ms)
    )
    if max_recording_ms < min_recording_ms:
        max_recording_ms = min_recording_ms
    noise_suppression = web._request_bool_value(
        data,
        "noise_suppression",
        web.settings.voice_input_noise_suppression,
    )
    echo_cancellation = web._request_bool_value(
        data,
        "echo_cancellation",
        web.settings.voice_input_echo_cancellation,
    )
    auto_gain_control = web._request_bool_value(
        data,
        "auto_gain_control",
        web.settings.voice_input_auto_gain_control,
    )
    noise_floor_rms = web.settings._normalize_voice_input_noise_floor_rms(
        data.get("noise_floor_rms", web.settings.voice_input_noise_floor_rms)
    )

    web.settings.voice_input_provider = provider
    web.settings.voice_input_enabled = enabled
    web.settings.voice_input_model = model
    web.settings.voice_input_language = language
    web.settings.voice_input_mode = mode
    web.settings.voice_input_submit_mode = submit_mode
    web.settings.voice_input_preview_required = submit_mode != "auto_submit"
    web.settings.voice_input_hands_free_sensitivity = hands_free_sensitivity
    web.settings.voice_input_hands_free_silence_ms = hands_free_silence_ms
    web.settings.voice_input_min_recording_ms = min_recording_ms
    web.settings.voice_input_max_recording_ms = max_recording_ms
    web.settings.voice_input_noise_suppression = noise_suppression
    web.settings.voice_input_echo_cancellation = echo_cancellation
    web.settings.voice_input_auto_gain_control = auto_gain_control
    web.settings.voice_input_noise_floor_rms = noise_floor_rms
    web.voice_input.configure(
        provider=provider,
        enabled=enabled,
        model=model,
        language=language,
        mode=mode,
        submit_mode=submit_mode,
        hands_free_sensitivity=hands_free_sensitivity,
        hands_free_silence_ms=hands_free_silence_ms,
        min_recording_ms=min_recording_ms,
        max_recording_ms=max_recording_ms,
        noise_suppression=noise_suppression,
        echo_cancellation=echo_cancellation,
        auto_gain_control=auto_gain_control,
        noise_floor_rms=noise_floor_rms,
    )
    web.settings.save()
    return jsonify(_voice_input_payload(web))


@voice_input_blueprint.route('/browse_voice_input_model_path', methods=['POST'])
def browse_voice_input_model_path_route():
    try:
        selected = str(_browse_directory("Select faster-whisper model folder") or "").strip()
    except Exception as exc:
        return jsonify({
            "status": "error",
            "message": f"Model folder picker unavailable: {exc}",
        }), 500
    if not selected:
        return jsonify({
            "status": "cancelled",
            "message": "No model folder selected.",
        })

    model_path = Path(selected).expanduser()
    if not model_path.exists() or not model_path.is_dir():
        return jsonify({
            "status": "error",
            "message": "Select a local faster-whisper model folder.",
        }), 400
    return jsonify({
        "status": "success",
        "model_path": str(model_path),
        "message": "Voice input model folder selected.",
    })


@voice_input_blueprint.route('/preload_voice_input_model', methods=['POST'])
def preload_voice_input_model_route():
    web = _web()
    try:
        _, message = web.voice_input.preload_model()
    except VoiceInputUnavailable as exc:
        return jsonify({
            "status": "unavailable",
            "message": str(exc),
            "voice_input_status": web.voice_input.status(),
        }), 409
    except VoiceInputError as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
            "voice_input_status": web.voice_input.status(),
        }), 500
    payload = _voice_input_payload(web)
    payload["message"] = message
    return jsonify(payload)


def _save_uploaded_clip(web):
    uploaded = request.files.get("audio")
    if not uploaded or not uploaded.filename:
        return None, (jsonify({"status": "error", "message": "Choose an audio clip first."}), 400)

    original_name = secure_filename(uploaded.filename or "voice.webm")
    suffix = Path(original_name).suffix.lower()
    if suffix not in web.ALLOWED_VOICE_INPUT_EXTENSIONS:
        return None, (jsonify({
            "status": "error",
            "message": "Voice input must be WEBM, WAV, MP3, OGG, M4A, AAC, or FLAC.",
        }), 400)

    mimetype = (uploaded.mimetype or "").split(";")[0].strip().lower()
    if mimetype and mimetype not in web.ALLOWED_VOICE_INPUT_MIMETYPES:
        return None, (jsonify({"status": "error", "message": f"Unsupported audio type: {mimetype}"}), 400)

    raw = uploaded.read(web.MAX_VOICE_INPUT_BYTES + 1)
    if not raw:
        return None, (jsonify({"status": "error", "message": "Recorded audio was empty."}), 400)
    if len(raw) > web.MAX_VOICE_INPUT_BYTES:
        return None, (jsonify({"status": "error", "message": "Recorded audio is too large."}), 413)

    web.VOICE_INPUT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = (web.VOICE_INPUT_UPLOAD_DIR / f"{int(time.time() * 1000)}-{original_name}").resolve()
    upload_root = web.VOICE_INPUT_UPLOAD_DIR.resolve()
    try:
        target.relative_to(upload_root)
    except ValueError:
        return None, (jsonify({"status": "error", "message": "Invalid audio filename."}), 400)
    target.write_bytes(raw)
    return target, None


@voice_input_blueprint.route('/transcribe_voice', methods=['POST'])
def transcribe_voice_route():
    web = _web()
    target, error = _save_uploaded_clip(web)
    if error:
        return error
    try:
        result = web.voice_input.transcribe_file(target)
    except VoiceInputUnavailable as exc:
        return jsonify({
            "status": "unavailable",
            "message": str(exc),
            "voice_input_status": web.voice_input.status(),
        }), 409
    except VoiceInputError as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
            "voice_input_status": web.voice_input.status(),
        }), 500
    finally:
        try:
            target.unlink()
        except OSError:
            pass

    transcript = result.get("transcript", "").strip()
    if not transcript:
        result["status"] = "no_speech"
        result["message"] = "No speech detected."
    else:
        result["message"] = "Transcript ready."
    result["voice_input_status"] = web.voice_input.status()
    return jsonify(result)
