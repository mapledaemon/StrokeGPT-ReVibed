import importlib.util
import importlib.machinery
import io
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
import warnings
import wave
from unittest import mock


elevenlabs_module = types.ModuleType("elevenlabs")
elevenlabs_module.__spec__ = importlib.machinery.ModuleSpec("elevenlabs", loader=None)
elevenlabs_module.VoiceSettings = lambda **kwargs: kwargs
elevenlabs_client_module = types.ModuleType("elevenlabs.client")
elevenlabs_client_module.__spec__ = importlib.machinery.ModuleSpec("elevenlabs.client", loader=None)
elevenlabs_client_module.ElevenLabs = object
sys.modules.setdefault("elevenlabs", elevenlabs_module)
sys.modules.setdefault("elevenlabs.client", elevenlabs_client_module)

from strokegpt.audio import AudioService


class AudioServiceTests(unittest.TestCase):
    def test_chatterbox_style_presets_are_available(self):
        expected = {"default", "calm", "expressive", "dramatic", "energetic", "clone_stable"}

        self.assertEqual(set(AudioService.CHATTERBOX_STYLE_PRESETS), expected)

    def test_local_engine_defaults_to_turbo(self):
        service = AudioService()

        self.assertEqual(service.local_engine, AudioService.LOCAL_ENGINE_CHATTERBOX_TURBO)

    def test_local_engine_change_unloads_cached_model(self):
        service = AudioService()
        service.local_engine = AudioService.LOCAL_ENGINE_CHATTERBOX
        service._local_model = object()
        service._local_model_engine = AudioService.LOCAL_ENGINE_CHATTERBOX
        service._local_preload_status = "error"
        service._local_preload_error = "old error"

        service.configure_local_voice(False, engine=AudioService.LOCAL_ENGINE_CHATTERBOX_TURBO)

        self.assertEqual(service.local_engine, AudioService.LOCAL_ENGINE_CHATTERBOX_TURBO)
        self.assertIsNone(service._local_model)
        self.assertEqual(service._local_preload_status, "idle")
        self.assertEqual(service._local_preload_phase, "idle")
        self.assertEqual(service._local_preload_error, "")

    def test_local_status_ignores_cached_model_for_previous_engine(self):
        service = AudioService()
        service.local_engine = AudioService.LOCAL_ENGINE_CHATTERBOX_TURBO
        service._local_model = object()
        service._local_model_engine = AudioService.LOCAL_ENGINE_CHATTERBOX
        service._local_model_device = "cuda"
        service._local_runtime_info = lambda: {
            "torch_available": True,
            "torch_version": "test",
            "cuda_available": True,
            "cuda_version": "test",
            "device_count": 1,
            "device_name": "test gpu",
            "device": "cuda",
            "device_override": "auto",
        }
        service._local_engine_options = lambda: [
            {"id": service.local_engine, "label": "Chatterbox Turbo", "available": True}
        ]

        status = service.local_status()

        self.assertFalse(status["model_loaded"])
        self.assertNotIn("Model loaded", status["message"])

    def test_preload_reports_ready_when_selected_model_is_already_loaded(self):
        service = AudioService()
        service.provider = "local"
        service.is_on = True
        service._local_model = object()
        service._local_model_engine = service.local_engine
        service._local_preload_status = "error"
        service._local_preload_error = "old error"

        started = service.preload_local_model_async()

        self.assertTrue(started)
        self.assertEqual(service._local_preload_status, "ready")
        self.assertEqual(service._local_preload_phase, "ready")
        self.assertEqual(service._local_preload_error, "")

    def test_local_status_reports_preload_progress_percent(self):
        service = AudioService()
        service.provider = "local"
        service.is_on = True
        service._local_runtime_info = lambda: {
            "torch_available": True,
            "torch_version": "test",
            "cuda_available": True,
            "cuda_version": "test",
            "device_count": 1,
            "device_name": "test gpu",
            "device": "cuda",
            "device_override": "auto",
        }
        service._local_engine_options = lambda: [
            {"id": service.local_engine, "label": "Chatterbox Turbo", "available": True}
        ]
        service._local_preload_status = "loading"
        service._local_preload_phase = "loading_model"
        service._local_preload_started_at = 1.0

        with mock.patch("strokegpt.audio.time.perf_counter", return_value=31.0):
            status = service.local_status()

        self.assertEqual(status["preload_status"], "loading")
        self.assertIsInstance(status["preload_progress_percent"], int)
        self.assertGreater(status["preload_progress_percent"], 1)
        self.assertLess(status["preload_progress_percent"], 100)

    def test_lightweight_local_status_skips_runtime_probe(self):
        service = AudioService()
        service.provider = "local"
        service.is_on = True
        service._local_runtime_info = mock.Mock(side_effect=AssertionError("runtime probe"))
        service._local_engine_options = lambda: [
            {"id": service.local_engine, "label": "Chatterbox Turbo", "available": True}
        ]

        status = service.local_status(lightweight=True)

        self.assertEqual(status["status"], "unchecked")
        self.assertTrue(status["torch"]["unchecked"])
        self.assertIsNone(status["cuda_available"])
        self.assertIn("after the app opens", status["message"])
        service._local_runtime_info.assert_not_called()

    def test_elevenlabs_generation_errors_are_reported(self):
        class FailingTextToSpeech:
            def convert(self, **_kwargs):
                raise RuntimeError("network failed")

        service = AudioService()
        service.api_key = "test"
        service.voice_id = "voice"
        service.client = types.SimpleNamespace(text_to_speech=FailingTextToSpeech())

        service._generate_elevenlabs_audio("hello")

        self.assertIn("ElevenLabs problem", service.last_error)
        self.assertIn("network failed", service.last_error)

    def test_local_style_preset_sets_generation_controls(self):
        service = AudioService()
        service.configure_local_voice(True, style="dramatic")

        preset = AudioService.CHATTERBOX_STYLE_PRESETS["dramatic"]
        self.assertEqual(service.local_style, "dramatic")
        self.assertEqual(service.local_exaggeration, preset["exaggeration"])
        self.assertEqual(service.local_cfg_weight, preset["cfg_weight"])
        self.assertEqual(service.local_temperature, preset["temperature"])
        self.assertEqual(service.local_top_p, preset["top_p"])
        self.assertEqual(service.local_min_p, preset["min_p"])
        self.assertEqual(service.local_repetition_penalty, preset["repetition_penalty"])

    def test_manual_local_controls_override_preset(self):
        service = AudioService()
        service.configure_local_voice(
            True,
            style="calm",
            exaggeration=0.8,
            cfg_weight=0.2,
            temperature=1.1,
            top_p=0.8,
            min_p=0.1,
            repetition_penalty=1.4,
        )

        self.assertEqual(service.local_style, "calm")
        self.assertEqual(service.local_exaggeration, 0.8)
        self.assertEqual(service.local_cfg_weight, 0.2)
        self.assertEqual(service.local_temperature, 1.1)
        self.assertEqual(service.local_top_p, 0.8)
        self.assertEqual(service.local_min_p, 0.1)
        self.assertEqual(service.local_repetition_penalty, 1.4)

    def test_local_status_warns_when_torch_is_cpu_only(self):
        service = AudioService()
        service._local_runtime_info = lambda: {
            "torch_available": True,
            "torch_version": "test",
            "cuda_available": False,
            "cuda_version": "",
            "device_count": 0,
            "device_name": "",
            "device": "cpu",
            "device_override": "auto",
        }
        service._local_engine_options = lambda: [
            {"id": service.local_engine, "label": "Chatterbox Turbo", "available": True}
        ]

        status = service.local_status()

        self.assertEqual(status["status"], "cpu_only")
        self.assertIn("CPU-only", status["message"])
        self.assertFalse(status["cuda_available"])

    def test_local_status_reports_missing_reference_sample(self):
        service = AudioService()
        service.local_prompt_path = str(Path(__file__).with_name("missing-reference-sample.wav"))
        service._local_runtime_info = lambda: {
            "torch_available": True,
            "torch_version": "test",
            "cuda_available": True,
            "cuda_version": "test",
            "device_count": 1,
            "device_name": "test gpu",
            "device": "cuda",
            "device_override": "auto",
        }
        service._local_engine_options = lambda: [
            {"id": service.local_engine, "label": "Chatterbox Turbo", "available": True}
        ]

        status = service.local_status()

        self.assertEqual(status["status"], "sample_missing")
        self.assertFalse(status["available"])
        self.assertEqual(status["prompt_path"], service.local_prompt_path)
        self.assertIn("Reference voice sample not found", status["message"])

    def test_local_generation_failure_resets_cached_model(self):
        class DummyModel:
            sr = 24000

        service = AudioService()
        service.provider = "local"
        service._local_model = DummyModel()
        service._local_model_engine = service.local_engine
        service._local_model_device = "cuda"
        service._generate_local_waveform = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cuda exploded"))
        service._empty_cuda_cache = lambda: None

        service.generate_audio_for_text("hello", force=True)

        self.assertIsNone(service._local_model)
        self.assertEqual(service._local_generation_status, "error")
        self.assertEqual(service._local_preload_status, "error")
        self.assertIn("cuda exploded", service._local_generation_error)
        self.assertIn("Local Chatterbox problem", service.last_error)

    def test_local_output_latency_uses_loaded_model_without_queueing_audio(self):
        class DummyModel:
            sr = 24000

        service = AudioService()
        service.provider = "local"
        service._local_model = DummyModel()
        service._local_model_engine = service.local_engine
        service._local_model_device = "cuda"
        service._generate_local_waveform = lambda *_args, **_kwargs: object()
        service._encode_wav_bytes = lambda *_args, **_kwargs: b"wav-bytes"

        result = service.measure_output_latency("ready")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider"], "local")
        self.assertEqual(result["device"], "cuda")
        self.assertEqual(result["audio_bytes"], len(b"wav-bytes"))
        self.assertEqual(service._local_generation_status, "idle")
        self.assertFalse(service.audio_output_queue)

    def test_audio_queue_waits_for_late_chunk(self):
        service = AudioService()

        def enqueue_later():
            time.sleep(0.02)
            service._enqueue_audio_chunk(b"RIFFlater", "audio/wav")

        thread = threading.Thread(target=enqueue_later)
        thread.start()
        try:
            chunk = service.wait_for_audio_chunk(0.5)
        finally:
            thread.join(timeout=1)

        self.assertEqual(chunk, {"bytes": b"RIFFlater", "mimetype": "audio/wav"})
        self.assertIsNone(service.get_next_audio_chunk())

    def test_local_tts_request_queue_keeps_latest_pending_text(self):
        service = AudioService()
        service.provider = "local"
        service.is_on = True
        started = threading.Event()
        release = threading.Event()
        spoken = []

        def generate(text):
            spoken.append(text)
            if text == "first":
                started.set()
                release.wait(timeout=1)

        service.generate_audio_for_text = generate

        self.assertTrue(service.enqueue_text_for_audio("first"))
        self.assertTrue(started.wait(timeout=1), spoken)
        self.assertTrue(service.enqueue_text_for_audio("second"))
        self.assertTrue(service.enqueue_text_for_audio("third"))
        self.assertEqual(service.tts_request_queue_depth(), 1)
        self.assertEqual(service._tts_dropped_text_count, 1)

        release.set()
        deadline = time.time() + 1
        while time.time() < deadline and spoken != ["first", "third"]:
            time.sleep(0.01)

        self.assertEqual(spoken, ["first", "third"])

    def test_non_local_tts_enqueue_preserves_async_generation_path(self):
        service = AudioService()
        called = threading.Event()
        spoken = []

        def generate(text):
            spoken.append(text)
            called.set()

        service.generate_audio_for_text = generate

        self.assertTrue(service.enqueue_text_for_audio("hello"))
        self.assertTrue(called.wait(timeout=1), spoken)
        self.assertEqual(spoken, ["hello"])

    def test_local_status_reports_tts_queue_depths(self):
        service = AudioService()
        service.provider = "local"
        service.is_on = True
        service._tts_request_queue.append("pending")
        service.audio_output_queue.append({"bytes": b"RIFF", "mimetype": "audio/wav"})
        service._local_runtime_info = lambda: {
            "torch_available": True,
            "torch_version": "test",
            "cuda_available": True,
            "cuda_version": "test",
            "device_count": 1,
            "device_name": "test gpu",
            "device": "cuda",
            "device_override": "auto",
        }
        service._local_engine_options = lambda: [
            {"id": service.local_engine, "label": "Chatterbox Turbo", "available": True}
        ]

        status = service.local_status()

        self.assertEqual(status["tts_request_queue_depth"], 1)
        self.assertEqual(status["tts_request_queue_limit"], service.LOCAL_TTS_PENDING_TEXT_LIMIT)
        self.assertEqual(status["audio_output_queue_depth"], 1)

    def test_local_preload_failure_resets_cached_model_state(self):
        service = AudioService()
        service._local_model = object()
        service._local_model_engine = "previous-engine"
        service._local_model_device = "cuda"
        service._get_chatterbox_model = lambda: (_ for _ in ()).throw(RuntimeError("download failed"))
        service._empty_cuda_cache = lambda: None

        started = service.preload_local_model_async(force=True)
        service._local_preload_thread.join(timeout=1)

        self.assertTrue(started)
        self.assertFalse(service._local_preload_thread.is_alive())
        self.assertIsNone(service._local_model)
        self.assertEqual(service._local_preload_status, "error")
        self.assertEqual(service._local_preload_phase, "error")
        self.assertIn("download failed", service._local_preload_error)

    def test_local_warmup_uses_realistic_text_twice(self):
        service = AudioService()
        calls = []

        service._generate_local_waveform = lambda _model, text: calls.append(text)

        service._warmup_local_model(object())

        self.assertEqual(calls, [service.LOCAL_TTS_WARMUP_TEXT, service.LOCAL_TTS_WARMUP_TEXT])
        self.assertGreater(len(service.LOCAL_TTS_WARMUP_TEXT), len("Ready."))
        self.assertTrue(service._local_warmup_done)

    @unittest.skipIf(importlib.util.find_spec("torch") is None, "torch not installed")
    def test_local_waveform_coerces_chatterbox_conditionals_to_float32(self):
        import numpy as np
        import torch

        class DummyT3Cond:
            def __init__(self):
                self.speaker_emb = torch.ones(1, 256, dtype=torch.float64)
                self.cond_prompt_speech_tokens = torch.ones(1, 4, dtype=torch.long)
                self.emotion_adv = torch.ones(1, 1, 1, dtype=torch.float64)

            def to(self, *, device=None, dtype=None):
                for name, value in vars(self).items():
                    if not torch.is_tensor(value):
                        continue
                    if value.is_floating_point():
                        setattr(self, name, value.to(device=device, dtype=dtype))
                    elif device:
                        setattr(self, name, value.to(device=device))
                return self

        class DummyConditionals:
            def __init__(self):
                self.t3 = DummyT3Cond()
                self.gen = {
                    "embedding": torch.ones(1, 4, dtype=torch.float64),
                    "prompt_token": torch.ones(1, dtype=torch.long),
                }

        class DummyModel:
            sr = 24000
            device = "cpu"

            def __init__(self):
                self.s3gen = types.SimpleNamespace(tokenizer=DummyTokenizer())
                self.ve = DummyVoiceEncoder()
                self.conds = DummyConditionals()
                self.generate_default_dtype = None
                self.generate_kwargs = None

            def prepare_conditionals(self, _path, exaggeration=0.5, norm_loudness=True):
                prompt_audio = self.norm_loudness(np.ones(4, dtype=np.float64), 24000)
                self.s3gen.tokenizer._prepare_audio([prompt_audio])
                self.ve.embeds_from_wavs([prompt_audio], sample_rate=16000)
                self.conds = DummyConditionals()

            def norm_loudness(self, wav, _sr):
                return np.asarray(wav, dtype=np.float64)

            def generate(self, _text, **kwargs):
                self.generate_default_dtype = torch.get_default_dtype()
                self.generate_kwargs = kwargs
                self.t3_speaker_dtype = self.conds.t3.speaker_emb.dtype
                self.t3_token_dtype = self.conds.t3.cond_prompt_speech_tokens.dtype
                self.gen_embedding_dtype = self.conds.gen["embedding"].dtype
                self.gen_token_dtype = self.conds.gen["prompt_token"].dtype
                return torch.ones(1, 4, dtype=torch.float64)

        class DummyTokenizer:
            def __init__(self):
                self.input_dtype = None

            def _prepare_audio(self, wavs):
                self.input_dtype = wavs[0].dtype
                return wavs

        class DummyVoiceEncoder:
            def __init__(self):
                self.input_dtype = None

            def embeds_from_wavs(self, wavs, **_kwargs):
                self.input_dtype = wavs[0].dtype
                return np.ones((1, 4), dtype=np.float32)

        service = AudioService()
        service.local_prompt_path = "sample.wav"
        model = DummyModel()
        original_dtype = torch.get_default_dtype()
        try:
            torch.set_default_dtype(torch.float64)
            waveform = service._generate_local_waveform(model, "Ready.")
            restored_dtype = torch.get_default_dtype()
        finally:
            torch.set_default_dtype(original_dtype)

        self.assertEqual(model.generate_default_dtype, torch.float32)
        self.assertEqual(restored_dtype, torch.float64)
        self.assertEqual(model.t3_speaker_dtype, torch.float32)
        self.assertEqual(model.t3_token_dtype, torch.long)
        self.assertEqual(model.gen_embedding_dtype, torch.float32)
        self.assertEqual(model.gen_token_dtype, torch.long)
        self.assertEqual(waveform.dtype, torch.float32)
        self.assertEqual(model.s3gen.tokenizer.input_dtype, np.float32)
        self.assertEqual(model.ve.input_dtype, np.float32)
        self.assertNotIn("audio_prompt_path", model.generate_kwargs)

    def test_chatterbox_prompt_conditionals_are_cached_between_chunks(self):
        class DummyModel:
            sr = 24000
            device = "cpu"

            def __init__(self):
                self.prepare_calls = 0
                self.generate_kwargs = []
                self.conds = object()

            def prepare_conditionals(self, _path, **_kwargs):
                self.prepare_calls += 1
                self.conds = object()

            def generate(self, _text, **kwargs):
                self.generate_kwargs.append(kwargs)
                return object()

        service = AudioService()
        model = DummyModel()
        with tempfile.NamedTemporaryFile(suffix=".wav") as sample:
            sample.write(b"sample")
            sample.flush()
            service.local_prompt_path = sample.name

            service._generate_local_waveform(model, "First.")
            service._generate_local_waveform(model, "Second.")

        self.assertEqual(model.prepare_calls, 1)
        self.assertEqual(len(model.generate_kwargs), 2)
        self.assertNotIn("audio_prompt_path", model.generate_kwargs[0])
        self.assertNotIn("audio_prompt_path", model.generate_kwargs[1])

    def test_local_tts_text_is_split_for_lower_first_audio_latency(self):
        service = AudioService()
        text = "First sentence is short. " + ("This sentence has enough words to make the local text to speech splitter create more than one chunk. " * 5)

        chunks = service._split_text_for_local_tts(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= service.LOCAL_TTS_CHUNK_CHARS for chunk in chunks))

    def test_local_tts_splits_long_first_sentence_for_lower_first_latency(self):
        service = AudioService()
        text = (
            "This opening sentence is deliberately long and filled with enough descriptive clauses, "
            "because local Chatterbox should be able to start rendering a short first clip before "
            "waiting on the entire reply to finish as one large audio chunk. "
            "The second sentence can use the normal chunk size."
        )

        chunks = service._split_text_for_local_tts(text)

        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(len(chunks[0]), service.LOCAL_TTS_FIRST_CHUNK_CHARS)

    @unittest.skipIf(importlib.util.find_spec("torch") is None, "torch not installed")
    def test_local_wav_encoder_uses_stdlib_wav(self):
        import torch

        service = AudioService()
        encoded = service._encode_wav_bytes(torch.tensor([[0.0, 0.5, -1.0, 1.0]]), 24000)

        with wave.open(io.BytesIO(encoded), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), 24000)
            self.assertEqual(wav_file.getnframes(), 4 + round(24000 * service.LOCAL_TTS_TAIL_PADDING_MS / 1000))
            frames = wav_file.readframes(wav_file.getnframes())
            self.assertEqual(frames[-16:], b"\x00" * 16)

    @unittest.skipIf(importlib.util.find_spec("chatterbox") is None, "chatterbox not installed")
    def test_local_status_suppresses_perth_pkg_resources_warning(self):
        service = AudioService()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            service.local_status()

        self.assertFalse(any("pkg_resources is deprecated as an API" in str(w.message) for w in caught))


if __name__ == "__main__":
    unittest.main()
