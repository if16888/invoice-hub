"""Small SQLite backup helpers for user-data safety.

This module intentionally stays independent from the GUI so it can be used by
CLI tools, migrations, repair utilities, and future batch-import flows.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .config import RUNTIME_DIR

DEFAULT_BACKUP_DIR = RUNTIME_DIR / "backups"


def _sanitize_reason(reason: str, *, max_len: int = 48) -> str:
    """Return a filesystem-safe backup reason slug."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (reason or "manual").strip().lower())
    slug = slug.strip("-._") or "manual"
    return slug[:max_len].strip("-._") or "manual"


def _unique_path(path: Path) -> Path:
    """Return a non-existing path by appending a numeric suffix when needed."""
    if not path.exists():
        return path
    for idx in range(1, 1000):
        candidate = path.with_name(f"{path.stem}-{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Unable to allocate backup path under {path.parent}")


def create_database_backup(
    db_path: str | Path,
    *,
    backup_dir: str | Path | None = None,
    reason: str = "manual",
    now: datetime | None = None,
) -> Path:
    """Copy a SQLite database file to a timestamped backup path.

    Args:
        db_path: Existing SQLite database file.
        backup_dir: Destination directory. Defaults to ``runtime/backups``.
        reason: Short operation label, such as ``before-migration`` or
            ``before-mobile-import``. It is sanitized before becoming part of
            the filename.
        now: Optional timestamp injection for deterministic tests.

    Returns:
        The created backup file path.

    Raises:
        FileNotFoundError: If ``db_path`` does not exist.
        ValueError: If ``db_path`` is not a regular file.
    """
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(source)
    if not source.is_file():
        raise ValueError(f"Database path is not a file: {source}")

    dest_dir = Path(backup_dir) if backup_dir is not None else DEFAULT_BACKUP_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    reason_slug = _sanitize_reason(reason)
    suffix = source.suffix or ".db"
    dest = dest_dir / f"{source.stem}-{timestamp}-before-{reason_slug}{suffix}"
    dest = _unique_path(dest)
    shutil.copy2(source, dest)
    return dest


def validate_sqlite_database(
    db_path: str | Path,
    *,
    required_tables: tuple[str, ...] = (),
) -> None:
    """Raise ``ValueError`` unless *db_path* is a readable, healthy SQLite DB."""
    path = Path(db_path)
    if not path.exists() or not path.is_file():
        raise ValueError("所选文件不是可用的数据库备份")
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
            rows = conn.execute("PRAGMA quick_check").fetchall()
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        raise ValueError("所选文件不是可用的 SQLite 数据库") from exc
    if not rows or any(str(row[0]).lower() != "ok" for row in rows):
        raise ValueError("所选数据库未通过完整性检查")
    available_tables = {str(row[0]) for row in table_rows}
    if any(table not in available_tables for table in required_tables):
        raise ValueError("所选文件不是 Invoice Hub 数据库备份")


def create_verified_database_backup(
    db_path: str | Path,
    *,
    backup_dir: str | Path | None = None,
    reason: str = "manual",
    now: datetime | None = None,
) -> Path:
    """Create and verify a transactionally consistent SQLite backup."""
    source = Path(db_path)
    validate_sqlite_database(source)
    dest_dir = Path(backup_dir) if backup_dir is not None else DEFAULT_BACKUP_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    suffix = source.suffix or ".db"
    dest = _unique_path(
        dest_dir / f"{source.stem}-{timestamp}-before-{_sanitize_reason(reason)}{suffix}"
    )
    try:
        with (
            closing(sqlite3.connect(source)) as source_conn,
            closing(sqlite3.connect(dest)) as dest_conn,
        ):
            source_conn.backup(dest_conn)
        validate_sqlite_database(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return dest


def restore_verified_database_backup(
    backup_path: str | Path,
    db_path: str | Path,
    *,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Replace a closed live DB from a verified backup and keep a safety copy.

    The caller must close every live connection before invoking this function.
    The selected backup is never modified. The destination is replaced only
    after a private staging copy has passed SQLite integrity validation.
    """
    selected = Path(backup_path)
    destination = Path(db_path)
    validate_sqlite_database(selected, required_tables=("invoices",))
    validate_sqlite_database(destination, required_tables=("invoices",))
    safety_backup = create_verified_database_backup(
        destination,
        backup_dir=backup_dir,
        reason="restore-safety",
        now=now,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = _unique_path(destination.with_name(f".{destination.name}.restore-staging"))
    try:
        shutil.copy2(selected, staging)
        validate_sqlite_database(staging, required_tables=("invoices",))
        os.replace(staging, destination)
        for suffix in ("-wal", "-shm"):
            try:
                destination.with_name(destination.name + suffix).unlink(missing_ok=True)
            except OSError:
                # A stale sidecar is best-effort cleanup after the atomic DB
                # replacement; it must not turn a completed restore into a
                # reported failure.
                pass
    except Exception:
        staging.unlink(missing_ok=True)
        raise
    return safety_backup


def prune_database_backups(
    backup_dir: str | Path | None = None,
    *,
    keep: int = 20,
    pattern: str = "*.db",
) -> list[Path]:
    """Delete older database backups and return the removed paths.

    The newest files by modification time are kept. This helper is deliberately
    conservative: ``keep`` must be non-negative and only regular files matching
    ``pattern`` inside ``backup_dir`` are considered.
    """
    if keep < 0:
        raise ValueError("keep must be non-negative")

    dest_dir = Path(backup_dir) if backup_dir is not None else DEFAULT_BACKUP_DIR
    if not dest_dir.exists():
        return []
    if not dest_dir.is_dir():
        raise ValueError(f"Backup path is not a directory: {dest_dir}")

    backups = sorted(
        (p for p in dest_dir.glob(pattern) if p.is_file()),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    to_remove = backups[keep:]
    removed: list[Path] = []
    for path in to_remove:
        path.unlink()
        removed.append(path)
    return removed
