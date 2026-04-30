import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "index.html"
APP_JS = PROJECT_ROOT / "static" / "app.js"
APP_CSS = PROJECT_ROOT / "static" / "app.css"
CONTEXT_JS = PROJECT_ROOT / "static" / "js" / "context.js"
AUDIO_JS = PROJECT_ROOT / "static" / "js" / "audio.js"
MOTION_CONTROL_JS = PROJECT_ROOT / "static" / "js" / "motion-control.js"
PATTERN_LIST_JS = PROJECT_ROOT / "static" / "js" / "motion" / "pattern-list.js"
SETUP_JS = PROJECT_ROOT / "static" / "js" / "setup.js"


def _read(path):
    return path.read_text(encoding="utf-8")


def _opening_tag(source, element_id):
    pattern = rf"<[^>]+id=\"{re.escape(element_id)}\"[^>]*>"
    match = re.search(pattern, source)
    if not match:
        raise AssertionError(f"opening tag for {element_id!r} not found")
    return match.group(0)


class BackendRequiredControlLockTests(unittest.TestCase):
    """Pin the connection-lost control-lock contract.

    Read-only navigation remains usable after the backend disappears, while
    controls that send writes/actions are marked with data-requires-backend and
    are disabled by the shared connection-state guard.
    """

    def setUp(self):
        self.index_html = _read(INDEX_HTML)
        self.app_js = _read(APP_JS)
        self.app_css = _read(APP_CSS)
        self.context_js = _read(CONTEXT_JS)
        self.audio_js = _read(AUDIO_JS)
        self.motion_control_js = _read(MOTION_CONTROL_JS)
        self.pattern_list_js = _read(PATTERN_LIST_JS)
        self.setup_js = _read(SETUP_JS)

    def test_context_exports_shared_backend_required_lock(self):
        self.assertIn("export const BACKEND_REQUIRED_SELECTOR = '[data-requires-backend]'", self.context_js)
        self.assertIn("export function applyBackendRequiredControlState(", self.context_js)
        self.assertIn("export function syncBackendRequiredControls(", self.context_js)
        self.assertIn("export function markRequiresBackend(", self.context_js)
        self.assertIn("export function initBackendRequiredControlGuard(", self.context_js)
        self.assertIn("control.disabled = true", self.context_js)
        self.assertIn("control.dataset.backendPreviousDisabled", self.context_js)
        self.assertIn("control.dataset.backendLocked", self.context_js)
        self.assertIn("MutationObserver", self.context_js)
        self.assertIn("blockBackendRequiredInteraction", self.context_js)

    def test_app_initializes_backend_required_guard(self):
        self.assertIn("initBackendRequiredControlGuard", self.app_js)
        self.assertRegex(
            self.app_js,
            r"function\s+initApp\s*\(\)\s*\{[^}]*initBackendRequiredControlGuard\(\)",
            "backend-required guard must initialize before the app starts polling",
        )

    def test_static_backend_action_controls_are_marked(self):
        required_ids = [
            "user-chat-input",
            "send-chat-btn",
            "like-this-move-btn",
            "dislike-this-move-btn",
            "pause-resume-btn",
            "start-auto-btn",
            "stop-auto-btn",
            "toggle-memory-btn",
            "edging-mode-btn",
            "milking-mode-btn",
            "freestyle-mode-btn",
            "emergency-stop-all-btn",
            "audio-provider-select",
            "enable-audio-checkbox",
            "set-elevenlabs-key-button",
            "elevenlabs-voice-select-box",
            "set-local-tts-button",
            "download-local-tts-model-button",
            "test-local-tts-button",
            "save-handy-key-btn",
            "motion-depth-min-slider",
            "motion-depth-max-slider",
            "test-motion-depth-range",
            "save-motion-depth-range",
            "save-motion-backend-btn",
            "save-motion-speed-limits",
            "save-timings-btn",
            "motion-feedback-auto-disable-checkbox",
            "refresh-motion-patterns-btn",
            "import-motion-pattern-btn",
            "play-motion-training-preview-btn",
            "save-motion-training-pattern-btn",
            "motion-training-feedback-up",
            "motion-training-feedback-neutral",
            "motion-training-feedback-down",
            "reset-settings-btn",
        ]
        for element_id in required_ids:
            with self.subTest(element_id=element_id):
                self.assertIn("data-requires-backend", _opening_tag(self.index_html, element_id))

    def test_navigation_controls_remain_usable_without_backend(self):
        navigation_ids = [
            "toggle-sidebar-btn",
            "open-settings-btn",
            "close-settings-btn",
            "refresh-model-field-btn",
            "open-motion-training-btn",
            "close-motion-training-btn",
        ]
        for element_id in navigation_ids:
            with self.subTest(element_id=element_id):
                self.assertNotIn("data-requires-backend", _opening_tag(self.index_html, element_id))

    def test_dynamic_backend_controls_are_marked_when_created(self):
        self.assertIn("markRequiresBackend(resetButton)", self.pattern_list_js)
        self.assertIn("markRequiresBackend(input)", self.pattern_list_js)
        self.assertIn("markRequiresBackend(button)", self.pattern_list_js)
        self.assertIn("markRequiresBackend(checkbox)", self.pattern_list_js)
        self.assertIn("markRequiresBackend(playButton)", self.motion_control_js)
        self.assertIn('id="setup-key" class="input-text" placeholder="Handy Key" data-requires-backend', self.setup_js)
        self.assertIn('id="test-depth-range" class="my-button" data-requires-backend', self.setup_js)
        self.assertIn('id="set-speed" class="my-button" data-requires-backend', self.setup_js)

    def test_direct_fetch_paths_update_connection_state(self):
        self.assertIn("fetchWithConnectionState('/upload_local_tts_sample'", self.audio_js)
        self.assertIn("fetchWithConnectionState('/get_audio'", self.audio_js)
        self.assertIn("fetchWithConnectionState(endpoint, options)", self.motion_control_js)
        self.assertIn("fetchWithConnectionState('/import_motion_pattern'", self.motion_control_js)

    def test_css_includes_backend_locked_state(self):
        self.assertIn('[data-backend-locked="true"]', self.app_css)


if __name__ == "__main__":
    unittest.main()
