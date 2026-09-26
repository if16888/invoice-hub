import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch import config as config_module


class FirstRunConfigSafetyTests(unittest.TestCase):
    def test_safe_loader_does_not_promote_example_config_on_clean_install(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config.example.json").write_text(
                json.dumps(
                    {
                        "email": {"provider": "qq", "address": "sample@example.com"},
                        "reimbursement": {
                            "buyer_name": "示例公司",
                            "buyer_tax_id": "91310000EXAMPLE",
                            "strict_buyer_check": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(config_module, "PROJECT_ROOT", root):
                cfg = config_module.load_config_safe()

            self.assertEqual(cfg["email"]["address"], "")
            self.assertEqual(cfg["reimbursement"]["buyer_name"], "")
            self.assertEqual(cfg["reimbursement"]["buyer_tax_id"], "")

    def test_explicit_example_path_is_still_loadable_for_tests_and_docs(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.example.json"
            path.write_text(
                json.dumps(
                    {
                        "email": {"provider": "qq", "address": "sample@example.com"},
                        "reimbursement": {"buyer_name": "示例公司"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            cfg = config_module.load_config_safe(path)
            self.assertEqual(cfg["reimbursement"]["buyer_name"], "示例公司")


if __name__ == "__main__":
    unittest.main()
