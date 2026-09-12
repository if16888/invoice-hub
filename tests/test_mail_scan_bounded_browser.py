from __future__ import annotations

import inspect
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

    def test_link_downloader_honors_scan_control_before_browser_work(self):
        control = ScanControl()
        control.cancel()
        downloader = self._downloader(Path("bounded-browser-test"), control)
        with self.assertRaises(ScanCancelled):
            downloader.download_from_email(None, 1, "2026-09-12")

    def test_cancel_during_browser_start_is_not_swallowed_as_start_failure(self):
        control = ScanControl()
        downloader = self._downloader(Path("bounded-browser-start-cancel"), control)

        def cancel_during_start():
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
        self.assertIn("deadline = attempt_started + self._max_seconds_per_url", source)
        self.assertIn("self._remaining_timeout_ms(deadline)", source)
        self.assertIn("self._check_cancelled()", source)
        self.assertIn("Browser download attempt finished", source)

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