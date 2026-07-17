# Settings / Preview Semantic Validation

This change adds a focused native Windows matrix for the remaining Settings
status and PreviewToolbar interaction states.

Run from an interactive Windows desktop session:

```powershell
python scripts/dev/run_settings_preview_matrix.py
```

Expected result:

- 16 screenshots
- 8 states at 1920×1080 / 100%
- 8 states at 1366×768 / 150%
- every case reports `PASS`
- every screenshot exists and is non-empty

States:

- Settings success, warning, danger, and info
- Preview normal, hover, keyboard focus, and disabled

Artifacts remain local under `.codex-artifacts/design-v1/` and must not be
committed.

The whole-application UI freeze remains conditional until this focused matrix
and GitHub Actions both pass.
