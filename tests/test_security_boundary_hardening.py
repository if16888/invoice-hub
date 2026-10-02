"""Synthetic regression coverage for network and OS security boundaries."""

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.invoice_fetch.ai_classifier import AIClassifier
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.mobile_upload import MobileUploadServer
from scripts.invoice_fetch.windows_paths import windows_system_executable


class SecurityBoundaryHardeningTests(unittest.TestCase):
    def test_ai_transport_has_default_timeout_even_when_none_is_supplied(self):
        classifier = object.__new__(AIClassifier)
        for options in ({}, {"timeout": None}, {"timeout": (5, 20)}):
            with self.subTest(options=options), patch(
                "scripts.invoice_fetch.ai_classifier.requests.post", return_value=Mock()
            ) as post:
                classifier._post_with_retry("https://example.invalid", **options)
                self.assertEqual(post.call_args.kwargs["timeout"], options.get("timeout") or 60)

    def test_ai_transport_rejects_unbounded_timeout_before_network_access(self):
        classifier = object.__new__(AIClassifier)
        for timeout in (0, -1, 61, True, float("inf"), float("nan"), (5, None), (), (5,)):
            with self.subTest(timeout=timeout), patch(
                "scripts.invoice_fetch.ai_classifier.requests.post"
            ) as post:
                with self.assertRaises(ValueError):
                    classifier._post_with_retry("https://example.invalid", timeout=timeout)
                post.assert_not_called()

    def test_dynamic_sql_binds_values_and_rejects_untrusted_columns(self):
        with tempfile.TemporaryDirectory() as td:
            db = InvoiceDB(Path(td) / "synthetic.db")
            try:
                value = "synthetic'); DROP TABLE invoices; --"
                invoice_id = db.insert_invoice({
                    "seller_name": value,
                    "invoice_number": "SYNTHETIC-001",
                    "total_amount": "1.00",
                    "untrusted_column); DROP TABLE invoices; --": "ignored",
                })
                self.assertIsNotNone(invoice_id)
                self.assertEqual(db.get_invoice(invoice_id)["seller_name"], value)
                self.assertFalse(db.is_duplicate(value, "1.00"))
                result = db.update_invoice_missing_fields(
                    invoice_id, {"seller_name = NULL; --": "ignored"}
                )
                self.assertEqual(result["updated_fields"], [])
                self.assertEqual(db.count_invoices(), 1)
            finally:
                db.close()

    def test_credential_backend_failure_is_visible_without_leaking_details(self):
        from scripts.invoice_fetch.credentials import delete_ai_api_key

        with patch("scripts.invoice_fetch.credentials.keyring.delete_password", side_effect=RuntimeError("synthetic-private-key")), self.assertLogs(
            "scripts.invoice_fetch.credentials", level="WARNING"
        ) as captured:
            delete_ai_api_key("deepseek")
        self.assertIn("RuntimeError", " ".join(captured.output))
        self.assertNotIn("synthetic-private-key", " ".join(captured.output))

    def test_self_check_uses_listener_not_session_url_or_proxy(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(host="127.0.0.1", bind_host="127.0.0.1", port=0, runtime_dir=Path(td))
            try:
                server.start()
                server.session = replace(server.session, upload_url="file:///synthetic-secret")
                with patch.dict(os.environ, {
                    "HTTP_PROXY": "http://127.0.0.1:1",
                    "HTTPS_PROXY": "http://127.0.0.1:1",
                    "NO_PROXY": "",
                }):
                    self.assertTrue(server.run_local_self_check())
                self.assertTrue(server.is_token_valid(server.session.token))
                self.assertFalse(server.is_token_valid("错" * len(server.session.token)))
                self.assertFalse(server.is_token_valid(None))
            finally:
                server.stop()

    def test_self_check_does_not_follow_redirects(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(host="127.0.0.1", bind_host="127.0.0.1", port=0, runtime_dir=Path(td))
            try:
                server.start()
                connection = Mock()
                connection.getresponse.return_value.status = 302
                with patch("scripts.invoice_fetch.mobile_upload.HTTPConnection", return_value=connection):
                    self.assertFalse(server.run_local_self_check())
                connection.request.assert_called_once()
                connection.close.assert_called_once()
                self.assertEqual(server._local_self_check_error, "http_302")
            finally:
                server.stop()

    @unittest.skipUnless(os.name == "nt", "Windows system executable resolution")
    def test_windows_program_resolution_ignores_path_and_windir(self):
        expected = windows_system_executable("explorer.exe")
        with patch.dict(os.environ, {"PATH": "C:/synthetic-untrusted", "WINDIR": "C:/synthetic-untrusted"}):
            self.assertEqual(windows_system_executable("explorer.exe"), expected)
        self.assertTrue(Path(expected).is_absolute())
        for invalid in ("../explorer.exe", "C:/synthetic/explorer.exe"):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                windows_system_executable(invalid)


if __name__ == "__main__":
    unittest.main()
