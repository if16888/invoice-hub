"""Partition the legacy claim-group regression suite without duplicating discovery.

The original large TestCase is kept in ``tests._claim_groups_cases`` so the
public ``tests.test_claim_groups`` module remains a compatibility entry point.
The isolated CI runner expands that entry point into three non-discovered
modules to shorten the critical path while keeping every test method owned by
exactly one partition.
"""

from __future__ import annotations

import tempfile
from functools import wraps
from pathlib import Path
from unittest.mock import Mock, patch

from tests import _claim_groups_cases as _cases


_GUI_EXACT = {
    "test_claim_quality_report_gui_prompt",
    "test_settings_dialog_uses_neutral_steps_selection_cards_and_one_primary_action",
    "test_startup_splash_initialization_is_gui_safe",
}

_MAIL_MARKERS = (
    "scan_email",
    "scan_summary",
    "mailbox",
    "download",
    "redownload",
    "pending_email",
    "ofd_",
    "rule_classifier",
    "run_classify",
    "ai_auth",
    "rename_reuses_existing_same_hash_attachment",
)

# These legacy regressions test status filtering / manifest metadata rather than
# missing-original behavior.  Their old synthetic rows predate the complete
# export contract and did not create attachment files.  Keep their original
# assertions, but materialize neutral synthetic originals before the real
# exporter runs so they continue testing only their intended concern.
_EXPORT_TESTS_REQUIRING_NEUTRAL_ORIGINALS = {
    "test_claim_export_default_includes_only_approved",
    "test_claim_export_include_to_review_includes_both",
    "test_claim_export_always_excludes_ignored_and_error",
    "test_claim_export_excludes_pending_evidence_even_if_legacy_link_exists",
    "test_claim_export_manifest_contains_correct_metadata_and_skipped_counts",
}


def active_test_names() -> list[str]:
    return sorted(
        name
        for name in dir(_cases.ClaimGroupsTests)
        if name.startswith("test_") and callable(getattr(_cases.ClaimGroupsTests, name))
    )


def category_for_test(name: str) -> str:
    if name.startswith("test_gui_") or name in _GUI_EXACT:
        return "gui"
    if any(marker in name for marker in _MAIL_MARKERS):
        return "mail"
    return "core"


def partition_test_names(category: str) -> list[str]:
    if category not in {"core", "gui", "mail"}:
        raise ValueError(f"unknown claim-group test category: {category}")
    return [name for name in active_test_names() if category_for_test(name) == category]


def _claim_quality_report_gui_prompt(self):
    """Verify QA summary and privacy-safe export-path text without PDF side effects."""
    try:
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv)

        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "project"
            runtime_dir = project_root / "runtime"
            external_export_root = Path(td) / "user-exports"
            db_path = runtime_dir / "invoices.db"

            with _cases.InvoiceDB(db_path) as db:
                claim_id = db.create_claim_group("GUI QA Group")
                invoice_id = db.insert_invoice(
                    {
                        "invoice_number": "GUI001",
                        "total_amount": "100.00",
                        "expense_date": "2026-06-01",
                        "seller_name": "",
                        "category": "交通",
                        "review_status": _cases.review_status.APPROVED,
                        "attachment_path": "attachments/dummy.pdf",
                    }
                )
                db.add_invoice_to_claim(claim_id, invoice_id)

                attachments_dir = runtime_dir / "attachments"
                attachments_dir.mkdir(parents=True, exist_ok=True)
                (attachments_dir / "dummy.pdf").write_bytes(b"%PDF-1.4 dummy")

                from scripts.invoice_fetch.gui.app import InvoiceReviewApp

                with patch("scripts.invoice_fetch.gui.app.RUNTIME_DIR", runtime_dir), patch(
                    "scripts.invoice_fetch.gui.app.PROJECT_ROOT", project_root
                ), patch(
                    "scripts.invoice_fetch.gui.app.resolve_export_directory",
                    return_value=external_export_root,
                ):
                    window = InvoiceReviewApp(db_path, splash=None)
                    try:
                        # Embedded PDF rendering is not part of this export-dialog
                        # contract and can retain synthetic files on Windows.
                        window._update_document_preview = Mock()
                        window._deferred_init()

                        with patch("scripts.invoice_fetch.gui.app.QMessageBox") as box_class:
                            box = box_class.return_value
                            box.clickedButton.return_value = Mock()

                            idx = window.combo_claims.findData(claim_id)
                            if idx >= 0:
                                window.combo_claims.setCurrentIndex(idx)

                            with patch.object(box_class, "Question", box_class.Question):
                                window._export_claim_package()

                            texts = [
                                call.args[0]
                                for call in box.setText.call_args_list
                                if call.args
                            ]
                            combined = "\n".join(texts)
                            self.assertIn("发现 1 个需确认项", combined)
                            self.assertIn("输出路径:", combined)
                            self.assertNotIn(str(td), combined)
                            self.assertNotIn(str(external_export_root), combined)

                        db.update_invoice_fields(
                            invoice_id=invoice_id,
                            invoice_number="GUI001",
                            expense_date="2026-06-01",
                            seller_name="Valid Seller",
                            total_amount="100.00",
                            category="交通",
                        )

                        with patch("scripts.invoice_fetch.gui.app.QMessageBox") as box_class:
                            box = box_class.return_value
                            box.clickedButton.return_value = Mock()

                            with patch.object(box_class, "Question", box_class.Question):
                                window._export_claim_package()

                            texts = [
                                call.args[0]
                                for call in box.setText.call_args_list
                                if call.args
                            ]
                            combined = "\n".join(texts)
                            self.assertIn("质量检查未发现需确认项", combined)
                            self.assertIn("输出路径:", combined)
                            self.assertNotIn(str(td), combined)
                    finally:
                        if hasattr(window, "pdf_document") and window.pdf_document is not None:
                            window.pdf_document.close()
                        if hasattr(window, "db") and window.db is not None:
                            window.db.close()
                        window.close()
                        window.deleteLater()
                        app.processEvents()
    except Exception as exc:
        if isinstance(exc, (ImportError, RuntimeError)):
            self.skipTest(f"Skipping GUI test: {exc}")
        raise


def _gui_export_dialog_copy_and_preflight_stats(self):
    """Keep the legacy status-count check while using a real approved original."""
    try:
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "test_gui_export_copy.db"
            approved_original = root / "approved-original.xml"
            approved_original.write_text("<invoice>synthetic</invoice>", encoding="utf-8")

            with _cases.InvoiceDB(db_path) as db:
                claim_id = db.create_claim_group("Export Copy")
                rows = [
                    {
                        "invoice_number": "APP",
                        "total_amount": "10.00",
                        "attachment_path": str(approved_original),
                        "review_status": "approved",
                    },
                    {
                        "invoice_number": "REV",
                        "total_amount": "",
                        "attachment_path": "",
                        "review_status": "to_review",
                    },
                    {
                        "invoice_number": "IGN",
                        "total_amount": "12.00",
                        "attachment_path": "i.pdf",
                        "review_status": "ignored",
                    },
                    {
                        "invoice_number": "ERR",
                        "total_amount": "13.00",
                        "attachment_path": "e.pdf",
                        "review_status": "error",
                    },
                ]
                for row in rows:
                    invoice_id = db.insert_invoice(
                        {
                            "seller_name": "Synthetic Seller",
                            "invoice_date": "2026-06-04",
                            "category": "synthetic",
                            **row,
                        }
                    )
                    db.add_invoice_to_claim(claim_id, invoice_id)

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp

            window = InvoiceReviewApp(db_path, splash=None)
            try:
                window._update_document_preview = Mock()
                stats = window._claim_export_preflight_stats(claim_id)
                self.assertEqual(stats["approved"], 1)
                self.assertEqual(stats["to_review"], 1)
                self.assertEqual(stats["ignored"], 1)
                self.assertEqual(stats["error"], 1)
                self.assertEqual(stats["missing_attachment"], 1)
                self.assertEqual(stats["missing_amount"], 1)
                text = window._format_claim_export_preflight_text(stats)
                self.assertIn("导出检查", text)
                self.assertIn("已通过发票：1 张", text)
                self.assertIn("待处理：1 张", text)
                self.assertIn("已忽略和异常发票不会进入报销包", text)
                self.assertNotIn("approved:", text)
                self.assertNotIn("to_review:", text)
                self.assertNotIn("所有已关联文件", text)
            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                app.processEvents()
    except Exception as exc:
        if isinstance(exc, (ImportError, RuntimeError)):
            self.skipTest(f"Skipping GUI test: {exc}")
        raise


def _missing_attachment_blocks_complete_export(self):
    """Legacy permissive export contract is replaced by fail-closed behavior."""
    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td) / "project"
        runtime_dir = project_root / "runtime"
        db_path = runtime_dir / "invoices.db"

        with _cases.InvoiceDB(db_path) as db:
            claim_id = db.create_claim_group("Missing Attachments")
            invoice_id = db.insert_invoice(
                {
                    "invoice_number": "MISS001",
                    "total_amount": "100.00",
                    "seller_name": "No File Corp",
                    "attachment_path": "attachments/does_not_exist.pdf",
                    "review_status": _cases.review_status.APPROVED,
                }
            )
            db.add_invoice_to_claim(claim_id, invoice_id)

            with self.assertRaisesRegex(ValueError, "发票原件复制失败或已不可用"):
                _cases.export_claim_package(db, claim_id, project_root, runtime_dir)

            self.assertEqual(db.list_export_runs(claim_id), [])
            export_root = project_root / "exports"
            if export_root.exists():
                self.assertEqual(list(export_root.iterdir()), [])


def _materialize_required_originals(db, claim_id: int, runtime_dir: Path, include_to_review: bool) -> None:
    included_statuses = {_cases.review_status.APPROVED}
    if include_to_review:
        included_statuses.add(_cases.review_status.TO_REVIEW)

    attachments_dir = Path(runtime_dir) / "attachments" / "legacy-contract-fixtures"
    changed = False
    for invoice in db.get_claim_invoices(claim_id):
        if invoice.get("review_status") not in included_statuses:
            continue
        if _cases.is_pending_evidence_invoice(invoice):
            continue

        raw_path = str(invoice.get("attachment_path") or "").strip()
        source = Path(raw_path) if raw_path else None
        if source is not None and not source.is_absolute():
            source = Path(runtime_dir) / source
        if source is not None and source.is_file():
            continue

        attachments_dir.mkdir(parents=True, exist_ok=True)
        fixture = attachments_dir / f"invoice-{invoice['id']}.xml"
        fixture.write_text("<invoice>synthetic export fixture</invoice>", encoding="utf-8")
        relative = fixture.relative_to(runtime_dir).as_posix()
        db._conn.execute(
            "UPDATE invoices SET attachment_path = ? WHERE id = ?",
            (relative, invoice["id"]),
        )
        changed = True

    if changed:
        db._conn.commit()


def _with_neutral_originals(method):
    """Adapt pre-contract export fixtures without weakening production checks."""
    real_export = _cases.export_claim_package

    @wraps(method)
    def wrapped(self):
        def export_with_fixture(db, claim_id, project_root, runtime_dir, *args, **kwargs):
            include_to_review = bool(kwargs.get("include_to_review", False))
            _materialize_required_originals(
                db,
                claim_id,
                Path(runtime_dir),
                include_to_review,
            )
            return real_export(
                db,
                claim_id,
                project_root,
                runtime_dir,
                *args,
                **kwargs,
            )

        with patch.object(_cases, "export_claim_package", new=export_with_fixture):
            return method(self)

    return wrapped


_TEST_OVERRIDES = {
    "test_claim_quality_report_gui_prompt": _claim_quality_report_gui_prompt,
    "test_gui_export_dialog_copy_and_preflight_stats": _gui_export_dialog_copy_and_preflight_stats,
    "test_missing_attachment_is_recorded_but_no_crash": _missing_attachment_blocks_complete_export,
}
for _name in _EXPORT_TESTS_REQUIRING_NEUTRAL_ORIGINALS:
    _TEST_OVERRIDES[_name] = _with_neutral_originals(
        getattr(_cases.ClaimGroupsTests, _name)
    )


def make_full_case(module_name: str):
    """Return the compatibility TestCase containing the complete active suite."""
    attrs = {"__module__": module_name}
    attrs.update(_TEST_OVERRIDES)
    return type(
        "ClaimGroupsTests",
        (_cases.ClaimGroupsTests,),
        attrs,
    )


def make_partition(module_name: str, category: str):
    """Return one disjoint TestCase partition for isolated CI execution."""
    owned = set(partition_test_names(category))
    attrs = {"__module__": module_name}
    for name in active_test_names():
        if name not in owned:
            attrs[name] = None
        elif name in _TEST_OVERRIDES:
            attrs[name] = _TEST_OVERRIDES[name]
    return type(
        f"ClaimGroups{category.title()}Tests",
        (_cases.ClaimGroupsTests,),
        attrs,
    )
