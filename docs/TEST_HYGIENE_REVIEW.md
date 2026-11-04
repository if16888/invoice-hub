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

## Remaining cleanup candidate

`tests/test_preview_pdf_nav_log_001.py` remains active because it contains substantial preview, navigation, privacy-log, and integration coverage. The former `TestMultiPageCompatibility` section has been removed; the file is now 1,338 lines.

The module should not be deleted wholesale. The remaining optional cleanup is to split it by responsibility; page-mode behavior is already covered by the PDF preview controller tests.

## Active-test rule

Tests under `tests/` should verify public or observable behavior. Source inspection is acceptable only for explicit repository-policy checks where runtime behavior cannot express the contract, and those exceptions should state why.

Historical tests must not force production UI to retain hidden widgets,
layouts, frames, or compatibility-only objects after the visible feature has
moved on. When a test relies on `hasattr(...)`, `inspect(...)`, or
`findChild(...)` for a retired implementation detail, replace it with a
behavior-level assertion or archive it. Do not satisfy it by creating another
hidden compatibility surface in production code.
