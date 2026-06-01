# -*- coding: utf-8 -*-
"""Privacy-preserving diagnostics export for Invoice Hub."""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import config as config_mod

_SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|token|password|auth[_-]?code|authorization|secret|credential)")
_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)(@[\w.-]+\.\w+)\b")
_PHONE_RE = re.compile(r"\b(1[3-9]\d)(\d{4})(\d{4})\b")
_LONG_DIGIT_RE = re.compile(r"\b(\d{2})\d{6,}(\d{2})\b")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_BEARER_FIELD_RE = re.compile(
    r"(?i)(\bauthorization\b\s*[:=]\s*)Bearer\s+[^\s,;\"'}]+"
)
_TWO_TOKEN_SECRET_FIELD_RE = re.compile(
    r"(?i)(\b(?:token|password|auth[_-]?code|secret|credential)\b\s*[:=]\s*)"
    r"([^\s,;\"'}]+\s+(?!\b[A-Z0-9_]*(?:api[_-]?key|token|password|auth[_-]?code|authorization|secret|credential)\b\s*[:=])[^\s,;\"'}]+)"
)
_SECRET_FIELD_RE = re.compile(
    r"(?i)(\b[A-Z0-9_]*(?:api[_-]?key|token|password|auth[_-]?code|authorization|secret|credential)\b\s*[:=]\s*)([^\s,;\"'}]+)"
)

_ALLOWED_ZIP_ENTRIES = {
    "app_info.json",
    "latest.log.redacted",
    "config.redacted.json",
    "environment.txt",
    "privacy_scan_result.txt",
}


def _mask_email(match: re.Match[str]) -> str:
    local = match.group(1) + match.group(2)
    if len(local) <= 1:
        masked = f"{local[:1]}***"
    else:
        masked = f"{local[0]}***{local[-1]}"
    return f"{masked}{match.group(3)}"


def _mask_url(match: re.Match[str]) -> str:
    text = match.group(0)
    try:
        parsed = urlsplit(text)
        if parsed.query:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "***", parsed.fragment))
    except ValueError:
        return "<url:redacted>"
    return text


def redact_text(value: object) -> str:
    """Redact common PII, credentials, long identifiers, and tokenized URLs."""
    text = str(value or "")
    if not text:
        return ""
    text = _BEARER_FIELD_RE.sub(lambda m: f"{m.group(1)}***redacted***", text)
    text = _TWO_TOKEN_SECRET_FIELD_RE.sub(lambda m: f"{m.group(1)}***redacted***", text)
    text = _SECRET_FIELD_RE.sub(lambda m: f"{m.group(1)}***redacted***", text)
    text = _URL_RE.sub(_mask_url, text)
    text = _EMAIL_RE.sub(_mask_email, text)
    text = _PHONE_RE.sub(lambda m: f"{m.group(1)}****{m.group(3)}", text)
    text = _LONG_DIGIT_RE.sub(lambda m: f"{m.group(1)}****{m.group(2)}", text)
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
    return {
        "app": "Invoice Hub",
        "version": "MVP",
        "mode": "frozen" if getattr(sys, "frozen", False) else "source",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "is_frozen": bool(getattr(sys, "frozen", False)),
        "runtime_dir": "<runtime_dir:redacted>",
        "latest_log": f"<log:redacted:{latest_log.name}>" if latest_log else "no log found",
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
    if script.exists():
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
        "app_info.json": json.dumps(collect_app_info(), ensure_ascii=False, indent=2),
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
