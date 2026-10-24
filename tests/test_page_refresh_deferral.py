# -*- coding: utf-8 -*-
"""Hidden workbench/export pages must not be recomputed on every review action.

Both pages scan the invoice table and open attachment files.  The workbench is
refreshed after every approve/ignore, so when it is hidden the UI thread paid
for a full scan nobody could see.  These tests pin the invalidation contract:
first build eager, visible page eager, hidden page deferred until shown.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class PageRefreshDeferralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _flush(self):
        self.app.processEvents()
        self.app.processEvents()

    def _build_window(self, db_path: Path):
        window = InvoiceReviewApp(db_path, splash=None)
        window._deferred_init()
        self._flush()
        return window

    def _close_window(self, window):
        try:
            window.close()
        except Exception:
            pass
        try:
            db = getattr(window, "db", None)
            if db is not None and getattr(db, "is_open", False):
                db.close()
        except Exception:
            pass
        self._flush()

    def _seed(self, db_path: Path, claim_name: str = "Claim A") -> int:
        with InvoiceDB(db_path) as db:
            invoice_id = db.insert_invoice(
                {
                    "invoice_number": "DEFER-001",
                    "total_amount": "10.00",
                    "seller_name": "Seller A",
                    "invoice_date": "2026-08-01",
                    "review_status": "approved",
                }
            )
            claim_id = db.create_claim_group(claim_name)
            db.add_invoice_to_claim(claim_id, invoice_id)
        return claim_id

    def test_hidden_workbench_refresh_is_deferred_until_shown(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "deferral.db"
            self._seed(db_path)
            window = self._build_window(db_path)
            try:
                # Visiting the page once is what turns deferral on for it.
                window._switch_main_page("overview")
                self._flush()

                calls = []
                original = window._collect_overview_metrics
                window._collect_overview_metrics = lambda: (calls.append(1), original())[1]

                window._switch_main_page("review")
                self._flush()
                window._refresh_overview_page()

                self.assertEqual(calls, [], "隐藏的工作台不应重算指标")
                self.assertTrue(window.overview_dirty)

                window._switch_main_page("overview")
                self._flush()

                self.assertTrue(calls, "切回工作台时必须补算一次")
                self.assertFalse(window.overview_dirty)
            finally:
                self._close_window(window)

    def test_first_build_stays_eager_for_a_never_visited_page(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "deferral-first.db"
            self._seed(db_path)
            window = self._build_window(db_path)
            try:
                self.assertNotIn("export", window._visited_page_keys)
                window._refresh_export_page()

                self.assertGreater(
                    window.export_group_list.count(),
                    0,
                    "从未打开过的页面首刷必须立即计算",
                )
                self.assertFalse(window.export_dirty)
            finally:
                self._close_window(window)

    def test_hidden_export_refresh_is_deferred_until_shown(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "deferral-export.db"
            self._seed(db_path)
            window = self._build_window(db_path)
            try:
                window._switch_main_page("export")
                self._flush()
                visible_count = window.export_group_list.count()

                window._switch_main_page("review")
                self._flush()

                with InvoiceDB(db_path) as db:
                    db.create_claim_group("Claim B")

                window._refresh_export_page()
                self.assertTrue(window.export_dirty)
                self.assertEqual(
                    window.export_group_list.count(),
                    visible_count,
                    "隐藏的导出页不应重算列表",
                )

                window._switch_main_page("export")
                self._flush()
                self.assertFalse(window.export_dirty)
                self.assertEqual(window.export_group_list.count(), visible_count + 1)
            finally:
                self._close_window(window)


if __name__ == "__main__":
    unittest.main()
