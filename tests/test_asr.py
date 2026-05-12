import os
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from strokegpt.asr import VoiceInputService, VoiceInputUnavailable, _ExternalParakeetRuntimeModel


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
        self.assertIn("local_nvidia_parakeet", [option["id"] for option in status["provider_options"]])
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

            with (
                mock.patch.object(VoiceInputService, "dependency_available", return_value=True),
                mock.patch("strokegpt.asr._count_cuda_devices", return_value=0),
            ):
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

    def test_nvidia_parakeet_status_reports_optional_dependency(self):
        service = VoiceInputService()
        service.configure(
            provider="local_nvidia_parakeet",
            enabled=True,
            model="tiny.en",
            language="auto",
        )

        with mock.patch.object(service, "dependency_available", return_value=False):
            status = service.status()

        self.assertEqual(service.model_name, "nvidia/parakeet-tdt-0.6b-v3")
        self.assertEqual(status["provider"], "local_nvidia_parakeet")
        self.assertEqual(status["status_code"], "dependency_missing")
        self.assertIn("NVIDIA Parakeet runtime", status["message"])
        self.assertIn("nvidia/parakeet-tdt-0.6b-v3", [option["id"] for option in status["model_options"]])

    def test_nvidia_parakeet_external_runtime_reports_dependency(self):
        temp_dir = tempfile.mkdtemp(prefix="parakeet_python_")
        fake_python = Path(temp_dir) / "python.exe"
        fake_python.write_text("", encoding="utf-8")
        original_python = os.environ.get("STROKEGPT_PARAKEET_PYTHON")
        try:
            os.environ["STROKEGPT_PARAKEET_PYTHON"] = str(fake_python)
            service = VoiceInputService()
            service.configure(
                provider="local_nvidia_parakeet",
                enabled=True,
                model="nvidia/parakeet-tdt-0.6b-v3",
                language="auto",
            )
            payload = {
                "ok": True,
                "nemo_available": True,
                "python": str(fake_python),
                "torch": {"cuda_available": True, "device_name": "RTX Test", "device": "cuda"},
            }
            completed = types.SimpleNamespace(
                returncode=0,
                stdout=f"log line\nSTROKEGPT_PARAKEET_RESULT {json.dumps(payload)}\n",
                stderr="",
            )

            with mock.patch("strokegpt.asr.subprocess.run", return_value=completed):
                self.assertTrue(service.dependency_available())
                setup = service.setup_status()

            self.assertTrue(setup["parakeet_external_runtime"])
            self.assertTrue(setup["nemo_available"])
            self.assertEqual(setup["torch"]["device"], "cuda")
        finally:
            if original_python is None:
                os.environ.pop("STROKEGPT_PARAKEET_PYTHON", None)
            else:
                os.environ["STROKEGPT_PARAKEET_PYTHON"] = original_python
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_nvidia_parakeet_external_runtime_preserves_failed_check_payload(self):
        temp_dir = tempfile.mkdtemp(prefix="parakeet_python_")
        fake_python = Path(temp_dir) / "python.exe"
        fake_python.write_text("", encoding="utf-8")
        original_python = os.environ.get("STROKEGPT_PARAKEET_PYTHON")
        try:
            os.environ["STROKEGPT_PARAKEET_PYTHON"] = str(fake_python)
            service = VoiceInputService()
            service.configure(
                provider="local_nvidia_parakeet",
                enabled=True,
                model="nvidia/parakeet-tdt-0.6b-v3",
                language="auto",
            )
            error = "PyTorch sees CUDA but a CUDA test kernel failed."
            payload = {
                "ok": False,
                "nemo_available": False,
                "python": str(fake_python),
                "torch": {
                    "cuda_available": True,
                    "device": "cuda",
                    "cuda_runtime_error": error,
                },
                "error": error,
            }
            completed = types.SimpleNamespace(
                returncode=1,
                stdout=f"STROKEGPT_PARAKEET_RESULT {json.dumps(payload)}\n",
                stderr="",
            )

            with mock.patch("strokegpt.asr.subprocess.run", return_value=completed):
                self.assertFalse(service.dependency_available())
                setup = service.setup_status()
                with self.assertRaisesRegex(VoiceInputUnavailable, "CUDA test kernel failed"):
                    service.preload_model()

            self.assertTrue(setup["parakeet_external_runtime"])
            self.assertEqual(setup["parakeet_external_error"], error)
            self.assertEqual(setup["torch"]["cuda_runtime_error"], error)
        finally:
            if original_python is None:
                os.environ.pop("STROKEGPT_PARAKEET_PYTHON", None)
            else:
                os.environ["STROKEGPT_PARAKEET_PYTHON"] = original_python
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_nvidia_parakeet_external_runtime_uses_repo_local_venv_without_env(self):
        temp_dir = tempfile.mkdtemp(prefix="parakeet_python_")
        fake_python = Path(temp_dir) / "python.exe"
        fake_python.write_text("", encoding="utf-8")
        original_python = os.environ.get("STROKEGPT_PARAKEET_PYTHON")
        try:
            os.environ.pop("STROKEGPT_PARAKEET_PYTHON", None)
            service = VoiceInputService()
            service.configure(
                provider="local_nvidia_parakeet",
                enabled=True,
                model="nvidia/parakeet-tdt-0.6b-v3",
                language="auto",
            )
            payload = {
                "ok": True,
                "nemo_available": True,
                "python": str(fake_python),
                "torch": {"cuda_available": True, "device": "cuda"},
            }
            completed = types.SimpleNamespace(
                returncode=0,
                stdout=f"STROKEGPT_PARAKEET_RESULT {json.dumps(payload)}\n",
                stderr="",
            )

            with (
                mock.patch("strokegpt.asr._default_parakeet_python_path", return_value=str(fake_python)),
                mock.patch("strokegpt.asr.subprocess.run", return_value=completed) as run,
            ):
                self.assertTrue(service.dependency_available())
                setup = service.setup_status()

            self.assertEqual(run.call_args.args[0][0], str(fake_python))
            self.assertTrue(setup["parakeet_external_runtime"])
            self.assertEqual(setup["parakeet_external_python"], str(fake_python))
            self.assertTrue(setup["nemo_available"])
        finally:
            if original_python is None:
                os.environ.pop("STROKEGPT_PARAKEET_PYTHON", None)
            else:
                os.environ["STROKEGPT_PARAKEET_PYTHON"] = original_python
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_nvidia_parakeet_external_runtime_preloads_and_transcribes(self):
        temp_dir = tempfile.mkdtemp(prefix="parakeet_python_")
        fake_python = Path(temp_dir) / "python.exe"
        fake_python.write_text("", encoding="utf-8")
        original_python = os.environ.get("STROKEGPT_PARAKEET_PYTHON")

        class FakeParakeetRuntime(_ExternalParakeetRuntimeModel):
            def __init__(self):
                self.python = str(fake_python)
                self.model = "nvidia/parakeet-tdt-0.6b-v3"
                self.device = "cuda"
                self.requests = []
                self.closed = False

            def request(self, payload):
                self.requests.append(dict(payload))
                return {
                    "ok": True,
                    "status": "success",
                    "transcript": f"stop now {len(self.requests)}",
                    "language": "en",
                    "timings": {"transcribe_ms": 42, "asr_attempts": 1},
                }

            def close(self):
                self.closed = True

        runtime = FakeParakeetRuntime()

        try:
            os.environ["STROKEGPT_PARAKEET_PYTHON"] = str(fake_python)
            service = VoiceInputService()
            service.configure(
                provider="local_nvidia_parakeet",
                enabled=True,
                model="nvidia/parakeet-tdt-0.6b-v3",
                language="auto",
            )

            with (
                mock.patch.object(service, "dependency_available", return_value=True),
                mock.patch.object(
                    service,
                    "_start_parakeet_worker",
                    return_value=(runtime, {"ok": True, "device": "cuda", "model_load_ms": 7}),
                ) as start_worker,
                mock.patch(
                    "strokegpt.asr._convert_audio_to_mono_wav",
                    side_effect=lambda _src, dst: Path(dst).write_bytes(b"fake wav") or Path(dst),
                ),
            ):
                ok, _ = service.preload_model()
                result = service.transcribe_file(Path("speech.wav"))
                second = service.transcribe_file(Path("speech-again.wav"))

            self.assertTrue(ok)
            self.assertEqual(start_worker.call_count, 1)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["transcript"], "stop now 1")
            self.assertEqual(second["transcript"], "stop now 2")
            self.assertEqual(runtime.requests, [
                {"action": "transcribe", "audio": "speech.parakeet.wav", "language": "auto"},
                {"action": "transcribe", "audio": "speech-again.parakeet.wav", "language": "auto"},
            ])
            self.assertEqual(result["recognition"]["runtime"], "external")
            self.assertEqual(result["timings"]["transcribe_ms"], 42)
            self.assertIn("normalization_ms", result["timings"])
            self.assertIn("worker_request_ms", result["timings"])
            self.assertIn("total_ms", result["timings"])
            service.close()
            self.assertTrue(runtime.closed)
        finally:
            if original_python is None:
                os.environ.pop("STROKEGPT_PARAKEET_PYTHON", None)
            else:
                os.environ["STROKEGPT_PARAKEET_PYTHON"] = original_python
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loaded_parakeet_worker_skips_runtime_check_on_status_and_transcribe(self):
        requests = []

        class FakeRuntime(_ExternalParakeetRuntimeModel):
            def __init__(self):
                self.process = types.SimpleNamespace(poll=lambda: None)

            def request(self, payload):
                requests.append(dict(payload))
                return {
                    "status": "success",
                    "transcript": "stop",
                    "language": "en",
                    "timings": {"transcribe_ms": 8},
                }

        service = VoiceInputService()
        service.configure(
            provider="local_nvidia_parakeet",
            enabled=True,
            model="nvidia/parakeet-tdt-0.6b-v3",
            language="auto",
        )
        service._model = FakeRuntime()
        service._model_key = ("local_nvidia_parakeet", "nvidia/parakeet-tdt-0.6b-v3")
        service._parakeet_runtime_checked_at = 0.0

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "speech.webm"
            source.write_bytes(b"fake webm")

            def fake_convert(_src, dst):
                Path(dst).write_bytes(b"fake wav")
                return Path(dst)

            with (
                mock.patch.object(service, "_run_parakeet_worker", side_effect=AssertionError("runtime check should not run")),
                mock.patch("strokegpt.asr._convert_audio_to_mono_wav", side_effect=fake_convert),
            ):
                status = service.status()
                result = service.transcribe_file(source)

        self.assertTrue(status["dependency_available"])
        self.assertTrue(status["can_transcribe"])
        self.assertEqual(result["transcript"], "stop")
        self.assertEqual(len(requests), 1)

    def test_nvidia_parakeet_model_load_uses_optional_nemo(self):
        calls = {}

        class FakeParakeetModel:
            def to(self, device):
                calls["device"] = device
                return self

            def eval(self):
                calls["eval"] = True
                return self

        class FakeASRModel:
            @staticmethod
            def from_pretrained(model_name):
                calls["model_name"] = model_name
                return FakeParakeetModel()

        fake_nemo = types.ModuleType("nemo")
        fake_collections = types.ModuleType("nemo.collections")
        fake_asr = types.ModuleType("nemo.collections.asr")
        fake_asr.models = types.SimpleNamespace(ASRModel=FakeASRModel)
        fake_nemo.collections = fake_collections
        fake_collections.asr = fake_asr

        module_names = ["nemo", "nemo.collections", "nemo.collections.asr"]
        original_modules = {name: sys.modules.get(name) for name in module_names}
        env_keys = ["HF_HOME", "HF_HUB_CACHE", "HF_XET_CACHE", "STROKEGPT_PARAKEET_DEVICE"]
        original_env = {key: os.environ.get(key) for key in env_keys}
        cache_parent = PROJECT_ROOT / "user_data" / "test_asr_cache"
        cache_parent.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="parakeet_", dir=cache_parent)

        try:
            for key in env_keys:
                os.environ.pop(key, None)
            sys.modules["nemo"] = fake_nemo
            sys.modules["nemo.collections"] = fake_collections
            sys.modules["nemo.collections.asr"] = fake_asr
            service = VoiceInputService(model_cache_dir=temp_dir)
            service.configure(
                provider="local_nvidia_parakeet",
                enabled=True,
                model="nvidia/parakeet-tdt-0.6b-v3",
                language="auto",
            )

            with (
                mock.patch.object(VoiceInputService, "dependency_available", return_value=True),
                mock.patch("strokegpt.asr._default_parakeet_python_path", return_value=""),
                mock.patch("strokegpt.asr._detect_torch_device", return_value="cuda"),
            ):
                ok, _ = service.preload_model()

            self.assertTrue(ok)
            self.assertEqual(calls["model_name"], "nvidia/parakeet-tdt-0.6b-v3")
            self.assertEqual(calls["device"], "cuda")
            self.assertTrue(calls["eval"])
            self.assertEqual(os.environ["HF_HOME"], temp_dir)
            self.assertEqual(os.environ["HF_HUB_CACHE"], str(Path(temp_dir) / "hub"))
        finally:
            for name, module in original_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_nvidia_parakeet_status_reports_external_runtime_error(self):
        service = VoiceInputService()
        service.configure(
            provider="local_nvidia_parakeet",
            enabled=True,
            model="nvidia/parakeet-tdt-0.6b-v3",
            language="auto",
        )
        service._parakeet_runtime_status = {
            "external_runtime": True,
            "nemo_available": False,
            "error": "operator torchvision::nms does not exist",
        }

        with mock.patch.object(service, "dependency_available", return_value=False):
            status = service.status()

        self.assertEqual(status["status_code"], "dependency_missing")
        self.assertIn("Runtime check failed", status["message"])
        self.assertIn("operator torchvision::nms does not exist", status["message"])

    def test_preload_model_preserves_provider_error_in_status(self):
        service = VoiceInputService()
        service.configure(
            provider="local_faster_whisper",
            enabled=True,
            model="tiny.en",
            language="en",
        )

        with (
            mock.patch.object(service, "dependency_available", return_value=True),
            mock.patch.object(
                service,
                "_load_model",
                side_effect=VoiceInputUnavailable("worker stopped: operator torchvision::nms does not exist"),
            ),
        ):
            with self.assertRaisesRegex(VoiceInputUnavailable, "operator torchvision::nms"):
                service.preload_model()
            status = service.status()

        self.assertEqual(status["status_code"], "error")
        self.assertEqual(status["preload_status"], "error")
        self.assertIn("operator torchvision::nms does not exist", status["last_error"])
        self.assertIn("operator torchvision::nms does not exist", status["message"])

    def test_nvidia_parakeet_transcribe_normalizes_nemo_output(self):
        class FakeParakeetModel:
            def transcribe(self, audio_paths):
                self.audio_paths = audio_paths
                return [types.SimpleNamespace(text=" stop now ")]

        model = FakeParakeetModel()
        service = VoiceInputService()
        service.configure(
            provider="local_nvidia_parakeet",
            enabled=True,
            model="nvidia/parakeet-tdt-0.6b-v3",
            language="auto",
        )
        service._model = model
        service._model_key = ("local_nvidia_parakeet", "nvidia/parakeet-tdt-0.6b-v3")

        with (
            mock.patch.object(service, "dependency_available", return_value=True),
            mock.patch(
                "strokegpt.asr._convert_audio_to_mono_wav",
                side_effect=lambda _src, dst: Path(dst).write_bytes(b"fake wav") or Path(dst),
            ),
        ):
            result = service.transcribe_file(Path("speech.wav"))

        self.assertEqual(model.audio_paths, ["speech.parakeet.wav"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["transcript"], "stop now")
        self.assertEqual(result["provider"], "local_nvidia_parakeet")
        self.assertEqual(result["model"], "nvidia/parakeet-tdt-0.6b-v3")

    def test_nvidia_parakeet_external_runtime_normalizes_browser_audio_to_wav(self):
        requests = []

        class FakeRuntime(_ExternalParakeetRuntimeModel):
            def __init__(self):
                pass

            def request(self, payload):
                requests.append(dict(payload))
                return {
                    "status": "success",
                    "transcript": "stop now",
                    "language": "en",
                    "timings": {"transcribe_ms": 12},
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "speech.webm"
            source.write_bytes(b"fake webm")

            def fake_convert(src, dst):
                self.assertEqual(src, source)
                self.assertEqual(dst, Path(temp_dir) / "speech.parakeet.wav")
                dst.write_bytes(b"fake wav")
                return dst

            service = VoiceInputService()
            service.configure(
                provider="local_nvidia_parakeet",
                enabled=True,
                model="nvidia/parakeet-tdt-0.6b-v3",
                language="auto",
            )
            service._model = FakeRuntime()

            with (
                mock.patch.object(service, "dependency_available", return_value=True),
                mock.patch("strokegpt.asr._convert_audio_to_mono_wav", side_effect=fake_convert) as convert,
            ):
                result = service.transcribe_file(source)

            convert.assert_called_once()
            self.assertEqual(requests[0]["audio"], str(Path(temp_dir) / "speech.parakeet.wav"))
            self.assertFalse((Path(temp_dir) / "speech.parakeet.wav").exists())
            self.assertTrue(source.exists())
            self.assertEqual(result["transcript"], "stop now")

    def test_nvidia_parakeet_external_runtime_normalizes_wav_to_mono(self):
        requests = []

        class FakeRuntime(_ExternalParakeetRuntimeModel):
            def __init__(self):
                pass

            def request(self, payload):
                requests.append(dict(payload))
                return {
                    "status": "success",
                    "transcript": "resume",
                    "language": "en",
                    "timings": {"transcribe_ms": 9},
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "speech.wav"
            source.write_bytes(b"fake wav")
            service = VoiceInputService()
            service.configure(
                provider="local_nvidia_parakeet",
                enabled=True,
                model="nvidia/parakeet-tdt-0.6b-v3",
                language="auto",
            )
            service._model = FakeRuntime()

            def fake_convert(src, dst):
                self.assertEqual(src, source)
                self.assertEqual(dst, Path(temp_dir) / "speech.parakeet.wav")
                dst.write_bytes(b"fake mono wav")
                return dst

            with (
                mock.patch.object(service, "dependency_available", return_value=True),
                mock.patch("strokegpt.asr._convert_audio_to_mono_wav", side_effect=fake_convert) as convert,
            ):
                result = service.transcribe_file(source)

            convert.assert_called_once()
            self.assertEqual(requests[0]["audio"], str(Path(temp_dir) / "speech.parakeet.wav"))
            self.assertFalse((Path(temp_dir) / "speech.parakeet.wav").exists())
            self.assertEqual(result["transcript"], "resume")

    def test_parakeet_mono_pcm_helper_collapses_stereo_channel_last(self):
        import struct
        from strokegpt import asr

        test_case = self

        class FakeMonoArray:
            def __init__(self, values):
                self.values = values

            def astype(self, dtype, copy=False):
                test_case.assertEqual(dtype, "int16")
                test_case.assertFalse(copy)
                return self

            def tobytes(self):
                return struct.pack("<" + "h" * len(self.values), *self.values)

        class FakeFrame:
            def to_ndarray(self):
                class FakeStereoArray:
                    ndim = 2
                    shape = (2, 2)

                    def mean(self, axis):
                        test_case.assertEqual(axis, -1)
                        return FakeMonoArray([200, 300])

                return FakeStereoArray()

        pcm = asr._audio_frame_to_mono_pcm(FakeFrame())

        self.assertEqual(struct.unpack("<hh", pcm), (200, 300))

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

    def test_cached_model_status_reuses_positive_scan_result(self):
        cache_parent = PROJECT_ROOT / "user_data" / "test_asr_cache"
        cache_parent.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="cached_model_reuse_", dir=cache_parent)
        try:
            service = VoiceInputService(model_cache_dir=temp_dir)
            service.configure(
                provider="local_faster_whisper",
                enabled=True,
                model="tiny.en",
                language="en",
            )
            cached_model_dir = Path(temp_dir) / "faster-whisper-tiny-en" / "snapshots" / "abc123"

            with (
                mock.patch.object(service, "dependency_available", return_value=True),
                mock.patch("strokegpt.asr.os.walk", return_value=[(str(cached_model_dir), [], ["model.bin"])]) as walk_cache,
            ):
                self.assertTrue(service.status()["model_cached"])
                self.assertTrue(service.status()["model_cached"])

            self.assertEqual(walk_cache.call_count, 1)
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


class ParakeetWorkerRuntimeTests(unittest.TestCase):
    def test_transcribe_loaded_model_uses_windows_safe_nemo_options(self):
        from strokegpt import parakeet_worker

        calls = []

        class FakeModel:
            def transcribe(self, audio_paths, **kwargs):
                calls.append({"audio_paths": audio_paths, "kwargs": kwargs})
                return [types.SimpleNamespace(text=" stop now ")]

        payload = parakeet_worker._transcribe_loaded_model(
            FakeModel(),
            audio=Path("speech.wav"),
            language="auto",
            model_name="nvidia/parakeet-tdt-0.6b-v3",
            device="cuda",
        )

        self.assertEqual(payload["transcript"], "stop now")
        self.assertEqual(calls[0]["audio_paths"], ["speech.wav"])
        self.assertEqual(calls[0]["kwargs"]["batch_size"], 1)
        self.assertEqual(calls[0]["kwargs"]["channel_selector"], "average")
        self.assertEqual(calls[0]["kwargs"]["num_workers"], 0)
        self.assertFalse(calls[0]["kwargs"]["use_lhotse"])
        self.assertFalse(calls[0]["kwargs"]["verbose"])

    def test_nemo_temp_cleanup_guard_sets_ignore_cleanup_errors(self):
        from strokegpt import parakeet_worker

        calls = []

        class FakeTemporaryDirectory:
            def __init__(self, *args, **kwargs):
                calls.append(kwargs)

            def __enter__(self):
                return "tempdir"

            def __exit__(self, *_args):
                return False

        with mock.patch.object(parakeet_worker.tempfile, "TemporaryDirectory", FakeTemporaryDirectory):
            with parakeet_worker._ignore_temporary_directory_cleanup_errors():
                parakeet_worker.tempfile.TemporaryDirectory()

        self.assertTrue(calls)
        self.assertTrue(calls[0]["ignore_cleanup_errors"])

    def test_torch_status_reports_unusable_cuda_kernel(self):
        from strokegpt import parakeet_worker

        class FakeCuda:
            @staticmethod
            def is_available():
                return True

            @staticmethod
            def device_count():
                return 1

            @staticmethod
            def get_device_name(index):
                return "GTX Test"

            @staticmethod
            def get_device_capability(index):
                return (5, 0)

            @staticmethod
            def synchronize():
                return None

        fake_torch = types.ModuleType("torch")
        fake_torch.__version__ = "2.4.0+cu121"
        fake_torch.version = types.SimpleNamespace(cuda="12.1")
        fake_torch.cuda = FakeCuda()

        def fake_ones(*_args, **_kwargs):
            raise RuntimeError("CUDA error: no kernel image is available for execution on the device")

        fake_torch.ones = fake_ones
        original_torch = sys.modules.get("torch")
        try:
            sys.modules["torch"] = fake_torch
            status = parakeet_worker._torch_status("")
        finally:
            if original_torch is None:
                sys.modules.pop("torch", None)
            else:
                sys.modules["torch"] = original_torch

        self.assertTrue(status["cuda_available"])
        self.assertFalse(status["cuda_runtime_usable"])
        self.assertIn("no kernel image is available", status["cuda_runtime_error"])
        self.assertIn("Local faster-whisper", status["cuda_runtime_error"])

    def test_check_rejects_unusable_cuda_before_nemo_import(self):
        from strokegpt import parakeet_worker

        torch_status = {
            "torch_available": True,
            "cuda_available": True,
            "cuda_runtime_error": "PyTorch sees CUDA but a CUDA test kernel failed.",
            "device": "cuda",
        }
        with (
            mock.patch.object(parakeet_worker, "_torch_status", return_value=torch_status),
            mock.patch.object(parakeet_worker, "_import_nemo") as import_nemo,
        ):
            payload = parakeet_worker._check(types.SimpleNamespace(device=""))

        import_nemo.assert_not_called()
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["nemo_available"])
        self.assertIn("CUDA test kernel failed", payload["error"])


if __name__ == "__main__":
    unittest.main()
