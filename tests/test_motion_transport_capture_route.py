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
            {"path": "hsp/add", "ok": True, "body": {"points": 12, "flush": True}},
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
        self.assertEqual(capture["summary"]["path_counts"], {"hsp/add": 1, "hsp/play": 1})
        self.assertEqual([command["path"] for command in capture["handy_command_history"]], ["hsp/add", "hsp/play"])
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


if __name__ == "__main__":
    unittest.main()
