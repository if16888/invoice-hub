# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
import os
from pathlib import Path
from email.message import EmailMessage

from scripts.invoice_fetch.link_downloader import (
    extract_links_with_metadata_from_html,
    _dedup_and_prioritize_with_metadata,
    _dedup_and_prioritize,
    _verify_and_clean_file,
    LinkDownloader,
    DownloadedFile
)

class TestLinkDownloader(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_link_priority_routing(self):
        # 1. 构造 HTML，包含高优先级“下载发票”和多个官网/低优先级链接
        # 避免使用 marketing/promo 等在 _EXCLUDE_PATTERNS 中会被过滤的关键词
        html = """
        <html>
            <body>
                <a href="http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=123">下载发票</a>
                <a href="http://www.nuonuo.com/help">官网帮助</a>
                <a href="http://www.nuonuo.com/info">官网信息</a>
                <a href="http://ntf.nuonuo.com/baoxiao">了解诺诺报销</a>
                <a href="http://fp.nuonuo.com/fapiao/show">查看电子发票</a>
            </body>
        </html>
        """
        raw_items = extract_links_with_metadata_from_html(html)
        self.assertEqual(len(raw_items), 5)

        # 2. 校验去重与排序
        high_items, low_items = _dedup_and_prioritize_with_metadata(raw_items, is_nuonuo_sender=True)
        high_urls = [item["url"] for item in high_items]
        low_urls = [item["url"] for item in low_items]

        # http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=123 应该是高优先级且排第一
        self.assertEqual(high_urls[0], "http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=123")
        self.assertIn("http://fp.nuonuo.com/fapiao/show", high_urls)
        self.assertIn("http://www.nuonuo.com/help", low_urls)
        self.assertIn("http://www.nuonuo.com/info", low_urls)
        self.assertIn("http://ntf.nuonuo.com/baoxiao", low_urls)

    def test_link_extraction_includes_receipt_and_meal_keywords(self):
        html = """
        <html>
            <body>
                <a href="https://example.com/receipt/detail?id=1">查看消费凭证</a>
                <a href="https://example.com/order/detail?kind=meal&id=2">订单详情</a>
            </body>
        </html>
        """
        raw_items = extract_links_with_metadata_from_html(html)
        self.assertEqual(
            [item["url"] for item in raw_items],
            [
                "https://example.com/receipt/detail?id=1",
                "https://example.com/order/detail?kind=meal&id=2",
            ],
        )
        high_items, low_items = _dedup_and_prioritize_with_metadata(raw_items, is_nuonuo_sender=False)
        self.assertEqual([item["url"] for item in high_items], [item["url"] for item in raw_items])
        self.assertEqual(low_items, [])

    def test_download_from_email_logs_redacted_summary_when_no_downloads(self):
        msg = EmailMessage()
        msg["Subject"] = "高铁上餐费报销凭证"
        msg["From"] = "finance@example.com"
        msg.set_content(
            """
            <html><body>
                <a href="https://example.com/receipt/detail?id=1&token=secret">查看消费凭证</a>
            </body></html>
            """,
            subtype="html",
        )

        dl = LinkDownloader(download_dir=self.tmp_dir)

        with patch.object(dl, "_download_url", return_value=None), self.assertLogs(
            "scripts.invoice_fetch.link_downloader", level="INFO"
        ) as logs:
            res = dl.download_from_email(msg, 123, "2026-06-07")

        self.assertEqual(res, [])
        log_text = "\n".join(logs.output)
        self.assertIn("found=", log_text)
        self.assertIn("attempted=", log_text)
        self.assertIn("subject=", log_text)
        self.assertIn("sender=", log_text)
        self.assertNotIn("secret", log_text)
        self.assertNotIn("https://example.com/receipt/detail", log_text)

    def test_download_from_email_dedupes_pdf_and_ofd_same_stem(self):
        pdf_file = Path(self.tmp_dir) / "invoice.pdf"
        ofd_file = Path(self.tmp_dir) / "invoice.ofd"
        pdf_file.write_bytes(b"%PDF-1.4 synthetic pdf")
        ofd_file.write_bytes(b"PK\x03\x04 synthetic ofd")

        msg = EmailMessage()
        msg.set_content(
            """
            <html><body>
              <a href="https://example.com/invoice/pdf">下载发票</a>
              <a href="https://example.com/invoice/ofd">下载发票</a>
            </body></html>
            """,
            subtype="html",
        )

        dl = LinkDownloader(self.tmp_dir)

        def fake_download(url, mail_uid, idx, date_str, disable_fallback=False):
            file_path = pdf_file if idx == 0 else ofd_file
            filename = "invoice.pdf" if idx == 0 else "invoice.ofd"
            return DownloadedFile(
                url=url,
                file_path=str(file_path),
                filename=filename,
                size=file_path.stat().st_size,
                is_invoice=True,
                source_type="official_download",
            )

        with patch.object(dl, "_download_url", side_effect=fake_download):
            results = dl.download_from_email(msg, 77, "2026-06-13")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].filename, "invoice.pdf")

    def test_download_from_email_dedupes_homologous_pdf_and_ofd(self):
        from scripts.invoice_fetch.link_downloader import DownloadedFile, _dedupe_downloaded_files

        # 1. invoice_77_0_resp.pdf + invoice_77_1_resp.ofd -> Keep PDF
        f1 = DownloadedFile("url1", "p1", "invoice_77_0_resp.pdf", 100, True, "official_download")
        f2 = DownloadedFile("url2", "p2", "invoice_77_1_resp.ofd", 200, True, "official_download")
        res1 = _dedupe_downloaded_files([f1, f2])
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0].filename, "invoice_77_0_resp.pdf")

        # 2. 狮王府电子发票.pdf + 电子发票.ofd -> Keep PDF
        f3 = DownloadedFile("url3", "p3", "狮王府电子发票.pdf", 100, True, "official_download")
        f4 = DownloadedFile("url4", "p4", "电子发票.ofd", 200, True, "official_download")
        res2 = _dedupe_downloaded_files([f3, f4])
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0].filename, "狮王府电子发票.pdf")

        # 3. invoice_a.pdf + invoice_b.pdf -> Keep both
        f5 = DownloadedFile("url5", "p5", "invoice_a.pdf", 100, True, "official_download")
        f6 = DownloadedFile("url6", "p6", "invoice_b.pdf", 200, True, "official_download")
        res3 = _dedupe_downloaded_files([f5, f6])
        self.assertEqual(len(res3), 2)

        # 4. invoice_a.pdf + invoice_b.pdf + invoice_b.ofd -> Keep invoice_a.pdf & invoice_b.pdf
        f7 = DownloadedFile("url7", "p7", "invoice_b.ofd", 150, True, "official_download")
        res4 = _dedupe_downloaded_files([f5, f6, f7])
        self.assertEqual(len(res4), 2)
        filenames = [f.filename for f in res4]
        self.assertIn("invoice_a.pdf", filenames)
        self.assertIn("invoice_b.pdf", filenames)
        self.assertNotIn("invoice_b.ofd", filenames)

    def test_verify_and_clean_file(self):
        # 1. 测试 PDF (必须大于等于 500 字节)
        pdf_path = Path(self.tmp_dir) / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\ncontent" + b"x" * 1000)
        self.assertTrue(_verify_and_clean_file(pdf_path))

        # 2. 测试 OFD (ZIP format with ofd.xml, 必须大于等于 500 字节)
        ofd_path = Path(self.tmp_dir) / "test.ofd"
        ofd_path.write_bytes(b"PK\x03\x04_content_ofd.xml_end" + b"y" * 1000)
        self.assertTrue(_verify_and_clean_file(ofd_path))

        # 3. 测试无效文件
        bad_path = Path(self.tmp_dir) / "bad.pdf"
        bad_path.write_bytes(b"badcontent" + b"z" * 1000)
        self.assertFalse(_verify_and_clean_file(bad_path))
        self.assertFalse(bad_path.exists()) # 校验是否已被删除

    def test_download_destination_stays_inside_save_directory(self):
        from scripts.invoice_fetch import link_downloader

        save_dir = Path(self.tmp_dir) / "downloads"
        save_dir.mkdir()

        relative_escape = link_downloader._safe_download_destination(
            save_dir,
            r"..\..\config.json",
            "invoice_1_0.pdf",
        )
        absolute_escape = link_downloader._safe_download_destination(
            save_dir,
            r"C:\Windows\Temp\invoice.pdf",
            "invoice_1_1.pdf",
        )

        self.assertEqual(relative_escape.parent, save_dir.resolve())
        self.assertEqual(relative_escape.name, "config.json")
        self.assertEqual(absolute_escape.parent, save_dir.resolve())
        self.assertEqual(absolute_escape.name, "invoice.pdf")

    def test_browser_request_guard_blocks_private_redirect_target(self):
        from scripts.invoice_fetch import link_downloader

        blocked_route = MagicMock()
        blocked_route.request.url = "http://127.0.0.1/private-invoice"
        link_downloader._route_browser_request(blocked_route)
        blocked_route.abort.assert_called_once_with("blockedbyclient")
        blocked_route.continue_.assert_not_called()

        shared_address_route = MagicMock()
        shared_address_route.request.url = "http://100.64.0.1/private-invoice"
        link_downloader._route_browser_request(shared_address_route)
        shared_address_route.abort.assert_called_once_with("blockedbyclient")
        shared_address_route.continue_.assert_not_called()

        public_route = MagicMock()
        public_route.request.url = "https://example.com/invoice.pdf"
        with patch.object(
            link_downloader,
            "_host_resolves_to_public_addresses",
            return_value=True,
        ):
            link_downloader._route_browser_request(public_route)
        public_route.continue_.assert_called_once_with()
        public_route.abort.assert_not_called()

        private_dns_route = MagicMock()
        private_dns_route.request.url = "https://invoice.example/private-target"
        with patch.object(
            link_downloader,
            "_host_resolves_to_public_addresses",
            return_value=False,
        ):
            link_downloader._route_browser_request(private_dns_route)
        private_dns_route.abort.assert_called_once_with("blockedbyclient")
        private_dns_route.continue_.assert_not_called()

        browser_internal_route = MagicMock()
        browser_internal_route.request.url = "about:blank"
        link_downloader._route_browser_request(browser_internal_route)
        browser_internal_route.continue_.assert_called_once_with()
        browser_internal_route.abort.assert_not_called()

    @patch("playwright.sync_api.sync_playwright")
    def test_invoice_page_detection_and_processor(self, mock_playwright):
        # 1. 模拟 Playwright page
        mock_page = MagicMock()

        # 统一使用 side_effect 返回字符串，防止 evaluate 返回 Mock 实例
        mock_page.evaluate.side_effect = lambda js, *args: "电子发票\n发票号码: 123456\n开票日期: 2026-06-07\n销售方: 某公司"

        dl = LinkDownloader(download_dir=self.tmp_dir)

        # 2. 模拟匹配
        url = "http://nnfp.jss.com.cn/scan-invoice/invoiceShow"
        save_dir = Path(self.tmp_dir)

        # Mock pdf generation to output a fake pdf (>= 500 bytes)
        def fake_pdf(path):
            Path(path).write_bytes(b"%PDF-1.4\nfallback" + b"p" * 1000)
        mock_page.pdf.side_effect = fake_pdf

        # 3. 拦截测试 (配置 fallback 为 True)
        with patch("scripts.invoice_fetch.config.load_config_safe") as mock_cfg:
            mock_cfg.return_value = {"link_download_allow_invoice_page_pdf_fallback": True}
            res = dl._handle_nuonuo_invoice_page(mock_page, url, save_dir, 123, 0)
            self.assertIsNotNone(res)
            path, source_type, parse_note = res
            self.assertTrue(os.path.exists(path))
            self.assertEqual(source_type, "invoice_page_pdf_fallback")
            self.assertIn("由发票展示页面保存为 PDF", parse_note)

        # 4. 配置 fallback 为 False
        with patch("scripts.invoice_fetch.config.load_config_safe") as mock_cfg:
            mock_cfg.return_value = {"link_download_allow_invoice_page_pdf_fallback": False}
            res = dl._handle_nuonuo_invoice_page(mock_page, url, save_dir, 123, 0)
            self.assertNilOrEmpty(res)

    def assertNilOrEmpty(self, value):
        self.assertTrue(value is None or value == "")

    def test_no_pyqt5_in_gui_app(self):
        app_path = Path("scripts/invoice_fetch/gui/app.py")
        self.assertTrue(app_path.exists())
        content = app_path.read_text(encoding="utf-8")
        self.assertNotIn("PyQt5", content)

    @patch("scripts.invoice_fetch.link_downloader.extract_html_from_message")
    @patch("scripts.invoice_fetch.link_downloader._is_safe_download_url")
    def test_download_from_email_suppresses_fallback_after_official_success(self, mock_safe, mock_extract_html):
        mock_safe.return_value = True
        mock_extract_html.return_value = """
        <html>
            <body>
                <a href="http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=1">Link 1</a>
                <a href="http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=2">Link 2</a>
            </body>
        </html>
        """

        dl = LinkDownloader(download_dir=self.tmp_dir)

        fallback_file = Path(self.tmp_dir) / "fallback.pdf"
        fallback_file.write_bytes(b"%PDF-fallback")

        official_file = Path(self.tmp_dir) / "official.pdf"
        official_file.write_bytes(b"%PDF-official")

        r1 = DownloadedFile(
            url="http://dummy1",
            file_path=str(fallback_file),
            filename="fallback.pdf",
            size=1000,
            is_invoice=True,
            source_type="invoice_page_pdf_fallback",
            parse_note=""
        )
        r2 = DownloadedFile(
            url="http://dummy2",
            file_path=str(official_file),
            filename="official.pdf",
            size=1000,
            is_invoice=True,
            source_type="official_download",
            parse_note=""
        )

        call_args = []
        def side_effect(url, mail_uid, idx, date_str, disable_fallback=False):
            call_args.append((url, disable_fallback))
            if "id=1" in url:
                return r1
            else:
                return r2

        with patch.object(dl, "_download_url", side_effect=side_effect):
            res = dl.download_from_email(MagicMock(), 123, "2026-06-07")

            self.assertEqual(len(res), 1)
            self.assertEqual(res[0].source_type, "official_download")
            self.assertFalse(fallback_file.exists()) # Fallback should be unlinked!
            self.assertTrue(official_file.exists())

    @patch("scripts.invoice_fetch.link_downloader.extract_html_from_message")
    @patch("scripts.invoice_fetch.link_downloader._is_safe_download_url")
    def test_download_from_email_disables_fallback_for_subsequent_links_after_official_success(self, mock_safe, mock_extract_html):
        mock_safe.return_value = True
        mock_extract_html.return_value = """
        <html>
            <body>
                <a href="http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=1">Link 1</a>
                <a href="http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=2">Link 2</a>
            </body>
        </html>
        """

        dl = LinkDownloader(download_dir=self.tmp_dir)

        official_file = Path(self.tmp_dir) / "official.pdf"
        official_file.write_bytes(b"%PDF-official")

        r1 = DownloadedFile(
            url="http://dummy1",
            file_path=str(official_file),
            filename="official.pdf",
            size=1000,
            is_invoice=True,
            source_type="official_download",
            parse_note=""
        )

        call_args = []
        def side_effect(url, mail_uid, idx, date_str, disable_fallback=False):
            call_args.append((url, disable_fallback))
            if "id=1" in url:
                return r1
            else:
                return None

        with patch.object(dl, "_download_url", side_effect=side_effect):
            res = dl.download_from_email(MagicMock(), 123, "2026-06-07")

            self.assertEqual(len(call_args), 2)
            self.assertEqual(call_args[0], ("http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=1", False))
            self.assertEqual(call_args[1], ("http://nnfp.jss.com.cn/scan-invoice/invoiceShow?id=2", True))
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0].source_type, "official_download")

    def test_db_backfill_log_level(self):
        import logging
        from scripts.invoice_fetch.db import InvoiceDB
        db_path = Path(self.tmp_dir) / "test_log.db"
        with InvoiceDB(db_path) as db:
            inv_id = db.insert_invoice({
                "invoice_number": "12345678",
                "total_amount": "100.00",
                "seller_name": "测试公司",
                "invoice_date": "2026-06-01",
                "attachment_path": "",
                "review_status": "to_review",
            })
            with self.assertLogs("scripts.invoice_fetch.db", level=logging.DEBUG) as log_capture:
                db.update_invoice_attachment_path_if_missing(inv_id, "dummy.pdf")

            self.assertTrue(any(record.levelname == "DEBUG" and "已回填附件路径" in record.getMessage() for record in log_capture.records))

    def test_fallback_parse_warning_downgraded_in_main(self):
        import logging
        from scripts.invoice_fetch.invoice_parser import InvoiceInfo
        from scripts.invoice_fetch.__main__ import _process_email
        from scripts.invoice_fetch.attachment_handler import Attachment
        from scripts.invoice_fetch.mail_fetcher import MailMessage
        from email.message import Message

        # Mock dependencies to run _process_email and trigger parse fail for a fallback file
        att_dir = Path(self.tmp_dir) / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)

        att_file = att_dir / "fallback.pdf"
        att_file.write_bytes(b"%PDF-fallback")

        mock_att_handler = MagicMock()
        mock_att_handler._base = att_dir
        mock_att_handler.extract.return_value = [] # no attachments, only links

        mock_parser = MagicMock()
        # Parse fails for any file, returns invalid PDF
        mock_parser.parse_pdf.return_value = InvoiceInfo(parse_success=False, parse_note="invalid pdf")

        mock_link_dl = MagicMock()
        mock_link_dl.download_from_email.return_value = [
            DownloadedFile(
                url="http://dummy1",
                file_path=str(att_file),
                filename="fallback.pdf",
                size=1000,
                is_invoice=True,
                source_type="invoice_page_pdf_fallback",
                parse_note=""
            )
        ]

        raw_msg = Message()
        raw_msg["Subject"] = "Test Fallback Invoice"
        raw_msg["From"] = "sender@example.com"
        raw_msg["Date"] = "Mon, 01 Jun 2026 12:00:00 +0800"
        msg = MailMessage(uid=1002, raw_msg=raw_msg)

        from scripts.invoice_fetch.db import InvoiceDB
        db_path = Path(self.tmp_dir) / "test_main_log.db"
        with InvoiceDB(db_path) as db:
            with self.assertLogs("invoice_fetch", level=logging.INFO) as log_capture:
                with patch('scripts.invoice_fetch.__main__.RUNTIME_DIR', Path(self.tmp_dir)):
                    _process_email(
                        msg=msg,
                        att_handler=mock_att_handler,
                        parser=mock_parser,
                        link_dl=mock_link_dl,
                        db=db,
                        categories={},
                        mailbox_key="test_mailbox"
                    )

            # Assert that there is an INFO log about fallback PDF not parsed, and NO WARNING log about invalid PDF
            info_msgs = [record.getMessage() for record in log_capture.records if record.levelname == "INFO"]
            warning_msgs = [record.getMessage() for record in log_capture.records if record.levelname == "WARNING"]

            self.assertTrue(any("发票展示页面 PDF 副本未参与结构化解析" in m for m in info_msgs))
            self.assertFalse(any("下载的 PDF 解析失败" in m for m in warning_msgs))

if __name__ == "__main__":
    unittest.main()
