import importlib.util
import io
import unittest
from types import SimpleNamespace
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
    FRONTEND_SCRIPT_PATHS = (
        "/static/app.js",
        "/static/js/context.js",
        "/static/js/settings.js",
        "/static/js/chat.js",
        "/static/js/audio.js",
        "/static/js/device-control.js",
        "/static/js/motion-control.js",
        "/static/js/setup.js",
    )

    @classmethod
    def setUpClass(cls):
        from strokegpt.web import app

        cls.app = app
        cls.client = app.test_client()

    def frontend_scripts(self):
        scripts = []
        for path in self.FRONTEND_SCRIPT_PATHS:
            response = self.client.get(path)
            try:
                self.assertEqual(response.status_code, 200, path)
                scripts.append(response.get_data(as_text=True))
            finally:
                response.close()
        return "\n".join(scripts)

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
            "/static/js/context.js": "text/javascript",
            "/static/js/settings.js": "text/javascript",
            "/static/js/chat.js": "text/javascript",
            "/static/js/audio.js": "text/javascript",
            "/static/js/device-control.js": "text/javascript",
            "/static/js/motion-control.js": "text/javascript",
            "/static/js/setup.js": "text/javascript",
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
            self.assertIn('type="module"', page)
            self.assertIn('id="like-this-move-btn"', page)
            self.assertIn('id="dislike-this-move-btn"', page)
            self.assertIn('id="motion-meter-panel"', page)
            self.assertIn('id="motion-feedback-buttons"', page)
            self.assertIn('id="sidebar-motion-indicator"', page)
            self.assertIn('id="handy-cylinder-indicator"', page)
            self.assertNotIn('id="motion-trace-panel"', page)
            self.assertNotIn('id="rhythm-canvas"', page)
            self.assertIn("Preset Modes", page)
            self.assertIn('class="preset-mode-stack"', page)
            self.assertIn('class="sidebar-stop-section"', page)
            self.assertNotIn("DANGER ZONE", page)
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

    def test_status_payload_includes_motion_observability(self):
        from strokegpt.motion import MotionTarget
        from strokegpt.web import handy, motion

        original_state = (
            handy.last_relative_speed,
            handy.last_stroke_speed,
            handy.last_depth_pos,
            handy.last_stroke_range,
            handy.min_handy_depth,
            handy.max_handy_depth,
        )
        try:
            handy.last_relative_speed = 55
            handy.last_stroke_speed = 42
            handy.last_depth_pos = 60
            handy.last_stroke_range = 70
            handy.min_handy_depth = 0
            handy.max_handy_depth = 100
            motion._record_target(MotionTarget(55, 60, 70, label="test trace"), source="unit test")

            response = self.client.get("/get_status")
            try:
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
            finally:
                response.close()

            self.assertEqual(payload["relative_speed"], 55)
            self.assertIn("motion_observability", payload)
            observability = payload["motion_observability"]
            self.assertEqual(observability["source"], "unit test")
            self.assertIn("diagnostics", observability)
            self.assertEqual(observability["diagnostics"]["physical_speed"], 42)
            self.assertEqual(observability["diagnostics"]["physical_depth"], 60)
            self.assertTrue(observability["trace"])
            self.assertEqual(observability["trace"][-1]["label"], "test trace")
        finally:
            (
                handy.last_relative_speed,
                handy.last_stroke_speed,
                handy.last_depth_pos,
                handy.last_stroke_range,
                handy.min_handy_depth,
                handy.max_handy_depth,
            ) = original_state
            with motion._observability_lock:
                motion._trace.clear()
                motion._last_source = "idle"
                motion._last_label = "idle"
                motion._last_command_time = None

    def test_send_message_returns_fallback_when_llm_omits_chat(self):
        from strokegpt.web import audio, chat_history, handy, llm, messages_for_ui, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        messages_for_ui.clear()
        chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with mock.patch.object(llm, "get_chat_response", return_value={"move": None, "new_mood": None}), \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "hello",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertFalse(data["chat_queued"])
            self.assertIn("no chat text", data["chat"])

            updates = self.client.get("/get_updates")
            try:
                queued = updates.get_json()["messages"]
            finally:
                updates.close()
            self.assertEqual(queued, [])
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            messages_for_ui.clear()
            chat_history.clear()

    def test_send_message_repairs_motion_claim_without_move(self):
        from strokegpt.web import audio, chat_history, handy, llm, messages_for_ui, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_handy_state = (
            handy.last_relative_speed,
            handy.last_depth_pos,
            handy.last_stroke_range,
        )
        captured_targets = []
        messages_for_ui.clear()
        chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            handy.last_relative_speed = 30
            handy.last_depth_pos = 40
            handy.last_stroke_range = 50
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "I'll switch to a new rhythm.",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(llm, "repair_motion_response", return_value={
                "chat": "Switching to a quick tip flick.",
                "move": {"zone": "tip", "pattern": "flick"},
                "new_mood": "Teasing",
            }) as repair, mock.patch.object(
                motion,
                "apply_generated_target",
                side_effect=lambda target, **_kwargs: captured_targets.append(target),
            ), \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "switch to another rhythm",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["chat"], "Switching to a quick tip flick.")
            self.assertTrue(data["motion_repaired"])
            self.assertTrue(data["motion_applied"])
            repair.assert_called_once()
            self.assertEqual(len(captured_targets), 1)
            self.assertIn("flick", captured_targets[0].label)
            self.assertEqual(captured_targets[0].depth, 10)
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            (
                handy.last_relative_speed,
                handy.last_depth_pos,
                handy.last_stroke_range,
            ) = original_handy_state
            messages_for_ui.clear()
            chat_history.clear()

    def test_send_message_does_not_repair_non_action_question(self):
        from strokegpt.web import audio, chat_history, handy, llm, messages_for_ui, motion, settings

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        messages_for_ui.clear()
        chat_history.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            with mock.patch.object(llm, "get_chat_response", return_value={
                "chat": "The tip is the shallow end of the stroke range.",
                "move": None,
                "new_mood": None,
            }), mock.patch.object(llm, "repair_motion_response") as repair, \
                    mock.patch.object(motion, "apply_generated_target") as apply_generated_target, \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "what does tip mean?",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertFalse(data["motion_repaired"])
            self.assertFalse(data["motion_applied"])
            repair.assert_not_called()
            apply_generated_target.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            messages_for_ui.clear()
            chat_history.clear()

    def test_send_message_relay_motion_feedback_to_active_mode(self):
        from strokegpt.web import audio, auto_mode_active_task, chat_history, handy
        from strokegpt.web import messages_for_ui, mode_message_event, mode_message_queue, motion, settings
        import strokegpt.web as web

        original_key = handy.handy_key
        original_settings_key = settings.handy_key
        original_task = auto_mode_active_task
        messages_for_ui.clear()
        chat_history.clear()
        mode_message_queue.clear()
        mode_message_event.clear()
        try:
            handy.handy_key = "test-key"
            settings.handy_key = "test-key"
            web.auto_mode_active_task = SimpleNamespace(name="edging", stop=lambda: None)
            with mock.patch.object(motion, "apply_generated_target") as apply_generated_target, \
                    mock.patch.object(audio, "generate_audio_for_text", return_value=None):
                response = self.client.post("/send_message", json={
                    "message": "focus on the tip",
                    "key": "test-key",
                    "persona_desc": settings.persona_desc,
                })

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "message_relayed_to_active_mode")
            self.assertEqual(list(mode_message_queue), ["focus on the tip"])
            self.assertTrue(mode_message_event.is_set())
            apply_generated_target.assert_not_called()
        finally:
            handy.handy_key = original_key
            settings.handy_key = original_settings_key
            web.auto_mode_active_task = original_task
            mode_message_queue.clear()
            mode_message_event.clear()
            messages_for_ui.clear()
            chat_history.clear()

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
            self.assertIn('id="motion-backend-select"', page)
            self.assertIn('id="save-motion-backend-btn"', page)
            self.assertIn('id="motion-backend-status"', page)
            self.assertIn('Flexible position/script (experimental)', page)
            self.assertIn('id="motion-pattern-list"', page)
            self.assertIn('id="refresh-motion-patterns-btn"', page)
            self.assertIn('id="import-motion-pattern-btn"', page)
            self.assertIn('id="open-motion-training-btn"', page)
            self.assertIn('id="motion-pattern-import-input"', page)
            self.assertIn('id="motion-training-dialog"', page)
            self.assertIn('id="close-motion-training-btn"', page)
            self.assertIn('id="motion-training-status"', page)
            self.assertIn('id="stop-motion-training-btn"', page)
            self.assertIn('id="motion-training-pattern-list"', page)
            self.assertIn('id="motion-training-pattern-title"', page)
            self.assertIn('id="motion-training-preview-canvas"', page)
            self.assertIn('id="motion-transform-smooth-btn"', page)
            self.assertIn('id="motion-transform-harshen-btn"', page)
            self.assertIn('id="motion-training-duration-value"', page)
            self.assertIn('id="motion-training-tempo-value"', page)
            self.assertIn('id="motion-transform-duration-down-btn"', page)
            self.assertIn('id="motion-transform-duration-up-btn"', page)
            self.assertIn('id="motion-transform-tempo-down-btn"', page)
            self.assertIn('id="motion-transform-tempo-up-btn"', page)
            self.assertIn('class="motion-training-arrow motion-training-arrow-down"', page)
            self.assertIn('data-range-step-target="motion-training-range-min"', page)
            self.assertIn('data-range-step-target="motion-training-range-max"', page)
            self.assertIn('id="motion-transform-range-btn"', page)
            self.assertIn('Duration and tempo', page)
            self.assertIn('id="play-motion-training-preview-btn"', page)
            self.assertIn('id="save-motion-training-pattern-btn"', page)
            self.assertIn('id="motion-training-feedback-up"', page)
            self.assertIn('Preview: Flexible position', page)
            self.assertIn('id="app-motion-backend-badge"', page)
            self.assertIn('App motion: HAMP continuous', page)
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
            self.assertIn("#motion-meter-panel", css)
            self.assertIn("#motion-feedback-buttons", css)
            self.assertIn("#sidebar-motion-indicator", css)
            self.assertIn("#handy-cylinder-indicator", css)
            self.assertIn("#handy-cylinder-range { position: absolute; left: 8px; right: 8px; top: 8%; height: 84%;", css)
            self.assertIn("#visualizer-box { width: min(440px, 100%);", css)
            self.assertIn(".settings-subsection { display: flex; flex-direction: column; gap: 12px;", css)
            self.assertIn(".settings-help", css)
            self.assertIn(".model-actions", css)
            self.assertIn(".motion-pattern-row", css)
            self.assertIn(".motion-pattern-list", css)
            self.assertIn("#dislike-this-move-btn", css)
            self.assertIn(".motion-pattern-weight-control", css)
            self.assertIn(".motion-pattern-weight-field", css)
            self.assertIn(".motion-training-workspace", css)
            self.assertIn(".motion-training-status", css)
            self.assertIn(".motion-training-preview-wrap", css)
            self.assertIn("#motion-training-preview-canvas", css)
            self.assertIn(".motion-backend-badge", css)
            self.assertIn(".motion-training-transform-panel", css)
            self.assertIn(".motion-training-control-section", css)
            self.assertIn(".motion-training-timing-grid", css)
            self.assertIn(".motion-training-timing-control", css)
            self.assertIn(".motion-training-icon-button", css)
            self.assertIn(".motion-training-arrow-up", css)
            self.assertIn(".motion-training-number-field", css)
            self.assertIn(".motion-training-number-stepper", css)
            self.assertIn(".motion-training-readout", css)
            self.assertIn(".motion-training-save-row", css)
            self.assertIn(".motion-training-feedback-row", css)
            self.assertIn(".setup-slider", css)
            self.assertIn(".preset-mode-stack", css)
            self.assertIn(".sidebar-stop-section", css)
            self.assertIn("@media (max-width: 760px)", css)
        finally:
            response.close()

    def test_frontend_js_avoids_incremental_inner_html_for_options(self):
        script = self.frontend_scripts()

        self.assertNotIn("innerHTML +=", script)
        self.assertIn("elevenLabsVoiceSelect.replaceChildren", script)
        self.assertIn("startHandyCylinderAnimation", script)
        self.assertIn("slider-container setup-slider", script)

    def test_frontend_js_polls_local_voice_status_and_serializes_playback(self):
        script = self.frontend_scripts()

        self.assertIn("localTtsStatusPolling: false", script)
        self.assertIn("async function refreshLocalTtsStatus", script)
        self.assertIn("preload_elapsed_seconds", script)
        self.assertIn("generation_elapsed_seconds", script)
        self.assertIn("audio.onended", script)
        self.assertIn("new Promise", script)

    def test_chat_messages_are_rendered_as_text_nodes(self):
        script = self.frontend_scripts()

        self.assertIn("function appendMessageText", script)
        self.assertIn("D.createTextNode", script)
        self.assertNotIn('message-bubble">${text}', script)

    def test_send_message_clears_typing_indicator_on_non_chat_statuses(self):
        script = self.frontend_scripts()

        self.assertIn("function clearTypingIndicator", script)
        self.assertIn("no_key_set", script)
        self.assertIn("message_relayed_to_active_mode", script)
        self.assertIn("addChatMessage('BOT', data.chat)", script)
        self.assertIn("data.chat_queued === false", script)
        self.assertIn("await pollChatUpdates()", script)

    def test_server_motion_request_detector_accepts_slowly(self):
        from strokegpt.web import _looks_like_motion_request

        self.assertTrue(_looks_like_motion_request("slowly focus on the tip"))

    def test_llm_context_includes_configured_speed_limits(self):
        from strokegpt.web import get_current_context, settings

        original_min_speed = settings.min_speed
        original_max_speed = settings.max_speed
        try:
            settings.min_speed = 15
            settings.max_speed = 55

            context = get_current_context()

            self.assertEqual(context["min_speed"], 15)
            self.assertEqual(context["max_speed"], 55)
        finally:
            settings.min_speed = original_min_speed
            settings.max_speed = original_max_speed

    def test_frontend_js_handles_motion_pattern_list_controls(self):
        script = self.frontend_scripts()

        self.assertIn("function renderMotionPatterns", script)
        self.assertIn("function renderMotionBackendOptions", script)
        self.assertIn("function cylinderAnimatedDepth", script)
        self.assertIn("function positionBackendAnimatedDepth", script)
        self.assertIn("function calibratedCylinderRange", script)
        self.assertIn("function activeStrokeZone", script)
        self.assertIn("startHandyCylinderAnimation", script)
        self.assertIn("Date.now() / 1000", script)
        self.assertIn("motion_observability", script)
        self.assertIn("physical_speed", script)
        self.assertIn("physical_depth", script)
        self.assertIn("stroke_zone", script)
        self.assertNotIn("el.handyCylinderRange.style.top", script)
        self.assertIn("full_travel_mm", script)
        self.assertIn("function updateMotionMeters", script)
        self.assertIn("function updateHandyCylinder", script)
        self.assertIn("handyCylinderPosition", script)
        self.assertIn("/set_motion_backend", script)
        self.assertIn("Flexible position/script", script)
        self.assertIn("refreshMotionPatterns", script)
        self.assertIn("/motion_patterns", script)
        self.assertIn("motionPatternList.replaceChildren", script)
        self.assertIn("motionTrainingPatternList.replaceChildren", script)
        self.assertIn("motionPatternImportInput", script)
        self.assertIn("FormData", script)
        self.assertIn("Import failed", script)
        self.assertIn("function openMotionTrainingWorkspace", script)
        self.assertIn("function drawMotionTrainingPreview", script)
        self.assertIn("function smoothEditedPattern", script)
        self.assertIn("function harshenEditedPattern", script)
        self.assertIn("function patternTempoScale", script)
        self.assertIn("function updateMotionTrainingTimingReadouts", script)
        self.assertIn("function setEditedPatternDuration", script)
        self.assertIn("function setEditedPatternTempo", script)
        self.assertIn("function stepMotionTrainingRangeInput", script)
        self.assertIn("tempo_scale", script)
        self.assertIn("editablePatternPayload", script)
        self.assertIn("(edited)", script)
        self.assertIn("/motion_training/preview", script)
        self.assertIn("/motion_patterns/save_generated", script)
        self.assertIn("/motion_training/start", script)
        self.assertIn("/motion_training/stop", script)
        self.assertIn("sendMotionTrainingFeedback", script)
        self.assertIn("thumbs_up", script)
        self.assertIn("function createPatternWeightControl", script)
        self.assertIn("function setMotionPatternWeight", script)
        self.assertIn("/motion_patterns/${encodeURIComponent(patternId)}/weight", script)
        self.assertIn("motion-training-number-step-up", script)
        self.assertIn("motion-training-number-step-down", script)
        self.assertIn("function dislikeLastMove", script)
        self.assertIn("/dislike_last_move", script)
        self.assertIn("weight ${pattern.weight", script)

    def test_frontend_js_is_split_into_domain_modules(self):
        response = self.client.get("/static/app.js")
        try:
            app_script = response.get_data(as_text=True)
        finally:
            response.close()

        self.assertIn("./js/settings.js", app_script)
        self.assertIn("./js/chat.js", app_script)
        self.assertIn("./js/audio.js", app_script)
        self.assertIn("./js/device-control.js", app_script)
        self.assertIn("./js/motion-control.js", app_script)
        self.assertIn("./js/setup.js", app_script)

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

    def test_motion_backend_can_be_selected_and_saved(self):
        from strokegpt.web import motion, settings

        original_setting = settings.motion_backend
        original_controller = motion.backend
        try:
            with mock.patch.object(settings, "save"):
                response = self.client.post("/set_motion_backend", json={"motion_backend": "position"})
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data["motion_backend"], "position")
                self.assertEqual(settings.motion_backend, "position")
                self.assertEqual(motion.backend, "position")

                response = self.client.get("/check_settings")
                payload = response.get_json()
                self.assertEqual(payload["motion_backend"], "position")
                self.assertTrue(any(item["experimental"] for item in payload["motion_backends"] if item["id"] == "position"))

                response = self.client.post("/set_motion_backend", json={"motion_backend": "bad"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["motion_backend"], "hamp")
                self.assertEqual(motion.backend, "hamp")
        finally:
            settings.motion_backend = original_setting
            motion.set_backend(original_controller)

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
