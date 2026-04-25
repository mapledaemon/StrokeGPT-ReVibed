import time
import unittest

from tests._web_support import WebTestCase


class WebStatusRouteTests(WebTestCase):
    def test_updates_and_audio_are_separate_browser_endpoints(self):
        from strokegpt.web import audio, messages_for_ui

        messages_for_ui.clear()
        audio.audio_output_queue.clear()
        messages_for_ui.append("hello")
        audio.audio_output_queue.append({"bytes": b"RIFFtest", "mimetype": "audio/wav"})

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
            web.auto_mode_active_task,
            web.active_mode_name,
            web.active_mode_started_at,
            web.edging_start_time,
        )
        try:
            web.auto_mode_active_task = None
            web.active_mode_name = "freestyle"
            web.active_mode_started_at = time.time() - 12.2
            web.edging_start_time = None

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
                web.auto_mode_active_task,
                web.active_mode_name,
                web.active_mode_started_at,
                web.edging_start_time,
            ) = original_state

    def test_status_payload_reports_motion_pause_state_and_frozen_timer(self):
        import strokegpt.web as web

        original_state = (
            web.auto_mode_active_task,
            web.active_mode_name,
            web.active_mode_started_at,
            web.active_mode_paused_at,
            web.active_mode_paused_total,
            web.motion_pause_active,
            web.edging_start_time,
        )
        try:
            now = time.time()
            web.auto_mode_active_task = None
            web.active_mode_name = "freestyle"
            web.active_mode_started_at = now - 20
            web.active_mode_paused_at = now - 5
            web.active_mode_paused_total = 0
            web.motion_pause_active = True
            web.edging_start_time = None

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
                web.auto_mode_active_task,
                web.active_mode_name,
                web.active_mode_started_at,
                web.active_mode_paused_at,
                web.active_mode_paused_total,
                web.motion_pause_active,
                web.edging_start_time,
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
            web.auto_mode_active_task,
            web.active_mode_name,
            web.active_mode_started_at,
            web.active_mode_paused_at,
            web.active_mode_paused_total,
            web.motion_pause_active,
            web.edging_start_time,
        )
        task = FakeTask()
        try:
            web.auto_mode_active_task = task
            web.active_mode_name = "freestyle"
            web.active_mode_started_at = time.time() - 10
            web.active_mode_paused_at = None
            web.active_mode_paused_total = 0
            web.motion_pause_active = False
            web.edging_start_time = None

            response = self.client.post("/toggle_motion_pause", json={"action": "pause"})
            try:
                self.assertEqual(response.status_code, 200)
                paused_payload = response.get_json()
            finally:
                response.close()

            self.assertTrue(paused_payload["paused"])
            self.assertTrue(paused_payload["active_mode_paused"])
            self.assertTrue(task.paused)
            self.assertIsNotNone(web.active_mode_paused_at)

            response = self.client.post("/toggle_motion_pause", json={"action": "resume"})
            try:
                self.assertEqual(response.status_code, 200)
                resumed_payload = response.get_json()
            finally:
                response.close()

            self.assertFalse(resumed_payload["paused"])
            self.assertFalse(resumed_payload["active_mode_paused"])
            self.assertFalse(task.paused)
            self.assertIsNone(web.active_mode_paused_at)
            self.assertGreaterEqual(web.active_mode_paused_total, 0)
        finally:
            (
                web.auto_mode_active_task,
                web.active_mode_name,
                web.active_mode_started_at,
                web.active_mode_paused_at,
                web.active_mode_paused_total,
                web.motion_pause_active,
                web.edging_start_time,
            ) = original_state
            web.motion.resume()


if __name__ == "__main__":
    unittest.main()
