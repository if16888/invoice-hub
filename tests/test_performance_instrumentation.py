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
