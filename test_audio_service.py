import importlib.util
import importlib.machinery
import io
import sys
import types
import unittest
import warnings
import wave


elevenlabs_module = types.ModuleType("elevenlabs")
elevenlabs_module.__spec__ = importlib.machinery.ModuleSpec("elevenlabs", loader=None)
elevenlabs_module.VoiceSettings = lambda **kwargs: kwargs
elevenlabs_client_module = types.ModuleType("elevenlabs.client")
elevenlabs_client_module.__spec__ = importlib.machinery.ModuleSpec("elevenlabs.client", loader=None)
elevenlabs_client_module.ElevenLabs = object
sys.modules.setdefault("elevenlabs", elevenlabs_module)
sys.modules.setdefault("elevenlabs.client", elevenlabs_client_module)

from strokegpt.audio import AudioService


class AudioServiceTests(unittest.TestCase):
    def test_chatterbox_style_presets_are_available(self):
        expected = {"default", "calm", "expressive", "dramatic", "energetic", "clone_stable"}

        self.assertEqual(set(AudioService.CHATTERBOX_STYLE_PRESETS), expected)

    def test_local_style_preset_sets_generation_controls(self):
        service = AudioService()
        service.configure_local_voice(True, style="dramatic")

        preset = AudioService.CHATTERBOX_STYLE_PRESETS["dramatic"]
        self.assertEqual(service.local_style, "dramatic")
        self.assertEqual(service.local_exaggeration, preset["exaggeration"])
        self.assertEqual(service.local_cfg_weight, preset["cfg_weight"])
        self.assertEqual(service.local_temperature, preset["temperature"])
        self.assertEqual(service.local_top_p, preset["top_p"])
        self.assertEqual(service.local_min_p, preset["min_p"])
        self.assertEqual(service.local_repetition_penalty, preset["repetition_penalty"])

    def test_manual_local_controls_override_preset(self):
        service = AudioService()
        service.configure_local_voice(
            True,
            style="calm",
            exaggeration=0.8,
            cfg_weight=0.2,
            temperature=1.1,
            top_p=0.8,
            min_p=0.1,
            repetition_penalty=1.4,
        )

        self.assertEqual(service.local_style, "calm")
        self.assertEqual(service.local_exaggeration, 0.8)
        self.assertEqual(service.local_cfg_weight, 0.2)
        self.assertEqual(service.local_temperature, 1.1)
        self.assertEqual(service.local_top_p, 0.8)
        self.assertEqual(service.local_min_p, 0.1)
        self.assertEqual(service.local_repetition_penalty, 1.4)

    @unittest.skipIf(importlib.util.find_spec("torch") is None, "torch not installed")
    def test_local_wav_encoder_uses_stdlib_wav(self):
        import torch

        service = AudioService()
        encoded = service._encode_wav_bytes(torch.tensor([[0.0, 0.5, -1.0, 1.0]]), 24000)

        with wave.open(io.BytesIO(encoded), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), 24000)
            self.assertEqual(wav_file.getnframes(), 4)

    @unittest.skipIf(importlib.util.find_spec("chatterbox") is None, "chatterbox not installed")
    def test_local_status_suppresses_perth_pkg_resources_warning(self):
        service = AudioService()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            service.local_status()

        self.assertFalse(any("pkg_resources is deprecated as an API" in str(w.message) for w in caught))


if __name__ == "__main__":
    unittest.main()
