from __future__ import annotations

import inspect
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch import link_downloader
from scripts.invoice_fetch.link_downloader import LinkDownloader
from scripts.invoice_fetch.scan_lifecycle import ScanCancelled, ScanControl


class BoundedBrowserScanTests(unittest.TestCase):
    def tearDown(self):
        link_downloader._host_resolves_to_public_addresses.cache_clear()

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
        with patch("scripts.invoice_fetch.config.load_config_safe", return_value={}):
            downloader = LinkDownloader(Path("bounded-browser-test"), scan_control=control)
        with self.assertRaises(ScanCancelled):
            downloader.download_from_email(None, 1, "2026-09-12")

    def test_url_deadline_and_cancellation_are_part_of_download_contract(self):
        source = inspect.getsource(LinkDownloader._download_url)
        self.assertIn("deadline = attempt_started + self._max_seconds_per_url", source)
        self.assertIn("self._remaining_timeout_ms(deadline)", source)
        self.assertIn("self._check_cancelled()", source)
        self.assertIn("Browser download attempt finished", source)

    def test_mail_scan_service_passes_scan_control_to_link_downloader(self):
        from scripts.invoice_fetch import services

        source = inspect.getsource(services.scan_email_and_download)
        self.assertIn(
            "LinkDownloader(att_dir, headed=headed, scan_control=scan_control)", source
        )

    def test_settings_rule_does_not_claim_a_fixed_three_month_window(self):
        from scripts.invoice_fetch.gui import settings_dialog

        source = inspect.getsource(settings_dialog.SettingsDialog)
        self.assertNotIn("只扫描最近 3 个月", source)
        self.assertIn("按各邮箱配置的时间范围进行增量抓取", source)


if __name__ == "__main__":
    unittest.main()
