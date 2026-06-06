"""IMAP mail fetcher — connect to an IMAP mailbox, retrieve invoice-related emails.

Improvements over the previous implementation:
- Newest-first scan (reversed message IDs)
- Client-side INTERNALDATE filtering (some IMAP servers may ignore SINCE)
- Automatic stop after 50 consecutive old emails
- Relevance pre-filter on subject / sender / attachment name
"""

from __future__ import annotations

import email as _email
import imaplib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import Message
from typing import Optional

from .log_privacy import PrivacyLogFilter

_log = logging.getLogger(__name__)
_log.addFilter(PrivacyLogFilter())

# ── Subject / sender keywords that suggest an invoice-related email ──

RELEVANCE_KEYWORDS = [
    "发票", "invoice", "fapiao", "电子发票", "报销",
    "行程单", "水单",
    "住宿", "酒店", "hotel",
    "打车", "出行", "滴滴", "曹操", "T3出行", "高德打车", "美团打车",
    "乘机", "航旅", "机票", "飞机",
    "铁路", "高铁", "火车", "12306", "电子客票", "车票", "客票",
    "train", "rail", "railway",
    "receipt",
]

EXCLUDE_KEYWORDS = [
    "信用卡", "电子账单", "还款", "额度", "积分",
    "招聘", "面试", "offer",
    "验证码", "密码", "冻结",
    "记忆", "相册",
]


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class MailMessage:
    """Lightweight representation of a fetched email."""

    uid: int
    raw_msg: Message
    subject: str = ""
    sender: str = ""
    date: str = ""          # YYYY-MM-DD
    message_id: str = ""

    def __post_init__(self):
        self.subject = _decode_mime(self.raw_msg.get("Subject", ""))
        self.sender = _decode_mime(self.raw_msg.get("From", ""))
        self.date = _parse_email_date(self.raw_msg.get("Date", ""))
        self.message_id = self.raw_msg.get("Message-ID", "")


# ── Helpers ──────────────────────────────────────────────────────────

def _decode_mime(header_value: str) -> str:
    """Decode a MIME-encoded header (Subject, From, filename …)."""
    if not header_value:
        return ""
    parts = decode_header(header_value)
    decoded = []
    for content, charset in parts:
        if isinstance(content, bytes):
            for enc in [charset or "utf-8", "utf-8", "gbk", "gb2312", "gb18030"]:
                try:
                    decoded.append(content.decode(enc))
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                decoded.append(content.decode("utf-8", errors="replace"))
        else:
            decoded.append(str(content))
    return "".join(decoded)


def _parse_email_date(date_str: str) -> str:
    """Return *YYYY-MM-DD* from an RFC-2822 date header."""
    if not date_str:
        return ""
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(date_str).strftime("%Y-%m-%d")
    except Exception:
        m = re.search(
            r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})",
            date_str,
        )
        if m:
            try:
                dt = datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%d %b %Y")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
    return ""


def _imap_date_string(months_back: int) -> str:
    """Return ``DD-Mon-YYYY`` for N months ago (IMAP SINCE format)."""
    d = datetime.now() - timedelta(days=months_back * 30)
    return d.strftime("%d-%b-%Y")


def _email_looks_relevant(msg: MailMessage) -> bool:
    """Quick filter: does the email look invoice-related?"""
    combined = (msg.subject + " " + msg.sender).lower()

    if any(kw.lower() in combined for kw in EXCLUDE_KEYWORDS):
        return False
    if any(kw.lower() in combined for kw in RELEVANCE_KEYWORDS):
        return True

    # Has attachment whose name mentions invoices?
    if msg.raw_msg.is_multipart():
        for part in msg.raw_msg.walk():
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                fname = str(part.get_filename() or "").lower()
                if any(kw in fname for kw in ["发票", "invoice", "水单", "行程"]):
                    return True
    return False


# ── Main fetcher ─────────────────────────────────────────────────────

class MailFetcher:
    """IMAP mail fetcher with newest-first scanning."""

    def __init__(self, address: str, auth_code: str,
                 server: str = "imap.qq.com", port: int = 993):
        self._address = address
        self._auth_code = auth_code
        self._server = server
        self._port = port
        self._conn: Optional[imaplib.IMAP4_SSL] = None
        self._selected_folder: Optional[str] = None

    # ── Context manager ──────────────────────────────────────────────

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.disconnect()

    # ── Connection ───────────────────────────────────────────────────

    def connect(self):
        _log.info("正在连接 IMAP %s:%s …", self._server, self._port)
        try:
            self._conn = imaplib.IMAP4_SSL(self._server, self._port)
            self._conn.login(self._address, self._auth_code)
            _log.info("邮箱登录成功: %s", self._address)
        except imaplib.IMAP4.error as exc:
            _log.error("IMAP 登录失败: %s", exc)
            raise ConnectionError(f"无法登录邮箱 IMAP 服务: {exc}") from exc

    def disconnect(self):
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None
            self._auth_code = ""
            _log.info("已断开 IMAP 连接")

    # ── Fetch ────────────────────────────────────────────────────────

    def fetch_emails(
        self,
        folder: str = "INBOX",
        months_back: int = 3,
        since_date: str = "",
        processed_uids: set[int] | None = None,
        limit: int | None = None,
    ) -> list[MailMessage]:
        """Return new, date-filtered emails (newest first).

        Args:
            since_date: Optional ``YYYY-MM-DD``.  When given, overrides
                *months_back* and scans from this date onward.
        """
        if not self._conn:
            raise ConnectionError("未连接 — 请先调用 connect()")

        processed_uids = processed_uids or set()

        status, data = self._conn.select(folder, readonly=True)
        if status != "OK":
            _log.error("无法打开文件夹 %s: %s", folder, data)
            return []

        total = int(data[0])
        _log.info("文件夹 %s 共 %d 封邮件", folder, total)

        # Determine cutoff date
        if since_date:
            try:
                cutoff = datetime.strptime(since_date, "%Y-%m-%d")
                _log.info("增量模式: 从 %s 开始扫描", since_date)
            except ValueError:
                cutoff = datetime.now() - timedelta(days=months_back * 30)
                _log.warning("日期格式错误 '%s', 回退到 %d 个月", since_date, months_back)
        else:
            cutoff = datetime.now() - timedelta(days=months_back * 30)

        cutoff_str = cutoff.strftime("%Y-%m-%d")
        _log.info("日期范围: %s 至今", cutoff_str)

        # IMAP SINCE as hint (some IMAP servers may ignore it)
        # Use standard imaplib multi-arg form — no extra quoting/parentheses
        since = cutoff.strftime("%d-%b-%Y")
        status, raw_ids = self._conn.search(None, 'SINCE', since)
        if status != "OK":
            _log.error("搜索失败")
            return []

        all_ids = raw_ids[0].split()
        since_works = len(all_ids) < total
        if since_works:
            _log.info("IMAP SINCE 生效: %d 封", len(all_ids))
        else:
            _log.info("IMAP SINCE 未生效 (返回全部 %d), 将做客户端日期过滤", len(all_ids))

        # Newest first
        all_ids = list(reversed(all_ids))

        messages: list[MailMessage] = []
        skip_old = 0
        skip_proc = 0
        errors = 0
        consec_old = 0

        # When SINCE doesn't work, we must scan deeper.
        # Only stop early after scanning at least 200 IDs and hitting 100
        # consecutive old emails (server ordering is not strictly chronological).
        early_stop_min_scan = 200
        early_stop_consec = 100

        for i, mid in enumerate(all_ids):
            if limit and len(messages) >= limit:
                _log.info("已达上限 %d，停止", limit)
                break
            if (not since_works
                    and i >= early_stop_min_scan
                    and consec_old >= early_stop_consec):
                _log.info(
                    "已扫描 %d 封, 连续 %d 封过旧, 停止",
                    i, consec_old,
                )
                break

            try:
                # Lightweight fetch: UID + INTERNALDATE
                st, meta = self._conn.fetch(mid, "(UID INTERNALDATE)")
                if st != "OK":
                    continue
                meta_s = self._meta_bytes(meta)

                uid = self._parse_uid(meta_s)
                if uid is None:
                    continue
                if uid in processed_uids:
                    skip_proc += 1
                    consec_old = 0  # processed ≠ old, reset counter
                    continue

                # Client-side date check
                if not since_works:
                    idate = self._parse_internaldate(meta_s)
                    if idate and idate < cutoff:
                        skip_old += 1
                        consec_old += 1
                        continue
                consec_old = 0

                # Full fetch
                st, body = self._conn.fetch(mid, "(RFC822)")
                if st != "OK":
                    errors += 1
                    continue
                raw = body[0][1]
                msg = MailMessage(uid=uid, raw_msg=_email.message_from_bytes(raw))
                messages.append(msg)

                if (i + 1) % 50 == 0:
                    _log.info(
                        "扫描进度: %d/%d — 获取 %d, 跳过 %d(已处理)+%d(过旧)",
                        i + 1, len(all_ids), len(messages), skip_proc, skip_old,
                    )
            except Exception as exc:
                errors += 1
                _log.debug("处理 msg_id=%s 出错: %s", mid, exc)

        _log.info(
            "获取完成: 扫描 %d/%d, 新增 %d, "
            "跳过 %d(已处理)+%d(过旧), 出错 %d",
            min(i + 1, len(all_ids)), len(all_ids),
            len(messages), skip_proc, skip_old, errors,
        )
        return messages

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _meta_bytes(meta) -> str:
        raw = meta[0] if meta[0] else b""
        if isinstance(raw, tuple):
            raw = raw[0]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return str(raw)

    @staticmethod
    def _parse_uid(s: str) -> int | None:
        m = re.search(r"UID\s+(\d+)", s)
        return int(m[1]) if m else None

    @staticmethod
    def _parse_internaldate(s: str) -> datetime | None:
        m = re.search(r'INTERNALDATE\s+"(\d{1,2}-\w{3}-\d{4})\s+[\d:]+\s+[+-]?\d{4}"', s)
        if m:
            try:
                return datetime.strptime(m[1], "%d-%b-%Y")
            except ValueError:
                pass
        return None

    # ── Phase 1: lightweight header scan ─────────────────────────────

    def scan_headers(
        self,
        folder: str = "INBOX",
        months_back: int = 3,
        since_date: str = "",
        known_uids: set[int] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Lightweight scan: fetch only UID + Subject + From + Date.

        Returns list of {"uid", "subject", "sender", "date"} dicts.
        ~10x faster than full RFC822 fetch.
        """
        if not self._conn:
            raise ConnectionError("未连接")

        known_uids = known_uids or set()

        status, data = self._conn.select(folder, readonly=True)
        if status != "OK":
            _log.error("无法打开文件夹 %s", folder)
            return []
        self._selected_folder = folder

        total = int(data[0])
        _log.info("文件夹 %s 共 %d 封邮件", folder, total)

        # Determine cutoff
        if since_date:
            try:
                cutoff = datetime.strptime(since_date, "%Y-%m-%d")
                _log.info("增量扫描: 从 %s 开始", since_date)
            except ValueError:
                cutoff = datetime.now() - timedelta(days=months_back * 30)
        else:
            cutoff = datetime.now() - timedelta(days=months_back * 30)

        _log.info("扫描日期范围: %s 至今", cutoff.strftime("%Y-%m-%d"))

        # IMAP SINCE hint
        since_str = cutoff.strftime("%d-%b-%Y")
        # Use standard imaplib SEARCH syntax (without raw nested parentheses) for best compatibility
        status, raw_ids = self._conn.search(None, 'SINCE', since_str)
        if status != "OK":
            return []

        all_ids = raw_ids[0].split()
        since_works = len(all_ids) < total
        if since_works:
            _log.info("IMAP SINCE 生效: %d 封", len(all_ids))
        else:
            _log.info("IMAP SINCE 未生效, 将客户端过滤 (%d 封)", len(all_ids))

        # Newest first
        all_ids = list(reversed(all_ids))

        headers: list[dict] = []
        skip_known = 0
        skip_old = 0
        errors = 0
        consec_old = 0
        i = 0

        # When IMAP SINCE doesn't work, stop early after scanning at least 100 emails
        # and hitting 50 consecutive old emails, or immediately after hitting 10 consecutive known emails.
        early_stop_min_scan = 100
        early_stop_consec = 50
        early_stop_known = 10
        consec_known = 0

        for i, mid in enumerate(all_ids):
            if limit and len(headers) >= limit:
                _log.info("已达上限 %d", limit)
                break

            if (not since_works
                    and i >= early_stop_min_scan
                    and consec_old >= early_stop_consec):
                _log.info(
                    "扫描提前结束: 已处理 %d 封, 连续 %d 封过旧",
                    i, consec_old,
                )
                break

            if since_date and consec_known >= early_stop_known:
                _log.info(
                    "增量扫描提前结束: 连续 %d 封为已扫描邮件",
                    consec_known,
                )
                break

            try:
                # Single lightweight fetch: UID + INTERNALDATE + HEADERS
                st, meta = self._conn.fetch(mid, "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
                if st != "OK":
                    continue
                meta_s = self._meta_bytes(meta)

                uid = self._parse_uid(meta_s)
                if uid is None:
                    continue
                if uid in known_uids:
                    skip_known += 1
                    consec_known += 1
                    continue

                # We found a new (unscanned) email, reset known counter
                consec_known = 0

                # Date filter
                idate = self._parse_internaldate(meta_s)
                if idate and idate < cutoff:
                    skip_old += 1
                    if not since_works:
                        consec_old += 1
                    continue

                if not since_works:
                    consec_old = 0

                # Parse the returned RFC822 headers
                header_block = b""
                for part in meta:
                    if isinstance(part, tuple) and len(part) > 1:
                        header_block = part[1]
                        break

                parsed_msg = _email.message_from_bytes(header_block)
                subject = _decode_mime(parsed_msg.get("Subject", ""))
                sender = _decode_mime(parsed_msg.get("From", ""))
                date_str = idate.strftime("%Y-%m-%d") if idate else ""

                headers.append({
                    "uid": uid,
                    "subject": subject,
                    "sender": sender,
                    "date": date_str,
                })

                if (i + 1) % 100 == 0:
                    _log.info(
                        "扫描进度: %d/%d — 获取 %d, 跳过 %d(已知)+%d(过旧)",
                        i + 1, len(all_ids), len(headers), skip_known, skip_old,
                    )
            except Exception as exc:
                errors += 1
                if "EOF" in str(exc) or "socket" in str(exc).lower():
                    _log.warning("连接断开，尝试重连… (%s)", exc)
                    try:
                        self._conn = imaplib.IMAP4_SSL(self._server, self._port)
                        self._conn.login(self._address, self._auth_code or "")
                        self._conn.select(folder, readonly=True)
                        self._selected_folder = folder
                        _log.info("重连成功，继续扫描")
                    except Exception:
                        _log.error("重连失败，停止扫描")
                        break
                else:
                    _log.debug("扫描 msg_id=%s 出错: %s", mid, exc)

        _log.info(
            "头扫描完成: 扫描 %d/%d, 新增 %d, "
            "跳过 %d(已知)+%d(过旧), 出错 %d",
            min(i + 1, len(all_ids)) if all_ids else 0, len(all_ids),
            len(headers), skip_known, skip_old, errors,
        )
        return headers

    # ── Phase 2: fetch single email by UID ───────────────────────────

    def fetch_by_uid(self, uid: int, folder: str = "INBOX") -> MailMessage | None:
        """Fetch a single email's full RFC822 content by UID."""
        if not self._conn:
            return None
        try:
            # Ensure folder is selected (crucial for --download-only mode)
            if self._selected_folder != folder:
                self._conn.select(folder, readonly=True)
                self._selected_folder = folder
            st, data = self._conn.uid("FETCH", str(uid), "(RFC822)")
            if st != "OK" or not data or data[0] is None:
                return None
            raw = data[0][1]
            return MailMessage(uid=uid, raw_msg=_email.message_from_bytes(raw))
        except Exception as exc:
            _log.debug("fetch_by_uid(%d) 失败: %s", uid, exc)
            return None
