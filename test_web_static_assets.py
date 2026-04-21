import importlib.util
import io
import unittest


REQUIRED_MODULES = ("flask", "requests", "elevenlabs")


def module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


MISSING_MODULES = [name for name in REQUIRED_MODULES if not module_available(name)]


@unittest.skipIf(MISSING_MODULES, f"missing app dependencies: {', '.join(MISSING_MODULES)}")
class WebStaticAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from strokegpt.web import app

        cls.app = app
        cls.client = app.test_client()

    def test_flask_default_static_route_is_disabled(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}

        self.assertNotIn("static", endpoints)

    def test_root_static_images_are_served(self):
        expected = {
            "/static/splash.jpg": "image/jpeg",
            "/static/default-pfp.png": "image/png",
        }

        for path, mimetype in expected.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.mimetype, mimetype)
                    self.assertGreater(len(response.data), 0)
                finally:
                    response.close()

    def test_updates_and_audio_are_separate_browser_endpoints(self):
        from strokegpt.web import audio, messages_for_ui

        messages_for_ui.clear()
        audio.audio_output_queue.clear()
        messages_for_ui.append("hello")
        audio.audio_output_queue.append({"bytes": b"RIFFtest", "mimetype": "audio/wav"})

        updates = self.client.get("/get_updates")
        try:
            self.assertEqual(updates.status_code, 200)
            self.assertEqual(updates.get_json()["messages"], ["hello"])
            self.assertTrue(updates.get_json()["audio_ready"])
        finally:
            updates.close()

        audio_response = self.client.get("/get_audio")
        try:
            self.assertEqual(audio_response.status_code, 200)
            self.assertEqual(audio_response.mimetype, "audio/wav")
            self.assertEqual(audio_response.data, b"RIFFtest")
        finally:
            audio_response.close()

    def test_mode_timings_are_saved_sorted_and_clamped(self):
        from strokegpt.web import settings

        original = (
            settings.auto_min_time,
            settings.auto_max_time,
            settings.edging_min_time,
            settings.edging_max_time,
            settings.milking_min_time,
            settings.milking_max_time,
        )
        try:
            response = self.client.post("/set_mode_timings", json={
                "auto_min": 20,
                "auto_max": 10,
                "edging_min": 0,
                "edging_max": 99,
                "milking_min": 3,
                "milking_max": 4,
            })
            self.assertEqual(response.status_code, 200)
            timings = response.get_json()["timings"]
            self.assertEqual(timings["auto_min"], 10)
            self.assertEqual(timings["auto_max"], 20)
            self.assertEqual(timings["edging_min"], 1.0)
            self.assertEqual(timings["edging_max"], 60.0)
            self.assertEqual(timings["milking_min"], 3.0)
            self.assertEqual(timings["milking_max"], 4.0)
        finally:
            (
                settings.auto_min_time,
                settings.auto_max_time,
                settings.edging_min_time,
                settings.edging_max_time,
                settings.milking_min_time,
                settings.milking_max_time,
            ) = original
            settings.save()

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
