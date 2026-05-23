"""Isolated NVIDIA Parakeet worker.

This module runs under the optional Parakeet Python environment selected by
STROKEGPT_PARAKEET_PYTHON. Keeping NeMo imports here avoids coupling the main
app environment to the Parakeet dependency stack.
"""

import argparse
import contextlib
import inspect
import json
import os
import sys
import tempfile
import time
from pathlib import Path


RESULT_PREFIX = "STROKEGPT_PARAKEET_RESULT "
CUDA_KERNEL_IMAGE_ERROR = "no kernel image is available for execution on the device"


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
        "cuda_device_capability": "",
        "cuda_runtime_usable": False,
        "cuda_runtime_error": "",
        "device": "cpu",
    }
    try:
        import torch  # type: ignore[import-not-found]
    except Exception as exc:
        status["error"] = str(exc)
        return status

    status["torch_available"] = True
    status["torch_version"] = getattr(torch, "__version__", "")
    try:
        status["cuda_available"] = bool(torch.cuda.is_available())
        status["cuda_version"] = getattr(torch.version, "cuda", "") or ""
        status["device_count"] = int(torch.cuda.device_count()) if status["cuda_available"] else 0
        status["device_name"] = torch.cuda.get_device_name(0) if status["cuda_available"] else ""
        if status["cuda_available"] and hasattr(torch.cuda, "get_device_capability"):
            capability = torch.cuda.get_device_capability(0)
            status["cuda_device_capability"] = ".".join(str(part) for part in capability)
    except Exception as exc:
        status["error"] = str(exc)
        return status
    explicit = (device_override or "").strip().lower()
    status["device"] = explicit if explicit and explicit != "auto" else ("cuda" if status["cuda_available"] else "cpu")
    if status["device"].startswith("cuda"):
        try:
            _check_cuda_runtime(torch, status["device"])
            status["cuda_runtime_usable"] = True
        except Exception as exc:
            status["cuda_runtime_error"] = _parakeet_cuda_error_message(str(exc), status)
            status["error"] = status["cuda_runtime_error"]
    return status


def _check_cuda_runtime(torch, device):
    sample = torch.ones((1,), device=device)
    sample = sample + 1
    if hasattr(torch.cuda, "synchronize"):
        torch.cuda.synchronize()
    return sample


def _parakeet_cuda_error_message(error, status):
    device_name = status.get("device_name") or "the selected NVIDIA GPU"
    capability = status.get("cuda_device_capability") or "unknown"
    base = (
        f"PyTorch sees CUDA device {device_name} (compute capability {capability}), "
        f"but a CUDA test kernel failed: {error}"
    )
    if CUDA_KERNEL_IMAGE_ERROR in error.lower():
        return (
            f"{base}. The installed PyTorch/CUDA wheel likely does not support this GPU. "
            "Switch Voice Input provider to Local faster-whisper, or install a Parakeet "
            "runtime built for this GPU/CUDA stack."
        )
    return (
        f"{base}. Switch Voice Input provider to Local faster-whisper, or repair the "
        "isolated Parakeet CUDA runtime."
    )


def _raise_for_unusable_selected_device(torch_status):
    if str(torch_status.get("device") or "").startswith("cuda") and torch_status.get("cuda_runtime_error"):
        raise RuntimeError(torch_status["cuda_runtime_error"])


def _transcript_from_nemo_output(output):
    if output is None:
        return ""
    if hasattr(output, "text"):
        return str(output.text or "").strip()
    if isinstance(output, dict):
        return str(output.get("text") or output.get("transcript") or "").strip()
    return str(output or "").strip()


@contextlib.contextmanager
def _ignore_temporary_directory_cleanup_errors():
    original_temporary_directory = tempfile.TemporaryDirectory

    def temporary_directory(*args, **kwargs):
        kwargs.setdefault("ignore_cleanup_errors", True)
        return original_temporary_directory(*args, **kwargs)

    tempfile.TemporaryDirectory = temporary_directory
    try:
        yield
    finally:
        tempfile.TemporaryDirectory = original_temporary_directory


def _transcribe_with_nemo(model, audio):
    requested_kwargs = {
        "batch_size": 1,
        "channel_selector": "average",
        "num_workers": 0,
        "use_lhotse": False,
        "verbose": False,
    }
    with _ignore_temporary_directory_cleanup_errors():
        return model.transcribe(
            [str(Path(audio))],
            **_transcribe_kwargs_for_model(model, requested_kwargs),
        )


def _transcribe_kwargs_for_model(model, requested_kwargs):
    try:
        parameters = inspect.signature(model.transcribe).parameters
    except (TypeError, ValueError):
        return {}
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return dict(requested_kwargs)
    return {key: value for key, value in requested_kwargs.items() if key in parameters}


def _numpy_dtype_values(numpy_module, names):
    values = []
    seen = set()
    for name in names:
        value = getattr(numpy_module, name, None)
        if value is None:
            continue
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)
        values.append(value)
    return values


def _install_numpy_compat():
    try:
        import numpy as np  # type: ignore[import-not-found]
    except Exception:
        return

    if not hasattr(np, "sctypes"):
        # Some NeMo transitive dependencies still read np.sctypes during
        # import. NumPy 2 removed it, so provide the narrow legacy shape they
        # expect instead of letting the voice worker fail before model load.
        np.sctypes = {
            "int": _numpy_dtype_values(np, ("int8", "int16", "int32", "int64", "int_")),
            "uint": _numpy_dtype_values(np, ("uint8", "uint16", "uint32", "uint64")),
            "float": _numpy_dtype_values(np, ("float16", "float32", "float64", "longdouble")),
            "complex": _numpy_dtype_values(np, ("complex64", "complex128", "clongdouble")),
            "others": _numpy_dtype_values(np, ("bool_", "bytes_", "str_", "object_", "void")),
        }

    legacy_aliases = {
        "bool": getattr(np, "bool_", bool),
        "int": int,
        "float": float,
        "complex": complex,
        "object": object,
        "str": str,
    }
    numpy_attrs = getattr(np, "__dict__", {})
    for name, value in legacy_aliases.items():
        if name not in numpy_attrs:
            setattr(np, name, value)


def _install_windows_signal_compat():
    if os.name != "nt":
        return
    import signal

    if not hasattr(signal, "SIGKILL") and hasattr(signal, "SIGTERM"):
        # Windows Python does not expose SIGKILL. Some NeMo transitive
        # dependencies reference the constant during import, so alias it to
        # SIGTERM before importing that stack.
        signal.SIGKILL = signal.SIGTERM


def _install_nemo_dependency_compat():
    _install_windows_signal_compat()
    _install_numpy_compat()


def _import_nemo():
    _install_nemo_dependency_compat()
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
    error = str(torch.get("cuda_runtime_error") or "")
    if error:
        nemo_available = False
    else:
        try:
            _import_nemo()
            nemo_available = True
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
    _raise_for_unusable_selected_device(torch)
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
    outputs = _transcribe_with_nemo(model, audio)
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
    _raise_for_unusable_selected_device(torch)
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
    _raise_for_unusable_selected_device(torch)
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
