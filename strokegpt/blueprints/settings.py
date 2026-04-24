from flask import Blueprint, jsonify

from ..settings import normalize_ollama_model


settings_blueprint = Blueprint("settings", __name__)


def _web():
    from .. import web

    return web


@settings_blueprint.route('/check_settings')
def check_settings_route():
    web = _web()
    return jsonify(web.settings_payload())


@settings_blueprint.route('/reset_settings', methods=['POST'])
def reset_settings_route():
    web = _web()
    data = web._request_json()
    if data.get("confirm") != "RESET":
        return jsonify({"status": "error", "message": "Reset confirmation is required."}), 400
    web.reset_runtime_state()
    payload = web.settings_payload()
    payload["status"] = "success"
    return jsonify(payload)


@settings_blueprint.route('/set_persona_prompt', methods=['POST'])
def set_persona_prompt_route():
    web = _web()
    data = web._request_json()
    prompt = data.get('persona_desc', '')
    save_prompt = data.get('save_prompt', True)
    if not web.settings.set_persona_prompt(prompt, save_prompt=save_prompt):
        return jsonify({"status": "error", "message": "Persona prompt is required."}), 400
    web.settings.save()
    return jsonify({
        "status": "success",
        "persona": web.settings.persona_desc,
        "persona_prompts": web.get_persona_prompts_for_ui(),
    })


@settings_blueprint.route('/set_ollama_model', methods=['POST'])
def set_ollama_model_route():
    web = _web()
    data = web._request_json()
    model = normalize_ollama_model(data.get('model', ''))
    if not model:
        return jsonify({"status": "error", "message": "Model name is required."}), 400
    if not web.llm.set_model(model):
        return jsonify({"status": "error", "message": "Invalid model name."}), 400
    web.settings.set_ollama_model(model)
    web.settings.save()
    return jsonify({
        "status": "success",
        "ollama_model": web.llm.model,
        "ollama_models": web.get_ollama_models_for_ui(),
        "ollama_status": web._ollama_status_payload(),
    })


@settings_blueprint.route('/ollama_status')
def ollama_status_route():
    web = _web()
    return jsonify(web._ollama_status_payload())


@settings_blueprint.route('/set_diagnostics_levels', methods=['POST'])
def set_diagnostics_levels_route():
    web = _web()
    data = web._request_json()
    motion_level = web.settings._normalize_diagnostics_level(
        data.get("motion_diagnostics_level", web.settings.motion_diagnostics_level)
    )
    ollama_level = web.settings._normalize_diagnostics_level(
        data.get("ollama_diagnostics_level", web.settings.ollama_diagnostics_level)
    )
    web.settings.motion_diagnostics_level = motion_level
    web.settings.ollama_diagnostics_level = ollama_level
    web.settings.save()
    return jsonify({
        "status": "success",
        "motion_diagnostics_level": motion_level,
        "ollama_diagnostics_level": ollama_level,
        "diagnostics_levels": web._diagnostics_level_options(),
        "ollama_status": web._ollama_status_payload(),
    })


@settings_blueprint.route('/pull_ollama_model', methods=['POST'])
def pull_ollama_model_route():
    web = _web()
    data = web._request_json()
    model = normalize_ollama_model(data.get('model') or web.llm.model)
    if not model:
        return jsonify({"status": "error", "message": "Model name is required."}), 400

    web.settings.set_ollama_model(model)
    web.llm.set_model(model)
    web.settings.save()
    ok, message = web._start_ollama_pull(model)
    return jsonify({
        "status": "started" if ok else "error",
        "message": message,
        "ollama_model": web.llm.model,
        "ollama_models": web.get_ollama_models_for_ui(),
        "ollama_status": web._ollama_status_payload(),
    })


@settings_blueprint.route('/set_ai_name', methods=['POST'])
def set_ai_name_route():
    web = _web()
    data = web._request_json()
    name = data.get('name', 'BOT').strip()
    if not name:
        name = 'BOT'

    if name.lower() == 'glados':
        web.special_persona_mode = "GLaDOS"
        web.special_persona_interactions_left = 5
        web.settings.ai_name = "GLaDOS"
        web.settings.save()
        return jsonify({"status": "special_persona_activated", "persona": "GLaDOS", "message": "Oh, it's *you*."})

    web.settings.ai_name = name
    web.settings.save()
    return jsonify({"status": "success", "name": name})


@settings_blueprint.route('/toggle_memory', methods=['POST'])
def toggle_memory_route():
    web = _web()
    data = web._request_json()
    if "enabled" in data:
        enabled = data.get("enabled")
        if isinstance(enabled, str):
            web.use_long_term_memory = enabled.strip().lower() in {"1", "true", "yes", "on"}
        else:
            web.use_long_term_memory = bool(enabled)
    else:
        web.use_long_term_memory = not web.use_long_term_memory
    return jsonify({"status": "success", "use_long_term_memory": web.use_long_term_memory})


@settings_blueprint.route('/set_profile_picture', methods=['POST'])
def set_pfp_route():
    web = _web()
    b64_data = web._request_json().get('pfp_b64')
    if not b64_data:
        return jsonify({"status": "error", "message": "Missing image data"}), 400
    web.settings.profile_picture_b64 = b64_data
    web.settings.save()
    return jsonify({"status": "success"})


@settings_blueprint.route('/set_handy_key', methods=['POST'])
def set_handy_key_route():
    web = _web()
    key = web._request_json().get('key')
    if not key:
        return jsonify({"status": "error", "message": "Key is missing"}), 400
    web.handy.set_api_key(key)
    web.settings.handy_key = key
    web.settings.save()
    return jsonify({"status": "success"})
