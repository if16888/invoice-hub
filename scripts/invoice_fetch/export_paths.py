"""User-owned export paths and migration from the legacy install-local folder."""

from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4


def get_documents_directory() -> Path:
    """Return the platform Documents directory without embedding a user name."""
    if sys.platform == "win32":
        path_ptr = ctypes.c_wchar_p()
        folder_id = UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7")
        guid = (ctypes.c_ubyte * 16).from_buffer_copy(folder_id.bytes_le)
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
        )
        if result == 0 and path_ptr.value:
            try:
                return Path(path_ptr.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
    return Path.home() / "Documents"


def default_export_directory(documents_dir: Path | None = None) -> Path:
    return (documents_dir or get_documents_directory()) / "Invoice Hub" / "Exports"


def resolve_export_directory(config: dict | None, documents_dir: Path | None = None) -> Path:
    configured = str((config or {}).get("export", {}).get("output_dir") or "").strip()
    return Path(configured).expanduser() if configured else default_export_directory(documents_dir)


@dataclass
class ExportMigrationResult:
    source: Path
    destination: Path
    processed: int = 0
    total: int = 0
    copied: int = 0
    conflicts: int = 0
    failures: list[str] = field(default_factory=list)
    source_remains: bool = False

    @property
    def attempted(self) -> bool:
        return self.copied > 0 or self.conflicts > 0 or bool(self.failures) or self.source_remains


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _conflict_target(target: Path, digest: str) -> Path:
    return target.with_name(f"{target.stem}.migrated-{digest[:8]}{target.suffix}")


def _notify_migration_progress(
    callback: Callable[[dict], None] | None,
    result: ExportMigrationResult,
) -> None:
    if callback is None:
        return
    callback(
        {
            "processed": result.processed,
            "total": result.total,
            "copied": result.copied,
            "conflicts": result.conflicts,
            "failed": len(result.failures),
        }
    )


def _copy_verified_atomically(source: Path, target: Path, source_digest: str) -> None:
    """Copy to a private temporary file before making the final target visible."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.invoice-hub-migrating-{uuid4().hex}.tmp"
    )
    try:
        shutil.copy2(source, temporary)
        if _digest(temporary) != source_digest:
            raise OSError("迁移复制校验失败")
        # On Windows os.rename refuses to replace an existing destination.  The
        # existence check below also turns a concurrent destination race into a
        # safe failure instead of overwriting a user file.
        if target.exists():
            raise FileExistsError(str(target))
        os.rename(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def migrate_legacy_exports(
    source: Path,
    destination: Path,
    progress_callback: Callable[[dict], None] | None = None,
) -> ExportMigrationResult:
    """Copy-verify legacy exports, then remove only verified source files/empty dirs.

    Existing files are never overwritten. A deterministic digest suffix makes retries
    idempotent after an interrupted migration.  Progress is reported from the caller's
    worker thread so the GUI can show counts without doing any file I/O on the UI thread.
    """
    source = Path(source)
    destination = Path(destination)
    result = ExportMigrationResult(source, destination)
    source_resolved = source.resolve()
    destination_resolved = destination.resolve()
    if (
        not source.is_dir()
        or source_resolved == destination_resolved
        or source_resolved in destination_resolved.parents
    ):
        return result

    files = sorted(item for item in source.rglob("*") if item.is_file())
    result.total = len(files)
    _notify_migration_progress(progress_callback, result)
    last_progress_at = time.monotonic()

    for item in files:
        relative = item.relative_to(source)
        target = destination / relative
        try:
            source_digest = _digest(item)
            if target.exists():
                if target.is_file() and _digest(target) == source_digest:
                    pass
                else:
                    target = _conflict_target(target, source_digest)
                    result.conflicts += 1
                    if target.exists() and _digest(target) != source_digest:
                        raise OSError("迁移冲突目标已存在且内容不同")
            if not target.exists():
                _copy_verified_atomically(item, target, source_digest)
                result.copied += 1
            item.unlink()
        except Exception as exc:
            result.failures.append(f"{relative.as_posix()}: {type(exc).__name__}: {exc}")
        finally:
            result.processed += 1
            now = time.monotonic()
            if (
                result.processed == result.total
                or result.processed % 25 == 0
                or now - last_progress_at >= 1.0
            ):
                last_progress_at = now
                _notify_migration_progress(progress_callback, result)

    for directory in sorted((p for p in source.rglob("*") if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        source.rmdir()
    except OSError:
        pass
    result.source_remains = source.exists()
    return result
