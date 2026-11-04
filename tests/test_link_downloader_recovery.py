# -*- coding: utf-8 -*-
"""Link downloader cache and attempt-limit recovery tests."""

import unittest
import tempfile
import shutil
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock


class TestLinkDownloaderCache(unittest.TestCase):
    """Tests for failed URL fingerprint cache."""

    def test_url_fingerprint_deterministic(self):
        """Same URL produces same fingerprint."""
        from scripts.invoice_fetch.link_downloader import LinkDownloader
        url = "https://51fapiao.cn/download?id=12345"
        fp1 = LinkDownloader._url_fingerprint(url)
        fp2 = LinkDownloader._url_fingerprint(url)
        self.assertEqual(fp1, fp2)

    def test_url_fingerprint_different_urls(self):
        """Different URLs produce different fingerprints."""
        from scripts.invoice_fetch.link_downloader import LinkDownloader
        fp1 = LinkDownloader._url_fingerprint("https://a.com/doc1.pdf")
        fp2 = LinkDownloader._url_fingerprint("https://a.com/doc2.pdf")
        self.assertNotEqual(fp1, fp2)

    def test_fingerprint_not_reversible(self):
        """Fingerprint does not contain full URL."""
        from scripts.invoice_fetch.link_downloader import LinkDownloader
        url = "https://51fapiao.cn/download?id=12345&token=secret"
        fp = LinkDownloader._url_fingerprint(url)
        self.assertNotIn("51fapiao", fp)
        self.assertNotIn("token", fp)
        self.assertNotIn("secret", fp)
        self.assertEqual(len(fp), 16)

    def test_failed_url_cached_and_skipped(self):
        """After a URL fails, same fingerprint causes skip on next attempt."""
        from scripts.invoice_fetch.link_downloader import LinkDownloader

        dl = LinkDownloader(download_dir=tempfile.mkdtemp())
        try:
            url = "https://51fapiao.cn/invoice/test123.pdf"
            fp = LinkDownloader._url_fingerprint(url)

            # Simulate failure: add to cache
            dl.failed_url_fingerprints.add(fp)

            # Simulate download_from_email parsing the same URL
            html = f'<html><body><a href="{url}">发票下载</a></body></html>'
            from scripts.invoice_fetch.link_downloader import extract_links_from_html, _dedup_and_prioritize

            raw = extract_links_from_html(html)
            links = _dedup_and_prioritize(raw)

            skipped = 0
            results = []
            for link_url in links:
                lfp = LinkDownloader._url_fingerprint(link_url)
                if lfp in dl.failed_url_fingerprints:
                    skipped += 1
                    continue
                results.append(link_url)

            self.assertEqual(skipped, 1)
            self.assertEqual(len(results), 0)
        finally:
            dl.close()

    def test_skip_when_attachment_invoice_present_config(self):
        """Default config has skip_when_attachment_invoice_present=True."""
        from scripts.invoice_fetch.link_downloader import LinkDownloader
        dl = LinkDownloader(download_dir=tempfile.mkdtemp())
        try:
            self.assertTrue(dl._skip_when_attachment_invoice_present)
            self.assertGreater(dl._max_links_per_email, 0)
        finally:
            dl.close()


# ── 7. Attachment-based skip tests ───────────────────────────────────


class TestLinkDownloaderAttemptLimit(unittest.TestCase):
    def test_attempt_limit_enforced(self):
        from scripts.invoice_fetch.link_downloader import LinkDownloader
        import logging
        import io
        import tempfile

        dl = LinkDownloader(download_dir=tempfile.mkdtemp())
        dl._max_links_per_email = 5

        # Mock _download_url to always fail (return None)
        dl._download_url = MagicMock(return_value=None)

        # Set up a logger interceptor to read summary log
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.INFO)
        logger = logging.getLogger("scripts.invoice_fetch.link_downloader")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        try:
            # Construct a dummy email with 7 links
            class MockMessage:
                def is_multipart(self):
                    return False
                def get_content_type(self):
                    return "text/html"
                def get_payload(self, decode=True):
                    return (
                        "<html><body>"
                        '<a href="https://51fapiao.cn/1">link1</a>'
                        '<a href="https://51fapiao.cn/2">link2</a>'
                        '<a href="https://51fapiao.cn/3">link3</a>'
                        '<a href="https://51fapiao.cn/4">link4</a>'
                        '<a href="https://51fapiao.cn/5">link5</a>'
                        '<a href="https://51fapiao.cn/6">link6</a>'
                        '<a href="https://51fapiao.cn/7">link7</a>'
                        "</body></html>"
                    ).encode("utf-8")
                def get_content_charset(self):
                    return "utf-8"

            msg = MockMessage()
            results = dl.download_from_email(msg, mail_uid=123)

            # Assertions
            self.assertEqual(len(results), 0)
            self.assertEqual(dl._download_url.call_count, 5)

            log_output = log_stream.getvalue()
            self.assertIn("failed=5", log_output)
            self.assertIn("attempted=5", log_output)
        finally:
            logger.removeHandler(handler)
            dl.close()
