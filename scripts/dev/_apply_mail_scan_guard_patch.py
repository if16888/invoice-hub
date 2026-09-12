from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one regex replacement, found {count}: {pattern[:120]!r}")
    path.write_text(new_text, encoding="utf-8")


link = ROOT / "scripts/invoice_fetch/link_downloader.py"
services = ROOT / "scripts/invoice_fetch/services.py"
settings = ROOT / "scripts/invoice_fetch/gui/settings_dialog.py"
config_example = ROOT / "config.example.json"

# 1) DNS safety checks must fail closed within a bounded amount of time.
regex_replace_once(
    link,
    r"@lru_cache\(maxsize=256\)\ndef _host_resolves_to_public_addresses\(host: str, port: int\) -> bool:\n.*?\n\ndef _is_safe_browser_request_url",
    '''_DNS_RESOLVE_TIMEOUT_SECONDS = 2.0\n\n\n@lru_cache(maxsize=256)\ndef _host_resolves_to_public_addresses(host: str, port: int) -> bool:\n    \"\"\"Fail closed unless every resolved address is public, with bounded DNS wait.\"\"\"\n    try:\n        literal_ip = ipaddress.ip_address(host)\n    except ValueError:\n        literal_ip = None\n    if literal_ip is not None:\n        return literal_ip.is_global\n\n    done = threading.Event()\n    result: dict[str, object] = {}\n\n    def resolve() -> None:\n        try:\n            result[\"records\"] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)\n        except OSError:\n            result[\"records\"] = None\n        finally:\n            done.set()\n\n    threading.Thread(\n        target=resolve,\n        name=\"InvoiceHubDnsSafetyCheck\",\n        daemon=True,\n    ).start()\n    if not done.wait(_DNS_RESOLVE_TIMEOUT_SECONDS):\n        fingerprint = hashlib.sha256(host.encode(\"utf-8\", errors=\"ignore\")).hexdigest()[:16]\n        _log.warning(\"DNS safety check timed out: <%s>\", fingerprint)\n        return False\n\n    records = result.get(\"records\")\n    if not records:\n        return False\n    addresses = {record[4][0] for record in records if record[4]}\n    if not addresses:\n        return False\n    for address in addresses:\n        try:\n            ip = ipaddress.ip_address(address)\n        except ValueError:\n            return False\n        if not ip.is_global:\n            return False\n    return True\n\n\ndef _is_safe_browser_request_url''',
)

# 2) Make browser work cancellation-aware and impose cumulative URL/email budgets.
replace_once(
    link,
    '    def __init__(self, download_dir: str | Path, timeout_ms: int = 30_000, headed: bool = False):\n',
    '    def __init__(self, download_dir: str | Path, timeout_ms: int = 30_000, headed: bool = False, scan_control=None):\n',
)

replace_once(
    link,
    '''        self._timeout = timeout_ms\n        cfg_timeout = link_cfg.get("timeout_ms")\n        if cfg_timeout is not None:\n            self._timeout = int(cfg_timeout)\n        self._max_links_per_email = int(link_cfg.get("max_links_per_email", 5))\n        self._max_seconds_per_email = float(link_cfg.get("max_seconds_per_email", 120))\n''',
    '''        requested_timeout = int(link_cfg.get("timeout_ms", timeout_ms))\n        max_operation_timeout_ms = int(link_cfg.get("max_operation_timeout_ms", 10_000))\n        self._timeout = max(1_000, min(requested_timeout, max_operation_timeout_ms))\n        self._max_seconds_per_url = max(3.0, float(link_cfg.get("max_seconds_per_url", 20.0)))\n        self._max_links_per_email = max(1, int(link_cfg.get("max_links_per_email", 3)))\n        self._max_seconds_per_email = max(\n            self._max_seconds_per_url,\n            float(link_cfg.get("max_seconds_per_email", 60.0)),\n        )\n''',
)

replace_once(
    link,
    '''        self._browser = None\n        self._headed = headed\n        # Per-process failed URL fingerprint cache — avoid retrying known failures\n''',
    '''        self._browser = None\n        self._headed = headed\n        self._scan_control = scan_control\n        # Per-process failed URL fingerprint cache — avoid retrying known failures\n''',
)

replace_once(
    link,
    '''    @staticmethod\n    def _url_fingerprint(url: str) -> str:\n        \"\"\"Return a hashed fingerprint for a URL — deterministic, not reversible.\"\"\"\n        return hashlib.sha256(url.encode()).hexdigest()[:16]\n\n    def _ensure_browser(self):\n''',
    '''    @staticmethod\n    def _url_fingerprint(url: str) -> str:\n        \"\"\"Return a hashed fingerprint for a URL — deterministic, not reversible.\"\"\"\n        return hashlib.sha256(url.encode()).hexdigest()[:16]\n\n    def _check_cancelled(self) -> None:\n        control = self._scan_control\n        if control is not None:\n            control.raise_if_cancelled()\n\n    def _remaining_timeout_ms(self, deadline: float, cap_ms: int | None = None) -> int:\n        self._check_cancelled()\n        remaining_ms = int((deadline - time.monotonic()) * 1000)\n        if remaining_ms <= 0:\n            raise TimeoutError(\"browser link download deadline exceeded\")\n        if cap_ms is not None:\n            remaining_ms = min(remaining_ms, int(cap_ms))\n        return max(1, min(remaining_ms, self._timeout))\n\n    def _ensure_browser(self):\n''',
)

replace_once(
    link,
    '''    def download_from_email(self, msg, mail_uid: int, date_str: str = "") -> list[DownloadedFile]:\n        subject = ""\n''',
    '''    def download_from_email(self, msg, mail_uid: int, date_str: str = "") -> list[DownloadedFile]:\n        self._check_cancelled()\n        subject = ""\n''',
)

# Both high- and low-priority loops use this exact sequence.
text = link.read_text(encoding="utf-8")
needle = '''            attempted_count += 1\n            r = self._download_url(url, mail_uid, len(results), date_str, disable_fallback=has_official_success)\n'''
if text.count(needle) != 2:
    raise RuntimeError(f"{link}: expected two browser attempt call sites, found {text.count(needle)}")
text = text.replace(
    needle,
    '''            self._check_cancelled()\n            attempted_count += 1\n            r = self._download_url(url, mail_uid, len(results), date_str, disable_fallback=has_official_success)\n            self._check_cancelled()\n''',
)
link.write_text(text, encoding="utf-8")

replace_once(
    link,
    '''    def _handle_nuonuo_invoice_page(self, page, url: str, save_dir: Path, mail_uid: int, idx: int, disable_fallback: bool = False) -> tuple[str | None, str | None, str | None] | None:\n''',
    '''    def _handle_nuonuo_invoice_page(self, page, url: str, save_dir: Path, mail_uid: int, idx: int, disable_fallback: bool = False, deadline: float | None = None) -> tuple[str | None, str | None, str | None] | None:\n''',
)

# Bound the fixed waits inside the site-specific handler by the remaining URL budget.
replace_once(
    link,
    '            page.wait_for_load_state("domcontentloaded", timeout=5000)\n',
    '            page.wait_for_load_state("domcontentloaded", timeout=self._remaining_timeout_ms(deadline, 5000) if deadline is not None else 5000)\n',
)
replace_once(
    link,
    '            page.wait_for_load_state("networkidle", timeout=5000)\n',
    '            page.wait_for_load_state("networkidle", timeout=self._remaining_timeout_ms(deadline, 5000) if deadline is not None else 5000)\n',
)
# There are multiple 2000ms waits; replace the first one in the handler and the later short response wait.
text = link.read_text(encoding="utf-8")
old_wait = '            page.wait_for_timeout(2000)\n'
if text.count(old_wait) < 2:
    raise RuntimeError(f"{link}: expected at least two 2000ms waits")
text = text.replace(
    old_wait,
    '            page.wait_for_timeout(min(1000, self._remaining_timeout_ms(deadline, 1000)) if deadline is not None else 1000)\n',
    2,
)
link.write_text(text, encoding="utf-8")

replace_once(
    link,
    '                        with page.expect_download(timeout=3000) as download_info:\n',
    '                        with page.expect_download(timeout=self._remaining_timeout_ms(deadline, 3000) if deadline is not None else 3000) as download_info:\n',
)

# Add the actual URL deadline and propagate cancellation rather than swallowing it.
replace_once(
    link,
    '''        _log.info("Browser download: %s", mask_url_for_log(url))\n\n        try:\n            self._ensure_browser()\n''',
    '''        attempt_started = time.monotonic()\n        deadline = attempt_started + self._max_seconds_per_url\n        fingerprint = self._url_fingerprint(url)\n        _log.info("Browser download: %s", mask_url_for_log(url))\n\n        try:\n            self._check_cancelled()\n            self._ensure_browser()\n            self._check_cancelled()\n''',
)

replace_once(
    link,
    '''            ctx.set_default_timeout(self._timeout)\n            ctx.set_default_navigation_timeout(self._timeout)\n''',
    '''            bounded_timeout = self._remaining_timeout_ms(deadline)\n            ctx.set_default_timeout(bounded_timeout)\n            ctx.set_default_navigation_timeout(bounded_timeout)\n''',
)

replace_once(
    link,
    '''            try:\n                page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)\n            except Exception:\n                pass\n''',
    '''            try:\n                page.goto(url, wait_until="domcontentloaded", timeout=self._remaining_timeout_ms(deadline))\n            except Exception:\n                self._check_cancelled()\n            self._check_cancelled()\n''',
)

replace_once(
    link,
    '''            res_handle = self._handle_nuonuo_invoice_page(page, url, save_dir, mail_uid, idx, disable_fallback=disable_fallback)\n''',
    '''            res_handle = self._handle_nuonuo_invoice_page(\n                page,\n                url,\n                save_dir,\n                mail_uid,\n                idx,\n                disable_fallback=disable_fallback,\n                deadline=deadline,\n            )\n            self._check_cancelled()\n''',
)

# The general-path wait should respect the same cumulative deadline.
replace_once(
    link,
    '''            if not downloaded_path:\n                page.wait_for_timeout(2000)\n                if not downloaded_path:\n''',
    '''            if not downloaded_path:\n                page.wait_for_timeout(min(1000, self._remaining_timeout_ms(deadline, 1000)))\n                self._check_cancelled()\n                if not downloaded_path:\n''',
)

replace_once(
    link,
    '''        except Exception as exc:\n            _log.debug("Browser download failed for <%s>: %s", self._url_fingerprint(url), exc)\n            self.failed_url_fingerprints.add(self._url_fingerprint(url))\n            return None\n        finally:\n            if ctx:\n                ctx.close()\n''',
    '''        except Exception as exc:\n            if self._scan_control is not None and self._scan_control.cancelled:\n                raise\n            elapsed = time.monotonic() - attempt_started\n            level = _log.warning if isinstance(exc, TimeoutError) or elapsed >= self._max_seconds_per_url else _log.debug\n            level("Browser download failed for <%s>: %s (elapsed=%.1fs)", fingerprint, exc, elapsed)\n            self.failed_url_fingerprints.add(fingerprint)\n            return None\n        finally:\n            elapsed = time.monotonic() - attempt_started\n            _log.info("Browser download attempt finished: <%s> elapsed=%.1fs", fingerprint, elapsed)\n            if ctx:\n                try:\n                    ctx.close()\n                except Exception:\n                    pass\n''',
)

# 3) Wire the active scan cancellation token into browser link downloads.
replace_once(
    services,
    '    link_dl = LinkDownloader(att_dir, headed=headed)\n',
    '    link_dl = LinkDownloader(att_dir, headed=headed, scan_control=scan_control)\n',
)

# 4) Remove the stale hard-coded 3-month UI statement; per-mailbox rows already render the actual value.
replace_once(
    settings,
    '        rules_layout.addWidget(QLabel("📅 扫描时间范围: 只扫描最近 3 个月内的增量发票邮件"), 0, 0)\n',
    '        rules_layout.addWidget(QLabel("📅 扫描时间范围: 按各邮箱配置的时间范围进行增量抓取"), 0, 0)\n',
)

# 5) Document the bounded browser policy in the example config.
replace_once(
    config_example,
    '''  "link_download": {\n    "timeout_ms": 10000,\n    "max_links_per_email": 5,\n''',
    '''  "link_download": {\n    "timeout_ms": 10000,\n    "max_operation_timeout_ms": 10000,\n    "max_seconds_per_url": 20,\n    "max_seconds_per_email": 60,\n    "max_links_per_email": 3,\n''',
)

print("mail scan bounded-browser patch applied")
