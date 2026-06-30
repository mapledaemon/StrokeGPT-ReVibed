import json
import threading

import requests

from . import payloads
from .settings import normalize_ollama_model


def get_ollama_models_for_ui(settings, llm):
    return payloads.ollama_models_for_ui(settings, llm)


def _format_bytes(value):
    return payloads.format_bytes(value)


def _set_ollama_pull_state(app_state, **updates):
    return app_state.set_ollama_pull_state(**updates)


def _ollama_pull_snapshot(app_state):
    return app_state.ollama_pull_snapshot()


def _ollama_installed_models(base_url, *, format_bytes=_format_bytes, requests_module=requests):
    response = requests_module.get(f"{base_url}/api/tags", timeout=0.5)
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
            "size_label": format_bytes(item.get("size")),
        })
    models.sort(key=lambda item: item["name"].lower())
    return models


def _ollama_running_models(base_url, *, format_bytes=_format_bytes, requests_module=requests):
    response = requests_module.get(f"{base_url}/api/ps", timeout=0.5)
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
            "size_label": format_bytes(size),
            "size_vram": size_vram,
            "size_vram_label": format_bytes(size_vram),
            "size_vram_reported": size_vram_reported,
            "processor": str(item.get("processor") or item.get("processor_label") or "").strip(),
        })
    models.sort(key=lambda item: item["name"].lower())
    return models


def _ollama_load_model_for_status(base_url, model, *, requests_module=requests):
    model = normalize_ollama_model(model)
    if not model:
        return {"ok": False, "error": "Model name is required."}
    response = requests_module.post(
        f"{base_url}/api/generate",
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


def _ollama_status_payload(
    *,
    settings,
    llm,
    base_url,
    live=True,
    pull_snapshot,
    installed_models,
    running_models,
    load_model_for_status,
):
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
            base_url=base_url,
            pull_snapshot=pull_snapshot,
        )
    return payloads.ollama_status_payload(
        settings=settings,
        llm=llm,
        base_url=base_url,
        pull_snapshot=pull_snapshot,
        installed_models=installed_models,
        running_models=running_models,
        load_model_for_status=load_model_for_status,
    )


def _run_ollama_pull(
    model,
    *,
    base_url,
    set_pull_state,
    format_bytes=_format_bytes,
    requests_module=requests,
):
    set_pull_state(
        state="downloading",
        model=model,
        message=f"Downloading {model} with Ollama. This can be several GB.",
        completed=0,
        total=0,
        percent=None,
    )
    try:
        response = requests_module.post(
            f"{base_url}/api/pull",
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
                detail = f" ({format_bytes(completed)} / {format_bytes(total)}, {percent}%)"
            set_pull_state(
                state="downloading",
                model=model,
                message=f"{last_status}{detail}",
                completed=completed,
                total=total,
                percent=percent,
            )
        set_pull_state(
            state="ready",
            model=model,
            message=f"{model} is downloaded and ready.",
            completed=0,
            total=0,
            percent=100,
        )
    except Exception as exc:
        set_pull_state(
            state="error",
            model=model,
            message=f"Download failed for {model}: {exc}",
            completed=0,
            total=0,
            percent=None,
        )


def _start_ollama_pull(
    model,
    *,
    app_state,
    status_payload,
    set_pull_state,
    run_ollama_pull,
):
    model = normalize_ollama_model(model)
    if not model:
        return False, "Model name is required."

    status = status_payload()
    if model in status.get("installed_model_names", []):
        set_pull_state(
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
        app_state.ollama_pull_thread = threading.Thread(target=run_ollama_pull, args=(model,), daemon=True)
        app_state.ollama_pull_thread.start()
    return True, f"Started downloading {model}."
