import io
import re
import warnings
import wave
from collections import deque
from contextlib import contextmanager

from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings


class AudioService:
    LOCAL_ENGINE_CHATTERBOX = "chatterbox"
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

        self.local_engine = self.LOCAL_ENGINE_CHATTERBOX
        self.local_style = "expressive"
        self.local_prompt_path = ""
        self.local_exaggeration = 0.65
        self.local_cfg_weight = 0.35
        self.local_temperature = 0.85
        self.local_top_p = 1.0
        self.local_min_p = 0.05
        self.local_repetition_penalty = 1.2
        self._local_model = None
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
    ):
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
        try:
            with self._suppress_perth_pkg_resources_warning():
                import chatterbox.tts  # noqa: F401
            return {
                "status": "success",
                "engine": self.local_engine,
                "available": True,
                "message": "Chatterbox is available.",
                "style_presets": self.CHATTERBOX_STYLE_PRESETS,
            }
        except Exception as e:
            return {
                "status": "missing_dependency",
                "engine": self.local_engine,
                "available": False,
                "message": f"Install local voice dependencies first: {e}",
                "style_presets": self.CHATTERBOX_STYLE_PRESETS,
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
            model = self._get_chatterbox_model()
            kwargs = {
                "exaggeration": self.local_exaggeration,
                "cfg_weight": self.local_cfg_weight,
                "temperature": self.local_temperature,
                "top_p": self.local_top_p,
                "min_p": self.local_min_p,
                "repetition_penalty": self.local_repetition_penalty,
            }
            if self.local_prompt_path:
                kwargs["audio_prompt_path"] = self.local_prompt_path

            print(f"[INFO] Generating local Chatterbox audio: '{text_to_speak[:50]}...'")
            generated_audio = model.generate(text_to_speak, **kwargs)

            self.audio_output_queue.append({
                "bytes": self._encode_wav_bytes(generated_audio, model.sr),
                "mimetype": "audio/wav",
            })
            self.last_error = ""
            print("[OK] Local audio ready.")
        except Exception as e:
            self.last_error = f"Local Chatterbox problem: {e}"
            print(f"[ERROR] {self.last_error}")

    def _get_chatterbox_model(self):
        if self._local_model is None:
            try:
                import torch
                with self._suppress_perth_pkg_resources_warning():
                    from chatterbox.tts import ChatterboxTTS

                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._local_model = ChatterboxTTS.from_pretrained(device=device)
                print(f"[OK] Chatterbox loaded on {device}.")
            except Exception as e:
                raise RuntimeError(f"Could not load Chatterbox. Install with requirements.txt. Details: {e}")
        return self._local_model

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
