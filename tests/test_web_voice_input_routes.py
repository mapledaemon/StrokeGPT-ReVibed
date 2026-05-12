import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._web_support import WebTestCase


class WebVoiceInputRouteTests(WebTestCase):
    def test_check_settings_includes_voice_input_status(self):
        from strokegpt.web import apply_settings_to_services, settings

        original = settings.to_dict()
        settings.voice_input_provider = "local_faster_whisper"
        settings.voice_input_model = "tiny.en"
        settings.voice_input_enabled = False
        apply_settings_to_services()
        response = self.client.get("/check_settings")
        try:
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("voice_input_status", data)
            self.assertEqual(data["voice_input_provider"], data["voice_input_status"]["provider"])
            self.assertIn("status_code", data["voice_input_status"])
            self.assertIn("provider_options", data["voice_input_status"])
            self.assertIn("local_nvidia_parakeet", [option["id"] for option in data["voice_input_status"]["provider_options"]])
            self.assertIn("mode_options", data["voice_input_status"])
            self.assertIn("submit_options", data["voice_input_status"])
            self.assertIn("model_options", data["voice_input_status"])
            self.assertIn("base.en", [option["id"] for option in data["voice_input_status"]["model_options"]])
            self.assertIn("hands_free_sensitivity", data["voice_input_status"])
            self.assertIn("hands_free_silence_ms", data["voice_input_status"])
            self.assertIn("min_recording_ms", data["voice_input_status"])
            self.assertIn("max_recording_ms", data["voice_input_status"])
            self.assertIn("noise_suppression", data["voice_input_status"])
            self.assertIn("echo_cancellation", data["voice_input_status"])
            self.assertIn("auto_gain_control", data["voice_input_status"])
            self.assertIn("noise_floor_rms", data["voice_input_status"])
            self.assertIn("audio_preprocessing", data["voice_input_status"])
            self.assertIn("silence_trim", data["voice_input_status"])
            self.assertIn("hands_free_mode_actions", data["voice_input_status"])
            self.assertIn("voice_input_hands_free_mode_actions", data)
            self.assertIn("beam_size", data["voice_input_status"])
            self.assertIn("condition_on_previous_text", data["voice_input_status"])
            self.assertIn("vad_threshold", data["voice_input_status"])
            self.assertIn("vad_min_silence_ms", data["voice_input_status"])
            self.assertIn("vad_speech_pad_ms", data["voice_input_status"])
            self.assertIn("model_cached", data["voice_input_status"])
            self.assertIn("load_requires_download", data["voice_input_status"])
            model_cache_dir = data["voice_input_status"]["model_cache_dir"]
            self.assertTrue(model_cache_dir)
            if "STROKEGPT_ASR_CACHE_DIR" not in os.environ:
                self.assertIn("user_data", model_cache_dir)
                self.assertIn("voice_input_hf_cache", model_cache_dir)
        finally:
            response.close()
            settings.apply_dict(original)
            apply_settings_to_services()

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
                "hands_free_sensitivity": 82,
                "hands_free_silence_ms": 1200,
                "min_recording_ms": 550,
                "max_recording_ms": 9000,
                "noise_suppression": False,
                "echo_cancellation": False,
                "auto_gain_control": True,
                "noise_floor_rms": 0.0234,
                "audio_preprocessing": False,
                "silence_trim": False,
                "hands_free_mode_actions": True,
                "beam_size": 4,
                "condition_on_previous_text": True,
                "vad_threshold": 0.38,
                "vad_min_silence_ms": 650,
                "vad_speech_pad_ms": 300,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(settings.voice_input_provider, "local_faster_whisper")
            self.assertTrue(settings.voice_input_enabled)
            self.assertEqual(settings.voice_input_mode, "hands_free")
            self.assertEqual(settings.voice_input_submit_mode, "auto_submit")
            self.assertFalse(settings.voice_input_preview_required)
            self.assertEqual(settings.voice_input_hands_free_sensitivity, 82)
            self.assertEqual(settings.voice_input_hands_free_silence_ms, 1200)
            self.assertEqual(settings.voice_input_min_recording_ms, 550)
            self.assertEqual(settings.voice_input_max_recording_ms, 9000)
            self.assertFalse(settings.voice_input_noise_suppression)
            self.assertFalse(settings.voice_input_echo_cancellation)
            self.assertTrue(settings.voice_input_auto_gain_control)
            self.assertEqual(settings.voice_input_noise_floor_rms, 0.0234)
            self.assertFalse(settings.voice_input_audio_preprocessing)
            self.assertFalse(settings.voice_input_silence_trim)
            self.assertTrue(settings.voice_input_hands_free_mode_actions)
            self.assertEqual(settings.voice_input_beam_size, 4)
            self.assertTrue(settings.voice_input_condition_on_previous_text)
            self.assertEqual(settings.voice_input_vad_threshold, 0.38)
            self.assertEqual(settings.voice_input_vad_min_silence_ms, 650)
            self.assertEqual(settings.voice_input_vad_speech_pad_ms, 300)
            self.assertEqual(voice_input.provider, "local_faster_whisper")
            self.assertEqual(voice_input.mode, "hands_free")
            self.assertEqual(voice_input.submit_mode, "auto_submit")
            self.assertEqual(voice_input.hands_free_sensitivity, 82)
            self.assertEqual(voice_input.hands_free_silence_ms, 1200)
            self.assertEqual(voice_input.min_recording_ms, 550)
            self.assertEqual(voice_input.max_recording_ms, 9000)
            self.assertFalse(voice_input.noise_suppression)
            self.assertFalse(voice_input.echo_cancellation)
            self.assertTrue(voice_input.auto_gain_control)
            self.assertEqual(voice_input.noise_floor_rms, 0.0234)
            self.assertFalse(voice_input.audio_preprocessing)
            self.assertFalse(voice_input.silence_trim)
            self.assertEqual(voice_input.beam_size, 4)
            self.assertTrue(voice_input.condition_on_previous_text)
            self.assertEqual(voice_input.vad_threshold, 0.38)
            self.assertEqual(voice_input.vad_min_silence_ms, 650)
            self.assertEqual(voice_input.vad_speech_pad_ms, 300)
            self.assertEqual(data["provider"], "local_faster_whisper")
            self.assertEqual(data["hands_free_sensitivity"], 82)
            self.assertFalse(data["noise_suppression"])
            self.assertEqual(data["noise_floor_rms"], 0.0234)
            self.assertFalse(data["audio_preprocessing"])
            self.assertFalse(data["silence_trim"])
            self.assertTrue(data["hands_free_mode_actions"])
            self.assertEqual(data["beam_size"], 4)
            self.assertTrue(data["condition_on_previous_text"])
            self.assertEqual(data["vad_threshold"], 0.38)
            self.assertEqual(data["vad_min_silence_ms"], 650)
            self.assertEqual(data["vad_speech_pad_ms"], 300)
        finally:
            settings.apply_dict(original)
            settings.save()
            apply_settings_to_services()

    def test_set_voice_input_saves_nvidia_parakeet_provider(self):
        from strokegpt.web import apply_settings_to_services, settings, voice_input

        original = settings.to_dict()
        try:
            response = self.client.post("/set_voice_input", json={
                "provider": "nvidia-parakeet",
                "enabled": True,
                "model": "tiny.en",
                "language": "auto",
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(settings.voice_input_provider, "local_nvidia_parakeet")
            self.assertTrue(settings.voice_input_enabled)
            self.assertEqual(settings.voice_input_model, "nvidia/parakeet-tdt-0.6b-v3")
            self.assertEqual(voice_input.provider, "local_nvidia_parakeet")
            self.assertEqual(voice_input.model_name, "nvidia/parakeet-tdt-0.6b-v3")
            self.assertEqual(data["provider"], "local_nvidia_parakeet")
            self.assertIn("nvidia/parakeet-tdt-0.6b-v3", [option["id"] for option in data["model_options"]])
        finally:
            settings.apply_dict(original)
            settings.save()
            apply_settings_to_services()

    def test_browse_voice_input_model_path_returns_selected_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("strokegpt.blueprints.voice_input._browse_directory", return_value=temp_dir):
                response = self.client.post("/browse_voice_input_model_path")
            try:
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data["status"], "success")
                self.assertEqual(data["model_path"], str(Path(temp_dir)))
            finally:
                response.close()

    def test_browse_voice_input_model_path_allows_cancel(self):
        with mock.patch("strokegpt.blueprints.voice_input._browse_directory", return_value=""):
            response = self.client.post("/browse_voice_input_model_path")
        try:
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "cancelled")
        finally:
            response.close()

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

    def test_transcribe_voice_preserves_low_confidence_rejection(self):
        from strokegpt.web import voice_input

        with mock.patch.object(voice_input, "transcribe_file", return_value={
            "status": "rejected",
            "transcript": "",
            "message": "I didn't catch that. Try speaking closer to the microphone.",
            "language": "en",
            "timings": {"transcribe_ms": 25, "asr_attempts": 2, "asr_beam_size": 5},
            "provider": "local_faster_whisper",
            "model": "tiny.en",
        }) as transcribe:
            response = self.client.post(
                "/transcribe_voice",
                data={"audio": (io.BytesIO(b"fake audio"), "speech.webm", "audio/webm")},
                content_type="multipart/form-data",
            )

        try:
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "rejected")
            self.assertEqual(data["transcript"], "")
            self.assertIn("I didn't catch that", data["message"])
            transcribe.assert_called_once()
        finally:
            response.close()

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
