import io
import os
import unittest
from unittest import mock

from tests._web_support import WebTestCase


class WebVoiceInputRouteTests(WebTestCase):
    def test_check_settings_includes_voice_input_status(self):
        response = self.client.get("/check_settings")
        try:
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("voice_input_status", data)
            self.assertEqual(data["voice_input_provider"], data["voice_input_status"]["provider"])
            self.assertIn("status_code", data["voice_input_status"])
            self.assertIn("provider_options", data["voice_input_status"])
            self.assertIn("mode_options", data["voice_input_status"])
            self.assertIn("submit_options", data["voice_input_status"])
            model_cache_dir = data["voice_input_status"]["model_cache_dir"]
            self.assertTrue(model_cache_dir)
            if "STROKEGPT_ASR_CACHE_DIR" not in os.environ:
                self.assertIn("user_data", model_cache_dir)
                self.assertIn("voice_input_hf_cache", model_cache_dir)
        finally:
            response.close()

    def test_set_voice_input_saves_hands_free_auto_submit_settings(self):
        from strokegpt.web import apply_settings_to_services, settings, voice_input

        original = settings.to_dict()
        try:
            response = self.client.post("/set_voice_input", json={
                "provider": "local_asr",
                "enabled": True,
                "mode": "hands_free",
                "submit_mode": "auto_submit",
                "model": "base.en",
                "language": "en",
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(settings.voice_input_provider, "local_faster_whisper")
            self.assertTrue(settings.voice_input_enabled)
            self.assertEqual(settings.voice_input_mode, "hands_free")
            self.assertEqual(settings.voice_input_submit_mode, "auto_submit")
            self.assertFalse(settings.voice_input_preview_required)
            self.assertEqual(voice_input.provider, "local_faster_whisper")
            self.assertEqual(voice_input.mode, "hands_free")
            self.assertEqual(voice_input.submit_mode, "auto_submit")
            self.assertEqual(data["provider"], "local_faster_whisper")
        finally:
            settings.apply_dict(original)
            settings.save()
            apply_settings_to_services()

    def test_transcribe_voice_returns_transcript_without_chat_side_effects(self):
        from strokegpt.web import app_state, voice_input

        app_state.messages_for_ui.clear()
        app_state.chat_history.clear()
        try:
            with mock.patch.object(voice_input, "transcribe_file", return_value={
                "status": "success",
                "transcript": "start freestyle",
                "language": "en",
                "duration": 1.25,
                "timings": {"transcribe_ms": 25},
                "provider": "local_faster_whisper",
                "model": "tiny.en",
            }) as transcribe:
                response = self.client.post(
                    "/transcribe_voice",
                    data={"audio": (io.BytesIO(b"fake audio"), "speech.webm", "audio/webm")},
                    content_type="multipart/form-data",
                )

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["transcript"], "start freestyle")
            self.assertEqual(data["message"], "Transcript ready.")
            self.assertIn("voice_input_status", data)
            self.assertIn("status_code", data["voice_input_status"])
            transcribe.assert_called_once()
            self.assertEqual(list(app_state.messages_for_ui), [])
            self.assertEqual(list(app_state.chat_history), [])
        finally:
            app_state.messages_for_ui.clear()
            app_state.chat_history.clear()

    def test_transcribe_voice_rejects_unsupported_files(self):
        response = self.client.post(
            "/transcribe_voice",
            data={"audio": (io.BytesIO(b"fake audio"), "speech.txt", "text/plain")},
            content_type="multipart/form-data",
        )
        try:
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["status"], "error")
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
