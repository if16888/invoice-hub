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

    def test_dtd_and_entities_rejected_independently_of_encoding(self):
        declarations = (
            '<!DOCTYPE EInvoice>',
            '<!DOCTYPE EInvoice [<!ENTITY demo "SYNTHETIC">]>',
            '<!DOCTYPE EInvoice SYSTEM "https://example.invalid/external.dtd">',
            '<!DOCTYPE EInvoice [<!ENTITY demo SYSTEM "file:///synthetic-secret">]>',
            '<!DOCTYPE EInvoice [<!ENTITY % demo SYSTEM "https://example.invalid/entity">%demo;]>',
        )
        for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"):
            for declaration in declarations:
                with self.subTest(encoding=encoding, declaration=declaration), tempfile.TemporaryDirectory() as td:
                    text = f'<?xml version="1.0" encoding="{encoding}"?>' + declaration + XML.decode("utf-8")
                    data = text.encode(encoding)
                    self.assertFalse(_payload_matches_extension(data, ".xml"))
                    path = Path(td) / "unsafe.xml"
                    path.write_bytes(data)
                    self.assertFalse(InvoiceParser().parse_einvoice_xml(str(path)).parse_success)
                    archive_path = Path(td) / "unsafe.zip"
                    with zipfile.ZipFile(archive_path, "w") as archive:
                        archive.writestr("invoice.xml", data)
                    self.assertFalse(InvoiceParser().parse_einvoice_xml(str(archive_path)).parse_success)

    def test_safe_utf16_invoice_still_parses(self):
        data = ('<?xml version="1.0" encoding="utf-16"?>' + XML.decode("utf-8")).encode("utf-16")
        self.assertTrue(_payload_matches_extension(data, ".xml"))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "safe.xml"
            path.write_bytes(data)
            result = InvoiceParser().parse_einvoice_xml(str(path))
            self.assertTrue(result.parse_success)
            self.assertEqual(result.total_amount, "106.00")

    def test_xml_size_limit_and_malformed_input_fail_closed(self):
        from scripts.invoice_fetch.xml_boundary import MAX_XML_BYTES, parse_invoice_xml

        for data in (XML + b" " * MAX_XML_BYTES, b"<EInvoice>"):
            with self.subTest(size=len(data)):
                self.assertFalse(_payload_matches_extension(data, ".xml"))
                with self.assertRaises(ValueError):
                    parse_invoice_xml(data)

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
