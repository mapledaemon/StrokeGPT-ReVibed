import unittest
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
        sent_commands = []
        try:
            handy._send_command = lambda path, body=None: sent_commands.append((path, body or {})) or True
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
            self.assertIn(("hamp/stop", {}), sent_commands)
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

                response = self.client.post("/set_motion_backend", json={"motion_backend": "bad"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["motion_backend"], "hamp")
                self.assertEqual(motion.backend, "hamp")
        finally:
            settings.motion_backend = original_setting
            motion.set_backend(original_controller)

    def test_llm_edge_permissions_can_be_selected_and_saved(self):
        from strokegpt.web import settings

        original = (
            settings.allow_llm_edge_in_freestyle,
            settings.allow_llm_edge_in_chat,
        )
        try:
            with mock.patch.object(settings, "save"):
                response = self.client.post("/set_llm_edge_permissions", json={
                    "allow_llm_edge_in_freestyle": False,
                    "allow_llm_edge_in_chat": False,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertFalse(data["allow_llm_edge_in_freestyle"])
            self.assertFalse(data["allow_llm_edge_in_chat"])
            self.assertFalse(settings.allow_llm_edge_in_freestyle)
            self.assertFalse(settings.allow_llm_edge_in_chat)
            self.assertIn("motion_preferences", data)

            response = self.client.get("/check_settings")
            payload = response.get_json()
            self.assertFalse(payload["allow_llm_edge_in_freestyle"])
            self.assertFalse(payload["allow_llm_edge_in_chat"])
        finally:
            (
                settings.allow_llm_edge_in_freestyle,
                settings.allow_llm_edge_in_chat,
            ) = original

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

        original = settings.motion_feedback_auto_disable
        try:
            with mock.patch.object(settings, "save"):
                response = self.client.post("/motion_feedback_options", json={"auto_disable": True})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["motion_feedback_auto_disable"])
            self.assertTrue(settings.motion_feedback_auto_disable)
            self.assertIn("motion_patterns", data)
            self.assertIn("motion_preferences", data)
        finally:
            settings.motion_feedback_auto_disable = original

    def test_system_prompts_route_returns_all_four_prompt_kinds(self):
        from strokegpt.web import settings

        original_min = settings.min_speed
        original_max = settings.max_speed
        try:
            settings.min_speed = 18
            settings.max_speed = 62

            response = self.client.get("/system_prompts")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            for key in ("chat", "repair", "name_this_move", "profile_consolidation",
                        "name_this_move_sample_inputs"):
                self.assertIn(key, data)

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
