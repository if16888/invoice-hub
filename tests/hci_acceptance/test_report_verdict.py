"""Unit tests for HarnessReport verdict consistency and scenario contract completeness.

Verifies that the single acceptance predicate (HarnessReport.accepted) and
its Markdown representation strictly enforce zero-defect and full-coverage requirements:
- scenario fail -> FAIL
- native crash -> FAIL
- timeout -> FAIL
- residual QThread -> FAIL
- residual Python -> FAIL
- residual InvoiceHub -> FAIL
- residual QtWebEngine -> FAIL
- clean 19/19 -> PASS
- empty suite -> FAIL (blocks empty false-pass)
- missing required scenario (18/19) -> FAIL (blocks partial suite false-pass)
- duplicate ID with missing ID (19 entries) -> FAIL (blocks duplicate false-pass)
- unknown extra ID (19+1) -> FAIL (blocks unknown scenario false-pass)
"""

from __future__ import annotations

try:
    import pytest
except ImportError:
    import unittest
    raise unittest.SkipTest("HCI acceptance harness requires pytest or scripts/dev/run_hci_acceptance.py")

from tests.hci_acceptance.harness import (
    REQUIRED_SCENARIO_IDS,
    HarnessReport,
    ScenarioResult,
)


def _make_clean_scenarios(scenario_ids: tuple[str, ...] | list[str] = REQUIRED_SCENARIO_IDS) -> list[ScenarioResult]:
    return [
        ScenarioResult(
            id=sid,
            title=f"Scenario {sid}",
            passed=True,
            backend_expected={"ok": True},
            backend_actual={"ok": True},
            ui_expected={"ok": True},
            ui_actual={"ok": True},
            duration_ms=10,
        )
        for sid in scenario_ids
    ]


class TestReportVerdictConsistency:
    """Validate that HarnessReport.accepted and to_markdown() verdicts are consistent."""

    def test_clean_19_scenarios_passes(self):
        """Clean 19/19 with 0 crashes, 0 timeouts, 0 residuals MUST be accepted."""
        report = HarnessReport(
            scenarios=_make_clean_scenarios(),
            native_crash=False,
            timeout=False,
            residual_threads=0,
            residual_python=0,
            residual_invoicehub=0,
            residual_qtwebengine=0,
        )
        assert report.scenario_contract_ok is True
        assert report.accepted is True
        assert report.passed == 19
        assert report.failed == 0
        md = report.to_markdown()
        assert "**Scenario contract:** PASS" in md
        assert "## Verdict: HCI ACCEPTANCE PASS" in md

    def test_scenario_fail_causes_verdict_fail(self):
        """Any failing scenario MUST cause report.accepted to be False and verdict FAIL."""
        scenarios = _make_clean_scenarios()
        scenarios[2].passed = False
        scenarios[2].broken_invariant = "Stale progress text"

        report = HarnessReport(
            scenarios=scenarios,
            native_crash=False,
            timeout=False,
            residual_threads=0,
            residual_python=0,
            residual_invoicehub=0,
            residual_qtwebengine=0,
        )
        assert report.scenario_contract_ok is True
        assert report.accepted is False
        assert report.failed == 1
        md = report.to_markdown()
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md
        assert "Broken invariant:" in md

    def test_native_crash_causes_verdict_fail(self):
        """Native crash MUST cause report.accepted to be False even if all scenarios passed."""
        report = HarnessReport(
            scenarios=_make_clean_scenarios(),
            native_crash=True,
            timeout=False,
            residual_threads=0,
            residual_python=0,
            residual_invoicehub=0,
            residual_qtwebengine=0,
        )
        assert report.accepted is False
        md = report.to_markdown()
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_timeout_causes_verdict_fail(self):
        """Watchdog timeout MUST cause report.accepted to be False even if all scenarios passed."""
        report = HarnessReport(
            scenarios=_make_clean_scenarios(),
            native_crash=False,
            timeout=True,
            residual_threads=0,
            residual_python=0,
            residual_invoicehub=0,
            residual_qtwebengine=0,
        )
        assert report.accepted is False
        md = report.to_markdown()
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_residual_qthread_causes_verdict_fail(self):
        """Residual QThread > 0 MUST cause report.accepted to be False."""
        report = HarnessReport(
            scenarios=_make_clean_scenarios(),
            native_crash=False,
            timeout=False,
            residual_threads=1,
            residual_python=0,
            residual_invoicehub=0,
            residual_qtwebengine=0,
        )
        assert report.accepted is False
        assert report.residual_threads == 1
        md = report.to_markdown()
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_residual_python_causes_verdict_fail(self):
        """Residual Python process > 0 MUST cause report.accepted to be False."""
        report = HarnessReport(
            scenarios=_make_clean_scenarios(),
            native_crash=False,
            timeout=False,
            residual_threads=0,
            residual_python=1,
            residual_invoicehub=0,
            residual_qtwebengine=0,
        )
        assert report.accepted is False
        assert report.residual_processes == 1
        md = report.to_markdown()
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_residual_invoicehub_causes_verdict_fail(self):
        """Residual InvoiceHub process > 0 MUST cause report.accepted to be False."""
        report = HarnessReport(
            scenarios=_make_clean_scenarios(),
            native_crash=False,
            timeout=False,
            residual_threads=0,
            residual_python=0,
            residual_invoicehub=1,
            residual_qtwebengine=0,
        )
        assert report.accepted is False
        assert report.residual_processes == 1
        md = report.to_markdown()
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_residual_qtwebengine_causes_verdict_fail(self):
        """Residual QtWebEngine process > 0 MUST cause report.accepted to be False."""
        report = HarnessReport(
            scenarios=_make_clean_scenarios(),
            native_crash=False,
            timeout=False,
            residual_threads=0,
            residual_python=0,
            residual_invoicehub=0,
            residual_qtwebengine=1,
        )
        assert report.accepted is False
        assert report.residual_processes == 1
        md = report.to_markdown()
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md


class TestScenarioContractCompleteness:
    """Validate that HarnessReport strictly blocks incomplete, duplicate, or corrupted scenario sets."""

    def test_19_correct_ids_contract_pass(self):
        """Exact 19 required scenario IDs MUST pass contract check."""
        report = HarnessReport(
            scenarios=_make_clean_scenarios(REQUIRED_SCENARIO_IDS),
            native_crash=False,
            timeout=False,
        )
        assert report.scenario_contract_ok is True
        assert report.accepted is True
        md = report.to_markdown()
        assert "**Scenario contract:** PASS" in md
        assert "## Verdict: HCI ACCEPTANCE PASS" in md

    def test_empty_scenarios_contract_fail(self):
        """Empty scenario list MUST fail contract and cause accepted to be False."""
        report = HarnessReport(
            scenarios=[],
            native_crash=False,
            timeout=False,
        )
        assert report.scenario_contract_ok is False
        assert report.accepted is False
        md = report.to_markdown()
        assert "**Scenario contract:** FAIL" in md
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_missing_required_scenario_contract_fail(self):
        """18/18 scenarios passed but missing 1 required ID (e.g. EXPORT-01) MUST fail."""
        partial_ids = list(REQUIRED_SCENARIO_IDS[:-1])
        report = HarnessReport(
            scenarios=_make_clean_scenarios(partial_ids),
            native_crash=False,
            timeout=False,
        )
        assert len(report.scenarios) == 18
        assert report.passed == 18
        assert report.failed == 0
        assert report.scenario_contract_ok is False
        assert report.accepted is False
        md = report.to_markdown()
        assert "**Scenario contract:** FAIL" in md
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_duplicate_id_and_missing_id_contract_fail(self):
        """19 scenario entries with 1 duplicate and 1 missing MUST fail contract."""
        corrupted_ids = list(REQUIRED_SCENARIO_IDS[:-1]) + [REQUIRED_SCENARIO_IDS[0]]
        assert len(corrupted_ids) == 19
        report = HarnessReport(
            scenarios=_make_clean_scenarios(corrupted_ids),
            native_crash=False,
            timeout=False,
        )
        assert len(report.scenarios) == 19
        assert report.passed == 19
        assert report.failed == 0
        assert report.scenario_contract_ok is False
        assert report.accepted is False
        md = report.to_markdown()
        assert "**Scenario contract:** FAIL" in md
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_unknown_extra_id_contract_fail(self):
        """19 required + 1 unknown extra scenario MUST fail contract."""
        extra_ids = list(REQUIRED_SCENARIO_IDS) + ["EXTRA-UNKNOWN-01"]
        report = HarnessReport(
            scenarios=_make_clean_scenarios(extra_ids),
            native_crash=False,
            timeout=False,
        )
        assert len(report.scenarios) == 20
        assert report.passed == 20
        assert report.failed == 0
        assert report.scenario_contract_ok is False
        assert report.accepted is False
        md = report.to_markdown()
        assert "**Scenario contract:** FAIL" in md
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md

    def test_unknown_id_replacing_required_id_contract_fail(self):
        """18 required + 1 unknown scenario (total 19) MUST fail contract."""
        replaced_ids = list(REQUIRED_SCENARIO_IDS[:-1]) + ["UNKNOWN-01"]
        report = HarnessReport(
            scenarios=_make_clean_scenarios(replaced_ids),
            native_crash=False,
            timeout=False,
        )
        assert len(report.scenarios) == 19
        assert report.passed == 19
        assert report.failed == 0
        assert report.scenario_contract_ok is False
        assert report.accepted is False
        md = report.to_markdown()
        assert "**Scenario contract:** FAIL" in md
        assert "## Verdict: HCI ACCEPTANCE FAIL" in md
