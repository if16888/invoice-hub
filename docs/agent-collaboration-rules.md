# Agent collaboration rules

This document defines how ChatGPT, Codex, Antigravity, and manual edits should share work on Invoice Hub without overwriting each other.

## 1. Default branch workflow

Use the RC polish branch for this work:

```bash
git fetch origin
git checkout rc-polish-performance-security-ui
git pull --ff-only origin rc-polish-performance-security-ui
git status
```

If `git status` shows local changes that are not yours, stop and report before editing.

Never force-push this branch.

## 2. Ownership boundaries

### ChatGPT

Best suited for:

- small safety utilities
- tests
- docs
- code review instructions
- privacy and release checklists
- low-risk non-GUI refactors

Avoid:

- large `app.py` edits
- visual GUI changes that require running the app
- broad parser rewrites without local tests

### Codex

Best suited for:

- backend logic
- database queries and indexes
- performance tests
- CLI tooling
- parser edge cases
- export correctness

Before editing GUI-heavy code, keep changes small and add regression tests.

### Antigravity

Best suited for:

- visual layout
- PySide widget spacing and hierarchy
- right-panel interaction design
- screenshots/manual GUI checks

Keep GUI commits focused. Avoid mixing visual changes with backend logic.

### Manual maintainer edits

Best suited for:

- final review
- real-data acceptance testing
- release notes
- merge decisions
- screenshots for README or release pages

## 3. Large-file rules

`app.py` is a high-conflict file.

Rules:

- Avoid editing `scripts/invoice_fetch/gui/app.py` unless necessary.
- If a planned `app.py` change exceeds about 150 lines, stop and propose a smaller split first.
- Prefer extracting new components before large reshuffles:
  - `scripts/invoice_fetch/gui/detail_panel.py`
  - `scripts/invoice_fetch/gui/review_actions.py`
  - `scripts/invoice_fetch/gui/claim_panel.py`
  - `scripts/invoice_fetch/gui/log_panel.py`
- Do not reformat the whole file.
- Do not combine GUI layout rewrites with parser/database changes.

## 4. Commit rules

Each commit should solve one problem.

Good examples:

```text
fix: avoid full invoice hydration on first load
fix: cap zip member extraction size
ui: add inline invoice review actions
test: cover database backup cli
docs: add manual rc acceptance checklist
```

Avoid:

```text
update code
fix stuff
big refactor
ui and backend changes
```

## 5. Required pre-edit checks

Before editing:

```bash
git fetch origin
git checkout rc-polish-performance-security-ui
git pull --ff-only origin rc-polish-performance-security-ui
git status
```

Before committing:

```bash
git diff --check
python -m compileall -q scripts tests
```

Run targeted tests for touched areas. Examples:

```bash
python -m unittest tests.test_privacy_defaults -v
python -m unittest tests.test_db_backup -v
python -m unittest tests.test_backup_cli -v
python -m unittest tests.test_mobile_upload -v
python -m unittest tests.test_claim_groups -v
python -m unittest tests.test_expense_date -v
```

For broad changes, run:

```bash
python -m unittest discover -v -s tests -p "test_*.py"
python scripts/check_public_export.py .
```

## 6. Privacy boundaries

Never commit or paste:

- `runtime/invoices.db`
- `runtime/backups/*.db`
- original invoices, receipts, images, OFD/PDF files
- exported claim packages
- mailbox authorization codes
- AI API keys
- full tokenized invoice download URLs
- diagnostics packages that have not been verified as redacted

Use synthetic test data only.

## 7. Conflict handling

If a pull fails or a file changed upstream:

1. Stop editing.
2. Record the current branch and commit.
3. Report the conflict file paths.
4. Re-fetch and inspect upstream changes.
5. Re-apply only the minimal intended patch.

Do not use `git push --force`.

## 8. Final report format

Every agent handoff should include:

- branch name
- latest commit SHA
- files changed
- tests run
- tests skipped or failed
- known risks
- next recommended step

Example:

```text
Branch: rc-polish-performance-security-ui
Commit: <sha>
Files: scripts/invoice_fetch/db_backup.py, tests/test_db_backup.py
Tests: python -m unittest tests.test_db_backup -v
Risks: not wired into GUI yet
Next: integrate backup before batch import after GUI review
```
