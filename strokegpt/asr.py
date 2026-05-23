import importlib.util
import json
import os
import re
import subprocess
import threading
import time
import wave
from pathlib import Path

from .settings import (
    DEFAULT_VOICE_INPUT_BEAM_SIZE,
    DEFAULT_VOICE_INPUT_CONDITION_ON_PREVIOUS_TEXT,
    DEFAULT_VOICE_INPUT_HANDS_FREE_SENSITIVITY,
    DEFAULT_VOICE_INPUT_HANDS_FREE_SILENCE_MS,
    DEFAULT_VOICE_INPUT_MAX_RECORDING_MS,
    DEFAULT_VOICE_INPUT_MIN_RECORDING_MS,
    DEFAULT_VOICE_INPUT_MODEL,
    DEFAULT_VOICE_INPUT_NVIDIA_PARAKEET_MODEL,
    DEFAULT_VOICE_INPUT_AUDIO_PREPROCESSING,
    DEFAULT_VOICE_INPUT_NOISE_FLOOR_RMS,
    DEFAULT_VOICE_INPUT_SILENCE_TRIM,
    DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS,
    DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS,
    DEFAULT_VOICE_INPUT_VAD_THRESHOLD,
    VOICE_INPUT_MODE_PUSH_TO_TALK,
    VOICE_INPUT_PROVIDER_DISABLED,
    VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
    VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET,
    VOICE_INPUT_NVIDIA_PARAKEET_LARGE_MODEL,
    VOICE_INPUT_NVIDIA_PARAKEET_MODELS,
    VOICE_INPUT_SUBMIT_PREVIEW,
    _default_parakeet_python_path,
)


_HF_TRUE_VALUES = {"1", "true", "yes", "on"}
_MODEL_CACHE_MARKER_FILES = {
    "config.json",
    "model.bin",
    "model.safetensors",
    "parakeet-tdt-0.6b-v3.nemo",
    "parakeet-tdt-1.1b.nemo",
    "tokenizer.json",
    "vocabulary.json",
    "vocabulary.txt",
}
_MODEL_CACHE_SCAN_LIMIT = 5000
VOICE_INPUT_FAST_BEAM_SIZE = 1
VOICE_INPUT_CONFIDENCE_RERUN_AVG_LOGPROB = -1.0
VOICE_INPUT_CONFIDENCE_RERUN_NO_SPEECH_PROB = 0.6
VOICE_INPUT_REJECT_AVG_LOGPROB = -1.5
VOICE_INPUT_REJECT_MESSAGE = (
    "I didn't catch that. Try speaking closer to the microphone, reducing background noise, or using push-to-talk."
)
VOICE_INPUT_INITIAL_PROMPT = (
    "speed depth tip base shaft slow fast harder gentle stop pause resume edge milk"
)
VOICE_INPUT_FASTER_WHISPER_MODEL_IDS = {"tiny.en", "base.en", "small.en", "distil-large-v3"}
PARAKEET_WORKER_RESULT_PREFIX = "STROKEGPT_PARAKEET_RESULT "
PARAKEET_RUNTIME_STATUS_TTL_SECONDS = 10.0
PARAKEET_NORMALIZED_SAMPLE_RATE = 16000


class _ExternalParakeetRuntimeModel:
    def __init__(self, *, python, model, device, process):
        self.python = python
        self.model = model
        self.device = device
        self.process = process
        self._lock = threading.Lock()
        self._request_id = 0

    def _read_payload(self):
        while True:
            line = self.process.stdout.readline() if self.process.stdout else ""
            if line == "":
                stderr = ""
                try:
                    stderr = (self.process.stderr.read() if self.process.stderr else "") or ""
                except Exception:
                    stderr = ""
                detail = stderr.strip() or f"exit code {self.process.poll()}"
                raise VoiceInputUnavailable(f"NVIDIA Parakeet worker stopped before returning a payload: {detail}")
            if line.startswith(PARAKEET_WORKER_RESULT_PREFIX):
                return json.loads(line[len(PARAKEET_WORKER_RESULT_PREFIX):])

    def request(self, payload):
        with self._lock:
            if self.process.poll() is not None:
                raise VoiceInputUnavailable(f"NVIDIA Parakeet worker is not running (exit code {self.process.returncode}).")
            self._request_id += 1
            request_id = self._request_id
            message = dict(payload)
            message["request_id"] = request_id
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
            except Exception as exc:
                raise VoiceInputUnavailable(f"NVIDIA Parakeet worker input failed: {exc}") from exc
            response = self._read_payload()
            if response.get("request_id") not in {None, request_id}:
                raise VoiceInputUnavailable("NVIDIA Parakeet worker returned a mismatched response.")
            if not response.get("ok"):
                raise VoiceInputUnavailable(response.get("error") or "NVIDIA Parakeet worker failed.")
            return response

    def is_running(self):
        return self.process.poll() is None

    def close(self):
        process = self.process
        if process.poll() is not None:
            return
        try:
            if process.stdin:
                process.stdin.write(json.dumps({"action": "stop"}) + "\n")
                process.stdin.flush()
        except Exception:
            pass
        try:
            process.wait(timeout=3)
        except Exception:
            process.terminate()
            try:
                process.wait(timeout=3)
            except Exception:
                process.kill()


def _env_flag_enabled(name):
    return os.environ[name].lower() in _HF_TRUE_VALUES


def _module_available(module_name):
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _count_cuda_devices():
    """Return the number of CUDA devices visible to CTranslate2, or 0 on any
    failure. Isolated from :func:`_detect_device` so tests can mock the
    detection without reaching into the ``ctranslate2`` module itself.

    The lazy import matches the rest of this module: ``ctranslate2`` is a
    transitive dependency of ``faster_whisper`` and is not guaranteed to be
    importable on every install (e.g. CPU-only builds, missing wheels). Any
    import or runtime error here just means "no CUDA visible," which is the
    safe fallback.
    """
    try:
        import ctranslate2  # type: ignore[import-not-found]
        return int(ctranslate2.get_cuda_device_count() or 0)
    except Exception:
        return 0


def _detect_device(env_value):
    """Pick the faster-whisper device.

    Honors an explicit env override (case- and whitespace-insensitive) so a
    user with broken CUDA libs can pin ``cpu``, or pin a specific GPU index
    like ``cuda:1``. When the value is unset, empty, or ``auto``, falls back
    to runtime detection: ``cuda`` if any CUDA device is visible to
    CTranslate2, otherwise ``cpu``. The ~10x speedup from GPU is the single
    biggest ASR latency cliff for users who happen to have NVIDIA hardware,
    so the auto path defaults toward enabling it.
    """
    explicit = (env_value or "").strip().lower()
    if explicit and explicit != "auto":
        return explicit
    return "cuda" if _count_cuda_devices() > 0 else "cpu"


def _detect_compute_type(env_value, device):
    """Pick the CTranslate2 ``compute_type`` for the chosen device.

    Honors an explicit env override. When unset, empty, or ``auto``, picks
    ``float16`` on CUDA (nearly 2x faster than ``int8`` for similar Whisper
    accuracy at common model sizes) and ``int8`` on CPU (smaller memory
    footprint, faster on AVX2-capable laptops). Anything other than
    ``cuda``/``cuda:N`` defaults to ``int8`` so a future ``metal`` or other
    device picks a safe baseline.
    """
    explicit = (env_value or "").strip().lower()
    if explicit and explicit != "auto":
        return explicit
    is_cuda = device == "cuda" or device.startswith("cuda:")
    return "float16" if is_cuda else "int8"


def _detect_torch_device(env_value):
    """Pick the optional NeMo/Parakeet torch device.

    Honors an explicit override for users who need to pin ``cpu`` or a
    particular CUDA device. The auto path uses CUDA only when PyTorch can see
    it, otherwise CPU. This helper deliberately avoids adding a UI setting;
    Parakeet is already behind the provider selector and explicit model-load
    action.
    """
    explicit = (env_value or "").strip().lower()
    if explicit and explicit != "auto":
        return explicit
    try:
        import torch  # type: ignore[import-not-found]
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _cache_search_text(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _safe_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _mean(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _estimated_model_preload_percent(elapsed_seconds, *, cached):
    elapsed = max(0.0, float(elapsed_seconds or 0.0))
    base = 35.0 if cached else 1.0
    ceiling = 99.0 if cached else 95.0
    curve_seconds = 20.0 if cached else 60.0
    percent = base + (elapsed / (elapsed + curve_seconds)) * (ceiling - base)
    return int(max(base, min(ceiling, round(percent))))


def _segment_confidence(segments):
    avg_logprob = _mean(_safe_float(getattr(segment, "avg_logprob", None)) for segment in segments)
    no_speech_values = [
        _safe_float(getattr(segment, "no_speech_prob", None))
        for segment in segments
    ]
    no_speech_values = [value for value in no_speech_values if value is not None]
    return {
        "avg_logprob": avg_logprob,
        "no_speech_prob": max(no_speech_values) if no_speech_values else None,
    }


def _transcript_from_segments(segments):
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()


def _transcript_from_nemo_output(output):
    if output is None:
        return ""
    if isinstance(output, (list, tuple)):
        return " ".join(
            transcript
            for transcript in (_transcript_from_nemo_output(item) for item in output)
            if transcript
        ).strip()
    if hasattr(output, "text"):
        return str(output.text or "").strip()
    if isinstance(output, dict):
        return str(output.get("text") or output.get("transcript") or "").strip()
    return str(output or "").strip()


def _iter_resampled_audio_frames(resampler, frame):
    frames = resampler.resample(frame)
    if frames is None:
        return ()
    if isinstance(frames, (list, tuple)):
        return frames
    return (frames,)


def _flush_resampled_audio_frames(resampler):
    try:
        return _iter_resampled_audio_frames(resampler, None)
    except (TypeError, ValueError):
        return ()


def _audio_frame_to_mono_pcm(frame):
    array = frame.to_ndarray()
    if getattr(array, "ndim", 1) == 1:
        mono = array
    elif array.shape[0] == 1:
        mono = array[0]
    elif array.shape[-1] == 1:
        mono = array.reshape(-1)
    elif array.shape[-1] <= 8:
        mono = array.mean(axis=-1)
    else:
        mono = array.mean(axis=0)
    return mono.astype("int16", copy=False).tobytes()


def _convert_audio_to_mono_wav(source_path, target_path, *, sample_rate=PARAKEET_NORMALIZED_SAMPLE_RATE):
    try:
        import av  # type: ignore[import-not-found]
    except Exception as exc:
        raise VoiceInputUnavailable(
            "Browser voice recordings need PyAV in the main app runtime before "
            "NVIDIA Parakeet can transcribe WEBM/OGG/M4A audio. Reinstall the "
            "main requirements, or switch Voice Input provider to Local faster-whisper."
        ) from exc

    source_path = Path(source_path)
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    samples_written = 0
    container = None
    try:
        container = av.open(str(source_path))
        audio_stream = next((stream for stream in container.streams if stream.type == "audio"), None)
        if audio_stream is None:
            raise VoiceInputError("Recorded audio did not contain an audio stream.")
        resampler = av.audio.resampler.AudioResampler(
            format="s16",
            layout="mono",
            rate=int(sample_rate),
        )
        with wave.open(str(target_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(sample_rate))
            for frame in container.decode(audio_stream):
                for resampled in _iter_resampled_audio_frames(resampler, frame):
                    pcm = _audio_frame_to_mono_pcm(resampled)
                    if pcm:
                        wav_file.writeframes(pcm)
                        samples_written += len(pcm) // 2
            for resampled in _flush_resampled_audio_frames(resampler):
                pcm = _audio_frame_to_mono_pcm(resampled)
                if pcm:
                    wav_file.writeframes(pcm)
                    samples_written += len(pcm) // 2
    except VoiceInputError:
        try:
            target_path.unlink()
        except OSError:
            pass
        raise
    except VoiceInputUnavailable:
        try:
            target_path.unlink()
        except OSError:
            pass
        raise
    except Exception as exc:
        try:
            target_path.unlink()
        except OSError:
            pass
        raise VoiceInputError(f"Voice audio conversion failed: {exc}") from exc
    finally:
        if container is not None:
            try:
                container.close()
            except Exception:
                pass

    if samples_written <= 0:
        try:
            target_path.unlink()
        except OSError:
            pass
        raise VoiceInputError("Recorded audio did not contain decodable audio.")
    return target_path


def _parakeet_transcription_audio_path(audio_path):
    audio_path = Path(audio_path)
    if audio_path.name.endswith(".parakeet.wav"):
        return audio_path, None
    normalized_path = audio_path.with_name(f"{audio_path.stem}.parakeet.wav")
    _convert_audio_to_mono_wav(audio_path, normalized_path)
    return normalized_path, normalized_path


def _unlink_transient_audio(path):
    if not path:
        return
    for attempt in range(5):
        try:
            Path(path).unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt < 4:
                time.sleep(0.05)
                continue
            raise


def _needs_confidence_rerun(confidence):
    avg_logprob = confidence.get("avg_logprob")
    no_speech_prob = confidence.get("no_speech_prob")
    return (
        avg_logprob is not None
        and avg_logprob < VOICE_INPUT_CONFIDENCE_RERUN_AVG_LOGPROB
    ) or (
        no_speech_prob is not None
        and no_speech_prob > VOICE_INPUT_CONFIDENCE_RERUN_NO_SPEECH_PROB
    )


def _should_reject_transcript(confidence):
    avg_logprob = confidence.get("avg_logprob")
    return avg_logprob is not None and avg_logprob < VOICE_INPUT_REJECT_AVG_LOGPROB


class VoiceInputError(RuntimeError):
    pass


class VoiceInputUnavailable(VoiceInputError):
    pass


class VoiceInputService:
    PROVIDER_OPTIONS = [
        {
            "id": VOICE_INPUT_PROVIDER_DISABLED,
            "label": "Disabled",
            "description": "Voice input is off.",
        },
        {
            "id": VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET,
            "label": "NVIDIA Parakeet (preferred on NVIDIA)",
            "description": "Preferred low-latency ASR for compatible NVIDIA CUDA runtimes.",
        },
        {
            "id": VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
            "label": "Local faster-whisper",
            "description": "Portable local ASR fallback for CPU and non-NVIDIA systems.",
        },
    ]
    MODE_OPTIONS = [
        {
            "id": VOICE_INPUT_MODE_PUSH_TO_TALK,
            "label": "Push to talk",
            "description": "Click the microphone to record one short command.",
        },
        {
            "id": "hands_free",
            "label": "Hands-free",
            "description": "Arm the microphone and submit speech segments as they are detected.",
        },
    ]
    SUBMIT_OPTIONS = [
        {
            "id": VOICE_INPUT_SUBMIT_PREVIEW,
            "label": "Preview before send",
            "description": "Show the transcript before it enters chat.",
        },
        {
            "id": "auto_submit",
            "label": "Auto-send transcript",
            "description": "Send transcripts through the normal chat path after recognition.",
        },
    ]
    MODEL_OPTIONS = [
        {
            "id": "tiny.en",
            "label": "Fast - tiny.en",
            "description": "Lowest latency for weak CPUs; least accurate in noise.",
            "tier": "fast",
        },
        {
            "id": "base.en",
            "label": "Balanced - base.en",
            "description": "Better accuracy than tiny.en while still reasonable on laptops.",
            "tier": "balanced",
        },
        {
            "id": "small.en",
            "label": "Accurate - small.en",
            "description": "Stronger recognition for moderate noise; higher CPU and RAM cost.",
            "tier": "accurate",
        },
        {
            "id": "distil-large-v3",
            "label": "Desktop/GPU - distil-large-v3",
            "description": "Higher accuracy target for faster desktops or GPU setups.",
            "tier": "desktop",
        },
    ]
    NVIDIA_PARAKEET_MODEL_OPTIONS = [
        {
            "id": DEFAULT_VOICE_INPUT_NVIDIA_PARAKEET_MODEL,
            "label": "NVIDIA Parakeet TDT 0.6B v3",
            "description": "Optional NeMo ASR model for NVIDIA GPU-focused recognition.",
            "tier": "nvidia",
        },
        {
            "id": VOICE_INPUT_NVIDIA_PARAKEET_LARGE_MODEL,
            "label": "NVIDIA Parakeet TDT 1.1B",
            "description": "Larger NeMo ASR model with higher accuracy target and higher VRAM/load cost.",
            "tier": "nvidia-large",
        },
    ]

    def __init__(self, model_cache_dir=None):
        self.provider = VOICE_INPUT_PROVIDER_DISABLED
        self.enabled = False
        self.model_name = DEFAULT_VOICE_INPUT_MODEL
        self.model_cache_dir = str(model_cache_dir or "").strip()
        self.language = "auto"
        self.mode = VOICE_INPUT_MODE_PUSH_TO_TALK
        self.submit_mode = VOICE_INPUT_SUBMIT_PREVIEW
        self.hands_free_sensitivity = DEFAULT_VOICE_INPUT_HANDS_FREE_SENSITIVITY
        self.hands_free_silence_ms = DEFAULT_VOICE_INPUT_HANDS_FREE_SILENCE_MS
        self.min_recording_ms = DEFAULT_VOICE_INPUT_MIN_RECORDING_MS
        self.max_recording_ms = DEFAULT_VOICE_INPUT_MAX_RECORDING_MS
        self.noise_suppression = True
        self.echo_cancellation = True
        self.auto_gain_control = True
        self.noise_floor_rms = DEFAULT_VOICE_INPUT_NOISE_FLOOR_RMS
        self.audio_preprocessing = DEFAULT_VOICE_INPUT_AUDIO_PREPROCESSING
        self.silence_trim = DEFAULT_VOICE_INPUT_SILENCE_TRIM
        self.beam_size = DEFAULT_VOICE_INPUT_BEAM_SIZE
        self.condition_on_previous_text = DEFAULT_VOICE_INPUT_CONDITION_ON_PREVIOUS_TEXT
        self.vad_threshold = DEFAULT_VOICE_INPUT_VAD_THRESHOLD
        self.vad_min_silence_ms = DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS
        self.vad_speech_pad_ms = DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS
        self._model = None
        self._model_key = None
        self._model_cached_key = None
        self._model_cached_value = False
        self._model_cached_checked_at = 0.0
        self._parakeet_runtime_status = None
        self._parakeet_runtime_checked_at = 0.0
        self._preload_status = "idle"
        self._preload_message = ""
        self._preload_started_at = 0.0
        self.last_error = ""
        self.last_transcript = ""
        self.last_timings = {}

    def configure(
        self,
        *,
        provider,
        enabled,
        model,
        language,
        mode=VOICE_INPUT_MODE_PUSH_TO_TALK,
        submit_mode=VOICE_INPUT_SUBMIT_PREVIEW,
        hands_free_sensitivity=DEFAULT_VOICE_INPUT_HANDS_FREE_SENSITIVITY,
        hands_free_silence_ms=DEFAULT_VOICE_INPUT_HANDS_FREE_SILENCE_MS,
        min_recording_ms=DEFAULT_VOICE_INPUT_MIN_RECORDING_MS,
        max_recording_ms=DEFAULT_VOICE_INPUT_MAX_RECORDING_MS,
        noise_suppression=True,
        echo_cancellation=True,
        auto_gain_control=True,
        noise_floor_rms=DEFAULT_VOICE_INPUT_NOISE_FLOOR_RMS,
        audio_preprocessing=DEFAULT_VOICE_INPUT_AUDIO_PREPROCESSING,
        silence_trim=DEFAULT_VOICE_INPUT_SILENCE_TRIM,
        beam_size=DEFAULT_VOICE_INPUT_BEAM_SIZE,
        condition_on_previous_text=DEFAULT_VOICE_INPUT_CONDITION_ON_PREVIOUS_TEXT,
        vad_threshold=DEFAULT_VOICE_INPUT_VAD_THRESHOLD,
        vad_min_silence_ms=DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS,
        vad_speech_pad_ms=DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS,
    ):
        provider = provider or VOICE_INPUT_PROVIDER_DISABLED
        enabled = bool(enabled) and provider != VOICE_INPUT_PROVIDER_DISABLED
        model = str(model or DEFAULT_VOICE_INPUT_MODEL).strip() or DEFAULT_VOICE_INPUT_MODEL
        if provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET and model in VOICE_INPUT_FASTER_WHISPER_MODEL_IDS:
            model = DEFAULT_VOICE_INPUT_NVIDIA_PARAKEET_MODEL
        elif provider == VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER and model in VOICE_INPUT_NVIDIA_PARAKEET_MODELS:
            model = DEFAULT_VOICE_INPUT_MODEL
        language = str(language or "auto").strip() or "auto"
        mode = str(mode or VOICE_INPUT_MODE_PUSH_TO_TALK).strip() or VOICE_INPUT_MODE_PUSH_TO_TALK
        submit_mode = str(submit_mode or VOICE_INPUT_SUBMIT_PREVIEW).strip() or VOICE_INPUT_SUBMIT_PREVIEW

        if provider != self.provider or model != self.model_name or not enabled:
            self._clear_loaded_model()
            self._clear_model_cached_status()
            self._clear_preload_status()
            self.last_error = ""
        self.provider = provider
        self.enabled = enabled
        self.model_name = model
        self.language = language
        self.mode = mode
        self.submit_mode = submit_mode
        self.hands_free_sensitivity = int(hands_free_sensitivity)
        self.hands_free_silence_ms = int(hands_free_silence_ms)
        self.min_recording_ms = int(min_recording_ms)
        self.max_recording_ms = int(max_recording_ms)
        self.noise_suppression = bool(noise_suppression)
        self.echo_cancellation = bool(echo_cancellation)
        self.auto_gain_control = bool(auto_gain_control)
        self.noise_floor_rms = float(noise_floor_rms)
        self.audio_preprocessing = bool(audio_preprocessing)
        self.silence_trim = bool(silence_trim)
        self.beam_size = int(beam_size)
        self.condition_on_previous_text = bool(condition_on_previous_text)
        self.vad_threshold = float(vad_threshold)
        self.vad_min_silence_ms = int(vad_min_silence_ms)
        self.vad_speech_pad_ms = int(vad_speech_pad_ms)

    def close(self):
        self._clear_loaded_model()

    def _clear_loaded_model(self):
        if isinstance(self._model, _ExternalParakeetRuntimeModel):
            self._model.close()
        self._model = None
        self._model_key = None

    def dependency_available(self):
        if self.provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET:
            if isinstance(self._model, _ExternalParakeetRuntimeModel):
                if self._model.is_running():
                    return True
                self._clear_loaded_model()
            if self._model is not None:
                return True
            if self._parakeet_python():
                return bool(self._get_parakeet_runtime_status().get("nemo_available"))
            return _module_available("nemo.collections.asr")
        return _module_available("faster_whisper")

    def _provider_dependency_name(self):
        if self.provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET:
            return "NVIDIA Parakeet runtime"
        return "faster-whisper"

    def _provider_model_options(self):
        if self.provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET:
            return list(self.NVIDIA_PARAKEET_MODEL_OPTIONS)
        return list(self.MODEL_OPTIONS)

    def effective_model_cache_dir(self):
        return str(os.getenv("STROKEGPT_ASR_CACHE_DIR", self.model_cache_dir) or "").strip()

    def _parakeet_python(self):
        return _default_parakeet_python_path()

    def _parakeet_worker_env(self):
        env = os.environ.copy()
        project_root = str(Path(__file__).resolve().parents[1])
        pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = project_root if not pythonpath else os.pathsep.join([project_root, pythonpath])
        return env

    def _run_parakeet_worker(self, action, *, audio_path=None, timeout=900):
        python = self._parakeet_python()
        if not python:
            raise VoiceInputUnavailable("STROKEGPT_PARAKEET_PYTHON is not configured.")
        if not os.path.exists(python):
            raise VoiceInputUnavailable(f"Configured Parakeet Python does not exist: {python}")

        command = [
            python,
            "-m",
            "strokegpt.parakeet_worker",
            action,
            "--model",
            self.model_name,
            "--cache-dir",
            self.effective_model_cache_dir(),
            "--device",
            os.getenv("STROKEGPT_PARAKEET_DEVICE", ""),
            "--language",
            self.language,
        ]
        if audio_path is not None:
            command.extend(["--audio", str(audio_path)])
        try:
            completed = subprocess.run(
                command,
                cwd=str(Path(__file__).resolve().parents[1]),
                env=self._parakeet_worker_env(),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VoiceInputUnavailable("NVIDIA Parakeet worker timed out.") from exc
        except OSError as exc:
            raise VoiceInputUnavailable(f"NVIDIA Parakeet worker failed to start: {exc}") from exc

        payload = None
        for line in reversed((completed.stdout or "").splitlines()):
            if line.startswith(PARAKEET_WORKER_RESULT_PREFIX):
                payload = json.loads(line[len(PARAKEET_WORKER_RESULT_PREFIX):])
                break
        if payload is None:
            stderr = (completed.stderr or "").strip()
            raise VoiceInputUnavailable(stderr or "NVIDIA Parakeet worker did not return a status payload.")
        if completed.returncode != 0 or not payload.get("ok"):
            exc = VoiceInputUnavailable(payload.get("error") or "NVIDIA Parakeet worker failed.")
            exc.payload = payload
            raise exc
        return payload

    def _start_parakeet_worker(self):
        python = self._parakeet_python()
        if not python:
            raise VoiceInputUnavailable("STROKEGPT_PARAKEET_PYTHON is not configured.")
        if not os.path.exists(python):
            raise VoiceInputUnavailable(f"Configured Parakeet Python does not exist: {python}")
        command = [
            python,
            "-m",
            "strokegpt.parakeet_worker",
            "serve",
            "--model",
            self.model_name,
            "--cache-dir",
            self.effective_model_cache_dir(),
            "--device",
            os.getenv("STROKEGPT_PARAKEET_DEVICE", ""),
            "--language",
            self.language,
        ]
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parents[1]),
                env=self._parakeet_worker_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise VoiceInputUnavailable(f"NVIDIA Parakeet worker failed to start: {exc}") from exc
        runtime = _ExternalParakeetRuntimeModel(
            python=python,
            model=self.model_name,
            device="",
            process=process,
        )
        try:
            payload = runtime._read_payload()
        except Exception:
            runtime.close()
            raise
        if not payload.get("ok"):
            runtime.close()
            raise VoiceInputUnavailable(payload.get("error") or "NVIDIA Parakeet worker failed to preload.")
        runtime.device = payload.get("device") or ""
        return runtime, payload

    def _get_parakeet_runtime_status(self, *, refresh=False):
        python = self._parakeet_python()
        if not python:
            return {
                "ok": False,
                "external_runtime": False,
                "python": "",
                "nemo_available": _module_available("nemo.collections.asr"),
                "torch": None,
                "error": "",
            }
        cache_age = time.monotonic() - self._parakeet_runtime_checked_at
        if (
            not refresh
            and self._parakeet_runtime_status is not None
            and cache_age < PARAKEET_RUNTIME_STATUS_TTL_SECONDS
        ):
            return dict(self._parakeet_runtime_status)
        try:
            status = self._run_parakeet_worker("check", timeout=60)
        except VoiceInputUnavailable as exc:
            payload = getattr(exc, "payload", None)
            if isinstance(payload, dict):
                status = dict(payload)
                status["ok"] = False
                status.setdefault("python", python)
                status.setdefault("nemo_available", False)
                status.setdefault("error", str(exc))
            else:
                status = {
                    "ok": False,
                    "external_runtime": True,
                    "python": python,
                    "nemo_available": False,
                    "torch": None,
                    "error": str(exc),
                }
        status["external_runtime"] = True
        status.setdefault("python", python)
        self._parakeet_runtime_status = dict(status)
        self._parakeet_runtime_checked_at = time.monotonic()
        return status

    def _model_cache_tokens(self):
        tokens = {_cache_search_text(self.model_name)}
        model_tail = self.model_name.rsplit("/", 1)[-1]
        tail_token = _cache_search_text(model_tail)
        if tail_token:
            tokens.add(tail_token)
            if not tail_token.startswith("faster-whisper-"):
                tokens.add(f"faster-whisper-{tail_token}")
        return {token for token in tokens if token}

    def _model_cached_status_key(self):
        return (self.provider, self.model_name, self.effective_model_cache_dir())

    def _clear_model_cached_status(self):
        self._model_cached_key = None
        self._model_cached_value = False
        self._model_cached_checked_at = 0.0

    def _set_model_cached_status(self, value):
        self._model_cached_key = self._model_cached_status_key()
        self._model_cached_value = bool(value)
        self._model_cached_checked_at = time.monotonic()

    def _clear_preload_status(self):
        self._preload_status = "idle"
        self._preload_message = ""
        self._preload_started_at = 0.0

    def _set_preload_status(self, status, message=""):
        self._preload_status = status
        self._preload_message = str(message or "")
        if status == "loading":
            self._preload_started_at = time.monotonic()
        elif not self._preload_started_at:
            self._preload_started_at = 0.0

    def _preload_elapsed_seconds(self):
        if self._preload_status != "loading" or not self._preload_started_at:
            return 0.0
        return max(0.0, time.monotonic() - self._preload_started_at)

    def _preload_progress_percent(self, *, model_cached):
        if self._model is not None or self._preload_status == "loaded":
            return 100
        if self._preload_status != "loading":
            return None
        return _estimated_model_preload_percent(
            self._preload_elapsed_seconds(),
            cached=bool(model_cached),
        )

    def _scan_model_cache(self):
        cache_dir = self.effective_model_cache_dir()
        if not cache_dir or not os.path.isdir(cache_dir):
            return False

        tokens = self._model_cache_tokens()
        entries_seen = 0
        for root, dirs, files in os.walk(cache_dir):
            entries_seen += len(dirs) + len(files)
            marker_files = _MODEL_CACHE_MARKER_FILES.intersection(name.lower() for name in files)
            if marker_files:
                relative_root = os.path.relpath(root, cache_dir)
                normalized_root = "" if relative_root == "." else _cache_search_text(relative_root)
                if not normalized_root or any(token in normalized_root for token in tokens):
                    return True
            if entries_seen >= _MODEL_CACHE_SCAN_LIMIT:
                break
        return False

    def is_model_cached(self, *, refresh=False):
        if self._model is not None:
            return True

        key = self._model_cached_status_key()
        cache_age = time.monotonic() - self._model_cached_checked_at
        if (
            not refresh
            and self._model_cached_key == key
            and self._model_cached_value
            and cache_age < 2.0
        ):
            return self._model_cached_value

        cached = self._scan_model_cache()
        self._set_model_cached_status(cached)
        return cached

    def status(self):
        supported_provider = self.provider in {
            VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
            VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET,
        }
        dependency_available = (
            self.dependency_available()
            if self.enabled and supported_provider
            else False
        )
        can_load_model = (
            self.enabled
            and supported_provider
            and dependency_available
        )
        model_cached = can_load_model and self.is_model_cached()
        can_transcribe = can_load_model and self._model is not None
        preload_status = self._preload_status
        if self.provider == VOICE_INPUT_PROVIDER_DISABLED or not self.enabled:
            status_code = "disabled"
            message = "Voice input is disabled."
        elif not supported_provider:
            status_code = "unsupported_provider"
            message = f"Unsupported voice input provider: {self.provider}"
        elif not dependency_available:
            status_code = "dependency_missing"
            parakeet_error = ""
            if self.provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET:
                parakeet_error = str((self._parakeet_runtime_status or {}).get("error") or "").strip()
            if parakeet_error:
                message = (
                    f"Voice input needs {self._provider_dependency_name()}. "
                    f"Runtime check failed: {parakeet_error}"
                )
            else:
                message = f"Voice input needs {self._provider_dependency_name()}. Install dependencies, then restart the app."
        elif preload_status == "loading":
            status_code = "model_loading"
            message = self._preload_message or f"Loading voice input model: {self.model_name}."
        elif self._model is None:
            status_code = "model_not_loaded"
            if model_cached:
                message = "Voice input model is cached but not loaded. Use Load Voice Input Model before recording."
            else:
                message = f"Voice input model is not downloaded. Use Download / Load Voice Input Model once to cache and load {self.model_name}."
        else:
            status_code = "ready"
            message = f"Voice input model loaded: {self.model_name}."
        if self.last_error:
            status_code = "error"
            message = f"{message} Last error: {self.last_error}"
        return {
            "status_code": status_code,
            "provider": self.provider,
            "enabled": self.enabled,
            "model": self.model_name,
            "model_cache_dir": self.effective_model_cache_dir(),
            "language": self.language,
            "mode": self.mode,
            "submit_mode": self.submit_mode,
            "preview_required": self.submit_mode != "auto_submit",
            "hands_free_sensitivity": self.hands_free_sensitivity,
            "hands_free_silence_ms": self.hands_free_silence_ms,
            "min_recording_ms": self.min_recording_ms,
            "max_recording_ms": self.max_recording_ms,
            "noise_suppression": self.noise_suppression,
            "echo_cancellation": self.echo_cancellation,
            "auto_gain_control": self.auto_gain_control,
            "noise_floor_rms": self.noise_floor_rms,
            "audio_preprocessing": self.audio_preprocessing,
            "silence_trim": self.silence_trim,
            "beam_size": self.beam_size,
            "condition_on_previous_text": self.condition_on_previous_text,
            "vad_threshold": self.vad_threshold,
            "vad_min_silence_ms": self.vad_min_silence_ms,
            "vad_speech_pad_ms": self.vad_speech_pad_ms,
            "dependency_available": dependency_available,
            "model_loaded": self._model is not None,
            "model_cached": model_cached,
            "can_load_model": can_load_model,
            "load_requires_download": can_load_model and not model_cached,
            "can_transcribe": can_transcribe,
            "preload_status": preload_status,
            "preload_message": self._preload_message,
            "preload_elapsed_seconds": round(self._preload_elapsed_seconds(), 1),
            "preload_progress_percent": self._preload_progress_percent(model_cached=model_cached),
            "message": message,
            "last_error": self.last_error,
            "last_transcript": self.last_transcript,
            "last_timings": dict(self.last_timings),
            "provider_options": list(self.PROVIDER_OPTIONS),
            "mode_options": list(self.MODE_OPTIONS),
            "submit_options": list(self.SUBMIT_OPTIONS),
            "model_options": self._provider_model_options(),
        }

    def setup_status(self):
        torch_runtime = {
            "torch_available": False,
            "torch_version": "",
            "cuda_available": False,
            "cuda_version": "",
            "device_count": 0,
            "device_name": "",
            "device": _detect_torch_device(os.getenv("STROKEGPT_PARAKEET_DEVICE")),
        }
        if _module_available("torch"):
            try:
                import torch  # type: ignore[import-not-found]

                torch_runtime["torch_available"] = True
                torch_runtime["torch_version"] = getattr(torch, "__version__", "")
                torch_runtime["cuda_available"] = bool(torch.cuda.is_available())
                torch_runtime["cuda_version"] = getattr(torch.version, "cuda", "") or ""
                torch_runtime["device_count"] = int(torch.cuda.device_count()) if torch_runtime["cuda_available"] else 0
                torch_runtime["device_name"] = torch.cuda.get_device_name(0) if torch_runtime["cuda_available"] else ""
                torch_runtime["device"] = _detect_torch_device(os.getenv("STROKEGPT_PARAKEET_DEVICE"))
            except Exception as exc:
                torch_runtime["error"] = str(exc)
        parakeet_runtime = self._get_parakeet_runtime_status()
        parakeet_torch = parakeet_runtime.get("torch") if parakeet_runtime.get("external_runtime") else torch_runtime
        nemo_available = (
            bool(parakeet_runtime.get("nemo_available"))
            if parakeet_runtime.get("external_runtime")
            else _module_available("nemo.collections.asr")
        )
        return {
            "selected": self.status(),
            "faster_whisper_available": _module_available("faster_whisper"),
            "ctranslate2_available": _module_available("ctranslate2"),
            "ctranslate2_cuda_devices": _count_cuda_devices(),
            "nemo_available": nemo_available,
            "torch": parakeet_torch or torch_runtime,
            "parakeet_external_runtime": parakeet_runtime.get("external_runtime", False),
            "parakeet_external_python": parakeet_runtime.get("python", ""),
            "parakeet_external_error": parakeet_runtime.get("error", ""),
        }

    def _require_ready(self):
        if not self.enabled or self.provider == VOICE_INPUT_PROVIDER_DISABLED:
            raise VoiceInputUnavailable("Voice input is disabled.")
        if self.provider not in {
            VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
            VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET,
        }:
            raise VoiceInputUnavailable(f"Unsupported voice input provider: {self.provider}")
        if not self.dependency_available():
            if self.provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET:
                runtime_error = str((self._parakeet_runtime_status or {}).get("error") or "").strip()
                if runtime_error:
                    raise VoiceInputUnavailable(f"NVIDIA Parakeet runtime check failed: {runtime_error}")
            raise VoiceInputUnavailable(
                f"Install {self._provider_dependency_name()} before using this voice input provider."
            )

    def _prepare_model_cache(self, *, configure_hf_home=False):
        cache_dir = self.effective_model_cache_dir()
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            os.environ.setdefault("HF_XET_CACHE", os.path.join(cache_dir, "xet"))
            if configure_hf_home:
                os.environ.setdefault("HF_HOME", cache_dir)
                os.environ.setdefault("HF_HUB_CACHE", os.path.join(cache_dir, "hub"))

        # Hugging Face's default cache uses symlinks and Xet integration when
        # available. On normal Windows user accounts that can fail or log access
        # errors, so default local ASR loads to a copy-based cache.
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

        try:
            import huggingface_hub.constants as hf_constants
        except Exception:
            return cache_dir

        hf_constants.HF_HUB_DISABLE_SYMLINKS = _env_flag_enabled("HF_HUB_DISABLE_SYMLINKS")
        hf_constants.HF_HUB_DISABLE_SYMLINKS_WARNING = _env_flag_enabled("HF_HUB_DISABLE_SYMLINKS_WARNING")
        hf_constants.HF_HUB_DISABLE_XET = _env_flag_enabled("HF_HUB_DISABLE_XET")
        hf_constants.HF_XET_CACHE = os.environ.get("HF_XET_CACHE", hf_constants.HF_XET_CACHE)
        if configure_hf_home:
            if hasattr(hf_constants, "HF_HOME"):
                hf_constants.HF_HOME = os.environ.get("HF_HOME", hf_constants.HF_HOME)
            if hasattr(hf_constants, "HF_HUB_CACHE"):
                hf_constants.HF_HUB_CACHE = os.environ.get("HF_HUB_CACHE", hf_constants.HF_HUB_CACHE)
        return cache_dir

    def _load_model(self):
        self._require_ready()
        key = (self.provider, self.model_name)
        if self._model is not None and self._model_key == key:
            return 0
        self._clear_loaded_model()
        started = time.perf_counter()
        if self.provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET:
            self._load_nvidia_parakeet_model()
        else:
            self._load_faster_whisper_model()
        self._model_key = key
        return int((time.perf_counter() - started) * 1000)

    def _load_faster_whisper_model(self):
        cache_dir = self._prepare_model_cache()
        from faster_whisper import WhisperModel

        # Auto-detect by default. Honors explicit STROKEGPT_ASR_DEVICE /
        # STROKEGPT_ASR_COMPUTE_TYPE overrides for users who need to pin a
        # specific GPU index, force CPU on a broken CUDA install, or trade
        # accuracy for memory. The auto path picks GPU+float16 when CUDA is
        # visible (the ~10x latency cliff that CPU-only voice users hit) and
        # CPU+int8 otherwise.
        device = _detect_device(os.getenv("STROKEGPT_ASR_DEVICE"))
        compute_type = _detect_compute_type(
            os.getenv("STROKEGPT_ASR_COMPUTE_TYPE"), device
        )
        print(
            f"[INFO] faster-whisper loading model={self.model_name!r} "
            f"device={device} compute_type={compute_type}"
        )
        self._model = WhisperModel(
            self.model_name,
            device=device,
            compute_type=compute_type,
            download_root=cache_dir or None,
        )

    def _load_nvidia_parakeet_model(self):
        if self._parakeet_python():
            self._model, payload = self._start_parakeet_worker()
            status = dict(payload)
            status.setdefault("ok", True)
            status.setdefault("nemo_available", True)
            status.setdefault("python", self._parakeet_python())
            status["external_runtime"] = True
            self._parakeet_runtime_status = status
            self._parakeet_runtime_checked_at = time.monotonic()
            return
        self._prepare_model_cache(configure_hf_home=True)
        from .parakeet_worker import _install_nemo_dependency_compat

        _install_nemo_dependency_compat()
        import nemo.collections.asr as nemo_asr  # type: ignore[import-not-found]

        device = _detect_torch_device(os.getenv("STROKEGPT_PARAKEET_DEVICE"))
        print(
            f"[INFO] NVIDIA NeMo ASR loading model={self.model_name!r} "
            f"device={device}"
        )
        self._model = nemo_asr.models.ASRModel.from_pretrained(
            model_name=self.model_name,
        )
        if hasattr(self._model, "to"):
            self._model.to(device)
        if hasattr(self._model, "eval"):
            self._model.eval()

    def _effective_language(self):
        language = str(self.language or "auto").strip() or "auto"
        if language.lower() == "auto":
            return "en"
        return language

    def _transcribe_attempt(self, audio_path, *, language, beam_size):
        segments, info = self._model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            vad_parameters={
                "threshold": self.vad_threshold,
                "min_silence_duration_ms": self.vad_min_silence_ms,
                "speech_pad_ms": self.vad_speech_pad_ms,
            },
            beam_size=beam_size,
            condition_on_previous_text=self.condition_on_previous_text,
            initial_prompt=VOICE_INPUT_INITIAL_PROMPT,
        )
        segments = list(segments)
        return {
            "transcript": _transcript_from_segments(segments),
            "info": info,
            "confidence": _segment_confidence(segments),
            "beam_size": beam_size,
        }

    def preload_model(self):
        self.last_error = ""
        self._set_preload_status("loading", f"Loading voice input model: {self.model_name}.")
        try:
            load_ms = self._load_model()
            self._set_model_cached_status(True)
            if load_ms:
                self.last_timings = {"model_load_ms": load_ms}
            message = f"Voice input model loaded: {self.model_name}."
            self._set_preload_status("loaded", message)
            return True, message
        except VoiceInputError as exc:
            self.last_error = str(exc)
            self._set_preload_status("error", str(exc))
            raise
        except Exception as exc:
            message = f"Voice input model load failed: {exc}"
            self.last_error = message
            self._set_preload_status("error", message)
            raise VoiceInputError(message) from exc

    def transcribe_file(self, audio_path):
        self._require_ready()
        if self._model is None:
            if self.is_model_cached():
                raise VoiceInputUnavailable("Load the cached voice input model before recording.")
            raise VoiceInputUnavailable("Download / load the voice input model before recording.")
        if self.provider == VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET:
            return self._transcribe_nvidia_parakeet_file(audio_path)
        return self._transcribe_faster_whisper_file(audio_path)

    def _transcribe_faster_whisper_file(self, audio_path):
        timings = {}
        try:
            language = self._effective_language()
            configured_beam_size = max(VOICE_INPUT_FAST_BEAM_SIZE, int(self.beam_size))
            started = time.perf_counter()
            attempt = self._transcribe_attempt(
                audio_path,
                language=language,
                beam_size=VOICE_INPUT_FAST_BEAM_SIZE,
            )
            attempts = [attempt]
            if (
                configured_beam_size > VOICE_INPUT_FAST_BEAM_SIZE
                and _needs_confidence_rerun(attempt["confidence"])
            ):
                attempt = self._transcribe_attempt(
                    audio_path,
                    language=language,
                    beam_size=configured_beam_size,
                )
                attempts.append(attempt)
            transcript = attempt["transcript"]
            confidence = attempt["confidence"]
            status = "success"
            message = None
            if transcript and _should_reject_transcript(confidence):
                status = "rejected"
                transcript = ""
                message = VOICE_INPUT_REJECT_MESSAGE
            timings["transcribe_ms"] = int((time.perf_counter() - started) * 1000)
            timings["asr_attempts"] = len(attempts)
            timings["asr_beam_size"] = attempt["beam_size"]
            self.last_error = ""
            self.last_transcript = transcript
            self.last_timings = timings
            result_language = getattr(attempt["info"], "language", None) or language
            result = {
                "status": status,
                "transcript": transcript,
                "language": result_language,
                "language_probability": getattr(attempt["info"], "language_probability", None),
                "duration": getattr(attempt["info"], "duration", None),
                "confidence": confidence,
                "recognition": {
                    "beam_size": attempt["beam_size"],
                    "configured_beam_size": configured_beam_size,
                    "attempts": [
                        {
                            "beam_size": item["beam_size"],
                            "confidence": item["confidence"],
                        }
                        for item in attempts
                    ],
                },
                "timings": timings,
                "provider": self.provider,
                "model": self.model_name,
            }
            if message:
                result["message"] = message
            return result
        except VoiceInputError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            raise VoiceInputError(f"Voice transcription failed: {exc}") from exc

    def _transcribe_nvidia_parakeet_file(self, audio_path):
        timings = {}
        parakeet_audio_path = None
        transient_audio_path = None
        total_started = time.perf_counter()
        try:
            normalization_started = time.perf_counter()
            parakeet_audio_path, transient_audio_path = _parakeet_transcription_audio_path(audio_path)
            timings["normalization_ms"] = int((time.perf_counter() - normalization_started) * 1000)
            if isinstance(self._model, _ExternalParakeetRuntimeModel):
                worker_started = time.perf_counter()
                payload = self._model.request({
                    "action": "transcribe",
                    "audio": str(parakeet_audio_path),
                    "language": self.language,
                })
                transcript = str(payload.get("transcript") or "").strip()
                timings.update(payload.get("timings") or {})
                timings.setdefault("normalization_ms", int((time.perf_counter() - normalization_started) * 1000))
                timings.setdefault("asr_attempts", 1)
                timings["worker_request_ms"] = int((time.perf_counter() - worker_started) * 1000)
                timings["total_ms"] = int((time.perf_counter() - total_started) * 1000)
                self.last_error = ""
                self.last_transcript = transcript
                self.last_timings = timings
                return {
                    "status": payload.get("status") or ("success" if transcript else "no_speech"),
                    "transcript": transcript,
                    "language": payload.get("language") or self._effective_language(),
                    "language_probability": None,
                    "duration": None,
                    "confidence": {},
                    "recognition": {
                        "provider": VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET,
                        "runtime": "external",
                        "attempts": 1,
                    },
                    "timings": timings,
                    "provider": self.provider,
                    "model": self.model_name,
                }
            started = time.perf_counter()
            outputs = self._model.transcribe([str(parakeet_audio_path)])
            output = outputs[0] if outputs else None
            transcript = _transcript_from_nemo_output(output)
            timings["transcribe_ms"] = int((time.perf_counter() - started) * 1000)
            timings["asr_attempts"] = 1
            timings["total_ms"] = int((time.perf_counter() - total_started) * 1000)
            self.last_error = ""
            self.last_transcript = transcript
            self.last_timings = timings
            return {
                "status": "success" if transcript else "no_speech",
                "transcript": transcript,
                "language": self._effective_language(),
                "language_probability": None,
                "duration": None,
                "confidence": {},
                "recognition": {
                    "provider": VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET,
                    "attempts": 1,
                },
                "timings": timings,
                "provider": self.provider,
                "model": self.model_name,
            }
        except VoiceInputError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            raise VoiceInputError(f"Voice transcription failed: {exc}") from exc
        finally:
            if transient_audio_path is not None:
                try:
                    _unlink_transient_audio(transient_audio_path)
                except OSError:
                    pass
