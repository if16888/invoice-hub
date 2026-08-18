"""Partition the legacy claim-group regression suite without duplicating discovery.

The original large TestCase is kept in ``tests._claim_groups_cases`` so the
public ``tests.test_claim_groups`` module remains a compatibility entry point.
The isolated CI runner expands that entry point into three non-discovered
modules to shorten the critical path while keeping every test method owned by
exactly one partition.
"""

from __future__ import annotations

import tempfile
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
                    "scripts.invoice_fetch.export_paths.resolve_export_directory",
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


def make_full_case(module_name: str):
    """Return the compatibility TestCase containing the complete active suite."""
    return type(
        "ClaimGroupsTests",
        (_cases.ClaimGroupsTests,),
        {
            "__module__": module_name,
            "test_claim_quality_report_gui_prompt": _claim_quality_report_gui_prompt,
        },
    )


def make_partition(module_name: str, category: str):
    """Return one disjoint TestCase partition for isolated CI execution."""
    owned = set(partition_test_names(category))
    attrs = {"__module__": module_name}
    for name in active_test_names():
        if name not in owned:
            attrs[name] = None
    if category == "gui":
        attrs["test_claim_quality_report_gui_prompt"] = _claim_quality_report_gui_prompt
    return type(
        f"ClaimGroups{category.title()}Tests",
        (_cases.ClaimGroupsTests,),
        attrs,
    )
