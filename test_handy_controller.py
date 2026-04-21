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
