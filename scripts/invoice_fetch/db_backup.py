"""Small SQLite backup helpers for user-data safety.

This module intentionally stays independent from the GUI so it can be used by
CLI tools, migrations, repair utilities, and future batch-import flows.
"""

from __future__ import annotations

import re
import shutil
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
