import email
import unittest
from datetime import datetime

from scripts.invoice_fetch.mail_fetcher import MailFetcher


class _FakeIMAP:
    def __init__(self, select_total=b"1", search_ids=b"1"):
        self.calls = []
        self._select_total = select_total
        self._search_ids = search_ids

    def select(self, folder, readonly=True):
        self.calls.append(("select", folder, readonly))
        return "OK", [self._select_total]

    def search(self, charset, *criteria):
        self.calls.append(("search", charset, criteria))
        return "OK", [self._search_ids]

    def fetch(self, mid, query):
        self.calls.append(("fetch", mid, query))
        uid = int(mid)
        day = "18" if uid == 1 else "19"
        date_line = f"{day}-May-2026 10:00:00 +0800"
        header_bytes = (
            f"Subject: Invoice {uid}\r\n"
            f"From: Billing <billing@example.com>\r\n"
            f"Date: {'Mon' if uid == 1 else 'Tue'}, {day} May 2026 10:00:00 +0800\r\n\r\n"
        ).encode("utf-8")
        if query == "(UID INTERNALDATE)":
            return "OK", [
                (
                    f'{uid} (UID {uid} INTERNALDATE "{date_line}")'.encode("utf-8"),
                    b"",
                )
            ]
        if query == "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])":
            return "OK", [
                (
                    f'{uid} (UID {uid} INTERNALDATE "{date_line}")'.encode("utf-8"),
                    header_bytes,
                )
            ]
        if query == "(RFC822)":
            raw = (
                f"Subject: Invoice {uid}\r\n".encode("utf-8")
                + b"From: Billing <billing@example.com>\r\n"
                + f"Date: {'Mon' if uid == 1 else 'Tue'}, {day} May 2026 10:00:00 +0800\r\n".encode("utf-8")
                + f"Message-ID: <msg-{uid}@example.com>\r\n\r\nBody".encode("utf-8")
            )
            return "OK", [(f"{uid} (RFC822 {{123}})".encode("utf-8"), raw)]
        if query == "(RFC822 INTERNALDATE)":
            raw = (
                f"Subject: Invoice {uid}\r\n".encode("utf-8")
                + b"From: Billing <billing@example.com>\r\n"
                + f"Date: {'Mon' if uid == 1 else 'Tue'}, {day} May 2026 10:00:00 +0800\r\n".encode("utf-8")
                + f"Message-ID: <msg-{uid}@example.com>\r\n\r\nBody".encode("utf-8")
            )
            return "OK", [
                (
                    f'{uid} (UID {uid} INTERNALDATE "{date_line}")'.encode("utf-8"),
                    raw,
                )
            ]
        raise AssertionError(f"unexpected fetch query: {query}")

    def uid(self, command, uid, query):
        self.calls.append(("uid", command, uid, query))
        if command == "FETCH" and query == "(RFC822)" and uid == "7":
            raw = (
                b"Subject: Invoice 7\r\n"
                b"From: Billing <billing@example.com>\r\n"
                b"Date: Mon, 18 May 2026 10:00:00 +0800\r\n"
                b"Message-ID: <msg-7@example.com>\r\n\r\nBody"
            )
            return "OK", [(b"7 (RFC822 {123})", raw)]
        raise AssertionError(f"unexpected uid call: {(command, uid, query)}")

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b"logout"]


class MailFetcherImapSemanticsTests(unittest.TestCase):
    def test_fetch_emails_uses_uid_lightweight_scan_before_full_fetch(self):
        fetcher = MailFetcher("user@example.com", "secret")
        fake = _FakeIMAP(select_total=b"1", search_ids=b"1")
        fetcher._conn = fake

        messages = fetcher.fetch_emails(folder="INBOX", months_back=3, since_date="2026-05-01")

        self.assertEqual(len(messages), 1)
        self.assertEqual(
            fake.calls[:4],
            [
                ("select", "INBOX", True),
                ("search", None, ("SINCE", "01-May-2026")),
                ("fetch", b"1", "(UID INTERNALDATE)"),
                ("fetch", b"1", "(RFC822)"),
            ],
        )

    def test_scan_headers_keeps_lightweight_header_fetch_and_known_uid_skip(self):
        fetcher = MailFetcher("user@example.com", "secret")
        fake = _FakeIMAP(select_total=b"2", search_ids=b"2 1")
        fetcher._conn = fake

        headers = fetcher.scan_headers(
            folder="INBOX",
            months_back=3,
            since_date="2026-05-01",
            known_uids={1},
        )

        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0]["uid"], 2)
        self.assertEqual(headers[0]["subject"], "Invoice 2")
        self.assertEqual(
            fake.calls[:4],
            [
                ("select", "INBOX", True),
                ("search", None, ("SINCE", "01-May-2026")),
                ("fetch", b"1", "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])"),
                ("fetch", b"2", "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])"),
            ],
        )

    def test_fetch_by_uid_uses_uid_fetch(self):
        fetcher = MailFetcher("user@example.com", "secret")
        fake = _FakeIMAP()
        fetcher._conn = fake

        message = fetcher.fetch_by_uid(7, folder="INBOX")

        self.assertIsNotNone(message)
        self.assertEqual(message.uid, 7)
        self.assertEqual(
            fake.calls[:2],
            [
                ("select", "INBOX", True),
                ("uid", "FETCH", "7", "(RFC822)"),
            ],
        )

    def test_internal_helpers_remain_available_for_uid_and_date_parsing(self):
        meta = '2 (UID 2 INTERNALDATE "19-May-2026 10:00:00 +0800")'

        self.assertEqual(MailFetcher._parse_uid(meta), 2)
        self.assertEqual(MailFetcher._meta_bytes([(meta.encode("utf-8"), b"")]), meta)
        self.assertEqual(MailFetcher._parse_internaldate(meta), datetime(2026, 5, 19))

    def test_railway_and_high_speed_train_subjects_are_relevant(self):
        from scripts.invoice_fetch.mail_fetcher import (
            EXCLUDE_KEYWORDS,
            RELEVANCE_KEYWORDS,
            MailMessage,
            _email_looks_relevant,
        )

        msg = MailMessage(
            9,
            email.message_from_string(
                "Subject: 12306 高铁电子客票\n"
                "From: Railway Service <service@12306.cn>\n"
                "Date: Tue, 19 May 2026 10:00:00 +0800\n\n"
            ),
        )
        self.assertFalse(any("??" in keyword for keyword in RELEVANCE_KEYWORDS))
        self.assertFalse(any("??" in keyword for keyword in EXCLUDE_KEYWORDS))
        self.assertIn("高铁", RELEVANCE_KEYWORDS)
        self.assertIn("电子客票", RELEVANCE_KEYWORDS)
        self.assertTrue(_email_looks_relevant(msg))


if __name__ == "__main__":
    unittest.main()
