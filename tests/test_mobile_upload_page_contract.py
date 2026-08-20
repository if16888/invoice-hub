import tempfile
import unittest
import urllib.request
from pathlib import Path

from scripts.invoice_fetch.mobile_upload import MobileUploadServer


class MobileUploadPageContractTests(unittest.TestCase):
    def _page(self) -> str:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        server = MobileUploadServer(
            runtime_dir=Path(self.tempdir.name) / "runtime",
            host="127.0.0.1",
            port=0,
        )
        session = server.start()
        self.addCleanup(server.stop)
        with urllib.request.urlopen(session.upload_url, timeout=5) as response:
            return response.read().decode("utf-8")

    def test_file_confirmation_contains_type_size_thumbnail_and_remove_contract(self):
        page = self._page()
        for token in (
            "fileKind",
            "formatBytes",
            "file-thumb",
            "图片预览",
            "file-detail",
            "移除",
            "清空重选",
            "可多选上传",
        ):
            self.assertIn(token, page)
        self.assertIn(".pdf,.ofd,application/pdf,application/octet-stream", page)
        self.assertIn("image/jpeg,image/png,image/heic,image/*", page)

    def test_upload_feedback_is_in_page_and_no_emoji_or_alert(self):
        page = self._page()
        self.assertIn("result-success", page)
        self.assertIn("result-error", page)
        self.assertIn("response.ok", page)
        self.assertNotIn("alert(", page)
        for icon in ("📄", "🖼️", "📷", "💡", "✅", "🔁", "❌"):
            self.assertNotIn(icon, page)

    def test_mobile_width_contract_is_present(self):
        page = self._page()
        self.assertIn("@media (max-width: 360px)", page)
        self.assertIn("width=device-width", page)
        self.assertIn("user-scalable=no", page)
        self.assertIn("entry-icon", page)


if __name__ == "__main__":
    unittest.main()
