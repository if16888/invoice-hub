# Design Baseline v1.0 closure

This change set closes the remaining source-level gaps found in the post-merge Design 1.0 review.

## Closed gaps

- Design token typography now matches the 14 px section-title contract.
- Legacy brand/status literals are normalized during canonical stylesheet assembly.
- Export filename readiness is computed from the selected claim's approved invoices instead of being permanently green.
- Export checklist rows use semantic Qt icons and state properties rather than Unicode check/cross glyphs and inline colors.
- Settings migrations now run through one deterministic, guarded pipeline instead of five independent zero-delay callbacks.

## Remaining manual gate

Physical Windows review at 100%, 125%, and 150% scaling remains required before declaring UI Freeze.
