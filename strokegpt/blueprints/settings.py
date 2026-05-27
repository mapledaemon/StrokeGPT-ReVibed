from flask import Blueprint, jsonify

from ..settings import default_user_profile, normalize_ollama_model


settings_blueprint = Blueprint("settings", __name__)


def _web():
    from .. import web

    return web


@settings_blueprint.route('/check_settings')
def check_settings_route():
    web = _web()
    return jsonify(web.settings_payload(
        include_live_ollama_status=False,
        include_motion_preferences=False,
        include_live_local_tts_status=False,
    ))


@settings_blueprint.route('/setup_check')
def setup_check_route():
    web = _web()
    return jsonify(web.setup_check_payload())


@settings_blueprint.route('/diagnostics_latency', methods=['POST'])
def diagnostics_latency_route():
    web = _web()
    return jsonify(web.diagnostics_latency_payload())


@settings_blueprint.route('/diagnostics_system_status')
def diagnostics_system_status_route():
    web = _web()
    return jsonify(web.diagnostics_system_status_payload())


@settings_blueprint.route('/motion_transport_capture', methods=['POST'])
def motion_transport_capture_route():
    web = _web()
    data = web._request_json()
    return jsonify(web.motion_transport_capture_payload(data.get("action", "snapshot")))


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


@settings_blueprint.route('/set_llm_prompt_mode', methods=['POST'])
def set_llm_prompt_mode_route():
    web = _web()
    data = web._request_json()
    mode = web.settings._normalize_llm_prompt_mode(
        data.get("llm_prompt_mode", web.settings.llm_prompt_mode)
    )
    web.settings.llm_prompt_mode = mode
    web.settings.save()
    web.llm.set_custom_prompt_set(web.settings.selected_llm_custom_prompt_set())
    return jsonify({
        "status": "success",
        "llm_prompt_mode": mode,
        "llm_prompt_mode_options": web.payloads.llm_prompt_mode_options(web.settings),
    })


@settings_blueprint.route('/set_user_genitalia', methods=['POST'])
def set_user_genitalia_route():
    web = _web()
    data = web._request_json()
    web.settings.user_genitalia = web.settings._normalize_user_genitalia(
        data.get("user_genitalia", web.settings.user_genitalia)
    )
    web.settings.user_genitalia_custom = web.settings._normalize_user_genitalia_custom(
        data.get("user_genitalia_custom", web.settings.user_genitalia_custom)
    )
    web.settings.save()
    return jsonify({
        "status": "success",
        "user_genitalia": web.settings.user_genitalia,
        "user_genitalia_custom": web.settings.user_genitalia_custom,
        "user_genitalia_options": web.payloads.user_genitalia_options(),
    })


@settings_blueprint.route('/save_llm_prompt_set', methods=['POST'])
def save_llm_prompt_set_route():
    web = _web()
    data = web._request_json()
    prompt_set, message = web.settings.set_llm_custom_prompt_set(
        data.get("name", ""),
        data.get("prompts", {}),
        data.get("prompt_set_id"),
    )
    if not prompt_set:
        return jsonify({"status": "error", "message": message or "Prompt style could not be saved."}), 400
    web.settings.save()
    web.llm.set_custom_prompt_set(web.settings.selected_llm_custom_prompt_set())
    return jsonify({
        "status": "success",
        "llm_prompt_mode": web.settings.llm_prompt_mode,
        "llm_prompt_mode_options": web.payloads.llm_prompt_mode_options(web.settings),
        "prompt_set": {
            "id": prompt_set.get("id"),
            "label": prompt_set.get("label"),
            "description": prompt_set.get("description"),
            "custom": True,
        },
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


@settings_blueprint.route('/set_ollama_thinking', methods=['POST'])
def set_ollama_thinking_route():
    web = _web()
    data = web._request_json()
    enabled = web._request_bool_value(data, "enabled", web.settings.ollama_thinking_enabled)
    web.settings.ollama_thinking_enabled = enabled
    web.llm.set_thinking_enabled(enabled)
    web.settings.save()
    return jsonify({
        "status": "success",
        "ollama_thinking_enabled": enabled,
        "ollama_status": web._ollama_status_payload(),
    })


@settings_blueprint.route('/delete_ollama_model', methods=['POST'])
def delete_ollama_model_route():
    web = _web()
    data = web._request_json()
    model = normalize_ollama_model(data.get('model', ''))
    ok, message = web.settings.delete_ollama_model(model)
    if not ok:
        return jsonify({"status": "error", "message": message}), 400
    web.settings.save()
    return jsonify({
        "status": "success",
        "message": message,
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
        # The user-typed handle ``glados`` activates the snarky-scientist
        # persona. Internal routing uses a neutral ``snarky_scientist``
        # token so the literal proper-noun never reaches the local model
        # via prompt context (see Persona Naming And Prompt Audit:
        # ROADMAP Up Next #4). ``ai_name`` keeps the branded display so
        # the UI still reflects what the user asked for.
        with web.app_state.lock:
            web.app_state.special_persona_mode = "snarky_scientist"
            web.app_state.special_persona_interactions_left = 5
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
        use_long_term_memory = (
            enabled.strip().lower() in {"1", "true", "yes", "on"}
            if isinstance(enabled, str)
            else bool(enabled)
        )
    else:
        use_long_term_memory = not web.app_state.use_long_term_memory
    with web.app_state.lock:
        web.app_state.use_long_term_memory = use_long_term_memory
    web.settings.use_long_term_memory = use_long_term_memory
    web.settings.save()
    return jsonify({
        "status": "success",
        "use_long_term_memory": use_long_term_memory,
        "memory_status": web.payloads.long_term_memory_payload(
            web.settings,
            use_long_term_memory,
        ),
    })


@settings_blueprint.route('/clear_memory', methods=['POST'])
def clear_memory_route():
    web = _web()
    with web.app_state.lock:
        web.app_state.chat_history.clear()
        use_long_term_memory = web.app_state.use_long_term_memory
    web.settings.user_profile = default_user_profile()
    web.settings.save()
    return jsonify({
        "status": "success",
        "use_long_term_memory": use_long_term_memory,
        "memory_status": web.payloads.long_term_memory_payload(
            web.settings,
            use_long_term_memory,
        ),
        "chat_history_cleared": True,
    })


@settings_blueprint.route('/delete_memory_item', methods=['POST'])
def delete_memory_item_route():
    web = _web()
    data = web._request_json()
    field = str(data.get("field") or "").strip()
    if not field:
        return jsonify({"status": "error", "message": "Missing memory field."}), 400

    profile = web.settings.user_profile if isinstance(web.settings.user_profile, dict) else default_user_profile()
    removed = None
    if field == "name":
        name = str(profile.get("name") or "").strip()
        if not name or name.lower() == "unknown":
            return jsonify({"status": "error", "message": "Saved name memory was not found."}), 404
        removed = name
        profile["name"] = "Unknown"
    else:
        values = profile.get(field)
        if not isinstance(values, list):
            return jsonify({"status": "error", "message": "Saved memory list was not found."}), 404
        try:
            index = int(data.get("index"))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Missing memory item index."}), 400
        if index < 0 or index >= len(values):
            return jsonify({"status": "error", "message": "Saved memory item was not found."}), 404
        removed = values.pop(index)
        if field not in {"likes", "dislikes", "key_memories"} and not values:
            profile.pop(field, None)

    with web.app_state.lock:
        web.app_state.chat_history.clear()
        use_long_term_memory = web.app_state.use_long_term_memory
    web.settings.user_profile = profile
    web.settings.save()
    return jsonify({
        "status": "success",
        "removed": {"field": field, "text": str(removed or "")},
        "use_long_term_memory": use_long_term_memory,
        "memory_status": web.payloads.long_term_memory_payload(
            web.settings,
            use_long_term_memory,
        ),
        "chat_history_cleared": True,
    })


@settings_blueprint.route('/set_profile_picture', methods=['POST'])
def set_pfp_route():
    web = _web()
    b64_data = web._request_json().get('pfp_b64')
    if not b64_data:
        return jsonify({"status": "error", "message": "Missing image data"}), 400
    web.settings.profile_picture_b64 = b64_data
    web.settings.save()
    return jsonify({"status": "success"})


_PROMPT_VISIBILITY_SAMPLE_NAME_MOVE = {"speed": 60, "depth": 40, "mood": "Teasing"}
_PROMPT_VISIBILITY_SAMPLE_PROFILE_LOG = (
    {"role": "user", "content": "[example user turn for prompt visibility only]"},
    {"role": "assistant", "content": "[example bot turn for prompt visibility only]"},
)


@settings_blueprint.route('/system_prompts')
def system_prompts_route():
    """Read-only snapshot of every system prompt the local model can
    receive. The chat and repair prompts use live ``get_current_context``
    so the user sees what would actually be sent right now; the
    name-this-move and profile-consolidation prompts use representative
    sample inputs because they are only built on demand. Chat history
    and the per-request user message are appended outside these prompt
    strings and are not part of the snapshot.
    """
    web = _web()
    web.llm.set_custom_prompt_set(web.settings.selected_llm_custom_prompt_set())
    context = web.get_current_context()
    return jsonify({
        "llm_prompt_mode": web.settings.llm_prompt_mode,
        "llm_prompt_mode_options": web.payloads.llm_prompt_mode_options(web.settings),
        "user_genitalia": web.settings.user_genitalia,
        "user_genitalia_custom": web.settings.user_genitalia_custom,
        "user_genitalia_options": web.payloads.user_genitalia_options(),
        "chat": web.llm.system_prompt(context),
        "repair": web.llm.repair_prompt(context),
        "name_this_move": web.llm.name_this_move_prompt(**_PROMPT_VISIBILITY_SAMPLE_NAME_MOVE),
        "profile_consolidation": web.llm.profile_consolidation_prompt(
            chat_chunk=list(_PROMPT_VISIBILITY_SAMPLE_PROFILE_LOG),
            current_profile=web.settings.user_profile,
        ),
        "name_this_move_sample_inputs": dict(_PROMPT_VISIBILITY_SAMPLE_NAME_MOVE),
    })


@settings_blueprint.route('/set_handy_key', methods=['POST'])
def set_handy_key_route():
    web = _web()
    key = web._request_json().get('key')
    if not key:
        return jsonify({"status": "error", "message": "Key is missing"}), 400
    web.handy.set_api_key(key)
    web.settings.handy_key = key
    web.settings.save()
    connection = web.handy.check_connection()
    return jsonify({
        "status": "success",
        "connected": bool(connection.get("connected")),
        "connection_status": connection.get("status", "error"),
        "message": connection.get("message", "Handy connection check completed."),
        "connection": connection,
    })


@settings_blueprint.route('/set_handy_device_config', methods=['POST'])
def set_handy_device_config_route():
    web = _web()
    data = web._request_json()
    firmware_version = web.settings._normalize_handy_firmware_version(
        data.get("handy_firmware_version", web.settings.handy_firmware_version)
    )
    api_v3_key = str(data.get("handy_api_v3_key", web.settings.handy_api_v3_key) or "").strip()

    web.settings.handy_firmware_version = firmware_version
    web.settings.handy_api_v3_key = api_v3_key
    web.handy.set_firmware_version(firmware_version)
    web.handy.set_handy_api_key(api_v3_key)
    web.settings.save()

    v4_ready = bool(web.handy.supports_api_v3_control())
    missing_v3_key = firmware_version == "fw4" and bool(web.settings.handy_key) and not api_v3_key
    bluetooth_transport = web.settings.handy_transport == "browser_bluetooth"
    return jsonify({
        "status": "success",
        "handy_firmware_version": firmware_version,
        "handy_api_v3_key": api_v3_key,
        "handy_api_v3_enabled": v4_ready,
        "handy_api_v3_key_configured": bool(api_v3_key),
        "handy_api_v3_unavailable_reason": web.handy.api_v3_unavailable_reason(),
        "continuous_streaming_supported": bool(web.handy.supports_continuous_streaming()),
        "message": (
            "Handy firmware set to v4; API v3 HSP streaming is enabled."
            if v4_ready
            else "Handy firmware set to v4; connect local Bluetooth from the top bar to enable HSP streaming."
            if bluetooth_transport and firmware_version == "fw4"
            else "Handy firmware set to v4; add a Handy API v3 Application ID to enable HSP streaming."
            if missing_v3_key
            else "Handy firmware set to v4; connect a Handy key to use API v3 HSP streaming."
            if firmware_version == "fw4"
            else "Handy firmware set to v3 legacy mode."
        ),
    })


@settings_blueprint.route('/set_handy_transport', methods=['POST'])
def set_handy_transport_route():
    web = _web()
    data = web._request_json()
    transport = web.settings._normalize_handy_transport(
        data.get("handy_transport", web.settings.handy_transport)
    )
    web.settings.handy_transport = transport
    web.handy.set_transport_mode(transport)
    web.settings.save()
    bluetooth = web.handy_bluetooth_bridge.snapshot()
    if transport == "browser_bluetooth":
        message = (
            "Local Bluetooth selected. Connect from the top bar before starting motion."
            if not bluetooth.get("connected")
            else "Local Bluetooth selected and connected."
        )
    else:
        message = "Cloud REST transport selected."
    return jsonify({
        "status": "success",
        "handy_transport": transport,
        "bluetooth": bluetooth,
        "continuous_streaming_supported": bool(web.handy.supports_continuous_streaming()),
        "message": message,
    })
