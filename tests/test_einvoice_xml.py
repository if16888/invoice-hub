import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock

from scripts.invoice_fetch.attachment_handler import Attachment, _payload_matches_extension
from scripts.invoice_fetch.invoice_parser import InvoiceParser
from scripts.invoice_fetch.mail_fetcher import MailMessage


XML = b'''<EInvoice><EInvoiceData><SellerInformation><SellerName>Seller</SellerName></SellerInformation><BuyerInformation><BuyerName>Buyer</BuyerName></BuyerInformation><BasicInformation><TotalAmWithoutTax>100.00</TotalAmWithoutTax><TotalTax-includedAmount>106.00</TotalTax-includedAmount></BasicInformation></EInvoiceData><TaxSupervisionInfo><InvoiceNumber>26322000000000000001</InvoiceNumber><IssueTime>2026-09-21T18:38:04</IssueTime></TaxSupervisionInfo></EInvoice>'''


class EInvoiceXmlTests(unittest.TestCase):
    def test_single_xml_zip_extracts_fields(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "invoice.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("nested/dzfp.xml", XML)
            result = InvoiceParser().parse_pdf(str(path))
            self.assertTrue(result.parse_success)
            self.assertEqual(result.total_amount, "106.00")
            self.assertEqual(result.invoice_date, "2026-09-21")
            self.assertEqual(result.seller_name, "Seller")
            self.assertTrue(_payload_matches_extension(XML, ".xml"))

    def test_multiple_xml_not_silently_selected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "multiple.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("one.xml", XML)
                archive.writestr("two.xml", XML)
            self.assertFalse(InvoiceParser().parse_pdf(str(path)).parse_success)

    def test_entity_document_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            data = b'<!DOCTYPE EInvoice [<!ENTITY x "expanded">]>' + XML
            path = Path(td) / "unsafe.xml"
            path.write_bytes(data)
            self.assertFalse(_payload_matches_extension(data, ".xml"))
            self.assertFalse(InvoiceParser().parse_pdf(str(path)).parse_success)

    def test_pdf_upgrades_xml_original_without_downgrading_pdf(self):
        from scripts.invoice_fetch.services import _needs_original_replacement

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive_path = root / "original.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("invoice.xml", XML)
            pdf_path = root / "ticket.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            self.assertTrue(_needs_original_replacement(str(archive_path), str(pdf_path)))
            self.assertFalse(_needs_original_replacement(str(pdf_path), str(archive_path)))
            self.assertFalse(_needs_original_replacement(str(pdf_path), str(pdf_path)))
            other_zip = root / "other.zip"
            with zipfile.ZipFile(other_zip, "w") as archive:
                archive.writestr("other.txt", b"other")
            self.assertFalse(_needs_original_replacement(str(other_zip), str(pdf_path)))

    def test_parsed_xml_does_not_skip_email_ticket_download(self):
        from scripts.invoice_fetch.services import _process_email

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "invoice.xml"
            path.write_bytes(XML)
            message = EmailMessage()
            message["Subject"] = "电子发票"
            message["From"] = "sender@example.test"
            message.set_content("invoice")
            handler = MagicMock()
            handler.extract.return_value = [
                Attachment(str(path), path.name, "application/xml", len(XML), True)
            ]
            downloader = MagicMock()
            downloader._skip_when_attachment_invoice_present = True
            downloader.download_from_email.side_effect = RuntimeError("download reached")
            with self.assertRaisesRegex(RuntimeError, "download reached"):
                _process_email(
                    MailMessage(uid=1, raw_msg=message),
                    handler,
                    InvoiceParser(),
                    downloader,
                    MagicMock(),
                    {},
                )
            downloader.download_from_email.assert_called_once()


if __name__ == "__main__":
    unittest.main()
