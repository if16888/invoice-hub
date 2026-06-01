import unittest
from unittest.mock import MagicMock, patch
import os
import sys

from scripts.invoice_fetch.credentials import (
    set_ai_api_key,
    get_ai_api_key,
    has_ai_api_key,
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


if __name__ == "__main__":
    unittest.main()
