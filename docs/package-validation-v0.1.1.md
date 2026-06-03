# Invoice Hub v0.1.1 Windows package validation

This document records the manual validation result for the Invoice Hub v0.1.1 Windows release package. It is intended as a public release-quality trace, not as a new release, winget submission, or GitHub Packages publishing step.

## Version

Invoice Hub v0.1.1

## Artifacts

- `InvoiceHub-Setup-v0.1.1.exe`
- `InvoiceHub-windows-x64-v0.1.1.zip`
- `checksums.txt`

## Validation Results

| Check | Result |
| --- | --- |
| SHA256 checksum matches `checksums.txt` | PASS |
| Normal installer launch | PASS |
| Per-user install without administrator permission | PASS |
| Silent install with `/VERYSILENT /NORESTART` | PASS |
| Installed app launch | PASS |
| Silent uninstall | PASS |
| Portable zip extraction | PASS |
| Portable app launch | PASS |

## Distribution Notes

- GitHub Releases remains the primary distribution channel for the Windows desktop app.
- GitHub Packages is not used for current Windows desktop app distribution.
- winget submission remains deferred to a later validated release.
- This record does not rename existing v0.1.1 release artifacts.
- This record does not include real invoices, email addresses, tax IDs, amounts, local paths, databases, Excel exports, API keys, authorization codes, or full download links.

