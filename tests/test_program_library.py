import importlib.util
import io
import json
import shutil
import time
import unittest
import uuid
import zipfile
from pathlib import Path

from strokegpt.program_library import (
    MAX_PROGRAM_ACTIONS,
    MAX_PROGRAM_DURATION_MS,
    PROGRAM_FILE_SUFFIX,
    ProgramLibrary,
    ProgramValidationError,
    record_from_payload,
)
from strokegpt.pattern_library import PATTERN_FILE_SUFFIX, PatternLibrary


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

    def test_library_renames_program_without_changing_id(self):
        with temporary_program_dir() as temp_dir:
            library = ProgramLibrary(temp_dir)
            library.import_payload(long_program_payload(), filename="long-wave.funscript")

            renamed = library.rename_program("long-wave", "Renamed Wave")

            self.assertIsNotNone(renamed)
            self.assertEqual(renamed.program_id, "long-wave")
            self.assertEqual(renamed.name, "Renamed Wave")
            path = Path(temp_dir) / f"long-wave{PROGRAM_FILE_SUFFIX}"
            self.assertTrue(path.exists())
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["id"], "long-wave")
            self.assertEqual(saved["name"], "Renamed Wave")
            self.assertEqual(library.catalog()["programs"][0]["name"], "Renamed Wave")

    def test_program_sections_interpolate_boundaries_and_rebase(self):
        record = record_from_payload({
            "id": "timeline",
            "name": "Timeline",
            "actions": [
                {"at": 0, "pos": 0},
                {"at": 1000, "pos": 100},
                {"at": 2000, "pos": 0},
            ],
        })

        section = record.section_actions(500, 1500)

        self.assertEqual([action.at for action in section], [0, 500, 1000])
        self.assertEqual([round(action.pos) for action in section], [50, 100, 50])

        payload = record.section_pattern_payload(500, 1500, name="Middle Cut")
        self.assertEqual(payload["name"], "Middle Cut")
        self.assertEqual(payload["actions"][0], {"at": 0, "pos": 50.0})
        self.assertIn("program-section", payload["tags"])


@unittest.skipIf(MISSING_WEB_MODULES, f"missing app dependencies: {', '.join(MISSING_WEB_MODULES)}")
class MotionProgramRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import strokegpt.web as web

        cls.web = web
        cls.client = web.app.test_client()

    def setUp(self):
        self.temp_dir = temporary_program_dir()
        self.pattern_temp_dir = temporary_program_dir()
        self.original_library = self.web.motion_program_library
        self.original_pattern_library = self.web.motion_pattern_library
        self.original_handy_key = self.web.handy.handy_key
        self.original_motion_backend = self.web.motion.backend
        self.original_apply_position_frames = self.web.motion.apply_position_frames
        self.original_apply_authored_actions = self.web.motion.apply_authored_actions
        self.original_motion_stop = self.web.motion.stop
        self.original_persona_desc = self.web.settings.persona_desc
        self.original_motion_style = self.web.settings.motion_style
        self.original_pattern_library_freestyle = self.web.settings.motion_pattern_library_enabled_in_freestyle
        self.original_pattern_library_chat = self.web.settings.motion_pattern_library_enabled_in_chat
        self.original_feedback_auto_disable = self.web.settings.motion_feedback_auto_disable
        self.original_pattern_enabled = dict(self.web.settings.motion_pattern_enabled)
        self.original_pattern_weights = dict(self.web.settings.motion_pattern_weights)
        self.original_pattern_feedback = dict(self.web.settings.motion_pattern_feedback)
        self.web.motion_program_library = ProgramLibrary(self.temp_dir.name)
        self.web.motion_pattern_library = PatternLibrary(self.pattern_temp_dir.name)
        self.stop_calls = []
        self.web.motion.stop = lambda: self.stop_calls.append("stopped")
        self.web._set_motion_training_state(
            state="idle",
            pattern_id="",
            pattern_name="",
            message="Motion training idle.",
            last_feedback="",
            preview=False,
        )
        self.web.app_state.motion_training_stop_event.clear()

    def tearDown(self):
        self.web._stop_motion_training()
        self.web.motion_program_library = self.original_library
        self.web.motion_pattern_library = self.original_pattern_library
        self.web.handy.handy_key = self.original_handy_key
        self.web.motion.backend = self.original_motion_backend
        self.web.motion.apply_position_frames = self.original_apply_position_frames
        self.web.motion.apply_authored_actions = self.original_apply_authored_actions
        self.web.motion.stop = self.original_motion_stop
        self.web.settings.persona_desc = self.original_persona_desc
        self.web.settings.motion_style = self.original_motion_style
        self.web.settings.motion_pattern_library_enabled_in_freestyle = self.original_pattern_library_freestyle
        self.web.settings.motion_pattern_library_enabled_in_chat = self.original_pattern_library_chat
        self.web.settings.motion_feedback_auto_disable = self.original_feedback_auto_disable
        self.web.settings.motion_pattern_enabled = self.original_pattern_enabled
        self.web.settings.motion_pattern_weights = self.original_pattern_weights
        self.web.settings.motion_pattern_feedback = self.original_pattern_feedback
        self.temp_dir.cleanup()
        self.pattern_temp_dir.cleanup()

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

    def test_program_play_route_uses_motion_controller_for_full_and_section(self):
        calls = []
        self.web.handy.handy_key = "test-key"
        self.web.motion.backend = "position"
        self.web.motion.apply_position_frames = lambda frames, *, stop_after=False, **_kwargs: calls.append({
            "frames": frames,
            "stop_after": stop_after,
        }) or True
        self.web.motion_program_library.import_payload(long_program_payload(action_count=6, step_ms=1000), filename="long-wave.funscript")

        response = self.client.post("/motion_programs/long-wave/play", json={"start_ms": 1000, "end_ms": 3000})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "started")
        for _ in range(20):
            if calls:
                break
            time.sleep(0.02)
        self.assertTrue(calls)
        self.assertTrue(calls[0]["stop_after"])
        self.assertEqual(len(calls[0]["frames"]), 3)
        self.assertTrue(all(frame.phase == "timed-pattern" for frame in calls[0]["frames"]))
        self.assertGreater(calls[0]["frames"][1].delay_factor, 0)

    def test_program_play_route_uses_authored_hsp_on_continuous_backend(self):
        calls = []
        self.web.handy.handy_key = "test-key"
        self.web.motion.backend = "continuous"

        def fake_apply_authored_actions(actions, target, *, stop_after=False, block=False, source="", **_kwargs):
            calls.append({
                "actions": tuple(actions),
                "target": target,
                "stop_after": stop_after,
                "block": block,
                "source": source,
            })
            return True

        self.web.motion.apply_authored_actions = fake_apply_authored_actions
        self.web.motion.apply_position_frames = lambda *_args, **_kwargs: self.fail("Continuous Program playback should not use HDSP position frames")
        self.web.motion_program_library.import_payload(long_program_payload(action_count=6, step_ms=1000), filename="long-wave.funscript")

        response = self.client.post("/motion_programs/long-wave/play", json={"start_ms": 1000, "end_ms": 3000})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "started")
        for _ in range(20):
            if calls:
                break
            time.sleep(0.02)
        self.assertTrue(calls)
        self.assertEqual([action.at for action in calls[0]["actions"]], [0, 1000, 2000])
        self.assertEqual([action.pos for action in calls[0]["actions"]], [1.0, 2.0, 3.0])
        self.assertEqual(calls[0]["target"].stroke_range, 100)
        self.assertTrue(calls[0]["stop_after"])
        self.assertTrue(calls[0]["block"])
        self.assertEqual(calls[0]["source"], "program playback")

    def test_program_rename_route_updates_catalog_name(self):
        self.web.motion_program_library.import_payload(long_program_payload(action_count=6, step_ms=1000), filename="long-wave.funscript")

        response = self.client.post("/motion_programs/long-wave/rename", json={"name": "Renamed Wave"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["program"]["id"], "long-wave")
        self.assertEqual(data["program"]["name"], "Renamed Wave")
        self.assertEqual(data["motion_programs"]["programs"][0]["name"], "Renamed Wave")

        blank_response = self.client.post("/motion_programs/long-wave/rename", json={"name": "   "})
        self.assertEqual(blank_response.status_code, 400)

    def test_program_tags_route_updates_catalog_and_open_detail(self):
        self.web.motion_program_library.import_payload(long_program_payload(action_count=6, step_ms=1000), filename="long-wave.funscript")

        response = self.client.post(
            "/motion_programs/long-wave/tags",
            json={"tags": " teasing, long-form, teasing "},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["program"]["tags"], ["teasing", "long-form", "program", "funscript"])
        self.assertEqual(data["motion_programs"]["programs"][0]["tags"], ["teasing", "long-form", "program", "funscript"])

        saved = json.loads((Path(self.temp_dir.name) / f"long-wave{PROGRAM_FILE_SUFFIX}").read_text(encoding="utf-8"))
        self.assertEqual(saved["tags"], ["teasing", "long-form", "program", "funscript"])

    def test_motion_library_export_zip_contains_shareable_patterns_programs_and_safe_preferences(self):
        self.web.settings.persona_desc = "Test persona text"
        self.web.settings.motion_style = "teasing"
        self.web.settings.motion_pattern_library_enabled_in_freestyle = True
        self.web.settings.motion_pattern_library_enabled_in_chat = False
        self.web.settings.motion_feedback_auto_disable = True
        self.web.settings.motion_pattern_enabled = {"stroke": False}
        self.web.settings.motion_pattern_weights = {"stroke": 72}
        self.web.settings.motion_pattern_feedback = {"stroke": {"thumbs_up": 2, "neutral": 0, "thumbs_down": 1}}
        self.web.motion_pattern_library.import_payload(
            {
                "id": "clip-loop",
                "name": "Clip Loop",
                "actions": [{"at": 0, "pos": 10}, {"at": 500, "pos": 90}],
                "tags": ["tip"],
            },
            filename="clip-loop.json",
        )
        self.web.motion_program_library.import_payload(long_program_payload(action_count=6, step_ms=1000), filename="long-wave.funscript")

        response = self.client.get("/motion_library/export")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("preferences/motion_preferences.json", names)
            self.assertIn("prompts/persona.txt", names)
            self.assertIn("patterns/clip-loop.strokegpt-pattern.json", names)
            self.assertIn("programs/long-wave.strokegpt-program.json", names)

            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["kind"], "strokegpt_library_export")
            self.assertEqual(manifest["counts"]["patterns"], 1)
            self.assertEqual(manifest["counts"]["programs"], 1)
            self.assertIn("Handy connection keys", manifest["excluded"])

            preferences = json.loads(archive.read("preferences/motion_preferences.json").decode("utf-8"))
            self.assertEqual(preferences["motion_style"], "teasing")
            self.assertTrue(preferences["motion_pattern_library_enabled_in_freestyle"])
            self.assertFalse(preferences["motion_pattern_library_enabled_in_chat"])
            self.assertEqual(preferences["motion_pattern_weights"], {"stroke": 72})
            self.assertEqual(archive.read("prompts/persona.txt").decode("utf-8"), "Test persona text\n")

    def test_program_section_save_route_writes_short_pattern(self):
        self.web.motion_program_library.import_payload(long_program_payload(action_count=6, step_ms=1000), filename="long-wave.funscript")

        response = self.client.post("/motion_programs/long-wave/sections/save_pattern", json={
            "start_ms": 1000,
            "end_ms": 3000,
            "name": "Wave Clip",
        })

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["pattern"]["id"], "wave-clip")
        self.assertEqual(data["pattern"]["source"], "trained")
        self.assertTrue((Path(self.pattern_temp_dir.name) / f"wave-clip{PATTERN_FILE_SUFFIX}").exists())


if __name__ == "__main__":
    unittest.main()
