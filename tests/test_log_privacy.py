import logging
import unittest
from unittest.mock import Mock, patch

from scripts.invoice_fetch.log_privacy import (
    PrivacyLogFilter,
    mask_email,
    mask_filename,
    mask_invoice_number,
    mask_sender_header,
    mask_url_for_log,
    sanitize_log_message,
)


class LogPrivacyTests(unittest.TestCase):
    def test_masks_email_invoice_number_url_amount_and_uid(self):
        text = sanitize_log_message(
            "UID=4050 user alice.smith@example.com url https://example.com/path?token=secret "
            "invoice 26322000003477340276 amount 169.08"
        )

        self.assertIn("a***h@example.com", text)
        self.assertNotIn("alice.smith", text)
        self.assertIn("26***76", text)
        self.assertNotIn("26322000003477340276", text)
        self.assertIn("https://example.com/<redacted:", text)
        self.assertNotIn("token=secret", text)
        self.assertNotIn("169.08", text)
        self.assertIn("UID=uid#", text)

    def test_sanitizes_windows_paths(self):
        text = sanitize_log_message(r"failed path C:\Users\alice\runtime\attachments\invoice_26322000003477340276.pdf")

        self.assertIn("file#", text)
        self.assertNotIn(r"C:\Users\alice", text)
        self.assertNotIn("26322000003477340276", text)

    def test_masks_filename_without_preserving_business_name(self):
        masked = mask_filename("餐饮_169.08_26322000003477340276.pdf")

        self.assertTrue(masked.startswith("file#"))
        self.assertTrue(masked.endswith(".pdf"))
        self.assertNotIn("餐饮", masked)
        self.assertNotIn("26322000003477340276", masked)

    def test_mask_helpers_keep_only_minimal_diagnostics(self):
        self.assertEqual(mask_email("if16888@example.com"), "i***8@example.com")
        self.assertEqual(mask_invoice_number("26322000003477340276"), "26***76")
        self.assertIn("https://example.com/<redacted:", mask_url_for_log("https://example.com/a?b=c"))

    def test_mask_sender_header_extracts_address_before_masking(self):
        self.assertEqual(
            mask_sender_header('"GitHub" <notifications@github.com>'),
            "n***s@github.com",
        )
        self.assertEqual(mask_sender_header("plain@example.com"), "p***n@example.com")
        self.assertEqual(mask_sender_header(""), "")

    def test_privacy_filter_sanitizes_rendered_log_record(self):
        record = logging.LogRecord(
            name="invoice_fetch",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="处理 UID=%d: %s",
            args=(4050, "餐饮管理有限公司电子发票 26322000003477340276 169.08"),
            exc_info=None,
        )

        self.assertTrue(PrivacyLogFilter().filter(record))
        rendered = record.getMessage()
        self.assertIn("UID=uid#", rendered)
        self.assertIn("<subject:redacted>", rendered)
        self.assertNotIn("4050", rendered)
        self.assertNotIn("餐饮管理有限公司", rendered)
        self.assertNotIn("26322000003477340276", rendered)

    def test_gui_write_log_sanitizes_before_file_mirror(self):
        from scripts.invoice_fetch.gui.log_diagnostics_mixin import LogDiagnosticsMixin

        target = Mock()
        with patch("logging.getLogger") as get_logger:
            LogDiagnosticsMixin.write_log(
                target,
                "user@example.com https://example.com/path?token=secret",
            )

        mirrored = get_logger.return_value.log.call_args.args[1]
        self.assertNotIn("user@example.com", mirrored)
        self.assertNotIn("token=secret", mirrored)
        target.txt_log.append.assert_called_once_with(mirrored)

    def test_gui_write_log_can_skip_file_mirror_for_forwarded_messages(self):
        from scripts.invoice_fetch.gui.log_diagnostics_mixin import LogDiagnosticsMixin

        target = Mock()
        with patch("logging.getLogger") as get_logger:
            LogDiagnosticsMixin.write_log(
                target,
                "already logged",
                mirror_to_file=False,
            )

        get_logger.assert_not_called()


if __name__ == "__main__":
    unittest.main()
