# -*- coding: utf-8 -*-
"""Link downloader: extract invoice URLs from email HTML and download PDFs."""

from __future__ import annotations

import base64
import hashlib
import io
import ipaddress
import logging
import os
import re
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from .log_privacy import mask_filename, mask_url_for_log

_log = logging.getLogger(__name__)


@dataclass
class DownloadedFile:
    url: str
    file_path: str
    filename: str
    size: int
    is_invoice: bool = False


_LINK_KEYWORDS = [
    "\u53d1\u7968",
    "invoice",
    "fapiao",
    "\u7535\u5b50\u53d1\u7968",
    "einvoice",
    "\u4e0b\u8f7d\u53d1\u7968",
    "\u67e5\u770b\u53d1\u7968",
    "\u884c\u7a0b\u5355",
    "\u884c\u7a0b\u8bb0\u5f55",
    "\u6c34\u5355",
    "folio",
    "receipt",
    "ofd",
    ".pdf",
    "\u7a0e\u52a1",
    "nuonuo",
    "baiwang",
    "51fapiao",
]

_EXCLUDE_PATTERNS = [
    "unsubscribe",
    "feedback",
    "survey",
    "ads",
    "click.email",
    "track.",
    "beacon.",
    "pixel",
    "campaign",
    "promo",
    "marketing",
    "analytics",
    "adclick",
    "clickrecord",
    "cmbchina.com",
    "cmbimg.com",
    "icbc.com.cn",
    "ccb.com",
    "boc.cn",
    "abchina.com",
    "psbc.com",
    "creditbill",
    "creditcard",
    "linkedin.com",
    "facebook.com",
    "weibo.",
    "mail.qq.com",
    "exmail.qq.com",
]

_SAFE_URL_SCHEMES = {"http", "https"}
_SKIP_URL_PATTERNS = ["tydl-login", "/login", "/register"]
_TECHNICAL_HOST_SUFFIXES = (
    "github.com",
    "githubusercontent.com",
    "gitlab.com",
    "gitee.com",
    "bitbucket.org",
)
_INVOICE_HOST_MARKERS = (
    "51fapiao",
    "fapiao",
    "nuonuo",
    "baiwang",
    "jss.com.cn",
    "chinatax",
    "12306",
    "railway",
)
_TRACKING_QUERY_KEYS = {
    "spm", "utm_source", "utm_medium",
    "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid",
}


def _is_safe_download_url(url: str) -> bool:
    """Allow only public HTTP(S) URLs without credentials."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _SAFE_URL_SCHEMES:
        return False
    if not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.strip().lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in _TECHNICAL_HOST_SUFFIXES):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def extract_links_from_html(html: str) -> list[str]:
    """Extract invoice-related URLs from email HTML body."""
    if not html:
        return []
    links: list[str] = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            url = a["href"].strip()
            text = a.get_text(strip=True)
            if not url or url.startswith(("mailto:", "#")):
                continue
            if not _is_safe_download_url(url):
                continue
            parsed = urlparse(url)
            combined = " ".join(
                (parsed.path, parsed.query, parsed.fragment, text)
            ).lower()
            host = (parsed.hostname or "").lower()
            has_invoice_host = any(marker in host for marker in _INVOICE_HOST_MARKERS)
            has_invoice_context = any(
                kw.lower() in combined for kw in _LINK_KEYWORDS
            )
            if has_invoice_host or has_invoice_context:
                if not any(ex in url.lower() for ex in _EXCLUDE_PATTERNS):
                    links.append(url)
    except Exception as exc:
        _log.warning("HTML link parse failed: %s", exc)
    return links


def extract_html_from_message(msg) -> str:
    """Pull the HTML body from an email.message.Message."""
    parts: list[str] = []

    def _decode(part):
        payload = part.get_payload(decode=True)
        if not payload:
            return ""
        charset = part.get_content_charset() or "utf-8"
        for enc in [charset, "utf-8", "gbk", "gb2312"]:
            try:
                return payload.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return ""

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                s = _decode(part)
                if s:
                    parts.append(s)
    elif msg.get_content_type() == "text/html":
        s = _decode(msg)
        if s:
            parts.append(s)

    return "\n".join(parts)


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    filtered = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not (k.lower() in _TRACKING_QUERY_KEYS or k.lower().startswith("utm_"))
    ]
    return urlunparse(parsed._replace(query=urlencode(filtered, doseq=True), fragment=""))


def _dedup_and_prioritize(links: list[str]) -> list[str]:
    seen = set()
    direct: list[str] = []
    other: list[str] = []
    for url in links:
        if not _is_safe_download_url(url):
            continue
        canon = _canonical_url(url).rstrip("/")
        if canon in seen:
            continue
        seen.add(canon)
        low = url.lower()
        if any(pat in low for pat in _SKIP_URL_PATTERNS):
            continue
        if any(d in low for d in ["dlj.", "nnfp.", "/dlj/", "/download"]):
            direct.append(url)
        else:
            other.append(url)
    return direct + other


def _save_download_to_path(download, dest: Path) -> bool:
    """Persist a Playwright download to *dest* without leaking callback errors."""
    if dest.exists():
        return True
    try:
        download.save_as(str(dest))
        return True
    except Exception as exc:
        _log.warning("Download save failed for %s: %s", mask_filename(dest.name), exc)
        return False


class LinkDownloader:
    """Download invoice PDFs from URLs using a headless browser."""

    def __init__(self, download_dir: str | Path, timeout_ms: int = 30_000, headed: bool = False):
        self._dir = Path(download_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        # Per-config capacity limits (can be overridden via config)
        from .config import load_config_safe
        cfg = load_config_safe()
        link_cfg = cfg.get("link_download", {}) if isinstance(cfg, dict) else {}
        self._timeout = timeout_ms
        cfg_timeout = link_cfg.get("timeout_ms")
        if cfg_timeout is not None:
            self._timeout = int(cfg_timeout)
        self._max_links_per_email = int(link_cfg.get("max_links_per_email", 5))
        self._skip_when_attachment_invoice_present = bool(
            link_cfg.get("skip_when_attachment_invoice_present", True)
        )
        self._pw = None
        self._browser = None
        self._headed = headed
        # Per-process failed URL fingerprint cache — avoid retrying known failures
        self.failed_url_fingerprints: set[str] = set()

    @staticmethod
    def _url_fingerprint(url: str) -> str:
        """Return a hashed fingerprint for a URL — deterministic, not reversible."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _ensure_browser(self):
        if self._browser:
            return
        from playwright.sync_api import sync_playwright
        from .config import load_config_safe

        cfg = load_config_safe()
        channel = cfg.get("playwright", {}).get("channel", "auto")

        self._pw = sync_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
        ]

        def _launch_browser(channel_name: str | None, label: str) -> None:
            kwargs = {
                "headless": not self._headed,
                "args": launch_args,
            }
            if channel_name:
                kwargs["channel"] = channel_name
            self._browser = self._pw.chromium.launch(**kwargs)
            _log.info(
                "Playwright browser started using %s (headless=%s)",
                label,
                not self._headed,
            )

        # 1. If an explicit channel is configured, honor it first.
        if channel not in {"auto", "chromium"}:
            try:
                _launch_browser(channel, f"configured channel '{channel}'")
                return
            except Exception as exc:
                _log.warning(
                    "Failed to launch configured channel '%s': %s. Falling back to auto.",
                    channel,
                    exc,
                )

        # 2. If the user explicitly asked for Chromium, do not change that contract.
        if channel == "chromium":
            try:
                _launch_browser(None, "default Chromium")
                return
            except Exception as exc:
                raise RuntimeError(
                    "未找到可用浏览器。请安装 Microsoft Edge / Google Chrome，或在设置中配置浏览器通道。"
                    f" (错误详情: 默认 Chromium 启动失败 - {exc})"
                ) from exc

        # 3. Auto mode: prefer the browser most Windows users already have.
        last_exc: Exception | None = None
        for channel_name, label in (
            ("msedge", "system Microsoft Edge"),
            ("chrome", "system Google Chrome"),
            (None, "default Chromium"),
        ):
            try:
                _launch_browser(channel_name, label)
                return
            except Exception as exc:
                last_exc = exc
                _log.warning("%s failed: %s", label, exc)

        raise RuntimeError(
            "未找到可用浏览器。请安装 Microsoft Edge / Google Chrome，或在设置中配置浏览器通道。"
            f" (错误详情: {last_exc})"
        ) from last_exc

    def close(self):
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def download_from_email(self, msg, mail_uid: int, date_str: str = "") -> list[DownloadedFile]:
        html = extract_html_from_message(msg)
        if not html:
            return []

        raw_links = extract_links_from_html(html)
        links = _dedup_and_prioritize(raw_links)
        if not links:
            return []

        found = len(raw_links)
        deduped = len(links)

        results: list[DownloadedFile] = []
        skipped_cached = 0
        start_time = time.perf_counter()
        for i, url in enumerate(links):
            if len(results) >= self._max_links_per_email:
                break
            # Skip URLs that already failed this session
            fp = self._url_fingerprint(url)
            if fp in self.failed_url_fingerprints:
                skipped_cached += 1
                _log.info("跳过本轮已失败链接: <%s>", fp)
                continue
            r = self._download_url(url, mail_uid, i, date_str)
            if r:
                results.append(r)

        elapsed = time.perf_counter() - start_time
        success = len(results)
        failed = len(links) - success - skipped_cached
        _log.info(
            "链接下载摘要: found=%d deduped=%d success=%d failed=%d skipped_cached=%d elapsed=%.1fs",
            found, deduped, success, failed, skipped_cached, elapsed,
        )
        return results

    def _download_url(self, url: str, mail_uid: int, idx: int, date_str: str) -> DownloadedFile | None:
        if not _is_safe_download_url(url):
            _log.warning("Skipping unsafe link: %s", mask_url_for_log(url))
            return None

        _log.info("Browser download: %s", mask_url_for_log(url))

        try:
            self._ensure_browser()
        except Exception as exc:
            _log.error("Playwright start failed: %s", exc)
            return None

        save_dir = self._dir / (date_str or "unknown_date")
        save_dir.mkdir(parents=True, exist_ok=True)

        ctx = None
        try:
            desktop_ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            ctx = self._browser.new_context(accept_downloads=True, user_agent=desktop_ua)
            page = ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            downloaded_path: str | None = None
            download_started = False
            download_done = threading.Event()

            def _on_download(download):
                nonlocal downloaded_path, download_started
                download_started = True
                fname = download.suggested_filename or f"invoice_{mail_uid}_{idx}.pdf"
                dest = save_dir / fname
                if dest.exists():
                    downloaded_path = str(dest)
                    download_done.set()
                    return
                if _save_download_to_path(download, dest):
                    downloaded_path = str(dest)
                download_done.set()

            page.on("download", _on_download)

            try:
                page.goto(url, wait_until="networkidle", timeout=self._timeout)
            except Exception:
                pass

            if not downloaded_path:
                page.wait_for_timeout(3000)
            if not downloaded_path:
                self._try_click_download(page)
            if not downloaded_path:
                downloaded_path = self._try_extract_embedded_pdf(page, save_dir, mail_uid, idx)
            if not downloaded_path:
                downloaded_path = self._try_page_print_pdf(page, save_dir, mail_uid, idx)
            if download_started and not downloaded_path:
                download_done.wait(timeout=5)

            if downloaded_path and os.path.exists(downloaded_path):
                size = os.path.getsize(downloaded_path)
                if size < 500:
                    os.remove(downloaded_path)
                    self.failed_url_fingerprints.add(self._url_fingerprint(url))
                    return None
                with open(downloaded_path, "rb") as f:
                    header = f.read(5)
                if header == b"%PDF-":
                    return DownloadedFile(
                        url=url,
                        file_path=downloaded_path,
                        filename=os.path.basename(downloaded_path),
                        size=size,
                        is_invoice=True,
                    )
                os.remove(downloaded_path)
            # Cache the failure fingerprint to avoid re-attempting in this session
            self.failed_url_fingerprints.add(self._url_fingerprint(url))
            return None
        except Exception as exc:
            _log.debug("Browser download failed for <%s>: %s", self._url_fingerprint(url), exc)
            self.failed_url_fingerprints.add(self._url_fingerprint(url))
            return None
        finally:
            if ctx:
                ctx.close()

    def _try_click_download(self, page) -> None:
        selectors = [
            'a:has-text("涓嬭浇")',
            'button:has-text("涓嬭浇")',
            'a:has-text("鍙戠エ")',
            'button:has-text("鍙戠エ")',
            'a:has-text("PDF")',
            'button:has-text("PDF")',
            'text=涓嬭浇',
        ]
        for sel in selectors:
            try:
                locator = page.locator(sel)
                if locator.count() == 0:
                    continue
                locator.first.click(timeout=2000)
                time.sleep(1)
                return
            except Exception:
                continue

    def _try_extract_embedded_pdf(self, page, save_dir: Path, mail_uid: int, idx: int) -> str | None:
        try:
            html = page.content()
            m = re.search(r"data:application/pdf;base64,([A-Za-z0-9+/=]+)", html)
            if not m:
                return None
            payload = base64.b64decode(m.group(1))
            dest = save_dir / f"invoice_{mail_uid}_{idx}_embedded.pdf"
            dest.write_bytes(payload)
            return str(dest)
        except Exception:
            return None

    def _try_page_print_pdf(self, page, save_dir: Path, mail_uid: int, idx: int) -> str | None:
        _log.debug("Skipping webpage print-to-PDF fallback; official PDF/OFD download was not obtained.")
        return None
