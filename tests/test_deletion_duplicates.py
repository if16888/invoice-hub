import unittest
import shutil
import tempfile
from pathlib import Path
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.services import _import_local_directory, _sha256_file
from scripts.invoice_fetch.invoice_parser import InvoiceParser, InvoiceInfo

class DummyParser(InvoiceParser):
    def __init__(self, parse_results_map=None):
        super().__init__()
        self.parse_results_map = parse_results_map or {}

    def parse_pdf(self, file_path: str) -> InvoiceInfo:
        name = Path(file_path).name
        if name in self.parse_results_map:
            return self.parse_results_map[name]
        return InvoiceInfo(
            parse_success=False,
            parse_note="Dummy parsing failed"
        )


class TestDeletionAndDuplicates(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_invoices.db"
        self.db = InvoiceDB(self.db_path)
        self.db.__enter__()

    def tearDown(self):
        self.db.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir)

    def test_soft_delete_and_restore(self):
        # Insert a sample invoice
        rec = {
            "invoice_number": "TEST-DEL-101",
            "invoice_code": "CODE101",
            "invoice_date": "2026-05-30",
            "total_amount": "100.00",
            "seller_name": "Test Seller",
            "file_hash": "dummyhash101",
        }
        row_id = self.db.insert_invoice(rec)
        self.assertIsNotNone(row_id)

        # Check in get_all_invoices
        all_invs = self.db.get_all_invoices()
        self.assertEqual(len(all_invs), 1)
        self.assertEqual(all_invs[0]["is_deleted"], 0)

        # Soft delete
        success = self.db.soft_delete_invoice(row_id)
        self.assertTrue(success)

        # Should be excluded by default
        all_invs_after = self.db.get_all_invoices()
        self.assertEqual(len(all_invs_after), 0)

        # Should be included when requested
        all_invs_with_del = self.db.get_all_invoices(include_deleted=True)
        self.assertEqual(len(all_invs_with_del), 1)
        self.assertEqual(all_invs_with_del[0]["is_deleted"], 1)

        # Restore
        restore_success = self.db.restore_invoice(row_id)
        self.assertTrue(restore_success)

        # Check restored
        all_invs_restored = self.db.get_all_invoices()
        self.assertEqual(len(all_invs_restored), 1)
        self.assertEqual(all_invs_restored[0]["is_deleted"], 0)

    def test_duplicate_and_conflict_import(self):
        # Setup source folder
        src_dir = self.temp_dir / "import_src"
        src_dir.mkdir()

        # Create two different dummy PDF files
        pdf1 = src_dir / "invoice1.pdf"
        pdf1.write_bytes(b"%PDF-1.4 dummy pdf content 1")

        pdf2 = src_dir / "invoice2.pdf"
        pdf2.write_bytes(b"%PDF-1.4 dummy pdf content 2")

        pdf_conflict = src_dir / "invoice_conflict.pdf"
        pdf_conflict.write_bytes(b"%PDF-1.4 dummy pdf content conflict")

        # Map dummy parse results
        # invoice1.pdf is a normal invoice
        res1 = InvoiceInfo(
            parse_success=True,
            invoice_number="INV-DUP-1",
            invoice_code="CODE-DUP-1",
            invoice_date="2026-05-30",
            amount="90.00",
            total_amount="100.00",
            seller_name="Seller A",
            buyer_name="Buyer B",
            invoice_type="增值税电子普通发票",
            parse_note="Successfully parsed normal invoice 1"
        )
        # invoice2.pdf is a duplicate of invoice1 by (number, total_amount, seller_name) but different file content
        res2 = InvoiceInfo(
            parse_success=True,
            invoice_number="INV-DUP-1",
            invoice_code="CODE-DUP-1",
            invoice_date="2026-05-30",
            amount="90.00",
            total_amount="100.00",
            seller_name="Seller A",
            buyer_name="Buyer B",
            invoice_type="增值税电子普通发票",
            parse_note="Successfully parsed invoice 2 duplicate"
        )
        # invoice_conflict.pdf has the same invoice_number but different total_amount/seller/date
        res_conflict = InvoiceInfo(
            parse_success=True,
            invoice_number="INV-DUP-1",
            invoice_code="CODE-DUP-1",
            invoice_date="2026-05-31",
            amount="190.00",
            total_amount="200.00",
            seller_name="Seller Conflict",
            buyer_name="Buyer B",
            invoice_type="增值税电子普通发票",
            parse_note="Conflict invoice"
        )

        parse_results = {
            "invoice1.pdf": res1,
            "invoice2.pdf": res2,
            "invoice_conflict.pdf": res_conflict
        }

        parser = DummyParser(parse_results)
        categories = {}
        att_dir = self.temp_dir / "attachments"
        att_dir.mkdir()

        # Create temporary sub-directories to import them sequentially, ensuring DB state updates between imports
        dir1 = self.temp_dir / "dir1"
        dir1.mkdir()
        shutil.move(str(pdf1), str(dir1 / "invoice1.pdf"))
        stats1 = _import_local_directory(dir1, self.db, parser, categories, att_dir)
        self.assertEqual(stats1["added"], 1)

        dir2 = self.temp_dir / "dir2"
        dir2.mkdir()
        shutil.move(str(pdf2), str(dir2 / "invoice2.pdf"))
        stats2 = _import_local_directory(dir2, self.db, parser, categories, att_dir)
        self.assertEqual(stats2["duplicates"], 1)

        dir3 = self.temp_dir / "dir3"
        dir3.mkdir()
        shutil.move(str(pdf_conflict), str(dir3 / "invoice_conflict.pdf"))
        stats3 = _import_local_directory(dir3, self.db, parser, categories, att_dir)
        self.assertEqual(stats3["conflicts"], 1)

        # Check DB records
        all_invs = self.db.get_all_invoices()
        self.assertEqual(len(all_invs), 2)  # Normal added + Conflict added

        # Check conflict invoice fields
        conflict_inv = self.db.find_invoice_by_number_and_amount("INV-DUP-1", "200.00")
        self.assertIsNotNone(conflict_inv)
        self.assertEqual(conflict_inv["review_status"], "error")
        self.assertEqual(conflict_inv["invoice_type"], "本地导入冲突")
        self.assertEqual(conflict_inv["parse_note"], "发票号重复但信息不一致，请人工确认")

if __name__ == "__main__":
    unittest.main()
