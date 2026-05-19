import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "replay_motion_capture.py"


def load_replay_module():
    spec = importlib.util.spec_from_file_location("replay_motion_capture", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MotionCaptureReplayScriptTests(unittest.TestCase):
    def sample_capture(self):
        return {
            "capture": {
                "run": {
                    "backend": "continuous",
                    "firmware": "v4",
                    "active_mode": "freestyle",
                },
                "after": {
                    "api_v3_enabled": True,
                    "api_v3_key_configured": True,
                },
                "motion_trace": [
                    {
                        "continuous_schema": "hsp",
                        "source": "freestyle planner",
                        "label": "freestyle flow",
                        "hsp_batch": "replace",
                        "hsp_replacement_kind": "intent",
                        "hsp_duplicate_suppressed_points": 2,
                        "handy_path": "hsp/add",
                        "handy_ok": True,
                    },
                    {
                        "continuous_schema": "hsp",
                        "source": "freestyle planner",
                        "label": "freestyle flow",
                        "hsp_batch": "add",
                        "hsp_replacement_kind": "drift",
                        "handy_path": "hsp/add",
                        "handy_ok": True,
                    },
                ],
                "handy_command_history": [
                    {
                        "path": "hsp/add",
                        "ok": True,
                        "status_code": 200,
                        "elapsed_ms": 80,
                        "body": {
                            "flush": True,
                            "points": [
                                {"t": 100, "x": 20},
                                {"t": 260, "x": 50},
                                {"t": 430, "x": 35},
                            ],
                        },
                        "response": {
                            "hsp_state": {
                                "current_time_ms": 25,
                                "current_point": 0,
                                "play_state": "HSP_STATE_PLAYING",
                            }
                        },
                    },
                    {
                        "path": "hsp/play",
                        "ok": True,
                        "status_code": 204,
                        "elapsed_ms": 40,
                    },
                ],
            }
        }

    def test_replay_module_summarizes_capture_metrics(self):
        replay = load_replay_module()

        capture = replay._capture_from_document(self.sample_capture())
        summary = replay.summarize_capture(capture)
        stats = replay.hsp_add_command_stats(capture["handy_command_history"])
        timeline = replay.build_timeline(capture)

        self.assertEqual(summary["trace_rows"], 2)
        self.assertEqual(summary["command_rows"], 2)
        self.assertEqual(summary["path_counts"], {"hsp/add": 1, "hsp/play": 1})
        self.assertEqual(summary["hsp_replacement_counts"], {"intent": 1, "drift": 1})
        self.assertEqual(summary["hsp_duplicate_suppressed_points"], 2)
        self.assertEqual(summary["hsp_add_max_preview_gap_ms"], 170.0)
        self.assertEqual(stats[0]["preview_max_delta"], 30.0)
        self.assertEqual(stats[0]["hsp_state"]["current_time_ms"], 25)
        self.assertEqual([event["kind"] for event in timeline], ["trace", "trace", "command", "command"])

    def test_replay_script_outputs_json(self):
        cache_parent = PROJECT_ROOT / "user_data" / "test_motion_capture_replay"
        cache_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache_parent) as temp_dir:
            capture_path = Path(temp_dir) / "capture.json"
            capture_path.write_text(json.dumps(self.sample_capture()), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), str(capture_path), "--json"],
                text=True,
                capture_output=True,
                check=True,
            )
        try:
            cache_parent.rmdir()
        except OSError:
            pass

        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["hsp_commands"], 2)
        self.assertEqual(payload["hsp_add_stats"][0]["point_count"], 3)
        self.assertEqual(payload["timeline"][0]["schema"], "hsp")


if __name__ == "__main__":
    unittest.main()
