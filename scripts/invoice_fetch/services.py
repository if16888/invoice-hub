from __future__ import annotations

import logging
from pathlib import Path

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
    log_callback=None,
) -> dict:
    """Public wrapper to scan emails and download invoices safely from GUI/CLI."""
    from .__main__ import _run_classify, _handle_pending_email

    def log(msg: str):
        msg = sanitize_log_message(msg)
        if log_callback:
            log_callback(msg)
        else:
            _log.info(msg)

    try:
        cfg = load_config_safe(config_path)
        email_addr = cfg.get("email", {}).get("address", "")
        if not email_addr or email_addr == "your_email@qq.com":
            raise ValueError("请先前往 [设置] 页面配置真实的邮箱地址。")

        imap_cfg = cfg.get("imap", {})
        search_cfg = cfg.get("search", {})
        ai_cfg = cfg.get("ai", {})
        categories = cfg.get("categories", {})
        months_back = months or search_cfg.get("months_back", 3)

        att_dir = db_path.parent / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        excel_path = db_path.parent / "发票汇总.xlsx"

        if not has_auth_code(email_addr):
            raise ValueError("未配置邮箱授权码，请先前往 [设置] 页面配置。")

        try:
            auth_code = get_auth_code(email_addr)
        except SystemExit:
            raise ValueError("未配置安全邮箱授权码，请前往 [设置] 页面配置。")

        log(f"Starting mailbox connection: {mask_email(email_addr)}...")

        scanned_count = 0
        downloaded_count = 0
        classified_invoice_count = 0
        pending_manual_count = 0
        failed_count = 0
        failed_summaries: list[str] = []
        duplicate_count = 0
        new_count = 0

        with InvoiceDB(db_path) as db:
            with MailFetcher(
                address=email_addr,
                auth_code=auth_code,
                server=imap_cfg.get("server", "imap.qq.com"),
                port=imap_cfg.get("port", 993),
            ) as fetcher:
                if not download_only:
                    since = "" if search_cfg.get("folder") != "INBOX" else db.get_last_scanned_date()

                    if since:
                        log(f"Incremental scan from {since}")
                    else:
                        log(f"Full scan of the most recent {months_back} months")

                    known = db.get_all_email_uids()
                    headers = fetcher.scan_headers(
                        folder=search_cfg.get("folder", "INBOX"),
                        months_back=months_back,
                        since_date=since,
                        known_uids=known,
                        limit=limit,
                    )
                    scanned_count = db.bulk_upsert_emails(headers)
                    log(f"Scan complete: {scanned_count} new emails")

                    unclassified = db.get_unclassified_emails()
                    if unclassified:
                        log(f"Classifying {len(unclassified)} unclassified emails")
                        _run_classify(db, ai_cfg, ai_cfg.get("provider", "none") == "none")
                    else:
                        log("No unclassified emails")

                    if scan_only:
                        export_excel(db.get_all_invoices(), excel_path)
                        return {
                            "scanned": scanned_count,
                            "new": 0,
                            "classified_invoice": 0,
                            "downloaded": 0,
                            "duplicates": 0,
                            "pending_manual": 0,
                            "failed": 0,
                            "failed_count": 0,
                            "failed_summaries": [],
                        }

                pending = db.get_invoice_emails_to_download()
                classified_invoice_count = len(pending)
                if not pending:
                    log("No invoice emails pending download")
                else:
                    log(f"Downloading {len(pending)} invoice emails")
                    att_handler = AttachmentHandler(att_dir)
                    parser = InvoiceParser()
                    link_dl = LinkDownloader(att_dir, headed=False)

                    try:
                        for i, row in enumerate(pending, 1):
                            log(f"[{i}/{len(pending)}] Processing {mask_uid(row['uid'])}")
                            try:
                                before_count = db.count_invoices()
                                success = _handle_pending_email(
                                    row=row,
                                    fetcher=fetcher,
                                    folder=search_cfg.get("folder", "INBOX"),
                                    att_handler=att_handler,
                                    parser=parser,
                                    link_dl=link_dl,
                                    db=db,
                                    categories=categories,
                                )
                                if success:
                                    downloaded_count += 1
                                    after_count = db.count_invoices()
                                    added_rows = max(0, after_count - before_count)
                                    new_count += added_rows
                                    if added_rows == 0:
                                        duplicate_count += 1
                                else:
                                    pending_manual_count += 1
                            except Exception as exc:
                                failed_count += 1
                                summary = sanitize_log_message(f"Failed to process {mask_uid(row['uid'])}: {exc}")
                                failed_summaries.append(summary)
                                log(summary)
                    finally:
                        link_dl.close()

            export_excel(db.get_all_invoices(), excel_path)
            log("Mailbox scan and invoice package generation completed")
            return {
                "scanned": scanned_count,
                "new": new_count,
                "classified_invoice": classified_invoice_count,
                "downloaded": downloaded_count,
                "duplicates": duplicate_count,
                "pending_manual": pending_manual_count,
                "failed": failed_count,
                "failed_count": failed_count,
                "failed_summaries": failed_summaries[:10],
            }

    except SystemExit as sys_err:
        raise ValueError(f"Unexpected SystemExit: {sys_err}") from None
