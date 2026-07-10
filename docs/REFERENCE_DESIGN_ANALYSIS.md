# Reference Design Analysis

Source: `https://designergpt.replit.app/pages/d291269cce84af7db797dd3dfa241b62.html`

Captured on 2026-07-11 at 1920 x 1080 and 1440 x 900. The reference is a
lightweight desktop workbench, not a mobile web page.

## Observed Visual System

| Area | Observed pattern | Invoice Hub translation |
| --- | --- | --- |
| App shell | Quiet left rail, compact top bar, large neutral canvas | Keep five primary destinations; use a compact top tool surface rather than page-specific toolbars. |
| Navigation | Approx. 166 px visible rail with soft selected fill and small count pills | Use 176-184 px expanded width and 56 px collapsed width. Counts remain muted metadata. |
| Content | Header begins close to the left content edge; cards align to one grid | Use one `PageHeader`, 16 px page margin, and 12 px section gap. |
| Cards | White surface, thin gray border, modest 8-10 px radius, virtually no shadow | Prefer surfaces and border hierarchy over web-style floating shadows. |
| Metrics | Small label, strong number, quiet caption | Restrict summary strips to actionable page-level metrics. |
| Main action | One wide cyan-blue action inside the task card | Keep a single visual primary action per page and do not make toolbar actions primary. |
| Lists | Dense, separated rows with right-aligned metadata | Use compact rows and show one status plus only necessary metadata. |
| Empty space | Intentional workspace breathing room after compact content | Do not stretch one-line cards to fill a page; use an explicit empty state when content is absent. |

## Directly Applicable Patterns

- Neutral app background, white work surfaces, thin borders, and restrained status colors.
- A clear reading order: header, summary, primary work, then secondary context.
- One dominant task card on the dashboard and compact supporting cards.
- Distinct list/detail responsibilities and concise timeline-style activity summaries.
- Soft selected navigation state instead of saturated icons or heavy tabs.

## Desktop Adaptations

- PySide6 needs fixed minimum sizes and high-DPI-safe tokens rather than CSS
  viewport units.
- The invoice review page remains a table, preview, and decision panel; its
  higher information density is intentional and does not mirror the reference
  dashboard one-to-one.
- Menus and task dialogs replace hover-only web interactions.
- Context panels use bounded widths so that tables and previews retain room at
  1366 px.

## Patterns Not To Copy

- The reference's large unused lower canvas is not appropriate for invoice
  lists, settings details, or export checks.
- Web-style wide primary buttons should not span a full card unless the card
  represents one explicit task.
- Decorative activity content must not replace real Invoice Hub records.
- Browser-specific footer subscription and support surfaces do not belong in
  the desktop workbench.
