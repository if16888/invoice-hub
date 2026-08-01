import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch.export_paths import (
    default_export_directory,
    migrate_legacy_exports,
    resolve_export_directory,
)


class ExportPathsTests(unittest.TestCase):

    def test_default_export_path_is_user_documents_not_install_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Program Files" / "InvoiceHub"
            target = default_export_directory(root / "Documents")
            self.assertEqual(
                target,
                root / "Documents" / "Invoice Hub" / "Exports",
            )
            self.assertNotIn(install, target.parents)

    def test_custom_export_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "chosen" / "packages"
            self.assertEqual(
                resolve_export_directory(
                    {"export": {"output_dir": str(custom)}},
                    Path(tmp) / "Documents",
                ),
                custom,
            )

    def test_legacy_exports_migrate_and_repeat_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "app" / "exports"
            target = root / "Documents" / "Invoice Hub" / "Exports"
            (source / "claim").mkdir(parents=True)
            (source / "claim" / "manifest.json").write_text("one", encoding="utf-8")
            first = migrate_legacy_exports(source, target)
            second = migrate_legacy_exports(source, target)
            self.assertEqual(first.copied, 1)
            self.assertEqual(first.processed, 1)
            self.assertFalse(first.source_remains)
            self.assertEqual(
                (target / "claim" / "manifest.json").read_text(encoding="utf-8"),
                "one",
            )
            self.assertFalse(second.attempted)

    def test_same_name_conflict_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "app" / "exports"
            target = root / "docs"
            source.mkdir(parents=True)
            target.mkdir()
            (source / "report.xlsx").write_bytes(b"legacy")
            (target / "report.xlsx").write_bytes(b"current")
            result = migrate_legacy_exports(source, target)
            self.assertEqual(result.conflicts, 1)
            self.assertEqual((target / "report.xlsx").read_bytes(), b"current")
            self.assertEqual(
                list(target.glob("report.migrated-*.xlsx"))[0].read_bytes(),
                b"legacy",
            )

    def test_migration_failure_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "app" / "exports"
            target = root / "docs"
            source.mkdir(parents=True)
            original = source / "report.xlsx"
            original.write_bytes(b"legacy")

            with patch(
                "scripts.invoice_fetch.export_paths.shutil.copy2",
                side_effect=PermissionError("denied"),
            ):
                result = migrate_legacy_exports(source, target)
            self.assertTrue(result.failures)
            self.assertTrue(result.source_remains)
            self.assertEqual(original.read_bytes(), b"legacy")

    def test_migration_reports_progress_for_many_small_and_large_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "app" / "exports"
            target = root / "Documents" / "Invoice Hub" / "Exports"
            source.mkdir(parents=True)
            for index in range(64):
                folder = source / f"claim-{index % 4}"
                folder.mkdir(exist_ok=True)
                (folder / f"small-{index}.json").write_text(
                    f"payload-{index}",
                    encoding="utf-8",
                )
            (source / "large-report.bin").write_bytes(b"x" * (2 * 1024 * 1024))

            events = []
            result = migrate_legacy_exports(source, target, events.append)

            self.assertEqual(result.total, 65)
            self.assertEqual(result.processed, 65)
            self.assertEqual(result.copied, 65)
            self.assertFalse(result.failures)
            self.assertFalse(result.source_remains)
            self.assertGreaterEqual(len(events), 4)
            self.assertEqual(events[0]["processed"], 0)
            self.assertEqual(events[-1]["processed"], 65)
            self.assertEqual(events[-1]["total"], 65)
            self.assertEqual(
                (target / "large-report.bin").stat().st_size,
                2 * 1024 * 1024,
            )


if __name__ == "__main__":
    unittest.main()
