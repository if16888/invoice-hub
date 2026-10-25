# -*- coding: utf-8 -*-
"""The workbench summary must inspect every claim's files in one pass.

`_collect_overview_metrics` used to call the per-claim preflight helper, which
inspected its own small batch of files and waited for it before the next claim.
The summary now loads the claim rows once, inspects all material files in a
single parallel pass and reuses the results, so this module pins both the
numbers and the batching.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp

import scripts.invoice_fetch.claim_export as claim_export


class OverviewMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _close(self, window):
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
        self.app.processEvents()

    def _build(self, root: Path) -> tuple[InvoiceReviewApp, int, int]:
        runtime = root / "runtime"
        attachments = runtime / "attachments"
        attachments.mkdir(parents=True, exist_ok=True)
        present = attachments / "present.pdf"
        present.write_bytes(b"%PDF-1.4 synthetic")
        db_path = runtime / "invoices.db"
        with InvoiceDB(db_path) as db:
            ready_invoice = int(db.insert_invoice({
                "invoice_number": "OVERVIEW-READY-1",
                "total_amount": "10.00",
                "seller_name": "Seller Ready",
                "invoice_date": "2026-08-01",
                "attachment_path": str(present),
                "review_status": "approved",
            }))
            broken_invoice = int(db.insert_invoice({
                "invoice_number": "OVERVIEW-BROKEN-1",
                "total_amount": "20.00",
                "seller_name": "Seller Broken",
                "invoice_date": "2026-08-02",
                "attachment_path": str(attachments / "gone.pdf"),
                "review_status": "approved",
            }))
            ready_claim = db.create_claim_group("Ready claim")
            broken_claim = db.create_claim_group("Broken claim")
            db.add_invoice_to_claim(ready_claim, ready_invoice)
            db.add_invoice_to_claim(broken_claim, broken_invoice)
        window = InvoiceReviewApp(db_path, splash=None)
        window._deferred_init()
        self.app.processEvents()
        return window, ready_claim, broken_claim

    def test_export_ready_counts_only_claims_whose_materials_are_usable(self):
        with tempfile.TemporaryDirectory() as td:
            window, _ready, _broken = self._build(Path(td))
            try:
                metrics = window._collect_overview_metrics()
                self.assertIsNotNone(metrics)
                self.assertEqual(metrics["total"], 2)
                # Both claims hold one approved invoice with a non-empty path,
                # so a field-only check would report 2 ready claims.  The
                # missing file must make the second claim unusable.
                self.assertEqual(metrics["export_ready"], 1, "缺少原件的报销组不能算可导出")
            finally:
                self._close(window)

    def test_summary_inspects_all_material_files_in_one_parallel_pass(self):
        with tempfile.TemporaryDirectory() as td:
            window, _ready, _broken = self._build(Path(td))
            try:
                calls = []
                original = claim_export.inspect_materials_for_invoices

                def recorded(invoices, runtime_dir):
                    rows = list(invoices)
                    calls.append([int(row.get("id")) for row in rows])
                    return original(rows, runtime_dir)

                with patch.object(
                    claim_export, "inspect_materials_for_invoices", side_effect=recorded
                ):
                    window._collect_overview_metrics()

                self.assertEqual(len(calls), 1, "整页预检应只调用一次批量检查")
                self.assertEqual(len(calls[0]), 2)
            finally:
                self._close(window)

    def test_precomputed_stats_match_a_fresh_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            window, ready_claim, broken_claim = self._build(Path(td))
            try:
                for claim_id in (ready_claim, broken_claim):
                    rows = window.db.get_claim_invoices(claim_id)
                    inspected = claim_export.inspect_materials_for_invoices(rows, Path(td))
                    materials = {
                        int(row.get("id")): result
                        for row, result in zip(rows, inspected)
                    }
                    reused = window._claim_export_preflight_stats_for_range(
                        claim_id,
                        include_to_review=False,
                        invoices=rows,
                        materials_by_id=materials,
                    )
                    fresh = window._claim_export_preflight_stats_for_range(
                        claim_id,
                        include_to_review=False,
                    )
                    self.assertEqual(reused, fresh)
            finally:
                self._close(window)


if __name__ == "__main__":
    unittest.main()
