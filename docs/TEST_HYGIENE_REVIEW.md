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

## Additional cleanup candidate

`tests/test_preview_pdf_nav_log_001.py` remains active because it contains substantial preview, navigation, privacy-log, and integration coverage. Its small `TestMultiPageCompatibility` section should be removed during a dedicated split: those tests currently simulate `hasattr()` branches using local mock classes instead of calling the production page-mode selector.

The whole 1,900-line module should not be deleted merely to remove those three weak tests. The safe next cleanup is to split it by responsibility and replace the simulated page-mode checks with a production helper test.

## Active-test rule

Tests under `tests/` should verify public or observable behavior. Source inspection is acceptable only for explicit repository-policy checks where runtime behavior cannot express the contract, and those exceptions should state why.
