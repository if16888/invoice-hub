# RC polish plan: performance, security and right-panel simplification

This note tracks the RC-stage polish scope for Invoice Hub after the phase-1 core flow became usable.

## Goal

Ship a stable RC build focused on personal weekly invoice collection and quarterly reimbursement export.

The scope is intentionally narrow:

- Do not add large new features.
- Do not rewrite the parser pipeline.
- Improve startup/list responsiveness.
- Tighten local-first/security boundaries.
- Simplify the right-side invoice information area for faster review.

## P1: UI simplification

### Current problem

The right-side panel currently uses three tabs:

1. Invoice details
2. Review
3. Claim export

This works functionally, but the review flow is unnecessarily split. The most frequent actions, such as approve, ignore and mark error, are hidden behind a tab. Claim export is a claim-group-level action, not a single-invoice detail action.

### Target design

Replace the three-tab structure with a single-page review panel:

```text
[Summary card]
Amount / expense date / invoice number / seller / category

[Review action bar]
Approve and next | Ignore | Mark error | More...

[Core fields]
Invoice number    Expense date
Amount            Category
Seller            Buyer
[Save]

[Files]
Original: View / Add original / Retry download
Supporting docs: Select / View

[Claim group]
Claim group: [dropdown] [+]
[Add to claim]
Current claim: N invoices | total ¥X

[More source info]
Invoice ID / invoice date / date source / mail subject / URL / full path

[Personal note]
Collapsed by default
```

### Implementation notes

1. Move the existing review buttons out of the `审核` tab and place them directly below the summary card.
2. Move `删除发票` into a secondary `更多` menu to avoid accidental destructive actions.
3. Keep claim association visible in the right panel, but move claim export to the top toolbar or an explicit claim export dialog.
4. Keep `更多来源信息` collapsed by default.
5. Collapse personal note by default; expand only when the user needs to add a note.
6. Merge the `报销闭环` suggestion into the summary card as a single hint line instead of a standalone card.

### Acceptance criteria

- Reviewing one invoice does not require switching tabs.
- The user can approve, ignore or mark an invoice as error from the default right panel.
- Claim export is no longer presented as a single-invoice detail tab.
- The right panel is visibly shorter and less dense than the current three-tab version.

## P1: Performance polish

### Current problem

The first-load path limits the displayed records to 100, but the code still performs a full `list_invoices(status=None, limit=None)` call for count/filter calculation. This can become expensive when a user accumulates thousands of invoices.

### Target behavior

- First load should fetch and render only the first page.
- Avoid full invoice hydration when only a count is needed.
- If exact count is expensive, show an approximate first-load notice instead of blocking startup.

### Suggested implementation

1. Add a DB-level count helper that does not hydrate rows:

```python
count_invoices_for_status(status=None, include_deleted=False) -> int
```

2. For the first-load no-filter case, avoid full count entirely and show:

```text
首屏已加载最近 100 张，点击“加载全部”查看完整列表。
```

3. Add a performance regression test with 1000 synthetic records.

### Acceptance criteria

- 1000 synthetic invoices: first-load render should stay responsive.
- `_load_invoices()` should not hydrate every invoice just to show the first screen.

## P1: Database backup and rollback safety

### Already completed in branch

- Added `scripts/invoice_fetch/db_backup.py` as a GUI-independent SQLite backup helper.
- Added `scripts/invoice_fetch/backup_cli.py` as a standalone backup command.
- Added `tests/test_db_backup.py` and `tests/test_backup_cli.py` for backup, pruning, and CLI coverage.

### Target behavior

Before any high-impact data operation, create a timestamped backup under `runtime/backups/`:

- database schema migration
- repair/backfill utilities
- batch mobile import
- batch delete/restore
- risky rescan or reparse workflows

Suggested naming pattern:

```text
invoices-YYYYMMDD-HHMMSS-before-<reason>.db
```

Manual backup command:

```bash
python -m scripts.invoice_fetch.backup_cli --reason before-manual-repair
```

Optional arguments:

```bash
python -m scripts.invoice_fetch.backup_cli --db runtime/invoices.db --backup-dir runtime/backups --keep-backups 20
```

### Integration notes

The helper is intentionally not wired into the GUI yet, because this pass avoids editing `app.py`. Future integration should call `create_database_backup()` from CLI repair tools, migration entry points, and desktop-confirmed batch-import flows.

## P1/P2: Security polish

### Already completed in branch

- AI request error logging no longer prints raw `RequestException` strings. This reduces the risk of leaking provider URLs or API keys when a provider uses query-string credentials.
- A unit test now verifies that the safe AI request error summary does not contain provider URLs, query keys, or a fake secret token.
- A unit test verifies that AI prompts only include masked `uid`, `subject`, and `sender`, not email body, attachment text, OCR text, or local file paths.

### Remaining security tasks

1. ZIP attachment extraction: keep total-size and file-count limits, and also cap individual inner files.
2. Mobile upload: after receiving files from the LAN upload page, ask the desktop user to confirm import instead of silently importing into the invoice DB.
3. Mobile upload: keep token TTL short and display clear stop-session control.
4. Diagnostics: keep the allowlist model; never include `invoices.db`, original invoice files, export packages, or full tokenized URLs.
5. AI payload boundary: cloud AI requests must remain limited to masked `uid`, `subject`, and `sender`; never send email body text, attachments, OCR text, PDF/OFD text, or image contents.

### Acceptance criteria

- Uploading from phone requires a live token and a desktop-visible session.
- Large ZIP members are skipped before loading their content into memory.
- AI/API exceptions do not contain raw request URLs or credentials in logs.
- High-impact data operations have a backup path before mutating the database.

## Suggested validation commands

```bash
python -m unittest tests.test_db_backup -v
python -m unittest tests.test_backup_cli -v
python -m unittest tests.test_privacy_defaults -v
python -m unittest tests.test_expense_date -v
python -m unittest tests.test_claim_groups -v
python -m unittest tests.test_diagnostics -v
python -m unittest tests.test_mobile_upload -v
python -m unittest discover -v -s tests -p "test_*.py"
python -m compileall -q scripts tests
python scripts/check_public_export.py .
git diff --check
```

## Release gate

The RC can be considered ready when:

- The right-side panel no longer requires tab switching for normal review.
- The first load avoids full-list hydration for the default path.
- The security polish tests pass.
- High-impact data operations create or document a database backup path.
- A real personal reimbursement package can be exported from a mixed set of email, local, and mobile-uploaded invoices.
