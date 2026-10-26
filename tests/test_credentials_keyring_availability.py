# -*- coding: utf-8 -*-
"""Credential-store availability and deletion reporting.

The shipped builds always install ``keyring``, but the import is tolerant so a
broken install does not fail at import time. Every entry point must therefore
report a missing store explicitly, and a failing deletion must be reported to
the caller instead of being swallowed while the UI says "removed".
"""

import unittest
from unittest.mock import patch

from scripts.invoice_fetch import credentials
from scripts.invoice_fetch.credentials import (
    CREDENTIAL_STORE_UNAVAILABLE_MESSAGE,
    CredentialStoreError,
    CredentialStoreUnavailable,
    delete_ai_api_key,
    delete_auth_code,
    get_auth_code,
    has_ai_profile_api_key,
    has_auth_code,
    set_ai_api_key,
    set_auth_code,
)


class _FakeStore:
    """Minimal stand-in for the keyring module."""

    def __init__(self, *, get=None, set=None, delete=None):
        self.get_password = get
        self.set_password = set
        self.delete_password = delete


def _reader_raises(exc: BaseException):
    def _read(*_args):
        raise exc

    return _read


def _writer_raises(exc: BaseException):
    def _write(*_args):
        raise exc

    return _write


def _deleter_raises(exc: BaseException):
    def _delete(*_args):
        raise exc

    return _delete


class KeyringAvailabilityTests(unittest.TestCase):
    def test_missing_store_raises_a_clear_error_instead_of_attribute_error(self):
        with patch.object(credentials, "keyring", None):
            for build in (
                lambda: get_auth_code("user@example.com"),
                lambda: set_auth_code("user@example.com", "code"),
                lambda: set_ai_api_key("gemini", "key"),
                lambda: delete_auth_code("user@example.com"),
            ):
                with self.subTest(call=build):
                    with self.assertRaises(CredentialStoreUnavailable) as ctx:
                        build()
                    self.assertEqual(
                        str(ctx.exception),
                        CREDENTIAL_STORE_UNAVAILABLE_MESSAGE,
                    )
                    self.assertNotIsInstance(ctx.exception, AttributeError)

    def test_status_helpers_stay_graceful_without_a_store(self):
        with patch.object(credentials, "keyring", None):
            self.assertFalse(has_auth_code("user@example.com"))
            self.assertFalse(has_ai_profile_api_key("gemini", "profile-1"))
            # Best-effort delete contract: no raise, the UI refreshes state.
            self.assertIsNone(delete_ai_api_key("gemini"))


class CredentialStoreReportingTests(unittest.TestCase):
    def test_delete_failure_is_reported_and_logged_without_the_backend_message(self):
        store = _FakeStore(
            delete=_deleter_raises(
                RuntimeError("backend detail: account=alice@example.com key=SECRET")
            )
        )
        with patch.object(credentials, "keyring", store):
            with self.assertLogs(
                "scripts.invoice_fetch.credentials", level="WARNING"
            ) as logs:
                with self.assertRaises(CredentialStoreError) as ctx:
                    delete_auth_code("user@example.com")

        self.assertIn("无法从系统凭据管理器删除", str(ctx.exception))
        joined = "\n".join(logs.output)
        self.assertIn("error_type=RuntimeError", joined)
        self.assertNotIn("SECRET", joined)
        self.assertNotIn("alice@example.com", joined)

    def test_delete_of_a_missing_password_is_not_an_error(self):
        class PasswordDeleteError(RuntimeError):
            pass

        store = _FakeStore(delete=_deleter_raises(PasswordDeleteError("not found")))
        with patch.object(credentials, "keyring", store):
            delete_auth_code("user@example.com")

    def test_read_and_write_failures_are_reported_without_raw_messages(self):
        with patch.object(
            credentials,
            "keyring",
            _FakeStore(get=_reader_raises(OSError(r"raw path C:\Users\alice"))),
        ):
            with self.assertRaises(CredentialStoreError) as read_ctx:
                get_auth_code("user@example.com")
        self.assertNotIn("alice", str(read_ctx.exception))

        with patch.object(
            credentials,
            "keyring",
            _FakeStore(set=_writer_raises(OSError("write denied for alice"))),
        ):
            with self.assertRaises(CredentialStoreError) as write_ctx:
                set_auth_code("user@example.com", "code")
            self.assertNotIn("alice", str(write_ctx.exception))

            with self.assertRaises(CredentialStoreError) as ai_ctx:
                set_ai_api_key("gemini", "key")
            self.assertNotIn("alice", str(ai_ctx.exception))

    def test_successful_operations_keep_the_keyring_contract(self):
        calls = []

        def read(service, user):
            calls.append(("get", service, user))
            return "stored-code"

        def write(service, user, value):
            calls.append(("set", service, user, value))

        def delete(service, user):
            calls.append(("delete", service, user))

        store = _FakeStore(get=read, set=write, delete=delete)
        with patch.object(credentials, "keyring", store):
            self.assertEqual(get_auth_code("user@example.com"), "stored-code")
            self.assertTrue(has_auth_code("user@example.com"))
            set_auth_code("user@example.com", "code-456")
            set_ai_api_key("gemini", "ai-key")
            delete_auth_code("user@example.com")

        service = credentials.KEYRING_SERVICE
        self.assertEqual(
            calls,
            [
                ("get", service, "user@example.com"),
                ("get", service, "user@example.com"),
                ("set", service, "user@example.com", "code-456"),
                ("set", "invoice-hub:ai:gemini", "default", "ai-key"),
                ("delete", service, "user@example.com"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
