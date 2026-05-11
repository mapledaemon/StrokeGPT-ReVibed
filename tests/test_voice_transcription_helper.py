"""Pin the requestVoiceTranscription helper seam in voice-input.js.

Behavior contract:

- ``requestVoiceTranscription(blob, filename, message)`` owns the
  ``/transcribe_voice`` upload path, error handling, and status messages.
  It must NOT touch transcript-preview state, auto-submit state, or any
  caller-specific behavior; it just returns the parsed payload (or
  ``null`` on failure).
- ``transcribeVoiceBlob(blob)`` prepares the captured clip, then calls the
  helper and layers the existing live-recording behavior on top: populate
  settings, surface no-speech messages, and either auto-submit or show the
  preview.
- The split makes a future "transcribe without auto-submitting" caller
  trivial without re-implementing the network path. The split itself is
  behavior-preserving for the existing live-recording flow.

Tests are source-text assertions for this static seam. Runtime DOM behavior
belongs under ``tests/js/`` when a bug needs to execute the module.
"""

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VOICE_INPUT_JS = PROJECT_ROOT / "static" / "js" / "voice-input.js"


def _read(path):
    return path.read_text(encoding="utf-8")


def _function_body(source, signature_prefix):
    """Return the brace-matched body of the first function whose declaration
    starts with ``signature_prefix``. Walks past the parameter list (which
    can contain default-value braces or destructuring) before scanning for
    the body's opening brace, so assertions stay scoped to one function.
    """
    start = source.find(signature_prefix)
    if start < 0:
        raise AssertionError(f"declaration {signature_prefix!r} not found")

    paren_open = source.find("(", start)
    if paren_open < 0:
        raise AssertionError(f"opening paren not found after {signature_prefix!r}")
    depth = 0
    paren_close = -1
    for index in range(paren_open, len(source)):
        ch = source[index]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                paren_close = index
                break
    if paren_close < 0:
        raise AssertionError(f"unbalanced parens in signature of {signature_prefix!r}")

    open_brace = source.find("{", paren_close)
    if open_brace < 0:
        raise AssertionError(f"opening body brace not found after {signature_prefix!r}")
    depth = 0
    for index in range(open_brace, len(source)):
        ch = source[index]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace : index + 1]
    raise AssertionError(f"unbalanced braces in body of {signature_prefix!r}")


class VoiceTranscriptionHelperTests(unittest.TestCase):
    def setUp(self):
        self.script = _read(VOICE_INPUT_JS)

    def test_request_voice_transcription_helper_exists(self):
        self.assertRegex(
            self.script,
            r"async function requestVoiceTranscription\(\s*blob\s*,\s*filename\s*,\s*message\s*\)",
            "requestVoiceTranscription must accept (blob, filename, message)",
        )

    def test_helper_owns_the_transcribe_voice_upload(self):
        body = _function_body(
            self.script, "async function requestVoiceTranscription("
        )
        # Network seam is in the helper.
        self.assertIn("fetchWithConnectionState('/transcribe_voice'", body)
        self.assertIn("FormData", body)
        # Returns the payload on success and null on every failure path.
        self.assertEqual(
            body.count("return null"),
            3,
            f"expected three null-return paths (empty blob, !response.ok, "
            f"network catch); got {body.count('return null')} in:\n{body}",
        )
        self.assertRegex(body, r"return\s+payload\s*;", "must return parsed payload on success")

        # Helper must NOT do caller-specific work.
        for forbidden in (
            "submitVoiceTranscriptToChat",
            "showTranscriptPreview",
            "hideTranscriptPreview",
            "voiceInputSubmitMode",
            "slowAsrWarning",
        ):
            self.assertNotIn(
                forbidden,
                body,
                f"requestVoiceTranscription must not reference {forbidden!r}; "
                f"caller-specific behavior belongs in transcribeVoiceBlob.",
            )

    def test_transcribe_voice_blob_calls_helper_and_keeps_caller_behavior(self):
        body = _function_body(self.script, "async function transcribeVoiceBlob(")

        # Prepares the clip, then calls the helper; no longer drives the
        # upload directly.
        self.assertIn("prepareVoiceBlobForUpload(blob)", body)
        self.assertRegex(
            body,
            r"await requestVoiceTranscription\(\s*prepared\.blob\s*,\s*prepared\.filename\s*,",
            "transcribeVoiceBlob must call the requestVoiceTranscription helper",
        )
        self.assertNotIn(
            "fetchWithConnectionState('/transcribe_voice'",
            body,
            "transcribeVoiceBlob must not own the /transcribe_voice fetch directly anymore",
        )
        self.assertNotIn(
            "FormData",
            body,
            "FormData construction belongs in the helper",
        )

        # Caller-specific behaviors stay here.
        self.assertIn("submitVoiceTranscriptToChat", body)
        self.assertIn("voiceChatSourceForRecording(source)", body)
        self.assertIn("showTranscriptPreview(transcript, chatSource)", body)
        self.assertIn("showTranscriptPreview", body)
        self.assertIn("hideTranscriptPreview", body)
        self.assertIn("voiceInputSubmitMode", body)
        self.assertIn("slowAsrWarning", body)

    def test_helper_appears_before_caller(self):
        helper = self.script.find("async function requestVoiceTranscription(")
        caller = self.script.find("async function transcribeVoiceBlob(")
        self.assertGreaterEqual(helper, 0)
        self.assertGreaterEqual(caller, 0)
        self.assertLess(
            helper,
            caller,
            "requestVoiceTranscription must be defined before transcribeVoiceBlob "
            "so the function-declaration order matches the call dependency.",
        )

    def test_helper_is_behavior_preserving_for_live_recording_flow(self):
        """The test-clip UX from PR #100 stays out of master."""
        # No new IDs sneaking in.
        for new_ui in (
            "voice-input-test-clip-input",
            "test-voice-input-clip-btn",
            "voice-input-test-clip-control",
        ):
            self.assertNotIn(
                new_ui,
                self.script,
                f"this branch must not introduce {new_ui!r}; that UI is "
                f"intentionally not part of the helper-only refactor.",
            )


if __name__ == "__main__":
    unittest.main()
