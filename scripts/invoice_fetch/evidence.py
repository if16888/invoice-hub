"""Shared evidence identities, legacy path migration and atomic associations.

Material records live beside invoices for compatibility with old imports. They
never contribute money or claim items. Relations, rather than a mail UID or a
consumed/deleted record, determine which invoices use each material.
"""

from __future__ import annotations

import json
import posixpath
import re
import sqlite3


def is_evidence_record(record: dict) -> bool:
    return (
        record.get("record_role") == "evidence"
        or record.get("invoice_type") == "待关联证明材料"
        or "待关联证明材料" in str(record.get("parse_note") or "")
    )


def path_key(value: object) -> str:
    # Legacy Windows paths may use either separator. Do not guess identity from
    # filenames or file contents: distinct files remain distinct material records.
    return posixpath.normpath(str(value or "").strip().replace("\\", "/")).casefold()


def material_paths(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = [value]
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    paths, seen = [], set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        key = path_key(item)
        if key not in seen:
            seen.add(key)
            paths.append(item.strip())
    return paths


def visible_invoice_sql(alias: str = "i") -> str:
    """One predicate for financial lists, counts and paginated review scopes."""
    return f"""(
        ({alias}.record_role = 'invoice' AND COALESCE({alias}.invoice_type, '') != '待关联证明材料')
        OR ({alias}.invoice_type = '待关联证明材料' AND ({alias}.is_deleted != 0 OR NOT EXISTS (
            SELECT 1 FROM invoice_evidence_relations er
            JOIN invoices parent ON parent.id = er.invoice_id
            WHERE er.evidence_id = {alias}.id AND parent.is_deleted = 0
        )))
    )"""


def _rows(conn, sql: str, params=()) -> list[dict]:
    cursor = conn.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def refresh_material_projection(conn, invoice_id: int) -> None:
    """Keep old readers' extra_paths/flags consistent with the relation graph."""
    records = _rows(conn, "SELECT * FROM invoices WHERE id=?", (invoice_id,))
    if not records or is_evidence_record(records[0]):
        return
    invoice = records[0]
    sources = _rows(conn, """
        SELECT e.attachment_path, e.is_deleted FROM invoice_evidence_relations r
        JOIN invoices e ON e.id=r.evidence_id WHERE r.invoice_id=?
        ORDER BY r.created_at, e.id
    """, (invoice_id,))
    paths = material_paths([row["attachment_path"] for row in sources])
    live = any(not row["is_deleted"] and str(row["attachment_path"] or "").strip() for row in sources)
    unavailable = any(row["is_deleted"] or not str(row["attachment_path"] or "").strip() for row in sources)
    missing = unavailable or (bool(invoice["evidence_required"]) and not live)
    conn.execute(
        "UPDATE invoices SET extra_paths=?, has_extra=?, missing_extra=?, "
        "extra_type=CASE WHEN ? AND evidence_required=0 THEN '' ELSE extra_type END WHERE id=?",
        (json.dumps(paths, ensure_ascii=False), int(live), int(missing), int(not sources), invoice_id),
    )


def _ensure_source(conn, path: str, parent: dict, known: dict | None = None) -> int:
    key = path_key(path)
    if known is None:
        candidates = _rows(conn, "SELECT * FROM invoices WHERE record_role='evidence' "
                           "OR invoice_type='待关联证明材料'")
        # An active material wins over a deliberately deleted material with the
        # same old path. Reusing a deleted identity must not silently restore it.
        candidates.sort(key=lambda row: (bool(row["is_deleted"]), row["id"]))
        known = {}
        for row in candidates:
            if row["attachment_path"]:
                known.setdefault(path_key(row["attachment_path"]), row["id"])
    if key in known:
        return int(known[key])
    cursor = conn.execute(
        "INSERT INTO invoices (record_role, invoice_type, review_status, attachment_path, "
        "mailbox_key, mail_uid, mail_subject, mail_date, mail_sender, parse_note) "
        "VALUES ('evidence', '证明材料', 'ignored', ?, ?, ?, ?, ?, ?, '从证明材料路径登记')",
        (path, parent.get("mailbox_key") or "legacy", parent.get("mail_uid"),
         parent.get("mail_subject") or "", parent.get("mail_date") or "",
         parent.get("mail_sender") or ""),
    )
    known[key] = cursor.lastrowid
    return int(cursor.lastrowid)


def replace_material_paths(conn, invoice_id: int, paths: object, known: dict | None = None) -> None:
    parent = _rows(conn, "SELECT * FROM invoices WHERE id=?", (invoice_id,))
    if not parent or is_evidence_record(parent[0]):
        return
    ids = tuple(dict.fromkeys(_ensure_source(conn, path, parent[0], known) for path in material_paths(paths)))
    # Removing a link removes the declaration, never the record or its file.
    if ids:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM invoice_evidence_relations WHERE invoice_id=? "
                     f"AND evidence_id NOT IN ({placeholders})", (invoice_id, *ids))
    else:
        conn.execute("DELETE FROM invoice_evidence_relations WHERE invoice_id=?", (invoice_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO invoice_evidence_relations (invoice_id,evidence_id,created_at) "
        "VALUES (?,?,datetime('now','localtime'))", [(invoice_id, evidence_id) for evidence_id in ids],
    )
    refresh_material_projection(conn, invoice_id)


def migrate_shared_evidence(conn) -> None:
    """V14 runs inside the migration savepoint, with no file moves or deletes."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(invoices)")}
    # Very early databases predate material columns altogether. Defaults add
    # unknown information without interpreting old financial records as assets.
    for name, definition in {
        "invoice_type": "TEXT", "parse_note": "TEXT DEFAULT ''",
        "attachment_path": "TEXT DEFAULT ''", "extra_paths": "TEXT DEFAULT '[]'",
        "has_extra": "INTEGER DEFAULT 0", "missing_extra": "INTEGER DEFAULT 0",
        "extra_type": "TEXT DEFAULT ''", "mail_uid": "INTEGER",
        "mail_subject": "TEXT", "mail_date": "TEXT", "mail_sender": "TEXT",
    }.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE invoices ADD COLUMN {name} {definition}")
    if "record_role" not in columns:
        conn.execute("ALTER TABLE invoices ADD COLUMN record_role TEXT NOT NULL DEFAULT 'invoice' "
                     "CHECK(record_role IN ('invoice','evidence'))")
    if "evidence_required" not in columns:
        conn.execute("ALTER TABLE invoices ADD COLUMN evidence_required INTEGER NOT NULL DEFAULT 0 "
                     "CHECK(evidence_required IN (0,1))")
    conn.execute("CREATE TABLE IF NOT EXISTS invoice_evidence_relations ("
                 "invoice_id INTEGER NOT NULL, evidence_id INTEGER NOT NULL, created_at TEXT NOT NULL, "
                 "PRIMARY KEY(invoice_id,evidence_id), CHECK(invoice_id != evidence_id), "
                 "FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE, "
                 "FOREIGN KEY(evidence_id) REFERENCES invoices(id) ON DELETE CASCADE)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_relations_source "
                 "ON invoice_evidence_relations(evidence_id)")
    records = _rows(conn, "SELECT * FROM invoices ORDER BY id")
    parents = [row for row in records if not is_evidence_record(row)]
    declared = {path_key(path): set() for parent in parents for path in material_paths(parent["extra_paths"])}
    for parent in parents:
        for path in material_paths(parent["extra_paths"]):
            declared[path_key(path)].add(parent["id"])
    known = {}
    # Active identities first. A prior 'consumed' source is restored only when
    # its explicit old association marker and the parent's path agree.
    for source in sorted((row for row in records if is_evidence_record(row)),
                         key=lambda row: (bool(row["is_deleted"]), row["id"])):
        conn.execute("UPDATE invoices SET record_role='evidence' WHERE id=?", (source["id"],))
        key = path_key(source["attachment_path"])
        if source["is_deleted"] and any(
            re.search(rf"已关联到发票 ID {parent_id}(?!\d)", str(source["parse_note"] or ""))
            for parent_id in declared.get(key, ())
        ):
            conn.execute("UPDATE invoices SET is_deleted=0 WHERE id=?", (source["id"],))
            source["is_deleted"] = 0
        if source["attachment_path"]:
            known.setdefault(key, source["id"])
    for parent in parents:
        required = bool(parent["missing_extra"] or str(parent["extra_type"] or "").strip())
        conn.execute("UPDATE invoices SET evidence_required=? WHERE id=?", (int(required), parent["id"]))
        if material_paths(parent["extra_paths"]):
            replace_material_paths(conn, parent["id"], parent["extra_paths"], known)


class EvidenceStoreMixin:
    """Database boundaries shared by GUI, importers, preview and export."""

    def list_evidence_sources(self, *, include_deleted: bool = False) -> list[dict]:
        sql = """SELECT e.*,
            (SELECT COUNT(*) FROM invoice_evidence_relations r WHERE r.evidence_id=e.id) AS linked_count,
            (SELECT COUNT(*) FROM invoice_evidence_relations r JOIN invoices p ON p.id=r.invoice_id
             WHERE r.evidence_id=e.id AND p.is_deleted=0) AS active_linked_count
            FROM invoices e WHERE (e.record_role='evidence' OR e.invoice_type='待关联证明材料')"""
        if not include_deleted:
            sql += " AND e.is_deleted=0"
        return _rows(self._conn, sql + " ORDER BY e.id DESC")

    def list_invoice_evidence(self, invoice_id: int) -> list[dict]:
        return _rows(self._conn, """SELECT e.*, r.created_at AS linked_at, e.id AS evidence_id,
            (SELECT COUNT(*) FROM invoice_evidence_relations other WHERE other.evidence_id=e.id) AS linked_count
            FROM invoice_evidence_relations r JOIN invoices e ON e.id=r.evidence_id
            WHERE r.invoice_id=? ORDER BY r.created_at, e.id""", (invoice_id,))

    def evidence_consumers(self, evidence_id: int) -> tuple[int, ...]:
        return tuple(row[0] for row in self._conn.execute(
            "SELECT invoice_id FROM invoice_evidence_relations WHERE evidence_id=? ORDER BY invoice_id",
            (evidence_id,),
        ))

    def is_registered_evidence_path(self, path, runtime_dir) -> bool:
        from pathlib import Path
        incoming = path_key(Path(path).resolve())
        for source in self.list_evidence_sources(include_deleted=True):
            stored = str(source.get("attachment_path") or "").replace("\\", "/")
            if not stored:
                continue
            candidate = Path(stored)
            if not candidate.is_absolute():
                candidate = Path(runtime_dir) / candidate
            if path_key(candidate.resolve()) == incoming:
                return True
        return False

    def _refresh_evidence_consumers(self, evidence_id: int) -> None:
        for invoice_id in self.evidence_consumers(evidence_id):
            refresh_material_projection(self._conn, invoice_id)

    def _with_evidence(self, invoice: dict) -> dict:
        invoice["linked_evidence"] = self.list_invoice_evidence(invoice["id"])
        return invoice

    def link_evidence_to_invoices(self, invoice_ids, evidence_ids) -> int:
        """Associate explicit IDs across any source, all-or-nothing and reusable."""
        targets = tuple(dict.fromkeys(int(value) for value in invoice_ids))
        materials = tuple(dict.fromkeys(int(value) for value in evidence_ids))
        if not targets or not materials:
            return 0
        with self._atomic_savepoint():
            self._conn.execute("UPDATE invoices SET id=id WHERE 0")
            for invoice_id in targets:
                target = self.get_invoice(invoice_id)
                if not target or is_evidence_record(target):
                    raise ValueError("目标发票已删除、不存在或本身是证明材料，请重新选择。")
            for evidence_id in materials:
                source = self.get_invoice(evidence_id)
                if not source or not is_evidence_record(source) or not str(source.get("attachment_path") or "").strip():
                    raise ValueError("证明材料已删除、不存在或没有文件路径，请重新选择。")
                self._conn.execute("UPDATE invoices SET record_role='evidence' WHERE id=?", (evidence_id,))
            count = 0
            for invoice_id in targets:
                # Adopt a legacy path-only row before adding an explicit source.
                target = self.get_invoice(invoice_id)
                if material_paths(target.get("extra_paths")) and not self.list_invoice_evidence(invoice_id):
                    replace_material_paths(self._conn, invoice_id, target["extra_paths"])
                for evidence_id in materials:
                    count += self._conn.execute(
                        "INSERT OR IGNORE INTO invoice_evidence_relations (invoice_id,evidence_id,created_at) "
                        "VALUES (?,?,datetime('now','localtime'))", (invoice_id, evidence_id),
                    ).rowcount
                refresh_material_projection(self._conn, invoice_id)
        return count

    def link_evidence_to_invoice(self, invoice_id: int, evidence_id: int) -> bool:
        try:
            self.link_evidence_to_invoices((invoice_id,), (evidence_id,))
            return True
        except (ValueError, sqlite3.Error):
            return False

    def unlink_evidence_from_invoices(self, invoice_ids, evidence_ids) -> int:
        targets = tuple(dict.fromkeys(int(value) for value in invoice_ids))
        materials = tuple(dict.fromkeys(int(value) for value in evidence_ids))
        if not targets or not materials:
            return 0
        with self._atomic_savepoint():
            self._conn.execute("UPDATE invoices SET id=id WHERE 0")
            for invoice_id in targets:
                target = self.get_invoice(invoice_id)
                if not target or is_evidence_record(target):
                    raise ValueError("目标发票已删除或不存在，请重新选择。")
            count = 0
            for invoice_id in targets:
                for evidence_id in materials:
                    count += self._conn.execute(
                        "DELETE FROM invoice_evidence_relations WHERE invoice_id=? AND evidence_id=?",
                        (invoice_id, evidence_id),
                    ).rowcount
                refresh_material_projection(self._conn, invoice_id)
        return count

    def unlink_evidence_from_invoice(self, invoice_id: int, evidence_id: int) -> bool:
        return bool(self.unlink_evidence_from_invoices((invoice_id,), (evidence_id,)))

    def apply_evidence_changes(self, invoice_ids, additions, removals, *, expected_sources=None) -> tuple[int, int]:
        targets = tuple(dict.fromkeys(int(value) for value in invoice_ids))
        additions = tuple(dict.fromkeys((int(parent), int(source)) for parent, source in additions))
        removals = tuple(dict.fromkeys((int(parent), int(source)) for parent, source in removals))
        if any(parent not in targets for parent, _ in additions + removals):
            raise ValueError("材料关联超出了已选择的发票范围。")
        if set(additions) & set(removals):
            raise ValueError("同一条材料关联不能同时添加和移除。")
        with self._atomic_savepoint():
            self._conn.execute("UPDATE invoices SET id=id WHERE 0")
            # Validate the whole approved target snapshot, even when a particular
            # row has no changes. Never silently expand or partially apply it.
            for parent in targets:
                record = self.get_invoice(parent)
                if not record or is_evidence_record(record):
                    raise ValueError("选择中含已删除的发票或证明材料，请重新选择。")
            if expected_sources is not None:
                for source in {source for _, source in additions}:
                    current = self.get_invoice(source)
                    signature = ((str(current.get("attachment_path") or ""), str(current.get("file_hash") or ""))
                                 if current else None)
                    if source not in expected_sources or signature != expected_sources[source]:
                        raise ValueError("证明材料在选择后已改变，请重新打开材料列表确认。")
            added = sum(self.link_evidence_to_invoices((parent,), (source,)) for parent, source in additions)
            removed = sum(self.unlink_evidence_from_invoices((parent,), (source,)) for parent, source in removals)
        return added, removed
