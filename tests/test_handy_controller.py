import importlib.machinery
import sys
import types
import unittest
from unittest import mock

requests_module = types.ModuleType("requests")
requests_module.__spec__ = importlib.machinery.ModuleSpec("requests", loader=None)
requests_module.exceptions = types.SimpleNamespace(RequestException=Exception)
sys.modules.setdefault("requests", requests_module)

import strokegpt.handy as handy_module
from strokegpt.handy import HandyController


class RecordingHandyController(HandyController):
    def __init__(self):
        super().__init__(handy_key="test", firmware_version="fw3")
        self.commands = []

    def _send_command(self, path, body=None):
        self.commands.append((path, body or {}))
        self._record_command_result(path, body, ok=True, status_code=204, elapsed_ms=0)
        return True


class RecordingV3HandyController(RecordingHandyController):
    def __init__(self):
        super().__init__()
        self.set_firmware_version("fw4")
        self.set_handy_api_key("app-id")
        self.v3_commands = []

    def _send_v3_command(self, path, body=None):
        self.v3_commands.append((path, body or {}))
        self._record_command_result(path, body, ok=True, status_code=200, elapsed_ms=0)
        return True

    def _estimated_server_time_ms(self, **_kwargs):
        return 123456


class ThresholdFailingV3HandyController(RecordingV3HandyController):
    def _send_v3_command(self, path, body=None):
        self.v3_commands.append((path, body or {}))
        if path == "hsp/threshold":
            self._record_command_result(path, body, ok=False, status_code=503, error="threshold unavailable")
            return False
        self._record_command_result(path, body, ok=True, status_code=200, elapsed_ms=0)
        return True


class RecordingBluetoothBridge:
    def __init__(self, *, ok=True, error="", response=None):
        self.commands = []
        self.ok = ok
        self.error = error
        self.response = response or {}

    def is_ready(self):
        return True

    def send_command(self, path, body=None):
        self.commands.append((path, body or {}))
        result = {"ok": self.ok, "elapsed_ms": 2.0}
        if self.error:
            result["error"] = self.error
        if self.response:
            result["response"] = self.response
        return result

    def snapshot(self):
        return {
            "transport": "browser_bluetooth",
            "connected": True,
            "status": "connected",
            "pending": 0,
            "inflight": 0,
        }


class StaleClockV3HandyController(RecordingV3HandyController):
    def _send_v3_command(self, path, body=None):
        self.v3_commands.append((path, body or {}))
        payload = None
        if path in {"hsp/add", "hsp/threshold"}:
            payload = {
                "hsp_state": {
                    "current_time_ms": 1403836,
                    "last_point_time_ms": 32160,
                    "points": 58,
                    "current_point": 58,
                    "play_state": 4,
                }
            }
        self._record_command_result(path, body, ok=True, status_code=200, elapsed_ms=0, response_payload=payload)
        return True


class FakeResponse:
    def __init__(self, status_code=204, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        return None

    def json(self):
        return dict(self.payload)

    def close(self):
        self.closed = True


class FakeSseResponse(FakeResponse):
    def __init__(self, lines, status_code=200):
        super().__init__(status_code=status_code)
        self.lines = list(lines)

    def iter_lines(self, decode_unicode=False):
        for line in self.lines:
            if decode_unicode:
                yield line
            else:
                yield str(line).encode("utf-8")


class HandyControllerTests(unittest.TestCase):
    def test_move_skips_exact_duplicate_device_commands(self):
        handy = RecordingHandyController()

        handy.move(50, 50, 50)
        handy.move(50, 50, 50)

        self.assertEqual(
            [path for path, _body in handy.commands],
            ["mode", "hamp/start", "slide", "hamp/velocity"],
        )

    def test_move_still_sends_changed_velocity_without_resending_same_slide(self):
        handy = RecordingHandyController()

        handy.move(50, 50, 50)
        handy.move(75, 50, 50)

        self.assertEqual([path for path, _body in handy.commands].count("slide"), 1)
        self.assertEqual([path for path, _body in handy.commands].count("hamp/velocity"), 2)

    def test_move_lowers_velocity_before_changing_slide_bounds(self):
        handy = RecordingHandyController()

        handy.move(100, 50, 80)
        handy.commands.clear()
        handy.move(20, 10, 36)

        self.assertEqual(
            [path for path, _body in handy.commands],
            ["hamp/velocity", "slide"],
        )

    def test_move_raises_velocity_after_changing_slide_bounds(self):
        handy = RecordingHandyController()

        handy.move(20, 50, 80)
        handy.commands.clear()
        handy.move(80, 10, 36)

        self.assertEqual(
            [path for path, _body in handy.commands],
            ["slide", "hamp/velocity"],
        )

    def test_stop_clears_motion_cache_so_next_move_reapplies_bounds(self):
        handy = RecordingHandyController()

        handy.move(50, 50, 50)
        handy.stop()
        handy.move(50, 50, 50)

        self.assertEqual([path for path, _body in handy.commands].count("slide"), 2)
        self.assertEqual([path for path, _body in handy.commands].count("hamp/velocity"), 2)

    def test_stop_switches_from_hdsp_to_hamp_before_stopping(self):
        handy = RecordingHandyController()
        handy.move_to_depth(50, 70)
        handy.commands.clear()

        handy.stop()

        self.assertEqual([path for path, _body in handy.commands], ["mode", "hamp/stop"])
        self.assertEqual(handy.commands[0][1], {"mode": 0})
        self.assertEqual(handy.diagnostics()["mode"], 0)

    def test_diagnostics_report_cached_motion_state(self):
        handy = RecordingHandyController()

        handy.move(50, 60, 70)

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["relative_speed"], 50)
        self.assertEqual(diagnostics["physical_speed"], 50)
        self.assertEqual(diagnostics["depth"], 60)
        self.assertEqual(diagnostics["physical_depth"], 60)
        self.assertEqual(diagnostics["position_mm"], 66.0)
        self.assertEqual(diagnostics["range"], 70)
        self.assertEqual(diagnostics["calibrated_range"], {"min": 0, "max": 100})
        self.assertEqual(diagnostics["stroke_zone"], {"min": 25, "max": 95})
        self.assertEqual(diagnostics["full_travel_mm"], handy.FULL_TRAVEL_MM)
        self.assertEqual(diagnostics["slide_bounds"], {"min": 5, "max": 75})
        self.assertEqual(diagnostics["velocity"], 50)
        self.assertTrue(diagnostics["hamp_started"])
        self.assertEqual(diagnostics["last_command"]["path"], "hamp/velocity")
        self.assertTrue(diagnostics["last_command"]["ok"])
        self.assertEqual(diagnostics["last_command"]["status_code"], 204)
        self.assertEqual(
            [command["path"] for command in diagnostics["command_history"]],
            ["mode", "hamp/start", "slide", "hamp/velocity"],
        )

    def test_send_command_records_success_without_secret_headers(self):
        handy = HandyController(handy_key="secret")

        with mock.patch(
            "strokegpt.handy.requests.put",
            return_value=FakeResponse(status_code=204),
            create=True,
        ) as put:
            self.assertTrue(handy._send_command("hdsp/xava", {"position": 22.5, "velocity": 40}))

        _args, kwargs = put.call_args
        self.assertEqual(kwargs["headers"]["X-Connection-Key"], "secret")
        diagnostics = handy.diagnostics()
        self.assertEqual(
            diagnostics["last_command"],
            {
                "path": "hdsp/xava",
                "ok": True,
                "status_code": 204,
                "elapsed_ms": diagnostics["last_command"]["elapsed_ms"],
                "body": {"position": 22.5, "velocity": 40},
            },
        )
        self.assertNotIn("secret", str(diagnostics["last_command"]))

    def test_send_v3_command_uses_app_key_for_v3_auth(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")

        with mock.patch(
            "strokegpt.handy.requests.put",
            return_value=FakeResponse(status_code=200),
            create=True,
        ) as put:
            self.assertTrue(handy._send_v3_command("mode2", {"mode": 0}))

        _args, kwargs = put.call_args
        self.assertEqual(kwargs["headers"]["X-Connection-Key"], "secret")
        self.assertEqual(kwargs["headers"]["X-Api-Key"], "app-id")
        self.assertTrue(handy.supports_continuous_streaming())
        self.assertNotIn("secret", str(handy.diagnostics()["last_command"]))
        self.assertNotIn("app-id", str(handy.diagnostics()["last_command"]))

    def test_send_v3_command_records_rate_limit_headers(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")

        with mock.patch(
            "strokegpt.handy.requests.put",
            return_value=FakeResponse(
                status_code=200,
                headers={
                    "X-RateLimit-Limit": "240",
                    "X-RateLimit-Remaining": "17",
                    "X-RateLimit-Reset": "12",
                },
            ),
            create=True,
        ):
            self.assertTrue(handy._send_v3_command("hsp/add", {"points": []}))

        self.assertEqual(
            handy.diagnostics()["last_command"]["rate_limit"],
            {"limit": 240, "remaining": 17, "reset_seconds": 12},
        )

    def test_send_v3_command_requires_app_key(self):
        handy = HandyController(handy_key="secret")

        self.assertFalse(handy._send_v3_command("mode2", {"mode": 0}))

        diagnostics = handy.diagnostics()
        self.assertFalse(diagnostics["api_v3_enabled"])
        self.assertFalse(diagnostics["api_v3_key_configured"])
        self.assertEqual(diagnostics["api_v3_unavailable_reason"], "missing_api_v3_key")
        self.assertEqual(diagnostics["last_command"]["error"], "missing Handy API v3 Application ID")

    def test_send_command_records_failure_instead_of_raising_name_error(self):
        handy = HandyController(handy_key="secret")
        error = handy_module.requests.exceptions.RequestException("device offline")
        error.response = FakeResponse(status_code=503)

        with mock.patch("strokegpt.handy.requests.put", side_effect=error, create=True):
            self.assertFalse(handy._send_command("slide", {"min": 10, "max": 90}))

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["last_command"]["path"], "slide")
        self.assertFalse(diagnostics["last_command"]["ok"])
        self.assertEqual(diagnostics["last_command"]["status_code"], 503)
        self.assertEqual(diagnostics["last_command"]["body"], {"min": 10, "max": 90})
        self.assertIn("device offline", diagnostics["last_command"]["error"])

    def test_check_connection_probes_position_without_motion(self):
        handy = HandyController(handy_key="secret")

        with mock.patch(
            "strokegpt.handy.requests.get",
            return_value=FakeResponse(status_code=200, payload={"position": 42.5}),
            create=True,
        ) as get:
            result = handy.check_connection()

        _args, kwargs = get.call_args
        self.assertEqual(kwargs["headers"]["X-Connection-Key"], "secret")
        self.assertEqual(result["status"], "connected")
        self.assertTrue(result["connected"])
        self.assertEqual(result["position_mm"], 42.5)
        self.assertEqual(result["last_command"]["path"], "slide/position/absolute")
        self.assertTrue(result["last_command"]["ok"])
        self.assertEqual(result["last_command"]["status_code"], 200)
        self.assertNotIn("secret", str(result))

    def test_check_connection_records_failure_without_motion(self):
        handy = HandyController(handy_key="secret")
        error = handy_module.requests.exceptions.RequestException("device offline")
        error.response = FakeResponse(status_code=503)

        with mock.patch("strokegpt.handy.requests.get", side_effect=error, create=True):
            result = handy.check_connection()

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["connected"])
        self.assertIn("device offline", result["message"])
        self.assertEqual(result["last_command"]["path"], "slide/position/absolute")
        self.assertFalse(result["last_command"]["ok"])
        self.assertEqual(result["last_command"]["status_code"], 503)

    def test_check_connection_probes_bluetooth_hsp_state(self):
        bridge = RecordingBluetoothBridge(response={
            "hsp_state": {
                "play_state": "stopped",
                "current_time_ms": 0,
                "stream_id": 12,
            }
        })
        handy = HandyController(
            firmware_version="fw4",
            transport_mode="browser_bluetooth",
            bluetooth_bridge=bridge,
        )

        result = handy.check_connection()

        self.assertEqual(bridge.commands, [("hsp/state", {})])
        self.assertEqual(result["status"], "connected")
        self.assertTrue(result["connected"])
        self.assertEqual(result["transport"], "browser_bluetooth")
        self.assertEqual(result["last_command"]["path"], "hsp/state")
        self.assertTrue(result["last_command"]["ok"])
        self.assertEqual(result["last_command"]["response"]["hsp_state"]["stream_id"], 12)
        self.assertEqual(handy.diagnostics()["hsp_state"]["stream_id"], 12)

    def test_check_connection_reports_bluetooth_hsp_state_failure(self):
        bridge = RecordingBluetoothBridge(ok=False, error="HSP state timed out")
        handy = HandyController(
            firmware_version="fw4",
            transport_mode="browser_bluetooth",
            bluetooth_bridge=bridge,
        )

        result = handy.check_connection()

        self.assertEqual(bridge.commands, [("hsp/state", {})])
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["connected"])
        self.assertIn("HSP state timed out", result["message"])
        self.assertEqual(result["last_command"]["path"], "hsp/state")
        self.assertFalse(result["last_command"]["ok"])

    def test_slide_bounds_remain_ordered_when_calibration_range_is_zero(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 80, 0, 0)

        handy.move(50, 50, 50)

        slide = next(body for path, body in handy.commands if path == "slide")
        self.assertLess(slide["min"], slide["max"])
        self.assertEqual(slide, {"min": 98, "max": 100})

    def test_move_normalizes_reversed_calibrated_depth_limits(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 80, 90, 10)

        handy.move(50, 25, 50)

        slide = next(body for path, body in handy.commands if path == "slide")
        self.assertEqual(slide, {"min": 50, "max": 90})
        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["calibrated_range"], {"min": 10, "max": 90})
        self.assertEqual(diagnostics["physical_depth"], 30)
        self.assertEqual(diagnostics["stroke_zone"], {"min": 10, "max": 50})

    def test_move_to_depth_uses_xava_with_calibrated_position_and_velocity(self):
        handy = RecordingHandyController()
        handy.update_settings(20, 80, 10, 90)

        result = handy.move_to_depth(50, 25)

        self.assertTrue(result)
        self.assertEqual([path for path, _body in handy.commands], ["mode", "hdsp/xava"])
        self.assertEqual(handy.commands[0][1], {"mode": 2})
        body = handy.commands[1][1]
        self.assertEqual(body["velocity"], 200)
        self.assertAlmostEqual(body["position"], handy.FULL_TRAVEL_MM * 0.3)
        self.assertTrue(body["stopOnTarget"])
        self.assertEqual(handy.last_stroke_range, 50)
        self.assertEqual(handy.diagnostics()["mode"], 2)
        self.assertEqual(handy.diagnostics()["velocity"], 200)

    def test_move_to_depth_can_keep_intermediate_targets_moving(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 70, 0, 100)

        handy.move_to_depth(50, 75, stop_on_target=False, velocity=48)

        body = handy.commands[-1][1]
        self.assertEqual(body["velocity"], 48)
        self.assertFalse(body["stopOnTarget"])

    def test_move_to_depth_keeps_intent_speed_separate_from_command_speed(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 70, 0, 100)

        handy.move_to_depth(90, 75, stop_on_target=False, velocity=60, intent_speed=20)

        body = handy.commands[-1][1]
        self.assertEqual(body["velocity"], 60)
        self.assertEqual(handy.diagnostics()["velocity"], 60)
        self.assertEqual(handy.diagnostics()["relative_speed"], 20)

    def test_move_to_depth_reuses_hdsp_mode_for_position_stream(self):
        handy = RecordingHandyController()

        handy.move_to_depth(40, 25)
        handy.move_to_depth(60, 75)

        self.assertEqual([path for path, _body in handy.commands], ["mode", "hdsp/xava", "hdsp/xava"])

    def test_supports_continuous_streaming_requires_connection_and_app_key(self):
        handy = RecordingHandyController()

        self.assertFalse(handy.supports_continuous_streaming())
        handy.set_firmware_version("fw4")

        self.assertFalse(handy.supports_continuous_streaming())
        self.assertEqual(handy.api_v3_unavailable_reason(), "missing_api_v3_key")
        handy.set_handy_api_key("app-id")
        self.assertTrue(handy.supports_continuous_streaming())
        handy.set_firmware_version("v3")
        self.assertFalse(handy.supports_continuous_streaming())

    def test_v3_unauthorized_falls_back_to_legacy_hamp_commands(self):
        class UnauthorizedV3HandyController(RecordingV3HandyController):
            def _send_v3_command(self, path, body=None):
                self.v3_commands.append((path, body or {}))
                self._record_command_result(path, body, ok=False, status_code=401, error="Unauthorized")
                self._disable_api_v3_control()
                return False

        handy = UnauthorizedV3HandyController()

        self.assertTrue(handy.move(50, 50, 50))

        self.assertEqual([path for path, _body in handy.v3_commands], ["mode2"])
        self.assertEqual(
            [path for path, _body in handy.commands],
            ["mode", "hamp/start", "slide", "hamp/velocity"],
        )
        self.assertFalse(handy.supports_continuous_streaming())

    def test_fw4_hamp_uses_v3_stroke_and_velocity_units(self):
        handy = RecordingV3HandyController()
        handy.update_settings(10, 70, 10, 90)

        handy.move(50, 60, 50)

        self.assertEqual(
            [path for path, _body in handy.v3_commands],
            ["mode2", "hamp/start", "hamp/stroke", "hamp/velocity"],
        )
        self.assertEqual(handy.commands, [])
        self.assertEqual(handy.v3_commands[0][1], {"mode": 0})
        self.assertEqual(handy.v3_commands[2][1], {"min": 0.38, "max": 0.78})
        self.assertEqual(handy.v3_commands[3][1], {"velocity": 0.5})

    def test_fw4_position_move_uses_normalized_xpt_and_duration_from_speed_limits(self):
        handy = RecordingV3HandyController()
        handy.update_settings(10, 70, 20, 80)
        handy.last_depth_pos = 25

        handy.move_to_depth(50, 75)

        self.assertEqual([path for path, _body in handy.v3_commands], ["mode2", "hdsp/xpt"])
        self.assertEqual(handy.commands, [])
        self.assertEqual(handy.v3_commands[0][1], {"mode": 2})
        body = handy.v3_commands[-1][1]
        self.assertEqual(body["xp"], 0.65)
        self.assertEqual(body["t"], 165)
        self.assertTrue(body["stop_on_target"])
        self.assertFalse(body["immediate_rsp"])

    def test_fw4_position_move_does_not_honor_too_short_timed_duration(self):
        handy = RecordingV3HandyController()
        handy.update_settings(10, 70, 0, 100)
        handy.last_depth_pos = 10

        handy.move_to_depth(40, 90, duration_ms=1, stop_on_target=False)

        body = handy.v3_commands[-1][1]
        self.assertGreater(body["t"], 1)
        self.assertFalse(body["stop_on_target"])

    def test_start_continuous_stream_uses_hsp_timed_points(self):
        handy = RecordingV3HandyController()
        handy.update_settings(10, 70, 10, 90)

        result = handy.start_continuous_stream(
            [
                {"t": 0, "x": 0, "intent_speed": 30, "range": 80},
                {"t": 160, "x": 50, "intent_speed": 30, "range": 80},
                {"t": 320, "x": 100, "intent_speed": 30, "range": 80},
            ],
            tail_point_stream_index=3,
            tail_point_threshold=1,
        )

        self.assertTrue(result)
        self.assertEqual(
            [path for path, _body in handy.v3_commands],
            ["mode2", "slider/stroke", "hsp/setup", "hsp/add", "hsp/threshold", "hsp/play"],
        )
        self.assertEqual(handy.v3_commands[0][1], {"mode": 4})
        self.assertEqual(handy.v3_commands[1][1], {"min": 0.1, "max": 0.9})
        self.assertEqual(handy.v3_commands[2][1], {"stream_id": 1})
        add = handy.v3_commands[3][1]
        self.assertTrue(add["flush"])
        self.assertEqual(add["tail_point_stream_index"], 3)
        self.assertNotIn("tail_point_threshold", add)
        self.assertEqual(
            add["points"],
            [
                {"t": 0, "x": 0},
                {"t": 160, "x": 50},
                {"t": 320, "x": 100},
            ],
        )
        self.assertEqual(handy.v3_commands[4][1], {"tail_point_threshold": 1})
        body = handy.v3_commands[-1][1]
        self.assertEqual(body["start_time"], 0)
        self.assertEqual(body["server_time"], 123456)
        self.assertFalse(body["pause_on_starving"])
        self.assertFalse(body["loop"])
        self.assertEqual(handy.diagnostics()["mode"], 4)
        self.assertEqual(handy.diagnostics()["relative_speed"], 30)
        self.assertEqual(handy.diagnostics()["depth"], 0)

    def test_browser_bluetooth_continuous_stream_uses_hsp_bridge_commands(self):
        bridge = RecordingBluetoothBridge()
        handy = HandyController(
            firmware_version="fw4",
            transport_mode="browser_bluetooth",
            bluetooth_bridge=bridge,
        )
        handy.update_settings(10, 70, 10, 90)

        result = handy.start_continuous_stream(
            [
                {"t": 0, "x": 0, "intent_speed": 30, "range": 80},
                {"t": 160, "x": 50, "intent_speed": 30, "range": 80},
                {"t": 320, "x": 100, "intent_speed": 30, "range": 80},
            ],
            tail_point_stream_index=3,
            tail_point_threshold=1,
        )

        self.assertTrue(result)
        self.assertEqual(
            [path for path, _body in bridge.commands],
            ["mode2", "slider/stroke", "hsp/setup", "hsp/add", "hsp/play"],
        )
        self.assertEqual(bridge.commands[0][1], {"mode": 4})
        self.assertEqual(bridge.commands[1][1], {"min": 0.1, "max": 0.9})
        self.assertEqual(bridge.commands[2][1], {"stream_id": 1})
        add = bridge.commands[3][1]
        self.assertTrue(add["flush"])
        self.assertEqual(add["tail_point_stream_index"], 3)
        self.assertEqual(add["tail_point_threshold"], 1)
        self.assertEqual(add["points"][-1], {"t": 320, "x": 100})
        self.assertEqual(bridge.commands[4][0], "hsp/play")
        self.assertTrue(bridge.commands[4][1]["pause_on_starving"])
        self.assertEqual(handy.diagnostics()["transport_mode"], "browser_bluetooth")

    def test_start_continuous_stream_rounds_hsp_points_to_api_integer_schema(self):
        handy = RecordingV3HandyController()

        result = handy.start_continuous_stream(
            [
                {"t": 0, "x": 50.125, "intent_speed": 30, "range": 80},
                {"t": 40, "x": 50.875, "intent_speed": 30, "range": 80},
                {"t": 80, "x": 51.0, "intent_speed": 30, "range": 80},
            ],
            tail_point_stream_index=3,
            tail_point_threshold=1,
        )

        self.assertTrue(result)
        add = next(body for path, body in handy.v3_commands if path == "hsp/add")
        self.assertEqual(
            add["points"],
            [
                {"t": 0, "x": 50},
                {"t": 40, "x": 51},
                {"t": 80, "x": 51},
            ],
        )

    def test_hsp_server_time_estimate_uses_servertime_offset(self):
        handy = HandyController(handy_key="test")

        def fake_get(url, timeout):
            self.assertEqual(url, f"{handy.api_v3_base_url}servertime")
            self.assertEqual(timeout, 5)
            return FakeResponse(payload={"server_time": 1000500})

        with (
            mock.patch.object(handy_module.requests, "get", side_effect=fake_get, create=True),
            mock.patch.object(handy_module.time, "monotonic", side_effect=[10.0, 10.0]),
            mock.patch.object(handy_module.time, "time", side_effect=[1000.0, 1000.1, 1000.2]),
        ):
            self.assertEqual(handy._estimated_server_time_ms(), 1000650)

    def test_hsp_play_uses_local_time_fallback_without_blocking_servertime(self):
        handy = HandyController(handy_key="test", api_v3_key="app-id", firmware_version="fw4")
        sent = []

        def fake_send(path, body=None):
            sent.append((path, body or {}))
            return True

        with (
            mock.patch.object(handy, "_send_v3_command", side_effect=fake_send),
            mock.patch.object(handy, "_refresh_server_time_offset_async", return_value=True) as async_refresh,
            mock.patch.object(
                handy,
                "_refresh_server_time_offset",
                side_effect=AssertionError("server time refresh must not block hsp/play"),
            ),
            mock.patch.object(handy_module.time, "monotonic", return_value=10.0),
            mock.patch.object(handy_module.time, "time", return_value=1234.567),
        ):
            self.assertTrue(handy._send_hsp_play(0))

        async_refresh.assert_called_once_with()
        self.assertEqual(sent, [("hsp/play", {
            "start_time": 0,
            "server_time": 1234567,
            "playback_rate": 1.0,
            "pause_on_starving": False,
            "loop": False,
        })])

    def test_sync_continuous_stream_time_sends_hsp_synctime(self):
        handy = RecordingV3HandyController()

        self.assertTrue(handy.sync_continuous_stream_time(875.4, filter=0.9))

        self.assertEqual(handy.v3_commands[-1][0], "hsp/synctime")
        self.assertEqual(
            handy.v3_commands[-1][1],
            {"current_time": 875, "server_time": 123456, "filter": 0.9},
        )
        self.assertEqual(handy.diagnostics()["last_command"]["body"]["current_time"], 875)
        self.assertEqual(handy.diagnostics()["last_command"]["body"]["filter"], 0.9)

    def test_v3_command_records_sanitized_hsp_response_state(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        payload = {
            "result": {
                "play_state": "playing",
                "current_time": 880,
                "current_point": 7,
                "points": 24,
                "max_points": 50,
                "stream_id": 3,
                "tail_point_stream_index": 24,
                "tail_point_stream_index_threshold": 20,
                "pause_on_starving": False,
                "playback_rate": 1.0,
            }
        }

        with mock.patch(
            "strokegpt.handy.requests.put",
            return_value=FakeResponse(status_code=200, payload=payload),
            create=True,
        ):
            self.assertTrue(handy._send_v3_command("hsp/synctime", {"current_time": 880, "filter": 0.5}))

        diagnostics = handy.diagnostics()
        hsp_state = diagnostics["hsp_state"]
        self.assertEqual(hsp_state["play_state"], "playing")
        self.assertEqual(hsp_state["current_time_ms"], 880)
        self.assertEqual(hsp_state["current_point"], 7)
        self.assertEqual(hsp_state["tail_point_stream_index_threshold"], 20)
        self.assertEqual(
            diagnostics["last_command"]["response"],
            {"hsp_state": hsp_state},
        )
        self.assertIsInstance(diagnostics["hsp_state_observed_at"], float)
        self.assertIsInstance(diagnostics["hsp_state_age_ms"], float)
        self.assertNotIn("secret", str(diagnostics))

    def test_v3_command_extracts_nested_hsp_response_state(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        payload = {
            "result": {
                "responseHspStateGet": {
                    "state": {
                        "playState": "playing",
                        "currentTime": 1240,
                        "currentPoint": 8,
                        "streamId": 4,
                    }
                }
            }
        }

        with mock.patch(
            "strokegpt.handy.requests.put",
            return_value=FakeResponse(status_code=200, payload=payload),
            create=True,
        ):
            self.assertTrue(handy._send_v3_command("hsp/state", {}))

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["hsp_state"]["current_time_ms"], 1240)
        self.assertEqual(diagnostics["hsp_state"]["current_point"], 8)
        self.assertEqual(diagnostics["hsp_state"]["stream_id"], 4)
        self.assertIsInstance(diagnostics["hsp_state_observed_at"], float)
        self.assertIsInstance(diagnostics["hsp_state_age_ms"], float)

    def test_refresh_hsp_state_polls_current_state_while_streaming(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True
        payload = {
            "result": {
                "responseHspStateGet": {
                    "state": {
                        "playState": "HSP_STATE_PLAYING",
                        "currentTime": 1480,
                        "currentPoint": 11,
                        "streamId": 6,
                        "playbackRate": 1.0,
                    }
                }
            }
        }

        with mock.patch(
            "strokegpt.handy.requests.get",
            return_value=FakeResponse(status_code=200, payload=payload),
            create=True,
        ) as get:
            self.assertTrue(handy.refresh_hsp_state(max_age_seconds=0))

        get.assert_called_once()
        self.assertIn("hsp/state", get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs["timeout"], handy_module.HSP_STATE_REFRESH_TIMEOUT_SECONDS)

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["hsp_state"]["play_state"], "HSP_STATE_PLAYING")
        self.assertEqual(diagnostics["hsp_state"]["current_time_ms"], 1480)
        self.assertEqual(diagnostics["hsp_state"]["current_point"], 11)
        self.assertEqual(diagnostics["hsp_state"]["stream_id"], 6)
        self.assertEqual(diagnostics["hsp_state"]["playback_rate"], 1)
        self.assertEqual(diagnostics["hsp_state_source"], "poll")
        self.assertEqual(diagnostics["hsp_state_refresh_failures"], 0)
        self.assertEqual(diagnostics["hsp_state_refresh_error"], "")
        self.assertIsInstance(diagnostics["hsp_state_refresh_success_at"], float)
        self.assertIsNone(diagnostics["last_command"])
        self.assertEqual(diagnostics["command_history"], [])

    def test_hsp_state_cache_rejects_stale_same_stream_clock(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")

        self.assertTrue(
            handy._update_hsp_state_cache(
                {"current_time_ms": 5000, "current_point": 20, "stream_id": 9},
                source="sse",
            )
        )
        self.assertFalse(
            handy._update_hsp_state_cache(
                {"current_time_ms": 4900, "current_point": 19, "stream_id": 9},
                source="command",
            )
        )

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["hsp_state"]["current_time_ms"], 5000)
        self.assertEqual(diagnostics["hsp_state"]["current_point"], 20)
        self.assertEqual(diagnostics["hsp_state_source"], "sse")

    def test_hsp_state_cache_accepts_lower_clock_for_new_stream(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")

        self.assertTrue(
            handy._update_hsp_state_cache(
                {"current_time_ms": 5000, "current_point": 20, "stream_id": 9},
                source="sse",
            )
        )
        self.assertTrue(
            handy._update_hsp_state_cache(
                {"current_time_ms": 25, "current_point": 1, "stream_id": 10},
                source="command",
            )
        )

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["hsp_state"]["current_time_ms"], 25)
        self.assertEqual(diagnostics["hsp_state"]["stream_id"], 10)
        self.assertEqual(diagnostics["hsp_state_source"], "command")

    def test_hsp_state_sse_close_joins_existing_worker(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        response = mock.Mock()
        thread = mock.Mock()
        thread.is_alive.return_value = True
        handy._hsp_state_sse_response = response
        handy._hsp_state_sse_thread = thread

        handy._close_hsp_state_sse_stream()

        response.close.assert_called_once()
        thread.join.assert_called_once_with(timeout=0.4)
        self.assertIsNone(handy._hsp_state_sse_response)
        self.assertIsNone(handy._hsp_state_sse_thread)

    def test_refresh_hsp_state_does_not_send_command_fallback_on_poll_failure(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True

        with mock.patch(
            "strokegpt.handy.requests.get",
            side_effect=RuntimeError("state endpoint unavailable"),
            create=True,
        ) as get, mock.patch.object(handy, "_send_v3_command", return_value=True) as send:
            self.assertFalse(handy.refresh_hsp_state(max_age_seconds=0))

        get.assert_called_once()
        send.assert_not_called()
        diagnostics = handy.diagnostics()
        self.assertIsNone(diagnostics["last_command"])
        self.assertEqual(diagnostics["hsp_state_refresh_failures"], 1)
        self.assertIn("state endpoint unavailable", diagnostics["hsp_state_refresh_error"])

    def test_hsp_state_sse_event_updates_state_from_nested_event_data(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True

        self.assertTrue(
            handy._handle_hsp_state_sse_event(
                {
                    "type": "hsp_threshold_reached",
                    "data": (
                        '{"connection_key":"secret","data":{"play_state":"HSP_STATE_PLAYING",'
                        '"current_time":1705,"current_point":12,"stream_id":9,'
                        '"tail_point_stream_index_threshold":42,"playback_rate":1.0}}'
                    ),
                }
            )
        )

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["hsp_state"]["play_state"], "HSP_STATE_PLAYING")
        self.assertEqual(diagnostics["hsp_state"]["current_time_ms"], 1705)
        self.assertEqual(diagnostics["hsp_state"]["current_point"], 12)
        self.assertEqual(diagnostics["hsp_state"]["stream_id"], 9)
        self.assertEqual(diagnostics["hsp_state"]["tail_point_stream_index_threshold"], 42)
        self.assertEqual(diagnostics["hsp_state_source"], "sse")
        self.assertEqual(diagnostics["hsp_state_sse_event_type"], "hsp_threshold_reached")
        self.assertEqual(diagnostics["hsp_state_sse_events"], 1)
        self.assertEqual(diagnostics["hsp_state_sse_failures"], 0)
        self.assertNotIn("secret", str(diagnostics))

    def test_hsp_state_sse_event_uses_payload_type_when_event_field_is_missing(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True

        self.assertTrue(
            handy._handle_hsp_state_sse_event(
                {
                    "data": (
                        '{"type":"hsp_state_changed","data":{"connection_key":"secret",'
                        '"data":{"playState":"playing","currentTime":2200,"currentPoint":14}}}'
                    ),
                }
            )
        )

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["hsp_state"]["play_state"], "playing")
        self.assertEqual(diagnostics["hsp_state"]["current_time_ms"], 2200)
        self.assertEqual(diagnostics["hsp_state"]["current_point"], 14)
        self.assertEqual(diagnostics["hsp_state_source"], "sse")
        self.assertEqual(diagnostics["hsp_state_sse_event_type"], "hsp_state_changed")

    def test_handy_sse_device_error_is_sanitized_in_diagnostics(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")

        self.assertTrue(
            handy._handle_hsp_state_sse_event(
                {
                    "id": "evt-7",
                    "type": "device_error",
                    "data": (
                        '{"connection_key":"secret","data":{"code":1002,'
                        '"name":"DeviceTimeout","message":"Device timeout",'
                        '"authorization":"secret-token"}}'
                    ),
                }
            )
        )

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["handy_sse_event_type"], "device_error")
        self.assertEqual(diagnostics["handy_sse_event"]["id"], "evt-7")
        payload = diagnostics["handy_sse_event"]["payload"]
        self.assertEqual(payload["data"]["code"], 1002)
        self.assertEqual(payload["data"]["name"], "DeviceTimeout")
        self.assertEqual(payload["data"]["message"], "Device timeout")
        self.assertNotIn("connection_key", str(diagnostics))
        self.assertNotIn("secret", str(diagnostics))
        self.assertEqual(len(diagnostics["handy_sse_recent_events"]), 1)

    def test_handy_sse_disconnect_clears_active_motion_state(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True
        handy._hamp_started = True
        handy._current_mode = handy_module.MODE_HSP
        handy._last_velocity = 80

        self.assertTrue(
            handy._handle_hsp_state_sse_event(
                {
                    "type": "device_disconnected",
                    "data": (
                        '{"connection_key":"secret","data":{"reason":"io error",'
                        '"description":"socket closed"}}'
                    ),
                }
            )
        )

        diagnostics = handy.diagnostics()
        self.assertFalse(diagnostics["hsp_streaming"])
        self.assertFalse(diagnostics["hamp_started"])
        self.assertIsNone(diagnostics["mode"])
        self.assertIsNone(diagnostics["velocity"])
        self.assertEqual(diagnostics["handy_sse_event_type"], "device_disconnected")
        self.assertIn("reason", diagnostics["handy_sse_event"]["payload"]["data"])
        self.assertEqual(diagnostics["device_connection_status"], "offline")
        self.assertEqual(diagnostics["device_connection_event_type"], "device_disconnected")
        self.assertEqual(diagnostics["device_connection_message"], "io error")
        self.assertNotIn("secret", str(diagnostics))

    def test_handy_sse_device_status_disconnected_clears_active_motion_state(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True
        handy._hamp_started = True
        handy._current_mode = handy_module.MODE_HSP

        self.assertTrue(
            handy._handle_hsp_state_sse_event(
                {
                    "type": "device_status",
                    "data": (
                        '{"connection_key":"secret","data":{"connected":false,'
                        '"info":{"fw_version":"4.0.0","session_id":"session-1"}}}'
                    ),
                }
            )
        )

        diagnostics = handy.diagnostics()
        self.assertFalse(diagnostics["hsp_streaming"])
        self.assertFalse(diagnostics["hamp_started"])
        self.assertIsNone(diagnostics["mode"])
        self.assertEqual(diagnostics["handy_sse_event_type"], "device_status")
        self.assertFalse(diagnostics["handy_sse_event"]["payload"]["data"]["connected"])
        self.assertEqual(diagnostics["device_connection_status"], "offline")
        self.assertEqual(diagnostics["device_connection_event_type"], "device_status")
        self.assertEqual(diagnostics["device_connection_message"], "Handy SSE reports the device is offline.")
        self.assertIsNotNone(diagnostics["device_connection_observed_at"])
        self.assertNotIn("secret", str(diagnostics))

    def test_handy_sse_device_connected_updates_device_connection_status(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")

        self.assertTrue(
            handy._handle_hsp_state_sse_event(
                {
                    "type": "device_connected",
                    "data": (
                        '{"connection_key":"secret","data":{"connected":true,'
                        '"description":"device online"}}'
                    ),
                }
            )
        )

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["device_connection_status"], "online")
        self.assertEqual(diagnostics["device_connection_event_type"], "device_connected")
        self.assertEqual(diagnostics["device_connection_message"], "device online")
        self.assertNotIn("secret", str(diagnostics))

    def test_hsp_state_sse_once_subscribes_with_query_auth_and_event_filter(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True
        response = FakeSseResponse(
            [
                "id: 1",
                "event: hsp_state_changed",
                (
                    'data: {"connection_key":"secret","data":{"play_state":"playing",'
                    '"current_time":3100,"current_point":22,"stream_id":5}}'
                ),
                "",
            ]
        )

        with mock.patch(
            "strokegpt.handy.requests.get",
            return_value=response,
            create=True,
        ) as get:
            self.assertTrue(handy._run_hsp_state_sse_once(handy._hsp_state_sse_generation))

        get.assert_called_once()
        url = get.call_args.args[0]
        self.assertIn("/sse?", url)
        self.assertIn("apikey=app-id", url)
        self.assertIn("ck=secret", url)
        self.assertIn("hsp_state_changed", url)
        self.assertIn("device_error", url)
        self.assertIn("slider_blocked", url)
        self.assertTrue(get.call_args.kwargs["stream"])
        self.assertEqual(get.call_args.kwargs["headers"]["Accept"], "text/event-stream")
        self.assertEqual(
            get.call_args.kwargs["timeout"],
            (
                handy_module.HSP_STATE_SSE_CONNECT_TIMEOUT_SECONDS,
                handy_module.HSP_STATE_SSE_READ_TIMEOUT_SECONDS,
            ),
        )
        self.assertTrue(response.closed)

        diagnostics = handy.diagnostics()
        self.assertEqual(diagnostics["hsp_state"]["current_time_ms"], 3100)
        self.assertEqual(diagnostics["hsp_state"]["current_point"], 22)
        self.assertEqual(diagnostics["hsp_state_source"], "sse")
        self.assertEqual(diagnostics["hsp_state_sse_failures"], 0)

    def test_hsp_state_sse_failure_does_not_send_command_fallback(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True

        with mock.patch(
            "strokegpt.handy.requests.get",
            side_effect=RuntimeError("sse unavailable"),
            create=True,
        ) as get, mock.patch.object(handy, "_send_v3_command", return_value=True) as send:
            self.assertFalse(handy._run_hsp_state_sse_once(handy._hsp_state_sse_generation))

        get.assert_called_once()
        send.assert_not_called()
        diagnostics = handy.diagnostics()
        self.assertIsNone(diagnostics["last_command"])
        self.assertEqual(diagnostics["hsp_state_sse_failures"], 1)
        self.assertIn("sse unavailable", diagnostics["hsp_state_sse_error"])

    def test_diagnostics_starts_async_hsp_state_refresh_worker(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True

        with mock.patch.object(
            handy, "ensure_hsp_state_sse_worker", return_value=True
        ) as ensure_sse, mock.patch.object(
            handy, "ensure_hsp_state_refresh_worker", return_value=True
        ) as ensure:
            handy.diagnostics(refresh_hsp_state=True)

        ensure_sse.assert_called_once()
        ensure.assert_called_once()

    def test_hsp_state_refresh_worker_uses_background_thread(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")
        handy._hsp_streaming = True

        with mock.patch("strokegpt.handy.threading.Thread") as thread_class:
            thread = mock.Mock()
            thread.is_alive.return_value = False
            thread_class.return_value = thread

            self.assertTrue(handy.ensure_hsp_state_refresh_worker())

        thread_class.assert_called_once()
        thread.start.assert_called_once()

    def test_hsp_state_sse_worker_uses_background_thread(self):
        handy = HandyController(handy_key="secret", api_v3_key="app-id")

        with mock.patch("strokegpt.handy.threading.Thread") as thread_class:
            thread = mock.Mock()
            thread.is_alive.return_value = False
            thread_class.return_value = thread

            self.assertTrue(handy.ensure_hsp_state_sse_worker())

        thread_class.assert_called_once()
        kwargs = thread_class.call_args.kwargs
        self.assertEqual(kwargs["name"], "StrokeGPT-HSP-State-SSE")
        thread.start.assert_called_once()

    def test_hsp_state_refresh_cadence_matches_status_polling(self):
        self.assertLessEqual(handy_module.HSP_STATE_REFRESH_MIN_INTERVAL_SECONDS, 0.3)
        self.assertLessEqual(handy_module.HSP_STATE_REFRESH_TIMEOUT_SECONDS, 0.5)

    def test_diagnostics_include_hsp_point_preview_without_secret_values(self):
        handy = RecordingV3HandyController()

        handy.start_continuous_stream(
            [{"t": index * 80, "x": index, "intent_speed": 30, "range": 80} for index in range(16)],
            tail_point_stream_index=16,
            tail_point_threshold=14,
        )

        diagnostics = handy.diagnostics()
        history = diagnostics["command_history"]
        add_command = next(command for command in history if command["path"] == "hsp/add")
        body = add_command["body"]
        self.assertEqual(body["points"], 16)
        self.assertEqual(len(body["points_preview"]), 12)
        self.assertEqual(body["points_preview"][0], {"t": 0, "x": 0})
        self.assertEqual(body["points_preview"][-1], {"t": 880, "x": 11})
        self.assertEqual(body["points_tail_preview"], [
            {"t": 1040, "x": 13},
            {"t": 1120, "x": 14},
            {"t": 1200, "x": 15},
        ])
        self.assertTrue(body["points_truncated"])
        self.assertNotIn("test", str(diagnostics))

    def test_append_continuous_stream_adds_points_without_flush(self):
        handy = RecordingV3HandyController()

        self.assertTrue(
            handy.append_continuous_stream(
                [{"t": 480, "x": 65, "intent_speed": 44, "range": 60}],
                tail_point_stream_index=4,
                tail_point_threshold=2,
            )
        )

        self.assertEqual([path for path, _body in handy.v3_commands], ["hsp/add", "hsp/threshold"])
        body = handy.v3_commands[-2][1]
        self.assertFalse(body["flush"])
        self.assertEqual(body["tail_point_stream_index"], 4)
        self.assertNotIn("tail_point_threshold", body)
        self.assertEqual(body["points"], [{"t": 480, "x": 65}])
        self.assertEqual(handy.v3_commands[-1][1], {"tail_point_threshold": 2})
        self.assertEqual(handy.diagnostics()["relative_speed"], 50)

    def test_browser_bluetooth_append_continuous_stream_inlines_threshold_and_resumes(self):
        bridge = RecordingBluetoothBridge()
        handy = HandyController(
            firmware_version="fw4",
            transport_mode="browser_bluetooth",
            bluetooth_bridge=bridge,
        )

        self.assertTrue(
            handy.append_continuous_stream(
                [{"t": 480, "x": 65, "intent_speed": 44, "range": 60}],
                tail_point_stream_index=4,
                tail_point_threshold=2,
            )
        )

        self.assertEqual([path for path, _body in bridge.commands], ["hsp/add", "hsp/resume"])
        add = bridge.commands[0][1]
        self.assertFalse(add["flush"])
        self.assertEqual(add["tail_point_stream_index"], 4)
        self.assertEqual(add["tail_point_threshold"], 2)
        self.assertEqual(add["points"], [{"t": 480, "x": 65}])
        self.assertEqual(bridge.commands[1][1], {"pick_up": True})
        self.assertEqual(handy.diagnostics()["last_command"]["path"], "hsp/add")

    def test_append_continuous_stream_throttles_threshold_updates_after_start(self):
        handy = RecordingV3HandyController()

        self.assertTrue(
            handy.start_continuous_stream(
                [
                    {"t": 0, "x": 20, "intent_speed": 30, "range": 80},
                    {"t": 160, "x": 70, "intent_speed": 30, "range": 80},
                ],
                tail_point_stream_index=2,
                tail_point_threshold=1,
            )
        )
        paths_before = [path for path, _body in handy.v3_commands]
        self.assertTrue(
            handy.append_continuous_stream(
                [{"t": 480, "x": 65, "intent_speed": 44, "range": 60}],
                tail_point_stream_index=4,
                tail_point_threshold=2,
            )
        )

        self.assertEqual(paths_before[-3:], ["hsp/add", "hsp/threshold", "hsp/play"])
        self.assertEqual([path for path, _body in handy.v3_commands][len(paths_before):], ["hsp/add"])

    def test_start_continuous_stream_keeps_playing_when_threshold_update_fails(self):
        handy = ThresholdFailingV3HandyController()

        result = handy.start_continuous_stream(
            [
                {"t": 0, "x": 20, "intent_speed": 30, "range": 80},
                {"t": 160, "x": 70, "intent_speed": 30, "range": 80},
            ],
            tail_point_stream_index=2,
            tail_point_threshold=1,
        )

        self.assertTrue(result)
        self.assertEqual([path for path, _body in handy.v3_commands][-3:], ["hsp/add", "hsp/threshold", "hsp/play"])
        self.assertEqual(handy.diagnostics()["last_command"]["path"], "hsp/play")
        self.assertTrue(handy.supports_continuous_streaming())

    def test_append_continuous_stream_keeps_add_result_when_threshold_update_fails(self):
        handy = ThresholdFailingV3HandyController()

        result = handy.append_continuous_stream(
            [{"t": 480, "x": 65, "intent_speed": 44, "range": 60}],
            tail_point_stream_index=4,
            tail_point_threshold=2,
        )

        self.assertTrue(result)
        self.assertEqual([path for path, _body in handy.v3_commands], ["hsp/add", "hsp/threshold"])
        self.assertEqual(handy.diagnostics()["last_command"]["path"], "hsp/add")
        self.assertTrue(handy.supports_continuous_streaming())

    def test_append_continuous_stream_restarts_when_firmware_clock_is_past_buffer(self):
        handy = StaleClockV3HandyController()

        result = handy.append_continuous_stream(
            [
                {"t": 29500, "x": 79, "intent_speed": 70, "range": 80},
                {"t": 30742, "x": 70, "intent_speed": 70, "range": 80},
            ],
            tail_point_stream_index=42,
            tail_point_threshold=40,
        )

        self.assertTrue(result)
        self.assertEqual([path for path, _body in handy.v3_commands], ["hsp/add", "hsp/threshold", "hsp/play"])
        play_body = handy.v3_commands[-1][1]
        self.assertEqual(play_body["start_time"], 29500)
        self.assertFalse(play_body["pause_on_starving"])
        self.assertEqual(handy.diagnostics()["last_command"]["path"], "hsp/play")

    def test_start_continuous_stream_reuses_hsp_setup_for_replacement(self):
        handy = RecordingV3HandyController()

        self.assertTrue(
            handy.start_continuous_stream(
                [{"t": 0, "x": 20, "intent_speed": 30, "range": 80}],
                tail_point_stream_index=1,
                tail_point_threshold=0,
            )
        )
        self.assertTrue(
            handy.start_continuous_stream(
                [{"t": 0, "x": 80, "intent_speed": 60, "range": 80}],
                tail_point_stream_index=1,
                tail_point_threshold=0,
            )
        )

        paths = [path for path, _body in handy.v3_commands]
        self.assertEqual(paths.count("hsp/setup"), 1)
        self.assertEqual(paths.count("hsp/play"), 1)
        setup_bodies = [body for path, body in handy.v3_commands if path == "hsp/setup"]
        self.assertEqual(setup_bodies, [{"stream_id": 1}])
        self.assertEqual(paths[-2:], ["hsp/add", "hsp/threshold"])
        replacement_adds = [body for path, body in handy.v3_commands if path == "hsp/add"]
        self.assertEqual(replacement_adds[-1]["flush"], True)
        self.assertEqual(handy.diagnostics()["last_command"]["path"], "hsp/add")

    def test_velocity_for_depth_interval_is_capped_by_user_speed(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 70, 0, 100)

        velocity = handy.velocity_for_depth_interval(50, 0, 100, 0.1)

        self.assertEqual(velocity, 200)

    def test_absolute_velocity_uses_percent_speed_settings_for_position_transport(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 80, 0, 100)

        self.assertEqual(handy.min_absolute_user_speed, 40)
        self.assertEqual(handy.max_absolute_user_speed, 320)
        self.assertEqual(handy.max_absolute_velocity_for_relative_speed(0), 40)
        self.assertEqual(handy.max_absolute_velocity_for_relative_speed(50), 200)
        self.assertEqual(handy.max_absolute_velocity_for_relative_speed(80), 320)
        self.assertEqual(handy.max_absolute_velocity_for_relative_speed(100), 320)

    def test_position_velocity_never_exceeds_current_max_speed(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 30, 0, 100)

        self.assertEqual(handy.velocity_for_depth_interval(100, 0, 100, 0.1), 120)
        handy.move_to_depth(100, 90, velocity=1000)

        body = handy.commands[-1][1]
        self.assertEqual(body["velocity"], 120)

    def test_move_to_depth_stops_hamp_before_position_preview(self):
        handy = RecordingHandyController()
        handy.move(50, 50, 50)
        handy.commands.clear()

        handy.move_to_depth(40, 20)

        self.assertEqual([path for path, _body in handy.commands], ["hamp/stop", "mode", "hdsp/xava"])
        self.assertEqual(handy.commands[1][1], {"mode": 2})
        self.assertFalse(handy._hamp_started)

    def test_depth_range_runs_low_high_low_once(self):
        handy = RecordingHandyController()

        result = handy.test_depth_range(80, 20, velocity_mm_per_sec=1000, pause_seconds=0)

        self.assertEqual(result, {"min_depth": 20, "max_depth": 80})
        self.assertEqual(handy.commands[0], ("mode", {"mode": 2}))
        positions = [body["position"] for path, body in handy.commands if path == "hdsp/xava"]
        self.assertEqual(len(positions), 3)
        self.assertEqual(positions[0], handy.FULL_TRAVEL_MM * 0.2)
        self.assertEqual(positions[1], handy.FULL_TRAVEL_MM * 0.8)
        self.assertEqual(positions[2], handy.FULL_TRAVEL_MM * 0.2)


if __name__ == "__main__":
    unittest.main()
