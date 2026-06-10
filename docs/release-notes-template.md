# Release notes template

Use this template for each tagged Invoice Hub release.

## Version

`vX.Y.Z`

## Release type

- [ ] RC
- [ ] Stable
- [ ] Hotfix

## Summary

Write 3-5 bullets focused on user-visible changes.

- 
- 
- 

## Upgrade notes

- Back up your local database before upgrading:

```bash
python -m scripts.invoice_fetch.backup_cli --reason before-upgrade
```

- The application stores local runtime data under `runtime/`.
- Uninstalling or replacing the executable should not be treated as a data backup.
- Do not upload real invoices, receipts, exported claim packages, or `invoices.db` when reporting issues.

## New features

- 

## Improvements

- 

## Fixes

- 

## Privacy and security

- Local-first behavior remains the default.
- Cloud AI must remain opt-in and should only receive masked minimal metadata.
- Diagnostics should not include local databases, original invoices, export packages, API keys, mailbox auth codes, or full tokenized URLs.

## Known limitations

- 
- 

## Manual acceptance checklist

Before publishing, complete:

```text
docs/manual-rc-acceptance-checklist.md
```

Minimum release gate:

- [ ] Unit tests pass.
- [ ] `python -m compileall -q scripts tests` passes.
- [ ] `python scripts/check_public_export.py .` passes.
- [ ] A real personal claim package can be exported from mixed email/local/mobile-uploaded invoices.
- [ ] Diagnostics are verified to be redacted.
- [ ] Release assets do not contain `runtime/`, `*.db`, original invoice files, or exported claim packages.

## Validation commands

```bash
python -m unittest tests.test_backup_cli -v
python -m unittest tests.test_db_backup -v
python -m unittest tests.test_privacy_defaults -v
python -m unittest tests.test_expense_date -v
python -m unittest tests.test_claim_groups -v
python -m unittest tests.test_diagnostics -v
python -m unittest tests.test_mobile_upload -v
python -m unittest tests.test_public_export_check -v
python -m unittest discover -v -s tests -p "test_*.py"
python -m compileall -q scripts tests
python scripts/check_public_export.py .
git diff --check
```
