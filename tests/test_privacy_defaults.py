import json
import tempfile
import unittest
from pathlib import Path

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

    def test_ai_masking_redacts_common_sensitive_patterns(self):
        masked = AIClassifier._mask_sensitive_info(
            '张三 <tester@example.com> 手机 13812345678 订单 20260520123456789'
        )

        self.assertIn("138****5678", masked)
        self.assertIn("20****89", masked)
        self.assertNotIn("13812345678", masked)
        self.assertNotIn("20260520123456789", masked)
        self.assertNotIn("tester@example.com", masked)


if __name__ == "__main__":
    unittest.main()
