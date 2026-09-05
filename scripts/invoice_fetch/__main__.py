"""CLI entry point — ``python -m scripts.invoice_fetch``

Usage:
    python -m scripts.invoice_fetch               # normal incremental run
    python -m scripts.invoice_fetch --scan-only   # scan and classify only
    python -m scripts.invoice_fetch --download-only # download pending invoices
    python -m scripts.invoice_fetch --classify-only # run AI on unclassified
    python -m scripts.invoice_fetch --reset       # clear processed list, re-scan
"""

from __future__ import annotations

import argparse
import email
import json
import hashlib
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import get_email_accounts, load_config, load_config_safe, RUNTIME_DIR, PROJECT_ROOT, is_outlook_like_account
from .credentials import get_auth_code
from .db import InvoiceDB, is_pending_evidence_invoice
from .excel_export import export_excel
from .attachment_handler import AttachmentHandler, build_managed_attachment_name
from .invoice_parser import InvoiceParser, parse_html_body, parse_subject
from .link_downloader import LinkDownloader, extract_html_from_message
from .mail_fetcher import MailFetcher
from .log_privacy import mask_email, sanitize_log_message, mask_filename, mask_invoice_number, mask_path, mask_uid, redact_text
from .scan_lifecycle import ScanCancelled, ScanControl, ScanStage, new_scan_id, redacted_progress
from .url_utils import _mask_url
from .rule_classifier import classify as rule_classify
from . import review_status
from . import services as application_services
from .services import (
    _classify,
    _import_local_directory,
    _normalize_path_list,
    _resolve_runtime_path,
    _restore_existing_invoice_if_deleted,
    _run_classify,
    _runtime_relative,
    _scan_mailboxes_with_db,
    _sha256_file,
)


def _handle_pending_email(*args, **kwargs):
    return application_services._handle_pending_email(*args, **kwargs)

# Re-export selected classes for tests while keeping optional AI imports lazy.
def __getattr__(name: str):
    if name == "MailMessage":
        from .mail_fetcher import MailMessage
        return MailMessage
    if name == "AIClassifier":
        from .ai_classifier import AIClassifier
        return AIClassifier
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

_log = logging.getLogger("invoice_fetch")

STATUS_LABELS = {
    review_status.TO_REVIEW: "待审核",
    review_status.APPROVED: "已通过",
    review_status.IGNORED: "已忽略",
    review_status.ERROR: "异常",
}


def _status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or review_status.TO_REVIEW, status or review_status.TO_REVIEW)


def _configure_console_utf8():
    """Use UTF-8 consistently for Windows console logging."""
    if os.name != "nt":
        return

    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except (AttributeError, OSError):
        pass

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError, ValueError):
                pass


def _setup_logging(verbose: bool = False):
    log_dir = RUNTIME_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt_console = logging.Formatter("[%(levelname)s] %(message)s")
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt_console)
    root.addHandler(ch)

    fmt_file = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    try:
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt_file)
        root.addHandler(fh)
    except OSError as exc:
        root.warning("Failed to open log file %s: %s", log_file, exc)

    # Suppress verbose third-party loggers to clean up output
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    for logger_name in ("urllib3", "keyring", "asyncio", "win32ctypes", "PIL"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


# ── CLI ──────────────────────────────────────────────────────────────

class ChineseHelpArgumentParser(argparse.ArgumentParser):
    """ArgumentParser with Chinese help text for the MVP CLI surface."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", help="显示帮助信息并退出")
        self._positionals.title = "位置参数"
        self._optionals.title = "选项"

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法:", 1)

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法:", 1)


def _parse_args() -> argparse.Namespace:
    p = ChineseHelpArgumentParser(
        description="Invoice Hub - 本地优先的报销资料整理助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", default=None, help="配置文件路径")
    p.add_argument("--limit", type=int, default=None, help="最大处理邮件数")
    p.add_argument("--months", type=int, default=None, help="搜索最近N个月")
    p.add_argument("--reset", action="store_true", help="清空记录，重新扫描")
    p.add_argument("--export-only", action="store_true", help="仅重新生成Excel")
    p.add_argument("--scan-only", action="store_true", help="仅扫描邮件头并分类")
    p.add_argument("--download-only", action="store_true", help="仅下载已标记的发票邮件")
    p.add_argument("--classify-only", action="store_true", help="仅对未分类邮件执行AI分类")
    p.add_argument("--import-dir", action="append", default=[], help="导入本地发票目录，可重复指定")
    p.add_argument("--no-ai", action="store_true", help="跳过AI分类（仅用规则）")
    p.add_argument("--headed", action="store_true", help="显示浏览器窗口（用于人工辅助验证或下载）")
    p.add_argument("--retry-failed", action="store_true", help="重新尝试下载之前失败的发票链接")
    p.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    subparsers = p.add_subparsers(dest="command", help="子命令", parser_class=ChineseHelpArgumentParser)

    # claim-create
    p_create = subparsers.add_parser("claim-create", help="新建报销组")
    p_create.add_argument("--name", required=True, help="报销组名称")
    p_create.add_argument("--start", default="", help="开始日期 (YYYY-MM-DD)")
    p_create.add_argument("--end", default="", help="结束日期 (YYYY-MM-DD)")

    # claim-add
    p_add = subparsers.add_parser("claim-add", help="添加发票到报销组")
    p_add.add_argument("--claim-id", type=int, required=True, help="报销组ID")
    p_add.add_argument("--invoice-id", type=int, required=True, help="发票ID")
    p_add.add_argument("--note", default="", help="备注")

    # claim-export
    p_export = subparsers.add_parser("claim-export", help="导出报销包（已忽略或异常状态的发票将始终被排除）")
    p_export.add_argument("--claim-id", type=int, required=True, help="报销组ID")
    p_export.add_argument("--include-to-review", action="store_true", help="是否包含待审核发票记录")

    # invoice-list
    p_inv_list = subparsers.add_parser("invoice-list", help="列出发票记录")
    p_inv_list.add_argument("--status", choices=["to_review", "approved", "ignored", "error"], help="根据审核状态筛选发票")
    p_inv_list.add_argument("--limit", type=int, default=None, help="限制输出的记录数")

    # invoice-claimable
    subparsers.add_parser("invoice-claimable", help="列出所有已通过可报销发票（等同于 invoice-list --status approved）")

    # invoice-show
    p_inv_show = subparsers.add_parser("invoice-show", help="显示发票的完整字段详情")
    p_inv_show.add_argument("--invoice-id", type=int, required=True, help="发票ID")

    # invoice-review
    p_inv_review = subparsers.add_parser("invoice-review", help="更新发票的审核状态")
    p_inv_review.add_argument("--invoice-id", type=int, required=True, help="发票ID")
    p_inv_review.add_argument("--status", required=True, choices=["to_review", "approved", "ignored", "error"], help="审核状态")
    p_inv_review.add_argument("--note", default="", help="审核备注")

    # desktop
    p_desktop = subparsers.add_parser("desktop", help="启动 PySide6 发票审核桌面应用")
    p_desktop.add_argument(
        "--startup-probe",
        action="store_true",
        help="无头启动探针：渲染首帧后立即退出，用于 CI 启动性能验证",
    )

    # invoice-delete
    p_inv_del = subparsers.add_parser("invoice-delete", help="删除发票记录 (软删除)")
    p_inv_del.add_argument("--invoice-id", type=int, required=True, help="发票ID")

    # invoice-restore
    p_inv_rest = subparsers.add_parser("invoice-restore", help="恢复已软删除的发票记录")
    p_inv_rest.add_argument("--invoice-id", type=int, required=True, help="发票ID")

    # email-reprocess
    p_reprocess = subparsers.add_parser("email-reprocess", help="安全的邮箱重处理修复工具")
    p_reprocess.add_argument("--mailbox", help="指定 mailbox_key 或邮箱地址")
    p_reprocess.add_argument("--uid", action="append", type=int, help="要处理的邮件 UID，可重复指定")
    p_reprocess.add_argument("--uid-range", help="要处理的邮件 UID 范围，例如 10000-10200")
    p_reprocess.add_argument("--since", help="起始日期 (YYYY-MM-DD)")
    p_reprocess.add_argument("--until", help="结束日期 (YYYY-MM-DD)")
    p_reprocess.add_argument("--subject-contains", help="邮件主题包含关键词")
    p_reprocess.add_argument("--sender-contains", help="发件人包含关键词")
    p_reprocess.add_argument("--only-downloaded", action="store_true", default=True, help="只处理 downloaded=1 的邮件")
    p_reprocess.add_argument("--no-only-downloaded", action="store_false", dest="only_downloaded", help="处理包含未下载 (downloaded=0) 的邮件")
    p_reprocess.add_argument("--include-approved", action="store_true", help="允许处理已审核通过的发票记录")
    p_reprocess.add_argument("--include-claimed", action="store_true", help="允许处理已关联报销组的发票记录")
    p_reprocess.add_argument("--reclassify", action="store_true", help="重置 is_invoice 为 -1 并重新运行规则/AI 分类")
    p_reprocess.add_argument("--dry-run", action="store_true", help="仅预览修改，默认开启")
    p_reprocess.add_argument("--apply", action="store_true", help="真正执行修复")
    p_reprocess.add_argument("--limit", type=int, default=50, help="最多处理的邮件数量，默认 50")
    p_reprocess.add_argument("--headed", action="store_true", help="显示浏览器窗口（用于人工辅助验证或下载）")
    p_reprocess.add_argument("--force-large-batch", action="store_true", help="允许在 apply 模式下处理超过 200 封邮件")

    # evidence-repair
    p_ev_repair = subparsers.add_parser("evidence-repair", help="邮箱未关联证明材料修复工具")
    p_ev_repair.add_argument("--mailbox", required=True, help="指定 mailbox_key 邮箱账号")
    p_ev_repair.add_argument("--uid", type=int, required=True, help="指定邮件 UID")
    p_ev_repair.add_argument("--dry-run", action="store_true", help="仅预览，不修改数据库")
    p_ev_repair.add_argument("--apply", action="store_true", help="真实执行，修补待关联证明材料记录")

    return p.parse_args()


# ── Classify ─────────────────────────────────────────────────────────

def _cmd_claim_create(args: argparse.Namespace, db: InvoiceDB):
    try:
        claim_id = db.create_claim_group(args.name, args.start, args.end)
        print(f"已创建报销组“{args.name}”，ID: {claim_id}")
        sys.exit(0)
    except Exception as e:
        _log.error("Failed to create claim group: %s", e)
        sys.exit(1)


def _cmd_claim_add(args: argparse.Namespace, db: InvoiceDB):
    try:
        claim = db.get_claim_group(args.claim_id)
        if not claim:
            print(f"错误: 报销组 ID {args.claim_id} 不存在。")
            sys.exit(1)

        # Check if invoice exists
        inv = db.get_invoice(args.invoice_id)
        if not inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        success = db.add_invoice_to_claim(args.claim_id, args.invoice_id, args.note)
        if success:
            print(f"已将发票 ID {args.invoice_id} 添加到报销组 ID {args.claim_id}。")
            sys.exit(0)
        else:
            print(f"错误: 发票 ID {args.invoice_id} 已在报销组 ID {args.claim_id} 中，或存在重复关联。")
            sys.exit(1)
    except Exception as e:
        _log.error("Failed to add invoice to claim group: %s", e)
        sys.exit(1)


def _cmd_claim_export(args: argparse.Namespace, db: InvoiceDB, project_root: Path, runtime_dir: Path):
    try:
        claim = db.get_claim_group(args.claim_id)
        if not claim:
            print(f"错误: 报销组 ID {args.claim_id} 不存在。")
            sys.exit(1)

        from .claim_export import export_claim_package
        include_to_review = getattr(args, "include_to_review", False)
        export_dir = export_claim_package(db, args.claim_id, project_root, runtime_dir, include_to_review=include_to_review)
        from .log_privacy import mask_path
        print(f"已导出报销组 ID {args.claim_id} 的报销包: {mask_path(export_dir)}")
        sys.exit(0)
    except ValueError as ve:
        print(f"错误: {ve}")
        sys.exit(1)
    except Exception as e:
        _log.error("Failed to export claim group: %s", e)
        sys.exit(1)


def _cmd_invoice_list(args: argparse.Namespace, db: InvoiceDB):
    try:
        invoices = db.list_invoices(status=getattr(args, "status", None), limit=getattr(args, "limit", None))
        if not invoices:
            print("未找到发票记录。")
            sys.exit(0)

        # Beautiful, clean text table format
        header_fmt = "{:<6} | {:<12} | {:<15} | {:<12} | {:<12} | {:<10} | {:<25}"
        row_fmt    = "{:<6} | {:<12} | {:<15} | {:<12} | {:<12} | {:<10} | {:<25}"

        print(header_fmt.format("ID", "状态", "发票号码", "日期", "金额", "分类", "销售方"))
        print("-" * 110)
        for inv in invoices:
            inv_id = inv.get("id") or ""
            status = _status_label(inv.get("review_status") or review_status.TO_REVIEW)
            number = inv.get("invoice_number") or ""
            date = inv.get("invoice_date") or ""
            amount = inv.get("total_amount") or ""
            category = inv.get("category") or ""
            seller = inv.get("seller_name") or ""

            if len(seller) > 25:
                seller = seller[:22] + "..."
            print(row_fmt.format(inv_id, status, number, date, amount, category, seller))
        sys.exit(0)
    except Exception as e:
        _log.error("Failed to list invoices: %s", e)
        sys.exit(1)


def _cmd_invoice_claimable(args: argparse.Namespace, db: InvoiceDB):
    args.status = "approved"
    args.limit = None
    _cmd_invoice_list(args, db)


def _cmd_invoice_show(args: argparse.Namespace, db: InvoiceDB):
    try:
        inv = db.get_invoice(args.invoice_id)
        if not inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        print("=" * 60)
        print(f"发票详情 (ID: {inv.get('id')})")
        print("=" * 60)
        print(f"发票号码:       {inv.get('invoice_number') or ''}")
        print(f"发票代码:       {inv.get('invoice_code') or ''}")
        print(f"开票日期:       {inv.get('invoice_date') or ''}")
        print(f"金额 (税前):    {inv.get('amount') or ''}")
        print(f"价税合计:       {inv.get('total_amount') or ''}")
        print(f"销售方名称:     {inv.get('seller_name') or ''}")
        print(f"购买方名称:     {inv.get('buyer_name') or ''}")
        print(f"发票类型:       {inv.get('invoice_type') or ''}")
        print(f"发票分类:       {inv.get('category') or ''}")
        print(f"审核状态:       {_status_label(inv.get('review_status') or review_status.TO_REVIEW)}")
        print(f"确认时间:       {inv.get('confirmed_at') or ''}")
        print(f"审核备注:       {inv.get('confirmed_note') or ''}")
        print(f"附加材料:       {'是' if inv.get('has_extra') else '否'}")
        print(f"缺少附件:       {'是' if inv.get('missing_extra') else '否'}")
        print(f"邮件主题:       {inv.get('mail_subject') or ''}")
        print(f"文件路径:       {inv.get('attachment_path') or ''}")
        print(f"下载链接:       {_mask_url(inv.get('download_url') or '')}")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        _log.error("Failed to show invoice details: %s", e)
        sys.exit(1)


def _cmd_invoice_review(args: argparse.Namespace, db: InvoiceDB):
    try:
        old_inv = db.get_invoice(args.invoice_id)
        if not old_inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        old_status = old_inv.get("review_status") or "to_review"

        success = db.update_invoice_review_status(args.invoice_id, args.status, args.note)
        if not success:
            print(f"错误: 发票 ID {args.invoice_id} 更新失败。")
            sys.exit(1)

        new_inv = db.get_invoice(args.invoice_id)
        new_status = new_inv.get("review_status")
        confirmed_at = new_inv.get("confirmed_at") or ""

        print("已更新发票审核状态:")
        print(f"  发票 ID:   {args.invoice_id}")
        print(f"  原状态:    {_status_label(old_status)}")
        print(f"  新状态:    {_status_label(new_status)}")
        print(f"  确认时间:  {confirmed_at}")
        print(f"  审核备注:  {args.note}")
        sys.exit(0)
    except ValueError as ve:
        print(f"错误: {ve}")
        sys.exit(1)
    except Exception as e:
        _log.error("Failed to review invoice: %s", e)
        sys.exit(1)


def _cmd_invoice_delete(args: argparse.Namespace, db: InvoiceDB):
    try:
        inv = db.get_invoice(args.invoice_id)
        if not inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        success = db.soft_delete_invoice(args.invoice_id)
        if success:
            print(f"已删除发票 ID {args.invoice_id}。")
            sys.exit(0)
        else:
            print(f"错误: 发票 ID {args.invoice_id} 删除失败。")
            sys.exit(1)
    except Exception as e:
        _log.error("Failed to delete invoice: %s", e)
        sys.exit(1)


def _cmd_invoice_restore(args: argparse.Namespace, db: InvoiceDB):
    try:
        inv = db.get_invoice(args.invoice_id, include_deleted=True)
        if not inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        success = db.restore_invoice(args.invoice_id)
        if success:
            print(f"已恢复发票 ID {args.invoice_id}。")
            sys.exit(0)
        else:
            print(f"错误: 发票 ID {args.invoice_id} 恢复失败。")
            sys.exit(1)
    except Exception as e:
        _log.error("Failed to restore invoice: %s", e)
        sys.exit(1)


def _cmd_evidence_repair(args: argparse.Namespace, db: InvoiceDB):
    """Subcommand to repair unassociated evidence documents for a given email UID."""
    mailbox_key = args.mailbox
    uid = args.uid
    dry_run = args.dry_run or not args.apply

    # Load configuration
    cfg = load_config(args.config)
    accounts = get_email_accounts(cfg)

    # 寻找匹配的邮箱
    acc = None
    for a in accounts:
        if a.get("mailbox_key") == mailbox_key or a.get("address") == mailbox_key:
            acc = a
            break

    if not acc:
        print(f"错误: 未在配置中找到 mailbox_key/address 匹配 '{mailbox_key}' 的邮箱配置。")
        sys.exit(1)

    addr = acc.get("address", "")
    auth_code = acc.get("auth_code", "")
    if not auth_code:
        try:
            auth_code = get_auth_code(addr)
        except (Exception, SystemExit) as e:
            print(f"错误: 获取邮箱 {addr} 的授权码失败: {e}")
            sys.exit(1)

    if not auth_code:
        print(f"错误: 邮箱 {addr} 的授权码为空。")
        sys.exit(1)

    provider = acc.get("provider", "")
    server = acc.get("imap", {}).get("server", "")
    if is_outlook_like_account(provider, addr, server):
        print(f"跳过 Outlook/Microsoft 邮箱：当前版本需要 OAuth2，暂不支持扫描。邮箱：{mask_email(addr)}")
        sys.exit(1)



    print(f"正在连接邮箱 {addr} 并获取邮件 UID: {uid}...")
    with MailFetcher(
        address=addr,
        auth_code=auth_code,
        server=acc.get("imap", {}).get("server", "imap.qq.com"),
        port=acc.get("imap", {}).get("port", 993),
    ) as fetcher:
        folder = acc.get("search", {}).get("folder", "INBOX")
        msg = fetcher.fetch_by_uid(uid, folder=folder)
        if not msg:
            print(f"错误: 未在邮箱中找到 UID 为 {uid} 的邮件。")
            sys.exit(1)

        print(f"邮件获取成功。主题: {msg.subject}")

        # 找出附加材料附件
        att_dir = db._path.parent / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        att_handler = AttachmentHandler(att_dir)

        # 提取附件
        attachments = att_handler.extract(msg.raw_msg, msg.uid, date_str=msg.date)
        extra_files = [a for a in attachments if a.is_extra]

        if not extra_files:
            print("该邮件的附件中未发现任何附加材料 [附加材料]。")
            sys.exit(0)

        # 获取该 UID 和 mailbox_key 在发票库里的所有未删除关联发票，以获得当前已经关联的 extra_paths
        invoices = db.get_invoices_by_mail_identity(mailbox_key, uid)
        associated_paths = set()
        for inv in invoices:
            paths = _normalize_path_list(inv.get("extra_paths"))
            for p in paths:
                resolved = _resolve_runtime_path(p)
                if resolved:
                    associated_paths.add(str(resolved.resolve()).lower())

        # 过滤出未关联 of extra_files
        unassociated_extras = []
        for att in extra_files:
            att_path = Path(att.file_path)
            if str(att_path.resolve()).lower() not in associated_paths:
                unassociated_extras.append(att)

        if not unassociated_extras:
            print("该邮件下的所有附加材料均已被关联，无需修复。")
            sys.exit(0)

        print(f"发现 {len(unassociated_extras)} 个未关联的证明材料：")
        categories = cfg.get("categories", {})

        for att in unassociated_extras:
            file_path = Path(att.file_path)
            file_hash = _sha256_file(file_path) if file_path.exists() else ""

            existing = None
            if file_hash:
                existing = db.find_invoice_by_file_hash(file_hash, include_deleted=True)

            if existing:
                inv_id = existing["id"]
                is_del = int(existing.get("is_deleted") or 0) == 1

                if is_del:
                    print(f"- [已删除记录] 文件: {att.original_name} (Hash: {file_hash[:10]}...), 准备在 apply 时恢复。")
                    if not dry_run:
                        _restore_existing_invoice_if_deleted(db, existing, "证明材料恢复")
                        if not existing.get("attachment_path"):
                            db.update_invoice_file_paths(inv_id, attachment_path=_runtime_relative(file_path))
                        print(f"  -> 已成功恢复记录 ID: {inv_id}")
                else:
                    print(f"- [已存在活跃记录] 文件: {att.original_name} (ID: {inv_id}), 跳过插入，已自动复用。")
                    if not dry_run:
                        if not existing.get("attachment_path"):
                            db.update_invoice_file_paths(inv_id, attachment_path=_runtime_relative(file_path))
            else:
                print(f"- [新证明材料] 文件: {att.original_name} (Hash: {file_hash[:10]}...), 准备在 apply 时创建待关联记录。")
                if not dry_run:
                    category, extra_type, extra_required = _classify(att.original_name, msg.sender or "", "", categories)
                    rec = {
                        "invoice_number": "",
                        "invoice_code": "",
                        "invoice_date": "",
                        "expense_date": "",
                        "date_source": "unknown",
                        "amount": "",
                        "total_amount": "",
                        "seller_name": "",
                        "buyer_name": "",
                        "invoice_type": "待关联证明材料",
                        "category": category,
                        "has_extra": False,
                        "extra_type": extra_type,
                        "missing_extra": False,
                        "mail_uid": msg.uid,
                        "mail_subject": msg.subject,
                        "mail_date": msg.date,
                        "mail_sender": msg.sender,
                        "parse_success": False,
                        "parse_note": "多发票邮件证明材料未唯一匹配，请人工关联",
                        "attachment_path": _runtime_relative(file_path),
                        "extra_paths": [],
                        "file_hash": file_hash,
                        "mailbox_key": mailbox_key,
                    }
                    row_id = db.insert_invoice(rec)
                    print(f"  -> 已成功创建待关联记录 ID: {row_id}")

        if dry_run:
            print("\n提示: 当前为 dry-run 预览模式，未对数据库做任何修改。如需真正执行修复，请添加 --apply 参数。")
        else:
            print("\n已成功完成修复。")

        sys.exit(0)


def _dispatch_claim_command(args: argparse.Namespace):
    """Execute the matching claim subcommand and exit, bypassing config loading."""
    db_path = RUNTIME_DIR / "invoices.db"
    if args.command == "desktop":
        import time as _time
        _t0 = _time.monotonic()
        from .gui import start_gui
        _t1 = _time.monotonic()
        app_init_ms = int((_t1 - _t0) * 1000)
        startup_probe = getattr(args, "startup_probe", False)
        start_gui(db_path, startup_probe=startup_probe, app_init_ms=app_init_ms)
        return

    with InvoiceDB(db_path) as db:
        if args.command == "claim-create":
            _cmd_claim_create(args, db)
        elif args.command == "claim-add":
            _cmd_claim_add(args, db)
        elif args.command == "claim-export":
            _cmd_claim_export(args, db, PROJECT_ROOT, RUNTIME_DIR)
        elif args.command == "invoice-list":
            _cmd_invoice_list(args, db)
        elif args.command == "invoice-claimable":
            _cmd_invoice_claimable(args, db)
        elif args.command == "invoice-show":
            _cmd_invoice_show(args, db)
        elif args.command == "invoice-review":
            _cmd_invoice_review(args, db)
        elif args.command == "invoice-delete":
            _cmd_invoice_delete(args, db)
        elif args.command == "invoice-restore":
            _cmd_invoice_restore(args, db)
        elif args.command == "email-reprocess":
            _cmd_email_reprocess(args, db)
        elif args.command == "evidence-repair":
            _cmd_evidence_repair(args, db)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    _configure_console_utf8()
    args = _parse_args()
    _setup_logging(args.verbose)

    # Early dispatch for subcommands (bypassing config.json loading)
    if getattr(args, "command", None):
        _dispatch_claim_command(args)
        return

    _log.info("=" * 60)
    _log.info("Invoice Hub - 本地优先的报销资料整理助手")
    _log.info("运行时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    _log.info("=" * 60)

    cfg = load_config(args.config)
    email_addr = cfg["email"]["address"]
    imap_cfg = cfg.get("imap", {})
    search_cfg = cfg.get("search", {})
    ai_cfg = cfg.get("ai", {})
    categories = cfg.get("categories", {})
    months = args.months or search_cfg.get("months_back", 3)

    # Paths
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    att_dir = RUNTIME_DIR / "attachments"
    db_path = RUNTIME_DIR / "invoices.db"
    excel_path = RUNTIME_DIR / "发票汇总.xlsx"

    with InvoiceDB(db_path) as db:
        # Export-only mode
        if args.export_only:
            export_excel(db.get_all_invoices(), excel_path)
            _log.info("完成 (仅导出)")
            return

        # Classify-only mode (no IMAP needed)
        if args.classify_only:
            _run_classify(db, ai_cfg, args.no_ai)
            return

        # Reset mode
        if args.reset:
            db.reset_emails()
            db.reset_processed()
            db.reset_invoices()
            _log.info("已重置，将重新扫描所有邮件")

        if args.import_dir:
            parser = InvoiceParser()
            total_stats = {"added": 0, "duplicates": 0, "conflicts": 0, "pending_manual": 0, "failed": 0}
            for import_dir in args.import_dir:
                stats = _import_local_directory(
                    import_dir=import_dir,
                    db=db,
                    parser=parser,
                    categories=categories,
                    att_dir=att_dir,
                )
                for k in total_stats:
                    total_stats[k] += stats.get(k, 0)
            export_excel(db.get_all_invoices(), excel_path)
            total_recorded = total_stats["added"] + total_stats["conflicts"] + total_stats["pending_manual"]
            _log.info(
                "本地导入完成: 成功入库/待处理 %d 条 (新增: %d, 重复: %d, 冲突: %d, 失败: %d)",
                total_recorded,
                total_stats["added"],
                total_stats["duplicates"],
                total_stats["conflicts"],
                total_stats["failed"],
            )
            _print_stats(db, excel_path)
            return

        # Retry failed downloads mode
        if args.retry_failed:
            failed_invoices = db.get_failed_downloads()
            if failed_invoices:
                failed_uids = [inv["mail_uid"] for inv in failed_invoices if inv["mail_uid"]]
                if failed_uids:
                    db.reset_emails_download_status(failed_uids)
                    db.delete_invoices_by_uid(failed_uids)
                    _log.info("已重置 %d 封未成功下载的发票邮件状态，将重新尝试下载", len(failed_uids))
            else:
                _log.info("未发现需要重新下载的失败发票记录")

        try:
            scan_summary = _scan_mailboxes_with_db(
                db=db,
                db_path=db_path,
                cfg=cfg,
                months=months,
                limit=args.limit,
                scan_only=args.scan_only,
                download_only=args.download_only,
                headed=args.headed,
                retry_failed=args.retry_failed,
                no_ai=args.no_ai,
            )
            if scan_summary:
                _log.info(
                    "Mailbox scan finished: %d/%d accounts succeeded, %d failed, "
                    "headers=%d new_headers=%d invoice_candidates=%d processed_emails=%d "
                    "new_records=%d restored=%d duplicates=%d manual_review_required=%d failed_items=%d",
                    scan_summary.get("accounts_success", 0),
                    scan_summary.get("accounts_total", 0),
                    scan_summary.get("accounts_failed", 0),
                    scan_summary.get("scanned_headers", scan_summary.get("scanned", 0)),
                    scan_summary.get("new_email_headers", 0),
                    scan_summary.get("classified_invoice", 0),
                    scan_summary.get("downloaded_emails", scan_summary.get("downloaded", 0)),
                    scan_summary.get("new_invoice_records", scan_summary.get("new", 0)),
                    scan_summary.get("restored_deleted", 0),
                    scan_summary.get("duplicates", 0),
                    scan_summary.get("manual_review_required", scan_summary.get("pending_manual", 0)),
                    scan_summary.get("failed_count", 0),
                )

            if args.scan_only:
                _print_stats(db, excel_path)
                return
        except ConnectionError as exc:
            _log.error("Mailbox scan failed: %s", exc)
            sys.exit(1)
        except ValueError as exc:
            _log.error("%s", exc)
            sys.exit(1)

        # Export & stats
        export_excel(db.get_all_invoices(), excel_path)
        _print_stats(db, excel_path)



def _print_stats(db: InvoiceDB, excel_path):
    """Print final statistics."""
    stats = db.get_email_stats()
    inv_count = db.count_invoices()
    rows = db.get_all_invoices()
    has_file = sum(1 for r in rows if r.get("attachment_path") and os.path.exists(RUNTIME_DIR / r.get("attachment_path")))

    _log.info("\n" + "=" * 60)
    _log.info("运行统计:")
    _log.info("  邮件: 总计 %d, 发票 %d, 非发票 %d, 未分类 %d",
              stats["total"], stats["invoice"],
              stats["not_invoice"], stats["unclassified"])
    _log.info("  发票入库: %d 张, 已下载文件: %d", inv_count, has_file)
    if stats["pending"]:
        _log.info("  ⬇️ 待下载: %d 封", stats["pending"])
    _log.info("  输出: %s", mask_path(excel_path))
    _log.info("=" * 60)


def import_local_directory(
    import_dir: str | Path,
    db_path: Path,
    config_path: Path | None = None
) -> int:
    """Public wrapper to import a local directory of invoices."""
    from .services import import_local_directory as _service_import
    try:
        return _service_import(import_dir, db_path, config_path)
    except ValueError as e:
        raise SystemExit(str(e))


def scan_email_and_download(
    db_path: Path,
    config_path: Path | None = None,
    months: int | None = None,
    limit: int | None = None,
    scan_only: bool = False,
    download_only: bool = False,
    log_callback = None
) -> dict:
    """Public wrapper to scan emails and download invoices safely from GUI/CLI."""
    from .services import scan_email_and_download as _service_scan
    return _service_scan(
        db_path=db_path,
        config_path=config_path,
        months=months,
        limit=limit,
        scan_only=scan_only,
        download_only=download_only,
        log_callback=log_callback
    )


def _cmd_email_reprocess(args: argparse.Namespace, db: InvoiceDB):
    """Subcommand handler to reprocess emails."""
    # 1. 验证 limit 必须为正整数
    if args.limit is not None and args.limit <= 0:
        print("错误: --limit 必须为正整数。")
        sys.exit(1)

    # 2. apply 模式下的高强度安全保护校验
    if args.apply:
        # 必须提供 mailbox
        if not args.mailbox:
            print("错误: 在 apply 模式下，必须指定 --mailbox 邮箱账号。")
            sys.exit(1)
        # 必须至少提供一个筛选范围条件
        has_filter = (
            args.uid or
            args.uid_range or
            args.since or
            args.until or
            args.subject_contains or
            args.sender_contains
        )
        if not has_filter:
            print("错误: 在 apply 模式下，必须提供至少一个具体的筛选范围（如 --uid, --uid-range, --since, --until, --subject-contains, --sender-contains）以防误操作全局删除。")
            sys.exit(1)
        # 单次最大数量限制，除非显式指定 --force-large-batch
        if args.limit is not None and args.limit > 200 and not args.force_large_batch:
            print("错误: 单次处理数量限制为 200。如果确需处理大批量邮件，请显式提供 --force-large-batch 选项。")
            sys.exit(1)

    # 3. 验证 uid-range 并解析
    uid_range = None
    if args.uid_range:
        parts = args.uid_range.split("-")
        if len(parts) == 2:
            try:
                start = int(parts[0])
                end = int(parts[1])
                if start <= end and start >= 0:
                    uid_range = (start, end)
            except ValueError:
                pass
        if not uid_range:
            print("错误: --uid-range 格式必须为 START-END, 且满足 START <= END (均需为非负整数)。")
            sys.exit(1)

    # 4. 验证 since/until 的格式 (YYYY-MM-DD) 以及 since <= until
    import re as _re
    date_pat = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if args.since:
        if not date_pat.match(args.since):
            print("错误: --since 日期格式必须为 YYYY-MM-DD。")
            sys.exit(1)
    if args.until:
        if not date_pat.match(args.until):
            print("错误: --until 日期格式必须为 YYYY-MM-DD。")
            sys.exit(1)
    if args.since and args.until:
        if args.since > args.until:
            print("错误: --since 起始日期不能大于 --until 结束日期。")
            sys.exit(1)

    dry_run = args.dry_run or not args.apply

    records = db.find_emails_for_reprocess(
        mailbox_key=args.mailbox,
        uids=args.uid,
        uid_range=uid_range,
        since=args.since,
        until=args.until,
        subject_contains=args.subject_contains,
        sender_contains=args.sender_contains,
        only_downloaded=args.only_downloaded,
        limit=args.limit,
    )

    if not records:
        print("没有找到符合条件的候选邮件记录。")
        sys.exit(0)

    cfg = load_config(args.config)
    _reprocess_email_records(
        db=db,
        cfg=cfg,
        records=records,
        include_approved=args.include_approved,
        include_claimed=args.include_claimed,
        reclassify=args.reclassify,
        dry_run=dry_run,
        headed=args.headed,
    )


def _reprocess_email_records(
    db: InvoiceDB,
    cfg: dict,
    records: list[dict],
    include_approved: bool = False,
    include_claimed: bool = False,
    reclassify: bool = False,
    dry_run: bool = True,
    headed: bool = False,
):
    """Reprocess the selected email records."""
    import json as _json

    # 1. 预先扫描拟删除及跳过的 invoices 详情
    all_targets = []
    total_to_delete = 0
    total_skipped_approved = 0
    total_skipped_claimed = 0

    for r in records:
        mailbox_key = r["mailbox_key"]
        uid = r["uid"]
        invoices = db.get_invoices_by_mail_identity(mailbox_key, uid)

        record_targets = []
        for inv in invoices:
            is_approved = (inv.get("review_status") == "approved")
            is_claimed = inv.get("claim_id") is not None

            skip_reason = None
            if is_approved and not include_approved:
                total_skipped_approved += 1
                skip_reason = "approved"
            elif is_claimed and not include_claimed:
                total_skipped_claimed += 1
                skip_reason = "claimed"
            else:
                total_to_delete += 1

            record_targets.append({
                "inv": inv,
                "skip_reason": skip_reason
            })

        all_targets.append({
            "email": r,
            "targets": record_targets
        })

    # Dry-run 模式
    if dry_run:
        print("邮箱重处理预览：")
        print(f"- 候选邮件：{len(records)} 封")
        print(f"- 将删除旧发票记录：{total_to_delete} 条")
        print(f"- 跳过已通过：{total_skipped_approved} 条")
        print(f"- 跳过已归组：{total_skipped_claimed} 条")
        print("\n候选：")

        for idx, item in enumerate(all_targets, start=1):
            email = item["email"]
            masked_mailbox = mask_email(email["mailbox_key"])
            masked_uid = mask_uid(email["uid"])
            redacted_subject = redact_text(email["subject"] or "", "subject")
            print(f"[{idx}] mailbox={masked_mailbox} uid={masked_uid} date={email['mail_date']} subject={redacted_subject}")

            for tgt in item["targets"]:
                inv = tgt["inv"]
                inv_id = inv["id"]
                inv_num = mask_invoice_number(inv.get("invoice_number") or "")
                amount = inv.get("total_amount") or "0.00"
                status = inv.get("review_status") or "to_review"
                fallback_str = " (legacy fallback)" if inv.get("is_legacy_fallback") else ""

                try:
                    extra_paths_list = _json.loads(inv.get("extra_paths") or "[]")
                except Exception:
                    extra_paths_list = []
                extra_count = len(extra_paths_list)

                if tgt["skip_reason"] == "approved":
                    print(f"    [跳过] 已通过审核: invoice id={inv_id}{fallback_str} 发票号={inv_num} 金额={amount}")
                elif tgt["skip_reason"] == "claimed":
                    claim_id = inv.get("claim_id")
                    print(f"    [跳过] 已关联报销组: invoice id={inv_id}{fallback_str} 发票号={inv_num} 金额={amount} 报销组ID={claim_id}")
                else:
                    print(f"    将删除 invoice id={inv_id}{fallback_str} 发票号={inv_num} 金额={amount} 状态={status} extra={extra_count}")

        print("\n未执行修改。确认无误后加 --apply 执行。")
        return

    # Apply 真正执行模式
    print("正在执行邮箱重处理，请稍候...")
    deleted_invoices_total = 0
    skipped_approved_total = 0
    skipped_claimed_total = 0

    # 1) 删除及重置
    for r in records:
        mailbox_key = r["mailbox_key"]
        uid = r["uid"]

        stats = db.delete_invoices_for_reprocess(
            mailbox_key=mailbox_key,
            uid=uid,
            include_approved=include_approved,
            include_claimed=include_claimed,
        )
        deleted_invoices_total += stats["deleted"]
        skipped_approved_total += stats["skipped_approved"]
        skipped_claimed_total += stats["skipped_claimed"]

        db.reset_email_for_reprocess(
            mailbox_key=mailbox_key,
            uid=uid,
            reclassify=reclassify,
        )

    # 2) 重新分类 (如果启用 reclassify)
    mailbox_keys = {r["mailbox_key"] for r in records}
    if reclassify:
        ai_cfg = cfg.get("ai", {})
        import sys as _sys
        no_ai_arg = "--no-ai" in _sys.argv
        for m_key in mailbox_keys:
            _run_classify(db, ai_cfg, no_ai=no_ai_arg, mailbox_key=m_key)

    # 3) 获取邮箱配置并进行下载
    accounts = get_email_accounts(cfg)
    account_contexts = []
    for acc in accounts:
        addr = acc.get("address", "")
        auth_code = ""
        # 优先使用配置里已有的 auth_code（在单元测试的 mock 里可能已经定义了）
        if "auth_code" in acc:
            auth_code = acc["auth_code"]
        else:
            try:
                auth_code = get_auth_code(addr)
            except (Exception, SystemExit) as e:
                _log.warning("获取邮箱 %s 的授权码失败: %s", mask_email(addr), e)
        account_contexts.append({**acc, "auth_code": auth_code})
    account_by_key = {acc["mailbox_key"]: acc for acc in account_contexts}

    att_dir = db._path.parent / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    att_handler = AttachmentHandler(att_dir)
    parser = InvoiceParser()
    link_dl = LinkDownloader(att_dir, headed=headed)

    reprocessed_count = 0
    failed_count = 0
    new_records_count = 0
    restored_deleted_count = 0
    duplicates_count = 0

    for m_key in mailbox_keys:
        selected_uids = {r["uid"] for r in records if r["mailbox_key"] == m_key}

        acc = account_by_key.get(m_key)
        if not acc:
            _log.warning("未在配置中找到 mailbox_key=%s 的邮箱配置，无法重新下载该邮箱下的邮件", m_key)
            pending_downloads = db.get_invoice_emails_to_download(mailbox_key=m_key)
            failed_uids = [row["uid"] for row in pending_downloads if row["uid"] in selected_uids]
            failed_count += len(failed_uids)
            reprocessed_count += (len(selected_uids) - len(failed_uids))
            continue

        pending = []
        try:
            pending = db.get_invoice_emails_to_download(mailbox_key=m_key)
            pending = [row for row in pending if row["uid"] in selected_uids]

            not_pending_uids = selected_uids - {row["uid"] for row in pending}
            reprocessed_count += len(not_pending_uids)

            if pending:
                if not acc.get("auth_code"):
                    _log.warning("获取邮箱 %s 的授权码为空，无法下载该邮箱下的 %d 封邮件", mask_email(acc["address"]), len(pending))
                    failed_count += len(pending)
                    continue

                provider = acc.get("provider", "")
                server = acc.get("imap", {}).get("server", "")
                if is_outlook_like_account(provider, acc["address"], server):
                    _log.warning("跳过 Outlook/Microsoft 邮箱：当前版本需要 OAuth2，暂不支持扫描。邮箱：%s", mask_email(acc["address"]))
                    failed_count += len(pending)
                    continue


                _log.info("正在连接邮箱 %s...", mask_email(acc["address"]))
                with MailFetcher(
                    address=acc["address"],
                    auth_code=acc["auth_code"],
                    server=acc.get("imap", {}).get("server", "imap.qq.com"),
                    port=acc.get("imap", {}).get("port", 993),
                ) as fetcher:
                    folder = acc.get("search", {}).get("folder", "INBOX")
                    for row in pending:
                        before_active_count = db.count_invoices()
                        before_total_count = db.count_invoices(include_deleted=True)

                        recorded = _handle_pending_email(
                            row=row,
                            fetcher=fetcher,
                            folder=folder,
                            att_handler=att_handler,
                            parser=parser,
                            link_dl=link_dl,
                            db=db,
                            categories=cfg.get("categories", {}),
                            config=cfg,
                            source_mode="reprocess",
                        )

                        after_active_count = db.count_invoices()
                        after_total_count = db.count_invoices(include_deleted=True)

                        if recorded:
                            reprocessed_count += 1
                            new_delta = max(0, after_total_count - before_total_count)
                            restored_delta = max(0, (after_active_count - before_active_count) - new_delta)
                            new_records_count += new_delta
                            restored_deleted_count += restored_delta
                            if new_delta == 0 and restored_delta == 0:
                                duplicates_count += 1
                        else:
                            failed_count += 1
            else:
                pass
        except Exception as exc:
            _log.error("连接邮箱 %s 失败或下载过程中出错: %s", mask_email(acc["address"]), exc)
            failed_count += len(pending)

    link_dl.close()

    print("\n邮箱重处理完成：")
    print(f"- 选中邮件：{len(records)} 封")
    print(f"- 删除旧记录：{deleted_invoices_total} 条")
    print(f"- 跳过已通过：{skipped_approved_total} 条")
    print(f"- 跳过已归组：{skipped_claimed_total} 条")
    print(f"- 重新处理成功：{reprocessed_count} 封")
    print(f"- 新增记录：{new_records_count} 条")
    print(f"- 恢复已删除记录：{restored_deleted_count} 条")
    print(f"- 重复：{duplicates_count} 条")
    print(f"- 失败：{failed_count} 封")


if __name__ == "__main__":
    main()
