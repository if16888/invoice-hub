"""Contract tests for Microsoft Store MSIX staging."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

from scripts.dev.prepare_msix import (
    DEFAULT_TEMPLATE,
    render_manifest,
    stage_msix_layout,
    store_package_version,
    validate_package_version,
)
from scripts.invoice_fetch.version import VERSION


class TestStorePackageVersion(unittest.TestCase):
    def test_current_source_version_maps_to_store_safe_version(self):
        self.assertEqual(VERSION, "0.1.8")
        self.assertEqual(store_package_version(VERSION), "1.1.8.0")

    def test_mapping_preserves_semver_order_and_nonzero_store_major(self):
        self.assertEqual(store_package_version("0.1.9"), "1.1.9.0")
        self.assertEqual(store_package_version("0.2.0"), "1.2.0.0")
        self.assertEqual(store_package_version("1.0.0"), "2.0.0.0")

    def test_store_version_requires_four_bounded_numeric_parts(self):
        self.assertEqual(validate_package_version("1.1.8.0"), "1.1.8.0")
        for invalid in (
            "0.1.8.0",
            "1.1.8.1",
            "1.1.8",
            "1.1.8-rc3",
            "65536.1.1.0",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_package_version(invalid)

    def test_store_mapping_rejects_prerelease_source_version(self):
        with self.assertRaises(ValueError):
            store_package_version("0.1.8-rc3")


class TestStoreManifest(unittest.TestCase):
    def test_manifest_uses_partner_center_identity_and_full_trust_desktop_contract(self):
        template = DEFAULT_TEMPLATE.read_text(encoding="utf-8")
        manifest = render_manifest(
            template,
            identity_name="12345InvoiceHub.InvoiceHub",
            publisher="CN=01234567-89AB-CDEF-0123-456789ABCDEF",
            publisher_display_name="Invoice Hub Developer",
            display_name="Invoice Hub",
            description="发票 & 报销 <本地优先>",
            package_version="1.1.8.0",
        )

        ElementTree.fromstring(manifest)
        self.assertIn('Name="12345InvoiceHub.InvoiceHub"', manifest)
        self.assertIn('Publisher="CN=01234567-89AB-CDEF-0123-456789ABCDEF"', manifest)
        self.assertIn('Version="1.1.8.0"', manifest)
        self.assertIn('ProcessorArchitecture="x64"', manifest)
        self.assertIn('EntryPoint="Windows.FullTrustApplication"', manifest)
        self.assertIn('<rescap:Capability Name="runFullTrust" />', manifest)
        self.assertIn('Name="Windows.Desktop"', manifest)
        self.assertIn("发票 &amp; 报销 &lt;本地优先&gt;", manifest)
        self.assertNotIn("@@", manifest)

    def test_manifest_rejects_placeholder_identity(self):
        template = DEFAULT_TEMPLATE.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            render_manifest(
                template,
                identity_name="@@IDENTITY_NAME@@",
                publisher="CN=Publisher",
                publisher_display_name="Publisher",
                display_name="Invoice Hub",
                description="Invoice Hub",
                package_version="1.1.8.0",
            )


class TestStoreLayoutStaging(unittest.TestCase):
    def _write_logo(self, path: Path) -> None:
        Image.new("RGBA", (256, 128), (255, 255, 255, 255)).save(path, format="PNG")

    def test_stage_copies_frozen_payload_and_generates_manifest_assets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = root / "payload"
            payload.mkdir()
            (payload / "InvoiceHub.exe").write_bytes(b"synthetic-frozen-exe")
            (payload / "LICENSE").write_text("license", encoding="utf-8")
            internal = payload / "internal"
            internal.mkdir()
            (internal / "dependency.dll").write_bytes(b"dll")

            logo = root / "logo.png"
            self._write_logo(logo)
            output = root / "msix-layout"

            metadata = stage_msix_layout(
                payload_dir=payload,
                output_dir=output,
                template_path=DEFAULT_TEMPLATE,
                logo_path=logo,
                identity_name="12345InvoiceHub.InvoiceHub",
                publisher="CN=01234567-89AB-CDEF-0123-456789ABCDEF",
                publisher_display_name="Invoice Hub Developer",
            )

            self.assertEqual(metadata["source_version"], VERSION)
            self.assertEqual(metadata["package_version"], "1.1.8.0")
            self.assertEqual(metadata["distribution"], "microsoft-store-msix")
            self.assertEqual((output / "InvoiceHub.exe").read_bytes(), b"synthetic-frozen-exe")
            self.assertTrue((output / "internal" / "dependency.dll").is_file())
            self.assertTrue((output / "AppxManifest.xml").is_file())

            expected_assets = {
                "Square44x44Logo.png": (44, 44),
                "Square150x150Logo.png": (150, 150),
                "StoreLogo.png": (50, 50),
            }
            for name, size in expected_assets.items():
                with self.subTest(name=name):
                    path = output / "Assets" / name
                    self.assertTrue(path.is_file())
                    with Image.open(path) as image:
                        self.assertEqual(image.size, size)

    def test_stage_requires_real_frozen_executable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = root / "payload"
            payload.mkdir()
            logo = root / "logo.png"
            self._write_logo(logo)

            with self.assertRaises(FileNotFoundError):
                stage_msix_layout(
                    payload_dir=payload,
                    output_dir=root / "output",
                    template_path=DEFAULT_TEMPLATE,
                    logo_path=logo,
                    identity_name="12345InvoiceHub.InvoiceHub",
                    publisher="CN=01234567-89AB-CDEF-0123-456789ABCDEF",
                    publisher_display_name="Invoice Hub Developer",
                )


class TestStoreWorkflowPolicy(unittest.TestCase):
    def test_store_workflow_is_manual_exact_master_and_does_not_publish(self):
        workflow = Path(".github/workflows/windows-store-msix.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn('refs/heads/master', workflow)
        self.assertIn("origin/master", workflow)
        self.assertIn("prepare_msix.py", workflow)
        self.assertIn("makeappx.exe", workflow.lower())
        self.assertIn("makeappx_path", workflow.lower())
        self.assertIn("validate /p", workflow.lower())
        self.assertIn("upload-artifact@v4", workflow)
        self.assertNotIn("action-gh-release", workflow)
        self.assertNotIn("Sign installer", workflow)
        self.assertNotIn("SIGNTOOL_PATH", workflow)

    def test_existing_inno_release_path_remains_present_during_migration(self):
        self.assertTrue(Path("packaging/invoice_hub_windows.iss").is_file())
        self.assertTrue(Path(".github/workflows/windows-release.yml").is_file())


if __name__ == "__main__":
    unittest.main()
