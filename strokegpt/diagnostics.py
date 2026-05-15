import ctypes
import os
import platform
import shutil
import subprocess
import time
import wave

import requests

from .asr import VoiceInputError
from .payloads import format_bytes


def _diagnostic_status(severity):
    if severity == "error":
        return "error"
    if severity == "warning":
        return "warning"
    if severity == "skipped":
        return "skipped"
    return "ok"


def _duration_ns_to_ms(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number / 1_000_000)


def _latency_summary(tests):
    if any(test.get("status") == "error" for test in tests):
        return {
            "status": "error",
            "message": "Latency diagnostics found a failing runtime check.",
        }
    if any(test.get("status") in {"warning", "skipped"} for test in tests):
        return {
            "status": "warning",
            "message": "Latency diagnostics completed with warnings or skipped checks.",
        }
    return {
        "status": "ok",
        "message": "Latency diagnostics completed.",
    }


def _diagnostic_voice_input_clip_path(diagnostics_dir):
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    clip_path = diagnostics_dir / "voice-input-latency-check.wav"
    sample_rate = 16_000
    duration_seconds = 0.8
    frames = int(sample_rate * duration_seconds)
    with wave.open(str(clip_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)
    return clip_path


def _ollama_ping_latency_test(base_url):
    started_at = time.perf_counter()
    try:
        response = requests.get(f"{base_url}/api/version", timeout=5)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        response.raise_for_status()
        version = ""
        try:
            version = response.json().get("version", "")
        except Exception:
            pass
        detail = "Ollama status endpoint responded."
        if version:
            detail += f" Version: {version}."
        return {
            "id": "ollama-ping",
            "label": "Ollama status",
            "status": "ok",
            "elapsed_ms": elapsed_ms,
            "detail": detail,
        }
    except Exception as exc:
        return {
            "id": "ollama-ping",
            "label": "Ollama status",
            "status": "error",
            "detail": f"Ollama did not answer the status check: {exc}",
        }


def _ollama_generation_latency_test(llm_url, llm, ollama_status):
    status = ollama_status()
    if not status.get("available"):
        return {
            "id": "ollama-generation",
            "label": "Ollama response",
            "status": "skipped",
            "detail": status.get("message") or "Ollama is not reachable.",
        }
    if not status.get("current_model_installed"):
        return {
            "id": "ollama-generation",
            "label": "Ollama response",
            "status": "skipped",
            "detail": f"Install {status.get('current_model') or 'the selected model'} before measuring response latency.",
        }

    started_at = time.perf_counter()
    try:
        response = requests.post(
            llm_url,
            json={
                "model": llm.model,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": 'Return compact JSON only: {"chat":"ok","move":null,"new_mood":null}',
                    },
                    {"role": "user", "content": "diagnostics latency ping"},
                ],
                "options": {"temperature": 0},
            },
            timeout=60,
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        response.raise_for_status()
        data = response.json()
        total_ms = _duration_ns_to_ms(data.get("total_duration"))
        load_ms = _duration_ns_to_ms(data.get("load_duration"))
        eval_ms = _duration_ns_to_ms(data.get("eval_duration"))
        metrics = {
            "http_ms": elapsed_ms,
            "ollama_total_ms": total_ms,
            "ollama_load_ms": load_ms,
            "ollama_eval_ms": eval_ms,
            "eval_count": data.get("eval_count"),
        }
        detail = f"{llm.model} responded in {elapsed_ms} ms."
        if total_ms:
            detail += f" Ollama total: {total_ms} ms."
        if load_ms:
            detail += f" Load: {load_ms} ms."
        return {
            "id": "ollama-generation",
            "label": "Ollama response",
            "status": "ok",
            "elapsed_ms": elapsed_ms,
            "detail": detail,
            "metrics": metrics,
        }
    except Exception as exc:
        return {
            "id": "ollama-generation",
            "label": "Ollama response",
            "status": "error",
            "detail": f"Ollama response latency check failed: {exc}",
        }


def _voice_input_latency_test(voice_input, diagnostics_dir):
    status = voice_input.status()
    if not status.get("can_transcribe"):
        return {
            "id": "voice-input",
            "label": "Voice input ASR",
            "status": "skipped",
            "detail": status.get("message") or "Load a voice input model before measuring ASR latency.",
        }

    try:
        clip_path = _diagnostic_voice_input_clip_path(diagnostics_dir)
        started_at = time.perf_counter()
        result = voice_input.transcribe_file(clip_path)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        timings = dict(result.get("timings") or {})
        transcribe_ms = timings.get("transcribe_ms")
        result_status = result.get("status") or "unknown"
        return {
            "id": "voice-input",
            "label": "Voice input ASR",
            "status": "ok",
            "elapsed_ms": elapsed_ms,
            "detail": (
                f"{result.get('model') or status.get('model') or 'Selected ASR model'} handled "
                f"a generated 0.8s quiet diagnostic clip. Result: {result_status}."
            ),
            "metrics": {
                "wall_ms": elapsed_ms,
                "transcribe_ms": transcribe_ms,
                "asr_attempts": timings.get("asr_attempts"),
                "provider": result.get("provider") or status.get("provider"),
                "model": result.get("model") or status.get("model"),
            },
        }
    except VoiceInputError as exc:
        return {
            "id": "voice-input",
            "label": "Voice input ASR",
            "status": "error",
            "detail": f"Voice input latency check failed: {exc}",
        }
    except Exception as exc:
        return {
            "id": "voice-input",
            "label": "Voice input ASR",
            "status": "error",
            "detail": f"Voice input latency check failed: {exc}",
        }


def _voice_output_latency_test(audio):
    result = audio.measure_output_latency("Ready.")
    status = _diagnostic_status(result.get("status"))
    elapsed_ms = result.get("elapsed_ms")
    metrics = {
        "provider": result.get("provider"),
        "engine": result.get("engine"),
        "device": result.get("device"),
        "audio_bytes": result.get("audio_bytes"),
    }
    detail = result.get("message") or "Voice output latency check completed."
    if elapsed_ms is not None:
        detail = f"{detail} Elapsed: {elapsed_ms} ms."
    return {
        "id": "voice-output",
        "label": "Voice output",
        "status": status,
        "elapsed_ms": elapsed_ms,
        "detail": detail,
        "metrics": metrics,
    }


def diagnostics_latency_payload(*, base_url, llm_url, llm, voice_input, audio, diagnostics_dir, ollama_status):
    tests = [
        _ollama_ping_latency_test(base_url),
        _ollama_generation_latency_test(llm_url, llm, ollama_status),
        _voice_input_latency_test(voice_input, diagnostics_dir),
        _voice_output_latency_test(audio),
    ]
    return {
        "summary": _latency_summary(tests),
        "tests": tests,
        "generated_at": int(time.time()),
    }


def _safe_text(value, fallback="unknown"):
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _yes_no(value):
    if value is None:
        return "unknown"
    return "yes" if bool(value) else "no"


def _total_memory_bytes():
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:
            return 0
        return 0

    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages) * int(page_size)
    except (AttributeError, OSError, ValueError):
        return 0


def _nvidia_smi_status():
    command = shutil.which("nvidia-smi")
    if not command:
        return {
            "available": False,
            "path": "",
            "gpus": [],
            "message": "nvidia-smi was not found on PATH.",
        }

    flags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [
                command,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=flags,
            check=False,
        )
    except Exception as exc:
        return {
            "available": True,
            "path": command,
            "gpus": [],
            "message": f"nvidia-smi could not be queried: {exc}",
        }

    gpus = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if not parts or not parts[0]:
                continue
            memory_mb = 0
            if len(parts) >= 3:
                try:
                    memory_mb = int(float(parts[2]))
                except (TypeError, ValueError):
                    memory_mb = 0
            gpus.append({
                "name": parts[0],
                "driver_version": parts[1] if len(parts) >= 2 else "",
                "memory_total_mb": memory_mb,
                "memory_total_label": format_bytes(memory_mb * 1024 * 1024),
            })
    message = (
        f"nvidia-smi reports {len(gpus)} NVIDIA GPU(s)."
        if gpus
        else (result.stderr or result.stdout or "nvidia-smi did not report GPUs.").strip()
    )
    return {
        "available": True,
        "path": command,
        "gpus": gpus,
        "message": message,
    }


def _system_specs():
    total_memory = _total_memory_bytes()
    return {
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_bits": platform.architecture()[0],
        "cpu_count": os.cpu_count(),
        "memory_total_bytes": total_memory,
        "memory_total_label": format_bytes(total_memory),
        "nvidia_smi": _nvidia_smi_status(),
    }


def _torch_summary(torch_status):
    torch_status = dict(torch_status or {})
    return {
        "torch_available": bool(torch_status.get("torch_available")),
        "torch_version": torch_status.get("torch_version") or "",
        "cuda_available": bool(torch_status.get("cuda_available")),
        "cuda_version": torch_status.get("cuda_version") or "",
        "device_count": int(torch_status.get("device_count") or 0),
        "device_name": torch_status.get("device_name") or "",
        "device": torch_status.get("device") or "cpu",
        "error": torch_status.get("error") or torch_status.get("cuda_runtime_error") or "",
    }


def _format_system_status_report(payload):
    system = payload.get("system") or {}
    app = payload.get("app") or {}
    ollama = app.get("ollama") or {}
    motion = app.get("motion") or {}
    voice_input = app.get("voice_input") or {}
    voice_output = app.get("voice_output") or {}
    nvidia = system.get("nvidia_smi") or {}
    voice_input_torch = voice_input.get("torch") or {}
    voice_output_torch = voice_output.get("torch") or {}

    lines = [
        "StrokeGPT-ReVibed Diagnostics",
        f"Generated: {payload.get('generated_at_iso') or 'unknown'}",
        "",
        "System Specifications",
        f"- OS: {_safe_text(system.get('os'))}",
        f"- Machine: {_safe_text(system.get('machine'))}",
        f"- Processor: {_safe_text(system.get('processor'))}",
        f"- CPU cores: {_safe_text(system.get('cpu_count'))}",
        f"- Memory: {_safe_text(system.get('memory_total_label'))}",
        f"- Python: {_safe_text(system.get('python_implementation'))} {_safe_text(system.get('python_version'))} ({_safe_text(system.get('python_bits'))})",
        f"- NVIDIA SMI: {nvidia.get('message') or 'unknown'}",
    ]
    for gpu in nvidia.get("gpus") or []:
        lines.append(
            f"  - {gpu.get('name') or 'NVIDIA GPU'}; driver {gpu.get('driver_version') or 'unknown'}; VRAM {gpu.get('memory_total_label') or 'unknown'}"
        )

    lines.extend([
        "",
        "Current App Status",
        f"- Motion backend: {_safe_text(motion.get('backend'))}",
        f"- Motion paused: {_yes_no(motion.get('paused'))}",
        f"- Active mode: {_safe_text(motion.get('active_mode'), 'none')}",
        f"- Handy firmware: {_safe_text(motion.get('handy_firmware_version'))}",
        f"- Handy API v3 configured: {_yes_no(motion.get('handy_api_v3_key_configured'))}",
        "",
        "Ollama",
        f"- Reachable: {_yes_no(ollama.get('available'))}",
        f"- Base URL: {_safe_text(ollama.get('base_url'))}",
        f"- Selected model: {_safe_text(ollama.get('current_model'))}",
        f"- Selected model installed: {_yes_no(ollama.get('current_model_installed'))}",
        f"- Selected model loaded: {_yes_no(ollama.get('current_model_running'))}",
        f"- GPU state: {_safe_text(ollama.get('gpu_state'))}",
        f"- GPU detail: {_safe_text(ollama.get('gpu_message'))}",
        f"- Loaded VRAM: {_safe_text(ollama.get('current_model_size_vram_label'))}",
        f"- Loaded total size: {_safe_text(ollama.get('current_model_size_label'))}",
    ])
    running_models = ollama.get("running_models") or []
    if running_models:
        lines.append("- Running models:")
        for model in running_models:
            vram = model.get("size_vram_label") or "unknown VRAM"
            processor = model.get("processor") or "processor unknown"
            lines.append(f"  - {model.get('name') or 'unknown'}; {vram}; {processor}")

    lines.extend([
        "",
        "CUDA / Voice Runtime",
        f"- Voice input provider: {_safe_text(voice_input.get('provider'))}",
        f"- Voice input enabled: {_yes_no(voice_input.get('enabled'))}",
        f"- Voice input model: {_safe_text(voice_input.get('model'))}",
        f"- Voice input model loaded: {_yes_no(voice_input.get('model_loaded'))}",
        f"- Voice input PyTorch: {_safe_text(voice_input_torch.get('torch_version'))}; CUDA {_yes_no(voice_input_torch.get('cuda_available'))}; device {_safe_text(voice_input_torch.get('device_name') or voice_input_torch.get('device'))}",
        f"- Voice input CTranslate2 CUDA devices: {_safe_text(voice_input.get('ctranslate2_cuda_devices'))}",
        f"- Voice output provider: {_safe_text(voice_output.get('provider'))}",
        f"- Voice output enabled: {_yes_no(voice_output.get('enabled'))}",
        f"- Local voice model loaded: {_yes_no(voice_output.get('model_loaded'))}",
        f"- Local voice PyTorch: {_safe_text(voice_output_torch.get('torch_version'))}; CUDA {_yes_no(voice_output_torch.get('cuda_available'))}; device {_safe_text(voice_output_torch.get('device_name') or voice_output_torch.get('device'))}",
    ])
    return "\n".join(lines)


def diagnostics_system_status_payload(*, settings, llm, audio, voice_input, ollama_status, app_state, motion):
    ollama = ollama_status()
    gpu_status = ollama.get("gpu_status") or {}
    local_tts_status = audio.local_status()
    voice_input_status = voice_input.status()
    voice_input_setup = voice_input.setup_status()
    generated_at = int(time.time())
    payload = {
        "status": "success",
        "generated_at": generated_at,
        "generated_at_iso": time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(generated_at)),
        "system": _system_specs(),
        "app": {
            "motion": {
                "backend": getattr(motion, "backend", ""),
                "paused": bool(getattr(app_state, "motion_pause_active", False)),
                "active_mode": getattr(app_state, "active_mode_name", "") or "",
                "handy_firmware_version": settings.handy_firmware_version,
                "handy_key_configured": bool(settings.handy_key),
                "handy_api_v3_key_configured": bool(settings.handy_api_v3_key),
                "min_speed": settings.min_speed,
                "max_speed": settings.max_speed,
                "min_depth": settings.min_depth,
                "max_depth": settings.max_depth,
            },
            "ollama": {
                "available": ollama.get("available"),
                "base_url": ollama.get("base_url") or "",
                "current_model": ollama.get("current_model") or getattr(llm, "model", ""),
                "current_model_installed": ollama.get("current_model_installed"),
                "current_model_running": gpu_status.get("current_model_running"),
                "gpu_state": gpu_status.get("state") or "unknown",
                "gpu_accelerated": gpu_status.get("accelerated"),
                "gpu_message": gpu_status.get("message") or "",
                "gpu_warning": gpu_status.get("warning") or "",
                "current_model_size_label": gpu_status.get("current_model_size_label") or "",
                "current_model_size_vram_label": gpu_status.get("current_model_size_vram_label") or "",
                "running_models": gpu_status.get("running_models") or [],
                "installed_model_count": len(ollama.get("installed_model_names") or []),
                "download": ollama.get("download") or {},
                "message": ollama.get("message") or "",
            },
            "voice_input": {
                "provider": voice_input_status.get("provider") or "",
                "enabled": bool(voice_input_status.get("enabled")),
                "model": voice_input_status.get("model") or "",
                "model_loaded": bool(voice_input_status.get("model_loaded")),
                "model_cached": bool(voice_input_status.get("model_cached")),
                "status_code": voice_input_status.get("status_code") or "",
                "message": voice_input_status.get("message") or "",
                "torch": _torch_summary(voice_input_setup.get("torch")),
                "ctranslate2_available": bool(voice_input_setup.get("ctranslate2_available")),
                "ctranslate2_cuda_devices": int(voice_input_setup.get("ctranslate2_cuda_devices") or 0),
                "nemo_available": bool(voice_input_setup.get("nemo_available")),
                "parakeet_external_runtime": bool(voice_input_setup.get("parakeet_external_runtime")),
            },
            "voice_output": {
                "provider": settings.audio_provider,
                "enabled": bool(settings.audio_enabled),
                "engine": local_tts_status.get("engine") or "",
                "model_loaded": bool(local_tts_status.get("model_loaded")),
                "status": local_tts_status.get("status") or "",
                "message": local_tts_status.get("message") or "",
                "torch": _torch_summary(local_tts_status.get("torch")),
            },
        },
    }
    payload["text"] = _format_system_status_report(payload)
    return payload
