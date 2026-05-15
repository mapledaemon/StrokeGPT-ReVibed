import unittest
from unittest import mock

from tests._web_support import WebTestCase


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return dict(self._payload)


class DiagnosticsLatencyRouteTests(WebTestCase):
    def test_diagnostics_latency_measures_ready_runtime_paths(self):
        from strokegpt.web import audio, voice_input

        fake_ollama_status = {
            "available": True,
            "current_model": "local/test-model:latest",
            "current_model_installed": True,
            "message": "Current model is installed: local/test-model:latest",
        }
        fake_voice_status = {
            "can_transcribe": True,
            "provider": "local_faster_whisper",
            "model": "tiny.en",
            "message": "Voice input model loaded.",
        }
        fake_voice_result = {
            "status": "no_speech",
            "provider": "local_faster_whisper",
            "model": "tiny.en",
            "timings": {"transcribe_ms": 123, "asr_attempts": 1},
        }
        fake_output_result = {
            "status": "ok",
            "provider": "local",
            "engine": "chatterbox_turbo",
            "device": "cuda",
            "elapsed_ms": 234,
            "audio_bytes": 4567,
            "message": "Generated a diagnostic local voice sample without queueing playback.",
        }

        with mock.patch("strokegpt.web._ollama_status_payload", return_value=fake_ollama_status), \
                mock.patch("strokegpt.diagnostics.requests.get", return_value=_FakeResponse({"version": "0.9.9"}), create=True), \
                mock.patch("strokegpt.diagnostics.requests.post", return_value=_FakeResponse({
                    "total_duration": 520_000_000,
                    "load_duration": 10_000_000,
                    "eval_duration": 300_000_000,
                    "eval_count": 7,
                }), create=True) as ollama_post, \
                mock.patch("strokegpt.diagnostics._diagnostic_voice_input_clip_path", return_value="diagnostic.wav"), \
                mock.patch.object(voice_input, "status", return_value=fake_voice_status), \
                mock.patch.object(voice_input, "transcribe_file", return_value=fake_voice_result), \
                mock.patch.object(audio, "measure_output_latency", return_value=fake_output_result):
            response = self.client.post("/diagnostics_latency")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["summary"]["status"], "ok")
        tests = {item["id"]: item for item in payload["tests"]}
        self.assertEqual(tests["ollama-ping"]["status"], "ok")
        self.assertEqual(tests["ollama-generation"]["metrics"]["ollama_total_ms"], 520)
        self.assertEqual(tests["voice-input"]["metrics"]["transcribe_ms"], 123)
        self.assertEqual(tests["voice-output"]["elapsed_ms"], 234)

        args, kwargs = ollama_post.call_args
        self.assertIn("/api/chat", args[0])
        self.assertFalse(kwargs["json"]["stream"])
        self.assertIn("think", kwargs["json"])

    def test_diagnostics_latency_skips_unloaded_voice_models(self):
        from strokegpt.web import audio, voice_input

        with mock.patch("strokegpt.web._ollama_status_payload", return_value={"available": False}), \
                mock.patch("strokegpt.diagnostics.requests.get", side_effect=RuntimeError("offline"), create=True), \
                mock.patch.object(voice_input, "status", return_value={
                    "can_transcribe": False,
                    "message": "Voice input model is not loaded.",
                }), \
                mock.patch.object(voice_input, "transcribe_file") as transcribe_file, \
                mock.patch.object(audio, "measure_output_latency", return_value={
                    "status": "skipped",
                    "provider": "local",
                    "message": "Local voice model is not loaded.",
                }):
            response = self.client.post("/diagnostics_latency")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["summary"]["status"], "error")
        tests = {item["id"]: item for item in payload["tests"]}
        self.assertEqual(tests["voice-input"]["status"], "skipped")
        self.assertEqual(tests["voice-output"]["status"], "skipped")
        transcribe_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
