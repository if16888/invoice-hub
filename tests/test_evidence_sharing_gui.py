"""Use real controls for explicit sharing, cancellation and failure recovery."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QPainter, QPdfWriter
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.evidence_dialog import EvidenceDialog


class EvidenceSharingGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        for target in ("scripts.invoice_fetch.gui.app.RUNTIME_DIR", "scripts.invoice_fetch.gui.preview_mixin.RUNTIME_DIR"):
            patcher = patch(target, self.runtime)
            patcher.start()
            self.addCleanup(patcher.stop)
        config = {"reimbursement": {"strict_buyer_check": True, "buyer_name": "Synthetic Buyer"}}
        config_patch = patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.view = InvoiceReviewApp(self.runtime / "invoices.db")
        self.view._deferred_init()
        self.view.resize(1200, 800)
        self.view.show()
        self.view._switch_main_page("review")
        self.counter = 0
        self.parent = self.seed()
        self.source = self.seed(invoice_number=None, invoice_type="待关联证明材料", mailbox_key="phone", mail_uid=None)
        self.select(self.parent)

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def seed(self, **fields):
        self.counter += 1
        relative = f"attachments/synthetic-{self.counter}.pdf"
        path = self.runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = QPdfWriter(str(path))
        painter = QPainter(writer)
        painter.drawText(50, 50, f"Synthetic {self.counter}")
        painter.end()
        del writer
        return self.view.db.insert_invoice({
            "invoice_number": f"EVIDENCE-GUI-{self.counter}", "invoice_date": "2026-10-01",
            "total_amount": "10.00", "seller_name": "Synthetic Seller", "buyer_name": "Synthetic Buyer",
            "parse_success": True, "category": "其他", "invoice_type": "电子发票",
            "attachment_path": relative, "mailbox_key": "mail-a", "mail_uid": 123,
            "confirmed_note": "Keep original note", **fields,
        })

    def select(self, invoice_id):
        self.view._load_invoices(preserve_invoice_id=invoice_id)
        for row, invoice in enumerate(self.view.invoices_list):
            if invoice["id"] == invoice_id:
                self.view.table.selectRow(row)
                break
        self.app.processEvents()

    def check_source(self, dialog, state=Qt.Checked):
        for row in range(dialog.table.rowCount()):
            item = dialog.table.item(row, 0)
            if item.data(Qt.UserRole) == self.source:
                item.setCheckState(state)
                return item
        self.fail("Missing material in sharing dialog")

    def accept(self, dialog):
        self.check_source(dialog)
        self.assertTrue(dialog.save.isEnabled())
        return QDialog.Accepted

    def test_single_invoice_manager_links_cross_source_and_keeps_current_note_and_preview(self):
        with patch.object(EvidenceDialog, "exec", lambda dialog: self.accept(dialog)):
            self.view._detail_panel.btn_manage_evidence.click()
        self.assertEqual(self.view.db.evidence_consumers(self.source), (self.parent,))
        self.assertEqual(self.view.current_invoice["id"], self.parent)
        self.assertEqual(self.view.db.get_invoice(self.parent)["confirmed_note"], "Keep original note")
        self.assertEqual(self.view.current_preview_docs[1]["evidence_id"], self.source)
        self.assertEqual(self.view._data_operation_gate.owner, "")
        self.assertIn("已新增 1", self.view.statusBar().currentMessage())

    def test_cancel_does_not_apply_staged_checkbox_changes(self):
        def cancel(dialog):
            self.check_source(dialog)
            return QDialog.Rejected
        with patch.object(EvidenceDialog, "exec", cancel):
            self.view._detail_panel.btn_manage_evidence.click()
        self.assertEqual(self.view.db.evidence_consumers(self.source), ())
        self.assertEqual(self.view._data_operation_gate.owner, "")

    def test_multi_selection_shares_material_to_exact_selected_invoices(self):
        other = self.seed()
        untouched = self.seed()
        self.select(self.parent)
        model = self.view.table.selectionModel()
        for row, record in enumerate(self.view.invoices_list):
            if record["id"] == other:
                model.select(self.view.table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.app.processEvents()
        self.assertEqual(set(self.view._selected_batch_invoice_ids()), {self.parent, other})
        with patch.object(EvidenceDialog, "exec", lambda dialog: self.accept(dialog)):
            self.view.batch_review_bar.evidence.click()
        self.assertEqual(set(self.view.db.evidence_consumers(self.source)), {self.parent, other})
        self.assertEqual(self.view.db.list_invoice_evidence(untouched), [])
        self.assertEqual(set(self.view._selected_batch_invoice_ids()), {self.parent, other})

    def test_partial_association_can_be_filled_or_cleared_without_touching_other_consumers(self):
        other = self.seed()
        outside = self.seed()
        self.view.db.link_evidence_to_invoices((self.parent, outside), (self.source,))
        sources = self.view.db.list_evidence_sources(include_deleted=True)
        associations = {self.source: self.view.db.evidence_consumers(self.source)}
        dialog = EvidenceDialog((self.parent, other), sources, associations, self.runtime)
        self.addCleanup(dialog.deleteLater)
        item = self.check_source(dialog, Qt.PartiallyChecked)
        self.assertEqual(dialog.association_changes(), ((), ()))
        item.setCheckState(Qt.Checked)
        self.assertEqual(dialog.association_changes(), (((other, self.source),), ()))
        item.setCheckState(Qt.Unchecked)
        self.assertEqual(dialog.association_changes(), ((), ((self.parent, self.source),)))

    def test_open_material_keeps_dialog_choices_and_uses_local_file_url(self):
        dialog = EvidenceDialog((self.parent,), self.view.db.list_evidence_sources(), {}, self.runtime)
        self.addCleanup(dialog.deleteLater)
        item = self.check_source(dialog)
        dialog.table.setCurrentItem(item)
        with patch.object(QDesktopServices, "openUrl", return_value=True) as opened:
            dialog.preview.click()
        opened.assert_called_once()
        self.assertEqual(opened.call_args.args[0].toLocalFile(), str(self.runtime / self.view.db.get_invoice(self.source)["attachment_path"]))
        self.assertEqual(dialog.association_changes(), (((self.parent, self.source),), ()))
        self.assertEqual(self.view.db.evidence_consumers(self.source), ())

    def test_deleted_material_can_be_unlinked_from_current_invoice_but_not_added_to_others(self):
        self.view.db.link_evidence_to_invoices((self.parent,), (self.source,))
        self.view.db.soft_delete_invoice(self.source)
        other = self.seed()
        sources = self.view.db.list_evidence_sources(include_deleted=True)
        dialog = EvidenceDialog((self.parent, other), sources, {self.source: (self.parent,)}, self.runtime)
        self.addCleanup(dialog.deleteLater)
        self.check_source(dialog, Qt.Checked)
        additions, removals = dialog.association_changes()
        self.assertEqual(additions, ())
        self.assertEqual(removals, ((self.parent, self.source),))

    def test_pending_material_is_rejected_as_target(self):
        self.select(self.source)
        with patch.object(EvidenceDialog, "exec") as execute:
            self.view._detail_panel.btn_manage_evidence.click()
        execute.assert_not_called()
        self.assertIn("不能作为关联目标", self.view.statusBar().currentMessage())
        self.assertEqual(self.view._data_operation_gate.owner, "")

    def test_busy_data_gate_does_not_open_or_apply_dialog(self):
        self.assertTrue(self.view._data_operation_gate.try_acquire("Other operation"))
        try:
            with patch.object(EvidenceDialog, "exec") as execute, patch.object(QMessageBox, "warning"), patch.object(QMessageBox, "information"):
                self.view._detail_panel.btn_manage_evidence.click()
            execute.assert_not_called()
            self.assertEqual(self.view.db.evidence_consumers(self.source), ())
        finally:
            self.view._data_operation_gate.release("Other operation")

    def test_unsaved_fields_remain_intact_when_material_management_is_blocked(self):
        self.view.txt_seller.setText("Unsaved seller")
        self.view.txt_note.setPlainText("Unsaved note")
        with patch.object(EvidenceDialog, "exec") as execute:
            self.view._detail_panel.btn_manage_evidence.click()
        execute.assert_not_called()
        self.assertEqual(self.view.txt_seller.text(), "Unsaved seller")
        self.assertEqual(self.view.txt_note.toPlainText(), "Unsaved note")
        self.assertEqual(self.view.db.evidence_consumers(self.source), ())

    def test_material_deleted_during_modal_causes_atomic_failure_and_releases_gate(self):
        def stale(dialog):
            self.check_source(dialog)
            self.view.db.soft_delete_invoice(self.source)
            return QDialog.Accepted
        with patch.object(EvidenceDialog, "exec", stale), patch.object(QMessageBox, "warning") as warning:
            self.view._detail_panel.btn_manage_evidence.click()
        warning.assert_called_once()
        self.assertEqual(self.view.db.evidence_consumers(self.source), ())
        self.assertEqual(self.view._data_operation_gate.owner, "")

    def test_save_failure_leaves_relationships_unchanged(self):
        with patch.object(EvidenceDialog, "exec", lambda dialog: self.accept(dialog)), patch.object(self.view.db, "apply_evidence_changes", side_effect=sqlite3.OperationalError("synthetic failure")), patch.object(QMessageBox, "warning") as warning:
            self.view._detail_panel.btn_manage_evidence.click()
        warning.assert_called_once()
        self.assertEqual(self.view.db.evidence_consumers(self.source), ())
        self.assertEqual(self.view._data_operation_gate.owner, "")

    def test_material_path_changed_during_selection_requires_reconfirmation(self):
        def stale(dialog):
            self.check_source(dialog)
            self.view.db.update_invoice_file_paths(self.source, attachment_path="attachments/replaced.pdf")
            return QDialog.Accepted
        with patch.object(EvidenceDialog, "exec", stale), patch.object(QMessageBox, "warning") as warning:
            self.view._detail_panel.btn_manage_evidence.click()
        warning.assert_called_once()
        self.assertEqual(self.view.db.evidence_consumers(self.source), ())
        self.assertEqual(self.view._data_operation_gate.owner, "")

    def test_committed_change_is_reported_truthfully_when_view_refresh_fails(self):
        with patch.object(EvidenceDialog, "exec", lambda dialog: self.accept(dialog)), patch.object(self.view, "_load_invoices", side_effect=RuntimeError("synthetic refresh failure")), patch.object(QMessageBox, "warning") as warning:
            self.view._detail_panel.btn_manage_evidence.click()
        warning.assert_not_called()
        self.assertEqual(self.view.db.evidence_consumers(self.source), (self.parent,))
        self.assertIn("已保存", self.view.statusBar().currentMessage())
        self.assertEqual(self.view._data_operation_gate.owner, "")

    def test_manual_file_add_registers_reusable_material_and_preserves_original(self):
        original = self.runtime / self.view.db.get_invoice(self.source)["attachment_path"]
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(original), "")):
            self.view._detail_panel.btn_add_evidence.click()
        self.assertTrue(original.is_file())
        sources = self.view.db.list_invoice_evidence(self.parent)
        self.assertEqual(len(sources), 1)
        other = self.seed()
        self.assertEqual(self.view.db.link_evidence_to_invoices((other,), (sources[0]["id"],)), 1)
        self.assertEqual(self.view._data_operation_gate.owner, "")
