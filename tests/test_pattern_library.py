import importlib.util
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from strokegpt.motion_patterns import PATTERNS
from strokegpt.pattern_library import (
    PATTERN_FILE_SUFFIX,
    PatternLibrary,
    PatternValidationError,
    record_from_payload,
)


REQUIRED_WEB_MODULES = ("flask", "requests", "elevenlabs")


def module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


MISSING_WEB_MODULES = [name for name in REQUIRED_WEB_MODULES if not module_available(name)]
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def temporary_pattern_dir():
    return tempfile.TemporaryDirectory(dir=WORKSPACE_ROOT)


class PatternLibraryTests(unittest.TestCase):
    def test_record_from_payload_accepts_funscript_style_actions(self):
        record = record_from_payload({
            "id": " Soft Wave ",
            "name": " Soft Wave ",
            "kind": "funscript",
            "source": "generated",
            "style": {
                "window_scale": 2.0,
                "speed_scale": 0.01,
                "tempo_scale": 9.0,
                "repeat": 30,
                "interpolation": "unknown",
                "max_step_delta": 200,
            },
            "actions": [
                {"at": 100, "pos": 40},
                {"at": 0, "pos": -10},
                {"at": 100, "pos": 60},
                {"at": 300, "pos": 130},
            ],
            "tags": [" smooth ", "smooth", "training"],
            "feedback": {"thumbs_up": "2", "neutral": "bad", "thumbs_down": -1},
        })

        self.assertEqual(record.pattern_id, "soft-wave")
        self.assertEqual(record.source, "generated")
        self.assertEqual([action.at for action in record.actions], [0, 100, 300])
        self.assertEqual([action.pos for action in record.actions], [0, 60.0, 100])
        self.assertEqual(record.window_scale, 1.0)
        self.assertEqual(record.speed_scale, 0.1)
        self.assertEqual(record.tempo_scale, 4.0)
        self.assertEqual(record.repeat, 20)
        self.assertEqual(record.interpolation, "cosine")
        self.assertEqual(record.max_step_delta, 100.0)
        self.assertEqual(record.to_export_dict()["style"]["tempo_scale"], 4.0)
        self.assertEqual(record.tags, ("smooth", "training"))
        self.assertEqual(record.feedback["thumbs_up"], 2)
        self.assertEqual(record.feedback["neutral"], 0)
        self.assertEqual(record.feedback["thumbs_down"], 0)

    def test_record_requires_valid_non_zero_action_sequence(self):
        with self.assertRaises(PatternValidationError):
            record_from_payload({"name": "bad", "actions": [{"at": 0, "pos": 50}]})

        with self.assertRaises(PatternValidationError):
            record_from_payload({"name": "bad", "actions": "not a list"})

    def test_library_lists_builtins_and_saves_imports_as_shareable_files(self):
        with temporary_pattern_dir() as temp_dir:
            library = PatternLibrary(temp_dir)
            record = library.import_payload(
                {
                    "id": "custom-loop",
                    "name": "Custom Loop",
                    "actions": [
                        {"at": 0, "pos": 10},
                        {"at": 250, "pos": 90},
                        {"at": 500, "pos": 15},
                    ],
                },
                filename="custom-loop.funscript",
            )

            self.assertEqual(record.pattern_id, "custom-loop")
            self.assertTrue((Path(temp_dir) / f"custom-loop{PATTERN_FILE_SUFFIX}").exists())

            catalog = library.catalog()
            pattern_ids = {pattern["id"] for pattern in catalog["patterns"]}
            self.assertIn("stroke", pattern_ids)
            self.assertIn("custom-loop", pattern_ids)
            self.assertFalse(catalog["errors"])

    def test_library_assigns_unique_ids_on_duplicate_imports(self):
        with temporary_pattern_dir() as temp_dir:
            library = PatternLibrary(temp_dir)
            payload = {
                "id": "repeat-me",
                "name": "Repeat Me",
                "actions": [{"at": 0, "pos": 0}, {"at": 100, "pos": 100}],
            }

            first = library.import_payload(payload, filename="repeat-me.json")
            second = library.import_payload(payload, filename="repeat-me.json")

            self.assertEqual(first.pattern_id, "repeat-me")
            self.assertEqual(second.pattern_id, "repeat-me-2")

    def test_library_can_save_trained_pattern_source(self):
        with temporary_pattern_dir() as temp_dir:
            library = PatternLibrary(temp_dir)
            record = library.import_payload(
                {
                    "id": "trained-loop",
                    "name": "Trained Loop",
                    "style": {"tempo_scale": 1.7},
                    "actions": [{"at": 0, "pos": 20}, {"at": 240, "pos": 80}],
                },
                filename="trained-loop.json",
                source_override="trained",
            )

            self.assertEqual(record.source, "trained")
            exported = json.loads((Path(temp_dir) / f"trained-loop{PATTERN_FILE_SUFFIX}").read_text(encoding="utf-8"))
            self.assertEqual(exported["source"], "trained")
            self.assertEqual(exported["style"]["tempo_scale"], 1.7)

    def test_library_reports_invalid_user_pattern_files_without_breaking_catalog(self):
        with temporary_pattern_dir() as temp_dir:
            Path(temp_dir, "broken.strokegpt-pattern.json").write_text("{bad json", encoding="utf-8")
            library = PatternLibrary(temp_dir)

            catalog = library.catalog()

            self.assertGreaterEqual(len(catalog["patterns"]), len(PATTERNS))
            self.assertEqual(catalog["errors"][0]["file"], "broken.strokegpt-pattern.json")

    def test_catalog_applies_local_enabled_overrides(self):
        with temporary_pattern_dir() as temp_dir:
            library = PatternLibrary(temp_dir)

            catalog = library.catalog(
                {"stroke": False},
                {"stroke": {"thumbs_up": 4, "neutral": 1, "thumbs_down": 2}},
            )
            stroke = next(pattern for pattern in catalog["patterns"] if pattern["id"] == "stroke")

            self.assertFalse(stroke["enabled"])
            self.assertEqual(stroke["feedback"], {"thumbs_up": 4, "neutral": 1, "thumbs_down": 2})


@unittest.skipIf(MISSING_WEB_MODULES, f"missing app dependencies: {', '.join(MISSING_WEB_MODULES)}")
class MotionPatternRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import strokegpt.web as web

        cls.web = web
        cls.app = web.app
        cls.client = web.app.test_client()

    def setUp(self):
        self.temp_dir = temporary_pattern_dir()
        self.original_library = self.web.motion_pattern_library
        self.original_pattern_enabled = dict(self.web.settings.motion_pattern_enabled)
        self.original_pattern_feedback = dict(self.web.settings.motion_pattern_feedback)
        self.original_pattern_weights = dict(self.web.settings.motion_pattern_weights)
        self.original_settings_save = self.web.settings.save
        self.original_audio_generate = self.web.audio.generate_audio_for_text
        self.original_last_live_pattern = self.web.last_live_motion_pattern_id
        self.original_handy_key = self.web.handy.handy_key
        self.original_handy_state = (
            self.web.handy.last_stroke_speed,
            self.web.handy.last_relative_speed,
            self.web.handy.last_depth_pos,
            self.web.handy.last_stroke_range,
        )
        self.original_apply_frames = self.web.motion.apply_frames
        self.original_apply_position_frames = self.web.motion.apply_position_frames
        self.original_motion_stop = self.web.motion.stop
        self.stop_calls = []
        self.web.motion_pattern_library = PatternLibrary(self.temp_dir.name)
        self.web.settings.motion_pattern_enabled = {}
        self.web.settings.motion_pattern_feedback = {}
        self.web.settings.motion_pattern_weights = {}
        self.web.settings.save = lambda *args, **kwargs: None
        self.web.audio.generate_audio_for_text = lambda *args, **kwargs: None
        self.web.last_live_motion_pattern_id = ""
        self.web.motion.stop = lambda: self.stop_calls.append("stopped")
        self.web._set_motion_training_state(
            state="idle",
            pattern_id="",
            pattern_name="",
            message="Motion training idle.",
            last_feedback="",
        )
        self.web.motion_training_stop_event.clear()

    def tearDown(self):
        self.web._stop_motion_training()
        self.web.motion_pattern_library = self.original_library
        self.web.settings.motion_pattern_enabled = self.original_pattern_enabled
        self.web.settings.motion_pattern_feedback = self.original_pattern_feedback
        self.web.settings.motion_pattern_weights = self.original_pattern_weights
        self.web.settings.save = self.original_settings_save
        self.web.audio.generate_audio_for_text = self.original_audio_generate
        self.web.last_live_motion_pattern_id = self.original_last_live_pattern
        self.web.handy.handy_key = self.original_handy_key
        (
            self.web.handy.last_stroke_speed,
            self.web.handy.last_relative_speed,
            self.web.handy.last_depth_pos,
            self.web.handy.last_stroke_range,
        ) = self.original_handy_state
        self.web.motion.apply_frames = self.original_apply_frames
        self.web.motion.apply_position_frames = self.original_apply_position_frames
        self.web.motion.stop = self.original_motion_stop
        self.temp_dir.cleanup()

    def test_catalog_and_detail_routes_expose_builtin_patterns(self):
        catalog_response = self.client.get("/motion_patterns")
        self.assertEqual(catalog_response.status_code, 200)
        catalog = catalog_response.get_json()
        self.assertIn("patterns", catalog)
        self.assertIn("stroke", {pattern["id"] for pattern in catalog["patterns"]})
        stroke_summary = next(pattern for pattern in catalog["patterns"] if pattern["id"] == "stroke")
        self.assertEqual(stroke_summary["weight"], 50)
        self.assertTrue(stroke_summary["llm_visible"])

        detail_response = self.client.get("/motion_patterns/stroke")
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.get_json()["pattern"]
        self.assertTrue(detail["readonly"])
        self.assertGreaterEqual(len(detail["actions"]), 2)

    def test_import_detail_and_export_routes_round_trip_user_pattern(self):
        payload = {
            "id": "uploaded-loop",
            "name": "Uploaded Loop",
            "actions": [{"at": 0, "pos": 5}, {"at": 300, "pos": 95}, {"at": 600, "pos": 10}],
        }
        response = self.client.post(
            "/import_motion_pattern",
            data={"pattern": (io.BytesIO(json.dumps(payload).encode("utf-8")), "uploaded-loop.funscript")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["pattern"]["id"], "uploaded-loop")

        detail_response = self.client.get("/motion_patterns/uploaded-loop")
        self.assertEqual(detail_response.status_code, 200)
        self.assertFalse(detail_response.get_json()["pattern"]["readonly"])

        export_response = self.client.get("/motion_patterns/uploaded-loop/export")
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.mimetype, "application/json")
        exported = json.loads(export_response.get_data(as_text=True))
        self.assertEqual(exported["id"], "uploaded-loop")
        self.assertEqual(exported["source"], "imported")

    def test_import_route_rejects_invalid_files(self):
        response = self.client.post(
            "/import_motion_pattern",
            data={"pattern": (io.BytesIO(b"not json"), "bad.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(".json or .funscript", response.get_json()["message"])

    def test_enabled_route_persists_local_pattern_state(self):
        response = self.client.post("/motion_patterns/stroke/enabled", json={"enabled": False})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["pattern"]["enabled"])
        self.assertFalse(self.web.settings.motion_pattern_enabled["stroke"])

        catalog_stroke = next(pattern for pattern in data["motion_patterns"]["patterns"] if pattern["id"] == "stroke")
        self.assertFalse(catalog_stroke["enabled"])

    def test_training_start_routes_pattern_through_motion_controller(self):
        calls = []
        self.web.handy.handy_key = "test-key"

        def fake_apply_position_frames(frames, *, stop_after=False, **_kwargs):
            calls.append({"frames": frames, "stop_after": stop_after})
            if stop_after:
                self.web.motion.stop()
            return True

        self.web.motion.apply_position_frames = fake_apply_position_frames

        response = self.client.post("/motion_training/start", json={"pattern_id": "stroke"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "started")
        self.assertEqual(data["motion_training"]["pattern_id"], "stroke")
        for _ in range(10):
            if calls:
                break
            time.sleep(0.02)
        self.assertTrue(calls)
        self.assertTrue(calls[0]["stop_after"])
        self.assertGreater(len(calls[0]["frames"]), 1)
        self.assertEqual(self.stop_calls, ["stopped"])

    def test_training_preview_routes_unsaved_pattern_without_writing_file(self):
        calls = []
        self.web.handy.handy_key = "test-key"

        def fake_apply_position_frames(frames, *, stop_after=False, **_kwargs):
            calls.append({"frames": frames, "stop_after": stop_after})
            if stop_after:
                self.web.motion.stop()
            return True

        self.web.motion.apply_position_frames = fake_apply_position_frames
        response = self.client.post("/motion_training/preview", json={
            "pattern": {
                "id": "edited-preview",
                "name": "Edited Preview",
                "actions": [{"at": 0, "pos": 15}, {"at": 180, "pos": 85}, {"at": 360, "pos": 25}],
            }
        })

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "started")
        self.assertTrue(data["motion_training"]["preview"])
        self.assertEqual(data["motion_training"]["pattern_id"], "edited-preview")
        for _ in range(10):
            if calls:
                break
            time.sleep(0.02)
        self.assertTrue(calls)
        self.assertTrue(calls[0]["stop_after"])
        self.assertEqual(tuple(Path(self.temp_dir.name).iterdir()), ())

    def test_save_generated_pattern_writes_trained_pattern_file(self):
        response = self.client.post("/motion_patterns/save_generated", json={
            "pattern": {
                "id": "edited-copy",
                "name": "Edited Copy",
                "actions": [{"at": 0, "pos": 10}, {"at": 250, "pos": 90}, {"at": 500, "pos": 30}],
            }
        })

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["pattern"]["id"], "edited-copy")
        self.assertEqual(data["pattern"]["source"], "trained")
        self.assertTrue((Path(self.temp_dir.name) / f"edited-copy{PATTERN_FILE_SUFFIX}").exists())
        self.assertIn("edited-copy", {pattern["id"] for pattern in data["motion_patterns"]["patterns"]})

    def test_training_start_uses_selected_pattern_shape(self):
        calls = []
        self.web.handy.handy_key = "test-key"

        def fake_apply_position_frames(frames, *, stop_after=False, **_kwargs):
            calls.append(tuple(round(frame.target.depth) for frame in frames))
            if stop_after:
                self.web.motion.stop()
            return True

        self.web.motion.apply_position_frames = fake_apply_position_frames

        for pattern_id in ("stroke", "tease"):
            response = self.client.post("/motion_training/start", json={"pattern_id": pattern_id})
            self.assertEqual(response.status_code, 200)
            for _ in range(20):
                if len(calls) > (1 if pattern_id == "tease" else 0):
                    break
                time.sleep(0.02)
            for _ in range(20):
                thread = self.web.motion_training_thread
                if not thread or not thread.is_alive():
                    break
                time.sleep(0.02)

        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])

    def test_training_target_does_not_collapse_after_position_preview(self):
        record = self.web.motion_pattern_library.get_record("stroke")
        self.web.handy.last_relative_speed = 0
        self.web.handy.last_depth_pos = 50
        self.web.handy.last_stroke_range = 5

        target = self.web._training_target_for_record(record)

        self.assertEqual(target.speed, 35)
        self.assertEqual(target.depth, 50)
        self.assertEqual(target.stroke_range, 50)

    def test_training_stop_calls_motion_stop(self):
        response = self.client.post("/motion_training/stop")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "stopped")
        self.assertEqual(self.stop_calls, ["stopped"])

    def test_training_feedback_persists_without_llm_changes(self):
        response = self.client.post("/motion_training/stroke/feedback", json={"rating": "thumbs_up"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["pattern"]["feedback"]["thumbs_up"], 1)
        self.assertEqual(data["pattern"]["weight"], 60)
        self.assertEqual(self.web.settings.motion_pattern_feedback["stroke"]["thumbs_up"], 1)
        self.assertEqual(self.web.settings.motion_pattern_weights["stroke"], 60)
        self.assertIn("motion_preferences", data)

    def test_three_thumbs_down_auto_disables_pattern(self):
        for _ in range(3):
            response = self.client.post("/motion_training/sway/feedback", json={"rating": "thumbs_down"})
            self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data["auto_disabled"])
        self.assertFalse(data["pattern"]["enabled"])
        self.assertEqual(data["pattern"]["weight"], 0)
        self.assertFalse(self.web.settings.motion_pattern_enabled["sway"])
        self.assertEqual(self.web.settings.motion_pattern_weights["sway"], 0)
        self.assertEqual(self.web.settings.motion_pattern_feedback["sway"]["thumbs_down"], 3)
        self.assertNotIn("sway", data["motion_preferences"]["prompt"])
        self.assertIn("sway", data["motion_preferences"]["summary"])

    def test_motion_preferences_route_exposes_enabled_weights_only(self):
        self.web.settings.motion_pattern_weights = {"sway": 74, "flutter": 22}
        self.web.settings.motion_pattern_enabled = {"flutter": False}

        response = self.client.get("/motion_preferences")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertIn("sway=74", data["prompt"])
        self.assertNotIn("flutter", data["prompt"])
        self.assertIn("Disabled fixed patterns: flutter.", data["summary"])
        self.assertIn("Only choose listed pattern names", data["prompt"])

    def test_weight_route_persists_fixed_pattern_weight(self):
        response = self.client.post("/motion_patterns/sway/weight", json={"weight": 88})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["pattern"]["weight"], 88)
        self.assertEqual(self.web.settings.motion_pattern_weights["sway"], 88)
        sway = next(pattern for pattern in data["motion_patterns"]["patterns"] if pattern["id"] == "sway")
        self.assertEqual(sway["weight"], 88)

    def test_chat_thumbs_down_rates_last_live_fixed_pattern(self):
        self.web.last_live_motion_pattern_id = "tease"

        for _ in range(3):
            response = self.client.post("/dislike_last_move")
            self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["auto_disabled"])
        self.assertEqual(data["pattern"]["id"], "tease")
        self.assertFalse(data["pattern"]["enabled"])
        self.assertEqual(data["pattern"]["weight"], 0)
        self.assertEqual(self.web.settings.motion_pattern_feedback["tease"]["thumbs_down"], 3)

    def test_disabled_llm_pattern_is_removed_before_motion(self):
        self.web.settings.motion_pattern_enabled = {"flutter": False}

        move = self.web._sanitize_llm_move_for_disabled_patterns({
            "sp": 40,
            "zone": "tip",
            "pattern": "flutter",
        })

        self.assertEqual(move["sp"], 40)
        self.assertEqual(move["zone"], "tip")
        self.assertNotIn("pattern", move)

    def test_zero_weight_llm_pattern_is_removed_before_motion(self):
        self.web.settings.motion_pattern_weights = {"flutter": 0}

        move = self.web._sanitize_llm_move_for_disabled_patterns({
            "sp": 40,
            "zone": "tip",
            "pattern": "flutter",
        })

        self.assertEqual(move["sp"], 40)
        self.assertEqual(move["zone"], "tip")
        self.assertNotIn("pattern", move)


if __name__ == "__main__":
    unittest.main()
