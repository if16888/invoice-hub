"""Integration contracts for performance markers on the existing GUI paths."""

from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.review_status import TO_REVIEW


class PerformanceInstrumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "performance.db"
        with InvoiceDB(db_path):
            pass
        window = InvoiceReviewApp(db_path)
        window.show()
        self.app.processEvents()
        self.addCleanup(window.close)
        return window

    def test_list_refresh_records_required_existing_stages(self):
        window = self._make_window()
        messages = []
        window._performance_probe.enabled = True
        window._performance_probe.set_sink(messages.append)
        window._load_invoices()

        record = next(record for record in reversed(window._performance_probe.records) if record["event"] == "list_refresh")
        stages = record["stages"]
        for stage in (
            "db_query", "scope_filter", "model_transform", "table_clear",
            "row_allocation", "item_population", "sorting", "selection_restore",
            "preview_trigger", "layout_schedule",
        ):
            self.assertIn(stage, stages)
        self.assertTrue(any("[性能][列表刷新]" in line for line in messages))

    def test_page_switch_is_observed_without_changing_page_contract(self):
        window = self._make_window()
        window._performance_probe.enabled = True
        window._performance_probe.set_sink(lambda _line: None)
        window._switch_main_page("imports")
        self.app.processEvents()

        record = next(record for record in reversed(window._performance_probe.records) if record["event"] == "page_switch")
        self.assertEqual(record["page"], "imports")
        self.assertIn("page_state_update", record["stages"])
        self.assertEqual(window.center_stack.currentWidget(), window.imports_page)

    def test_completion_handlers_keep_t1_to_t4_trace_contract(self):
        for method_name in ("_mobile_upload_finished", "_scan_email_finished", "_import_local_finished"):
            source = inspect.getsource(getattr(InvoiceReviewApp, method_name))
            self.assertIn("T1_gui_signal", source)
            self.assertIn("T2_state_update", source)
            self.assertIn("T3_db_list_refresh_complete", source)
            self.assertIn("_performance_request_completion_paint", source)

    def test_completion_call_observer_records_ordinal_and_visibility(self):
        window = self._make_window()
        window._performance_probe.enabled = True
        window._performance_probe.set_sink(lambda _line: None)
        trace = window._performance_probe.begin("upload_complete")
        window._performance_active_completion_trace = trace
        calls = []

        window._performance_completion_call(
            trace,
            "load_invoices",
            lambda: calls.append("first"),
            surface="review",
        )
        window._performance_completion_call(
            trace,
            "load_invoices",
            lambda: calls.append("second"),
            surface="review",
        )
        window._performance_completion_call(
            trace,
            "refresh_settings",
            lambda: calls.append("settings"),
            surface="settings",
        )
        record = trace.finish("T6_interactive", surface="review")

        self.assertEqual(calls, ["first", "second", "settings"])
        self.assertEqual(record["load_invoices_count"], 2)
        self.assertEqual(record["refresh_settings_count"], 1)
        self.assertIn("load_invoices_1_ms", record)
        self.assertIn("load_invoices_2_ms", record)
        self.assertTrue(record["load_invoices_1_visible"])
        self.assertTrue(record["load_invoices_2_visible"])
        self.assertFalse(record["refresh_settings_1_visible"])

    def test_mobile_completion_loads_authoritative_scope_once_and_defers_hidden_pages(self):
        window = self._make_window()
        first_id = window.db.insert_invoice({
            "invoice_number": "PHASE2B-001",
            "total_amount": "10.00",
            "seller_name": "Synthetic",
            "invoice_date": "2026-08-25",
            "review_status": TO_REVIEW,
        })
        second_id = window.db.insert_invoice({
            "invoice_number": "PHASE2B-002",
            "total_amount": "20.00",
            "seller_name": "Synthetic",
            "invoice_date": "2026-08-25",
            "review_status": TO_REVIEW,
        })
        window._switch_main_page("imports")
        with (
            patch.object(window, "_load_invoices", wraps=window._load_invoices) as load_invoices,
            patch.object(window, "_refresh_overview_page", wraps=window._refresh_overview_page) as refresh_overview,
            patch.object(window, "_refresh_imports_page", wraps=window._refresh_imports_page) as refresh_imports,
            patch.object(window, "_refresh_settings_page", wraps=window._refresh_settings_page) as refresh_settings,
        ):
            window._mobile_upload_finished({
                "batch_id": "phase2b-a",
                "received": 2,
                "created": 1,
                "upload_duplicate": 1,
                "duplicate_outcomes": [{}],
                "new_invoice_ids": (first_id,),
                "review_invoice_ids": (first_id,),
            })
            self.assertEqual(load_invoices.call_count, 1)
            self.assertEqual(
                {int(row["id"]) for row in window.invoices_list},
                {first_id},
            )
            self.assertEqual(window._review_scope_ids, (first_id,))
            self.assertEqual(refresh_overview.call_count, 0)
            self.assertEqual(refresh_imports.call_count, 0)
            self.assertEqual(refresh_settings.call_count, 0)
            self.assertTrue(window.overview_dirty)
            self.assertTrue(window.imports_dirty)
            self.assertTrue(window.settings_dirty)

            window._switch_main_page("overview")
            self.assertEqual(refresh_overview.call_count, 1)
            self.assertFalse(window.overview_dirty)
            window._switch_main_page("imports")
            self.assertEqual(refresh_imports.call_count, 1)
            self.assertFalse(window.imports_dirty)
            window._switch_main_page("settings")
            self.assertEqual(refresh_settings.call_count, 1)
            self.assertFalse(window.settings_dirty)

            load_invoices.reset_mock()
            window._mobile_upload_finished({
                "batch_id": "phase2b-b",
                "received": 1,
                "created": 1,
                "new_invoice_ids": (second_id,),
                "review_invoice_ids": (second_id,),
            })
            self.assertEqual(load_invoices.call_count, 1)
            self.assertEqual(window._review_scope_ids, (second_id,))
            self.assertEqual(
                {int(row["id"]) for row in window.invoices_list},
                {second_id},
            )

    def test_local_completion_updates_list_before_completion_dialog(self):
        window = self._make_window()
        new_id = window.db.insert_invoice({
            "invoice_number": "PHASE2B-LOCAL",
            "total_amount": "30.00",
            "seller_name": "Synthetic",
            "invoice_date": "2026-08-25",
            "review_status": TO_REVIEW,
        })
        dialog_observations = []

        def observe_dialog(parent, _title, _message):
            dialog_observations.append({int(row["id"]) for row in parent.invoices_list})

        with patch("scripts.invoice_fetch.gui.app.QMessageBox.information", side_effect=observe_dialog):
            window._import_local_finished({
                "added": 1,
                "duplicates": 0,
                "conflicts": 0,
                "pending_manual": 0,
                "failed": 0,
                "new_invoice_ids": (new_id,),
                "review_invoice_ids": (new_id,),
            })

        self.assertEqual(len(dialog_observations), 1)
        self.assertIn(new_id, dialog_observations[0])

    def test_performance_log_sink_does_not_copy_sensitive_fields(self):
        window = self._make_window()
        messages = []
        window._performance_probe.enabled = True
        window._performance_probe.set_sink(messages.append)
        window._performance_probe.mark_event(
            "preview",
            "load",
            path=r"C:\Users\real-user\invoice-001.pdf",
            invoice_number="INV-001",
            seller="Real Seller",
            rows=1,
        )
        self.assertEqual(len(messages), 1)
        self.assertNotIn("real-user", messages[0])
        self.assertNotIn("invoice-001", messages[0])
        self.assertNotIn("INV-001", messages[0])
        self.assertNotIn("Real Seller", messages[0])
        self.assertIn("rows=1", messages[0])


if __name__ == "__main__":
    unittest.main()
