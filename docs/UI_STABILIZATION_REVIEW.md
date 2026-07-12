# v0.1.5 UI stabilization review

Review target: source tree at `4e14d0246d7a5acf8df6fb9aa7a768c8621594d9`.

## Evidence and scope

- Reproducible source screenshots are produced by `scripts/dev/capture_ui_matrix.py`.
- This review used an isolated temporary SQLite database and synthetic UI state only. It did not read, copy, or export user invoices, credentials, or runtime data.
- Captures are written to `runtime/ui-review/`, which is Git-ignored. The local matrix includes dashboard, import/mobile, export, mailbox, AI, and API-key surfaces at 1366x768, 1920x1080, and a 2560x1440 / 150% Qt-scale run.
- The headless capture host has no CJK font, so its screenshot glyphs are square placeholders. Geometry, control bounds, visual hierarchy, and image placement remain useful; Chinese typography needs final inspection on a source-matched Windows build.

## 4e14d02 claim verification

| Claim | Code and automated evidence | Result |
| --- | --- | --- |
| API-key action is local validation, not a remote connection test | `ApiKeyDialog` labels the primary action `保存并校验配置`; `test_api_key_local_validation_copy_is_truthful` rejects success/test/connected copy. | Pass |
| Mobile upload has visible idle / starting / active / error states and safe close ordering | `MobileUploadSessionPanel` has four pages; `closeEvent` requires `shutdown()` before `db.close()`; focused lifecycle tests pass. | Automated pass; physical Windows lifecycle still pending |
| Navigation uses bundled SVG icons | `IconProvider` resolves `assets/icons/<semantic>.svg` first; all primary navigation SVGs share `viewBox="0 0 18 18"`; fallback is only for missing assets. | Pass |
| AI profiles adapt to zero, one, and many profiles | `test_ai_profile_list_visibility_follows_count` verifies empty state, hidden single-profile list, and visible two-profile list. | Pass |
| Mailbox detail is a master-detail surface with long-value support | Long name/address/server fields use `ElidedTextLabel` plus tooltip; actions are after read-only details. | Automated pass; physical 150% typography pending |
| Export preflight is structured and compact | Checklist uses `ChecklistRow`, top-aligned cards, and a content-width primary export button. | Pass |
| DPI checks use real page containers instead of font-only buttons | Three isolated `QApplication` subprocess checks create an `InvoiceReviewApp`, switch pages, and verify visible button/line-edit/combo geometry at 100%, 125%, and 150% Qt scale. | Pass in offscreen Qt; Windows-display confirmation pending |

## Screenshot matrix

The current local output directory is `runtime/ui-review/`. Each invocation records page, state, requested scale, effective device-pixel ratio, logical DPI, and output filename in a JSON manifest.

Useful commands:

```powershell
python scripts/dev/capture_ui_matrix.py --page all --state normal --size 1366x768 --scale 1
python scripts/dev/capture_ui_matrix.py --page imports-mobile --state mobile-active --size 2560x1440 --scale 1.5
python scripts/dev/capture_ui_matrix.py --page settings-mailbox --state long-text --size 1920x1080 --scale 1.25
```

Qt applies scale at `QApplication` creation, so the tool intentionally accepts one `--scale` per invocation rather than producing incorrectly labelled screenshots.

## Findings

### Clipping

No visible `QPushButton`, `QLineEdit`, or `QComboBox` exceeded the 1366x768 source window bounds in the isolated 100%, 125%, or 150% checks. Long mailbox values preserve a tooltip for the complete value.

### Information duplication

No remaining duplicated mailbox summary strip was found in the current settings surface. The import sidebar presents the unified activity timeline rather than a separate persistent mailbox-only summary.

### Remaining acceptance gaps

1. The locally installed application window is `Invoice Hub v0.1.3`, not a build of `4e14d02`; it cannot prove the current source's Windows rendering.
2. Headless Qt captures do not substitute for a physical Windows 125%/150% display with installed CJK fonts.
3. Clean install, in-place upgrade, uninstall, and a user-data workflow have not been executed in this review because they require a source-matched package and would alter local application state.

Therefore this review does **not** recommend UI Freeze yet.

## PR50-02 follow-up

- The capture utility now has an explicit page/state support matrix and rejects unsupported combinations before creating a screenshot or manifest.
- Every accepted capture validates the constructed state and records requested/actual size, mode (`offscreen` or `windows`), Qt platform, scale, source commit, and UTC timestamp.
- The geometry helper checks visible button, tool-button, combo, line-edit, and elided-value contracts. Offscreen runs explicitly skip non-ASCII glyph-width assertions when the host lacks a CJK font; the `windows` mode is reserved for physical Windows font/DPI evidence.
- AI settings now calls the action `校验配置` and describes local-only validation; the old method name remains only as a compatibility alias.

The source-matched PyInstaller build was produced in a disposable TEMP directory from the PR worktree tip; executable SHA256 was recorded locally as `CDD874FA650962E9DEDCDEEC831BBB67F41EAF305B6E5C7F2050EB9ABFE78C00`. The build emitted non-fatal warnings for unavailable Playwright hidden imports and was not copied into Git or an installed application directory.
