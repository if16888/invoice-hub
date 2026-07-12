# Real workflow acceptance record

Target: current head of PR #50 on `agent/ui-stabilization-real-workflow`.

## Safety boundary

Automated acceptance uses temporary SQLite databases, synthetic accounts and
synthetic UI state only. It does not open, copy, export, or describe production
invoices, credentials, API keys, authorization codes, or user databases.

Runtime screenshots, disposable packages and temporary databases remain outside
Git. `email_report.html` is not part of the acceptance evidence.

## Completed automated workflow acceptance

| Workflow checkpoint | Evidence | Result |
| --- | --- | --- |
| App Shell and five primary pages | Isolated `InvoiceReviewApp` tests navigate Dashboard, Review, Import, Export and Settings | Pass |
| Review count and selection truthfulness | `ReviewViewState`, zero-result, no-record and no-selection tests | Pass |
| Mailbox account states | Normal, missing credential, disabled, empty and long-text tests | Pass |
| AI configuration states | Zero, one and multiple profiles; local-only configuration validation copy | Pass |
| Embedded mobile upload | Idle, starting, active, error, network switch and shutdown ordering tests | Pass |
| Import activity ownership | One controller event updates one business activity batch | Pass |
| Export preflight | Approved/pending/evidence/file/directory/naming checklist and blocked state | Pass |
| DPI/geometry | Isolated 100%, 125% and 150% Qt-scale control-bound and text-fit checks | Pass |
| Privacy/public source | Repository privacy and public-export gates | Pass |

## Source-matched build evidence

A disposable PyInstaller onedir build was produced from the PR worktree in a
TEMP directory. It was not installed over the user's existing application and
was not committed. The earlier recorded test executable SHA256 was:

`CDD874FA650962E9DEDCDEEC831BBB67F41EAF305B6E5C7F2050EB9ABFE78C00`

That build proves packaging can complete; it does not prove installer, upgrade,
persistence, uninstall or final Windows typography behavior for the current
head after all Design Baseline changes.

## Required controlled manual run

Use a new disposable validation profile and synthetic fixtures only:

1. Build a fresh source-matched package from the final PR head.
2. Clean-install it without replacing the production profile.
3. Start with an empty database and verify Dashboard/Settings empty states.
4. Import a synthetic invoice file.
5. Review and edit one synthetic field.
6. Attach synthetic proof material.
7. Create a synthetic reimbursement group and add the invoice.
8. Verify export preflight and export a synthetic reimbursement package.
9. Close and restart; verify records, group, settings and layout persist.
10. Upgrade from the previous installed release in a disposable profile.
11. Uninstall and reinstall; verify the documented user-data policy.
12. Review Chinese typography at physical Windows 100%, 125% and 150% scaling.

Record only pass/fail, counts and interaction findings. Do not record real
addresses, invoice fields, keys, tokens or private local paths.

## Acceptance decision

- **Design Baseline source implementation:** complete.
- **Automated workflow acceptance:** complete when the final PR CI is green.
- **Physical Windows and installer acceptance:** pending.
- **Release/UI Freeze:** not approved until the controlled manual run passes.
