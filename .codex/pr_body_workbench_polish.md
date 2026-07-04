## Scope
- tighten review workbench visual density without changing the main layout structure
- compact the right-side summary/action area and preview toolbar
- improve preview empty states and thumbnail behavior
- harden preview selection/PDF rebinding sync
- update GUI regression tests to match the shipped workbench behavior

## Validation
- python -m unittest tests.test_workbench_layout -v
- python -m unittest tests.test_preview_workbench_ui -v
- python -m unittest tests.test_detail_panel_ui -v
- python -m unittest tests.test_gui_column_filters -v
- python -m unittest tests.test_ui_preview_helpers -v
- python -m unittest discover -v -s tests -p "test_*.py"
- python -m compileall -q scripts tests
- git diff --check
- python scripts/check_repo_privacy.py
- python scripts/check_public_export.py .

## Manual QA
- 1920x1080 review workbench
- right-side detail header/buttons/tabs density
- preview empty state for missing original
- row selection syncing detail and preview
- preview focus mode and shortcuts
