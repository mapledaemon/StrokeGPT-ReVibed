import re

from .motion_preferences import build_motion_preference_payload, enrich_catalog
from .motion_tags import motion_tag_suggestions
from .settings import (
    AUTOSPEAK_MOTION_AUTONOMY_LEVELS,
    CUSTOM_LLM_PROMPT_PREFIX,
    DIAGNOSTICS_LEVELS,
    LLM_PROMPT_MODES,
    MOTION_STYLES,
    USER_GENITALIA_OPTIONS,
    VOICE_INPUT_PROVIDER_DISABLED,
    VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
    VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET,
    DEFAULT_OLLAMA_MODEL_OPTIONS,
    default_user_profile,
    normalize_ollama_model,
)


HANDY_API_V3_CONNECTION_KEY_RE = re.compile(r"^[A-Za-z0-9]{1,128}$")


def _handy_connection_key_valid_for_api_v3(value):
    return bool(HANDY_API_V3_CONNECTION_KEY_RE.fullmatch(str(value or "").strip()))


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


KNOWN_OLLAMA_MODEL_DETAILS = {
    option["name"]: {
        "size": option["size"],
        "size_label": option["size_label"],
        "source": "catalog",
    }
    for option in DEFAULT_OLLAMA_MODEL_OPTIONS
}


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


def motion_style_options():
    labels = {
        "balanced": "Balanced",
        "smooth": "Smooth",
        "steady": "Steady",
        "teasing": "Teasing",
        "pulsing": "Pulsing",
        "ramping": "Ramping",
        "high_variation": "High variation",
        "full_range": "Full range",
        "freestyle": "Freestyle",
    }
    descriptions = {
        "balanced": "Let the model choose a sensible mix.",
        "smooth": "Favor eased, flowing transitions.",
        "steady": "Favor consistent rhythm and fewer abrupt changes.",
        "teasing": "Favor lighter shallow/mid emphasis unless asked otherwise.",
        "pulsing": "Favor pressure pulses and recurring accents.",
        "ramping": "Favor gradual build-ups and releases.",
        "high_variation": "Favor wider variation in speed, range, and zone.",
        "full_range": "Favor longer travel through more of the calibrated range.",
        "freestyle": "Favor looser pattern variety while staying inside limits.",
    }
    order = (
        "balanced",
        "smooth",
        "steady",
        "teasing",
        "pulsing",
        "ramping",
        "high_variation",
        "full_range",
        "freestyle",
    )
    return [
        {
            "id": style,
            "label": labels[style],
            "description": descriptions[style],
        }
        for style in order
        if style in MOTION_STYLES
    ]


def autospeak_motion_autonomy_options():
    labels = {
        "chat_only": "Talk only",
        "style": "Style only",
        "full": "Full motion",
    }
    descriptions = {
        "chat_only": "Autospeak speaks and keeps the current motion alive, but does not change style or movement.",
        "style": "Autospeak may change the saved Motion Style between requests, but cannot send direct movement targets.",
        "full": "Autospeak may change Motion Style and send direct movement targets between user requests.",
    }
    order = ("chat_only", "style", "full")
    return [
        {
            "id": level,
            "label": labels[level],
            "description": descriptions[level],
        }
        for level in order
        if level in AUTOSPEAK_MOTION_AUTONOMY_LEVELS
    ]


def llm_prompt_mode_options(settings=None):
    labels = {
        "revibed": "ReVibed",
        "legacy": "Legacy",
    }
    descriptions = {
        "revibed": "Less clinical default voice with the same motion-control contract.",
        "legacy": "Previous technical prompt shape for comparison or fallback.",
    }
    options = [
        {
            "id": mode,
            "label": labels[mode],
            "description": descriptions[mode],
        }
        for mode in ("revibed", "legacy")
        if mode in LLM_PROMPT_MODES
    ]
    if settings is not None:
        for prompt_set in getattr(settings, "llm_custom_prompt_sets", []) or []:
            prompt_id = prompt_set.get("id")
            if not prompt_id:
                continue
            options.append({
                "id": f"{CUSTOM_LLM_PROMPT_PREFIX}{prompt_id}",
                "label": prompt_set.get("label") or prompt_id,
                "description": prompt_set.get("description") or "Custom prompt style.",
                "custom": True,
            })
    return options


def user_genitalia_options():
    labels = {
        "penis": "Penis",
        "vagina": "Vagina",
        "custom": "Custom",
    }
    descriptions = {
        "penis": "Tell the prompt the device is being used on a penis.",
        "vagina": "Tell the prompt the device is being used on a vagina/vulva.",
        "custom": "Use custom anatomy wording in the prompt.",
    }
    return [
        {
            "id": option,
            "label": labels[option],
            "description": descriptions[option],
        }
        for option in ("penis", "vagina", "custom")
        if option in USER_GENITALIA_OPTIONS
    ]


def ollama_models_for_ui(settings, llm):
    models = list(settings.ollama_models)
    if llm.model not in models:
        models.insert(0, llm.model)
    return models


def long_term_memory_payload(settings, use_long_term_memory):
    profile = settings.user_profile if isinstance(settings.user_profile, dict) else default_user_profile()
    default_profile = default_user_profile()
    likes = profile.get("likes") if isinstance(profile.get("likes"), list) else []
    dislikes = profile.get("dislikes") if isinstance(profile.get("dislikes"), list) else []
    key_memories = profile.get("key_memories") if isinstance(profile.get("key_memories"), list) else []
    name = str(profile.get("name") or "").strip()
    items = long_term_memory_items(profile)
    has_memory = (
        profile != default_profile
        or bool(likes)
        or bool(dislikes)
        or bool(key_memories)
        or bool(name and name.lower() != "unknown")
        or bool(items)
    )
    counts = {
        "likes": len(likes),
        "dislikes": len(dislikes),
        "key_memories": len(key_memories),
    }
    summary_parts = []
    if name and name.lower() != "unknown":
        summary_parts.append(f"name: {name}")
    if counts["likes"]:
        summary_parts.append(f"{counts['likes']} like(s)")
    if counts["dislikes"]:
        summary_parts.append(f"{counts['dislikes']} dislike(s)")
    if counts["key_memories"]:
        summary_parts.append(f"{counts['key_memories']} key memory item(s)")
    return {
        "enabled": bool(use_long_term_memory),
        "persistent": True,
        "has_memory": bool(has_memory),
        "profile": profile,
        "items": items,
        "counts": counts,
        "summary": ", ".join(summary_parts) if summary_parts else "No saved long-term memories yet.",
    }


def long_term_memory_items(profile):
    if not isinstance(profile, dict):
        return []
    items = []
    name = str(profile.get("name") or "").strip()
    if name and name.lower() != "unknown":
        items.append({
            "field": "name",
            "index": None,
            "kind": "name",
            "label": "Name",
            "text": name,
        })

    known_fields = ("likes", "dislikes", "key_memories")
    extra_fields = sorted(
        key
        for key, value in profile.items()
        if key not in (*known_fields, "name") and isinstance(value, list)
    )
    for field in (*known_fields, *extra_fields):
        values = profile.get(field)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            text = str(value).strip()
            if not text:
                continue
            items.append({
                "field": field,
                "index": index,
                "kind": "list",
                "label": _memory_field_label(field),
                "text": text,
            })
    return items


def _memory_field_label(field):
    labels = {
        "likes": "Like",
        "dislikes": "Dislike",
        "key_memories": "Key Memory",
    }
    if field in labels:
        return labels[field]
    words = str(field or "memory").replace("_", " ").split()
    return " ".join(word.capitalize() for word in words) or "Memory"


def persona_prompts_for_ui(settings):
    return settings.persona_prompt_options()


def _ollama_model_names_match(left, right):
    left = normalize_ollama_model(left)
    right = normalize_ollama_model(right)
    if left == right:
        return True
    return f"{left}:latest" == right or left == f"{right}:latest"


def _matching_model_detail(model, items):
    for item in list(items or []):
        if _ollama_model_names_match(item.get("name"), model):
            return item
    return {}


def _installed_model_candidates(model_options, installed_models):
    installed_names = [
        normalize_ollama_model(item.get("name"))
        for item in list(installed_models or [])
        if normalize_ollama_model(item.get("name"))
    ]
    candidates = []
    for model in list(model_options or []) + installed_names:
        normalized = normalize_ollama_model(model)
        if not normalized:
            continue
        if any(_ollama_model_names_match(normalized, item) for item in candidates):
            continue
        if any(_ollama_model_names_match(normalized, installed) for installed in installed_names):
            candidates.append(normalized)
    return candidates


def ollama_model_details_payload(models, installed_models, running_models, current_model, gpu_status):
    details = {}
    current_model = normalize_ollama_model(current_model)
    for model in list(models or []):
        normalized = normalize_ollama_model(model)
        if not normalized:
            continue
        installed = _matching_model_detail(normalized, installed_models)
        running = _matching_model_detail(normalized, running_models)
        known = KNOWN_OLLAMA_MODEL_DETAILS.get(normalized, {})
        size = int((installed or running or known).get("size") or 0)
        size_label = (
            installed.get("size_label")
            or running.get("size_label")
            or known.get("size_label")
            or format_bytes(size)
        )
        source = (
            "installed" if installed
            else "running" if running
            else known.get("source", "")
        )
        detail = {
            "name": normalized,
            "size": size,
            "size_label": size_label,
            "size_source": source,
            "installed": bool(installed),
            "running": bool(running),
            "warning": "",
        }
        if running.get("size_vram_reported"):
            detail["size_vram"] = int(running.get("size_vram") or 0)
            detail["size_vram_label"] = running.get("size_vram_label") or format_bytes(running.get("size_vram"))
        if _ollama_model_names_match(normalized, current_model) and gpu_status.get("warning"):
            detail["warning"] = gpu_status["warning"]
        details[normalized] = detail
    return details


def ollama_gpu_status_payload(current_model, running_models, error=""):
    running = list(running_models or [])
    payload = {
        "state": "unknown",
        "accelerated": None,
        "message": "Ollama GPU status has not been checked.",
        "warning": "",
        "setup_warning": "",
        "current_model_running": False,
        "current_model_size": 0,
        "current_model_size_label": "",
        "current_model_size_vram": 0,
        "current_model_size_vram_label": "",
        "current_model_size_vram_reported": False,
        "running_models": running,
    }
    if error:
        payload["message"] = f"Ollama GPU status could not be checked: {error}"
        return payload
    if not running:
        payload.update({
            "state": "not_loaded",
            "message": "Ollama GPU use is unknown until the selected model is loaded.",
        })
        return payload

    current = None
    for item in running:
        if _ollama_model_names_match(item.get("name"), current_model):
            current = item
            break
    if not current:
        names = ", ".join(item.get("name", "") for item in running if item.get("name"))
        payload.update({
            "state": "not_loaded",
            "message": (
                f"Ollama is running {names}, but the selected model is not loaded yet."
                if names
                else "Ollama has running models, but the selected model is not loaded yet."
            ),
        })
        return payload

    size = int(current.get("size") or 0)
    size_vram = int(current.get("size_vram") or 0)
    size_vram_reported = current.get("size_vram_reported")
    if size_vram_reported is None:
        size_vram_reported = "size_vram" in current
    processor = str(current.get("processor") or current.get("processor_label") or "").strip()
    processor_upper = processor.upper()
    payload.update({
        "current_model_running": True,
        "current_model_size": size,
        "current_model_size_label": format_bytes(size),
        "current_model_size_vram": size_vram,
        "current_model_size_vram_label": format_bytes(size_vram),
        "current_model_size_vram_reported": bool(size_vram_reported),
    })
    if not size_vram_reported:
        payload.update({
            "state": "unknown",
            "message": "Ollama did not report VRAM use for the selected model.",
        })
        return payload
    if size_vram <= 0:
        warning = (
            "Ollama reports the selected model is running in system memory only. "
            "Chat may be slow; if this machine has a supported GPU or the model "
            "is too large for the current GPU runtime, check the README Ollama "
            "GPU notes."
        )
        payload.update({
            "state": "cpu",
            "accelerated": False,
            "message": "Ollama reports the selected model is CPU-only right now.",
            "warning": warning,
            "setup_warning": warning,
        })
        return payload
    if "CPU" in processor_upper and "GPU" in processor_upper and "100% GPU" not in processor_upper:
        warning = (
            "Ollama reports the selected model is split between GPU and "
            f"system memory ({processor}). It may be slow."
        )
        payload.update({
            "state": "partial_gpu",
            "accelerated": True,
            "message": (
                "Ollama reports partial GPU use for the selected model "
                f"({processor})."
            ),
            "warning": warning,
            "setup_warning": warning,
        })
        return payload

    total_text = f"; {format_bytes(size)} total loaded" if size > 0 else ""
    payload.update({
        "state": "gpu",
        "accelerated": True,
        "message": (
            "Ollama reports GPU use for the selected model"
            f" ({format_bytes(size_vram)} VRAM{total_text})."
        ),
    })
    return payload


def ollama_status_payload(
    *,
    settings,
    llm,
    base_url,
    pull_snapshot,
    installed_models,
    running_models=None,
    load_model_for_status=None,
):
    current_model = normalize_ollama_model(llm.model)
    diagnostics_level = settings.ollama_diagnostics_level
    model_options = ollama_models_for_ui(settings, llm)
    gpu_status = ollama_gpu_status_payload(current_model, [])
    thinking_enabled = bool(getattr(llm, "thinking_enabled", False))
    payload = {
        "available": False,
        "base_url": base_url,
        "current_model": current_model,
        "thinking_enabled": thinking_enabled,
        "current_model_installed": False,
        "installed_models": [],
        "installed_model_names": [],
        "model_selection_required": False,
        "installed_model_candidates": [],
        "suggested_model": "",
        "download": pull_snapshot(),
        "diagnostics_level": diagnostics_level,
        "llm_diagnostics": llm.diagnostics(include_raw=diagnostics_level == "debug"),
        "gpu_status": gpu_status,
        "model_details": ollama_model_details_payload(model_options, [], [], current_model, gpu_status),
        "message": "Ollama is not reachable. Start Ollama before downloading or using local models.",
    }
    try:
        installed = installed_models()
    except Exception as exc:
        payload["error"] = str(exc)
        return payload
    running_error = ""
    running = []
    if running_models:
        try:
            running = running_models()
        except Exception as exc:
            running_error = str(exc)

    current_model_installed = bool(_matching_model_detail(current_model, installed))
    installed_model_candidates = (
        [] if current_model_installed else _installed_model_candidates(model_options, installed)
    )
    suggested_model = installed_model_candidates[0] if installed_model_candidates else ""
    preflight_load = {}
    if (
        current_model_installed
        and not running_error
        and running_models
        and load_model_for_status
        and not _matching_model_detail(current_model, running)
    ):
        try:
            preflight_load = load_model_for_status(current_model) or {}
        except Exception as exc:
            preflight_load = {"ok": False, "error": str(exc)}
        if preflight_load.get("ok", True):
            try:
                running = running_models()
            except Exception as exc:
                running_error = str(exc)
    names = [item["name"] for item in installed]
    gpu_status = ollama_gpu_status_payload(current_model, running, running_error)
    if preflight_load:
        gpu_status["preflight_load"] = preflight_load
        if preflight_load.get("ok") is False and gpu_status.get("state") == "not_loaded":
            error = str(preflight_load.get("error") or "unknown error").strip()
            gpu_status["message"] = f"Ollama could not load the selected model for GPU status: {error}"
    payload.update({
        "available": True,
        "installed_models": installed,
        "installed_model_names": names,
        "current_model_installed": current_model_installed,
        "model_selection_required": not current_model_installed,
        "installed_model_candidates": installed_model_candidates,
        "suggested_model": suggested_model,
        "gpu_status": gpu_status,
        "model_details": ollama_model_details_payload(model_options, installed, running, current_model, gpu_status),
    })
    if current_model_installed:
        payload["message"] = f"Current model is installed: {current_model}"
    elif suggested_model:
        payload["message"] = (
            f"Selected model is not installed: {current_model}. "
            f"Installed model available: {suggested_model}. Select it or download the selected model before chatting."
        )
    else:
        payload["message"] = f"Current model is not installed: {current_model}. Click Download Model before chatting."
    return payload


def ollama_status_pending_payload(*, settings, llm, base_url, pull_snapshot):
    current_model = normalize_ollama_model(llm.model)
    diagnostics_level = settings.ollama_diagnostics_level
    model_options = ollama_models_for_ui(settings, llm)
    gpu_status = ollama_gpu_status_payload(current_model, [])
    thinking_enabled = bool(getattr(llm, "thinking_enabled", False))
    gpu_status.update({
        "state": "unchecked",
        "message": "Ollama GPU status will refresh after startup.",
    })
    model_details = ollama_model_details_payload(model_options, [], [], current_model, gpu_status)
    for detail in model_details.values():
        detail["unchecked"] = True
        detail["installed"] = None
    return {
        "available": None,
        "unchecked": True,
        "base_url": base_url,
        "current_model": current_model,
        "thinking_enabled": thinking_enabled,
        "current_model_installed": None,
        "installed_models": [],
        "installed_model_names": [],
        "model_selection_required": False,
        "installed_model_candidates": [],
        "suggested_model": "",
        "download": pull_snapshot(),
        "diagnostics_level": diagnostics_level,
        "llm_diagnostics": llm.diagnostics(include_raw=diagnostics_level == "debug"),
        "gpu_status": gpu_status,
        "model_details": model_details,
        "message": "Checking Ollama model status...",
    }


def _setup_check_item(item_id, label, status, detail):
    return {
        "id": item_id,
        "label": label,
        "status": status,
        "detail": detail,
    }


def _setup_check_section(section_id, title, items):
    return {
        "id": section_id,
        "title": title,
        "items": items,
    }


def _selected_voice_input_provider(voice_input_setup):
    return (voice_input_setup.get("selected") or {}).get("provider") or VOICE_INPUT_PROVIDER_DISABLED


def _optional_dependency_status(is_available, provider_selected):
    if is_available:
        return "ok"
    return "error" if provider_selected else "info"


def _setup_summary(sections):
    statuses_by_section = {
        section.get("id"): [
            item.get("status")
            for item in section.get("items", [])
        ]
        for section in sections
    }
    statuses = [
        status
        for section_statuses in statuses_by_section.values()
        for status in section_statuses
    ]
    if "error" in statuses:
        blocking_errors = any(
            "error" in statuses_by_section.get(section_id, [])
            for section_id in {"core", "ollama"}
        )
        return {
            "status": "error",
            "message": (
                "Core app or selected model setup needs attention."
                if blocking_errors
                else "Core app is ready; selected optional features need setup."
            ),
        }
    if "warning" in statuses:
        return {
            "status": "warning",
            "message": "Setup check completed with performance or optional-dependency warnings.",
        }
    return {
        "status": "ok",
        "message": "Setup check passed for the currently selected configuration.",
    }


def _handy_connection_setup_items(*, handy_key, handy_transport="rest", bluetooth_status=None):
    transport = str(handy_transport or "rest")
    if transport == "browser_bluetooth":
        bluetooth = bluetooth_status if isinstance(bluetooth_status, dict) else {}
        connected = bool(bluetooth.get("connected"))
        status = str(bluetooth.get("status") or "").lower()
        device = str(bluetooth.get("device_name") or "").strip()
        message = str(bluetooth.get("message") or bluetooth.get("last_error") or "").strip()
        if connected:
            detail = message or (
                f"Local Bluetooth bridge is connected to {device}."
                if device
                else "Local Bluetooth bridge is connected."
            )
        elif status == "stale":
            detail = message or "Local Bluetooth browser bridge is stale. Reopen this tab or reconnect the Handy."
        elif message:
            detail = message
        else:
            detail = "Local Bluetooth is selected. Use the top-bar Bluetooth button to connect before controlling hardware."
        return [
            _setup_check_item(
                "handy-transport",
                "Handy transport",
                "ok",
                "Local Bluetooth selected.",
            ),
            _setup_check_item(
                "handy-bluetooth",
                "Local Bluetooth device",
                "ok" if connected else "warning",
                detail,
            ),
        ]
    return [
        _setup_check_item(
            "handy-transport",
            "Handy transport",
            "ok",
            "Cloud REST selected.",
        ),
        _setup_check_item(
            "handy-key",
            "Handy connection key",
            "ok" if handy_key else "warning",
            "Connection key is saved." if handy_key else "Add a Handy connection key before controlling hardware.",
        ),
    ]


def setup_check_payload(
    *,
    configured,
    handy_key,
    handy_transport="rest",
    bluetooth_status=None,
    ollama_status,
    voice_input_setup,
    local_tts_status,
    audio_provider,
    audio_enabled,
    elevenlabs_key,
):
    gpu_status = ollama_status.get("gpu_status") or {}
    ollama_items = [
        _setup_check_item(
            "ollama-server",
            "Ollama server",
            "ok" if ollama_status.get("available") else "error",
            ollama_status.get("message") or "Ollama status unavailable.",
        ),
        _setup_check_item(
            "ollama-model",
            "Selected Ollama model",
            "ok" if ollama_status.get("current_model_installed") else "warning",
            (
                f"{ollama_status.get('current_model')} is installed."
                if ollama_status.get("current_model_installed")
                else ollama_status.get("message") or "Download the selected model before chatting."
            ),
        ),
    ]
    if not ollama_status.get("available"):
        gpu_item = _setup_check_item(
            "ollama-gpu",
            "Ollama GPU acceleration",
            "info",
            "Start Ollama before checking whether the loaded model uses GPU memory.",
        )
    elif gpu_status.get("warning"):
        gpu_item = _setup_check_item(
            "ollama-gpu",
            "Ollama GPU acceleration",
            "warning",
            gpu_status.get("warning") or gpu_status.get("message") or "Ollama reports CPU-only inference.",
        )
    elif gpu_status.get("accelerated") is True:
        gpu_item = _setup_check_item(
            "ollama-gpu",
            "Ollama GPU acceleration",
            "ok",
            gpu_status.get("message") or "Ollama reports GPU use for the selected model.",
        )
    elif gpu_status.get("state") == "not_loaded":
        gpu_item = _setup_check_item(
            "ollama-gpu",
            "Ollama GPU acceleration",
            "info",
            gpu_status.get("message") or "Load the selected model once before checking GPU use.",
        )
    else:
        gpu_item = _setup_check_item(
            "ollama-gpu",
            "Ollama GPU acceleration",
            "warning",
            gpu_status.get("message") or "Ollama did not report whether the selected model uses VRAM.",
        )
    ollama_items.append(gpu_item)

    selected_voice = voice_input_setup.get("selected") or {}
    voice_provider = _selected_voice_input_provider(voice_input_setup)
    faster_selected = voice_provider == VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER
    parakeet_selected = voice_provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET
    faster_available = bool(voice_input_setup.get("faster_whisper_available"))
    ctranslate2_available = bool(voice_input_setup.get("ctranslate2_available"))
    ctranslate2_cuda_devices = int(voice_input_setup.get("ctranslate2_cuda_devices") or 0)
    nemo_available = bool(voice_input_setup.get("nemo_available"))
    parakeet_external_runtime = bool(voice_input_setup.get("parakeet_external_runtime"))
    parakeet_external_python = str(voice_input_setup.get("parakeet_external_python") or "").strip()
    parakeet_external_error = str(voice_input_setup.get("parakeet_external_error") or "").strip()
    torch = voice_input_setup.get("torch") or {}
    torch_cuda_error = str(torch.get("cuda_runtime_error") or torch.get("error") or "").strip()
    torch_cuda_usable = bool(torch.get("cuda_available")) and not torch_cuda_error
    voice_input_items = [
        _setup_check_item(
            "voice-input-provider",
            "Selected voice input provider",
            "info" if voice_provider == VOICE_INPUT_PROVIDER_DISABLED else (
                "error" if selected_voice.get("status_code") == "dependency_missing" else "ok"
            ),
            selected_voice.get("message") or "Voice input is disabled.",
        ),
        _setup_check_item(
            "voice-input-faster-whisper",
            "faster-whisper dependency",
            _optional_dependency_status(faster_available, faster_selected),
            (
                "faster-whisper is importable."
                if faster_available
                else "Install requirements.txt before using Local faster-whisper voice input."
            ),
        ),
        _setup_check_item(
            "voice-input-ctranslate2",
            "faster-whisper CUDA",
            (
                "ok"
                if ctranslate2_available and ctranslate2_cuda_devices > 0
                else "warning" if faster_selected else "info"
            ),
            (
                f"CTranslate2 sees {ctranslate2_cuda_devices} CUDA device(s)."
                if ctranslate2_available and ctranslate2_cuda_devices > 0
                else "CTranslate2 does not see CUDA devices; faster-whisper will use CPU unless you install a compatible GPU runtime."
            ),
        ),
        _setup_check_item(
            "voice-input-nemo",
            "NVIDIA Parakeet dependency",
            _optional_dependency_status(nemo_available, parakeet_selected),
            (
                f"External Parakeet runtime is available: {parakeet_external_python}."
                if nemo_available and parakeet_external_runtime and parakeet_external_python
                else "NVIDIA NeMo ASR is importable in the app runtime."
                if nemo_available
                else parakeet_external_error
                if parakeet_external_runtime and parakeet_external_error
                else "Use scripts/install_parakeet.ps1, or set STROKEGPT_PARAKEET_PYTHON to a compatible custom runtime, before using NVIDIA Parakeet voice input."
            ),
        ),
        _setup_check_item(
            "voice-input-parakeet-cuda",
            "NVIDIA Parakeet CUDA",
            "ok" if torch_cuda_usable else "error" if parakeet_selected and torch_cuda_error else "warning" if parakeet_selected else "info",
            (
                torch_cuda_error
                if torch_cuda_error
                else f"PyTorch sees CUDA ({torch.get('device_name') or 'GPU'})."
                if torch_cuda_usable
                else "PyTorch does not see CUDA; Parakeet is intended for a CUDA-capable environment."
            ),
        ),
    ]

    engines = local_tts_status.get("engines") or []
    selected_engine = next(
        (engine for engine in engines if engine.get("id") == local_tts_status.get("engine")),
        {},
    )
    output_local_selected = audio_provider == "local"
    output_enabled = bool(audio_enabled)
    local_tts_torch = local_tts_status.get("torch") or {}
    voice_output_items = [
        _setup_check_item(
            "voice-output-provider",
            "Selected voice output provider",
            "info" if not output_enabled else "ok",
            (
                local_tts_status.get("message")
                if output_local_selected
                else "ElevenLabs voice output is selected." if elevenlabs_key else "Voice output is off or ElevenLabs key is not set."
            ),
        ),
        _setup_check_item(
            "voice-output-chatterbox",
            "Local Chatterbox dependency",
            "ok" if selected_engine.get("available") else "error" if output_local_selected else "info",
            (
                f"{selected_engine.get('label') or local_tts_status.get('engine_label') or 'Local Chatterbox'} is installed."
                if selected_engine.get("available")
                else "Install requirements.txt before using local Chatterbox voice output."
            ),
        ),
        _setup_check_item(
            "voice-output-cuda",
            "Local voice CUDA",
            "ok" if local_tts_status.get("cuda_available") else "warning" if output_local_selected else "info",
            (
                f"PyTorch sees CUDA ({local_tts_torch.get('device_name') or local_tts_status.get('device') or 'GPU'})."
                if local_tts_status.get("cuda_available")
                else "PyTorch is CPU-only for local voice; Chatterbox can run but may be slow."
            ),
        ),
    ]

    sections = [
        _setup_check_section(
            "core",
            "Core App",
            [
                _setup_check_item(
                    "backend",
                    "Backend process",
                    "ok",
                    "Flask backend is running and serving setup checks.",
                ),
                *_handy_connection_setup_items(
                    handy_key=handy_key,
                    handy_transport=handy_transport,
                    bluetooth_status=bluetooth_status,
                ),
                _setup_check_item(
                    "configured",
                    "First-run setup",
                    "ok" if configured else "warning",
                    "Required first-run settings are present." if configured else "Finish the setup wizard before normal use.",
                ),
            ],
        ),
        _setup_check_section("ollama", "Ollama", ollama_items),
        _setup_check_section("voice-input", "Voice Input", voice_input_items),
        _setup_check_section("voice-output", "Voice Output", voice_output_items),
    ]
    return {
        "summary": _setup_summary(sections),
        "sections": sections,
    }


def motion_backends_payload():
    return [
        {
            "id": "continuous",
            "label": "Continuous position",
            "description": "Recommended default: fixed patterns run as live sampled motion until the next command or stop.",
            "experimental": False,
        },
        {
            "id": "hamp",
            "label": "HAMP legacy",
            "description": "Legacy bounded-oscillation path. Kept as a fallback, but fixed patterns lose shape fidelity here.",
            "experimental": False,
            "deprecated": True,
        },
        {
            "id": "position",
            "label": "Flexible position/script",
            "description": "Finite position/script playback for previews and compatibility.",
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
    diagnostics_levels,
    voice_input_status,
    motion_programs=None,
    motion_preferences=None,
    local_tts_status=None,
):
    local_tts_status = local_tts_status or audio.local_status()
    payload = {
        "configured": bool(
            (settings.handy_key or settings.handy_transport == "browser_bluetooth")
            and settings.min_depth < settings.max_depth
        ),
        "persona": settings.persona_desc,
        "persona_prompts": persona_prompts,
        "llm_prompt_mode": settings.llm_prompt_mode,
        "llm_prompt_mode_options": llm_prompt_mode_options(settings),
        "user_genitalia": settings.user_genitalia,
        "user_genitalia_custom": settings.user_genitalia_custom,
        "user_genitalia_options": user_genitalia_options(),
        "handy_key": settings.handy_key,
        "handy_firmware_version": settings.handy_firmware_version,
        "handy_api_v3_key": settings.handy_api_v3_key,
        "handy_transport": settings.handy_transport,
        "handy_transport_options": [
            {
                "id": "rest",
                "label": "Cloud REST",
                "description": "Use Handy cloud REST API with the saved connection key.",
            },
            {
                "id": "browser_bluetooth",
                "label": "Local Bluetooth",
                "description": "Experimental browser Web Bluetooth HSP transport for local timed-point streaming.",
            },
        ],
        "handy_firmware_options": [
            {
                "id": "fw4",
                "label": "Firmware v4 / API v3",
                "description": "Current Handy firmware path. Continuous backend can use API v3 HSP timed point streaming with the saved Handy connection key plus the public API v3 Application ID.",
            },
            {
                "id": "fw3",
                "label": "Firmware v3 / legacy",
                "description": "Legacy compatibility path using API v2 HDSP/HAMP direct commands.",
            },
        ],
        "handy_api_v3_enabled": bool(
            settings.handy_firmware_version == "fw4"
            and (
                settings.handy_transport == "browser_bluetooth"
                or (
                    settings.handy_key
                    and _handy_connection_key_valid_for_api_v3(settings.handy_key)
                    and settings.handy_api_v3_key
                )
            )
        ),
        "handy_api_v3_connection_key_valid": (
            True
            if settings.handy_transport == "browser_bluetooth" or not settings.handy_key
            else _handy_connection_key_valid_for_api_v3(settings.handy_key)
        ),
        "handy_api_v3_key_configured": bool(settings.handy_api_v3_key),
        "ai_name": settings.ai_name,
        "elevenlabs_key": settings.elevenlabs_api_key,
        "ollama_model": llm.model,
        "ollama_models": ollama_models,
        "ollama_thinking_enabled": bool(settings.ollama_thinking_enabled),
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
        "voice_input_status": voice_input_status,
        "voice_input_provider": settings.voice_input_provider,
        "voice_input_enabled": settings.voice_input_enabled,
        "voice_input_model": settings.voice_input_model,
        "voice_input_language": settings.voice_input_language,
        "voice_input_mode": settings.voice_input_mode,
        "voice_input_submit_mode": settings.voice_input_submit_mode,
        "voice_input_preview_required": settings.voice_input_preview_required,
        "voice_input_hands_free_sensitivity": settings.voice_input_hands_free_sensitivity,
        "voice_input_hands_free_silence_ms": settings.voice_input_hands_free_silence_ms,
        "voice_input_min_recording_ms": settings.voice_input_min_recording_ms,
        "voice_input_max_recording_ms": settings.voice_input_max_recording_ms,
        "voice_input_noise_suppression": settings.voice_input_noise_suppression,
        "voice_input_echo_cancellation": settings.voice_input_echo_cancellation,
        "voice_input_auto_gain_control": settings.voice_input_auto_gain_control,
        "voice_input_noise_floor_rms": settings.voice_input_noise_floor_rms,
        "voice_input_audio_preprocessing": settings.voice_input_audio_preprocessing,
        "voice_input_silence_trim": settings.voice_input_silence_trim,
        "voice_input_hands_free_mode_actions": settings.voice_input_hands_free_mode_actions,
        "voice_input_beam_size": settings.voice_input_beam_size,
        "voice_input_condition_on_previous_text": settings.voice_input_condition_on_previous_text,
        "voice_input_vad_threshold": settings.voice_input_vad_threshold,
        "voice_input_vad_min_silence_ms": settings.voice_input_vad_min_silence_ms,
        "voice_input_vad_speech_pad_ms": settings.voice_input_vad_speech_pad_ms,
        "min_depth": settings.min_depth,
        "max_depth": settings.max_depth,
        "min_speed": settings.min_speed,
        "max_speed": settings.max_speed,
        "motion_backend": settings.motion_backend,
        "motion_style": settings.motion_style,
        "motion_reverse_direction": settings.motion_reverse_direction,
        "motion_style_options": motion_style_options(),
        "motion_diagnostics_level": settings.motion_diagnostics_level,
        "ollama_diagnostics_level": settings.ollama_diagnostics_level,
        "motion_feedback_auto_disable": settings.motion_feedback_auto_disable,
        "motion_pattern_library_enabled_in_freestyle": settings.motion_pattern_library_enabled_in_freestyle,
        "motion_pattern_library_enabled_in_chat": settings.motion_pattern_library_enabled_in_chat,
        "allow_llm_edge_in_freestyle": settings.allow_llm_edge_in_freestyle,
        "allow_llm_edge_in_chat": settings.allow_llm_edge_in_chat,
        "allow_llm_mode_actions_in_chat": settings.allow_llm_mode_actions_in_chat,
        "autospeak_enabled": settings.autospeak_enabled,
        "autospeak_min_seconds": settings.autospeak_min_seconds,
        "autospeak_max_seconds": settings.autospeak_max_seconds,
        "autospeak_motion_autonomy": settings.autospeak_motion_autonomy,
        "autospeak_motion_autonomy_options": autospeak_motion_autonomy_options(),
        "use_long_term_memory": use_long_term_memory,
        "memory_status": long_term_memory_payload(settings, use_long_term_memory),
        "diagnostics_levels": diagnostics_levels,
        "motion_backends": motion_backends_payload(),
        "motion_patterns": motion_patterns,
        "motion_programs": motion_programs or {"programs": [], "errors": []},
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
    if motion_preferences is not None:
        payload["motion_preferences"] = motion_preferences
    return payload


def motion_pattern_catalog_payload(pattern_library, settings, feedback_history_limit):
    payload = enrich_catalog(
        pattern_library.catalog(settings.motion_pattern_enabled, settings.motion_pattern_feedback),
        settings.motion_pattern_weights,
    )
    payload["tag_suggestions"] = motion_tag_suggestions()
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


def motion_preference_payload(catalog, excluded_llm_pattern_ids=None, program_catalog=None):
    return build_motion_preference_payload(catalog, excluded_llm_pattern_ids, program_catalog)
