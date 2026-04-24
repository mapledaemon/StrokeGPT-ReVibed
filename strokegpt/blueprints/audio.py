import io
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename


audio_blueprint = Blueprint("audio", __name__)


def _web():
    from .. import web

    return web


@audio_blueprint.route('/setup_elevenlabs', methods=['POST'])
def elevenlabs_setup_route():
    web = _web()
    api_key = web._request_json().get('api_key')
    if not api_key or not web.audio.set_api_key(api_key):
        return jsonify({"status": "error"}), 400
    web.settings.elevenlabs_api_key = api_key
    web.settings.save()
    return jsonify(web.audio.fetch_available_voices())


@audio_blueprint.route('/set_elevenlabs_voice', methods=['POST'])
def set_elevenlabs_voice_route():
    web = _web()
    data = web._request_json()
    voice_id, enabled = data.get('voice_id'), data.get('enabled', False)
    ok, message = web.audio.configure_voice(voice_id, enabled)
    if ok:
        web.settings.audio_provider = "elevenlabs"
        web.settings.audio_enabled = bool(enabled)
        web.settings.elevenlabs_voice_id = voice_id
        web.settings.save()
    return jsonify({"status": "ok" if ok else "error", "message": message})


@audio_blueprint.route('/set_audio_provider', methods=['POST'])
def set_audio_provider_route():
    web = _web()
    data = web._request_json()
    provider = data.get('provider', 'elevenlabs')
    enabled = data.get('enabled', web.settings.audio_enabled)
    ok, message = web.audio.set_provider(provider, enabled)
    if ok:
        web.settings.audio_provider = provider
        web.settings.audio_enabled = bool(enabled)
        web.settings.save()
    return jsonify({
        "status": "ok" if ok else "error",
        "message": message,
        "local_tts_status": web.audio.local_status(),
    })


@audio_blueprint.route('/local_tts_status')
def local_tts_status_route():
    web = _web()
    return jsonify(web.audio.local_status())


@audio_blueprint.route('/preload_local_tts_model', methods=['POST'])
def preload_local_tts_model_route():
    web = _web()
    started = web.audio.preload_local_model_async(force=True)
    message = "Local voice model download/load started." if started else "Local voice model could not be started."
    return jsonify({
        "status": "started" if started else "error",
        "message": message,
        "local_tts_status": web.audio.local_status(),
    })


@audio_blueprint.route('/set_local_tts_voice', methods=['POST'])
def set_local_tts_voice_route():
    web = _web()
    data = web._request_json()
    enabled = data.get('enabled', False)
    prompt_path = data.get('prompt_path', '')
    style = data.get('style', web.settings.local_tts_style)
    engine = data.get('engine', web.settings.local_tts_engine)
    exaggeration = data.get('exaggeration', 0.65)
    cfg_weight = data.get('cfg_weight', 0.35)
    temperature = data.get('temperature', web.settings.local_tts_temperature)
    top_p = data.get('top_p', web.settings.local_tts_top_p)
    min_p = data.get('min_p', web.settings.local_tts_min_p)
    repetition_penalty = data.get('repetition_penalty', web.settings.local_tts_repetition_penalty)
    ok, message = web.audio.configure_local_voice(
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
        web.persist_local_voice_settings()
    return jsonify({
        "status": "ok" if ok else "error",
        "message": message,
        "local_tts_status": web.audio.local_status(),
    })


@audio_blueprint.route('/upload_local_tts_sample', methods=['POST'])
def upload_local_tts_sample_route():
    web = _web()
    uploaded = request.files.get('sample')
    if not uploaded or not uploaded.filename:
        return jsonify({"status": "error", "message": "Choose an audio file first."}), 400

    original_name = secure_filename(uploaded.filename)
    extension = Path(original_name).suffix.lower()
    if extension not in web.ALLOWED_VOICE_SAMPLE_EXTENSIONS:
        return jsonify({
            "status": "error",
            "message": "Sample must be WAV, MP3, FLAC, M4A, OGG, or AAC.",
        }), 400

    web.VOICE_SAMPLE_DIR.mkdir(exist_ok=True)
    stem = Path(original_name).stem or "voice-sample"
    filename = f"{int(time.time())}-{stem}{extension}"
    target = (web.VOICE_SAMPLE_DIR / filename).resolve()
    sample_root = web.VOICE_SAMPLE_DIR.resolve()
    try:
        target.relative_to(sample_root)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid sample filename."}), 400

    uploaded.save(target)
    web.audio.configure_local_voice(
        web.audio.is_on,
        str(target),
        web.audio.local_exaggeration,
        web.audio.local_cfg_weight,
        web.audio.local_style,
        web.audio.local_temperature,
        web.audio.local_top_p,
        web.audio.local_min_p,
        web.audio.local_repetition_penalty,
        web.audio.local_engine,
    )
    web.persist_local_voice_settings()
    return jsonify({
        "status": "success",
        "prompt_path": str(target),
        "message": "Sample audio saved.",
        "local_tts_status": web.audio.local_status(),
    })


@audio_blueprint.route('/test_local_tts_voice', methods=['POST'])
def test_local_tts_voice_route():
    web = _web()
    if not web.audio.local_model_loaded():
        return jsonify({
            "status": "needs_download",
            "message": "Download / load the local Chatterbox model before testing voice. First use may download several GB.",
            "local_tts_status": web.audio.local_status(),
        })
    threading.Thread(
        target=web.audio.generate_audio_for_text,
        args=("Local voice test.",),
        kwargs={"force": True},
        daemon=True,
    ).start()
    return jsonify({
        "status": "queued",
        "message": "Local voice test queued.",
        "local_tts_status": web.audio.local_status(),
    })


@audio_blueprint.route('/get_audio')
def get_audio_route():
    web = _web()
    audio_chunk = web.audio.get_next_audio_chunk()
    if not audio_chunk:
        return ("", 204)
    return send_file(io.BytesIO(audio_chunk["bytes"]), mimetype=audio_chunk["mimetype"])
