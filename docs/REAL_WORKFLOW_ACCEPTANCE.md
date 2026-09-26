# Invoice Hub v0.1.8 — real workflow acceptance

This document defines the **final release acceptance boundary** for the current v0.1.8 source line.

The exact release SHA is not hard-coded here. The authoritative candidate is the SHA recorded by the final release audit and must remain identical across exact-SHA CI, Windows pre-tag audit, and manual acceptance evidence.

## Evidence classes

Do not conflate these evidence types:

| Evidence | What it proves | What it does not prove |
| --- | --- | --- |
| Local preflight | source, unit and HCI checks pass in the developer environment | packaged Windows behavior |
| PR / exact-SHA CI | repository tree passes required automated gates | physical Windows typography or upgrade UX |
| Windows build audit | PyInstaller/Inno build, startup, payload hygiene, install/start/uninstall | real user upgrade/persistence and visual quality |
| Synthetic UI matrix | layout/control contracts at declared sizes/scales | human visual balance on a physical display |
| Physical Windows acceptance | real installer, upgrade, restart persistence and DPI behavior | Android/WeChat mobile behavior |
| Real-device mobile acceptance | LAN/firewall/browser/upload behavior | broader desktop release quality |

A final stable GO needs the evidence classes that correspond to features claimed as supported.

## Privacy boundary

Acceptance data must be disposable and synthetic unless the release owner is performing a private local-only personal workflow check.

Never commit or upload:

- real invoices, receipts, itineraries or claim packages;
- production SQLite databases;
- mailbox authorization codes or API keys;
- real email addresses, tax IDs or company consumption data;
- local private paths or full tokenized URLs.

Public evidence records only pass/fail, counts, timings and interaction findings.

## Automated acceptance required on the final candidate

Run local preflight before remote CI:

~~~powershell
python scripts/dev/run_local_ci_preflight.py
~~~

The exact final candidate must then have successful authority for:

- source/privacy/architecture gates;
- all unit-test shards;
- HCI acceptance;
- release metadata and public-export contracts;
- Qt startup warning regression;
- repeated PDF preview replacement without the known QPdfLinkModel/null-document warning.

The native geometry lane remains diagnostic when the hosted environment cannot satisfy the physical desktop geometry contract.

## Windows pre-tag release audit

Dispatch **Windows Build & Release** in pre-tag audit mode from the exact master candidate.

The audit must verify:

- checked-out SHA equals the candidate and origin/master;
- PyInstaller frozen build succeeds;
- packaged embedded version matches the source release line;
- portable startup stays within the configured startup threshold;
- payload contains required license/notice files and no runtime/private/browser payload;
- Inno Setup installer builds successfully;
- historical installer ownership recovery remains safe;
- generated installer completes install → startup → uninstall;
- SHA256 evidence is generated for release artifacts.

Pre-tag audit evidence must not create a release tag or public GitHub Release.

## Controlled physical-Windows workflow

Use a disposable Windows profile/data directory.

1. Clean-install the final source-matched installer.
2. Launch with an empty database and verify Dashboard/Settings empty states.
3. Import a synthetic PDF/OFD/image/ZIP set.
4. Review a synthetic invoice and edit one field.
5. Repeatedly switch between PDF records and confirm no Qt PDF/font warnings.
6. Associate synthetic proof material.
7. Create a reimbursement group and add approved invoices.
8. Run export preflight and export the synthetic reimbursement package.
9. Open the Excel file and a copied attachment.
10. Close and restart; confirm records, settings, claim group and layout persist.
11. Upgrade from the previous stable installed release using a disposable profile.
12. Uninstall and reinstall; verify the documented user-data retention policy.
13. Review the main pages at physical Windows 100%, 125% and 150% scaling.

## Mobile acceptance when mobile upload is a supported release claim

For a packaged Windows build:

- start a mobile upload session;
- confirm the intended Private-network firewall flow;
- open the session from a real phone on the same LAN;
- upload PDF/image files and confirm they enter the desktop import/review flow;
- stop the session and confirm the URL/token no longer works.

Android Chrome/system browser is the minimum real-device browser target. WeChat-specific behavior should be claimed only after its own acceptance is complete.

## GO / NO-GO

Stable GO requires all of the following on one final candidate:

- local preflight PASS;
- exact-SHA CI PASS;
- Windows pre-tag audit PASS;
- physical Windows clean install / upgrade / restart / DPI acceptance PASS;
- no P0/P1 data-loss, privacy, export-integrity or GUI-lifecycle blocker;
- known limitations documented in release notes.

If the candidate changes after any release-blocking fix, previous exact-SHA evidence is stale and the required gates must be rerun for the new candidate.
