import zipfile
from scripts.invoice_fetch.invoice_parser import InvoiceParser
from scripts.invoice_fetch.attachment_handler import _payload_matches_extension


XML = b'''<EInvoice><EInvoiceData><SellerInformation><SellerName>Seller</SellerName></SellerInformation><BuyerInformation><BuyerName>Buyer</BuyerName></BuyerInformation><BasicInformation><TotalAmWithoutTax>100.00</TotalAmWithoutTax><TotalTax-includedAmount>106.00</TotalTax-includedAmount></BasicInformation></EInvoiceData><TaxSupervisionInfo><InvoiceNumber>26322000000000000001</InvoiceNumber><IssueTime>2026-09-21T18:38:04</IssueTime></TaxSupervisionInfo></EInvoice>'''


def test_single_xml_zip_extracts_fields(tmp_path):
    path = tmp_path / 'invoice.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('nested/dzfp.xml', XML)
    result = InvoiceParser().parse_pdf(str(path))
    assert result.parse_success
    assert result.total_amount == '106.00'
    assert result.invoice_date == '2026-09-21'
    assert result.seller_name == 'Seller'
    assert _payload_matches_extension(XML, '.xml')


def test_multiple_xml_not_silently_selected(tmp_path):
    path = tmp_path / 'multiple.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('one.xml', XML)
        archive.writestr('two.xml', XML)
    assert not InvoiceParser().parse_pdf(str(path)).parse_success


def test_entity_document_rejected(tmp_path):
    data = b'<!DOCTYPE EInvoice [<!ENTITY x "expanded">]>' + XML
    path = tmp_path / 'unsafe.xml'
    path.write_bytes(data)
    assert not _payload_matches_extension(data, '.xml')
    assert not InvoiceParser().parse_pdf(str(path)).parse_success


def test_pdf_upgrades_xml_original_without_downgrading_pdf(tmp_path):
    from scripts.invoice_fetch.services import _needs_original_replacement
    archive_path = tmp_path / 'original.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('invoice.xml', XML)
    pdf_path = tmp_path / 'ticket.pdf'
    pdf_path.write_bytes(b'%PDF-1.4')
    assert _needs_original_replacement(str(archive_path), str(pdf_path))
    assert not _needs_original_replacement(str(pdf_path), str(archive_path))
    assert not _needs_original_replacement(str(pdf_path), str(pdf_path))
    other_zip = tmp_path / 'other.zip'
    with zipfile.ZipFile(other_zip, 'w') as archive:
        archive.writestr('other.txt', b'other')
    assert not _needs_original_replacement(str(other_zip), str(pdf_path))


def test_parsed_xml_does_not_skip_email_ticket_download(tmp_path):
    from unittest.mock import MagicMock
    from email.message import EmailMessage
    import pytest
    from scripts.invoice_fetch.attachment_handler import Attachment
    from scripts.invoice_fetch.mail_fetcher import MailMessage
    from scripts.invoice_fetch.services import _process_email

    path = tmp_path / 'invoice.xml'
    path.write_bytes(XML)
    message = EmailMessage()
    message['Subject'] = '电子发票'
    message['From'] = 'sender@example.test'
    message.set_content('invoice')
    handler = MagicMock()
    handler.extract.return_value = [Attachment(str(path), path.name, 'application/xml', len(XML), True)]
    downloader = MagicMock()
    downloader._skip_when_attachment_invoice_present = True
    downloader.download_from_email.side_effect = RuntimeError('download reached')
    with pytest.raises(RuntimeError, match='download reached'):
        _process_email(MailMessage(uid=1, raw_msg=message), handler, InvoiceParser(),
                       downloader, MagicMock(), {})
    downloader.download_from_email.assert_called_once()
