"""HCI Acceptance Test Suite for Invoice Hub.

Executes all 19 core HCI state-transition scenarios against the synthetic environment
and asserts dual-oracle invariants (backend DB + visible Qt widget state).
"""

from __future__ import annotations

try:
    import pytest
except ImportError:
    import unittest
    raise unittest.SkipTest("HCI acceptance harness requires pytest or scripts/dev/run_hci_acceptance.py")

from tests.hci_acceptance.scenarios import (
    run_cr_01,
    run_cr_02,
    run_cr_03,
    run_cr_04,
    run_cr_05,
    run_cr_06,
    run_cr_07,
    run_cr_08,
    run_rv_01,
    run_rv_02,
    run_mail_01,
    run_mail_02,
    run_mail_03,
    run_mail_04,
    run_mail_05,
    run_date_01,
    run_date_02,
    run_safe_01,
    run_export_01,
)


class TestHciAcceptance:
    """Test suite executing the 19 core HCI state transitions."""

    def _assert_scenario(self, result):
        if not result.passed:
            msg = (
                f"\n[FAIL] {result.id}: {result.title}\n"
                f"Broken invariant: {result.broken_invariant}\n"
                f"Expected backend: {result.backend_expected}\n"
                f"Actual backend: {result.backend_actual}\n"
                f"Expected UI: {result.ui_expected}\n"
                f"Actual UI: {result.ui_actual}"
            )
            pytest.fail(msg)

    # ── Continuous Review Scenarios ──────────────────────────────────

    def test_cr_01_continuous_review_entry(self, review_window, qapp):
        result = run_cr_01(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_cr_02_continuous_review_approve_one(self, review_window, qapp):
        result = run_cr_02(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_cr_03_continuous_review_two_consecutive(self, review_window, qapp):
        result = run_cr_03(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_cr_04_ignore_transition(self, review_window, qapp):
        result = run_cr_04(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_cr_05_error_transition(self, review_window, qapp):
        result = run_cr_05(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_cr_06_skip_without_status_change(self, review_window, qapp):
        result = run_cr_06(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_cr_07_exit_and_reenter(self, review_window, qapp):
        result = run_cr_07(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_cr_08_last_item_complete(self, review_window, qapp):
        result = run_cr_08(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    # ── Review Workspace Scenarios ───────────────────────────────────

    def test_rv_01_workspace_selection_consistency(self, review_window, qapp):
        result = run_rv_01(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_rv_02_status_badge_counts_consistency(self, review_window, qapp):
        result = run_rv_02(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    # ── Mail Sync Scenarios ──────────────────────────────────────────

    def test_mail_01_sync_active_download(self, review_window, qapp):
        result = run_mail_01(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_mail_02_active_stage_transition(self, review_window, qapp):
        result = run_mail_02(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_mail_03_sync_complete(self, review_window, qapp):
        result = run_mail_03(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_mail_04_sync_failed(self, review_window, qapp):
        result = run_mail_04(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_mail_05_sync_cancelled(self, review_window, qapp):
        result = run_mail_05(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    # ── Date Range Scenarios ─────────────────────────────────────────

    def test_date_01_date_range_presets(self, review_window, qapp):
        result = run_date_01(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_date_02_date_range_invalid_rejected(self, review_window, qapp):
        result = run_date_02(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    # ── Safety & Export Scenarios ────────────────────────────────────

    def test_safe_01_operation_mutual_exclusion(self, review_window, qapp):
        result = run_safe_01(review_window, review_window.db, qapp)
        self._assert_scenario(result)

    def test_export_01_missing_material_fail_closed(self, review_window, qapp):
        result = run_export_01(review_window, review_window.db, qapp)
        self._assert_scenario(result)
