"""Opt-in browser smoke for the mobile upload page.

The normal pytest suite keeps this test skipped because CI machines do not
necessarily have a browser runtime.  Run it explicitly with
``INVOICE_HUB_RUN_BROWSER_SMOKE=1`` on a Windows machine with Chromium when
validating the real browser-side PDF.js and file-selection flow.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.mobile_upload import MobileUploadServer

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - optional browser dependency
    sync_playwright = None


def _synthetic_pdf(page_count: int = 2) -> bytes:
    """Build a small valid PDF without adding a fixture artifact."""
    page_count = max(1, int(page_count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
    ]
    font_number = 3 + page_count * 2
    page_numbers = []
    for page_index in range(page_count):
        page_number = 3 + page_index * 2
        content_number = page_number + 1
        page_numbers.append(page_number)
        content = f"BT /F1 20 Tf 50 150 Td (Invoice Hub {page_index + 1}) Tj ET\n".encode("ascii")
        objects.extend([
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
                f"/Contents {content_number} 0 R /Resources << /Font << /F1 {font_number} 0 R >> >> >>"
            ).encode("ascii"),
            b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream",
        ])
    objects[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{number} 0 R' for number in page_numbers)}] "
        f"/Count {page_count} >>"
    ).encode("ascii")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode("ascii"))
        result.extend(payload)
        result.extend(b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(result)


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@unittest.skipUnless(
    os.environ.get("INVOICE_HUB_RUN_BROWSER_SMOKE") == "1" and sync_playwright,
    "set INVOICE_HUB_RUN_BROWSER_SMOKE=1 with a Chromium runtime to run browser smoke",
)
class MobileUploadBrowserSmokeTests(unittest.TestCase):
    @staticmethod
    def _dispatch_touch(page, start, end):
        page.evaluate(
            """([start, end]) => {
                const stage = document.querySelector("#previewStage");
                const emit = (type, touches, changedTouches) => {
                    const event = new Event(type, { bubbles: true, cancelable: true });
                    Object.defineProperty(event, "touches", { value: touches });
                    Object.defineProperty(event, "changedTouches", { value: changedTouches });
                    stage.dispatchEvent(event);
                };
                const point = ([x, y]) => ({ clientX: x, clientY: y });
                emit("touchstart", [point(start)], []);
                emit("touchend", [], [point(end)]);
            }""",
            [list(start), list(end)],
        )

    def test_local_pdf_review_and_upload_flow_has_no_early_post(self):
        executable = Path(
            os.environ.get(
                "INVOICE_HUB_BROWSER_EXECUTABLE",
                r"C:\Users\gawk\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe",
            )
        )
        if not executable.exists():
            self.skipTest(f"Chromium executable not found: {executable}")

        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="127.0.0.1",
                port=0,
            )
            session = server.start()
            self.addCleanup(server.stop)
            post_requests: list[str] = []

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=str(executable),
                )
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                page.on(
                    "request",
                    lambda request: post_requests.append(request.url)
                    if request.method == "POST"
                    else None,
                )
                try:
                    page.goto(session.upload_url, wait_until="networkidle")
                    self.assertEqual(page.locator("body").get_attribute("data-upload-state"), "EMPTY")
                    self.assertTrue(page.locator("#result").is_hidden())

                    page.set_input_files(
                        "#inputFile",
                        {
                            "name": "超长发票号码-20260822-北京分公司-住宿服务-000000000000000000000000.pdf",
                            "mimeType": "application/pdf",
                            "buffer": _synthetic_pdf(),
                        },
                    )
                    page.locator("#pendingTitle").wait_for(state="visible")
                    page.locator(".pdf-thumb").wait_for(state="visible")
                    self.assertEqual(page.locator("#pendingTitle").inner_text(), "待上传 · 1")
                    self.assertIn("PDF · 2 页", page.locator(".file-detail").inner_text())
                    displayed_name = page.locator(".file-name").inner_text()
                    self.assertTrue(displayed_name.endswith(".pdf"))
                    self.assertLessEqual(len(displayed_name), 36)
                    self.assertEqual(
                        page.locator(".file-name").get_attribute("title"),
                        "超长发票号码-20260822-北京分公司-住宿服务-000000000000000000000000.pdf",
                    )
                    self.assertTrue(page.locator("#btnUpload").is_enabled())
                    self.assertEqual(post_requests, [])

                    page.locator(".review-button").click()
                    page.locator("#previewModal").wait_for(state="visible")
                    page.locator("#previewCanvas").wait_for(state="visible")
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 1/1 · 页 1/2")
                    page.locator("#previewNext").click()
                    page.wait_for_function(
                        "() => document.querySelector('#previewPageIndicator').textContent === "
                        + json.dumps("文件 1/1 · 页 2/2", ensure_ascii=False),
                    )
                    page.locator("#previewCanvas").wait_for(state="visible")
                    page.locator("#previewPrev").click()
                    page.wait_for_function(
                        "() => document.querySelector('#previewPageIndicator').textContent === "
                        + json.dumps("文件 1/1 · 页 1/2", ensure_ascii=False),
                    )
                    page.locator("#previewCanvas").wait_for(state="visible")
                    page.locator("#previewBack").click()

                    page.locator("#btnUpload").click()
                    page.locator("#result.result-success").wait_for(state="visible")
                    self.assertEqual(len(post_requests), 1)
                    self.assertEqual(page.locator("body").get_attribute("data-upload-state"), "SUCCESS")
                finally:
                    context.close()
                    browser.close()

    def test_multi_file_preview_navigates_pages_files_and_returns_without_post(self):
        executable = Path(
            os.environ.get(
                "INVOICE_HUB_BROWSER_EXECUTABLE",
                r"C:\Users\gawk\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe",
            )
        )
        if not executable.exists():
            self.skipTest(f"Chromium executable not found: {executable}")

        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="127.0.0.1",
                port=0,
            )
            session = server.start()
            self.addCleanup(server.stop)
            post_requests: list[str] = []

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                page.on(
                    "request",
                    lambda request: post_requests.append(request.url)
                    if request.method == "POST"
                    else None,
                )
                try:
                    page.goto(session.upload_url, wait_until="networkidle")
                    page.set_input_files(
                        "#inputFile",
                        [
                            {"name": "A.pdf", "mimeType": "application/pdf", "buffer": _synthetic_pdf(3)},
                            {"name": "B.pdf", "mimeType": "application/pdf", "buffer": _synthetic_pdf(2)},
                            {"name": "C.pdf", "mimeType": "application/pdf", "buffer": _synthetic_pdf(1)},
                        ],
                    )
                    page.locator(".pdf-thumb").nth(2).wait_for(state="visible")
                    self.assertEqual(page.locator(".file-card").count(), 3)

                    def expect_position(value):
                        page.wait_for_function(
                            "() => document.querySelector('#previewPageIndicator').textContent === "
                            + json.dumps(value, ensure_ascii=False),
                        )

                    page.locator(".review-button").nth(0).click()
                    page.locator("#previewCanvas").wait_for(state="visible")
                    expect_position("文件 1/3 · 页 1/3")
                    self.assertIn("当前第 1 个文件，共 3 个文件；第 1 页，共 3 页", page.locator("#previewPageIndicator").get_attribute("aria-label"))

                    page.locator("#previewNext").click()
                    expect_position("文件 1/3 · 页 2/3")
                    page.locator("#previewNext").click()
                    expect_position("文件 1/3 · 页 3/3")
                    page.locator("#previewNext").click()
                    expect_position("文件 2/3 · 页 1/2")
                    self.assertEqual(page.locator("#previewTitle").inner_text(), "B.pdf")
                    page.locator("#previewNext").click()
                    expect_position("文件 2/3 · 页 2/2")
                    page.locator("#previewNext").click()
                    expect_position("文件 3/3 · 页 1/1")
                    self.assertTrue(page.locator("#previewNext").is_disabled())

                    page.locator("#previewPrev").click()
                    expect_position("文件 2/3 · 页 2/2")
                    page.locator("#previewPrev").click()
                    expect_position("文件 2/3 · 页 1/2")
                    page.locator("#previewPrev").click()
                    expect_position("文件 1/3 · 页 3/3")
                    page.locator("#previewPrev").click()
                    expect_position("文件 1/3 · 页 2/3")
                    page.locator("#previewPrev").click()
                    expect_position("文件 1/3 · 页 1/3")
                    self.assertTrue(page.locator("#previewPrev").is_disabled())

                    page.locator("#previewBack").click()
                    self.assertEqual(page.locator(".file-card").count(), 3)
                    self.assertEqual(page.locator("body").get_attribute("data-upload-state"), "SELECTED")
                    page.locator(".review-button").nth(1).click()
                    expect_position("文件 2/3 · 页 1/2")
                    self.assertEqual(page.locator("#previewTitle").inner_text(), "B.pdf")
                    self.assertEqual(post_requests, [])
                finally:
                    context.close()
                    browser.close()

    def test_preview_swipe_contract_respects_direction_threshold_and_zoom(self):
        executable = Path(
            os.environ.get(
                "INVOICE_HUB_BROWSER_EXECUTABLE",
                r"C:\Users\gawk\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe",
            )
        )
        if not executable.exists():
            self.skipTest(f"Chromium executable not found: {executable}")

        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="127.0.0.1",
                port=0,
            )
            session = server.start()
            self.addCleanup(server.stop)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(executable))
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                try:
                    page.goto(session.upload_url, wait_until="networkidle")
                    page.set_input_files(
                        "#inputFile",
                        [
                            {"name": "A.pdf", "mimeType": "application/pdf", "buffer": _synthetic_pdf(1)},
                            {"name": "B.pdf", "mimeType": "application/pdf", "buffer": _synthetic_pdf(1)},
                            {"name": "C.pdf", "mimeType": "application/pdf", "buffer": _synthetic_pdf(1)},
                        ],
                    )
                    page.locator(".pdf-thumb").nth(2).wait_for(state="visible")
                    page.locator(".review-button").nth(0).click()
                    page.locator("#previewCanvas").wait_for(state="visible")
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 1/3 · 页 1/1")

                    self._dispatch_touch(page, (220, 220), (190, 300))
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 1/3 · 页 1/1")
                    self._dispatch_touch(page, (220, 220), (175, 222))
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 1/3 · 页 1/1")
                    self._dispatch_touch(page, (220, 220), (140, 223))
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 2/3 · 页 1/1")
                    self._dispatch_touch(page, (140, 220), (230, 223))
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 1/3 · 页 1/1")
                    page.locator("#previewCanvas").wait_for(state="visible")

                    page.evaluate(
                        """() => {
                            const canvas = document.querySelector('#previewCanvas');
                            canvas.style.setProperty('max-width', 'none', 'important');
                            canvas.style.setProperty('width', '1000px', 'important');
                            canvas.style.setProperty('flex', '0 0 auto', 'important');
                        }"""
                    )
                    page.wait_for_function(
                        "() => document.querySelector('#previewCanvas').getBoundingClientRect().width "
                        "> document.querySelector('#previewStage').clientWidth + 4"
                    )
                    self._dispatch_touch(page, (220, 220), (130, 223))
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 1/3 · 页 1/1")
                finally:
                    context.close()
                    browser.close()

    def test_mobile_widths_do_not_introduce_horizontal_scroll(self):
        executable = Path(
            os.environ.get(
                "INVOICE_HUB_BROWSER_EXECUTABLE",
                r"C:\Users\gawk\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe",
            )
        )
        if not executable.exists():
            self.skipTest(f"Chromium executable not found: {executable}")

        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="127.0.0.1",
                port=0,
            )
            session = server.start()
            self.addCleanup(server.stop)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=str(executable),
                )
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                try:
                    for width, height in (
                        (320, 568),
                        (360, 800),
                        (375, 812),
                        (390, 844),
                        (412, 915),
                        (430, 932),
                    ):
                        page.set_viewport_size({"width": width, "height": height})
                        page.goto(session.upload_url, wait_until="domcontentloaded")
                        self.assertLessEqual(
                            page.evaluate("document.documentElement.scrollWidth"),
                            page.evaluate("document.documentElement.clientWidth") + 1,
                            f"horizontal overflow at {width}x{height}",
                        )
                        self.assertEqual(page.locator(".source-action").count(), 3)
                        self.assertTrue(
                            all(
                                (page.locator(".source-action").nth(index).bounding_box() or {}).get("height", 0) >= 44
                                for index in range(3)
                            )
                        )
                finally:
                    context.close()
                    browser.close()

    def test_image_mixed_broken_pdf_camera_and_clear_flows(self):
        executable = Path(
            os.environ.get(
                "INVOICE_HUB_BROWSER_EXECUTABLE",
                r"C:\Users\gawk\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe",
            )
        )
        if not executable.exists():
            self.skipTest(f"Chromium executable not found: {executable}")

        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                host="127.0.0.1",
                port=0,
            )
            session = server.start()
            self.addCleanup(server.stop)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=str(executable),
                )
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                try:
                    page.goto(session.upload_url, wait_until="networkidle")
                    page.set_input_files(
                        "#inputFile",
                        [
                            {"name": "two-pages.pdf", "mimeType": "application/pdf", "buffer": _synthetic_pdf(2)},
                            {"name": "receipt.ofd", "mimeType": "application/octet-stream", "buffer": b"OFD synthetic"},
                        ],
                    )
                    page.set_input_files(
                        "#inputGallery",
                        {"name": "receipt.png", "mimeType": "image/png", "buffer": _ONE_PIXEL_PNG},
                    )
                    page.locator(".pdf-thumb").wait_for(state="visible")
                    self.assertEqual(page.locator(".file-card").count(), 3)
                    self.assertEqual(page.locator('[data-file-kind="PDF"]').count(), 1)
                    self.assertEqual(page.locator('[data-file-kind="OFD"]').count(), 1)
                    self.assertEqual(page.locator('[data-file-kind="图片"]').count(), 1)
                    self.assertTrue(page.locator('[data-file-kind="OFD"] .file-preview').is_disabled())
                    self.assertIn("手机浏览器暂不支持内容预览", page.locator('[data-file-kind="OFD"]').inner_text())

                    page.locator('[data-file-kind="PDF"] .review-button').click()
                    page.locator("#previewCanvas").wait_for(state="visible")
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 1/3 · 页 1/2")
                    page.locator("#previewNext").click()
                    page.wait_for_function(
                        "() => document.querySelector('#previewPageIndicator').textContent === "
                        + json.dumps("文件 1/3 · 页 2/2", ensure_ascii=False),
                    )
                    page.locator("#previewNext").click()
                    page.wait_for_function(
                        "() => document.querySelector('#previewPageIndicator').textContent === "
                        + json.dumps("文件 2/3 · 页 1/1", ensure_ascii=False),
                    )
                    self.assertIn("手机浏览器暂不支持内容预览", page.locator("#previewError").inner_text())
                    page.locator("#previewNext").click()
                    page.locator("#previewImage").wait_for(state="visible")
                    self.assertEqual(page.locator("#previewPageIndicator").inner_text(), "文件 3/3 · 页 1/1")
                    page.locator("#previewBack").click()

                    page.locator('[data-file-kind="图片"] .review-button').click()
                    page.locator("#previewImage").wait_for(state="visible")
                    self.assertEqual(page.locator("body").get_attribute("data-upload-state"), "PREVIEWING")
                    page.locator("#previewBack").click()
                    self.assertEqual(page.locator("body").get_attribute("data-upload-state"), "SELECTED")

                    page.locator(".remove-button").nth(1).click()
                    self.assertEqual(page.locator(".file-card").count(), 2)
                    page.locator("#btnClear").click()
                    self.assertTrue(page.locator("#pendingSection").is_hidden())
                    self.assertEqual(page.locator("body").get_attribute("data-upload-state"), "EMPTY")
                    self.assertTrue(page.locator("#result").is_hidden())

                    page.set_input_files(
                        "#inputCamera",
                        {"name": "camera.jpg", "mimeType": "image/jpeg", "buffer": _ONE_PIXEL_PNG},
                    )
                    page.locator('[data-file-kind="图片"] .file-preview').wait_for(state="visible")
                    page.locator('[data-file-kind="图片"] .review-button').click()
                    page.locator("#previewImage").wait_for(state="visible")
                    page.locator("#previewBack").click()
                    page.locator(".remove-button").click()
                    self.assertEqual(page.locator("body").get_attribute("data-upload-state"), "EMPTY")

                    page.set_input_files(
                        "#inputFile",
                        {"name": "broken.pdf", "mimeType": "application/pdf", "buffer": b"not a pdf"},
                    )
                    page.locator(".file-preview-error").wait_for(state="visible")
                    self.assertTrue(page.locator("#btnUpload").is_disabled())
                    self.assertIn("无法预览", page.locator("#selectionHint").inner_text())
                finally:
                    context.close()
                    browser.close()


if __name__ == "__main__":
    unittest.main()
