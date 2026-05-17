import unittest
from unittest import mock

from tests._web_support import WebTestCase


def _diagnostics(command_history, **updates):
    payload = {
        "relative_speed": 50,
        "physical_speed": 120,
        "depth": 50,
        "range": 60,
        "firmware_version": "fw4",
        "api_v3_enabled": True,
        "api_v3_key_configured": True,
        "api_v3_auth_failed": False,
        "api_v3_unavailable_reason": "",
        "continuous_streaming_supported": True,
        "last_command": command_history[-1] if command_history else None,
        "command_history": list(command_history),
    }
    payload.update(updates)
    return payload


def _observability(trace, **updates):
    payload = {
        "backend": "continuous",
        "source": "test",
        "label": "test motion",
        "playback_active": True,
        "last_command_time": 123.0,
        "trace": list(trace),
    }
    payload.update(updates)
    return payload


class MotionTransportCaptureRouteTests(WebTestCase):
    def tearDown(self):
        self.client.post("/motion_transport_capture", json={"action": "cancel"})

    def test_motion_transport_capture_slices_new_hsp_commands(self):
        from strokegpt.web import handy, motion

        before_commands = [{"path": "slide", "ok": True}]
        after_commands = [
            *before_commands,
            {
                "path": "hsp/add",
                "ok": True,
                "elapsed_ms": 115.4,
                "body": {
                    "points": 16,
                    "points_preview": [
                        {"t": 0, "x": 50},
                        {"t": 50, "x": 56},
                        {"t": 100, "x": 63},
                    ],
                    "points_tail_preview": [
                        {"t": 650, "x": 44},
                        {"t": 700, "x": 50},
                    ],
                    "points_truncated": True,
                    "flush": True,
                    "tail_point_stream_index": 16,
                },
                "response": {
                    "hsp_state": {
                        "current_time_ms": 25,
                        "current_point": 1,
                        "points": 16,
                        "play_state": "playing",
                    }
                },
            },
            {"path": "hsp/play", "ok": True, "body": {"start_time": 0, "playback_rate": 1}},
        ]
        before_trace = [{"label": "old", "depth": 50}]
        after_trace = [
            *before_trace,
            {"label": "flick", "continuous_schema": "hsp", "hsp_point_time_ms": 120, "depth": 65},
        ]

        with mock.patch.object(handy, "diagnostics", side_effect=[
            _diagnostics(before_commands),
            _diagnostics(after_commands),
        ]), mock.patch.object(motion, "observability_snapshot", side_effect=[
            _observability(before_trace),
            _observability(after_trace),
        ]):
            start_response = self.client.post("/motion_transport_capture", json={"action": "start"})
            finish_response = self.client.post("/motion_transport_capture", json={"action": "finish"})

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(finish_response.status_code, 200)
        payload = finish_response.get_json()
        self.assertEqual(payload["status"], "success")
        capture = payload["capture"]
        self.assertEqual(capture["summary"]["status"], "ok")
        self.assertEqual(capture["summary"]["hsp_commands"], 2)
        self.assertEqual(capture["summary"]["hsp_add_batches"], 1)
        self.assertEqual(capture["summary"]["hsp_add_max_preview_gap_ms"], 550)
        self.assertEqual(capture["summary"]["hsp_add_max_preview_delta"], 19)
        self.assertEqual(capture["summary"]["path_counts"], {"hsp/add": 1, "hsp/play": 1})
        self.assertEqual([command["path"] for command in capture["handy_command_history"]], ["hsp/add", "hsp/play"])
        self.assertEqual(capture["hsp_add_stats"][0]["point_count"], 16)
        self.assertTrue(capture["hsp_add_stats"][0]["preview_partial"])
        self.assertTrue(capture["hsp_add_stats"][0]["flush"])
        self.assertEqual(capture["hsp_add_stats"][0]["preview_max_gap_ms"], 550)
        self.assertEqual(capture["hsp_add_stats"][0]["hsp_state"]["current_time_ms"], 25)
        self.assertEqual(len(capture["motion_trace"]), 1)
        self.assertEqual(capture["motion_trace"][0]["continuous_schema"], "hsp")
        self.assertNotIn("command_history", capture["before"])
        self.assertNotIn("command_history", capture["after"])

    def test_motion_transport_capture_warns_on_hdsp_fallback(self):
        from strokegpt.web import handy, motion

        with mock.patch.object(handy, "diagnostics", return_value=_diagnostics([
            {"path": "hdsp/xpt", "ok": True, "body": {"xp": 0.5, "t": 160}},
        ])), mock.patch.object(motion, "observability_snapshot", return_value=_observability([
            {"label": "fallback", "backend": "continuous", "depth": 50},
        ])):
            response = self.client.post("/motion_transport_capture", json={"action": "snapshot"})

        self.assertEqual(response.status_code, 200)
        capture = response.get_json()["capture"]
        self.assertEqual(capture["summary"]["status"], "warning")
        self.assertEqual(capture["summary"]["hdsp_commands"], 1)
        self.assertIn("HDSP", capture["summary"]["message"])

    def test_motion_transport_capture_reports_missing_v3_key_fallback(self):
        from strokegpt.web import handy, motion

        diagnostics = _diagnostics(
            [{"path": "hdsp/xava", "ok": True, "body": {"position": 50, "velocity": 40}}],
            api_v3_enabled=False,
            api_v3_key_configured=False,
            continuous_streaming_supported=False,
            api_v3_unavailable_reason="missing_api_v3_key",
        )
        trace = _observability([
            {
                "label": "continuous fallback",
                "backend": "continuous",
                "continuous_schema": "hdsp_fallback",
                "continuous_fallback_reason": "missing_api_v3_key",
            },
        ])

        with mock.patch.object(handy, "diagnostics", return_value=diagnostics), mock.patch.object(
            motion, "observability_snapshot", return_value=trace
        ):
            response = self.client.post("/motion_transport_capture", json={"action": "snapshot"})

        self.assertEqual(response.status_code, 200)
        capture = response.get_json()["capture"]
        self.assertEqual(capture["summary"]["status"], "warning")
        self.assertIn("no Handy API v3 Application ID", capture["summary"]["message"])
        self.assertFalse(capture["summary"]["api_v3_enabled"])
        self.assertFalse(capture["summary"]["api_v3_key_configured"])
        self.assertEqual(capture["summary"]["api_v3_unavailable_reason"], "missing_api_v3_key")
        self.assertEqual(capture["summary"]["continuous_schemas"], ["hdsp_fallback"])


if __name__ == "__main__":
    unittest.main()
