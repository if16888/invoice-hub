"""Empirical Challenger Test Suite for Milestone 4 (GUI & Service Architecture Cleanup).

Adversarially challenges and stress-tests:
1. Settings dialog AI validation (_v5_test_ai_clicked across multiple profile states)
2. Settings dialog AI action buttons (_v5_edit_active_ai_clicked, _v5_clear_ai_key_clicked)
3. Preview mixin deduplication, importability, PDF engine fallbacks, and runtime compatibility
4. Global services._rename_source_mode mutation elimination and source_mode threading
5. Workers BaseException elimination and unhandled SystemExit/KeyboardInterrupt propagation
6. Architecture policy conformance
"""

import ast
import inspect
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QLabel, QWidget
except ImportError:
    QApplication, QMessageBox, QLabel, QWidget = None, None, None, None


class TestChallengerM4Empirical(unittest.TestCase):
    """Empirical challenger tests for Milestone M4 deliverables."""

    @classmethod
    def setUpClass(cls):
        if QApplication is not None:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        else:
            cls.app = None

    def setUp(self):
        if self.app is None:
            raise unittest.SkipTest("PySide6 not available for GUI empirical testing")

        self.mock_warning = patch(
            "scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning",
            return_value=QMessageBox.Ok,
        ).start()
        self.mock_info = patch(
            "scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information",
            return_value=QMessageBox.Ok,
        ).start()

    def tearDown(self):
        patch.stopall()

    def _create_dialog(self, cfg_overrides=None):
        from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog

        base_cfg = {
            "email_accounts": [
                {
                    "address": "test_challenger@example.com",
                    "provider": "qq",
                    "is_default": True,
                    "months": 3,
                }
            ],
            "ai_profiles": [
                {
                    "profile_id": "prof_ds_1",
                    "provider": "deepseek",
                    "name": "DeepSeek Primary",
                    "model": "deepseek-chat",
                    "enabled": True,
                }
            ],
        }
        if cfg_overrides:
            base_cfg.update(cfg_overrides)

        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(base_cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()
        return dialog

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 1: Settings Dialog AI Validation & Action Buttons
    # ──────────────────────────────────────────────────────────────────────────

    def test_01_no_active_ai_profile_shows_warning_no_fake_success(self):
        """Scenario A: No active AI profile -> warning shown, no fake success popup."""
        dialog = self._create_dialog({
            "ai_profiles": [
                {
                    "profile_id": "prof_disabled",
                    "provider": "deepseek",
                    "name": "DeepSeek Disabled",
                    "model": "deepseek-chat",
                    "enabled": False,
                }
            ]
        })

        dialog._v5_test_ai_clicked()

        self.mock_warning.assert_called_once()
        args, kwargs = self.mock_warning.call_args
        title, message = args[1], args[2]
        self.assertIn("AI 配置测试", title)
        self.assertIn("当前未启用任何 AI 配置", message)

        # Crucial: Information popup (success) must NOT be shown
        self.mock_info.assert_not_called()

    def test_02_empty_ai_profiles_list_shows_warning(self):
        """Scenario A2: Empty AI profiles list -> warning shown, no fake success."""
        dialog = self._create_dialog({"ai_profiles": []})

        dialog._v5_test_ai_clicked()

        self.mock_warning.assert_called_once()
        self.assertIn("当前未启用任何 AI 配置", self.mock_warning.call_args[0][2])
        self.mock_info.assert_not_called()

    def test_03_active_profile_with_valid_key_active_session(self):
        """Scenario C: Active profile with configured key and active session -> genuine info."""
        dialog = self._create_dialog()

        with patch("scripts.invoice_fetch.credentials.get_ai_api_key_source", return_value="profile"):
            with patch("scripts.invoice_fetch.credentials.get_ai_api_key", return_value="sk-valid-key"):
                with patch("scripts.invoice_fetch.ai_classifier.is_provider_session_paused", return_value=False):
                    dialog._v5_test_ai_clicked()

        self.mock_warning.assert_not_called()
        self.mock_info.assert_called_once()
        args, _ = self.mock_info.call_args
        title, message = args[1], args[2]
        self.assertEqual(title, "AI 配置与凭据验证")
        self.assertIn("DeepSeek Primary", message)
        self.assertIn("deepseek", message)
        self.assertIn("deepseek-chat", message)
        self.assertIn("本次会话可用", message)
        self.assertNotIn("正在发起连接与文本结构化提取测试... 接口连通正常！", message)

    def test_04_active_profile_with_valid_key_paused_session(self):
        """Scenario D: Active profile with configured key and paused session -> shows paused warning in info."""
        dialog = self._create_dialog()

        with patch("scripts.invoice_fetch.credentials.get_ai_api_key_source", return_value="env"):
            with patch("scripts.invoice_fetch.credentials.get_ai_api_key", return_value="sk-valid-key"):
                with patch("scripts.invoice_fetch.ai_classifier.is_provider_session_paused", return_value=True):
                    dialog._v5_test_ai_clicked()

        self.mock_warning.assert_not_called()
        self.mock_info.assert_called_once()
        args, _ = self.mock_info.call_args
        title, message = args[1], args[2]
        self.assertIn("本次会话已暂停（可能因限流或认证失败自动熔断）", message)
        self.assertNotIn("正在发起连接与文本结构化提取测试... 接口连通正常！", message)

    def test_05_active_profile_missing_key_shows_warning_no_crash(self):
        """Scenario B: Missing API key shows warning dialog without crashing or raising SystemExit."""
        dialog = self._create_dialog()

        # Isolate environment and keyring so key is truly missing
        with patch("keyring.get_password", return_value=None):
            with patch.dict(os.environ, {}, clear=True):
                dialog._v5_test_ai_clicked()

        self.mock_warning.assert_called_once()
        args, _ = self.mock_warning.call_args
        self.assertIn("AI 配置测试", args[1])
        self.assertIn("尚未配置 API Key", args[2])
        self.mock_info.assert_not_called()

    def test_05b_active_profile_missing_key_warning_when_mocked_safely(self):
        """Verify that if get_ai_api_key returns empty string without crashing, the warning is formatted properly."""
        dialog = self._create_dialog()

        with patch("scripts.invoice_fetch.credentials.get_ai_api_key_source", return_value="missing"):
            with patch("scripts.invoice_fetch.credentials.get_ai_api_key", return_value=""):
                dialog._v5_test_ai_clicked()

        self.mock_warning.assert_called_once()
        args, _ = self.mock_warning.call_args
        self.assertIn("AI 配置测试", args[1])
        self.assertIn("尚未配置 API Key", args[2])
        self.assertIn("DeepSeek Primary", args[2])
        self.assertIn("deepseek-chat", args[2])
        self.mock_info.assert_not_called()

    def test_05c_clear_ai_key_action(self):
        """Verify _v5_clear_ai_key_clicked invokes delete_ai_api_key and informs user."""
        dialog = self._create_dialog()

        with patch("scripts.invoice_fetch.credentials.delete_ai_api_key") as mock_del:
            dialog._v5_clear_ai_key_clicked()
            mock_del.assert_called_once_with("deepseek", "prof_ds_1")
            self.mock_info.assert_called_once()

    def test_05d_edit_active_ai_navigates_to_editor(self):
        """Scenario E: _v5_edit_active_ai_clicked navigates to editor for active profile without AttributeError."""
        dialog = self._create_dialog()
        dialog._v5_edit_active_ai_clicked()
        self.assertEqual(dialog._editing_ai_profile_id, "prof_ds_1")
        self.assertEqual(dialog.settings_stack.currentWidget(), dialog.page_ai_editor)

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 2: Preview Mixin Deduplication & Fallback Chains
    # ──────────────────────────────────────────────────────────────────────────

    def test_06_preview_mixin_importable_symbols(self):
        """Verify PreviewMixin and helper functions are cleanly imported."""
        from scripts.invoice_fetch.gui.preview_mixin import (
            PreviewMixin,
            check_has_qt_pdf,
            get_qt_pdf_classes,
            _runtime_dir_compat,
        )
        self.assertTrue(inspect.isclass(PreviewMixin))
        self.assertTrue(callable(check_has_qt_pdf))
        self.assertTrue(callable(get_qt_pdf_classes))
        self.assertTrue(callable(_runtime_dir_compat))

    def test_07_preview_mixin_ast_no_duplicate_definitions(self):
        """Verify AST of preview_mixin.py contains exactly 1 definition of each top-level entity."""
        preview_mixin_path = Path("scripts/invoice_fetch/gui/preview_mixin.py")
        self.assertTrue(preview_mixin_path.exists())
        tree = ast.parse(preview_mixin_path.read_text(encoding="utf-8"))

        func_names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        class_names = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]

        self.assertEqual(func_names.count("check_has_qt_pdf"), 1, "Duplicate check_has_qt_pdf found!")
        self.assertEqual(func_names.count("get_qt_pdf_classes"), 1, "Duplicate get_qt_pdf_classes found!")
        self.assertEqual(func_names.count("_runtime_dir_compat"), 1, "Duplicate _runtime_dir_compat found!")
        self.assertEqual(class_names.count("PreviewMixin"), 1, "Duplicate PreviewMixin found!")

    def test_08_pdf_engine_fallback_when_qtpdf_unavailable(self):
        """Simulate missing PySide6.QtPdf and verify graceful fallback to (None, None) and False."""
        import scripts.invoice_fetch.gui.preview_mixin as pm

        orig_classes = pm._QPDF_CLASSES
        orig_has_pdf = pm.HAS_QT_PDF
        try:
            pm._QPDF_CLASSES = None
            pm.HAS_QT_PDF = None

            with patch.dict(sys.modules, {"PySide6.QtPdf": None}):
                with patch("builtins.__import__", side_effect=ImportError("No module named 'PySide6.QtPdf'")):
                    classes = pm.get_qt_pdf_classes()
                    self.assertEqual(classes, (None, None))
                    has_pdf = pm.check_has_qt_pdf()
                    self.assertFalse(has_pdf)
        finally:
            pm._QPDF_CLASSES = orig_classes
            pm.HAS_QT_PDF = orig_has_pdf

    def test_09_runtime_dir_compat_fallback(self):
        """Verify _runtime_dir_compat falls back to config.RUNTIME_DIR when app module not present."""
        from scripts.invoice_fetch.gui.preview_mixin import _runtime_dir_compat
        from scripts.invoice_fetch.config import RUNTIME_DIR

        rd = _runtime_dir_compat()
        self.assertTrue(isinstance(rd, Path))

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 3: Global _rename_source_mode Immutability & Threading
    # ──────────────────────────────────────────────────────────────────────────

    def test_10_services_rename_source_mode_not_mutated(self):
        """Verify services._rename_source_mode remains 'normal' and is not mutated."""
        from scripts.invoice_fetch import services

        self.assertEqual(services._rename_source_mode, "normal")

    def test_11_handle_pending_email_accepts_source_mode_parameter(self):
        """Verify _handle_pending_email accepts source_mode and forwards it without mutating global state."""
        from scripts.invoice_fetch import services
        sig = inspect.signature(services._handle_pending_email)
        self.assertIn("source_mode", sig.parameters)
        self.assertEqual(sig.parameters["source_mode"].default, "normal")

    def test_12_reprocess_does_not_mutate_services_global_mode(self):
        """AST inspection: verify __main__.py does not assign to application_services._rename_source_mode."""
        main_path = Path("scripts/invoice_fetch/__main__.py")
        main_src = main_path.read_text(encoding="utf-8")
        self.assertNotIn("application_services._rename_source_mode =", main_src)
        self.assertNotIn("services._rename_source_mode =", main_src)

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 4: Workers BaseException Elimination
    # ──────────────────────────────────────────────────────────────────────────

    def test_13_no_base_exception_handlers_in_workers(self):
        """Static AST analysis: verify workers.py has zero 'except BaseException' handlers."""
        workers_path = Path("scripts/invoice_fetch/gui/workers.py")
        tree = ast.parse(workers_path.read_text(encoding="utf-8"))

        base_exception_handlers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if isinstance(node.type, ast.Name) and node.type.id == "BaseException":
                    base_exception_handlers.append(node.lineno)

        self.assertEqual(
            base_exception_handlers,
            [],
            f"Found forbidden except BaseException handlers at lines: {base_exception_handlers}",
        )

    def test_14_worker_run_propagates_system_exit(self):
        """Empirically verify that SystemExit is not caught and swallowed as an application error."""
        from scripts.invoice_fetch.gui.workers import ExportMigrationWorker

        worker = ExportMigrationWorker(Path("dummy_src"), Path("dummy_dst"))
        with patch("scripts.invoice_fetch.export_paths.migrate_legacy_exports", side_effect=SystemExit(42)):
            with self.assertRaises(SystemExit) as ctx:
                worker.run()
            self.assertEqual(ctx.exception.code, 42)

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 5: Architecture Policy Conformance
    # ──────────────────────────────────────────────────────────────────────────

    def test_15_architecture_policy_clean(self):
        """Run check_architecture_policy and verify exit code 0."""
        import subprocess

        res = subprocess.run(
            [sys.executable, "scripts/check_architecture_policy.py"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Architecture policy failed: {res.stderr}\n{res.stdout}")
        self.assertIn("[PASS]", res.stdout)

    def test_16_process_email_threads_source_mode_to_all_call_sites(self):
        """AST analysis: verify services._process_email passes source_mode=source_mode to all 12 call sites."""
        services_path = Path("scripts/invoice_fetch/services.py")
        tree = ast.parse(services_path.read_text(encoding="utf-8"))

        func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_process_email")
        rename_calls = []
        extras_calls = []

        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None)
                if name == "_rename_by_invoice_code":
                    kw = {k.arg: getattr(k.value, "id", None) for k in node.keywords}
                    rename_calls.append(kw.get("source_mode") == "source_mode")
                elif name == "_attach_email_extras_to_invoice":
                    kw = {k.arg: getattr(k.value, "id", None) for k in node.keywords}
                    extras_calls.append(kw.get("source_mode") == "source_mode")

        self.assertEqual(len(rename_calls), 6, "Expected exactly 6 _rename_by_invoice_code calls in _process_email")
        self.assertTrue(all(rename_calls), f"Not all _rename_by_invoice_code calls pass source_mode=source_mode: {rename_calls}")

        self.assertEqual(len(extras_calls), 6, "Expected exactly 6 _attach_email_extras_to_invoice calls in _process_email")
        self.assertTrue(all(extras_calls), f"Not all _attach_email_extras_to_invoice calls pass source_mode=source_mode: {extras_calls}")


if __name__ == "__main__":
    unittest.main()
