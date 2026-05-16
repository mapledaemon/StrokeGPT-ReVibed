import importlib.util
import io
import json
import shutil
import unittest
import uuid
from pathlib import Path

from strokegpt.program_library import (
    MAX_PROGRAM_ACTIONS,
    MAX_PROGRAM_DURATION_MS,
    PROGRAM_FILE_SUFFIX,
    ProgramLibrary,
    ProgramValidationError,
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
PROGRAM_TEST_TEMP_ROOT = WORKSPACE_ROOT / "user_data" / "test-program-library"


class ProgramTestTempDir:
    def __init__(self):
        self._created_user_data_root = not PROGRAM_TEST_TEMP_ROOT.parent.exists()
        PROGRAM_TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = PROGRAM_TEST_TEMP_ROOT / f"case-{uuid.uuid4().hex}"
        self.path.mkdir()
        self.name = str(self.path)

    def cleanup(self):
        shutil.rmtree(self.path)
        try:
            PROGRAM_TEST_TEMP_ROOT.rmdir()
        except OSError:
            pass
        if self._created_user_data_root:
            try:
                PROGRAM_TEST_TEMP_ROOT.parent.rmdir()
            except OSError:
                pass

    def __enter__(self):
        return self.name

    def __exit__(self, exc_type, exc, traceback):
        self.cleanup()


def temporary_program_dir():
    return ProgramTestTempDir()


def long_program_payload(action_count=2501, step_ms=240):
    return {
        "kind": "funscript",
        "id": "long-wave",
        "name": "Long Wave",
        "actions": [
            {"at": index * step_ms, "pos": index % 101}
            for index in range(action_count)
        ],
    }


class ProgramLibraryTests(unittest.TestCase):
    def test_program_record_accepts_long_funscript_beyond_pattern_limits(self):
        record = record_from_payload(long_program_payload())

        self.assertEqual(record.program_id, "long-wave")
        self.assertEqual(record.name, "Long Wave")
        self.assertEqual(record.action_count, 2501)
        self.assertEqual(record.duration_ms, 600_000)
        self.assertIn("program", record.tags)
        self.assertIn("funscript", record.tags)

    def test_program_actions_rebase_to_zero(self):
        record = record_from_payload({
            "name": "Offset Program",
            "actions": [
                {"at": 10_000, "pos": 20},
                {"at": 12_500, "pos": 80},
            ],
        })

        self.assertEqual([action.at for action in record.actions], [0, 2500])

    def test_program_rejects_too_many_or_too_long_actions(self):
        with self.assertRaises(ProgramValidationError):
            record_from_payload({
                "name": "Too Dense",
                "actions": [
                    {"at": index, "pos": 50}
                    for index in range(MAX_PROGRAM_ACTIONS + 1)
                ],
            })

        with self.assertRaises(ProgramValidationError):
            record_from_payload({
                "name": "Too Long",
                "actions": [
                    {"at": 0, "pos": 50},
                    {"at": MAX_PROGRAM_DURATION_MS + 1, "pos": 60},
                ],
            })

    def test_library_saves_program_files_with_separate_suffix(self):
        with temporary_program_dir() as temp_dir:
            library = ProgramLibrary(temp_dir)
            record = library.import_payload(long_program_payload(), filename="long-wave.funscript")

            self.assertEqual(record.program_id, "long-wave")
            self.assertTrue((Path(temp_dir) / f"long-wave{PROGRAM_FILE_SUFFIX}").exists())

            catalog = library.catalog()
            self.assertEqual(catalog["programs"][0]["id"], "long-wave")
            self.assertEqual(catalog["programs"][0]["duration_ms"], 600_000)
            self.assertFalse(catalog["errors"])

    def test_library_deletes_program_files_by_record_id(self):
        with temporary_program_dir() as temp_dir:
            library = ProgramLibrary(temp_dir)
            library.import_payload(long_program_payload(), filename="long-wave.funscript")

            deleted = library.delete_program("long-wave")

            self.assertIsNotNone(deleted)
            self.assertEqual(deleted.program_id, "long-wave")
            self.assertFalse((Path(temp_dir) / f"long-wave{PROGRAM_FILE_SUFFIX}").exists())
            self.assertEqual(library.catalog()["programs"], [])


@unittest.skipIf(MISSING_WEB_MODULES, f"missing app dependencies: {', '.join(MISSING_WEB_MODULES)}")
class MotionProgramRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import strokegpt.web as web

        cls.web = web
        cls.client = web.app.test_client()

    def setUp(self):
        self.temp_dir = temporary_program_dir()
        self.original_library = self.web.motion_program_library
        self.web.motion_program_library = ProgramLibrary(self.temp_dir.name)

    def tearDown(self):
        self.web.motion_program_library = self.original_library
        self.temp_dir.cleanup()

    def test_program_import_detail_catalog_and_export_routes(self):
        payload = long_program_payload()
        response = self.client.post(
            "/import_motion_program",
            data={"program": (io.BytesIO(json.dumps(payload).encode("utf-8")), "long-wave.funscript")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        imported = response.get_json()["program"]
        self.assertEqual(imported["id"], "long-wave")
        self.assertEqual(imported["duration_ms"], 600_000)

        catalog_response = self.client.get("/motion_programs")
        self.assertEqual(catalog_response.status_code, 200)
        catalog = catalog_response.get_json()
        self.assertIn("long-wave", {program["id"] for program in catalog["programs"]})

        detail_response = self.client.get("/motion_programs/long-wave")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(len(detail_response.get_json()["program"]["actions"]), 2501)

        export_response = self.client.get("/motion_programs/long-wave/export")
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.mimetype, "application/json")
        exported = json.loads(export_response.get_data(as_text=True))
        self.assertEqual(exported["kind"], "funscript_program")
        self.assertEqual(exported["id"], "long-wave")

        delete_response = self.client.delete("/motion_programs/long-wave")
        self.assertEqual(delete_response.status_code, 200)
        delete_payload = delete_response.get_json()
        self.assertEqual(delete_payload["status"], "success")
        self.assertEqual(delete_payload["program"]["id"], "long-wave")
        self.assertEqual(delete_payload["motion_programs"]["programs"], [])

        missing_response = self.client.get("/motion_programs/long-wave")
        self.assertEqual(missing_response.status_code, 404)

    def test_program_import_route_rejects_pattern_text_file_shape(self):
        response = self.client.post(
            "/import_motion_program",
            data={"program": (io.BytesIO(b"not json"), "bad.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(".json or .funscript", response.get_json()["message"])


if __name__ == "__main__":
    unittest.main()
