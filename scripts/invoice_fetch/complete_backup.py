"""Portable database-and-material backup with verified, staged restore.

No configuration, credentials, logs, or unrelated local files are included.
Restore installs materials in a new directory and commits the database last,
so an interrupted or rejected restore cannot overwrite existing originals.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .db_backup import create_verified_database_backup, restore_verified_database_backup, validate_current_database

MAX_BACKUP_BYTES = 2 * 1024**3
MAX_BACKUP_FILES = 10_000
MATERIAL_PREFIX = "attachments/complete-restore/"


class MissingMaterialsError(ValueError):
    """Actionable local-only summary; never includes filesystem paths."""

    def __init__(self, issues):
        self.issues = tuple(issues)
        lines = []
        for item in self.issues[:20]:
            number = str(item["invoice_number"] or "").replace("\n", " ").replace("\r", " ")[:64]
            entity = "材料" if item.get("record_role") == "evidence" else "发票"
            identifier = f"{entity} ID {item['invoice_id']}" + (f"（票号 {number}）" if number else "")
            lines.append(f"{identifier}：{item['kind']}缺失")
        if len(self.issues) > 20:
            lines.append(f"另外 {len(self.issues) - 20} 处缺失关联")
        super().__init__("完整备份未创建，以下材料缺失，请先补齐；可先创建数据库备份保留记录。\n" + "\n".join(lines))


def _verify_materials(connection, runtime, cancel_check):
    issues = []
    rows = connection.execute(
        "SELECT id, invoice_number, attachment_path, extra_paths, record_role FROM invoices"
    ).fetchall()
    parent_evidence_paths = {
        _material_path_key(runtime, path)
        for _invoice_id, _number, _original, extras, role in rows
        if role != "evidence"
        for path in _paths(extras)
    }

    for invoice_id, number, original, extras, role in rows:
        _check_cancel(cancel_check)
        is_evidence = role == "evidence"
        references = []
        if original and not (is_evidence and _material_path_key(runtime, original) in parent_evidence_paths):
            references.append(("证明材料" if is_evidence else "原件", original))
        if not is_evidence:
            references.extend(("证明材料", path) for path in _paths(extras))
        for kind, reference in references:
            source = Path(reference)
            if not source.is_absolute():
                source = runtime / source
            if not source.is_file():
                issues.append({
                    "invoice_id": invoice_id,
                    "invoice_number": number,
                    "kind": kind,
                    "record_role": role,
                })
    if issues:
        raise MissingMaterialsError(issues)


def _material_path_key(runtime, reference):
    source = Path(reference)
    if not source.is_absolute():
        source = runtime / source
    return str(source.resolve()).casefold()


def _check_cancel(cancel_check):
    if cancel_check is not None and cancel_check():
        raise ValueError("备份操作已取消，原数据保留")


def _paths(raw):
    if not raw:
        return []
    if isinstance(raw, str):
        value = json.loads(raw) if raw.lstrip().startswith("[") else [raw]
    else:
        value = raw
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("材料关联格式不可用")
    return [item for item in value if item.strip()]


def _rows(connection):
    return connection.execute("SELECT id, attachment_path, extra_paths FROM invoices").fetchall()


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_complete_backup(db_path, runtime_dir, *, backup_dir=None, cancel_check=None):
    runtime = Path(runtime_dir)
    destination_dir = Path(backup_dir or Path(db_path).parent / "backups")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"InvoiceHub-complete-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.zip"
    staging_zip = destination.with_suffix(".part")
    try:
        with tempfile.TemporaryDirectory(prefix="ih-complete-", dir=destination_dir) as temp:
            stage = Path(temp)
            snapshot = create_verified_database_backup(db_path, backup_dir=stage, reason="complete")
            stored = {}
            mapping = {}
            total = snapshot.stat().st_size
            with closing(sqlite3.connect(snapshot)) as connection:
                _verify_materials(connection, runtime, cancel_check)
                for invoice_id, original, extras in _rows(connection):
                    references = ([original] if original else []) + _paths(extras)
                    for reference in references:
                        if reference in mapping:
                            continue
                        _check_cancel(cancel_check)
                        source = Path(reference)
                        if not source.is_absolute():
                            source = runtime / source
                        if not source.is_file():
                            raise ValueError("有关联原件或证明材料缺失，无法创建完整备份；请先补齐材料")
                        expected_size = source.stat().st_size
                        total += expected_size
                        if total > MAX_BACKUP_BYTES or len(mapping) >= MAX_BACKUP_FILES - 2:
                            raise ValueError("完整备份超过安全限制（2 GiB／10000文件）")
                        blob = stage / uuid.uuid4().hex
                        digest = hashlib.sha256()
                        copied = 0
                        with source.open("rb") as stream, blob.open("wb") as output:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                _check_cancel(cancel_check)
                                copied += len(chunk)
                                if copied > expected_size:
                                    raise ValueError("材料超过备份安全限制")
                                digest.update(chunk)
                                output.write(chunk)
                        if copied != expected_size or source.stat().st_size != expected_size:
                            raise ValueError("备份期间材料发生变化，请重试")
                        suffix = source.suffix.lower()
                        if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                            suffix = ".bin"
                        key = MATERIAL_PREFIX + digest.hexdigest() + suffix
                        mapping[reference] = key
                        if key not in stored:
                            stored[key] = {"path": blob, "size": copied, "sha256": digest.hexdigest()}
                    connection.execute(
                        "UPDATE invoices SET attachment_path=?, extra_paths=? WHERE id=?",
                        (mapping.get(original, ""), json.dumps([mapping[p] for p in _paths(extras)], ensure_ascii=False), invoice_id),
                    )
                connection.commit()
            validate_current_database(snapshot)
            stored["invoices.db"] = {"path": snapshot, "size": snapshot.stat().st_size, "sha256": _digest(snapshot)}
            manifest = {"format": "invoice-hub-complete", "version": 1, "files": [
                {"name": name, "size": item["size"], "sha256": item["sha256"]} for name, item in stored.items()
            ]}
            manifest_json = json.dumps(manifest, ensure_ascii=False)
            if len(manifest_json.encode("utf-8")) > 1024 * 1024:
                raise ValueError("备份清单超过安全限制，请减少关联材料后重试")
            if sum(item["size"] for item in stored.values()) + len(manifest_json.encode("utf-8")) > MAX_BACKUP_BYTES:
                raise ValueError("完整备份超过2 GiB安全限制")
            with zipfile.ZipFile(staging_zip, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, item in stored.items():
                    _check_cancel(cancel_check)
                    archive.write(item["path"], name)
                archive.writestr("manifest.json", manifest_json)
            # CRC verification must finish before the final filename appears.
            with zipfile.ZipFile(staging_zip) as archive:
                if archive.testzip() is not None:
                    raise ValueError("备份校验失败，未发布备份文件")
            _check_cancel(cancel_check)
            os.replace(staging_zip, destination)
        return destination
    finally:
        staging_zip.unlink(missing_ok=True)


def restore_complete_backup(backup_path, db_path, runtime_dir, *, cancel_check=None):
    runtime = Path(runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    archive_path = Path(backup_path)
    if archive_path.stat().st_size > MAX_BACKUP_BYTES + 16 * 1024 * 1024:
        raise ValueError("备份包超过安全限制")
    installed = runtime / "attachments" / f"complete-restore-{uuid.uuid4().hex}"
    committed = False
    try:
        with tempfile.TemporaryDirectory(prefix="ih-restore-", dir=runtime) as temp:
            stage = Path(temp)
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos]
                if len(infos) > MAX_BACKUP_FILES or len(set(names)) != len(names):
                    raise ValueError("备份文件数量或名称不合法")
                if sum(info.file_size for info in infos) > MAX_BACKUP_BYTES:
                    raise ValueError("备份解压体积超过安全限制")
                info = archive.getinfo("manifest.json")
                if info.file_size > 1024 * 1024:
                    raise ValueError("备份清单超过安全限制")
                manifest = json.loads(archive.read(info))
                if manifest.get("format") != "invoice-hub-complete" or manifest.get("version") != 1:
                    raise ValueError("不是受支持的完整备份")
                entries = manifest.get("files")
                if not isinstance(entries, list) or not entries:
                    raise ValueError("备份清单不可用")
                expected = [entry["name"] for entry in entries]
                if len(set(expected)) != len(expected) or set(names) != set(expected) | {"manifest.json"} or "invoices.db" not in expected:
                    raise ValueError("备份清单与文件不一致")
                for entry in entries:
                    _check_cancel(cancel_check)
                    name = entry["name"]
                    if name != "invoices.db" and not re.fullmatch(r"attachments/complete-restore/[a-f0-9]{64}\.[a-z0-9]{1,10}", name):
                        raise ValueError("备份包含非法路径")
                    member = archive.getinfo(name)
                    if member.file_size != entry["size"] or member.file_size < 0:
                        raise ValueError("备份文件体积不一致")
                    target = stage / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    written = 0
                    with archive.open(member) as stream, target.open("wb") as output:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            _check_cancel(cancel_check)
                            written += len(chunk)
                            if written > member.file_size:
                                raise ValueError("备份文件超限")
                            digest.update(chunk)
                            output.write(chunk)
                    if written != member.file_size or digest.hexdigest() != entry["sha256"]:
                        raise ValueError("备份内容校验失败，原数据未改变")
            snapshot = stage / "invoices.db"
            validate_current_database(snapshot)
            new_prefix = installed.relative_to(runtime).as_posix() + "/"
            with closing(sqlite3.connect(snapshot)) as connection:
                for invoice_id, original, extras in _rows(connection):
                    paths = ([original] if original else []) + _paths(extras)
                    if any(path not in expected or not path.startswith(MATERIAL_PREFIX) for path in paths):
                        raise ValueError("数据库引用未打包的材料，恢复已取消")
                    connection.execute(
                        "UPDATE invoices SET attachment_path=?, extra_paths=? WHERE id=?",
                        (original.replace(MATERIAL_PREFIX, new_prefix, 1) if original else "",
                         json.dumps([path.replace(MATERIAL_PREFIX, new_prefix, 1) for path in _paths(extras)], ensure_ascii=False), invoice_id),
                    )
                connection.commit()
            _check_cancel(cancel_check)
            materials = stage / "attachments" / "complete-restore"
            installed.parent.mkdir(parents=True, exist_ok=True)
            if materials.exists():
                os.replace(materials, installed)
            else:
                installed.mkdir()
            # The caller has closed its live connection; the existing helper
            # validates, retains a safety database and rolls back on failure.
            safety = restore_verified_database_backup(snapshot, db_path, backup_dir=Path(db_path).parent / "backups")
            committed = True
            return safety
    finally:
        if not committed and installed.exists():
            shutil.rmtree(installed)
