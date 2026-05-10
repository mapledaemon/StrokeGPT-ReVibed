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
            audio_preprocessing=False,
            silence_trim=False,
            beam_size=3,
            condition_on_previous_text=True,
            vad_threshold=0.35,
            vad_min_silence_ms=650,
            vad_speech_pad_ms=250,
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
        self.assertFalse(status["audio_preprocessing"])
        self.assertFalse(status["silence_trim"])
        self.assertEqual(status["beam_size"], 3)
        self.assertTrue(status["condition_on_previous_text"])
        self.assertEqual(status["vad_threshold"], 0.35)
        self.assertEqual(status["vad_min_silence_ms"], 650)
        self.assertEqual(status["vad_speech_pad_ms"], 250)
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

    def test_transcribe_passes_recognition_tuning_to_faster_whisper(self):
        calls = []

        class FakeModel:
            def transcribe(self, audio_path, **kwargs):
                calls.append({"audio_path": audio_path, "kwargs": kwargs})
                return [types.SimpleNamespace(
                    text=" start freestyle ",
                    avg_logprob=-0.4,
                    no_speech_prob=0.05,
                )], types.SimpleNamespace(
                    language="en",
                    language_probability=0.98,
                    duration=1.2,
                )

        service = VoiceInputService()
        service.configure(
            provider="local_faster_whisper",
            enabled=True,
            model="tiny.en",
            language="en",
            beam_size=4,
            condition_on_previous_text=False,
            vad_threshold=0.42,
            vad_min_silence_ms=700,
            vad_speech_pad_ms=300,
        )
        service._model = FakeModel()
        service._model_key = ("local_faster_whisper", "tiny.en")

        with mock.patch.object(service, "dependency_available", return_value=True):
            result = service.transcribe_file(Path("speech.webm"))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["transcript"], "start freestyle")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["audio_path"], "speech.webm")
        self.assertEqual(calls[0]["kwargs"]["language"], "en")
        self.assertTrue(calls[0]["kwargs"]["vad_filter"])
        self.assertEqual(calls[0]["kwargs"]["beam_size"], 1)
        self.assertEqual(result["recognition"]["configured_beam_size"], 4)
        self.assertEqual(result["recognition"]["beam_size"], 1)
        self.assertIn("tip base shaft", calls[0]["kwargs"]["initial_prompt"])
        self.assertFalse(calls[0]["kwargs"]["condition_on_previous_text"])
        self.assertEqual(calls[0]["kwargs"]["vad_parameters"], {
            "threshold": 0.42,
            "min_silence_duration_ms": 700,
            "speech_pad_ms": 300,
        })

    def test_transcribe_forces_english_when_language_is_auto(self):
        calls = []

        class FakeModel:
            def transcribe(self, audio_path, **kwargs):
                calls.append(kwargs)
                return [types.SimpleNamespace(
                    text=" stop ",
                    avg_logprob=-0.2,
                    no_speech_prob=0.01,
                )], types.SimpleNamespace(language="en")

        service = VoiceInputService()
        service.configure(
            provider="local_faster_whisper",
            enabled=True,
            model="tiny.en",
            language="auto",
        )
        service._model = FakeModel()
        service._model_key = ("local_faster_whisper", "tiny.en")

        with mock.patch.object(service, "dependency_available", return_value=True):
            result = service.transcribe_file(Path("speech.webm"))

        self.assertEqual(result["transcript"], "stop")
        self.assertEqual(calls[0]["language"], "en")

    def test_transcribe_reruns_low_confidence_clip_with_configured_beam(self):
        calls = []

        class FakeModel:
            def transcribe(self, audio_path, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    return [types.SimpleNamespace(
                        text=" start ",
                        avg_logprob=-0.2,
                        no_speech_prob=0.72,
                    )], types.SimpleNamespace(language="en")
                return [types.SimpleNamespace(
                    text=" start freestyle ",
                    avg_logprob=-0.5,
                    no_speech_prob=0.03,
                )], types.SimpleNamespace(language="en")

        service = VoiceInputService()
        service.configure(
            provider="local_faster_whisper",
            enabled=True,
            model="tiny.en",
            language="en",
            beam_size=5,
        )
        service._model = FakeModel()
        service._model_key = ("local_faster_whisper", "tiny.en")

        with mock.patch.object(service, "dependency_available", return_value=True):
            result = service.transcribe_file(Path("speech.webm"))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["transcript"], "start freestyle")
        self.assertEqual([call["beam_size"] for call in calls], [1, 5])
        self.assertEqual(result["timings"]["asr_attempts"], 2)
        self.assertEqual(result["recognition"]["beam_size"], 5)

    def test_transcribe_rejects_transcript_after_low_confidence_rerun(self):
        calls = []

        class FakeModel:
            def transcribe(self, audio_path, **kwargs):
                calls.append(kwargs)
                return [types.SimpleNamespace(
                    text=" random wrong command ",
                    avg_logprob=-1.7,
                    no_speech_prob=0.05,
                )], types.SimpleNamespace(language="en")

        service = VoiceInputService()
        service.configure(
            provider="local_faster_whisper",
            enabled=True,
            model="tiny.en",
            language="en",
            beam_size=5,
        )
        service._model = FakeModel()
        service._model_key = ("local_faster_whisper", "tiny.en")

        with mock.patch.object(service, "dependency_available", return_value=True):
            result = service.transcribe_file(Path("speech.webm"))

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["transcript"], "")
        self.assertIn("I didn't catch that", result["message"])
        self.assertEqual([call["beam_size"] for call in calls], [1, 5])
        self.assertEqual(service.last_transcript, "")

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


class DeviceDetectionTests(unittest.TestCase):
    """Pin the auto-detection contract for ``_detect_device`` /
    ``_detect_compute_type``. Closes ROADMAP #13 ASR step 1 line for
    "auto-CUDA/device detection, compute-type selection."
    """

    def test_explicit_value_honored_case_and_whitespace_insensitive(self):
        from strokegpt import asr
        self.assertEqual(asr._detect_device("CPU"), "cpu")
        self.assertEqual(asr._detect_device("  cpu  "), "cpu")
        self.assertEqual(asr._detect_device("cuda"), "cuda")

    def test_explicit_pin_to_specific_gpu_index_passes_through(self):
        # `cuda:1` is a valid CTranslate2 device spec for users with
        # multi-GPU setups. Honor it without trying to interpret.
        from strokegpt import asr
        self.assertEqual(asr._detect_device("cuda:1"), "cuda:1")

    def test_auto_with_no_cuda_returns_cpu(self):
        from strokegpt import asr
        with mock.patch.object(asr, "_count_cuda_devices", return_value=0):
            self.assertEqual(asr._detect_device("auto"), "cpu")

    def test_auto_with_cuda_returns_cuda(self):
        from strokegpt import asr
        with mock.patch.object(asr, "_count_cuda_devices", return_value=1):
            self.assertEqual(asr._detect_device("auto"), "cuda")
        with mock.patch.object(asr, "_count_cuda_devices", return_value=4):
            self.assertEqual(asr._detect_device("auto"), "cuda")

    def test_empty_string_treated_as_auto(self):
        from strokegpt import asr
        with mock.patch.object(asr, "_count_cuda_devices", return_value=0):
            self.assertEqual(asr._detect_device(""), "cpu")
        with mock.patch.object(asr, "_count_cuda_devices", return_value=1):
            self.assertEqual(asr._detect_device(""), "cuda")

    def test_none_treated_as_auto(self):
        from strokegpt import asr
        with mock.patch.object(asr, "_count_cuda_devices", return_value=0):
            self.assertEqual(asr._detect_device(None), "cpu")


class ComputeTypeDetectionTests(unittest.TestCase):
    def test_explicit_honored_case_and_whitespace_insensitive(self):
        from strokegpt import asr
        self.assertEqual(asr._detect_compute_type("INT8_FLOAT16", "cuda"), "int8_float16")
        self.assertEqual(asr._detect_compute_type("  int8  ", "cuda"), "int8")

    def test_auto_cuda_picks_float16(self):
        from strokegpt import asr
        self.assertEqual(asr._detect_compute_type("auto", "cuda"), "float16")

    def test_auto_cuda_with_index_picks_float16(self):
        from strokegpt import asr
        self.assertEqual(asr._detect_compute_type("auto", "cuda:0"), "float16")
        self.assertEqual(asr._detect_compute_type("auto", "cuda:1"), "float16")

    def test_auto_cpu_picks_int8(self):
        from strokegpt import asr
        self.assertEqual(asr._detect_compute_type("auto", "cpu"), "int8")

    def test_auto_unknown_device_picks_int8_defensive(self):
        # If a future device string ("metal", "rocm", etc.) reaches here,
        # default to int8 rather than guessing a CUDA-specific compute_type.
        from strokegpt import asr
        self.assertEqual(asr._detect_compute_type("auto", "metal"), "int8")
        self.assertEqual(asr._detect_compute_type("auto", ""), "int8")

    def test_unset_treated_as_auto(self):
        from strokegpt import asr
        self.assertEqual(asr._detect_compute_type(None, "cpu"), "int8")
        self.assertEqual(asr._detect_compute_type("", "cuda"), "float16")


class CountCudaDevicesTests(unittest.TestCase):
    def test_returns_zero_when_ctranslate2_get_count_raises(self):
        # ctranslate2 ships as a faster-whisper transitive dep on systems
        # with the voice stack installed. Even when present, broken CUDA
        # libs can make ``get_cuda_device_count`` throw at runtime; the
        # helper must absorb that and return 0 so auto-detection falls
        # back to CPU instead of crashing the model load.
        from strokegpt import asr
        try:
            import ctranslate2
        except ImportError:
            # ctranslate2 not installed in this env; helper returns 0
            # via the same except-Exception path. Verify it.
            self.assertEqual(asr._count_cuda_devices(), 0)
            return
        with mock.patch.object(
            ctranslate2, "get_cuda_device_count", side_effect=RuntimeError("CUDA libs missing"),
        ):
            self.assertEqual(asr._count_cuda_devices(), 0)

    def test_returns_count_when_ctranslate2_reports_devices(self):
        from strokegpt import asr
        try:
            import ctranslate2
        except ImportError:
            self.skipTest("ctranslate2 not installed; integration check skipped")
        with mock.patch.object(ctranslate2, "get_cuda_device_count", return_value=2):
            self.assertEqual(asr._count_cuda_devices(), 2)


if __name__ == "__main__":
    unittest.main()
