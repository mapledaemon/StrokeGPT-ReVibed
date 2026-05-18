import time
import threading
import unittest
from unittest import mock

from tests._web_support import WebTestCase


class WebStatusRouteTests(WebTestCase):
    def test_updates_and_audio_are_separate_browser_endpoints(self):
        from strokegpt.web import app_state, audio

        app_state.messages_for_ui.clear()
        app_state.chat_audio_warning = ""
        audio.clear_audio_queue()
        app_state.messages_for_ui.append("hello")
        audio._enqueue_audio_chunk(b"RIFFtest", "audio/wav")

        updates = self.client.get("/get_updates")
        try:
            self.assertEqual(updates.status_code, 200)
            self.assertEqual(updates.get_json()["messages"], ["hello"])
            self.assertTrue(updates.get_json()["audio_ready"])
        finally:
            updates.close()

        audio_response = self.client.get("/get_audio")
        try:
            self.assertEqual(audio_response.status_code, 200)
            self.assertEqual(audio_response.mimetype, "audio/wav")
            self.assertEqual(audio_response.data, b"RIFFtest")
        finally:
            audio_response.close()

    def test_get_audio_waits_until_pending_chat_has_been_polled(self):
        from strokegpt.web import app_state, audio

        app_state.messages_for_ui.clear()
        audio.clear_audio_queue()
        try:
            app_state.messages_for_ui.append("visible before voice")
            audio._enqueue_audio_chunk(b"RIFFheld", "audio/wav")

            audio_response = self.client.get("/get_audio")
            try:
                self.assertEqual(audio_response.status_code, 204)
                self.assertTrue(audio.has_audio())
            finally:
                audio_response.close()

            updates = self.client.get("/get_updates")
            try:
                self.assertEqual(updates.status_code, 200)
                self.assertEqual(updates.get_json()["messages"], ["visible before voice"])
            finally:
                updates.close()

            audio_response = self.client.get("/get_audio")
            try:
                self.assertEqual(audio_response.status_code, 200)
                self.assertEqual(audio_response.mimetype, "audio/wav")
                self.assertEqual(audio_response.data, b"RIFFheld")
            finally:
                audio_response.close()
        finally:
            app_state.messages_for_ui.clear()
            audio.clear_audio_queue()

    def test_updates_are_cursor_based_per_browser_client(self):
        from strokegpt.web import add_message_to_queue, app_state

        app_state.messages_for_ui.clear()
        app_state.ui_message_log.clear()
        app_state.ui_message_next_id = 0
        app_state.ui_client_cursors.clear()
        try:
            add_message_to_queue(
                "seen by every active browser",
                add_to_history=False,
                generate_audio=False,
            )

            first_tab = self.client.get("/get_updates?client_id=tab-a")
            try:
                self.assertEqual(first_tab.status_code, 200)
                self.assertEqual(first_tab.get_json()["messages"], ["seen by every active browser"])
            finally:
                first_tab.close()

            second_tab = self.client.get("/get_updates?client_id=tab-b")
            try:
                self.assertEqual(second_tab.status_code, 200)
                self.assertEqual(second_tab.get_json()["messages"], ["seen by every active browser"])
            finally:
                second_tab.close()

            first_tab_again = self.client.get("/get_updates?client_id=tab-a")
            try:
                self.assertEqual(first_tab_again.status_code, 200)
                self.assertEqual(first_tab_again.get_json()["messages"], [])
            finally:
                first_tab_again.close()

            self.assertEqual(list(app_state.messages_for_ui), [])
        finally:
            app_state.messages_for_ui.clear()
            app_state.ui_message_log.clear()
            app_state.ui_message_next_id = 0
            app_state.ui_client_cursors.clear()

    def test_get_audio_waits_for_that_browser_client_to_poll_chat(self):
        from strokegpt.web import add_message_to_queue, app_state, audio

        app_state.messages_for_ui.clear()
        app_state.ui_message_log.clear()
        app_state.ui_message_next_id = 0
        app_state.ui_client_cursors.clear()
        audio.clear_audio_queue()
        try:
            add_message_to_queue(
                "visible before client voice",
                add_to_history=False,
                generate_audio=False,
            )
            audio._enqueue_audio_chunk(b"RIFFclient", "audio/wav")

            audio_response = self.client.get("/get_audio?client_id=tab-a")
            try:
                self.assertEqual(audio_response.status_code, 204)
                self.assertTrue(audio.has_audio())
            finally:
                audio_response.close()

            updates = self.client.get("/get_updates?client_id=tab-a")
            try:
                self.assertEqual(updates.status_code, 200)
                self.assertEqual(updates.get_json()["messages"], ["visible before client voice"])
            finally:
                updates.close()

            audio_response = self.client.get("/get_audio?client_id=tab-a")
            try:
                self.assertEqual(audio_response.status_code, 200)
                self.assertEqual(audio_response.mimetype, "audio/wav")
                self.assertEqual(audio_response.data, b"RIFFclient")
            finally:
                audio_response.close()
        finally:
            app_state.messages_for_ui.clear()
            app_state.ui_message_log.clear()
            app_state.ui_message_next_id = 0
            app_state.ui_client_cursors.clear()
            audio.clear_audio_queue()

    def test_get_audio_can_briefly_wait_for_generated_audio(self):
        from strokegpt.web import audio

        audio.clear_audio_queue()

        def enqueue_later():
            time.sleep(0.02)
            audio._enqueue_audio_chunk(b"RIFFwait", "audio/wav")

        thread = threading.Thread(target=enqueue_later)
        thread.start()
        try:
            response = self.client.get("/get_audio?wait_ms=500")
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "audio/wav")
                self.assertEqual(response.data, b"RIFFwait")
            finally:
                response.close()
        finally:
            thread.join(timeout=1)

    def test_updates_surface_and_consume_chat_audio_warning(self):
        from strokegpt.web import add_message_to_queue, app_state, audio

        app_state.messages_for_ui.clear()
        app_state.chat_audio_warning = ""
        try:
            with mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                add_message_to_queue(
                    "hidden spoken reply",
                    add_to_history=False,
                    queue_message=False,
                    generate_audio=True,
                )

            response = self.client.get("/get_updates")
            try:
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
            finally:
                response.close()

            self.assertIn("without a matching chat message", payload["chat_audio_warning"])

            response = self.client.get("/get_updates")
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["chat_audio_warning"], "")
            finally:
                response.close()
        finally:
            app_state.messages_for_ui.clear()
            app_state.chat_audio_warning = ""

    def test_updates_surface_and_consume_mode_status_message(self):
        from strokegpt.web import add_mode_status_message, app_state

        app_state.messages_for_ui.clear()
        app_state.mode_status_message = ""
        try:
            add_mode_status_message("<b>Adding slower pressure in Freestyle.</b>")

            response = self.client.get("/get_updates")
            try:
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
            finally:
                response.close()

            self.assertEqual(payload["messages"], [])
            self.assertEqual(payload["mode_status_message"], "Adding slower pressure in Freestyle.")

            response = self.client.get("/get_updates")
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["mode_status_message"], "")
            finally:
                response.close()
        finally:
            app_state.messages_for_ui.clear()
            app_state.mode_status_message = ""

    def test_status_payload_includes_motion_observability(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import handy, motion, settings

        original_state = (
            handy.last_relative_speed,
            handy.last_stroke_speed,
            handy.last_depth_pos,
            handy.last_stroke_range,
            handy.min_handy_depth,
            handy.max_handy_depth,
            settings.motion_diagnostics_level,
        )
        try:
            settings.motion_diagnostics_level = "debug"
            handy.last_relative_speed = 55
            handy.last_stroke_speed = 42
            handy.last_depth_pos = 60
            handy.last_stroke_range = 70
            handy.min_handy_depth = 0
            handy.max_handy_depth = 100
            motion._record_target(MotionTarget(55, 60, 70, label="test trace"), source="unit test")

            response = self.client.get("/get_status")
            try:
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
            finally:
                response.close()

            self.assertEqual(payload["relative_speed"], 55)
            self.assertIn("active_mode_elapsed_seconds", payload)
            self.assertIn("motion_observability", payload)
            observability = payload["motion_observability"]
            self.assertEqual(payload["motion_diagnostics_level"], "debug")
            self.assertEqual(observability["diagnostics_level"], "debug")
            self.assertEqual(observability["source"], "unit test")
            self.assertIn("diagnostics", observability)
            self.assertEqual(observability["diagnostics"]["physical_speed"], 42)
            self.assertEqual(observability["diagnostics"]["physical_depth"], 60)
            self.assertTrue(observability["trace"])
            self.assertEqual(observability["trace"][-1]["label"], "test trace")
        finally:
            (
                handy.last_relative_speed,
                handy.last_stroke_speed,
                handy.last_depth_pos,
                handy.last_stroke_range,
                handy.min_handy_depth,
                handy.max_handy_depth,
                settings.motion_diagnostics_level,
            ) = original_state
            with motion._observability_lock:
                motion._trace.clear()
                motion._last_source = "idle"
                motion._last_label = "idle"
                motion._last_command_time = None

    def test_status_payload_reports_active_mode_elapsed_time(self):
        import strokegpt.web as web

        original_state = (
            web.app_state.auto_mode_active_task,
            web.app_state.active_mode_name,
            web.app_state.active_mode_started_at,
            web.app_state.edging_start_time,
        )
        try:
            web.app_state.auto_mode_active_task = None
            web.app_state.active_mode_name = "freestyle"
            web.app_state.active_mode_started_at = time.time() - 12.2
            web.app_state.edging_start_time = None

            response = self.client.get("/get_status")
            try:
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
            finally:
                response.close()

            self.assertEqual(payload["active_mode"], "freestyle")
            self.assertGreaterEqual(payload["active_mode_elapsed_seconds"], 12)
        finally:
            (
                web.app_state.auto_mode_active_task,
                web.app_state.active_mode_name,
                web.app_state.active_mode_started_at,
                web.app_state.edging_start_time,
            ) = original_state

    def test_status_payload_reports_chat_session_timer_and_intensity_guide(self):
        import strokegpt.web as web

        original_state = (
            web.app_state.chat_session_started_at,
            web.app_state.chat_last_activity_at,
            web.app_state.chat_intensity_guide,
            web.app_state.chat_intensity_guide_started_at,
        )
        try:
            now = time.time()
            web.app_state.chat_session_started_at = now - 42.4
            web.app_state.chat_last_activity_at = now - 5.0
            web.app_state.chat_intensity_guide = "ramp_down"
            web.app_state.chat_intensity_guide_started_at = now - 12.0

            response = self.client.get("/get_status")
            try:
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
            finally:
                response.close()

            self.assertEqual(payload["chat_intensity_guide"], "ramp_down")
            self.assertEqual(payload["arc"], "ramp_down")
            self.assertEqual(payload["chat_arc"], "ramp_down")
            self.assertEqual(payload["chat_intensity_count_direction"], "down")
            self.assertGreaterEqual(payload["chat_elapsed_seconds"], 42)
            self.assertEqual(payload["chat_intensity_target_seconds"], 600)
            self.assertLessEqual(payload["chat_intensity_count_seconds"], 588)
        finally:
            (
                web.app_state.chat_session_started_at,
                web.app_state.chat_last_activity_at,
                web.app_state.chat_intensity_guide,
                web.app_state.chat_intensity_guide_started_at,
            ) = original_state

    def test_chat_session_timer_resets_after_idle_before_next_message(self):
        import strokegpt.web as web

        original_state = (
            web.app_state.chat_session_started_at,
            web.app_state.chat_last_activity_at,
            web.app_state.chat_intensity_guide_started_at,
        )
        try:
            now = time.time()
            web.app_state.chat_session_started_at = now - 1800.0
            web.app_state.chat_last_activity_at = now - 1200.0
            web.app_state.chat_intensity_guide_started_at = now - 1700.0

            started_at = web._ensure_chat_session_started(now=now)

            self.assertEqual(started_at, now)
            self.assertEqual(web.app_state.chat_session_started_at, now)
            self.assertEqual(web.app_state.chat_last_activity_at, now)
            self.assertEqual(web.app_state.chat_intensity_guide_started_at, now)
        finally:
            (
                web.app_state.chat_session_started_at,
                web.app_state.chat_last_activity_at,
                web.app_state.chat_intensity_guide_started_at,
            ) = original_state

    def test_set_chat_intensity_guide_route_normalizes_without_starting_timer(self):
        import strokegpt.web as web

        original_state = (
            web.app_state.chat_session_started_at,
            web.app_state.chat_last_activity_at,
            web.app_state.chat_intensity_guide,
            web.app_state.chat_intensity_guide_started_at,
        )
        try:
            web.app_state.chat_session_started_at = None
            web.app_state.chat_last_activity_at = None
            web.app_state.chat_intensity_guide = "steady"
            web.app_state.chat_intensity_guide_started_at = None

            response = self.client.post("/set_chat_intensity_guide", json={"arc": "variable"})
            try:
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
            finally:
                response.close()

            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["chat_intensity_guide"], "variable")
            self.assertEqual(payload["arc"], "variable")
            self.assertEqual(payload["chat_arc"], "variable")
            self.assertEqual(payload["chat_intensity_count_direction"], "variable")
            self.assertIsNone(payload["chat_elapsed_seconds"])
            self.assertIsNone(web.app_state.chat_session_started_at)
        finally:
            (
                web.app_state.chat_session_started_at,
                web.app_state.chat_last_activity_at,
                web.app_state.chat_intensity_guide,
                web.app_state.chat_intensity_guide_started_at,
            ) = original_state

    def test_status_payload_reports_motion_pause_state_and_frozen_timer(self):
        import strokegpt.web as web

        original_state = (
            web.app_state.auto_mode_active_task,
            web.app_state.active_mode_name,
            web.app_state.active_mode_started_at,
            web.app_state.active_mode_paused_at,
            web.app_state.active_mode_paused_total,
            web.app_state.motion_pause_active,
            web.app_state.edging_start_time,
        )
        try:
            now = time.time()
            web.app_state.auto_mode_active_task = None
            web.app_state.active_mode_name = "freestyle"
            web.app_state.active_mode_started_at = now - 20
            web.app_state.active_mode_paused_at = now - 5
            web.app_state.active_mode_paused_total = 0
            web.app_state.motion_pause_active = True
            web.app_state.edging_start_time = None

            response = self.client.get("/get_status")
            try:
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
            finally:
                response.close()

            self.assertEqual(payload["active_mode"], "freestyle")
            self.assertTrue(payload["active_mode_paused"])
            self.assertTrue(payload["motion_paused"])
            self.assertGreaterEqual(payload["active_mode_elapsed_seconds"], 14)
            self.assertLessEqual(payload["active_mode_elapsed_seconds"], 16)
        finally:
            (
                web.app_state.auto_mode_active_task,
                web.app_state.active_mode_name,
                web.app_state.active_mode_started_at,
                web.app_state.active_mode_paused_at,
                web.app_state.active_mode_paused_total,
                web.app_state.motion_pause_active,
                web.app_state.edging_start_time,
            ) = original_state
            web.motion.resume()

    def test_toggle_motion_pause_route_pauses_and_resumes_active_mode(self):
        import strokegpt.web as web

        class FakeTask:
            name = "freestyle"

            def __init__(self):
                self.paused = False

            def pause(self):
                self.paused = True

            def resume(self):
                self.paused = False

        original_state = (
            web.app_state.auto_mode_active_task,
            web.app_state.active_mode_name,
            web.app_state.active_mode_started_at,
            web.app_state.active_mode_paused_at,
            web.app_state.active_mode_paused_total,
            web.app_state.motion_pause_active,
            web.app_state.edging_start_time,
        )
        task = FakeTask()
        try:
            web.app_state.auto_mode_active_task = task
            web.app_state.active_mode_name = "freestyle"
            web.app_state.active_mode_started_at = time.time() - 10
            web.app_state.active_mode_paused_at = None
            web.app_state.active_mode_paused_total = 0
            web.app_state.motion_pause_active = False
            web.app_state.edging_start_time = None

            response = self.client.post("/toggle_motion_pause", json={"action": "pause"})
            try:
                self.assertEqual(response.status_code, 200)
                paused_payload = response.get_json()
            finally:
                response.close()

            self.assertTrue(paused_payload["paused"])
            self.assertTrue(paused_payload["active_mode_paused"])
            self.assertTrue(task.paused)
            self.assertIsNotNone(web.app_state.active_mode_paused_at)

            response = self.client.post("/toggle_motion_pause", json={"action": "resume"})
            try:
                self.assertEqual(response.status_code, 200)
                resumed_payload = response.get_json()
            finally:
                response.close()

            self.assertFalse(resumed_payload["paused"])
            self.assertFalse(resumed_payload["active_mode_paused"])
            self.assertFalse(task.paused)
            self.assertIsNone(web.app_state.active_mode_paused_at)
            self.assertGreaterEqual(web.app_state.active_mode_paused_total, 0)
        finally:
            (
                web.app_state.auto_mode_active_task,
                web.app_state.active_mode_name,
                web.app_state.active_mode_started_at,
                web.app_state.active_mode_paused_at,
                web.app_state.active_mode_paused_total,
                web.app_state.motion_pause_active,
                web.app_state.edging_start_time,
            ) = original_state
            web.motion.resume()


if __name__ == "__main__":
    unittest.main()
