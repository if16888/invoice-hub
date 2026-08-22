# Invoice Hub Design Baseline v1.0 — implementation review

Review target: historical PR #50 (`agent/ui-stabilization-real-workflow`) plus the
v0.1.6 interaction amendment tracked in PR #107.

## Decision

**The historical Design Baseline source implementation is complete. The v0.1.6
mobile interaction design is frozen by an addendum, while packaged-Windows and
Android/WeChat release acceptance remain open.**

The historical baseline was applied to the App Shell, Dashboard, Review
Workspace, Import Center, reimbursement/export flow, and every Settings
subpage. The current authority for v0.1.6 Mobile Upload and compact-layout
amendments is:

- [`docs/design/2026-08-22-v0.1.6-interaction-freeze.md`](design/2026-08-22-v0.1.6-interaction-freeze.md)

This remains a source/UI milestone, not a claim that the v0.1.6 release or real
device acceptance is complete.

## Implemented baseline

| Area | Implemented contract | Current status |
| --- | --- | --- |
| Global visual tokens | Semantic page/surface/selected/border/text/accent/success/warning/danger palette; 22px page title; restrained surfaces/controls | Pass / frozen |
| Page archetypes | Dashboard, dense Review Workspace, Task Flow, Settings secondary navigation | Pass / frozen |
| Mailbox Golden Page | Two-line account list, one detail surface, field ownership, contextual footer, actionable empty state | Pass; compact reflow amendment documented |
| AI configuration | Zero/one/many profile states, one integration surface, truthful local validation copy, credential storage and privacy boundary | Pass |
| Runtime/privacy/data/About | One bounded surface per page, field ownership, content-height footer, no raw technical-log page layout | Pass |
| Dashboard | Task-first dashboard with one primary continue action; no generic analytics-chart treatment | Pass / frozen |
| Import Center — mail/local | Source/task/result responsibility layout with compact actions | Pass / frozen |
| Import Center — mobile active | Parent workspace owns mobile-active width; QR + connection-status desktop workspace; no internal narrow debug scroll; technical details collapsed | **Pass / UI-MOBILE-DESKTOP-001 closed** |
| Mobile Web Upload | Choose → local review → explicit upload; image preview; vendored PDF.js first-page/multipage review; OFD fallback; sticky CTA | Source/Chromium pass; Android/WeChat acceptance open |
| Windows Firewall UX | Packaged Private-only explicit authorization; source/dev current-port-only explicit authorization and explicit cleanup; firewall state separated from LAN reachability | Source contract pass; packaged real-phone acceptance open |
| Export | Group list, flexible invoice region, preflight and structured naming readiness | Pass / frozen |
| Review Workspace | Unified review state, truthful empty/no-selection states, dense list/detail ownership and continuous-review behavior | Pass / frozen |
| Screenshot evidence | Explicit page/state matrix and native capture metadata | Automated/native evidence available; human review remains authoritative for visual balance |

## v0.1.6 mobile freeze state

`UI-MOBILE-DESKTOP-001` is closed at the PR #107 interaction-freeze candidate:

- Import Workspace, not the embedded child size hint, owns active-mobile desktop
  width allocation;
- desktop active state uses QR + Connection Status columns;
- default user UI does not expose bind/public/debug rows;
- technical details are collapsed;
- the former narrow internal details scroll strip is removed;
- native Windows screenshots cover 1366×768, 1440×900 and 1920×1080 at the
  accepted 100%/150% matrix.

The design contract is frozen; future edits to this area require a demonstrated
regression or a separately approved design revision.

## Evidence boundary

- Automated tests create temporary SQLite databases and synthetic UI state.
- Screenshot output is written only to ignored review/runtime trees.
- No production invoice, mailbox, credential, API key, authorization code, or
  `email_report.html` is read or committed as acceptance evidence.
- A source-matched disposable PyInstaller build is test evidence only until its
  packaged Windows flow is actually exercised.
- Chromium smoke validates browser contracts but is not a substitute for an
  Android device or WeChat WebView.

## Supported screenshot / browser matrix

The desktop capture utility covers:

- Dashboard: normal / empty / error
- Review: normal / empty / no-selection
- Import: mail / local / mobile normal, mobile active and error
- Export: normal / empty / blocked
- Mailbox: normal / empty / missing authorization / disabled / long text
- AI: normal / empty / multiple profiles
- Runtime, privacy, data/backup and About
- API Key dialog: normal / empty / error / long text

Mobile browser smoke covers the local page contract, PDF.js review, images,
OFD/broken-PDF fallbacks, long filenames and representative mobile viewports.

Each accepted desktop capture records requested and actual geometry, Qt mode,
scale, device-pixel ratio, logical DPI, source commit, timestamp, and state
validation.

## Acceptance rules

The following evidence classes must not be conflated:

- synthetic/offscreen geometry PASS != human visual PASS;
- Chromium smoke PASS != Android/WeChat PASS;
- local self-check PASS != LAN/phone reachability PASS;
- firewall rule present != LAN access confirmed;
- source tests PASS != packaged Windows acceptance.

## Manual gates still required for v0.1.6 mobile closure

1. **Packaged Windows firewall flow** using the source-matched
   `InvoiceHub.exe`: missing-rule state → explicit UAC authorization → exact
   Private/TCP program rule → real-phone GET 200 → real upload/import.
2. **Android Chrome/system browser**: file/gallery/camera, PDF first-page
   thumbnail, multipage navigation, user zoom, long filename, sticky CTA and
   real upload/import.
3. **WeChat**: compact limitation guidance plus the real external-browser
   handoff for the full PDF flow.

The existing installer/upgrade/uninstall and broader physical-Windows release
gates continue to apply when a formal release candidate is cut.

## Freeze terminology

- **Historical Design Baseline source implementation:** complete.
- **v0.1.6 Interaction Design:** frozen by the 2026-08-22 addendum once its
  source assertions are green.
- **UI-MOBILE-DESKTOP-001:** closed / frozen.
- **MOBILE-NET-001:** open pending packaged Windows + real phone evidence.
- **UI-UPLOAD-001:** open pending Android/WeChat evidence.
- **Automated regression gate:** green only when the current PR HEAD succeeds.
- **Release/UI acceptance:** not yet approved; PR #107 remains Draft until the
  real-device gates above are complete.
