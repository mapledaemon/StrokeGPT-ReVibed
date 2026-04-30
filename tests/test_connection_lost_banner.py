import re
import unittest
from pathlib import Path

from tests._web_support import WebTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "index.html"
APP_CSS = PROJECT_ROOT / "static" / "app.css"
CONTEXT_JS = PROJECT_ROOT / "static" / "js" / "context.js"


def _read(path):
    return path.read_text(encoding="utf-8")


def _function_body(source, signature_prefix):
    """Return the brace-matched body of the first function whose declaration
    starts with ``signature_prefix``. Walks past the parameter list (which
    can contain default-value braces like ``options = {}``) before looking
    for the body's opening brace, so assertions stay scoped to one function.
    """
    start = source.find(signature_prefix)
    if start < 0:
        raise AssertionError(f"declaration {signature_prefix!r} not found")

    # Skip the parameter list: balance parentheses from the first '(' so any
    # nested parens are ignored, then look for the body brace after it.
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


class ConnectionLostBannerSourceTests(unittest.TestCase):
    """Pin the contract for the connection-lost banner.

    Spec (KNOWN_PROBLEMS.md): when the Flask backend stops responding the UI
    must surface a persistent banner (not just a quickly-overwritten status
    line) so settings toggles, sliders, and feedback do not silently fail.
    The banner must hide automatically once the backend is reachable again.
    """

    def setUp(self):
        self.index_html = _read(INDEX_HTML)
        self.app_css = _read(APP_CSS)
        self.context_js = _read(CONTEXT_JS)

    def test_index_html_declares_banner(self):
        # The banner must be in the body markup so it cannot be lost by a
        # script that fails to load. Hidden by default and announced by
        # screen readers when shown.
        self.assertIn('id="connection-lost-banner"', self.index_html)
        self.assertIn('role="alert"', self.index_html)
        self.assertIn('aria-live="assertive"', self.index_html)

        banner_match = re.search(
            r'<div id="connection-lost-banner"[^>]*>',
            self.index_html,
        )
        self.assertIsNotNone(banner_match, "banner opening tag must be a single div element")
        self.assertIn(" hidden", banner_match.group(0), "banner must be hidden by default")

    def test_app_css_styles_banner_and_hides_it(self):
        self.assertIn("#connection-lost-banner", self.app_css)
        self.assertIn(
            "#connection-lost-banner[hidden]",
            self.app_css,
            "the [hidden] selector must be styled so display:none wins over the "
            "fixed-position visible rule",
        )
        # Fixed-position so the banner is always visible regardless of scroll.
        banner_rule_match = re.search(
            r"#connection-lost-banner\s*\{[^}]*\}",
            self.app_css,
        )
        self.assertIsNotNone(banner_rule_match)
        rule = banner_rule_match.group(0)
        self.assertIn("position: fixed", rule)
        self.assertIn("z-index", rule)

    def test_context_js_tracks_connection_lost_state(self):
        self.assertIn("connectionLost: false", self.context_js)
        self.assertIn(
            "connectionLostBanner: D.getElementById('connection-lost-banner')",
            self.context_js,
        )

    def test_set_connection_lost_toggles_banner_idempotently(self):
        body = _function_body(self.context_js, "export function setConnectionLost(")
        # Idempotency guard: do not flip the banner attribute if state is unchanged.
        self.assertIn("state.connectionLost === next", body)
        self.assertIn("state.connectionLost = next", body)
        # The banner element may be missing during early init or in tests; the
        # writer must guard for that without throwing.
        self.assertIn("if (el.connectionLostBanner)", body)
        self.assertIn("el.connectionLostBanner.hidden = !next", body)
        self.assertIn("syncBackendRequiredControls()", body)

    def test_api_call_distinguishes_network_failure_from_http_error(self):
        body = _function_body(self.context_js, "export async function apiCall(")
        fetch_body = _function_body(self.context_js, "export async function fetchWithConnectionState(")

        # apiCall delegates the raw fetch to fetchWithConnectionState so direct
        # fetch users and JSON callers share the same connection-lost behavior.
        self.assertIn("fetchWithConnectionState(endpoint, options)", body)

        # The three load-bearing positions across the fetch helper and apiCall.
        catch_index = fetch_body.find("catch (error)")
        success_clear_index = fetch_body.find("setConnectionLost(false)")
        http_error_index = body.find("if (!response.ok)")
        for label, index in (
            ("catch (error)", catch_index),
            ("setConnectionLost(false)", success_clear_index),
            ("if (!response.ok)", http_error_index),
        ):
            self.assertGreaterEqual(index, 0, f"expected {label!r} in connection-aware fetch path")

        # Network failure path: a setConnectionLost(true) call must live inside
        # the catch block, while successful fetches clear the banner before
        # apiCall inspects HTTP status codes.
        set_lost_true_index = fetch_body.find("setConnectionLost(true)")
        self.assertGreater(
            set_lost_true_index,
            catch_index,
            "setConnectionLost(true) must live inside the catch block",
        )

        self.assertLess(success_clear_index, fetch_body.find("return response"))

        # HTTP error branch must return undefined without flipping the banner
        # back on; extract it by brace-matching from the if header.
        http_error_open = body.index("{", http_error_index)
        depth = 0
        http_error_close = -1
        for index in range(http_error_open, len(body)):
            ch = body[index]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    http_error_close = index
                    break
        self.assertGreater(http_error_close, http_error_open, "unbalanced !response.ok block")
        http_error_block = body[http_error_open : http_error_close + 1]
        self.assertIn("return undefined", http_error_block)
        self.assertNotIn(
            "setConnectionLost(true)",
            http_error_block,
            "an HTTP error from a reachable backend must not show the banner",
        )


class ConnectionLostBannerRenderTests(WebTestCase):
    def test_root_page_renders_connection_lost_banner(self):
        response = self.client.get("/")
        try:
            page = response.get_data(as_text=True)
            self.assertIn('id="connection-lost-banner"', page)
            self.assertIn('role="alert"', page)
            self.assertIn('aria-live="assertive"', page)
            # Banner must be hidden by default so it does not flash on every load.
            banner_match = re.search(
                r'<div id="connection-lost-banner"[^>]*>',
                page,
            )
            self.assertIsNotNone(banner_match)
            self.assertIn(" hidden", banner_match.group(0))
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()
