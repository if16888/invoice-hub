# Settings / Preview Semantic Test Plan

## Automated

```powershell
python -m unittest tests/test_settings_preview_semantic_contract.py
python -m unittest tests/test_settings_preview_matrix_contract.py
python -m unittest tests/test_settings_baseline_pipeline.py
python -m unittest discover -v -s tests -p "test_*.py"
python -m compileall -q scripts tests
python scripts/check_repo_privacy.py
python scripts/check_public_export.py .
git diff --check
```

## Native Windows

```powershell
python scripts/dev/run_settings_preview_matrix.py
```

Validate all 16 screenshots manually. The focused matrix is required because
focus, hover, disabled, and semantic status states are not represented in the
standard page-layout screenshot matrix.
