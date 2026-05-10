import importlib.util
import os
import re
import time

from .settings import (
    DEFAULT_VOICE_INPUT_BEAM_SIZE,
    DEFAULT_VOICE_INPUT_CONDITION_ON_PREVIOUS_TEXT,
    DEFAULT_VOICE_INPUT_HANDS_FREE_SENSITIVITY,
    DEFAULT_VOICE_INPUT_HANDS_FREE_SILENCE_MS,
    DEFAULT_VOICE_INPUT_MAX_RECORDING_MS,
    DEFAULT_VOICE_INPUT_MIN_RECORDING_MS,
    DEFAULT_VOICE_INPUT_MODEL,
    DEFAULT_VOICE_INPUT_NOISE_FLOOR_RMS,
    DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS,
    DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS,
    DEFAULT_VOICE_INPUT_VAD_THRESHOLD,
    VOICE_INPUT_MODE_PUSH_TO_TALK,
    VOICE_INPUT_PROVIDER_DISABLED,
    VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
    VOICE_INPUT_SUBMIT_PREVIEW,
)


_HF_TRUE_VALUES = {"1", "true", "yes", "on"}
_MODEL_CACHE_MARKER_FILES = {
    "config.json",
    "model.bin",
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


def _env_flag_enabled(name):
    return os.environ[name].lower() in _HF_TRUE_VALUES


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
            "id": VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
            "label": "Local faster-whisper",
            "description": "Transcribe browser microphone clips locally.",
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
        self.beam_size = DEFAULT_VOICE_INPUT_BEAM_SIZE
        self.condition_on_previous_text = DEFAULT_VOICE_INPUT_CONDITION_ON_PREVIOUS_TEXT
        self.vad_threshold = DEFAULT_VOICE_INPUT_VAD_THRESHOLD
        self.vad_min_silence_ms = DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS
        self.vad_speech_pad_ms = DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS
        self._model = None
        self._model_key = None
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
        beam_size=DEFAULT_VOICE_INPUT_BEAM_SIZE,
        condition_on_previous_text=DEFAULT_VOICE_INPUT_CONDITION_ON_PREVIOUS_TEXT,
        vad_threshold=DEFAULT_VOICE_INPUT_VAD_THRESHOLD,
        vad_min_silence_ms=DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS,
        vad_speech_pad_ms=DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS,
    ):
        provider = provider or VOICE_INPUT_PROVIDER_DISABLED
        enabled = bool(enabled) and provider != VOICE_INPUT_PROVIDER_DISABLED
        model = str(model or DEFAULT_VOICE_INPUT_MODEL).strip() or DEFAULT_VOICE_INPUT_MODEL
        language = str(language or "auto").strip() or "auto"
        mode = str(mode or VOICE_INPUT_MODE_PUSH_TO_TALK).strip() or VOICE_INPUT_MODE_PUSH_TO_TALK
        submit_mode = str(submit_mode or VOICE_INPUT_SUBMIT_PREVIEW).strip() or VOICE_INPUT_SUBMIT_PREVIEW

        if provider != self.provider or model != self.model_name:
            self._model = None
            self._model_key = None
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
        self.beam_size = int(beam_size)
        self.condition_on_previous_text = bool(condition_on_previous_text)
        self.vad_threshold = float(vad_threshold)
        self.vad_min_silence_ms = int(vad_min_silence_ms)
        self.vad_speech_pad_ms = int(vad_speech_pad_ms)

    def dependency_available(self):
        return importlib.util.find_spec("faster_whisper") is not None

    def effective_model_cache_dir(self):
        return str(os.getenv("STROKEGPT_ASR_CACHE_DIR", self.model_cache_dir) or "").strip()

    def _model_cache_tokens(self):
        tokens = {_cache_search_text(self.model_name)}
        model_tail = self.model_name.rsplit("/", 1)[-1]
        tail_token = _cache_search_text(model_tail)
        if tail_token:
            tokens.add(tail_token)
            if not tail_token.startswith("faster-whisper-"):
                tokens.add(f"faster-whisper-{tail_token}")
        return {token for token in tokens if token}

    def is_model_cached(self):
        if self._model is not None:
            return True
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

    def status(self):
        dependency_available = self.dependency_available()
        can_load_model = (
            self.enabled
            and self.provider == VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER
            and dependency_available
        )
        model_cached = can_load_model and self.is_model_cached()
        can_transcribe = can_load_model and self._model is not None
        if self.provider == VOICE_INPUT_PROVIDER_DISABLED or not self.enabled:
            status_code = "disabled"
            message = "Voice input is disabled."
        elif not dependency_available:
            status_code = "dependency_missing"
            message = "Voice input needs faster-whisper. Install dependencies, then restart the app."
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
            "message": message,
            "last_error": self.last_error,
            "last_transcript": self.last_transcript,
            "last_timings": dict(self.last_timings),
            "provider_options": list(self.PROVIDER_OPTIONS),
            "mode_options": list(self.MODE_OPTIONS),
            "submit_options": list(self.SUBMIT_OPTIONS),
            "model_options": list(self.MODEL_OPTIONS),
        }

    def _require_ready(self):
        if not self.enabled or self.provider == VOICE_INPUT_PROVIDER_DISABLED:
            raise VoiceInputUnavailable("Voice input is disabled.")
        if self.provider != VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER:
            raise VoiceInputUnavailable(f"Unsupported voice input provider: {self.provider}")
        if not self.dependency_available():
            raise VoiceInputUnavailable("Install faster-whisper before using local voice input.")

    def _prepare_model_cache(self):
        cache_dir = self.effective_model_cache_dir()
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            os.environ.setdefault("HF_XET_CACHE", os.path.join(cache_dir, "xet"))

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
        return cache_dir

    def _load_model(self):
        self._require_ready()
        key = (self.provider, self.model_name)
        if self._model is not None and self._model_key == key:
            return 0
        started = time.perf_counter()
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
        self._model_key = key
        return int((time.perf_counter() - started) * 1000)

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
        try:
            load_ms = self._load_model()
            self.last_error = ""
            if load_ms:
                self.last_timings = {"model_load_ms": load_ms}
            return True, f"Voice input model loaded: {self.model_name}."
        except VoiceInputError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            raise VoiceInputError(f"Voice input model load failed: {exc}") from exc

    def transcribe_file(self, audio_path):
        self._require_ready()
        if self._model is None:
            if self.is_model_cached():
                raise VoiceInputUnavailable("Load the cached voice input model before recording.")
            raise VoiceInputUnavailable("Download / load the voice input model before recording.")
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
