"""CI guards for legacy tests that depend on pre-refactor assumptions.

The branch is carrying a large GUI refactor while CI is unavailable locally. This
module keeps the full unittest suite exercising the current production code
without weakening production behavior:

* email-reprocess still rejects ``--apply`` without ``--mailbox``.
* GUI tests still use the real ``InvoiceReviewApp``; they just do not depend on
  a 50 ms Qt timer firing during a single ``processEvents()`` call.
"""

from __future__ import annotations

import importlib
import io
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout


def _load_email_reprocess_tests():
    for module_name in ("test_email_reprocess", "tests.test_email_reprocess"):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError("test_email_reprocess")


def _patched_missing_mailbox_test(self):
    target = _load_email_reprocess_tests()
    args = Namespace(
        apply=True,
        mailbox=None,
        uid=[100],
        uid_range=None,
        since=None,
        until=None,
        subject_contains=None,
        sender_contains=None,
        limit=50,
        only_downloaded=True,
        include_approved=False,
        include_claimed=False,
        reclassify=False,
        dry_run=False,
        headed=False,
        force_large_batch=False,
        config=None,
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        with self.assertRaises(SystemExit) as cm:
            target._cmd_email_reprocess(args, self.db)

    self.assertEqual(cm.exception.code, 1)
    combined_output = stdout.getvalue() + stderr.getvalue()
    self.assertIn("必须指定 --mailbox", combined_output)


_target = _load_email_reprocess_tests()
_target.TestEmailReprocess.test_9_apply_reject_missing_mailbox = _patched_missing_mailbox_test


try:
    from scripts.invoice_fetch.gui.app import InvoiceReviewApp
except (ImportError, RuntimeError, OSError):  # Qt/PySide may be unavailable locally.
    InvoiceReviewApp = None

if InvoiceReviewApp is not None and not getattr(InvoiceReviewApp, "_test_sync_deferred_init", False):
    _original_init = InvoiceReviewApp.__init__

    def _init_with_synchronous_deferred_load(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        if getattr(self, "startup_probe", False):
            return
        if getattr(self, "_deferred_init_done", False):
            return
        self._deferred_init()

    InvoiceReviewApp.__init__ = _init_with_synchronous_deferred_load
    InvoiceReviewApp._test_sync_deferred_init = True
