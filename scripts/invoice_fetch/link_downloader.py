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
import socket
import time
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from .log_privacy import mask_filename, mask_sender_header, mask_url_for_log, redact_text

_log = logging.getLogger(__name__)


@dataclass
class DownloadedFile:
    url: str
    file_path: str
    filename: str
    size: int
    is_invoice: bool = False
    source_type: str | None = None
    parse_note: str | None = None


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
    "\u9910\u8d39",
    "\u9910\u996e",
    "\u7528\u9910",
    "\u5c0f\u7968",
    "\u7535\u5b50\u5c0f\u7968",
    "\u6d88\u8d39\u51ed\u8bc1",
    "\u8ba2\u5355\u8be6\u60c5",
    "\u652f\u4ed8\u51ed\u8bc1",
    "meal",
    "catering",
    "food",
    "train",
    "rail",
    "\u9ad8\u94c1",
    "\u94c1\u8def",
    "\u52a8\u8f66",
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
    return ip.is_global


@lru_cache(maxsize=256)
def _host_resolves_to_public_addresses(host: str, port: int) -> bool:
    """Fail closed unless every resolved address is publicly routable."""
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        return literal_ip.is_global

    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {record[4][0] for record in records if record[4]}
    if not addresses:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _is_safe_browser_request_url(url: str) -> bool:
    """Allow browser-internal resources and public HTTP(S) destinations."""
    parsed = urlparse(str(url or ""))
    scheme = parsed.scheme.lower()
    if scheme in {"about", "blob", "data"}:
        return True
    if not _is_safe_download_url(url):
        return False
    port = parsed.port or (443 if scheme == "https" else 80)
    return _host_resolves_to_public_addresses(parsed.hostname or "", port)


def _route_browser_request(route) -> None:
    """Abort browser requests that target local or otherwise unsafe URLs."""
    url = str(route.request.url or "")
    if _is_safe_browser_request_url(url):
        route.continue_()
        return
    fingerprint = hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()[:16]
    _log.warning("Blocked unsafe browser request: <%s>", fingerprint)
    route.abort("blockedbyclient")


def _safe_download_destination(
    save_dir: str | Path,
    suggested_filename: str,
    fallback_filename: str,
) -> Path:
    """Return a sanitized download path contained by *save_dir*."""
    root = Path(save_dir).resolve()
    raw_name = str(suggested_filename or fallback_filename or "").replace("\\", "/")
    basename = raw_name.rsplit("/", 1)[-1]
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", basename).strip(" .")
    if not safe_name or safe_name in {".", ".."}:
        safe_name = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]',
            "_",
            str(fallback_filename or "invoice_download"),
        ).strip(" .")

    candidate = (root / safe_name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        candidate = (root / Path(fallback_filename or "invoice_download").name).resolve()
    return candidate


def _extract_links_with_metadata_from_html_and_stats(html: str) -> tuple[list[dict], dict]:
    if not html:
        return [], {
            "anchor_count": 0,
            "unsafe_skipped": 0,
            "excluded_skipped": 0,
        }
    results: list[dict] = []
    unsafe_skipped = 0
    excluded_skipped = 0
    try:
        soup = BeautifulSoup(html, "html.parser")
        anchors = soup.find_all("a", href=True)
        for a in anchors:
            url = a["href"].strip()
            text = a.get_text(strip=True)
            if not url or url.startswith(("mailto:", "#")):
                continue
            if not _is_safe_download_url(url):
                unsafe_skipped += 1
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
                    results.append({"url": url, "text": text})
                else:
                    excluded_skipped += 1
    except Exception as exc:
        _log.warning("HTML link parse failed: %s", exc)
        return [], {
            "anchor_count": 0,
            "unsafe_skipped": unsafe_skipped,
            "excluded_skipped": excluded_skipped,
        }
    return results, {
        "anchor_count": len(anchors) if "anchors" in locals() else 0,
        "unsafe_skipped": unsafe_skipped,
        "excluded_skipped": excluded_skipped,
    }


def extract_links_with_metadata_from_html(html: str) -> list[dict]:
    """Extract invoice-related URLs along with their anchor text from email HTML body."""
    results, _stats = _extract_links_with_metadata_from_html_and_stats(html)
    return results


def extract_links_from_html(html: str) -> list[str]:
    """Extract invoice-related URLs from email HTML body."""
    return [item["url"] for item in extract_links_with_metadata_from_html(html)]


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


def _dedup_and_prioritize_with_metadata(raw_items: list[dict], is_nuonuo_sender: bool) -> tuple[list[dict], list[dict]]:
    seen = set()
    high_items: list[dict] = []
    low_items: list[dict] = []

    for item in raw_items:
        url = item["url"]
        text = item["text"]
        if not _is_safe_download_url(url):
            continue
        canon = _canonical_url(url).rstrip("/")
        if canon in seen:
            continue
        seen.add(canon)

        url_lower = url.lower()
        if any(pat in url_lower for pat in _SKIP_URL_PATTERNS):
            continue

        # Check low priority keywords
        low_priority_keywords = [
            "了解诺诺", "官网", "帮助", "广告", "营销", "用户协议", "隐私政策",
            "baoxiao", "ntf", "bmjc"
        ]
        combined_text = (text + " " + url_lower).lower()
        special_priority_keywords = [
            "receipt", "meal", "catering", "food", "train", "rail", "高铁", "铁路", "动车",
            "餐费", "餐饮", "用餐", "小票", "电子小票", "消费凭证", "订单详情", "支付凭证",
        ]
        is_low = any(kw in combined_text for kw in low_priority_keywords) and not any(
            kw in combined_text for kw in special_priority_keywords
        )

        if is_low:
            low_items.append(item)
        else:
            high_items.append(item)

    # Sort high_items
    def get_sort_key(item):
        url = item["url"]
        text = item["text"]
        url_lower = url.lower()

        # Rule 1: Nuonuo sender prioritization
        rule1_match = 0
        if is_nuonuo_sender and "nnfp.jss.com.cn/scan-invoice/invoiceshow" in url_lower:
            rule1_match = 1

        # Rule 2: High priority anchor/URL keywords
        rule2_match = 0
        high_text_kws = ["下载发票", "查看发票", "电子发票", "发票下载", "pdf", "ofd"]
        high_url_kws = ["invoice", "fp", "fapiao", "scan-invoice", "invoiceshow"]

        if any(kw in text.lower() for kw in high_text_kws) or any(kw in url_lower for kw in high_url_kws):
            rule2_match = 1

        return (rule1_match, rule2_match)

    high_items.sort(key=get_sort_key, reverse=True)
    return high_items, low_items


def _dedup_and_prioritize(links: list[str]) -> list[str]:
    raw_items = [{"url": u, "text": ""} for u in links]
    high, low = _dedup_and_prioritize_with_metadata(raw_items, is_nuonuo_sender=False)
    return [item["url"] for item in high] + [item["url"] for item in low]


def _download_result_sort_key(item: DownloadedFile) -> tuple[int, int, int, str]:
    name = Path(item.filename or item.file_path or "").name
    suffix = Path(name).suffix.lower()
    ext_rank = {
        ".pdf": 0,
        ".ofd": 1,
    }.get(suffix, 2)
    source_rank = {
        "official_download": 0,
        "official_response": 1,
        "embedded_pdf": 2,
        "invoice_page_pdf_fallback": 3,
    }.get(str(item.source_type or ""), 4)
    return (ext_rank, source_rank, -int(item.size or 0), name.lower())


def _are_stems_homologous(pdf_stem: str, ofd_stem: str) -> bool:
    """Check if a PDF filename stem and an OFD filename stem are homologous (same source)."""
    p_lower = pdf_stem.lower().strip()
    o_lower = ofd_stem.lower().strip()
    if p_lower == o_lower:
        return True

    # 1. Check digit-normalized pattern equivalence (e.g. invoice_77_0_resp vs invoice_77_1_resp)
    p_norm = re.sub(r'\d+', '#', p_lower)
    o_norm = re.sub(r'\d+', '#', o_lower)
    if p_norm == o_norm:
        return True

    # 2. Check substring homology (e.g. 狮王府电子发票.pdf vs 电子发票.ofd)
    # The shorter stem must have a minimum length of 4 to prevent false positive matches
    if len(p_lower) >= 4 and len(o_lower) >= 4:
        if p_lower in o_lower or o_lower in p_lower:
            return True

    return False


def _dedupe_downloaded_files(results: list[DownloadedFile]) -> list[DownloadedFile]:
    # Group results by suffix
    pdfs = []
    ofds = []
    others = []
    for item in results:
        name = item.filename or item.file_path or ""
        suffix = Path(name).suffix.lower()
        if suffix == ".pdf":
            pdfs.append(item)
        elif suffix == ".ofd":
            ofds.append(item)
        else:
            others.append(item)

    # 1. Deduplicate pdfs by stem, keeping the one with best priority (smaller sort key)
    best_pdf_by_stem: dict[str, DownloadedFile] = {}
    for item in pdfs:
        stem = Path(item.filename or item.file_path or "").stem.lower()
        if stem not in best_pdf_by_stem:
            best_pdf_by_stem[stem] = item
        else:
            if _download_result_sort_key(item) < _download_result_sort_key(best_pdf_by_stem[stem]):
                best_pdf_by_stem[stem] = item
    unique_pdfs = list(best_pdf_by_stem.values())

    # 2. Deduplicate ofds by stem, keeping the one with best priority
    best_ofd_by_stem: dict[str, DownloadedFile] = {}
    for item in ofds:
        stem = Path(item.filename or item.file_path or "").stem.lower()
        if stem not in best_ofd_by_stem:
            best_ofd_by_stem[stem] = item
        else:
            if _download_result_sort_key(item) < _download_result_sort_key(best_ofd_by_stem[stem]):
                best_ofd_by_stem[stem] = item
    unique_ofds = list(best_ofd_by_stem.values())

    # 3. Match OFDs with homologous PDFs and mark for discard
    discarded_ofd_ids = set()

    # Special Rule: If exactly 1 PDF and 1 OFD total in the batch, prioritize PDF and discard OFD.
    if len(unique_pdfs) == 1 and len(unique_ofds) == 1:
        discarded_ofd_ids.add(id(unique_ofds[0]))
        _log.info(
            "PDF/OFD Deduplication: Exactly 1 PDF and 1 OFD found. Retaining PDF '%s' and discarding OFD '%s'",
            mask_filename(unique_pdfs[0].filename),
            mask_filename(unique_ofds[0].filename)
        )
    else:
        for ofd in unique_ofds:
            ofd_stem = Path(ofd.filename or ofd.file_path or "").stem
            matched_pdf = None
            for pdf in unique_pdfs:
                pdf_stem = Path(pdf.filename or pdf.file_path or "").stem
                if _are_stems_homologous(pdf_stem, ofd_stem):
                    matched_pdf = pdf
                    break
            if matched_pdf:
                discarded_ofd_ids.add(id(ofd))
                _log.info(
                    "PDF/OFD Deduplication: Found homologous PDF '%s' for OFD '%s'. Discarding OFD.",
                    mask_filename(matched_pdf.filename),
                    mask_filename(ofd.filename)
                )
            else:
                _log.info(
                    "PDF/OFD Deduplication: OFD '%s' has no homologous PDF. Keeping it.",
                    mask_filename(ofd.filename)
                )

    # Reconstruct the list preserving the original order of items that are kept
    final_results = []
    seen_ids = set()
    for item in results:
        item_id = id(item)
        if item_id in seen_ids:
            continue
        is_kept_pdf = any(id(p) == item_id for p in unique_pdfs)
        is_kept_ofd = any(id(o) == item_id for o in unique_ofds) and item_id not in discarded_ofd_ids
        is_other = any(id(x) == item_id for x in others)

        if is_kept_pdf or is_kept_ofd or is_other:
            final_results.append(item)
            seen_ids.add(item_id)
    return final_results


def _save_download_to_path(download, dest: Path, timeout_ms: int = 30_000) -> bool:
    """Persist a Playwright download to *dest* without leaking callback errors."""
    if dest.exists():
        return True
    result: dict[str, object] = {"ok": False, "error": None}

    def _worker() -> None:
        try:
            download.save_as(str(dest))
            result["ok"] = True
        except Exception as exc:
            result["error"] = exc

    timeout_seconds = max(0.001, float(timeout_ms or 30_000) / 1000.0)
    thread = threading.Thread(target=_worker, name="invoice-download-save", daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        _log.warning(
            "Download save timed out for %s after %.1fs",
            mask_filename(dest.name),
            timeout_seconds,
        )
        return False
    if result["ok"]:
        return True
    if result["error"] is not None:
        _log.warning("Download save failed for %s: %s", mask_filename(dest.name), result["error"])
        return False
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
        self._max_seconds_per_email = float(link_cfg.get("max_seconds_per_email", 120))
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

def _verify_and_clean_file(path: str | Path) -> bool:
    """Validate if file is a valid PDF or OFD. Delete if invalid."""
    p = Path(path)
    if not p.exists():
        return False
    size = p.stat().st_size
    if size < 500:
        try:
            p.unlink()
        except Exception:
            pass
        return False
    try:
        with open(p, "rb") as f:
            header = f.read(5)
        is_pdf = header.startswith(b"%PDF")
        is_zip = header.startswith(b"PK\x03\x04")
        is_ofd = False
        if is_zip:
            content = p.read_bytes()
            if b"ofd.xml" in content or b"OFD.xml" in content:
                is_ofd = True
        if is_pdf or is_ofd:
            return True
        else:
            try:
                p.unlink()
            except Exception:
                pass
            return False
    except Exception:
        try:
            p.unlink()
        except Exception:
            pass
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
        self._max_seconds_per_email = float(link_cfg.get("max_seconds_per_email", 120))
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
        subject = ""
        sender = ""
        if msg:
            if hasattr(msg, "get"):
                try:
                    subject = msg.get("Subject", "") or ""
                except Exception:
                    pass
            if hasattr(msg, "get"):
                try:
                    sender = msg.get("From", "") or ""
                except Exception:
                    pass
            elif hasattr(msg, "__getitem__"):
                try:
                    sender = msg["From"] or ""
                except Exception:
                    pass
        is_nuonuo_sender = "invoice@info.nuonuo.com" in str(sender)

        html = extract_html_from_message(msg)
        raw_stats = {
            "anchor_count": 0,
            "unsafe_skipped": 0,
            "excluded_skipped": 0,
        }
        self.last_download_diagnostics = {
            "found_links": 0,
            "candidate_links": 0,
            "attempted": 0,
            "failed": 0,
        }
        if html:
            raw_items, raw_stats = _extract_links_with_metadata_from_html_and_stats(html)
        else:
            raw_items = []

        if not raw_items:
            _log.info(
                "Link download diagnostic: subject=%s sender=%s found_links=%d candidate_links=0 skipped_unsafe=%d skipped_low_priority=0 attempted=0 failed=0",
                redact_text(subject, "subject"),
                mask_sender_header(sender),
                raw_stats.get("anchor_count", 0),
                raw_stats.get("unsafe_skipped", 0),
            )
            return []

        high_items, low_items = _dedup_and_prioritize_with_metadata(raw_items, is_nuonuo_sender)

        found = len(raw_items)
        deduped = len(high_items) + len(low_items)
        prioritized = len(high_items)

        results: list[DownloadedFile] = []
        skipped_cached = 0
        attempted_count = 0
        low_priority_skipped = 0
        has_official_success = False
        timed_out = False

        start_time = time.perf_counter()

        def email_budget_exhausted() -> bool:
            if self._max_seconds_per_email <= 0 or attempted_count == 0:
                return False
            return (time.perf_counter() - start_time) >= self._max_seconds_per_email

        # 1. Try high priority links first
        high_success = False
        for item in high_items:
            if attempted_count >= self._max_links_per_email:
                break
            if email_budget_exhausted():
                timed_out = True
                break
            url = item["url"]
            fp = self._url_fingerprint(url)
            if fp in self.failed_url_fingerprints:
                skipped_cached += 1
                _log.info("跳过本轮已失败链接: <%s>", fp)
                continue
            attempted_count += 1
            r = self._download_url(url, mail_uid, len(results), date_str, disable_fallback=has_official_success)
            if r:
                results.append(r)
                high_success = True
                if r.source_type != "invoice_page_pdf_fallback":
                    has_official_success = True

        # 2. Try low priority links if no high priority links succeeded and limit not reached
        if high_success:
            low_priority_skipped = len(low_items)
        else:
            for item in low_items:
                if attempted_count >= self._max_links_per_email:
                    low_priority_skipped += 1
                    continue
                if email_budget_exhausted():
                    timed_out = True
                    low_priority_skipped += 1
                    continue
                url = item["url"]
                fp = self._url_fingerprint(url)
                if fp in self.failed_url_fingerprints:
                    skipped_cached += 1
                    _log.info("跳过本轮已失败链接: <%s>", fp)
                    continue
                attempted_count += 1
                r = self._download_url(url, mail_uid, len(results), date_str, disable_fallback=has_official_success)
                if r:
                    results.append(r)
                    if r.source_type != "invoice_page_pdf_fallback":
                        has_official_success = True

        # Post-process: if has_official_success is True, filter out and clean up any fallback results
        if has_official_success:
            filtered_results = []
            for r in results:
                if r.source_type == "invoice_page_pdf_fallback":
                    try:
                        if os.path.exists(r.file_path):
                            os.unlink(r.file_path)
                    except Exception:
                        pass
                else:
                    filtered_results.append(r)
            results = filtered_results

        before_dedupe_count = len(results)
        results = _dedupe_downloaded_files(results)
        deduped_removed = max(0, before_dedupe_count - len(results))

        elapsed = time.perf_counter() - start_time
        success = len(results)
        failed = max(0, attempted_count - success - deduped_removed)
        self.last_download_diagnostics = {
            "found_links": found,
            "candidate_links": deduped,
            "attempted": attempted_count,
            "failed": failed,
            "timed_out": timed_out,
            "elapsed": elapsed,
        }
        official_success = sum(1 for r in results if r.source_type != "invoice_page_pdf_fallback")
        fallback_success = sum(1 for r in results if r.source_type == "invoice_page_pdf_fallback")
        _log.info(
            "链接下载摘要: found=%d deduped=%d success=%d official_success=%d fallback_success=%d failed=%d skipped_cached=%d attempted=%d prioritized=%d low_priority_skipped=%d elapsed=%.1fs",
            found, deduped, success, official_success, fallback_success, failed, skipped_cached, attempted_count, prioritized, low_priority_skipped, elapsed,
        )
        if timed_out:
            _log.warning(
                "链接下载达到单邮件耗时上限: attempted=%d elapsed=%.1fs limit=%.1fs",
                attempted_count,
                elapsed,
                self._max_seconds_per_email,
            )
        if success == 0:
            _log.info(
                "Link download diagnostic: subject=%s sender=%s found_links=%d candidate_links=%d skipped_unsafe=%d skipped_low_priority=%d attempted=%d failed=%d",
                redact_text(subject, "subject"),
                mask_sender_header(sender),
                found,
                deduped,
                raw_stats.get("unsafe_skipped", 0),
                low_priority_skipped,
                attempted_count,
                failed,
            )
        return results

    def _handle_nuonuo_invoice_page(self, page, url: str, save_dir: Path, mail_uid: int, idx: int, disable_fallback: bool = False) -> tuple[str | None, str | None, str | None] | None:
        """ Nuonuo/JSS site specific downloader handler """
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        try:
            page.wait_for_timeout(2000)
        except Exception:
            pass

        try:
            texts = []
            try:
                t_main = page.evaluate("() => document.body.innerText") or ""
                texts.append(t_main)
            except Exception:
                pass
            for frame in page.frames:
                try:
                    t_frame = frame.evaluate("() => document.body.innerText") or ""
                    texts.append(t_frame)
                except Exception:
                    pass
            page_text = "\n".join(texts)
        except Exception:
            page_text = ""

        features = [
            "电子发票", "发票", "发票号码", "开票日期", "销售方", "价税合计",
            "购买方", "金额", "合计金额", "销方", "购方"
        ]
        matched_features = [f for f in features if f in page_text]

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
        is_candidate = (
            any(d in host for d in ["nnfp.jss.com.cn", "jss.com.cn", "nuonuo.com"])
            or any(p in path for p in ["scan-invoice", "invoiceshow", "invoice", "fp"])
        )

        clean_path = path.strip().rstrip("/")
        is_explicit_invoice_url = False
        if host == "nnfp.jss.com.cn" or host.endswith(".nnfp.jss.com.cn") or host == "fp.nuonuo.com" or host.endswith(".fp.nuonuo.com"):
            if (clean_path and clean_path not in ("/index.html", "/index.htm", "/index")) or parsed.query:
                is_explicit_invoice_url = True

        if not is_explicit_invoice_url:
            if any(d in host for d in ["nnfp.jss.com.cn", "jss.com.cn"]):
                if any(p in path for p in ["scan-invoice", "invoiceshow", "invoice"]):
                    is_explicit_invoice_url = True
            elif "nuonuo.com" in host and "fp" in host:
                if any(p in path for p in ["scan-invoice", "invoiceshow", "invoice"]):
                    is_explicit_invoice_url = True

        if not is_explicit_invoice_url:
            if not (is_candidate and len(matched_features) >= 2):
                _log.debug("页面不匹配发票页面特征，跳过站点级处理器")
                return None

        _log.info("诺诺/JSS 发票页面识别成功，尝试站点级下载")

        captured_files = []
        def on_response(response):
            try:
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "").lower()
                url_lower = response.url.lower()

                is_target = False
                if "application/pdf" in ct or "application/ofd" in ct:
                    is_target = True
                elif "application/octet-stream" in ct:
                    if any(kw in url_lower for kw in ["pdf", "ofd", "download", "invoice"]):
                        is_target = True
                elif any(kw in url_lower for kw in ["pdf", "ofd", "/download"]):
                    is_target = True

                if is_target:
                    body = response.body()
                    if len(body) > 100:
                        is_pdf = body.startswith(b"%PDF")
                        is_zip = body.startswith(b"PK\x03\x04")
                        is_ofd = False
                        if is_zip and (b"ofd.xml" in body or b"OFD.xml" in body):
                            is_ofd = True
                        if is_pdf or is_ofd:
                            ext = ".pdf" if is_pdf else ".ofd"
                            fname = f"invoice_{mail_uid}_{idx}_resp{ext}"
                            dest = save_dir / fname
                            dest.write_bytes(body)
                            captured_files.append(str(dest))
            except Exception:
                pass

        page.on("response", on_response)

        # 1. Try clicking download button
        try:
            selectors = [
                'text="下载发票"',
                'text="下载PDF"',
                'text="PDF下载"',
                'text="OFD下载"',
                'text="下载"',
                'text="PDF"',
                'text="OFD"',
                'a:has-text("下载")',
                'button:has-text("下载")',
                'a:has-text("PDF")',
                'button:has-text("PDF")',
            ]
            for sel in selectors:
                locator = page.locator(sel)
                if locator.count() > 0:
                    try:
                        with page.expect_download(timeout=3000) as download_info:
                            locator.first.click()
                        if download_info:
                            download = download_info.value
                            dest = _safe_download_destination(
                                save_dir,
                                download.suggested_filename,
                                f"invoice_{mail_uid}_{idx}.pdf",
                            )
                            if _save_download_to_path(download, dest, self._timeout):
                                if _verify_and_clean_file(dest):
                                    _log.info("已点击页面下载按钮并捕获文件")
                                    return str(dest), "official_download", None
                    except Exception:
                        pass
                    break
        except Exception as e:
            _log.debug("点击页面下载按钮失败: %s", e)

        # Short wait to collect responses
        page.wait_for_timeout(2000)

        # Check captured responses
        for f in captured_files:
            if _verify_and_clean_file(f):
                _log.info("已从网络响应捕获官方 PDF/OFD")
                return f, "official_response", None

        # 2. Try iframe blob fetching inside its own frame context
        for frame in page.frames:
            try:
                embed_sources = frame.evaluate("""() => {
                    const srcs = [];
                    document.querySelectorAll('iframe, embed, object').forEach(el => {
                        const src = el.src || el.data;
                        if (src) srcs.push(src);
                    });
                    return srcs;
                }""")
            except Exception:
                embed_sources = []

            for src in embed_sources:
                if src.startswith("blob:"):
                    try:
                        b64_data = frame.evaluate("""async (blobUrl) => {
                            const resp = await fetch(blobUrl);
                            const blob = await resp.blob();
                            return new Promise((resolve, reject) => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result.split(',')[1]);
                                reader.onerror = reject;
                                reader.readAsDataURL(blob);
                            });
                        }""", src)
                        if b64_data:
                            body = base64.b64decode(b64_data)
                            is_pdf = body.startswith(b"%PDF")
                            is_zip = body.startswith(b"PK\x03\x04")
                            is_ofd = False
                            if is_zip and (b"ofd.xml" in body or b"OFD.xml" in body):
                                is_ofd = True
                            if is_pdf or is_ofd:
                                ext = ".pdf" if is_pdf else ".ofd"
                                dest = save_dir / f"invoice_{mail_uid}_{idx}_blob{ext}"
                                dest.write_bytes(body)
                                _log.info("已从嵌入 PDF/OFD 资源保存文件")
                                return str(dest), "embedded_pdf", None
                    except Exception as e:
                        _log.debug("Fetch blob from frame context failed: %s", e)

        # 3. Controlled PDF Print Fallback
        if disable_fallback:
            allow_fallback = False
        else:
            from .config import load_config_safe
            cfg = load_config_safe()
            allow_fallback = True
            if isinstance(cfg, dict):
                if "link_download_allow_invoice_page_pdf_fallback" in cfg:
                    allow_fallback = bool(cfg["link_download_allow_invoice_page_pdf_fallback"])
                elif "link_download" in cfg and isinstance(cfg["link_download"], dict):
                    allow_fallback = bool(cfg["link_download"].get("allow_invoice_page_pdf_fallback", True))

        if allow_fallback:
            try:
                dest = save_dir / f"invoice_{mail_uid}_{idx}_page_fallback.pdf"
                page.pdf(path=str(dest))
                if _verify_and_clean_file(dest):
                    _log.info("发票展示页面已保存为 PDF fallback")
                    return str(dest), "invoice_page_pdf_fallback", "由发票展示页面保存为 PDF，建议核对原件"
            except Exception as e:
                _log.debug("PDF print fallback failed: %s", e)

        return None

    def _download_url(self, url: str, mail_uid: int, idx: int, date_str: str, disable_fallback: bool = False) -> DownloadedFile | None:
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
            ctx.set_default_timeout(self._timeout)
            ctx.set_default_navigation_timeout(self._timeout)
            page.route("**/*", _route_browser_request)
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            downloaded_path: str | None = None
            source_type: str | None = None
            parse_note: str | None = None
            download_started = False
            download_done = threading.Event()

            def _on_download(download):
                nonlocal downloaded_path, download_started
                download_started = True
                dest = _safe_download_destination(
                    save_dir,
                    download.suggested_filename,
                    f"invoice_{mail_uid}_{idx}.pdf",
                )
                if dest.exists():
                    downloaded_path = str(dest)
                    download_done.set()
                    return
                if _save_download_to_path(download, dest, self._timeout):
                    downloaded_path = str(dest)
                download_done.set()

            page.on("download", _on_download)

            captured_files = []
            def on_response(response):
                try:
                    if response.status != 200:
                        return
                    ct = response.headers.get("content-type", "").lower()
                    url_lower = response.url.lower()

                    is_target = False
                    if "application/pdf" in ct or "application/ofd" in ct:
                        is_target = True
                    elif "application/octet-stream" in ct:
                        if any(kw in url_lower for kw in ["pdf", "ofd", "download", "invoice"]):
                            is_target = True
                    elif any(kw in url_lower for kw in ["pdf", "ofd", "/download"]):
                        is_target = True

                    if is_target:
                        body = response.body()
                        if len(body) > 100:
                            is_pdf = body.startswith(b"%PDF")
                            is_zip = body.startswith(b"PK\x03\x04")
                            is_ofd = False
                            if is_zip and (b"ofd.xml" in body or b"OFD.xml" in body):
                                is_ofd = True
                            if is_pdf or is_ofd:
                                ext = ".pdf" if is_pdf else ".ofd"
                                fname = f"invoice_{mail_uid}_{idx}_resp{ext}"
                                dest = save_dir / fname
                                dest.write_bytes(body)
                                captured_files.append(str(dest))
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
            except Exception:
                pass
            final_url = str(getattr(page, "url", "") or "")
            if final_url and not _is_safe_browser_request_url(final_url):
                _log.warning(
                    "Blocked unsafe final browser destination: <%s>",
                    self._url_fingerprint(final_url),
                )
                self.failed_url_fingerprints.add(self._url_fingerprint(url))
                return None

            # 1. Try JSS/Nuonuo site specific download logic first
            res_handle = self._handle_nuonuo_invoice_page(page, url, save_dir, mail_uid, idx, disable_fallback=disable_fallback)
            if res_handle:
                downloaded_path, source_type, parse_note = res_handle

            # 2. General logic
            if not downloaded_path:
                page.wait_for_timeout(2000)
                if not downloaded_path:
                    self._try_click_download(page)
                if download_started and not downloaded_path:
                    download_done.wait(timeout=5)
                    if downloaded_path:
                        source_type = "official_download"
                if not downloaded_path:
                    for f in captured_files:
                        if _verify_and_clean_file(f):
                            downloaded_path = f
                            source_type = "official_response"
                            break
                if not downloaded_path:
                    downloaded_path = self._try_extract_embedded_pdf(page, save_dir, mail_uid, idx)
                    if downloaded_path:
                        source_type = "embedded_pdf"

            if downloaded_path and os.path.exists(downloaded_path):
                if _verify_and_clean_file(downloaded_path):
                    size = os.path.getsize(downloaded_path)
                    return DownloadedFile(
                        url=url,
                        file_path=downloaded_path,
                        filename=os.path.basename(downloaded_path),
                        size=size,
                        is_invoice=True,
                        source_type=source_type,
                        parse_note=parse_note,
                    )

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
            'a:has-text("下载")',
            'button:has-text("下载")',
            'a:has-text("发票")',
            'button:has-text("发票")',
            'a:has-text("PDF")',
            'button:has-text("PDF")',
            'text=下载',
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
