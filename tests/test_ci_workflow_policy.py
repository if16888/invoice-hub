from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestCIWorkflowPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

    def test_master_run_attests_identical_successful_pr_tree(self):
        workflow = self.workflow
        self.assertIn("name: Exact-master CI attestation", workflow)
        self.assertIn("scripts/dev/attest_master_ci.py", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertIn("Fetch previous stable tag for release metadata", workflow)
        self.assertIn("PREVIOUS_STABLE_VERSION", workflow)
        self.assertIn("git fetch --force --no-tags --depth=1 origin $refspec", workflow)
        self.assertIn("needs.master_ci_attestation.result == 'success'", workflow)
        self.assertIn(
            'attest_master_ci.py --sha "${{ github.event.pull_request.base.sha }}"',
            workflow,
        )
        self.assertIn("Source gates were successful on the identical PR tree", workflow)
        self.assertIn("Unit shard ${{ matrix.shard }} passed on the identical PR tree", workflow)
        self.assertIn("HCI acceptance passed on the identical PR tree", workflow)

    def test_full_source_unit_and_hci_runs_are_pr_only(self):
        workflow = self.workflow
        self.assertIn("if: github.event_name == 'pull_request'\n        uses: actions/checkout@v4", workflow)
        self.assertIn("if: github.event_name == 'pull_request'\n        run: python scripts/check_repo_privacy.py", workflow)
        self.assertIn("if: github.event_name == 'pull_request'\n        shell: pwsh", workflow)
        self.assertIn("--shard-count 3 --shard-index ${{ matrix.shard }}", workflow)
        self.assertIn("if: always() && github.event_name == 'pull_request'", workflow)

    def test_native_geometry_is_pr_only_non_gating_and_preflight_conditioned(self):
        geometry = self.workflow.split("  native_geometry_preflight:", 1)[1]
        self.assertIn("if: github.event_name == 'pull_request'", geometry)
        self.assertIn("continue-on-error: true", geometry)
        self.assertIn("id: native_geometry_classification", geometry)
        self.assertIn(
            "if: steps.native_geometry_classification.outcome == 'success'",
            geometry,
        )


if __name__ == "__main__":
    unittest.main()
