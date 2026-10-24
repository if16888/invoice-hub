# -*- coding: utf-8 -*-
"""Privacy-preserving diagnostics export for Invoice Hub."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import APP_VERSION
from . import config as config_mod
from .log_privacy import (
    mask_amount,
    mask_invoice_number,
    mask_url_for_log,
    redact_text as _privacy_redact_text,
    sanitize_log_message,
)

_SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|token|password|auth[_-]?code|authorization|secret|credential)")
# Shared redaction rules live in ``log_privacy`` so the log drawer, the
# clipboard copy and the diagnostic ZIP can never disagree.  The patterns below
# only cover forms the shared log pipeline does not handle yet.
_USER_PROFILE_RE = re.compile(
    r"(?i)(?P<prefix>\b[A-Za-z]:[\\/]Users[\\/]|/Users/|/home/)"
    r"(?P<name>[^\\/\r\n]+)(?=[\\/])"
)
_URL_RE = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")
# The shared log rule only masks bearer tokens of 8+ characters; a diagnostics
# export must not keep shorter ones either.
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)(?!<)([A-Za-z0-9._~+/=-]+)")
_PREFIXED_SECRET_RE = re.compile(
    r"(?i)((?<!<)\b[A-Z0-9_]*(?:API[_-]?KEY|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN"
    r"|AUTH[_-]?CODE|PASSWORD|PASSWD|SECRET|TOKEN|CREDENTIAL)[A-Z0-9_]*"
    r"\s*[:=]\s*)(?!<)([^\s,;\"'}]+)"
)
_BARE_EIGHT_DIGIT_RE = re.compile(r"(?<![\d.])\d{8}(?![\d.])")
_GROUPED_AMOUNT_RE = re.compile(
    r"(?<![\w.])(?:[¥￥])?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?(?![\w.])"
)

_ALLOWED_ZIP_ENTRIES = {
    "app_info.json",
    "latest.log.redacted",
    "config.redacted.json",
    "environment.txt",
    "privacy_scan_result.txt",
}


def _mask_user_profile(match: re.Match[str]) -> str:
    """Mask the user-name segment of a Windows/macOS/Linux home path."""
    return match.group("prefix") + _privacy_redact_text(match.group("name"), "user")


def _mask_url(match: re.Match[str]) -> str:
    """Mask everything in a URL after the host, including its path token."""
    text = match.group(0)
    if "<redacted:" in text:
        return text
    try:
        parsed = urlsplit(text)
    except ValueError:
        return _privacy_redact_text(text, "url")
    # The shared helper keeps the host; user-info credentials in the authority
    # would therefore survive, so such URLs are masked as a whole.
    if "@" in parsed.netloc:
        return _privacy_redact_text(text, "url")
    # The shared log rule already replaced the sensitive part with this
    # placeholder; do not wrap the harmless scheme+host prefix a second time.
    if not parsed.path.strip("/") and not parsed.query and not parsed.fragment:
        return text
    return mask_url_for_log(text)


def _mask_prefixed_secret(match: re.Match[str]) -> str:
    """Mask environment-style keys such as ``GEMINI_API_KEY=...``."""
    return match.group(1) + _privacy_redact_text(match.group(2), "secret")


def _mask_bearer(match: re.Match[str]) -> str:
    return match.group(1) + _privacy_redact_text(match.group(2), "token")


def _mask_bare_eight_digit(match: re.Match[str]) -> str:
    """Mask 8-digit paper invoice numbers while keeping YYYYMMDD dates."""
    value = match.group(0)
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return mask_invoice_number(value)
    return value


def redact_text(value: object) -> str:
    """Redact common PII, credentials, user paths, and tokenized URLs."""
    text = str(value or "")
    if not text:
        return ""
    # URLs go first: the path/query (and any bearer token in it) must be gone
    # before the shared rules rewrite the remainder.
    text = _URL_RE.sub(_mask_url, text)
    text = _USER_PROFILE_RE.sub(_mask_user_profile, text)
    # Grouped amounts have to be handled before the shared decimal-amount rule,
    # otherwise ``1,234.56`` is only half masked.
    text = _GROUPED_AMOUNT_RE.sub(lambda m: mask_amount(m.group(0)), text)
    text = sanitize_log_message(text)
    text = _BEARER_RE.sub(_mask_bearer, text)
    text = _PREFIXED_SECRET_RE.sub(_mask_prefixed_secret, text)
    text = _BARE_EIGHT_DIGIT_RE.sub(_mask_bare_eight_digit, text)
    return text


def _redact_config_value(key: str, value: Any) -> Any:
    if _SECRET_KEY_RE.search(str(key)):
        return "***redacted***"
    if isinstance(value, dict):
        return {str(k): _redact_config_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_config_value(key, item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a recursively redacted copy of a configuration dictionary."""
    return _redact_config_value("", dict(config or {}))


def _read_redacted_config() -> dict[str, Any]:
    candidates = [
        config_mod.RUNTIME_DIR / "config.json",
        config_mod.PROJECT_ROOT / "config.json",
        config_mod.PROJECT_ROOT / "config.example.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return redact_config(raw)
        except Exception as exc:
            return {"read_error": redact_text(str(exc))}
    return {"status": "config file not found"}


def _latest_log_text() -> str:
    latest_log = _latest_log_path()
    if not latest_log:
        return "No log file found."
    try:
        return redact_text(latest_log.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return f"Failed to read latest log: {redact_text(exc)}"


def _latest_log_path() -> Path | None:
    log_dir = config_mod.RUNTIME_DIR / "logs"
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None
    return logs[0]


def collect_app_info() -> dict[str, Any]:
    """Collect non-sensitive app diagnostics metadata."""
    latest_log = _latest_log_path()
    config = _read_redacted_config()
    email_cfg = config.get("email", {}) if isinstance(config, dict) else {}
    ai_cfg = config.get("ai", {}) if isinstance(config, dict) else {}
    return {
        "app": "Invoice Hub",
        "version": APP_VERSION,
        "mode": "frozen" if getattr(sys, "frozen", False) else "source",
        "build_mode": "release" if getattr(sys, "frozen", False) else "local/dev",
        "build_commit": (
            os.environ.get("GITHUB_SHA")
            or os.environ.get("INVOICE_HUB_BUILD_COMMIT")
            or "unavailable"
        ),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "is_frozen": bool(getattr(sys, "frozen", False)),
        "data_dir": "<runtime_dir:redacted>",
        "log_dir": "<log_dir:redacted>",
        "runtime_dir": "<runtime_dir:redacted>",
        "latest_log": f"<log:redacted:{latest_log.name}>" if latest_log else "no log found",
        "config_summary": {
            "email_provider": email_cfg.get("provider", "unknown") if isinstance(email_cfg, dict) else "unknown",
            "email_configured": bool(email_cfg.get("address")) if isinstance(email_cfg, dict) else False,
            "ai_provider": ai_cfg.get("provider", "none") if isinstance(ai_cfg, dict) else "none",
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _environment_text() -> str:
    lines = [
        f"python={platform.python_version()}",
        f"platform={platform.platform()}",
        f"machine={platform.machine()}",
        f"is_frozen={bool(getattr(sys, 'frozen', False))}",
        "runtime_dir=<runtime_dir:redacted>",
    ]
    return "\n".join(redact_text(line) for line in lines) + "\n"


def _privacy_scan_result() -> str:
    script = config_mod.PROJECT_ROOT / "scripts" / "check_repo_privacy.py"
    # A frozen build has no Python interpreter on this machine: sys.executable
    # is the app itself, so the repo-scan subprocess can never start. Fall
    # through to the packaged allowlist summary instead of failing.
    if script.exists() and not getattr(sys, "frozen", False):
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(config_mod.PROJECT_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=30,
                check=False,
            )
            output = result.stdout or f"privacy scan exited with code {result.returncode}"
            return redact_text(output)
        except Exception as exc:
            return f"privacy scan unavailable: {redact_text(exc)}\n"

    forbidden = [
        "invoices.db",
        "attachments/",
        "exports/",
        "PDF/OFD/images/Excel/ZIP originals",
        "API keys and mailbox authorization codes",
        "full tokenized URLs",
    ]
    return (
        "诊断包导出 allowlist 已启用。\n"
        f"Allowed entries: {', '.join(sorted(_ALLOWED_ZIP_ENTRIES))}\n"
        f"Forbidden data excluded: {', '.join(forbidden)}\n"
    )


def export_diagnostics_zip(output_dir: str | Path | None = None) -> Path:
    """Export a diagnostics zip containing only redacted allowlisted files."""
    target_dir = Path(output_dir) if output_dir else config_mod.RUNTIME_DIR / "diagnostics"
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / f"InvoiceHub-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.zip"

    entries = {
        # Every allowlisted entry runs through the same redaction pipeline, so a
        # future field that carries a path or a token cannot leak by accident.
        "app_info.json": redact_text(
            json.dumps(collect_app_info(), ensure_ascii=False, indent=2)
        ),
        "latest.log.redacted": _latest_log_text(),
        "config.redacted.json": json.dumps(_read_redacted_config(), ensure_ascii=False, indent=2),
        "environment.txt": _environment_text(),
        "privacy_scan_result.txt": _privacy_scan_result(),
    }
    if set(entries) != _ALLOWED_ZIP_ENTRIES:
        raise RuntimeError("诊断包导出 allowlist 不匹配")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(_ALLOWED_ZIP_ENTRIES):
            zf.writestr(name, entries[name])
    return zip_path
