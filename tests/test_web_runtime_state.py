import types
import unittest
from unittest import mock

from tests._web_support import WebTestCase


class WebRuntimeStateTests(WebTestCase):
    def test_flask_default_static_route_is_disabled(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}

        self.assertNotIn("static", endpoints)

    def test_domain_routes_are_registered_through_blueprints(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}

        self.assertIn("settings.check_settings_route", endpoints)
        self.assertIn("motion.get_status_route", endpoints)
        self.assertIn("audio.get_audio_route", endpoints)
        self.assertIn("modes.start_edging_route", endpoints)

    def test_runtime_state_exports_bridge_to_app_state(self):
        import strokegpt.web as web

        original = (
            web.active_mode_name,
            web.active_mode_started_at,
            web.use_long_term_memory,
        )
        try:
            web.active_mode_name = "freestyle"
            web.active_mode_started_at = 123.0
            web.use_long_term_memory = False

            self.assertEqual(web.app_state.active_mode_name, "freestyle")
            self.assertEqual(web.app_state.active_mode_started_at, 123.0)
            self.assertFalse(web.app_state.use_long_term_memory)
            self.assertIs(web.messages_for_ui, web.app_state.messages_for_ui)
            self.assertIs(web.mode_message_queue, web.app_state.mode_message_queue)

            web.app_state.active_mode_name = "milking"
            self.assertEqual(web.active_mode_name, "milking")
        finally:
            (
                web.active_mode_name,
                web.active_mode_started_at,
                web.use_long_term_memory,
            ) = original

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

    def test_startup_url_uses_https_scheme_when_enabled(self):
        from strokegpt.web import _server_url

        self.assertEqual(_server_url("http", "127.0.0.1", 5000), "http://127.0.0.1:5000")
        self.assertEqual(_server_url("https", "0.0.0.0", 5011), "https://127.0.0.1:5011")

    def test_main_passes_https_context_to_flask(self):
        import strokegpt.web as web

        tls_config = types.SimpleNamespace(
            enabled=True,
            scheme="https",
            ssl_context=("cert.pem", "key.pem"),
            source="generated local certificate",
            cert_path=None,
        )
        with mock.patch.object(web.atexit, "register"), \
             mock.patch.object(web, "resolve_server_tls", return_value=tls_config), \
             mock.patch.object(web, "_select_bind_port", return_value=5011), \
             mock.patch.object(web.app, "run") as run, \
             mock.patch.dict(
                 "os.environ",
                 {"STROKEGPT_HOST": "0.0.0.0", "STROKEGPT_PORT": "5011"},
                 clear=True,
             ):
            web.main()

        run.assert_called_once_with(
            host="0.0.0.0",
            port=5011,
            debug=False,
            ssl_context=("cert.pem", "key.pem"),
        )

    def test_startup_browser_flag_is_opt_in(self):
        from strokegpt.web import _env_flag

        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(_env_flag("STROKEGPT_OPEN_BROWSER"))

        with mock.patch.dict("os.environ", {"STROKEGPT_OPEN_BROWSER": "1"}):
            self.assertTrue(_env_flag("STROKEGPT_OPEN_BROWSER"))

        with mock.patch.dict("os.environ", {"STROKEGPT_OPEN_BROWSER": "off"}):
            self.assertFalse(_env_flag("STROKEGPT_OPEN_BROWSER"))


if __name__ == "__main__":
    unittest.main()
