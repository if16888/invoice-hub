import json
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.config import get_email_accounts, load_config, load_config_safe, validate_config_gui


class GenericImapConfigTests(unittest.TestCase):
    def _write_config(self, data: dict) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "config.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_163_provider_uses_imap_preset(self):
        path = self._write_config({
            "email": {
                "provider": "netease_163",
                "address": "user@163.com"
            },
            "imap": {},
        })

        cfg = load_config(path)

        self.assertEqual(cfg["email"]["provider"], "netease_163")
        self.assertEqual(cfg["email"]["username"], "user@163.com")
        self.assertEqual(cfg["imap"]["server"], "imap.163.com")
        self.assertEqual(cfg["imap"]["port"], 993)
        self.assertTrue(cfg["imap"]["ssl"])

    def test_126_provider_uses_imap_preset(self):
        path = self._write_config({
            "email": {
                "provider": "netease_126",
                "address": "user@126.com"
            },
            "imap": {},
        })

        cfg = load_config(path)

        self.assertEqual(cfg["imap"]["server"], "imap.126.com")
        self.assertEqual(cfg["imap"]["port"], 993)

    def test_custom_provider_requires_explicit_server(self):
        path = self._write_config({
            "email": {
                "provider": "custom",
                "address": "user@example.com"
            },
            "imap": {
                "server": "imap.example.com",
                "port": 993,
                "ssl": True,
            },
        })

        cfg = load_config(path)

        self.assertEqual(cfg["email"]["provider"], "custom")
        self.assertEqual(cfg["imap"]["server"], "imap.example.com")
        self.assertEqual(cfg["email"]["username"], "user@example.com")

    def test_custom_provider_without_server_is_invalid_for_load_config(self):
        path = self._write_config({
            "email": {
                "provider": "custom",
                "address": "user@example.com"
            },
            "imap": {},
        })

        with self.assertRaises(SystemExit):
            load_config(path)

    def test_validate_config_gui_accepts_custom_imap(self):
        validate_config_gui({
            "email": {
                "provider": "custom",
                "address": "user@example.com"
            },
            "imap": {
                "server": "imap.example.com",
                "port": 993,
                "ssl": True,
            },
            "search": {"months_back": 3},
            "ai": {"provider": "none"},
        })

    def test_load_config_safe_normalizes_provider_without_raising(self):
        path = self._write_config({
            "email": {
                "provider": "netease_163",
                "address": "user@163.com"
            },
            "imap": {},
        })

        cfg = load_config_safe(path)

        self.assertEqual(cfg["imap"]["server"], "imap.163.com")

    def test_qq_preset_fills_server_and_port(self):
        path = self._write_config({
            "email": {
                "provider": "qq",
                "address": "user@qq.com"
            },
            "imap": {},
        })
        cfg = load_config(path)
        self.assertEqual(cfg["imap"]["server"], "imap.qq.com")
        self.assertEqual(cfg["imap"]["port"], 993)

    def test_email_accounts_list_normalizes_multiple_enabled_accounts(self):
        path = self._write_config({
            "email_accounts": [
                {
                    "name": "Primary QQ",
                    "provider": "qq",
                    "address": "primary@qq.com",
                    "search": {"months_back": 4},
                },
                {
                    "name": "Rail Mail",
                    "provider": "custom",
                    "address": "rail@example.com",
                    "imap": {"server": "imap.example.com", "port": 993, "ssl": True},
                    "search": {"folder": "INBOX", "months_back": 2},
                },
                {
                    "name": "Disabled",
                    "provider": "qq",
                    "address": "disabled@qq.com",
                    "enabled": False,
                },
            ],
            "ai": {"provider": "none"},
        })
        cfg = load_config(path)
        accounts = get_email_accounts(cfg)
        self.assertEqual(len(accounts), 2)
        self.assertEqual(cfg["email"]["address"], "primary@qq.com")
        self.assertEqual(cfg["email"]["provider"], "qq")
        self.assertEqual(accounts[0]["mailbox_key"], "primary@qq.com")
        self.assertEqual(accounts[1]["mailbox_key"], "rail@example.com")
        self.assertEqual(accounts[1]["imap"]["server"], "imap.example.com")
        self.assertEqual(accounts[0]["search"]["months_back"], 4)

    def test_legacy_single_account_is_exposed_as_email_accounts(self):
        path = self._write_config({
            "email": {
                "provider": "qq",
                "address": "legacy@qq.com"
            },
            "imap": {},
        })
        cfg = load_config(path)
        accounts = get_email_accounts(cfg)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["address"], "legacy@qq.com")
        self.assertEqual(accounts[0]["mailbox_key"], "legacy")

    def test_disabled_account_list_falls_back_to_valid_legacy_account(self):
        cfg = {
            "email": {
                "provider": "qq",
                "address": "synthetic_user@qq.com",
            },
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
            "email_accounts": [
                {
                    "name": "Disabled sample",
                    "enabled": False,
                    "provider": "qq",
                    "address": "disabled@qq.com",
                },
            ],
        }

        accounts = get_email_accounts(cfg)

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["address"], "synthetic_user@qq.com")
        self.assertEqual(accounts[0]["mailbox_key"], "legacy")

    def test_placeholder_accounts_are_not_returned_as_enabled_mailboxes(self):
        cfg = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "email_accounts": [
                {
                    "name": "Placeholder",
                    "enabled": True,
                    "provider": "qq",
                    "address": "your_email@qq.com",
                },
            ],
        }

        self.assertEqual(get_email_accounts(cfg), [])

    def test_custom_imap_missing_server_fails(self):
        with self.assertRaises(ValueError):
            validate_config_gui({
                "email": {
                    "provider": "custom",
                    "address": "user@example.com"
                },
                "imap": {
                    "server": "",
                    "port": 993
                },
                "search": {"months_back": 3},
                "ai": {"provider": "none"}
            })

    def test_validate_config_gui_accepts_multi_account_mailboxes(self):
        validate_config_gui({
            "email_accounts": [
                {
                    "name": "Primary QQ",
                    "provider": "qq",
                    "address": "primary@qq.com",
                    "search": {"months_back": 3},
                },
                {
                    "name": "Rail Mail",
                    "provider": "custom",
                    "address": "rail@example.com",
                    "imap": {"server": "imap.example.com", "port": 993, "ssl": True},
                    "search": {"folder": "INBOX", "months_back": 2},
                },
            ],
            "ai": {"provider": "none"},
        })

    def test_config_example_loads_multi_account_samples(self):
        config_path = Path("config.example.json")
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(raw["email_accounts"]), 2)
        self.assertTrue(raw["email_accounts"][0].get("enabled"))
        self.assertEqual(raw["email_accounts"][0]["address"], "your_email@qq.com")
        self.assertFalse(raw["email_accounts"][1].get("enabled"))
        with self.assertRaises(SystemExit) as context:
            load_config(config_path)
        self.assertIn("至少配置一个启用的邮箱账号", str(context.exception))

    def test_load_config_rejects_all_disabled_email_accounts_with_clear_message(self):
        path = self._write_config({
            "email_accounts": [
                {
                    "name": "Disabled",
                    "provider": "qq",
                    "address": "disabled@example.com",
                    "enabled": False,
                },
            ],
            "ai": {"provider": "none"},
        })
        with self.assertRaises(SystemExit) as context:
            load_config(path)
        self.assertIn("至少配置一个启用的邮箱账号", str(context.exception))

    def test_save_config_strips_auth_code(self):
        from scripts.invoice_fetch.config import save_config
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            save_config({
                "email": {"address": "test@qq.com"},
                "auth_code": "my_secret_code",
                "imap": {"server": "imap.qq.com", "port": 993},
                "search": {"months_back": 3},
                "ai": {"provider": "none"}
            }, path=path)

            saved_content = path.read_text(encoding="utf-8")
            self.assertNotIn("my_secret_code", saved_content)
            self.assertNotIn("auth_code", saved_content)

    def test_ai_provider_none_does_not_affect_validation(self):
        validate_config_gui({
            "email": {
                "provider": "qq",
                "address": "user@qq.com"
            },
            "imap": {
                "server": "imap.qq.com",
                "port": 993
            },
            "search": {"months_back": 3},
            "ai": {"provider": "none", "model": ""}
        })

    def test_gmail_preset_fills_server_and_port(self):
        path = self._write_config({
            "email": {
                "provider": "gmail",
                "address": "user@gmail.com"
            },
            "imap": {},
        })
        cfg = load_config(path)
        self.assertEqual(cfg["imap"]["server"], "imap.gmail.com")
        self.assertEqual(cfg["imap"]["port"], 993)

    def test_outlook_preset_fills_server_and_port(self):
        path = self._write_config({
            "email": {
                "provider": "outlook",
                "address": "user@outlook.com"
            },
            "imap": {},
        })
        cfg = load_config(path)
        self.assertEqual(cfg["imap"]["server"], "outlook.office365.com")
        self.assertEqual(cfg["imap"]["port"], 993)

    def test_settings_dialog_saves_sparse_config_without_keyerror(self):
        try:
            from PySide6.QtWidgets import QApplication, QWidget
            import sys
            from unittest.mock import MagicMock, patch

            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.gui.app import SettingsDialog

            parent = QWidget()
            parent.write_log = MagicMock()

            dialog = SettingsDialog(parent)
            dialog.cfg = {} # Sparse config with missing sections

            dialog.txt_email.setText("test@qq.com")
            dialog.txt_auth_code.setText("")
            dialog.txt_months.setText("3")
            dialog._select_provider_card("qq") # QQ
            dialog.combo_ai_provider.setCurrentText("none")
            dialog.txt_ai_model.setCurrentText("")
            dialog.test_success = True

            with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
                 patch("scripts.invoice_fetch.gui.app.QMessageBox.warning") as mock_warn, \
                 patch("scripts.invoice_fetch.gui.app.QMessageBox.information") as mock_info, \
                 patch("scripts.invoice_fetch.gui.app.QMessageBox.question") as mock_quest, \
                 patch("scripts.invoice_fetch.gui.app.QMessageBox.critical") as mock_crit:

                dialog._save_mailbox_settings()

                # Check if there were any warnings or critical errors
                if mock_warn.called:
                    print("Warning called with:", mock_warn.call_args)
                if mock_crit.called:
                    print("Critical called with:", mock_crit.call_args)

                mock_save.assert_called_once()

                self.assertIn("email", dialog.cfg)
                self.assertIn("imap", dialog.cfg)
                self.assertIn("search", dialog.cfg)
                self.assertIn("ai", dialog.cfg)
                self.assertEqual(len(dialog.cfg["email_accounts"]), 1)
                self.assertEqual(dialog.cfg["email_accounts"][0]["address"], "test@qq.com")
                self.assertTrue(dialog.cfg["email_accounts"][0]["enabled"])

            dialog.close()
            dialog.deleteLater()
            app.processEvents()
        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping SettingsDialog GUI test: {e}")
            raise

    def test_settings_dialog_updates_matching_disabled_account_without_removing_others(self):
        try:
            from PySide6.QtWidgets import QApplication, QWidget
            import sys
            from unittest.mock import MagicMock, patch

            app = QApplication.instance() or QApplication(sys.argv)
            from scripts.invoice_fetch.gui.app import SettingsDialog

            parent = QWidget()
            parent.write_log = MagicMock()
            parent.config = {}
            dialog = SettingsDialog(parent)
            dialog.cfg = {
                "email": {"provider": "qq", "address": "old@qq.com"},
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
                "email_accounts": [
                    {
                        "name": "Old disabled",
                        "enabled": False,
                        "provider": "qq",
                        "address": "test@qq.com",
                        "mailbox_key": "test@qq.com",
                    },
                    {
                        "name": "Other account",
                        "enabled": True,
                        "provider": "qq",
                        "address": "other@qq.com",
                        "mailbox_key": "other@qq.com",
                    },
                ],
            }
            dialog.txt_email.setText("test@qq.com")
            dialog.txt_auth_code.setText("")
            dialog.txt_months.setText("6")
            dialog._select_provider_card("qq")
            dialog.combo_ai_provider.setCurrentText("none")
            dialog.test_success = True

            with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
                    patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value={"loaded": True}), \
                    patch("scripts.invoice_fetch.gui.app.QMessageBox.information"), \
                    patch("scripts.invoice_fetch.gui.app.QMessageBox.warning"), \
                    patch("scripts.invoice_fetch.gui.app.QMessageBox.critical"):
                dialog._save_mailbox_settings()

            mock_save.assert_called_once()
            self.assertEqual(len(dialog.cfg["email_accounts"]), 2)
            updated = next(
                account for account in dialog.cfg["email_accounts"]
                if account["address"] == "test@qq.com"
            )
            self.assertTrue(updated["enabled"])
            self.assertEqual(updated["mailbox_key"], "test@qq.com")
            self.assertEqual(updated["search"]["months_back"], 6)
            self.assertTrue(any(
                account["address"] == "other@qq.com"
                for account in dialog.cfg["email_accounts"]
            ))
            self.assertEqual(parent.config, {"loaded": True})

            dialog.close()
            dialog.deleteLater()
            app.processEvents()
        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping SettingsDialog GUI test: {e}")
            raise

    def test_settings_dialog_ai_provider_model_switching_and_custom_save(self):
        try:
            from PySide6.QtWidgets import QApplication, QWidget
            import sys
            from unittest.mock import MagicMock, patch

            app = QApplication.instance() or QApplication(sys.argv)

            from scripts.invoice_fetch.gui.app import SettingsDialog

            parent = QWidget()
            parent.write_log = MagicMock()

            dialog = SettingsDialog(parent)
            dialog.cfg = {
                "email": {"provider": "qq", "address": "tester@example.com"},
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"months_back": 3},
            }

            # 1. Switch to deepseek and verify default model
            dialog.combo_ai_provider.setCurrentText("deepseek")
            self.assertEqual(dialog.txt_ai_model.currentText(), "deepseek-v4-flash")

            # 2. Switch to gemini and verify default model
            dialog.combo_ai_provider.setCurrentText("gemini")
            self.assertEqual(dialog.txt_ai_model.currentText(), "gemini-2.5-flash")

            # 3. Switch to none and verify model/API inputs are inactive
            dialog.combo_ai_provider.setCurrentText("none")
            self.assertEqual(dialog.txt_ai_model.currentText(), "")
            self.assertFalse(dialog.txt_ai_model.isEnabled())
            self.assertFalse(dialog.txt_ai_key.isVisible())

            # 4. Enter a custom model name and save
            dialog.combo_ai_provider.setCurrentText("deepseek")
            dialog.txt_ai_model.setCurrentText("deepseek-custom-model")

            with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
                 patch("scripts.invoice_fetch.gui.app.QMessageBox.information"), \
                 patch("scripts.invoice_fetch.gui.app.QMessageBox.warning") as mock_warning, \
                 patch("scripts.invoice_fetch.gui.app.QMessageBox.critical") as mock_critical:
                dialog._save_ai_settings()
                mock_save.assert_called_once()
                mock_warning.assert_not_called()
                mock_critical.assert_not_called()
                self.assertEqual(dialog.cfg["ai"]["provider"], "deepseek")
                self.assertEqual(dialog.cfg["ai"]["model"], "deepseek-custom-model")

            dialog.close()
            dialog.deleteLater()
            app.processEvents()
        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping SettingsDialog GUI test: {e}")
            raise

    def test_resolve_runtime_dir_default_non_frozen(self):
        from unittest.mock import patch
        import sys
        from scripts.invoice_fetch.config import _resolve_runtime_dir, PROJECT_ROOT

        with patch.dict("os.environ", {}), patch("sys.frozen", False, create=True):
            res = _resolve_runtime_dir()
            self.assertEqual(res, PROJECT_ROOT / "runtime")

    def test_resolve_runtime_dir_override(self):
        from unittest.mock import patch
        import sys
        from scripts.invoice_fetch.config import _resolve_runtime_dir

        custom_path = "D:\\my_custom_runtime"
        with patch.dict("os.environ", {"INVOICE_HUB_RUNTIME_DIR": custom_path}), patch("sys.frozen", False, create=True):
            res = _resolve_runtime_dir()
            self.assertEqual(res, Path(custom_path))

    def test_resolve_runtime_dir_frozen_with_appdata(self):
        from unittest.mock import patch
        import sys
        from scripts.invoice_fetch.config import _resolve_runtime_dir

        with patch.dict("os.environ", {"APPDATA": "C:\\Users\\MockUser\\AppData\\Roaming"}), patch("sys.frozen", True, create=True):
            res = _resolve_runtime_dir()
            self.assertEqual(res, Path("C:\\Users\\MockUser\\AppData\\Roaming") / "InvoiceHub")

    def test_frozen_config_load_and_save_use_runtime_dir(self):
        from unittest.mock import patch
        from scripts.invoice_fetch.config import save_config
        import scripts.invoice_fetch.config as config_mod

        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td) / "runtime"
            runtime_dir.mkdir()
            runtime_cfg = runtime_dir / "config.json"
            runtime_cfg.write_text(json.dumps({
                "email": {"provider": "qq", "address": "frozen@example.com"},
                "imap": {},
            }), encoding="utf-8")

            with patch("sys.frozen", True, create=True), patch.object(config_mod, "RUNTIME_DIR", runtime_dir):
                loaded = load_config()
                self.assertEqual(loaded["email"]["address"], "frozen@example.com")

                save_config({
                    "email": {"provider": "qq", "address": "saved@example.com"},
                    "imap": {},
                })

            saved = json.loads(runtime_cfg.read_text(encoding="utf-8"))
            self.assertEqual(saved["email"]["address"], "saved@example.com")


if __name__ == "__main__":
    unittest.main()
