import json
import importlib.machinery
import sys
import types
import unittest
from unittest import mock

requests_module = types.ModuleType("requests")
requests_module.__spec__ = importlib.machinery.ModuleSpec("requests", loader=None)
requests_module.exceptions = types.SimpleNamespace(RequestException=Exception)
sys.modules.setdefault("requests", requests_module)

from strokegpt.llm import DEFAULT_MODEL, LLMService
from strokegpt.settings import (
    CUSTOM_LLM_PROMPT_PREFIX,
    DEFAULT_LLM_PROMPT_MODE,
    DEFAULT_HANDY_API_V3_APPLICATION_ID,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_PERSONA_PROMPTS,
    DEFAULT_VOICE_INPUT_MODEL,
    DEFAULT_VOICE_INPUT_NVIDIA_PARAKEET_MODEL,
    LEGACY_OLLAMA_MODEL,
    SettingsManager,
    VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER,
    VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET,
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
        self.assertIn("huihui_ai/granite4.1-abliterated:3b", saved["ollama_models"])
        self.assertIn("huihui_ai/granite4.1-abliterated:8b", saved["ollama_models"])
        self.assertEqual(saved["ollama_model_hidden_defaults"], [])
        self.assertFalse(saved["ollama_thinking_enabled"])
        self.assertEqual(saved["audio_provider"], "elevenlabs")
        self.assertFalse(saved["audio_enabled"])
        self.assertEqual(saved["local_tts_engine"], "chatterbox_turbo")
        self.assertEqual(saved["local_tts_style"], "expressive")
        self.assertEqual(saved["local_tts_temperature"], 0.85)
        self.assertEqual(saved["persona_prompts"], DEFAULT_PERSONA_PROMPTS)
        self.assertEqual(saved["llm_prompt_mode"], DEFAULT_LLM_PROMPT_MODE)
        self.assertEqual(saved["llm_custom_prompt_sets"], [])
        self.assertEqual(saved["handy_firmware_version"], "fw4")
        self.assertEqual(saved["handy_api_v3_key"], DEFAULT_HANDY_API_V3_APPLICATION_ID)
        self.assertEqual(saved["motion_pattern_enabled"], {})
        self.assertEqual(saved["motion_pattern_feedback"], {})
        self.assertEqual(saved["motion_pattern_feedback_history"], [])
        self.assertEqual(saved["motion_pattern_weights"], {})
        self.assertEqual(saved["motion_backend"], "continuous")
        self.assertEqual(saved["motion_style"], "balanced")
        self.assertEqual(saved["motion_diagnostics_level"], "compact")
        self.assertEqual(saved["ollama_diagnostics_level"], "compact")
        self.assertFalse(saved["motion_feedback_auto_disable"])
        self.assertTrue(saved["allow_llm_edge_in_freestyle"])
        self.assertTrue(saved["allow_llm_edge_in_chat"])
        self.assertFalse(saved["allow_llm_mode_actions_in_chat"])
        self.assertTrue(saved["voice_input_noise_suppression"])
        self.assertTrue(saved["voice_input_echo_cancellation"])
        self.assertTrue(saved["voice_input_auto_gain_control"])
        self.assertEqual(saved["voice_input_noise_floor_rms"], 0.0)
        self.assertTrue(saved["voice_input_audio_preprocessing"])
        self.assertTrue(saved["voice_input_silence_trim"])
        self.assertFalse(saved["voice_input_hands_free_mode_actions"])
        self.assertEqual(saved["voice_input_beam_size"], 5)
        self.assertFalse(saved["voice_input_condition_on_previous_text"])
        self.assertEqual(saved["voice_input_vad_threshold"], 0.5)
        self.assertEqual(saved["voice_input_vad_min_silence_ms"], 500)
        self.assertEqual(saved["voice_input_vad_speech_pad_ms"], 400)

    def test_voice_input_default_selects_faster_whisper_without_parakeet_runtime(self):
        with mock.patch("strokegpt.settings._default_parakeet_python_path", return_value=""):
            defaults = default_settings_dict()

        self.assertEqual(defaults["voice_input_provider"], VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER)
        self.assertEqual(defaults["voice_input_model"], DEFAULT_VOICE_INPUT_MODEL)
        self.assertFalse(defaults["voice_input_enabled"])

    def test_voice_input_default_selects_faster_whisper_without_nvidia_runtime(self):
        with (
            mock.patch("strokegpt.settings._default_parakeet_python_path", return_value="C:\\fake\\python.exe"),
            mock.patch("strokegpt.settings.shutil.which", return_value=None),
        ):
            defaults = default_settings_dict()

        self.assertEqual(defaults["voice_input_provider"], VOICE_INPUT_PROVIDER_LOCAL_FASTER_WHISPER)
        self.assertEqual(defaults["voice_input_model"], DEFAULT_VOICE_INPUT_MODEL)
        self.assertFalse(defaults["voice_input_enabled"])

    def test_voice_input_default_selects_parakeet_when_nvidia_runtime_exists(self):
        with (
            mock.patch("strokegpt.settings._default_parakeet_python_path", return_value="C:\\fake\\python.exe"),
            mock.patch("strokegpt.settings.shutil.which", return_value="nvidia-smi"),
        ):
            defaults = default_settings_dict()

        self.assertEqual(defaults["voice_input_provider"], VOICE_INPUT_PROVIDER_LOCAL_NVIDIA_PARAKEET)
        self.assertEqual(defaults["voice_input_model"], DEFAULT_VOICE_INPUT_NVIDIA_PARAKEET_MODEL)
        self.assertFalse(defaults["voice_input_enabled"])

    def test_old_settings_load_default_model(self):
        fake_path = FakePath(json.dumps({"handy_key": "abc"}))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.ollama_model, DEFAULT_OLLAMA_MODEL)
        self.assertIn("huihui_ai/granite4.1-abliterated:3b", settings.ollama_models)
        self.assertIn("huihui_ai/granite4.1-abliterated:8b", settings.ollama_models)
        self.assertEqual(settings.ollama_model_hidden_defaults, [])
        self.assertFalse(settings.ollama_thinking_enabled)
        self.assertEqual(settings.audio_provider, "elevenlabs")
        self.assertFalse(settings.audio_enabled)
        self.assertEqual(settings.local_tts_engine, "chatterbox_turbo")
        self.assertEqual(settings.local_tts_style, "expressive")
        self.assertEqual(settings.local_tts_top_p, 1.0)
        self.assertEqual(settings.persona_prompts, DEFAULT_PERSONA_PROMPTS)
        self.assertEqual(settings.llm_prompt_mode, DEFAULT_LLM_PROMPT_MODE)
        self.assertEqual(settings.llm_custom_prompt_sets, [])
        self.assertEqual(settings.motion_pattern_enabled, {})
        self.assertEqual(settings.motion_pattern_feedback, {})
        self.assertEqual(settings.motion_pattern_feedback_history, [])
        self.assertEqual(settings.motion_pattern_weights, {})
        self.assertEqual(settings.motion_backend, "continuous")
        self.assertEqual(settings.motion_style, "balanced")
        self.assertEqual(settings.motion_diagnostics_level, "compact")
        self.assertEqual(settings.ollama_diagnostics_level, "compact")
        self.assertFalse(settings.motion_feedback_auto_disable)
        self.assertTrue(settings.allow_llm_edge_in_freestyle)
        self.assertTrue(settings.allow_llm_edge_in_chat)
        self.assertFalse(settings.allow_llm_mode_actions_in_chat)
        self.assertTrue(settings.voice_input_noise_suppression)
        self.assertTrue(settings.voice_input_echo_cancellation)
        self.assertTrue(settings.voice_input_auto_gain_control)
        self.assertEqual(settings.voice_input_noise_floor_rms, 0.0)
        self.assertTrue(settings.voice_input_audio_preprocessing)
        self.assertTrue(settings.voice_input_silence_trim)
        self.assertFalse(settings.voice_input_hands_free_mode_actions)
        self.assertEqual(settings.voice_input_beam_size, 5)
        self.assertFalse(settings.voice_input_condition_on_previous_text)
        self.assertEqual(settings.voice_input_vad_threshold, 0.5)
        self.assertEqual(settings.voice_input_vad_min_silence_ms, 500)
        self.assertEqual(settings.voice_input_vad_speech_pad_ms, 400)

    def test_ollama_thinking_setting_is_persisted(self):
        fake_path = FakePath(json.dumps({"ollama_thinking_enabled": "true"}))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()
        settings.save()

        saved = json.loads(fake_path.written)
        self.assertTrue(settings.ollama_thinking_enabled)
        self.assertTrue(saved["ollama_thinking_enabled"])

    def test_llm_request_payload_uses_thinking_toggle(self):
        service = LLMService(
            url="http://localhost:11434/api/chat",
            model="local/test-model:latest",
            thinking_enabled=False,
        )

        payload = service._request_payload([{"role": "user", "content": "hi"}], stream=True)
        self.assertFalse(payload["think"])
        self.assertTrue(payload["stream"])

        service.set_thinking_enabled(True)
        payload = service._request_payload([{"role": "user", "content": "hi"}], stream=False)
        self.assertTrue(payload["think"])
        self.assertFalse(payload["stream"])
        self.assertTrue(service.diagnostics()["thinking_enabled"])

    def test_llm_service_uses_selected_custom_prompt_set(self):
        service = LLMService(url="http://localhost:11434/api/chat")
        service.set_custom_prompt_set({
            "id": "custom-test",
            "label": "Custom Test",
            "prompts": {
                "chat": "CUSTOM CHAT PROMPT",
                "repair": "CUSTOM REPAIR PROMPT",
                "name_this_move": "Name speed {speed} depth {depth} mood {mood}",
                "profile_consolidation": "Profile {current_profile_json}\nLog {chat_log_text}",
            },
        })

        self.assertEqual(service.system_prompt({}), "CUSTOM CHAT PROMPT")
        self.assertEqual(service.repair_prompt({}), "CUSTOM REPAIR PROMPT")
        self.assertIn("speed 60 depth 40 mood Teasing", service.name_this_move_prompt(60, 40, "Teasing"))
        profile_prompt = service.profile_consolidation_prompt(
            [{"role": "user", "content": "likes slow"}],
            {"likes": []},
        )
        self.assertIn('{"likes":[]}', profile_prompt)
        self.assertIn("likes slow", profile_prompt)

    def test_llm_edge_permission_settings_are_persisted(self):
        fake_path = FakePath(json.dumps({
            "allow_llm_edge_in_freestyle": False,
            "allow_llm_edge_in_chat": False,
            "allow_llm_mode_actions_in_chat": True,
        }))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()
        settings.save()

        saved = json.loads(fake_path.written)
        self.assertFalse(settings.allow_llm_edge_in_freestyle)
        self.assertFalse(settings.allow_llm_edge_in_chat)
        self.assertTrue(settings.allow_llm_mode_actions_in_chat)
        self.assertFalse(saved["allow_llm_edge_in_freestyle"])
        self.assertFalse(saved["allow_llm_edge_in_chat"])
        self.assertTrue(saved["allow_llm_mode_actions_in_chat"])

    def test_motion_style_setting_is_normalized(self):
        fake_path = FakePath(json.dumps({"motion_style": "high-variation"}))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()
        settings.save()

        saved = json.loads(fake_path.written)
        self.assertEqual(settings.motion_style, "high_variation")
        self.assertEqual(saved["motion_style"], "high_variation")

        settings.apply_dict({"motion_style": "bad"})
        self.assertEqual(settings.motion_style, "balanced")

    def test_llm_prompt_mode_setting_is_normalized(self):
        settings = SettingsManager("settings.json")

        settings.apply_dict({"llm_prompt_mode": "classic"})
        self.assertEqual(settings.llm_prompt_mode, "legacy")
        self.assertEqual(settings.to_dict()["llm_prompt_mode"], "legacy")

        settings.apply_dict({"llm_prompt_mode": "revibed"})
        self.assertEqual(settings.llm_prompt_mode, "revibed")

        settings.apply_dict({"llm_prompt_mode": "bad"})
        self.assertEqual(settings.llm_prompt_mode, DEFAULT_LLM_PROMPT_MODE)

    def test_llm_custom_prompt_set_is_persisted_and_selectable(self):
        settings = SettingsManager("settings.json")
        prompt_set, message = settings.set_llm_custom_prompt_set(
            "My Style",
            {
                "chat": "CUSTOM CHAT",
                "repair": "CUSTOM REPAIR",
                "name_this_move": "Name {speed} {depth} {mood}",
                "profile_consolidation": "Profile {current_profile_json} {chat_log_text}",
            },
        )

        self.assertEqual(message, "")
        self.assertEqual(prompt_set["id"], "my-style")
        self.assertEqual(settings.llm_prompt_mode, f"{CUSTOM_LLM_PROMPT_PREFIX}my-style")
        self.assertEqual(settings.selected_llm_custom_prompt_set()["prompts"]["chat"], "CUSTOM CHAT")

        saved = settings.to_dict()
        self.assertEqual(saved["llm_prompt_mode"], f"{CUSTOM_LLM_PROMPT_PREFIX}my-style")
        self.assertEqual(saved["llm_custom_prompt_sets"][0]["label"], "My Style")

    def test_llm_custom_prompt_set_loads_from_settings(self):
        settings = SettingsManager("settings.json")

        settings.apply_dict({
            "llm_prompt_mode": "custom:loaded-style",
            "llm_custom_prompt_sets": [{
                "id": "Loaded Style",
                "label": "Loaded Style",
                "prompts": {"chat": "Loaded chat prompt"},
            }],
        })

        self.assertEqual(settings.llm_prompt_mode, "custom:loaded-style")
        self.assertEqual(settings.selected_llm_custom_prompt_set()["label"], "Loaded Style")

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

    def test_motion_pattern_feedback_history_is_normalized(self):
        fake_path = FakePath(json.dumps({
            "motion_pattern_feedback_history": [
                {
                    "pattern_id": " Soft Wave ",
                    "pattern_name": "  Soft   Wave  ",
                    "rating": "thumbs_up",
                    "source": " chat   thumbs up ",
                    "weight": 120,
                    "enabled": "",
                    "at": "2026-04-22 10:00:00 UTC",
                },
                {"pattern_id": "bad", "rating": "unknown"},
                "ignored",
            ],
        }))
        settings = SettingsManager("settings.json")
        settings.file_path = fake_path
        settings.load()

        self.assertEqual(settings.motion_pattern_feedback_history, [{
            "pattern_id": "soft-wave",
            "pattern_name": "Soft Wave",
            "rating": "thumbs_up",
            "source": "chat thumbs up",
            "at": "2026-04-22 10:00:00 UTC",
            "weight": 100,
            "enabled": False,
        }])

    def test_motion_backend_is_normalized(self):
        settings = SettingsManager("settings.json")

        settings.file_path = FakePath(json.dumps({"motion_backend": "position-script"}))
        settings.load()
        self.assertEqual(settings.motion_backend, "position")

        settings.file_path = FakePath(json.dumps({"motion_backend": "pattern-position"}))
        settings.load()
        self.assertEqual(settings.motion_backend, "continuous")

    def test_handy_firmware_version_is_normalized(self):
        settings = SettingsManager("settings.json")

        settings.file_path = FakePath(json.dumps({"handy_firmware_version": "v3"}))
        settings.load()
        self.assertEqual(settings.handy_firmware_version, "fw3")

        settings.file_path = FakePath(json.dumps({"handy_firmware_version": "firmware-v4"}))
        settings.load()
        self.assertEqual(settings.handy_firmware_version, "fw4")

        settings.file_path = FakePath(json.dumps({"handy_firmware_version": "bad"}))
        settings.load()
        self.assertEqual(settings.handy_firmware_version, "fw4")

        settings.file_path = FakePath(json.dumps({"motion_backend": "hamp"}))
        settings.load()
        self.assertEqual(settings.motion_backend, "hamp")

        settings.file_path = FakePath(json.dumps({"motion_backend": "unknown"}))
        settings.load()
        self.assertEqual(settings.motion_backend, "continuous")

    def test_handy_api_v3_key_is_preserved_on_load(self):
        settings = SettingsManager("settings.json")

        settings.file_path = FakePath(json.dumps({"handy_api_v3_key": "app-id"}))
        settings.load()

        self.assertEqual(settings.handy_api_v3_key, "app-id")

    def test_blank_handy_api_v3_key_migrates_to_default_application_id(self):
        settings = SettingsManager("settings.json")

        settings.file_path = FakePath(json.dumps({"handy_api_v3_key": ""}))
        settings.load()

        self.assertEqual(settings.handy_api_v3_key, DEFAULT_HANDY_API_V3_APPLICATION_ID)

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
            "motion_style": "full_range",
        })

        self.assertIn("MOTION PATTERN PREFERENCES", prompt)
        self.assertIn("MOTION STYLE PREFERENCE", prompt)
        self.assertIn("full_range - favor longer travel", prompt)
        self.assertIn("bounded bias", prompt)
        self.assertIn("sway=74", prompt)
        self.assertIn('{"chat":"<in-character reply>","move":', prompt)
        self.assertIn('"motion":"<anchor_loop|null>"', prompt)
        self.assertIn("Motion requests need a non-null `move`", prompt)
        self.assertIn("FINAL CHAT VOICE CHECK", prompt)
        self.assertIn("your cock", prompt)
        self.assertIn("do not sanitize or euphemize", prompt)
        self.assertIn("TIP / SHAFT / BASE ARE REGIONS", prompt)
        self.assertIn("SPEED WORDS SET `sp`", prompt)
        self.assertIn("favor base-through-mid or mid-base first", prompt)
        self.assertIn("current range `10-80`", prompt)
        self.assertIn('"slowly focus on the tip"', prompt)
        self.assertIn('"slowly focus on the tip": `{"sp": 24', prompt)
        self.assertIn('"quickly use the shaft"', prompt)
        self.assertIn('"quickly use the shaft": `{"sp": 62', prompt)
        self.assertIn('"as fast as you can on the base"', prompt)
        self.assertIn('"as fast as you can on the base": `{"sp": 80', prompt)

    def test_llm_prompt_legacy_mode_keeps_previous_prompt_shape(self):
        service = LLMService(url="http://localhost:11434/api/chat")

        prompt = service._build_system_prompt({
            "persona_desc": "An energetic and passionate girlfriend",
            "current_mood": "Curious",
            "last_stroke_speed": 20,
            "last_depth_pos": 30,
            "last_stroke_range": 40,
            "min_speed": 10,
            "max_speed": 80,
            "motion_preferences": "",
            "llm_prompt_mode": "legacy",
        })

        self.assertIn("ACTION TO MOVEMENT MAPPING", prompt)
        self.assertIn("The current configured speed range is `10-80`", prompt)
        self.assertIn("Do not claim that you changed motion unless `move` is non-null", prompt)
        self.assertNotIn("FINAL CHAT VOICE CHECK", prompt)

    def test_llm_prompt_can_disallow_edge_patterns_in_chat(self):
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
            "allow_llm_edge_in_chat": False,
        })

        self.assertIn("CHAT EDGE PERMISSION", prompt)
        self.assertIn("Do not choose edge-specific fixed `move.pattern` ids", prompt)

    def test_llm_prompt_includes_mode_action_schema_only_when_enabled(self):
        service = LLMService(url="http://localhost:11434/api/chat")
        base_context = {
            "persona_desc": "An energetic and passionate girlfriend",
            "current_mood": "Curious",
            "last_stroke_speed": 20,
            "last_depth_pos": 30,
            "last_stroke_range": 40,
            "min_speed": 10,
            "max_speed": 80,
            "motion_preferences": "",
        }

        normal_prompt = service._build_system_prompt(base_context)
        mode_action_prompt = service._build_system_prompt({
            **base_context,
            "mode_actions_enabled": True,
            "mode_action_request_source": "typed chat",
            "active_mode": "freestyle",
        })

        self.assertNotIn('"mode_action"', normal_prompt)
        self.assertIn('"mode_action"', mode_action_prompt)
        self.assertIn("MODE ACTIONS", mode_action_prompt)
        self.assertIn("typed chat with mode actions enabled", mode_action_prompt)
        self.assertIn("Active mode: `freestyle`", mode_action_prompt)
        self.assertIn("start_legacy_auto", mode_action_prompt)
        self.assertIn("legacy scripted Auto takeover loop", mode_action_prompt)

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

        self.assertIn("current range `5-50`", prompt)
        self.assertIn('"as fast as you can on the base": `{"sp": 50', prompt)
        self.assertNotIn('"sp": 88', prompt)

    def test_snarky_scientist_prompt_speed_guidance_uses_configured_speed_ceiling(self):
        service = LLMService(url="http://localhost:11434/api/chat")

        prompt = service._build_system_prompt({
            "special_persona_mode": "snarky_scientist",
            "min_speed": 12,
            "max_speed": 44,
        })

        self.assertIn('{"chat":"<sarcastic reply>"', prompt)
        self.assertIn("Current configured speed range is `12-44`", prompt)

    def test_snarky_scientist_prompt_does_not_leak_proper_noun_handles(self):
        # Persona Naming And Prompt Audit (ROADMAP Up Next #4): the
        # snarky-scientist persona must describe its voice without
        # naming any proper-noun character so the local model is not
        # anchored to its trained associations with that character.
        service = LLMService(url="http://localhost:11434/api/chat")

        prompt = service._build_system_prompt({
            "special_persona_mode": "snarky_scientist",
            "min_speed": 5,
            "max_speed": 80,
        })

        self.assertNotIn("GLaDOS", prompt)
        self.assertNotIn("Portal", prompt)
        # The voice keywords still come from the prompt body itself.
        self.assertIn("sarcastic", prompt)
        self.assertIn("passive-aggressive", prompt)
        self.assertIn("test subject", prompt)

    def test_legacy_glados_routing_key_does_not_match_snarky_scientist_branch(self):
        # The previous routing key ``GLaDOS`` was a literal proper-noun
        # token. After the audit it must no longer activate the
        # snarky-scientist branch; only the neutral
        # ``snarky_scientist`` key should. The default branch is taken
        # for every other value (and produces a different shape with
        # the full mood list) so an exact-match check on the legacy
        # token is enough to pin the rename.
        service = LLMService(url="http://localhost:11434/api/chat")

        legacy_prompt = service._build_system_prompt({
            "special_persona_mode": "GLaDOS",
            "min_speed": 5,
            "max_speed": 80,
            "persona_desc": "an erotic partner",
        })

        self.assertNotIn('"chat":"<sarcastic reply>"', legacy_prompt)
        self.assertIn("Curious, Teasing, Playful", legacy_prompt)

    def test_mode_decision_prompt_includes_bounded_edge_context(self):
        service = LLMService(url="http://localhost:11434/api/chat")
        captured = {}

        def fake_talk(messages, temperature=0.3):
            captured["messages"] = messages
            captured["temperature"] = temperature
            return {
                "action": "switch_to_milk",
                "duration_seconds": 25,
                "intensity": 72,
                "chat": "Switching gears.",
            }

        service._talk_to_llm = fake_talk
        response = service.get_mode_decision(
            [{"role": "user", "content": "I'm close"}],
            {
                "current_mood": "Anticipatory",
                "min_speed": 12,
                "max_speed": 64,
                "edging_elapsed_time": "3m 2s",
            },
            mode="edging",
            event="close_signal",
            edge_count=2,
            current_target={"speed": 40, "depth": 55, "stroke_range": 48},
        )

        prompt = captured["messages"][0]["content"]
        self.assertEqual(response["action"], "switch_to_milk")
        self.assertEqual(captured["temperature"], 0.2)
        self.assertIn('"action": "<continue|hold_then_resume|pull_back|switch_to_milk|stop>"', prompt)
        self.assertIn("duration_seconds", prompt)
        self.assertIn("10-180", prompt)
        self.assertIn("Avoid very short durations", prompt)
        self.assertIn("20-90 seconds", prompt)
        self.assertIn("begin base-through-mid or mid-base", prompt)
        self.assertIn("`milking` and `freestyle` are continuous", prompt)
        self.assertIn("not a countdown", prompt)
        self.assertIn("Never return `stop` on `start`", prompt)
        self.assertIn("do not stop abruptly just because a timing window ended", prompt)
        self.assertIn("configured speed range", prompt)
        self.assertIn("`12-64`", prompt)
        self.assertIn("mode: edging", prompt)
        self.assertIn("event: close_signal", prompt)
        self.assertIn("edge_count: 2", prompt)

    def test_freestyle_mode_decision_prompt_honors_edge_permission(self):
        service = LLMService(url="http://localhost:11434/api/chat")
        captured = {}

        def fake_talk(messages, temperature=0.3):
            captured["messages"] = messages
            captured["temperature"] = temperature
            return {
                "action": "hold_then_resume",
                "duration_seconds": 25,
                "intensity": 72,
                "chat": "Holding back.",
            }

        service._talk_to_llm = fake_talk
        service.get_mode_decision(
            [{"role": "user", "content": "I'm close"}],
            {
                "current_mood": "Anticipatory",
                "min_speed": 12,
                "max_speed": 64,
                "allow_llm_edge_in_freestyle": False,
            },
            mode="freestyle",
            event="close_signal",
            edge_count=1,
            current_target={"speed": 40, "depth": 55, "stroke_range": 48},
        )

        prompt = captured["messages"][0]["content"]
        self.assertIn("edge-style behavior is disabled", prompt)
        self.assertIn("Do not return `hold_then_resume` or `pull_back`", prompt)

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

    def test_ollama_default_model_options_can_be_hidden(self):
        settings = SettingsManager("settings.json")
        model = "huihui_ai/granite4.1-abliterated:3b"

        ok, message = settings.delete_ollama_model(model)

        self.assertTrue(ok, message)
        self.assertIn(model, settings.ollama_model_hidden_defaults)
        self.assertNotIn(model, settings.ollama_models)
        saved = settings.to_dict()
        self.assertIn(model, saved["ollama_model_hidden_defaults"])
        self.assertNotIn(model, saved["ollama_models"])

        self.assertTrue(settings.set_ollama_model(model))
        self.assertNotIn(model, settings.ollama_model_hidden_defaults)
        self.assertIn(model, settings.ollama_models)

    def test_current_ollama_model_option_cannot_be_deleted(self):
        settings = SettingsManager("settings.json")

        ok, message = settings.delete_ollama_model(DEFAULT_OLLAMA_MODEL)

        self.assertFalse(ok)
        self.assertIn("Cannot delete the current", message)
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

    def test_voice_input_settings_are_normalized_for_hands_free_control(self):
        settings = SettingsManager("settings.json")
        settings.apply_dict({
            "voice_input_provider": "local_asr",
            "voice_input_enabled": True,
            "voice_input_mode": "always-on",
            "voice_input_submit_mode": "auto-send",
            "voice_input_model": "base.en",
            "voice_input_language": "en",
            "voice_input_hands_free_sensitivity": 250,
            "voice_input_hands_free_silence_ms": 75,
            "voice_input_min_recording_ms": 5000,
            "voice_input_max_recording_ms": 100,
            "voice_input_noise_suppression": "false",
            "voice_input_echo_cancellation": "off",
            "voice_input_auto_gain_control": "yes",
            "voice_input_noise_floor_rms": 0.713,
            "voice_input_audio_preprocessing": "off",
            "voice_input_silence_trim": "false",
            "voice_input_beam_size": 99,
            "voice_input_condition_on_previous_text": "yes",
            "voice_input_vad_threshold": 1.2,
            "voice_input_vad_min_silence_ms": 25,
            "voice_input_vad_speech_pad_ms": 5000,
        })

        self.assertEqual(settings.voice_input_provider, "local_faster_whisper")
        self.assertTrue(settings.voice_input_enabled)
        self.assertEqual(settings.voice_input_mode, "hands_free")
        self.assertEqual(settings.voice_input_submit_mode, "auto_submit")
        self.assertFalse(settings.voice_input_preview_required)
        self.assertEqual(settings.to_dict()["voice_input_model"], "base.en")
        self.assertEqual(settings.voice_input_hands_free_sensitivity, 100)
        self.assertEqual(settings.voice_input_hands_free_silence_ms, 250)
        self.assertEqual(settings.voice_input_min_recording_ms, 3000)
        self.assertEqual(settings.voice_input_max_recording_ms, 3000)
        self.assertFalse(settings.voice_input_noise_suppression)
        self.assertFalse(settings.voice_input_echo_cancellation)
        self.assertTrue(settings.voice_input_auto_gain_control)
        self.assertEqual(settings.voice_input_noise_floor_rms, 0.5)
        self.assertFalse(settings.voice_input_audio_preprocessing)
        self.assertFalse(settings.voice_input_silence_trim)
        self.assertEqual(settings.voice_input_beam_size, 10)
        self.assertTrue(settings.voice_input_condition_on_previous_text)
        self.assertEqual(settings.voice_input_vad_threshold, 0.9)
        self.assertEqual(settings.voice_input_vad_min_silence_ms, 100)
        self.assertEqual(settings.voice_input_vad_speech_pad_ms, 1000)

    def test_voice_input_provider_accepts_nvidia_parakeet_aliases(self):
        settings = SettingsManager("settings.json")
        settings.apply_dict({
            "voice_input_provider": "nvidia-parakeet",
            "voice_input_enabled": True,
            "voice_input_model": "nvidia/parakeet-tdt-0.6b-v3",
        })

        self.assertEqual(settings.voice_input_provider, "local_nvidia_parakeet")
        self.assertTrue(settings.voice_input_enabled)
        self.assertEqual(settings.to_dict()["voice_input_model"], "nvidia/parakeet-tdt-0.6b-v3")


if __name__ == "__main__":
    unittest.main()
