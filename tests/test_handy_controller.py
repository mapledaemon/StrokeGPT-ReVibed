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

    def test_stop_clears_motion_cache_so_next_move_reapplies_bounds(self):
        handy = RecordingHandyController()

        handy.move(50, 50, 50)
        handy.stop()
        handy.move(50, 50, 50)

        self.assertEqual([path for path, _body in handy.commands].count("slide"), 2)
        self.assertEqual([path for path, _body in handy.commands].count("hamp/velocity"), 2)

    def test_slide_bounds_remain_ordered_when_calibration_range_is_zero(self):
        handy = RecordingHandyController()
        handy.update_settings(10, 80, 0, 0)

        handy.move(50, 50, 50)

        slide = next(body for path, body in handy.commands if path == "slide")
        self.assertLess(slide["min"], slide["max"])
        self.assertEqual(slide, {"min": 98, "max": 100})

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
