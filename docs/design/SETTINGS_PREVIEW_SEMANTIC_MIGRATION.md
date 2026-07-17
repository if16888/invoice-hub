# Settings / Preview Semantic Migration

This PR intentionally closes the runtime styling gap without reopening the
frozen page layout.

## Completed in this PR

- Settings status labels are normalized to plain text and semantic tone
  properties at the baseline-pipeline boundary.
- Settings semantic colors are rendered from Design v1 tokens.
- The actual `PreviewToolbar` component contains no product color literals and
  derives normal, hover, focus, pressed, and disabled states from the UI theme.
- A focused 16-case native Windows validation matrix covers Settings status and
  PreviewToolbar interaction states at 100% and 150% scale.

## Still tracked by Issue #66

- Remove legacy rich-text color strings directly from the large Settings dialog
  implementation once that file is split into smaller controllers/views.
- Delete the unreachable legacy toolbar block after the early return in
  `preview_mixin.py`.

Those structural deletions are deliberately not hidden inside this visual-state
change because they touch large legacy files and require separate regression
review.
