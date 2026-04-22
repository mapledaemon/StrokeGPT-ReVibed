import importlib.machinery
import sys
import types
import unittest

requests_module = types.ModuleType("requests")
requests_module.__spec__ = importlib.machinery.ModuleSpec("requests", loader=None)
requests_module.exceptions = types.SimpleNamespace(RequestException=Exception)
sys.modules.setdefault("requests", requests_module)

from strokegpt.handy import HandyController


class RecordingHandyController(HandyController):
    def __init__(self):
        super().__init__(handy_key="test")
        self.commands = []

    def _send_command(self, path, body=None):
        self.commands.append((path, body or {}))
        return True


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
        self.assertEqual([path for path, _body in handy.commands], ["hdsp/xava"])
        body = handy.commands[0][1]
        self.assertEqual(body["velocity"], 50)
        self.assertAlmostEqual(body["position"], handy.FULL_TRAVEL_MM * 0.3)
        self.assertTrue(body["stopOnTarget"])
        self.assertEqual(handy.last_stroke_range, 50)

    def test_move_to_depth_can_keep_intermediate_targets_moving(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 70, 0, 100)

        handy.move_to_depth(50, 75, stop_on_target=False, velocity=18)

        body = handy.commands[0][1]
        self.assertEqual(body["velocity"], 18)
        self.assertFalse(body["stopOnTarget"])

    def test_velocity_for_depth_interval_is_capped_by_user_speed(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 70, 0, 100)

        velocity = handy.velocity_for_depth_interval(50, 0, 100, 0.1)

        self.assertEqual(velocity, 40)

    def test_move_to_depth_stops_hamp_before_position_preview(self):
        handy = RecordingHandyController()
        handy.move(50, 50, 50)
        handy.commands.clear()

        handy.move_to_depth(40, 20)

        self.assertEqual([path for path, _body in handy.commands], ["hamp/stop", "hdsp/xava"])
        self.assertFalse(handy._hamp_started)

    def test_depth_range_runs_low_high_low_once(self):
        handy = RecordingHandyController()

        result = handy.test_depth_range(80, 20, velocity_mm_per_sec=1000, pause_seconds=0)

        self.assertEqual(result, {"min_depth": 20, "max_depth": 80})
        positions = [body["position"] for path, body in handy.commands if path == "hdsp/xava"]
        self.assertEqual(len(positions), 3)
        self.assertEqual(positions[0], handy.FULL_TRAVEL_MM * 0.2)
        self.assertEqual(positions[1], handy.FULL_TRAVEL_MM * 0.8)
        self.assertEqual(positions[2], handy.FULL_TRAVEL_MM * 0.2)


if __name__ == "__main__":
    unittest.main()
