# Installer ownership manifests

These manifests record files shipped by the official Windows Portable assets
for the historical `v0.1.5-rc1` and `v0.1.5-rc2` releases. They are used only
to recover installer-owned files whose original Inno uninstall log was lost.

Each row is:

```text
relative_path|size|sha256
```

The source asset name and SHA256 are recorded in the header of each manifest.
Do not replace these files with a local build. To regenerate them, download
the matching official GitHub Release Portable ZIP, extract it, and run:

```text
python scripts/dev/generate_installer_ownership.py manifest \
  --source-dir <extracted-official-payload> \
  --output packaging/legacy/v0.1.5-rcN-files.txt \
  --release v0.1.5-rcN \
  --asset-name InvoiceHub-0.1.5-rcN-win64-portable.zip \
  --asset-sha256 <GitHub-asset-sha256>
```

At release build time, the workflow hashes the exact current PyInstaller
payload and generates `packaging/legacy/installer_ownership.issinc`. The generated Inno
code removes only historical paths absent from the current payload and only
when the on-disk SHA256 matches a recorded official hash. Unknown files and
hash-mismatched files are preserved.
