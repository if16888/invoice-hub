"""Small SQLite backup helpers for user-data safety.

This module intentionally stays independent from the GUI so it can be used by
CLI tools, migrations, repair utilities, and future batch-import flows.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .config import RUNTIME_DIR
from .migrations import LATEST_SCHEMA_VERSION

DEFAULT_BACKUP_DIR = RUNTIME_DIR / "backups"
_log = logging.getLogger(__name__)


class DatabaseBackupError(RuntimeError):
    """A verified backup or restore could not be completed safely."""


class DatabaseRestoreError(DatabaseBackupError):
    """A restore was rejected or rolled back before it could be committed."""


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


def _path_exists(path: Path) -> bool:
    """Return true for regular files and broken links alike."""
    return os.path.lexists(str(path))


def _private_path(path: Path, purpose: str) -> Path:
    return path.with_name(f".{path.name}.{purpose}-{uuid.uuid4().hex}.tmp")


def _read_sqlite_metadata(path: Path) -> tuple[int, set[str]]:
    if not _path_exists(path) or not path.is_file():
        raise ValueError("所选文件不是可用的数据库备份")
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
            checks = conn.execute("PRAGMA quick_check").fetchall()
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        raise ValueError("所选文件不是可用的 SQLite 数据库") from exc
    if not checks or any(str(row[0]).lower() != "ok" for row in checks):
        raise ValueError("所选数据库未通过完整性检查")
    if version < 0 or version > LATEST_SCHEMA_VERSION:
        raise ValueError("所选数据库版本高于当前应用，无法安全恢复")
    return version, tables


def validate_sqlite_database(
    db_path: str | Path,
    *,
    required_tables: tuple[str, ...] = (),
) -> None:
    """Raise ``ValueError`` unless a SQLite file is healthy and supported."""
    _version, tables = _read_sqlite_metadata(Path(db_path))
    if any(table not in tables for table in required_tables):
        raise ValueError("所选文件不是 Invoice Hub 数据库备份")


def _migrate_and_validate_database(
    db_path: Path,
    *,
    required_tables: tuple[str, ...],
) -> None:
    """Run the real application migrations on a private copy, then verify it."""
    db = None
    try:
        # Import lazily so db.py does not depend on this module at import time.
        from .db import InvoiceDB

        db = InvoiceDB(db_path)
        version = int(db._conn.execute("PRAGMA user_version").fetchone()[0])
        if version != LATEST_SCHEMA_VERSION:
            raise DatabaseBackupError("数据库迁移未达到当前支持的架构版本")
    except DatabaseBackupError:
        raise
    except Exception as exc:
        raise DatabaseBackupError("数据库迁移或重新打开校验失败") from exc
    finally:
        if db is not None:
            db.close()
    validate_sqlite_database(db_path, required_tables=required_tables)


def _remove_private_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        try:
            sidecar.unlink(missing_ok=True)
        except OSError as exc:
            raise DatabaseBackupError("无法清理临时数据库文件") from exc


def create_verified_database_backup(
    db_path: str | Path,
    *,
    backup_dir: str | Path | None = None,
    reason: str = "manual",
    now: datetime | None = None,
    required_tables: tuple[str, ...] = ("invoices",),
) -> Path:
    """Create a consistent, migrated, and integrity-checked SQLite backup."""
    source = Path(db_path)
    validate_sqlite_database(source, required_tables=required_tables)
    dest_dir = Path(backup_dir) if backup_dir is not None else DEFAULT_BACKUP_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    suffix = source.suffix or ".db"
    dest = _unique_path(
        dest_dir / f"{source.stem}-{timestamp}-before-{_sanitize_reason(reason)}{suffix}"
    )
    try:
        with (
            closing(sqlite3.connect(str(source), timeout=5)) as source_conn,
            closing(sqlite3.connect(str(dest), timeout=5)) as dest_conn,
        ):
            source_conn.backup(dest_conn)
        _migrate_and_validate_database(dest, required_tables=required_tables)
    except Exception as exc:
        try:
            dest.unlink(missing_ok=True)
            _remove_private_sidecars(dest)
        except Exception:
            _log.warning("verified backup cleanup failed", exc_info=True)
        if isinstance(exc, (ValueError, DatabaseBackupError)):
            raise
        raise DatabaseBackupError("数据库备份创建失败") from exc
    return dest


def _move_existing_sidecars(destination: Path) -> dict[Path, Path]:
    moved: dict[Path, Path] = {}
    try:
        for suffix in ("-wal", "-shm"):
            original = destination.with_name(destination.name + suffix)
            if not _path_exists(original):
                continue
            temporary = _private_path(destination, f"restore-sidecar{suffix}")
            os.replace(str(original), str(temporary))
            moved[original] = temporary
    except OSError as exc:
        try:
            _restore_sidecars(moved)
        except OSError as restore_exc:
            raise DatabaseRestoreError("数据库旁路文件保护失败，且无法恢复原文件") from restore_exc
        raise DatabaseRestoreError("数据库旁路文件无法安全保护，恢复已取消") from exc
    return moved


def _restore_sidecars(moved: dict[Path, Path]) -> None:
    for original, temporary in reversed(list(moved.items())):
        if _path_exists(temporary):
            os.replace(str(temporary), str(original))


def _discard_path(path: Path) -> None:
    if not _path_exists(path):
        return
    try:
        os.unlink(str(path))
    except OSError as exc:
        raise DatabaseRestoreError("无法清理临时数据库文件") from exc


def _rollback_restore(
    destination: Path,
    rollback_db: Path | None,
    moved_sidecars: dict[Path, Path],
) -> None:
    """Restore the original DB and sidecars without deleting user data."""
    errors: list[BaseException] = []
    if _path_exists(destination):
        displaced = _private_path(destination, "restore-failed-candidate")
        try:
            os.replace(str(destination), str(displaced))
            _discard_path(displaced)
        except BaseException as exc:  # pragma: no cover - catastrophic OS failure
            errors.append(exc)
    if rollback_db is not None and _path_exists(rollback_db):
        try:
            os.replace(str(rollback_db), str(destination))
        except BaseException as exc:  # pragma: no cover - catastrophic OS failure
            errors.append(exc)
    try:
        _restore_sidecars(moved_sidecars)
    except BaseException as exc:  # pragma: no cover - catastrophic OS failure
        errors.append(exc)
    if errors:
        raise DatabaseRestoreError("恢复失败，原数据库无法自动回滚") from errors[0]


def restore_verified_database_backup(
    backup_path: str | Path,
    db_path: str | Path,
    *,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
    reopen_validator: Callable[[Path], None] | None = None,
    required_tables: tuple[str, ...] = ("invoices",),
) -> Path:
    """Restore a backup with a sidecar-safe atomic transaction.

    The caller must stop all data workers and close the live application DB.
    The selected backup is copied to a private staging file, migrated and
    validated there, then atomically swapped into place.  Existing ``-wal`` and
    ``-shm`` files are moved to transaction-owned paths before the swap; any
    failure before or after replacement restores the original DB and sidecars.
    """
    selected = Path(backup_path)
    destination = Path(db_path)
    validate_sqlite_database(selected, required_tables=required_tables)
    validate_sqlite_database(destination, required_tables=required_tables)
    safety_backup = create_verified_database_backup(
        destination,
        backup_dir=backup_dir,
        reason="restore-safety",
        now=now,
        required_tables=required_tables,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = _private_path(destination, "restore-staging")
    rollback_db: Path | None = None
    moved_sidecars: dict[Path, Path] = {}
    original_moved = False
    try:
        try:
            shutil.copy2(selected, staging)
            _migrate_and_validate_database(staging, required_tables=required_tables)
            _remove_private_sidecars(staging)
        except (ValueError, DatabaseBackupError):
            raise
        except OSError as exc:
            raise DatabaseRestoreError("备份文件无法复制或验证") from exc

        moved_sidecars = _move_existing_sidecars(destination)
        rollback_db = _private_path(destination, "restore-original")
        try:
            os.replace(str(destination), str(rollback_db))
            original_moved = True
            os.replace(str(staging), str(destination))
        except OSError as exc:
            raise DatabaseRestoreError("数据库替换失败，恢复已取消") from exc

        try:
            if reopen_validator is None:
                _migrate_and_validate_database(destination, required_tables=required_tables)
            else:
                reopen_validator(destination)
            validate_sqlite_database(destination, required_tables=required_tables)
        except Exception as exc:
            try:
                _rollback_restore(destination, rollback_db, moved_sidecars)
                original_moved = False
            except DatabaseRestoreError:
                raise
            raise DatabaseRestoreError("恢复后的数据库无法重新打开，已自动回滚") from exc

        # These are private transaction files, never user data.  If cleanup is
        # interrupted, keep the old copy rather than risking data loss; the
        # valid restored DB is already committed and the safety backup remains.
        try:
            if rollback_db is not None:
                _discard_path(rollback_db)
            for temporary in moved_sidecars.values():
                _discard_path(temporary)
        except DatabaseRestoreError:
            _log.warning("restore transaction cleanup left a private safety file", exc_info=True)
        rollback_db = None
        moved_sidecars = {}
        original_moved = False
        return safety_backup
    except Exception as exc:
        if original_moved:
            try:
                _rollback_restore(destination, rollback_db, moved_sidecars)
            except DatabaseRestoreError:
                raise
        else:
            try:
                _restore_sidecars(moved_sidecars)
            except OSError as restore_exc:
                raise DatabaseRestoreError("恢复失败，原数据库旁路文件无法恢复") from restore_exc
        if isinstance(exc, (ValueError, DatabaseRestoreError, DatabaseBackupError)):
            raise
        raise DatabaseRestoreError("数据库恢复失败，原数据库未被替换") from exc
    finally:
        try:
            if _path_exists(staging):
                _discard_path(staging)
            _remove_private_sidecars(staging)
        except Exception:
            _log.warning("restore staging cleanup failed", exc_info=True)


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
