"""Isolated NVIDIA Parakeet worker.

This module runs under the optional Parakeet Python environment selected by
STROKEGPT_PARAKEET_PYTHON. Keeping NeMo imports here avoids coupling the main
app environment to the Parakeet dependency stack.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


RESULT_PREFIX = "STROKEGPT_PARAKEET_RESULT "


def _configure_cache(cache_dir):
    if not cache_dir:
        return
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_path))
    os.environ.setdefault("HF_HUB_CACHE", str(cache_path / "hub"))
    os.environ.setdefault("HF_XET_CACHE", str(cache_path / "xet"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def _torch_status(device_override):
    status = {
        "torch_available": False,
        "torch_version": "",
        "cuda_available": False,
        "cuda_version": "",
        "device_count": 0,
        "device_name": "",
        "device": "cpu",
    }
    try:
        import torch  # type: ignore[import-not-found]
    except Exception as exc:
        status["error"] = str(exc)
        return status

    status["torch_available"] = True
    status["torch_version"] = getattr(torch, "__version__", "")
    status["cuda_available"] = bool(torch.cuda.is_available())
    status["cuda_version"] = getattr(torch.version, "cuda", "") or ""
    status["device_count"] = int(torch.cuda.device_count()) if status["cuda_available"] else 0
    status["device_name"] = torch.cuda.get_device_name(0) if status["cuda_available"] else ""
    explicit = (device_override or "").strip().lower()
    status["device"] = explicit if explicit and explicit != "auto" else ("cuda" if status["cuda_available"] else "cpu")
    return status


def _transcript_from_nemo_output(output):
    if output is None:
        return ""
    if hasattr(output, "text"):
        return str(output.text or "").strip()
    if isinstance(output, dict):
        return str(output.get("text") or output.get("transcript") or "").strip()
    return str(output or "").strip()


def _import_nemo():
    import nemo.collections.asr as nemo_asr  # type: ignore[import-not-found]

    return nemo_asr


def _load_model(model_name, device):
    nemo_asr = _import_nemo()
    model = nemo_asr.models.ASRModel.from_pretrained(model_name=model_name)
    if hasattr(model, "to"):
        model.to(device)
    if hasattr(model, "eval"):
        model.eval()
    return model


def _check(args):
    torch = _torch_status(args.device)
    try:
        _import_nemo()
        nemo_available = True
        error = ""
    except Exception as exc:
        nemo_available = False
        error = str(exc)
    return {
        "ok": nemo_available,
        "nemo_available": nemo_available,
        "torch": torch,
        "python": sys.executable,
        "error": error,
    }


def _preload(args):
    _configure_cache(args.cache_dir)
    torch = _torch_status(args.device)
    started = time.perf_counter()
    _load_model(args.model, torch["device"])
    return {
        "ok": True,
        "model": args.model,
        "device": torch["device"],
        "torch": torch,
        "model_load_ms": int((time.perf_counter() - started) * 1000),
    }


def _transcribe_loaded_model(model, *, audio, language, model_name, device):
    if not audio:
        raise ValueError("audio is required for transcribe")
    started = time.perf_counter()
    outputs = model.transcribe([str(Path(audio))])
    output = outputs[0] if outputs else None
    transcript = _transcript_from_nemo_output(output)
    return {
        "ok": True,
        "status": "success" if transcript else "no_speech",
        "transcript": transcript,
        "language": "en" if language == "auto" else language,
        "model": model_name,
        "device": device,
        "timings": {
            "transcribe_ms": int((time.perf_counter() - started) * 1000),
            "asr_attempts": 1,
        },
    }


def _transcribe(args):
    _configure_cache(args.cache_dir)
    torch = _torch_status(args.device)
    model = _load_model(args.model, torch["device"])
    return _transcribe_loaded_model(
        model,
        audio=args.audio,
        language=args.language,
        model_name=args.model,
        device=torch["device"],
    )


def _serve(args):
    _configure_cache(args.cache_dir)
    torch = _torch_status(args.device)
    started = time.perf_counter()
    model = _load_model(args.model, torch["device"])
    _emit({
        "ok": True,
        "status": "ready",
        "model": args.model,
        "device": torch["device"],
        "torch": torch,
        "python": sys.executable,
        "model_load_ms": int((time.perf_counter() - started) * 1000),
    })

    for line in sys.stdin:
        request = {}
        request_id = None
        try:
            request = json.loads(line or "{}")
            request_id = request.get("request_id")
            action = str(request.get("action") or "").strip().lower()
            if action == "stop":
                _emit({"ok": True, "status": "stopped", "request_id": request_id})
                break
            if action != "transcribe":
                raise ValueError(f"Unsupported worker action: {action or '<empty>'}")
            language = str(request.get("language") or args.language or "auto").strip() or "auto"
            payload = _transcribe_loaded_model(
                model,
                audio=request.get("audio"),
                language=language,
                model_name=args.model,
                device=torch["device"],
            )
            payload["request_id"] = request_id
            _emit(payload)
        except Exception as exc:
            _emit({
                "ok": False,
                "error": str(exc),
                "request_id": request_id,
                "python": sys.executable,
            })
    return 0


def _emit(payload):
    print(f"{RESULT_PREFIX}{json.dumps(payload, sort_keys=True)}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices={"check", "preload", "transcribe", "serve"})
    parser.add_argument("--model", default="nvidia/parakeet-tdt-0.6b-v3")
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--device", default="")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--audio", default="")
    args = parser.parse_args(argv)

    try:
        if args.action == "check":
            payload = _check(args)
        elif args.action == "serve":
            return _serve(args)
        elif args.action == "preload":
            payload = _preload(args)
        else:
            if not args.audio:
                raise ValueError("--audio is required for transcribe")
            payload = _transcribe(args)
        _emit(payload)
        return 0 if payload.get("ok") else 1
    except Exception as exc:
        _emit({"ok": False, "error": str(exc), "python": sys.executable})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
