import json
import importlib.machinery
import sys
import types
import unittest

requests_module = types.ModuleType("requests")
requests_module.__spec__ = importlib.machinery.ModuleSpec("requests", loader=None)
requests_module.exceptions = types.SimpleNamespace(RequestException=Exception)
sys.modules.setdefault("requests", requests_module)

from strokegpt.llm import DEFAULT_MODEL, LLMService
from strokegpt.settings import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_PERSONA_PROMPTS,
    LEGACY_OLLAMA_MODEL,
    SettingsManager,
    default_settings_dict,
    normalize_ollama_model,
)


class FakePath:
    def __init__(self, text=None):
        self.text = text
        self.written = None

    def exists(self):
        return self.text is not None

    def read_text(self, *args, **kwargs):
        return self.text

    def write_text(self, text, *args, **kwargs):
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
        self.assertEqual(saved["local_tts_engine"], "chatterbox_turbo")
        self.assertEqual(saved["local_tts_style"], "expressive")
        self.assertEqual(saved["local_tts_temperature"], 0.85)
        self.assertEqual(saved["persona_prompts"], DEFAULT_PERSONA_PROMPTS)
        self.assertEqual(saved["motion_pattern_enabled"], {})
        self.assertEqual(saved["motion_pattern_feedback"], {})
        self.assertEqual(saved["motion_pattern_weights"], {})
        self.assertEqual(saved["motion_backend"], "hamp")
        self.assertEqual(saved["motion_diagnostics_level"], "compact")
        self.assertEqual(saved["ollama_diagnostics_level"], "compact")
        self.assertFalse(saved["motion_feedback_auto_disable"])

    def test_old_settings_load_default_model(self):
        fake_path = FakePath(json.dumps({"handy_key": "abc"}))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.ollama_model, DEFAULT_OLLAMA_MODEL)
        self.assertEqual(settings.audio_provider, "elevenlabs")
        self.assertFalse(settings.audio_enabled)
        self.assertEqual(settings.local_tts_engine, "chatterbox_turbo")
        self.assertEqual(settings.local_tts_style, "expressive")
        self.assertEqual(settings.local_tts_top_p, 1.0)
        self.assertEqual(settings.persona_prompts, DEFAULT_PERSONA_PROMPTS)
        self.assertEqual(settings.motion_pattern_enabled, {})
        self.assertEqual(settings.motion_pattern_feedback, {})
        self.assertEqual(settings.motion_pattern_weights, {})
        self.assertEqual(settings.motion_backend, "hamp")
        self.assertEqual(settings.motion_diagnostics_level, "compact")
        self.assertEqual(settings.ollama_diagnostics_level, "compact")
        self.assertFalse(settings.motion_feedback_auto_disable)

    def test_motion_pattern_enabled_map_is_normalized(self):
        fake_path = FakePath(json.dumps({
            "motion_pattern_enabled": {
                " Soft Wave ": True,
                "bad id!!": False,
                "": True,
            },
        }))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.motion_pattern_enabled, {
            "soft-wave": True,
            "bad-id": False,
        })

    def test_motion_pattern_feedback_map_is_normalized(self):
        fake_path = FakePath(json.dumps({
            "motion_pattern_feedback": {
                " Soft Wave ": {"thumbs_up": "3", "neutral": "bad", "thumbs_down": -1},
                "ignored": "not a map",
            },
        }))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.motion_pattern_feedback, {
            "soft-wave": {"thumbs_up": 3, "neutral": 0, "thumbs_down": 0},
        })

    def test_motion_pattern_weight_map_is_normalized(self):
        fake_path = FakePath(json.dumps({
            "motion_pattern_weights": {
                " Soft Wave ": "74",
                "too high": 180,
                "too low": -20,
                "": 50,
            },
        }))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.motion_pattern_weights, {
            "soft-wave": 74,
            "too-high": 100,
            "too-low": 0,
        })

    def test_motion_backend_is_normalized(self):
        settings = SettingsManager("settings.json")

        settings.file_path = FakePath(json.dumps({"motion_backend": "position-script"}))
        settings.load()
        self.assertEqual(settings.motion_backend, "position")

        settings.file_path = FakePath(json.dumps({"motion_backend": "unknown"}))
        settings.load()
        self.assertEqual(settings.motion_backend, "hamp")

    def test_diagnostics_levels_are_normalized(self):
        fake_path = FakePath(json.dumps({
            "motion_diagnostics_level": "verbose",
            "ollama_diagnostics_level": "debug",
        }))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.motion_diagnostics_level, "status")
        self.assertEqual(settings.ollama_diagnostics_level, "debug")

        settings.file_path = FakePath(json.dumps({
            "motion_diagnostics_level": "bad",
            "ollama_diagnostics_level": "off",
        }))
        settings.load()

        self.assertEqual(settings.motion_diagnostics_level, "compact")
        self.assertEqual(settings.ollama_diagnostics_level, "compact")

    def test_llm_prompt_includes_motion_pattern_preferences(self):
        service = LLMService(url="http://localhost:11434/api/chat")

        prompt = service._build_system_prompt({
            "persona_desc": "An energetic and passionate girlfriend",
            "current_mood": "Curious",
            "last_stroke_speed": 20,
            "last_depth_pos": 30,
            "last_stroke_range": 40,
            "min_speed": 10,
            "max_speed": 80,
            "motion_preferences": "Available fixed move.pattern weights from 0-100.\nsway=74",
        })

        self.assertIn("MOTION PATTERN PREFERENCES", prompt)
        self.assertIn("sway=74", prompt)
        self.assertIn("Do not claim that you changed motion unless `move` is non-null", prompt)
        self.assertIn("TIP / SHAFT / BASE ARE REGIONS", prompt)
        self.assertIn("TRANSLATE SPEED WORDS INTO `sp`", prompt)
        self.assertIn("The current configured speed range is `10-80`", prompt)
        self.assertIn('"slowly focus on the tip"', prompt)
        self.assertIn('"slowly focus on the tip"**: `{"sp": 24', prompt)
        self.assertIn('"quickly use the shaft"', prompt)
        self.assertIn('"quickly use the shaft"**: `{"sp": 62', prompt)
        self.assertIn('"as fast as you can on the base"', prompt)
        self.assertIn('"as fast as you can on the base"**: `{"sp": 80', prompt)

    def test_llm_prompt_speed_guidance_uses_configured_speed_ceiling(self):
        service = LLMService(url="http://localhost:11434/api/chat")

        prompt = service._build_system_prompt({
            "persona_desc": "An energetic and passionate girlfriend",
            "current_mood": "Curious",
            "last_stroke_speed": 20,
            "last_depth_pos": 30,
            "last_stroke_range": 40,
            "min_speed": 5,
            "max_speed": 50,
            "motion_preferences": "",
        })

        self.assertIn("The current configured speed range is `5-50`", prompt)
        self.assertIn('"as fast as you can on the base"**: `{"sp": 50', prompt)
        self.assertNotIn('"sp": 88', prompt)

    def test_glados_prompt_speed_guidance_uses_configured_speed_ceiling(self):
        service = LLMService(url="http://localhost:11434/api/chat")

        prompt = service._build_system_prompt({
            "special_persona_mode": "GLaDOS",
            "min_speed": 12,
            "max_speed": 44,
        })

        self.assertIn('{"chat": "<Your sarcastic reply>"', prompt)
        self.assertIn("Current configured speed range is `12-44`", prompt)

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

    def test_persona_prompts_are_normalized_and_saved_for_later(self):
        settings = SettingsManager("settings.json")

        self.assertTrue(settings.set_persona_prompt("  An energetic and passionate partner  "))
        self.assertTrue(settings.set_persona_prompt("An energetic   and passionate partner"))

        self.assertEqual(settings.persona_desc, "An energetic and passionate partner")
        self.assertEqual(settings.persona_prompts.count("An energetic and passionate partner"), 1)
        for prompt in DEFAULT_PERSONA_PROMPTS:
            self.assertIn(prompt, settings.persona_prompts)

    def test_blank_saved_persona_falls_back_to_default(self):
        fake_path = FakePath(json.dumps({"persona_desc": ""}))

        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.persona_desc, DEFAULT_PERSONA_PROMPTS[0])

    def test_reset_to_defaults_rebuilds_portable_settings_payload(self):
        settings = SettingsManager("settings.json")
        settings.handy_key = "secret"
        settings.ai_name = "Custom"
        settings.set_persona_prompt("An energetic and passionate teammate")
        settings.min_speed = 40

        settings.reset_to_defaults(save=False)

        self.assertEqual(settings.to_dict(), default_settings_dict())


if __name__ == "__main__":
    unittest.main()
