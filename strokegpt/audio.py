import gc
import io
import inspect
import importlib.util
import logging
import os
import re
import threading
import time
import warnings
import wave
from collections import deque
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

class AudioService:
    LOCAL_ENGINE_CHATTERBOX = "chatterbox"
    LOCAL_ENGINE_CHATTERBOX_TURBO = "chatterbox_turbo"
    LOCAL_ENGINE_DEFAULT = LOCAL_ENGINE_CHATTERBOX_TURBO
    LOCAL_TTS_FIRST_CHUNK_CHARS = 150
    LOCAL_TTS_CHUNK_CHARS = 220
    LOCAL_TTS_TAIL_PADDING_MS = 120
    LOCAL_TTS_PENDING_TEXT_LIMIT = 1
    AUDIO_OUTPUT_QUEUE_LIMIT = 8
    AUDIO_OUTPUT_QUEUE_BYTES_LIMIT = 12 * 1024 * 1024
    LOCAL_TTS_WARMUP_TEXT = "Hello there. I am ready when you are."
    LOCAL_TTS_WARMUP_PASSES = 2
    LOCAL_TTS_IDLE_UNLOAD_SECONDS = 15 * 60
    LOCAL_ENGINE_LABELS = {
        LOCAL_ENGINE_CHATTERBOX_TURBO: "Chatterbox Turbo",
        LOCAL_ENGINE_CHATTERBOX: "Chatterbox Standard",
    }
    CHATTERBOX_REPO_IDS = {
        LOCAL_ENGINE_CHATTERBOX_TURBO: "ResembleAI/chatterbox-turbo",
        LOCAL_ENGINE_CHATTERBOX: "ResembleAI/chatterbox",
    }
    CHATTERBOX_CACHE_REQUIRED_FILES = {
        LOCAL_ENGINE_CHATTERBOX_TURBO: (
            "ve.safetensors",
            "t3_turbo_v1.safetensors",
            "s3gen_meanflow.safetensors",
            "tokenizer_config.json",
            "vocab.json",
            "merges.txt",
            "conds.pt",
        ),
        LOCAL_ENGINE_CHATTERBOX: (
            "ve.safetensors",
            "t3_cfg.safetensors",
            "s3gen.safetensors",
            "tokenizer.json",
            "conds.pt",
        ),
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
        self._local_preload_phase = "idle"
        self._local_preload_error = ""
        self._local_preload_started_at = None
        self._local_generation_status = "idle"
        self._local_generation_error = ""
        self._local_generation_started_at = None
        self._local_warmup_done = False
        self._local_prompt_conditionals_signature = None
        self._local_model_last_used_at = None
        self._local_idle_unload_timer = None
        self.last_generation_seconds = None
        self.last_error = ""

        self.audio_output_queue = deque()
        self._audio_output_queue_bytes = 0
        self._audio_output_dropped_count = 0
        self._audio_queue_condition = threading.Condition()
        self._tts_request_queue = deque()
        self._tts_request_condition = threading.Condition()
        self._tts_worker_thread = None
        self._tts_dropped_text_count = 0

    def set_provider(self, provider, enabled=None):
        if provider not in {"elevenlabs", "local"}:
            return False, "Unknown audio provider."
        previous_provider = self.provider
        self.provider = provider
        if enabled is not None:
            self.is_on = bool(enabled)
        if previous_provider == "local" and (provider != "local" or not self.is_on):
            self.unload_local_model(reason="local voice disabled", clear_queues=True)
        return True, "Audio provider updated."

    def set_api_key(self, api_key):
        self.api_key = api_key
        try:
            self.client = self._elevenlabs_client_class()(api_key=self.api_key)
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

        was_local = self.provider == "local"
        self.provider = "elevenlabs"
        self.voice_id = voice_id
        self.is_on = bool(enabled)
        if was_local:
            self.unload_local_model(reason="switched to ElevenLabs", clear_queues=True)

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
            self.unload_local_model(reason="local voice engine changed", clear_queues=True)
            self.local_engine = next_engine
            self._local_preload_status = "idle"
            self._local_preload_phase = "idle"
            self._local_preload_error = ""
            self._local_preload_started_at = None

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
        if not self.is_on:
            self.unload_local_model(reason="local voice disabled", clear_queues=True)
        return True, "Local voice settings updated."

    def local_status(self, *, lightweight=False):
        engines = self._local_engine_options()
        selected = next((engine for engine in engines if engine["id"] == self.local_engine), None)
        prompt_problem = self._local_prompt_path_problem()
        model_loaded = self.local_model_loaded()
        cached_model_path = self._chatterbox_cached_model_path()
        model_cached = bool(model_loaded or cached_model_path)
        model_cache_path = str(cached_model_path or "")
        if lightweight:
            message = "Local voice status will refresh after startup."
            if self.provider == "local" or self.is_on:
                message = "Checking local Chatterbox voice after the app opens so startup is not blocked by Torch/CUDA scans."
            return {
                "status": "unchecked",
                "engine": self.local_engine,
                "engine_label": self.LOCAL_ENGINE_LABELS.get(self.local_engine, self.local_engine),
                "engines": engines,
                "available": False,
                "message": message,
                "style_presets": self.CHATTERBOX_STYLE_PRESETS,
                "torch": {
                    "unchecked": True,
                    "torch_available": None,
                    "cuda_available": None,
                    "device": "",
                    "device_name": "",
                },
                "device": self._local_model_device,
                "cuda_available": None,
                "model_loaded": model_loaded,
                "model_cached": model_cached,
                "model_cache_path": model_cache_path,
                "load_requires_download": not model_cached,
                "preload_status": self._local_preload_status,
                "preload_phase": self._local_preload_phase,
                "preload_error": self._local_preload_error,
                "preload_elapsed_seconds": self._elapsed_seconds(self._local_preload_started_at),
                "preload_progress_percent": self._local_preload_progress_percent(),
                "generation_status": self._local_generation_status,
                "generation_error": self._local_generation_error,
                "generation_elapsed_seconds": self._elapsed_seconds(self._local_generation_started_at),
                "last_generation_seconds": self.last_generation_seconds,
                "tts_request_queue_depth": self.tts_request_queue_depth(),
                "tts_request_queue_limit": self.LOCAL_TTS_PENDING_TEXT_LIMIT,
                "tts_dropped_text_count": self._tts_dropped_text_count,
                "audio_output_queue_depth": self.audio_output_queue_depth(),
                "audio_output_queue_limit": self.AUDIO_OUTPUT_QUEUE_LIMIT,
                "audio_output_queue_bytes": self.audio_output_queue_bytes(),
                "audio_output_queue_bytes_limit": self.AUDIO_OUTPUT_QUEUE_BYTES_LIMIT,
                "audio_output_dropped_count": self._audio_output_dropped_count,
                "local_tts_idle_unload_seconds": self._local_idle_unload_seconds(),
                "prompt_path": self.local_prompt_path,
            }

        runtime = self._local_runtime_info()
        engine_available = bool(selected and selected["available"])
        torch_available = bool(runtime["torch_available"])
        available = engine_available and torch_available and not runtime.get("error") and not prompt_problem

        if not engine_available:
            message = f"{self.LOCAL_ENGINE_LABELS.get(self.local_engine, self.local_engine)} is not installed."
            status = "missing_dependency"
        elif not torch_available:
            message = "Install PyTorch before using local Chatterbox voice."
            status = "missing_dependency"
        elif runtime.get("error"):
            message = f"Local voice device problem: {runtime['error']}"
            status = "device_error"
        elif prompt_problem:
            message = prompt_problem
            status = "sample_missing"
        elif runtime["cuda_available"]:
            message = f"{selected['label']} is available on {runtime['device']} ({runtime['device_name']})."
            status = "success"
        else:
            message = f"{selected['label']} is available, but Torch is CPU-only. Local voice will be slow until CUDA PyTorch is installed."
            status = "cpu_only"

        if model_loaded:
            message += f" Model loaded on {self._local_model_device or runtime['device']}."
        elif self._local_preload_status == "loading":
            load_label = "load" if model_cached else "download/load"
            message += f" Model {load_label} is running ({self._local_preload_phase.replace('_', ' ')})."
        elif self._local_preload_status == "error" and self._local_preload_error:
            message += f" Download/load failed: {self._local_preload_error}"
        elif available and model_cached:
            message += " Model is cached but not loaded yet. It can load in the background without downloading."
        elif available:
            message += " Model is not loaded yet. Click Download / Load Local Voice Model before testing; first use may download several GB."

        if self._local_generation_status == "generating":
            message += " Local voice generation is running."
        elif self._local_generation_status == "error" and self._local_generation_error:
            message += f" Last generation failed: {self._local_generation_error}"

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
            "model_loaded": model_loaded,
            "model_cached": model_cached,
            "model_cache_path": model_cache_path,
            "load_requires_download": not model_cached,
            "preload_status": self._local_preload_status,
            "preload_phase": self._local_preload_phase,
            "preload_error": self._local_preload_error,
            "preload_elapsed_seconds": self._elapsed_seconds(self._local_preload_started_at),
            "preload_progress_percent": self._local_preload_progress_percent(),
            "generation_status": self._local_generation_status,
            "generation_error": self._local_generation_error,
            "generation_elapsed_seconds": self._elapsed_seconds(self._local_generation_started_at),
            "last_generation_seconds": self.last_generation_seconds,
            "tts_request_queue_depth": self.tts_request_queue_depth(),
            "tts_request_queue_limit": self.LOCAL_TTS_PENDING_TEXT_LIMIT,
            "tts_dropped_text_count": self._tts_dropped_text_count,
            "audio_output_queue_depth": self.audio_output_queue_depth(),
            "audio_output_queue_limit": self.AUDIO_OUTPUT_QUEUE_LIMIT,
            "audio_output_queue_bytes": self.audio_output_queue_bytes(),
            "audio_output_queue_bytes_limit": self.AUDIO_OUTPUT_QUEUE_BYTES_LIMIT,
            "audio_output_dropped_count": self._audio_output_dropped_count,
            "local_tts_idle_unload_seconds": self._local_idle_unload_seconds(),
            "prompt_path": self.local_prompt_path,
        }

    def local_model_loaded(self):
        return self._local_model is not None and self._local_model_engine == self.local_engine

    def measure_output_latency(self, text_to_speak="Ready."):
        if self.provider != "local":
            return {
                "status": "skipped",
                "provider": self.provider,
                "message": "Hosted voice output latency is not measured automatically to avoid API usage.",
            }
        if not self.local_model_loaded():
            return {
                "status": "skipped",
                "provider": self.provider,
                "engine": self.local_engine,
                "message": "Local voice model is not loaded. Use Download / Load Local Voice Model before testing output latency.",
            }

        text = self._clean_text(text_to_speak) or "Ready."
        self._local_generation_status = "generating"
        self._local_generation_error = ""
        self._local_generation_started_at = time.perf_counter()
        started_at = time.perf_counter()
        try:
            with self._local_generation_lock:
                model = self._get_chatterbox_model()
                generated_audio = self._generate_local_waveform(model, text)
                audio_bytes = self._encode_wav_bytes(generated_audio, model.sr)
            elapsed_seconds = time.perf_counter() - started_at
            self.last_generation_seconds = round(elapsed_seconds, 3)
            self._local_generation_status = "idle"
            self._local_generation_started_at = None
            self.last_error = ""
            return {
                "status": "ok",
                "provider": self.provider,
                "engine": self.local_engine,
                "engine_label": self.LOCAL_ENGINE_LABELS.get(self.local_engine, self.local_engine),
                "device": self._local_model_device,
                "elapsed_ms": int(elapsed_seconds * 1000),
                "audio_bytes": len(audio_bytes),
                "message": "Generated a diagnostic local voice sample without queueing playback.",
            }
        except Exception as e:
            error = str(e)
            self._local_generation_status = "error"
            self._local_generation_error = error
            self._local_generation_started_at = None
            self._local_preload_status = "error"
            self._local_preload_phase = "error"
            self._local_preload_error = error
            self._reset_local_model_after_failure()
            self.last_error = f"Local Chatterbox problem: {error}"
            return {
                "status": "error",
                "provider": self.provider,
                "engine": self.local_engine,
                "message": self.last_error,
            }

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

    def enqueue_text_for_audio(self, text_to_speak):
        if self.provider != "local":
            threading.Thread(target=self.generate_audio_for_text, args=(text_to_speak,), daemon=True).start()
            return True
        if not self.is_on:
            return False
        text = self._clean_text(text_to_speak)
        if not text:
            return False
        with self._tts_request_condition:
            while len(self._tts_request_queue) >= self.LOCAL_TTS_PENDING_TEXT_LIMIT:
                dropped = self._tts_request_queue.popleft()
                self._tts_dropped_text_count += 1
                print(f"[INFO] Local TTS fell behind; skipping older queued text: '{dropped[:60]}...'")
            self._tts_request_queue.append(text)
            self._ensure_tts_worker_started_locked()
            self._tts_request_condition.notify_all()
        return True

    def _ensure_tts_worker_started_locked(self):
        if self._tts_worker_thread and self._tts_worker_thread.is_alive():
            return
        self._tts_worker_thread = threading.Thread(target=self._tts_worker_loop, daemon=True)
        self._tts_worker_thread.start()

    def _tts_worker_loop(self):
        while True:
            with self._tts_request_condition:
                while not self._tts_request_queue:
                    self._tts_request_condition.wait()
                text = self._tts_request_queue.popleft()
            self.generate_audio_for_text(text)

    def get_next_audio_chunk(self):
        return self.wait_for_audio_chunk(0.0)

    def wait_for_audio_chunk(self, wait_seconds=0.0, defer_predicate=None):
        deadline = time.monotonic() + max(0.0, float(wait_seconds or 0.0))
        with self._audio_queue_condition:
            while not self.audio_output_queue:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._audio_queue_condition.wait(timeout=remaining)
            if defer_predicate and defer_predicate():
                return None
            chunk = self.audio_output_queue.popleft()
            self._audio_output_queue_bytes = max(
                0,
                self._audio_output_queue_bytes - self._audio_chunk_size(chunk),
            )
            return chunk

    def _enqueue_audio_chunk(self, audio_bytes, mimetype):
        with self._audio_queue_condition:
            chunk = {"bytes": audio_bytes, "mimetype": mimetype}
            self.audio_output_queue.append(chunk)
            self._audio_output_queue_bytes += self._audio_chunk_size(chunk)
            self._trim_audio_output_queue_locked()
            self._audio_queue_condition.notify_all()

    def clear_audio_queue(self):
        with self._audio_queue_condition:
            self.audio_output_queue.clear()
            self._audio_output_queue_bytes = 0
        with self._tts_request_condition:
            self._tts_request_queue.clear()
        return None

    def has_audio(self):
        with self._audio_queue_condition:
            return bool(self.audio_output_queue)

    def audio_output_queue_depth(self):
        with self._audio_queue_condition:
            return len(self.audio_output_queue)

    def audio_output_queue_bytes(self):
        with self._audio_queue_condition:
            return self._audio_output_queue_bytes

    def _audio_chunk_size(self, chunk):
        try:
            return len(chunk.get("bytes") or b"")
        except Exception:
            return 0

    def _trim_audio_output_queue_locked(self):
        while (
            len(self.audio_output_queue) > self.AUDIO_OUTPUT_QUEUE_LIMIT
            or self._audio_output_queue_bytes > self.AUDIO_OUTPUT_QUEUE_BYTES_LIMIT
        ):
            dropped = self.audio_output_queue.popleft()
            self._audio_output_queue_bytes = max(
                0,
                self._audio_output_queue_bytes - self._audio_chunk_size(dropped),
            )
            self._audio_output_dropped_count += 1
        return None

    def tts_request_queue_depth(self):
        with self._tts_request_condition:
            return len(self._tts_request_queue)

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
                voice_settings=self._elevenlabs_voice_settings(
                    stability=0.4,
                    similarity_boost=0.7,
                    style=0.1,
                    use_speaker_boost=True,
                ),
            )

            audio_bytes_data = b"".join(audio_stream)
            self._enqueue_audio_chunk(audio_bytes_data, "audio/mpeg")
            self.last_error = ""
            print("[OK] ElevenLabs audio ready.")

        except Exception as e:
            self.last_error = f"ElevenLabs problem: {e}"
            print(f"[ERROR] {self.last_error}")

    def _generate_local_audio(self, text_to_speak):
        try:
            chunks = self._split_text_for_local_tts(text_to_speak)
            if not chunks:
                return

            print(f"[INFO] Generating local Chatterbox audio ({len(chunks)} chunk(s)): '{text_to_speak[:50]}...'")
            self._local_generation_status = "generating"
            self._local_generation_error = ""
            self._local_generation_started_at = time.perf_counter()
            for chunk in chunks:
                started_at = time.perf_counter()
                with self._local_generation_lock:
                    model = self._get_chatterbox_model()
                    generated_audio = self._generate_local_waveform(model, chunk)
                    self._enqueue_audio_chunk(self._encode_wav_bytes(generated_audio, model.sr), "audio/wav")
                self.last_generation_seconds = round(time.perf_counter() - started_at, 3)
                print(f"[OK] Local audio chunk ready in {self.last_generation_seconds}s.")
            self._local_generation_status = "idle"
            self._local_generation_started_at = None
            self.last_error = ""
        except Exception as e:
            error = str(e)
            self._local_generation_status = "error"
            self._local_generation_error = error
            self._local_generation_started_at = None
            self._local_preload_status = "error"
            self._local_preload_phase = "error"
            self._local_preload_error = error
            self._reset_local_model_after_failure()
            self.last_error = f"Local Chatterbox problem: {error}"
            print(f"[ERROR] {self.last_error}")

    def local_model_cached(self):
        return bool(self.local_model_loaded() or self._chatterbox_cached_model_path())

    def _get_chatterbox_model(self, *, require_cached=False):
        with self._local_model_lock:
            if self._local_model is not None and self._local_model_engine == self.local_engine:
                model = self._local_model
            else:
                try:
                    runtime = self._local_runtime_info()
                    if not runtime["torch_available"]:
                        raise RuntimeError("PyTorch is not installed.")
                    if runtime.get("error"):
                        raise RuntimeError(runtime["error"])
                    model_class = self._chatterbox_model_class(self.local_engine)
                    device = runtime["device"]
                    cached_model_path = self._chatterbox_cached_model_path()
                    with self._torch_float32_default_dtype():
                        if cached_model_path:
                            print(
                                "[INFO] Loading local Chatterbox model from cached weights: "
                                f"{cached_model_path}"
                            )
                            with self._suppress_chatterbox_console_output():
                                loaded_model = model_class.from_local(cached_model_path, device=device)
                        else:
                            if require_cached:
                                raise RuntimeError(
                                    "Local Chatterbox weights are not cached yet. Use Download / Load Local Voice Model once."
                                )
                            print(
                                "[INFO] Loading local Chatterbox model. "
                                "If the model weights are not cached, this may download several GB."
                            )
                            with self._suppress_chatterbox_console_output():
                                loaded_model = model_class.from_pretrained(device=device)
                    self._local_model = self._prepare_chatterbox_model_for_inference(loaded_model)
                    self._local_model_engine = self.local_engine
                    self._local_model_device = device
                    self._local_model_last_used_at = time.monotonic()
                    model = self._local_model
                    print(f"[OK] {self.LOCAL_ENGINE_LABELS.get(self.local_engine, self.local_engine)} loaded on {device}.")
                except Exception as e:
                    raise RuntimeError(f"Could not load Chatterbox. Install with requirements.txt. Details: {e}")
        self._mark_local_model_used()
        return model

    def preload_local_model_async(self, force=False, require_cached=False):
        if not force and (self.provider != "local" or not self.is_on):
            return False
        if self.local_model_loaded():
            self._mark_local_model_used()
            self._local_preload_status = "ready"
            self._local_preload_phase = "ready"
            self._local_preload_error = ""
            self._local_preload_started_at = None
            return True
        if require_cached and not self._chatterbox_cached_model_path():
            return False
        if self._local_preload_thread and self._local_preload_thread.is_alive():
            return True

        def preload():
            self._local_preload_status = "loading"
            self._local_preload_phase = "loading_model"
            self._local_preload_error = ""
            self._local_preload_started_at = time.perf_counter()
            try:
                model = (
                    self._get_chatterbox_model(require_cached=True)
                    if require_cached
                    else self._get_chatterbox_model()
                )
                self._local_preload_phase = "warming_up"
                self._warmup_local_model(model)
                self._local_preload_status = "ready"
                self._local_preload_phase = "ready"
                self._local_preload_started_at = None
            except Exception as e:
                error = str(e)
                self._local_preload_status = "error"
                self._local_preload_phase = "error"
                self._local_preload_error = error
                self._local_preload_started_at = None
                self._reset_local_model_after_failure()
                self.last_error = f"Local Chatterbox preload problem: {error}"
                print(f"[ERROR] {self.last_error}")

        self._local_preload_thread = threading.Thread(target=preload, daemon=True)
        self._local_preload_thread.start()
        return True

    def preload_local_model_async_if_cached(self):
        return self.preload_local_model_async(require_cached=True)

    def _warmup_local_model(self, model):
        if self._local_warmup_done or os.getenv("STROKEGPT_TTS_WARMUP", "1") == "0":
            return
        with self._local_generation_lock:
            started_at = time.perf_counter()
            for _index in range(max(1, int(self.LOCAL_TTS_WARMUP_PASSES))):
                self._generate_local_waveform(model, self.LOCAL_TTS_WARMUP_TEXT)
            self._local_warmup_done = True
            self._mark_local_model_used()
            print(f"[OK] Local Chatterbox warmup completed in {time.perf_counter() - started_at:.3f}s.")

    def _reset_local_model_after_failure(self):
        self._release_local_model_state()
        gc.collect()
        self._empty_cuda_cache()

    def unload_local_model(self, *, reason="manual", clear_queues=False):
        if clear_queues:
            self.clear_audio_queue()
        with self._local_generation_lock:
            had_model = self.local_model_loaded()
            self._release_local_model_state()
        gc.collect()
        self._empty_cuda_cache()
        if had_model:
            print(f"[INFO] Local Chatterbox model unloaded ({reason}).")
        return had_model

    def _release_local_model_state(self):
        self._cancel_local_idle_unload_timer()
        with self._local_model_lock:
            self._local_model = None
            self._local_model_engine = None
            self._local_model_device = ""
            self._local_warmup_done = False
            self._local_prompt_conditionals_signature = None
            self._local_model_last_used_at = None
        return None

    def _mark_local_model_used(self):
        self._local_model_last_used_at = time.monotonic()
        self._schedule_local_idle_unload()

    def _local_idle_unload_seconds(self):
        raw = os.getenv("STROKEGPT_LOCAL_TTS_IDLE_UNLOAD_SECONDS")
        try:
            value = float(raw) if raw is not None else self.LOCAL_TTS_IDLE_UNLOAD_SECONDS
        except (TypeError, ValueError):
            value = self.LOCAL_TTS_IDLE_UNLOAD_SECONDS
        return max(0.0, value)

    def _cancel_local_idle_unload_timer(self):
        timer = self._local_idle_unload_timer
        self._local_idle_unload_timer = None
        if timer:
            timer.cancel()

    def _schedule_local_idle_unload(self):
        seconds = self._local_idle_unload_seconds()
        if seconds <= 0:
            self._cancel_local_idle_unload_timer()
            return
        with self._local_model_lock:
            if self._local_model is None or self._local_model_engine != self.local_engine:
                self._cancel_local_idle_unload_timer()
                return
        self._cancel_local_idle_unload_timer()
        timer = threading.Timer(seconds, self._unload_local_model_if_idle)
        timer.daemon = True
        self._local_idle_unload_timer = timer
        timer.start()

    def _unload_local_model_if_idle(self):
        seconds = self._local_idle_unload_seconds()
        if seconds <= 0:
            return
        if self._local_generation_status == "generating" or self._local_preload_status == "loading":
            self._schedule_local_idle_unload()
            return
        last_used = self._local_model_last_used_at
        if last_used is None:
            return
        idle_for = time.monotonic() - last_used
        if idle_for < seconds:
            self._schedule_local_idle_unload()
            return
        self._local_preload_status = "idle"
        self._local_preload_phase = "idle"
        self._local_preload_error = ""
        self._local_preload_started_at = None
        self.unload_local_model(reason=f"idle for {int(seconds)}s")

    def _empty_cuda_cache(self):
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _generate_local_waveform(self, model, text):
        kwargs = self._local_generation_kwargs()
        self._prepare_chatterbox_model_for_inference(model)
        with self._torch_float32_default_dtype(), self._torch_inference_mode():
            if self.local_prompt_path:
                with self._suppress_chatterbox_console_output():
                    prepared_prompt = self._prepare_chatterbox_prompt_conditionals(model, kwargs)
                if not prepared_prompt:
                    kwargs["audio_prompt_path"] = self.local_prompt_path
            self._coerce_chatterbox_conditionals_to_float32(model)
            with self._suppress_chatterbox_console_output():
                generated = model.generate(text, **kwargs)
            return self._coerce_local_waveform_dtype(generated)

    def _prepare_chatterbox_model_for_inference(self, model):
        self._patch_chatterbox_float32_inputs(model)
        self._coerce_chatterbox_conditionals_to_float32(model)
        return model

    def _patch_chatterbox_float32_inputs(self, model):
        if getattr(model, "_strokegpt_float32_inputs_patched", False):
            return
        try:
            import numpy as np
            import torch
        except Exception:
            return

        def coerce_audio(value):
            if isinstance(value, np.ndarray) and np.issubdtype(value.dtype, np.floating):
                return value.astype(np.float32, copy=False)
            if torch.is_tensor(value) and value.is_floating_point() and value.dtype != torch.float32:
                return value.to(dtype=torch.float32)
            return value

        tokenizer = getattr(getattr(model, "s3gen", None), "tokenizer", None)
        if tokenizer is not None and not getattr(tokenizer, "_strokegpt_float32_inputs_patched", False):
            original_prepare_audio = getattr(tokenizer, "_prepare_audio", None)
            if callable(original_prepare_audio):
                def prepare_audio_float32(wavs, _original=original_prepare_audio):
                    return [coerce_audio(wav) for wav in _original([coerce_audio(wav) for wav in wavs])]

                tokenizer._prepare_audio = prepare_audio_float32

            original_pad = getattr(tokenizer, "pad", None)
            if callable(original_pad):
                def pad_float32(wavs, sr, _original=original_pad):
                    return [coerce_audio(wav) for wav in _original([coerce_audio(wav) for wav in wavs], sr)]

                tokenizer.pad = pad_float32

            tokenizer._strokegpt_float32_inputs_patched = True

        voice_encoder = getattr(model, "ve", None)
        if voice_encoder is not None and not getattr(voice_encoder, "_strokegpt_float32_inputs_patched", False):
            original_embeds_from_wavs = getattr(voice_encoder, "embeds_from_wavs", None)
            if callable(original_embeds_from_wavs):
                def embeds_from_wavs_float32(wavs, *args, _original=original_embeds_from_wavs, **kwargs):
                    return _original([coerce_audio(wav) for wav in wavs], *args, **kwargs)

                voice_encoder.embeds_from_wavs = embeds_from_wavs_float32
                voice_encoder._strokegpt_float32_inputs_patched = True

        original_norm_loudness = getattr(model, "norm_loudness", None)
        if callable(original_norm_loudness) and not getattr(model, "_strokegpt_norm_loudness_patched", False):
            def norm_loudness_float32(wav, *args, _original=original_norm_loudness, **kwargs):
                return coerce_audio(_original(coerce_audio(wav), *args, **kwargs))

            model.norm_loudness = norm_loudness_float32
            model._strokegpt_norm_loudness_patched = True

        model._strokegpt_float32_inputs_patched = True

    def _prepare_chatterbox_prompt_conditionals(self, model, generation_kwargs):
        prepare = getattr(model, "prepare_conditionals", None)
        if not callable(prepare):
            return False

        signature = self._chatterbox_prompt_conditionals_signature(model, generation_kwargs)
        if signature and self._local_prompt_conditionals_signature == signature:
            return True

        prepare_kwargs = {}
        try:
            parameters = inspect.signature(prepare).parameters
        except (TypeError, ValueError):
            parameters = {}

        if not parameters or "exaggeration" in parameters:
            prepare_kwargs["exaggeration"] = generation_kwargs.get("exaggeration", self.local_exaggeration)
        if "norm_loudness" in parameters:
            prepare_kwargs["norm_loudness"] = True

        try:
            prepare(self.local_prompt_path, **prepare_kwargs)
        except TypeError:
            if parameters or not prepare_kwargs:
                raise
            prepare(self.local_prompt_path)
        self._coerce_chatterbox_conditionals_to_float32(model)
        self._local_prompt_conditionals_signature = signature
        return True

    def _chatterbox_prompt_conditionals_signature(self, model, generation_kwargs):
        if not self.local_prompt_path:
            return None
        path = Path(self.local_prompt_path)
        try:
            resolved_path = str(path.resolve(strict=False))
        except Exception:
            resolved_path = str(path)
        try:
            stat = path.stat()
            file_signature = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            file_signature = None
        return (
            id(model),
            self.local_engine,
            resolved_path,
            file_signature,
            round(float(generation_kwargs.get("exaggeration", self.local_exaggeration)), 4),
            True,
        )

    def _coerce_chatterbox_conditionals_to_float32(self, model):
        try:
            import torch
        except Exception:
            return

        conds = getattr(model, "conds", None)
        if conds is None:
            return

        device = getattr(model, "device", None) or None
        t3_cond = getattr(conds, "t3", None)
        if t3_cond is not None:
            to_method = getattr(t3_cond, "to", None)
            if callable(to_method):
                try:
                    to_method(device=device, dtype=torch.float32)
                except TypeError:
                    to_method(device=device)
            for name, value in vars(t3_cond).items():
                coerced = self._coerce_chatterbox_tensor_to_float32(value, torch, device)
                if coerced is not value:
                    setattr(t3_cond, name, coerced)

        gen_cond = getattr(conds, "gen", None)
        if isinstance(gen_cond, dict):
            for key, value in list(gen_cond.items()):
                gen_cond[key] = self._coerce_chatterbox_tensor_to_float32(value, torch, device)

    def _coerce_chatterbox_tensor_to_float32(self, value, torch, device):
        if not torch.is_tensor(value):
            return value
        if value.is_floating_point():
            if device:
                return value.to(device=device, dtype=torch.float32)
            return value.to(dtype=torch.float32)
        if device:
            return value.to(device=device)
        return value

    def _coerce_local_waveform_dtype(self, waveform):
        try:
            import torch
        except Exception:
            return waveform
        if torch.is_tensor(waveform) and waveform.is_floating_point() and waveform.dtype != torch.float32:
            return waveform.to(dtype=torch.float32)
        return waveform

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

    def _elevenlabs_client_class(self):
        from elevenlabs.client import ElevenLabs

        return ElevenLabs

    def _elevenlabs_voice_settings(self, **kwargs):
        from elevenlabs import VoiceSettings

        return VoiceSettings(**kwargs)

    def _encode_wav_bytes(self, waveform, sample_rate):
        if not hasattr(waveform, "detach"):
            raise TypeError("Chatterbox returned an unsupported audio buffer.")

        audio = waveform.detach().cpu()
        if audio.dim() == 1:
            audio = audio.unsqueeze(0)
        if audio.dim() != 2:
            raise ValueError(f"Expected 1D or 2D audio tensor, got {audio.dim()}D.")

        channels = int(audio.shape[0])
        sample_rate = int(sample_rate)
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
        tail_frames = max(0, round(sample_rate * self.LOCAL_TTS_TAIL_PADDING_MS / 1000))
        if tail_frames:
            pcm += b"\x00" * tail_frames * channels * 2

        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return output.getvalue()

    def _normalize_local_engine(self, engine):
        engine = (engine or self.local_engine or self.LOCAL_ENGINE_DEFAULT).strip()
        if engine not in self.LOCAL_ENGINE_LABELS:
            return self.LOCAL_ENGINE_DEFAULT
        return engine

    def _chatterbox_hf_cache_roots(self):
        roots = []
        seen = set()

        def add_root(path):
            if not path:
                return
            try:
                root = Path(path).expanduser()
            except (TypeError, ValueError):
                return
            key = os.path.normcase(str(root))
            if key not in seen:
                seen.add(key)
                roots.append(root)

        add_root(os.getenv("HF_HUB_CACHE"))
        add_root(os.getenv("HUGGINGFACE_HUB_CACHE"))
        hf_home = os.getenv("HF_HOME")
        if hf_home:
            add_root(Path(hf_home) / "hub")
        add_root(Path.home() / ".cache" / "huggingface" / "hub")
        return roots

    def _chatterbox_cached_model_path(self, engine=None):
        engine = self._normalize_local_engine(engine)
        repo_id = self.CHATTERBOX_REPO_IDS.get(engine)
        if not repo_id:
            return None
        repo_cache_dir = f"models--{repo_id.replace('/', '--')}"
        required_files = self.CHATTERBOX_CACHE_REQUIRED_FILES.get(engine, ())
        candidates = []
        for root in self._chatterbox_hf_cache_roots():
            snapshots_dir = root / repo_cache_dir / "snapshots"
            if not snapshots_dir.is_dir():
                continue
            try:
                snapshot_dirs = [path for path in snapshots_dir.iterdir() if path.is_dir()]
            except OSError:
                continue
            candidates.extend(snapshot_dirs)
        candidates.sort(key=self._path_mtime_or_zero, reverse=True)
        for candidate in candidates:
            if all((candidate / filename).exists() for filename in required_files):
                return candidate
        return None

    def _path_mtime_or_zero(self, path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

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

    def _local_prompt_path_problem(self):
        if not self.local_prompt_path:
            return ""
        if not Path(self.local_prompt_path).exists():
            return f"Reference voice sample not found: {self.local_prompt_path}"
        return ""

    def _elapsed_seconds(self, started_at):
        if not started_at:
            return None
        return max(0, round(time.perf_counter() - started_at, 1))

    def _local_preload_progress_percent(self):
        if self.local_model_loaded() or self._local_preload_status == "ready":
            return 100
        if self._local_preload_status != "loading":
            return None
        elapsed = float(self._elapsed_seconds(self._local_preload_started_at) or 0.0)
        if self._local_preload_phase == "warming_up":
            percent = 90 + (elapsed / (elapsed + 10.0)) * 9.0
            return int(max(90, min(99, round(percent))))
        percent = 1 + (elapsed / (elapsed + 60.0)) * 94.0
        return int(max(1, min(95, round(percent))))

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

        sentences = self._local_tts_text_segments(text)
        chunks = []
        current = ""
        for sentence in sentences:
            max_chars = self.LOCAL_TTS_FIRST_CHUNK_CHARS if not chunks and not current else self.LOCAL_TTS_CHUNK_CHARS
            if len(sentence) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                hard_chunks = self._hard_split_text(sentence, max_chars)
                chunks.extend(hard_chunks)
                continue
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def _local_tts_text_segments(self, text):
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        segments = []
        for sentence in sentences:
            if len(sentence) <= self.LOCAL_TTS_CHUNK_CHARS:
                segments.append(sentence)
                continue
            clauses = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]
            if len(clauses) <= 1:
                segments.append(sentence)
            else:
                segments.extend(clauses)
        return segments

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
    def _torch_float32_default_dtype(self):
        try:
            import torch
        except Exception:
            yield
            return

        get_default_dtype = getattr(torch, "get_default_dtype", None)
        set_default_dtype = getattr(torch, "set_default_dtype", None)
        if not callable(get_default_dtype) or not callable(set_default_dtype):
            yield
            return

        previous_dtype = get_default_dtype()
        try:
            if previous_dtype != torch.float32:
                set_default_dtype(torch.float32)
            yield
        finally:
            if get_default_dtype() != previous_dtype:
                set_default_dtype(previous_dtype)

    @contextmanager
    def _suppress_chatterbox_console_output(self):
        verbose = os.getenv("STROKEGPT_TTS_VERBOSE", "").strip().lower()
        if verbose in {"1", "true", "yes", "on"}:
            yield
            return

        class SilentStream:
            def write(self, _value):
                return 0

            def flush(self):
                return None

        previous_logging_disable = logging.root.manager.disable
        previous_root_handlers = list(logging.root.handlers)
        sink = SilentStream()
        try:
            logging.disable(logging.CRITICAL)
            with redirect_stdout(sink), redirect_stderr(sink):
                yield
        finally:
            logging.disable(previous_logging_disable)
            for handler in list(logging.root.handlers):
                if handler not in previous_root_handlers and getattr(handler, "stream", None) is sink:
                    logging.root.removeHandler(handler)
                    handler.close()

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
