from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from .config import load_config_safe
from .credentials import get_auth_code, has_auth_code
from .mail_fetcher import MailFetcher
from .attachment_handler import AttachmentHandler
from .invoice_parser import InvoiceParser
from .link_downloader import LinkDownloader
from .db import InvoiceDB
from .excel_export import export_excel
from .log_privacy import mask_email, mask_uid, sanitize_log_message

_log = logging.getLogger("invoice_fetch")


def import_local_directory(
    import_dir: str | Path,
    db_path: Path,
    config_path: Path | None = None,
    file_paths: Iterable[str | Path] | None = None,
) -> dict:
    """Public wrapper to import a local directory of invoices."""
    from .__main__ import _import_local_directory

    try:
        cfg = load_config_safe(config_path)
        categories = cfg.get("categories", {})

        att_dir = db_path.parent / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)

        parser = InvoiceParser()
        with InvoiceDB(db_path) as db:
            stats = _import_local_directory(
                import_dir=import_dir,
                db=db,
                parser=parser,
                categories=categories,
                att_dir=att_dir,
                file_paths=file_paths,
            )
            excel_path = db_path.parent / "发票汇总.xlsx"
            export_excel(db.get_all_invoices(), excel_path)
            return stats
    except SystemExit as sys_err:
        raise ValueError(str(sys_err)) from None


def scan_email_and_download(
    db_path: Path,
    config_path: Path | None = None,
    months: int | None = None,
    limit: int | None = None,
    scan_only: bool = False,
    download_only: bool = False,
    headed: bool = False,
    retry_failed: bool = False,
    log_callback=None,
    selected_keys: list[str] | None = None,
) -> dict:
    """Public wrapper to scan emails and download invoices safely from GUI/CLI."""
    from .__main__ import _scan_mailboxes_with_db

    def log(msg: str):
        msg = sanitize_log_message(str(msg or ""))
        _log.info(msg)
        if log_callback:
            log_callback(msg)

    try:
        cfg = load_config_safe(config_path)
        with InvoiceDB(db_path) as db:
            return _scan_mailboxes_with_db(
                db=db,
                db_path=db_path,
                cfg=cfg,
                months=months,
                limit=limit,
                scan_only=scan_only,
                download_only=download_only,
                headed=headed,
                retry_failed=retry_failed,
                log_callback=log,
                selected_keys=selected_keys,
            )

    except SystemExit as sys_err:
        raise ValueError(f"Unexpected SystemExit: {sys_err}") from None
