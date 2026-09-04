import inspect
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_COLORS
from scripts.invoice_fetch.gui.page_layouts import SETTINGS_BASELINE_STAGES
from scripts.invoice_fetch.gui.settings_status import (
    infer_status_tone,
    normalize_status_label,
    plain_status_text,
)
from scripts.invoice_fetch.gui.ui.components.preview_toolbar import PreviewToolbar
from scripts.invoice_fetch.gui.ui.preview_toolbar_style import build_preview_toolbar_qss


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class SettingsSemanticStatusContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_plain_status_text_removes_legacy_font_markup(self):
        source = "授权状态：<font color='#10B981'><b>已安全保存</b></font>"
        self.assertEqual(plain_status_text(source), "授权状态：已安全保存")

    def test_status_language_maps_to_semantic_tones(self):
        self.assertEqual(infer_status_tone("已安全保存到系统凭据管理器"), "success")
        self.assertEqual(infer_status_tone("Outlook 当前版本暂不支持配置"), "warning")
        self.assertEqual(infer_status_tone("尚未配置 API Key"), "danger")
        self.assertEqual(infer_status_tone("API Key 状态：已保存"), "info")
        self.assertEqual(infer_status_tone("普通说明"), "muted")

    def test_normalize_status_label_uses_plain_text_and_properties(self):
        label = QLabel("API Key 状态：<font color='#B42318'><b>未配置</b></font>")
        try:
            tone = normalize_status_label(label)
            self.assertEqual(tone, "danger")
            self.assertEqual(label.text(), "API Key 状态：未配置")
            self.assertEqual(label.textFormat(), Qt.PlainText)
            self.assertTrue(label.property("semanticStatus"))
            self.assertEqual(label.property("status"), "danger")
            self.assertEqual(label.accessibleName(), label.text())
        finally:
            label.deleteLater()
            self.app.processEvents()

    def test_semantic_status_stage_runs_after_token_qss(self):
        names = [name for name, _stage in SETTINGS_BASELINE_STAGES]
        self.assertIn("semantic_status", names)
        self.assertGreater(names.index("semantic_status"), names.index("token_contract"))


class PreviewToolbarTokenContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_preview_toolbar_component_contains_no_hex_color_literals(self):
        source = inspect.getsource(PreviewToolbar)
        self.assertNotRegex(source, r"#[0-9A-Fa-f]{6}")
        self.assertIn("build_preview_toolbar_qss", source)

    def test_preview_toolbar_qss_is_derived_from_design_tokens(self):
        qss = build_preview_toolbar_qss()
        self.assertIn(DESIGN_V1_COLORS["surface"], qss)
        self.assertIn(DESIGN_V1_COLORS["accent"], qss)
        self.assertIn(DESIGN_V1_COLORS["focus_ring"], qss)
        self.assertIn(DESIGN_V1_COLORS["placeholder"], qss)
        self.assertIn("QToolButton.PreviewToolBtn:focus", qss)
        self.assertIn("QToolButton.PreviewToolBtn:disabled", qss)

    def test_preview_toolbar_buttons_have_stable_focus_contracts(self):
        toolbar = PreviewToolbar()
        try:
            buttons = (
                toolbar.btn_zoom_out,
                toolbar.btn_zoom_100,
                toolbar.btn_zoom_in,
                toolbar.btn_fit_width,
                toolbar.btn_fit_page,
                toolbar.btn_rotate_left,
                toolbar.btn_rotate_right,
                toolbar.btn_download,
                toolbar.btn_print,
                toolbar.btn_fullscreen,
            )
            self.assertEqual(toolbar.accessibleName(), "原件预览工具栏")
            for button in buttons:
                self.assertEqual(button.focusPolicy(), Qt.StrongFocus)
                self.assertTrue(button.objectName().startswith("PreviewAction_"))
                self.assertTrue(button.accessibleName())
        finally:
            toolbar.close()
            toolbar.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
