"""Tests for export preflight and package creation consistency.

Verifies:
1. Strict tax ID check consistency between UI preflight and package export.
2. Tax balance validation consistency between UI preflight and package export.
3. Buyer name mismatch warning allows export with warning.
4. Per-invoice issues displayed according to selected export scope.
5. Double-click navigation from export invoice list to review page.
"""

from contextlib import contextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

from scripts.invoice_fetch import config as config_module, diagnostics
from scripts.invoice_fetch.claim_export import (
    claim_export_preflight,
    export_claim_package,
    invoice_export_issues,
    verify_export_manifest,
)
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui import app as app_module
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.company_tax_profile import CompanyTaxProfileDialog
from scripts.invoice_fetch.gui import workbench_settings as settings_module
from scripts.invoice_fetch.gui.selection_surfaces import INVOICE_ROW_ROLE
from scripts.invoice_fetch.gui.workers import ClaimExportWorker
from scripts.invoice_fetch.log_privacy import attach_privacy_filter
from tests import original_modal_entry_points
from unittest.mock import patch

# Two checksum-valid USCCs with different taxpayer IDs
VALID_USCC_1 = "91350211M000100X45"
VALID_USCC_2 = "91350211M000100Y46"


class ExportPreflightConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._keyring_patch = patch("keyring.get_password", return_value=None)
        cls._keyring_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._keyring_patch.stop()

    def settle(self):
        for _ in range(4):
            self.app.processEvents()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    @contextmanager
    def window(self, records, prepare=None, *, saved_config=None):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(settings_module, "RUNTIME_DIR", Path(td)), \
             patch.object(app_module, "RUNTIME_DIR", Path(td)), \
             patch.object(config_module, "RUNTIME_DIR", Path(td)), \
             patch.object(config_module, "PROJECT_ROOT", Path(td)), \
             patch("scripts.invoice_fetch.credentials.has_auth_code", return_value=False), \
             patch("scripts.invoice_fetch.credentials.get_ai_api_key", return_value=None):
            settings = settings_module.workbench_settings()
            settings.setValue("migration/legacy_qsettings_v1", True)
            settings.sync()
            root = Path(td)
            if saved_config is not None:
                config_module.save_config(saved_config)
            original = root / "original.pdf"
            original.write_bytes(b"%PDF-1.4 synthetic invoice")
            path = root / "review.db"
            with InvoiceDB(path) as db:
                ids = [
                    db.insert_invoice({
                        "invoice_number": f"PREFLIGHT-{index}",
                        "seller_name": "Synthetic Seller",
                        "invoice_date": datetime.now().strftime("%Y-%m-%d"),
                        "total_amount": "20.00",
                        "attachment_path": str(original),
                        "review_status": "approved",
                        **row,
                    })
                    for index, row in enumerate(records)
                ]
                if prepare:
                    prepare(db, ids, root)
            win = InvoiceReviewApp(path, splash=None)
            win._deferred_init()
            if saved_config is None:
                win.config = {"reimbursement": {}}
            win._export_dir = root / "exports"
            win.resize(1440, 900)
            win.show()
            self.settle()
            try:
                yield win, ids, root
            finally:
                win._shutdown_background_workers(wait_ms=1000)
                win.close()
                win.deleteLater()
                self.settle()

    def run_modal(self, dialog_class, trigger, interact):
        """Drive the real modal from its visible action; keep other dialogs guarded."""
        entry = "QMessageBox.exec" if dialog_class is QMessageBox else "QDialog.exec"
        real_exec = original_modal_entry_points().get(entry, dialog_class.exec)
        entered, errors = [], []

        def execute(dialog):
            def drive():
                entered.append(dialog)
                try:
                    self.assertIs(self.app.activeModalWidget(), dialog)
                    interact(dialog)
                    self.assertFalse(dialog.isVisible())
                except BaseException as error:
                    errors.append(error)
                    dialog.reject()

            timer = QTimer(dialog)
            timer.setSingleShot(True)
            timer.timeout.connect(drive)
            timer.start(0)
            try:
                return real_exec(dialog)
            finally:
                timer.stop()

        with patch.object(dialog_class, "exec", execute):
            trigger()
        if errors:
            raise errors[0]
        self.assertEqual(len(entered), 1)

    def select_claim(self, win, claim_id):
        for index in range(win.export_group_list.count()):
            if win.export_group_list.item(index).data(Qt.UserRole) == claim_id:
                win.export_group_list.setCurrentRow(index)
                win._sync_export_claim_selection()
                self.settle()
                return
        self.fail("Missing claim row")

    def find_item_by_invoice_id(self, win, invoice_id):
        for i in range(win.export_invoice_list.count()):
            item = win.export_invoice_list.item(i)
            if item.data(Qt.UserRole) == invoice_id:
                return item
        return None

    def test_strict_tax_id_mismatch_preflight_and_export_consistency(self):
        claims = []

        def prepare(db, ids, root):
            claims.append(db.create_claim_group("Strict Tax Claim"))
            db.add_invoice_to_claim(claims[0], ids[0])

        rows = [{
            "buyer_name": "Test Company",
            "buyer_tax_id": VALID_USCC_1,
            "buyer_tax_id_type": "uscc",
            "review_status": "approved",
        }]

        with self.window(rows, prepare) as (win, ids, root):
            # Configure strict buyer tax check with a different expected tax ID
            win.config = {
                "reimbursement": {
                    "strict_buyer_tax_check": True,
                    "buyer_tax_id": VALID_USCC_2,
                    "buyer_name": "Test Company",
                }
            }
            win._switch_main_page("export")
            self.select_claim(win, claims[0])

            # 1. UI Preflight blocks and shows consistent reason
            self.assertFalse(win.btn_run_export_page.isEnabled())
            self.assertIn("购买方税号与默认主体不符", win.lbl_export_action_hint.text())

            # 2. Per-invoice row displays specific blocker
            item = self.find_item_by_invoice_id(win, ids[0])
            self.assertIsNotNone(item)
            self.assertIn("税号与默认主体不符", item.text())
            payload = item.data(INVOICE_ROW_ROLE)
            self.assertTrue(payload["attention"])
            self.assertIn("税号与默认主体不符", payload["subtitle"])
            self.assertIn("需处理：", payload["subtitle"])

            # 3. Direct export fails with the exact same reason
            exports_dir = root / "exports"
            with self.assertRaisesRegex(ValueError, "购买方税号与默认主体不符"):
                export_claim_package(
                    win.db,
                    claims[0],
                    root,
                    root,
                    export_root=exports_dir,
                    reimbursement_config=win.config["reimbursement"],
                )
            self.assertFalse(exports_dir.exists())

            # 4. Double click navigation: activate the item opens review page
            win._open_export_invoice(item)
            self.settle()
            self.assertEqual(win._current_page_key(), "review")
            self.assertEqual(win.current_invoice["id"], ids[0])

            # 5. When tax ID is corrected to match default entity, preflight passes and export succeeds
            win.db.update_invoice_financial_fields(
                ids[0],
                amount="20.00",
                tax_amount="0.00",
                tax_rate="0%",
                invoice_code="",
                buyer_tax_id=VALID_USCC_2,
                buyer_tax_id_type="uscc",
            )
            win._switch_main_page("export")
            self.select_claim(win, claims[0])
            self.assertTrue(win.btn_run_export_page.isEnabled())
            self.assertIn("已通过发票可导出", win.lbl_export_action_hint.text())
            item_fixed = self.find_item_by_invoice_id(win, ids[0])
            self.assertFalse(item_fixed.data(INVOICE_ROW_ROLE)["attention"])

            package = export_claim_package(
                win.db,
                claims[0],
                root,
                root,
                export_root=exports_dir,
                reimbursement_config=win.config["reimbursement"],
            )
            self.assertTrue(package.exists())

    def test_tax_balance_mismatch_preflight_and_export_consistency(self):
        claims = []

        def prepare(db, ids, root):
            claims.append(db.create_claim_group("Tax Balance Claim"))
            db.add_invoice_to_claim(claims[0], ids[0])

        # amount 100.00 + tax 13.00 != total 120.00
        rows = [{
            "amount": "100.00",
            "tax_amount": "13.00",
            "total_amount": "120.00",
            "review_status": "approved",
        }]

        with self.window(rows, prepare) as (win, ids, root):
            win._switch_main_page("export")
            self.select_claim(win, claims[0])

            # 1. UI Preflight blocks and shows tax balance mismatch reason
            self.assertFalse(win.btn_run_export_page.isEnabled())
            self.assertIn("税前金额 + 税额与价税合计不一致", win.lbl_export_action_hint.text())

            # 2. Per-invoice row displays tax balance blocker
            item = self.find_item_by_invoice_id(win, ids[0])
            self.assertIn("税前金额 + 税额与价税合计不一致", item.text())
            payload = item.data(INVOICE_ROW_ROLE)
            self.assertTrue(payload["attention"])
            self.assertIn("税前金额 + 税额与价税合计不一致", payload["subtitle"])

            # 3. Direct export fails with the exact same reason
            exports_dir = root / "exports"
            with self.assertRaisesRegex(ValueError, "税前金额 \\+ 税额与价税合计不一致"):
                export_claim_package(
                    win.db,
                    claims[0],
                    root,
                    root,
                    export_root=exports_dir,
                    reimbursement_config={},
                )
            self.assertFalse(exports_dir.exists())

    def test_buyer_name_warning_does_not_block_export(self):
        claims = []

        def prepare(db, ids, root):
            claims.append(db.create_claim_group("Buyer Name Claim"))
            db.add_invoice_to_claim(claims[0], ids[0])

        rows = [{
            "buyer_name": "Mismatched Company Name",
            "review_status": "approved",
        }]

        with self.window(rows, prepare) as (win, ids, root):
            # strict_buyer_check is True, but strict_buyer_tax_check is False
            win.config = {
                "reimbursement": {
                    "strict_buyer_check": True,
                    "buyer_name": "Standard Default Company",
                    "strict_buyer_tax_check": False,
                }
            }
            win._switch_main_page("export")
            self.select_claim(win, claims[0])

            # 1. Row displays warning reason
            item = self.find_item_by_invoice_id(win, ids[0])
            self.assertIn("购买方抬头不符", item.text())
            payload = item.data(INVOICE_ROW_ROLE)
            self.assertTrue(payload["attention"])
            self.assertIn("购买方抬头不符", payload["subtitle"])

            # 2. Export is NOT blocked (warning only)
            self.assertTrue(win.btn_run_export_page.isEnabled())
            self.assertIn("已通过发票可导出", win.lbl_export_action_hint.text())

            # 3. Direct export succeeds and includes warning in manifest
            exports_dir = root / "exports"
            package = export_claim_package(
                win.db,
                claims[0],
                root,
                root,
                export_root=exports_dir,
                reimbursement_config=win.config["reimbursement"],
            )
            self.assertTrue(package.exists())
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("购买方与默认开票主体不一致", manifest["items"][0]["warning"])

    def test_scope_filtering_updates_per_invoice_issues(self):
        claims = []

        def prepare(db, ids, root):
            claims.append(db.create_claim_group("Scope Filter Claim"))
            db.add_invoice_to_claim(claims[0], ids[0])
            db.add_invoice_to_claim(claims[0], ids[1])

        # Invoice 0: approved, clean
        # Invoice 1: to_review, with tax ID mismatch
        rows = [
            {
                "invoice_number": "INV-APPROVED",
                "buyer_tax_id": VALID_USCC_2,
                "review_status": "approved",
            },
            {
                "invoice_number": "INV-PENDING-BAD-TAX",
                "buyer_tax_id": VALID_USCC_1,
                "review_status": "to_review",
            },
        ]

        with self.window(rows, prepare) as (win, ids, root):
            win.config = {
                "reimbursement": {
                    "strict_buyer_tax_check": True,
                    "buyer_tax_id": VALID_USCC_2,
                }
            }
            win._switch_main_page("export")
            self.select_claim(win, claims[0])

            # Scope: 仅已通过发票 (include_pending = False)
            win.export_scope.setCurrentIndex(0)
            self.settle()

            # Invoice 0 is in scope and clean
            item_approved = self.find_item_by_invoice_id(win, ids[0])
            self.assertFalse(item_approved.data(INVOICE_ROW_ROLE)["attention"])

            # Invoice 1 is out of scope: no blockers displayed for current scope
            item_pending = self.find_item_by_invoice_id(win, ids[1])
            self.assertFalse(item_pending.data(INVOICE_ROW_ROLE)["attention"])
            self.assertEqual(item_pending.data(INVOICE_ROW_ROLE)["subtitle"], "待审核 · INV-PENDING-BAD-TAX")

            # Export is ready for approved invoices
            self.assertTrue(win.btn_run_export_page.isEnabled())
            self.assertIn("已通过发票可导出", win.lbl_export_action_hint.text())

            # Switch scope to: 已通过和待审核发票 (include_pending = True)
            win.export_scope.setCurrentIndex(1)
            self.settle()

            # Invoice 1 is now in scope and its blocker is displayed!
            item_pending = self.find_item_by_invoice_id(win, ids[1])
            self.assertTrue(item_pending.data(INVOICE_ROW_ROLE)["attention"])
            self.assertIn("需处理：税号与默认主体不符", item_pending.data(INVOICE_ROW_ROLE)["subtitle"])
            self.assertIn("税号与默认主体不符", item_pending.text())

            # Export is now blocked by the pending invoice's issue
            self.assertFalse(win.btn_run_export_page.isEnabled())
            self.assertIn("购买方税号与默认主体不符", win.lbl_export_action_hint.text())

    def test_confirmation_rechecks_saved_company_profile_from_another_window(self):
        claims = []

        def prepare(db, ids, root):
            claims.append(db.create_claim_group("Shared settings claim"))
            for invoice_id in ids:
                db.add_invoice_to_claim(claims[0], invoice_id)

        rows = [
            {"buyer_name": "Test Company", "buyer_tax_id": VALID_USCC_1,
             "buyer_tax_id_type": "uscc", "review_status": status}
            for status in ("approved", "to_review", "ignored")
        ]
        initial = {"reimbursement": {"buyer_name": "Test Company", "buyer_tax_id": VALID_USCC_1,
                                     "strict_buyer_tax_check": False, "strict_buyer_check": False}}
        with self.window(rows, prepare, saved_config=initial) as (win, ids, root):
            win.workbench_nav_buttons["export"].click()
            self.select_claim(win, claims[0])
            self.assertTrue(win.btn_run_export_page.isEnabled())
            editor = InvoiceReviewApp(win.db_path, splash=None)
            try:
                editor._deferred_init()
                editor.resize(1440, 900)
                editor.show()
                editor.workbench_nav_buttons["settings"].click()
                self.settle()
                nav = editor.settings_tabs.nav_list
                company = next(nav.item(i) for i in range(nav.count())
                               if nav.item(i).data(Qt.UserRole) == "company_tax_profile")
                nav.scrollToItem(company)
                QTest.mouseClick(nav.viewport(), Qt.LeftButton, pos=nav.visualItemRect(company).center())
                self.settle()
                self.assertTrue(editor.btn_settings_company_profile_edit.isVisible())

                def confirm_after_save(box, buyer_name):
                    self.assertEqual(box.windowTitle(), "确认导出报销包")
                    self.assertIn("仅已通过发票", box.text())

                    def edit(dialog):
                        dialog.txt_buyer_name.setText(buyer_name)
                        dialog.txt_tax_id.setText(VALID_USCC_2)
                        dialog.chk_strict_tax.setChecked(True)
                        dialog.chk_strict_name.setChecked(False)
                        save = next(b for b in dialog.findChildren(QPushButton) if b.text() == "保存")
                        QTest.mouseClick(save, Qt.LeftButton)

                    # A separate desktop instance can save while confirmation is
                    # open. Invoke its actual settings action despite Qt's
                    # same-process modality in this test.
                    self.run_modal(CompanyTaxProfileDialog,
                                   editor.btn_settings_company_profile_edit.click, edit)
                    persisted = config_module.load_config_safe()["reimbursement"]
                    self.assertTrue(persisted["strict_buyer_tax_check"])
                    self.assertEqual(persisted["buyer_tax_id"], VALID_USCC_2)
                    self.assertEqual(persisted["buyer_name"], buyer_name)
                    QTest.mouseClick(next(b for b in box.buttons() if b.text() == "确认导出"), Qt.LeftButton)

                with patch.object(QMessageBox, "warning") as warning:
                    self.run_modal(QMessageBox, win.btn_run_export_page.click,
                                   lambda box: confirm_after_save(box, "Test Company"))
                    warning.assert_called_once()
                    self.assertIn("购买方税号与默认主体不符", warning.call_args.args[2])
                self.settle()
                self.assertFalse(win.btn_run_export_page.isEnabled())
                self.assertIn("购买方税号与默认主体不符", win.lbl_export_action_hint.text())
                self.assertTrue(self.find_item_by_invoice_id(win, ids[0]).data(INVOICE_ROW_ROLE)["attention"])
                self.assertEqual(win.db.get_claim_group(claims[0])["status"], "draft")
                self.assertEqual(win.db.get_export_runs(claims[0]), [])
                self.assertFalse((root / "exports").exists())

                # Correct the approved invoice, then save another profile while
                # confirming. The real worker must receive that latest snapshot.
                self.assertTrue(win.db.update_invoice_financial_fields(
                    ids[0], amount="20.00", tax_amount="0.00", tax_rate="0%",
                    invoice_code="", buyer_tax_id=VALID_USCC_2, buyer_tax_id_type="uscc"))
                win._refresh_export_page()
                self.select_claim(win, claims[0])
                self.assertTrue(win.btn_run_export_page.isEnabled())
                for invoice_id in ids[1:]:
                    self.assertFalse(self.find_item_by_invoice_id(win, invoice_id).data(INVOICE_ROW_ROLE)["attention"])
                with patch.object(app_module, "ClaimExportWorker", wraps=ClaimExportWorker) as start, \
                     patch("scripts.invoice_fetch.claim_export.claim_export_preflight",
                           wraps=claim_export_preflight) as preflight:
                    self.run_modal(QMessageBox, win.btn_run_export_page.click,
                                   lambda box: confirm_after_save(box, "Updated Test Company"))
                    start.assert_called_once()
                    snapshot = start.call_args.kwargs["reimbursement_config"]
                    self.assertEqual(snapshot, config_module.load_config_safe()["reimbursement"])
                    self.assertTrue(any(call.kwargs["reimbursement_config"] is snapshot
                                        for call in preflight.call_args_list))
                    self.assertFalse(start.call_args.kwargs["include_to_review"])
                    self.assertEqual(start.call_args.kwargs["export_root"], root / "exports")
                worker = win.claim_export_worker
                if worker is not None:
                    self.assertTrue(worker.wait(10000))
                self.settle()
                manifests = list((root / "exports").rglob("manifest.json"))
                self.assertEqual(len(manifests), 1)
                self.assertTrue(verify_export_manifest(manifests[0].parent)["valid"])
                manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
                self.assertEqual([item["invoice_id"] for item in manifest["items"]], [ids[0]])
                self.assertEqual(win.db.get_claim_group(claims[0])["status"], "exported")
                self.assertEqual(len(win.db.get_export_runs(claims[0])), 1)
            finally:
                editor._shutdown_background_workers(wait_ms=1000)
                editor.close()
                editor.deleteLater()
                self.settle()

    def test_strict_tax_failure_keeps_full_ids_out_of_logs_and_diagnostic_zip(self):
        claims = []

        def prepare(db, ids, root):
            claims.append(db.create_claim_group("Diagnostic claim"))
            db.add_invoice_to_claim(claims[0], ids[0])

        number = "98501234"
        rows = [{"invoice_number": number, "buyer_tax_id": VALID_USCC_1, "buyer_tax_id_type": "uscc"}]
        # Cover both flat and nested config fields in the redacted diagnostic copy.
        config = {"buyer_tax_id": VALID_USCC_1,
                  "reimbursement": {"buyer_tax_id": VALID_USCC_2, "strict_buyer_tax_check": True}}
        with self.window(rows, prepare, saved_config=config) as (win, ids, root):
            log_path = root / "logs" / "synthetic-export.log"
            log_path.parent.mkdir(exist_ok=True)
            handler = attach_privacy_filter(logging.FileHandler(log_path, encoding="utf-8"))
            logger = logging.getLogger("invoice_fetch.gui.app")
            logger.addHandler(handler)
            worker = ClaimExportWorker(db_path=win.db_path, claim_id=claims[0], project_root=root,
                                       runtime_dir=root, include_to_review=False,
                                       reimbursement_config=config_module.load_config_safe()["reimbursement"],
                                       export_root=root / "exports")
            errors = []
            worker.error.connect(errors.append)
            worker.error.connect(win._claim_export_error)
            try:
                with patch.object(QMessageBox, "critical") as critical:
                    worker.start()
                    self.assertTrue(worker.wait(10000))
                    self.settle()
                    critical.assert_called_once()
                    self.assertIn(number, critical.call_args.args[2])
            finally:
                worker.wait()
                logger.removeHandler(handler)
                handler.close()
            self.assertEqual(len(errors), 1)
            self.assertIn(number, errors[0])
            self.assertIn("购买方税号与默认主体不符", errors[0])
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("发票号 98***34", log_text)
            self.assertIn("购买方税号与默认主体不符", log_text)
            with self.subTest(surface="worker error"):
                self.assertNotIn(VALID_USCC_1, errors[0])
                self.assertNotIn(VALID_USCC_2, errors[0])
            with self.subTest(surface="runtime log"):
                self.assertNotIn(VALID_USCC_1, log_text)
                self.assertNotIn(VALID_USCC_2, log_text)

            archive = diagnostics.export_diagnostics_zip(root / "diagnostics")
            with zipfile.ZipFile(archive) as zf:
                entries = {name: zf.read(name).decode("utf-8") for name in zf.namelist()}
                for name, contents in entries.items():
                    with self.subTest(entry=name):
                        self.assertNotIn(VALID_USCC_1, contents)
                        self.assertNotIn(VALID_USCC_2, contents)
                self.assertIn("购买方税号与默认主体不符", entries["latest.log.redacted"])
                self.assertIn("发票号 98***34", entries["latest.log.redacted"])
                redacted = json.loads(entries["config.redacted.json"])
                self.assertEqual(redacted["buyer_tax_id"], "***redacted***")
                self.assertEqual(redacted["reimbursement"]["buyer_tax_id"], "***redacted***")
            saved = config_module.load_config_safe()
            self.assertEqual(saved["buyer_tax_id"], VALID_USCC_1)
            self.assertEqual(saved["reimbursement"]["buyer_tax_id"], VALID_USCC_2)
            self.assertEqual(win.db.get_invoice(ids[0])["buyer_tax_id"], VALID_USCC_1)
            self.assertEqual(win.db.get_claim_group(claims[0])["status"], "draft")
            self.assertEqual(win.db.get_export_runs(claims[0]), [])
            self.assertFalse((root / "exports").exists())

    def test_strict_tax_checks_preserve_null_empty_and_declared_type_semantics(self):
        flat = {"buyer_tax_id": VALID_USCC_2, "strict_buyer_tax_check": True}
        cases = [
            (None, "unknown", set()),
            ("", "unknown", {"buyer_tax"}),
            (VALID_USCC_1, "uscc", {"buyer_tax"}),
            (VALID_USCC_2, "uscc", set()),
            (VALID_USCC_2, "unknown", set()),
            (VALID_USCC_2, "invalid", {"tax_id"}),
            (VALID_USCC_2, "legacy15", {"tax_id"}),
        ]
        for cfg in (flat, {"reimbursement": flat}):
            for value, scheme, expected in cases:
                with self.subTest(scheme=scheme, expected=expected):
                    invoice = {"total_amount": "20.00", "buyer_tax_id": value,
                               "buyer_tax_id_type": scheme}
                    self.assertEqual(set(invoice_export_issues(invoice, cfg)), expected)


if __name__ == "__main__":
    unittest.main()
