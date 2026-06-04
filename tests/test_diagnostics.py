import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


class DiagnosticsTests(unittest.TestCase):
    def test_app_version_comes_from_single_version_module(self):
        from scripts.invoice_fetch import APP_VERSION
        from scripts.invoice_fetch.version import APP_VERSION as VERSION_APP_VERSION
        from scripts.invoice_fetch.version import VERSION

        self.assertEqual(VERSION, "0.1.3-rc1")
        self.assertEqual(VERSION_APP_VERSION, "v0.1.3-rc1")
        self.assertEqual(APP_VERSION, VERSION_APP_VERSION)

    def test_collect_app_info_includes_version_metadata_without_secrets(self):
        from scripts.invoice_fetch import diagnostics
        from scripts.invoice_fetch import APP_VERSION

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = base / "runtime"
            runtime.mkdir()
            (runtime / "config.json").write_text(
                json.dumps({
                    "email": {"provider": "qq", "address": "tester@example.com", "auth_code": "mail-secret"},
                    "ai": {"provider": "none", "api_key": "sk-test-placeholder"},
                }),
                encoding="utf-8",
            )

            with patch.object(diagnostics.config_mod, "RUNTIME_DIR", runtime), \
                    patch.object(diagnostics.config_mod, "PROJECT_ROOT", base):
                info = diagnostics.collect_app_info()

        combined = json.dumps(info, ensure_ascii=False)
        self.assertEqual(info["app"], "Invoice Hub")
        self.assertEqual(info["version"], APP_VERSION)
        self.assertNotIn("MVP", info["version"])
        self.assertIn(info["build_mode"], {"release", "local/dev"})
        self.assertEqual(info["data_dir"], "<runtime_dir:redacted>")
        self.assertEqual(info["log_dir"], "<log_dir:redacted>")
        self.assertEqual(info["config_summary"]["email_provider"], "qq")
        self.assertTrue(info["config_summary"]["email_configured"])
        self.assertNotIn(str(runtime), combined)
        self.assertNotIn("tester@example.com", combined)
        self.assertNotIn("mail-secret", combined)
        self.assertNotIn("sk-test-placeholder", combined)

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

    def test_issue_templates_have_privacy_first_feedback_flow(self):
        template = Path(".github/ISSUE_TEMPLATE/bug_report.yml")
        self.assertTrue(template.exists())
        content = template.read_text(encoding="utf-8")
        lower_content = content.lower()

        for field_id in (
            "id: version",
            "id: os",
            "id: run_mode",
            "id: summary",
            "id: steps",
            "id: actual",
            "id: expected",
            "id: diagnostics",
            "id: additional",
            "id: privacy",
        ):
            self.assertIn(field_id, content)

        for required_text in (
            "Invoice Hub 版本",
            "操作系统",
            "启动方式",
            "问题描述",
            "复现步骤",
            "实际结果",
            "期望结果",
            "是否已导出脱敏诊断包",
            "补充信息",
            "不要上传真实发票",
            "邮箱授权码",
            "API Key",
            "Cookie",
            "完整下载链接",
        ):
            self.assertIn(required_text, content)

        self.assertIn("checkboxes", content)
        self.assertIn("privacy", lower_content)
        self.assertIn("diagnostic", lower_content)
        self.assertIn("installer", lower_content)
        self.assertIn("portable", lower_content)
        self.assertIn("source", lower_content)

        feature_template = Path(".github/ISSUE_TEMPLATE/feature_request.yml")
        config_template = Path(".github/ISSUE_TEMPLATE/config.yml")
        self.assertTrue(feature_template.exists())
        self.assertTrue(config_template.exists())

        feature_content = feature_template.read_text(encoding="utf-8")
        self.assertIn("Feature request", feature_content)
        self.assertIn("不要上传真实发票", feature_content)
        self.assertIn("不上传任何真实发票", feature_content)

        config_content = config_template.read_text(encoding="utf-8")
        self.assertIn("blank_issues_enabled: false", config_content)
        self.assertIn("security/policy", config_content)

    def test_desktop_feedback_entry_uses_public_issues_with_fallback(self):
        source = Path("scripts/invoice_fetch/gui/app.py").read_text(encoding="utf-8")

        self.assertIn("https://github.com/if16888/invoice-hub/issues/new/choose", source)
        self.assertNotIn("invoice-hub-private/issues", source)
        self.assertIn("FEEDBACK_PRIVACY_NOTICE", source)
        self.assertIn("QDesktopServices.openUrl", source)
        self.assertIn("QApplication.clipboard().setText(GITHUB_ISSUES_URL)", source)

    def test_bug_report_template_has_privacy_checkbox(self):
        template = Path(".github/ISSUE_TEMPLATE/bug_report.yml")
        self.assertTrue(template.exists())
        content = template.read_text(encoding="utf-8")
        self.assertIn("checkboxes", content)
        self.assertIn("privacy", content.lower())
        self.assertIn("diagnostic", content.lower())
        self.assertIn("Invoice Hub 版本", content)
        self.assertIn("操作系统", content)
        self.assertIn("installer", content.lower())
        self.assertIn("portable", content.lower())
        self.assertIn("source", content.lower())
        self.assertIn("问题描述", content)
        self.assertIn("复现步骤", content)
        self.assertIn("是否已导出脱敏诊断包", content)
        self.assertIn("Privacy confirmation / 隐私确认", content)


if __name__ == "__main__":
    unittest.main()
