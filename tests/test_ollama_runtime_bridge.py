import unittest
from unittest import mock

import strokegpt.web as web


class OllamaRuntimeBridgeTests(unittest.TestCase):
    def test_web_ollama_model_list_bridge_uses_runtime(self):
        sentinel = object()
        with mock.patch.object(web.ollama_runtime, "get_ollama_models_for_ui", return_value=sentinel) as runtime:
            self.assertIs(web.get_ollama_models_for_ui(), sentinel)
        runtime.assert_called_once_with(web.settings, web.llm)

    def test_web_ollama_format_bytes_bridge_uses_runtime(self):
        with mock.patch.object(web.ollama_runtime, "_format_bytes", return_value="12 B") as runtime:
            self.assertEqual(web._format_bytes(12), "12 B")
        runtime.assert_called_once_with(12)

    def test_web_ollama_pull_state_bridge_uses_runtime(self):
        sentinel = {"state": "ready"}
        with mock.patch.object(web.ollama_runtime, "_set_ollama_pull_state", return_value=sentinel) as runtime:
            self.assertIs(web._set_ollama_pull_state(state="ready"), sentinel)
        runtime.assert_called_once_with(web.app_state, state="ready")

    def test_web_ollama_pull_snapshot_bridge_uses_runtime(self):
        sentinel = {"state": "idle"}
        with mock.patch.object(web.ollama_runtime, "_ollama_pull_snapshot", return_value=sentinel) as runtime:
            self.assertIs(web._ollama_pull_snapshot(), sentinel)
        runtime.assert_called_once_with(web.app_state)

    def test_web_ollama_installed_models_bridge_uses_runtime(self):
        sentinel = [{"name": "model"}]
        with mock.patch.object(web.ollama_runtime, "_ollama_installed_models", return_value=sentinel) as runtime:
            self.assertIs(web._ollama_installed_models(), sentinel)
        runtime.assert_called_once_with(
            web.OLLAMA_BASE_URL,
            format_bytes=web._format_bytes,
            requests_module=web.requests,
        )

    def test_web_ollama_running_models_bridge_uses_runtime(self):
        sentinel = [{"name": "model"}]
        with mock.patch.object(web.ollama_runtime, "_ollama_running_models", return_value=sentinel) as runtime:
            self.assertIs(web._ollama_running_models(), sentinel)
        runtime.assert_called_once_with(
            web.OLLAMA_BASE_URL,
            format_bytes=web._format_bytes,
            requests_module=web.requests,
        )

    def test_web_ollama_load_model_bridge_uses_runtime(self):
        sentinel = {"ok": True}
        with mock.patch.object(web.ollama_runtime, "_ollama_load_model_for_status", return_value=sentinel) as runtime:
            self.assertIs(web._ollama_load_model_for_status("model"), sentinel)
        runtime.assert_called_once_with(
            web.OLLAMA_BASE_URL,
            "model",
            requests_module=web.requests,
        )

    def test_web_ollama_status_payload_bridge_uses_runtime(self):
        sentinel = {"available": True}
        with mock.patch.object(web.ollama_runtime, "_ollama_status_payload", return_value=sentinel) as runtime:
            self.assertIs(web._ollama_status_payload(live=False), sentinel)
        runtime.assert_called_once_with(
            settings=web.settings,
            llm=web.llm,
            base_url=web.OLLAMA_BASE_URL,
            live=False,
            pull_snapshot=web._ollama_pull_snapshot,
            installed_models=web._ollama_installed_models,
            running_models=web._ollama_running_models,
            load_model_for_status=web._ollama_load_model_for_status,
        )

    def test_web_ollama_run_pull_bridge_uses_runtime(self):
        with mock.patch.object(web.ollama_runtime, "_run_ollama_pull") as runtime:
            web._run_ollama_pull("model")
        runtime.assert_called_once_with(
            "model",
            base_url=web.OLLAMA_BASE_URL,
            set_pull_state=web._set_ollama_pull_state,
            format_bytes=web._format_bytes,
            requests_module=web.requests,
        )

    def test_web_ollama_start_pull_bridge_uses_runtime(self):
        sentinel = (True, "Started.")
        with mock.patch.object(web.ollama_runtime, "_start_ollama_pull", return_value=sentinel) as runtime:
            self.assertIs(web._start_ollama_pull("model"), sentinel)
        runtime.assert_called_once_with(
            "model",
            app_state=web.app_state,
            status_payload=web._ollama_status_payload,
            set_pull_state=web._set_ollama_pull_state,
            run_ollama_pull=web._run_ollama_pull,
        )


if __name__ == "__main__":
    unittest.main()
