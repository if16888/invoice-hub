from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QWidget

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.local_file_drop import LocalFileDropFilter, local_import_paths
from scripts.invoice_fetch.gui.mobile_upload_session import (
    MobileUploadSessionController,
    MobileUploadSessionPanel,
)


_APP = QApplication.instance() or QApplication([])


class V020DragDropLayoutNetworkTests(unittest.TestCase):
    def test_drop_payload_filters_unsupported_remote_and_duplicate_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pdf = root / "invoice.PDF"
            unsupported = root / "notes.txt"
            pdf.write_bytes(b"pdf")
            unsupported.write_text("text", encoding="utf-8")
            mime = QMimeData()
            mime.setUrls([
                QUrl.fromLocalFile(str(pdf)),
                QUrl.fromLocalFile(str(pdf)),
                QUrl.fromLocalFile(str(unsupported)),
                QUrl("https://example.invalid/invoice.pdf"),
            ])

            self.assertEqual(local_import_paths(mime), (pdf.resolve(),))

    def test_drop_filter_accepts_files_on_child_widgets_and_routes_them_once(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "invoice.pdf"
            path.write_bytes(b"pdf")
            window = QMainWindow()
            window._shutdown_requested = False
            window._start_local_import_paths = Mock(return_value=True)
            child = QWidget(window)
            drop_filter = LocalFileDropFilter(window)
            try:
                self.assertTrue(child.acceptDrops())
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(path))])
                enter = QDragEnterEvent(
                    QPoint(2, 2), Qt.CopyAction, mime, Qt.NoButton, Qt.NoModifier
                )
                QApplication.sendEvent(child, enter)
                self.assertTrue(enter.isAccepted())

                drop = QDropEvent(
                    QPointF(2, 2), Qt.CopyAction, mime, Qt.NoButton, Qt.NoModifier
                )
                QApplication.sendEvent(child, drop)
                self.assertTrue(drop.isAccepted())
                window._start_local_import_paths.assert_called_once_with((path.resolve(),))
            finally:
                _APP.removeEventFilter(drop_filter)
                window.close()

    def test_drop_import_respects_the_data_operation_busy_lock(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "invoice.pdf"
            path.write_bytes(b"pdf")
            window = InvoiceReviewApp(Path(td) / "invoices.db", splash=None)
            try:
                with patch.object(window, "_try_begin_data_operation", return_value=False) as acquire, patch(
                    "scripts.invoice_fetch.gui.app.LocalImportWorker"
                ) as worker:
                    self.assertFalse(window._start_local_import_paths((path,)))
                acquire.assert_called_once_with("本地导入")
                worker.assert_not_called()
            finally:
                window.close()

    def test_review_detail_panel_collapses_restores_and_persists_width(self):
        with tempfile.TemporaryDirectory() as td:
            settings = QSettings(str(Path(td) / "workbench.ini"), QSettings.IniFormat)
            with patch("scripts.invoice_fetch.gui.app.workbench_settings", return_value=settings):
                window = InvoiceReviewApp(Path(td) / "invoices.db", splash=None)
                window.resize(1440, 900)
                window.show()
                window._switch_main_page("review")
                _APP.processEvents()
                _APP.processEvents()
                initial_width = window.main_splitter.sizes()[1]
                self.assertGreater(initial_width, 0)
                self.assertIn("Ctrl+B", window.workbench_shortcuts)

                available = sum(window.main_splitter.sizes())
                window.main_splitter.setSizes([available - 400, 400])
                window.main_splitter.splitterMoved.emit(400, 1)
                _APP.processEvents()
                window._save_splitter_prefs()
                self.assertEqual(settings.value("splitter/review_detail_restore_width", type=int), 400)

                QTest.keyClick(window, Qt.Key_B, Qt.ControlModifier)
                _APP.processEvents()
                self.assertTrue(window._review_detail_collapsed)
                self.assertEqual(window.main_splitter.sizes()[1], 0)

                window.btn_toggle_review_detail.click()
                _APP.processEvents()
                self.assertFalse(window._review_detail_collapsed)
                self.assertGreater(window.main_splitter.sizes()[1], 0)
                self.assertGreaterEqual(window._review_detail_restore_width, 352)
                self.assertFalse(settings.value("review_detail_collapsed", True, type=bool))
                window._splitter_save_timer.stop()
                window._save_splitter_prefs()
                window.close()
                _APP.processEvents()

    def test_network_diagnosis_is_available_from_desktop_and_explains_ap_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            controller = MobileUploadSessionController(Path(td) / "invoices.db")
            panel = MobileUploadSessionPanel(controller)
            controller.server = SimpleNamespace(
                status=lambda: {
                    "active": True,
                    "local_self_check": "pass",
                    "lan_client_access_confirmed": False,
                    "interface_name": "Wi-Fi",
                    "public_host": "192.168.1.50",
                }
            )
            controller.firewall_status = SimpleNamespace(
                as_dict=lambda: {"state": "rule_present"}
            )
            captured = {}

            def capture_exec(box):
                captured["summary"] = box.text()
                captured["details"] = box.detailedText()
                return QMessageBox.Ok

            with patch.object(QMessageBox, "exec", new=capture_exec):
                panel.btn_idle_network_diagnosis.click()

            self.assertIn("尚未收到手机访问", captured["summary"])
            self.assertIn("AP 隔离", captured["summary"])
            self.assertIn("个人热点", captured["details"])
            self.assertIn("微信文件传输助手", captured["details"])
            self.assertIn("192.168.1.50", captured["details"])
            panel.close()
            panel.deleteLater()
            controller.deleteLater()
            _APP.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
