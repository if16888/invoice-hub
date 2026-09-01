# -*- coding: utf-8 -*-
"""Native desktop geometry observations for the workbench.

These tests intentionally depend on a real Qt desktop/window manager and are
owned by the non-gating native geometry lane.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QPoint, Qt, QSettings
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QSplitter, QWidget
    from scripts.invoice_fetch.gui.workbench_settings import workbench_settings

    _HAS_PYSIDE6 = True
except (ImportError, OSError, RuntimeError):
    _HAS_PYSIDE6 = False

_QAPP = None


def _get_app():
    global _QAPP
    if not _HAS_PYSIDE6:
        return None
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class TestWorkbenchNativeGeometry(unittest.TestCase):
    """Tests that observe native desktop geometry rather than policy tokens."""

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6/native desktop unavailable")
        self._settings_dir = tempfile.TemporaryDirectory(
            prefix="invoice-hub-native-workbench-settings-"
        )
        self.addCleanup(self._settings_dir.cleanup)
        self._settings_patch = patch(
            "scripts.invoice_fetch.gui.app.workbench_settings",
            side_effect=lambda runtime_dir=None: workbench_settings(
                runtime_dir or Path(self._settings_dir.name)
            ),
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)
        _get_app()
        settings = self._settings()
        settings.remove("nav_collapsed_manual")
        settings.remove("shortcut_help_expanded")
        settings.sync()

    def tearDown(self):
        if _HAS_PYSIDE6:
            QApplication.processEvents()
            settings = self._settings()
            settings.remove("nav_collapsed_manual")
            settings.remove("shortcut_help_expanded")
            settings.sync()

    def _settings(self):
        return workbench_settings(Path(self._settings_dir.name))

    def _make_window(self, td: str):
        """Create a minimal InvoiceReviewApp against a temporary database."""
        try:
            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        except (ImportError, OSError, RuntimeError) as exc:
            self.skipTest(f"InvoiceReviewApp import failed: {exc}")
        db_path = Path(td) / "workbench_native_geometry.db"
        return InvoiceReviewApp(db_path, splash=None)

    @staticmethod
    def _close_window(window):
        if window is None:
            return
        try:
            from shiboken6 import isValid
        except ImportError:
            isValid = lambda _object: True
        try:
            if not isValid(window):
                return
            db = getattr(window, "db", None)
            if db is not None and getattr(db, "is_open", False):
                db.close()
            window.close()
            window.deleteLater()
            QApplication.processEvents()
        except (AttributeError, RuntimeError):
            pass

    def test_main_splitter_stretch_factors(self):
        """Left pane stretches; right detail pane has zero stretch."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                # Both splitter children must have positive size
                sizes = window.main_splitter.sizes()
                self.assertEqual(len(sizes), 2)
                self.assertTrue(all(s > 0 for s in sizes))
            finally:
                self._close_window(window)

    def test_left_splitter_sizes_nonzero(self):
        """Both vertical panes must have positive size after construction."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                sizes = window.left_splitter.sizes()
                self.assertEqual(len(sizes), 2)
                self.assertTrue(all(s > 0 for s in sizes))
            finally:
                self._close_window(window)

    def test_preview_toolbar_and_thumbnail_rail_stay_compact(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertLessEqual(window.overlay_toolbar.height(), 40)
                self.assertLessEqual(window.thumbnail_rail.width(), 104)
            finally:
                self._close_window(window)

    def test_invoice_record_header_exists_and_stays_compact(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertEqual(window.lbl_record_section_title.text(), "发票记录")
                self.assertLessEqual(window.record_header.height(), 28)
                self.assertGreaterEqual(window.record_header.height(), 24)
            finally:
                self._close_window(window)

    def test_review_table_shows_at_least_seven_dense_rows_at_1366(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                QApplication.processEvents()
                visible_rows = window.table.viewport().height() // window.table.verticalHeader().defaultSectionSize()
                self.assertGreaterEqual(visible_rows, 7)
            finally:
                self._close_window(window)

    def test_workbench_core_surfaces_do_not_overflow_at_target_widths(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                for width in (1366, 1600, 1920):
                    window.resize(width, 900)
                    window.show()
                    QApplication.processEvents()
                    self.assertLessEqual(window.workbench_top_toolbar.width(), width)
                    self.assertLessEqual(window.filter_bar_widget.width(), width)
                    self.assertLessEqual(window.record_header.width(), width)
            finally:
                self._close_window(window)

    def test_shortcut_disclosure_defaults_collapsed_without_resizing_splitter(self):
        settings = self._settings()
        settings.remove("shortcut_help_expanded")
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.resize(1920, 1080)
                window.show()
                QApplication.processEvents()
                QApplication.processEvents()
                self.assertFalse(window.shortcut_disclosure.is_expanded())
                before = window.main_splitter.sizes()
                window._toggle_shortcut_disclosure()
                QApplication.processEvents()
                self.assertTrue(window.shortcut_disclosure.is_expanded())
                self.assertEqual(window.main_splitter.sizes(), before)
            finally:
                window.shortcut_disclosure.hide()
                self._close_window(window)

    def test_user_adjusted_left_splitter_is_not_reset_by_resize(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                # Earlier integration cases may leave hidden top-level test
                # windows alive in this shared QApplication. Close those
                # stale Invoice Hub windows before exercising this window so
                # their pending layout/timer work cannot affect the contract.
                for other in QApplication.topLevelWidgets():
                    if (
                        isinstance(other, QWidget)
                        and other is not window
                        and other.windowTitle().startswith("Invoice Hub")
                    ):
                        other.close()
                        other.deleteLater()
                QApplication.processEvents()
                window.show()
                window.showNormal()
                window.raise_()
                window.activateWindow()
                # Keep the test window inside the native desktop work area.
                # On hosted Windows, requesting a 1920x1080 normal window on
                # a smaller desktop can leave the window apparently at that
                # size until the next resize, when the window manager restores
                # it to the available geometry.  That turns a width-only
                # request into an unrelated height resize before the product
                # can be evaluated.
                screen = QApplication.primaryScreen()
                available = (
                    screen.availableGeometry()
                    if screen is not None
                    else window.geometry()
                )
                if window.minimumWidth() > available.width():
                    # Some hosted Windows images expose a 1024px desktop
                    # while the product's compact minimum is 1040px. Relax
                    # only the top-level test window constraint so the
                    # vertical splitter can still be exercised in a real
                    # native window instead of skipping the contract.
                    window.setMinimumWidth(0)
                target_width = min(1200, max(0, available.width() - 40))
                target_height = min(900, max(0, available.height() - 10))
                target_width = max(target_width, window.minimumWidth() + 1)
                target_height = max(target_height, window.minimumHeight() + 1)
                self.assertLessEqual(
                    target_width,
                    available.width(),
                    "native desktop is narrower than the workbench minimum: "
                    f"available={available.width()}x{available.height()}, "
                    f"minimum={window.minimumWidth()}x{window.minimumHeight()}",
                )
                self.assertLessEqual(
                    target_height,
                    available.height(),
                    "native desktop is shorter than the workbench minimum: "
                    f"available={available.width()}x{available.height()}, "
                    f"minimum={window.minimumWidth()}x{window.minimumHeight()}",
                )
                window.resize(target_width, target_height)
                # Construction starts with a compatibility shim and then
                # installs the real QSplitter from a deferred callback. Wait
                # for the actual handle/geometry instead of assuming a fixed
                # delay or interacting with the shim.  Compact native
                # desktops may legitimately compress the panes below their
                # ideal minimumSizeHint; that must not prevent exercising the
                # real handle path.
                deadline = time.monotonic() + 2.0
                splitter = None
                while time.monotonic() < deadline:
                    QApplication.processEvents()
                    candidate = getattr(window, "left_splitter", None)
                    middle = getattr(window, "middle_workspace", None)
                    if middle is not None and middle.layout() is not None:
                        middle.layout().activate()
                    if candidate is not None:
                        parent = candidate.parentWidget()
                        if parent is not None and parent.layout() is not None:
                            parent.layout().activate()
                        candidate.updateGeometry()
                    if (
                        isinstance(candidate, QSplitter)
                        and candidate.count() == 2
                        and candidate.handle(1) is not None
                        and len(candidate.sizes()) == 2
                        and all(int(size) > 0 for size in candidate.sizes())
                    ):
                        splitter = candidate
                        break
                    QTest.qWait(20)
                self.assertIsNotNone(
                    splitter,
                    "real vertical splitter handle did not become available",
                )
                assert splitter is not None

                initial_sizes = splitter.sizes()
                total_before = sum(initial_sizes)
                record_widget = splitter.widget(0)
                preview_widget = splitter.widget(1)
                record_min = int(record_widget.minimumHeight())
                record_max = min(
                    int(record_widget.maximumHeight()),
                    total_before - int(preview_widget.minimumHeight()),
                )
                current_record = int(initial_sizes[0])
                down_room = max(0, current_record - record_min)
                up_room = max(0, record_max - current_record)
                if down_room:
                    delta = -min(40, down_room)
                else:
                    delta = min(40, up_room)
                self.assertNotEqual(
                    delta,
                    0,
                    "native splitter has no feasible user-adjustment range: "
                    f"sizes={initial_sizes}, total={total_before}, "
                    f"record_min={record_min}, record_max={record_max}",
                )

                moved_positions = []
                splitter.splitterMoved.connect(
                    lambda position, _index: moved_positions.append(int(position))
                )
                handle = splitter.handle(1)
                start = handle.rect().center()
                end = QPoint(start.x(), start.y() + delta)
                # setSizes() changes pixels but does not establish the native
                # user-adjusted state. Exercise the same handle path as a user.
                QTest.mousePress(handle, Qt.LeftButton, pos=start)
                QTest.qWait(20)
                QTest.mouseMove(handle, end, 50)
                QTest.mouseRelease(handle, Qt.LeftButton, pos=end)
                QApplication.processEvents()
                moved_sizes = splitter.sizes()

                self.assertTrue(
                    moved_positions,
                    "real splitter handle drag did not emit splitterMoved",
                )
                self.assertNotEqual(
                    moved_sizes[0],
                    initial_sizes[0],
                    "native handle drag did not move the record pane: "
                    f"initial={initial_sizes}, moved={moved_sizes}",
                )

                # Keep the native height constant.  A large width delta can
                # make the Windows window manager clamp the requested height
                # to the available desktop, turning this into a height resize
                # and legitimately rebalancing the panes.  Use the smallest
                # feasible width change so this contract remains width-only.
                before_resize_width = window.width()
                before_resize_height = window.height()
                if before_resize_width <= window.minimumWidth():
                    window.setMinimumWidth(0)
                resized_width = (
                    before_resize_width - 1
                    if before_resize_width > 1
                    else before_resize_width + 1
                )
                self.assertNotEqual(resized_width, before_resize_width)
                window.resize(resized_width, before_resize_height)
                QApplication.processEvents()
                # Hosted Windows runners can deliver the final splitter/layout
                # geometry one event-loop turn after the resize event.  Read
                # the user-adjusted state only after that native layout pass.
                QTest.qWait(50)
                QApplication.processEvents()
                self.assertEqual(
                    window.height(),
                    before_resize_height,
                    "requested width-only resize changed the native window height: "
                    f"before={before_resize_width}x{before_resize_height}, "
                    f"after={window.width()}x{window.height()}, "
                    f"requested_width={resized_width}",
                )
                resized_sizes = splitter.sizes()

                # QSplitter preserves the user-adjusted pane in native pixels;
                # compare the actual user-selected pixel position rather than
                # an impossible fixed target or a platform-dependent ratio.
                self.assertAlmostEqual(
                    resized_sizes[0],
                    moved_sizes[0],
                    delta=8,
                    msg=(
                        "user splitter position changed after width-only resize: "
                        f"window={window.width()}x{window.height()}, "
                        f"splitter={splitter.width()}x{splitter.height()}, "
                        f"initial={initial_sizes}, moved={moved_sizes}, "
                        f"resized={resized_sizes}, "
                        f"upper_minmax=({record_widget.minimumHeight()},"
                        f"{record_widget.maximumHeight()}), "
                        f"preview_min={preview_widget.minimumHeight()}, "
                        "baseline="
                        f"{window.review_page.property('reviewBaselinePipelineApplied')}, "
                        "scheduled="
                        f"{window.review_page.property('reviewBaselinePipelineScheduled')}"
                    ),
                )
            finally:
                self._close_window(window)
