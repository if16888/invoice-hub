"""Edge-case contracts for the Playwright invoice link downloader.

Synthetic only: fake Playwright response/page/download objects and local temp
files. No real network access, no real invoices, no runtime/ data.
"""

from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.invoice_fetch import link_downloader
from scripts.invoice_fetch.link_downloader import (
    DownloadedFile,
    LinkDownloader,
    _are_stems_homologous,
    _bounded_response_body,
    _dedupe_downloaded_files,
    _ensure_verified_extension,
    _is_safe_browser_request_url,
    _route_browser_request,
    _save_verified_capture,
    _UnsafeRequestGuard,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PUBLIC_PDF = b"%PDF-1.4\n" + b"p" * 900
PUBLIC_PDF_2 = b"%PDF-1.4\n" + b"q" * 900


def _ofd_bytes(marker: bytes = b"a") -> bytes:
    return b"PK\x03\x04" + marker + b"ofd.xml" + b"z" * 700


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        declared_length: int | None = None,
        content_type: str = "application/pdf",
        url: str = "https://nnfp.jss.com.cn/invoice.pdf",
        status: int = 200,
        transfer_encoding: str | None = None,
        content_encoding: str = "identity",
    ):
        self.status = status
        self.url = url
        self._body = body
        self.body_calls = 0
        self.headers = {"content-type": content_type}
        if declared_length is None:
            declared_length = len(body)
        self.headers["content-length"] = str(declared_length)
        if transfer_encoding:
            self.headers["transfer-encoding"] = transfer_encoding
        if content_encoding:
            self.headers["content-encoding"] = content_encoding

    def body(self) -> bytes:
        self.body_calls += 1
        return self._body


class FakeInvoicePage:
    """Minimal page double for the Nuonuo/JSS site handler."""

    def __init__(self, response: FakeResponse | None = None, pdf_bytes: bytes | None = None):
        self.url = "https://nnfp.jss.com.cn/scan-invoice/invoiceShow"
        self.frames = []
        self._response = response
        self._pdf_bytes = pdf_bytes
        self._handlers: dict[str, list] = {}
        self._response_dispatched = False
        self.pdf_paths: list[str] = []

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def wait_for_function(self, *args, **kwargs):
        return None

    def evaluate(self, script, *args):
        if "innerText" in script:
            return "电子发票\n发票号码: 123456\n开票日期: 2026-06-01\n销售方: 某公司"
        return ""

    def locator(self, selector):
        locator = MagicMock()
        locator.count.return_value = 0
        locator.first.wait_for.return_value = None
        return locator

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def wait_for_timeout(self, milliseconds):
        if self._response is not None and not self._response_dispatched:
            self._response_dispatched = True
            for handler in self._handlers.get("response", []):
                handler(self._response)

    def pdf(self, path):
        if self._pdf_bytes is None:
            raise AssertionError("page.pdf must not be used by this test")
        self.pdf_paths.append(str(path))
        Path(path).write_bytes(self._pdf_bytes)


class BoundedResponseBodyTests(unittest.TestCase):
    def test_exact_declared_length_is_accepted(self):
        response = FakeResponse(PUBLIC_PDF)
        self.assertEqual(_bounded_response_body(response), PUBLIC_PDF)
        self.assertEqual(response.body_calls, 1)

    def test_truncated_body_is_rejected(self):
        # The connection ended early: a %PDF prefix alone is not integrity.
        response = FakeResponse(PUBLIC_PDF, declared_length=len(PUBLIC_PDF) + 1000)
        self.assertEqual(_bounded_response_body(response), b"")

    def test_oversize_declared_length_is_rejected_before_buffering(self):
        response = FakeResponse(b"x" * 10, declared_length=link_downloader.MAX_DOWNLOAD_BYTES + 1)
        self.assertEqual(_bounded_response_body(response), b"")
        self.assertEqual(response.body_calls, 0)

    def test_chunked_or_compressed_bodies_are_not_buffered(self):
        chunked = FakeResponse(PUBLIC_PDF, transfer_encoding="chunked")
        compressed = FakeResponse(PUBLIC_PDF, content_encoding="gzip")
        self.assertEqual(_bounded_response_body(chunked), b"")
        self.assertEqual(_bounded_response_body(compressed), b"")
        self.assertEqual(chunked.body_calls, 0)
        self.assertEqual(compressed.body_calls, 0)

    def test_invalid_declared_length_is_not_buffered(self):
        response = FakeResponse(PUBLIC_PDF)
        response.headers["content-length"] = "not-a-number"
        self.assertEqual(_bounded_response_body(response), b"")
        self.assertEqual(response.body_calls, 0)


class SafeCaptureWriteTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.save_dir = Path(self._tempdir.name) / "attachments"
        self.save_dir.mkdir()

    def tearDown(self):
        self._tempdir.cleanup()

    def test_capture_saved_to_a_fresh_verified_file(self):
        saved = _save_verified_capture(self.save_dir, "invoice_1_0_resp", PUBLIC_PDF)
        self.assertIsNotNone(saved)
        self.assertEqual(Path(saved).read_bytes(), PUBLIC_PDF)
        self.assertTrue(Path(saved).name.startswith("invoice_1_0_resp"))

    def test_capture_never_overwrites_an_existing_attachment(self):
        existing = self.save_dir / "invoice_1_0_resp.pdf"
        existing.write_bytes(PUBLIC_PDF_2)

        saved = _save_verified_capture(self.save_dir, "invoice_1_0_resp", PUBLIC_PDF)

        self.assertIsNotNone(saved)
        self.assertNotEqual(Path(saved), existing)
        self.assertEqual(existing.read_bytes(), PUBLIC_PDF_2)
        self.assertEqual(Path(saved).read_bytes(), PUBLIC_PDF)

    def test_invalid_or_too_small_capture_is_not_left_behind(self):
        self.assertIsNone(_save_verified_capture(self.save_dir, "invoice_1_0_resp", b"<html>"))
        self.assertIsNone(
            _save_verified_capture(self.save_dir, "invoice_1_0_resp", b"%PDF-1.4 too small")
        )
        self.assertEqual(list(self.save_dir.iterdir()), [])

    def test_ofd_capture_keeps_ofd_extension(self):
        saved = _save_verified_capture(self.save_dir, "invoice_1_0_resp", _ofd_bytes())
        self.assertIsNotNone(saved)
        self.assertTrue(saved.endswith(".ofd"))


class BrowserRedirectGuardTests(unittest.TestCase):
    def test_redirect_hop_to_private_host_fails_closed(self):
        context = MagicMock()
        guard = _UnsafeRequestGuard(context)
        request = MagicMock()
        request.url = "http://127.0.0.1/intranet"
        request.redirected_from = "https://example.com/invoice"

        guard(request)

        self.assertTrue(guard.blocked)
        context.close.assert_called_once()

    def test_safe_redirect_hop_is_allowed(self):
        context = MagicMock()
        guard = _UnsafeRequestGuard(context)
        request = MagicMock()
        request.url = "https://example.com/invoice.pdf"
        request.redirected_from = "https://example.com/start"
        with patch.object(
            link_downloader, "_host_resolves_to_public_addresses", return_value=True
        ):
            guard(request)
        self.assertFalse(guard.blocked)
        context.close.assert_not_called()

    def test_plain_unsafe_resource_is_left_to_the_route_layer(self):
        context = MagicMock()
        guard = _UnsafeRequestGuard(context)
        request = MagicMock()
        request.url = "http://127.0.0.1/asset"
        request.redirected_from = None

        guard(request)

        self.assertFalse(guard.blocked)
        context.close.assert_not_called()

        route = MagicMock()
        route.request.url = "http://127.0.0.1/asset"
        _route_browser_request(route)
        route.abort.assert_called_once_with("blockedbyclient")
        route.continue_.assert_not_called()

    def test_out_of_range_port_fails_closed_instead_of_raising(self):
        self.assertFalse(_is_safe_browser_request_url("http://example.com:99999/invoice"))
        self.assertFalse(_is_safe_browser_request_url("https://[::1]:99999/invoice"))


class NuonuoCaptureIntegrityTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.download_dir = Path(self._tempdir.name) / "downloads"
        self.save_dir = Path(self._tempdir.name) / "mail-1"
        self.save_dir.mkdir()
        with patch(
            "scripts.invoice_fetch.config.load_config_safe", return_value={}
        ):
            self.downloader = LinkDownloader(self.download_dir)

    def tearDown(self):
        self._tempdir.cleanup()

    def _call_handler(self, page):
        return self.downloader._handle_nuonuo_invoice_page(
            page,
            "https://nnfp.jss.com.cn/scan-invoice/invoiceShow",
            self.save_dir,
            123,
            0,
            disable_fallback=True,
        )

    def test_valid_captured_response_does_not_reuse_existing_attachment(self):
        existing = self.save_dir / "invoice_123_0_resp.pdf"
        existing.write_bytes(PUBLIC_PDF_2)
        page = FakeInvoicePage(response=FakeResponse(PUBLIC_PDF))

        result = self._call_handler(page)

        self.assertIsNotNone(result)
        saved_path, source_type, _note = result
        self.assertEqual(source_type, "official_response")
        self.assertNotEqual(Path(saved_path), existing)
        self.assertEqual(existing.read_bytes(), PUBLIC_PDF_2)
        self.assertEqual(Path(saved_path).read_bytes(), PUBLIC_PDF)

    def test_invalid_captured_response_cannot_overwrite_or_delete_existing_attachment(self):
        existing = self.save_dir / "invoice_123_0_resp.pdf"
        existing.write_bytes(PUBLIC_PDF_2)
        # Valid %PDF prefix, but far below the verified minimum size.
        page = FakeInvoicePage(response=FakeResponse(b"%PDF-1.4 tiny"))

        result = self._call_handler(page)

        self.assertIsNone(result)
        self.assertEqual(existing.read_bytes(), PUBLIC_PDF_2)
        self.assertEqual(list(self.save_dir.iterdir()), [existing])

    def test_truncated_captured_response_is_not_written(self):
        existing = self.save_dir / "invoice_123_0_resp.pdf"
        existing.write_bytes(PUBLIC_PDF_2)
        response = FakeResponse(PUBLIC_PDF, declared_length=len(PUBLIC_PDF) + 500)
        page = FakeInvoicePage(response=response)

        result = self._call_handler(page)

        self.assertIsNone(result)
        self.assertEqual(existing.read_bytes(), PUBLIC_PDF_2)

    def test_page_pdf_fallback_does_not_overwrite_existing_attachment(self):
        existing = self.save_dir / "invoice_123_0_page_fallback.pdf"
        existing.write_bytes(PUBLIC_PDF_2)
        page = FakeInvoicePage(pdf_bytes=PUBLIC_PDF)

        with patch(
            "scripts.invoice_fetch.config.load_config_safe",
            return_value={"link_download_allow_invoice_page_pdf_fallback": True},
        ):
            result = self.downloader._handle_nuonuo_invoice_page(
                page,
                "https://nnfp.jss.com.cn/scan-invoice/invoiceShow",
                self.save_dir,
                123,
                0,
                disable_fallback=False,
            )

        self.assertIsNotNone(result)
        saved_path, source_type, _note = result
        self.assertEqual(source_type, "invoice_page_pdf_fallback")
        self.assertNotEqual(Path(saved_path), existing)
        self.assertEqual(existing.read_bytes(), PUBLIC_PDF_2)
        self.assertEqual(Path(saved_path).read_bytes(), PUBLIC_PDF)


    def test_failed_page_pdf_fallback_leaves_no_partial_file(self):
        class FailingPdfPage(FakeInvoicePage):
            def __init__(self):
                super().__init__(pdf_bytes=PUBLIC_PDF)

            def pdf(self, path):
                Path(path).write_bytes(b"%PDF-1.4 partial")
                raise RuntimeError("synthetic print failure")

        page = FailingPdfPage()
        with patch(
            "scripts.invoice_fetch.config.load_config_safe",
            return_value={"link_download_allow_invoice_page_pdf_fallback": True},
        ):
            result = self.downloader._handle_nuonuo_invoice_page(
                page,
                "https://nnfp.jss.com.cn/scan-invoice/invoiceShow",
                self.save_dir,
                123,
                0,
                disable_fallback=False,
            )

        self.assertIsNone(result)
        self.assertEqual(list(self.save_dir.iterdir()), [])


class DownloadUrlIntegrityTests(unittest.TestCase):
    def test_mislabeled_download_suffix_is_aligned_with_verified_content(self):
        with tempfile.TemporaryDirectory() as td:
            downloader = LinkDownloader(td)
            browser = MagicMock()
            downloader._browser = browser
            ctx = browser.new_context.return_value
            page = ctx.new_page.return_value
            page.url = "https://nnfp.jss.com.cn/invoice"
            save_dir = Path(td) / "2026-10-19"
            save_dir.mkdir()
            mislabeled = save_dir / "invoice_1_0.pdf"
            mislabeled.write_bytes(_ofd_bytes())

            with (
                patch.object(downloader, "_ensure_browser", return_value=None),
                patch.object(
                    downloader,
                    "_handle_nuonuo_invoice_page",
                    return_value=(str(mislabeled), "official_download", None),
                ),
                patch.object(
                    link_downloader, "_host_resolves_to_public_addresses", return_value=True
                ),
            ):
                result = downloader._download_url(
                    "https://nnfp.jss.com.cn/invoice", 1, 0, "2026-10-19"
                )

            self.assertIsNotNone(result)
            self.assertTrue(result.file_path.endswith(".ofd"), result.file_path)
            self.assertFalse(mislabeled.exists())
            self.assertTrue(Path(result.file_path).exists())
            ctx.close.assert_called_once()


class VerifiedExtensionTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tempdir.name)

    def tearDown(self):
        self._tempdir.cleanup()

    def test_pdf_content_renamed_from_ofd_suffix(self):
        path = self.root / "invoice.ofd"
        path.write_bytes(PUBLIC_PDF)
        renamed = _ensure_verified_extension(path)
        self.assertTrue(renamed.endswith(".pdf"))
        self.assertFalse(path.exists())
        self.assertTrue(Path(renamed).exists())

    def test_ofd_content_renamed_from_pdf_suffix(self):
        path = self.root / "invoice.pdf"
        path.write_bytes(_ofd_bytes())
        renamed = _ensure_verified_extension(path)
        self.assertTrue(renamed.endswith(".ofd"))
        self.assertFalse(path.exists())

    def test_matching_suffix_is_unchanged(self):
        path = self.root / "invoice.pdf"
        path.write_bytes(PUBLIC_PDF)
        self.assertEqual(_ensure_verified_extension(path), str(path))
        self.assertTrue(path.exists())


class DnsCacheTtlTests(unittest.TestCase):
    def setUp(self):
        link_downloader._clear_dns_safety_cache()
        self.addCleanup(link_downloader._clear_dns_safety_cache)

    def _records(self, *addresses):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            for address in addresses
        ]

    def test_public_verdict_expires_and_rebinding_to_private_is_blocked(self):
        addresses = iter(["93.184.216.34", "127.0.0.1"])
        with patch.object(link_downloader.socket, "getaddrinfo", side_effect=lambda *a, **k: self._records(next(addresses))), patch.object(
            link_downloader, "_dns_cache_bucket", return_value=10
        ):
            self.assertEqual(
                link_downloader._resolve_public_address("rebind.example", 443),
                "93.184.216.34",
            )
        with patch.object(link_downloader.socket, "getaddrinfo", side_effect=lambda *a, **k: self._records("127.0.0.1")), patch.object(
            link_downloader, "_dns_cache_bucket", return_value=11
        ):
            self.assertIsNone(
                link_downloader._resolve_public_address("rebind.example", 443)
            )

    def test_cached_unsafe_verdict_recovers_at_the_next_ttl_window(self):
        with patch.object(link_downloader.socket, "getaddrinfo", side_effect=lambda *a, **k: self._records("10.0.0.5")), patch.object(
            link_downloader, "_dns_cache_bucket", return_value=20
        ):
            self.assertFalse(
                link_downloader._host_resolves_to_public_addresses("recover.example", 443)
            )
        with patch.object(link_downloader.socket, "getaddrinfo", side_effect=lambda a, *rest, **k: self._records("93.184.216.34")), patch.object(
            link_downloader, "_dns_cache_bucket", return_value=21
        ):
            self.assertTrue(
                link_downloader._host_resolves_to_public_addresses("recover.example", 443)
            )


class BrowserLaunchCleanupTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)

    def test_launch_forces_loopback_and_link_local_through_the_safety_proxy(self):
        # Chromium implicitly bypasses a configured proxy for localhost and
        # link-local targets (169.254/16 = cloud metadata, [::1], 127.0.0.1/8).
        # A redirect to such a target would reach it directly before the
        # request guard reacts, so launch must subtract that implicit bypass.
        calls: list[dict] = []

        class FakeBrowser:
            def close(self):
                pass

        class FakeChromium:
            def launch(self, **kwargs):
                calls.append(kwargs)
                if kwargs.get("channel") in (None, "msedge"):
                    return FakeBrowser()
                raise RuntimeError("unavailable")

        class FakePlaywright:
            def __init__(self):
                self.chromium = FakeChromium()
                self.stopped = False

            def stop(self):
                self.stopped = True

        class FakeSyncPlaywright:
            def __init__(self):
                self.playwright = FakePlaywright()

            def start(self):
                return self.playwright

        fake_sync = FakeSyncPlaywright()
        with (
            patch(
                "scripts.invoice_fetch.config.load_config_safe",
                return_value={"playwright": {"channel": "auto"}},
            ),
            patch("playwright.sync_api.sync_playwright", return_value=fake_sync),
        ):
            downloader = LinkDownloader(self._tempdir.name)
            downloader._ensure_browser()
            downloader.close()

        self.assertTrue(calls)
        for call in calls:
            proxy = call["proxy"]
            self.assertTrue(proxy["server"].startswith("http://127.0.0.1:"), call)
            self.assertEqual(proxy.get("bypass"), "<-loopback>", call)

    def test_failed_launch_stops_driver_and_proxy(self):
        class RecordingPlaywright:
            def __init__(self):
                self.stopped = False
                self.chromium = MagicMock()
                self.chromium.launch.side_effect = RuntimeError("synthetic launch failure")

            def stop(self):
                self.stopped = True

        class FakeSyncPlaywright:
            def __init__(self):
                self.playwright = RecordingPlaywright()

            def start(self):
                return self.playwright

        fake_sync = FakeSyncPlaywright()

        class RecordingProxy:
            instances: list["RecordingProxy"] = []

            def __init__(self, resolver):
                self.resolver = resolver
                self.started = False
                self.stopped = False
                RecordingProxy.instances.append(self)

            def start(self):
                self.started = True
                return "http://127.0.0.1:9"

            def stop(self):
                self.stopped = True

        downloader = LinkDownloader(self._tempdir.name)
        with (
            patch(
                "scripts.invoice_fetch.config.load_config_safe",
                return_value={"playwright": {"channel": "chromium"}},
            ),
            patch("playwright.sync_api.sync_playwright", return_value=fake_sync),
            patch.object(link_downloader, "SafeBrowserProxy", RecordingProxy),
        ):
            with self.assertRaises(RuntimeError):
                downloader._ensure_browser()

        self.assertTrue(fake_sync.playwright.stopped)
        self.assertTrue(RecordingProxy.instances)
        self.assertTrue(RecordingProxy.instances[0].stopped)
        self.assertIsNone(downloader._pw)
        self.assertIsNone(downloader._safety_proxy)
        self.assertIsNone(downloader._browser)


class DownloadDeduplicationTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tempdir.name)

    def tearDown(self):
        self._tempdir.cleanup()

    def _file(self, name: bytes = b"x") -> DownloadedFile:
        path = self.root / name.decode()
        path.write_bytes(b"%PDF-1.4" + b"x" * 600)
        return DownloadedFile(
            url=f"https://example.com/{name.decode()}",
            file_path=str(path),
            filename=name.decode(),
            size=path.stat().st_size,
            is_invoice=True,
            source_type="official_download",
        )

    def test_different_invoices_with_homologous_stems_are_not_collapsed(self):
        self.assertTrue(_are_stems_homologous("invoice", "invoice"))
        self.assertTrue(_are_stems_homologous("电子发票", "电子发票_1"))
        # Homologous PDF/OFD stems are retained as separate artifacts.
        pdf = self._file(b"invoice_a.pdf")
        ofd_path = self.root / "invoice_a.ofd"
        ofd_path.write_bytes(_ofd_bytes())
        ofd = DownloadedFile(
            url="https://example.com/invoice_a.ofd",
            file_path=str(ofd_path),
            filename="invoice_a.ofd",
            size=ofd_path.stat().st_size,
            is_invoice=True,
            source_type="official_download",
        )
        deduped = _dedupe_downloaded_files([pdf, ofd])
        self.assertEqual({item.file_path for item in deduped}, {pdf.file_path, ofd.file_path})

    def test_identical_content_with_different_names_is_not_collapsed_here(self):
        # Two links may resolve to the same invoice file under different browser
        # suggested names.  Path-level de-duplication must not collapse them
        # (it cannot know two differently-named files are the same document);
        # services de-duplicate by invoice identity/file hash downstream and
        # remove the redundant download.
        first = self._file(b"a.pdf")
        second = self._file(b"b.pdf")
        deduped = _dedupe_downloaded_files([first, second])
        self.assertEqual(len(deduped), 2)

    def test_deduplication_keeps_priority_choice_regardless_of_input_order(self):
        low = self._file(b"same.pdf")
        low.size = 100
        low.source_type = "invoice_page_pdf_fallback"
        high_path = self.root / "same.pdf"
        high = DownloadedFile(
            url="https://example.com/same.pdf",
            file_path=str(high_path),
            filename="same.pdf",
            size=5000,
            is_invoice=True,
            source_type="official_download",
        )
        forward = _dedupe_downloaded_files([low, high])
        backward = _dedupe_downloaded_files([high, low])
        self.assertEqual([item.file_path for item in forward], [high.file_path])
        self.assertEqual([item.file_path for item in backward], [high.file_path])


class DownloadCancellationCleanupTests(unittest.TestCase):
    def test_cancelled_download_closes_the_browser_context(self):
        from scripts.invoice_fetch.scan_lifecycle import ScanCancelled

        class FakeControl:
            cancelled = False

            def raise_if_cancelled(self):
                if self.cancelled:
                    raise ScanCancelled("synthetic cancel")

        control = FakeControl()
        with tempfile.TemporaryDirectory() as td:
            downloader = LinkDownloader(td, scan_control=control)
            browser = MagicMock()
            downloader._browser = browser
            ctx = browser.new_context.return_value
            page = ctx.new_page.return_value
            page.url = "https://nnfp.jss.com.cn/invoice"

            def cancel_during_navigation(*args, **kwargs):
                control.cancelled = True

            page.goto.side_effect = cancel_during_navigation
            with (
                patch.object(downloader, "_ensure_browser", return_value=None),
                patch.object(
                    link_downloader, "_host_resolves_to_public_addresses", return_value=True
                ),
            ):
                with self.assertRaises(ScanCancelled):
                    downloader._download_url(
                        "https://nnfp.jss.com.cn/invoice", 1, 0, "2026-10-19"
                    )
            ctx.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
