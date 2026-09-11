"""Contract tests for Microsoft Store MSIX staging."""

from __future__ import annotations

import subprocess
import sys
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestStorePackageVersion(unittest.TestCase):
    def test_current_source_version_maps_deterministically(self):
        major, minor, patch = (int(part) for part in VERSION.split("."))
        expected = f"{major + 1}.{minor}.{patch}.0"
        self.assertEqual(store_package_version(VERSION), expected)

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

    def _write_payload(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "InvoiceHub.exe").write_bytes(b"synthetic-frozen-exe")
        (path / "LICENSE").write_text("license", encoding="utf-8")

    def _stage(
        self,
        *,
        payload: Path,
        output: Path,
        logo: Path,
        template: Path = DEFAULT_TEMPLATE,
    ) -> dict[str, str]:
        return stage_msix_layout(
            payload_dir=payload,
            output_dir=output,
            template_path=template,
            logo_path=logo,
            identity_name="12345InvoiceHub.InvoiceHub",
            publisher="CN=01234567-89AB-CDEF-0123-456789ABCDEF",
            publisher_display_name="Invoice Hub Developer",
        )

    def test_stage_copies_frozen_payload_and_generates_manifest_assets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = root / "payload"
            self._write_payload(payload)
            internal = payload / "internal"
            internal.mkdir()
            (internal / "dependency.dll").write_bytes(b"dll")

            logo = root / "logo.png"
            self._write_logo(logo)
            output = root / "msix-layout"

            metadata = self._stage(payload=payload, output=output, logo=logo)

            self.assertEqual(metadata["source_version"], VERSION)
            self.assertEqual(metadata["package_version"], store_package_version(VERSION))
            self.assertEqual(metadata["distribution"], "microsoft-store-msix")
            self.assertEqual((output / "InvoiceHub.exe").read_bytes(), b"synthetic-frozen-exe")
            self.assertTrue((output / "internal" / "dependency.dll").is_file())
            manifest_path = output / "AppxManifest.xml"
            self.assertTrue(manifest_path.is_file())
            manifest = manifest_path.read_text(encoding="utf-8")
            self.assertIn("invoice-hub-msix-staging-owner:v1", manifest)
            ElementTree.fromstring(manifest)

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
                self._stage(payload=payload, output=root / "output", logo=logo)

    def test_stage_rejects_payload_output_overlap_before_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logo = root / "logo.png"
            self._write_logo(logo)

            payload = root / "payload"
            self._write_payload(payload)
            exe = payload / "InvoiceHub.exe"

            for output in (payload, payload / "nested-output"):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    self._stage(payload=payload, output=output, logo=logo)
                self.assertTrue(exe.is_file())

            parent_output = root / "parent-output"
            nested_payload = parent_output / "payload"
            self._write_payload(nested_payload)
            unrelated = parent_output / "keep-me.txt"
            unrelated.write_text("keep", encoding="utf-8")

            with self.assertRaises(ValueError):
                self._stage(payload=nested_payload, output=parent_output, logo=logo)
            self.assertTrue((nested_payload / "InvoiceHub.exe").is_file())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

    def test_stage_rejects_output_containing_template_or_logo_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = root / "payload"
            self._write_payload(payload)

            output = root / "unsafe-output"
            output.mkdir()
            template = output / "AppxManifest.template.xml"
            template.write_text(DEFAULT_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
            logo = output / "logo.png"
            self._write_logo(logo)
            keep = output / "keep-me.txt"
            keep.write_text("keep", encoding="utf-8")

            with self.assertRaises(ValueError):
                self._stage(payload=payload, output=output, logo=logo, template=template)
            self.assertTrue(template.is_file())
            self.assertTrue(logo.is_file())
            self.assertEqual(keep.read_text(encoding="utf-8"), "keep")

    def test_stage_refuses_to_delete_existing_unowned_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = root / "payload"
            self._write_payload(payload)
            logo = root / "logo.png"
            self._write_logo(logo)
            output = root / "existing-output"
            output.mkdir()
            keep = output / "keep-me.txt"
            keep.write_text("keep", encoding="utf-8")

            with self.assertRaises(ValueError):
                self._stage(payload=payload, output=output, logo=logo)
            self.assertEqual(keep.read_text(encoding="utf-8"), "keep")
            self.assertTrue((payload / "InvoiceHub.exe").is_file())

    def test_stage_replaces_only_prior_owned_staging(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = root / "payload"
            self._write_payload(payload)
            logo = root / "logo.png"
            self._write_logo(logo)
            output = root / "msix-layout"

            self._stage(payload=payload, output=output, logo=logo)
            stale = output / "stale.txt"
            stale.write_text("stale", encoding="utf-8")

            self._stage(payload=payload, output=output, logo=logo)
            self.assertFalse(stale.exists())
            self.assertTrue((output / "InvoiceHub.exe").is_file())
            self.assertIn(
                "invoice-hub-msix-staging-owner:v1",
                (output / "AppxManifest.xml").read_text(encoding="utf-8"),
            )

    def test_prepare_script_is_runnable_by_path(self):
        result = subprocess.run(
            [sys.executable, "scripts/dev/prepare_msix.py", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--identity-name", result.stdout)
        self.assertNotIn("--package-version", result.stdout)


class TestStoreWorkflowPolicy(unittest.TestCase):
    def _workflow(self) -> str:
        return (PROJECT_ROOT / ".github" / "workflows" / "windows-store-msix.yml").read_text(
            encoding="utf-8"
        )

    def test_store_workflow_is_manual_exact_master_and_does_not_publish(self):
        workflow = self._workflow()
        lowered = workflow.lower()
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn('refs/heads/master', workflow)
        self.assertIn("origin/master", workflow)
        self.assertIn("prepare_msix.py", workflow)
        self.assertIn("makeappx.exe", lowered)
        self.assertIn("makeappx_path", lowered)
        self.assertIn(" pack /d ", lowered)
        self.assertIn(" unpack /p ", lowered)
        self.assertNotIn("makeappx_path validate", lowered)
        self.assertNotIn(" /nv", lowered)
        self.assertIn("expectedNameAttribute", workflow)
        self.assertIn("expectedVersionAttribute", workflow)
        self.assertIn("upload-artifact@v4", workflow)
        self.assertNotIn("action-gh-release", workflow)
        self.assertNotIn("Sign installer", workflow)
        self.assertNotIn("SIGNTOOL_PATH", workflow)

    def test_store_source_gates_are_independent_fail_fast_steps(self):
        workflow = self._workflow()
        gate_commands = (
            "python scripts/check_repo_privacy.py",
            "python scripts/check_public_export.py .",
            "python scripts/check_release_metadata.py",
            "python scripts/check_architecture_policy.py",
            "python -m compileall -q scripts/invoice_fetch scripts/dev/prepare_msix.py",
        )
        self.assertNotIn("- name: Run release source gates", workflow)
        for command in gate_commands:
            with self.subTest(command=command):
                self.assertEqual(workflow.count(f"run: {command}"), 1)

    def test_existing_inno_release_path_remains_present_during_migration(self):
        self.assertTrue((PROJECT_ROOT / "packaging" / "invoice_hub_windows.iss").is_file())
        self.assertTrue((PROJECT_ROOT / ".github" / "workflows" / "windows-release.yml").is_file())


if __name__ == "__main__":
    unittest.main()
