import ast
import os
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.invoice_parser import InvoiceInfo
from scripts.invoice_fetch.gui.reparse_worker import (
    InvoiceReparseRequest,
    InvoiceReparseWorker,
    ReparseInvoiceSnapshot,
    run_invoice_reparse,
)


class ReparseAsyncServiceTests(unittest.TestCase):
    def test_request_copies_mutable_category_configuration(self):
        categories = {"meal": {"keywords": ["food"]}}
        request = InvoiceReparseRequest.from_values(
            7,
            ({"id": 3, "attachment_path": "a.pdf", "invoice_type": "电子发票"},),
            Path("db.sqlite"),
            Path("runtime"),
            categories,
        )
        categories["meal"]["keywords"].append("changed")
        self.assertEqual(request.request_id, 7)
        self.assertEqual(request.invoice_snapshots[0].invoice_id, 3)
        self.assertEqual(request.categories["meal"]["keywords"], ["food"])
        with self.assertRaises(TypeError):
            request.categories["new"] = {}

    def test_service_reparses_and_updates_with_worker_owned_database(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime_dir = root / "runtime"
            attachment_dir = runtime_dir / "attachments"
            attachment_dir.mkdir(parents=True)
            pdf_path = attachment_dir / "invoice.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 synthetic")
            db_path = runtime_dir / "invoices.db"

            with InvoiceDB(db_path) as db:
                invoice_id = db.insert_invoice(
                    {
                        "invoice_number": "OLD-001",
                        "total_amount": "1.00",
                        "seller_name": "Old Seller",
                        "attachment_path": "attachments/invoice.pdf",
                        "invoice_type": "电子发票",
                    }
                )

            class FakeParser:
                def parse_pdf(self, _path):
                    return InvoiceInfo(
                        invoice_number="NEW-001",
                        invoice_code="CODE-1",
                        invoice_date="2026-09-06",
                        amount="9.00",
                        total_amount="10.00",
                        seller_name="New Seller",
                        buyer_name="Buyer",
                        invoice_type="电子发票",
                        parse_success=True,
                        parse_note="ok",
                        item_name="Meal",
                        expense_date="2026-09-06",
                        date_source="invoice_date",
                    )

            request = InvoiceReparseRequest.from_values(
                1,
                (
                    ReparseInvoiceSnapshot(
                        invoice_id=invoice_id,
                        attachment_path="attachments/invoice.pdf",
                        invoice_type="电子发票",
                        has_extra=False,
                    ),
                ),
                db_path,
                runtime_dir,
                {},
            )
            with patch(
                "scripts.invoice_fetch.gui.reparse_worker.InvoiceParser",
                return_value=FakeParser(),
            ), patch(
                "scripts.invoice_fetch.gui.reparse_worker._classify",
                return_value=("餐饮", "", False),
            ):
                result = run_invoice_reparse(request)

            self.assertFalse(result["cancelled"])
            self.assertEqual(result["requested_count"], 1)
            self.assertEqual(result["processed_count"], 1)
            self.assertEqual(result["success_count"], 1)
            self.assertEqual(result["missing_files"], ())
            self.assertEqual(result["parse_failed_files"], ())

            with InvoiceDB(db_path) as db:
                updated = db.get_invoice(invoice_id)
                self.assertEqual(updated["invoice_number"], "NEW-001")
                self.assertEqual(updated["total_amount"], "10.00")
                self.assertEqual(updated["seller_name"], "New Seller")
                self.assertEqual(updated["category"], "餐饮")

    def test_service_cancellation_stops_before_next_invoice(self):
        request = InvoiceReparseRequest.from_values(
            2,
            (
                {"id": 1, "attachment_path": "a.pdf"},
                {"id": 2, "attachment_path": "b.pdf"},
            ),
            Path("unused.db"),
            Path("unused-runtime"),
            {},
        )
        with patch(
            "scripts.invoice_fetch.gui.reparse_worker.InvoiceDB"
        ) as db_cls, patch(
            "scripts.invoice_fetch.gui.reparse_worker.InvoiceParser"
        ):
            db_cls.return_value.close.return_value = None
            result = run_invoice_reparse(request, should_cancel=lambda: True)
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["processed_count"], 0)

    def test_qthread_executes_reparse_service_off_calling_thread(self):
        caller_thread = threading.get_ident()
        worker_threads = []
        request = InvoiceReparseRequest.from_values(
            3,
            (),
            Path("unused.db"),
            Path("unused-runtime"),
            {},
        )

        def fake_run(_request, **_kwargs):
            worker_threads.append(threading.get_ident())
            return {
                "requested_count": 0,
                "processed_count": 0,
                "success_count": 0,
                "missing_files": (),
                "duplicate_conflicts": (),
                "parse_failed_files": (),
                "cancelled": False,
            }

        with patch(
            "scripts.invoice_fetch.gui.reparse_worker.run_invoice_reparse",
            side_effect=fake_run,
        ):
            worker = InvoiceReparseWorker(request)
            worker.start()
            self.assertTrue(worker.wait(5000))

        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], caller_thread)


class ReparseGuiBoundaryTests(unittest.TestCase):
    def test_gui_reparse_callback_only_starts_background_worker(self):
        app_path = Path("scripts/invoice_fetch/gui/app.py")
        tree = ast.parse(app_path.read_text(encoding="utf-8"))
        target = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_reparse_selected_invoices"
        )
        calls = {
            node.func.id
            for node in ast.walk(target)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        attributes = {
            node.func.attr
            for node in ast.walk(target)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("InvoiceReparseWorker", calls)
        self.assertNotIn("InvoiceParser", calls)
        self.assertNotIn("parse_pdf", attributes)
        self.assertNotIn("reconcile_reparsed_invoice", calls)
        self.assertNotIn("update_invoice_parsed_metadata", attributes)
        self.assertNotIn("delete_invoice_permanently", attributes)
        self.assertNotIn("soft_delete_invoice", attributes)


if __name__ == "__main__":
    unittest.main()
