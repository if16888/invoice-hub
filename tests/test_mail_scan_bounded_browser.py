from __future__ import annotations

import inspect
import sys
import tempfile
import threading
import time
import unittest
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.invoice_fetch import link_downloader
from scripts.invoice_fetch.link_downloader import LinkDownloader
from scripts.invoice_fetch.scan_lifecycle import ScanCancelled, ScanControl


class BoundedBrowserScanTests(unittest.TestCase):
    def tearDown(self):
        link_downloader._host_resolves_to_public_addresses.cache_clear()

    def _downloader(self, root: Path, control: ScanControl | None = None) -> LinkDownloader:
        with patch("scripts.invoice_fetch.config.load_config_safe", return_value={}):
            return LinkDownloader(root, scan_control=control)

    def test_browser_operation_timeout_is_capped_by_configured_hard_limit(self):
        config = {
            "link_download": {
                "timeout_ms": 30_000,
                "max_operation_timeout_ms": 10_000,
            }
        }
        with tempfile.TemporaryDirectory(prefix="invoice-hub-browser-timeout-") as td, patch(
            "scripts.invoice_fetch.config.load_config_safe", return_value=config
        ):
            downloader = LinkDownloader(td)
        self.assertEqual(downloader._timeout, 10_000)

    def test_dns_safety_check_fails_closed_without_waiting_for_stuck_resolver(self):
        blocker = threading.Event()

        def stuck_getaddrinfo(*_args, **_kwargs):
            blocker.wait(1.0)
            return []

        link_downloader._host_resolves_to_public_addresses.cache_clear()
        started = time.monotonic()
        with patch.object(link_downloader, "_DNS_RESOLVE_TIMEOUT_SECONDS", 0.02), patch.object(
            link_downloader.socket, "getaddrinfo", side_effect=stuck_getaddrinfo
        ):
            allowed = link_downloader._host_resolves_to_public_addresses(
                "invoice-timeout.example", 443
            )
        elapsed = time.monotonic() - started
        blocker.set()

        self.assertFalse(allowed)
        self.assertLess(elapsed, 0.25)

    def test_dns_safety_check_caps_stuck_resolver_thread_growth(self):
        blocker = threading.Event()
        calls: list[str] = []

        def stuck_getaddrinfo(host, *_args, **_kwargs):
            calls.append(str(host))
            blocker.wait(1.0)
            return []

        link_downloader._host_resolves_to_public_addresses.cache_clear()
        slots = threading.BoundedSemaphore(2)
        exhausted_elapsed = None
        try:
            with patch.object(
                link_downloader, "_DNS_RESOLVE_TIMEOUT_SECONDS", 0.02
            ), patch.object(
                link_downloader, "_DNS_RESOLVE_SLOTS", slots
            ), patch.object(
                link_downloader.socket, "getaddrinfo", side_effect=stuck_getaddrinfo
            ):
                self.assertFalse(
                    link_downloader._host_resolves_to_public_addresses(
                        "invoice-timeout-a.example", 443
                    )
                )
                self.assertFalse(
                    link_downloader._host_resolves_to_public_addresses(
                        "invoice-timeout-b.example", 443
                    )
                )
                started = time.monotonic()
                self.assertFalse(
                    link_downloader._host_resolves_to_public_addresses(
                        "invoice-timeout-c.example", 443
                    )
                )
                exhausted_elapsed = time.monotonic() - started
        finally:
            blocker.set()

        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(exhausted_elapsed)
        self.assertLess(exhausted_elapsed, 0.1)

    def test_link_downloader_honors_scan_control_before_browser_work(self):
        control = ScanControl()
        control.cancel()
        downloader = self._downloader(Path("bounded-browser-test"), control)
        with self.assertRaises(ScanCancelled):
            downloader.download_from_email(None, 1, "2026-09-12")

    def test_cancel_during_browser_start_is_not_swallowed_as_start_failure(self):
        control = ScanControl()
        downloader = self._downloader(Path("bounded-browser-start-cancel"), control)

        def cancel_during_start(*_args, **_kwargs):
            control.cancel()
            raise ScanCancelled("cancel during browser start")

        with patch.object(downloader, "_ensure_browser", side_effect=cancel_during_start):
            with self.assertRaises(ScanCancelled):
                downloader._download_url("https://example.com/invoice", 1, 0, "2026-09-12")

    def test_cancel_after_low_priority_attempt_stops_before_next_link(self):
        control = ScanControl()
        downloader = self._downloader(Path("bounded-browser-low-priority"), control)
        msg = EmailMessage()
        msg["Subject"] = "invoice"

        attempts = []

        def attempt(*_args, **_kwargs):
            attempts.append(1)
            control.cancel()
            return None

        raw = [{"url": "https://example.com/receipt", "text": "receipt"}]
        low = [
            {"url": "https://example.com/receipt", "text": "receipt"},
            {"url": "https://example.com/receipt2", "text": "receipt"},
        ]
        with patch.object(link_downloader, "extract_html_from_message", return_value="<html></html>"), patch.object(
            link_downloader,
            "_extract_links_with_metadata_from_html_and_stats",
            return_value=(raw, {"anchor_count": 1, "unsafe_skipped": 0, "excluded_skipped": 0}),
        ), patch.object(
            link_downloader,
            "_dedup_and_prioritize_with_metadata",
            return_value=([], low),
        ), patch.object(downloader, "_download_url", side_effect=attempt):
            with self.assertRaises(ScanCancelled):
                downloader.download_from_email(msg, 1, "2026-09-12")

        self.assertEqual(len(attempts), 1)

    def test_url_deadline_and_cancellation_are_part_of_download_contract(self):
        source = inspect.getsource(LinkDownloader._download_url)
        self.assertIn("url_deadline = attempt_started + self._max_seconds_per_url", source)
        self.assertIn("min(url_deadline, deadline)", source)
        self.assertIn("self._ensure_browser(deadline)", source)
        self.assertIn("self._remaining_timeout_ms(deadline)", source)
        self.assertIn("self._try_click_download(page, deadline)", source)
        self.assertIn("self._wait_event_until(download_done, deadline, 5.0)", source)
        self.assertIn("self._check_cancelled()", source)
        self.assertIn("Browser download attempt finished", source)

    def test_browser_launch_fallbacks_share_the_remaining_deadline(self):
        source = inspect.getsource(LinkDownloader._ensure_browser)
        self.assertIn("deadline: float | None = None", source)
        self.assertIn("self._remaining_timeout_ms(deadline)", source)
        self.assertNotIn('"timeout": self._timeout,', source)

    def test_email_deadline_is_forwarded_to_each_url_attempt(self):
        downloader = self._downloader(Path("bounded-browser-email-deadline"))
        downloader._max_seconds_per_email = 2.0
        msg = EmailMessage()
        msg["Subject"] = "invoice"
        raw = [{"url": "https://example.com/invoice", "text": "invoice"}]
        deadlines = []

        def attempt(*_args, **kwargs):
            deadlines.append(kwargs.get("deadline"))
            return None

        started = time.monotonic()
        with patch.object(link_downloader, "extract_html_from_message", return_value="<html></html>"), patch.object(
            link_downloader,
            "_extract_links_with_metadata_from_html_and_stats",
            return_value=(raw, {"anchor_count": 1, "unsafe_skipped": 0, "excluded_skipped": 0}),
        ), patch.object(
            link_downloader,
            "_dedup_and_prioritize_with_metadata",
            return_value=(raw, []),
        ), patch.object(downloader, "_download_url", side_effect=attempt):
            downloader.download_from_email(msg, 1, "2026-09-12")

        self.assertEqual(len(deadlines), 1)
        self.assertIsNotNone(deadlines[0])
        self.assertGreater(deadlines[0], started)
        self.assertLessEqual(deadlines[0], started + 2.2)

    def test_download_event_wait_observes_cancellation_promptly(self):
        control = ScanControl()
        downloader = self._downloader(Path("bounded-browser-event-cancel"), control)
        event = threading.Event()

        def cancel_soon():
            time.sleep(0.03)
            control.cancel()

        thread = threading.Thread(target=cancel_soon, daemon=True)
        thread.start()
        started = time.monotonic()
        with self.assertRaises(ScanCancelled):
            downloader._wait_event_until(event, time.monotonic() + 1.0, 1.0)
        elapsed = time.monotonic() - started
        thread.join(timeout=0.2)
        self.assertLess(elapsed, 0.3)

    def test_mail_scan_service_passes_scan_control_to_link_downloader(self):
        from scripts.invoice_fetch import services

        source = inspect.getsource(services._scan_mailboxes_with_db)
        self.assertIn(
            "LinkDownloader(att_dir, headed=headed, scan_control=scan_control)", source
        )

    def test_settings_rule_does_not_claim_a_fixed_three_month_window(self):
        source = Path("scripts/invoice_fetch/gui/settings_dialog.py").read_text(encoding="utf-8")
        self.assertNotIn("只扫描最近 3 个月", source)
        self.assertIn("按各邮箱配置的时间范围进行增量抓取", source)

    def test_semantic_evidence_fingerprint_includes_later_pages(self):
        from scripts.invoice_fetch import services

        class FakePage:
            def __init__(self, text: str):
                self._text = text

            def extract_text(self):
                return self._text

        class FakePdf:
            def __init__(self, texts: list[str]):
                self.pages = [FakePage(text) for text in texts]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        common = [
            "Trip statement common first page with enough visible text for stable fingerprinting.",
            "Trip statement common second page with the same shared reimbursement details.",
        ]

        def fake_open(path: str):
            tail = (
                "Third page contains trip A details and route one."
                if Path(path).stem == "a"
                else "Third page contains trip B details and route two."
            )
            return FakePdf(common + [tail])

        fake_pdfplumber = SimpleNamespace(open=fake_open)
        with tempfile.TemporaryDirectory(prefix="invoice-hub-evidence-pages-") as td:
            a = Path(td) / "a.pdf"
            b = Path(td) / "b.pdf"
            a.write_bytes(b"a")
            b.write_bytes(b"b")
            with patch.dict(sys.modules, {"pdfplumber": fake_pdfplumber}):
                a_fingerprint = services._semantic_evidence_fingerprint(a)
                b_fingerprint = services._semantic_evidence_fingerprint(b)

        self.assertTrue(a_fingerprint.startswith("pdftext:"))
        self.assertTrue(b_fingerprint.startswith("pdftext:"))
        self.assertNotEqual(a_fingerprint, b_fingerprint)

    def test_semantic_evidence_fingerprint_fails_open_for_long_documents(self):
        from scripts.invoice_fetch import services

        class FakePdf:
            def __init__(self):
                self.pages = [SimpleNamespace(extract_text=lambda: "content") for _ in range(33)]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        fake_pdfplumber = SimpleNamespace(open=lambda _path: FakePdf())
        with tempfile.TemporaryDirectory(prefix="invoice-hub-evidence-long-") as td:
            document = Path(td) / "long.pdf"
            document.write_bytes(b"long")
            with patch.dict(sys.modules, {"pdfplumber": fake_pdfplumber}):
                fingerprint = services._semantic_evidence_fingerprint(document)

        self.assertEqual(fingerprint, "")

    def test_email_extra_semantic_duplicate_is_not_copied_or_appended(self):
        from scripts.invoice_fetch import services

        with tempfile.TemporaryDirectory(prefix="invoice-hub-evidence-idempotency-") as td:
            root = Path(td)
            existing = root / "existing.pdf"
            incoming = root / "incoming.pdf"
            existing.write_bytes(b"existing bytes")
            incoming.write_bytes(b"regenerated bytes")

            class FakeDB:
                def __init__(self):
                    self.updated_paths = None
                    self.flags = []

                def get_invoice(self, _invoice_id):
                    return {"id": 7, "extra_paths": ["existing.pdf"]}

                def update_invoice_file_paths(self, _invoice_id, *, extra_paths):
                    self.updated_paths = list(extra_paths)

                def update_invoice_extra_flags(self, invoice_id, **kwargs):
                    self.flags.append((invoice_id, kwargs))

            db = FakeDB()
            extra = SimpleNamespace(
                file_path=str(incoming),
                original_name="20260912_trip_detail.pdf",
            )
            attached_sources: set[str] = set()
            kept_paths: set[str] = set()

            def resolve(path):
                if str(path) == "existing.pdf":
                    return existing
                return None

            with patch.object(services, "_resolve_runtime_path", side_effect=resolve), patch.object(
                services,
                "_semantic_evidence_fingerprint",
                return_value="pdftext:same-visible-document",
            ), patch.object(services, "_rename_by_invoice_code") as rename:
                result = services._attach_email_extras_to_invoice(
                    db=db,
                    invoice_id=7,
                    extra_files=[extra],
                    code="123456",
                    inv_date="2026-09-12",
                    att_base=root,
                    category="交通",
                    total_amount="88.00",
                    invoice_number="123456",
                    kept_paths=kept_paths,
                    attached_source_paths=attached_sources,
                )

            self.assertEqual(result, ["existing.pdf"])
            rename.assert_not_called()
            self.assertIsNone(db.updated_paths)
            self.assertIn(str(incoming.resolve()), attached_sources)
            self.assertNotIn(str(incoming.resolve()), kept_paths)


if __name__ == "__main__":
    unittest.main()
