"""Source-text pins for the settings-write feedback contract.

Behavioral assertions live in ``tests/js/settings_save_feedback.test.mjs``
(driven via ``tests/test_frontend_runtime.py``). These Python source-text
tests cover the parts a runtime test cannot easily express:

- the helper is exported from ``context.js`` so other modules can import
  it without reaching into private state,
- the helper is named consistently and has the documented contract
  (skip on success, skip on undefined, surface server message otherwise),
- ``apiCall``'s HTTP-error branch parses the server's JSON body and
  surfaces ``message`` so the global statusText shows useful detail,
- the wired settings handlers actually call the helper instead of
  silently swallowing the failure.

Mirrors the source-text style established in
``tests/test_frontend_chat_statuses.py``,
``tests/test_motion_status_log_timecodes.py``,
``tests/test_connection_lost_banner.py``,
``tests/test_voice_transcription_helper.py``. Behavioral coverage runs
via Node:test when Node 20+ is available; this file fills the gap on
Python-only environments.
"""

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTEXT_JS = PROJECT_ROOT / "static" / "js" / "context.js"
SETTINGS_JS = PROJECT_ROOT / "static" / "js" / "settings.js"


def _read(path):
    return path.read_text(encoding="utf-8")


def _function_body(source, signature_prefix):
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


class ReportSaveFailureHelperTests(unittest.TestCase):
    def setUp(self):
        self.context_js = _read(CONTEXT_JS)

    def test_helper_is_exported_from_context_js(self):
        self.assertRegex(
            self.context_js,
            r"export\s+function\s+reportSaveFailure\s*\(",
            "reportSaveFailure must be an exported top-level function in context.js",
        )

    def test_helper_signature_takes_status_el_data_and_fallback(self):
        match = re.search(
            r"export\s+function\s+reportSaveFailure\s*\(\s*([^)]*)\)",
            self.context_js,
        )
        self.assertIsNotNone(match)
        params = [p.strip() for p in match.group(1).split(",")]
        self.assertEqual(len(params), 3, f"expected 3 parameters, got: {params!r}")
        self.assertEqual(params[0], "statusEl")
        self.assertEqual(params[1], "data")
        self.assertTrue(
            params[2].startswith("fallbackMessage"),
            f"third param should be fallbackMessage with optional default; got: {params[2]!r}",
        )

    def test_helper_skips_when_status_el_is_missing_or_data_is_undefined(self):
        body = _function_body(self.context_js, "export function reportSaveFailure(")
        # Defensive against a missing element.
        self.assertIn("if (!statusEl) return", body)
        # Network/HTTP error path was already covered by apiCall + banner.
        self.assertIn("if (data === undefined) return", body)
        # Success path is the caller's responsibility.
        self.assertRegex(body, r"data\.status === 'success'\s*\)\s*return")

    def test_helper_paints_yellow_and_uses_server_message_when_present(self):
        body = _function_body(self.context_js, "export function reportSaveFailure(")
        # Caller-supplied or server-supplied message.
        self.assertIn("data.message", body)
        self.assertIn("fallbackMessage", body)
        # Yellow is the failure color in this app's palette.
        self.assertIn("var(--yellow)", body)


class ApiCallHttpErrorBodyTests(unittest.TestCase):
    """Pin that ``apiCall``'s !response.ok branch surfaces the server's
    JSON ``message`` field instead of dropping it for the generic line."""

    def setUp(self):
        self.context_js = _read(CONTEXT_JS)

    def test_http_error_branch_attempts_to_parse_body(self):
        body = _function_body(self.context_js, "export async function apiCall(")
        # Locate the !response.ok block.
        match = re.search(
            r"if \(!response\.ok\)\s*\{",
            body,
        )
        self.assertIsNotNone(match)
        block_start = match.start()
        # Within the body following that header, we expect a try/catch
        # around response.clone().json() and a serverMessage variable.
        tail = body[block_start:]
        self.assertIn("response.clone()", tail, "must clone before parsing so the body remains readable")
        self.assertIn(".json()", tail)
        self.assertIn("serverMessage", tail)

    def test_http_error_branch_falls_back_to_generic_message(self):
        body = _function_body(self.context_js, "export async function apiCall(")
        # The fallback string must remain in place for the case where the
        # response body is missing, empty, or non-JSON.
        self.assertIn("Error: server returned", body)

    def test_http_error_branch_still_returns_undefined(self):
        # Existing contract preserved: tests/test_connection_lost_banner.py
        # asserts apiCall returns undefined on HTTP error so the caller's
        # `if (data && data.status === 'success')` short-circuits.
        body = _function_body(self.context_js, "export async function apiCall(")
        match = re.search(r"if \(!response\.ok\)\s*\{", body)
        self.assertIsNotNone(match)
        block = body[match.start():]
        self.assertIn("return undefined", block)


class SettingsHandlerWiringTests(unittest.TestCase):
    """Pin that the wired settings.js handlers actually call the helper.

    Only three handlers are wired in this branch (setPersonaPrompt,
    setOllamaModel, saveDiagnosticsLevels) as the template; future PRs
    extend the pattern to motion-control.js, audio.js, etc.
    """

    def setUp(self):
        self.settings_js = _read(SETTINGS_JS)

    def test_settings_imports_report_save_failure(self):
        self.assertRegex(
            self.settings_js,
            r"import\s*\{[^}]*reportSaveFailure[^}]*\}\s*from\s*['\"]\./context\.js['\"]",
            "settings.js must import reportSaveFailure from ./context.js",
        )

    def test_set_persona_prompt_handles_failure(self):
        body = _function_body(self.settings_js, "export async function setPersonaPrompt(")
        # The success branch is unchanged; the new else branch must call
        # the helper with el.statusText and a meaningful fallback.
        self.assertRegex(
            body,
            r"\}\s*else\s*\{\s*reportSaveFailure\(",
            "setPersonaPrompt must surface failure via reportSaveFailure",
        )
        self.assertIn("el.statusText", body)
        self.assertIn("Persona prompt save failed", body)

    def test_save_diagnostics_levels_handles_failure(self):
        # saveDiagnosticsLevels is module-private so we inspect by header.
        match = re.search(
            r"async function saveDiagnosticsLevels\(\)\s*\{",
            self.settings_js,
        )
        self.assertIsNotNone(match)
        # Find the matching close brace.
        index = self.settings_js.find("{", match.start())
        depth = 0
        for i in range(index, len(self.settings_js)):
            if self.settings_js[i] == "{":
                depth += 1
            elif self.settings_js[i] == "}":
                depth -= 1
                if depth == 0:
                    body = self.settings_js[index : i + 1]
                    break
        else:
            self.fail("could not locate saveDiagnosticsLevels body")
        self.assertIn("reportSaveFailure(el.statusText", body)
        self.assertIn("Diagnostics settings save failed", body)

    def test_set_ollama_model_handles_failure(self):
        match = re.search(
            r"async function setOllamaModel\(model\)\s*\{",
            self.settings_js,
        )
        self.assertIsNotNone(match)
        index = self.settings_js.find("{", match.start())
        depth = 0
        for i in range(index, len(self.settings_js)):
            if self.settings_js[i] == "{":
                depth += 1
            elif self.settings_js[i] == "}":
                depth -= 1
                if depth == 0:
                    body = self.settings_js[index : i + 1]
                    break
        else:
            self.fail("could not locate setOllamaModel body")
        self.assertIn("reportSaveFailure(el.ollamaModelStatus", body)
        self.assertIn("Could not set model", body)


if __name__ == "__main__":
    unittest.main()
