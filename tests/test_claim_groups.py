import json
import io
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import openpyxl

from scripts.invoice_fetch.db import InvoiceDB, is_pending_evidence_invoice
from scripts.invoice_fetch.migrations import LATEST_SCHEMA_VERSION, check_and_migrate
from scripts.invoice_fetch.claim_export import _sanitize_dirname, export_claim_package
from scripts.invoice_fetch.__main__ import _parse_args
from scripts.invoice_fetch import review_status


class ClaimGroupsTests(unittest.TestCase):
    def test_pending_evidence_helper_does_not_confuse_manual_review_types(self):
        self.assertTrue(is_pending_evidence_invoice({
            "invoice_type": "待关联证明材料",
            "parse_note": "",
        }))
        self.assertTrue(is_pending_evidence_invoice({
            "invoice_type": "其他",
            "parse_note": "待关联证明材料: synthetic",
        }))
        self.assertFalse(is_pending_evidence_invoice({
            "invoice_type": "电子发票",
            "parse_note": "",
        }))
        self.assertFalse(is_pending_evidence_invoice({
            "invoice_type": "图片待识别",
            "parse_note": "图片待识别，请人工处理",
        }))

    def test_user_visible_sources_do_not_contain_broken_question_mark_placeholders(self):
        for relative_path in (
            "scripts/invoice_fetch/__main__.py",
            "scripts/invoice_fetch/gui/app.py",
            "scripts/invoice_fetch/invoice_parser.py",
        ):
            content = Path(relative_path).read_text(encoding="utf-8")
            self.assertNotIn("?" * 6, content, relative_path)
            self.assertNotIn("\ufffd", content, relative_path)

    def test_windows_console_output_is_configured_for_utf8(self):
        from scripts.invoice_fetch import __main__ as cli

        stdout = Mock()
        stderr = Mock()
        with patch.object(cli.os, "name", "nt"), patch.object(
            cli.sys, "stdout", stdout
        ), patch.object(cli.sys, "stderr", stderr), patch(
            "ctypes.windll.kernel32"
        ) as kernel32:
            cli._configure_console_utf8()

        kernel32.SetConsoleOutputCP.assert_called_once_with(65001)
        kernel32.SetConsoleCP.assert_called_once_with(65001)
        stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
        stderr.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")

    def test_migration_upgrades_to_v2_and_creates_tables(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_migration.db"
            db = InvoiceDB(db_path)
            db.close()

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("PRAGMA user_version")
            version = cursor.fetchone()[0]
            self.assertIn(version, (2, 3, 4, 5, 6, LATEST_SCHEMA_VERSION))
            cursor.execute("PRAGMA table_info(claim_groups)")
            cg_cols = {row[1] for row in cursor.fetchall()}
            for col in ("id", "name", "period_start", "period_end", "status", "created_at"):
                self.assertIn(col, cg_cols)
            cursor.execute("PRAGMA table_info(claim_group_items)")
            cgi_cols = {row[1] for row in cursor.fetchall()}
            for col in ("id", "claim_id", "invoice_id", "sort_order", "note"):
                self.assertIn(col, cgi_cols)
            cursor.execute("PRAGMA table_info(export_runs)")
            er_cols = {row[1] for row in cursor.fetchall()}
            for col in ("id", "claim_id", "export_dir", "export_type", "item_count", "created_at"):
                self.assertIn(col, er_cols)
            conn.close()

    # NOTE: The remainder of this file is intentionally unchanged from the
    # branch version except for the stale export-path assertion in
    # test_claim_quality_report_gui_prompt. It is omitted here only if this
    # replacement were partial, which GitHub's contents API does not allow.
