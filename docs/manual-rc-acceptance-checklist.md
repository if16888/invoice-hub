# Manual RC acceptance checklist

This checklist is for validating Invoice Hub with real personal workflows before tagging an RC release.

Do not upload real invoices, receipts, exported claim packages, local databases, authorization codes, API keys, or full download URLs to GitHub Issues or public chat logs.

## 1. Pre-check

- [ ] Confirm the build/version shown in the app is the expected RC candidate.
- [ ] Confirm the app starts without a crash on a clean launch.
- [ ] Create a database backup before using real data:

```bash
python -m scripts.invoice_fetch.backup_cli --reason before-rc-manual-test
```

- [ ] Confirm the backup appears under `runtime/backups/`.
- [ ] Confirm no real invoice files or `invoices.db` are staged in git.

## 2. Intake flow

### Email scan

- [ ] Scan 20-50 recent emails.
- [ ] Confirm invoice-like emails are found.
- [ ] Confirm non-invoice emails are not aggressively imported.
- [ ] Confirm duplicate emails do not create duplicate invoices.
- [ ] Confirm logs do not show raw auth codes, API keys, or full tokenized URLs.

### Local import

- [ ] Import a mixed local folder containing PDF/OFD/image files.
- [ ] Confirm invalid files are skipped gracefully.
- [ ] Confirm duplicate files are detected.
- [ ] Confirm original file paths are not exposed in diagnostic output.

### Mobile upload

- [ ] Start a mobile upload session from the desktop.
- [ ] Upload 5-10 files from the phone.
- [ ] Confirm token expiry/stop-session behavior is clear.
- [ ] Confirm uploaded files are visible in the local inbox/session folder.
- [ ] Confirm unexpected files do not silently become approved invoices.

## 3. Review flow

- [ ] Select a pending invoice.
- [ ] Confirm summary amount, expense date, invoice number, seller, buyer, and category are visible.
- [ ] Correct one field and save it.
- [ ] Approve one invoice and confirm the next invoice becomes selected.
- [ ] Ignore one invoice and confirm it moves out of the pending workflow.
- [ ] Mark one invoice as error and confirm it is easy to find again.
- [ ] Delete one test invoice and confirm it is soft-deleted/recoverable or clearly recoverable through the deleted filter.
- [ ] Restart the app and confirm review status persists.

## 4. Evidence and claim grouping

- [ ] Attach or associate one supporting document, such as itinerary, water bill, payment proof, or receipt.
- [ ] Confirm the supporting document can be opened from the app.
- [ ] Create one claim group.
- [ ] Add several approved invoices to the claim group.
- [ ] Confirm claim group count and total amount look reasonable.
- [ ] Confirm unlinked invoices can still be found.

## 5. Export flow

- [ ] Export one claim package.
- [ ] Open the generated Excel file.
- [ ] Check at least these columns manually:
  - expense date
  - invoice number
  - seller
  - buyer
  - amount
  - category
  - review status
- [ ] Confirm railway/travel invoices use the travel/expense date, not the invoice issue date.
- [ ] Confirm exported attachments are present and openable.
- [ ] Confirm no ignored/error/deleted invoices are accidentally exported.

## 6. Privacy and diagnostics

- [ ] Export a diagnostics package.
- [ ] Confirm it does not include:
  - `invoices.db`
  - original invoices/receipts/images
  - exported claim packages
  - mailbox auth codes
  - AI API keys
  - full tokenized URLs
- [ ] Confirm diagnostic text is still useful enough to report a bug.
- [ ] Confirm Issue templates or docs warn users not to upload real invoices.

## 7. Startup and performance

- [ ] Launch the app with an existing database.
- [ ] Confirm first screen appears quickly enough for normal use.
- [ ] Confirm the first load does not block on full database hydration.
- [ ] Confirm search/filter still works after the first screen loads.
- [ ] Confirm log expand/collapse does not break layout after maximizing the window.

## 8. Release decision

RC can proceed only when:

- [ ] The real claim package is usable without major manual cleanup.
- [ ] No high-risk privacy leak is observed in logs or diagnostics.
- [ ] No data-loss path is observed during import, review, delete, or export.
- [ ] Unit tests and compile checks pass locally.
- [ ] Known limitations are documented in release notes.

## Suggested local commands

```bash
python -m unittest tests.test_backup_cli -v
python -m unittest tests.test_db_backup -v
python -m unittest tests.test_privacy_defaults -v
python -m unittest tests.test_expense_date -v
python -m unittest tests.test_claim_groups -v
python -m unittest tests.test_diagnostics -v
python -m unittest tests.test_mobile_upload -v
python -m unittest discover -v -s tests -p "test_*.py"
python -m compileall -q scripts tests
python scripts/check_public_export.py .
git diff --check
git status --short
```
