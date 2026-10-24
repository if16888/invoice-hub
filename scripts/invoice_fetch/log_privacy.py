# -*- coding: utf-8 -*-
"""Privacy-safe helpers for logs and diagnostics."""

from __future__ import annotations

import hashlib
import logging
import re
import traceback
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlparse


def _digest(value: object, length: int = 8) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:length]


def mask_email(value: str) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return redact_text(text, "email")
    local, domain = text.rsplit("@", 1)
    if not local:
        return f"***@{domain}"
    if len(local) <= 2:
        masked_local = local[0] + "***" if local else "***"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def mask_sender_header(sender: str) -> str:
    """Mask only the address portion of a display-name sender header."""
    text = str(sender or "").strip()
    if not text:
        return ""
    _, address = parseaddr(text)
    return mask_email(address) if address else redact_text(text, "sender")


def mask_uid(value: object) -> str:
    return f"uid#{_digest(value, 6)}"


def mask_mailbox_key(value: object) -> str:
    """Mask a mailbox identifier while keeping plain labels readable.

    ``mailbox_key`` defaults to the account address, so logging it verbatim
    writes a full mailbox address to disk.  Labels that are not addresses
    (``legacy`` or a user-chosen name) stay readable for debugging.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return mask_email(text) if "@" in text else text


def mask_invoice_number(value: object) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    if not text:
        return ""
    if len(text) <= 6:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def mask_amount(value: object) -> str:
    return "***" if str(value or "").strip() else ""


def redact_text(value: object, label: str = "text") -> str:
    text = str(value or "")
    if not text:
        return ""
    return f"<{label}:redacted:{_digest(text)}>"


def mask_filename(value: object) -> str:
    name = Path(str(value or "")).name
    suffix = Path(name).suffix.lower()
    suffix = suffix if len(suffix) <= 10 else ""
    return f"file#{_digest(name)}{suffix}"


def mask_path(value: object) -> str:
    return mask_filename(value)


def mask_url_for_log(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/<redacted:{_digest(text)}>"
    return f"<url:redacted:{_digest(text)}>"


def sanitize_log_message(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(
        r"(?:^|(?<=\s))(?:(?:runtime|attachments|downloads|exports)[\\/])?[^\s]+[\\/][^\s]*\.(?:pdf|ofd|png|jpe?g|bmp|heic|xlsx|zip)\b",
        lambda m: mask_path(m.group(0)),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[A-Za-z]:\\[^\s]+", lambda m: mask_path(m.group(0)), text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", lambda m: mask_email(m.group(0)), text)
    text = re.sub(r"https?://\S+", lambda m: mask_url_for_log(m.group(0)), text)
    # ── Credentials and bearer material ────────────────────────────────
    # A token pasted into a warning must never reach runtime/logs or a
    # diagnostic package; mask it even when it has no ``key=`` label.
    text = re.sub(
        r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}",
        r"\1<token:redacted>",
        text,
    )
    # ``(?<!<)`` / ``(?!<)`` keep this rule from re-masking the placeholder the
    # bearer rule just produced; ``authorization`` is omitted on purpose because
    # the bearer rule already covers that header.
    text = re.sub(
        r"""(?ix)
        (?<!<)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?code
           |password|passwd|secret|client[_-]?secret|token)\b
        (\s*[:=]\s*)(["']?)(?!<)([^\s,;'"&)]{4,})
        """,
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}<secret:redacted>",
        text,
    )
    text = re.sub(
        r"\beyJ[A-Za-z0-9_=-]{8,}\.[A-Za-z0-9_=-]{8,}\.[A-Za-z0-9_=-]{8,}",
        "<jwt:redacted>",
        text,
    )
    text = re.sub(
        r"\b[A-Za-z0-9+/]{60,}={0,2}",
        lambda m: f"<blob:redacted:{_digest(m.group(0))}>",
        text,
    )
    # ── Invoice numbers ────────────────────────────────────────────────
    # 8-digit paper invoice numbers are shorter than the blanket rule below,
    # so keep the explicit label they are logged with.
    text = re.sub(
        r"(?i)(发票号码|发票号|票号|invoice\s*(?:no\.?|number)?)(\s*[:：=]?\s*)(\d{6,24})",
        lambda m: m.group(1) + m.group(2) + mask_invoice_number(m.group(3)),
        text,
    )
    text = re.sub(r"\b\d{10,24}\b", lambda m: mask_invoice_number(m.group(0)), text)
    text = re.sub(r"(?<![\w.])(?:[¥￥])?\d{1,9}\.\d{2}(?![\w.])", "***", text)
    text = re.sub(r"(?i)\buid\s*=\s*\d+\b", lambda m: "UID=" + mask_uid(m.group(0)), text)
    text = re.sub(r"(销方=)[^\s,，;；]+", r"\1<seller:redacted>", text)
    text = re.sub(r"(销售方[:：]\s*)[^\s,，;；]+", r"\1<seller:redacted>", text)
    text = re.sub(r"(处理\s+UID=[^:：]+[:：]\s*).+", r"\1<subject:redacted>", text)
    return text


class PrivacyLogFilter(logging.Filter):
    """Sanitize log record messages, arguments and exception text.

    Attaching this filter to a handler (rather than to individual logger
    objects) is what makes the guarantee hold for every module and for
    third-party loggers that share the same handlers.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = sanitize_log_message(rendered)
        record.args = ()
        # Exception tracebacks bypass %-formatting entirely, so a message-only
        # filter would leak whatever the raised error text contains.
        if record.exc_info:
            record.exc_text = sanitize_log_message(
                "".join(traceback.format_exception(*record.exc_info))
            )
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = sanitize_log_message(record.exc_text)
        if record.stack_info:
            record.stack_info = sanitize_log_message(record.stack_info)
        return True


def attach_privacy_filter(handler: logging.Handler) -> logging.Handler:
    """Install the privacy filter on a handler so every logger is covered."""
    if not any(isinstance(existing, PrivacyLogFilter) for existing in handler.filters):
        handler.addFilter(PrivacyLogFilter())
    return handler
