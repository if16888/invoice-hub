"""Prevent new PR/acceptance-named GUI patch modules from accumulating."""

from __future__ import annotations

import sys
from pathlib import Path


GUI_DIR = Path(__file__).resolve().parents[1] / "scripts" / "invoice_fetch" / "gui"
DEBT_MARKERS = ("_fixes", "_closure", "_baseline", "_contract")

# Existing debt is frozen.  Entries may be deleted or moved into domain modules,
# but additions require changing this gate and should be rejected in review.
FROZEN_DEBT = frozenset(
    {
        "business_pages_baseline.py",
        "design_baseline_styles.py",
        "design_v1_review_task_closure.py",
        "hci_v1_closure.py",
        "review_baseline_pipeline.py",
        "review_detail_closure.py",
        "review_feedback_fixes.py",
        "review_legacy_contract.py",
        "review_settings_issue_fixes.py",
        "review_table_width_contract.py",
        "review_toolbar_filter_fixes.py",
        "review_workspace_baseline.py",
        "review_workspace_closure.py",
        "selection_surface_contract.py",
        "settings_baseline.py",
        "settings_baseline_pipeline.py",
        "settings_feedback_fixes.py",
        "settings_legacy_contract.py",
        "settings_pages_baseline.py",
        "settings_semantic_status_contract.py",
        "settings_token_contract.py",
        "ui_visibility_contracts.py",
    }
)


def find_patch_debt(gui_dir: Path = GUI_DIR) -> set[str]:
    """Return relative paths for patch/acceptance-named GUI modules."""
    return {
        path.relative_to(gui_dir).as_posix()
        for path in gui_dir.rglob("*.py")
        if any(marker in path.name for marker in DEBT_MARKERS)
    }


def main() -> int:
    current = find_patch_debt()
    additions = sorted(current - FROZEN_DEBT)
    if additions:
        print("[FAIL] 检测到新的 GUI 补丁式模块：")
        for name in additions:
            print(f"  - {name}")
        print("请把新行为放入 review/settings/import/preview 等领域模块。")
        return 1
    print(f"[PASS] GUI 补丁债冻结；现存 {len(current)} 个，未新增")
    return 0


if __name__ == "__main__":
    sys.exit(main())
