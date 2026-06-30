import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.invoice_fetch.db import InvoiceDB


class PreviewWorkbenchUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            import sys

            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def _make_window(self):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "preview.db"
        with InvoiceDB(db_path):
            pass
        config_patch = patch(
            "scripts.invoice_fetch.gui.app.load_config_safe",
            return_value={"reimbursement": {"strict_buyer_check": False}},
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)
        window = InvoiceReviewApp(db_path, splash=None)
        window._deferred_init()
        self.app.processEvents()
        self.addCleanup(window.close)
        self.addCleanup(window.db.close)
        return window, Path(temp_dir.name)

    def test_primary_preview_actions_have_stable_order(self):
        window, _ = self._make_window()
        self.assertEqual(
            tuple(window.preview_actions),
            (
                "zoom_out", "zoom_100", "zoom_in", "fit_width", "fit_page",
                "rotate_left", "rotate_right", "download", "print", "focus_mode",
            ),
        )

    def test_thumbnail_selection_updates_document_index(self):
        window, root = self._make_window()
        first = root / "first.png"
        second = root / "second.png"
        first.write_bytes(b"not-an-image")
        second.write_bytes(b"not-an-image")
        window.current_invoice = {"id": 1}
        window.current_preview_docs = [
            {"path": first, "label": "first"},
            {"path": second, "label": "second"},
        ]
        window.current_preview_index = 0

        window._refresh_preview_thumbnails()
        window._select_preview_doc(1)

        self.assertEqual(window.current_preview_index, 1)
        self.assertTrue(window.thumbnail_buttons[1].property("selected"))

    def test_preview_focus_mode_restores_original_parent_and_selection(self):
        window, _ = self._make_window()
        original_parent = window.preview_workbench.parentWidget()
        window.current_invoice = {"id": 42}
        window.current_preview_index = 2

        window._enter_preview_focus_mode()
        self.app.processEvents()
        self.assertIs(window.preview_workbench.parentWidget(), window.preview_focus_dialog)

        window._exit_preview_focus_mode()
        self.app.processEvents()
        self.assertIs(window.preview_workbench.parentWidget(), original_parent)
        self.assertEqual(window.current_invoice["id"], 42)
        self.assertEqual(window.current_preview_index, 2)

    def test_image_rotation_is_normalized_and_rejects_other_steps(self):
        window, root = self._make_window()
        image = root / "invoice.png"
        image.write_bytes(b"not-an-image")
        window.current_preview_docs = [{"path": image, "label": "invoice"}]
        window.current_preview_index = 0

        with patch.object(window, "_update_image_display") as update:
            self.assertTrue(window._rotate_preview(-90))
            self.assertEqual(window.preview_rotation, 270)
            update.assert_called_once_with()
        with self.assertRaises(ValueError):
            window._rotate_preview(180)

    def test_preview_action_availability_explains_unsupported_operations(self):
        window, root = self._make_window()
        pdf = root / "invoice.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        window._set_preview_action_availability(pdf)

        self.assertFalse(window.preview_actions["rotate_left"].isEnabled())
        self.assertIn("PDF", window.preview_actions["rotate_left"].toolTip())
        self.assertTrue(window.preview_actions["download"].isEnabled())
        self.assertTrue(window.preview_actions["print"].isEnabled())
        self.assertTrue(window.preview_actions["focus_mode"].isEnabled())

    def test_missing_preview_disables_actions_with_reason(self):
        window, root = self._make_window()
        missing = root / "missing.png"

        window._set_preview_action_availability(missing)

        for action in window.preview_actions.values():
            self.assertFalse(action.isEnabled())
            self.assertTrue(action.toolTip())

    def test_missing_preview_status_uses_explicit_multiline_guidance(self):
        window, _ = self._make_window()
        window._show_preview_status("文件不存在")
        text = window.lbl_preview_status.text()
        self.assertIn("原件文件不存在", text)
        self.assertIn("路径可能已移动、删除，或下载未完成。", text)
        self.assertIn("定位", text)
        self.assertIn("替换", text)

    def test_selection_change_updates_preview_document_binding(self):
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt

        window, root = self._make_window()
        first = root / "first.png"
        second = root / "second.png"

        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(Qt.red)
        self.assertTrue(image.save(str(first)))
        image.fill(Qt.blue)
        self.assertTrue(image.save(str(second)))

        first_id = window.db.insert_invoice(
            {
                "invoice_number": "SYNC-001",
                "expense_date": "2026-06-01",
                "invoice_date": "2026-06-01",
                "total_amount": "18.00",
                "seller_name": "Seller A",
                "review_status": "to_review",
                "attachment_path": str(first),
            }
        )
        second_id = window.db.insert_invoice(
            {
                "invoice_number": "SYNC-002",
                "expense_date": "2026-06-02",
                "invoice_date": "2026-06-02",
                "total_amount": "28.00",
                "seller_name": "Seller B",
                "review_status": "to_review",
                "attachment_path": str(second),
            }
        )

        window.show()
        self.app.processEvents()
        window._load_invoices()
        self.app.processEvents()

        self.assertTrue(window._select_invoice_by_id(first_id))
        self.app.processEvents()
        self.assertEqual(window.current_invoice["id"], first_id)
        self.assertEqual(window.current_preview_docs[0]["path"].resolve(), first.resolve())

        self.assertTrue(window._select_invoice_by_id(second_id))
        self.app.processEvents()
        self.assertEqual(window.current_invoice["id"], second_id)
        self.assertEqual(window.current_preview_docs[0]["path"].resolve(), second.resolve())
        self.assertIn("second.png", window.lbl_file_info.toolTip())

    def test_first_selected_invoice_populates_preview_surface(self):
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt

        window, root = self._make_window()
        preview_file = root / "initial.png"
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(Qt.green)
        self.assertTrue(image.save(str(preview_file)))

        invoice_id = window.db.insert_invoice(
            {
                "invoice_number": "FIRST-001",
                "expense_date": "2026-06-01",
                "invoice_date": "2026-06-01",
                "total_amount": "18.00",
                "seller_name": "Seller A",
                "review_status": "to_review",
                "attachment_path": str(preview_file),
            }
        )

        window.show()
        self.app.processEvents()
        window._load_invoices()
        self.app.processEvents()

        self.assertEqual(window.current_invoice["id"], invoice_id)
        self.assertTrue(window.current_preview_docs)
        self.assertEqual(window.current_preview_docs[0]["path"].resolve(), preview_file.resolve())
        self.assertNotEqual(window.preview_stack.currentWidget(), window.lbl_preview_status)

    def test_empty_preview_thumbnail_rail_keeps_single_add_attachment_entry(self):
        window, _ = self._make_window()
        window.current_invoice = {"id": 1}
        window.current_preview_docs = []
        window.current_preview_index = 0

        window._update_document_preview()
        self.app.processEvents()
        window._enter_preview_focus_mode()
        self.app.processEvents()

        add_buttons = [
            button for button in window.thumbnail_content.findChildren(type(window.btn_add_attachment))
            if button.objectName() == "PreviewAddAttachment"
        ]
        self.assertEqual(len(add_buttons), 1)

    def test_switching_between_pdf_invoices_rebinds_pdf_document(self):
        from PySide6.QtWidgets import QWidget

        class FakePdfDocument:
            def __init__(self, _parent=None):
                self.loaded_path = None
                self.closed = False
                self.deleted = False

            def load(self, path):
                self.loaded_path = path

            def close(self):
                self.closed = True

            def deleteLater(self):
                self.deleted = True

        class FakePdfView(QWidget):
            class PageMode:
                MultiPage = "multi"
                SinglePage = "single"

            class ZoomMode:
                FitToWidth = "fit-width"

            def __init__(self, _parent=None):
                super().__init__(_parent)
                self.document_ref = None

            def setDocument(self, document):
                self.document_ref = document

            def setPageMode(self, _mode):
                pass

            def setZoomMode(self, _mode):
                pass

            def pageNavigator(self):
                return None

        window, root = self._make_window()
        first = root / "first.pdf"
        second = root / "second.pdf"
        first.write_bytes(b"%PDF-1.4 first")
        second.write_bytes(b"%PDF-1.4 second")

        first_id = window.db.insert_invoice(
            {
                "invoice_number": "PDF-001",
                "expense_date": "2026-06-01",
                "invoice_date": "2026-06-01",
                "total_amount": "18.00",
                "seller_name": "Seller A",
                "review_status": "to_review",
                "attachment_path": str(first),
            }
        )
        second_id = window.db.insert_invoice(
            {
                "invoice_number": "PDF-002",
                "expense_date": "2026-06-02",
                "invoice_date": "2026-06-02",
                "total_amount": "28.00",
                "seller_name": "Seller B",
                "review_status": "to_review",
                "attachment_path": str(second),
            }
        )

        with patch(
            "scripts.invoice_fetch.gui.preview_mixin.get_qt_pdf_classes",
            return_value=(FakePdfDocument, FakePdfView),
        ):
            window.show()
            self.app.processEvents()
            window._load_invoices()
            self.app.processEvents()

            self.assertTrue(window._select_invoice_by_id(first_id))
            self.app.processEvents()
            first_document = window.pdf_document
            self.assertIsNotNone(first_document)
            self.assertEqual(Path(first_document.loaded_path).resolve(), first.resolve())

            self.assertTrue(window._select_invoice_by_id(second_id))
            self.app.processEvents()
            self.assertIsNot(window.pdf_document, first_document)
            self.assertTrue(first_document.closed)
            self.assertEqual(Path(window.pdf_document.loaded_path).resolve(), second.resolve())
            self.assertIs(window.pdf_view.document_ref, window.pdf_document)

    def test_double_clicking_preview_toggles_focus_mode(self):
        from PySide6.QtCore import QEvent

        window, _ = self._make_window()
        event = MagicMock()
        event.type.return_value = QEvent.Type.MouseButtonDblClick
        with patch.object(window, "_toggle_preview_focus_mode") as toggle:
            self.assertTrue(window.eventFilter(window.preview_container, event))
            toggle.assert_called_once_with()

    def test_control_wheel_zooms_without_scrolling_document(self):
        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtCore import Qt

        window, _ = self._make_window()
        event = MagicMock()
        event.type.return_value = QEvent.Type.Wheel
        event.modifiers.return_value = Qt.ControlModifier
        event.angleDelta.return_value = QPoint(0, 120)
        with patch.object(window, "_zoom_in") as zoom_in:
            self.assertTrue(window.eventFilter(window.image_scroll_area, event))
            zoom_in.assert_called_once_with()

    def test_workbench_shortcuts_use_only_approved_bindings(self):
        window, _ = self._make_window()
        self.assertEqual(
            set(window.workbench_shortcuts),
            {
                "Up", "Down", "Return", "Enter", "Delete", "Ctrl+E",
                "Ctrl+F", "F11", "Ctrl+I", "Ctrl+U", "Ctrl+M", "Ctrl+R", "Esc",
            },
        )
        self.assertFalse({"Space", "J", "K", "Alt+A", "Alt+I", "Alt+E"} & set(window.workbench_shortcuts))

    def test_workbench_review_action_yields_to_editing_widget(self):
        window, _ = self._make_window()
        action = MagicMock()

        with patch("scripts.invoice_fetch.gui.app.QApplication.focusWidget", return_value=window.txt_search):
            self.assertFalse(window._invoke_workbench_action(action))
        action.assert_not_called()

    def test_preview_toolbar_has_no_orphan_legacy_controls(self):
        window, _ = self._make_window()
        window.show()
        self.app.processEvents()

        toolbar_widgets = {window.overlay_toolbar}
        toolbar_widgets.update(window.preview_actions.values())
        legacy_names = (
            "btn_prev",
            "lbl_file_info",
            "btn_next",
            "btn_prev_page",
            "btn_next_page",
            "btn_open_ext",
            "btn_link_evidence",
        )

        for name in legacy_names:
            widget = getattr(window, name, None)
            if widget is None:
                continue
            self.assertTrue(
                widget is window.overlay_toolbar or window.overlay_toolbar.isAncestorOf(widget),
                f"{name} should be contained by overlay_toolbar",
            )
            if widget not in toolbar_widgets:
                self.assertFalse(widget.isVisible(), f"{name} leaked as a visible orphan control")
                geom = widget.geometry()
                self.assertLessEqual(max(geom.width(), geom.height()), 64, f"{name} kept abnormal geometry {geom}")

    def test_preview_focus_mode_keeps_review_shortcuts(self):
        window, root = self._make_window()
        attachment = root / "shortcut.bin"
        attachment.write_bytes(b"synthetic preview data")
        invoice_id = window.db.insert_invoice(
            {
                "invoice_number": "SHORTCUT-001",
                "expense_date": "2026-06-01",
                "invoice_date": "2026-06-01",
                "total_amount": "88.00",
                "seller_name": "Seller",
                "review_status": "to_review",
                "attachment_path": str(attachment),
            }
        )
        window._load_invoices()
        self.app.processEvents()
        window._select_invoice_by_id(invoice_id)
        self.app.processEvents()

        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        window._enter_preview_focus_mode()
        self.app.processEvents()
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        window.preview_focus_dialog.keyPressEvent(event)
        self.app.processEvents()

        self.assertEqual(window.db.get_invoice(invoice_id)["review_status"], "approved")

    def test_preview_focus_escape_exits_without_losing_selection(self):
        window, root = self._make_window()
        attachment = root / "escape.bin"
        attachment.write_bytes(b"synthetic preview data")
        invoice_id = window.db.insert_invoice(
            {
                "invoice_number": "ESC-001",
                "expense_date": "2026-06-01",
                "invoice_date": "2026-06-01",
                "total_amount": "88.00",
                "seller_name": "Seller",
                "review_status": "to_review",
                "attachment_path": str(attachment),
            }
        )
        window._load_invoices()
        self.app.processEvents()
        window._select_invoice_by_id(invoice_id)
        selected_row = window.table.currentRow()

        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        window._enter_preview_focus_mode()
        self.app.processEvents()
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        window.preview_focus_dialog.keyPressEvent(event)
        self.app.processEvents()

        self.assertIsNone(window.preview_focus_dialog)
        self.assertEqual(window.current_invoice["id"], invoice_id)
        self.assertEqual(window.table.currentRow(), selected_row)


if __name__ == "__main__":
    unittest.main()
