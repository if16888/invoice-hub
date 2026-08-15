"""Regression tests for versioned installer ownership recovery."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.dev.generate_installer_ownership import (
    OwnershipRecord,
    build_records,
    compute_legacy_obsolete,
    normalize_relative_path,
    read_manifest,
    write_inno_include,
    write_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestInstallerOwnershipData(unittest.TestCase):
    def test_normalize_rejects_paths_that_could_escape_app_directory(self):
        for value in ("", "/absolute.txt", "C:\\absolute.txt", "..\\outside.txt", "a\\..\\b"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_relative_path(value)

    def test_manifest_round_trip_preserves_size_and_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "payload"
            root.mkdir()
            file_path = root / "legacy" / "old-only.dll"
            file_path.parent.mkdir()
            file_path.write_bytes(b"historical payload")
            records = build_records(root)
            manifest = Path(td) / "rc1-files.txt"

            write_manifest(
                records,
                manifest,
                release="v0.1.5-rc1",
                asset_name="fixture.zip",
                asset_sha256="0" * 64,
            )

            self.assertEqual(read_manifest(manifest), records)
            self.assertEqual(records[0].size, len(b"historical payload"))
            self.assertEqual(
                records[0].sha256,
                hashlib.sha256(b"historical payload").hexdigest(),
            )

    def test_obsolete_set_is_path_based_and_keeps_distinct_historical_hashes(self):
        current = [OwnershipRecord("InvoiceHub.exe", 3, "a" * 64)]
        legacy = [
            OwnershipRecord("legacy/old.dll", 1, "b" * 64),
            OwnershipRecord("legacy/old.dll", 2, "c" * 64),
            OwnershipRecord("InvoiceHub.exe", 3, "d" * 64),
        ]

        obsolete = compute_legacy_obsolete(current, legacy)

        self.assertEqual(len(obsolete), 2)
        self.assertEqual({record.sha256 for record in obsolete}, {"b" * 64, "c" * 64})

    def test_inno_include_is_hash_checked_data_not_a_wildcard(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "installer_ownership.issinc"
            records = [OwnershipRecord("legacy\\old.dll", 7, "f" * 64)]
            write_inno_include(records, output, source_manifests=[Path("rc1-files.txt")])
            text = output.read_text(encoding="utf-8")

            self.assertIn("LegacyOwnershipCount = 1;", text)
            self.assertIn("legacy\\old.dll|" + "f" * 64, text)
            self.assertIn("#13#10", text)
            self.assertNotIn("LegacyOwnershipPaths", text)
            self.assertNotIn("*", text)

    def test_official_legacy_manifests_are_present_and_nonempty(self):
        expected = {
            "v0.1.5-rc1-files.txt": "b70e75101ee0786e03995a8594f4918286a54bf7e10e56031bb6725ab8fa2c41",
            "v0.1.5-rc2-files.txt": "b24c59640cf42201d3241a6d61b31a2bcb9275f9567c45a3d2693d940468a269",
        }
        for name, asset_hash in expected.items():
            with self.subTest(name=name):
                manifest = PROJECT_ROOT / "packaging" / "legacy" / name
                self.assertTrue(manifest.exists())
                text = manifest.read_text(encoding="utf-8")
                self.assertIn(f"# asset_sha256={asset_hash}", text)
                self.assertGreater(len(read_manifest(manifest)), 0)


class TestInstallerOwnershipContract(unittest.TestCase):
    def test_inno_uninstaller_uses_exact_historical_hashes_and_safe_paths(self):
        source = (PROJECT_ROOT / "packaging" / "invoice_hub_windows.iss").read_text(
            encoding="utf-8"
        )
        for token in (
            '#include "legacy\\installer_ownership.issinc"',
            "LegacyOwnershipData",
            "GetSHA256OfFile",
            "LegacyPathHasReparsePoint",
            "ProtectLegacyFilesBeforeNativeUninstall",
            "FailLegacyProtection",
            "RestoreLegacyFilesAfterNativeUninstall",
            "RemoveKnownLegacyOwnedFiles",
            "RemoveEmptyDirectoryTree",
            "FILE_ATTRIBUTE_REPARSE_POINT",
            "Refusing to touch a legacy path below a reparse point",
            "Abort;",
        ):
            self.assertIn(token, source)
        self.assertNotIn('Name: "{app}\\*"', source)
        self.assertNotIn("filesandordirs", source.lower())

    def test_release_workflow_generates_current_ownership_before_inno(self):
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "windows-release.yml").read_text(
            encoding="utf-8"
        )
        generator = "scripts\\dev\\generate_installer_ownership.py include"
        self.assertIn(generator, workflow)
        self.assertIn("v0.1.5-rc1-files.txt", workflow)
        self.assertIn("v0.1.5-rc2-files.txt", workflow)
        self.assertIn("build\\current-installer-files.txt", workflow)
        self.assertLess(workflow.index(generator), workflow.index("Build Inno Setup installer"))
        self.assertIn("Verify installer lifecycle ownership recovery", workflow)
        self.assertIn("-InstallRoot $env:TEMP", workflow)


if __name__ == "__main__":
    unittest.main()
