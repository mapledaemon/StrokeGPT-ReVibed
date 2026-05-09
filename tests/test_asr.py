import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from strokegpt.asr import VoiceInputService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VoiceInputServiceTests(unittest.TestCase):
    def test_status_reports_actionable_state_codes(self):
        service = VoiceInputService()

        self.assertEqual(service.status()["status_code"], "disabled")

        service.configure(
            provider="local_faster_whisper",
            enabled=True,
            model="tiny.en",
            language="en",
            hands_free_sensitivity=88,
            hands_free_silence_ms=1250,
            min_recording_ms=500,
            max_recording_ms=10000,
            noise_suppression=False,
            echo_cancellation=False,
            auto_gain_control=True,
            noise_floor_rms=0.021,
        )
        with mock.patch.object(service, "dependency_available", return_value=False):
            status = service.status()
        self.assertEqual(status["status_code"], "dependency_missing")
        self.assertIn("Install dependencies", status["message"])
        self.assertEqual(status["hands_free_sensitivity"], 88)
        self.assertEqual(status["hands_free_silence_ms"], 1250)
        self.assertEqual(status["min_recording_ms"], 500)
        self.assertEqual(status["max_recording_ms"], 10000)
        self.assertFalse(status["noise_suppression"])
        self.assertFalse(status["echo_cancellation"])
        self.assertTrue(status["auto_gain_control"])
        self.assertEqual(status["noise_floor_rms"], 0.021)
        self.assertIn("model_options", status)
        self.assertIn("base.en", [option["id"] for option in status["model_options"]])
        self.assertIn("small.en", [option["id"] for option in status["model_options"]])
        self.assertIn("distil-large-v3", [option["id"] for option in status["model_options"]])

        with mock.patch.object(service, "dependency_available", return_value=True):
            status = service.status()
        self.assertEqual(status["status_code"], "model_not_loaded")
        self.assertFalse(status["model_cached"])
        self.assertTrue(status["load_requires_download"])
        self.assertIn("Download / Load Voice Input Model", status["message"])

        service._model = object()
        with mock.patch.object(service, "dependency_available", return_value=True):
            status = service.status()
        self.assertEqual(status["status_code"], "ready")
        self.assertTrue(status["model_cached"])
        self.assertFalse(status["load_requires_download"])
        self.assertTrue(status["can_transcribe"])

        service.last_error = "download failed"
        with mock.patch.object(service, "dependency_available", return_value=True):
            status = service.status()
        self.assertEqual(status["status_code"], "error")
        self.assertIn("download failed", status["message"])

    def test_model_load_uses_windows_safe_local_cache(self):
        calls = {}
        fake_module = types.ModuleType("faster_whisper")

        class FakeWhisperModel:
            def __init__(self, model_name, **kwargs):
                calls["model_name"] = model_name
                calls["kwargs"] = kwargs

        fake_module.WhisperModel = FakeWhisperModel
        env_keys = [
            "HF_HUB_DISABLE_SYMLINKS",
            "HF_HUB_DISABLE_SYMLINKS_WARNING",
            "HF_HUB_DISABLE_XET",
            "HF_XET_CACHE",
            "STROKEGPT_ASR_CACHE_DIR",
        ]
        original_env = {key: os.environ.get(key) for key in env_keys}
        original_module = sys.modules.get("faster_whisper")
        cache_parent = PROJECT_ROOT / "user_data" / "test_asr_cache"
        cache_parent.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="model_", dir=cache_parent)

        try:
            for key in env_keys:
                os.environ.pop(key, None)
            sys.modules["faster_whisper"] = fake_module
            service = VoiceInputService(model_cache_dir=temp_dir)
            service.configure(
                provider="local_faster_whisper",
                enabled=True,
                model="tiny.en",
                language="en",
            )

            with mock.patch.object(VoiceInputService, "dependency_available", return_value=True):
                ok, _ = service.preload_model()

            self.assertTrue(ok)
            self.assertEqual(calls["model_name"], "tiny.en")
            self.assertEqual(calls["kwargs"]["download_root"], temp_dir)
            self.assertEqual(calls["kwargs"]["device"], "cpu")
            self.assertEqual(calls["kwargs"]["compute_type"], "int8")
            self.assertEqual(os.environ["HF_HUB_DISABLE_SYMLINKS"], "1")
            self.assertEqual(os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"], "1")
            self.assertEqual(os.environ["HF_HUB_DISABLE_XET"], "1")
            self.assertEqual(os.environ["HF_XET_CACHE"], str(Path(temp_dir) / "xet"))
        finally:
            if original_module is None:
                sys.modules.pop("faster_whisper", None)
            else:
                sys.modules["faster_whisper"] = original_module
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_status_distinguishes_cached_model_files_from_uncached_download(self):
        cache_parent = PROJECT_ROOT / "user_data" / "test_asr_cache"
        cache_parent.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="cached_model_", dir=cache_parent)
        try:
            service = VoiceInputService(model_cache_dir=temp_dir)
            service.configure(
                provider="local_faster_whisper",
                enabled=True,
                model="tiny.en",
                language="en",
            )

            with mock.patch.object(service, "dependency_available", return_value=True):
                status = service.status()
            self.assertEqual(status["status_code"], "model_not_loaded")
            self.assertFalse(status["model_cached"])
            self.assertTrue(status["load_requires_download"])
            self.assertIn("not downloaded", status["message"])

            cached_model_dir = Path(temp_dir) / "faster-whisper-tiny-en" / "snapshots" / "abc123"
            with (
                mock.patch.object(service, "dependency_available", return_value=True),
                mock.patch("strokegpt.asr.os.walk", return_value=[(str(cached_model_dir), [], ["model.bin"])]),
            ):
                status = service.status()
            self.assertEqual(status["status_code"], "model_not_loaded")
            self.assertTrue(status["model_cached"])
            self.assertFalse(status["load_requires_download"])
            self.assertIn("cached but not loaded", status["message"])

            with (
                mock.patch.object(service, "dependency_available", return_value=True),
                mock.patch("strokegpt.asr.os.walk", return_value=[(str(cached_model_dir), [], ["model.bin"])]),
            ):
                with self.assertRaisesRegex(Exception, "Load the cached voice input model"):
                    service.transcribe_file(Path(temp_dir) / "speech.webm")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
