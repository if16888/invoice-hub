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
        self.assertEqual(self.panel.btn_save_draft.property("variant"), "primary")
        self.assertEqual(self.panel.lbl_dirty_hint.text(), "已修改")

    def test_save_button_disabled_after_clear_dirty(self):
        """Calling set_dirty_state(False) must disable btn_save_draft."""
        self.panel.set_dirty_state(True)
        self.panel.set_dirty_state(False)
        self.assertFalse(self.panel.btn_save_draft.isEnabled())
        self.assertEqual(self.panel.btn_save_draft.property("variant"), "secondary")
        self.assertEqual(self.panel.lbl_dirty_hint.text(), "已保存")
        if hasattr(self.panel, "_saved_timer"):
            self.panel._saved_timer.timeout.emit()
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
            "缺失"
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
        self.assertIn("通过并下一张", self.panel.btn_app.text())
        self.assertNotIn("\n", self.panel.btn_app.text())
        self.assertIn("忽略", self.panel.btn_ign.text())
        self.assertNotIn("\n", self.panel.btn_ign.text())
        self.assertEqual(self.panel.btn_err.text(), "异常")
        self.assertNotIn("\n", self.panel.btn_err.text())
        self.assertIn("Enter", self.panel.btn_app.toolTip())
        self.assertIn("Del", self.panel.btn_ign.toolTip())
        self.assertIn("Ctrl+E", self.panel.btn_err.toolTip())

    def test_review_action_buttons_stay_compact_in_narrow_panel(self):
        for btn in (self.panel.btn_app, self.panel.btn_ign, self.panel.btn_err):
            self.assertLessEqual(btn.height(), 32)

    def test_review_actions_clear_detail_tabs_in_narrow_panel(self):
        self.panel.resize(390, 850)
        self.panel.show()
        self.app.processEvents()

        buttons_bottom = max(
            btn.mapTo(self.panel, btn.rect().bottomLeft()).y()
            for btn in (self.panel.btn_app, self.panel.btn_ign, self.panel.btn_err, self.panel.btn_inline_more)
        )
        tabs_top = self.panel.detail_tabs.tabBar().mapTo(
            self.panel, self.panel.detail_tabs.tabBar().rect().topLeft()
        ).y()
        self.assertLess(buttons_bottom + 4, tabs_top)

    def test_basic_info_fields_stack_to_single_column(self):
        self.panel.resize(390, 850)
        self.panel.show()
        self.app.processEvents()

        number_x = self.panel.txt_number.mapTo(self.panel, self.panel.txt_number.rect().topLeft()).x()
        date_x = self.panel.txt_date.mapTo(self.panel, self.panel.txt_date.rect().topLeft()).x()
        amount_x = self.panel.txt_amount.mapTo(self.panel, self.panel.txt_amount.rect().topLeft()).x()
        buyer_x = self.panel.txt_buyer.mapTo(self.panel, self.panel.txt_buyer.rect().topLeft()).x()
        seller_x = self.panel.txt_seller.mapTo(self.panel, self.panel.txt_seller.rect().topLeft()).x()

        self.assertLessEqual(abs(number_x - date_x), 4)
        self.assertLessEqual(abs(number_x - amount_x), 4)
        self.assertLessEqual(abs(number_x - buyer_x), 4)
        self.assertLessEqual(abs(number_x - seller_x), 4)
        self.assertLess(
            self.panel.txt_date.mapTo(self.panel, self.panel.txt_date.rect().topLeft()).y(),
            self.panel.txt_amount.mapTo(self.panel, self.panel.txt_amount.rect().topLeft()).y(),
        )
        self.assertLess(
            self.panel.txt_buyer.mapTo(self.panel, self.panel.txt_buyer.rect().topLeft()).y(),
            self.panel.txt_seller.mapTo(self.panel, self.panel.txt_seller.rect().topLeft()).y(),
        )

    def test_summary_and_review_actions_are_fixed_above_detail_tabs(self):
        fixed = self.panel.fixed_header_container
        for widget in (
            self.panel.lbl_sum_amount,
            self.panel.lbl_sum_status,
            self.panel.lbl_sum_category,
            self.panel.lbl_sum_date,
            self.panel.lbl_sum_number,
            self.panel.lbl_sum_seller,
            self.panel.lbl_date_warning,
            self.panel.lbl_buyer_warning,
            self.panel.btn_app,
            self.panel.btn_ign,
            self.panel.btn_err,
        ):
            self.assertTrue(fixed.isAncestorOf(widget), widget.objectName())
            self.assertFalse(self.panel.right_content_widget.viewport().isAncestorOf(widget))
        self.assertEqual(self.panel.detail_tabs.tabText(0), "基本信息")
        self.assertEqual(self.panel.detail_tabs.tabText(1), "报销信息")
        self.assertEqual(self.panel.detail_tabs.count(), 2)
        self.assertEqual(self.panel.detail_tabs.indexOf(self.panel.contract_scroll), -1)
        self.assertEqual(self.panel.detail_tabs.indexOf(self.panel.operation_scroll), -1)

    # ── 8. Claim group buttons ──────────────────────────────────────────────

    def test_fixed_header_container_stays_compact(self):
        self.panel.resize(760, 850)
        self.panel.show()
        self.app.processEvents()
        self.assertLessEqual(self.panel.fixed_header_container.height(), 126)
        self.assertLessEqual(self.panel.btn_app.height(), 50)
        self.assertLessEqual(self.panel.btn_err.height(), 50)
        self.assertEqual(self.panel.summary_card.objectName(), "DetailSummaryCard")

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

        claim_x = self.panel.combo_claims.mapTo(self.panel, self.panel.combo_claims.rect().topLeft()).x()
        claim_actions_x = self.panel.claim_actions_widget.mapTo(self.panel, self.panel.claim_actions_widget.rect().topLeft()).x()
        claim_combo_right = claim_x + self.panel.combo_claims.width()
        self.assertGreaterEqual(claim_actions_x, claim_combo_right - 2)
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
        material_x = self.panel.txt_path.mapTo(self.panel, self.panel.txt_path.rect().topLeft()).x()
        core_x = self.panel.txt_number.mapTo(self.panel, self.panel.txt_number.rect().topLeft()).x()
        self.assertLessEqual(abs(material_x - core_x), 2)

    def test_basic_info_section_stays_compact(self):
        self.panel.resize(760, 850)
        self.panel.show()
        self.app.processEvents()
        self.assertLessEqual(self.panel.detail_core_section.height(), 260)

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
        self.assertFalse(panel.btn_open_extra_files.isHidden())  # visible as "打开"
        self.assertFalse(panel.btn_add_evidence.isHidden())  # visible as "替换/管理"

        QTest.mouseDClick(panel.txt_path, Qt.LeftButton)
        QTest.mouseDClick(panel.lbl_evidence_name, Qt.LeftButton)
        self.assertEqual(called, ["directory", "evidence"])
        panel.close()
        panel.deleteLater()

    def test_detail_scrollbar_is_hidden_by_default(self):
        """The first view must not display a vertical scrollbar."""
        from PySide6.QtCore import Qt
        self.assertEqual(
            self.panel.right_content_widget.verticalScrollBarPolicy(),
            Qt.ScrollBarAsNeeded,
        )

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

    def test_materials_buttons_callback_wiring(self):
        """Buttons in the Materials zone must trigger their respective callbacks."""
        called = {}
        from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel, InvoiceDetailCallbacks
        cb = InvoiceDetailCallbacks(
            on_open_file=lambda: called.update({"open_file": True}),
            on_add_attachment=lambda: called.update({"add_attachment": True}),
            on_open_evidence=lambda: called.update({"open_evidence": True}),
            on_add_evidence=lambda: called.update({"add_evidence": True}),
            on_delete_claim=lambda: called.update({"delete_claim": True}),
        )
        panel = InvoiceDetailPanel(callbacks=cb)

        panel.btn_open_file.setEnabled(True)
        panel.btn_open_file.click()
        self.assertTrue(called.get("open_file"))

        panel.btn_add_attachment.setEnabled(True)
        panel.btn_add_attachment.click()
        self.assertTrue(called.get("add_attachment"))

        panel.btn_open_extra_files.setEnabled(True)
        panel.btn_open_extra_files.click()
        self.assertTrue(called.get("open_evidence"))

        panel.btn_add_evidence.setEnabled(True)
        panel.btn_add_evidence.click()
        self.assertTrue(called.get("add_evidence"))

        panel.btn_delete_claim.setEnabled(True)
        panel.btn_delete_claim.click()
        self.assertTrue(called.get("delete_claim"))

        panel.close()
        panel.deleteLater()

    # ── 14. Note section collapsed/expanded state ───────────────────────────

    def test_note_collapsed_without_text_hides_summary_row(self):
        """set_note('') must leave the note area fully collapsed: no summary, no editor row."""
        self.panel.set_note("")
        self.app.processEvents()

        # txt_note must be hidden (own flag, independent of panel.show())
        self.assertTrue(self.panel.txt_note.isHidden(),
                        "txt_note should be hidden when no note text")
        # lbl_note_summary must be hidden (no phantom 'summary' row)
        self.assertTrue(self.panel.lbl_note_summary.isHidden(),
                        "lbl_note_summary should be hidden when no note text")
        # note_content_row (wrapper widget) must be hidden
        if hasattr(self.panel, "note_content_row"):
            self.assertTrue(self.panel.note_content_row.isHidden(),
                            "note_content_row should be hidden when no note text")
        # button text stays in expand mode
        self.assertEqual(self.panel.btn_toggle_note.text(), "备注 + 展开")

    def test_note_set_text_defaults_to_collapsed_summary(self):
        """set_note('xxx') must default to collapsed state showing a one-line summary.

        The user should not see the editor until they explicitly click '备注 + 展开'.
        """
        self.panel.set_note("客户项目说明")
        self.app.processEvents()

        # Editor must be hidden by default (collapsed)
        self.assertTrue(self.panel.txt_note.isHidden(),
                        "txt_note should be hidden by default after set_note with text")
        if hasattr(self.panel, "note_content_row"):
            self.assertTrue(self.panel.note_content_row.isHidden(),
                            "note_content_row should be hidden by default after set_note with text")
        # Summary must be visible and contain the note text
        self.assertFalse(self.panel.lbl_note_summary.isHidden(),
                         "lbl_note_summary should be visible after set_note with text")
        self.assertIn("备注：客户项目说明", self.panel.lbl_note_summary.text(),
                      "lbl_note_summary should contain the note text with full-width colon")
        # Button text stays in expand mode
        self.assertEqual(self.panel.btn_toggle_note.text(), "备注 + 展开")

    def test_note_expand_shows_editor(self):
        """Clicking expand (toggle) from a has-note collapsed state must reveal the editor."""
        # Start from collapsed state with real note text
        self.panel.set_note("客户项目说明")
        self.app.processEvents()

        # Verify collapsed (own hidden flag)
        self.assertTrue(self.panel.txt_note.isHidden())
        self.assertFalse(self.panel.lbl_note_summary.isHidden())

        # Click expand
        self.panel._toggle_note_visibility()
        self.app.processEvents()

        # Editor must now be visible (own hidden flag)
        self.assertFalse(self.panel.txt_note.isHidden(),
                         "txt_note should not be hidden after expanding")
        if hasattr(self.panel, "note_content_row"):
            self.assertFalse(self.panel.note_content_row.isHidden(),
                             "note_content_row should be visible after expanding")
        # Summary must be hidden (editing mode)
        self.assertTrue(self.panel.lbl_note_summary.isHidden(),
                        "lbl_note_summary should be hidden while editor is open")
        # Button text reflects expanded state
        self.assertEqual(self.panel.btn_toggle_note.text(), "备注 + 收起")


if __name__ == "__main__":
    unittest.main()
