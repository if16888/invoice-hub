import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from scripts.invoice_fetch.ai_classifier import AIClassifier
from scripts.invoice_fetch.config import load_config


class PrivacyDefaultTests(unittest.TestCase):
    def test_load_config_defaults_to_no_cloud_ai(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps({
                "email": {"address": "user@example.com"},
            }), encoding="utf-8")

            cfg = load_config(cfg_path)

        self.assertEqual(cfg["ai"]["provider"], "none")
        self.assertEqual(cfg["ai"]["model"], "")

    def test_load_config_accepts_explicit_no_cloud_ai(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps({
                "email": {"address": "user@example.com"},
                "ai": {"provider": "none", "model": ""},
            }), encoding="utf-8")

            cfg = load_config(cfg_path)

        self.assertEqual(cfg["ai"]["provider"], "none")
        self.assertEqual(cfg["ai"]["model"], "")

    def test_ai_classifier_none_provider_does_not_require_api_key(self):
        ai = AIClassifier(provider="none", model="", batch_size=20)

        results = ai.classify_batch([
            {"uid": 1, "subject": "maybe invoice", "sender": "billing@example.com"},
        ])

        self.assertEqual(results[0]["uid"], 1)
        self.assertIsNone(results[0]["is_invoice"])
        self.assertIn("AI 分类未启用", results[0]["reason"])

    @patch("scripts.invoice_fetch.ai_classifier.get_ai_api_key", return_value="")
    def test_ai_classifier_defaults_gemini_to_25_flash(self, _mock_get_key):
        ai = AIClassifier(provider="gemini", model="", batch_size=20)

        self.assertEqual(ai.model, "gemini-2.5-flash")
    def test_ai_masking_redacts_common_sensitive_patterns(self):
        masked = AIClassifier._mask_sensitive_info(
            '张三 <tester@example.com> 手机 13812345678 订单 20260520123456789'
        )

        self.assertIn("138****5678", masked)
        self.assertIn("20****89", masked)
        self.assertNotIn("13812345678", masked)
        self.assertNotIn("20260520123456789", masked)
        self.assertNotIn("tester@example.com", masked)

    def test_ai_prompt_uses_only_masked_headers_not_body_or_attachments(self):
        ai = AIClassifier(provider="none", model="", batch_size=20)

        prompt = ai._build_user_message([
            {
                "uid": 99,
                "subject": "发票 订单 202606091234567890",
                "sender": "real.person@example.com",
                "body": "正文包含身份证 110101199001011234，不应进入云 AI 请求",
                "attachment_text": "PDF/OFD 全文、银行卡 6222020202020202020，不应进入云 AI 请求",
                "ocr_text": "图片 OCR 全文，不应进入云 AI 请求",
                "file_path": r"D:\\private\\invoice.pdf",
            }
        ])

        self.assertIn("UID=99", prompt)
        self.assertIn("主题:", prompt)
        self.assertIn("发件人:", prompt)
        self.assertIn("20****90", prompt)
        self.assertIn("r***n@example.com", prompt)
        self.assertNotIn("202606091234567890", prompt)
        self.assertNotIn("real.person@example.com", prompt)
        self.assertNotIn("身份证", prompt)
        self.assertNotIn("110101199001011234", prompt)
        self.assertNotIn("银行卡", prompt)
        self.assertNotIn("6222020202020202020", prompt)
        self.assertNotIn("PDF/OFD", prompt)
        self.assertNotIn("OCR", prompt)
        self.assertNotIn("D:\\private", prompt)

    def test_ai_request_error_summary_does_not_leak_url_or_key(self):
        request = requests.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=secret-token",
        ).prepare()
        response = requests.Response()
        response.status_code = 403
        response.request = request
        exc = requests.HTTPError(
            "403 Client Error for url: https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=secret-token",
            response=response,
        )

        safe = AIClassifier._safe_request_error(exc)

        self.assertEqual(safe, "HTTPError:status=403")
        self.assertNotIn("secret-token", safe)
        self.assertNotIn("generativelanguage", safe)
        self.assertNotIn("key=", safe)

    @patch("scripts.invoice_fetch.ai_classifier.get_ai_api_key", return_value="test-key")
    def test_classifier_loads_profile_scoped_key(self, mock_get_key):
        AIClassifier(
            provider="deepseek",
            model="deepseek-chat",
            batch_size=20,
            profile_id="ai-main",
        )
        mock_get_key.assert_called_once_with("deepseek", profile_id="ai-main")

    def test_run_classify_forwards_active_profile_id(self):
        captured = {}

        class FakeClassifier:
            auth_failed = False

            def __init__(self, **kwargs):
                captured.update(kwargs)

            def classify_batch(self, emails):
                return [{"uid": emails[0]["uid"], "is_invoice": True, "reason": "test"}]

        db = MagicMock()
        db.get_unclassified_emails.return_value = [{
            "uid": 1,
            "subject": "普通邮件",
            "sender": "sender@example.com",
            "mailbox_key": "mailbox-one",
        }]
        db.is_trusted_sender.return_value = False
        ai_cfg = {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "batch_size": 20,
            "profile_id": "ai-main",
        }
        import scripts.invoice_fetch.services as application_services
        with patch.object(application_services, "AIClassifier", FakeClassifier, create=True), patch.object(
            application_services, "rule_classify", return_value=(-1, "未命中本地规则")
        ):
            application_services._run_classify(
                db,
                ai_cfg,
                no_ai=False,
                mailbox_key="mailbox-one",
            )
        self.assertEqual(captured["profile_id"], "ai-main")


if __name__ == "__main__":
    unittest.main()
