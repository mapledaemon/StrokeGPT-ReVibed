import unittest
from unittest import mock

from tests._web_support import WebTestCase


class DiagnosticsSystemStatusRouteTests(WebTestCase):
    def test_system_status_summarizes_runtime_without_secret_values(self):
        import strokegpt.web as web

        fake_ollama_status = {
            "available": True,
            "base_url": "http://localhost:11434",
            "current_model": "local/test-model:latest",
            "current_model_installed": True,
            "installed_model_names": ["local/test-model:latest"],
            "download": {"state": "idle"},
            "message": "Current model is installed: local/test-model:latest",
            "gpu_status": {
                "state": "gpu",
                "accelerated": True,
                "message": "Ollama reports GPU use for the selected model (4.0 GB VRAM).",
                "warning": "",
                "current_model_running": True,
                "current_model_size_label": "6.0 GB",
                "current_model_size_vram_label": "4.0 GB",
                "running_models": [
                    {
                        "name": "local/test-model:latest",
                        "size_vram_label": "4.0 GB",
                        "processor": "100% GPU",
                    },
                ],
            },
        }
        fake_voice_input_status = {
            "provider": "local_faster_whisper",
            "enabled": True,
            "model": "tiny.en",
            "model_loaded": True,
            "model_cached": True,
            "status_code": "ready",
            "message": "Voice input model loaded.",
        }
        fake_voice_input_setup = {
            "torch": {
                "torch_available": True,
                "torch_version": "2.8.0+cu128",
                "cuda_available": True,
                "cuda_version": "12.8",
                "device_count": 1,
                "device_name": "Test GPU",
                "device": "cuda",
            },
            "ctranslate2_available": True,
            "ctranslate2_cuda_devices": 1,
            "nemo_available": False,
        }
        fake_local_status = {
            "status": "success",
            "engine": "chatterbox-turbo",
            "message": "Local voice model ready.",
            "model_loaded": True,
            "torch": fake_voice_input_setup["torch"],
        }

        original_values = (
            web.settings.handy_key,
            web.settings.handy_api_v3_key,
            web.settings.handy_firmware_version,
            web.llm.thinking_enabled,
        )
        try:
            web.settings.handy_key = "secret-handy-key"
            web.settings.handy_api_v3_key = "secret-app-id"
            web.settings.handy_firmware_version = "fw4"
            web.llm.set_thinking_enabled(False)
            with mock.patch("strokegpt.web._ollama_status_payload", return_value=fake_ollama_status), \
                    mock.patch.object(web.voice_input, "status", return_value=fake_voice_input_status) as voice_status, \
                    mock.patch.object(web.voice_input, "setup_status", return_value=fake_voice_input_setup) as setup_status, \
                    mock.patch.object(web.audio, "local_status", return_value=fake_local_status), \
                    mock.patch("strokegpt.diagnostics._total_memory_bytes", return_value=16 * 1024 ** 3), \
                    mock.patch("strokegpt.diagnostics._nvidia_smi_status", return_value={
                        "available": True,
                        "path": "nvidia-smi",
                        "message": "nvidia-smi reports 1 NVIDIA GPU(s).",
                        "gpus": [{
                            "name": "Test GPU",
                            "driver_version": "555.12",
                            "memory_total_mb": 8192,
                            "memory_total_label": "8.0 GB",
                        }],
                    }):
                response = self.client.get("/diagnostics_system_status")
            try:
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
            finally:
                response.close()
        finally:
            (
                web.settings.handy_key,
                web.settings.handy_api_v3_key,
                web.settings.handy_firmware_version,
                web.llm.thinking_enabled,
            ) = original_values
        voice_status.assert_called_once_with()
        setup_status.assert_called_once_with()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["system"]["memory_total_label"], "16.0 GB")
        self.assertTrue(data["app"]["ollama"]["current_model_running"])
        self.assertEqual(data["app"]["ollama"]["current_model_size_vram_label"], "4.0 GB")
        self.assertFalse(data["app"]["ollama"]["thinking_enabled"])
        self.assertTrue(data["app"]["voice_input"]["torch"]["cuda_available"])
        self.assertTrue(data["app"]["voice_output"]["torch"]["cuda_available"])
        self.assertIn("local/test-model:latest", data["text"])
        self.assertIn("Ollama reports GPU use", data["text"])
        self.assertIn("Thinking enabled: no", data["text"])
        self.assertIn("Test GPU", data["text"])
        self.assertIn("Handy API v3 configured: yes", data["text"])
        self.assertNotIn("secret-handy-key", data["text"])
        self.assertNotIn("secret-app-id", data["text"])

    def test_system_status_reports_running_ollama_cpu_only_instead_of_unknown_vram(self):
        import strokegpt.web as web

        fake_ollama_status = {
            "available": True,
            "base_url": "http://localhost:11434",
            "current_model": "selected/model:latest",
            "current_model_installed": True,
            "installed_model_names": ["selected/model:latest", "running/model:latest"],
            "download": {"state": "idle"},
            "message": "Current model is installed: selected/model:latest",
            "gpu_status": {
                "state": "not_loaded",
                "accelerated": None,
                "message": "Ollama is running running/model:latest, but the selected model is not loaded yet.",
                "warning": "",
                "current_model_running": False,
                "current_model_size_label": "",
                "current_model_size_vram": 0,
                "current_model_size_vram_reported": False,
                "current_model_size_vram_label": "",
                "running_models": [
                    {
                        "name": "running/model:latest",
                        "size": 8 * 1024 ** 3,
                        "size_label": "8.0 GB",
                        "size_vram": 0,
                        "size_vram_label": "",
                        "size_vram_reported": True,
                        "processor": "",
                    },
                ],
            },
        }
        fake_voice_input_status = {
            "provider": "local_nvidia_parakeet",
            "enabled": True,
            "model": "nvidia/parakeet-tdt-0.6b-v3",
            "model_loaded": False,
            "model_cached": False,
            "status_code": "dependency_missing",
            "message": "Voice input dependency missing.",
        }
        fake_voice_input_setup = {
            "torch": {"torch_available": False, "cuda_available": False},
            "ctranslate2_available": False,
            "ctranslate2_cuda_devices": 0,
            "nemo_available": False,
            "parakeet_external_runtime": True,
        }
        fake_local_status = {
            "status": "disabled",
            "engine": "chatterbox-turbo",
            "message": "Local voice disabled.",
            "model_loaded": False,
            "torch": {"torch_available": False, "cuda_available": False},
        }

        with mock.patch("strokegpt.web._ollama_status_payload", return_value=fake_ollama_status), \
                mock.patch.object(web.voice_input, "status", return_value=fake_voice_input_status), \
                mock.patch.object(web.voice_input, "setup_status", return_value=fake_voice_input_setup), \
                mock.patch.object(web.audio, "local_status", return_value=fake_local_status), \
                mock.patch("strokegpt.diagnostics._total_memory_bytes", return_value=16 * 1024 ** 3), \
                mock.patch("strokegpt.diagnostics._nvidia_smi_status", return_value={
                    "available": True,
                    "path": "nvidia-smi",
                    "message": "nvidia-smi reports 1 NVIDIA GPU(s).",
                    "gpus": [],
                }):
            response = self.client.get("/diagnostics_system_status")
        try:
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
        finally:
            response.close()

        summary = data["app"]["ollama"]["running_gpu_summary"]
        self.assertEqual(summary["state"], "cpu")
        self.assertEqual(summary["cpu_model_count"], 1)
        self.assertEqual(summary["models"][0]["gpu_label"], "CPU/system memory")
        self.assertEqual(summary["models"][0]["size_vram_label"], "0 B")
        self.assertIn("system memory only; chat may be slow", data["text"])
        self.assertIn("running/model:latest; CPU/system memory; VRAM 0 B", data["text"])
        self.assertNotIn("unknown VRAM", data["text"])


if __name__ == "__main__":
    unittest.main()
