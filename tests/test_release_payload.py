# -*- coding: utf-8 -*-
"""Guard the Windows release payload and the packaging spec that builds it.

The release workflow runs ``pyinstaller packaging/invoice_hub_windows.spec``.
That spec now refuses to build when the PDF viewer, its CMap/font data, the GUI
assets, the license files or the Playwright driver are missing — each of those
used to produce an installer that installs and then fails at runtime.

The legacy root ``InvoiceHub.spec`` built ``launcher.py`` with an empty payload
list and was referenced by no workflow, so it was removed; these tests keep it
from coming back.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING_SPEC = ROOT / "packaging" / "invoice_hub_windows.spec"

sys.path.insert(0, str(ROOT / "packaging"))
import release_payload  # noqa: E402


def _write_required_payload(root: Path) -> None:
    for name in release_payload.REQUIRED_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic", encoding="utf-8")
    for name in release_payload.REQUIRED_DIRS:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "placeholder.txt").write_text("synthetic", encoding="utf-8")
    for name in release_payload.REQUIRED_FILES_RELATIVE:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic", encoding="utf-8")


class ReleasePayloadTests(unittest.TestCase):
    def test_repository_contains_the_full_release_payload(self):
        missing = release_payload.collect_missing_payload(ROOT)
        self.assertEqual(missing, [], f"发布包必需文件缺失: {missing}")

    def test_complete_payload_passes_on_a_synthetic_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_required_payload(root)
            release_payload.require_release_payload(root)

    def test_missing_payload_entries_abort_the_build(self):
        removals = [
            "config.example.json",
            "LICENSE",
            "THIRD_PARTY_NOTICES.md",
            "scripts/invoice_fetch/web_assets/pdfjs/pdf.min.mjs",
            "scripts/invoice_fetch/web_assets/pdfjs",
            "scripts/invoice_fetch/gui/assets",
        ]
        for removed in removals:
            with self.subTest(removed=removed), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                _write_required_payload(root)
                target = root / removed
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()

                missing = release_payload.collect_missing_payload(root)
                self.assertIn(
                    removed if removed in missing else removed + "/",
                    missing,
                )
                with self.assertRaises(FileNotFoundError):
                    release_payload.require_release_payload(root)

    def test_empty_payload_directory_counts_as_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_required_payload(root)
            empty = root / "scripts/invoice_fetch/web_assets/pdfjs/cmaps"
            for entry in empty.iterdir():
                entry.unlink()

            self.assertIn(
                "scripts/invoice_fetch/web_assets/pdfjs/cmaps/",
                release_payload.collect_missing_payload(root),
            )

    def test_playwright_driver_must_be_present(self):
        with tempfile.TemporaryDirectory() as td:
            driver = Path(td) / "driver"
            with self.assertRaises(FileNotFoundError):
                release_payload.require_playwright_driver(driver)

            driver.mkdir()
            (driver / "playwright.cmd").write_text("echo", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                release_payload.require_playwright_driver(driver)
            (driver / "node.exe").write_bytes(b"node executable")
            with self.assertRaises(FileNotFoundError):
                release_payload.require_playwright_driver(driver)
            (driver / "package").mkdir()
            (driver / "package" / "cli.js").write_text("driver CLI", encoding="utf-8")
            release_payload.require_playwright_driver(driver)
            (driver / "node.exe").unlink()
            (driver / "node").write_bytes(b"node executable")
            release_payload.require_playwright_driver(driver)
            (driver / "package" / "cli.js").write_bytes(b"")
            with self.assertRaises(FileNotFoundError):
                release_payload.require_playwright_driver(driver)

    def test_installed_playwright_driver_matches_payload_contract(self):
        import playwright
        release_payload.require_playwright_driver(Path(playwright.__file__).parent / "driver")

    def test_release_spec_uses_the_shared_payload_guard(self):
        spec_text = PACKAGING_SPEC.read_text(encoding="utf-8")
        self.assertIn("release_payload.py", spec_text)
        self.assertIn("require_release_payload(_root)", spec_text)
        self.assertIn("require_playwright_driver(_pw_driver)", spec_text)
        # The spec is executed by PyInstaller, so at least prove it compiles.
        compile(spec_text, str(PACKAGING_SPEC), "exec")

    def test_release_workflows_build_the_packaging_spec(self):
        checked = 0
        for workflow in ("windows-release.yml", "windows-store-msix.yml"):
            path = ROOT / ".github" / "workflows" / workflow
            if not path.exists():
                continue
            checked += 1
            self.assertIn(
                "packaging/invoice_hub_windows.spec",
                path.read_text(encoding="utf-8"),
                workflow,
            )
        self.assertGreater(checked, 0, "至少应存在一个发布工作流")

    def test_legacy_root_spec_is_gone(self):
        """The root spec built launcher.py with no payload and no workflow used it."""
        self.assertFalse((ROOT / "InvoiceHub.spec").exists())


if __name__ == "__main__":
    unittest.main()
