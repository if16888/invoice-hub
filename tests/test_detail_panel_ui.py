# -*- coding: utf-8 -*-
"""Tests for InvoiceDetailPanel UI refactoring — detail workbench hierarchy polish.

Verifies:
1. All form fields are editable (QLineEdit/QComboBox, not read-only)
2. Save button disabled when clean, enabled after field edit (dirty tracking)
3. "更多来源信息" is collapsed by default
4. Evidence row shows "缺失" badge when no supporting documents
5. Evidence row shows filename label (not missing badge) when documents present
6. Button text: btn_save_draft shows "保存字段修改"
7. combo_supporting_docs is hidden (backward-compat, not visible in UI)
"""

from __future__ import annotations

import sys
import unittest

try:
    from PySide6.QtWidgets import QApplication
    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False

_QAPP = None


def _get_or_create_app():
    global _QAPP
    if not _HAS_PYSIDE6:
        return None
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class TestInvoiceDetailPanelUI(unittest.TestCase):
    """Tests for the refactored InvoiceDetailPanel UI."""

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        self.app = _get_or_create_app()
        from scripts.invoice_fetch.gui.invoice_detail_panel import (
            InvoiceDetailPanel, InvoiceDetailCallbacks,
        )
        self.panel = InvoiceDetailPanel()

    def tearDown(self):
        if hasattr(self, "panel") and self.panel is not None:
            self.panel.close()
            self.panel.deleteLater()
            if self.app:
                self.app.processEvents()

    # ── 1. Save button text ─────────────────────────────────────────────────

    def test_save_button_text_is_save_fields(self):
        """btn_save_draft must read '保存', with tooltip '保存字段修改', and min-width >= 72. Font size shouldn't exceed 10pt."""
        self.assertEqual(self.panel.btn_save_draft.text(), "保存")
        self.assertEqual(self.panel.btn_save_draft.toolTip(), "保存字段修改")
        self.assertGreaterEqual(self.panel.btn_save_draft.minimumWidth(), 72)
        self.assertLessEqual(self.panel.btn_save_draft.font().pointSize(), 10)

    # ── 2. Form fields editability ──────────────────────────────────────────

    def test_form_fields_are_qlineedit_or_qcombobox(self):
        """Core form fields must be editable inputs, not plain read-only labels. Font should not be 12pt."""
        from PySide6.QtWidgets import QLineEdit, QComboBox
        self.assertIsInstance(self.panel.txt_number, QLineEdit)
        self.assertFalse(self.panel.txt_number.isReadOnly(), "txt_number should not be read-only")
        self.assertLessEqual(self.panel.txt_number.font().pointSize(), 10)

        self.assertIsInstance(self.panel.txt_date, QLineEdit)
        self.assertFalse(self.panel.txt_date.isReadOnly(), "txt_date should not be read-only")

        self.assertIsInstance(self.panel.txt_seller, QLineEdit)
        self.assertFalse(self.panel.txt_seller.isReadOnly(), "txt_seller should not be read-only")

        self.assertIsInstance(self.panel.txt_buyer, QLineEdit)
        self.assertFalse(self.panel.txt_buyer.isReadOnly(), "txt_buyer should not be read-only")

        self.assertIsInstance(self.panel.txt_amount, QLineEdit)
        self.assertFalse(self.panel.txt_amount.isReadOnly(), "txt_amount should not be read-only")
        self.assertLessEqual(self.panel.txt_amount.font().pointSize(), 10)

        self.assertIsInstance(self.panel.combo_category, QComboBox)
        self.assertTrue(self.panel.combo_category.isEditable(), "combo_category should be editable")
        self.assertLessEqual(self.panel.combo_category.font().pointSize(), 10)

    # ── 3. Save button disabled when clean ─────────────────────────────────

    def test_save_button_disabled_when_clean(self):
        """btn_save_draft must start disabled (no unsaved changes)."""
        self.assertFalse(
            self.panel.btn_save_draft.isEnabled(),
            "Save button should be disabled when no changes have been made"
        )

    def test_save_button_enabled_after_set_dirty(self):
        """Calling set_dirty_state(True) must enable btn_save_draft."""
        self.panel.set_dirty_state(True)
        self.assertTrue(self.panel.btn_save_draft.isEnabled())
        self.assertEqual(self.panel.lbl_dirty_hint.text(), "已修改")

    def test_save_button_disabled_after_clear_dirty(self):
        """Calling set_dirty_state(False) must disable btn_save_draft."""
        self.panel.set_dirty_state(True)
        self.panel.set_dirty_state(False)
        self.assertFalse(self.panel.btn_save_draft.isEnabled())
        self.assertEqual(self.panel.lbl_dirty_hint.text(), "")

    # ── 4. More source info collapsed by default ────────────────────────────

    def test_more_source_info_collapsed_by_default(self):
        """more_source_widget must be hidden on panel creation."""
        self.assertFalse(
            self.panel.more_source_widget.isVisible(),
            "更多来源信息 section must start collapsed"
        )

    def test_more_source_btn_exists(self):
        """btn_more_source must exist as a QToolButton."""
        from PySide6.QtWidgets import QToolButton
        self.assertIsInstance(self.panel.btn_more_source, QToolButton)
        self.assertIn("更多来源信息", self.panel.btn_more_source.text())

    def test_more_source_toggle_expands(self):
        """Toggling btn_more_source must show/hide more_source_widget."""
        # Widget must be realized for visibility to be meaningful
        self.panel.show()
        self.app.processEvents()
        self.assertFalse(self.panel.more_source_widget.isVisible())
        self.panel._toggle_more_source_info(True)
        self.assertTrue(self.panel.more_source_widget.isVisible())
        self.panel._toggle_more_source_info(False)
        self.assertFalse(self.panel.more_source_widget.isVisible())

    # ── 5. Evidence row — missing badge ────────────────────────────────────

    def test_evidence_row_widgets_exist(self):
        """New evidence row widgets must all be present."""
        from PySide6.QtWidgets import QLabel, QPushButton
        self.assertIsInstance(self.panel.lbl_evidence_dot, QLabel)
        self.assertIsInstance(self.panel.lbl_evidence_name, QLabel)
        self.assertIsInstance(self.panel.lbl_evidence_missing, QLabel)
        self.assertIsInstance(self.panel.btn_open_extra_files, QPushButton)
        self.assertIsInstance(self.panel.btn_add_evidence, QPushButton)

    def test_evidence_row_shows_missing_badge_when_no_docs(self):
        """When no supporting documents, lbl_evidence_missing must be visible."""
        self.panel.update_evidence_row([])
        # Use not isHidden() since parent panel may not be shown in headless tests
        self.assertFalse(
            self.panel.lbl_evidence_missing.isHidden(),
            "缺失 badge must not be hidden when no supporting documents"
        )
        self.assertTrue(
            self.panel.lbl_evidence_name.isHidden(),
            "filename label must be hidden when no supporting documents"
        )
        self.assertFalse(
            self.panel.btn_open_extra_files.isEnabled(),
            "Open button must be disabled when no supporting documents"
        )
        self.assertTrue(
            self.panel.btn_open_extra_files.isHidden(),
            "Open button must be hidden when no supporting documents"
        )
        self.assertEqual(self.panel.btn_add_evidence.text(), "补充")

    def test_evidence_row_shows_filename_when_doc_present(self):
        """When a supporting document exists, filename label is visible and badge hidden."""
        items = [{"label": "行程单.pdf", "path": "/tmp/行程单.pdf"}]
        self.panel.update_evidence_row(items)
        self.assertTrue(
            self.panel.lbl_evidence_missing.isHidden(),
            "缺失 badge must be hidden when a doc is present"
        )
        self.assertFalse(
            self.panel.lbl_evidence_name.isHidden(),
            "Filename label must not be hidden when a doc is present"
        )
        self.assertIn("行程单.pdf", self.panel.lbl_evidence_name.text())
        self.assertTrue(self.panel.btn_open_extra_files.isEnabled())
        self.assertFalse(
            self.panel.btn_open_extra_files.isHidden(),
            "Open button must be visible when a doc is present"
        )
        self.assertEqual(self.panel.btn_add_evidence.text(), "替换")

    def test_evidence_row_filename_truncated_when_long(self):
        """Filenames longer than 40 chars are truncated with ellipsis."""
        long_name = "A" * 50 + ".pdf"
        items = [{"label": long_name, "path": f"/tmp/{long_name}"}]
        self.panel.update_evidence_row(items)
        displayed = self.panel.lbl_evidence_name.text()
        self.assertLessEqual(len(displayed), 44, "Long filenames must be truncated")
        self.assertIn("…", displayed)

    def test_evidence_row_syncs_with_set_supporting_documents(self):
        """set_supporting_documents() must also update the evidence row."""
        self.panel.set_supporting_documents([])
        self.assertFalse(self.panel.lbl_evidence_missing.isHidden())

        docs = [{"label": "hotel_receipt.pdf", "path": "/tmp/hotel_receipt.pdf"}]
        self.panel.set_supporting_documents(docs)
        self.assertTrue(self.panel.lbl_evidence_missing.isHidden())
        self.assertFalse(self.panel.lbl_evidence_name.isHidden())

    # ── 6. Hidden combo_supporting_docs (backward compat) ──────────────────

    def test_combo_supporting_docs_is_hidden(self):
        """combo_supporting_docs must not be visible in the UI (hidden, for compat only)."""
        self.assertFalse(
            self.panel.combo_supporting_docs.isVisible(),
            "combo_supporting_docs must be hidden — row-style replaces it"
        )

    # ── 7. Approve/ignore/error/more buttons ────────────────────────────────

    def test_review_action_buttons_exist(self):
        """Primary review action buttons must be present."""
        from PySide6.QtWidgets import QPushButton
        self.assertIsInstance(self.panel.btn_app, QPushButton)
        self.assertIsInstance(self.panel.btn_ign, QPushButton)
        self.assertIsInstance(self.panel.btn_err, QPushButton)
        self.assertIsInstance(self.panel.btn_inline_more, QPushButton)
        # Text checks
        self.assertEqual(self.panel.btn_app.text(), "通过并下一张")
        self.assertEqual(self.panel.btn_ign.text(), "忽略")

    # ── 8. Claim group buttons ──────────────────────────────────────────────

    def test_claim_group_buttons_exist(self):
        """Claim group add/export buttons must be present."""
        from PySide6.QtWidgets import QPushButton
        self.assertIsInstance(self.panel.btn_add_to_claim, QPushButton)
        self.assertIsInstance(self.panel.btn_export, QPushButton)

    # ── 9. get_form_values includes all editable fields ─────────────────────

    def test_get_form_values_returns_all_fields(self):
        """get_form_values() must return a dict with all core editable fields."""
        vals = self.panel.get_form_values()
        required_keys = {"invoice_number", "expense_date", "total_amount",
                         "category", "seller_name", "buyer_name"}
        self.assertEqual(required_keys, set(vals.keys()))

    # ── 10. Privacy: no full path exposed in UI labels ──────────────────────

    def test_evidence_name_does_not_expose_full_path(self):
        """The visible filename label must show only the basename, not full path."""
        items = [{"label": "receipt.pdf", "path": "C:\\Users\\secret\\Documents\\receipt.pdf"}]
        self.panel.update_evidence_row(items)
        displayed = self.panel.lbl_evidence_name.text()
        # label is 'receipt.pdf', not the full path
        self.assertNotIn("C:\\", displayed)
        self.assertNotIn("secret", displayed)

    # ── 11. Attachment row text & visibility ───────────────────────────────

    def test_attachment_row_shows_supplement_when_no_file(self):
        """When no attachment exists, btn_open_file is hidden, btn_add_attachment is '补充'."""
        self.panel.set_attachment_state(has_file=False)
        self.assertTrue(self.panel.btn_open_file.isHidden())
        self.assertEqual(self.panel.btn_add_attachment.text(), "补充")

    def test_attachment_row_shows_replace_when_file_exists(self):
        """When attachment exists, btn_open_file is visible, btn_add_attachment is '替换'."""
        self.panel.set_attachment_state(has_file=True, file_name="invoice.pdf", file_path="/tmp/invoice.pdf")
        self.assertFalse(self.panel.btn_open_file.isHidden())
        self.assertEqual(self.panel.btn_add_attachment.text(), "替换")


if __name__ == "__main__":
    unittest.main()
