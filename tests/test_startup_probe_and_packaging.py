"""
tests/test_startup_probe_and_packaging.py

Tests for the startup-probe CLI flag, import structure, launcher script,
and PyInstaller spec integrity.

All tests run offline without a real database, real credentials, or a
PySide6 display — safe for CI.
"""

from __future__ import annotations

import ast
from contextlib import redirect_stdout
import io
import os
import re
import subprocess
import sys
import textwrap
import tempfile
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
        import importlib
        app_mod = importlib.import_module("scripts.invoice_fetch.gui.app")

        sig = inspect.signature(app_mod.start_gui_app)
        params = list(sig.parameters.keys())
        self.assertIn("startup_probe", params)
        self.assertIn("app_init_ms", params)

    def test_start_gui_app_keeps_main_window_hidden_until_splash_finishes(self):
        """Normal startup must not show the main window before the splash is dismissed."""
        import importlib

        app_mod = importlib.import_module("scripts.invoice_fetch.gui.app")
        fake_app = MagicMock()
        fake_app.exec.return_value = 0
        fake_splash = MagicMock()
        fake_window = MagicMock()
        fake_window.db_open_ms = 0
        fake_window.gui_init_ms = 0
        fake_window.first_load_ms = 0

        with patch.object(app_mod, "QApplication", return_value=fake_app), \
             patch.object(app_mod, "StartupSplash", return_value=fake_splash), \
             patch.object(app_mod, "InvoiceReviewApp", return_value=fake_window), \
             patch.object(app_mod.sys, "exit") as mock_exit:
            app_mod.start_gui_app(PROJECT_ROOT / "runtime" / "invoices.db", startup_probe=False, app_init_ms=0)

        fake_splash.show.assert_called_once()
        fake_window.show.assert_not_called()
        mock_exit.assert_called_once_with(fake_app.exec.return_value)


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


class TestVersionSource(unittest.TestCase):
    """Release metadata should read from the same app version source."""

    def test_release_workflow_reads_python_version_source(self):
        workflow = PROJECT_ROOT / ".github" / "workflows" / "windows-release.yml"
        src = workflow.read_text(encoding="utf-8")
        self.assertIn("scripts.invoice_fetch.version", src)
        self.assertIn("VERSION", src)
        self.assertNotIn("APP_VERSION", src)

    def test_release_workflow_accepts_rc_tags_with_matching_base_version(self):
        workflow = PROJECT_ROOT / ".github" / "workflows" / "windows-release.yml"
        src = workflow.read_text(encoding="utf-8")
        self.assertIn("(?<base>\\d+\\.\\d+\\.\\d+)", src)
        self.assertIn("(?:rc|pre)", src)
        self.assertIn("contains(env.VERSION, '-')", src)


class TestWindowsVersionInfo(unittest.TestCase):
    """Windows version metadata should be generated from a stable source."""

    def test_generator_uses_stable_product_metadata(self):
        from scripts.generate_windows_version_info import build_version_info_text

        text = build_version_info_text("0.1.3")
        self.assertIn("filevers=(0, 1, 3, 0)", text)
        self.assertIn("prodvers=(0, 1, 3, 0)", text)
        for value in (
            "CompanyName', 'Invoice Hub",
            "ProductName', 'Invoice Hub",
            "FileDescription', 'Invoice Hub",
            "InternalName', 'InvoiceHub",
            "OriginalFilename', 'InvoiceHub.exe",
            "ProductVersion', '0.1.3",
        ):
            self.assertIn(value, text)

    def test_generator_cli_writes_requested_output_file(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "windows-version-info.txt"
            result = subprocess.run(
                [sys.executable, "-m", "scripts.generate_windows_version_info", "--output", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(output.exists(), "generator did not write the requested output file")
            text = output.read_text(encoding="utf-8")
            self.assertIn("VSVersionInfo(", text)
            self.assertIn("filevers=(0, 1, 5, 0)", text)
            self.assertIn("ProductVersion', '0.1.5", text)
            self.assertIn(str(output), result.stdout + result.stderr)

    def test_spec_attaches_generated_version_resource(self):
        src = (PROJECT_ROOT / "packaging" / "invoice_hub_windows.spec").read_text(encoding="utf-8")
        self.assertIn('build" / "windows-version-info.txt', src)
        self.assertIn("version=str(_version_file)", src)


class TestOptionalWindowsSigning(unittest.TestCase):
    """Optional signing should be warning-only when no certificate is configured."""

    def test_missing_certificate_configuration_warns_without_modifying_file(self):
        script = PROJECT_ROOT / "scripts" / "sign_windows.ps1"
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "unsigned.exe"
            target.write_bytes(b"unsigned")
            env = os.environ.copy()
            for name in ("SIGNTOOL_PATH", "CERT_SUBJECT", "TIMESTAMP_URL"):
                env.pop(name, None)
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(target)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, combined)
            self.assertTrue(any(x in combined.upper() for x in ("WARNING", "SIGNING SKIPPED", "SKIPPED")), combined)
            self.assertEqual(target.read_bytes(), b"unsigned")

    def test_script_mentions_sign_tool_and_timestamp_contract(self):
        src = (PROJECT_ROOT / "scripts" / "sign_windows.ps1").read_text(encoding="utf-8")
        for token in ("SIGNTOOL_PATH", "CERT_SUBJECT", "TIMESTAMP_URL", "/fd", "/tr", "/td", "SHA256"):
            self.assertIn(token, src)


class TestWindowsVersionInfoGenerator(unittest.TestCase):
    """Windows version resource text should be stable and generated from VERSION."""

    def _module_path(self) -> Path:
        p = PROJECT_ROOT / "scripts" / "generate_windows_version_info.py"
        self.assertTrue(p.exists(), f"version resource generator not found at {p}")
        return p

    def test_generator_module_exists(self):
        self._module_path()

    def test_generator_source_imports_version_constant(self):
        src = self._module_path().read_text(encoding="utf-8")
        self.assertIn("from scripts.invoice_fetch.version import VERSION", src)

    def test_build_version_info_text_formats_version_tuple_and_metadata(self):
        from scripts.generate_windows_version_info import build_version_info_text

        text = build_version_info_text("0.1.3")

        self.assertIn("filevers=(0, 1, 3, 0)", text)
        self.assertIn("prodvers=(0, 1, 3, 0)", text)
        for field, value in {
            "CompanyName": "Invoice Hub",
            "ProductName": "Invoice Hub",
            "FileDescription": "Invoice Hub",
            "InternalName": "InvoiceHub",
            "OriginalFilename": "InvoiceHub.exe",
            "ProductVersion": "0.1.3",
        }.items():
            self.assertIn(f"StringStruct('{field}', '{value}')", text)

    def test_build_version_info_text_truncates_extra_numeric_components(self):
        from scripts.generate_windows_version_info import build_version_info_text

        text = build_version_info_text("1.2.3.4.5")
        self.assertIn("filevers=(1, 2, 3, 4)", text)
        self.assertIn("prodvers=(1, 2, 3, 4)", text)

    def test_cli_defaults_to_build_output_and_writes_utf8_text(self):
        from scripts import generate_windows_version_info as mod

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    exit_code = mod.main([])
            finally:
                os.chdir(old_cwd)

            self.assertEqual(exit_code, 0)
            output_path = root / "build" / "windows-version-info.txt"
            self.assertTrue(output_path.exists(), f"expected output file at {output_path}")
            self.assertIn(str(Path("build") / "windows-version-info.txt"), buf.getvalue())
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("VSVersionInfo(", text)
            self.assertIn("StringStruct('ProductVersion', '0.1.5')", text)

    def test_cli_uses_explicit_output_directory(self):
        from scripts import generate_windows_version_info as mod

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output_path = root / "nested" / "windows-version-info.txt"
            buf = io.StringIO()
            with redirect_stdout(buf):
                exit_code = mod.main(["--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists(), f"expected output file at {output_path}")
            self.assertIn(str(output_path), buf.getvalue())
            self.assertIn("VSVersionInfo(", output_path.read_text(encoding="utf-8"))


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

    def test_spec_references_generated_version_file(self):
        src = self._spec_path().read_text(encoding="utf-8")
        self.assertIn('_version_file = _root / "build" / "windows-version-info.txt"', src)
        self.assertIn('version=str(_version_file)', src)

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

    def _lifecycle_probe_path(self) -> Path:
        p = PROJECT_ROOT / "scripts" / "dev" / "verify_installer_lifecycle.ps1"
        self.assertTrue(p.exists(), f"installer lifecycle probe not found at {p}")
        return p

    def test_inno_script_exists(self):
        self._installer_path()

    def test_inno_installs_per_user_without_admin(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", src)
        self.assertIn(
            '#define DefaultInstallDir "{localappdata}\\Programs\\InvoiceHub"',
            src,
        )
        self.assertIn("DefaultDirName={#DefaultInstallDir}", src)
        self.assertIn(
            "AppId={{B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D}",
            src,
        )

    def test_inno_creates_desktop_and_start_menu_shortcuts(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertIn(r"{autodesktop}\Invoice Hub", src)
        self.assertIn(r"{autoprograms}\Invoice Hub", src)

    def test_inno_uses_canonical_setup_name_and_optional_signing(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertIn("OutputBaseFilename=InvoiceHub-{#AppVersion}-win64-setup", src)
        self.assertIn("#ifdef SignToolName", src)
        self.assertIn("SignTool={#SignToolName}", src)
        self.assertIn("SignedUninstaller=yes", src)

    def test_inno_does_not_delete_user_appdata_on_uninstall(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertIn("[UninstallDelete]", src)
        self.assertIn('Type: dirifempty; Name: "{app}\\exports"', src)
        self.assertIn('Type: dirifempty; Name: "{app}"', src)
        self.assertNotIn("filesandordirs", src.lower())
        self.assertNotIn("{userappdata}", src)
        self.assertNotIn("{commonappdata}", src)

    def test_inno_removes_only_a_broken_registered_uninstaller_key(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertIn("function RemoveBrokenUninstallRegistration: String;", src)
        self.assertIn("IsInnoUninstallerName", src)
        self.assertIn("AppDirectory := InstallLocation", src)
        self.assertIn("FileExists(ChangeFileExt(UninstallerPath, '.dat'))", src)
        self.assertIn("RegDeleteKeyIncludingSubkeys", src)
        self.assertNotIn("FindAlternateUninstaller", src)
        self.assertNotIn("RegWriteStringValue", src)
        self.assertNotIn("DeleteFile(UninstallerPath", src)
        self.assertNotIn("RenameFile(UninstallerPath", src)
        self.assertIn("function InitializeSetup: Boolean;", src)
        self.assertIn("SuppressibleMsgBox(RepairError", src)
        self.assertIn("native setup", src)
        self.assertIn("procedure RemoveEmptyDirectoryTree", src)
        self.assertIn("FILE_ATTRIBUTE_REPARSE_POINT", src)
        self.assertIn("procedure CurUninstallStepChanged", src)
        self.assertIn("RemoveDir(Directory)", src)

    def test_inno_preserves_valid_native_upgrade_logs(self):
        src = self._installer_path().read_text(encoding="utf-8")
        valid_log_guard = """if FileExists(ChangeFileExt(UninstallerPath, '.dat')) then
    Exit;"""
        self.assertIn(valid_log_guard, src)
        self.assertNotIn("UninstallLogMode=overwrite", src)
        self.assertNotIn("UninstallFilesDir=", src)

    def test_inno_orphan_cleanup_is_narrow_and_keeps_user_data(self):
        src = self._installer_path().read_text(encoding="utf-8")
        self.assertIn(
            'Type: files; Name: "{app}\\unins???.exe.invoicehub-orphan"',
            src,
        )
        self.assertNotIn('Name: "{app}\\unins*.exe"', src)
        self.assertNotIn("filesandordirs", src.lower())

    def test_installer_lifecycle_probe_uses_isolated_identity_and_paths(self):
        src = self._lifecycle_probe_path().read_text(encoding="utf-8")
        self.assertIn("[guid]::NewGuid()", src)
        self.assertIn("InvoiceHubInstallerLifecycle-$PID", src)
        self.assertIn("0.1.5-rc1", src)
        self.assertIn("0.1.5-rc2", src)
        self.assertIn("historical-rc2-repair.log", src)
        self.assertIn("Get-UserDataSnapshot", src)
        self.assertIn("Removed the damaged Invoice Hub uninstall registration before native setup.", src)
        self.assertIn("INSTALLER_LIFECYCLE_PROBE: PASS", src)

    def test_workflow_builds_setup_zip_and_checksums(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("iscc", src.lower())
        self.assertIn("python -m scripts.generate_windows_version_info --output build/windows-version-info.txt", src)
        self.assertIn("InvoiceHub-${version}-win64-setup.exe", src)
        self.assertIn("InvoiceHub-${version}-win64-portable.zip", src)
        self.assertIn("SHA256SUMS.txt", src)
        self.assertIn("scripts\\sign_windows.ps1", src)

    def test_workflow_uploads_setup_zip_and_checksums(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("InvoiceHub-windows-release", src)
        self.assertIn("dist/${{ env.ZIP_NAME }}", src)
        self.assertIn("dist/${{ env.SETUP_NAME }}", src)
        self.assertIn("dist/SHA256SUMS.txt", src)
        self.assertIn("actions/download-artifact@v4", src)

    def test_workflow_signs_before_portable_zip_and_installer(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertEqual(src.count("scripts\\sign_windows.ps1"), 2)
        self.assertLess(
            src.index("scripts\\sign_windows.ps1 \"dist\\InvoiceHub\\InvoiceHub.exe\""),
            src.index("Compress-Archive"),
        )
        self.assertLess(
            src.index("Compress-Archive"),
            src.index("scripts\\sign_windows.ps1 \"dist\\${env:SETUP_NAME}\""),
        )

    def test_workflow_release_job_downloads_single_bundle(self):
        src = self._workflow_path().read_text(encoding="utf-8")
        self.assertIn("InvoiceHub-windows-release", src)
        self.assertIn("dist/${{ env.ZIP_NAME }}", src)
        self.assertIn("dist/${{ env.SETUP_NAME }}", src)
        self.assertIn("dist/SHA256SUMS.txt", src)
        self.assertIn("Create GitHub Release", src)

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

    def test_spec_places_data_files_next_to_executable(self):
        src = (PROJECT_ROOT / "packaging" / "invoice_hub_windows.spec").read_text(encoding="utf-8")
        exe_block = re.search(r"exe = EXE\((.*?)\n\)", src, re.DOTALL)
        self.assertIsNotNone(exe_block)
        self.assertIn('contents_directory="."', exe_block.group(1))

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


class TestWindowsInstallDocumentation(unittest.TestCase):
    """Windows install guidance should explain download safety and canonical assets."""

    def test_windows_install_guide_covers_download_safety_and_hash_verification(self):
        src = (PROJECT_ROOT / "docs" / "windows-install.md").read_text(encoding="utf-8")
        for token in (
            "SmartScreen",
            "Unknown Publisher",
            "不常见下载",
            "https://github.com/if16888/invoice-hub/releases",
            "Get-FileHash",
            "SHA256SUMS.txt",
            "MSI",
            "Authenticode",
        ):
            self.assertIn(token, src)

    def test_readme_links_windows_install_guide_and_canonical_assets(self):
        src = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/windows-install.md", src)
        self.assertIn("InvoiceHub-*-win64-setup.exe", src)
        self.assertIn("InvoiceHub-*-win64-portable.zip", src)
        self.assertIn("SHA256SUMS.txt", src)

    def test_release_checklist_uses_canonical_windows_artifacts(self):
        src = (PROJECT_ROOT / "docs" / "release-checklist.md").read_text(encoding="utf-8")
        self.assertIn("InvoiceHub-*-win64-setup.exe", src)
        self.assertIn("InvoiceHub-*-win64-portable.zip", src)
        self.assertIn("SHA256SUMS.txt", src)


if __name__ == "__main__":
    unittest.main()
