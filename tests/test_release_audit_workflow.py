from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "windows-release.yml"
INSTALL_SMOKE = REPO_ROOT / "scripts" / "dev" / "verify_release_install.ps1"


class ReleaseAuditWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.install_smoke = INSTALL_SMOKE.read_text(encoding="utf-8")

    def test_manual_audit_requires_exact_master_event_sha(self) -> None:
        self.assertIn(
            "if: github.event_name == 'workflow_dispatch' || startsWith(github.ref, 'refs/tags/v')",
            self.workflow,
        )
        self.assertIn("EVENT_REF: ${{ github.ref }}", self.workflow)
        self.assertIn("EVENT_SHA: ${{ github.sha }}", self.workflow)
        self.assertIn('if ($env:EVENT_REF -ne "refs/heads/master")', self.workflow)
        self.assertIn("Checked out SHA $actual does not match workflow event SHA $eventSha", self.workflow)
        self.assertIn("git fetch --no-tags origin master --depth=1", self.workflow)
        self.assertIn("Audit event SHA $actual is not exact origin/master", self.workflow)
        self.assertNotIn("candidate_sha:", self.workflow)

    def test_dispatch_input_is_not_interpolated_into_powershell_code(self) -> None:
        self.assertNotIn('$thresh = "${{ github.event.inputs.strict_startup_ms }}"', self.workflow)
        self.assertIn("REQUESTED_STARTUP_MS: ${{ github.event.inputs.strict_startup_ms }}", self.workflow)
        self.assertIn("$thresh = $env:REQUESTED_STARTUP_MS", self.workflow)
        self.assertIn("strict_startup_ms must be a positive integer", self.workflow)

    def test_tag_publication_remains_tag_only_and_requires_annotated_tag(self) -> None:
        release_job = self.workflow.split("\n  release:\n", 1)[1]
        self.assertIn("if: startsWith(github.ref, 'refs/tags/v')", release_job)
        self.assertNotIn("workflow_dispatch", release_job)
        self.assertIn('(git cat-file -t "refs/tags/$tag").Trim()', self.workflow)
        self.assertIn("Release tag $tag must be annotated", self.workflow)
        self.assertIn("name: InvoiceHub-windows-release", release_job)

    def test_audit_artifact_cannot_be_confused_with_release_artifact(self) -> None:
        self.assertIn(
            'InvoiceHub-windows-audit-$($env:SOURCE_SHA.Substring(0, 12))',
            self.workflow,
        )
        self.assertIn("name: ${{ env.ARTIFACT_NAME }}", self.workflow)
        self.assertIn('$artifactName = "InvoiceHub-windows-release"', self.workflow)

    def test_audit_rechecks_master_before_package_evidence_upload(self) -> None:
        self.assertIn("Reconfirm audit candidate is still master", self.workflow)
        self.assertIn(
            "origin/master moved to $master during audit; evidence for $env:SOURCE_SHA is stale",
            self.workflow,
        )
        recheck_index = self.workflow.index("Reconfirm audit candidate is still master")
        upload_index = self.workflow.index("Upload Windows package")
        self.assertLess(recheck_index, upload_index)

    def test_real_installer_is_installed_started_and_uninstalled(self) -> None:
        self.assertIn("verify_release_install.ps1", self.workflow)
        self.assertIn("Upload real installer smoke evidence", self.workflow)
        self.assertIn('-SourceExePath "dist\\InvoiceHub\\InvoiceHub.exe"', self.workflow)
        self.assertIn("INVOICE_HUB_RUNTIME_DIR", self.install_smoke)
        self.assertIn("scripts\\check_startup_time.py", self.install_smoke)
        self.assertIn("Get-ChildItem -LiteralPath $installDir -Filter 'unins*.exe'", self.install_smoke)
        self.assertIn("SETUP_SHA256=", self.install_smoke)
        self.assertIn("SOURCE_EXE_SHA256=", self.install_smoke)
        self.assertIn("INSTALLED_EXE_SHA256=", self.install_smoke)
        self.assertIn("INSTALLED_EXE_MATCHES_SOURCE=PASS", self.install_smoke)
        self.assertIn("INSTALL=PASS", self.install_smoke)
        self.assertIn("STARTUP=PASS", self.install_smoke)
        self.assertIn("UNINSTALL=PASS", self.install_smoke)
        self.assertIn("RELEASE_INSTALL_SMOKE=PASS", self.install_smoke)

    def test_synthetic_ownership_recovery_gate_is_preserved(self) -> None:
        self.assertIn("verify_installer_lifecycle.ps1", self.workflow)
        self.assertIn("Verify installer lifecycle ownership recovery", self.workflow)


if __name__ == "__main__":
    unittest.main()
