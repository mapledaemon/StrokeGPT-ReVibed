import importlib.util
import os
import time

from .settings import (
    DEFAULT_VOICE_INPUT_MODEL,
    VOICE_INPUT_MODE_PUSH_TO_TALK,
    VOICE_INPUT_PROVIDER_DISABLED,
    VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
    VOICE_INPUT_SUBMIT_PREVIEW,
)


_HF_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_flag_enabled(name):
    return os.environ[name].lower() in _HF_TRUE_VALUES


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

    def __init__(self, model_cache_dir=None):
        self.provider = VOICE_INPUT_PROVIDER_DISABLED
        self.enabled = False
        self.model_name = DEFAULT_VOICE_INPUT_MODEL
        self.model_cache_dir = str(model_cache_dir or "").strip()
        self.language = "auto"
        self.mode = VOICE_INPUT_MODE_PUSH_TO_TALK
        self.submit_mode = VOICE_INPUT_SUBMIT_PREVIEW
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

    def dependency_available(self):
        return importlib.util.find_spec("faster_whisper") is not None

    def effective_model_cache_dir(self):
        return str(os.getenv("STROKEGPT_ASR_CACHE_DIR", self.model_cache_dir) or "").strip()

    def status(self):
        dependency_available = self.dependency_available()
        can_load_model = (
            self.enabled
            and self.provider == VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER
            and dependency_available
        )
        can_transcribe = can_load_model and self._model is not None
        if self.provider == VOICE_INPUT_PROVIDER_DISABLED or not self.enabled:
            message = "Voice input is disabled."
        elif not dependency_available:
            message = "Install faster-whisper before using local voice input."
        elif self._model is None:
            message = f"Click Download / Load Voice Input Model before recording. First load may download {self.model_name}."
        else:
            message = f"Voice input model loaded: {self.model_name}."
        if self.last_error:
            message = f"{message} Last error: {self.last_error}"
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "model": self.model_name,
            "model_cache_dir": self.effective_model_cache_dir(),
            "language": self.language,
            "mode": self.mode,
            "submit_mode": self.submit_mode,
            "preview_required": self.submit_mode != "auto_submit",
            "dependency_available": dependency_available,
            "model_loaded": self._model is not None,
            "can_load_model": can_load_model,
            "can_transcribe": can_transcribe,
            "message": message,
            "last_error": self.last_error,
            "last_transcript": self.last_transcript,
            "last_timings": dict(self.last_timings),
            "provider_options": list(self.PROVIDER_OPTIONS),
            "mode_options": list(self.MODE_OPTIONS),
            "submit_options": list(self.SUBMIT_OPTIONS),
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

        device = os.getenv("STROKEGPT_ASR_DEVICE", "cpu").strip() or "cpu"
        compute_type = os.getenv("STROKEGPT_ASR_COMPUTE_TYPE", "int8").strip() or "int8"
        self._model = WhisperModel(
            self.model_name,
            device=device,
            compute_type=compute_type,
            download_root=cache_dir or None,
        )
        self._model_key = key
        return int((time.perf_counter() - started) * 1000)

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
            raise VoiceInputUnavailable("Download / load the voice input model before recording.")
        timings = {}
        try:
            language = None if self.language.lower() == "auto" else self.language
            started = time.perf_counter()
            segments, info = self._model.transcribe(
                str(audio_path),
                language=language,
                vad_filter=True,
            )
            transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
            timings["transcribe_ms"] = int((time.perf_counter() - started) * 1000)
            self.last_error = ""
            self.last_transcript = transcript
            self.last_timings = timings
            return {
                "status": "success",
                "transcript": transcript,
                "language": getattr(info, "language", language or "auto"),
                "language_probability": getattr(info, "language_probability", None),
                "duration": getattr(info, "duration", None),
                "timings": timings,
                "provider": self.provider,
                "model": self.model_name,
            }
        except VoiceInputError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            raise VoiceInputError(f"Voice transcription failed: {exc}") from exc
