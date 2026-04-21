import json
import sys
import types
import unittest

sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(exceptions=types.SimpleNamespace(RequestException=Exception)),
)

from strokegpt.llm import DEFAULT_MODEL, LLMService
from strokegpt.settings import DEFAULT_OLLAMA_MODEL, LEGACY_OLLAMA_MODEL, SettingsManager, normalize_ollama_model


class FakePath:
    def __init__(self, text=None):
        self.text = text
        self.written = None

    def exists(self):
        return self.text is not None

    def read_text(self):
        return self.text

    def write_text(self, text):
        self.written = text


class ModelConfigurationTests(unittest.TestCase):
    def test_llm_service_defaults_to_gemma_model(self):
        service = LLMService(url="http://localhost:11434/api/chat")
        self.assertEqual(service.model, DEFAULT_MODEL)
        self.assertEqual(service.model, "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b")

    def test_settings_default_model_is_persisted(self):
        fake_path = FakePath()
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.save()

        saved = json.loads(fake_path.written)
        self.assertEqual(saved["ollama_model"], DEFAULT_OLLAMA_MODEL)
        self.assertIn(DEFAULT_OLLAMA_MODEL, saved["ollama_models"])
        self.assertEqual(saved["audio_provider"], "elevenlabs")
        self.assertFalse(saved["audio_enabled"])
        self.assertEqual(saved["local_tts_style"], "expressive")
        self.assertEqual(saved["local_tts_temperature"], 0.85)

    def test_old_settings_load_default_model(self):
        fake_path = FakePath(json.dumps({"handy_key": "abc"}))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.ollama_model, DEFAULT_OLLAMA_MODEL)
        self.assertEqual(settings.audio_provider, "elevenlabs")
        self.assertFalse(settings.audio_enabled)
        self.assertEqual(settings.local_tts_style, "expressive")
        self.assertEqual(settings.local_tts_top_p, 1.0)

    def test_legacy_model_migrates_to_new_default(self):
        fake_path = FakePath(json.dumps({"ollama_model": LEGACY_OLLAMA_MODEL}))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.ollama_model, DEFAULT_OLLAMA_MODEL)
        self.assertIn(LEGACY_OLLAMA_MODEL, settings.ollama_models)

    def test_model_names_are_normalized_and_saved_for_later(self):
        settings = SettingsManager("settings.json")
        self.assertTrue(settings.set_ollama_model("nexusriot / Gemma-4-Uncensored-HauhauCS-Aggressive : e4b"))

        self.assertEqual(settings.ollama_model, DEFAULT_OLLAMA_MODEL)
        self.assertEqual(
            normalize_ollama_model("nexusriot / Gemma-4-Uncensored-HauhauCS-Aggressive : e4b"),
            DEFAULT_OLLAMA_MODEL,
        )
        self.assertIn(DEFAULT_OLLAMA_MODEL, settings.ollama_models)


if __name__ == "__main__":
    unittest.main()
