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
            "displayFileName",
            "file-card",
            "file-preview",
            "pdf-thumb",
            "图片预览",
            "file-detail",
            "移除",
            "清空重选",
            "待上传 · 0",
            "查看 PDF",
        ):
            self.assertIn(token, page)
        self.assertIn(".pdf,.ofd,application/pdf,application/octet-stream", page)
        self.assertIn("image/jpeg,image/png,image/heic,image/*", page)
        self.assertNotIn("尚未选择文件", page)

    def test_mobile_first_selection_review_and_upload_contract(self):
        page = self._page()
        for token in (
            "添加材料",
            "选择文件",
            "相册",
            "拍照",
            "pendingSection",
            "previewModal",
            "uploadBar",
            "safe-area-inset-bottom",
            "min-height:44px",
            "overflow-wrap:anywhere",
            "-webkit-line-clamp:2",
            "name.setAttribute(\"aria-label\", fullName)",
            "待上传 · ",
            "已选 ",
        ):
            self.assertIn(token, page)

        for state in ("EMPTY", "SELECTED", "PREVIEWING", "UPLOADING", "SUCCESS", "PARTIAL", "FAILURE"):
            self.assertIn(state, page)
        self.assertIn('setState("UPLOADING")', page)
        self.assertIn('setState(failed > 0 ? "PARTIAL" : "SUCCESS")', page)
        self.assertIn('setState("FAILURE")', page)

    def test_pdf_preview_is_local_and_upload_is_explicit(self):
        page = self._page()
        for token in (
            'const PDFJS_BASE = "/assets/pdfjs/"',
            'import(PDFJS_BASE + "pdf.min.mjs")',
            'pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_BASE + "pdf.worker.min.mjs"',
            "getDocument({",
            "record.pdfDocument.numPages",
            "record.pdfDocument.getPage(1)",
            "PREVIEWING",
            "无法预览，但仍可移除/重新选择。",
            "fetch(UPLOAD_URL",
        ):
            self.assertIn(token, page)
        self.assertNotIn("https://", page)
        self.assertNotIn("http://", page)
        self.assertLess(
            page.index('btnUpload.addEventListener("click"'),
            page.index("fetch(UPLOAD_URL"),
        )

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
        self.assertIn("@media (max-width:360px)", page)
        self.assertIn("width=device-width", page)
        self.assertIn("user-scalable=no", page)
        self.assertIn("entry-icon", page)
        self.assertIn("overflow-x:hidden", page)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", page)


if __name__ == "__main__":
    unittest.main()
