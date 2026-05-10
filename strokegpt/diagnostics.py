import time
import wave

import requests

from .asr import VoiceInputError


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
