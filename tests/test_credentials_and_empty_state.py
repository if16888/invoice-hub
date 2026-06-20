import unittest
from unittest.mock import MagicMock, patch, call
import os
import sys

from scripts.invoice_fetch.credentials import (
    set_ai_api_key,
    get_ai_api_key,
    has_ai_api_key,
    has_ai_profile_api_key,
    get_ai_api_key_source,
    delete_ai_api_key,
)


class CredentialsAndEmptyStateTests(unittest.TestCase):
    @patch("keyring.get_password")
    @patch("keyring.set_password")
    def test_ai_key_keyring_read_write(self, mock_set, mock_get):
        # Setup mocks
        mock_get.return_value = "fake-api-key"

        # Test writing
        set_ai_api_key("deepseek", "fake-api-key")
        mock_set.assert_called_with("invoice-hub:ai:deepseek", "default", "fake-api-key")

        # Test checking presence
        present = has_ai_api_key("deepseek")
        self.assertTrue(present)
        mock_get.assert_called_with("invoice-hub:ai:deepseek", "default")

        # Test reading
        val = get_ai_api_key("deepseek")
        self.assertEqual(val, "fake-api-key")

    @patch("keyring.get_password")
    @patch("keyring.delete_password")
    def test_ai_key_keyring_delete(self, mock_delete, mock_get):
        # Test delete
        delete_ai_api_key("gemini")
        mock_delete.assert_called_with("invoice-hub:ai:gemini", "default")

    @patch("keyring.get_password")
    def test_ai_key_fallback_to_env(self, mock_get):
        # If keyring fails/returns None, it should fall back to the env var
        mock_get.return_value = None

        with patch.dict(os.environ, {"GEMINI_API_KEY": "env-gemini-key"}):
            key = get_ai_api_key("gemini")
            self.assertEqual(key, "env-gemini-key")


class AIProfileCredentialTests(unittest.TestCase):
    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_ai_profile_keys_use_different_services(self, mock_keyring):
        set_ai_api_key("deepseek", "key-one", profile_id="ai-one")
        set_ai_api_key("gemini", "key-two", profile_id="ai-two")
        services = [call.args[0] for call in mock_keyring.set_password.call_args_list]
        self.assertEqual(
            services,
            ["invoice-hub:ai-profile:ai-one:deepseek", "invoice-hub:ai-profile:ai-two:gemini"],
        )

    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_profile_specific_key_check_is_strict(self, mock_keyring):
        mock_keyring.get_password.side_effect = lambda service, username: {
            "invoice-hub:ai-profile:ai-one:deepseek": "profile-key",
            "invoice-hub:ai:deepseek": "legacy-key",
        }.get(service)

        self.assertTrue(has_ai_profile_api_key("deepseek", profile_id="ai-one"))
        self.assertFalse(has_ai_profile_api_key("gemini", profile_id="ai-one"))

    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_ai_api_key_source_reports_profile_provider_env_and_missing(self, mock_keyring):
        cases = [
            ("profile", {"invoice-hub:ai-profile:ai-one:deepseek": "profile-key"}, {}, "deepseek", "ai-one"),
            ("provider", {"invoice-hub:ai:deepseek": "legacy-key"}, {}, "deepseek", "ai-one"),
            ("env", {}, {"GEMINI_API_KEY": "env-gemini-key"}, "gemini", "ai-one"),
            ("missing", {}, {}, "gemini", "ai-one"),
        ]

        for expected, keyring_values, env_values, provider, profile_id in cases:
            with self.subTest(expected=expected):
                mock_keyring.get_password.side_effect = lambda service, username, values=keyring_values: values.get(service)
                with patch.dict(os.environ, env_values, clear=True):
                    self.assertEqual(get_ai_api_key_source(provider, profile_id=profile_id), expected)
                mock_keyring.get_password.reset_mock()

    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_profile_key_falls_back_to_legacy_provider_key(self, mock_keyring):
        mock_keyring.get_password.side_effect = [None, "legacy-key"]
        self.assertEqual(
            get_ai_api_key("deepseek", profile_id="ai-one"), "legacy-key"
        )
        self.assertEqual(
            mock_keyring.get_password.call_args_list[1].args[0],
            "invoice-hub:ai:deepseek",
        )

    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_profile_key_does_not_reuse_across_providers(self, mock_keyring):
        mock_keyring.get_password.side_effect = lambda service, username: {
            "invoice-hub:ai-profile:ai-one:deepseek": "deepseek-key",
        }.get(service)

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                get_ai_api_key("gemini", profile_id="ai-one")

        self.assertEqual(
            [call.args[0] for call in mock_keyring.get_password.call_args_list],
            ["invoice-hub:ai-profile:ai-one:gemini", "invoice-hub:ai:gemini"],
        )

    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_delete_profile_key_does_not_delete_legacy_key(self, mock_keyring):
        delete_ai_api_key("deepseek", profile_id="ai-one")
        mock_keyring.delete_password.assert_called_once_with(
            "invoice-hub:ai-profile:ai-one:deepseek", "default"
        )


if __name__ == "__main__":
    unittest.main()
