"""Regression tests: untrusted names are Windows-safe in every managed path.

Windows rejects reserved device names (``CON``, ``NUL``, ``COM1``…), control
characters, and names whose stem matches a device. Mail attachment names,
downloaded ``Content-Disposition`` names, phone-upload names, and claim export
directory names must all stay writable.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.invoice_fetch.attachment_handler import build_managed_attachment_name
from scripts.invoice_fetch.claim_export import _sanitize_dirname
from scripts.invoice_fetch.filename_safety import (
    escape_windows_reserved_stem,
    sanitize_windows_basename,
)
from scripts.invoice_fetch.link_downloader import _safe_download_destination
from scripts.invoice_fetch.mobile_upload import _safe_upload_name
from scripts.invoice_fetch.services import _safe_local_import_name


class WindowsReservedNameTests(unittest.TestCase):
    def test_reserved_device_names_are_escaped_including_extensions(self):
        for raw in ("CON", "con", "NUL", "AUX", "PRN", "COM1", "lpt9"):
            self.assertTrue(
                sanitize_windows_basename(raw, fallback="").startswith("_"),
                raw,
            )
            self.assertTrue(
                sanitize_windows_basename(f"{raw}.pdf", fallback="").startswith("_"),
                raw,
            )

    def test_reserved_stem_check_uses_the_part_before_the_first_dot(self):
        self.assertEqual(escape_windows_reserved_stem("CON.final.pdf"), "_CON.final.pdf")
        self.assertEqual(escape_windows_reserved_stem("CONSOLE.pdf"), "CONSOLE.pdf")
        self.assertEqual(escape_windows_reserved_stem("report.pdf"), "report.pdf")

    def test_control_characters_are_replaced(self):
        self.assertEqual(sanitize_windows_basename("a\x00b\tc.pdf"), "a_b_c.pdf")
        self.assertEqual(sanitize_windows_basename("invoice\x1f.pdf"), "invoice_.pdf")

    def test_blank_and_dot_names_fall_back(self):
        self.assertEqual(sanitize_windows_basename("", fallback="untitled"), "untitled")
        self.assertEqual(sanitize_windows_basename("..", fallback="untitled"), "untitled")
        self.assertEqual(sanitize_windows_basename("report. ", fallback="untitled"), "report")


class ManagedAttachmentNameTests(unittest.TestCase):
    def test_reserved_source_name_stays_creatable(self):
        name = build_managed_attachment_name(original_name="CON.pdf", invoice_date="2026-01-02")
        self.assertEqual(name, "2026-01-02__CON.pdf")

    def test_control_characters_in_source_name_are_replaced(self):
        name = build_managed_attachment_name(original_name="bad\x01name.pdf", invoice_date="2026-01-02")
        self.assertEqual(name, "2026-01-02_bad_name.pdf")

    def test_reserved_category_field_is_escaped(self):
        name = build_managed_attachment_name(
            original_name="x.pdf",
            invoice_date="2026-01-02",
            category="CON",
            total_amount="10.00",
            invoice_number="123",
            role="原件",
        )
        self.assertEqual(name, "2026-01-02__CON_10.00_123_原件.pdf")


class DownloadDestinationTests(unittest.TestCase):
    def test_reserved_suggested_name_is_escaped(self):
        dest = _safe_download_destination("downloads", "CON.pdf", "fallback.pdf")
        self.assertEqual(dest.name, "_CON.pdf")

    def test_control_characters_and_traversal_are_neutralized(self):
        dest = _safe_download_destination("downloads", "..\\nested/bad\x00name.pdf", "fallback.pdf")
        self.assertEqual(dest.name, "bad_name.pdf")
        self.assertEqual(dest.parent.name, "downloads")

    def test_empty_name_uses_fallback_even_if_reserved(self):
        dest = _safe_download_destination("downloads", "", "NUL")
        self.assertEqual(dest.name, "_NUL")


class UploadAndStagingNameTests(unittest.TestCase):
    def test_upload_reserved_name_is_escaped(self):
        self.assertEqual(_safe_upload_name("CON.pdf"), "_CON.pdf")
        self.assertEqual(_safe_upload_name("nul"), "_nul")

    def test_upload_control_characters_are_replaced(self):
        self.assertEqual(_safe_upload_name("a\x01b.pdf"), "a_b.pdf")

    def test_local_staging_reserved_name_is_escaped(self):
        self.assertEqual(_safe_local_import_name(Path("CON.pdf")), "_CON.pdf")
        self.assertEqual(_safe_local_import_name(Path("a\x01b.pdf")), "a_b.pdf")


class ClaimExportDirnameTests(unittest.TestCase):
    def test_reserved_directory_name_is_escaped(self):
        self.assertEqual(_sanitize_dirname("CON"), "_CON")
        self.assertEqual(_sanitize_dirname("nul"), "_nul")

    def test_control_characters_are_replaced(self):
        self.assertEqual(_sanitize_dirname("a\x01b"), "a_b")


if __name__ == "__main__":
    unittest.main()
