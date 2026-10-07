"""Shared material lifecycle, migration, transactional recovery and export."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch.claim_export import export_claim_package, inspect_extra_material
from scripts.invoice_fetch.complete_backup import create_complete_backup, restore_complete_backup
from scripts.invoice_fetch.db import InvoiceDB, _SCHEMA
from scripts.invoice_fetch.db_backup import DatabaseBackupError, create_verified_database_backup, restore_verified_database_backup
from scripts.invoice_fetch.evidence import material_paths
from scripts.invoice_fetch.migrations import check_and_migrate, validate_latest_schema
from scripts.invoice_fetch.reparse_reconciliation import reconcile_reparsed_invoice
from scripts.invoice_fetch.review_query import ReviewColumnFilter, ReviewQuery


class EvidenceSharingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.path = self.runtime / "invoices.db"
        self.db = InvoiceDB(self.path)
        self.counter = 0

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def file(self, name):
        path = self.runtime / "attachments" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Synthetic material " + name.encode())
        return path.relative_to(self.runtime).as_posix()

    def invoice(self, **fields):
        self.counter += 1
        return self.db.insert_invoice({
            "invoice_number": f"INV-{self.counter}", "invoice_date": "2026-10-01",
            "total_amount": "100.00", "seller_name": "Synthetic Seller",
            "buyer_name": "Synthetic Buyer", "review_status": "to_review",
            "attachment_path": self.file(f"invoice-{self.counter}.pdf"),
            "confirmed_note": "Keep this note", **fields,
        })

    def evidence(self, **fields):
        self.counter += 1
        return self.db.insert_invoice({
            "invoice_type": "待关联证明材料", "parse_note": "待关联证明材料: 水单",
            "attachment_path": self.file(f"material-{self.counter}.pdf"),
            "mailbox_key": "phone", "mail_uid": None, **fields,
        })

    def relate(self, parents, source):
        return self.db.link_evidence_to_invoices(parents, (source,))

    def test_cross_source_one_material_four_invoices_without_consuming_source(self):
        parents = [self.invoice(mailbox_key=f"email-{n}", mail_uid=n) for n in range(4)]
        source = self.evidence()
        self.assertEqual(self.relate(parents, source), 4)
        self.assertEqual(self.relate(parents, source), 0)
        self.assertEqual(self.db.evidence_consumers(source), tuple(parents))
        self.assertEqual(self.db.get_invoice(source)["is_deleted"], 0)
        for parent in parents:
            record = self.db.get_invoice(parent)
            self.assertEqual(record["confirmed_note"], "Keep this note")
            self.assertEqual(record["review_status"], "to_review")
            self.assertEqual(record["linked_evidence"][0]["id"], source)
            self.assertEqual(record["has_extra"], 1)
        self.assertEqual(self.db.count_invoices(), 4)

    def test_multiple_materials_and_parent_scoped_unlink_keep_other_consumers_and_files(self):
        parents = [self.invoice() for _ in range(2)]
        sources = [self.evidence() for _ in range(2)]
        self.db.link_evidence_to_invoices(parents, sources)
        self.assertTrue(self.db.unlink_evidence_from_invoice(parents[0], sources[0]))
        self.assertEqual(self.db.evidence_consumers(sources[0]), (parents[1],))
        self.assertEqual(len(self.db.list_invoice_evidence(parents[0])), 1)
        for source in sources:
            self.assertTrue((self.runtime / self.db.get_invoice(source)["attachment_path"]).exists())

    def test_required_material_requirement_survives_last_unlink(self):
        parent = self.invoice(missing_extra=1, extra_type="水单", evidence_required=1)
        source = self.evidence()
        self.relate((parent,), source)
        self.assertEqual(self.db.get_invoice(parent)["missing_extra"], 0)
        self.db.unlink_evidence_from_invoice(parent, source)
        record = self.db.get_invoice(parent)
        self.assertEqual(record["missing_extra"], 1)
        self.assertEqual(record["extra_type"], "水单")
        self.assertFalse(self.db.update_invoice_review_status(source, "approved"))

    def test_optional_material_last_unlink_removes_declaration(self):
        parent = self.invoice(extra_type="可选水单", evidence_required=0)
        source = self.evidence()
        self.relate((parent,), source)
        self.db.unlink_evidence_from_invoice(parent, source)
        record = self.db.get_invoice(parent)
        self.assertEqual(record["missing_extra"], 0)
        self.assertEqual(record["extra_type"], "")
        self.assertFalse(inspect_extra_material(record, self.runtime)["unavailable_extra"])

    def test_soft_delete_material_blocks_every_consumer_and_restore_repairs_them(self):
        parents = [self.invoice() for _ in range(2)]
        source = self.evidence(file_hash="synthetic-material-hash")
        self.relate(parents, source)
        self.db.soft_delete_invoice(source)
        self.assertIn(source, {row["id"] for row in self.db.get_all_invoices(include_deleted=True)})
        query = ReviewQuery(column_filters=(ReviewColumnFilter("missing_extra", values=("缺证明",)),))
        self.assertEqual(self.db.count_review_invoices(query), 2)
        for parent in parents:
            record = self.db.get_invoice(parent)
            self.assertEqual(record["missing_extra"], 1)
            self.assertTrue(inspect_extra_material(record, self.runtime)["unavailable_extra"])
        self.db.restore_invoice(source)
        self.assertEqual(self.db.count_review_invoices(query), 0)
        self.assertEqual(self.db.evidence_consumers(source), tuple(parents))
        self.db.soft_delete_invoice(source)
        self.assertEqual(self.db.restore_deleted_invoices_by_file_hashes({"synthetic-material-hash"}), [source])
        self.assertEqual(self.db.count_review_invoices(query), 0)

    def test_parent_soft_delete_restore_and_hard_delete_do_not_delete_material(self):
        parent = self.invoice()
        source = self.evidence()
        self.relate((parent,), source)
        self.db.soft_delete_invoice(parent)
        self.assertEqual(self.db.evidence_consumers(source), (parent,))
        self.assertFalse(self.db.delete_invoice_permanently(source))
        self.db.restore_invoice(parent)
        self.assertEqual(self.db.get_invoice(parent)["linked_evidence"][0]["id"], source)
        self.assertTrue(self.db.delete_invoice_permanently(parent))
        self.assertIsNotNone(self.db.get_invoice(source))
        self.assertEqual(self.db.evidence_consumers(source), ())
        self.assertTrue((self.runtime / self.db.get_invoice(source)["attachment_path"]).exists())

    def test_pending_queue_and_paging_counts_share_same_scope(self):
        parent = self.invoice()
        source = self.evidence(mailbox_key="a", mail_uid=123)
        self.assertEqual(self.db.count_invoices(), 2)
        self.assertEqual(len(self.db.list_pending_evidence_for_mail("a", 123)), 1)
        self.relate((parent,), source)
        query = ReviewQuery(limit=1)
        self.assertEqual(self.db.count_review_invoices(query), 1)
        self.assertEqual(self.db.count_invoices_for_status(), 1)
        self.assertEqual(self.db.list_review_invoice_ids(query), (parent,))
        self.assertEqual([r["id"] for r in self.db.list_invoices()], [parent])
        self.assertEqual([r["id"] for r in self.db.list_invoices_by_ids((source, parent))], [parent])
        self.assertEqual(self.db.list_pending_evidence_for_mail("a", 123), [])
        self.db.unlink_evidence_from_invoice(parent, source)
        self.assertEqual(self.db.count_invoices(), 2)

    def test_legacy_path_api_registers_one_shared_identity_and_keeps_assets_out_of_lists(self):
        path = self.file("shared.pdf")
        a = self.invoice(extra_paths=[path, path.replace("/", "\\")])
        b = self.invoice(extra_paths=[path])
        self.assertEqual(self.db.count_invoices(include_deleted=True), 2)
        source = self.db.list_invoice_evidence(a)[0]["id"]
        self.assertEqual(self.db.list_invoice_evidence(b)[0]["id"], source)
        self.assertEqual(self.db.get_invoice(a)["extra_paths"], json.dumps([path]))
        self.db.update_invoice_file_paths(a, extra_paths=[])
        self.assertEqual(self.db.evidence_consumers(source), (b,))
        self.assertEqual(self.db.count_invoices(), 2)
        self.assertFalse(self.db.add_invoice_to_claim(self.db.create_claim_group("Claim"), source))

    def test_distinct_paths_are_not_merged_by_filename_or_identical_content(self):
        paths = [self.file("a/receipt.pdf"), self.file("b/receipt.pdf")]
        a, b = [self.invoice(extra_paths=[path]) for path in paths]
        self.assertNotEqual(self.db.list_invoice_evidence(a)[0]["id"], self.db.list_invoice_evidence(b)[0]["id"])

    def test_material_amount_does_not_enter_financial_totals_or_duplicate_identity(self):
        from decimal import Decimal
        from scripts.invoice_fetch.batch_review import batch_amount_summary
        from scripts.invoice_fetch.reimbursement import amount_total
        parent = self.invoice()
        source = self.evidence(invoice_number="PROOF-NUMBER", seller_name="Proof Seller", total_amount="800.00")
        rows = self.db.get_all_invoices()
        self.assertEqual(amount_total(rows), (1, Decimal("100.00"), False))
        self.assertEqual(batch_amount_summary(rows), "¥100.00")
        self.assertIsNone(self.db.find_invoice_by_number("PROOF-NUMBER"))
        self.assertIsNone(self.db.find_invoice_by_seller_and_amount("Proof Seller", "800.00"))

    def test_source_path_replacement_updates_all_parents_and_retains_material_identity(self):
        parents = [self.invoice() for _ in range(2)]
        source = self.evidence()
        self.relate(parents, source)
        path = self.file("repaired.pdf")
        self.db.update_invoice_file_paths(source, attachment_path=path)
        for parent in parents:
            self.assertEqual(material_paths(self.db.get_invoice(parent)["extra_paths"]), [path])
            self.assertEqual(self.db.list_invoice_evidence(parent)[0]["id"], source)

    def test_bad_target_or_material_rolls_back_entire_multi_target_change(self):
        parent = self.invoice()
        source = self.evidence()
        for targets, sources in (((parent, 99999), (source,)), ((parent,), (source, 99999)), ((source,), (source,))):
            with self.subTest(targets=targets, sources=sources):
                with self.assertRaises(ValueError):
                    self.db.link_evidence_to_invoices(targets, sources)
                self.assertEqual(self.db.evidence_consumers(source), ())
        self.assertEqual(self.db.get_invoice(parent)["extra_paths"], "[]")

    def test_mixed_add_remove_changes_roll_back_on_missing_material(self):
        parent = self.invoice()
        source = self.evidence()
        self.relate((parent,), source)
        with self.assertRaises(ValueError):
            self.db.apply_evidence_changes((parent,), ((parent, 99999),), ((parent, source),))
        self.assertEqual(self.db.evidence_consumers(source), (parent,))
        with self.assertRaises(ValueError):
            self.db.apply_evidence_changes((parent,), ((99999, source),), ())

    def test_relation_and_projection_write_failure_roll_back_together(self):
        parent = self.invoice()
        source = self.evidence()
        with patch("scripts.invoice_fetch.evidence.refresh_material_projection", side_effect=sqlite3.OperationalError("synthetic failure")):
            self.assertFalse(self.db.link_evidence_to_invoice(parent, source))
        self.assertEqual(self.db.evidence_consumers(source), ())
        self.assertEqual(self.db.get_invoice(parent)["extra_paths"], "[]")
        self.assertFalse(self.db._conn.in_transaction)

    def test_release_failure_rolls_back_link_and_leaves_connection_usable(self):
        parent = self.invoice()
        source = self.evidence()
        connection = self.db._conn
        class FailRelease:
            fail = True
            def execute(self, sql, parameters=()):
                if self.fail and sql.startswith("RELEASE invoice_hub_"):
                    self.fail = False
                    raise sqlite3.OperationalError("synthetic commit failure")
                return connection.execute(sql, parameters)
            def __getattr__(self, name):
                return getattr(connection, name)
        self.db._conn = FailRelease()
        try:
            self.assertFalse(self.db.link_evidence_to_invoice(parent, source))
        finally:
            self.db._conn = connection
        self.assertEqual(self.db.evidence_consumers(source), ())
        self.assertTrue(self.db.link_evidence_to_invoice(parent, source))

    def test_link_preserves_caller_owned_transaction(self):
        parent = self.invoice()
        source = self.evidence()
        self.db._conn.execute("UPDATE invoices SET confirmed_note='Pending outer transaction' WHERE id=?", (parent,))
        self.relate((parent,), source)
        self.assertTrue(self.db._conn.in_transaction)
        self.db._conn.rollback()
        self.assertEqual(self.db.evidence_consumers(source), ())
        self.assertEqual(self.db.get_invoice(parent)["confirmed_note"], "Keep this note")

    def test_email_reprocess_preserves_material_with_cross_source_or_deleted_consumers(self):
        parent = self.invoice(mailbox_key="other", mail_uid=9)
        source = self.evidence(mailbox_key="email", mail_uid=123)
        self.relate((parent,), source)
        self.db.soft_delete_invoice(parent)
        result = self.db.delete_invoices_for_reprocess("email", 123, include_approved=True, include_claimed=True)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "evidence_in_use")
        self.assertIsNotNone(self.db.get_invoice(source))

    def test_existing_material_reimport_does_not_move_or_delete_its_file(self):
        from scripts.invoice_fetch import services
        parents = [self.invoice() for _ in range(2)]
        source = self.evidence()
        self.relate((parents[0],), source)
        path = self.runtime / self.db.get_invoice(source)["attachment_path"]
        with patch.object(services, "RUNTIME_DIR", self.runtime), patch.object(services, "_rename_by_invoice_code") as rename:
            self.assertTrue(services._attach_evidence_to_invoice(self.db, self.db.get_invoice(parents[1]), path))
            self.assertFalse(services._attach_evidence_to_invoice(self.db, self.db.get_invoice(parents[1]), path))
            rename.assert_not_called()
        self.assertTrue(path.exists())
        self.assertEqual(self.db.evidence_consumers(source), tuple(parents))

    def test_duplicate_import_cleanup_never_deletes_registered_material_used_elsewhere(self):
        from scripts.invoice_fetch import services
        parents = [self.invoice() for _ in range(2)]
        sources = [self.evidence() for _ in range(2)]
        for parent, source in zip(parents, sources):
            self.relate((parent,), source)
        referenced = self.runtime / self.db.get_invoice(sources[0])["attachment_path"]
        other = self.runtime / self.db.get_invoice(sources[1])["attachment_path"]
        other.write_bytes(referenced.read_bytes())
        incoming = self.root / "incoming.pdf"
        incoming.write_bytes(referenced.read_bytes())
        with patch.object(services, "RUNTIME_DIR", self.runtime), patch.object(services, "_semantic_evidence_fingerprint", return_value=""), patch.object(services, "_rename_by_invoice_code", return_value=referenced.relative_to(self.runtime).as_posix()):
            self.assertFalse(services._attach_evidence_to_invoice(self.db, self.db.get_invoice(parents[1]), incoming))
        self.assertTrue(referenced.exists())
        self.assertEqual(self.db.evidence_consumers(sources[0]), (parents[0],))

    def reparse(self, parent, **fields):
        return reconcile_reparsed_invoice(self.db, parent, invoice_number="REPARSED", invoice_code="", invoice_date="2026-10-02",
            amount="100.00", total_amount="100.00", seller_name="Synthetic Seller", buyer_name="Synthetic Buyer",
            invoice_type="电子发票", category="其他", has_extra=False, extra_type="", missing_extra=False,
            parse_success=True, parse_note="重新解析", **fields)

    def test_linked_material_cannot_be_reparsed_into_financial_invoice(self):
        parent = self.invoice()
        source = self.evidence()
        self.relate((parent,), source)
        backfill = self.db.update_invoice_missing_fields(source, {"invoice_type": "电子发票"}, only_if_empty=False)
        self.assertEqual(backfill["updated_fields"], [])
        self.assertEqual(backfill["skipped_fields"], ["invoice_type"])
        result = self.reparse(source)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "evidence_in_use")
        self.assertEqual(self.db.get_invoice(source)["record_role"], "evidence")

    def test_reparse_duplicate_reconciliation_transfers_all_material_links(self):
        master = self.invoice(invoice_number="REPARSED")
        parent = self.invoice()
        sources = [self.evidence() for _ in range(2)]
        self.relate((master,), sources[0])
        self.relate((parent,), sources[1])
        result = self.reparse(parent)
        self.assertTrue(result.success)
        self.assertIsNone(self.db.get_invoice(master, include_deleted=True))
        self.assertEqual({row["id"] for row in self.db.list_invoice_evidence(parent)}, set(sources))
        self.assertEqual(self.db.get_invoice(parent)["has_extra"], 1)

    def test_financial_invoice_with_materials_cannot_be_changed_into_material(self):
        parent = self.invoice()
        source = self.evidence()
        self.relate((parent,), source)
        fields = dict(invoice_number="REPARSED", invoice_code="", invoice_date="2026-10-02", amount="100.00",
            total_amount="100.00", seller_name="Synthetic Seller", buyer_name="Synthetic Buyer", category="其他",
            invoice_type="待关联证明材料", has_extra=False, extra_type="", missing_extra=False, parse_success=True,
            parse_note="待关联证明材料")
        self.assertFalse(self.db.update_invoice_parsed_metadata(parent, **fields))
        self.assertFalse(reconcile_reparsed_invoice(self.db, parent, **fields).success)
        result = self.db.update_invoice_missing_fields(parent, {"invoice_type": "待关联证明材料"}, only_if_empty=False)
        self.assertEqual(result["updated_fields"], [])
        self.assertEqual(self.db.get_invoice(parent)["record_role"], "invoice")
        self.assertEqual(self.db.evidence_consumers(source), (parent,))

    def test_database_backup_restores_relations_and_deleted_source_state(self):
        parent = self.invoice()
        source = self.evidence()
        self.relate((parent,), source)
        self.db.soft_delete_invoice(source)
        self.db.close()
        backup = create_verified_database_backup(self.path, backup_dir=self.root / "backups")
        self.db = InvoiceDB(self.path)
        self.db.unlink_evidence_from_invoice(parent, source)
        self.db.close()
        restore_verified_database_backup(backup, self.path, backup_dir=self.root / "backups")
        self.db = InvoiceDB(self.path)
        self.assertEqual(self.db.evidence_consumers(source), (parent,))
        self.assertEqual(self.db.get_invoice(parent)["missing_extra"], 1)
        self.assertEqual(self.db.get_invoice(source, include_deleted=True)["is_deleted"], 1)

    def test_complete_backup_restores_one_shared_file_and_all_relations(self):
        parents = [self.invoice() for _ in range(2)]
        source = self.evidence()
        self.relate(parents, source)
        self.db.close()
        backup = create_complete_backup(self.path, self.runtime, backup_dir=self.root / "backups")
        target = self.root / "restored"
        InvoiceDB(target / "invoices.db").close()
        restore_complete_backup(backup, target / "invoices.db", target)
        with InvoiceDB(target / "invoices.db") as restored:
            self.assertEqual(restored.evidence_consumers(source), tuple(parents))
            restored_path = restored.get_invoice(source)["attachment_path"]
            self.assertTrue((target / restored_path).is_file())
            for parent in parents:
                self.assertEqual(material_paths(restored.get_invoice(parent)["extra_paths"]), [restored_path])
            self.assertEqual(restored.count_invoices(), 2)

    def claim(self, parents):
        claim = self.db.create_claim_group("Shared evidence claim")
        for parent in parents:
            self.assertTrue(self.db.update_invoice_review_status(parent, "approved", "Keep this note"))
            self.assertTrue(self.db.add_invoice_to_claim(claim, parent))
        return claim

    def export(self, claim):
        return export_claim_package(self.db, claim, self.root, self.runtime, export_root=self.root / "exports")

    def test_export_manifest_references_one_copied_material_for_four_invoices(self):
        parents = [self.invoice(invoice_date=f"2026-10-0{n+1}") for n in range(4)]
        source = self.evidence()
        self.relate(parents, source)
        package = self.export(self.claim(parents))
        manifest = json.loads((package / "manifest.json").read_text())
        references = [item["evidence_references"][0] for item in manifest["items"]]
        self.assertEqual(len(references), 4)
        self.assertEqual({ref["evidence_id"] for ref in references}, {source})
        copied_paths = {ref["copied_path"] for ref in references}
        self.assertEqual(len(copied_paths), 1)
        self.assertEqual(len(list((package / "attachments").iterdir())), 5)
        self.assertTrue((package / next(iter(copied_paths))).is_file())

    def test_export_blocks_deleted_material_even_if_its_file_is_readable(self):
        parent = self.invoice()
        source = self.evidence()
        self.relate((parent,), source)
        claim = self.claim((parent,))
        self.db.soft_delete_invoice(source)
        with self.assertRaises(ValueError):
            self.export(claim)
        self.assertFalse((self.root / "exports").exists())

    def test_export_retains_each_identity_when_legacy_and_imported_sources_share_a_path(self):
        parent = self.invoice(extra_paths=[self.file("same-file.pdf")])
        legacy = self.db.list_invoice_evidence(parent)[0]["id"]
        source = self.evidence(attachment_path="attachments/same-file.pdf")
        self.relate((parent,), source)
        package = self.export(self.claim((parent,)))
        item = json.loads((package / "manifest.json").read_text())["items"][0]
        self.assertEqual({row["evidence_id"] for row in item["evidence_references"]}, {legacy, source})
        self.assertEqual(len(item["extra_paths"]), 1)
        self.assertEqual(len(list((package / "attachments").iterdir())), 2)

    def test_backup_rejects_orphaned_material_relation(self):
        parent = self.invoice()
        source = self.evidence()
        self.relate((parent,), source)
        self.db._conn.execute("PRAGMA foreign_keys=OFF")
        self.db._conn.execute("DELETE FROM invoices WHERE id=?", (source,))
        self.db._conn.commit()
        self.db.close()
        with self.assertRaises(DatabaseBackupError):
            create_verified_database_backup(self.path, backup_dir=self.root / "backups")

    def test_export_blocks_missing_shared_file_without_creating_package(self):
        parents = [self.invoice() for _ in range(2)]
        source = self.evidence()
        self.relate(parents, source)
        claim = self.claim(parents)
        (self.runtime / self.db.get_invoice(source)["attachment_path"]).unlink()
        with self.assertRaises(ValueError):
            self.export(claim)
        self.assertFalse((self.root / "exports").exists())

    def test_preview_keeps_explicit_material_identity_after_cross_mail_association(self):
        from scripts.invoice_fetch.gui.helpers import resolve_invoice_documents_with_evidence
        parent = self.invoice(mailbox_key="a", mail_uid=1)
        source = self.evidence(mailbox_key="b", mail_uid=2)
        self.relate((parent,), source)
        documents = resolve_invoice_documents_with_evidence(self.db.get_invoice(parent), self.db, self.runtime)
        self.assertEqual(documents[1]["type"], "supporting")
        self.assertEqual(documents[1]["evidence_id"], source)
        self.assertEqual(len(documents), 2)


class EvidenceMigrationTests(unittest.TestCase):
    def legacy(self, factory=sqlite3.Connection):
        conn = sqlite3.connect(":memory:", factory=factory)
        conn.executescript(_SCHEMA)
        with patch("scripts.invoice_fetch.evidence.migrate_shared_evidence"):
            check_and_migrate(conn)
        conn.execute("PRAGMA user_version=13")
        return conn

    def test_migration_converts_paths_shares_identity_and_restores_only_consumed_source(self):
        conn = self.legacy()
        self.addCleanup(conn.close)
        conn.executemany(
            "INSERT INTO invoices (id,invoice_type,attachment_path,extra_paths,is_deleted,parse_note,missing_extra,extra_type) VALUES (?,?,?,?,?,?,?,?)",
            [(1,"电子发票","a.pdf",'["shared.pdf","shared.pdf"]',0,"",0,"水单"),
             (2,"电子发票","b.pdf",'["shared.pdf"]',0,"",0,""),
             (3,"待关联证明材料","shared.pdf","[]",1,"待关联证明材料; 已关联到发票 ID 1",0,""),
             (4,"待关联证明材料","deleted.pdf","[]",1,"用户主动删除",0,""),
             (5,"电子发票","c.pdf",'["deleted.pdf"]',0,"",0,"")],
        )
        conn.commit()
        check_and_migrate(conn)
        validate_latest_schema(conn)
        self.assertEqual(conn.execute("SELECT is_deleted FROM invoices WHERE id=3").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT is_deleted FROM invoices WHERE id=4").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT invoice_id,evidence_id FROM invoice_evidence_relations ORDER BY invoice_id").fetchall(), [(1,3),(2,3),(5,4)])
        self.assertEqual(conn.execute("SELECT missing_extra FROM invoices WHERE id=5").fetchone()[0], 1)
        before = conn.execute("SELECT * FROM invoice_evidence_relations").fetchall()
        check_and_migrate(conn)
        self.assertEqual(conn.execute("SELECT * FROM invoice_evidence_relations").fetchall(), before)

    def test_migration_accepts_plain_and_json_scalar_paths_without_creating_financial_values(self):
        conn = self.legacy()
        self.addCleanup(conn.close)
        conn.executemany("INSERT INTO invoices (extra_paths) VALUES (?)", [("plain.pdf",), ('"scalar.pdf"',)])
        conn.commit()
        check_and_migrate(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoice_evidence_relations").fetchone()[0], 2)
        for row in conn.execute("SELECT invoice_number,total_amount,record_role FROM invoices WHERE record_role='evidence'"):
            self.assertEqual(row, (None, None, "evidence"))

    def test_failed_migration_rolls_back_ddl_relations_records_and_version(self):
        class FailingConnection(sqlite3.Connection):
            fail = False
            def execute(self, sql, parameters=()):
                if self.fail and sql.startswith("INSERT INTO invoices (record_role"):
                    raise sqlite3.OperationalError("synthetic material registration failure")
                return super().execute(sql, parameters)
        conn = self.legacy(FailingConnection)
        self.addCleanup(conn.close)
        conn.execute("INSERT INTO invoices(extra_paths) VALUES ('[\"material.pdf\"]')")
        conn.commit()
        conn.fail = True
        with self.assertRaises(sqlite3.OperationalError):
            check_and_migrate(conn)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 13)
        self.assertNotIn("record_role", {row[1] for row in conn.execute("PRAGMA table_info(invoices)")})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0], 1)
        self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='invoice_evidence_relations'").fetchone())
        conn.fail = False
        check_and_migrate(conn)
        validate_latest_schema(conn)
