# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
import os
from pathlib import Path

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

if __name__ == "__main__":
    unittest.main()
