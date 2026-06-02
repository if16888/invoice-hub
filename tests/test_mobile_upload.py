import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.mobile_upload import (
    ALLOWED_UPLOAD_EXTS,
    MobileUploadServer,
    UploadedFile,
    build_upload_host_options,
)


def _multipart_body(files: list[tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----InvoiceHubTestBoundary"
    chunks: list[bytes] = []
    for filename, content, content_type in files:
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            content,
            b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), boundary


class MobileUploadTests(unittest.TestCase):
    def test_upload_host_options_prioritize_real_lan_and_keep_172_networks(self):
        options = build_upload_host_options([
            ("Docker vEthernet", "172.18.0.1"),
            ("Wi-Fi", "172.20.10.5"),
            ("Ethernet", "192.168.1.9"),
            ("Loopback", "127.0.0.1"),
            ("APIPA", "169.254.1.2"),
            ("WSL", "172.22.64.1"),
        ])

        hosts = [opt.host for opt in options]
        self.assertIn("172.20.10.5", hosts)
        self.assertNotIn("127.0.0.1", hosts)
        self.assertNotIn("169.254.1.2", hosts)
        self.assertEqual(options[0].host, "172.20.10.5")
        self.assertFalse(options[0].is_virtual)
        virtual_hosts = {opt.host for opt in options if opt.is_virtual}
        self.assertIn("172.18.0.1", virtual_hosts)
        self.assertIn("172.22.64.1", virtual_hosts)

    def test_mobile_upload_server_can_switch_public_host_without_rotating_token(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="192.168.1.9", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            old_token = session.token
            updated = server.set_public_host("10.0.0.23")

            self.assertEqual(updated.token, old_token)
            self.assertEqual(updated.host, "10.0.0.23")
            self.assertIn("http://10.0.0.23:", updated.upload_url)
            self.assertEqual(server.status()["upload_url"], updated.upload_url)

    def test_save_uploads_writes_manifest_dedupes_and_imports_supported_files(self):
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td) / "runtime"
            db_path = runtime_dir / "invoices.db"
            server = MobileUploadServer(
                runtime_dir=runtime_dir,
                db_path=db_path,
                host="127.0.0.1",
                port=0,
                import_on_upload=True,
            )
            session = server.start()
            self.addCleanup(server.stop)

            result = server.save_uploads([
                UploadedFile("../invoice.pdf", b"%PDF-1.4\nnot a real invoice", "application/pdf"),
                UploadedFile("payment screenshot.png", b"not really png", "image/png"),
                UploadedFile("invoice-again.pdf", b"%PDF-1.4\nnot a real invoice", "application/pdf"),
            ])

            self.assertEqual(result["accepted"], 2)
            self.assertEqual(result["duplicate"], 1)
            self.assertEqual(result["failed"], 0)
            self.assertGreaterEqual(result["imported"].get("added", 0) + result["imported"].get("failed", 0), 2)

            manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "mobile_qr")
            self.assertEqual(manifest["batch_id"], session.batch_id)
            self.assertEqual(manifest["stats"]["accepted"], 2)
            self.assertEqual(manifest["stats"]["duplicate"], 1)
            stored_names = [Path(item["stored_path"]).name for item in manifest["files"] if item["status"] == "accepted"]
            self.assertIn("invoice.pdf", stored_names)
            self.assertTrue(all(".." not in name and "/" not in name and "\\" not in name for name in stored_names))

            with InvoiceDB(db_path) as db:
                invoices = db.get_all_invoices()
            self.assertGreaterEqual(len(invoices), 2)
            self.assertTrue(all(inv["mail_sender"] == "mobile_qr" for inv in invoices))
            self.assertTrue(all(inv["file_hash"] for inv in invoices))

    def test_duplicate_upload_restores_soft_deleted_file_hash_record(self):
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td) / "runtime"
            db_path = runtime_dir / "invoices.db"
            server = MobileUploadServer(
                runtime_dir=runtime_dir,
                db_path=db_path,
                host="127.0.0.1",
                port=0,
                import_on_upload=True,
            )
            server.start()
            self.addCleanup(server.stop)

            first = server.save_uploads([
                UploadedFile("receipt.pdf", b"%PDF-1.4\nsynthetic receipt", "application/pdf"),
            ])
            self.assertEqual(first["accepted"], 1)

            with InvoiceDB(db_path) as db:
                rows = db.get_all_invoices()
                self.assertEqual(len(rows), 1)
                self.assertTrue(db.soft_delete_invoice(rows[0]["id"]))

            second = server.save_uploads([
                UploadedFile("receipt-again.pdf", b"%PDF-1.4\nsynthetic receipt", "application/pdf"),
            ])

            with InvoiceDB(db_path) as db:
                restored = db.get_all_invoices()

            self.assertEqual(second["accepted"], 0)
            self.assertEqual(second["duplicate"], 1)
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0]["is_deleted"], 0)

    def test_http_upload_page_upload_endpoint_and_invalid_token(self):
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td) / "runtime"
            server = MobileUploadServer(runtime_dir=runtime_dir, host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(session.upload_url, timeout=5) as resp:
                page_html = resp.read().decode("utf-8")
            self.assertIn('type="file"', page_html)
            self.assertIn("multiple", page_html)
            self.assertIn('capture="environment"', page_html)

            body, boundary = _multipart_body([
                ("meal.pdf", b"%PDF-1.4\nfake", "application/pdf"),
                ("receipt.jpg", b"jpg bytes", "image/jpeg"),
            ])
            req = urllib.request.Request(
                session.api_url,
                data=body,
                method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(payload["accepted"], 2)
            self.assertEqual(payload["failed"], 0)

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(session.base_url + "/u/bad-token", timeout=5)
            self.assertEqual(ctx.exception.code, 403)

    def test_batch_upload_accepts_more_than_ten_images(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            files = [
                UploadedFile(f"receipt_{idx}.jpg", f"image bytes {idx}".encode("utf-8"), "image/jpeg")
                for idx in range(12)
            ]

            result = server.save_uploads(files)

            self.assertEqual(result["accepted"], 12)
            self.assertEqual(result["duplicate"], 0)
            manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["stats"]["accepted"], 12)
            self.assertEqual(len([item for item in manifest["files"] if item["status"] == "accepted"]), 12)

    def test_expired_token_rejects_upload(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0, ttl_seconds=-1)
            session = server.start()
            self.addCleanup(server.stop)

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(session.upload_url, timeout=5)
            self.assertEqual(ctx.exception.code, 403)

    # ---------- New tests for three-entry UX, OFD/HEIC, WeChat tip ----------

    def test_allowed_extensions_include_ofd_and_heic(self):
        """OFD (Chinese e-invoice standard) and HEIC (iPhone photos) must be accepted."""
        self.assertIn(".ofd", ALLOWED_UPLOAD_EXTS)
        self.assertIn(".heic", ALLOWED_UPLOAD_EXTS)
        self.assertIn(".pdf", ALLOWED_UPLOAD_EXTS)
        self.assertIn(".jpg", ALLOWED_UPLOAD_EXTS)
        self.assertIn(".jpeg", ALLOWED_UPLOAD_EXTS)
        self.assertIn(".png", ALLOWED_UPLOAD_EXTS)

    def test_ofd_file_upload_accepted(self):
        """OFD invoice files should be accepted and stored."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            server.start()
            self.addCleanup(server.stop)

            result = server.save_uploads([
                UploadedFile("电子发票.ofd", b"OFD file content", "application/octet-stream"),
            ])
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["failed"], 0)

    def test_heic_file_upload_accepted(self):
        """HEIC images from iPhone should be accepted."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            server.start()
            self.addCleanup(server.stop)

            result = server.save_uploads([
                UploadedFile("IMG_1234.HEIC", b"HEIC image data", "image/heic"),
            ])
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["failed"], 0)

    def test_unsupported_file_types_rejected(self):
        """Files with unsupported extensions must be rejected."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            server.start()
            self.addCleanup(server.stop)

            result = server.save_uploads([
                UploadedFile("malware.exe", b"binary content", "application/octet-stream"),
                UploadedFile("doc.docx", b"docx content", "application/vnd.openxmlformats"),
                UploadedFile("archive.zip", b"zip content", "application/zip"),
                UploadedFile("script.js", b"console.log(1)", "text/javascript"),
            ])
            self.assertEqual(result["accepted"], 0)
            self.assertEqual(result["failed"], 4)

    def test_upload_page_has_three_entry_titles(self):
        """The upload page must have three distinct entry titles."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(session.upload_url, timeout=5) as resp:
                page_html = resp.read().decode("utf-8")

            self.assertIn("选择 PDF/OFD/文件", page_html)
            self.assertIn("选择相册图片", page_html)
            self.assertIn("拍照上传", page_html)

    def test_upload_page_has_three_file_inputs_with_correct_accept(self):
        """Three separate file inputs with distinct accept attributes."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(session.upload_url, timeout=5) as resp:
                page_html = resp.read().decode("utf-8")

            # PDF/OFD entry
            self.assertIn('accept=".pdf,.ofd,application/pdf,application/octet-stream"', page_html)
            # Gallery entry
            self.assertIn('accept="image/jpeg,image/png,image/heic,image/*"', page_html)
            # Camera entry
            self.assertIn('capture="environment"', page_html)

    def test_upload_page_has_entry_descriptions(self):
        """Each entry should have a descriptive subtitle."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(session.upload_url, timeout=5) as resp:
                page_html = resp.read().decode("utf-8")

            self.assertIn("适合电子发票、滴滴行程单、酒店水单、下载文件", page_html)
            self.assertIn("适合截图、照片、小票图片", page_html)
            self.assertIn("适合纸质票据、现场小票", page_html)

    def test_upload_page_has_wechat_browser_tip(self):
        """Page must contain WeChat in-app browser detection and tip text."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(session.upload_url, timeout=5) as resp:
                page_html = resp.read().decode("utf-8")

            self.assertIn("MicroMessenger", page_html)
            self.assertIn("在浏览器打开", page_html)
            self.assertIn("wechatTip", page_html)

    def test_upload_page_has_file_list_preview_elements(self):
        """Page must contain file list preview UI elements."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(session.upload_url, timeout=5) as resp:
                page_html = resp.read().decode("utf-8")

            self.assertIn("fileListSection", page_html)
            self.assertIn("清空重选", page_html)
            self.assertIn("开始上传", page_html)

    def test_upload_page_has_usage_tips(self):
        """Page must include practical usage guidance for workers."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(session.upload_url, timeout=5) as resp:
                page_html = resp.read().decode("utf-8")

            self.assertIn("微信聊天", page_html)
            self.assertIn("保存到手机", page_html)
            self.assertIn("同一 Wi-Fi", page_html)
            self.assertIn("Windows 防火墙", page_html)
            self.assertIn("请勿上传与报销无关的私人照片", page_html)
            self.assertIn("ofd", page_html)

    def test_upload_page_supports_ofd_format_in_tips(self):
        """The format list in tips should mention OFD alongside PDF."""
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(runtime_dir=Path(td) / "runtime", host="127.0.0.1", port=0)
            session = server.start()
            self.addCleanup(server.stop)

            with urllib.request.urlopen(session.upload_url, timeout=5) as resp:
                page_html = resp.read().decode("utf-8")

            self.assertIn("pdf、ofd", page_html)

    def test_gui_exposes_mobile_upload_button_and_dialog(self):
        try:
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            from PySide6.QtWidgets import QApplication
            from scripts.invoice_fetch.gui.app import InvoiceReviewApp, MobileUploadDialog
        except Exception as exc:
            self.skipTest(f"PySide6 is not available: {exc}")

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "invoices.db"
            window = InvoiceReviewApp(db_path)
            dialog = None
            try:
                self.assertTrue(hasattr(window, "btn_mobile_upload"))
                self.assertEqual(window.btn_mobile_upload.text(), "📱 扫码上传")

                dialog = MobileUploadDialog(window, db_path)
                self.assertIn("/u/", dialog.txt_url.text())
                self.assertTrue(dialog.btn_stop.isEnabled())
                # Verify WeChat tip is included in the dialog status text
                self.assertIn("微信扫码", dialog.lbl_status.text())
                self.assertIn("在浏览器打开", dialog.lbl_status.text())
                try:
                    import qrcode  # noqa: F401
                    self.assertIsNotNone(dialog.lbl_qr.pixmap())
                    self.assertFalse(dialog.lbl_qr.pixmap().isNull())
                except Exception:
                    self.assertIn("qrcode", dialog.lbl_qr.text())
            finally:
                if dialog is not None:
                    dialog.close()
                window.close()
                app.processEvents()


if __name__ == "__main__":
    unittest.main()
