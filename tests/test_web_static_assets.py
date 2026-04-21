import importlib.util
import io
import unittest
from unittest import mock


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

    def test_startup_port_selection_falls_back(self):
        from strokegpt.web import _port_candidates, _select_bind_port

        self.assertEqual(_port_candidates(5000, fallback_count=3), [5000, 5001, 5002, 5003])
        selected = _select_bind_port(
            "127.0.0.1",
            5000,
            fallback_count=3,
            can_bind=lambda host, port: port != 5000,
        )

        self.assertEqual(selected, 5001)

    def test_root_static_assets_are_served(self):
        expected = {
            "/static/splash.jpg": "image/jpeg",
            "/static/default-pfp.png": "image/png",
            "/static/app.css": "text/css",
            "/static/app.js": "text/javascript",
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

    def test_root_links_frontend_assets(self):
        response = self.client.get("/")
        try:
            page = response.get_data(as_text=True)

            self.assertIn('href="/static/app.css"', page)
            self.assertIn('src="/static/app.js"', page)
            self.assertNotIn("<style>", page)
            self.assertNotIn("<script>", page)
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

    def test_settings_dialog_contains_device_and_speed_controls(self):
        response = self.client.get("/")
        try:
            page = response.get_data(as_text=True)

            self.assertIn('id="persona-prompt-select"', page)
            self.assertIn('id="save-persona-prompt-btn"', page)
            self.assertIn('data-settings-tab="device"', page)
            self.assertIn('id="settings-tab-device"', page)
            self.assertIn('id="handy-key-input"', page)
            self.assertIn('id="motion-depth-min-slider"', page)
            self.assertIn('id="motion-depth-max-slider"', page)
            self.assertIn('id="motion-speed-min-slider"', page)
            self.assertIn('id="motion-speed-max-slider"', page)
            self.assertIn('id="save-motion-speed-limits"', page)
            self.assertIn('data-settings-tab="advanced"', page)
            self.assertIn('id="settings-tab-advanced"', page)
            self.assertIn('id="reset-settings-btn"', page)
            self.assertIn('id="local-tts-engine-select"', page)
            self.assertIn('value="chatterbox_turbo"', page)
            self.assertIn('id="download-ollama-model-btn"', page)
            self.assertIn('id="refresh-ollama-status-btn"', page)
            self.assertIn('id="download-local-tts-model-button"', page)
            self.assertIn('class="model-actions"', page)
            self.assertIn('class="model-actions model-actions-wide"', page)
        finally:
            response.close()

    def test_frontend_css_contains_responsive_layout_guards(self):
        response = self.client.get("/static/app.css")
        try:
            css = response.get_data(as_text=True)

            self.assertIn("#chat-messages-container { display: flex; flex-direction: column;", css)
            self.assertIn(".message-bubble pre", css)
            self.assertIn("white-space: pre-wrap", css)
            self.assertIn("repeat(auto-fit, minmax(150px, 1fr))", css)
            self.assertIn(".my-button:disabled", css)
            self.assertIn("#rhythm-canvas { display: block; width: 100%; height: 100%; }", css)
            self.assertIn(".settings-subsection { display: flex; flex-direction: column; gap: 12px;", css)
            self.assertIn(".model-actions", css)
            self.assertIn(".setup-slider", css)
            self.assertIn("@media (max-width: 760px)", css)
        finally:
            response.close()

    def test_frontend_js_avoids_incremental_inner_html_for_options(self):
        response = self.client.get("/static/app.js")
        try:
            script = response.get_data(as_text=True)

            self.assertNotIn("innerHTML +=", script)
            self.assertIn("elevenLabsVoiceSelect.replaceChildren", script)
            self.assertIn("rhythmCanvas.getBoundingClientRect", script)
            self.assertIn("slider-container setup-slider", script)
        finally:
            response.close()

    def test_chat_messages_are_rendered_as_text_nodes(self):
        response = self.client.get("/static/app.js")
        try:
            script = response.get_data(as_text=True)

            self.assertIn("function appendMessageText", script)
            self.assertIn("D.createTextNode", script)
            self.assertNotIn('message-bubble">${text}', script)
        finally:
            response.close()

    def test_persona_prompt_can_be_selected_and_saved(self):
        from strokegpt.web import settings

        original_persona = settings.persona_desc
        original_prompts = list(settings.persona_prompts)
        try:
            response = self.client.post("/set_persona_prompt", json={
                "persona_desc": "  An energetic and passionate teammate  ",
                "save_prompt": True,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["persona"], "An energetic and passionate teammate")
            self.assertIn("An energetic and passionate teammate", data["persona_prompts"])
            self.assertEqual(settings.persona_desc, "An energetic and passionate teammate")
            self.assertIn("An energetic and passionate teammate", settings.persona_prompts)
        finally:
            settings.persona_desc = original_persona
            settings.persona_prompts = original_prompts
            settings.save()

    def test_reset_settings_requires_confirmation(self):
        response = self.client.post("/reset_settings", json={})
        try:
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["status"], "error")
        finally:
            response.close()

    def test_json_routes_handle_missing_or_invalid_payloads_without_500(self):
        invalid_posts = [
            "/set_handy_key",
            "/set_profile_picture",
            "/setup_elevenlabs",
        ]

        for path in invalid_posts:
            with self.subTest(path=path):
                response = self.client.post(path, data="not json", content_type="text/plain")
                try:
                    self.assertLess(response.status_code, 500)
                finally:
                    response.close()

    def test_numeric_routes_fall_back_on_invalid_values(self):
        from strokegpt.web import handy, settings

        original = (
            settings.min_speed,
            settings.max_speed,
            handy.min_user_speed,
            handy.max_user_speed,
        )
        try:
            response = self.client.post("/set_speed_limits", json={
                "min_speed": "bad",
                "max_speed": None,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["min_speed"], 10)
            self.assertEqual(data["max_speed"], 80)
        finally:
            (
                settings.min_speed,
                settings.max_speed,
                handy.min_user_speed,
                handy.max_user_speed,
            ) = original
            handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
            settings.save()

    def test_reset_settings_restores_defaults_and_runtime_services(self):
        from strokegpt.settings import DEFAULT_OLLAMA_MODEL, DEFAULT_PERSONA_PROMPT
        from strokegpt.web import apply_settings_to_services, audio, handy, llm, settings

        original = settings.to_dict()
        original_send_command = handy._send_command
        sent_commands = []
        try:
            handy._send_command = lambda path, body=None: sent_commands.append((path, body or {})) or True
            settings.handy_key = "test-key"
            settings.ai_name = "Custom"
            settings.set_persona_prompt("An energetic and passionate teammate")
            settings.min_speed = 40
            settings.max_speed = 50
            settings.audio_provider = "local"
            settings.audio_enabled = True
            apply_settings_to_services()

            response = self.client.post("/reset_settings", json={"confirm": "RESET"})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn(("hamp/stop", {}), sent_commands)
            self.assertFalse(data["configured"])
            self.assertEqual(settings.handy_key, "")
            self.assertEqual(handy.handy_key, "")
            self.assertEqual(settings.ai_name, "BOT")
            self.assertEqual(settings.persona_desc, DEFAULT_PERSONA_PROMPT)
            self.assertEqual(settings.min_speed, 10)
            self.assertEqual(settings.max_speed, 80)
            self.assertEqual(handy.min_user_speed, 10)
            self.assertEqual(handy.max_user_speed, 80)
            self.assertEqual(llm.model, DEFAULT_OLLAMA_MODEL)
            self.assertEqual(audio.provider, "elevenlabs")
            self.assertFalse(audio.is_on)
        finally:
            handy._send_command = original_send_command
            settings.apply_dict(original)
            settings.save()
            apply_settings_to_services()

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

    def test_speed_limits_are_saved_sorted_and_clamped(self):
        from strokegpt.web import handy, settings

        original = (
            settings.min_speed,
            settings.max_speed,
            handy.min_user_speed,
            handy.max_user_speed,
        )
        try:
            response = self.client.post("/set_speed_limits", json={
                "min_speed": 120,
                "max_speed": -5,
            })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["min_speed"], 0)
            self.assertEqual(data["max_speed"], 100)
            self.assertEqual(settings.min_speed, 0)
            self.assertEqual(settings.max_speed, 100)
            self.assertEqual(handy.min_user_speed, 0)
            self.assertEqual(handy.max_user_speed, 100)
        finally:
            (
                settings.min_speed,
                settings.max_speed,
                handy.min_user_speed,
                handy.max_user_speed,
            ) = original
            handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
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
                    mock.patch("strokegpt.web._ollama_status_payload", return_value=fake_status):
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
            self.assertEqual(response.get_json()["status"], "started")
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
