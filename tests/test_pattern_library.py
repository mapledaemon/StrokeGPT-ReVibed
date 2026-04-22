import importlib.util
import io
import json
import tempfile
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
        self.assertEqual(record.repeat, 20)
        self.assertEqual(record.interpolation, "cosine")
        self.assertEqual(record.max_step_delta, 100.0)
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

    def test_library_reports_invalid_user_pattern_files_without_breaking_catalog(self):
        with temporary_pattern_dir() as temp_dir:
            Path(temp_dir, "broken.strokegpt-pattern.json").write_text("{bad json", encoding="utf-8")
            library = PatternLibrary(temp_dir)

            catalog = library.catalog()

            self.assertGreaterEqual(len(catalog["patterns"]), len(PATTERNS))
            self.assertEqual(catalog["errors"][0]["file"], "broken.strokegpt-pattern.json")


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
        self.web.motion_pattern_library = PatternLibrary(self.temp_dir.name)

    def tearDown(self):
        self.web.motion_pattern_library = self.original_library
        self.temp_dir.cleanup()

    def test_catalog_and_detail_routes_expose_builtin_patterns(self):
        catalog_response = self.client.get("/motion_patterns")
        self.assertEqual(catalog_response.status_code, 200)
        catalog = catalog_response.get_json()
        self.assertIn("patterns", catalog)
        self.assertIn("stroke", {pattern["id"] for pattern in catalog["patterns"]})

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


if __name__ == "__main__":
    unittest.main()
