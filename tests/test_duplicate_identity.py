"""Behaviour tests for duplicate identity in the e-mail parse flow.

The duplicate identity of a parsed invoice must not degrade to
``invoice_number + total_amount`` when the seller contradicts the parsed
seller: two different issuers can reuse the same 8/12-digit legacy number, so
merging them silently loses a real invoice (and its attachment).

Every fixture here is synthetic; no real invoice data is used.
"""

import email
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch import services
from scripts.invoice_fetch.attachment_handler import Attachment
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.invoice_parser import InvoiceInfo


class _StaticAttachmentHandler:
    def __init__(self, base, attachments):
        self._base = Path(base)
        self._attachments = attachments

    def extract(self, *args, **kwargs):
        return self._attachments


class _StaticParser:
    def __init__(self, info):
        self._info = info

    def parse_pdf(self, path):
        return self._info


class _NoopLinkDownloader:
    def download_from_email(self, *args, **kwargs):
        return []


def _mail(uid: int, subject: str = "synthetic invoice mail") -> services.MailMessage:
    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "billing@example.com"
    msg["Date"] = "Mon, 18 May 2026 10:00:00 +0800"
    return services.MailMessage(uid=uid, raw_msg=msg)


def _parsed(
    invoice_number: str,
    total_amount: str,
    seller_name: str,
    *,
    invoice_code: str = "",
) -> InvoiceInfo:
    return InvoiceInfo(
        parse_success=True,
        invoice_number=invoice_number,
        invoice_code=invoice_code,
        invoice_date="2026-05-18",
        amount="",
        total_amount=total_amount,
        seller_name=seller_name,
        buyer_name="Synthetic Buyer",
        invoice_type="电子发票",
        parse_note="synthetic parse",
    )


class _SyntheticMailFlowCase(unittest.TestCase):
    """Temp runtime + DB with the real ``_process_email`` entry point."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.base = Path(self._temp.name)
        self.runtime = self.base / "runtime"
        self.att_dir = self.runtime / "attachments"
        self.att_dir.mkdir(parents=True)
        self.incoming = self.base / "incoming"
        self.incoming.mkdir()

        self.db = InvoiceDB(self.runtime / "invoices.db")
        self.addCleanup(self.db.close)

        self._runtime_patch = patch.object(services, "RUNTIME_DIR", self.runtime)
        self._runtime_patch.start()
        self.addCleanup(self._runtime_patch.stop)

    def _attachment(self, name: str, payload: bytes) -> Attachment:
        path = self.incoming / name
        path.write_bytes(payload)
        return Attachment(
            file_path=str(path),
            original_name=name,
            content_type="application/pdf",
            size=len(payload),
            is_invoice=True,
            is_extra=False,
        )

    def _process(
        self,
        uid: int,
        attachment: Attachment,
        info: InvoiceInfo,
        *,
        subject: str = "synthetic invoice mail",
    ) -> int:
        return services._process_email(
            _mail(uid, subject),
            _StaticAttachmentHandler(self.att_dir, [attachment]),
            _StaticParser(info),
            _NoopLinkDownloader(),
            self.db,
            {},
        )


class DuplicateIdentityMailFlowTests(_SyntheticMailFlowCase):
    def test_same_number_and_amount_with_different_seller_keeps_both_invoices(self):
        """(a) Same number+amount but a different seller => two rows, both originals."""
        first = self._attachment("mail-a.pdf", b"%PDF synthetic invoice A")
        self.assertEqual(
            self._process(
                501,
                first,
                _parsed("LEGACY-0001", "100.00", "Synthetic Seller A", invoice_code="031002500111"),
            ),
            1,
        )

        second = self._attachment("mail-b.pdf", b"%PDF synthetic invoice B")
        self.assertEqual(
            self._process(
                502,
                second,
                _parsed("LEGACY-0001", "100.00", "Synthetic Seller B", invoice_code="031009900222"),
            ),
            1,
        )

        rows = self.db.get_all_invoices()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["seller_name"] for row in rows},
            {"Synthetic Seller A", "Synthetic Seller B"},
        )
        self.assertEqual({row["invoice_number"] for row in rows}, {"LEGACY-0001"})
        stored_paths = [row["attachment_path"] for row in rows]
        self.assertTrue(all(stored_paths), "both invoices must keep an original")
        for relative_path in stored_paths:
            self.assertTrue(
                (self.runtime / relative_path).exists(),
                f"attachment was lost: {relative_path}",
            )

    def test_exact_identity_is_still_deduplicated(self):
        """(b) Same number+amount+seller is still one invoice."""
        info = _parsed("LEGACY-0002", "88.00", "Synthetic Seller", invoice_code="031002500111")
        self.assertEqual(
            self._process(511, self._attachment("dup-a.pdf", b"%PDF first"), info), 1
        )
        self.assertEqual(
            self._process(512, self._attachment("dup-b.pdf", b"%PDF second"), info), 1
        )

        rows = self.db.get_all_invoices()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["invoice_number"], "LEGACY-0002")
        self.assertEqual(rows[0]["seller_name"], "Synthetic Seller")

    def test_soft_deleted_genuine_duplicate_is_restored_not_duplicated(self):
        """(c) A genuine duplicate that was soft-deleted is restored in place."""
        existing_id = self.db.insert_invoice(
            {
                "invoice_number": "LEGACY-0003",
                "invoice_code": "031002500111",
                "invoice_date": "2026-05-18",
                "total_amount": "66.00",
                "seller_name": "Synthetic Seller",
                "attachment_path": "",
            }
        )
        self.assertIsNotNone(existing_id)
        self.assertTrue(self.db.soft_delete_invoice(existing_id))

        with self.assertLogs("invoice_fetch", level="INFO") as logs:
            recorded = self._process(
                521,
                self._attachment("restore.pdf", b"%PDF restore"),
                _parsed("LEGACY-0003", "66.00", "Synthetic Seller", invoice_code="031002500111"),
            )

        rows = self.db.get_all_invoices()
        self.assertEqual(recorded, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], existing_id)
        self.assertEqual(rows[0]["is_deleted"], 0)
        self.assertIn("已恢复已删除的重复发票", "\n".join(logs.output))

    def test_code_and_number_identity_is_preferred_over_seller_drift(self):
        """invoice_code+invoice_number wins over a re-parsed seller and amount."""
        existing_id = self.db.insert_invoice(
            {
                "invoice_number": "LEGACY-0004",
                "invoice_code": "031002500111",
                "invoice_date": "2026-05-18",
                "total_amount": "120.00",
                "seller_name": "Synthetic Seller (北京)",
                "attachment_path": "",
            }
        )
        self.assertIsNotNone(existing_id)

        recorded = self._process(
            531,
            self._attachment("code-match.pdf", b"%PDF code match"),
            _parsed(
                "LEGACY-0004",
                "120.00",
                "Synthetic Seller（北京）",
                invoice_code="031002500111",
            ),
        )

        rows = self.db.get_all_invoices()
        self.assertEqual(recorded, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], existing_id)


class DuplicateIdentityLookupTests(_SyntheticMailFlowCase):
    def test_number_and_amount_with_different_seller_returns_none(self):
        self.db.insert_invoice(
            {
                "invoice_number": "LOOKUP-0001",
                "invoice_code": "031002500111",
                "invoice_date": "2026-05-18",
                "total_amount": "100.00",
                "seller_name": "Synthetic Seller A",
                "attachment_path": "",
            }
        )

        found = services._find_existing_invoice_for_parse(
            self.db, "LOOKUP-0001", "100.00", "Synthetic Seller B"
        )

        self.assertIsNone(found)

    def test_exact_identity_returns_existing_row(self):
        row_id = self.db.insert_invoice(
            {
                "invoice_number": "LOOKUP-0002",
                "invoice_code": "031002500111",
                "invoice_date": "2026-05-18",
                "total_amount": "100.00",
                "seller_name": "Synthetic Seller",
                "attachment_path": "",
            }
        )

        found = services._find_existing_invoice_for_parse(
            self.db, "LOOKUP-0002", "100.00", "Synthetic Seller"
        )

        self.assertIsNotNone(found)
        self.assertEqual(found["id"], row_id)

    def test_soft_deleted_exact_identity_is_returned_for_restore(self):
        row_id = self.db.insert_invoice(
            {
                "invoice_number": "LOOKUP-0003",
                "invoice_code": "031002500111",
                "invoice_date": "2026-05-18",
                "total_amount": "100.00",
                "seller_name": "Synthetic Seller",
                "attachment_path": "",
            }
        )
        self.assertTrue(self.db.soft_delete_invoice(row_id))

        found = services._find_existing_invoice_for_parse(
            self.db, "LOOKUP-0003", "100.00", "Synthetic Seller"
        )

        self.assertIsNotNone(found)
        self.assertEqual(found["id"], row_id)
        self.assertEqual(found["is_deleted"], 1)

    def test_records_without_invoice_number_never_match(self):
        self.db.insert_invoice(
            {
                "invoice_number": "",
                "invoice_date": "2026-05-18",
                "total_amount": "100.00",
                "seller_name": "Synthetic Seller",
                "attachment_path": "",
            }
        )

        found = services._find_existing_invoice_for_parse(
            self.db, "", "100.00", "Synthetic Seller"
        )

        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
