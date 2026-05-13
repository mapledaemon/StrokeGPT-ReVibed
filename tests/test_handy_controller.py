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
        self.v3_commands = []

    def _send_v3_command(self, path, body=None):
        self.v3_commands.append((path, body or {}))
        self._record_command_result(path, body, ok=True, status_code=200, elapsed_ms=0)
        return True


class FakeResponse:
    def __init__(self, status_code=204, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return dict(self.payload)


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
        self.assertEqual(diagnostics["physical_speed"], 45)
        self.assertEqual(diagnostics["depth"], 60)
        self.assertEqual(diagnostics["physical_depth"], 60)
        self.assertEqual(diagnostics["position_mm"], 66.0)
        self.assertEqual(diagnostics["range"], 70)
        self.assertEqual(diagnostics["calibrated_range"], {"min": 0, "max": 100})
        self.assertEqual(diagnostics["stroke_zone"], {"min": 25, "max": 95})
        self.assertEqual(diagnostics["full_travel_mm"], handy.FULL_TRAVEL_MM)
        self.assertEqual(diagnostics["slide_bounds"], {"min": 5, "max": 75})
        self.assertEqual(diagnostics["velocity"], 45)
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

    def test_send_v3_command_uses_connection_key_for_v3_auth(self):
        handy = HandyController(handy_key="secret")

        with mock.patch(
            "strokegpt.handy.requests.put",
            return_value=FakeResponse(status_code=200),
            create=True,
        ) as put:
            self.assertTrue(handy._send_v3_command("mode2", {"mode": 0}))

        _args, kwargs = put.call_args
        self.assertEqual(kwargs["headers"]["X-Connection-Key"], "secret")
        self.assertEqual(kwargs["headers"]["X-Api-Key"], "secret")
        self.assertTrue(handy.supports_continuous_streaming())
        self.assertNotIn("secret", str(handy.diagnostics()["last_command"]))

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

    def test_slide_bounds_remain_ordered_when_calibration_range_is_zero(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 80, 0, 0)

        handy.move(50, 50, 50)

        slide = next(body for path, body in handy.commands if path == "slide")
        self.assertLess(slide["min"], slide["max"])
        self.assertEqual(slide, {"min": 98, "max": 100})

    def test_move_to_depth_uses_xava_with_calibrated_position_and_velocity(self):
        handy = RecordingHandyController()
        handy.update_settings(20, 80, 10, 90)

        result = handy.move_to_depth(50, 25)

        self.assertTrue(result)
        self.assertEqual([path for path, _body in handy.commands], ["mode", "hdsp/xava"])
        self.assertEqual(handy.commands[0][1], {"mode": 2})
        body = handy.commands[1][1]
        self.assertEqual(body["velocity"], 50)
        self.assertAlmostEqual(body["position"], handy.FULL_TRAVEL_MM * 0.3)
        self.assertTrue(body["stopOnTarget"])
        self.assertEqual(handy.last_stroke_range, 50)
        self.assertEqual(handy.diagnostics()["mode"], 2)
        self.assertEqual(handy.diagnostics()["velocity"], 50)

    def test_move_to_depth_can_keep_intermediate_targets_moving(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 70, 0, 100)

        handy.move_to_depth(50, 75, stop_on_target=False, velocity=18)

        body = handy.commands[-1][1]
        self.assertEqual(body["velocity"], 18)
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

    def test_supports_continuous_streaming_uses_saved_connection_key(self):
        handy = RecordingHandyController()

        self.assertFalse(handy.supports_continuous_streaming())
        handy.set_firmware_version("fw4")

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
        self.assertEqual(handy.v3_commands[3][1], {"velocity": 0.4})

    def test_fw4_position_move_uses_xpt_percent_and_duration_from_speed_limits(self):
        handy = RecordingV3HandyController()
        handy.update_settings(10, 70, 0, 100)
        handy.last_depth_pos = 25

        handy.move_to_depth(50, 75)

        self.assertEqual([path for path, _body in handy.v3_commands], ["mode2", "hdsp/xpt"])
        self.assertEqual(handy.commands, [])
        self.assertEqual(handy.v3_commands[0][1], {"mode": 2})
        body = handy.v3_commands[-1][1]
        self.assertEqual(body["xp"], 75)
        self.assertEqual(body["t"], 1375)
        self.assertTrue(body["stop_on_target"])
        self.assertFalse(body["immediate_rsp"])

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
            ["slider/stroke", "mode2", "hsp/setup", "hsp/add", "hsp/play"],
        )
        self.assertEqual(handy.v3_commands[0][1], {"min": 0.1, "max": 0.9})
        self.assertEqual(handy.v3_commands[1][1], {"mode": 4})
        add = handy.v3_commands[3][1]
        self.assertTrue(add["flush"])
        self.assertEqual(add["tail_point_stream_index"], 3)
        self.assertEqual(
            add["points"],
            [
                {"t": 0, "x": 10},
                {"t": 160, "x": 50},
                {"t": 320, "x": 90},
            ],
        )
        body = handy.v3_commands[-1][1]
        self.assertEqual(body["start_time"], 0)
        self.assertIn("server_time", body)
        self.assertTrue(body["pause_on_starving"])
        self.assertFalse(body["loop"])
        self.assertEqual(handy.diagnostics()["mode"], 4)
        self.assertEqual(handy.diagnostics()["relative_speed"], 30)
        self.assertEqual(handy.diagnostics()["depth"], 100)

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

        self.assertEqual(handy.v3_commands[-1][0], "hsp/add")
        body = handy.v3_commands[-1][1]
        self.assertFalse(body["flush"])
        self.assertEqual(body["tail_point_stream_index"], 4)
        self.assertEqual(body["tail_point_threshold"], 2)
        self.assertEqual(body["points"], [{"t": 480, "x": 65}])
        self.assertEqual(handy.diagnostics()["relative_speed"], 44)

    def test_velocity_for_depth_interval_is_capped_by_user_speed(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 70, 0, 100)

        velocity = handy.velocity_for_depth_interval(50, 0, 100, 0.1)

        self.assertEqual(velocity, 40)

    def test_position_velocity_never_exceeds_current_max_speed(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 30, 0, 100)

        self.assertEqual(handy.velocity_for_depth_interval(100, 0, 100, 0.1), 30)
        handy.move_to_depth(100, 90, velocity=1000)

        body = handy.commands[-1][1]
        self.assertEqual(body["velocity"], 30)

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
