# Installer data paths (source / Inno Setup / Microsoft Store MSIX)

Status: verified against the packaging sources on this branch. Synthetic checks
live in `tests/test_runtime_paths.py` and `tests/test_msix_packaging.py`; real
installer runs are covered by `scripts/dev/verify_installer_lifecycle.ps1`.

## Contract

1. **One Windows user-data root:** `%APPDATA%\InvoiceHub`. The SQLite database
   (`invoices.db`), `config.json`, `attachments/`, `logs/`, `backups/` and
   `exports/` all live below it.
2. **No user data in the install directory.** Installers copy only the frozen
   application payload; they never seed or overwrite `invoices.db` or
   `config.json`, and the app never writes runtime data into its install folder.
3. **Uninstall never deletes user data.** Upgrades replace application files and
   keep `%APPDATA%\InvoiceHub` untouched.
4. `INVOICE_HUB_RUNTIME_DIR` (absolute path) overrides the root in every mode.
   It exists for tests/diagnostics and portable isolation, not as a user-facing
   setting.

## Path table

| Mode | Process | Resolved runtime data root | Visible to the other builds? |
|---|---|---|---|
| Source run | `sys.frozen` is false | `<repo>/runtime/` | No (developer data only) |
| Inno Setup install | frozen | `%APPDATA%\InvoiceHub` (real directory) | Yes — portable/Inno share it |
| Portable ZIP | frozen | `%APPDATA%\InvoiceHub` (real directory) | Yes — portable/Inno share it |
| Microsoft Store MSIX (Windows 11+) | frozen, packaged | `%APPDATA%\InvoiceHub` (real directory, unvirtualized) | Yes — after the MSIX manifest opt-out below |

Install payload locations are separate from user data:

- Inno: `%LOCALAPPDATA%\Programs\InvoiceHub` (per-user, `PrivilegesRequired=lowest`,
  no administrator write access; `[UninstallDelete]` only removes empty
  installer-owned directories and never references `{userappdata}`).
- MSIX: the package volume (`C:\Program Files\WindowsApps\<package_full_name>`),
  read-only at runtime; uninstall removes the package, not the real AppData root.
- Portable ZIP: wherever the user unpacked it; deleting that folder leaves
  `%APPDATA%\InvoiceHub` untouched.

## Why the MSIX manifest opts out of AppData virtualization

A packaged (MSIX/Desktop Bridge) app does not write to the real AppData by
default. On Windows 10 1903+ new files under `%APPDATA%` are redirected to a
private per-user, per-package store (for example
`%LOCALAPPDATA%\Packages\<PackageFamilyName>\LocalCache\Roaming\InvoiceHub`);
older Windows versions redirect every AppData write copy-on-write. Files in that
private store are visible only to the packaged app and are removed when the
package is uninstalled.

That default would break this product's contract in two ways:

- the Store build would not see data created by the Inno/portable build (and
  vice versa, except for the "read falls back to real AppData" case);
- uninstalling the Store package would delete the user's invoices.

The manifest therefore declares:

- the restricted capability `unvirtualizedResources`, and
- `<virtualization:FileSystemWriteVirtualization>` with
  `ExcludedDirectory` `$(KnownFolder:RoamingAppData)\InvoiceHub`

(see `packaging/msix/AppxManifest.template.xml`). AppData writes for that folder
then go to the real `%APPDATA%\InvoiceHub`, are visible to the standalone builds,
and survive uninstall.

The generic `desktop6:FileSystemWriteVirtualization` switch is **not** used: its
documentation says it is intended only for certain Microsoft/partner PC games,
so an invoice-management app cannot rely on Store approval for it. The granular
`virtualization:` form is documented for general apps; Microsoft's guidance
dates the granular behavior to Windows 11 (the schema reference lists a
Windows 10 build as its floor), so the Store package conservatively sets
`MinVersion` to Windows 11 (`10.0.22000`). Windows 10 users keep the Inno Setup
and portable ZIP channels, which share the same `%APPDATA%\InvoiceHub` data.

## Residual risks

- `unvirtualizedResources` is a **restricted capability**: Partner Center must
  approve it during Store submission. If it is rejected, the Store package must
  not be shipped; do not fall back to the virtualized default, because that
  silently breaks the cross-build and uninstall-retention contract.
- The Store MSIX targets Windows 11 and later (MinVersion `10.0.22000`) because
  granular AppData exclusion is a Windows 11 feature. Windows 10 remains served
  by the Inno Setup and portable ZIP channels.
- Real-device MSIX acceptance is still required: clean install, upgrade over
  existing `%APPDATA%\InvoiceHub` data, uninstall retention, Credential Manager
  (keyring) access, opening attachments/exports through the shell.
- Data written by any pre-fix MSIX test package lives in the package-private
  LocalCache location. After switching to the unvirtualized package it will not
  appear in `%APPDATA%\InvoiceHub`; copy it out before upgrading such a test
  install (no Store release shipped with the virtualized behavior).
- Source-run data stays in `<repo>/runtime/` by design; moving between source
  runs and installed builds is a copy/complete-backup operation, not a shared
  directory.

## References

- [Flexible virtualization (MSIX)](https://learn.microsoft.com/en-us/windows/msix/desktop/flexible-virtualization)
- [virtualization:FileSystemWriteVirtualization](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-virtualization-filesystemwritevirtualization)
- [desktop6:FileSystemWriteVirtualization (games-only legacy switch)](https://learn.microsoft.com/en-us/uwp/schemas/appxpackage/uapmanifestschema/element-desktop6-filesystemwritevirtualization)
- [How packaged desktop apps run on Windows](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes)
- [Prepare to package a desktop application](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare)
