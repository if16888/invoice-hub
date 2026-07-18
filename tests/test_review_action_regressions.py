import gc
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMessageBox

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.column_filters import VISIBLE_COLUMN_DEFINITIONS


_QAPP = None


def _get_or_create_app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class ReviewActionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.app = _get_or_create_app()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = InvoiceDB(self.db_path)
        self.db._conn.execute(
            """
            INSERT INTO invoices (
                invoice_number, invoice_date, total_amount,
                seller_name, is_deleted, review_status
            ) VALUES
                ('111', '2026-06-11', '10.00', 'SellerA', 0, 'to_review'),
                ('222', '2026-06-12', '20.00', 'SellerB', 0, 'to_review'),
                ('333', '2026-06-13', '30.00', 'SellerC', 0, 'to_review')
            """
        )
        self.db._conn.commit()

        self.msgbox_patcher = patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.Yes,
        )
        self.msgbox_patcher.start()

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value={}):
            self.review_app = InvoiceReviewApp(db_path=self.db_path)
            self.review_app._deferred_init()
        self.review_app.show()
        self.app.processEvents()

    def tearDown(self):
        self.msgbox_patcher.stop()
        if getattr(self, "review_app", None) is not None:
            if getattr(self.review_app, "db", None) is not None:
                self.review_app.db.close()
            self.review_app.close()
            self.review_app.deleteLater()
        self.db.close()
        gc.collect()
        self.app.processEvents()
        try:
            self.temp_dir.cleanup()
        except OSError:
            pass

    def test_toolbar_buttons_busy_state(self):
        app = self.review_app
        self.assertTrue(app.btn_import_local.isEnabled())
        self.assertTrue(app.btn_mobile_upload.isEnabled())
        self.assertTrue(app.btn_scan_email.isEnabled())
        self.assertTrue(app.btn_toolbar_export.isEnabled())

    def test_single_row_selection_keeps_current_and_selected_rows_in_sync(self):
        app = self.review_app
        self.assertTrue(app._apply_single_row_selection(2))
        self.app.processEvents()

        selected = app.table.selectionModel().selectedRows()
        self.assertEqual([index.row() for index in selected], [2])
        self.assertEqual(app.table.currentRow(), 2)

        app._set_action_busy(app.btn_import_local, "导入中...")
        self.assertEqual(app.btn_import_local.text(), "导入中...")
        self.assertEqual(app.btn_import_local.property("busy"), "true")
        self.assertFalse(app.btn_import_local.isEnabled())
        self.assertFalse(app.btn_mobile_upload.isEnabled())
        self.assertFalse(app.btn_scan_email.isEnabled())
        self.assertFalse(app.btn_toolbar_export.isEnabled())

        app._clear_action_busy(app.btn_import_local, "导入")
        self.assertEqual(app.btn_import_local.text(), "导入")
        self.assertEqual(app.btn_import_local.property("busy"), "false")
        self.assertTrue(app.btn_import_local.isEnabled())
        self.assertTrue(app.btn_mobile_upload.isEnabled())
        self.assertTrue(app.btn_scan_email.isEnabled())
        self.assertTrue(app.btn_toolbar_export.isEnabled())

    def test_delete_multiple_rows_deduplicates_selection_and_keeps_row_hint(self):
        app = self.review_app
        self.assertEqual(app.table.rowCount(), 3)
        app.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        model = app.table.selectionModel()
        model.clearSelection()
        model.select(
            app.table.model().index(0, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )
        model.select(
            app.table.model().index(1, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )
        self.assertEqual(len(model.selectedRows()), 2)

        app._delete_selected_invoices()

        remaining = [row for row in app.db.get_all_invoices() if row.get("is_deleted") != 1]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["invoice_number"], "111")
        self.assertEqual(app.table.currentRow(), 0)
        visible_keys = [key for key, _label in VISIBLE_COLUMN_DEFINITIONS]
        invoice_column = visible_keys.index("invoice_number")
        self.assertEqual(app.table.item(0, invoice_column).text(), "111")

    def test_link_to_claim_keeps_original_invoice_selected_when_visible(self):
        app = self.review_app
        claim_id = app.db.create_claim_group("Selection claim")
        app._load_claims()
        claim_index = app.combo_claims.findData(claim_id)
        self.assertGreaterEqual(claim_index, 0)
        app.combo_claims.setCurrentIndex(claim_index)
        app.table.selectRow(1)
        self.app.processEvents()
        selected_id = app.invoices_list[1]["id"]
        with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
            app._link_invoices_to_claim()
        self.app.processEvents()
        self.assertEqual(app.invoices_list[app.table.currentRow()]["id"], selected_id)

    def test_link_under_unlinked_filter_keeps_same_row_position(self):
        app = self.review_app
        claim_id = app.db.create_claim_group("Filtered selection claim")
        app._load_claims()
        claim_index = app.combo_claims.findData(claim_id)
        self.assertGreaterEqual(claim_index, 0)
        app.combo_claims.setCurrentIndex(claim_index)
        app.chk_unlinked.setChecked(True)
        app.search_reload_timer.stop()
        app._load_invoices()
        self.assertEqual(app.table.rowCount(), 3)
        app.table.selectRow(1)
        self.app.processEvents()
        removed_id = app.invoices_list[1]["id"]
        expected_id = app.invoices_list[2]["id"]
        with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
            app._link_invoices_to_claim()
        self.app.processEvents()
        self.assertEqual(app.table.currentRow(), 1)
        self.assertEqual(app.invoices_list[1]["id"], expected_id)
        self.assertNotIn(removed_id, [row["id"] for row in app.invoices_list])

    def test_capture_selection_row_hint_uses_valid_minimum_row(self):
        app = self.review_app
        original_table = app.table
        selection_model = MagicMock()
        fake_table = MagicMock()
        fake_table.selectionModel.return_value = selection_model
        row_one = MagicMock()
        row_one.row.return_value = 1
        row_two = MagicMock()
        row_two.row.return_value = 2
        invalid_row = MagicMock()
        invalid_row.row.return_value = 99
        try:
            app.table = fake_table
            selection_model.selectedRows.return_value = [row_two]
            selection_model.selectedIndexes.return_value = [row_one]
            self.assertEqual(app._capture_selection_row_hint(), 2)
            selection_model.selectedRows.return_value = []
            selection_model.selectedIndexes.return_value = [row_two, row_one, row_one, invalid_row]
            self.assertEqual(app._capture_selection_row_hint(), 1)
            selection_model.selectedIndexes.return_value = [invalid_row]
            self.assertEqual(app._capture_selection_row_hint(), -1)
        finally:
            app.table = original_table

    def test_unlink_from_claim_keeps_original_invoice_selected(self):
        app = self.review_app
        claim_id = app.db.create_claim_group("Unlink selection claim")
        selected_id = app.invoices_list[1]["id"]
        self.assertTrue(app.db.add_invoice_to_claim(claim_id, selected_id))
        app._load_claims()
        claim_index = app.combo_claims.findData(claim_id)
        self.assertGreaterEqual(claim_index, 0)
        app.combo_claims.setCurrentIndex(claim_index)
        app._load_invoices()
        selected_row = next(
            index for index, invoice in enumerate(app.invoices_list)
            if invoice["id"] == selected_id
        )
        app.table.selectRow(selected_row)
        self.app.processEvents()
        with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
            app._unlink_selected_invoices()
        self.app.processEvents()
        self.assertEqual(app.invoices_list[app.table.currentRow()]["id"], selected_id)

    def test_restore_invoice_keeps_original_invoice_selected(self):
        app = self.review_app
        selected_id = app.invoices_list[1]["id"]
        self.assertTrue(app.db.soft_delete_invoice(selected_id))
        app.chk_show_deleted.setChecked(True)
        app.search_reload_timer.stop()
        app._load_invoices()
        selected_row = next(
            index for index, invoice in enumerate(app.invoices_list)
            if invoice["id"] == selected_id
        )
        app.table.selectRow(selected_row)
        self.app.processEvents()
        app._restore_selected_invoices()
        self.app.processEvents()
        self.assertEqual(app.invoices_list[app.table.currentRow()]["id"], selected_id)
        self.assertEqual(app.db.get_invoice(selected_id)["is_deleted"], 0)

    def test_context_actions_capture_selection_row_hint_before_reload(self):
        app = self.review_app
        claim_id = app.db.create_claim_group("Context action claim")
        app._load_claims()
        claim_index = app.combo_claims.findData(claim_id)
        self.assertGreaterEqual(claim_index, 0)
        app.combo_claims.setCurrentIndex(claim_index)
        app.table.selectRow(1)
        self.app.processEvents()
        captured_hints = []

        def record_reload():
            captured_hints.append(app._select_row_hint)

        with patch.object(app, "_load_invoices", side_effect=record_reload), \
                patch.object(app, "_load_claims"), \
                patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
            app._link_invoices_to_claim()
        self.assertEqual(captured_hints[-1], 1)

        captured_hints.clear()
        with patch.object(app, "_load_invoices", side_effect=record_reload), \
                patch.object(app, "_load_claims"), \
                patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
            app._unlink_selected_invoices()
        self.assertEqual(captured_hints[-1], 1)

        selected_id = app.invoices_list[1]["id"]
        app.db.soft_delete_invoice(selected_id)
        captured_hints.clear()
        with patch.object(app, "_load_invoices", side_effect=record_reload), \
                patch.object(app, "_load_claims"):
            app._restore_selected_invoices()
        self.assertEqual(captured_hints[-1], 1)

        captured_hints.clear()
        with patch.object(app, "_load_invoices", side_effect=record_reload), \
                patch.object(app, "_load_claims"), \
                patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
            app._reparse_selected_invoices()
        self.assertEqual(captured_hints[-1], 1)

        class FakeDownloader:
            def __init__(self, download_dir):
                self.download_dir = download_dir

            def close(self):
                return None

        captured_hints.clear()
        with patch("scripts.invoice_fetch.link_downloader.LinkDownloader", FakeDownloader), \
                patch.object(app, "_load_invoices", side_effect=record_reload), \
                patch.object(app, "_load_claims"), \
                patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
            app._redownload_selected_invoices()
        self.assertEqual(captured_hints[-1], 1)


if __name__ == "__main__":
    unittest.main()
