# -*- coding: utf-8 -*-
"""Background execution boundary for invoice reparsing.

The GUI supplies immutable invoice snapshots and receives only queued Qt
signals.  Parsing, classification, path resolution, and SQLite mutation all run
inside the worker thread.  The worker opens its own InvoiceDB connection so the
GUI-owned SQLite connection never crosses thread boundaries.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from PySide6.QtCore import QThread, Signal

from ..db import InvoiceDB
from ..invoice_parser import InvoiceParser
from ..reparse_reconciliation import (
    MERGED_INTO_CLAIMED_DUPLICATE,
    REPLACED_UNLINKED_DUPLICATE,
    reconcile_reparsed_invoice,
)
from ..services import _classify
from .helpers import resolve_stored_path


@dataclass(frozen=True)
class ReparseInvoiceSnapshot:
    """Immutable subset of one GUI invoice row required for reparsing."""

    invoice_id: int
    attachment_path: str
    invoice_type: str
    has_extra: bool

    @classmethod
    def from_mapping(cls, invoice: Mapping[str, object]) -> "ReparseInvoiceSnapshot":
        return cls(
            invoice_id=int(invoice.get("id") or 0),
            attachment_path=str(invoice.get("attachment_path") or ""),
            invoice_type=str(invoice.get("invoice_type") or ""),
            has_extra=bool(invoice.get("has_extra") or False),
        )


@dataclass(frozen=True)
class InvoiceReparseRequest:
    """Immutable request snapshot for one review-workbench reparse batch."""

    request_id: int
    invoice_snapshots: tuple[ReparseInvoiceSnapshot, ...]
    db_path: Path
    runtime_dir: Path
    categories: Mapping[str, object]

    @classmethod
    def from_values(
        cls,
        request_id: int,
        invoice_snapshots,
        db_path: Path,
        runtime_dir: Path,
        categories: Mapping[str, object],
    ) -> "InvoiceReparseRequest":
        snapshots = tuple(
            value
            if isinstance(value, ReparseInvoiceSnapshot)
            else ReparseInvoiceSnapshot.from_mapping(value)
            for value in invoice_snapshots
        )
        return cls(
            request_id=int(request_id),
            invoice_snapshots=snapshots,
            db_path=Path(db_path),
            runtime_dir=Path(runtime_dir),
            categories=MappingProxyType(deepcopy(dict(categories or {}))),
        )


def _empty_result(requested_count: int) -> dict:
    return {
        "requested_count": int(requested_count),
        "processed_count": 0,
        "success_count": 0,
        "missing_files": (),
        "duplicate_conflicts": (),
        "parse_failed_files": (),
        "cancelled": False,
    }


def run_invoice_reparse(
    request: InvoiceReparseRequest,
    *,
    should_cancel: Callable[[], bool] | None = None,
    log_callback: Callable[[str], None] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    """Reparse one immutable batch using a worker-owned SQLite connection."""

    should_cancel = should_cancel or (lambda: False)
    log_callback = log_callback or (lambda _message: None)
    progress_callback = progress_callback or (lambda _payload: None)

    requested_count = len(request.invoice_snapshots)
    result = _empty_result(requested_count)
    missing_files: list[str] = []
    parse_failed_files: list[str] = []
    duplicate_conflicts: list[str] = []
    success_count = 0
    processed_count = 0

    parser = InvoiceParser()
    db = InvoiceDB(request.db_path)
    try:
        for snapshot in request.invoice_snapshots:
            if should_cancel():
                result["cancelled"] = True
                break

            inv_id = snapshot.invoice_id
            attachment_path = snapshot.attachment_path

            if not attachment_path:
                missing_files.append(f"发票 ID {inv_id}: 无附件文件记录")
            else:
                file_path = resolve_stored_path(attachment_path, request.runtime_dir)
                if not file_path or not file_path.exists():
                    missing_files.append(
                        f"发票 ID {inv_id}: 文件不存在 ({attachment_path})"
                    )
                else:
                    try:
                        info = parser.parse_pdf(str(file_path))
                        if info.parse_success:
                            category, extra_type, extra_required = _classify(
                                file_path.name,
                                "local import",
                                info.seller_name,
                                request.categories,
                            )
                            reconciliation = reconcile_reparsed_invoice(
                                db,
                                inv_id,
                                invoice_number=info.invoice_number,
                                invoice_code=info.invoice_code,
                                invoice_date=info.invoice_date,
                                amount=info.amount,
                                total_amount=info.total_amount,
                                seller_name=info.seller_name,
                                buyer_name=info.buyer_name,
                                invoice_type=(
                                    info.invoice_type
                                    or snapshot.invoice_type
                                    or "电子发票"
                                ),
                                category=category,
                                has_extra=snapshot.has_extra,
                                extra_type=extra_type,
                                missing_extra=extra_required,
                                parse_success=True,
                                parse_note=info.parse_note or "重新解析",
                                item_name=getattr(info, "item_name", ""),
                                expense_date=getattr(info, "expense_date", ""),
                                date_source=getattr(info, "date_source", ""),
                            )
                            if reconciliation.success:
                                duplicate_id = reconciliation.duplicate_invoice_id
                                if reconciliation.action == REPLACED_UNLINKED_DUPLICATE:
                                    duplicate_conflicts.append(
                                        f"发票 ID {inv_id}: 已删除旧重复记录 ID {duplicate_id}"
                                    )
                                    log_callback(
                                        f"🔁 [重新解析] 发票 ID {inv_id} 命中旧重复记录 ID {duplicate_id}，"
                                        "已删除旧记录并修复当前记录"
                                    )
                                elif reconciliation.action == MERGED_INTO_CLAIMED_DUPLICATE:
                                    log_callback(
                                        f"🔁 [重新解析] 发票 ID {inv_id} 命中已关联报销组的重复记录 ID {duplicate_id}，"
                                        "改为更新该主记录"
                                    )
                                    log_callback(
                                        f"✅ [重新解析] 发票 ID {inv_id} 已合并到主记录 ID "
                                        f"{reconciliation.target_invoice_id}"
                                    )
                                else:
                                    log_callback(
                                        f"✅ [重新解析] 发票 ID {inv_id} 已更新解析结果"
                                    )
                                success_count += 1
                            elif reconciliation.error == "unique_conflict":
                                duplicate_conflicts.append(
                                    f"发票 ID {inv_id}: 解析结果与已有发票唯一键冲突"
                                )
                                log_callback(
                                    f"⚠️ [重新解析] 发票 ID {inv_id} 与已有发票重复，未覆盖当前记录"
                                )
                            elif reconciliation.duplicate_invoice_id is not None:
                                duplicate_conflicts.append(
                                    f"发票 ID {inv_id}: 重复记录 ID "
                                    f"{reconciliation.duplicate_invoice_id} 协调失败，事务已回滚"
                                )
                                log_callback(
                                    f"⚠️ [重新解析] 发票 ID {inv_id} 重复协调失败，原子事务已回滚 "
                                    f"({reconciliation.error})"
                                )
                            else:
                                parse_failed_files.append(
                                    f"发票 ID {inv_id}: 解析结果写入失败 ({info.parse_note})"
                                )
                        else:
                            parse_failed_files.append(
                                f"发票 ID {inv_id}: 解析失败 ({info.parse_note})"
                            )
                    except Exception as exc:
                        parse_failed_files.append(
                            f"发票 ID {inv_id}: 异常 ({str(exc)})"
                        )

            processed_count += 1
            progress_callback(
                {
                    "processed": processed_count,
                    "total": requested_count,
                    "invoice_id": inv_id,
                }
            )
    finally:
        db.close()

    result.update(
        {
            "processed_count": processed_count,
            "success_count": success_count,
            "missing_files": tuple(missing_files),
            "duplicate_conflicts": tuple(duplicate_conflicts),
            "parse_failed_files": tuple(parse_failed_files),
        }
    )
    return result


class InvoiceReparseWorker(QThread):
    """Run one invoice reparse batch outside the Qt GUI thread."""

    log = Signal(str)
    progress = Signal(dict)
    result = Signal(object)
    error = Signal(str)

    def __init__(self, request: InvoiceReparseRequest, parent=None):
        super().__init__(parent)
        self.request = request

    @property
    def request_id(self) -> int:
        return int(self.request.request_id) if self.request is not None else -1

    def request_cancel(self) -> None:
        self.requestInterruption()

    @staticmethod
    def _safe_error_text(_error: Exception) -> str:
        return "重新解析失败，请稍后重试。"

    def run(self) -> None:
        request = self.request
        if request is None:
            return
        try:
            payload = run_invoice_reparse(
                request,
                should_cancel=self.isInterruptionRequested,
                log_callback=self.log.emit,
                progress_callback=self.progress.emit,
            )
            self.result.emit(payload)
        except Exception as exc:
            self.error.emit(self._safe_error_text(exc))
        finally:
            self.request = None
