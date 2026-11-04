# Test hygiene review

## Removed from active CI

The former `tests/test_rc_fixes.py` mixed release-candidate naming, source-code string assertions, and unrelated behavioral tests.

Four source-shape assertions were moved to `tests_archive/source_contracts_v013.py` because they checked method names or exact source snippets rather than observable behavior:

- manual attachment refresh referenced a specific callback name;
- manual evidence persistence referenced exact DB method-call text;
- supporting-document refresh referenced an exact helper-call string;
- GUI export referenced an exact keyword argument in source text.

The twelve behavioral regressions remain active in focused files:

- `tests/test_attachment_naming_and_excel.py`
- `tests/test_review_action_regressions.py`

## Preview test split (completed)

The former 1,338-line `tests/test_preview_pdf_nav_log_001.py` has been split by responsibility:

- `tests/test_preview_navigation_ui.py` — focus protection, file/page navigation, navigation focus stability, compact detail panel
- `tests/test_link_downloader_recovery.py` — downloader cache and attempt-limit regressions
- `tests/test_attachment_backfill.py` — attachment skip, duplicate backfill, seller fallback, claimed-invoice protection

The `TestMultiPageCompatibility` section was removed earlier; page-mode behavior remains covered by the PDF preview controller tests.

## Active-test rule

Tests under `tests/` should verify public or observable behavior. Source inspection is acceptable only for explicit repository-policy checks where runtime behavior cannot express the contract, and those exceptions should state why.

Historical tests must not force production UI to retain hidden widgets,
layouts, frames, or compatibility-only objects after the visible feature has
moved on. When a test relies on `hasattr(...)`, `inspect(...)`, or
`findChild(...)` for a retired implementation detail, replace it with a
behavior-level assertion or archive it. Do not satisfy it by creating another
hidden compatibility surface in production code.
