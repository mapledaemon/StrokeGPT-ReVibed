import unittest

from tests._web_support import WebTestCase


class WebRuntimeStateTests(WebTestCase):
    def test_flask_default_static_route_is_disabled(self):
        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}

        self.assertNotIn("static", endpoints)

    def test_domain_routes_are_registered_through_blueprints(self):
        import strokegpt.web as web

        endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}

        self.assertIn("settings.check_settings_route", endpoints)
        self.assertIn("motion.get_status_route", endpoints)
        self.assertIn("audio.get_audio_route", endpoints)
        self.assertIn("modes.start_edging_route", endpoints)
        self.assertIs(web.check_settings_route, web.settings_routes.check_settings_route)
        self.assertIs(web.get_status_route, web.motion_routes.get_status_route)

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


if __name__ == "__main__":
    unittest.main()
