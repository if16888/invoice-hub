# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
import json
import tempfile
import shutil

from scripts.invoice_fetch.gui.helpers import resolve_invoice_documents, resolve_stored_path, _normalize_path_list

class TestUIPreviewHelpers(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp()).resolve()
        self.runtime_dir = self.temp_dir / "runtime"
        self.attachments_dir = self.runtime_dir / "attachments"
        self.attachments_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_normalize_path_list(self):
        self.assertEqual(_normalize_path_list(None), [])
        self.assertEqual(_normalize_path_list(""), [])
        self.assertEqual(_normalize_path_list("path/to/file.pdf"), ["path/to/file.pdf"])
        self.assertEqual(_normalize_path_list(["a.pdf", "b.pdf"]), ["a.pdf", "b.pdf"])
        self.assertEqual(_normalize_path_list(json.dumps(["a.pdf", "b.pdf"])), ["a.pdf", "b.pdf"])

    def test_resolve_invoice_documents_empty(self):
        invoice = {}
        docs = resolve_invoice_documents(invoice, self.runtime_dir)
        self.assertEqual(docs, [])

    def test_resolve_invoice_documents_relative_exists(self):
        # Create attachment file
        att_file = self.attachments_dir / "invoice.pdf"
        att_file.touch()

        # Create extra file under runtime_dir directly
        extra_file = self.runtime_dir / "receipt.png"
        extra_file.touch()

        invoice = {
            "attachment_path": "invoice.pdf",
            "extra_paths": json.dumps(["receipt.png", "not_exist.pdf"])
        }

        docs = resolve_invoice_documents(invoice, self.runtime_dir)
        self.assertEqual(len(docs), 3)

        # Primary doc should be resolved to runtime/attachments/invoice.pdf since it exists there
        self.assertEqual(docs[0]["type"], "primary")
        self.assertEqual(docs[0]["title"], "主发票")
        self.assertEqual(docs[0]["path"], att_file)
        self.assertEqual(docs[0]["basename"], "invoice.pdf")

        # First extra doc resolved to runtime/receipt.png
        self.assertEqual(docs[1]["type"], "supporting")
        self.assertEqual(docs[1]["path"], extra_file)

        # Second extra doc does not exist, falls back to relative under runtime_dir
        self.assertEqual(docs[2]["type"], "supporting")
        self.assertEqual(docs[2]["path"], self.runtime_dir / "not_exist.pdf")

    def test_resolve_invoice_documents_absolute_path(self):
        abs_file = self.temp_dir / "absolute_invoice.pdf"
        abs_file.touch()

        invoice = {
            "attachment_path": str(abs_file.resolve())
        }

        docs = resolve_invoice_documents(invoice, self.runtime_dir)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["path"], abs_file)

    def test_resolve_stored_path_uses_shared_candidates(self):
        nested = self.attachments_dir / "2026-06-01" / "shared.png"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.touch()

        resolved = resolve_stored_path("attachments/2026-06-01/shared.png", self.runtime_dir)
        self.assertEqual(resolved, nested)

        fallback = resolve_stored_path("shared.png", self.runtime_dir)
        self.assertEqual(fallback, nested)

    def test_pagination_bounds_logic(self):
        # Simulate simple pagination index adjustment bounds logic
        docs = [1, 2, 3]

        # Test basic index constraints
        def clamp_index(idx, length):
            if length == 0:
                return 0
            return max(0, min(idx, length - 1))

        self.assertEqual(clamp_index(-1, len(docs)), 0)
        self.assertEqual(clamp_index(1, len(docs)), 1)
        self.assertEqual(clamp_index(3, len(docs)), 2)
        self.assertEqual(clamp_index(5, len(docs)), 2)


class TestUIPreviewGUI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp()).resolve()
        self.db_path = self.temp_dir / "test_gui_preview.db"
        self.pdf_file = self.temp_dir / "a.pdf"
        self.pdf_file.touch()
        self.img_file = self.temp_dir / "extra1.png"
        self.img_file.touch()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_preview_panel_selection_states(self):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            # Setup db
            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                db.insert_invoice({
                    "mail_from": "test@sender.com",
                    "mail_subject": "Invoice test 1",
                    "mail_date": "2026-05-30",
                    "invoice_type": "PDF",
                    "invoice_number": "11111",
                    "invoice_date": "2026-06-01",
                    "total_amount": "100.00",
                    "buyer_name": "Company",
                    "seller_name": "Seller A",
                    "attachment_path": str(self.pdf_file.resolve()),
                    "extra_paths": [str(self.img_file.resolve())],
                    "category": "Office",
                    "confirmed_note": "",
                    "review_status": "to_review"
                })
                db.insert_invoice({
                    "mail_from": "test2@sender.com",
                    "mail_subject": "Invoice test 2",
                    "mail_date": "2026-05-30",
                    "invoice_type": "PDF",
                    "invoice_number": "22222",
                    "invoice_date": "2026-05-30",
                    "total_amount": "200.00",
                    "buyer_name": "Company",
                    "seller_name": "Seller B",
                    "attachment_path": "b.pdf",
                    "extra_paths": [],
                    "category": "Office",
                    "confirmed_note": "",
                    "review_status": "to_review"
                })



            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                self.assertIsNone(window.pdf_document)
                self.assertIsNone(window.pdf_view)
                window._deferred_init()
                app.processEvents()

                # Case 1: No selection
                window.table.clearSelection()
                window._on_table_selection_changed()
                app.processEvents()
                self.assertEqual(window.lbl_preview_status.text(), "请选择一张发票查看原件")
                self.assertEqual(window.lbl_file_info.text(), "0 / 0 无文件")
                self.assertFalse(window.btn_prev.isEnabled())
                self.assertFalse(window.btn_next.isEnabled())
                self.assertFalse(window.btn_open_ext.isEnabled())

                # Case 2: Single selection
                window.table.selectRow(0)
                window._on_table_selection_changed()
                app.processEvents()
                self.assertEqual(window.current_preview_index, 0)
                self.assertEqual(len(window.current_preview_docs), 2) # a.pdf + extra1.png
                self.assertTrue(window.lbl_file_info.text().startswith("1/2"))
                self.assertTrue(window.btn_prev.isEnabled())
                self.assertTrue(window.btn_next.isEnabled())
                from scripts.invoice_fetch.gui.app import check_has_qt_pdf
                if check_has_qt_pdf():
                    self.assertIsNotNone(window.pdf_document)
                    self.assertIsNotNone(window.pdf_view)
                    window._zoom_fit_width()
                    window._zoom_fit_page()
                    window._zoom_100()
                    window._zoom_in()
                    window._zoom_out()

                # Check overlay toolbar hidden by default upon document load
                self.assertTrue(window.overlay_toolbar.isHidden())

                # Trigger show overlay helper
                window._show_overlay_toolbar()
                self.assertFalse(window.overlay_toolbar.isHidden())

                # Trigger hide overlay helper
                window._hide_overlay_toolbar()
                self.assertTrue(window.overlay_toolbar.isHidden())

                # Case 3: Multiple selection
                window.table.selectAll()
                window._on_table_selection_changed()
                app.processEvents()
                self.assertEqual(window.lbl_preview_status.text(), "已选择多张发票，请选择单张查看原件")
                self.assertEqual(window.lbl_file_info.text(), "0 / 0 无文件")
                self.assertFalse(window.btn_prev.isEnabled())
                self.assertFalse(window.btn_next.isEnabled())
                self.assertFalse(window.btn_open_ext.isEnabled())
                self.assertTrue(window.overlay_toolbar.isHidden())



            finally:
                if hasattr(window, "pdf_view") and window.pdf_view is not None:
                    window.pdf_view.setDocument(None)
                if hasattr(window, "pdf_document") and window.pdf_document is not None:
                    window.pdf_document.close()
                    window.pdf_document.setParent(None)
                    window.pdf_document = None
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()
                import gc; gc.collect()



        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_empty_preview_state_mentions_file_actions(self):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                db.insert_invoice({
                    "mail_subject": "Invoice without attachment",
                    "mail_date": "2026-05-30",
                    "invoice_type": "PDF",
                    "invoice_number": "33333",
                    "invoice_date": "2026-06-02",
                    "total_amount": "100.00",
                    "buyer_name": "Company",
                    "seller_name": "Seller C",
                    "attachment_path": "",
                    "extra_paths": [],
                    "category": "Office",
                    "confirmed_note": "",
                    "review_status": "to_review"
                })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                window._deferred_init()
                window.table.selectRow(0)
                window._on_table_selection_changed()
                app.processEvents()

                self.assertIn("当前发票没有可预览的原件", window.lbl_preview_status.text())
                self.assertIn("查看文件", window.lbl_preview_status.text())
                self.assertIn("定位文件", window.lbl_preview_status.text())
                self.assertFalse(window.btn_prev.isEnabled())
                self.assertFalse(window.btn_next.isEnabled())
            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()
        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_preview_status_distinguishes_common_empty_states(self):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                db.insert_invoice({
                    "mail_subject": "Preview failure modes",
                    "mail_date": "2026-05-30",
                    "invoice_type": "PDF",
                    "invoice_number": "44444",
                    "invoice_date": "2026-06-02",
                    "total_amount": "100.00",
                    "buyer_name": "Company",
                    "seller_name": "Seller D",
                    "attachment_path": "",
                    "extra_paths": [],
                    "category": "Office",
                    "confirmed_note": "",
                    "review_status": "to_review"
                })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                window._deferred_init()
                app.processEvents()

                window._show_preview_status("当前发票没有可预览的原件")
                self.assertIn("查看文件", window.lbl_preview_status.text())
                self.assertIn("定位文件", window.lbl_preview_status.text())

                window._show_preview_status("文件不存在")
                self.assertIn("原件文件不存在", window.lbl_preview_status.text())

                window._show_preview_status("暂不支持内嵌预览，请点击打开外部文件")
                self.assertIn("当前格式暂不支持内嵌预览", window.lbl_preview_status.text())

                window._show_preview_status("图片加载失败，暂不支持预览")
                self.assertIn("图片加载失败", window.lbl_preview_status.text())
            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()
        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_preview_logs_large_image_and_uses_resize_debounce(self):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            large_img = self.temp_dir / "large-preview.png"
            with open(large_img, "wb") as f:
                f.seek((9 * 1024 * 1024) - 1)
                f.write(b"\0")

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            logs = []
            window.write_log = logs.append
            try:
                self.assertTrue(window.image_resize_timer.isSingleShot())
                self.assertEqual(window.image_resize_timer.interval(), 80)

                window.current_preview_docs = [{
                    "path": large_img,
                    "title": "测试图片",
                    "basename": large_img.name,
                }]
                window.current_preview_index = 0
                window._update_document_preview()
                app.processEvents()

                self.assertTrue(any("[性能] 大图预览可能较慢" in line for line in logs))
                self.assertTrue(any("[性能] 原件预览: type=.png" in line for line in logs))
                self.assertTrue(any("fallback=1" in line for line in logs))

                window._schedule_image_display_update()
                self.assertTrue(window.image_resize_timer.isActive())
                window.image_resize_timer.stop()
            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()
        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_preview_zoom_methods(self):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            # Setup db
            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                db.insert_invoice({
                    "mail_from": "test@sender.com",
                    "mail_subject": "Invoice test 1",
                    "mail_date": "2026-05-30",
                    "invoice_type": "PDF",
                    "invoice_number": "11111",
                    "invoice_date": "2026-06-01",
                    "total_amount": "100.00",
                    "buyer_name": "Company",
                    "seller_name": "Seller A",
                    "attachment_path": "a.pdf",
                    "extra_paths": ["extra1.png"],
                    "category": "Office",
                    "confirmed_note": "",
                    "review_status": "to_review"
                })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                window._deferred_init()
                app.processEvents()

                # Check default zoom mode is fit_width
                self.assertEqual(window.image_zoom_mode, "fit_width")

                # Setup active image scroll area and check custom zooms do not crash
                window.preview_stack.setCurrentWidget(window.image_scroll_area)
                window.image_zoom_mode = "fit_width"
                window._zoom_fit_page()
                self.assertEqual(window.image_zoom_mode, "fit_page")

                window._zoom_fit_width()
                self.assertEqual(window.image_zoom_mode, "fit_width")

                window._zoom_100()
                self.assertEqual(window.image_zoom_mode, "custom")
                self.assertEqual(window.image_zoom_factor, 1.0)

                window._zoom_in()
                self.assertEqual(window.image_zoom_mode, "custom")
                self.assertGreater(window.image_zoom_factor, 1.0)

                window._zoom_out()
                self.assertEqual(window.image_zoom_mode, "custom")

            finally:
                if hasattr(window, "pdf_view") and window.pdf_view is not None:
                    window.pdf_view.setDocument(None)
                if hasattr(window, "pdf_document") and window.pdf_document is not None:
                    window.pdf_document.close()
                    window.pdf_document.setParent(None)
                    window.pdf_document = None
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()
                import gc; gc.collect()

        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_lazy_loading_and_first_load_limits(self):
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            # Setup db with more than 100 entries to test the 100 first load limit
            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                for i in range(120):
                    db.insert_invoice({
                        "invoice_number": f"LIMIT_{i}",
                        "total_amount": "100.00",
                        "seller_name": "Limit Seller",
                        "invoice_date": "2026-06-01",
                        "category": "Office",
                        "review_status": "to_review"
                    })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            # Ensure no prior instantiation was made and check that pdf_document/pdf_view are None initially (Lazy Widget Instantiation)
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                self.assertIsNone(window.pdf_document)
                self.assertIsNone(window.pdf_view)
                self.assertTrue(window._is_first_load)

                # Execute deferred init
                window._deferred_init()
                app.processEvents()

                # Verify that only 100 invoices are loaded on first paint/load due to the first load limit
                self.assertEqual(len(window.invoices_list), 100)
                self.assertEqual(window.table.rowCount(), 100)
                self.assertFalse(window._is_first_load)
                # Load-all button should be visible with total count
                self.assertTrue(window._limited_first_load_active)
                self.assertEqual(window._limited_first_load_total, 120)
                self.assertFalse(window.btn_load_all.isHidden())
                self.assertIn("120", window.btn_load_all.text())

                # Reset filter should reload everything, exceeding the 100 limit since _is_first_load is now False
                window._reset_invoice_filters()
                app.processEvents()
                self.assertEqual(len(window.invoices_list), 120)
                self.assertEqual(window.table.rowCount(), 120)
                self.assertFalse(window._limited_first_load_active)
                self.assertTrue(window.btn_load_all.isHidden())

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()

        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_first_load_limit_shows_load_all_button(self):
        """Test 1: First load with >100 invoices shows 'load all' button with correct count."""
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                for i in range(120):
                    db.insert_invoice({
                        "invoice_number": f"BTN_{i:04d}",
                        "total_amount": "10.00",
                        "seller_name": "Button Seller",
                        "invoice_date": "2026-06-01",
                        "category": "Office",
                        "review_status": "to_review"
                    })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                window._deferred_init()
                app.processEvents()

                # Table should show only 100
                self.assertEqual(window.table.rowCount(), 100)
                # Filter button "all" should show total 120
                self.assertIn("120", window.filter_buttons["all"].text())
                # Load-all button should be visible
                self.assertFalse(window.btn_load_all.isHidden())
                self.assertIn("加载全部 120 张", window.btn_load_all.text())
                # Status bar should show limited info
                status_text = window.lbl_status_left.text()
                self.assertIn("100 / 120", status_text)
                self.assertIn("首屏限量加载", status_text)

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()

        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_load_all_click_shows_all_records(self):
        """Test 2: Clicking 'load all' loads all records and hides the button."""
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                for i in range(120):
                    db.insert_invoice({
                        "invoice_number": f"ALL_{i:04d}",
                        "total_amount": "10.00",
                        "seller_name": "All Seller",
                        "invoice_date": "2026-06-01",
                        "category": "Office",
                        "review_status": "to_review"
                    })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                window._deferred_init()
                app.processEvents()

                # Precondition: limited load active
                self.assertEqual(window.table.rowCount(), 100)
                self.assertFalse(window.btn_load_all.isHidden())

                # Click load all
                window._load_all_invoices_clicked()
                app.processEvents()
                app.processEvents()  # Ensure all deferred QTimer callbacks are flushed

                # All records should be loaded
                self.assertEqual(window.table.rowCount(), 120)
                self.assertEqual(len(window.invoices_list), 120)
                # Button should be hidden
                self.assertTrue(window.btn_load_all.isHidden())
                self.assertFalse(window._limited_first_load_active)
                # Status prefix should not show limited info
                prefix = window._format_status_count_prefix()
                self.assertNotIn("100 / 120", prefix)
                self.assertIn("120", prefix)

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()

        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_under_100_hides_load_all_button(self):
        """Test 3: With <100 invoices, load-all button stays hidden."""
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                for i in range(50):
                    db.insert_invoice({
                        "invoice_number": f"SMALL_{i:04d}",
                        "total_amount": "5.00",
                        "seller_name": "Small Seller",
                        "invoice_date": "2026-06-01",
                        "category": "Office",
                        "review_status": "to_review"
                    })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                window._deferred_init()
                app.processEvents()

                self.assertEqual(window.table.rowCount(), 50)
                self.assertTrue(window.btn_load_all.isHidden())
                self.assertFalse(window._limited_first_load_active)

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()

        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_search_bypasses_first_load_limit(self):
        """Test 4: Search is not affected by first-load limit and hides load-all button."""
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                for i in range(120):
                    db.insert_invoice({
                        "invoice_number": f"SRCH_{i:04d}",
                        "total_amount": "10.00",
                        "seller_name": "Target Seller" if i < 5 else "Other Seller",
                        "invoice_date": "2026-06-01",
                        "category": "Office",
                        "review_status": "to_review"
                    })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                window._deferred_init()
                app.processEvents()

                # Precondition: limited load is active
                self.assertEqual(window.table.rowCount(), 100)
                self.assertFalse(window.btn_load_all.isHidden())

                # Search for "Target Seller"
                window.txt_search.setText("Target Seller")
                window.search_reload_timer.stop()
                window._load_invoices()
                app.processEvents()

                # Should show only matching results (5)
                self.assertEqual(window.table.rowCount(), 5)
                # Load-all button should be hidden during search
                self.assertTrue(window.btn_load_all.isHidden())
                self.assertFalse(window._limited_first_load_active)

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()

        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise

    def test_load_all_selection_reset(self):
        """Test: Selection reset behavior for first load and load all."""
        try:
            from PySide6.QtWidgets import QApplication
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.db import InvoiceDB
            with InvoiceDB(self.db_path) as db:
                for i in range(120):
                    db.insert_invoice({
                        "invoice_number": f"SEL_{i:04d}",
                        "total_amount": "10.00",
                        "seller_name": "Selection Seller",
                        "invoice_date": "2026-06-01",
                        "category": "Office",
                        "review_status": "to_review"
                    })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            window = InvoiceReviewApp(self.db_path, splash=None)
            try:
                window._deferred_init()
                app.processEvents()

                # 1. First load: row count is 100, selectedRows count should be 1
                self.assertEqual(window.table.rowCount(), 100)
                selected_rows = window.table.selectionModel().selectedRows()
                self.assertEqual(len(selected_rows), 1)

                # 2. Click load all: row count is 120, selectedRows count should remain 1
                window._load_all_invoices_clicked()
                app.processEvents()
                app.processEvents()  # Ensure QTimer events are processed

                self.assertEqual(window.table.rowCount(), 120)
                selected_rows = window.table.selectionModel().selectedRows()
                self.assertEqual(len(selected_rows), 1)

                # 3. Manual selectAll: selectedRows count can be 120
                window.table.selectAll()
                app.processEvents()
                selected_rows = window.table.selectionModel().selectedRows()
                self.assertEqual(len(selected_rows), 120)

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()

        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test: {e}")
            raise
