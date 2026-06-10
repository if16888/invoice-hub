"""CI guard for email-reprocess CLI argument validation tests.

The legacy email reprocess tests use MagicMock namespaces. A bare MagicMock can
make omitted argparse attributes truthy and can also print the expected
"missing mailbox" validation message into the full CI log. This module is
imported before ``test_email_reprocess`` during unittest discovery and replaces
that one legacy test with an explicit argparse.Namespace version.

This is intentionally narrow: it does not weaken production validation. The
production command must still raise SystemExit(1) when ``--apply`` is used
without ``--mailbox``.
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
