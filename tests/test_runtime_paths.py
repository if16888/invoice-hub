"""Data-directory contract for source, Inno Setup and Microsoft Store MSIX runs.

Synthetic only: these tests read packaging sources and patch ``sys.frozen`` /
``APPDATA`` / ``INVOICE_HUB_RUNTIME_DIR``. No installer runs and no real user
data is read or written.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch.config import PROJECT_ROOT, _resolve_runtime_dir

PACKAGING_ROOT = PROJECT_ROOT / "packaging"
INNO_SCRIPT = PACKAGING_ROOT / "invoice_hub_windows.iss"
MSIX_TEMPLATE = PACKAGING_ROOT / "msix" / "AppxManifest.template.xml"
MSIX_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "windows-store-msix.yml"
DATA_PATH_NOTE = PROJECT_ROOT / "docs" / "installer-data-paths.md"


class RuntimeDirResolutionTests(unittest.TestCase):
    def test_source_run_uses_project_runtime_dir(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "sys.frozen", False, create=True
        ):
            self.assertEqual(_resolve_runtime_dir(), PROJECT_ROOT / "runtime")

    def test_frozen_run_uses_roaming_appdata_invoicehub(self):
        # Inno Setup and the portable ZIP both run frozen. The MSIX manifest
        # opts out of AppData virtualization so it resolves the same physical
        # directory instead of a package-private LocalCache copy.
        appdata = r"C:\Users\Synthetic\AppData\Roaming"
        with patch.dict(os.environ, {"APPDATA": appdata}, clear=True), patch(
            "sys.frozen", True, create=True
        ):
            self.assertEqual(_resolve_runtime_dir(), Path(appdata) / "InvoiceHub")

    def test_runtime_dir_override_wins_in_every_mode(self):
        override = r"D:\synthetic-runtime"
        appdata = r"C:\Users\Synthetic\AppData\Roaming"
        for frozen in (False, True):
            with self.subTest(frozen=frozen), patch.dict(
                os.environ,
                {"INVOICE_HUB_RUNTIME_DIR": override, "APPDATA": appdata},
                clear=True,
            ), patch("sys.frozen", frozen, create=True):
                self.assertEqual(_resolve_runtime_dir(), Path(override))

    def test_frozen_without_appdata_keeps_documented_fallback(self):
        # APPDATA always exists in an interactive desktop session; keep the
        # fallback explicit so a stripped environment cannot crash resolution.
        with patch.dict(os.environ, {}, clear=True), patch(
            "sys.frozen", True, create=True
        ):
            self.assertEqual(_resolve_runtime_dir(), PROJECT_ROOT / "runtime")


class InnoInstallerDataPathContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = INNO_SCRIPT.read_text(encoding="utf-8")

    def test_per_user_install_without_program_files_write_access(self):
        self.assertIn("PrivilegesRequired=lowest", self.source)
        self.assertIn(
            '#define DefaultInstallDir "{localappdata}\\Programs\\InvoiceHub"',
            self.source,
        )
        self.assertIn("DefaultDirName={#DefaultInstallDir}", self.source)
        self.assertNotIn("{pf}", self.source)
        self.assertNotIn("{commonpf}", self.source)

    def test_user_data_lives_outside_install_directory_and_survives_uninstall(self):
        self.assertIn("[UninstallDelete]", self.source)
        uninstall_section = self.source.split("[UninstallDelete]", 1)[1].split("[", 1)[0]
        self.assertNotIn("{userappdata}", uninstall_section)
        self.assertNotIn("{commonappdata}", uninstall_section)
        self.assertNotIn("filesandordirs", uninstall_section.lower())
        # Only empty installer-owned directories may be removed on uninstall.
        self.assertIn('Type: dirifempty; Name: "{app}\\exports"', uninstall_section)
        self.assertIn('Type: dirifempty; Name: "{app}"', uninstall_section)

    def test_installer_never_seeds_or_overwrites_user_data(self):
        self.assertNotIn("{userappdata}", self.source)
        self.assertNotIn("{commonappdata}", self.source)
        files_section = self.source.split("[Files]", 1)[1].split("[", 1)[0]
        self.assertIn('DestDir: "{app}"', files_section)
        self.assertNotIn("invoices.db", files_section)
        self.assertNotIn("config.json", files_section)


    def test_installer_lifecycle_probe_asserts_user_data_unchanged(self):
        # The real Inno install/upgrade/uninstall harness keeps AppData fixed
        # under a synthetic profile and asserts it is byte-identical afterwards.
        probe = (
            PROJECT_ROOT / "scripts" / "dev" / "verify_installer_lifecycle.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(r"AppData\InvoiceHub", probe)
        self.assertIn("Assert-UserDataUnchanged", probe)
        self.assertIn("Invoke-RegisteredUninstall", probe)


class MsixDataPathContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = MSIX_TEMPLATE.read_text(encoding="utf-8")
        cls.workflow = MSIX_WORKFLOW.read_text(encoding="utf-8")

    def test_msix_opts_out_of_appdata_virtualization(self):
        self.assertIn('Name="unvirtualizedResources"', self.template)
        self.assertIn("<virtualization:FileSystemWriteVirtualization>", self.template)
        self.assertIn(
            r"$(KnownFolder:RoamingAppData)\InvoiceHub",
            self.template,
        )
        ignorable = self.template.split("IgnorableNamespaces=", 1)[1].split('"', 2)[1]
        self.assertIn("virtualization", ignorable)

    def test_msix_min_version_supports_granular_unvirtualized_appdata(self):
        # The granular ExcludedDirectories behavior is documented as Windows 11
        # (the schema reference lists an older build floor); keep the
        # conservative Windows 11 minimum.
        self.assertIn('MinVersion="10.0.22000.0"', self.template)

    def test_store_workflow_stages_the_frozen_payload_with_this_manifest(self):
        self.assertIn("prepare_msix.py", self.workflow)
        self.assertIn("--payload-dir dist/InvoiceHub", self.workflow)
        self.assertIn("makeappx", self.workflow.lower())
        # The packing lane re-inspects the packed manifest so MakeAppx cannot
        # silently drop the AppData opt-out.
        for token in ("unvirtualizedResources", "FileSystemWriteVirtualization", "RoamingAppData"):
            with self.subTest(token=token):
                self.assertIn(token, self.workflow)


class InstallerDataPathDocumentationTests(unittest.TestCase):
    def test_data_path_note_documents_all_three_modes(self):
        self.assertTrue(DATA_PATH_NOTE.is_file(), f"missing {DATA_PATH_NOTE}")
        text = DATA_PATH_NOTE.read_text(encoding="utf-8")
        for marker in (
            "Source run",
            "Inno Setup",
            "MSIX",
            "%APPDATA%\\InvoiceHub",
            "INVOICE_HUB_RUNTIME_DIR",
            "unvirtualizedResources",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
