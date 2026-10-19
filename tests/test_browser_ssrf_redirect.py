"""Real-browser regression: a redirect into a private host must never connect.

Gated behind ``INVOICE_HUB_RUN_BROWSER_SMOKE=1`` like the other browser
smoke tests; needs a working Chromium channel (Edge/Chrome) on the machine.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch import link_downloader

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment without Playwright
    sync_playwright = None


def _available_channel() -> str | None:
    if sync_playwright is None:
        return None
    for channel in ("msedge", "chrome"):
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel=channel, headless=True, chromium_sandbox=True,
                )
                browser.close()
            return channel
        except Exception:
            continue
    return None


@unittest.skipUnless(
    os.environ.get("INVOICE_HUB_RUN_BROWSER_SMOKE") == "1" and sync_playwright,
    "set INVOICE_HUB_RUN_BROWSER_SMOKE=1 with a Chromium channel to run the SSRF browser test",
)
class BrowserRedirectSsrfTests(unittest.TestCase):
    def test_private_redirect_target_receives_no_request(self):
        channel = _available_channel()
        if channel is None:
            self.skipTest("no Chromium channel (msedge/chrome) available")

        hits: list[tuple[str, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append((self.headers.get("Host", ""), self.path))
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", f"http://private.test:{server.server_address[1]}/track")
                    self.end_headers()
                    return
                body = b"tracked"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))

        resolver_calls: list[tuple[str, int, str | None]] = []

        def resolver(host, port_):
            """Proxy-layer resolver: vetted address or None to deny."""
            host = str(host).lower()
            if host == "public.test":
                address = "127.0.0.1"
            else:
                # private.test and background browser traffic are denied.
                address = None
            resolver_calls.append((host, port_, address))
            return address

        def dns_check(host, port_):
            """Route/request-guard DNS decision for the same hostnames."""
            return str(host).lower() == "public.test"

        config = {
            "playwright": {"channel": channel},
            "link_download": {
                "timeout_ms": 4000,
                "max_operation_timeout_ms": 4000,
                "budget_seconds_per_url": 5,
                "nuonuo_budget_seconds": 5,
                "budget_seconds_per_email": 8,
            },
        }

        with tempfile.TemporaryDirectory(prefix="invoice-hub-ssrf-") as td, patch(
            "scripts.invoice_fetch.config.load_config_safe", return_value=config,
        ), patch.object(
            link_downloader, "_resolve_public_address", side_effect=resolver,
        ), patch.object(
            link_downloader, "_host_resolves_to_public_addresses", side_effect=dns_check,
        ), patch.object(
            link_downloader, "_host_resolves_to_public_addresses_cached", side_effect=dns_check,
        ):
            downloader = link_downloader.LinkDownloader(Path(td))
            try:
                result = downloader._download_url(
                    f"http://public.test:{port}/redirect", 1, 0, "2026-10-19",
                )
            finally:
                downloader.close()

        self.assertIsNone(result)
        private_track_hits = [hit for hit in hits if hit[1].startswith("/track")]
        self.assertEqual(
            private_track_hits, [],
            f"private redirect target received a request: {private_track_hits}",
        )
        private_checks = [call for call in resolver_calls if call[0] == "private.test"]
        self.assertTrue(private_checks, f"private target was never vetted: {resolver_calls}")
        self.assertTrue(all(call[2] is None for call in private_checks), private_checks)


if __name__ == "__main__":
    unittest.main()
