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
        self.assertIn("Fetch release tags for metadata validation", workflow)
        self.assertIn("git fetch --force --tags --depth=1 origin", workflow)
        self.assertIn("release note that declares a published stable line", workflow)
        self.assertIn("needs.master_ci_attestation.result == 'success'", workflow)
        self.assertIn("Source gates were successful on the identical PR tree", workflow)
        self.assertIn("Unit shard ${{ matrix.shard }} passed on the identical PR tree", workflow)
        self.assertIn("HCI acceptance passed on the identical PR tree", workflow)

    def test_pull_request_gates_do_not_depend_on_existing_master_attestation(self):
        workflow = self.workflow
        source_gates = workflow.split("  source_gates:", 1)[1].split("\n  unit_tests:", 1)[0]
        self.assertNotIn("Verify master attestation against exact base commit", source_gates)
        self.assertNotIn("attest_master_ci.py --sha", source_gates)
        self.assertNotIn("permissions:", source_gates)

    def test_full_source_unit_and_hci_runs_are_pr_only(self):
        workflow = self.workflow
        self.assertRegex(
            workflow,
            r"if: github\.event_name == 'pull_request'\n\s+uses: actions/checkout@[0-9a-f]{40}",
        )
        self.assertIn("if: github.event_name == 'pull_request'\n        run: python scripts/check_repo_privacy.py", workflow)
        self.assertIn("if: github.event_name == 'pull_request'\n        shell: pwsh", workflow)
        self.assertIn("--shard-count 3 --shard-index ${{ matrix.shard }}", workflow)
        self.assertIn("if: always() && github.event_name == 'pull_request'", workflow)

    def test_source_gates_audit_locked_dependencies(self):
        source_gates = self.workflow.split("  source_gates:", 1)[1].split("\n  unit_tests:", 1)[0]
        self.assertIn("name: Audit locked dependencies", source_gates)
        self.assertIn('"pip-audit==2.10.1"', source_gates)
        self.assertIn("python -m pip_audit", source_gates)
        for lock in (
            "requirements.lock.txt",
            "requirements-desktop.lock.txt",
            "requirements-build.lock.txt",
            "requirements-test.lock.txt",
        ):
            with self.subTest(lock=lock):
                self.assertIn(f"-r {lock}", source_gates)

    def test_workflow_actions_are_pinned_to_immutable_commits(self):
        import re

        pattern = re.compile(r"uses:\s*([^\s@]+)@([^\s#]+)(?:\s*#\s*(\S+))?")
        for workflow_path in sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml")):
            source = workflow_path.read_text(encoding="utf-8")
            for match in pattern.finditer(source):
                action = match.group(1)
                if action.startswith("./"):
                    continue
                with self.subTest(workflow=workflow_path.name, action=action):
                    self.assertRegex(match.group(2), r"^[0-9a-f]{40}$")
                    self.assertIsNotNone(
                        match.group(3),
                        f"{action} must keep a version comment next to the SHA",
                    )

    def test_dependabot_covers_python_and_actions(self):
        config = (PROJECT_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        self.assertIn('package-ecosystem: "pip"', config)
        self.assertIn('package-ecosystem: "github-actions"', config)
        self.assertIn('dependency-name: "pyee"', config)
        self.assertIn('">=14.0.0"', config)
        self.assertIn("version-update:semver-major", config)

    def test_native_geometry_remains_a_release_gate_without_a_pr_runner(self):
        # The hosted Windows desktop cannot certify native geometry. Do not
        # spend a separate non-gating PR runner on this unsuitable environment.
        self.assertNotIn("  native_geometry_preflight:", self.workflow)
        self.assertNotIn("Native GUI geometry preflight (non-gating)", self.workflow)
        self.assertTrue((PROJECT_ROOT / "scripts/dev/check_native_gui_geometry.py").is_file())
        self.assertTrue((PROJECT_ROOT / "tests/test_workbench_native_geometry.py").is_file())


if __name__ == "__main__":
    unittest.main()
