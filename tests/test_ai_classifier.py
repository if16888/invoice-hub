import logging
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.invoice_fetch.ai_classifier import (
    AIAuthError,
    AIClassifier,
    is_provider_session_paused,
    pause_provider_session,
    clear_provider_session_paused,
    clear_all_session_paused,
)


class AIClassifierAuthTests(unittest.TestCase):
    @staticmethod
    def _classifier(batch_size=1):
        classifier = object.__new__(AIClassifier)
        classifier.provider = "deepseek"
        classifier.model = "deepseek-chat"
        classifier.batch_size = batch_size
        classifier.api_key = "synthetic-secret-key"
        classifier.auth_failed = False
        return classifier

    def test_chat_provider_destination_matches_selected_credential_and_model(self):
        emails = [{"uid": 1, "subject": "Private project 发票", "sender": "private@example.invalid"}]
        for provider, endpoint, model in (
            ("openai", "https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
            ("deepseek", "https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
        ):
            with self.subTest(provider=provider):
                key = f"synthetic-{provider}-key"
                with patch("scripts.invoice_fetch.ai_classifier.get_ai_api_key", return_value=key) as credentials:
                    classifier = AIClassifier(provider=provider, profile_id="synthetic-profile")
                credentials.assert_called_once_with(provider, profile_id="synthetic-profile")
                response = Mock()
                response.json.return_value = {"choices": [{"message": {"content": '[{"uid":1,"is_invoice":null}]'}}]}
                with patch.object(classifier, "_post_with_retry", return_value=response) as post:
                    result = classifier._call_api(emails)
                self.assertIsNone(result[0]["is_invoice"])
                self.assertEqual(post.call_args.args, (endpoint,))
                request = post.call_args.kwargs
                self.assertEqual(request["headers"]["Authorization"], f"Bearer {key}")
                self.assertEqual(request["json"]["model"], model)
                message = request["json"]["messages"][1]["content"]
                self.assertIn("发票", message)
                self.assertNotIn("Private project", message)
                self.assertNotIn("example.invalid", message)

    def test_gemini_keeps_its_own_transport(self):
        classifier = self._classifier()
        classifier.provider = "gemini"
        emails = [{"uid": 1}]
        with patch.object(classifier, "_call_gemini", return_value=[]) as gemini, patch.object(classifier, "_call_chat_completions") as chat:
            self.assertEqual(classifier._call_api(emails), [])
        gemini.assert_called_once_with(emails)
        chat.assert_not_called()

    def test_disabled_or_unknown_provider_never_posts(self):
        for provider in ("none", "unknown"):
            with self.subTest(provider=provider):
                classifier = self._classifier()
                classifier.provider = provider
                with patch.object(classifier, "_post_with_retry") as post:
                    result = classifier._call_api([{"uid": 1}])
                post.assert_not_called()
                self.assertIsNone(result[0]["is_invoice"])

    def test_deepseek_401_does_not_retry(self):
        response = Mock(status_code=401)
        error = requests.HTTPError("contains synthetic-secret-key", response=response)
        classifier = self._classifier()

        with patch(
            "scripts.invoice_fetch.ai_classifier.requests.post",
            side_effect=error,
        ) as post, patch("scripts.invoice_fetch.ai_classifier.time.sleep") as sleep:
            with self.assertRaises(AIAuthError):
                classifier._post_with_retry("https://example.invalid?key=synthetic-secret-key")

        post.assert_called_once()
        sleep.assert_not_called()

    def test_auth_failure_stops_later_batches(self):
        classifier = self._classifier(batch_size=1)
        emails = [
            {"uid": 1, "subject": "one", "sender": "one@example.com"},
            {"uid": 2, "subject": "two", "sender": "two@example.com"},
        ]

        with patch.object(
            classifier,
            "_call_api",
            side_effect=AIAuthError("deepseek", "deepseek-chat", 401),
        ) as call_api:
            results = classifier.classify_batch(emails)

        call_api.assert_called_once()
        self.assertTrue(classifier.auth_failed)
        self.assertEqual([item["uid"] for item in results], [1, 2])
        self.assertTrue(all(item["is_invoice"] is None for item in results))
        self.assertTrue(all("AI 鉴权失败" in item["reason"] for item in results))

    def test_server_error_still_retries_once_without_logging_api_key(self):
        response = Mock(status_code=500)
        error = requests.HTTPError("synthetic-secret-key", response=response)
        classifier = self._classifier()

        with patch(
            "scripts.invoice_fetch.ai_classifier.requests.post",
            side_effect=error,
        ) as post, patch("scripts.invoice_fetch.ai_classifier.time.sleep"), self.assertLogs(
            "scripts.invoice_fetch.ai_classifier",
            level=logging.WARNING,
        ) as captured:
            with self.assertRaises(requests.HTTPError):
                classifier._post_with_retry(
                    "https://example.invalid?key=synthetic-secret-key"
                )

        self.assertEqual(post.call_count, 2)
        self.assertNotIn("synthetic-secret-key", "\n".join(captured.output))

    def test_session_paused_state_persists_across_instances(self):
        # Ensure starts clean
        clear_all_session_paused()
        self.assertFalse(is_provider_session_paused("deepseek"))

        # Setup classifier to raise auth error
        classifier = self._classifier(batch_size=1)
        emails = [{"uid": 1, "subject": "test", "sender": "test@example.com"}]

        with patch.object(
            classifier,
            "_call_api",
            side_effect=AIAuthError("deepseek", "deepseek-chat", 401),
        ):
            results = classifier.classify_batch(emails)

        self.assertTrue(classifier.auth_failed)
        self.assertTrue(is_provider_session_paused("deepseek"))

        # Create a new classifier instance for same provider
        classifier2 = self._classifier(batch_size=1)
        # Mock _call_api to ensure it's NOT called
        with patch.object(classifier2, "_call_api") as mock_call:
            results2 = classifier2.classify_batch(emails)
            mock_call.assert_not_called()

        self.assertEqual(results2[0]["is_invoice"], None)
        self.assertIn("AI 鉴权失败", results2[0]["reason"])

        # Now clear it and verify it calls the API again
        clear_provider_session_paused("deepseek")
        self.assertFalse(is_provider_session_paused("deepseek"))

        with patch.object(classifier2, "_call_api", return_value=[{"uid": 1, "is_invoice": True, "reason": "ok"}]):
            results3 = classifier2.classify_batch(emails)
            self.assertEqual(results3[0]["is_invoice"], True)

    def test_run_classify_respects_session_pause_state(self):
        from scripts.invoice_fetch.services import _run_classify
        from scripts.invoice_fetch.db import InvoiceDB

        clear_all_session_paused()
        pause_provider_session("deepseek")

        db = Mock(spec=InvoiceDB)
        db.get_unclassified_emails.return_value = [{"uid": 1, "subject": "test", "sender": "test@example.com"}]
        db.is_trusted_sender.return_value = False

        ai_cfg = {"provider": "deepseek", "model": "deepseek-chat"}

        with patch("scripts.invoice_fetch.services._log") as mock_log:
            res = _run_classify(db, ai_cfg, no_ai=False, mailbox_key="test")
            self.assertEqual(res["auth_failed"], True)
            self.assertEqual(res["pending_classification"], 1)
            mock_log.warning.assert_any_call("AI 已因鉴权失败暂停，请检查 API Key。")

        clear_all_session_paused()


if __name__ == "__main__":
    unittest.main()
