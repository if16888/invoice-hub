import io
import logging
import unittest
from unittest.mock import Mock, patch

from scripts.invoice_fetch.log_privacy import (
    PrivacyLogFilter,
    attach_privacy_filter,
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

    def test_sanitizes_relative_attachment_business_filename(self):
        text = sanitize_log_message(
            "保存 attachments/2026-06-14/2026-06-14_餐饮_169.08_26322000003477340276_原件.pdf"
        )

        self.assertIn("file#", text)
        self.assertNotIn("餐饮", text)
        self.assertNotIn("169.08", text)
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

    def test_exception_sanitization(self):
        exc = Exception("Connection failed to user@example.com with token=secret")
        sanitized = sanitize_log_message(str(exc))
        self.assertNotIn("user@example.com", sanitized)
        self.assertIn("u***r@example.com", sanitized)

    # ── Batch 3: credentials, tracebacks and handler-level coverage ─────

    def test_bearer_and_secret_tokens_are_masked(self):
        text = sanitize_log_message(
            "request failed Authorization: Bearer gho_AbCdEf123456 api_key=sk-live-9876 "
            "access_token=ya29.abcdefgh"
        )

        self.assertNotIn("gho_AbCdEf123456", text)
        self.assertIn("<token:redacted>", text)
        self.assertNotIn("sk-live-9876", text)
        self.assertNotIn("ya29.abcdefgh", text)
        self.assertIn("<secret:redacted>", text)

    def test_jwt_and_long_blob_are_masked(self):
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        blob = "A" * 80

        text = sanitize_log_message(f"header {jwt} payload {blob}")

        self.assertNotIn(jwt, text)
        self.assertIn("<jwt:redacted>", text)
        self.assertNotIn(blob, text)
        self.assertIn("<blob:redacted:", text)

    def test_labelled_eight_digit_invoice_number_is_masked_but_date_survives(self):
        text = sanitize_log_message("发票号码 12345678 开票日期 20261024")

        self.assertNotIn("12345678", text)
        self.assertIn("12***78", text)
        self.assertIn("20261024", text)

    def test_privacy_filter_sanitizes_exception_traceback(self):
        import sys

        try:
            raise RuntimeError("failed for user@example.com with token=secret")
        except RuntimeError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="invoice_fetch.db",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="邮箱扫描状态已清空",
            args=(),
            exc_info=exc_info,
        )

        self.assertTrue(PrivacyLogFilter().filter(record))

        self.assertIsNone(record.exc_info)
        self.assertIn("u***r@example.com", record.exc_text)
        self.assertNotIn("user@example.com", record.exc_text)
        self.assertNotIn("token=secret", record.exc_text)

    def test_handler_level_filter_covers_an_unrelated_logger(self):
        stream = io.StringIO()
        handler = attach_privacy_filter(logging.StreamHandler(stream))
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("synthetic_third_party.module")
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            logger.warning("download failed for alice@example.com token=abcd1234")
        finally:
            logger.removeHandler(handler)
            handler.close()
            logger.propagate = True

        output = stream.getvalue()
        self.assertNotIn("alice@example.com", output)
        self.assertNotIn("abcd1234", output)

    def test_setup_logging_installs_the_filter_on_every_root_handler(self):
        import tempfile
        from pathlib import Path

        from scripts.invoice_fetch import __main__ as cli

        root = logging.getLogger()
        before = list(root.handlers)
        added = []
        with tempfile.TemporaryDirectory() as td:
            with patch.object(cli, "RUNTIME_DIR", Path(td)):
                cli._setup_logging(verbose=False)
            added = [handler for handler in root.handlers if handler not in before]
            try:
                self.assertTrue(added, "日志初始化必须安装 handler")
                for handler in added:
                    self.assertTrue(
                        any(isinstance(f, PrivacyLogFilter) for f in handler.filters),
                        f"{type(handler).__name__} 缺少隐私过滤器",
                    )
            finally:
                # Close the file handler before the temporary directory is
                # removed, otherwise Windows keeps the log file locked.
                for handler in added:
                    root.removeHandler(handler)
                    handler.close()


if __name__ == "__main__":
    unittest.main()
