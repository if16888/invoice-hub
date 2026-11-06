# Design Baseline Token Authority

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

## Approved shared values (`design-v1.4-desktop`)

- Page background: `#F5F5F7`
- Navigation background: `#EFEFF2`
- Surface: `#FFFFFF`
- Selection background: `#EAF2FC`
- Main text: `#1D1D1F`
- Secondary text: `#55555D`; muted text: `#63636A`
- Accent and focus ring: `#0066CC`
- Success: `#16803C`
- Warning: `#B54708`
- Danger: `#B42318`
- Page title: `20px`; body: `13px`; secondary text: `12px`
- Standard control height: `32px`; compact toolbar controls: `28px`
- Page margin: `24px`

New shared UI code must import from `design_tokens.py` rather than introduce a
second token dictionary.

The UI kit is the last layer of the canonical stylesheet, after the legacy
baseline. Legacy neutral text literals are normalized to these tokens before
rendering. The opt-in dark theme derives its colors from the same stylesheet;
`INVOICE_HUB_THEME=dark` enables it. Native Windows system theme detection is
not enabled by this change.
