import unittest
from types import SimpleNamespace
from unittest import mock

from tests._web_support import WebTestCase


class WebChatRouteTests(WebTestCase):
    def test_send_message_returns_fallback_when_llm_omits_chat(self):
        from strokegpt.web import audio, chat_history, handy, llm, messages_for_ui, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        messages_for_ui.clear()
        chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with mock.patch.object(llm, "get_chat_response", return_value={"move": None, "new_mood": None}), \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "hello",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data["chat_queued"])
            self.assertIn("no chat text", data["chat"])

            updates = self.client.get("/get_updates")
            try:
                queued = updates.get_json()["messages"]
            finally:
                updates.close()
            self.assertEqual(len(queued), 1)
            self.assertIn("no chat text", queued[0])
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            messages_for_ui.clear()
            chat_history.clear()

    def test_send_message_queues_same_text_used_for_local_tts(self):
        from strokegpt.web import audio, chat_history, handy, llm, messages_for_ui, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        spoken = []
        messages_for_ui.clear()
        chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "This text should be visible and spoken.",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(audio, "generate_audio_for_text", side_effect=lambda text: spoken.append(text)):
                response = self.client.post("/send_message", json={
                    "message": "say something",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["chat"], "This text should be visible and spoken.")
            self.assertTrue(data["chat_queued"])

            updates = self.client.get("/get_updates")
            try:
                queued = updates.get_json()["messages"]
            finally:
                updates.close()
            self.assertEqual(queued, ["This text should be visible and spoken."])
            self.assertEqual(spoken, ["This text should be visible and spoken."])
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            messages_for_ui.clear()
            chat_history.clear()

    def test_send_message_repairs_motion_claim_without_move(self):
        from strokegpt.web import audio, chat_history, handy, llm, messages_for_ui, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_handy_state = (
            handy.last_relative_speed,
            handy.last_depth_pos,
            handy.last_stroke_range,
        )
        captured_targets = []
        messages_for_ui.clear()
        chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            handy.last_relative_speed = 30
            handy.last_depth_pos = 40
            handy.last_stroke_range = 50
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "I'll switch to a new rhythm.",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(llm, "repair_motion_response", return_value={
                "chat": "Switching to a quick tip flick.",
                "move": {"zone": "tip", "pattern": "flick"},
                "new_mood": "Teasing",
            }) as repair, mock.patch.object(
                motion,
                "apply_generated_target",
                side_effect=lambda target, **_kwargs: captured_targets.append(target),
            ), \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "switch to another rhythm",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["chat"], "Switching to a quick tip flick.")
            self.assertTrue(data["motion_repaired"])
            self.assertTrue(data["motion_applied"])
            repair.assert_called_once()
            self.assertEqual(len(captured_targets), 1)
            self.assertIn("flick", captured_targets[0].label)
            self.assertEqual(captured_targets[0].depth, 10)
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            (
                handy.last_relative_speed,
                handy.last_depth_pos,
                handy.last_stroke_range,
            ) = original_handy_state
            messages_for_ui.clear()
            chat_history.clear()

    def test_send_message_does_not_repair_non_action_question(self):
        from strokegpt.web import audio, chat_history, handy, llm, messages_for_ui, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        messages_for_ui.clear()
        chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "The tip is the shallow end of the stroke range.",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(llm, "repair_motion_response") as repair, \
                    mock.patch.object(motion, "apply_generated_target") as apply_generated_target, \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "what does tip mean?",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertFalse(data["motion_repaired"])
            self.assertFalse(data["motion_applied"])
            repair.assert_not_called()
            apply_generated_target.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            messages_for_ui.clear()
            chat_history.clear()

    def test_send_message_relay_motion_feedback_to_active_mode(self):
        from strokegpt.web import audio, auto_mode_active_task, chat_history, handy
        from strokegpt.web import messages_for_ui, mode_message_event, mode_message_queue, motion, settings
        import strokegpt.web as web

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_task = auto_mode_active_task
        messages_for_ui.clear()
        chat_history.clear()
        mode_message_queue.clear()
        mode_message_event.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            web.auto_mode_active_task = SimpleNamespace(name="edging", stop=lambda: None)
            with mock.patch.object(motion, "apply_generated_target") as apply_generated_target, \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "focus on the tip",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "message_relayed_to_active_mode")
            self.assertEqual(list(mode_message_queue), ["focus on the tip"])
            self.assertTrue(mode_message_event.is_set())
            apply_generated_target.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            web.auto_mode_active_task = original_task
            mode_message_queue.clear()
            mode_message_event.clear()
            messages_for_ui.clear()
            chat_history.clear()

    def test_close_signal_wakes_edging_milking_or_freestyle_mode(self):
        from strokegpt.web import auto_mode_active_task, mode_message_event, user_signal_event
        import strokegpt.web as web

        original_task = auto_mode_active_task
        user_signal_event.clear()
        mode_message_event.clear()
        try:
            for mode_name in ("edging", "milking", "freestyle"):
                with self.subTest(mode_name=mode_name):
                    user_signal_event.clear()
                    mode_message_event.clear()
                    web.auto_mode_active_task = SimpleNamespace(name=mode_name, stop=lambda: None)

                    response = self.client.post("/signal_edge")

                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertEqual(data["status"], "signaled")
                    self.assertEqual(data["mode"], mode_name)
                    self.assertTrue(user_signal_event.is_set())
                    self.assertTrue(mode_message_event.is_set())
        finally:
            web.auto_mode_active_task = original_task
            user_signal_event.clear()
            mode_message_event.clear()

    def test_memory_toggle_route_updates_runtime_state(self):
        import strokegpt.web as web

        original = web.use_long_term_memory
        try:
            web.use_long_term_memory = True

            response = self.client.get("/check_settings")
            self.assertTrue(response.get_json()["use_long_term_memory"])

            response = self.client.post("/toggle_memory")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertFalse(data["use_long_term_memory"])
            self.assertFalse(web.use_long_term_memory)

            response = self.client.post("/toggle_memory", json={"enabled": True})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["use_long_term_memory"])
            self.assertTrue(web.use_long_term_memory)
        finally:
            web.use_long_term_memory = original

    def test_start_freestyle_route_uses_adaptive_mode(self):
        import strokegpt.web as web

        with mock.patch.object(web, "start_background_mode") as start_background_mode:
            response = self.client.post("/start_freestyle_mode")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "freestyle_started")
        start_background_mode.assert_called_once_with(
            web.freestyle_mode_logic,
            "Starting adaptive Freestyle.",
            mode_name='freestyle',
        )

    def test_server_motion_request_detector_accepts_slowly(self):
        from strokegpt.web import _looks_like_motion_request

        self.assertTrue(_looks_like_motion_request("slowly focus on the tip"))

    def test_llm_context_includes_configured_speed_limits(self):
        from strokegpt.web import get_current_context, settings

        original_min_speed = settings.min_speed
        original_max_speed = settings.max_speed
        try:
            settings.min_speed = 15
            settings.max_speed = 55

            context = get_current_context()

            self.assertEqual(context["min_speed"], 15)
            self.assertEqual(context["max_speed"], 55)
        finally:
            settings.min_speed = original_min_speed
            settings.max_speed = original_max_speed


if __name__ == "__main__":
    unittest.main()
