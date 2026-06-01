import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


class DiagnosticsTests(unittest.TestCase):
    def test_export_diagnostics_zip_excludes_private_runtime_data(self):
        from scripts.invoice_fetch import diagnostics

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = base / "runtime"
            runtime.mkdir()
            (runtime / "invoices.db").write_bytes(b"sqlite private data")
            (runtime / "attachments").mkdir()
            (runtime / "attachments" / "invoice.pdf").write_bytes(b"%PDF-private")
            (runtime / "exports").mkdir()
            (runtime / "exports" / "reimbursement.xlsx").write_bytes(b"private xlsx")
            (runtime / "logs").mkdir()
            (runtime / "logs" / "run_20260531_123456.log").write_text(
                "user tester@example.com DEEPSEEK_API_KEY=sk-test-placeholder invoice 2632700000005659506 "
                "url https://example.com/invoice?token=redacted-placeholder&x=1 phone 13812345678",
                encoding="utf-8",
            )
            (runtime / "config.json").write_text(
                json.dumps({
                    "email": {"address": "tester@example.com", "auth_code": "mail-secret"},
                    "ai": {"api_key": "sk-test-placeholder"},
                    "headers": {"authorization": "Bearer redacted-placeholder"},
                    "download_url": "https://example.com/invoice?token=redacted-placeholder",
                }),
                encoding="utf-8",
            )

            with patch.object(diagnostics.config_mod, "RUNTIME_DIR", runtime), \
                    patch.object(diagnostics.config_mod, "PROJECT_ROOT", base):
                zip_path = diagnostics.export_diagnostics_zip(base / "out")

            self.assertRegex(zip_path.name, r"^InvoiceHub-diagnostics-\d{8}-\d{6}\.zip$")
            with zipfile.ZipFile(zip_path) as zf:
                names = set(zf.namelist())
                self.assertEqual(names, {
                    "app_info.json",
                    "latest.log.redacted",
                    "config.redacted.json",
                    "environment.txt",
                    "privacy_scan_result.txt",
                })
                combined = "\n".join(
                    zf.read(name).decode("utf-8", errors="replace")
                    for name in sorted(names)
                )

            self.assertNotIn("invoices.db", names)
            self.assertNotIn("attachments/invoice.pdf", names)
            self.assertNotIn("exports/reimbursement.xlsx", names)
            self.assertNotIn("tester@example.com", combined)
            self.assertNotIn("sk-test-placeholder", combined)
            self.assertNotIn("mail-secret", combined)
            self.assertNotIn("Bearer redacted-placeholder", combined)
            self.assertNotIn("2632700000005659506", combined)
            self.assertNotIn("token=redacted-placeholder", combined)
            self.assertNotIn("DEEPSEEK_API_KEY=sk-test-placeholder", combined)
            self.assertIn("?***", combined)
            self.assertIn("***redacted***", combined)

    def test_redact_text_masks_required_patterns(self):
        from scripts.invoice_fetch.diagnostics import redact_text

        redacted = redact_text(
            "email tester@example.com user@example.com phone 13812345678 invoice 2632700000005659506 "
            "url https://example.com/a?token=redacted-placeholder&x=1 auth_code: abc123 GEMINI_API_KEY=xyz "
            "Authorization: Bearer sk-test-placeholder authorization=Bearer abc.def token=abc def"
        )

        self.assertIn("t***r@example.com", redacted)
        self.assertIn("u***r@example.com", redacted)
        self.assertIn("138****5678", redacted)
        self.assertIn("26****06", redacted)
        self.assertIn("https://example.com/a?***", redacted)
        self.assertIn("auth_code: ***redacted***", redacted)
        self.assertIn("GEMINI_API_KEY=***redacted***", redacted)
        self.assertIn("Authorization: ***redacted***", redacted)
        self.assertIn("authorization=***redacted***", redacted)
        self.assertIn("token=***redacted***", redacted)
        self.assertNotIn("tester@example.com", redacted)
        self.assertNotIn("user@example.com", redacted)
        self.assertNotIn("2632700000005659506", redacted)
        self.assertNotIn("token=redacted-placeholder", redacted)
        self.assertNotIn("GEMINI_API_KEY=xyz", redacted)
        self.assertNotIn("sk-test-placeholder", redacted)
        self.assertNotIn("abc.def", redacted)
        self.assertNotIn("abc def", redacted)

    def test_redact_config_masks_sensitive_fields_recursively(self):
        from scripts.invoice_fetch.diagnostics import redact_config

        redacted = redact_config({
            "email": {"address": "tester@example.com", "auth_code": "mail-secret"},
            "nested": [{"token": "abc"}, {"authorization": "Bearer redacted-placeholder"}],
            "download_url": "https://example.com/a?token=redacted-placeholder",
        })

        self.assertEqual(redacted["email"]["auth_code"], "***redacted***")
        self.assertEqual(redacted["nested"][0]["token"], "***redacted***")
        self.assertEqual(redacted["nested"][1]["authorization"], "***redacted***")
        self.assertEqual(redacted["email"]["address"], "t***r@example.com")
        self.assertEqual(redacted["download_url"], "https://example.com/a?***")

    def test_bug_report_template_has_privacy_checkbox(self):
        template = Path(".github/ISSUE_TEMPLATE/bug_report.yml")
        self.assertTrue(template.exists())
        content = template.read_text(encoding="utf-8")
        self.assertIn("checkboxes", content)
        self.assertIn("privacy", content.lower())
        self.assertIn("diagnostic", content.lower())
        self.assertIn("environment", content.lower())
        self.assertIn("installer", content.lower())
        self.assertIn("source", content.lower())
        self.assertIn("Problem description / 问题描述", content)
        self.assertIn("Steps to reproduce / 复现步骤", content)
        self.assertIn("Environment / 环境信息", content)
        self.assertIn("Redacted diagnostics package / 脱敏诊断包", content)
        self.assertIn("Privacy confirmation / 隐私确认", content)


if __name__ == "__main__":
    unittest.main()
