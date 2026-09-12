from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = ROOT / "scripts/invoice_fetch/link_downloader.py"
TESTS = ROOT / "tests/test_mail_scan_bounded_browser.py"
CONFIG = ROOT / "config.example.json"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# These are cooperative browser-work budgets, not a claim that every Playwright
# completion primitive can be preempted at an exact wall-clock boundary.
replace_once(
    CONFIG,
    '''    "max_seconds_per_url": 20,\n    "max_seconds_per_email": 60,\n''',
    '''    "budget_seconds_per_url": 20,\n    "budget_seconds_per_email": 60,\n''',
)

replace_once(
    LINK,
    '''        self._max_seconds_per_url = max(3.0, float(link_cfg.get("max_seconds_per_url", 20.0)))\n        self._max_links_per_email = max(1, int(link_cfg.get("max_links_per_email", 3)))\n        self._max_seconds_per_email = max(\n            self._max_seconds_per_url,\n            float(link_cfg.get("max_seconds_per_email", 60.0)),\n        )\n''',
    '''        legacy_url_budget = link_cfg.get("max_seconds_per_url", 20.0)\n        self._url_budget_seconds = max(\n            3.0,\n            float(link_cfg.get("budget_seconds_per_url", legacy_url_budget)),\n        )\n        self._max_links_per_email = max(1, int(link_cfg.get("max_links_per_email", 3)))\n        legacy_email_budget = link_cfg.get("max_seconds_per_email", 60.0)\n        self._email_budget_seconds = max(\n            self._url_budget_seconds,\n            float(link_cfg.get("budget_seconds_per_email", legacy_email_budget)),\n        )\n''',
)

text = LINK.read_text(encoding="utf-8")
text = text.replace("self._max_seconds_per_url", "self._url_budget_seconds")
text = text.replace("self._max_seconds_per_email", "self._email_budget_seconds")
LINK.write_text(text, encoding="utf-8")

replace_once(
    LINK,
    '''def _save_download_to_path(download, dest: Path, timeout_ms: int = 30_000) -> bool:\n    \"\"\"Persist a Playwright download to *dest* without leaking callback errors.\"\"\"\n''',
    '''def _save_download_to_path(download, dest: Path) -> bool:\n    \"\"\"Persist a completed Playwright download without implying a fake save timeout.\"\"\"\n''',
)
text = LINK.read_text(encoding="utf-8")
text = text.replace("_save_download_to_path(download, dest, self._timeout)", "_save_download_to_path(download, dest)")
LINK.write_text(text, encoding="utf-8")

replace_once(
    LINK,
    '''                r = self._download_url(\n                url,\n                mail_uid,\n                len(results),\n                date_str,\n                disable_fallback=has_official_success,\n                deadline=email_deadline,\n            )\n''',
    '''                r = self._download_url(\n                    url,\n                    mail_uid,\n                    len(results),\n                    date_str,\n                    disable_fallback=has_official_success,\n                    deadline=email_deadline,\n                )\n''',
)

# Make diagnostics truthful even when the last attempted link consumed the budget.
needle = '''            if r:\n                results.append(r)\n                high_success = True\n                if r.source_type != "invoice_page_pdf_fallback":\n                    has_official_success = True\n\n        # 2. Try low priority links if no high priority links succeeded and limit not reached\n'''
replace_once(
    LINK,
    needle,
    '''            if r:\n                results.append(r)\n                high_success = True\n                if r.source_type != "invoice_page_pdf_fallback":\n                    has_official_success = True\n            if time.monotonic() >= email_deadline:\n                timed_out = True\n\n        # 2. Try low priority links if no high priority links succeeded and limit not reached\n''',
)
needle = '''                if r:\n                    results.append(r)\n                    if r.source_type != "invoice_page_pdf_fallback":\n                        has_official_success = True\n\n        # Post-process: if has_official_success is True, filter out and clean up any fallback results\n'''
replace_once(
    LINK,
    needle,
    '''                if r:\n                    results.append(r)\n                    if r.source_type != "invoice_page_pdf_fallback":\n                        has_official_success = True\n                if time.monotonic() >= email_deadline:\n                    timed_out = True\n\n        # Post-process: if has_official_success is True, filter out and clean up any fallback results\n''',
)
replace_once(
    LINK,
    '''                "链接下载达到单邮件耗时上限: attempted=%d elapsed=%.1fs limit=%.1fs",\n                attempted_count,\n                elapsed,\n                self._email_budget_seconds,\n''',
    '''                "链接下载达到单邮件浏览器处理预算: attempted=%d elapsed=%.1fs budget=%.1fs",\n                attempted_count,\n                elapsed,\n                self._email_budget_seconds,\n''',
)

# Focused tests: budget naming is explicit; legacy keys remain accepted for branch compatibility.
text = TESTS.read_text(encoding="utf-8")
text = text.replace("self._max_seconds_per_url", "self._url_budget_seconds")
text = text.replace("downloader._max_seconds_per_email", "downloader._email_budget_seconds")
TESTS.write_text(text, encoding="utf-8")

replace_once(
    TESTS,
    '''    def test_dns_safety_check_fails_closed_without_waiting_for_stuck_resolver(self):\n''',
    '''    def test_browser_budget_config_uses_truthful_names_and_keeps_legacy_aliases(self):\n        config = {\n            "link_download": {\n                "budget_seconds_per_url": 7,\n                "budget_seconds_per_email": 19,\n            }\n        }\n        with tempfile.TemporaryDirectory(prefix="invoice-hub-browser-budget-") as td, patch(\n            "scripts.invoice_fetch.config.load_config_safe", return_value=config\n        ):\n            downloader = LinkDownloader(td)\n        self.assertEqual(downloader._url_budget_seconds, 7.0)\n        self.assertEqual(downloader._email_budget_seconds, 19.0)\n\n        legacy_config = {\n            "link_download": {\n                "max_seconds_per_url": 8,\n                "max_seconds_per_email": 21,\n            }\n        }\n        with tempfile.TemporaryDirectory(prefix="invoice-hub-browser-budget-legacy-") as td, patch(\n            "scripts.invoice_fetch.config.load_config_safe", return_value=legacy_config\n        ):\n            legacy = LinkDownloader(td)\n        self.assertEqual(legacy._url_budget_seconds, 8.0)\n        self.assertEqual(legacy._email_budget_seconds, 21.0)\n\n    def test_download_save_helper_does_not_advertise_an_unenforced_timeout(self):\n        signature = inspect.signature(link_downloader._save_download_to_path)\n        self.assertNotIn("timeout_ms", signature.parameters)\n\n    def test_example_config_calls_scan_limits_budgets_not_hard_deadlines(self):\n        source = Path("config.example.json").read_text(encoding="utf-8")\n        self.assertIn('"budget_seconds_per_url": 20', source)\n        self.assertIn('"budget_seconds_per_email": 60', source)\n        self.assertNotIn('"max_seconds_per_url"', source)\n        self.assertNotIn('"max_seconds_per_email"', source)\n\n    def test_dns_safety_check_fails_closed_without_waiting_for_stuck_resolver(self):\n''',
)

print("mail scan budget truth patch applied")
