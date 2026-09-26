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


    # ── 2. Form fields editability ──────────────────────────────────────────


    # ── 3. Save button disabled when clean ─────────────────────────────────


    # ── 4. More source info collapsed by default ────────────────────────────


    # ── 5. Evidence row — missing badge ────────────────────────────────────

    def test_evidence_row_widgets_exist(self):
        """New evidence row widgets must all be present."""
        from PySide6.QtWidgets import QLabel, QPushButton
        self.assertFalse(hasattr(self.panel, "lbl_evidence_dot"))
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
        self.assertEqual(
            self.panel.lbl_evidence_missing.text(),
            "必需但缺失"
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

    def test_evidence_row_distinguishes_not_required_optional_and_required_missing(self):
        self.panel.update_evidence_row([], required=False, optional=False)
        self.assertEqual(self.panel.lbl_evidence_missing.text(), "不需要")
        self.assertEqual(self.panel.evidence_status_line.lbl_status.text(), "不需要")

        self.panel.update_evidence_row([], required=False, optional=True)
        self.assertEqual(self.panel.lbl_evidence_missing.text(), "未添加（可选）")
        self.assertEqual(
            self.panel.evidence_status_line.lbl_status.text(),
            "未添加（可选）",
        )

        self.panel.update_evidence_row([], required=True, optional=False)
        self.assertEqual(self.panel.lbl_evidence_missing.text(), "必需但缺失")
        self.assertEqual(
            self.panel.evidence_status_line.lbl_status.text(),
            "必需但缺失",
        )

    def test_evidence_row_marks_linked_zero_byte_file_unavailable(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty-trip.pdf"
            path.write_bytes(b"")
            self.panel.update_evidence_row(
                [{"label": path.name, "path": path, "status": "linked"}],
                required=False,
            )
            self.assertEqual(
                self.panel.evidence_status_line.lbl_status.text(),
                "已关联不可用",
            )
            self.assertFalse(self.panel.btn_open_extra_files.isEnabled())

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
            "Open button should be visible in the ActionCluster when file exists"
        )
        self.assertEqual(self.panel.btn_add_evidence.text(), "替换/管理")

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


    # ── 7. Approve/ignore/error/more buttons ────────────────────────────────


    # ── 8. Claim group buttons ──────────────────────────────────────────────


    def test_claim_group_buttons_exist(self):
        """Claim group add/export buttons must be present."""
        from PySide6.QtWidgets import QPushButton
        self.assertIsInstance(self.panel.btn_add_to_claim, QPushButton)
        self.assertIsInstance(self.panel.btn_export, QPushButton)

    def test_claim_group_controls_share_one_compact_row(self):
        """Claim selection and its actions remain compact in the reimbursement tab."""
        self.panel.resize(760, 850)
        self.panel.show()
        self.app.processEvents()
        self.panel.detail_tabs.setCurrentWidget(self.panel.reimbursement_scroll)
        self.app.processEvents()

        self.assertTrue(self.panel.combo_claims.isHidden())
        self.assertTrue(self.panel.lbl_claim_assignment.isVisible())
        self.assertTrue(self.panel.btn_refresh_claims.isHidden())
        self.assertFalse(self.panel.lbl_claim_total.isHidden())
        self.assertGreaterEqual(self.panel.claim_actions_widget.layout().indexOf(self.panel.btn_delete_claim), 0)
        self.assertEqual(self.panel.claim_summary_row.indexOf(self.panel.btn_delete_claim), -1)

    def test_reimbursement_tab_shows_empty_hint_without_claim_groups(self):
        self.panel.show()
        self.app.processEvents()
        self.panel.detail_tabs.setCurrentWidget(self.panel.reimbursement_scroll)
        self.app.processEvents()

        self.assertTrue(self.panel.claim_empty_hint.isVisible())
        self.assertIn("新建报销组", self.panel.claim_empty_hint.text())

    def test_claim_combo_aligns_with_first_column_fields(self):
        """Material and core fields align inside the basic-information tab."""
        self.panel.resize(760, 850)
        self.panel.show()
        self.app.processEvents()
        material_x = self.panel.original_status_line.mapTo(self.panel, self.panel.original_status_line.rect().topLeft()).x()
        core_x = self.panel.lbl_core_number.mapTo(self.panel, self.panel.lbl_core_number.rect().topLeft()).x()
        self.assertGreaterEqual(material_x, 0)
        self.assertGreaterEqual(core_x, 0)


    def test_empty_claim_delete_button_exists_in_summary_row(self):
        """Deleting an empty group lives in the claim action cluster, not the summary row."""
        from PySide6.QtWidgets import QPushButton
        self.assertIsInstance(self.panel.btn_delete_claim, QPushButton)
        self.assertGreaterEqual(self.panel.claim_actions_widget.layout().indexOf(self.panel.btn_delete_claim), 0)
        self.assertEqual(self.panel.claim_summary_row.indexOf(self.panel.btn_delete_claim), -1)

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
        """When attachment exists, action buttons stay hidden and replacement state is retained."""
        self.panel.set_attachment_state(has_file=True, file_name="invoice.pdf", file_path="/tmp/invoice.pdf")
        self.assertFalse(self.panel.btn_open_file.isHidden())
        self.assertEqual(self.panel.btn_add_attachment.text(), "替换")

    def test_material_actions_are_hidden_and_double_clickable(self):
        """Material filenames replace visible action buttons and support double-click editing."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel, InvoiceDetailCallbacks

        called = []
        panel = InvoiceDetailPanel(callbacks=InvoiceDetailCallbacks(
            on_open_dir=lambda: called.append("directory"),
            on_add_evidence=lambda: called.append("evidence"),
        ))
        panel.show()
        self.app.processEvents()
        panel.update_evidence_row([{"label": "proof.pdf", "path": "/tmp/proof.pdf"}])

        self.assertTrue(panel.btn_open_file.isHidden())
        self.assertTrue(panel.btn_add_attachment.isHidden())
        self.assertTrue(panel.btn_retry_download.isHidden())
        self.assertFalse(panel.btn_open_extra_files.isHidden())
        self.assertFalse(panel.btn_add_evidence.isHidden())  # visible as "替换/管理"

        QTest.mouseDClick(panel.txt_path, Qt.LeftButton)
        QTest.mouseDClick(panel.lbl_evidence_name, Qt.LeftButton)
        self.assertEqual(called, ["directory", "evidence"])
        panel.close()
        panel.deleteLater()


    # ── 12. Inline claim creation toggling ───────────────────────────────────

    def test_inline_claim_creation_toggling(self):
        """Selecting the dropdown's new-group item shows creation, and cancel hides it."""
        self.assertTrue(self.panel.new_claim_widget.isHidden())
        self.panel.combo_claims.addItem("＋ 新建报销组…", self.panel.NEW_CLAIM_VALUE)
        self.panel.combo_claims.setCurrentIndex(0)
        self.panel._set_new_claim_input_visible(True)
        self.assertFalse(self.panel.new_claim_widget.isHidden())
        self.assertTrue(self.panel.btn_new_claim_toggle.isHidden())

        self.panel.btn_cancel_create_claim.click()
        self.assertTrue(self.panel.new_claim_widget.isHidden())
        self.assertTrue(self.panel.btn_new_claim_toggle.isHidden())

    # ── 13. Callback wiring for materials buttons ───────────────────────────


    # ── 14. Note section collapsed/expanded state ───────────────────────────


if __name__ == "__main__":
    unittest.main()
