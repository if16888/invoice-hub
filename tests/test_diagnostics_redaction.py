"""Synthetic regression coverage for diagnostic-package redaction.

The diagnostic ZIP and the "copy redacted diagnostics" action must never carry
mobile-upload tokens, user-profile paths, invoice numbers or search terms.
"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch


TOKEN = "synthetic-upload-token-7f3a9c2e"
USER = "synthetic-alice-9f2c"

_EXPECTED_ZIP_ENTRIES = {
    "app_info.json",
    "latest.log.redacted",
    "config.redacted.json",
    "environment.txt",
    "privacy_scan_result.txt",
}


def _export_package(runtime: Path, base: Path) -> tuple[set[str], str]:
    from scripts.invoice_fetch import diagnostics

    with patch.object(diagnostics.config_mod, "RUNTIME_DIR", runtime), \
            patch.object(diagnostics.config_mod, "PROJECT_ROOT", base):
        zip_path = diagnostics.export_diagnostics_zip(base / "out")
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        combined = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in sorted(names)
        )
    return names, combined


class DiagnosticsRedactionTests(unittest.TestCase):
    def _make_runtime(
        self,
        base: Path,
        *,
        config: dict | None = None,
        log_text: str = "",
    ) -> Path:
        runtime = base / "runtime"
        (runtime / "logs").mkdir(parents=True)
        (runtime / "logs" / "run_20260531_123456.log").write_text(
            log_text, encoding="utf-8"
        )
        (runtime / "config.json").write_text(
            json.dumps(config or {}, ensure_ascii=False), encoding="utf-8"
        )
        return runtime

    def test_upload_token_in_url_path_is_absent_from_package(self):
        log_text = (
            f"手机上传链接 http://192.168.50.20:8765/u/{TOKEN} 已打开\n"
        )
        config = {
            "download_url": f"http://192.168.50.20:8765/u/{TOKEN}?x=1",
            "mobile_upload": {
                "upload_url": f"http://192.168.50.20:8765/u/{TOKEN}",
            },
        }
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = self._make_runtime(base, config=config, log_text=log_text)
            names, combined = _export_package(runtime, base)

        self.assertEqual(names, _EXPECTED_ZIP_ENTRIES)
        self.assertNotIn(TOKEN, combined)
        self.assertNotIn("/u/", combined)
        self.assertIn("<redacted:", combined)

    def test_windows_user_profile_paths_are_masked(self):
        spaced_user = "Synthetic Alice"
        config = {
            "export": {
                "output_dir": rf"C:\Users\{USER}\Documents\invoice-export",
            },
        }
        log_text = (
            rf"config read C:\Users\{USER}\AppData\Local\InvoiceHub\runtime\config.json"
            "\n"
            rf"archive failed C:\Users\{spaced_user}\Documents\invoice.pdf"
            "\n"
        )
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = self._make_runtime(base, config=config, log_text=log_text)
            names, combined = _export_package(runtime, base)

        self.assertEqual(names, _EXPECTED_ZIP_ENTRIES)
        self.assertNotIn(USER, combined)
        self.assertNotIn("Synthetic Alice", combined)
        self.assertNotIn(r"C:\Users", combined)
        self.assertIn("file#", combined)

    def test_eight_digit_invoice_number_and_amount_are_masked_in_package(self):
        log_text = (
            "发票号码 12345678 金额 169.08 开票日期 20261024\n"
            "invoice 87654321 amount 1,234.56\n"
        )
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = self._make_runtime(base, log_text=log_text)
            names, combined = _export_package(runtime, base)

        self.assertEqual(names, _EXPECTED_ZIP_ENTRIES)
        self.assertNotIn("12345678", combined)
        self.assertNotIn("87654321", combined)
        self.assertNotIn("169.08", combined)
        self.assertNotIn("1,234.56", combined)
        self.assertIn("12***78", combined)
        self.assertIn("87***21", combined)
        self.assertIn("***", combined)
        # Dates are not invoice numbers and must remain readable diagnostics.
        self.assertIn("20261024", combined)

    def test_package_allowlist_is_unchanged_and_rejects_private_files(self):
        from scripts.invoice_fetch import diagnostics

        self.assertEqual(set(diagnostics._ALLOWED_ZIP_ENTRIES), _EXPECTED_ZIP_ENTRIES)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = self._make_runtime(base, log_text="diagnostics\n")
            (runtime / "invoices.db").write_bytes(b"sqlite synthetic private data")
            (runtime / "attachments").mkdir()
            (runtime / "attachments" / "invoice.pdf").write_bytes(b"%PDF-synthetic")
            (runtime / "exports").mkdir()
            (runtime / "exports" / "reimbursement.xlsx").write_bytes(b"synthetic")

            names, combined = _export_package(runtime, base)

        self.assertEqual(names, _EXPECTED_ZIP_ENTRIES)
        self.assertNotIn("invoices.db", names)
        self.assertNotIn("attachments/invoice.pdf", names)
        self.assertNotIn("exports/reimbursement.xlsx", names)
        self.assertFalse(
            [name for name in names if name.lower().endswith((".db", ".pdf", ".xlsx"))]
        )
        self.assertNotIn("sqlite synthetic private data", combined)
        self.assertNotIn("%PDF-synthetic", combined)

    def test_copied_diagnostics_drop_raw_search_and_sensitive_values(self):
        try:
            from scripts.invoice_fetch.gui.log_diagnostics_mixin import (
                LogDiagnosticsMixin,
            )
        except Exception as exc:  # pragma: no cover - PySide6 may be unavailable
            self.skipTest(f"PySide6 is not available: {exc}")

        search = "SYNTHETIC-SEARCH-7f3a9c2e"
        token_url = f"http://192.168.50.20:8765/u/{TOKEN}"
        profile_path = rf"C:\Users\{USER}\Documents\invoice.pdf"

        class _Window(LogDiagnosticsMixin):
            def __init__(self):
                self.current_filter_status = "to_review"
                self.txt_search = Mock()
                self.txt_search.text.return_value = search
                self.chk_unlinked = Mock()
                self.chk_unlinked.isChecked.return_value = False
                self.chk_needs_fix = Mock()
                self.chk_needs_fix.isChecked.return_value = False
                self.chk_show_deleted = Mock()
                self.chk_show_deleted.isChecked.return_value = False
                self._last_scan_summary = {"note": f"{token_url} {profile_path}"}

            def _database_user_version(self):
                return 4

            def write_log(self, *args, **kwargs):
                return None

            def statusBar(self):
                return Mock()

        window = _Window()
        app_info = {
            "app": "Invoice Hub",
            "version": "v9.9.9",
            "latest_log": "<log:redacted:run.log>",
            "config_summary": {
                "email_provider": "qq",
                "email_configured": False,
                "ai_provider": "none",
            },
        }
        with patch(
            "scripts.invoice_fetch.gui.log_diagnostics_mixin.collect_app_info",
            return_value=app_info,
        ), patch(
            "scripts.invoice_fetch.gui.log_diagnostics_mixin.QApplication"
        ) as qapp:
            window._copy_diagnostic_info()
            copied = qapp.clipboard.return_value.setText.call_args.args[0]

        payload = json.loads(copied)
        self.assertNotIn(search, copied)
        self.assertNotIn(TOKEN, copied)
        self.assertNotIn(USER, copied)
        self.assertIn("<search:redacted:", copied)
        self.assertEqual(payload["current_filter_state"]["status"], "to_review")
        self.assertEqual(payload["database_user_version"], 4)


if __name__ == "__main__":
    unittest.main()
