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

    def test_production_upload_page_contracts(self):
        """Check the complete static page contract from one real HTTP response."""
        page = self._page()
        token_groups = {
            "file confirmation": (
                "fileKind", "formatBytes", "displayFileName", "file-card", "file-preview",
                "pdf-thumb", "图片预览", "file-detail", "移除", "清空重选", "待上传 · 0", "查看 PDF",
            ),
            "mobile-first source actions": (
                "添加材料", "选择文件", "相册", "拍照", "选择 PDF/OFD/文件", "选择相册图片",
                "拍照上传", 'aria-label="选择 PDF/OFD/文件"', 'aria-label="选择相册图片"',
                'aria-label="拍照上传"', "entry-icon", "min-height:54px", "min-height:44px",
            ),
            "file inputs": (
                'accept=".pdf,.ofd,application/pdf,application/octet-stream"',
                'accept="image/jpeg,image/png,image/heic,image/*"', 'capture="environment"',
            ),
            "review and sticky upload": (
                "pendingSection", "fileListItems", "file-card", "previewModal", "activePreviewIndex",
                "navigatePreview", "文件 ", "页 ", "上一项", "下一项", "touchstart", "touchend",
                "SWIPE_THRESHOLD_PX", "uploadBar", "btnUpload", "safe-area-inset-bottom",
                "overflow-wrap:anywhere", "-webkit-line-clamp:2", 'name.setAttribute("aria-label", fullName)',
                "待上传 · ", "已选 ", "上传",
            ),
            "local PDF preview": (
                'const PDFJS_BASE = "/assets/pdfjs/"', 'import(PDFJS_BASE + "pdf.min.mjs")',
                'pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_BASE + "pdf.worker.min.mjs"', "getDocument({",
                "record.pdfDocument.numPages", "record.pdfDocument.getPage(1)", "PREVIEWING",
                "无法预览，但仍可移除/重新选择。", "当前第 ", "visualViewport",
                "文件仍保留在手机本地", "fetch(UPLOAD_URL", "const PDF_RENDER_DPR_CAP = 3",
                "const PDF_RENDER_DPR_FLOOR = 2", "scale: cssScale * dpr", 'toDataURL("image/jpeg", .92)',
                ".preview-stage canvas[hidden]",
            ),
            "WeChat guidance": (
                "MicroMessenger", "在浏览器打开", "wechatTip", "微信聊天", "保存到手机", "同一 Wi-Fi",
                "Windows 防火墙", "请勿上传与报销无关的私人照片",
            ),
            "OFD guidance": ("ofd", "OFD", "手机浏览器暂不支持内容预览"),
            "responsive width contract": (
                "@media (max-width:360px)", "width=device-width", "initial-scale=1", "viewport-fit=cover",
                "entry-icon", "overflow-x:hidden", "grid-template-columns:repeat(3,minmax(0,1fr))",
            ),
            "in-page upload feedback": ("result-success", "result-error", "response.ok"),
        }
        for contract, tokens in token_groups.items():
            with self.subTest(contract=contract):
                for token in tokens:
                    self.assertIn(token, page)

        state_tokens = ("EMPTY", "SELECTED", "PREVIEWING", "UPLOADING", "SUCCESS", "PARTIAL", "FAILURE")
        with self.subTest(contract="selection and upload state machine"):
            for state in state_tokens:
                self.assertIn(state, page)
            self.assertIn('setState("UPLOADING")', page)
            self.assertIn('setState(failed > 0 ? "PARTIAL" : "SUCCESS")', page)
            self.assertIn('setState("FAILURE")', page)

        with self.subTest(contract="must not expose contradictory or external preview behavior"):
            for token in ("尚未选择文件", "https://", "http://", "user-scalable=no", "maximum-scale=1", "批次 mobile_", "alert("):
                self.assertNotIn(token, page)
            for icon in ("📄", "🖼️", "📷", "💡", "✅", "🔁", "❌"):
                self.assertNotIn(icon, page)
            self.assertIn("可使用浏览器/系统手势放大", page)
            self.assertRegex(page, r"链接约 \d+ 分钟后失效")

        with self.subTest(contract="upload remains an explicit user action"):
            self.assertLess(
                page.index('btnUpload.addEventListener("click"'),
                page.index("fetch(UPLOAD_URL"),
            )


if __name__ == "__main__":
    unittest.main()
