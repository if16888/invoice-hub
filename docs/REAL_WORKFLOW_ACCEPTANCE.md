# Real workflow acceptance record

Target source revision: `4e14d0246d7a5acf8df6fb9aa7a768c8621594d9`.

## Safety boundary

This repository checkout contains local runtime and database paths that may hold personal invoice data. This record intentionally does not open, copy, export, or describe those records. The installed desktop application currently reports `v0.1.3`, so it is not a valid executable for accepting the current `4e14d02` source.

The automated portions below use temporary SQLite databases and synthetic UI state only.

## Completed automated acceptance

| Workflow checkpoint | Evidence | Result |
| --- | --- | --- |
| Open dashboard and switch to import, export, and settings | Isolated `InvoiceReviewApp` geometry tests switch all four pages. | Pass |
| Select mobile upload and render active state | Screenshot matrix injects a synthetic mobile session, URL, QR code, and statistics. | Pass |
| Stop/close controller before database close | Mobile shutdown and close-order tests pass. | Pass |
| Display import/export blockers and checklist | Export page uses structured checklist rows; synthetic blocked capture disables export. | Pass |
| Refresh cross-page import activity | Existing focused mobile/import tests verify a batch updates one activity rather than accumulating snapshots. | Pass |

## Deferred manual acceptance

The following operations remain deliberately unperformed:

1. Importing a real local file or scanning a real mailbox account.
2. Editing a record in the local production database.
3. Adding a production record to a reimbursement group and exporting a package.
4. Closing/restarting a source-matched installed package to verify persistence.
5. Clean install, in-place upgrade, and uninstall validation.

They require a fresh package built from this source and an explicitly selected disposable validation profile. Running them against the visible installed `v0.1.3` application or an unknown local production database would not validate this revision and would mutate user state.

## Proposed next controlled run

1. Build the package from this revision.
2. Install it in a disposable per-user test profile with a fresh `%APPDATA%` root.
3. Use a non-sensitive synthetic invoice fixture to complete import, review, grouping, export, close, and restart.
4. Perform clean-install, in-place-upgrade, and uninstall checks in that same disposable profile.
5. Record only counts, actions, and pass/fail outcomes; never document invoice fields, addresses, tokens, keys, or local paths.

## Acceptance decision

**Not ready for Freeze.** Automated source checks are green, but the source-matched Windows package workflow and installer/upgrade acceptance are still P0 release gates.
