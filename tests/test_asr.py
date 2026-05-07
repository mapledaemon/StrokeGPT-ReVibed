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


if __name__ == "__main__":
    unittest.main()
