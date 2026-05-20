import json
import unittest
import time
from types import SimpleNamespace
from unittest import mock

from tests._web_support import WebTestCase


class WebChatRouteTests(WebTestCase):
    def test_unrequested_tight_llm_focus_preserves_current_pattern(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import _target_from_llm_response_move, settings

        original_pattern_library_chat = settings.motion_pattern_library_enabled_in_chat
        current = MotionTarget(27, 50, 95, "llm+milk")
        response = {
            "move": {
                "sp": 21,
                "dp": 0,
                "rng": 36,
                "zone": "tip",
                "pattern": "flutter",
            }
        }

        try:
            settings.motion_pattern_library_enabled_in_chat = True
            target = _target_from_llm_response_move(response, current, user_input="fuck me")
        finally:
            settings.motion_pattern_library_enabled_in_chat = original_pattern_library_chat

        self.assertEqual(target.label, "llm+milk")
        self.assertEqual(target.speed, 21)
        self.assertEqual(target.depth, 50)
        self.assertEqual(target.stroke_range, 95)
        self.assertIsNone(target.motion_program)

    def test_explicit_tight_llm_focus_request_is_preserved(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import _target_from_llm_response_move, settings

        original_pattern_library_chat = settings.motion_pattern_library_enabled_in_chat
        current = MotionTarget(27, 50, 95, "llm+milk")
        response = {
            "move": {
                "sp": 21,
                "dp": 0,
                "rng": 36,
                "zone": "tip",
                "pattern": "flutter",
            }
        }

        try:
            settings.motion_pattern_library_enabled_in_chat = True
            target = _target_from_llm_response_move(response, current, user_input="flutter at the tip")
        finally:
            settings.motion_pattern_library_enabled_in_chat = original_pattern_library_chat

        self.assertEqual(target.label, "llm+tip+flutter")
        self.assertEqual(target.speed, 21)
        self.assertEqual(target.depth, 0)
        self.assertEqual(target.stroke_range, 36)

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
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
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
        original_model = llm.model
        original_thinking = llm.thinking_enabled
        original_prompt_mode = settings.llm_prompt_mode
        spoken = []
        app_state.messages_for_ui.clear()
        app_state.ui_message_log.clear()
        app_state.ui_message_next_id = 0
        app_state.ui_client_cursors.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            llm.model = "local/direct-model:latest"
            llm.thinking_enabled = True
            settings.llm_prompt_mode = "revibed"
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "This text should be visible and spoken.",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(audio, "enqueue_text_for_audio", side_effect=lambda text: spoken.append(text)):
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
            self.assertEqual(data["llm_message_metadata"]["model"], "local/direct-model:latest")
            self.assertTrue(data["llm_message_metadata"]["thinking_enabled"])

            updates = self.client.get("/get_updates?client_id=tab-b")
            try:
                payload = updates.get_json()
                queued = payload["messages"]
                records = payload["message_records"]
            finally:
                updates.close()
            self.assertEqual(queued, ["This text should be visible and spoken."])
            self.assertEqual(records[0]["text"], "This text should be visible and spoken.")
            self.assertEqual(records[0]["metadata"]["model"], "local/direct-model:latest")
            self.assertEqual(records[0]["metadata"]["prompt_mode"], "revibed")
            self.assertTrue(records[0]["metadata"]["thinking_enabled"])
            self.assertEqual(spoken, ["This text should be visible and spoken."])
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            llm.model = original_model
            llm.thinking_enabled = original_thinking
            settings.llm_prompt_mode = original_prompt_mode
            app_state.messages_for_ui.clear()
            app_state.ui_message_log.clear()
            app_state.ui_message_next_id = 0
            app_state.ui_client_cursors.clear()
            app_state.chat_history.clear()

    def test_send_message_starts_cached_local_voice_preload_before_llm(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_audio = (audio.provider, audio.is_on)
        original_auto_preload_disabled = self.app.config.get("DISABLE_AUTO_LOCAL_TTS_PRELOAD")
        calls = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            audio.provider = "local"
            audio.is_on = True
            self.app.config["DISABLE_AUTO_LOCAL_TTS_PRELOAD"] = False

            def fake_llm_response(*_args, **_kwargs):
                calls.append("llm")
                return {"chat": "Ready.", "move": None, "new_mood": None}

            def fake_preload():
                calls.append("preload")
                return True

            with mock.patch.object(audio, "preload_local_model_async_if_cached", side_effect=fake_preload), \
                    mock.patch.object(llm, "get_chat_response", side_effect=fake_llm_response), \
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
                response = self.client.post("/send_message", json={
                    "message": "hello",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "ok")
            self.assertEqual(calls[:2], ["preload", "llm"])
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            audio.provider, audio.is_on = original_audio
            self.app.config["DISABLE_AUTO_LOCAL_TTS_PRELOAD"] = original_auto_preload_disabled
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_send_message_schedules_standalone_autospeak_followup(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings = (
            settings.handy_key,
            settings.autospeak_enabled,
            settings.autospeak_min_seconds,
            settings.autospeak_max_seconds,
        )
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.autospeak_enabled = True
            settings.autospeak_min_seconds = 2
            settings.autospeak_max_seconds = 30
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "I will keep talking.",
                "move": None,
                "new_mood": None,
                "autospeak_seconds": 7,
            }), mock.patch.object(audio, "enqueue_text_for_audio", return_value=True), \
                    mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=True) as schedule_autospeak:
                response = self.client.post("/send_message", json={
                    "message": "hello",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data["autospeak_scheduled"])
            schedule_autospeak.assert_called_once_with(7)
        finally:
            handy.handy_key = original_key
            (
                settings.handy_key,
                settings.autospeak_enabled,
                settings.autospeak_min_seconds,
                settings.autospeak_max_seconds,
            ) = original_settings
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_direct_motion_command_reschedules_autospeak(self):
        from strokegpt.web import app_state, handy, motion, settings

        original_key = handy.handy_key
        original_settings = (
            settings.handy_key,
            settings.autospeak_enabled,
            settings.autospeak_min_seconds,
            settings.autospeak_max_seconds,
        )
        captured_targets = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.autospeak_enabled = True
            settings.autospeak_min_seconds = 2
            settings.autospeak_max_seconds = 30
            with mock.patch.object(
                motion,
                "apply_generated_target",
                side_effect=lambda target, **_kwargs: captured_targets.append(target),
            ), mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=True) as schedule_autospeak:
                response = self.client.post("/send_message", json={
                    "message": "lick the base",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "move_applied")
            self.assertTrue(data["autospeak_scheduled"])
            schedule_autospeak.assert_called_once_with(0)
            self.assertEqual(len(captured_targets), 1)
            self.assertEqual(captured_targets[0].depth, 88)
            self.assertEqual(captured_targets[0].stroke_range, 24)
        finally:
            handy.handy_key = original_key
            (
                settings.handy_key,
                settings.autospeak_enabled,
                settings.autospeak_min_seconds,
                settings.autospeak_max_seconds,
            ) = original_settings
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_direct_chat_pattern_command_uses_patternless_target_when_chat_library_disabled(self):
        from strokegpt.web import app_state, handy, motion, settings

        original_key = handy.handy_key
        original_settings = (
            settings.handy_key,
            settings.motion_pattern_library_enabled_in_chat,
        )
        captured_targets = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.motion_pattern_library_enabled_in_chat = False
            with mock.patch.object(
                motion,
                "apply_generated_target",
                side_effect=lambda target, **_kwargs: captured_targets.append(target),
            ), mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=False):
                response = self.client.post("/send_message", json={
                    "message": "flutter at the tip",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "move_applied")
            self.assertEqual(len(captured_targets), 1)
            self.assertNotIn("flutter", captured_targets[0].label)
            self.assertIn("tip", captured_targets[0].label)
        finally:
            handy.handy_key = original_key
            (
                settings.handy_key,
                settings.motion_pattern_library_enabled_in_chat,
            ) = original_settings
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_standalone_autospeak_turn_emits_chat_and_reschedules(self):
        import strokegpt.web as web
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings = (
            settings.handy_key,
            settings.autospeak_enabled,
            settings.autospeak_min_seconds,
            settings.autospeak_max_seconds,
        )
        spoken = []
        captured = {}
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.autospeak_enabled = True
            settings.autospeak_min_seconds = 0
            settings.autospeak_max_seconds = 12
            app_state.chat_history.append({"role": "user", "content": "hello"})
            with app_state.lock:
                app_state.autospeak_generation += 1
                token = app_state.autospeak_generation

            def fake_chat_response(messages, context, temperature=0.3):
                captured["messages"] = messages
                captured["context"] = context
                captured["temperature"] = temperature
                return {
                    "chat": "Still right here.",
                    "move": None,
                    "new_mood": "Playful",
                    "autospeak_seconds": 6,
                }

            with mock.patch.object(llm, "get_chat_response", side_effect=fake_chat_response), \
                    mock.patch.object(audio, "enqueue_text_for_audio", side_effect=lambda text: spoken.append(text)), \
                    mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=True) as schedule_autospeak:
                self.assertTrue(web._run_standalone_autospeak_turn(token))

            self.assertTrue(captured["context"]["autospeak_event"])
            self.assertEqual(captured["temperature"], 0.35)
            self.assertIn("Autospeak is due", captured["messages"][-1]["content"])
            self.assertEqual(list(app_state.messages_for_ui), ["Still right here."])
            self.assertIn({"role": "assistant", "content": "Still right here."}, list(app_state.chat_history))
            self.assertEqual(spoken, ["Still right here."])
            schedule_autospeak.assert_called_once_with(6)
        finally:
            handy.handy_key = original_key
            (
                settings.handy_key,
                settings.autospeak_enabled,
                settings.autospeak_min_seconds,
                settings.autospeak_max_seconds,
            ) = original_settings
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_standalone_autospeak_preflight_recovers_inactive_chat_motion(self):
        import strokegpt.web as web
        from strokegpt.motion import MotionTarget
        from strokegpt.web import app_state, audio, handy, llm, motion, settings

        original_key = handy.handy_key
        original_settings = (
            settings.handy_key,
            settings.autospeak_enabled,
            settings.autospeak_min_seconds,
            settings.autospeak_max_seconds,
        )
        original_target = app_state.chat_motion_keepalive_target
        original_attempt = app_state.chat_motion_keepalive_last_attempt_at
        original_live_pattern = app_state.last_live_motion_pattern_id
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        target = MotionTarget(34, 50, 88, "llm+milk")
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.autospeak_enabled = True
            settings.autospeak_min_seconds = 0
            settings.autospeak_max_seconds = 12
            app_state.chat_history.append({"role": "user", "content": "hello"})
            with app_state.lock:
                app_state.chat_motion_keepalive_target = target
                app_state.chat_motion_keepalive_last_attempt_at = 0.0
                app_state.autospeak_generation += 1
                token = app_state.autospeak_generation

            with mock.patch.object(motion, "observability_snapshot", return_value={"playback_active": False}), \
                    mock.patch.object(motion, "apply_generated_target") as apply_generated_target, \
                    mock.patch.object(llm, "get_chat_response", return_value={
                        "chat": "Still with you.",
                        "move": None,
                        "new_mood": None,
                        "autospeak_seconds": 6,
                    }), \
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True), \
                    mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=True):
                self.assertTrue(web._run_standalone_autospeak_turn(token))

            apply_generated_target.assert_called_once_with(target, source="autospeak preflight")
        finally:
            handy.handy_key = original_key
            (
                settings.handy_key,
                settings.autospeak_enabled,
                settings.autospeak_min_seconds,
                settings.autospeak_max_seconds,
            ) = original_settings
            with app_state.lock:
                app_state.chat_motion_keepalive_target = original_target
                app_state.chat_motion_keepalive_last_attempt_at = original_attempt
                app_state.last_live_motion_pattern_id = original_live_pattern
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_chat_motion_keepalive_restarts_saved_target_when_playback_is_inactive(self):
        import strokegpt.web as web
        from strokegpt.motion import MotionTarget
        from strokegpt.web import app_state, handy, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_target = app_state.chat_motion_keepalive_target
        original_attempt = app_state.chat_motion_keepalive_last_attempt_at
        original_live_pattern = app_state.last_live_motion_pattern_id
        target = MotionTarget(42, 55, 70, "llm+wave")
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with app_state.lock:
                app_state.chat_motion_keepalive_target = target
                app_state.chat_motion_keepalive_last_attempt_at = 0.0

            with mock.patch.object(motion, "observability_snapshot", return_value={"playback_active": False}), \
                    mock.patch.object(motion, "apply_generated_target") as apply_generated_target:
                self.assertTrue(web._chat_motion_keepalive_once("unit keepalive"))

            apply_generated_target.assert_called_once_with(target, source="unit keepalive")
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            with app_state.lock:
                app_state.chat_motion_keepalive_target = original_target
                app_state.chat_motion_keepalive_last_attempt_at = original_attempt
                app_state.last_live_motion_pattern_id = original_live_pattern

    def test_chat_motion_keepalive_skips_when_playback_is_active(self):
        import strokegpt.web as web
        from strokegpt.motion import MotionTarget
        from strokegpt.web import app_state, handy, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_target = app_state.chat_motion_keepalive_target
        original_attempt = app_state.chat_motion_keepalive_last_attempt_at
        target = MotionTarget(42, 55, 70, "llm+wave")
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with app_state.lock:
                app_state.chat_motion_keepalive_target = target
                app_state.chat_motion_keepalive_last_attempt_at = 0.0

            with mock.patch.object(motion, "observability_snapshot", return_value={"playback_active": True}), \
                    mock.patch.object(motion, "apply_generated_target") as apply_generated_target:
                self.assertFalse(web._chat_motion_keepalive_once("unit keepalive"))

            apply_generated_target.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            with app_state.lock:
                app_state.chat_motion_keepalive_target = original_target
                app_state.chat_motion_keepalive_last_attempt_at = original_attempt

    def test_motion_request_without_effect_clears_stale_chat_keepalive(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import app_state, audio, handy, llm, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_target = app_state.chat_motion_keepalive_target
        original_attempt = app_state.chat_motion_keepalive_last_attempt_at
        stale_target = MotionTarget(42, 55, 70, "llm+wave")
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with app_state.lock:
                app_state.chat_motion_keepalive_target = stale_target
                app_state.chat_motion_keepalive_last_attempt_at = 0.0

            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "I'll switch to something different.",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(llm, "repair_motion_response", return_value={
                "chat": "I tried to switch it up.",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(motion, "observability_snapshot", return_value={"playback_active": False}), \
                    mock.patch.object(motion, "apply_generated_target") as apply_generated_target, \
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
                response = self.client.post("/send_message", json={
                    "message": "switch to another rhythm",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertFalse(data["motion_applied"])
            self.assertFalse(data["motion_keepalive_restarted"])
            apply_generated_target.assert_not_called()
            self.assertIsNone(app_state.chat_motion_keepalive_target)
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            with app_state.lock:
                app_state.chat_motion_keepalive_target = original_target
                app_state.chat_motion_keepalive_last_attempt_at = original_attempt
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_motion_request_model_error_clears_stale_chat_keepalive(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import app_state, audio, handy, llm, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_target = app_state.chat_motion_keepalive_target
        original_attempt = app_state.chat_motion_keepalive_last_attempt_at
        stale_target = MotionTarget(34, 50, 88, "llm+milk")
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with app_state.lock:
                app_state.chat_motion_keepalive_target = stale_target
                app_state.chat_motion_keepalive_last_attempt_at = 0.0

            error_text = "LLM Connection Error: HTTPConnectionPool read timed out"
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": error_text,
                "move": None,
                "new_mood": None,
            }), mock.patch.object(llm, "repair_motion_response") as repair_motion_response, \
                    mock.patch.object(motion, "observability_snapshot", return_value={"playback_active": False}), \
                    mock.patch.object(motion, "apply_generated_target") as apply_generated_target, \
                    mock.patch.object(audio, "enqueue_text_for_audio") as enqueue_audio:
                response = self.client.post("/send_message", json={
                    "message": "switch to another rhythm",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "model_error")
            self.assertFalse(data["motion_keepalive_restarted"])
            self.assertFalse(data["motion_applied"])
            self.assertIsNone(app_state.chat_motion_keepalive_target)
            apply_generated_target.assert_not_called()
            repair_motion_response.assert_not_called()
            enqueue_audio.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            with app_state.lock:
                app_state.chat_motion_keepalive_target = original_target
                app_state.chat_motion_keepalive_last_attempt_at = original_attempt
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_standalone_autospeak_turn_retries_after_model_error(self):
        import strokegpt.web as web
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings = (
            settings.handy_key,
            settings.autospeak_enabled,
            settings.autospeak_min_seconds,
            settings.autospeak_max_seconds,
        )
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.autospeak_enabled = True
            settings.autospeak_min_seconds = 2
            settings.autospeak_max_seconds = 30
            app_state.chat_history.append({"role": "user", "content": "hello"})
            with app_state.lock:
                app_state.autospeak_generation += 1
                token = app_state.autospeak_generation

            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "LLM Connection Error: read timed out",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(audio, "enqueue_text_for_audio") as enqueue_audio, \
                    mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=True) as schedule_autospeak:
                self.assertTrue(web._run_standalone_autospeak_turn(token))

            self.assertEqual(list(app_state.messages_for_ui), [])
            self.assertEqual(list(app_state.chat_history), [{"role": "user", "content": "hello"}])
            enqueue_audio.assert_not_called()
            schedule_autospeak.assert_called_once_with(2.0)
        finally:
            handy.handy_key = original_key
            (
                settings.handy_key,
                settings.autospeak_enabled,
                settings.autospeak_min_seconds,
                settings.autospeak_max_seconds,
            ) = original_settings
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_standalone_autospeak_zero_delay_uses_natural_floor(self):
        import strokegpt.web as web

        with mock.patch("strokegpt.web.time.sleep") as sleep, \
                mock.patch("strokegpt.web._run_standalone_autospeak_turn", return_value=True) as run_turn:
            web._standalone_autospeak_worker(123, 0)

        sleep.assert_called_once_with(web.STANDALONE_AUTOSPEAK_WAKE_FLOOR_SECONDS)
        run_turn.assert_called_once_with(123)

    def test_standalone_autospeak_prompt_asks_for_wording_variety(self):
        import strokegpt.web as web

        message = web._standalone_autospeak_user_message([
            {"role": "assistant", "content": "Stay with me."},
            {"role": "assistant", "content": "Still with you."},
        ])

        self.assertIn("Do not repeat the previous chat line", message)
        self.assertIn("vary the erotic wording naturally", message)
        self.assertIn("Recent assistant lines to avoid repeating", message)
        self.assertIn('"Stay with me."', message)
        self.assertIn('"Still with you."', message)

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
                    mock.patch.object(audio, "enqueue_text_for_audio", side_effect=lambda text: spoken.append(text)):
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
            self.assertTrue(final["chat_queued"])

            updates = self.client.get("/get_updates")
            try:
                queued = updates.get_json()["messages"]
            finally:
                updates.close()
            self.assertEqual(queued, ["Visible as it arrives."])
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

    def test_send_message_stream_starts_cached_local_voice_preload_before_llm(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_audio = (audio.provider, audio.is_on)
        original_auto_preload_disabled = self.app.config.get("DISABLE_AUTO_LOCAL_TTS_PRELOAD")
        calls = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            audio.provider = "local"
            audio.is_on = True
            self.app.config["DISABLE_AUTO_LOCAL_TTS_PRELOAD"] = False

            def fake_chunks(*_args, **_kwargs):
                calls.append("llm")
                return iter(['{"chat":"Ready.","move":null,"new_mood":null}'])

            def fake_preload():
                calls.append("preload")
                return True

            with mock.patch.object(audio, "preload_local_model_async_if_cached", side_effect=fake_preload), \
                    mock.patch.object(llm, "iter_chat_response_content", side_effect=fake_chunks), \
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
                response = self.client.post("/send_message_stream", json={
                    "message": "hello",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                }, buffered=True)

            self.assertEqual(response.status_code, 200)
            events = [
                json.loads(line)
                for line in response.get_data(as_text=True).splitlines()
                if line.strip()
            ]
            final = [event["data"] for event in events if event["type"] == "final"][-1]
            self.assertEqual(final["status"], "ok")
            self.assertEqual(calls[:2], ["preload", "llm"])
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            audio.provider, audio.is_on = original_audio
            self.app.config["DISABLE_AUTO_LOCAL_TTS_PRELOAD"] = original_auto_preload_disabled
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_streamed_chat_marks_initiating_client_seen(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_model = llm.model
        original_thinking = llm.thinking_enabled
        original_prompt_mode = settings.llm_prompt_mode
        app_state.messages_for_ui.clear()
        app_state.ui_message_log.clear()
        app_state.ui_message_next_id = 0
        app_state.ui_client_cursors.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            llm.model = "local/stream-model:latest"
            llm.thinking_enabled = True
            settings.llm_prompt_mode = "revibed"
            chunks = iter([
                '{"chat":"Already visible in the sending tab.","move":null,"new_mood":null}',
            ])
            with mock.patch.object(llm, "iter_chat_response_content", return_value=chunks), \
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
                response = self.client.post("/send_message_stream", json={
                    "message": "say something",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                    "client_id": "tab-a",
                }, buffered=True)
            self.assertEqual(response.status_code, 200)
            events = [
                json.loads(line)
                for line in response.get_data(as_text=True).splitlines()
                if line.strip()
            ]
            final = [event["data"] for event in events if event["type"] == "final"][-1]
            self.assertEqual(final["llm_message_metadata"]["model"], "local/stream-model:latest")
            self.assertTrue(final["llm_message_metadata"]["thinking_enabled"])

            same_tab = self.client.get("/get_updates?client_id=tab-a")
            try:
                self.assertEqual(same_tab.get_json()["messages"], [])
            finally:
                same_tab.close()

            other_tab = self.client.get("/get_updates?client_id=tab-b")
            try:
                payload = other_tab.get_json()
                self.assertEqual(payload["messages"], ["Already visible in the sending tab."])
                self.assertEqual(payload["message_records"][0]["text"], "Already visible in the sending tab.")
                self.assertEqual(payload["message_records"][0]["metadata"]["model"], "local/stream-model:latest")
                self.assertEqual(payload["message_records"][0]["metadata"]["prompt_mode"], "revibed")
                self.assertTrue(payload["message_records"][0]["metadata"]["thinking_enabled"])
            finally:
                other_tab.close()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            llm.model = original_model
            llm.thinking_enabled = original_thinking
            settings.llm_prompt_mode = original_prompt_mode
            app_state.messages_for_ui.clear()
            app_state.ui_message_log.clear()
            app_state.ui_message_next_id = 0
            app_state.ui_client_cursors.clear()
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
        original_settings = (
            settings.handy_key,
            settings.autospeak_enabled,
        )
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.autospeak_enabled = False
            error_text = "LLM Connection Error: HTTPConnectionPool read timed out"
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": error_text,
                "move": None,
                "new_mood": None,
            }), mock.patch.object(llm, "repair_motion_response") as repair_motion_response, \
                    mock.patch.object(audio, "enqueue_text_for_audio") as generate_audio:
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
            (
                settings.handy_key,
                settings.autospeak_enabled,
            ) = original_settings
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_send_message_model_error_reschedules_enabled_autospeak(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings = (
            settings.handy_key,
            settings.autospeak_enabled,
            settings.autospeak_min_seconds,
            settings.autospeak_max_seconds,
        )
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.autospeak_enabled = True
            settings.autospeak_min_seconds = 3
            settings.autospeak_max_seconds = 30
            error_text = "LLM Connection Error: HTTPConnectionPool read timed out"
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": error_text,
                "move": None,
                "new_mood": None,
            }), mock.patch.object(audio, "enqueue_text_for_audio") as enqueue_audio, \
                    mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=True) as schedule_autospeak:
                response = self.client.post("/send_message", json={
                    "message": "say something",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "model_error")
            self.assertTrue(data["autospeak_scheduled"])
            schedule_autospeak.assert_called_once_with(3.0)
            enqueue_audio.assert_not_called()
        finally:
            handy.handy_key = original_key
            (
                settings.handy_key,
                settings.autospeak_enabled,
                settings.autospeak_min_seconds,
                settings.autospeak_max_seconds,
            ) = original_settings
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
        original_pattern_enabled = dict(settings.motion_pattern_enabled)
        original_pattern_feedback = dict(settings.motion_pattern_feedback)
        original_pattern_weights = dict(settings.motion_pattern_weights)
        original_pattern_library_chat = settings.motion_pattern_library_enabled_in_chat
        captured_targets = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            settings.motion_pattern_enabled["flick"] = True
            settings.motion_pattern_feedback["flick"] = {"thumbs_up": 0, "neutral": 0, "thumbs_down": 0}
            settings.motion_pattern_weights["flick"] = 50
            settings.motion_pattern_library_enabled_in_chat = True
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
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
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
            settings.motion_pattern_enabled = original_pattern_enabled
            settings.motion_pattern_feedback = original_pattern_feedback
            settings.motion_pattern_weights = original_pattern_weights
            settings.motion_pattern_library_enabled_in_chat = original_pattern_library_chat
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
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
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
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
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
        from strokegpt.motion import MotionTarget

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_target = app_state.chat_motion_keepalive_target
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        app_state.mode_status_message = ""
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with app_state.lock:
                app_state.chat_motion_keepalive_target = MotionTarget(30, 50, 70, "llm+milk")

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
            self.assertIsNone(app_state.chat_motion_keepalive_target)

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
            with app_state.lock:
                app_state.chat_motion_keepalive_target = original_target
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
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
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
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
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
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
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
            }), mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
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
        from strokegpt.web import app_state, settings

        original = (
            settings.allow_llm_edge_in_freestyle,
            settings.allow_llm_edge_in_chat,
            settings.allow_llm_mode_actions_in_chat,
            settings.autospeak_enabled,
            settings.autospeak_min_seconds,
            settings.autospeak_max_seconds,
            settings.save,
            app_state.autospeak_wake_requested,
        )
        try:
            settings.save = lambda *args, **kwargs: None
            settings.autospeak_enabled = False
            app_state.autospeak_wake_requested = False
            app_state.mode_message_event.clear()
            with mock.patch("strokegpt.web._schedule_standalone_autospeak", return_value=True) as schedule_autospeak:
                response = self.client.post("/set_llm_edge_permissions", json={
                    "allow_llm_edge_in_freestyle": False,
                    "allow_llm_edge_in_chat": False,
                    "allow_llm_mode_actions_in_chat": True,
                    "autospeak_enabled": True,
                    "autospeak_min_seconds": 4,
                    "autospeak_max_seconds": 9,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertFalse(settings.allow_llm_edge_in_freestyle)
            self.assertFalse(settings.allow_llm_edge_in_chat)
            self.assertTrue(settings.allow_llm_mode_actions_in_chat)
            self.assertTrue(settings.autospeak_enabled)
            self.assertEqual(settings.autospeak_min_seconds, 4.0)
            self.assertEqual(settings.autospeak_max_seconds, 9.0)
            self.assertFalse(data["allow_llm_edge_in_freestyle"])
            self.assertFalse(data["allow_llm_edge_in_chat"])
            self.assertTrue(data["allow_llm_mode_actions_in_chat"])
            self.assertTrue(data["autospeak_enabled"])
            self.assertEqual(data["autospeak_min_seconds"], 4.0)
            self.assertEqual(data["autospeak_max_seconds"], 9.0)
            schedule_autospeak.assert_called_once_with(0)
            self.assertFalse(app_state.autospeak_wake_requested)
            self.assertFalse(app_state.mode_message_event.is_set())
        finally:
            (
                settings.allow_llm_edge_in_freestyle,
                settings.allow_llm_edge_in_chat,
                settings.allow_llm_mode_actions_in_chat,
                settings.autospeak_enabled,
                settings.autospeak_min_seconds,
                settings.autospeak_max_seconds,
                settings.save,
                app_state.autospeak_wake_requested,
            ) = original
            app_state.mode_message_event.clear()

    def test_memory_toggle_route_updates_runtime_state(self):
        import strokegpt.web as web

        original_runtime = web.app_state.use_long_term_memory
        original_setting = web.settings.use_long_term_memory
        try:
            web.app_state.use_long_term_memory = True
            web.settings.use_long_term_memory = True

            response = self.client.get("/check_settings")
            self.assertTrue(response.get_json()["use_long_term_memory"])

            with mock.patch.object(web.settings, "save") as save:
                response = self.client.post("/toggle_memory")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertFalse(data["use_long_term_memory"])
            self.assertFalse(data["memory_status"]["enabled"])
            self.assertTrue(data["memory_status"]["persistent"])
            self.assertFalse(web.app_state.use_long_term_memory)
            self.assertFalse(web.settings.use_long_term_memory)
            save.assert_called_once()

            with mock.patch.object(web.settings, "save") as save:
                response = self.client.post("/toggle_memory", json={"enabled": True})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data["use_long_term_memory"])
            self.assertTrue(data["memory_status"]["enabled"])
            self.assertTrue(web.app_state.use_long_term_memory)
            self.assertTrue(web.settings.use_long_term_memory)
            save.assert_called_once()
        finally:
            web.app_state.use_long_term_memory = original_runtime
            web.settings.use_long_term_memory = original_setting

    def test_clear_memory_route_resets_saved_profile_and_current_chat_context(self):
        import strokegpt.web as web
        from strokegpt.settings import default_user_profile

        original_profile = web.settings.user_profile
        original_runtime = web.app_state.use_long_term_memory
        original_setting = web.settings.use_long_term_memory
        original_history = list(web.app_state.chat_history)
        try:
            web.settings.user_profile = {
                "name": "Tester",
                "likes": ["smooth motion"],
                "dislikes": [],
                "key_memories": ["prefers quiet narration"],
            }
            web.settings.use_long_term_memory = True
            web.app_state.use_long_term_memory = True
            web.app_state.chat_history.clear()
            web.app_state.chat_history.append({"role": "user", "content": "remember this"})

            with mock.patch.object(web.settings, "save") as save:
                response = self.client.post("/clear_memory")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["chat_history_cleared"])
            self.assertTrue(data["use_long_term_memory"])
            self.assertFalse(data["memory_status"]["has_memory"])
            self.assertEqual(web.settings.user_profile, default_user_profile())
            self.assertEqual(list(web.app_state.chat_history), [])
            save.assert_called_once()
        finally:
            web.settings.user_profile = original_profile
            web.settings.use_long_term_memory = original_setting
            web.app_state.use_long_term_memory = original_runtime
            web.app_state.chat_history.clear()
            web.app_state.chat_history.extend(original_history)

    def test_delete_memory_item_route_removes_one_saved_list_item(self):
        import strokegpt.web as web

        original_profile = web.settings.user_profile
        original_runtime = web.app_state.use_long_term_memory
        original_history = list(web.app_state.chat_history)
        try:
            web.settings.user_profile = {
                "name": "Tester",
                "likes": ["smooth motion", "fast motion"],
                "dislikes": [],
                "key_memories": ["prefers quiet narration"],
            }
            web.app_state.use_long_term_memory = True
            web.app_state.chat_history.clear()
            web.app_state.chat_history.append({"role": "user", "content": "likes smooth motion"})

            with mock.patch.object(web.settings, "save") as save:
                response = self.client.post("/delete_memory_item", json={
                    "field": "likes",
                    "index": 0,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["chat_history_cleared"])
            self.assertEqual(data["removed"]["text"], "smooth motion")
            self.assertEqual(web.settings.user_profile["likes"], ["fast motion"])
            self.assertEqual(list(web.app_state.chat_history), [])
            self.assertEqual(data["memory_status"]["counts"]["likes"], 1)
            self.assertTrue(any(
                item["field"] == "likes" and item["text"] == "fast motion"
                for item in data["memory_status"]["items"]
            ))
            save.assert_called_once()
        finally:
            web.settings.user_profile = original_profile
            web.app_state.use_long_term_memory = original_runtime
            web.app_state.chat_history.clear()
            web.app_state.chat_history.extend(original_history)

    def test_delete_memory_item_route_resets_saved_name(self):
        import strokegpt.web as web

        original_profile = web.settings.user_profile
        try:
            web.settings.user_profile = {
                "name": "Tester",
                "likes": [],
                "dislikes": [],
                "key_memories": [],
            }

            with mock.patch.object(web.settings, "save") as save:
                response = self.client.post("/delete_memory_item", json={
                    "field": "name",
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["removed"]["text"], "Tester")
            self.assertEqual(web.settings.user_profile["name"], "Unknown")
            self.assertFalse(data["memory_status"]["has_memory"])
            save.assert_called_once()
        finally:
            web.settings.user_profile = original_profile

    def test_delete_memory_item_route_rejects_missing_items(self):
        import strokegpt.web as web

        original_profile = web.settings.user_profile
        try:
            web.settings.user_profile = {
                "name": "Unknown",
                "likes": ["smooth motion"],
                "dislikes": [],
                "key_memories": [],
            }

            response = self.client.post("/delete_memory_item", json={
                "field": "likes",
                "index": 4,
            })

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.get_json()["status"], "error")
            self.assertEqual(web.settings.user_profile["likes"], ["smooth motion"])
        finally:
            web.settings.user_profile = original_profile

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

    def test_replaced_background_mode_cannot_clear_newer_active_mode(self):
        import strokegpt.web as web
        from strokegpt.web import app_state

        original_task = app_state.auto_mode_active_task
        created = []

        class FakeModeTask:
            def __init__(self, _mode_logic, initial_message, _services, callbacks, mode_name="auto", **_kwargs):
                self.initial_message = initial_message
                self._callbacks = callbacks
                self.name = mode_name
                self.stopped = False
                self.join_timeouts = []
                created.append(self)

            def start(self):
                pass

            def stop(self):
                self.stopped = True

            def join(self, timeout=None):
                self.join_timeouts.append(timeout)

        try:
            app_state.auto_mode_active_task = None
            with mock.patch.object(web, "AutoModeThread", FakeModeTask):
                web.start_background_mode(lambda *_args: None, "First.", mode_name="freestyle")
                first = created[-1]
                web.start_background_mode(lambda *_args: None, "Second.", mode_name="milking")
                second = created[-1]

            self.assertTrue(first.stopped)
            self.assertEqual(first.join_timeouts, [5])
            self.assertIs(app_state.auto_mode_active_task, second)
            self.assertFalse(first._callbacks["should_finalize_on_exit"]())
            first._callbacks["on_stop"]()
            self.assertIs(app_state.auto_mode_active_task, second)

            self.assertTrue(second._callbacks["should_finalize_on_exit"]())
            second._callbacks["on_stop"]()
            self.assertIsNone(app_state.auto_mode_active_task)
        finally:
            app_state.auto_mode_active_task = original_task
            app_state.mode_message_queue.clear()
            app_state.mode_message_event.clear()

    def test_autospeak_enabled_mode_decision_chat_queues_visible_spoken_chat(self):
        import strokegpt.web as web
        from strokegpt import background_modes
        from strokegpt.mode_decisions import ModeDecision
        from strokegpt.web import app_state, audio, settings

        original_task = app_state.auto_mode_active_task
        original_autospeak = settings.autospeak_enabled
        spoken = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        app_state.mode_status_message = ""
        try:
            settings.autospeak_enabled = True

            def mode_logic(stop_event, _services, callbacks):
                background_modes._send_background_decision_message(
                    callbacks,
                    callbacks["send_message"],
                    ModeDecision(chat="Stay with me.", autospeak_seconds=7, source="llm"),
                )
                stop_event.set()

            with mock.patch.object(web.motion, "stop", return_value=None), \
                    mock.patch.object(audio, "enqueue_text_for_audio", side_effect=lambda text: spoken.append(text)):
                web.start_background_mode(
                    mode_logic,
                    "Starting adaptive Freestyle.",
                    mode_name="freestyle",
                )
                task = app_state.auto_mode_active_task
                self.assertIsNotNone(task)
                task.join(timeout=1)
                self.assertFalse(task.is_alive())

            deadline = time.time() + 1.0
            while not spoken and time.time() < deadline:
                time.sleep(0.01)

            self.assertEqual(list(app_state.messages_for_ui), ["Stay with me."])
            self.assertIn({"role": "assistant", "content": "Stay with me."}, list(app_state.chat_history))
            self.assertEqual(spoken, ["Stay with me."])

            response = self.client.get("/get_updates")
            try:
                payload = response.get_json()
            finally:
                response.close()
            self.assertEqual(payload["messages"], ["Stay with me."])
            self.assertNotEqual(payload["mode_status_message"], "Stay with me.")
        finally:
            app_state.auto_mode_active_task = original_task
            settings.autospeak_enabled = original_autospeak
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

    def test_same_fixed_pattern_target_without_meaningful_delta_is_noop(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import _target_has_motion_effect

        current = MotionTarget(26, 50, 90, "llm+milk continuous")
        target = MotionTarget(26, 56, 95, "llm+milk")

        self.assertFalse(_target_has_motion_effect(current, target))

    def test_same_fixed_pattern_target_with_meaningful_delta_applies(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import _target_has_motion_effect

        current = MotionTarget(26, 50, 90, "llm+milk continuous")
        target = MotionTarget(28, 50, 90, "llm+milk")
        deeper = MotionTarget(26, 59, 90, "llm+milk")
        wider = MotionTarget(26, 50, 99, "llm+milk")
        speed_flutter = MotionTarget(28, 50, 82, "llm+milk")

        self.assertTrue(_target_has_motion_effect(current, target))
        self.assertTrue(_target_has_motion_effect(current, deeper))
        self.assertTrue(_target_has_motion_effect(current, wider))
        self.assertTrue(_target_has_motion_effect(MotionTarget(34, 50, 82, "llm+milk"), speed_flutter))

    def test_different_fixed_pattern_target_applies(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import _target_has_motion_effect

        current = MotionTarget(26, 50, 90, "llm+milk continuous")
        target = MotionTarget(26, 50, 90, "llm+wave")

        self.assertTrue(_target_has_motion_effect(current, target))

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

    def test_normal_chat_starts_session_timer_before_llm_context(self):
        from strokegpt.web import app_state, audio, handy, llm, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_state = (
            app_state.chat_session_started_at,
            app_state.chat_last_activity_at,
            app_state.chat_intensity_guide,
            app_state.chat_intensity_guide_started_at,
        )
        captured_contexts = []
        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            app_state.chat_session_started_at = None
            app_state.chat_last_activity_at = None
            app_state.chat_intensity_guide = "ramp_up"
            app_state.chat_intensity_guide_started_at = None

            def fake_chat_response(_history, context):
                captured_contexts.append(dict(context))
                return {"chat": "Timer noted.", "move": None, "new_mood": None}

            with mock.patch.object(llm, "get_chat_response", side_effect=fake_chat_response), \
                    mock.patch.object(audio, "enqueue_text_for_audio", return_value=True):
                response = self.client.post("/send_message", json={
                    "message": "start",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            self.assertTrue(captured_contexts)
            context = captured_contexts[-1]
            self.assertEqual(context["arc"], "ramp_up")
            self.assertEqual(context["chat_arc"], "ramp_up")
            self.assertEqual(context["chat_intensity_guide"], "ramp_up")
            self.assertEqual(context["chat_intensity_count_direction"], "up")
            self.assertIsNotNone(context["chat_elapsed_seconds"])
            self.assertIsNotNone(context["chat_elapsed_time"])
            self.assertEqual(context["chat_intensity_target_seconds"], 600)
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            (
                app_state.chat_session_started_at,
                app_state.chat_last_activity_at,
                app_state.chat_intensity_guide,
                app_state.chat_intensity_guide_started_at,
            ) = original_state
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()


if __name__ == "__main__":
    unittest.main()
