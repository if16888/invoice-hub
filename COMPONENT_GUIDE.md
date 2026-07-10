# Invoice Hub UI Components

## Stable

- `PageHeader`: consistent page title, description, and right-side actions.
- `SummaryStrip`: compact page-level metrics and filter entry points.
- `SectionCard`: shared titled content surface.
- `CommandBar`: primary, secondary, and more action hierarchy.
- `EntityList`: list-oriented group and account selection.
- `ReadOnlyDetailPanel`: stacked read-only values.
- `ElidedValueLabel`: long-value display with tooltip.
- `StatusLine`: one status and one contextual action.
- `SecondaryNavStack`: settings secondary navigation.
- `MoreMenuButton`: fixed-size low-frequency action menu.

## New Sprint 2 primitives

- `EmptyStateCard`: title, short explanation, and one relevant action.
- `LoadingCard`: compact non-technical loading state.
- `InlineErrorCard`: inline failure message with optional retry action.

## Reference-led primitives

- `SelectableSourceCard`: one selected import source with a title and one-line explanation.
- `CompactFieldRow`: compact read-only label/value/action row for bounded settings pages.
- `ActivityTimeline`: product-facing activity summaries; never raw runtime log lines.
- `DangerZone`: explicit surface for destructive operations and their confirmation path.

## Tokens

`scripts/invoice_fetch/gui/styles.py` owns layout, spacing, control, radius,
typography, and color tokens. New shared components and core surfaces use those
tokens instead of page-local color values or arbitrary dimensions.

## Review Rules

- Pages must use `PageHeader`, `SectionCard`, and shared command components instead of one-off frames.
- A page has at most one visual primary action.
- Status colors come from the shared stylesheet; page code must not invent status colors.
- Low-frequency and destructive actions belong in More menus or a danger zone.

## Deprecated / Compatibility

- Legacy log page object remains for compatibility but is not a first-level navigation entry.
- Legacy material card objects remain hidden while StatusLine owns the visible material workflow.
- Hidden compatibility widgets must not be added to visible layouts or reparented across layouts.
