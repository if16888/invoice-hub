"""Release-trust tests for Windows Authenticode signing policy."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIGN_SCRIPT = PROJECT_ROOT / "scripts" / "sign_windows.ps1"
RELEASE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "windows-release.yml"


class TestWindowsSigningPolicySource(unittest.TestCase):
    def test_stable_tag_is_fail_closed_and_signature_is_verified(self):
        src = SIGN_SCRIPT.read_text(encoding="utf-8")
        for token in (
            "^v\\d+\\.\\d+\\.\\d+$",
            "AUDIT_MODE",
            "TAG_NAME",
            "RequireSignature",
            "Get-AuthenticodeSignature",
            'Status -ne "Valid"',
            "SignerCertificate",
            "TimeStamperCertificate",
            "TIMESTAMP_URL",
            "CERT_SUBJECT",
            "SIGNTOOL_PATH",
        ):
            self.assertIn(token, src)

        self.assertIn("Authenticode signing is required for this stable release", src)
        self.assertIn("signer subject does not match the configured publisher", src)
        self.assertIn("trusted timestamp is missing", src)

    def test_release_workflow_signs_real_artifacts_before_packaging_and_checksums(self):
        src = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("TAG_NAME: ${{ github.ref_name }}", src)
        self.assertIn('& scripts\\sign_windows.ps1 "dist\\InvoiceHub\\InvoiceHub.exe"', src)
        self.assertIn('& scripts\\sign_windows.ps1 "dist\\${env:SETUP_NAME}"', src)

        portable_sign = src.index("- name: Sign portable executable")
        portable_zip = src.index("- name: Create portable zip")
        installer_sign = src.index("- name: Sign installer")
        checksums = src.index("- name: Create checksums")
        self.assertLess(portable_sign, portable_zip)
        self.assertLess(installer_sign, checksums)


@unittest.skipUnless(os.name == "nt", "PowerShell release signing contract is Windows-only")
class TestWindowsSigningPolicyRuntime(unittest.TestCase):
    def _run_signer(self, target: Path, *, tag_name: str, audit_mode: str = "false"):
        env = os.environ.copy()
        for name in ("SIGNTOOL_PATH", "CERT_SUBJECT", "TIMESTAMP_URL"):
            env.pop(name, None)
        env["TAG_NAME"] = tag_name
        env["AUDIT_MODE"] = audit_mode
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SIGN_SCRIPT),
                str(target),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_stable_tag_without_signing_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "unsigned.exe"
            target.write_bytes(b"unsigned")
            result = self._run_signer(target, tag_name="v0.1.8")
            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, combined)
            self.assertIn("Authenticode signing is required for this stable release", combined)
            self.assertEqual(target.read_bytes(), b"unsigned")

    def test_rc_tag_without_signing_configuration_remains_warning_only(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "unsigned.exe"
            target.write_bytes(b"unsigned")
            result = self._run_signer(target, tag_name="v0.1.8-rc3")
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, combined)
            self.assertIn("Signing skipped", combined)
            self.assertEqual(target.read_bytes(), b"unsigned")

    def test_pre_tag_audit_without_signing_configuration_remains_warning_only(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "unsigned.exe"
            target.write_bytes(b"unsigned")
            result = self._run_signer(target, tag_name="master", audit_mode="true")
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, combined)
            self.assertIn("Signing skipped", combined)
            self.assertEqual(target.read_bytes(), b"unsigned")


if __name__ == "__main__":
    unittest.main()
