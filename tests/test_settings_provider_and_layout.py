# -*- coding: utf-8 -*-
"""
Tests for the invoice detail panel layout and review geometry.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from PySide6.QtWidgets import QApplication, QWidget, QSizePolicy
    from PySide6.QtCore import Qt, QPoint
except ImportError:
    QApplication, QWidget, QSizePolicy = None, None, None
    Qt, QPoint = None, None

from scripts.invoice_fetch.db import InvoiceDB


class TestInvoiceDetailPanelLayout(unittest.TestCase):
    """Verify geometry / size policy adjustments in InvoiceDetailPanel."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def setUp(self):
        from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel
        self.panel = InvoiceDetailPanel()

    def tearDown(self):
        if hasattr(self, "panel") and self.panel is not None:
            self.panel.close()
            self.panel.deleteLater()
            if self.app:
                self.app.processEvents()

    def test_detail_workbench_size_policy_and_layout_margins(self):
        # 1. detail_workbench should be expanding vertically, not fixed
        self.assertEqual(
            self.panel.detail_workbench.sizePolicy().verticalPolicy(),
            QSizePolicy.Expanding
        )

        # 2. right_content_layout top and bottom margins must be 0 for proper vertical alignment
        margins = self.panel.right_layout.contentsMargins()
        self.assertEqual(margins.top(), 0)
        self.assertEqual(margins.bottom(), 0)

        # 3. Verify no extra addStretch is added outside the workbench card layout
        count = self.panel.right_layout.count()
        stretch_exists = False
        for i in range(count):
            item = self.panel.right_layout.itemAt(i)
            if item.spacerItem() is not None:
                stretch_exists = True
                break
        self.assertFalse(stretch_exists, "right_layout should not have a spacer/stretch pushing detail_workbench up")


class TestInvoiceReviewAppGeometry(unittest.TestCase):
    """Verify real geometry alignment of components in InvoiceReviewApp."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def test_main_window_vertical_alignment_with_real_record(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_gui_geometry.db"
            with InvoiceDB(db_path) as db:
                db.insert_invoice({
                    "invoice_number": "CAT001",
                    "total_amount": "88.00",
                    "seller_name": "Geometry Seller",
                    "invoice_date": "2026-05-24",
                    "category": "餐饮",
                    "review_status": "to_review",
                })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            cfg = {
                "reimbursement": {
                    "buyer_name": "示例公司",
                    "strict_buyer_check": False,
                }
            }
            with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=cfg):
                window = InvoiceReviewApp(db_path, splash=None)

            try:
                window._deferred_init()
                self.app.processEvents()

                # Resize to a modest size that headless CI can handle
                window.resize(1280, 800)
                window.show()
                self.app.processEvents()

                # Select row to show detail_workbench
                window.table.selectRow(0)
                self.app.processEvents()

                # Verify detail_workbench is visible
                self.assertTrue(window._detail_panel.detail_workbench.isVisible())

                # Compare same-row sibling containers in the main horizontal splitter.
                # _detail_panel (right column) and preview_panel (bottom of left column)
                # share the same bottom edge since they are siblings under the same splitter row.
                # This comparison is stable regardless of the actual window size on headless CI.
                detail_panel_top = window._detail_panel.mapTo(window, QPoint(0, 0)).y()
                detail_panel_bottom = detail_panel_top + window._detail_panel.height()

                record_header_top = window.record_header.mapTo(window, QPoint(0, 0)).y()
                table_top = window.table.mapTo(window, QPoint(0, 0)).y()
                fixed_header_top = window._detail_panel.fixed_header_container.mapTo(window, QPoint(0, 0)).y()

                # Top alignment: fixed review header is aligned with middle workspace content area.
                filter_h = window.filter_bar_widget.height() if hasattr(window, "filter_bar_widget") else 0
                self.assertLessEqual(
                    abs((record_header_top - filter_h) - fixed_header_top),
                    24,
                    "fixed detail header is offset from record header top by > 24px",
                )
                self.assertGreaterEqual(
                    table_top - record_header_top,
                    24,
                    "record table should remain below the compact record header",
                )

                # Bottom alignment: right_content_widget (scroll area) should fill the detail_panel height.
                # We check inner scroll area bottom vs outer _detail_panel bottom - a purely internal measurement
                # that is not affected by window size or headless display constraints.
                tabs = window._detail_panel.detail_tabs
                tabs_bottom = tabs.mapTo(window, QPoint(0, 0)).y() + tabs.height()
                self.assertLessEqual(abs(detail_panel_bottom - tabs_bottom), 6, "detail tabs bottom is offset from _detail_panel bottom by > 6px")

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_detail_row_alignment_uses_shared_left_edge_and_fixed_action_cluster(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_gui_geometry_rows.db"
            with InvoiceDB(db_path) as db:
                db.insert_invoice({
                    "invoice_number": "CAT002",
                    "total_amount": "66.00",
                    "seller_name": "Geometry Seller 2",
                    "invoice_date": "2026-05-25",
                    "category": "餐饮",
                    "review_status": "to_review",
                })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            cfg = {
                "reimbursement": {
                    "buyer_name": "示例公司",
                    "strict_buyer_check": False,
                }
            }
            with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=cfg):
                window = InvoiceReviewApp(db_path, splash=None)

            try:
                window._deferred_init()
                self.app.processEvents()
                window.resize(1680, 1050)
                window.show()
                self.app.processEvents()
                window.table.selectRow(0)
                self.app.processEvents()

                panel = window._detail_panel
                self.assertFalse(hasattr(panel, "lbl_evidence_dot"))
                panel.set_note("示例备注")
                panel._apply_note_state(expanded=True)
                panel.update_evidence_row([])
                self.app.processEvents()

                core_x = panel.txt_number.mapTo(panel, QPoint(0, 0)).x()
                amount_x = panel.txt_amount.mapTo(panel, QPoint(0, 0)).x()
                buyer_x = panel.txt_buyer.mapTo(panel, QPoint(0, 0)).x()
                path_x = panel.original_status_line.mapTo(panel, QPoint(0, 0)).x()
                panel.detail_tabs.setCurrentWidget(panel.operation_scroll)
                self.app.processEvents()
                note_x = panel.txt_note.mapTo(panel, QPoint(0, 0)).x()
                panel.detail_tabs.setCurrentWidget(panel.right_content_widget)
                self.app.processEvents()
                missing_x = panel.evidence_status_line.mapTo(panel, QPoint(0, 0)).x()

                self.assertLessEqual(abs(core_x - amount_x), 4)
                self.assertLessEqual(abs(core_x - buyer_x), 4)
                self.assertLessEqual(abs(path_x - missing_x), 6)
                self.assertEqual(panel.original_status_line.height(), panel.evidence_status_line.height())

                panel.update_evidence_row([
                    {"label": "proof.pdf", "path": "/tmp/proof.pdf"}
                ])
                self.app.processEvents()
                filename_x = panel.evidence_status_line.mapTo(panel, QPoint(0, 0)).x()
                self.assertLessEqual(abs(path_x - filename_x), 6)

                panel.detail_tabs.setCurrentWidget(panel.reimbursement_scroll)
                self.app.processEvents()
                self.assertTrue(panel.combo_claims.isHidden())
                self.assertTrue(panel.lbl_claim_assignment.isVisible())
                self.assertGreaterEqual(panel.claim_actions_widget.layout().indexOf(panel.btn_delete_claim), 0)
                self.assertGreater(panel.detail_workbench.height(), 0)

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()
