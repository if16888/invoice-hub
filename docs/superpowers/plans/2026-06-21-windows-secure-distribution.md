# Windows Secure Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing PyInstaller onedir and Inno Setup flow while producing consistently named setup, portable, and SHA256 artifacts with stable Windows metadata and optional Authenticode signing hooks.

**Architecture:** A small Python module generates the PyInstaller version resource from the existing single version source. A standalone PowerShell signer is called at the two future signing points but exits successfully with a warning when signing is not configured. The release workflow remains the orchestrator and publishes one verified three-file artifact bundle.

**Tech Stack:** Python 3.11, unittest, PyInstaller, PowerShell, Inno Setup, GitHub Actions.

---

## File structure

- Create `scripts/generate_windows_version_info.py`: generate a PyInstaller-compatible Windows version resource from `scripts.invoice_fetch.version.VERSION`.
- Create `scripts/sign_windows.ps1`: optionally sign one or more Windows files with `signtool.exe` and environment-based configuration.
- Modify `packaging/invoice_hub_windows.spec`: require and attach generated version metadata while preserving onedir and disabled UPX.
- Modify `packaging/invoice_hub_windows.iss`: adopt the stable setup filename and conditionally enable an externally registered Inno SignTool.
- Modify `.github/workflows/windows-release.yml`: generate metadata, call optional signing hooks in the correct order, rename artifacts, checksum them, and upload/release all three.
- Create `docs/windows-install.md`: explain Windows warnings, official download source, checksum verification, and Authenticode priority over MSI migration.
- Modify `README.md`: use the new artifact names and link the Windows safety guide.
- Modify `docs/release-checklist.md`: align release verification with the three canonical artifact names and signing readiness.
- Modify `tests/test_startup_probe_and_packaging.py`: enforce all packaging, signing, workflow, and documentation contracts.

### Task 1: Lock down version-resource behavior

**Files:**
- Create: `scripts/generate_windows_version_info.py`
- Modify: `packaging/invoice_hub_windows.spec`
- Test: `tests/test_startup_probe_and_packaging.py`

- [ ] **Step 1: Write failing version-resource tests**

Add tests that import `build_version_info_text`, assert numeric four-part tuples for `0.1.3`, assert stable product fields, run the module into a temporary output file, and assert the spec contains `version=str(_version_file)` plus the existing onedir and `upx=False` contracts.

```python
class TestWindowsVersionInfo(unittest.TestCase):
    def test_generator_uses_stable_product_metadata(self):
        from scripts.generate_windows_version_info import build_version_info_text

        text = build_version_info_text("0.1.3")
        self.assertIn("filevers=(0, 1, 3, 0)", text)
        self.assertIn("prodvers=(0, 1, 3, 0)", text)
        for value in (
            "CompanyName', 'Invoice Hub",
            "ProductName', 'Invoice Hub",
            "FileDescription', 'Invoice Hub",
            "InternalName', 'InvoiceHub",
            "OriginalFilename', 'InvoiceHub.exe",
            "ProductVersion', '0.1.3",
        ):
            self.assertIn(value, text)

    def test_spec_attaches_generated_version_resource(self):
        src = (PROJECT_ROOT / "packaging" / "invoice_hub_windows.spec").read_text(encoding="utf-8")
        self.assertIn('build" / "windows-version-info.txt', src)
        self.assertIn("version=str(_version_file)", src)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestWindowsVersionInfo`

Expected: FAIL because `scripts.generate_windows_version_info` does not exist and the spec has no version resource.

- [ ] **Step 3: Implement the generator**

Create a generator with `build_version_info_text(version: str) -> str`, a numeric tuple helper that extracts up to four dot-separated numeric components and pads with zeroes, and a CLI `--output` option defaulting to `build/windows-version-info.txt`. Use PyInstaller's `VSVersionInfo`, `FixedFileInfo`, `StringFileInfo`, `StringTable`, `StringStruct`, `VarFileInfo`, and `VarStruct` text format. The CLI imports `VERSION` from `scripts.invoice_fetch.version`, creates the parent directory, writes UTF-8 text, and prints the output path.

- [ ] **Step 4: Attach metadata in the spec**

Define `_version_file = _root / "build" / "windows-version-info.txt"`, raise a clear `FileNotFoundError` when it is absent, and pass `version=str(_version_file)` to `EXE`. Do not change `exclude_binaries=True`, either `upx=False`, the `COLLECT`, or bundled data.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestWindowsVersionInfo tests.test_startup_probe_and_packaging.TestPyInstallerSpecIntegrity`

Expected: PASS.

### Task 2: Add the non-blocking optional signer

**Files:**
- Create: `scripts/sign_windows.ps1`
- Test: `tests/test_startup_probe_and_packaging.py`

- [ ] **Step 1: Write failing signer tests**

Add a test that creates a temporary file, removes `SIGNTOOL_PATH`, `CERT_SUBJECT`, and `TIMESTAMP_URL` from a copied environment, invokes Windows PowerShell with the script and target path, and asserts exit code zero, `WARNING` in combined output, and unchanged bytes. Add static contract assertions for all three environment variables and `/fd`, `/tr`, and `/td` arguments.

```python
class TestOptionalWindowsSigning(unittest.TestCase):
    def test_missing_certificate_configuration_warns_without_modifying_file(self):
        import subprocess
        import tempfile

        script = PROJECT_ROOT / "scripts" / "sign_windows.ps1"
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "unsigned.exe"
            target.write_bytes(b"unsigned")
            env = os.environ.copy()
            for name in ("SIGNTOOL_PATH", "CERT_SUBJECT", "TIMESTAMP_URL"):
                env.pop(name, None)
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(target)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("WARNING", (result.stdout + result.stderr).upper())
            self.assertEqual(target.read_bytes(), b"unsigned")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestOptionalWindowsSigning`

Expected: FAIL because `scripts/sign_windows.ps1` does not exist.

- [ ] **Step 3: Implement the signer**

Implement an advanced PowerShell script with a mandatory `string[] Path` parameter. If `SIGNTOOL_PATH` or `CERT_SUBJECT` is blank, call `Write-Warning` and `return`. Otherwise verify the signer and every target exist, then execute:

```powershell
& $signTool sign /fd SHA256 /n $certSubject /tr $timestampUrl /td SHA256 $resolvedPath
```

Omit `/tr` and `/td` only when `TIMESTAMP_URL` is blank, while warning that no timestamp is configured. Throw if `signtool.exe` returns a non-zero exit code.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestOptionalWindowsSigning`

Expected: PASS and the temporary target remains unchanged.

### Task 3: Prepare Inno Setup for optional signing and canonical naming

**Files:**
- Modify: `packaging/invoice_hub_windows.iss`
- Test: `tests/test_startup_probe_and_packaging.py`

- [ ] **Step 1: Replace old Inno assertions with failing canonical-contract tests**

Assert `OutputBaseFilename=InvoiceHub-{#AppVersion}-win64-setup`, `#ifdef SignToolName`, `SignTool={#SignToolName}`, and `SignedUninstaller=yes`. Preserve assertions for `PrivilegesRequired=lowest`, `%LOCALAPPDATA%` installation, and no user-data deletion.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestInnoSetupInstallerPackaging`

Expected: FAIL on the old output filename and missing conditional signing configuration.

- [ ] **Step 3: Make the minimal Inno changes**

Change only the output base filename and add this optional block in `[Setup]`:

```iss
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif
```

Do not alter `AppId`, install location, privileges, file copy rules, shortcuts, or uninstall behavior.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestInnoSetupInstallerPackaging`

Expected: Inno-specific tests PASS; workflow-name tests remain RED until Task 4.

### Task 4: Rewire CI artifact production and upload

**Files:**
- Modify: `.github/workflows/windows-release.yml`
- Test: `tests/test_startup_probe_and_packaging.py`

- [ ] **Step 1: Write failing workflow contract tests**

Assert the workflow reads `VERSION` rather than `APP_VERSION`, creates these exact paths, calls the version generator before PyInstaller, calls `scripts/sign_windows.ps1` once before portable compression and once after Inno compilation, creates `SHA256SUMS.txt`, uploads a single `InvoiceHub-windows-release` artifact containing all three files, downloads that artifact in the release job, and publishes all three exact wildcard patterns.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestVersionSource tests.test_startup_probe_and_packaging.TestGithubWorkflowExists tests.test_startup_probe_and_packaging.TestInnoSetupInstallerPackaging`

Expected: FAIL because the workflow still uses the old setup, zip, and checksum names and has no signing hooks.

- [ ] **Step 3: Generate metadata before PyInstaller**

Add `python -m scripts.generate_windows_version_info --output build/windows-version-info.txt` immediately before the PyInstaller build step.

- [ ] **Step 4: Use pure semantic version artifact names**

Read `VERSION`, require `github.ref_name` to equal `v${version}`, and export:

```powershell
echo "VERSION=${version}" >> $env:GITHUB_ENV
echo "ZIP_NAME=InvoiceHub-${version}-win64-portable.zip" >> $env:GITHUB_ENV
echo "SETUP_NAME=InvoiceHub-${version}-win64-setup.exe" >> $env:GITHUB_ENV
```

- [ ] **Step 5: Insert optional signing calls in order**

After executable/startup verification and before `Compress-Archive`, call:

```powershell
& scripts\sign_windows.ps1 "dist\InvoiceHub\InvoiceHub.exe"
```

After `iscc`, call the same script with `dist\${env:SETUP_NAME}`. Keep environment variables unset in repository CI.

- [ ] **Step 6: Build and checksum canonical artifacts**

Compress `dist\InvoiceHub\*` into `dist\${env:ZIP_NAME}`. Build Inno with pure `AppVersion`. Hash setup and portable into `dist\SHA256SUMS.txt` using lowercase SHA256, two spaces, and leaf filenames.

- [ ] **Step 7: Upload and publish one three-file bundle**

Replace split uploads with one `actions/upload-artifact@v4` named `InvoiceHub-windows-release`, containing the two canonical wildcard paths and `dist/SHA256SUMS.txt`. Download that one artifact in the release job and publish the same three paths with updated release-body names and safety-guide language.

- [ ] **Step 8: Run tests and verify GREEN**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestVersionSource tests.test_startup_probe_and_packaging.TestGithubWorkflowExists tests.test_startup_probe_and_packaging.TestInnoSetupInstallerPackaging`

Expected: PASS.

### Task 5: Document Windows download safety

**Files:**
- Create: `docs/windows-install.md`
- Modify: `README.md`
- Modify: `docs/release-checklist.md`
- Test: `tests/test_startup_probe_and_packaging.py`

- [ ] **Step 1: Write failing documentation tests**

Assert the guide contains `SmartScreen`, `Unknown Publisher`, `不常见下载`, the official `https://github.com/if16888/invoice-hub/releases` URL, `Get-FileHash`, `SHA256SUMS.txt`, `MSI`, and `Authenticode`. Assert README links the guide and uses both canonical wildcard names. Assert the release checklist names all three canonical artifacts.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestWindowsInstallDocumentation`

Expected: FAIL because the guide does not exist and current docs use old names.

- [ ] **Step 3: Add the safety guide**

Explain that reputation warnings are expected for unsigned/low-reputation downloads, direct users only to official GitHub Releases, give this verification example, and explain its limits:

```powershell
Get-FileHash .\InvoiceHub-0.1.3-win64-setup.exe -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

State explicitly that MSI is an installer format rather than a SmartScreen solution and that trusted, timestamped Authenticode signing is the priority before broad promotion.

- [ ] **Step 4: Align README and release checklist**

Use `InvoiceHub-*-win64-setup.exe`, `InvoiceHub-*-win64-portable.zip`, and `SHA256SUMS.txt`; link `docs/windows-install.md`; do not edit historical release notes or user-data documentation.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging.TestWindowsInstallDocumentation`

Expected: PASS.

### Task 6: Full verification and scope audit

**Files:**
- Verify all files changed by Tasks 1-5.

- [ ] **Step 1: Run the focused packaging suite**

Run: `python -m unittest -v tests.test_startup_probe_and_packaging`

Expected: PASS.

- [ ] **Step 2: Generate and inspect the real version resource**

Run: `python -m scripts.generate_windows_version_info --output build/windows-version-info.txt`

Expected: output file exists and contains version `0.1.3` plus stable metadata fields.

- [ ] **Step 3: Exercise unsigned signing behavior locally**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sign_windows.ps1 scripts/invoice_fetch/version.py`

Expected: warning and exit code zero; the target remains unchanged.

- [ ] **Step 4: Run the complete test suite**

Run: `python -m unittest discover -v -s tests -p "test_*.py"`

Expected: PASS, allowing only documented pre-existing skips.

- [ ] **Step 5: Run source and release hygiene gates**

Run:

```powershell
python -m compileall -q scripts tests
python scripts/check_repo_privacy.py
python scripts/check_public_export.py .
git diff --check
```

Expected: every command exits zero.

- [ ] **Step 6: Audit scope and secrets**

Run `git status --short`, `git diff --stat`, and targeted searches for `*.pfx`, `*.p12`, `*.key`, tokens, and certificate blobs among changed files. Confirm no user-data path or application business logic changed.

- [ ] **Step 7: Report release retagging separately**

Do not delete or move `v0.1.3` during implementation. After the verified changes are integrated, report that recreating the existing release requires separately deleting the old GitHub Release and old local/remote tag, then tagging the final release commit.
