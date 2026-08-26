import json
import tempfile
import types
import unittest
from pathlib import Path

import app


class DummyCore(types.SimpleNamespace):
    def reset_cancel_request(self):
        self.CANCEL_REQUESTED = False


class SettingsTests(unittest.TestCase):
    def test_password_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = app.AppSettings(
                email="operator@example.org",
                output_folder=str(Path(folder) / "downloads"),
            )
            app.save_settings(settings, path)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("password", persisted)
            self.assertEqual(app.load_settings(path).email, "operator@example.org")

    def test_corrupt_settings_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text("not-json", encoding="utf-8")
            settings = app.load_settings(path)
            self.assertEqual(settings.institution_id, "10870")
            self.assertTrue(settings.output_folder)

    def test_state_and_log_paths_stay_with_output(self):
        state, logs = app.runtime_state_paths("C:/Research/Clarius")
        self.assertEqual(state.name, "last_sync_active.json")
        self.assertEqual(logs.name, "logs")
        self.assertEqual(state.parent.name, "_ClariusDownloader")

        archived_state, _ = app.runtime_state_paths("C:/Research/Clarius", archived=True)
        self.assertEqual(archived_state.name, "last_sync_archived.json")


class EngineMappingTests(unittest.TestCase):
    def test_normal_mode_mapping(self):
        core = DummyCore()
        settings = app.AppSettings(
            email="operator@example.org",
            output_folder="C:/Research/Clarius",
            run_mode="normal",
        )
        app.apply_engine_settings(core, settings, "session-only-password")
        self.assertEqual(core.EMAIL, settings.email)
        self.assertEqual(core.PASSWORD, "session-only-password")
        self.assertIsNone(core.PATIENT_RANGE_START)
        self.assertIsNone(core.PATIENT_RANGE_END)
        self.assertFalse(core.FORCE_PATIENT_RANGE)
        self.assertFalse(core.CANCEL_REQUESTED)

    def test_range_mode_mapping(self):
        core = DummyCore()
        settings = app.AppSettings(
            email="operator@example.org",
            output_folder="C:/Research/Clarius",
            run_mode="range",
            range_start="149",
            range_end="151",
            overwrite_existing_raw=True,
        )
        app.apply_engine_settings(core, settings, "session-only-password")
        self.assertEqual(core.PATIENT_RANGE_START, 149)
        self.assertEqual(core.PATIENT_RANGE_END, 151)
        self.assertTrue(core.FORCE_PATIENT_RANGE)
        self.assertTrue(core.OVERWRITE_EXISTING_RAW)


if __name__ == "__main__":
    unittest.main()
