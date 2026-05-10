import unittest
from unittest import mock

from tests._web_support import WebTestCase


class SetupCheckRouteTests(WebTestCase):
    def test_setup_check_reports_ollama_and_voice_gpu_warnings(self):
        from strokegpt.web import audio, settings, voice_input

        original = (settings.audio_provider, settings.audio_enabled)
        fake_ollama_status = {
            "available": True,
            "current_model": "local/test-model:latest",
            "current_model_installed": True,
            "message": "Current model is installed: local/test-model:latest",
            "gpu_status": {
                "state": "cpu",
                "accelerated": False,
                "warning": "Ollama reports the selected model is running in system memory only.",
            },
        }
        fake_voice_input_setup = {
            "selected": {
                "provider": "local_faster_whisper",
                "status_code": "model_not_loaded",
                "message": "Voice input model is cached but not loaded.",
            },
            "faster_whisper_available": True,
            "ctranslate2_available": True,
            "ctranslate2_cuda_devices": 0,
            "nemo_available": False,
            "torch": {"cuda_available": False},
        }
        fake_local_tts_status = {
            "engine": "chatterbox_turbo",
            "engine_label": "Chatterbox Turbo",
            "message": "Chatterbox Turbo is available, but Torch is CPU-only.",
            "engines": [{"id": "chatterbox_turbo", "label": "Chatterbox Turbo", "available": True}],
            "cuda_available": False,
            "torch": {"device": "cpu", "device_name": ""},
        }
        try:
            settings.audio_provider = "local"
            settings.audio_enabled = True
            with mock.patch("strokegpt.web._ollama_status_payload", return_value=fake_ollama_status), \
                    mock.patch.object(voice_input, "setup_status", return_value=fake_voice_input_setup), \
                    mock.patch.object(audio, "local_status", return_value=fake_local_tts_status):
                response = self.client.get("/setup_check")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["summary"]["status"], "warning")
            sections = {section["id"]: section for section in payload["sections"]}
            self.assertIn("ollama", sections)
            self.assertIn("voice-input", sections)
            self.assertIn("voice-output", sections)

            ollama_items = {item["id"]: item for item in sections["ollama"]["items"]}
            self.assertEqual(ollama_items["ollama-gpu"]["status"], "warning")
            self.assertIn("system memory", ollama_items["ollama-gpu"]["detail"])

            input_items = {item["id"]: item for item in sections["voice-input"]["items"]}
            self.assertEqual(input_items["voice-input-ctranslate2"]["status"], "warning")
            self.assertIn("does not see CUDA", input_items["voice-input-ctranslate2"]["detail"])

            output_items = {item["id"]: item for item in sections["voice-output"]["items"]}
            self.assertEqual(output_items["voice-output-cuda"]["status"], "warning")
            self.assertIn("CPU-only", output_items["voice-output-cuda"]["detail"])
        finally:
            settings.audio_provider, settings.audio_enabled = original


if __name__ == "__main__":
    unittest.main()
