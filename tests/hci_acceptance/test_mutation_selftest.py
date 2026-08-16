"""Mutation Sanity Self-Test for HCI Acceptance Oracle.

Verifies that the test harness and oracles are sensitive to bugs and do NOT
"always PASS". Intentionally injects mutations (e.g. stale progress text,
broken DB counts) and asserts that the corresponding scenarios correctly FAIL.
"""

from __future__ import annotations

try:
    import pytest
except ImportError:
    import unittest
    raise unittest.SkipTest("HCI acceptance harness requires pytest or scripts/dev/run_hci_acceptance.py")

from scripts.invoice_fetch.gui import hci_v1
from tests.hci_acceptance.scenarios import run_cr_02, run_cr_03, run_rv_02


class TestOracleMutationSanity:
    """Validate that the harness oracles fail when invariants are broken."""

    def test_stale_progress_mutation_causes_cr02_failure(
        self, review_window, qapp, monkeypatch
    ):
        """Injecting a stale progress string must cause CR-02 to FAIL."""
        monkeypatch.setattr(
            hci_v1,
            "_review_progress_text",
            lambda window: "1 / 5 · 当前还剩 5 张待审核",
        )

        result = run_cr_02(review_window, review_window.db, qapp)
        assert not result.passed, "CR-02 should FAIL when progress text is stale"
        assert result.broken_invariant is not None
        assert "progress" in result.broken_invariant.lower()

    def test_stale_progress_mutation_causes_cr03_failure(
        self, review_window, qapp, monkeypatch
    ):
        """Injecting a stale progress string must cause CR-03 to FAIL."""
        monkeypatch.setattr(
            hci_v1,
            "_review_progress_text",
            lambda window: "1 / 5 · 当前还剩 5 张待审核",
        )

        result = run_cr_03(review_window, review_window.db, qapp)
        assert not result.passed, "CR-03 should FAIL when progress text is stale"
        assert result.broken_invariant is not None
        assert "progress" in result.broken_invariant.lower()

    def test_broken_badge_count_causes_rv02_failure(
        self, review_window, qapp, monkeypatch
    ):
        """Injecting a mismatch between DB and UI badges must cause RV-02 to FAIL."""
        if hasattr(review_window, "filter_buttons") and "to_review" in review_window.filter_buttons:
            review_window.filter_buttons["to_review"].set_value("999")

        result = run_rv_02(review_window, review_window.db, qapp)
        assert not result.passed, "RV-02 should FAIL when UI badge count does not match DB"
        assert result.broken_invariant is not None
        assert "to_review" in result.broken_invariant
