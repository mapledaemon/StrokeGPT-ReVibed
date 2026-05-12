import unittest
from unittest import mock

from tests._web_support import WebTestCase
from strokegpt.settings import DEFAULT_OLLAMA_MODELS


class WebOllamaRouteTests(WebTestCase):
    def test_ollama_model_can_be_selected_and_saved(self):
        from strokegpt.web import llm, settings

        original_model = settings.ollama_model
        original_models = list(settings.ollama_models)
        original_llm_model = llm.model
        try:
            response = self.client.post("/set_ollama_model", json={
                "model": " custom / model : tag "
            })
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["ollama_model"], "custom/model:tag")
            self.assertEqual(llm.model, "custom/model:tag")
            self.assertIn("custom/model:tag", data["ollama_models"])
        finally:
            settings.ollama_model = original_model
            settings.ollama_models = original_models
            llm.model = original_llm_model
            settings.save()

    def test_ollama_model_option_can_be_deleted(self):
        from strokegpt.web import llm, settings

        original_model = settings.ollama_model
        original_models = list(settings.ollama_models)
        original_hidden = list(settings.ollama_model_hidden_defaults)
        original_llm_model = llm.model
        try:
            settings.ollama_models = settings._normalize_model_list(["custom/model:tag"], include_current=True)
            response = self.client.post("/delete_ollama_model", json={"model": "custom/model:tag"})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertNotIn("custom/model:tag", data["ollama_models"])
            self.assertNotIn("custom/model:tag", settings.ollama_models)
        finally:
            settings.ollama_model = original_model
            settings.ollama_models = original_models
            settings.ollama_model_hidden_defaults = original_hidden
            llm.model = original_llm_model
            settings.save()

    def test_default_ollama_model_option_delete_stays_hidden(self):
        from strokegpt.web import llm, settings

        original_model = settings.ollama_model
        original_models = list(settings.ollama_models)
        original_hidden = list(settings.ollama_model_hidden_defaults)
        original_llm_model = llm.model
        model = next(
            candidate
            for candidate in DEFAULT_OLLAMA_MODELS
            if candidate != settings.ollama_model
        )
        try:
            response = self.client.post("/delete_ollama_model", json={"model": model})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn(model, settings.ollama_model_hidden_defaults)
            self.assertNotIn(model, data["ollama_models"])
            settings.save()
            self.assertNotIn(model, settings.to_dict()["ollama_models"])
        finally:
            settings.ollama_model = original_model
            settings.ollama_models = original_models
            settings.ollama_model_hidden_defaults = original_hidden
            llm.model = original_llm_model
            settings.save()

    def test_current_ollama_model_option_delete_is_rejected(self):
        from strokegpt.web import llm, settings

        original_model = settings.ollama_model
        original_models = list(settings.ollama_models)
        original_hidden = list(settings.ollama_model_hidden_defaults)
        original_llm_model = llm.model
        try:
            response = self.client.post("/delete_ollama_model", json={"model": settings.ollama_model})

            self.assertEqual(response.status_code, 400)
            data = response.get_json()
            self.assertEqual(data["status"], "error")
            self.assertIn("Cannot delete the current", data["message"])
        finally:
            settings.ollama_model = original_model
            settings.ollama_models = original_models
            settings.ollama_model_hidden_defaults = original_hidden
            llm.model = original_llm_model
            settings.save()

    def test_ollama_status_reports_missing_current_model(self):
        fake_response = mock.Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"models": [{"name": "installed/model:tag", "size": 2048}]}

        with mock.patch("strokegpt.web.requests.get", return_value=fake_response, create=True):
            response = self.client.get("/ollama_status")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["available"])
        self.assertFalse(data["current_model_installed"])
        self.assertIn("Download Model", data["message"])
        self.assertEqual(data["installed_models"][0]["size_label"], "2.0 KB")

    def test_ollama_status_includes_known_default_model_sizes(self):
        from strokegpt.web import llm, settings

        original_model = settings.ollama_model
        original_models = list(settings.ollama_models)
        original_hidden = list(settings.ollama_model_hidden_defaults)
        original_llm_model = llm.model
        try:
            settings.ollama_model_hidden_defaults = []
            settings.ollama_models = settings._normalize_model_list([], include_current=True)
            with mock.patch("strokegpt.web._ollama_installed_models", return_value=[]), \
                    mock.patch("strokegpt.web._ollama_running_models", return_value=[]):
                response = self.client.get("/ollama_status")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            details = data["model_details"]
            self.assertEqual(details["huihui_ai/granite4.1-abliterated:3b"]["size_label"], "2.1 GB")
            self.assertEqual(details["huihui_ai/granite4.1-abliterated:8b"]["size_label"], "5.3 GB")
        finally:
            settings.ollama_model = original_model
            settings.ollama_models = original_models
            settings.ollama_model_hidden_defaults = original_hidden
            llm.model = original_llm_model
            settings.save()

    def test_ollama_status_reports_gpu_vram_for_loaded_current_model(self):
        from strokegpt.web import llm

        original_model = llm.model
        llm.model = "local/test-model:latest"
        try:
            with mock.patch("strokegpt.web._ollama_installed_models", return_value=[
                {"name": "local/test-model:latest", "size": 4096, "size_label": "4.0 KB"},
            ]), mock.patch("strokegpt.web._ollama_running_models", return_value=[
                {
                    "name": "local/test-model:latest",
                    "size": 4096,
                    "size_label": "4.0 KB",
                    "size_vram": 4096,
                    "size_vram_label": "4.0 KB",
                },
            ]):
                response = self.client.get("/ollama_status")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data["gpu_status"]["accelerated"])
            self.assertEqual(data["gpu_status"]["state"], "gpu")
            self.assertEqual(data["gpu_status"]["current_model_size_vram_label"], "4.0 KB")
            self.assertEqual(data["gpu_status"]["setup_warning"], "")
        finally:
            llm.model = original_model

    def test_ollama_status_warns_when_loaded_model_only_partially_fits_gpu(self):
        from strokegpt.web import llm, settings

        original_model = settings.ollama_model
        original_models = list(settings.ollama_models)
        original_llm_model = llm.model
        model = "local/large-model:latest"
        total_size = 8 * 1024 * 1024 * 1024
        vram_size = 5 * 1024 * 1024 * 1024
        try:
            settings.ollama_model = model
            settings.ollama_models = settings._normalize_model_list([model], include_current=True)
            llm.model = model
            with mock.patch("strokegpt.web._ollama_installed_models", return_value=[
                {"name": model, "size": total_size, "size_label": "8.0 GB"},
            ]), mock.patch("strokegpt.web._ollama_running_models", return_value=[
                {
                    "name": model,
                    "size": total_size,
                    "size_label": "8.0 GB",
                    "size_vram": vram_size,
                    "size_vram_label": "5.0 GB",
                    "size_vram_reported": True,
                },
            ]):
                response = self.client.get("/ollama_status")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["gpu_status"]["state"], "partial_gpu")
            self.assertTrue(data["gpu_status"]["accelerated"])
            self.assertIn("larger than the GPU memory", data["gpu_status"]["warning"])
            self.assertEqual(data["gpu_status"]["setup_warning"], data["gpu_status"]["warning"])
            self.assertEqual(data["model_details"][model]["size_label"], "8.0 GB")
            self.assertIn("larger than the GPU memory", data["model_details"][model]["warning"])
        finally:
            settings.ollama_model = original_model
            settings.ollama_models = original_models
            llm.model = original_llm_model
            settings.save()

    def test_ollama_status_warns_when_loaded_current_model_reports_no_vram(self):
        from strokegpt.web import llm

        original_model = llm.model
        llm.model = "local/test-model:latest"
        try:
            with mock.patch("strokegpt.web._ollama_installed_models", return_value=[
                {"name": "local/test-model:latest", "size": 4096, "size_label": "4.0 KB"},
            ]), mock.patch("strokegpt.web._ollama_running_models", return_value=[
                {
                    "name": "local/test-model:latest",
                    "size": 4096,
                    "size_label": "4.0 KB",
                    "size_vram": 0,
                    "size_vram_label": "",
                },
            ]):
                response = self.client.get("/ollama_status")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertFalse(data["gpu_status"]["accelerated"])
            self.assertEqual(data["gpu_status"]["state"], "cpu")
            self.assertIn("system memory only", data["gpu_status"]["warning"])
            self.assertEqual(data["gpu_status"]["setup_warning"], data["gpu_status"]["warning"])
        finally:
            llm.model = original_model

    def test_ollama_status_keeps_idle_current_model_as_unknown_not_cpu_warning(self):
        from strokegpt.web import llm

        original_model = llm.model
        llm.model = "local/test-model:latest"
        try:
            with mock.patch("strokegpt.web._ollama_installed_models", return_value=[
                {"name": "local/test-model:latest", "size": 4096, "size_label": "4.0 KB"},
            ]), mock.patch("strokegpt.web._ollama_running_models", return_value=[]):
                response = self.client.get("/ollama_status")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsNone(data["gpu_status"]["accelerated"])
            self.assertEqual(data["gpu_status"]["state"], "not_loaded")
            self.assertEqual(data["gpu_status"]["warning"], "")
            self.assertEqual(data["gpu_status"]["setup_warning"], "")
        finally:
            llm.model = original_model

    def test_ollama_status_does_not_warn_cpu_when_running_payload_lacks_vram_field(self):
        from strokegpt.web import llm

        original_model = llm.model
        llm.model = "local/test-model:latest"
        try:
            with mock.patch("strokegpt.web._ollama_installed_models", return_value=[
                {"name": "local/test-model:latest", "size": 4096, "size_label": "4.0 KB"},
            ]), mock.patch("strokegpt.web._ollama_running_models", return_value=[
                {"name": "local/test-model:latest", "size": 4096, "size_label": "4.0 KB"},
            ]):
                response = self.client.get("/ollama_status")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsNone(data["gpu_status"]["accelerated"])
            self.assertEqual(data["gpu_status"]["state"], "unknown")
            self.assertEqual(data["gpu_status"]["warning"], "")
            self.assertIn("did not report VRAM", data["gpu_status"]["message"])
        finally:
            llm.model = original_model

    def test_ollama_download_endpoint_selects_model_and_starts_pull(self):
        from strokegpt.web import llm, settings

        original_model = settings.ollama_model
        original_models = list(settings.ollama_models)
        original_llm_model = llm.model
        fake_status = {
            "available": True,
            "current_model": "custom/model:tag",
            "current_model_installed": False,
            "installed_models": [],
            "installed_model_names": [],
            "download": {"state": "downloading", "model": "custom/model:tag", "message": "Queued."},
            "message": "Current model is not installed: custom/model:tag. Click Download Model before chatting.",
        }
        try:
            with mock.patch("strokegpt.web._start_ollama_pull", return_value=(True, "Started.")) as start_pull, \
                    mock.patch("strokegpt.payloads.ollama_status_payload", return_value=fake_status):
                response = self.client.post("/pull_ollama_model", json={"model": " custom / model : tag "})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "started")
            self.assertEqual(data["ollama_model"], "custom/model:tag")
            self.assertEqual(llm.model, "custom/model:tag")
            self.assertIn("custom/model:tag", settings.ollama_models)
            start_pull.assert_called_once_with("custom/model:tag")
        finally:
            settings.ollama_model = original_model
            settings.ollama_models = original_models
            llm.model = original_llm_model
            settings.save()


if __name__ == "__main__":
    unittest.main()
