# Invoice Hub Design Baseline v1.0 — implementation review

Review target: current head of PR #50 (`agent/ui-stabilization-real-workflow`).

## Decision

**Source implementation complete; manual release acceptance still pending.**

The Design Baseline is now applied to the App Shell, Dashboard, Review Workspace,
Import Center, reimbursement/export flow, and every Settings subpage. This is a
source/UI milestone, not a release or physical-Windows freeze claim.

## Implemented baseline

| Area | Implemented contract | Automated status |
| --- | --- | --- |
| Global visual tokens | Semantic page/surface/selected/border/text/accent/success/warning/danger palette; 22px page title; 8px surfaces; 6px controls | Pass |
| Page archetypes | Dashboard 1360px, dense Workspace, Task Flow 1440px, Settings 1120px/168px nav | Pass |
| Mailbox Golden Page | 280px two-line account list, one 560–760px detail surface, 104px field grid, contextual footer, actionable empty state | Pass |
| AI configuration | Zero/one/many profile states, one integration surface, truthful local validation copy, credential storage and privacy boundary | Pass |
| Runtime/privacy/data/About | One bounded surface per page, field ownership, content-height footer, no raw technical-log page layout | Pass |
| Dashboard | Desktop-width content host, one content-width `继续审核` primary, compact activity surface | Pass |
| Import Center | Source/task/result responsibility widths, compact local/mail actions, embedded mobile upload retained | Pass |
| Export | 280px group list, flexible invoices, 360px preflight, structured naming check, content-width export action | Pass |
| Review Workspace | Unified `ReviewViewState`, truthful empty/no-selection states, compact filters without Unicode decoration, 24px dense rows, bounded detail width | Pass |
| Screenshot evidence | Explicit page/state matrix, unsupported-state rejection, source SHA/DPI/scale/actual-size manifest | Pass |

## Evidence boundary

- Automated tests create temporary SQLite databases and synthetic UI state.
- Screenshot output is written only to the ignored `runtime/ui-review/` tree.
- No production invoice, mailbox, credential, API key, authorization code, or
  `email_report.html` is read or committed as acceptance evidence.
- The source-matched disposable PyInstaller build remains test evidence only; it
  is not a formal release installer.

## Supported screenshot matrix

The capture utility covers:

- Dashboard: normal / empty / error
- Review: normal / empty / no-selection
- Import: mail / local / mobile normal, mobile active and error
- Export: normal / empty / blocked
- Mailbox: normal / empty / missing authorization / disabled / long text
- AI: normal / empty / multiple profiles
- Runtime, privacy, data/backup and About
- API Key dialog: normal / empty / error / long text

Each accepted capture records requested and actual geometry, Qt mode, scale,
device-pixel ratio, logical DPI, source commit, timestamp, and state validation.

## Manual gates still required

The following remain outside automated/source completion and block a formal UI
or release freeze:

1. Source-matched Windows installer clean install.
2. Upgrade from the current installed release while retaining config and data.
3. Uninstall and reinstall behavior.
4. Physical Windows Chinese-font review at 100%, 125%, and 150% scaling.
5. A disposable end-to-end workflow: import synthetic invoice → review → add
   proof → reimbursement group → export → close → restart → verify persistence.
6. Human screenshot review for visual balance, not only geometry correctness.

## Freeze terminology

- **Design Baseline source implementation:** complete.
- **Automated regression gate:** green when PR CI succeeds.
- **Manual Windows acceptance:** pending.
- **Release/UI Freeze:** not yet approved.
