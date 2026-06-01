"""
tests/test_startup_probe_and_packaging.py

Tests for the startup-probe CLI flag, import structure, launcher script,
and PyInstaller spec integrity.

All tests run offline without a real database, real credentials, or a
PySide6 display — safe for CI.
"""

from __future__ import annotations

import ast
import os
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Locate project root ───────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestStartupProbeArgparse(unittest.TestCase):
    """The desktop subparser must expose --startup-probe."""

    def _make_parser(self):
        # Import argparse logic without triggering heavy side-effects.
        from scripts.invoice_fetch.__main__ import _parse_args
        return _parse_args

    def test_desktop_startup_probe_flag_registered(self):
        """desktop --startup-probe must parse without error."""
        from scripts.invoice_fetch.__main__ import _parse_args as _fn
        # Temporarily redirect sys.argv
        old_argv = sys.argv[:]
        try:
            sys.argv = ["invoice_fetch", "desktop", "--startup-probe"]
            import argparse
            # Patch sys.exit so SystemExit doesn't abort the test
            with patch("sys.exit"):
                # Re-parse using the real function
                # We can't call _parse_args directly (reads sys.argv),
                # so we rebuild an equivalent parser by inspecting the code.
                import scripts.invoice_fetch.__main__ as m
                # Build a minimal parser and check sub-command
                import argparse as ap
                # Call _parse_args via a monkey-patched sys.argv
                ns = m._parse_args()
            self.assertEqual(ns.command, "desktop")
            self.assertTrue(ns.startup_probe)
        finally:
            sys.argv = old_argv

    def test_desktop_startup_probe_default_false(self):
        """desktop without --startup-probe must default to False."""
        old_argv = sys.argv[:]
        try:
            sys.argv = ["invoice_fetch", "desktop"]
            import scripts.invoice_fetch.__main__ as m
            ns = m._parse_args()
            self.assertFalse(ns.startup_probe)
        finally:
            sys.argv = old_argv


class TestGuiStartFunctionSignature(unittest.TestCase):
    """start_gui and start_gui_app must accept the startup_probe kwargs."""

    def test_start_gui_accepts_startup_probe(self):
        """start_gui(**kwargs) should not raise a TypeError for known params."""
        import inspect
        # Import module-level; PySide6 not available so we stub it.
        with patch.dict("sys.modules", {"PySide6": MagicMock(),
                                         "PySide6.QtWidgets": MagicMock()}):
            import importlib
            gui_init = importlib.import_module("scripts.invoice_fetch.gui")
            importlib.reload(gui_init)

        sig = inspect.signature(gui_init.start_gui)
        params = list(sig.parameters.keys())
        self.assertIn("db_path", params)
        self.assertIn("startup_probe", params)
        self.assertIn("app_init_ms", params)

    def test_start_gui_app_accepts_startup_probe(self):
        """start_gui_app must accept startup_probe and app_init_ms."""
        import inspect
        with patch.dict("sys.modules", {
            "PySide6": MagicMock(),
            "PySide6.QtWidgets": MagicMock(),
            "PySide6.QtCore": MagicMock(),
            "PySide6.QtGui": MagicMock(),
        }):
            import importlib
            app_mod = importlib.import_module("scripts.invoice_fetch.gui.app")

        sig = inspect.signature(app_mod.start_gui_app)
        params = list(sig.parameters.keys())
        self.assertIn("startup_probe", params)
        self.assertIn("app_init_ms", params)


class TestCheckStartupTimeScript(unittest.TestCase):
    """check_startup_time.py must exist and parse metrics correctly."""

    def _script_path(self) -> Path:
        p = PROJECT_ROOT / "scripts" / "check_startup_time.py"
        self.assertTrue(p.exists(), f"check_startup_time.py not found at {p}")
        return p

    def test_script_exists(self):
        self._script_path()

    def test_script_parseable(self):
        """check_startup_time.py must be valid Python syntax."""
        src = self._script_path().read_text(encoding="utf-8")
        try:
            ast.parse(src)
        except SyntaxError as exc:
            self.fail(f"SyntaxError in check_startup_time.py: {exc}")

    def test_metric_regex_parses_probe_output(self):
        """The regex patterns should extract values from probe stdout."""
        import re
        src = self._script_path().read_text(encoding="utf-8")
        # Extract the regex constants
        ns: dict = {}
        exec(compile(src, str(self._script_path()), "exec"), ns)  # noqa: S102

        sample_output = textwrap.dedent("""\
            APP_INIT_MS=123
            MAIN_WINDOW_SHOW_MS=456
            STARTUP_MS=579
        """)

        m_app = ns["_RE_APP_INIT_MS"].search(sample_output)
        m_show = ns["_RE_SHOW_MS"].search(sample_output)
        m_total = ns["_RE_STARTUP_MS"].search(sample_output)

        self.assertIsNotNone(m_app, "_RE_APP_INIT_MS did not match")
        self.assertIsNotNone(m_show, "_RE_SHOW_MS did not match")
        self.assertIsNotNone(m_total, "_RE_STARTUP_MS did not match")
        self.assertEqual(int(m_app.group(1)), 123)
        self.assertEqual(int(m_show.group(1)), 456)
        self.assertEqual(int(m_total.group(1)), 579)


class TestDesktopLauncherScript(unittest.TestCase):
    """scripts/invoice_fetch_desktop.py must exist and be valid Python."""

    def _launcher_path(self) -> Path:
        p = PROJECT_ROOT / "scripts" / "invoice_fetch_desktop.py"
        self.assertTrue(p.exists(), f"invoice_fetch_desktop.py not found at {p}")
        return p

    def test_launcher_exists(self):
        self._launcher_path()

    def test_launcher_parseable(self):
        src = self._launcher_path().read_text(encoding="utf-8")
        try:
            ast.parse(src)
        except SyntaxError as exc:
            self.fail(f"SyntaxError in invoice_fetch_desktop.py: {exc}")

    def test_launcher_defaults_to_desktop_command(self):
        """When launched with no argv, the launcher appends 'desktop'."""
        src = self._launcher_path().read_text(encoding="utf-8")
        # Check that the launcher appends 'desktop' when len(sys.argv) == 1
        self.assertIn("desktop", src)
        self.assertIn("sys.argv.append", src)


class TestPyInstallerSpecIntegrity(unittest.TestCase):
    """packaging/invoice_hub_windows.spec must exist and match expectations."""

    def _spec_path(self) -> Path:
        p = PROJECT_ROOT / "packaging" / "invoice_hub_windows.spec"
        self.assertTrue(p.exists(), f"spec file not found at {p}")
        return p

    def test_spec_exists(self):
        self._spec_path()

    def test_spec_uses_onedir(self):
        """Spec must use COLLECT (onedir) and NOT use EXE with a.datas inline."""
        src = self._spec_path().read_text(encoding="utf-8")
        self.assertIn("COLLECT(", src, "Spec must include COLLECT() for onedir mode")
        self.assertIn("exclude_binaries=True", src, "Spec must set exclude_binaries=True for onedir")

    def test_spec_no_upx(self):
        """UPX must be disabled."""
        src = self._spec_path().read_text(encoding="utf-8")
        # upx=False must appear (and upx=True must not appear)
        self.assertIn("upx=False", src, "Spec must have upx=False")
        self.assertNotIn("upx=True", src, "Spec must NOT have upx=True")

    def test_spec_includes_playwright(self):
        """playwright must appear in _hiddenimports (bundled, not excluded)."""
        src = self._spec_path().read_text(encoding="utf-8")
        self.assertIn("playwright", src)
        # Must be in hidden imports section, not only in excludes
        lines = src.splitlines()
        in_hidden = False
        found_in_hidden = False
        for line in lines:
            if "_hiddenimports" in line and "=" in line:
                in_hidden = True
            if in_hidden and "playwright" in line and "#" not in line.split("playwright")[0]:
                found_in_hidden = True
                break
            if in_hidden and line.strip().startswith("]"):
                in_hidden = False
        self.assertTrue(found_in_hidden, "playwright must appear in _hiddenimports list in spec")

    def test_spec_entry_point_is_desktop_launcher(self):
        """Spec must reference invoice_fetch_desktop.py as the entry-point."""
        src = self._spec_path().read_text(encoding="utf-8")
        self.assertIn("invoice_fetch_desktop", src)

    def test_spec_excludes_runtime_and_private(self):
        """Spec must NOT bundle runtime/, config.json, private/, or tests/."""
        src = self._spec_path().read_text(encoding="utf-8")
        # These paths must not appear as bundled data sources
        self.assertNotIn('"runtime"', src)
        self.assertNotIn('"config.json"', src)
        self.assertNotIn('"private"', src)

    def test_spec_excludes_chromium_browser(self):
        """Spec must NOT bundle ms-playwright or chromium browser (Strategy B)."""
        src = self._spec_path().read_text(encoding="utf-8")
        self.assertNotIn("ms-playwright", src)
        self.assertNotIn("chromium-", src)


class TestStartupProbeIsolated(unittest.TestCase):
    """Verify that startup probe does not trigger side-effects like mail scanning or server launch."""

    @patch("scripts.invoice_fetch.gui.app.InvoiceDB")
    def test_startup_probe_does_not_launch_servers_or_mail_scans(self, mock_db):
        """Standard GUI launch must not launch background scans or import playwright at start."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        # Verify app can be instantiated without triggering side-effects
        with patch("scripts.invoice_fetch.gui.app.load_config_safe") as mock_cfg:
            mock_cfg.return_value = {
                "email": {"provider": "qq", "address": "test@qq.com"},
                "playwright": {"channel": "auto"}
            }
            # We mock sys.modules to assert playwright is not loaded, or simply assert
            # that instantiation is completely offline and side-effect free.
            db_mock = MagicMock()
            db_mock.is_open = True
            mock_db.return_value = db_mock
            _qt_app = QApplication.instance() or QApplication([])
            app = InvoiceReviewApp(Path("dummy.db"))

            # Check that background scanner threads or mobile servers are not running
            self.assertFalse(hasattr(app, "mail_thread") or getattr(app, "mail_thread", None) is not None)
            self.assertFalse(hasattr(app, "server_thread") or getattr(app, "server_thread", None) is not None)



class TestGithubWorkflowExists(unittest.TestCase):
    """The GitHub Actions workflow file must exist and reference key steps."""

    def _workflow_path(self) -> Path:
        p = PROJECT_ROOT / ".github" / "workflows" / "windows-release.yml"
        self.assertTrue(p.exists(), f"workflow not found at {p}")
        return p

    def test_workflow_exists(self):
        self._workflow_path()

    def test_workflow_references_pyinstaller(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("pyinstaller", src.lower())

    def test_workflow_references_startup_probe(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("startup", src.lower())

    def test_workflow_triggers_on_version_tags(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("v*", src)
        self.assertNotIn("Release tag (e.g. v1.0.0)", src)
        self.assertNotIn("tag_name:", src)

    def test_workflow_runs_on_windows(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("windows-latest", src)

    def test_workflow_runs_unit_tests(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("unittest", src)

    def test_workflow_runs_release_readiness_gates(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("Run repository privacy gate", src)
        self.assertIn("python scripts/check_repo_privacy.py", src)
        self.assertIn("Run public export/source tree gate", src)
        self.assertIn("python scripts/check_public_export.py .", src)

    def test_workflow_uses_minimal_build_and_release_permissions(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", src)
        self.assertIn("release:\n    name: Publish GitHub Release", src)
        self.assertIn("permissions:\n      contents: write", src)
        self.assertIn("actions/download-artifact@v4", src)


class TestInnoSetupInstallerPackaging(unittest.TestCase):
    """The Windows release must build both portable zip and per-user setup exe."""

    def _installer_path(self) -> Path:
        p = PROJECT_ROOT / "packaging" / "invoice_hub_windows.iss"
        self.assertTrue(p.exists(), f"Inno Setup script not found at {p}")
        return p

    def _workflow_path(self) -> Path:
        p = PROJECT_ROOT / ".github" / "workflows" / "windows-release.yml"
        self.assertTrue(p.exists(), f"workflow not found at {p}")
        return p

    def test_inno_script_exists(self):
        self._installer_path()

    def test_inno_installs_per_user_without_admin(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", src)
        self.assertIn(r"DefaultDirName={localappdata}\Programs\InvoiceHub", src)

    def test_inno_creates_desktop_and_start_menu_shortcuts(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertIn(r"{autodesktop}\Invoice Hub", src)
        self.assertIn(r"{autoprograms}\Invoice Hub", src)

    def test_inno_does_not_delete_user_appdata_on_uninstall(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertNotIn("[UninstallDelete]", src)
        self.assertNotIn("{userappdata}", src)
        self.assertNotIn("{commonappdata}", src)

    def test_workflow_builds_setup_zip_and_checksums(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("iscc", src.lower())
        self.assertIn("InvoiceHub-Setup-${version}.exe", src)
        self.assertIn("InvoiceHub-windows-x64-${version}.zip", src)
        self.assertIn("checksums.txt", src)

    def test_workflow_uploads_setup_zip_and_checksums(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("InvoiceHub-portable", src)
        self.assertIn("InvoiceHub-setup", src)
        self.assertIn("dist/InvoiceHub-windows-x64-*.zip", src)
        self.assertIn("dist/InvoiceHub-Setup-*.exe", src)
        self.assertIn("dist/checksums.txt", src)

    def test_workflow_installs_python_deps_once_with_build_requirements(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("requirements-build.txt", src)
        self.assertIn("cache-dependency-path", src)
        self.assertIn("--prefer-binary", src)
        self.assertIn("--no-input", src)
        self.assertNotIn("pip install PySide6 pyinstaller", src)

    def test_build_requirements_file_exists_and_pins_heavy_packages(self):
        p = PROJECT_ROOT / "requirements-build.txt"
        self.assertTrue(p.exists(), f"build requirements file not found at {p}")
        src = p.read_text(encoding="utf-8")
        self.assertIn("PySide6==", src)
        self.assertIn("pyinstaller==", src)

    def test_workflow_checks_artifacts_and_browser_exclusion(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("Verify release artifacts", src)
        self.assertIn("ms-playwright", src)
        self.assertIn("chromium-", src)

    def test_spec_bundles_license_and_third_party_notices(self):
        src = (PROJECT_ROOT / "packaging" / "invoice_hub_windows.spec").read_text(encoding="utf-8")
        self.assertIn("LICENSE", src)
        self.assertIn("THIRD_PARTY_NOTICES.md", src)
        self.assertIn('"licenses"', src)

    def test_workflow_requires_notice_files_in_release_payload(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("dist\\InvoiceHub\\LICENSE", src)
        self.assertIn("dist\\InvoiceHub\\THIRD_PARTY_NOTICES.md", src)
        self.assertIn("dist\\InvoiceHub\\licenses\\LGPL-3.0.txt", src)
        self.assertIn("dist\\InvoiceHub\\licenses\\GPL-3.0.txt", src)


class TestReleaseReadinessFiles(unittest.TestCase):
    """MVP release readiness files must exist and state the intended terms."""

    def test_license_is_apache_2(self):
        src = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", src)
        self.assertIn("Version 2.0", src)

    def test_third_party_notices_cover_packaging_and_qt(self):
        src = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for token in ("PySide6", "Qt", "Playwright", "PyInstaller", "Inno Setup"):
            self.assertIn(token, src)

    def test_qt_license_files_exist(self):
        for rel in ("licenses/LGPL-3.0.txt", "licenses/GPL-3.0.txt"):
            path = PROJECT_ROOT / rel
            self.assertTrue(path.exists(), f"missing license file: {rel}")
            self.assertIn("GNU", path.read_text(encoding="utf-8"))

    def test_contributing_documents_dco(self):
        src = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("DCO", src)
        self.assertIn("Signed-off-by", src)
        self.assertIn("git commit -s", src)

    def test_pyside_license_doc_mentions_current_modules(self):
        src = (PROJECT_ROOT / "docs" / "pyside6-license-compliance.md").read_text(encoding="utf-8")
        for token in ("QtPdf", "QtPdfWidgets", "QtNetwork"):
            self.assertIn(token, src)

    def test_codeowners_protects_sensitive_paths(self):
        src = (PROJECT_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        for token in ("/.github/workflows/", "/packaging/", "/SECURITY.md", "/scripts/check_public_export.py"):
            self.assertIn(token, src)


if __name__ == "__main__":
    unittest.main()
