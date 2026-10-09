import json
import sqlite3
from pathlib import Path

from scripts.invoice_fetch import review_status
from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.migrations import LATEST_SCHEMA_VERSION, validate_latest_schema


def _add_invoice(db: InvoiceDB, invoice_number: str, status: str, path: str = "invoice.pdf") -> int:
    return int(db.insert_invoice({
        "invoice_number": invoice_number,
        "total_amount": "42.50",
        "seller_name": "Example Seller",
        "review_status": status,
        "attachment_path": path,
    }))


def test_export_freezes_claim_and_reimbursement_marks_exact_exported_items(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "invoice.pdf").write_bytes(b"approved invoice")
    db_path = runtime / "invoices.db"

    with InvoiceDB(db_path) as db:
        claim_id = db.create_claim_group("September travel")
        included_id = _add_invoice(db, "APPROVED-1", review_status.APPROVED)
        skipped_id = _add_invoice(db, "IGNORED-1", review_status.IGNORED, "missing.pdf")
        assert db.add_invoice_to_claim(claim_id, included_id)
        assert db.add_invoice_to_claim(claim_id, skipped_id)

        package = export_claim_package(
            db,
            claim_id,
            tmp_path,
            runtime,
            export_root=tmp_path / "exports",
            reimbursement_config={},
        )
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        assert [item["invoice_id"] for item in manifest["items"]] == [included_id]

        claim = db.get_claim_group(claim_id)
        assert claim["status"] == "exported"
        assert claim["exported_at"]
        runs = db.get_export_runs(claim_id)
        assert len(runs) == 1
        assert db.get_export_run_items(runs[0]["id"]) == [included_id]
        assert [event["to_status"] for event in db.get_claim_status_events(claim_id)] == ["exported"]

        assert not db.add_invoice_to_claim(claim_id, _add_invoice(db, "LATE-ADD", review_status.APPROVED))
        assert db.last_error == "claim_exported_locked"
        assert not db.remove_invoice_from_claim(claim_id, skipped_id)
        assert not db.update_claim_reason(claim_id, reason_detail="changed")
        assert not db.update_invoice_reason(included_id, "changed")
        assert not db.update_invoice_review_status(included_id, review_status.IGNORED)
        assert not db.soft_delete_invoice(included_id)

        other_claim = db.create_claim_group("Other claim")
        assert not db.add_invoice_to_claim(other_claim, included_id)
        assert db.last_error == "invoice_exported_locked"

        assert db.mark_claim_reimbursed(claim_id, runs[0]["id"])
        claim = db.get_claim_group(claim_id)
        invoice = db.get_invoice(included_id)
        assert claim["status"] == "reimbursed"
        assert claim["reimbursed_at"]
        assert invoice["reimbursed_at"] == claim["reimbursed_at"]
        assert invoice["reimbursed_group_id"] == claim_id
        assert db.get_invoice(skipped_id)["reimbursed_at"] is None
        assert [event["to_status"] for event in db.get_claim_status_events(claim_id)] == [
            "exported", "reimbursed",
        ]
        assert not db.mark_claim_reimbursed(claim_id, runs[0]["id"])
        assert not db.update_invoice_financial_fields(
            included_id,
            amount="40",
            buyer_tax_id=None,
            tax_amount=None,
            tax_rate=None,
            invoice_code="",
        )
        try:
            export_claim_package(
                db,
                claim_id,
                tmp_path,
                runtime,
                export_root=tmp_path / "exports",
                reimbursement_config={},
            )
        except ValueError as exc:
            assert "已标记报销" in str(exc)
        else:
            raise AssertionError("a reimbursed claim must not be exported again")


def test_failed_export_does_not_transition_claim_state(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with InvoiceDB(runtime / "invoices.db") as db:
        claim_id = db.create_claim_group("Missing original")
        invoice_id = _add_invoice(db, "MISSING-ORIGINAL", review_status.APPROVED, "missing.pdf")
        assert db.add_invoice_to_claim(claim_id, invoice_id)
        try:
            export_claim_package(
                db,
                claim_id,
                tmp_path,
                runtime,
                export_root=tmp_path / "exports",
                reimbursement_config={},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("missing source original should block export")
        claim = db.get_claim_group(claim_id)
        assert claim["status"] == "draft"
        assert claim["exported_at"] is None
        assert db.get_export_runs(claim_id) == []
        assert db.get_claim_status_events(claim_id) == []


def test_v15_migration_marks_historically_exported_groups_as_locked(tmp_path: Path):
    db_path = tmp_path / "migration.db"
    with InvoiceDB(db_path) as db:
        claim_id = db.create_claim_group("Already exported")
        db._conn.execute(
            "INSERT INTO export_runs (claim_id, export_dir, export_type, item_count) "
            "VALUES (?, 'exports/old', 'generic_excel', 1)",
            (claim_id,),
        )
        db._conn.commit()
        db._conn.execute("DELETE FROM claim_status_events")
        db._conn.execute("DROP INDEX idx_invoices_reimbursement_group")
        db._conn.execute("DROP INDEX idx_export_run_items_invoice")
        db._conn.execute("DROP INDEX idx_claim_status_events_claim")
        db._conn.execute("DROP TABLE export_run_items")
        db._conn.execute("DROP TABLE claim_status_events")
        db._conn.execute("ALTER TABLE invoices DROP COLUMN reimbursed_group_id")
        db._conn.execute("ALTER TABLE invoices DROP COLUMN reimbursed_at")
        db._conn.execute("ALTER TABLE claim_groups DROP COLUMN reimbursed_at")
        db._conn.execute("ALTER TABLE claim_groups DROP COLUMN exported_at")
        db._conn.execute("PRAGMA user_version = 14")
        db._conn.commit()

    with InvoiceDB(db_path) as migrated:
        assert migrated._conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        assert migrated.get_claim_group(claim_id)["status"] == "exported"
        assert migrated.get_claim_group(claim_id)["exported_at"]
        assert migrated.get_claim_status_events(claim_id)[0]["to_status"] == "exported"
        validate_latest_schema(migrated._conn)
