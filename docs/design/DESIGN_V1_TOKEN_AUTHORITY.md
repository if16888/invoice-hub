# Design Baseline v1.0 Token Authority

`design_tokens.py` is the only product-wide source for shared visual colors,
typography sizes and common geometry metrics.

## Runtime contract

1. Legacy `styles.COLOR_TOKENS` is treated as a compatibility mapping only.
2. Before the application stylesheet is installed, compatibility keys are
   overwritten from `DESIGN_V1_COLORS`.
3. The core stylesheet and the Design v1 override layer are rebuilt together.
4. The main window records `designBaselineTokenVersion` for diagnostics.
5. Page archetype margins and gaps are read from `DESIGN_V1_METRICS`.

Page-specific geometry, such as Review detail widths or table-column minimums,
remains owned by the corresponding page contract and is not promoted to a
product-wide token unless it is genuinely shared.

## Approved shared values

- Page background: `#F7F8FA`
- Surface: `#FFFFFF`
- Selection background: `#EFF6FF`
- Accent: `#2563EB`
- Success: `#16803C`
- Warning: `#B54708`
- Danger: `#B42318`
- Page title: `22px`
- Standard control height: `34px`
- Page margin: `24px`

New shared UI code must import from `design_tokens.py` rather than introduce a
second token dictionary.
