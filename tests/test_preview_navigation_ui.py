# -*- coding: utf-8 -*-
"""Preview navigation, focus protection and compact detail-panel tests."""

import unittest
import tempfile
import shutil
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock


_PENDING_EVIDENCE_TYPE = "待关联证明材料"


def _ensure_deferred_invoice_load(window, app_obj):
    was_unloaded = not getattr(window, "_deferred_init_done", False)
    if hasattr(window, "_deferred_init") and was_unloaded:
        window._deferred_init()
        if app_obj is not None:
            app_obj.processEvents()
    return was_unloaded


def _adjust_row_idx_after_deferred_load(window, row_idx, was_unloaded):
    if not was_unloaded or row_idx != 0:
        return row_idx
    invoices = list(getattr(window, "invoices_list", []) or [])
    if not invoices:
        return row_idx
    first_type = str((invoices[0] or {}).get("invoice_type") or "")
    if first_type != _PENDING_EVIDENCE_TYPE:
        return row_idx
    for idx, inv in enumerate(invoices):
        if str((inv or {}).get("invoice_type") or "") != _PENDING_EVIDENCE_TYPE:
            return idx
    return row_idx


# ── 1. File info formatting tests ────────────────────────────────────


class TestKeyboardFocusProtection(unittest.TestCase):
    """Tests for _focus_is_editing_widget."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError):
            cls.app = None

    @classmethod
    def tearDownClass(cls):
        cls.app = None

    def setUp(self):
        if self.app is None:
            self.skipTest("PySide6 not available")


    def test_pushbutton_is_not_editing(self):
        """QPushButton focus -> False."""
        from PySide6.QtWidgets import QPushButton, QWidget, QVBoxLayout
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = QWidget()
        window.setWindowTitle("test")
        widget = QPushButton("Test")
        layout = QVBoxLayout(window)
        layout.addWidget(widget)
        window.show()
        widget.setFocus()
        self.app.processEvents()

        app_obj = InvoiceReviewApp.__new__(InvoiceReviewApp)
        self.assertFalse(app_obj._focus_is_editing_widget())
        window.hide()

    def test_no_focus_is_not_editing(self):
        """No focused widget -> False."""
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        app_obj = InvoiceReviewApp.__new__(InvoiceReviewApp)
        self.assertFalse(app_obj._focus_is_editing_widget())


# ── 4. File-level navigation tests ───────────────────────────────────


class TestFileLevelNavigation(unittest.TestCase):
    """Tests for _prev_preview_doc / _next_preview_doc."""

    def test_next_file_increments_index(self):
        """Ctrl+Right equivalent: index advances from 0 to 1."""
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        app_obj = InvoiceReviewApp.__new__(InvoiceReviewApp)
        app_obj.current_preview_docs = [{"title": "主发票", "path": Path("a.pdf")},
                                         {"title": "证明材料", "path": Path("b.png")}]
        app_obj.current_preview_index = 0
        # Patch _update_document_preview to avoid QPdfDocument loading
        app_obj._update_document_preview = MagicMock()
        app_obj._update_pdf_page_buttons = MagicMock()

        app_obj._next_preview_doc()
        self.assertEqual(app_obj.current_preview_index, 1)

        app_obj._next_preview_doc()
        self.assertEqual(app_obj.current_preview_index, 0)  # wraps around

    def test_prev_file_decrements_index(self):
        """Ctrl+Left equivalent: index wraps from 0 to last."""
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        app_obj = InvoiceReviewApp.__new__(InvoiceReviewApp)
        app_obj.current_preview_docs = [{"title": "主发票", "path": Path("a.pdf")},
                                         {"title": "证明材料", "path": Path("b.png")}]
        app_obj.current_preview_index = 0
        app_obj._update_document_preview = MagicMock()
        app_obj._update_pdf_page_buttons = MagicMock()

        app_obj._prev_preview_doc()
        self.assertEqual(app_obj.current_preview_index, 1)  # wraps around


# ── 5. PDF page navigation tests ─────────────────────────────────────


class TestPdfPageNavigation(unittest.TestCase):
    """Tests for _navigate_pdf_page and related methods."""


    def test_navigate_non_pdf_returns_false(self):
        """_navigate_pdf_page returns False when not viewing a PDF."""
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        app_obj = InvoiceReviewApp.__new__(InvoiceReviewApp)
        app_obj.preview_stack = MagicMock()
        app_obj.preview_stack.currentWidget.return_value = MagicMock()  # not pdf_view

        result = app_obj._navigate_pdf_page(1)
        self.assertFalse(result)

    def test_pdf_page_buttons_disabled_for_single_page(self):
        """Page buttons should be disabled when PDF has only 1 page."""
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        app_obj = InvoiceReviewApp.__new__(InvoiceReviewApp)

        btn_prev = MagicMock()
        btn_next = MagicMock()
        app_obj.btn_prev_page = btn_prev
        app_obj.btn_next_page = btn_next

        mock_nav = MagicMock()
        mock_nav.currentPage.return_value = 0

        mock_pdf_doc = MagicMock()
        mock_pdf_doc.pageCount.return_value = 1
        mock_pdf_doc.pageNavigator.return_value = mock_nav

        mock_pdf_view = MagicMock()
        app_obj.pdf_document = mock_pdf_doc
        app_obj.pdf_view = mock_pdf_view
        app_obj.preview_stack = MagicMock()
        app_obj.preview_stack.currentWidget.return_value = mock_pdf_view

        app_obj._update_pdf_page_buttons()
        btn_prev.setEnabled.assert_called_with(False)
        btn_next.setEnabled.assert_called_with(False)


# ── 6. Link downloader cache tests ────────────────────────────────────


class TestNavigationFocusStability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError):
            cls.app = None

    @classmethod
    def tearDownClass(cls):
        cls.app = None

    def setUp(self):
        if self.app is None:
            self.skipTest("PySide6 not available")

    def test_focus_out_of_preview_does_not_intercept(self):
        from PySide6.QtWidgets import QWidget, QLineEdit
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent, Qt
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        # 1. 模拟焦点在一个独立的 QLineEdit (代表编辑框)
        window = QWidget()
        window.setWindowTitle("test focus")
        edit = QLineEdit(window)
        window.show()
        edit.setFocus()
        self.app.processEvents()

        app_obj = InvoiceReviewApp.__new__(InvoiceReviewApp)
        app_obj.preview_stack = MagicMock()

        # 模拟安装 eventFilter
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Left, Qt.NoModifier)
        watched = MagicMock()

        app_obj._prev_preview_doc = MagicMock()
        res = app_obj.eventFilter(watched, event)
        self.assertFalse(res)  # 不抢占焦点
        app_obj._prev_preview_doc.assert_not_called()
        window.hide()

    def test_focus_in_preview_intercepts(self):
        from PySide6.QtWidgets import QWidget, QScrollArea
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent, Qt
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = QWidget()
        window.setWindowTitle("test focus in preview")
        # 模拟 image_scroll_area
        scroll_area = QScrollArea(window)
        window.show()
        scroll_area.setFocus()
        self.app.processEvents()

        app_obj = InvoiceReviewApp.__new__(InvoiceReviewApp)
        app_obj._prev_preview_doc = MagicMock()

        # watched 设为 image_scroll_area 模拟事件分发
        app_obj.image_scroll_area = scroll_area
        app_obj.preview_container = window
        app_obj.preview_stack = MagicMock()
        app_obj.preview_stack.currentWidget.return_value = None
        app_obj.pdf_view = None
        app_obj.overlay_toolbar = None

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Left, Qt.NoModifier)
        res = app_obj.eventFilter(scroll_area, event)
        self.assertTrue(res)  # 成功拦截并消耗事件
        app_obj._prev_preview_doc.assert_called_once()
        window.hide()


class TestDetailPanelCompact001(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError):
            cls.app = None

    @classmethod
    def tearDownClass(cls):
        cls.app = None

    def setUp(self):
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_compact.db"
        if self.app is not None:
            self.app.processEvents()

    def tearDown(self):
        import shutil
        if self.app is not None:
            # Flush deferred widget deletions before the next test builds its
            # own windows.  A QPdfView/QPdfDocument ``deleteLater`` landing
            # during unrelated widget construction has crashed the native heap
            # (access violation) on the Windows CI runner.
            from PySide6.QtCore import QEvent

            self.app.processEvents()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _select_row(self, window, row_idx):
        from PySide6.QtCore import QItemSelectionModel
        was_unloaded = _ensure_deferred_invoice_load(window, self.app)
        row_idx = _adjust_row_idx_after_deferred_load(window, row_idx, was_unloaded)
        window.table.clearSelection()
        window.table.setCurrentItem(None)
        if window.table.selectionModel() is not None:
            window.table.selectionModel().clearSelection()
            window.table.selectionModel().clear()
        self.app.processEvents()

        window.table.selectRow(row_idx)
        self.app.processEvents()
        model = window.table.model()
        sel_model = window.table.selectionModel()
        idx = model.index(row_idx, 0)
        sel_model.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        window._on_table_selection_changed()
        self.app.processEvents()


    def test_supporting_docs_selector_multi(self):
        if self.app is None:
            self.skipTest("PySide6 not available")

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        from scripts.invoice_fetch.db import InvoiceDB

        # Create invoice with 2 linked docs + 1 pending evidence in the same mail
        with InvoiceDB(self.db_path) as db:
            db.insert_invoice({
                "id": 1,
                "invoice_number": "111",
                "invoice_date": "2026-06-01",
                "seller_name": "销售方A",
                "total_amount": "100.00",
                "review_status": "to_review",
                "mailbox_key": "mail_test",
                "mail_uid": 12345,
                "extra_paths": json.dumps(["attachments/doc1.pdf", "attachments/doc2.pdf"]),
            })
            # Pending evidence doc in same mail
            db.insert_invoice({
                "id": 2,
                "invoice_number": "",
                "invoice_date": "2026-06-01",
                "seller_name": "",
                "total_amount": "0.00",
                "review_status": "to_review",
                "invoice_type": "待关联证明材料",
                "mailbox_key": "mail_test",
                "mail_uid": 12345,
                "attachment_path": "attachments/doc3.pdf",
            })

        window = InvoiceReviewApp(self.db_path, splash=None)
        try:
            window.show()
            self.app.processEvents()

            # Find row index of invoice ID 1
            row_idx = 0
            for idx, inv in enumerate(window.invoices_list):
                if inv["id"] == 1:
                    row_idx = idx
                    break

            self._select_row(window, row_idx)

            # Expect 3 items (2 linked, 1 pending)
            self.assertEqual(window.combo_supporting_docs.count(), 3)
            texts = [window.combo_supporting_docs.itemText(i) for i in range(3)]
            linked_count = sum(1 for t in texts if "[已关联]" in t)
            pending_count = sum(1 for t in texts if "[待关联]" in t)
            self.assertEqual(linked_count, 2)
            self.assertEqual(pending_count, 1)
        finally:
            window.close()


    def test_open_selected_supporting_doc(self):
        if self.app is None:
            self.skipTest("PySide6 not available")

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        from scripts.invoice_fetch.db import InvoiceDB

        doc1 = self.temp_dir / "doc1.pdf"
        doc2 = self.temp_dir / "doc2.pdf"
        doc1.write_bytes(b"pdf1")
        doc2.write_bytes(b"pdf2")

        with InvoiceDB(self.db_path) as db:
            db.insert_invoice({
                "invoice_number": "111",
                "invoice_date": "2026-06-01",
                "seller_name": "销售方A",
                "total_amount": "100.00",
                "review_status": "to_review",
                "extra_paths": json.dumps([str(doc1), str(doc2)]),
            })

        window = InvoiceReviewApp(self.db_path, splash=None)
        try:
            window.show()
            self.app.processEvents()

            self._select_row(window, 0)

            # Mock _open_local_path
            window._open_local_path = MagicMock()

            # Select second item (index 1)
            window.combo_supporting_docs.setCurrentIndex(1)
            self.app.processEvents()

            # Trigger opening
            window._open_extra_docs()
            self.app.processEvents()

            # Verify only doc2 was opened
            window._open_local_path.assert_called_once_with(doc2)
        finally:
            window.close()
            window.deleteLater()
            if self.app is not None:
                self.app.processEvents()


    def test_supporting_doc_label_formatting(self):
        if self.app is None:
            self.skipTest("PySide6 not available")

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        window = InvoiceReviewApp(self.db_path, splash=None)
        try:
            path_normal = Path("short_name.pdf")
            label_normal = window._format_supporting_doc_label("已关联", path_normal)
            self.assertEqual(label_normal, "[已关联] short_name.pdf")

            path_long = Path("出租_87.90_2653700000000009000697_ex_6.pdf")
            label_long = window._format_supporting_doc_label("已关联", path_long, max_len=42)
            self.assertTrue(label_long.startswith("[已关联]"))
            self.assertIn("...", label_long)
            self.assertLessEqual(len(label_long), 42)
        finally:
            window.close()

    def test_post_link_combo_reposition(self):
        if self.app is None:
            self.skipTest("PySide6 not available")

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        from scripts.invoice_fetch.db import InvoiceDB

        doc1 = self.temp_dir / "doc1.pdf"
        doc2 = self.temp_dir / "doc2.pdf"
        doc1.write_bytes(b"pdf1")
        doc2.write_bytes(b"pdf2")

        with InvoiceDB(self.db_path) as db:
            db.insert_invoice({
                "invoice_number": "111",
                "invoice_date": "2026-06-01",
                "seller_name": "销售方A",
                "total_amount": "100.00",
                "review_status": "to_review",
                "extra_paths": json.dumps([str(doc1), str(doc2)]),
            })

        window = InvoiceReviewApp(self.db_path, splash=None)
        try:
            window.show()
            self.app.processEvents()

            self._select_row(window, 0)

            window._update_supporting_docs_selector(window.current_invoice, selected_path=doc2)
            self.app.processEvents()

            self.assertEqual(window.combo_supporting_docs.currentIndex(), 1)
            self.assertIn("doc2.pdf", window.combo_supporting_docs.itemText(1))
        finally:
            window.close()

    def test_excel_export_notes_and_evidence(self):
        from scripts.invoice_fetch.excel_export import export_excel
        import openpyxl

        doc1 = self.temp_dir / "doc1.pdf"
        doc2 = self.temp_dir / "doc2.pdf"

        rows = [
            {
                "invoice_number": "EXCEL001",
                "invoice_code": "CODE001",
                "invoice_date": "2026-06-01",
                "amount": "100.00",
                "total_amount": "100.00",
                "seller_name": "销售方A",
                "buyer_name": "购买方B",
                "confirmed_note": "团建说明",
                "extra_paths": [str(doc1), str(doc2)],
            }
        ]

        excel_file = self.temp_dir / "test_export.xlsx"
        export_excel(rows, excel_file)

        wb = openpyxl.load_workbook(excel_file)
        ws = wb["发票汇总"]

        headers = [ws.cell(row=1, column=col_idx).value for col_idx in range(1, ws.max_column + 1)]
        self.assertIn("个人备注", headers)
        self.assertIn("证明材料", headers)

        note_col_idx = headers.index("个人备注") + 1
        evidence_col_idx = headers.index("证明材料") + 1

        note_val = ws.cell(row=2, column=note_col_idx).value
        evidence_val = ws.cell(row=2, column=evidence_col_idx).value

        self.assertEqual(note_val, "团建说明")
        self.assertEqual(evidence_val, "doc1.pdf；doc2.pdf")
        self.assertNotIn(str(self.temp_dir), evidence_val)

    def test_gui_empty_attachment_hint(self):
        if self.app is None:
            self.skipTest("PySide6 not available")

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        from scripts.invoice_fetch.db import InvoiceDB

        with InvoiceDB(self.db_path) as db:
            db.insert_invoice({
                "invoice_number": "222",
                "invoice_date": "2026-06-01",
                "seller_name": "销售方B",
                "total_amount": "200.00",
                "review_status": "to_review",
                "mail_uid": 123,
                "download_url": "http://nnfp.jss.com.cn/show",
                "attachment_path": "",
            })

        window = InvoiceReviewApp(self.db_path, splash=None)
        try:
            window.show()
            self.app.processEvents()

            self._select_row(window, 0)

            self.assertEqual(window.txt_path.text(), "未下载原件（可重试下载或手动补原件）")
            self.assertTrue(window.btn_add_attachment.isEnabled())
            self.assertTrue(window.btn_retry_download.isEnabled())
            self.assertTrue(window.btn_retry_download.isVisible())
            self.assertEqual(window.txt_path.statusTip(), "双击补充原件")
            self.assertFalse(window.btn_open_file.isEnabled())
        finally:
            window.close()

    def test_approval_missing_attachment(self):
        if self.app is None:
            self.skipTest("PySide6 not available")

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        window = InvoiceReviewApp(self.db_path, splash=None)
        try:
            inv = {
                "invoice_number": "222",
                "invoice_date": "2026-06-01",
                "total_amount": "200.00",
                "attachment_path": "",
                "download_url": "http://nnfp.jss.com.cn/show",
            }
            missing = window._approval_missing_fields(inv)
            self.assertIn("原件", missing)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
