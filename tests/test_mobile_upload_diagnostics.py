import json
import tempfile
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch.mobile_upload import (
    MobileUploadServer,
    UploadedFile,
    build_upload_host_options,
    log_upload_host_candidates,
)


def _multipart_body(filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = "----InvoiceHubDiagnosticsBoundary"
    body = b"".join([
        f"--{boundary}\r\n".encode("ascii"),
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode("utf-8"),
        f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
        content,
        f"\r\n--{boundary}--\r\n".encode("ascii"),
    ])
    return body, boundary


class MobileUploadDiagnosticsTests(unittest.TestCase):
    def test_candidate_diagnostics_are_one_per_option_and_redacted(self):
        options = build_upload_host_options([
            ("Wi-Fi", "192.168.1.22"),
            ("Docker vEthernet", "172.18.0.1"),
        ])
        with self.assertLogs("invoice_fetch.mobile_upload", level="INFO") as captured:
            log_upload_host_candidates(options)
        messages = "\n".join(record.getMessage() for record in captured.records)
        self.assertEqual(messages.count("network candidate"), 2)
        self.assertIn("interface=Wi-Fi", messages)
        self.assertIn("virtual=true", messages)
        self.assertIn("priority=", messages)
        self.assertNotIn("192.168.1.22", messages)

    def test_server_start_self_check_and_http_access_logs_are_safe(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="127.0.0.1",
                port=0,
                interface_name="Wi-Fi",
                network_priority=0,
            )
            with self.assertLogs("invoice_fetch.mobile_upload", level="INFO") as captured:
                session = server.start()
                self.assertTrue(server.run_local_self_check())
                with urllib.request.urlopen(session.upload_url, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                with self.assertRaises(urllib.error.HTTPError) as invalid:
                    urllib.request.urlopen(session.base_url + "/u/not-the-token", timeout=5)
                self.assertEqual(invalid.exception.code, 403)
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(session.base_url + "/not-found", timeout=5)
                self.assertEqual(missing.exception.code, 404)
                body, boundary = _multipart_body("receipt.pdf", b"%PDF-1.4 synthetic", "application/pdf")
                request = urllib.request.Request(
                    session.api_url,
                    data=body,
                    method="POST",
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(json.loads(response.read().decode("utf-8"))["accepted"], 1)
                server.stop()

            messages = "\n".join(record.getMessage() for record in captured.records)
            self.assertNotIn(session.token, messages)
            self.assertIn("selected network", messages)
            self.assertIn("server started", messages)
            self.assertIn("qr generated", messages)
            self.assertIn("local self-check result=pass", messages)
            self.assertIn("method=GET", messages)
            self.assertIn("method=POST", messages)
            self.assertIn("path=/u/<redacted> status=200", messages)
            self.assertIn("path=/u/<redacted> status=403", messages)
            self.assertIn("path=/not-found status=404", messages)
            self.assertIn("path=/api/upload/<redacted> status=200", messages)
            self.assertIn("server stop", messages)

    def test_vendored_pdfjs_assets_are_served_locally_and_path_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="127.0.0.1",
                port=0,
            )
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(
                session.base_url + "/assets/pdfjs/pdf.min.mjs", timeout=5
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "text/javascript")
                self.assertIn(b"Mozilla Foundation", response.read(4096))

            with urllib.request.urlopen(
                session.base_url + "/assets/pdfjs/pdf.worker.min.mjs", timeout=5
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "text/javascript")

            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(
                    session.base_url + "/assets/pdfjs/../mobile_upload.py", timeout=5
                )
            self.assertEqual(missing.exception.code, 404)

    def test_local_self_check_does_not_confirm_lan_client(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)
            self.assertTrue(server.run_local_self_check())
            status = server.status()
            self.assertFalse(status["lan_client_access_confirmed"])
            self.assertFalse(status["last_lan_client_access_at"])
            self.assertNotIn("phone_access_confirmed", status)

    def test_selected_and_other_local_interface_gets_do_not_confirm_lan_client(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="192.168.1.50",
                port=0,
                local_host_addresses={"192.168.1.50", "10.0.0.20"},
            )
            session = server.start()
            self.addCleanup(server.stop)

            for client in ("192.168.1.50", "10.0.0.20"):
                server._record_request("GET", f"/u/{session.token}", client, 200)
                self.assertFalse(server.status()["lan_client_access_confirmed"])

            self.assertFalse(server.status()["last_lan_client_access_at"])

    def test_external_valid_get_confirms_lan_client_and_uses_safe_log(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="192.168.1.50",
                port=0,
                local_host_addresses={"192.168.1.50", "10.0.0.20"},
            )
            session = server.start()
            self.addCleanup(server.stop)

            with self.assertLogs("invoice_fetch.mobile_upload", level="INFO") as captured:
                server._record_request("GET", f"/u/{session.token}", "192.168.1.80", 200)
            status = server.status()
            self.assertTrue(status["lan_client_access_confirmed"])
            self.assertTrue(status["last_lan_client_access_at"])
            messages = "\n".join(record.getMessage() for record in captured.records)
            self.assertNotIn(session.token, messages)
            self.assertIn("LAN client access confirmed", messages)
            self.assertNotIn("phone_access_confirmed", messages)

    def test_invalid_get_and_post_do_not_confirm_lan_client(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="192.168.1.50",
                port=0,
                local_host_addresses={"192.168.1.50"},
            )
            session = server.start()
            self.addCleanup(server.stop)

            with self.assertLogs("invoice_fetch.mobile_upload", level="INFO") as captured:
                server._record_request("GET", "/u/not-the-token", "192.168.1.80", 200)
                server._record_request("GET", "/u/not-the-token", "192.168.1.80", 403)
                server._record_request("POST", f"/api/upload/{session.token}", "192.168.1.80", 200)

            status = server.status()
            self.assertFalse(status["lan_client_access_confirmed"])
            self.assertFalse(status["last_lan_client_access_at"])
            messages = "\n".join(record.getMessage() for record in captured.records)
            self.assertIn("method=GET", messages)
            self.assertIn("status=403", messages)
            self.assertIn("method=POST", messages)
            self.assertNotIn("LAN client access confirmed", messages)

    def test_request_status_updates_are_synchronized(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="192.168.1.50",
                port=0,
                local_host_addresses={"192.168.1.50", "10.0.0.20"},
            )
            session = server.start()
            self.addCleanup(server.stop)

            clients = ["192.168.1.50", "10.0.0.20", "192.168.1.80"] * 8
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(
                    lambda client: server._record_request(
                        "GET", f"/u/{session.token}", client, 200,
                    ),
                    clients,
                ))

            status = server.status()
            self.assertTrue(status["lan_client_access_confirmed"])
            self.assertTrue(status["last_request_at"])
            self.assertTrue(status["last_lan_client_access_at"])

    def test_expiry_network_change_and_stop_are_observable(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="127.0.0.1",
                port=0,
                ttl_seconds=-1,
            )
            with self.assertLogs("invoice_fetch.mobile_upload", level="INFO") as captured:
                session = server.start()
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(session.upload_url, timeout=5)
                server.set_public_host("192.168.1.21")
                server.stop()
            messages = "\n".join(record.getMessage() for record in captured.records)
            self.assertNotIn(session.token, messages)
            self.assertIn("session expired", messages)
            self.assertIn("network changed", messages)
            self.assertIn("server stop", messages)
            self.assertEqual(server.status()["bind_host"], "0.0.0.0")

    def test_start_failure_reports_exception_type_without_token(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            with patch(
                "scripts.invoice_fetch.mobile_upload.ThreadingHTTPServer",
                side_effect=OSError("synthetic port unavailable"),
            ):
                with self.assertLogs("invoice_fetch.mobile_upload", level="INFO") as captured:
                    with self.assertRaises(OSError):
                        server.start()
            messages = "\n".join(record.getMessage() for record in captured.records)
            self.assertIn("server start failed", messages)
            self.assertIn("exception_type=OSError", messages)
            self.assertIn("synthetic port unavailable", messages)

    def test_status_preserves_bind_host_and_network_state(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="192.168.1.50",
                port=0,
                interface_name="WLAN",
                network_priority=0,
                network_virtual=False,
            )
            session = server.start()
            self.addCleanup(server.stop)
            status = server.status()
            self.assertEqual(status["bind_host"], "0.0.0.0")
            self.assertEqual(status["interface_name"], "WLAN")
            self.assertEqual(status["public_host"], "192.168.1.50")
            self.assertEqual(status["local_self_check"], "pending")
            self.assertIn("http://192.168.1.50:", session.upload_url)


if __name__ == "__main__":
    unittest.main()
