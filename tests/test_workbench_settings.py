import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings

from scripts.invoice_fetch.gui.workbench_settings import (
    migrate_legacy_workbench_settings,
    sync_workbench_settings,
    workbench_settings,
)


class WorkbenchSettingsTests(unittest.TestCase):
    def test_runtime_dir_is_injectable_and_does_not_use_default_path(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = workbench_settings(Path(directory))
            self.assertEqual(Path(settings.fileName()).parent, Path(directory))
            self.assertEqual(Path(settings.fileName()).name, "workbench.ini")
            settings.setValue("nav_collapsed_manual", True)
            self.assertTrue(sync_workbench_settings(settings))

    def test_legacy_preferences_are_migrated_once_without_overwriting_new_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = QSettings(str(root / "legacy.ini"), QSettings.IniFormat)
            legacy.setValue("nav_collapsed_manual", True)
            legacy.setValue("shortcut_help_expanded", False)
            legacy.setValue("splitter/main", [600, 400])
            self.assertTrue(sync_workbench_settings(legacy))

            target = workbench_settings(root / "target")
            self.assertTrue(migrate_legacy_workbench_settings(target, legacy))
            self.assertTrue(target.value("nav_collapsed_manual", type=bool))
            self.assertFalse(target.value("shortcut_help_expanded", type=bool))
            self.assertEqual(target.value("splitter/main"), [600, 400])
            self.assertTrue(
                target.value("migration/legacy_qsettings_v1", type=bool)
            )

            target.setValue("nav_collapsed_manual", False)
            legacy.setValue("nav_collapsed_manual", True)
            self.assertTrue(migrate_legacy_workbench_settings(target, legacy))
            self.assertFalse(target.value("nav_collapsed_manual", type=bool))

    def test_sync_reports_qsettings_write_failure(self):
        class FailingSettings:
            def sync(self):
                return None

            def status(self):
                return QSettings.AccessError

            def fileName(self):
                return "read-only/workbench.ini"

        self.assertFalse(sync_workbench_settings(FailingSettings()))


if __name__ == "__main__":
    unittest.main()
