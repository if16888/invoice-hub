from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = ROOT / "scripts/invoice_fetch/link_downloader.py"
CONFIG = ROOT / "config.example.json"
TESTS = ROOT / "tests/test_mail_scan_bounded_browser.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Response-time safety is owned by the URL/email browser-work budgets.  Preserve
# the pre-existing capacity of five candidate links so the shutdown hardening
# cannot silently discard a fourth or fifth legitimate invoice link.
replace_once(
    LINK,
    'self._max_links_per_email = max(1, int(link_cfg.get("max_links_per_email", 3)))',
    'self._max_links_per_email = max(1, int(link_cfg.get("max_links_per_email", 5)))',
)
replace_once(
    CONFIG,
    '    "max_links_per_email": 3,\n',
    '    "max_links_per_email": 5,\n',
)

anchor = '''    def test_download_save_helper_does_not_advertise_an_unenforced_timeout(self):\n'''
insert = '''    def test_default_capacity_preserves_five_candidate_links_until_budget_stops_work(self):\n        downloader = self._downloader(Path("bounded-browser-five-link-capacity"))\n        self.assertEqual(downloader._max_links_per_email, 5)\n        msg = EmailMessage()\n        msg["Subject"] = "invoice bundle"\n        raw = [\n            {"url": f"https://example.com/invoice-{idx}", "text": "invoice"}\n            for idx in range(5)\n        ]\n        attempts: list[str] = []\n\n        def attempt(url, *_args, **_kwargs):\n            attempts.append(url)\n            return None\n\n        with patch.object(\n            link_downloader, "extract_html_from_message", return_value="<html></html>"\n        ), patch.object(\n            link_downloader,\n            "_extract_links_with_metadata_from_html_and_stats",\n            return_value=(raw, {"anchor_count": 5, "unsafe_skipped": 0, "excluded_skipped": 0}),\n        ), patch.object(\n            link_downloader,\n            "_dedup_and_prioritize_with_metadata",\n            return_value=(raw, []),\n        ), patch.object(downloader, "_download_url", side_effect=attempt):\n            downloader.download_from_email(msg, 1, "2026-09-12")\n\n        self.assertEqual(attempts, [item["url"] for item in raw])\n\n'''
replace_once(TESTS, anchor, insert + anchor)

print("mail link capacity restore applied")
