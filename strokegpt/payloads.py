from .motion_preferences import build_motion_preference_payload, enrich_catalog
from .settings import DIAGNOSTICS_LEVELS, normalize_ollama_model


def format_bytes(value):
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


def diagnostics_level_options():
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


def ollama_models_for_ui(settings, llm):
    models = list(settings.ollama_models)
    if llm.model not in models:
        models.insert(0, llm.model)
    return models


def persona_prompts_for_ui(settings):
    return settings.persona_prompt_options()


def ollama_status_payload(*, settings, llm, base_url, pull_snapshot, installed_models):
    current_model = normalize_ollama_model(llm.model)
    diagnostics_level = settings.ollama_diagnostics_level
    payload = {
        "available": False,
        "base_url": base_url,
        "current_model": current_model,
        "current_model_installed": False,
        "installed_models": [],
        "installed_model_names": [],
        "download": pull_snapshot(),
        "diagnostics_level": diagnostics_level,
        "llm_diagnostics": llm.diagnostics(include_raw=diagnostics_level == "debug"),
        "message": "Ollama is not reachable. Start Ollama before downloading or using local models.",
    }
    try:
        installed = installed_models()
    except Exception as exc:
        payload["error"] = str(exc)
        return payload

    names = [item["name"] for item in installed]
    payload.update({
        "available": True,
        "installed_models": installed,
        "installed_model_names": names,
        "current_model_installed": current_model in names,
        "message": (
            f"Current model is installed: {current_model}"
            if current_model in names
            else f"Current model is not installed: {current_model}. Click Download Model before chatting."
        ),
    })
    return payload


def motion_backends_payload():
    return [
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
    ]


def settings_payload(
    *,
    settings,
    llm,
    audio,
    use_long_term_memory,
    persona_prompts,
    ollama_models,
    ollama_status,
    motion_patterns,
    motion_preferences,
    diagnostics_levels,
):
    local_tts_status = audio.local_status()
    return {
        "configured": bool(settings.handy_key and settings.min_depth < settings.max_depth),
        "persona": settings.persona_desc,
        "persona_prompts": persona_prompts,
        "handy_key": settings.handy_key,
        "ai_name": settings.ai_name,
        "elevenlabs_key": settings.elevenlabs_api_key,
        "ollama_model": llm.model,
        "ollama_models": ollama_models,
        "ollama_status": ollama_status,
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
        "allow_llm_edge_in_freestyle": settings.allow_llm_edge_in_freestyle,
        "allow_llm_edge_in_chat": settings.allow_llm_edge_in_chat,
        "use_long_term_memory": use_long_term_memory,
        "diagnostics_levels": diagnostics_levels,
        "motion_backends": motion_backends_payload(),
        "motion_patterns": motion_patterns,
        "motion_preferences": motion_preferences,
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


def motion_pattern_catalog_payload(pattern_library, settings, feedback_history_limit):
    payload = enrich_catalog(
        pattern_library.catalog(settings.motion_pattern_enabled, settings.motion_pattern_feedback),
        settings.motion_pattern_weights,
    )
    payload["feedback_history"] = list(settings.motion_pattern_feedback_history[:feedback_history_limit])
    return payload


def motion_pattern_summary(record, weight_overrides=None, *, include_actions=False):
    enriched = enrich_catalog(
        {"patterns": [record.to_summary_dict(include_actions=include_actions)]},
        weight_overrides,
    )
    patterns = enriched.get("patterns") or []
    if patterns:
        return patterns[0]
    return record.to_summary_dict(include_actions=include_actions)


def motion_preference_payload(catalog, excluded_llm_pattern_ids=None):
    return build_motion_preference_payload(catalog, excluded_llm_pattern_ids)
