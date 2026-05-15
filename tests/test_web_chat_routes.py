import json
import unittest
from types import SimpleNamespace
from unittest import mock

from tests._web_support import WebTestCase


class WebChatRouteTests(WebTestCase):
    def test_send_message_returns_fallback_when_llm_omits_chat(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
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
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_send_message_queues_same_text_used_for_local_tts(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        spoken = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
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
            self.assertIn("timings", data)
            self.assertIn("request_ms", data["timings"])
            self.assertIn("llm_ms", data["timings"])
            self.assertIn("motion_repair_ms", data["timings"])
            self.assertIn("motion_apply_ms", data["timings"])

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
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_send_message_stream_renders_deltas_without_queue_duplicate(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        spoken = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            chunks = iter([
                '{"chat":"Visible ',
                'as it arrives.","move":null,"new_mood":null}',
            ])
            with mock.patch.object(llm, "iter_chat_response_content", return_value=chunks), \
                    mock.patch.object(audio, "generate_audio_for_text", side_effect=lambda text: spoken.append(text)):
                response = self.client.post("/send_message_stream", json={
                    "message": "say something",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                }, buffered=True)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-transform")
            self.assertEqual(response.headers.get("X-Accel-Buffering"), "no")
            events = [
                json.loads(line)
                for line in response.get_data(as_text=True).splitlines()
                if line.strip()
            ]
            delta_text = "".join(event.get("text", "") for event in events if event["type"] == "delta")
            final = [event["data"] for event in events if event["type"] == "final"][-1]
            self.assertEqual(delta_text, "Visible as it arrives.")
            self.assertEqual(final["status"], "ok")
            self.assertEqual(final["chat"], "Visible as it arrives.")
            self.assertTrue(final["chat_streamed"])
            self.assertFalse(final["chat_queued"])

            updates = self.client.get("/get_updates")
            try:
                queued = updates.get_json()["messages"]
            finally:
                updates.close()
            self.assertEqual(queued, [])
            self.assertEqual(list(app_state.chat_history), [
                {"role": "user", "content": "say something"},
                {"role": "assistant", "content": "Visible as it arrives."},
            ])
            self.assertEqual(spoken, ["Visible as it arrives."])
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_streaming_chat_extractor_parses_incremental_escapes(self):
        from strokegpt.web import _StreamingChatTextExtractor

        extractor = _StreamingChatTextExtractor()
        chunks = [
            '{"move":null,',
            '"chat":"Line 1\\n',
            'Line 2 \\u2764',
            '","new_mood":null}',
        ]

        deltas = [extractor.append(chunk) for chunk in chunks]

        self.assertEqual("".join(deltas), "Line 1\nLine 2 \u2764")
        self.assertEqual(json.loads(extractor.raw_content())["chat"], "Line 1\nLine 2 \u2764")
        self.assertTrue(extractor.has_streamed_text())

    def test_send_message_keeps_llm_transport_error_out_of_dialogue_state(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            error_text = "LLM Connection Error: HTTPConnectionPool read timed out"
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": error_text,
                "move": None,
                "new_mood": None,
            }), mock.patch.object(llm, "repair_motion_response") as repair_motion_response, \
                    mock.patch.object(audio, "generate_audio_for_text") as generate_audio:
                response = self.client.post("/send_message", json={
                    "message": "switch to another rhythm",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "model_error")
            self.assertEqual(data["message"], "Model request failed. Check Ollama status and try again.")
            self.assertEqual(data["chat"], error_text)
            self.assertFalse(data["chat_queued"])
            self.assertFalse(data["motion_repaired"])
            self.assertFalse(data["motion_applied"])

            updates = self.client.get("/get_updates")
            try:
                queued = updates.get_json()["messages"]
            finally:
                updates.close()
            self.assertEqual(queued, [])
            self.assertEqual(list(app_state.chat_history), [{"role": "user", "content": "switch to another rhythm"}])
            repair_motion_response.assert_not_called()
            generate_audio.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_send_message_repairs_motion_claim_without_move(self):
        from strokegpt.web import app_state, audio, handy, llm, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_handy_state = (
            handy.last_relative_speed,
            handy.last_depth_pos,
            handy.last_stroke_range,
        )
        captured_targets = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
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
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_send_message_does_not_repair_non_action_question(self):
        from strokegpt.web import app_state, audio, handy, llm, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
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
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_send_message_relay_motion_feedback_to_active_mode(self):
        from strokegpt.web import app_state, audio, handy, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_task = app_state.auto_mode_active_task
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        app_state.mode_message_queue.clear()
        app_state.mode_message_event.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            app_state.auto_mode_active_task = SimpleNamespace(name="edging", stop=lambda: None)
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
            self.assertEqual(list(app_state.mode_message_queue), ["focus on the tip"])
            self.assertTrue(app_state.mode_message_event.is_set())
            apply_generated_target.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            app_state.auto_mode_active_task = original_task
            app_state.mode_message_queue.clear()
            app_state.mode_message_event.clear()
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_stop_command_uses_status_instead_of_bot_chat_bubble(self):
        from strokegpt.web import app_state, handy, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        app_state.mode_status_message = ""
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"

            with mock.patch("strokegpt.web.motion.stop", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "stop",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "stopped")
            self.assertEqual(list(app_state.messages_for_ui), [])
            self.assertEqual(list(app_state.chat_history), [{"role": "user", "content": "stop"}])

            updates = self.client.get("/get_updates")
            try:
                payload = updates.get_json()
            finally:
                updates.close()
            self.assertEqual(payload["messages"], [])
            self.assertEqual(payload["mode_status_message"], "Stopping.")
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()
            app_state.mode_status_message = ""

    def test_im_close_chat_signals_active_mode_instead_of_restarting_milk(self):
        from strokegpt.web import app_state, handy, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_task = app_state.auto_mode_active_task
        app_state.user_signal_event.clear()
        app_state.mode_message_event.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            app_state.auto_mode_active_task = SimpleNamespace(name="freestyle", stop=lambda: None)

            response = self.client.post("/send_message", json={
                "message": "I'm close",
                "key": "test-key",
                "persona_desc": settings.persona_desc,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "close_signaled")
            self.assertEqual(data["mode"], "freestyle")
            self.assertTrue(app_state.user_signal_event.is_set())
            self.assertTrue(app_state.mode_message_event.is_set())
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            app_state.auto_mode_active_task = original_task
            app_state.user_signal_event.clear()
            app_state.mode_message_event.clear()
            app_state.chat_history.clear()

    def test_handsfree_llm_mode_action_can_signal_active_mode(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_task = app_state.auto_mode_active_task
        original_handsfree_actions = settings.voice_input_hands_free_mode_actions
        original_voice_mode = settings.voice_input_mode
        captured_contexts = []
        app_state.user_signal_event.clear()
        app_state.mode_message_event.clear()
        app_state.mode_message_queue.clear()
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.voice_input_hands_free_mode_actions = True
            settings.voice_input_mode = "hands_free"
            app_state.auto_mode_active_task = SimpleNamespace(name="freestyle", stop=lambda: None)

            def fake_response(_history, context):
                captured_contexts.append(dict(context))
                return {
                    "chat": "I heard you. Holding the edge.",
                    "move": None,
                    "mode_action": "close_signal",
                    "new_mood": None,
                }

            with mock.patch.object(llm, "get_chat_response", side_effect=fake_response), \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "keep me right at the edge",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                    "source": "voice_hands_free",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["mode_action"], "close_signal")
            self.assertTrue(data["mode_action_applied"])
            self.assertFalse(data["active_mode_message_relayed"])
            self.assertTrue(app_state.user_signal_event.is_set())
            self.assertTrue(app_state.mode_message_event.is_set())
            self.assertEqual(list(app_state.mode_message_queue), [])
            self.assertTrue(captured_contexts[-1]["handsfree_mode_actions_enabled"])
            self.assertEqual(captured_contexts[-1]["active_mode"], "freestyle")
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            settings.voice_input_hands_free_mode_actions = original_handsfree_actions
            settings.voice_input_mode = original_voice_mode
            app_state.auto_mode_active_task = original_task
            app_state.user_signal_event.clear()
            app_state.mode_message_event.clear()
            app_state.mode_message_queue.clear()
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_typed_chat_mode_action_requires_opt_in(self):
        import strokegpt.web as web
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_chat_mode_actions = settings.allow_llm_mode_actions_in_chat
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.allow_llm_mode_actions_in_chat = False
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "I can keep talking.",
                "move": None,
                "mode_action": "start_freestyle",
                "new_mood": None,
            }), mock.patch.object(web, "start_background_mode") as start_background_mode, \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "say hello",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                    "source": "chat",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["mode_action"], "")
            self.assertFalse(data["mode_action_applied"])
            start_background_mode.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            settings.allow_llm_mode_actions_in_chat = original_chat_mode_actions
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_typed_chat_mode_action_can_start_visible_mode_when_enabled(self):
        import strokegpt.web as web
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_chat_mode_actions = settings.allow_llm_mode_actions_in_chat
        captured_contexts = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.allow_llm_mode_actions_in_chat = True

            def fake_response(_history, context):
                captured_contexts.append(dict(context))
                return {
                    "chat": "Starting Freestyle.",
                    "move": None,
                    "mode_action": "start_freestyle",
                    "new_mood": None,
                }

            with mock.patch.object(llm, "get_chat_response", side_effect=fake_response), \
                    mock.patch.object(web, "start_background_mode") as start_background_mode, \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "surprise me",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                    "source": "chat",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["mode_action"], "start_freestyle")
            self.assertTrue(data["mode_action_applied"])
            start_background_mode.assert_called_once_with(
                web.freestyle_mode_logic,
                "Starting adaptive Freestyle.",
                mode_name="freestyle",
            )
            self.assertTrue(captured_contexts[-1]["mode_actions_enabled"])
            self.assertFalse(captured_contexts[-1]["handsfree_mode_actions_enabled"])
            self.assertEqual(captured_contexts[-1]["mode_action_request_source"], "typed chat")
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            settings.allow_llm_mode_actions_in_chat = original_chat_mode_actions
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_handsfree_without_mode_action_still_relays_feedback_to_active_mode(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_task = app_state.auto_mode_active_task
        original_handsfree_actions = settings.voice_input_hands_free_mode_actions
        original_voice_mode = settings.voice_input_mode
        app_state.user_signal_event.clear()
        app_state.mode_message_event.clear()
        app_state.mode_message_queue.clear()
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.voice_input_hands_free_mode_actions = True
            settings.voice_input_mode = "hands_free"
            app_state.auto_mode_active_task = SimpleNamespace(name="edging", stop=lambda: None)
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "I will keep that shape.",
                "move": {"zone": "tip", "pattern": "tease"},
                "mode_action": None,
                "new_mood": None,
            }), mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "focus on the tip",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                    "source": "voice_hands_free",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["mode_action"], "")
            self.assertFalse(data["mode_action_applied"])
            self.assertTrue(data["active_mode_message_relayed"])
            self.assertEqual(list(app_state.mode_message_queue), ["focus on the tip"])
            self.assertTrue(app_state.mode_message_event.is_set())
            self.assertFalse(app_state.user_signal_event.is_set())
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            settings.voice_input_hands_free_mode_actions = original_handsfree_actions
            settings.voice_input_mode = original_voice_mode
            app_state.auto_mode_active_task = original_task
            app_state.user_signal_event.clear()
            app_state.mode_message_event.clear()
            app_state.mode_message_queue.clear()
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_close_signal_wakes_edging_milking_or_freestyle_mode(self):
        from strokegpt.web import app_state

        original_task = app_state.auto_mode_active_task
        app_state.user_signal_event.clear()
        app_state.mode_message_event.clear()
        try:
            for mode_name in ("edging", "milking", "freestyle"):
                with self.subTest(mode_name=mode_name):
                    app_state.user_signal_event.clear()
                    app_state.mode_message_event.clear()
                    app_state.auto_mode_active_task = SimpleNamespace(name=mode_name, stop=lambda: None)

                    response = self.client.post("/signal_edge")

                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertEqual(data["status"], "signaled")
                    self.assertEqual(data["mode"], mode_name)
                    self.assertTrue(app_state.user_signal_event.is_set())
                    self.assertTrue(app_state.mode_message_event.is_set())
        finally:
            app_state.auto_mode_active_task = original_task
            app_state.user_signal_event.clear()
            app_state.mode_message_event.clear()

    def test_set_llm_permissions_saves_chat_mode_action_toggle(self):
        from strokegpt.web import settings

        original = (
            settings.allow_llm_edge_in_freestyle,
            settings.allow_llm_edge_in_chat,
            settings.allow_llm_mode_actions_in_chat,
            settings.save,
        )
        try:
            settings.save = lambda *args, **kwargs: None
            response = self.client.post("/set_llm_edge_permissions", json={
                "allow_llm_edge_in_freestyle": False,
                "allow_llm_edge_in_chat": False,
                "allow_llm_mode_actions_in_chat": True,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertFalse(settings.allow_llm_edge_in_freestyle)
            self.assertFalse(settings.allow_llm_edge_in_chat)
            self.assertTrue(settings.allow_llm_mode_actions_in_chat)
            self.assertFalse(data["allow_llm_edge_in_freestyle"])
            self.assertFalse(data["allow_llm_edge_in_chat"])
            self.assertTrue(data["allow_llm_mode_actions_in_chat"])
        finally:
            (
                settings.allow_llm_edge_in_freestyle,
                settings.allow_llm_edge_in_chat,
                settings.allow_llm_mode_actions_in_chat,
                settings.save,
            ) = original

    def test_memory_toggle_route_updates_runtime_state(self):
        import strokegpt.web as web

        original = web.app_state.use_long_term_memory
        try:
            web.app_state.use_long_term_memory = True

            response = self.client.get("/check_settings")
            self.assertTrue(response.get_json()["use_long_term_memory"])

            response = self.client.post("/toggle_memory")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertFalse(data["use_long_term_memory"])
            self.assertFalse(web.app_state.use_long_term_memory)

            response = self.client.post("/toggle_memory", json={"enabled": True})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["use_long_term_memory"])
            self.assertTrue(web.app_state.use_long_term_memory)
        finally:
            web.app_state.use_long_term_memory = original

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

    def test_background_mode_narration_stays_out_of_chat_history(self):
        import strokegpt.web as web
        from strokegpt.web import app_state

        original_task = app_state.auto_mode_active_task
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        app_state.mode_status_message = ""

        def mode_logic(stop_event, _services, callbacks):
            callbacks["send_message"]("Adding slower pressure in Freestyle.")
            stop_event.set()

        try:
            with mock.patch.object(web.motion, "stop", return_value=None):
                web.start_background_mode(
                    mode_logic,
                    "Starting adaptive Freestyle.",
                    mode_name="freestyle",
                )
                task = app_state.auto_mode_active_task
                self.assertIsNotNone(task)
                task.join(timeout=1)
                self.assertFalse(task.is_alive())

            self.assertEqual(list(app_state.messages_for_ui), [])
            self.assertEqual(list(app_state.chat_history), [])

            response = self.client.get("/get_updates")
            try:
                payload = response.get_json()
            finally:
                response.close()
            self.assertEqual(payload["messages"], [])
            self.assertEqual(payload["mode_status_message"], "Okay, you're in control now.")
        finally:
            app_state.auto_mode_active_task = original_task
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()
            app_state.mode_status_message = ""
            app_state.mode_message_queue.clear()
            app_state.mode_message_event.clear()

    def test_start_auto_route_uses_auto_mode(self):
        import strokegpt.web as web

        with mock.patch.object(web, "start_background_mode") as start_background_mode:
            response = self.client.post("/start_auto_mode")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "auto_started")
        start_background_mode.assert_called_once_with(
            web.auto_mode_logic,
            "Okay, I'll take over...",
            mode_name='auto',
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
