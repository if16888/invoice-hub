from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = ROOT / "scripts/invoice_fetch/link_downloader.py"
TESTS = ROOT / "tests/test_mail_scan_bounded_browser.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one replacement, found {count}: {old[:160]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_exact_count(path: Path, old: str, new: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(
            f"{path}: expected {expected} replacements, found {count}: {old[:160]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


# One monotonic email deadline is authoritative for every URL attempt in the email.
replace_once(
    LINK,
    '''        start_time = time.perf_counter()\n\n        def email_budget_exhausted() -> bool:\n            if self._max_seconds_per_email <= 0 or attempted_count == 0:\n                return False\n            return (time.perf_counter() - start_time) >= self._max_seconds_per_email\n''',
    '''        start_time = time.monotonic()\n        email_deadline = start_time + self._max_seconds_per_email\n\n        def email_budget_exhausted() -> bool:\n            if self._max_seconds_per_email <= 0 or attempted_count == 0:\n                return False\n            return time.monotonic() >= email_deadline\n''',
)
replace_once(
    LINK,
    '        elapsed = time.perf_counter() - start_time\n',
    '        elapsed = time.monotonic() - start_time\n',
)

replace_exact_count(
    LINK,
    '            r = self._download_url(url, mail_uid, len(results), date_str, disable_fallback=has_official_success)\n',
    '''            r = self._download_url(\n                url,\n                mail_uid,\n                len(results),\n                date_str,\n                disable_fallback=has_official_success,\n                deadline=email_deadline,\n            )\n''',
    2,
)

# All bounded browser operations share the same URL/email deadline, including launch fallbacks.
replace_once(
    LINK,
    '    def _ensure_browser(self):\n',
    '    def _ensure_browser(self, deadline: float | None = None):\n',
)
replace_once(
    LINK,
    '''        self._pw = sync_playwright().start()\n\n        launch_args = [\n''',
    '''        self._pw = sync_playwright().start()\n        self._check_cancelled()\n        if deadline is not None:\n            self._remaining_timeout_ms(deadline)\n\n        launch_args = [\n''',
)
replace_once(
    LINK,
    '                "timeout": self._timeout,\n',
    '                "timeout": self._remaining_timeout_ms(deadline) if deadline is not None else self._timeout,\n',
)

# Cooperative waits keep close/cancel responsive instead of sleeping or blocking for a fixed 5 seconds.
replace_once(
    LINK,
    '''    def _remaining_timeout_ms(self, deadline: float, cap_ms: int | None = None) -> int:\n        self._check_cancelled()\n        remaining_ms = int((deadline - time.monotonic()) * 1000)\n        if remaining_ms <= 0:\n            raise TimeoutError("browser link download deadline exceeded")\n        if cap_ms is not None:\n            remaining_ms = min(remaining_ms, int(cap_ms))\n        return max(1, min(remaining_ms, self._timeout))\n\n''',
    '''    def _remaining_timeout_ms(self, deadline: float, cap_ms: int | None = None) -> int:\n        self._check_cancelled()\n        remaining_ms = int((deadline - time.monotonic()) * 1000)\n        if remaining_ms <= 0:\n            raise TimeoutError("browser link download deadline exceeded")\n        if cap_ms is not None:\n            remaining_ms = min(remaining_ms, int(cap_ms))\n        return max(1, min(remaining_ms, self._timeout))\n\n    def _sleep_with_cancel(self, seconds: float, deadline: float | None = None) -> None:\n        wait_deadline = time.monotonic() + max(0.0, float(seconds))\n        if deadline is not None:\n            wait_deadline = min(wait_deadline, deadline)\n        while True:\n            self._check_cancelled()\n            now = time.monotonic()\n            remaining = wait_deadline - now\n            if remaining <= 0:\n                if deadline is not None and now >= deadline:\n                    raise TimeoutError("browser link download deadline exceeded")\n                return\n            time.sleep(min(0.05, remaining))\n\n    def _wait_event_until(\n        self,\n        event: threading.Event,\n        deadline: float,\n        cap_seconds: float,\n    ) -> bool:\n        wait_deadline = min(deadline, time.monotonic() + max(0.0, float(cap_seconds)))\n        while True:\n            self._check_cancelled()\n            now = time.monotonic()\n            remaining = wait_deadline - now\n            if remaining <= 0:\n                if now >= deadline:\n                    raise TimeoutError("browser link download deadline exceeded")\n                return event.is_set()\n            if event.wait(min(0.05, remaining)):\n                return True\n\n''',
)

replace_once(
    LINK,
    '    def _download_url(self, url: str, mail_uid: int, idx: int, date_str: str, disable_fallback: bool = False) -> DownloadedFile | None:\n',
    '''    def _download_url(\n        self,\n        url: str,\n        mail_uid: int,\n        idx: int,\n        date_str: str,\n        disable_fallback: bool = False,\n        deadline: float | None = None,\n    ) -> DownloadedFile | None:\n''',
)
replace_once(
    LINK,
    '''        attempt_started = time.monotonic()\n        deadline = attempt_started + self._max_seconds_per_url\n        fingerprint = self._url_fingerprint(url)\n''',
    '''        attempt_started = time.monotonic()\n        url_deadline = attempt_started + self._max_seconds_per_url\n        deadline = min(url_deadline, deadline) if deadline is not None else url_deadline\n        fingerprint = self._url_fingerprint(url)\n''',
)
replace_once(
    LINK,
    '''            self._check_cancelled()\n            self._ensure_browser()\n            self._check_cancelled()\n''',
    '''            self._check_cancelled()\n            self._ensure_browser(deadline)\n            self._check_cancelled()\n''',
)

# Site-specific click and response waits must consume the same deadline.
replace_once(
    LINK,
    '''                        with page.expect_download(timeout=self._remaining_timeout_ms(deadline, 3000) if deadline is not None else 3000) as download_info:\n                            locator.first.click()\n''',
    '''                        with page.expect_download(timeout=self._remaining_timeout_ms(deadline, 3000) if deadline is not None else 3000) as download_info:\n                            locator.first.click(\n                                timeout=self._remaining_timeout_ms(deadline, 3000)\n                                if deadline is not None\n                                else 3000\n                            )\n''',
)
replace_once(
    LINK,
    '''        # Short wait to collect responses\n        page.wait_for_timeout(2000)\n''',
    '''        # Short wait to collect responses without exceeding the URL/email deadline.\n        page.wait_for_timeout(\n            min(2000, self._remaining_timeout_ms(deadline, 2000))\n            if deadline is not None\n            else 2000\n        )\n''',
)

replace_once(
    LINK,
    '                    self._try_click_download(page)\n',
    '                    self._try_click_download(page, deadline)\n',
)
replace_once(
    LINK,
    '''                if download_started and not downloaded_path:\n                    download_done.wait(timeout=5)\n                    if downloaded_path:\n''',
    '''                if download_started and not downloaded_path:\n                    self._wait_event_until(download_done, deadline, 5.0)\n                    if downloaded_path:\n''',
)
replace_once(
    LINK,
    '    def _try_click_download(self, page) -> None:\n',
    '    def _try_click_download(self, page, deadline: float | None = None) -> None:\n',
)
replace_once(
    LINK,
    '''                locator.first.click(timeout=2000)\n                time.sleep(1)\n                return\n''',
    '''                locator.first.click(\n                    timeout=self._remaining_timeout_ms(deadline, 2000)\n                    if deadline is not None\n                    else 2000\n                )\n                self._sleep_with_cancel(1.0, deadline)\n                return\n''',
)

# Strengthen the focused regression contract: shared launch deadline, email deadline propagation,
# and cancellation during event waiting are executable behavior rather than source-only intent.
replace_once(
    TESTS,
    '''    def test_url_deadline_and_cancellation_are_part_of_download_contract(self):\n        source = inspect.getsource(LinkDownloader._download_url)\n        self.assertIn("deadline = attempt_started + self._max_seconds_per_url", source)\n        self.assertIn("self._remaining_timeout_ms(deadline)", source)\n        self.assertIn("self._check_cancelled()", source)\n        self.assertIn("Browser download attempt finished", source)\n\n''',
    '''    def test_url_deadline_and_cancellation_are_part_of_download_contract(self):\n        source = inspect.getsource(LinkDownloader._download_url)\n        self.assertIn("url_deadline = attempt_started + self._max_seconds_per_url", source)\n        self.assertIn("min(url_deadline, deadline)", source)\n        self.assertIn("self._ensure_browser(deadline)", source)\n        self.assertIn("self._remaining_timeout_ms(deadline)", source)\n        self.assertIn("self._try_click_download(page, deadline)", source)\n        self.assertIn("self._wait_event_until(download_done, deadline, 5.0)", source)\n        self.assertIn("self._check_cancelled()", source)\n        self.assertIn("Browser download attempt finished", source)\n\n    def test_browser_launch_fallbacks_share_the_remaining_deadline(self):\n        source = inspect.getsource(LinkDownloader._ensure_browser)\n        self.assertIn("deadline: float | None = None", source)\n        self.assertIn("self._remaining_timeout_ms(deadline)", source)\n        self.assertNotIn('"timeout": self._timeout,', source)\n\n    def test_email_deadline_is_forwarded_to_each_url_attempt(self):\n        downloader = self._downloader(Path("bounded-browser-email-deadline"))\n        downloader._max_seconds_per_email = 2.0\n        msg = EmailMessage()\n        msg["Subject"] = "invoice"\n        raw = [{"url": "https://example.com/invoice", "text": "invoice"}]\n        deadlines = []\n\n        def attempt(*_args, **kwargs):\n            deadlines.append(kwargs.get("deadline"))\n            return None\n\n        started = time.monotonic()\n        with patch.object(link_downloader, "extract_html_from_message", return_value="<html></html>"), patch.object(\n            link_downloader,\n            "_extract_links_with_metadata_from_html_and_stats",\n            return_value=(raw, {"anchor_count": 1, "unsafe_skipped": 0, "excluded_skipped": 0}),\n        ), patch.object(\n            link_downloader,\n            "_dedup_and_prioritize_with_metadata",\n            return_value=(raw, []),\n        ), patch.object(downloader, "_download_url", side_effect=attempt):\n            downloader.download_from_email(msg, 1, "2026-09-12")\n\n        self.assertEqual(len(deadlines), 1)\n        self.assertIsNotNone(deadlines[0])\n        self.assertGreater(deadlines[0], started)\n        self.assertLessEqual(deadlines[0], started + 2.2)\n\n    def test_download_event_wait_observes_cancellation_promptly(self):\n        control = ScanControl()\n        downloader = self._downloader(Path("bounded-browser-event-cancel"), control)\n        event = threading.Event()\n\n        def cancel_soon():\n            time.sleep(0.03)\n            control.cancel()\n\n        thread = threading.Thread(target=cancel_soon, daemon=True)\n        thread.start()\n        started = time.monotonic()\n        with self.assertRaises(ScanCancelled):\n            downloader._wait_event_until(event, time.monotonic() + 1.0, 1.0)\n        elapsed = time.monotonic() - started\n        thread.join(timeout=0.2)\n        self.assertLess(elapsed, 0.3)\n\n''',
)

print("mail scan deadline closure patch applied")
