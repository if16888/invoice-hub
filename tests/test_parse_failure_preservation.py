"""An unparsed invoice PDF must stay visible in review instead of disappearing.

Regression guard for the email path: a scanned invoice, a broken font map or a
parser timeout used to end with a log line and the temporary attachment was
then deleted, so the user never saw the invoice again.
"""

import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock

from scripts.invoice_fetch.attachment_handler import Attachment
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.invoice_parser import InvoiceInfo, InvoiceParser
from scripts.invoice_fetch.mail_fetcher import MailMessage
from scripts.invoice_fetch.services import _process_email


class FailingParser(InvoiceParser):
    """Parser stand-in that always reports the scanned-invoice failure."""

    def __init__(self, note: str = "无法提取文本(可能为扫描件)"):
        super().__init__()
        self._note = note

    def parse_pdf(self, file_path, *args, **kwargs):  # noqa: D102 - test double
        return InvoiceInfo(parse_success=False, parse_note=self._note)


def _mail_message() -> MailMessage:
    message = EmailMessage()
    message["Subject"] = "电子发票"
    message["From"] = "sender@example.test"
    message.set_content("请查收发票")
    return MailMessage(uid=7, raw_msg=message)


class ParseFailurePreservationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = InvoiceDB(self.root / "invoices.db")
        self.att_dir = self.root / "attachments"
        self.att_dir.mkdir()
        self.pdf = self.att_dir / "scan.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n% synthetic scanned invoice\n")

        self.handler = MagicMock()
        self.handler._base = self.att_dir
        self.handler.extract.return_value = [
            Attachment(
                str(self.pdf),
                self.pdf.name,
                "application/pdf",
                self.pdf.stat().st_size,
                True,
            )
        ]
        self.downloader = MagicMock()
        self.downloader._skip_when_attachment_invoice_present = True
        self.downloader.download_from_email.return_value = []

    def tearDown(self):
        try:
            self.db.close()
        finally:
            self._tmp.cleanup()

    def _process(self) -> int:
        return _process_email(
            _mail_message(),
            self.handler,
            FailingParser(),
            self.downloader,
            self.db,
            {},
        )

    def test_unparsed_pdf_is_kept_and_reviewable(self):
        recorded = self._process()

        self.assertEqual(recorded, 1)
        rows = self.db.get_all_invoices()
        self.assertEqual(len(rows), 1, "解析失败的 PDF 必须产生一条可审核记录")

        row = rows[0]
        self.assertEqual(row["invoice_type"], "PDF待人工处理")
        self.assertFalse(int(row.get("parse_success") or 0))
        self.assertIn("parse_failed", row.get("parse_note") or "")
        self.assertTrue(str(row.get("attachment_path") or ""), "记录必须指向保留的原件")

        self.assertTrue(self.pdf.exists(), "原始 PDF 不能被未使用附件清理逻辑删除")

    def test_record_is_review_status_to_review(self):
        self._process()
        rows = self.db.get_all_invoices()
        self.assertEqual(rows[0].get("review_status"), "to_review")

    def test_same_failed_pdf_is_not_duplicated_on_reprocess(self):
        self._process()
        self._process()

        rows = self.db.get_all_invoices()
        self.assertEqual(len(rows), 1, "同一份文件重新处理不应重复入库")
        self.assertTrue(self.pdf.exists())

    def test_original_survives_even_when_the_record_cannot_be_created(self):
        # A failing insert must not silently delete the user's original.
        original_insert = self.db.insert_invoice

        def _broken_insert(record):  # noqa: ANN001 - test double
            return 0

        self.db.insert_invoice = _broken_insert
        try:
            self._process()
        finally:
            self.db.insert_invoice = original_insert

        self.assertEqual(len(self.db.get_all_invoices()), 0)
        self.assertTrue(self.pdf.exists(), "无法入库时也必须保留原件")


if __name__ == "__main__":
    unittest.main()
