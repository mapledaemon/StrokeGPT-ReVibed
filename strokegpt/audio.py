import io
import importlib.util
import os
import re
import threading
import time
import warnings
import wave
from collections import deque
from contextlib import contextmanager
from pathlib import Path

from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings


class AudioService:
    LOCAL_ENGINE_CHATTERBOX = "chatterbox"
    LOCAL_ENGINE_CHATTERBOX_TURBO = "chatterbox_turbo"
    LOCAL_ENGINE_DEFAULT = LOCAL_ENGINE_CHATTERBOX_TURBO
    LOCAL_TTS_CHUNK_CHARS = 220
    LOCAL_ENGINE_LABELS = {
        LOCAL_ENGINE_CHATTERBOX_TURBO: "Chatterbox Turbo",
        LOCAL_ENGINE_CHATTERBOX: "Chatterbox Standard",
    }
    CHATTERBOX_STYLE_PRESETS = {
        "default": {
            "label": "Default",
            "exaggeration": 0.5,
            "cfg_weight": 0.5,
            "temperature": 0.8,
            "top_p": 1.0,
            "min_p": 0.05,
            "repetition_penalty": 1.2,
        },
        "calm": {
            "label": "Calm / steady",
            "exaggeration": 0.35,
            "cfg_weight": 0.65,
            "temperature": 0.65,
            "top_p": 0.9,
            "min_p": 0.05,
            "repetition_penalty": 1.25,
        },
        "expressive": {
            "label": "Expressive",
            "exaggeration": 0.7,
            "cfg_weight": 0.3,
            "temperature": 0.9,
            "top_p": 1.0,
            "min_p": 0.05,
            "repetition_penalty": 1.15,
        },
        "dramatic": {
            "label": "Dramatic",
            "exaggeration": 1.0,
            "cfg_weight": 0.25,
            "temperature": 1.0,
            "top_p": 1.0,
            "min_p": 0.04,
            "repetition_penalty": 1.1,
        },
        "energetic": {
            "label": "Energetic",
            "exaggeration": 0.85,
            "cfg_weight": 0.45,
            "temperature": 1.05,
            "top_p": 1.0,
            "min_p": 0.05,
            "repetition_penalty": 1.1,
        },
        "clone_stable": {
            "label": "Reference voice stable",
            "exaggeration": 0.45,
            "cfg_weight": 0.3,
            "temperature": 0.75,
            "top_p": 0.95,
            "min_p": 0.05,
            "repetition_penalty": 1.25,
        },
    }

    def __init__(self):
        self.provider = "elevenlabs"
        self.is_on = False

        self.api_key = ""
        self.voice_id = ""
        self.client = None
        self.available_voices = {}

        self.local_engine = self.LOCAL_ENGINE_DEFAULT
        self.local_style = "expressive"
        self.local_prompt_path = ""
        self.local_exaggeration = 0.65
        self.local_cfg_weight = 0.35
        self.local_temperature = 0.85
        self.local_top_p = 1.0
        self.local_min_p = 0.05
        self.local_repetition_penalty = 1.2
        self._local_model = None
        self._local_model_engine = None
        self._local_model_device = ""
        self._local_model_lock = threading.Lock()
        self._local_generation_lock = threading.Lock()
        self._local_preload_thread = None
        self._local_preload_status = "idle"
        self._local_preload_error = ""
        self._local_warmup_done = False
        self.last_generation_seconds = None
        self.last_error = ""

        self.audio_output_queue = deque()

    def set_provider(self, provider, enabled=None):
        if provider not in {"elevenlabs", "local"}:
            return False, "Unknown audio provider."
        self.provider = provider
        if enabled is not None:
            self.is_on = bool(enabled)
        return True, "Audio provider updated."

    def set_api_key(self, api_key):
        self.api_key = api_key
        try:
            self.client = ElevenLabs(api_key=self.api_key)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to initialize ElevenLabs client: {e}")
            self.client = None
            return False

    def fetch_available_voices(self):
        if not self.client:
            return {"status": "error", "message": "API key not set or invalid."}

        try:
            voices_list = self.client.voices.get_all()
            self.available_voices = {voice.name: voice.voice_id for voice in voices_list.voices}
            print(f"[OK] ElevenLabs key set. Found {len(self.available_voices)} voices.")
            return {"status": "success", "voices": self.available_voices}
        except Exception as e:
            return {"status": "error", "message": f"Couldn't fetch voices: {e}"}

    def configure_voice(self, voice_id, enabled):
        if not voice_id and enabled and self.provider == "elevenlabs":
            return False, "A voice must be selected to enable ElevenLabs audio."

        self.provider = "elevenlabs"
        self.voice_id = voice_id
        self.is_on = bool(enabled)

        status_message = "ON" if self.is_on else "OFF"
        if voice_id:
            voice_name = next((name for name, v_id in self.available_voices.items() if v_id == voice_id), "Unknown")
            print(f"[INFO] ElevenLabs voice set to '{voice_name}'. Audio is now {status_message}.")
        else:
            print(f"[INFO] ElevenLabs audio is now {status_message}.")
        return True, "Settings updated."

    def configure_local_voice(
        self,
        enabled,
        prompt_path="",
        exaggeration=None,
        cfg_weight=None,
        style="expressive",
        temperature=None,
        top_p=None,
        min_p=None,
        repetition_penalty=None,
        engine=None,
    ):
        next_engine = self._normalize_local_engine(engine)
        if next_engine != self.local_engine:
            with self._local_model_lock:
                self._local_model = None
                self._local_model_engine = None
                self._local_model_device = ""
                self._local_warmup_done = False
            self.local_engine = next_engine

        if style not in self.CHATTERBOX_STYLE_PRESETS:
            style = "expressive"
        preset = self.CHATTERBOX_STYLE_PRESETS[style]
        self.provider = "local"
        self.is_on = bool(enabled)
        self.local_style = style
        self.local_prompt_path = (prompt_path or "").strip()
        self.local_exaggeration = self._clamp_float(exaggeration, 0.25, 2.0, preset["exaggeration"])
        self.local_cfg_weight = self._clamp_float(cfg_weight, 0.0, 1.0, preset["cfg_weight"])
        self.local_temperature = self._clamp_float(temperature, 0.05, 5.0, preset["temperature"])
        self.local_top_p = self._clamp_float(top_p, 0.05, 1.0, preset["top_p"])
        self.local_min_p = self._clamp_float(min_p, 0.0, 1.0, preset["min_p"])
        self.local_repetition_penalty = self._clamp_float(
            repetition_penalty, 1.0, 2.0, preset["repetition_penalty"]
        )
        return True, "Local voice settings updated."

    def local_status(self):
        runtime = self._local_runtime_info()
        engines = self._local_engine_options()
        selected = next((engine for engine in engines if engine["id"] == self.local_engine), None)
        engine_available = bool(selected and selected["available"])
        torch_available = bool(runtime["torch_available"])
        available = engine_available and torch_available and not runtime.get("error")

        if not engine_available:
            message = f"{self.LOCAL_ENGINE_LABELS.get(self.local_engine, self.local_engine)} is not installed."
            status = "missing_dependency"
        elif not torch_available:
            message = "Install PyTorch before using local Chatterbox voice."
            status = "missing_dependency"
        elif runtime.get("error"):
            message = f"Local voice device problem: {runtime['error']}"
            status = "device_error"
        elif runtime["cuda_available"]:
            message = f"{selected['label']} is available on {runtime['device']} ({runtime['device_name']})."
            status = "success"
        else:
            message = f"{selected['label']} is available, but Torch is CPU-only. Local voice will be slow until CUDA PyTorch is installed."
            status = "cpu_only"

        if self._local_model is not None:
            message += f" Model loaded on {self._local_model_device or runtime['device']}."
        elif self._local_preload_status == "loading":
            message += " Model download/load is running."
        elif self._local_preload_status == "error" and self._local_preload_error:
            message += f" Download/load failed: {self._local_preload_error}"
        elif available:
            message += " Model is not loaded yet. Click Download / Load Local Voice Model before testing; first use may download several GB."

        return {
            "status": status,
            "engine": self.local_engine,
            "engine_label": self.LOCAL_ENGINE_LABELS.get(self.local_engine, self.local_engine),
            "engines": engines,
            "available": available,
            "message": message,
            "style_presets": self.CHATTERBOX_STYLE_PRESETS,
            "torch": runtime,
            "device": runtime["device"],
            "cuda_available": runtime["cuda_available"],
            "model_loaded": self._local_model is not None,
            "preload_status": self._local_preload_status,
            "preload_error": self._local_preload_error,
            "last_generation_seconds": self.last_generation_seconds,
        }

    def local_model_loaded(self):
        return self._local_model is not None and self._local_model_engine == self.local_engine

    def generate_audio_for_text(self, text_to_speak, force=False):
        if not self.is_on and not force:
            return

        text = self._clean_text(text_to_speak)
        if not text:
            return

        if self.provider == "local":
            self._generate_local_audio(text)
        else:
            self._generate_elevenlabs_audio(text)

    def get_next_audio_chunk(self):
        if self.audio_output_queue:
            return self.audio_output_queue.popleft()
        return None

    def has_audio(self):
        return bool(self.audio_output_queue)

    def consume_last_error(self):
        error = self.last_error
        self.last_error = ""
        return error

    def _generate_elevenlabs_audio(self, text_to_speak):
        if not self.api_key or not self.voice_id or not self.client:
            return

        try:
            print(f"[INFO] Generating ElevenLabs audio: '{text_to_speak[:50]}...'")

            audio_stream = self.client.text_to_speech.convert(
                voice_id=self.voice_id,
                text=text_to_speak,
                model_id="eleven_multilingual_v2",
                voice_settings=VoiceSettings(stability=0.4, similarity_boost=0.7, style=0.1, use_speaker_boost=True),
            )

            audio_bytes_data = b"".join(audio_stream)
            self.audio_output_queue.append({"bytes": audio_bytes_data, "mimetype": "audio/mpeg"})
            print("[OK] ElevenLabs audio ready.")

        except Exception as e:
            print(f"[ERROR] ElevenLabs problem: {e}")

    def _generate_local_audio(self, text_to_speak):
        try:
            chunks = self._split_text_for_local_tts(text_to_speak)
            if not chunks:
                return

            print(f"[INFO] Generating local Chatterbox audio ({len(chunks)} chunk(s)): '{text_to_speak[:50]}...'")
            for chunk in chunks:
                started_at = time.perf_counter()
                with self._local_generation_lock:
                    model = self._get_chatterbox_model()
                    generated_audio = self._generate_local_waveform(model, chunk)
                    self.audio_output_queue.append({
                        "bytes": self._encode_wav_bytes(generated_audio, model.sr),
                        "mimetype": "audio/wav",
                    })
                self.last_generation_seconds = round(time.perf_counter() - started_at, 3)
                print(f"[OK] Local audio chunk ready in {self.last_generation_seconds}s.")
            self.last_error = ""
        except Exception as e:
            self.last_error = f"Local Chatterbox problem: {e}"
            print(f"[ERROR] {self.last_error}")

    def _get_chatterbox_model(self):
        with self._local_model_lock:
            if self._local_model is not None and self._local_model_engine == self.local_engine:
                return self._local_model
            try:
                runtime = self._local_runtime_info()
                if not runtime["torch_available"]:
                    raise RuntimeError("PyTorch is not installed.")
                if runtime.get("error"):
                    raise RuntimeError(runtime["error"])
                model_class = self._chatterbox_model_class(self.local_engine)
                device = runtime["device"]
                print(
                    "[INFO] Loading local Chatterbox model. "
                    "If the model weights are not cached, this may download several GB."
                )
                self._local_model = model_class.from_pretrained(device=device)
                self._local_model_engine = self.local_engine
                self._local_model_device = device
                print(f"[OK] {self.LOCAL_ENGINE_LABELS.get(self.local_engine, self.local_engine)} loaded on {device}.")
            except Exception as e:
                raise RuntimeError(f"Could not load Chatterbox. Install with requirements.txt. Details: {e}")
        return self._local_model

    def preload_local_model_async(self, force=False):
        if not force and (self.provider != "local" or not self.is_on):
            return False
        if self.local_model_loaded():
            return True
        if self._local_preload_thread and self._local_preload_thread.is_alive():
            return True

        def preload():
            self._local_preload_status = "loading"
            self._local_preload_error = ""
            try:
                model = self._get_chatterbox_model()
                self._warmup_local_model(model)
                self._local_preload_status = "ready"
            except Exception as e:
                self._local_preload_status = "error"
                self._local_preload_error = str(e)
                self.last_error = f"Local Chatterbox preload problem: {e}"
                print(f"[ERROR] {self.last_error}")

        self._local_preload_thread = threading.Thread(target=preload, daemon=True)
        self._local_preload_thread.start()
        return True

    def _warmup_local_model(self, model):
        if self._local_warmup_done or os.getenv("STROKEGPT_TTS_WARMUP", "1") == "0":
            return
        with self._local_generation_lock:
            started_at = time.perf_counter()
            self._generate_local_waveform(model, "Ready.")
            self._local_warmup_done = True
            print(f"[OK] Local Chatterbox warmup completed in {time.perf_counter() - started_at:.3f}s.")

    def _generate_local_waveform(self, model, text):
        kwargs = self._local_generation_kwargs()
        if self.local_prompt_path:
            kwargs["audio_prompt_path"] = self.local_prompt_path
        with self._torch_inference_mode():
            return model.generate(text, **kwargs)

    def _local_generation_kwargs(self):
        kwargs = {
            "exaggeration": self.local_exaggeration,
            "cfg_weight": self.local_cfg_weight,
            "temperature": self.local_temperature,
            "top_p": self.local_top_p,
            "min_p": self.local_min_p,
            "repetition_penalty": self.local_repetition_penalty,
        }
        if self.local_engine == self.LOCAL_ENGINE_CHATTERBOX_TURBO:
            kwargs["min_p"] = min(kwargs["min_p"], 0.05)
        return kwargs

    def _chatterbox_model_class(self, engine):
        with self._suppress_perth_pkg_resources_warning():
            if engine == self.LOCAL_ENGINE_CHATTERBOX_TURBO:
                from chatterbox.tts_turbo import ChatterboxTurboTTS

                return ChatterboxTurboTTS
            from chatterbox.tts import ChatterboxTTS

            return ChatterboxTTS

    def _encode_wav_bytes(self, waveform, sample_rate):
        if not hasattr(waveform, "detach"):
            raise TypeError("Chatterbox returned an unsupported audio buffer.")

        audio = waveform.detach().cpu()
        if audio.dim() == 1:
            audio = audio.unsqueeze(0)
        if audio.dim() != 2:
            raise ValueError(f"Expected 1D or 2D audio tensor, got {audio.dim()}D.")

        channels = int(audio.shape[0])
        pcm = (
            audio.clamp(-1.0, 1.0)
            .mul(32767)
            .round()
            .short()
            .transpose(0, 1)
            .contiguous()
            .numpy()
            .tobytes()
        )

        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(sample_rate))
            wav_file.writeframes(pcm)
        return output.getvalue()

    def _normalize_local_engine(self, engine):
        engine = (engine or self.local_engine or self.LOCAL_ENGINE_DEFAULT).strip()
        if engine not in self.LOCAL_ENGINE_LABELS:
            return self.LOCAL_ENGINE_DEFAULT
        return engine

    def _local_engine_options(self):
        return [
            {
                "id": engine_id,
                "label": label,
                "available": self._chatterbox_module_file_available(
                    "tts_turbo" if engine_id == self.LOCAL_ENGINE_CHATTERBOX_TURBO else "tts"
                ),
            }
            for engine_id, label in self.LOCAL_ENGINE_LABELS.items()
        ]

    def _chatterbox_module_file_available(self, module_name):
        spec = importlib.util.find_spec("chatterbox")
        if not spec or not spec.submodule_search_locations:
            return False
        for location in spec.submodule_search_locations:
            package_path = Path(location)
            if (package_path / f"{module_name}.py").exists():
                return True
            if (package_path / module_name / "__init__.py").exists():
                return True
        return False

    def _local_runtime_info(self):
        runtime = {
            "torch_available": False,
            "torch_version": "",
            "cuda_available": False,
            "cuda_version": "",
            "device_count": 0,
            "device_name": "",
            "device": "cpu",
            "device_override": os.getenv("STROKEGPT_TTS_DEVICE", "auto").strip().lower() or "auto",
        }
        if importlib.util.find_spec("torch") is None:
            return runtime

        try:
            import torch

            runtime["torch_available"] = True
            runtime["torch_version"] = getattr(torch, "__version__", "")
            runtime["cuda_available"] = bool(torch.cuda.is_available())
            runtime["cuda_version"] = getattr(torch.version, "cuda", "") or ""
            runtime["device_count"] = int(torch.cuda.device_count()) if runtime["cuda_available"] else 0
            runtime["device_name"] = torch.cuda.get_device_name(0) if runtime["cuda_available"] else ""
            runtime["device"] = self._select_tts_device(torch, runtime["device_override"])
        except Exception as e:
            runtime["error"] = str(e)
        return runtime

    def _select_tts_device(self, torch_module, requested):
        if requested == "cpu":
            return "cpu"
        if requested == "cuda":
            if not torch_module.cuda.is_available():
                raise RuntimeError("STROKEGPT_TTS_DEVICE=cuda was requested, but CUDA is not available.")
            return "cuda"
        if torch_module.cuda.is_available():
            return "cuda"
        return "cpu"

    def _split_text_for_local_tts(self, text):
        text = " ".join(str(text or "").split())
        if not text:
            return []
        if len(text) <= self.LOCAL_TTS_CHUNK_CHARS:
            return [text]

        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        chunks = []
        current = ""
        for sentence in sentences:
            if len(sentence) > self.LOCAL_TTS_CHUNK_CHARS:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._hard_split_text(sentence, self.LOCAL_TTS_CHUNK_CHARS))
                continue
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > self.LOCAL_TTS_CHUNK_CHARS:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def _hard_split_text(self, text, max_chars):
        words = text.split()
        chunks = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = word
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    @contextmanager
    def _torch_inference_mode(self):
        try:
            import torch
        except Exception:
            yield
            return
        with torch.inference_mode():
            yield

    @contextmanager
    def _suppress_perth_pkg_resources_warning(self):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"pkg_resources is deprecated as an API.*",
            )
            yield

    def _clean_text(self, text):
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text.startswith(("(", "[")):
            return ""
        return text

    def _clamp_float(self, value, low, high, default):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return max(low, min(high, value))
