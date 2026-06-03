# Windows package and winget readiness

Invoice Hub is currently distributed as a Windows desktop app through GitHub Releases. The project is still an early preview, so this document is only a readiness review for future winget submission. It does not publish a release, create GitHub Packages, or submit anything to `microsoft/winget-pkgs`.

## Current distribution status

- Current public version context: Invoice Hub v0.1.1.
- Primary download entry: GitHub Releases.
- README and `docs/release-notes/v0.1.1.md` both reference:
  - `InvoiceHub-Setup-*.exe`
  - `InvoiceHub-windows-x64-*.zip`
  - `checksums.txt`
- The release workflow exists at `.github/workflows/windows-release.yml`.
- The workflow builds release assets on version tags and publishes them only from tag refs.
- Current v0.1.1 release assets used `v` in the filename version because the workflow passes the tag name as `AppVersion`.
- Manual package validation for v0.1.1 is recorded in `docs/package-validation-v0.1.1.md`.

## Installer script status

Installer script: `packaging/invoice_hub_windows.iss`

- Expected `InstallerType`: Inno Setup / `inno`.
- Install mode: per-user.
- Admin requirement: no administrator permission expected.
- `PrivilegesRequired=lowest`.
- Default install directory: `{localappdata}\Programs\InvoiceHub`.
- Output filename rule: `InvoiceHub-Setup-{#AppVersion}`.
- If `AppVersion` is passed as `v0.1.1`, the installer name includes `v`.
- If `AppVersion` is passed as `0.1.1`, the installer name does not include `v`.

## Naming consistency recommendation

Current v0.1.1 assets already used:

- `InvoiceHub-Setup-v0.1.1.exe`
- `InvoiceHub-windows-x64-v0.1.1.zip`

Do not rename the existing v0.1.1 release assets and do not rewrite historical release notes.

For v0.1.2 or later, consider standardizing on:

- Git tag: `v0.1.2`
- PackageVersion / winget version: `0.1.2`
- Release assets:
  - `InvoiceHub-Setup-0.1.2.exe`
  - `InvoiceHub-windows-x64-0.1.2.zip`
  - `checksums.txt`

This would require passing a pure semver value to the installer and artifact naming steps while keeping the Git tag with the `v` prefix.

## GitHub Packages conclusion

- GitHub Packages is mainly useful for package or container ecosystems such as npm, NuGet, Maven, and Docker/OCI.
- Invoice Hub is currently a Windows desktop application.
- The appropriate primary distribution channel is GitHub Releases.
- GitHub Packages is not needed for the current distribution model.
- An empty Packages section on the repository sidebar is not a problem.

## Recommended winget metadata

Recommended `PackageIdentifier`:

```text
if16888.InvoiceHub
```

Recommended manifest fields:

```yaml
PackageIdentifier: if16888.InvoiceHub
PackageName: Invoice Hub
Publisher: if16888
License: Apache-2.0
Homepage: https://github.com/if16888/invoice-hub
LicenseUrl: https://github.com/if16888/invoice-hub/blob/master/LICENSE
ShortDescription: Local-first invoice and reimbursement organizer for personal expense preparation.
Description: Invoice Hub is a local-first Windows desktop app for collecting, deduplicating, reviewing, grouping, and exporting invoice and reimbursement documents before submitting them to an enterprise expense system.
InstallerType: inno
```

Expected installer switches:

```yaml
Silent: /VERYSILENT /NORESTART
SilentWithProgress: /SILENT /NORESTART
```

These silent switches must be manually verified against the real Windows installer before they are used in a winget manifest.

## Pre-winget checklist

- [ ] Release asset naming is stable.
- [ ] Installer URL is publicly downloadable.
- [ ] Installer SHA256 matches `checksums.txt`.
- [ ] `InstallerType` is confirmed as `inno`.
- [ ] Silent install `/VERYSILENT /NORESTART` is verified.
- [ ] Silent uninstall is verified.
- [ ] Start menu shortcut works after installation.
- [ ] Normal user permission install works.
- [ ] Windows Defender / SmartScreen prompts are recorded.
- [ ] README and release note download descriptions match.
- [ ] `PackageVersion` uses pure semver, for example `0.1.2`.
- [ ] Git tag uses a `v` prefix, for example `v0.1.2`.
- [ ] No real invoices, databases, Excel exports, secrets, full download links, or local paths are submitted.

## Future wingetcreate draft

Do not run these commands for the current early preview. They are only a future workflow sketch.

```powershell
winget install wingetcreate

wingetcreate new `
  --urls "https://github.com/if16888/invoice-hub/releases/download/v0.1.2/InvoiceHub-Setup-0.1.2.exe"

wingetcreate submit <manifest-path>
```

Before a real submission, confirm the installer SHA256, silent install and uninstall behavior, public asset URL, and version naming.
