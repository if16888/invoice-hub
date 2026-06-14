import logging
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.invoice_fetch.ai_classifier import AIAuthError, AIClassifier


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


if __name__ == "__main__":
    unittest.main()
