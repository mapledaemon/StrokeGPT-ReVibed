import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._web_support import WebTestCase


class WebSettingsRouteTests(WebTestCase):
    def test_persona_prompt_can_be_selected_and_saved(self):
        from strokegpt.web import settings

        original_persona = settings.persona_desc
        original_prompts = list(settings.persona_prompts)
        try:
            response = self.client.post("/set_persona_prompt", json={
                "persona_desc": "  An energetic and passionate teammate  ",
                "save_prompt": True,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["persona"], "An energetic and passionate teammate")
            self.assertIn("An energetic and passionate teammate", data["persona_prompts"])
            self.assertEqual(settings.persona_desc, "An energetic and passionate teammate")
            self.assertIn("An energetic and passionate teammate", settings.persona_prompts)
        finally:
            settings.persona_desc = original_persona
            settings.persona_prompts = original_prompts
            settings.save()

    def test_reset_settings_requires_confirmation(self):
        response = self.client.post("/reset_settings", json={})
        try:
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["status"], "error")
        finally:
            response.close()

    def test_llm_prompt_mode_can_be_selected_and_saved(self):
        from strokegpt.web import llm, settings

        original_mode = settings.llm_prompt_mode
        original_prompt_sets = list(getattr(settings, "llm_custom_prompt_sets", []))
        try:
            with mock.patch.object(settings, "save") as save:
                response = self.client.post("/set_llm_prompt_mode", json={
                    "llm_prompt_mode": "classic",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["llm_prompt_mode"], "legacy")
            self.assertTrue(any(option["id"] == "revibed" for option in data["llm_prompt_mode_options"]))
            self.assertEqual(settings.llm_prompt_mode, "legacy")
            self.assertIsNone(llm.custom_prompt_set)
            save.assert_called_once()
        finally:
            settings.llm_prompt_mode = original_mode
            settings.llm_custom_prompt_sets = original_prompt_sets
            llm.set_custom_prompt_set(settings.selected_llm_custom_prompt_set())

    def test_user_genitalia_can_be_selected_and_reported_in_prompts(self):
        from strokegpt.web import get_current_context, settings

        original = (settings.user_genitalia, settings.user_genitalia_custom)
        try:
            with mock.patch.object(settings, "save") as save:
                response = self.client.post("/set_user_genitalia", json={
                    "user_genitalia": "vulva",
                    "user_genitalia_custom": "  ignored unless custom  ",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["user_genitalia"], "vagina")
            self.assertEqual(data["user_genitalia_custom"], "ignored unless custom")
            self.assertTrue(any(option["id"] == "custom" for option in data["user_genitalia_options"]))
            self.assertEqual(settings.user_genitalia, "vagina")
            self.assertEqual(get_current_context()["user_genitalia"], "vagina")
            save.assert_called_once()

            response = self.client.get("/check_settings")
            payload = response.get_json()
            self.assertEqual(payload["user_genitalia"], "vagina")
            self.assertTrue(any(option["id"] == "penis" for option in payload["user_genitalia_options"]))

            response = self.client.get("/system_prompts")
            prompts = response.get_json()
            self.assertEqual(prompts["user_genitalia"], "vagina")
            self.assertIn("The device is being used on my vagina/vulva", prompts["chat"])
            self.assertIn("The device is being used on my vagina/vulva", prompts["repair"])
        finally:
            settings.user_genitalia, settings.user_genitalia_custom = original

    def test_custom_llm_prompt_set_can_be_saved_and_selected(self):
        from strokegpt.web import llm, settings

        original_mode = settings.llm_prompt_mode
        original_prompt_sets = list(getattr(settings, "llm_custom_prompt_sets", []))
        try:
            with mock.patch.object(settings, "save") as save:
                response = self.client.post("/save_llm_prompt_set", json={
                    "name": "My Custom",
                    "prompts": {
                        "chat": "CUSTOM CHAT",
                        "repair": "CUSTOM REPAIR",
                        "name_this_move": "Name {speed} {depth} {mood}",
                        "profile_consolidation": "Profile {current_profile_json} {chat_log_text}",
                    },
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["llm_prompt_mode"], "custom:my-custom")
            self.assertTrue(any(option["id"] == "custom:my-custom" for option in data["llm_prompt_mode_options"]))
            self.assertEqual(llm.system_prompt({}), "CUSTOM CHAT")
            save.assert_called_once()
        finally:
            settings.llm_prompt_mode = original_mode
            settings.llm_custom_prompt_sets = original_prompt_sets
            llm.set_custom_prompt_set(settings.selected_llm_custom_prompt_set())

    def test_json_routes_handle_missing_or_invalid_payloads_without_500(self):
        invalid_posts = [
            "/set_handy_key",
            "/set_profile_picture",
            "/setup_elevenlabs",
        ]

        for path in invalid_posts:
            with self.subTest(path=path):
                response = self.client.post(path, data="not json", content_type="text/plain")
                try:
                    self.assertLess(response.status_code, 500)
                finally:
                    response.close()

    def test_set_handy_key_saves_and_checks_connection(self):
        from strokegpt.web import handy, settings

        original_key = settings.handy_key
        original_runtime_key = handy.handy_key
        connection_payload = {
            "status": "connected",
            "connected": True,
            "message": "Connected to Handy.",
            "last_command": {"path": "slide/position/absolute", "ok": True, "status_code": 200},
        }
        try:
            with mock.patch.object(settings, "save") as save, \
                    mock.patch.object(handy, "check_connection", return_value=connection_payload) as check:
                response = self.client.post("/set_handy_key", json={"key": "probe-key"})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["connected"])
            self.assertEqual(data["connection_status"], "connected")
            self.assertEqual(data["message"], "Connected to Handy.")
            self.assertEqual(data["connection"], connection_payload)
            self.assertEqual(settings.handy_key, "probe-key")
            self.assertEqual(handy.handy_key, "probe-key")
            save.assert_called_once()
            check.assert_called_once()
        finally:
            settings.handy_key = original_key
            handy.set_api_key(original_runtime_key)

    def test_set_handy_device_config_saves_firmware_and_v3_key(self):
        from strokegpt.web import handy, settings

        original = settings.to_dict()
        original_runtime = {
            "handy_key": handy.handy_key,
            "firmware": handy.firmware_version,
            "api_v3_key": handy.api_v3_key,
        }
        try:
            settings.handy_key = "saved-key"
            handy.set_api_key("saved-key")
            settings.handy_api_v3_key = ""
            handy.set_handy_api_key("")
            with mock.patch.object(settings, "save") as save:
                response = self.client.post("/set_handy_device_config", json={
                    "handy_firmware_version": "v4",
                    "handy_api_v3_key": "app-id",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["handy_firmware_version"], "fw4")
            self.assertTrue(data["handy_api_v3_enabled"])
            self.assertTrue(data["handy_api_v3_key_configured"])
            self.assertEqual(data["handy_api_v3_key"], "app-id")
            self.assertEqual(settings.handy_firmware_version, "fw4")
            self.assertEqual(settings.handy_api_v3_key, "app-id")
            self.assertEqual(handy.firmware_version, "fw4")
            self.assertEqual(handy.api_v3_key, "app-id")
            self.assertTrue(handy.supports_continuous_streaming())
            save.assert_called_once()

            response = self.client.post("/set_handy_device_config", json={
                "handy_firmware_version": "v3",
                "handy_api_v3_key": "legacy-still-saved",
            })
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["handy_firmware_version"], "fw3")
            self.assertFalse(data["continuous_streaming_supported"])
            self.assertEqual(settings.handy_api_v3_key, "legacy-still-saved")
        finally:
            settings.apply_dict(original)
            handy.set_api_key(original_runtime["handy_key"])
            handy.set_firmware_version(original_runtime["firmware"])
            handy.set_handy_api_key(original_runtime["api_v3_key"])

    def test_numeric_routes_fall_back_on_invalid_values(self):
        from strokegpt.web import handy, settings

        original = (
            settings.min_speed,
            settings.max_speed,
            handy.min_user_speed,
            handy.max_user_speed,
        )
        try:
            response = self.client.post("/set_speed_limits", json={
                "min_speed": "bad",
                "max_speed": None,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["min_speed"], 10)
            self.assertEqual(data["max_speed"], 80)
        finally:
            (
                settings.min_speed,
                settings.max_speed,
                handy.min_user_speed,
                handy.max_user_speed,
            ) = original
            handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
            settings.save()

    def test_reset_settings_restores_defaults_and_runtime_services(self):
        from strokegpt.settings import DEFAULT_OLLAMA_MODEL, DEFAULT_PERSONA_PROMPT
        from strokegpt.web import apply_settings_to_services, audio, handy, llm, settings

        original = settings.to_dict()
        original_send_command = handy._send_command
        original_send_v3_command = handy._send_v3_command
        sent_commands = []
        sent_v3_commands = []
        try:
            handy._send_command = lambda path, body=None: sent_commands.append((path, body or {})) or True
            handy._send_v3_command = lambda path, body=None: sent_v3_commands.append((path, body or {})) or True
            settings.handy_key = "test-key"
            settings.ai_name = "Custom"
            settings.set_persona_prompt("An energetic and passionate teammate")
            settings.min_speed = 40
            settings.max_speed = 50
            settings.audio_provider = "local"
            settings.audio_enabled = True
            apply_settings_to_services()

            response = self.client.post("/reset_settings", json={"confirm": "RESET"})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn(("hamp/stop", {}), sent_commands + sent_v3_commands)
            self.assertFalse(data["configured"])
            self.assertEqual(settings.handy_key, "")
            self.assertEqual(handy.handy_key, "")
            self.assertEqual(settings.ai_name, "BOT")
            self.assertEqual(settings.persona_desc, DEFAULT_PERSONA_PROMPT)
            self.assertEqual(settings.min_speed, 10)
            self.assertEqual(settings.max_speed, 80)
            self.assertEqual(handy.min_user_speed, 10)
            self.assertEqual(handy.max_user_speed, 80)
            self.assertEqual(llm.model, DEFAULT_OLLAMA_MODEL)
            self.assertEqual(audio.provider, "elevenlabs")
            self.assertFalse(audio.is_on)
        finally:
            handy._send_command = original_send_command
            handy._send_v3_command = original_send_v3_command
            settings.apply_dict(original)
            settings.save()
            apply_settings_to_services()

    def test_mode_timings_are_saved_sorted_and_clamped(self):
        from strokegpt.web import settings

        original = (
            settings.auto_min_time,
            settings.auto_max_time,
            settings.edging_min_time,
            settings.edging_max_time,
            settings.milking_min_time,
            settings.milking_max_time,
        )
        try:
            response = self.client.post("/set_mode_timings", json={
                "auto_min": 20,
                "auto_max": 10,
                "edging_min": 0,
                "edging_max": 99,
                "milking_min": 3,
                "milking_max": 4,
            })
            self.assertEqual(response.status_code, 200)
            timings = response.get_json()["timings"]
            self.assertEqual(timings["auto_min"], 10)
            self.assertEqual(timings["auto_max"], 20)
            self.assertEqual(timings["edging_min"], 1.0)
            self.assertEqual(timings["edging_max"], 60.0)
            self.assertEqual(timings["milking_min"], 3.0)
            self.assertEqual(timings["milking_max"], 4.0)
        finally:
            (
                settings.auto_min_time,
                settings.auto_max_time,
                settings.edging_min_time,
                settings.edging_max_time,
                settings.milking_min_time,
                settings.milking_max_time,
            ) = original
            settings.save()

    def test_speed_limits_are_saved_sorted_and_clamped(self):
        from strokegpt.web import handy, settings

        original = (
            settings.min_speed,
            settings.max_speed,
            handy.min_user_speed,
            handy.max_user_speed,
        )
        try:
            response = self.client.post("/set_speed_limits", json={
                "min_speed": 120,
                "max_speed": -5,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["min_speed"], 0)
            self.assertEqual(data["max_speed"], 100)
            self.assertEqual(settings.min_speed, 0)
            self.assertEqual(settings.max_speed, 100)
            self.assertEqual(handy.min_user_speed, 0)
            self.assertEqual(handy.max_user_speed, 100)
        finally:
            (
                settings.min_speed,
                settings.max_speed,
                handy.min_user_speed,
                handy.max_user_speed,
            ) = original
            handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
            settings.save()

    def test_speed_limits_refresh_active_motion_with_previous_range(self):
        from strokegpt.web import handy, motion, settings

        original = (
            settings.min_speed,
            settings.max_speed,
            handy.min_user_speed,
            handy.max_user_speed,
        )
        original_refresh = motion.refresh_speed_limits
        calls = []
        try:
            settings.min_speed = 10
            settings.max_speed = 80
            handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)

            def refresh(previous_min, previous_max, next_min, next_max, **kwargs):
                calls.append((previous_min, previous_max, next_min, next_max, kwargs))
                return True

            motion.refresh_speed_limits = refresh

            response = self.client.post("/set_speed_limits", json={
                "min_speed": 20,
                "max_speed": 100,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data["motion_refreshed"])
            self.assertEqual(calls, [(10, 80, 20, 100, {})])
        finally:
            motion.refresh_speed_limits = original_refresh
            (
                settings.min_speed,
                settings.max_speed,
                handy.min_user_speed,
                handy.max_user_speed,
            ) = original
            handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
            settings.save()

    def test_motion_backend_can_be_selected_and_saved(self):
        from strokegpt.web import motion, settings

        original_setting = settings.motion_backend
        original_controller = motion.backend
        try:
            with mock.patch.object(settings, "save"):
                response = self.client.post("/set_motion_backend", json={"motion_backend": "position"})
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data["motion_backend"], "position")
                self.assertEqual(settings.motion_backend, "position")
                self.assertEqual(motion.backend, "position")

                response = self.client.get("/check_settings")
                payload = response.get_json()
                self.assertEqual(payload["motion_backend"], "position")
                self.assertTrue(any(item["experimental"] for item in payload["motion_backends"] if item["id"] == "position"))
                self.assertTrue(any(item.get("deprecated") for item in payload["motion_backends"] if item["id"] == "hamp"))

                response = self.client.post("/set_motion_backend", json={"motion_backend": "bad"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["motion_backend"], "continuous")
                self.assertEqual(motion.backend, "continuous")
        finally:
            settings.motion_backend = original_setting
            motion.set_backend(original_controller)

    def test_motion_style_can_be_selected_and_reported(self):
        from strokegpt.web import get_current_context, settings

        original_style = settings.motion_style
        try:
            with mock.patch.object(settings, "save"):
                response = self.client.post("/set_motion_style", json={"motion_style": "full-range"})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["motion_style"], "full_range")
            self.assertTrue(any(item["id"] == "full_range" for item in data["motion_style_options"]))
            self.assertEqual(settings.motion_style, "full_range")
            self.assertEqual(get_current_context()["motion_style"], "full_range")

            response = self.client.get("/check_settings")
            payload = response.get_json()
            self.assertEqual(payload["motion_style"], "full_range")
            self.assertTrue(any(item["id"] == "teasing" for item in payload["motion_style_options"]))
        finally:
            settings.motion_style = original_style

    def test_motion_reverse_direction_can_be_selected_and_reported(self):
        from strokegpt.web import get_current_context, motion, settings

        original_setting = settings.motion_reverse_direction
        original_controller = motion.reverse_direction
        try:
            with mock.patch.object(settings, "save"):
                response = self.client.post("/set_motion_reverse_direction", json={"motion_reverse_direction": True})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["motion_reverse_direction"])
            self.assertTrue(settings.motion_reverse_direction)
            self.assertTrue(motion.reverse_direction)
            self.assertTrue(get_current_context()["motion_reverse_direction"])

            response = self.client.get("/check_settings")
            payload = response.get_json()
            self.assertTrue(payload["motion_reverse_direction"])
        finally:
            settings.motion_reverse_direction = original_setting
            motion.set_reverse_direction(original_controller)

    def test_loaded_motion_direction_is_applied_on_startup(self):
        repo_root = Path(__file__).resolve().parents[1]
        startup_script = (
            "import strokegpt.web as web\n"
            "assert web.settings.motion_reverse_direction is True\n"
            "assert web.motion.reverse_direction is True, web.motion.reverse_direction\n"
            "assert web.settings.motion_backend == 'position'\n"
            "assert web.motion.backend == 'position', web.motion.backend\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "my_settings.json"
            settings_path.write_text(
                json.dumps({
                    "motion_reverse_direction": True,
                    "motion_backend": "position",
                }),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
            result = subprocess.run(
                [sys.executable, "-c", startup_script],
                cwd=temp_dir,
                env=env,
                text=True,
                capture_output=True,
                timeout=20,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_settings_uses_fast_startup_payload(self):
        with mock.patch("strokegpt.web._ollama_installed_models", side_effect=AssertionError("live Ollama probe")), \
                mock.patch("strokegpt.web._ollama_running_models", side_effect=AssertionError("live Ollama probe")), \
                mock.patch("strokegpt.web.audio._local_runtime_info", side_effect=AssertionError("live Chatterbox probe")):
            response = self.client.get("/check_settings")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ollama_status"]["unchecked"])
        self.assertIsNone(data["ollama_status"]["available"])
        self.assertEqual(data["local_tts_status"]["status"], "unchecked")
        self.assertTrue(data["local_tts_status"]["torch"]["unchecked"])
        self.assertIn("ollama_thinking_enabled", data)
        self.assertIn("thinking_enabled", data["ollama_status"])
        self.assertNotIn("motion_preferences", data)
        self.assertIn("motion_patterns", data)
        self.assertIn("motion_pattern_library_enabled_in_freestyle", data)
        self.assertIn("motion_pattern_library_enabled_in_chat", data)

    def test_llm_edge_permissions_can_be_selected_and_saved(self):
        from strokegpt.web import app_state, settings

        original = (
            settings.allow_llm_edge_in_freestyle,
            settings.allow_llm_edge_in_chat,
            settings.autospeak_enabled,
            settings.autospeak_min_seconds,
            settings.autospeak_max_seconds,
            settings.autospeak_motion_autonomy,
            app_state.autospeak_wake_requested,
        )
        try:
            settings.autospeak_enabled = False
            app_state.autospeak_wake_requested = False
            app_state.mode_message_event.clear()
            with mock.patch.object(settings, "save"), \
                    mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=True) as schedule_autospeak:
                response = self.client.post("/set_llm_edge_permissions", json={
                    "allow_llm_edge_in_freestyle": False,
                    "allow_llm_edge_in_chat": False,
                    "autospeak_enabled": True,
                    "autospeak_min_seconds": 8,
                    "autospeak_max_seconds": 2,
                    "autospeak_motion_autonomy": "full-motion",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertFalse(data["allow_llm_edge_in_freestyle"])
            self.assertFalse(data["allow_llm_edge_in_chat"])
            self.assertTrue(data["autospeak_enabled"])
            self.assertEqual(data["autospeak_min_seconds"], 2.0)
            self.assertEqual(data["autospeak_max_seconds"], 8.0)
            self.assertEqual(data["autospeak_motion_autonomy"], "full")
            self.assertTrue(any(item["id"] == "style" for item in data["autospeak_motion_autonomy_options"]))
            self.assertFalse(settings.allow_llm_edge_in_freestyle)
            self.assertFalse(settings.allow_llm_edge_in_chat)
            self.assertTrue(settings.autospeak_enabled)
            self.assertEqual(settings.autospeak_min_seconds, 2.0)
            self.assertEqual(settings.autospeak_max_seconds, 8.0)
            self.assertEqual(settings.autospeak_motion_autonomy, "full")
            self.assertIn("motion_preferences", data)
            schedule_autospeak.assert_called_once_with(0)
            self.assertFalse(app_state.autospeak_wake_requested)
            self.assertFalse(app_state.mode_message_event.is_set())

            response = self.client.get("/check_settings")
            payload = response.get_json()
            self.assertFalse(payload["allow_llm_edge_in_freestyle"])
            self.assertFalse(payload["allow_llm_edge_in_chat"])
            self.assertTrue(payload["autospeak_enabled"])
            self.assertEqual(payload["autospeak_min_seconds"], 2.0)
            self.assertEqual(payload["autospeak_max_seconds"], 8.0)
            self.assertEqual(payload["autospeak_motion_autonomy"], "full")
        finally:
            (
                settings.allow_llm_edge_in_freestyle,
                settings.allow_llm_edge_in_chat,
                settings.autospeak_enabled,
                settings.autospeak_min_seconds,
                settings.autospeak_max_seconds,
                settings.autospeak_motion_autonomy,
                app_state.autospeak_wake_requested,
            ) = original
            app_state.mode_message_event.clear()

    def test_diagnostics_levels_can_be_selected_and_saved(self):
        from strokegpt.web import settings

        original_motion_level = settings.motion_diagnostics_level
        original_ollama_level = settings.ollama_diagnostics_level
        try:
            with mock.patch.object(settings, "save"), \
                    mock.patch("strokegpt.payloads.ollama_status_payload", return_value={"diagnostics_level": "debug"}):
                response = self.client.post("/set_diagnostics_levels", json={
                    "motion_diagnostics_level": "verbose",
                    "ollama_diagnostics_level": "debug",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["motion_diagnostics_level"], "status")
            self.assertEqual(data["ollama_diagnostics_level"], "debug")
            self.assertEqual(settings.motion_diagnostics_level, "status")
            self.assertEqual(settings.ollama_diagnostics_level, "debug")
            self.assertIn("diagnostics_levels", data)
        finally:
            settings.motion_diagnostics_level = original_motion_level
            settings.ollama_diagnostics_level = original_ollama_level

    def test_motion_feedback_auto_disable_option_can_be_saved(self):
        from strokegpt.web import settings

        original = (
            settings.motion_feedback_auto_disable,
            settings.motion_pattern_library_enabled_in_freestyle,
            settings.motion_pattern_library_enabled_in_chat,
        )
        try:
            with mock.patch.object(settings, "save"):
                response = self.client.post("/motion_feedback_options", json={
                    "auto_disable": True,
                    "motion_pattern_library_enabled_in_freestyle": True,
                    "motion_pattern_library_enabled_in_chat": True,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["motion_feedback_auto_disable"])
            self.assertTrue(data["motion_pattern_library_enabled_in_freestyle"])
            self.assertTrue(data["motion_pattern_library_enabled_in_chat"])
            self.assertTrue(settings.motion_feedback_auto_disable)
            self.assertTrue(settings.motion_pattern_library_enabled_in_freestyle)
            self.assertTrue(settings.motion_pattern_library_enabled_in_chat)
            self.assertIn("motion_patterns", data)
            self.assertIn("motion_preferences", data)
        finally:
            (
                settings.motion_feedback_auto_disable,
                settings.motion_pattern_library_enabled_in_freestyle,
                settings.motion_pattern_library_enabled_in_chat,
            ) = original

    def test_system_prompts_route_returns_all_four_prompt_kinds(self):
        from strokegpt.web import settings

        original_min = settings.min_speed
        original_max = settings.max_speed
        original_mode = settings.llm_prompt_mode
        try:
            settings.min_speed = 18
            settings.max_speed = 62
            settings.llm_prompt_mode = "revibed"

            response = self.client.get("/system_prompts")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            for key in ("chat", "repair", "name_this_move", "profile_consolidation",
                        "name_this_move_sample_inputs", "user_genitalia",
                        "user_genitalia_custom", "user_genitalia_options"):
                self.assertIn(key, data)
            self.assertEqual(data["llm_prompt_mode"], "revibed")
            self.assertTrue(any(option["id"] == "legacy" for option in data["llm_prompt_mode_options"]))

            # The chat prompt is rendered against live context, so the
            # configured speed range must round-trip through it.
            self.assertIn("18-62", data["chat"])

            # Repair prompt is the chat system prompt + a static suffix
            # block; the suffix must be appended (not replaced).
            self.assertIn("18-62", data["repair"])
            self.assertIn("MOTION RESPONSE REPAIR", data["repair"])
            self.assertNotIn("MOTION RESPONSE REPAIR", data["chat"])

            # Name-this-move prompt embeds the sample speed/depth/mood
            # so the user can see the shape at a glance.
            sample = data["name_this_move_sample_inputs"]
            self.assertIn(f"speed {sample['speed']}%", data["name_this_move"])
            self.assertIn(f"depth {sample['depth']}%", data["name_this_move"])
            self.assertIn(f"mood '{sample['mood']}'", data["name_this_move"])

            # Profile consolidation prompt must include the user-profile
            # JSON anchor so the model can actually edit it.
            self.assertIn("EXISTING PROFILE JSON", data["profile_consolidation"])
            self.assertIn("NEW CONVERSATION LOG", data["profile_consolidation"])
        finally:
            settings.min_speed = original_min
            settings.max_speed = original_max
            settings.llm_prompt_mode = original_mode

    def test_system_prompts_route_returns_selected_custom_prompt_set(self):
        from strokegpt.web import llm, settings

        original_mode = settings.llm_prompt_mode
        original_prompt_sets = list(getattr(settings, "llm_custom_prompt_sets", []))
        original_autospeak = settings.autospeak_enabled
        try:
            settings.autospeak_enabled = False
            prompt_set, _ = settings.set_llm_custom_prompt_set(
                "Route Custom",
                {
                    "chat": "ROUTE CUSTOM CHAT",
                    "repair": "ROUTE CUSTOM REPAIR",
                    "name_this_move": "Route name {speed} {depth} {mood}",
                    "profile_consolidation": "Route profile {current_profile_json} {chat_log_text}",
                },
            )
            llm.set_custom_prompt_set(prompt_set)

            response = self.client.get("/system_prompts")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["llm_prompt_mode"], "custom:route-custom")
            self.assertEqual(data["chat"], "ROUTE CUSTOM CHAT")
            self.assertEqual(data["repair"], "ROUTE CUSTOM REPAIR")
            self.assertIn("Route name 60 40 Teasing", data["name_this_move"])
            self.assertIn("Route profile", data["profile_consolidation"])
        finally:
            settings.llm_prompt_mode = original_mode
            settings.llm_custom_prompt_sets = original_prompt_sets
            settings.autospeak_enabled = original_autospeak
            llm.set_custom_prompt_set(settings.selected_llm_custom_prompt_set())

    def test_system_prompts_route_does_not_leak_proper_noun_handles_in_default_branch(self):
        # Persona Naming And Prompt Audit follow-up: the Prompts tab is
        # the first user-visible surface that exposes the rendered chat
        # prompt to non-developers, so the default (non-special-persona)
        # branch must not leak any proper-noun character handles into
        # the model.
        response = self.client.get("/system_prompts")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        for prompt_kind in ("chat", "repair"):
            self.assertNotIn("GLaDOS", data[prompt_kind])
            self.assertNotIn("Portal", data[prompt_kind])


if __name__ == "__main__":
    unittest.main()
