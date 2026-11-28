"""Contracts for atomically replacing Qt PDF preview views."""

from __future__ import annotations

import inspect
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QSize, Qt, qInstallMessageHandler
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QPushButton, QStackedWidget, QWidget

from scripts.invoice_fetch.gui.pdf_preview_controller import PdfPreviewController
from scripts.invoice_fetch.gui import preview_mixin


def _make_pdf(path: Path, colors=None) -> None:
    """Write a tiny valid PDF for native QtPdf lifecycle tests."""
    streams = [b""] if colors is None else [
        (" ".join(str(channel / 255) for channel in color) + " rg 0 0 300 400 re f\n").encode("ascii")
        for color in colors
    ]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [" + " ".join(f"{3 + 2 * i} 0 R" for i in range(len(streams)))
         + f"] /Count {len(streams)} >>").encode("ascii"),
    ]
    for i, stream in enumerate(streams):
        objects.extend([
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Contents {4 + 2 * i} 0 R "
             "/Resources << >> >>").encode("ascii"),
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream",
        ])
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode("ascii"))
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref_offset = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(data)


class PdfPreviewControllerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_controller_replaces_views_without_null_document_attachment(self):
        source = inspect.getsource(PdfPreviewController)
        self.assertIn("view.setDocument(document)", source)
        self.assertIn("self._stack.removeWidget(view)", source)
        self.assertIn("document.close()", source)
        self.assertNotIn("setDocument(None)", source)


    def test_failed_replacement_always_notifies_host(self):
        source = inspect.getsource(PdfPreviewController.load)
        self.assertIn("self.failed.emit(str(path))", source)
        self.assertNotIn("if self._view is None:", source)

    def test_failed_replacement_clears_previous_preview_before_error_state(self):
        target = SimpleNamespace(
            pdf_preview_controller=SimpleNamespace(clear=MagicMock()),
            _show_preview_status=MagicMock(),
            _set_zoom_buttons_enabled=MagicMock(),
            pdf_view=object(),
            pdf_document=object(),
        )

        preview_mixin.PreviewMixin._on_pdf_preview_failed(target, "broken.pdf")

        target.pdf_preview_controller.clear.assert_called_once_with()
        self.assertIsNone(target.pdf_view)
        self.assertIsNone(target.pdf_document)
        target._show_preview_status.assert_called_once_with("PDF 加载失败，暂不支持预览")

    def test_generation_guard_prevents_stale_activation(self):
        source = inspect.getsource(PdfPreviewController._activate)
        self.assertIn("generation != self._generation", source)


    def test_duplicate_ready_activation_keeps_active_view_alive(self):
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        view = QWidget(stack)
        document = _FakeDocument(Path("invoice.pdf"))

        controller._activate(0, view, document)
        controller._activate(0, view, document)

        self.assertIs(controller.active_view(), view)
        self.assertGreaterEqual(stack.indexOf(view), 0)
        self.app.processEvents()

    def test_dispose_ignores_already_deleted_qt_view(self):
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        view = QWidget(stack)
        stack.addWidget(view)
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # Windows Qt may leave the Python wrapper reachable after C++ deletion.
        controller._dispose(view, None)
        self.assertIsNone(controller.active_view())

    def test_rapid_invoice_switches_keep_only_latest_pdf(self):
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        for index in range(10):
            view = QWidget(stack)
            document = _FakeDocument(Path(f"invoice-{index}.pdf"))
            controller._generation += 1
            controller._activate(controller._generation, view, document)

        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(controller.active_path(), Path("invoice-9.pdf"))
        self.assertEqual(stack.count(), 1)

        controller.clear()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertIsNone(controller.active_document())
        self.assertEqual(stack.count(), 0)

    def test_repeated_real_pdf_switches_emit_no_known_qt_lifecycle_warnings(self):
        try:
            from PySide6.QtPdf import QPdfDocument  # noqa: F401
        except ImportError:
            self.skipTest("QtPdf is unavailable")

        messages: list[str] = []

        def capture_message(_kind, _context, message):
            messages.append(str(message))

        previous_handler = qInstallMessageHandler(capture_message)
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        try:
            with tempfile.TemporaryDirectory() as td:
                paths = [Path(td) / "first.pdf", Path(td) / "second.pdf"]
                for path in paths:
                    _make_pdf(path)

                for _ in range(5):
                    for path in paths:
                        controller.load(path)
                        deadline = time.monotonic() + 2.0
                        while controller.active_path() != path and time.monotonic() < deadline:
                            self.app.processEvents()
                            QTest.qWait(5)
                        self.assertEqual(controller.active_path(), path)

                controller.clear()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()
        finally:
            qInstallMessageHandler(previous_handler)

        blocked = (
            "QObject::connect(QPdfDocument, QPdfLinkModel): invalid nullptr parameter",
            "QFont::setPointSize: Point size <= 0",
        )
        offenders = [message for message in messages if any(token in message for token in blocked)]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_show_preview_status_cancels_pending_pdf_load(self):
        _SlowDocument.instances.clear()
        stack = QStackedWidget()
        host = _PreviewHost(stack)
        host.pdf_preview_controller.document_class = _SlowDocument
        host.pdf_preview_controller.view_class = _FakePdfView

        host.pdf_preview_controller.load(Path("invoice-a.pdf"))
        pending = _SlowDocument.instances[-1]
        self.assertIsNone(host.pdf_preview_controller.active_view())

        # The user selects something the PDF surface cannot show.
        host._show_preview_status("暂不支持内嵌预览，请点击打开外部文件")

        # The old load finishes afterwards and must not activate.
        pending.set_ready()
        self.app.processEvents()

        self.assertIsNone(
            host.pdf_preview_controller.active_view(),
            "迟到的 PDF 加载不能覆盖更新的选择",
        )
        self.assertIsNone(host.pdf_view)
        self.assertIsNone(host.pdf_document)
        self.assertEqual(stack.count(), 1, "被取消的视图不能被加入预览栈")
        self.assertIs(stack.currentWidget(), host.lbl_preview_status)

    def test_show_preview_status_disposes_active_pdf_view(self):
        stack = QStackedWidget()
        host = _PreviewHost(stack)
        controller = host.pdf_preview_controller
        view = _FakePdfView(stack)
        document = _FakeDocument(Path("invoice-a.pdf"))
        controller._generation += 1
        controller._activate(controller._generation, view, document)
        self.assertIs(controller.active_view(), view)

        host._show_preview_status("文件不存在")
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

        self.assertIsNone(controller.active_view())
        self.assertIsNone(host.pdf_view)
        self.assertEqual(stack.count(), 1)
        self.assertIs(stack.currentWidget(), host.lbl_preview_status)


class NativeReviewPdfNavigationTests(unittest.TestCase):
    """Exercise the actual review window, not a navigator that accepts any arguments."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtPdf import QPdfDocument  # noqa: F401
            from PySide6.QtPdfWidgets import QPdfView  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("QtPdf is unavailable")
        cls.app = QApplication.instance() or QApplication([])

    def _wait_for(self, predicate, description):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(predicate(), description)

    @contextmanager
    def _review_window(self):
        from scripts.invoice_fetch.db import InvoiceDB
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = {key: root / f"{key}.pdf" for key in ("A", "B", "S", "broken")}
            colors = {"A": [(194, 61, 78)], "B": [(64, 156, 205), (53, 162, 88), (228, 151, 54)],
                      "S": [(170, 96, 202), (85, 185, 172)]}
            for key, pages in colors.items():
                _make_pdf(paths[key], pages)
            paths["broken"].write_bytes(b"not a PDF")
            db_path = root / "navigation.db"
            ids = {}
            with InvoiceDB(db_path) as db:
                for key in ("broken", "A", "B"):
                    ids[key] = db.insert_invoice({
                        "invoice_number": f"SYNTH-{key}", "invoice_date": "2026-08-01", "expense_date": "2026-08-01",
                        "total_amount": "12.00", "seller_name": "Synthetic", "buyer_name": "Synthetic",
                        "review_status": "to_review", "attachment_path": str(paths[key]),
                        "extra_paths": [str(paths["S"])] if key == "B" else [],
                    })
                    self.assertIsNotNone(ids[key])
            self.assertFalse(db.is_open)
            window = InvoiceReviewApp(db_path)
            # Existing page-button consumers are optional/legacy. These real
            # Qt widgets observe their enabled state without adding product UI.
            window.btn_prev_page = QPushButton(window)
            window.btn_next_page = QPushButton(window)
            window.btn_prev_page.hide()
            window.btn_next_page.hide()
            try:
                window.resize(1280, 760)
                window.show()
                window.activateWindow()
                self._wait_for(lambda: window._deferred_init_done, "initial review load")
                QTest.mouseClick(window.workbench_nav_buttons["review"], Qt.LeftButton)
                self._wait_for(lambda: window.table.isVisible() and len(window.invoices_list) == 3, "visible review table")
                yield window, paths, colors, ids
            finally:
                # The real preview owns the file handles. Retire its pair
                # before removing the generated PDF/SQLite files on Windows.
                window._reset_pdf_preview_state()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                window.close()
                self._wait_for(lambda: not window.db.is_open, "review window closed its SQLite connection")
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()

    def _click_invoice(self, window, invoice_id):
        row = next(i for i, item in enumerate(window.invoices_list) if item["id"] == invoice_id)
        index = window.table.model().index(row, 0)
        window.table.scrollTo(index)
        self.app.processEvents()
        rect = window.table.visualRect(index).intersected(window.table.viewport().rect())
        self.assertFalse(rect.isEmpty(), "invoice cell is visible")
        QTest.mouseClick(window.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        self.app.processEvents()
        self.assertEqual(window.current_invoice["id"], invoice_id)

    def _assert_page(self, window, path, page, count, index, invoice_id, *, pair=None, color=None):
        from PySide6.QtPdf import QPdfDocument
        controller = window.pdf_preview_controller
        self._wait_for(lambda: controller._pending_document is None, "PDF activation settled")
        self.app.processEvents()
        self.assertEqual(controller.active_path(), path)
        view, document = controller.active_view(), controller.active_document()
        self.assertIsNotNone(view)
        self.assertIsNotNone(document)
        self.assertIs(window.preview_stack.currentWidget(), view)
        self.assertTrue(view.isVisible())
        self.assertIs(window.pdf_view, view)
        self.assertIs(window.pdf_document, document)
        self.assertIs(view.document(), document)
        self.assertEqual(document.status(), QPdfDocument.Status.Ready)
        self.assertEqual(document.pageCount(), count)
        self.assertEqual(view.pageNavigator().currentPage(), page)
        self.assertEqual(window._get_pdf_page_info(), (page + 1, count))
        self.assertEqual(window.current_preview_index, index)
        self.assertEqual(window.current_preview_docs[index]["path"], path)
        self.assertEqual(window.current_invoice["id"], invoice_id)
        self.assertEqual(window.btn_prev_page.isEnabled(), page > 0)
        self.assertEqual(window.btn_next_page.isEnabled(), page < count - 1)
        if pair is not None:
            self.assertIs(view, pair[0])
            self.assertIs(document, pair[1])
            self.assertEqual(controller._generation, pair[2])
        if color is not None:
            # Validate that the native document's selected page really is the
            # intended colored fixture, without a screen/timing threshold.
            image = document.render(page, QSize(12, 16))
            self.assertFalse(image.isNull())
            rgb = image.pixelColor(6, 8).getRgb()[:3]
            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(rgb, color)), (rgb, color))
        return view, document, controller._generation

    def _key(self, window, key):
        view = window.pdf_view
        view.setFocus()
        self.app.processEvents()
        focus = self.app.focusWidget()
        self.assertTrue(focus is view or (focus is not None and view.isAncestorOf(focus)))
        QTest.keyClick(view, key)
        self.app.processEvents()

    def _menu_action(self, window, text):
        # Exercise the real context-menu event and connected QAction. Only
        # intercept the blocking native menu loop so no modal can be stranded.
        chosen = []

        test = self

        class ActionMenu(QMenu):
            def exec(self, *_args, **_kwargs):
                action = next(item for item in self.actions() if item.text() == text)
                test.assertTrue(action.isEnabled())
                chosen.append(action.text())
                action.trigger()
                return action

        container = window.preview_container
        pos = container.rect().center()
        with patch.object(preview_mixin, "QMenu", ActionMenu):
            QCoreApplication.sendEvent(container, QContextMenuEvent(QContextMenuEvent.Mouse, pos, container.mapToGlobal(pos)))
        self.app.processEvents()
        self.assertEqual(chosen, [text])

    def test_review_keys_and_context_actions_keep_pair_until_file_boundary(self):
        from PySide6.QtPdfWidgets import QPdfView

        messages = []
        old_handler = qInstallMessageHandler(lambda _kind, _context, message: messages.append(str(message)))
        try:
            with self._review_window() as (window, paths, colors, ids):
                self._click_invoice(window, ids["A"])
                self._assert_page(window, paths["A"], 0, 1, 0, ids["A"], color=colors["A"][0])
                self._click_invoice(window, ids["B"])
                pair = self._assert_page(window, paths["B"], 0, 3, 0, ids["B"], color=colors["B"][0])
                controller = window.pdf_preview_controller
                with patch.object(controller, "load", wraps=controller.load) as loads:
                    self._menu_action(window, "100% 原始比例")
                    self._menu_action(window, "放大")
                    self.assertEqual(pair[0].zoomMode(), QPdfView.ZoomMode.Custom)
                    zoom = pair[0].zoomFactor()
                    for key, page in ((Qt.Key_Right, 1), (Qt.Key_Left, 0)):
                        self._key(window, key)
                        self._assert_page(window, paths["B"], page, 3, 0, ids["B"], pair=pair, color=colors["B"][page])
                    for action, page in (("下一页 ▶", 1), ("◀ 上一页", 0), ("◀ 上一页", 0),
                                         ("下一页 ▶", 1), ("下一页 ▶", 2), ("下一页 ▶", 2)):
                        self._menu_action(window, action)
                        self._assert_page(window, paths["B"], page, 3, 0, ids["B"], pair=pair)
                    self.assertEqual(pair[0].zoomMode(), QPdfView.ZoomMode.Custom)
                    self.assertAlmostEqual(pair[0].zoomFactor(), zoom)
                    loads.assert_not_called()

                    # Keyboard falls back to the next file only at the actual
                    # page boundary; each file replacement owns a fresh pair.
                    self._key(window, Qt.Key_Right)
                    material = self._assert_page(window, paths["S"], 0, 2, 1, ids["B"], color=colors["S"][0])
                    loads.assert_called_once_with(paths["S"])
                    self.assertEqual(material[2], pair[2] + 1)
                    self.assertIsNot(material[0], pair[0])
                    self.assertIsNot(material[1], pair[1])
                    self.assertEqual(material[0].zoomMode(), QPdfView.ZoomMode.FitToWidth)
                    loads.reset_mock()
                    self._key(window, Qt.Key_Right)
                    self._assert_page(window, paths["S"], 1, 2, 1, ids["B"], pair=material, color=colors["S"][1])
                    self._key(window, Qt.Key_Left)
                    self._assert_page(window, paths["S"], 0, 2, 1, ids["B"], pair=material)
                    loads.assert_not_called()
                    self._key(window, Qt.Key_Left)
                    returned = self._assert_page(window, paths["B"], 0, 3, 0, ids["B"], color=colors["B"][0])
                    loads.assert_called_once_with(paths["B"])
                    self.assertEqual(returned[2], material[2] + 1)
                    self.assertIsNot(returned[0], material[0])
                    self.assertIsNot(returned[1], material[1])

                # Rapid real invoice switches and a corrupt replacement must
                # never leave the retired PDF visible under another invoice.
                self._click_invoice(window, ids["A"])
                self._click_invoice(window, ids["B"])
                self._click_invoice(window, ids["broken"])
                self._wait_for(lambda: controller.active_view() is None and "PDF 加载失败" in window.lbl_preview_status.text(),
                               "failed replacement clears the old PDF")
                self.assertIsNone(controller.active_document())
                self.assertIsNone(controller.active_path())
                self.assertIsNone(window.pdf_view)
                self.assertIsNone(window.pdf_document)
                self.assertIs(window.preview_stack.currentWidget(), window.preview_empty_page)
                self._click_invoice(window, ids["B"])
                self._assert_page(window, paths["B"], 0, 3, 0, ids["B"], color=colors["B"][0])
        finally:
            qInstallMessageHandler(old_handler)
        offenders = [message for message in messages if "invalid nullptr parameter" in message or "QFont::setPointSize: Point size <= 0" in message]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_native_navigator_and_scroll_emit_page_state_without_reloading(self):
        with self._review_window() as (window, paths, _colors, ids):
            self._click_invoice(window, ids["A"])
            self._click_invoice(window, ids["B"])
            pair = self._assert_page(window, paths["B"], 0, 3, 0, ids["B"])
            controller = window.pdf_preview_controller
            navigator = pair[0].pageNavigator()
            pages = []
            controller.page_changed.connect(lambda page, count: pages.append((page, count)))
            with patch.object(controller, "load", wraps=controller.load) as loads:
                # Unlike the application's navigation method, a native jump
                # doesn't explicitly refresh the page buttons. The connection
                # in _activate must propagate this state change by itself.
                navigator.jump(1, QPointF(), 0.0)
                self.app.processEvents()
                self.assertIn((1, 3), pages)
                self._assert_page(window, paths["B"], 1, 3, 0, ids["B"], pair=pair)
                scrollbar = pair[0].verticalScrollBar()
                self._wait_for(lambda: scrollbar.maximum() > 0, "native multipage document is scrollable")
                for key, page in ((Qt.Key_End, 2), (Qt.Key_Home, 0)):
                    pages.clear()
                    scrollbar.setFocus()
                    QTest.keyClick(scrollbar, key)
                    self._wait_for(lambda: navigator.currentPage() == page, "native scroll changes page")
                    self.assertIn((page, 3), pages)
                    self._assert_page(window, paths["B"], page, 3, 0, ids["B"], pair=pair)
                loads.assert_not_called()


class _PreviewHost(preview_mixin.PreviewMixin):
    """Minimal host exposing only the surface ``_show_preview_status`` touches."""

    def __init__(self, stack: QStackedWidget):
        self.preview_stack = stack
        self.lbl_preview_status = QLabel("status")
        stack.addWidget(self.lbl_preview_status)
        self.overlay_toolbar = MagicMock()
        self.pdf_preview_controller = PdfPreviewController(stack, None)
        self.pdf_view = object()
        self.pdf_document = object()
        self.zoom_enabled: list[bool] = []

    def _set_zoom_buttons_enabled(self, enabled):
        self.zoom_enabled.append(enabled)


class _FakePdfStatus:
    Ready = "ready"
    Error = "error"


class _FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, value):
        for slot in list(self._slots):
            slot(value)


class _SlowDocument:
    """Document double whose ``load`` stays pending until the test says so."""

    Status = _FakePdfStatus
    instances: list["_SlowDocument"] = []

    def __init__(self, parent=None):
        self.statusChanged = _FakeSignal()
        self._status = "loading"
        self.loaded_path = None
        self.closed = False
        self.deleted = False
        _SlowDocument.instances.append(self)

    def load(self, path):
        self.loaded_path = path

    def status(self):
        return self._status

    def set_ready(self):
        self._status = _FakePdfStatus.Ready
        self.statusChanged.emit(self._status)

    def close(self):
        self.closed = True

    def deleteLater(self):
        self.deleted = True


class _FakePdfView(QWidget):
    class PageMode:
        MultiPage = 0
        SinglePage = 1

    class ZoomMode:
        FitToWidth = 0
        FitInView = 1
        Custom = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        self._navigator = MagicMock()

    def setDocument(self, document):
        self.document = document

    def setPageMode(self, _mode):
        pass

    def setZoomMode(self, _mode):
        pass

    def zoomFactor(self):
        return 1.0

    def pageNavigator(self):
        return self._navigator


class _FakeDocument:
    def __init__(self, path: Path):
        self._invoice_hub_path = path
        self.closed = False
        self.deleted = False

    def close(self):
        self.closed = True

    def deleteLater(self):
        self.deleted = True


if __name__ == "__main__":
    unittest.main()
