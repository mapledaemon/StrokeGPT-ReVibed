"""Pin reportSaveFailure wiring across motion + audio handlers.

Extends the audit started in ``tests/test_settings_write_feedback.py``
(which covers the three settings.js seeds) to the next batch of
handlers in ``static/js/motion-control.js``,
``static/js/motion/pattern-list.js``,
``static/js/motion/feedback-controls.js``, and ``static/js/audio.js``.

Each test confirms the handler's failure branch calls
``reportSaveFailure`` with a sensible target status element and a
fallback message describing the specific operation. Future PRs covering
the remaining handlers (mode start buttons, like/dislike, audio sample
upload, etc.) should extend this file rather than introduce a new one.
"""

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOTION_CONTROL_JS = PROJECT_ROOT / "static" / "js" / "motion-control.js"
PATTERN_LIST_JS = PROJECT_ROOT / "static" / "js" / "motion" / "pattern-list.js"
FEEDBACK_CONTROLS_JS = PROJECT_ROOT / "static" / "js" / "motion" / "feedback-controls.js"
AUDIO_JS = PROJECT_ROOT / "static" / "js" / "audio.js"


def _read(path):
    return path.read_text(encoding="utf-8")


def _function_body_by_header(source, header_pattern):
    match = re.search(header_pattern, source)
    if not match:
        raise AssertionError(f"header {header_pattern!r} not found")
    open_brace = source.find("{", match.start())
    if open_brace < 0:
        raise AssertionError(f"opening brace not found after {header_pattern!r}")
    depth = 0
    for index in range(open_brace, len(source)):
        ch = source[index]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace : index + 1]
    raise AssertionError(f"unbalanced braces after {header_pattern!r}")


def _assert_failure_wired(testcase, body, status_target, fallback_substring, label):
    testcase.assertRegex(
        body,
        r"\}\s*else\s*\{\s*reportSaveFailure\(",
        f"{label} must surface failure via reportSaveFailure",
    )
    testcase.assertIn(
        status_target,
        body,
        f"{label} must target {status_target!r} as the status element",
    )
    testcase.assertIn(
        fallback_substring,
        body,
        f"{label} fallback must mention {fallback_substring!r}",
    )


class MotionControlSaveFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.source = _read(MOTION_CONTROL_JS)

    def test_imports_report_save_failure(self):
        self.assertRegex(
            self.source,
            r"import\s*\{[^}]*reportSaveFailure[^}]*\}\s*from\s*['\"]\./context\.js['\"]",
        )

    def test_save_motion_backend_handles_failure(self):
        body = _function_body_by_header(self.source, r"async function saveMotionBackend\(\)")
        _assert_failure_wired(
            self,
            body,
            "el.motionBackendStatus",
            "Could not save motion backend",
            "saveMotionBackend",
        )

    def test_save_motion_speed_limits_handles_failure(self):
        body = _function_body_by_header(self.source, r"async function saveMotionSpeedLimits\(\)")
        _assert_failure_wired(
            self,
            body,
            "el.statusText",
            "Could not save speed limits",
            "saveMotionSpeedLimits",
        )

    def test_toggle_long_term_memory_handles_failure(self):
        body = _function_body_by_header(self.source, r"async function toggleLongTermMemory\(\)")
        _assert_failure_wired(
            self,
            body,
            "el.statusText",
            "Could not toggle long-term memory",
            "toggleLongTermMemory",
        )

    def test_save_mode_timings_handles_failure(self):
        body = _function_body_by_header(self.source, r"async function saveModeTimings\(\)")
        _assert_failure_wired(
            self,
            body,
            "el.statusText",
            "Could not save mode timings",
            "saveModeTimings",
        )


class PatternListSaveFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.source = _read(PATTERN_LIST_JS)

    def test_imports_report_save_failure(self):
        self.assertRegex(
            self.source,
            r"import\s*\{[^}]*reportSaveFailure[^}]*\}\s*from\s*['\"]\.\./context\.js['\"]",
        )

    def test_set_motion_pattern_enabled_handles_failure(self):
        body = _function_body_by_header(
            self.source,
            r"export async function setMotionPatternEnabled\(",
        )
        _assert_failure_wired(
            self,
            body,
            "el.motionPatternStatus",
            "Could not change pattern enablement",
            "setMotionPatternEnabled",
        )

    def test_set_motion_pattern_weight_handles_failure(self):
        body = _function_body_by_header(
            self.source,
            r"export async function setMotionPatternWeight\(",
        )
        _assert_failure_wired(
            self,
            body,
            "el.motionPatternStatus",
            "Could not save pattern weight",
            "setMotionPatternWeight",
        )

    def test_reset_motion_pattern_feedback_handles_failure(self):
        body = _function_body_by_header(
            self.source,
            r"export async function resetMotionPatternFeedback\(",
        )
        _assert_failure_wired(
            self,
            body,
            "el.motionPatternStatus",
            "Could not reset pattern feedback",
            "resetMotionPatternFeedback",
        )


class FeedbackControlsSaveFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.source = _read(FEEDBACK_CONTROLS_JS)

    def test_imports_report_save_failure(self):
        self.assertRegex(
            self.source,
            r"import\s*\{[^}]*reportSaveFailure[^}]*\}\s*from\s*['\"]\.\./context\.js['\"]",
        )

    def test_save_motion_feedback_options_handles_failure(self):
        body = _function_body_by_header(
            self.source,
            r"export async function saveMotionFeedbackOptions\(\)",
        )
        _assert_failure_wired(
            self,
            body,
            "el.motionPatternStatus",
            "Could not save feedback options",
            "saveMotionFeedbackOptions",
        )


class AudioSaveFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.source = _read(AUDIO_JS)

    def test_imports_report_save_failure(self):
        self.assertRegex(
            self.source,
            r"import\s*\{[^}]*reportSaveFailure[^}]*\}\s*from\s*['\"]\./context\.js['\"]",
        )

    def test_setup_eleven_labs_key_handles_failure(self):
        body = _function_body_by_header(
            self.source,
            r"async function setupElevenLabsKey\(\)",
        )
        _assert_failure_wired(
            self,
            body,
            "el.statusText",
            "Could not validate ElevenLabs API key",
            "setupElevenLabsKey",
        )


if __name__ == "__main__":
    unittest.main()
