import io
import unittest
from unittest import mock

from tests._web_support import WebTestCase


class WebLocalTtsRouteTests(WebTestCase):
    def test_local_tts_settings_do_not_auto_preload_model(self):
        from strokegpt.web import audio, settings

        original = settings.to_dict()
        original_preload = audio.preload_local_model_async
        calls = []
        try:
            audio.preload_local_model_async = lambda *args, **kwargs: calls.append((args, kwargs)) or True
            response = self.client.post("/set_local_tts_voice", json={
                "enabled": True,
                "engine": "chatterbox_turbo",
                "style": "expressive",
            })

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "ok")
            self.assertEqual(calls, [])
        finally:
            audio.preload_local_model_async = original_preload
            settings.apply_dict(original)
            audio.configure_local_voice(
                settings.audio_enabled,
                settings.local_tts_prompt_path,
                settings.local_tts_exaggeration,
                settings.local_tts_cfg_weight,
                settings.local_tts_style,
                settings.local_tts_temperature,
                settings.local_tts_top_p,
                settings.local_tts_min_p,
                settings.local_tts_repetition_penalty,
                settings.local_tts_engine,
            )
            settings.save()

    def test_local_tts_download_endpoint_is_explicit_preload(self):
        from strokegpt.web import audio

        original_preload = audio.preload_local_model_async
        calls = []
        try:
            audio.preload_local_model_async = lambda *args, **kwargs: calls.append((args, kwargs)) or True
            response = self.client.post("/preload_local_tts_model")

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "started")
            self.assertIn("local_tts_status", data)
            self.assertIn("preload_elapsed_seconds", data["local_tts_status"])
            self.assertIn("generation_status", data["local_tts_status"])
            self.assertEqual(calls, [((), {"force": True})])
        finally:
            audio.preload_local_model_async = original_preload

    def test_local_tts_test_requires_explicit_model_download(self):
        from strokegpt.web import audio

        with mock.patch.object(audio, "local_model_loaded", return_value=False):
            response = self.client.post("/test_local_tts_voice")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "needs_download")
        self.assertIn("Download / load", data["message"])

    def test_local_tts_engine_can_be_selected_and_saved(self):
        from strokegpt.web import audio, settings

        original = settings.to_dict()
        try:
            response = self.client.post("/set_local_tts_voice", json={
                "enabled": False,
                "engine": "chatterbox",
                "style": "expressive",
            })

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "ok")
            self.assertEqual(audio.local_engine, "chatterbox")
            self.assertEqual(settings.local_tts_engine, "chatterbox")
        finally:
            settings.apply_dict(original)
            audio.configure_local_voice(
                settings.audio_enabled,
                settings.local_tts_prompt_path,
                settings.local_tts_exaggeration,
                settings.local_tts_cfg_weight,
                settings.local_tts_style,
                settings.local_tts_temperature,
                settings.local_tts_top_p,
                settings.local_tts_min_p,
                settings.local_tts_repetition_penalty,
                settings.local_tts_engine,
            )
            settings.save()

    def test_local_tts_sample_upload_saves_prompt_path(self):
        from strokegpt.web import VOICE_SAMPLE_DIR, audio, settings

        original_prompt = settings.local_tts_prompt_path
        original_audio_prompt = audio.local_prompt_path
        saved_path = None
        try:
            response = self.client.post(
                "/upload_local_tts_sample",
                data={"sample": (io.BytesIO(b"RIFFsampledata"), "sample.wav")},
                content_type="multipart/form-data",
            )

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            saved_path = data["prompt_path"]
            self.assertEqual(data["status"], "success")
            self.assertTrue(saved_path.endswith(".wav"))
            self.assertTrue(saved_path.startswith(str(VOICE_SAMPLE_DIR.resolve())))
            self.assertEqual(settings.local_tts_prompt_path, saved_path)
            self.assertEqual(audio.local_prompt_path, saved_path)
        finally:
            if saved_path:
                path = VOICE_SAMPLE_DIR / saved_path.split("\\")[-1]
                if path.exists():
                    path.unlink()
            if VOICE_SAMPLE_DIR.exists() and not any(VOICE_SAMPLE_DIR.iterdir()):
                VOICE_SAMPLE_DIR.rmdir()
            settings.local_tts_prompt_path = original_prompt
            audio.local_prompt_path = original_audio_prompt
            settings.save()


if __name__ == "__main__":
    unittest.main()
