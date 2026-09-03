"""Guard against growth of known GUI patch and compatibility debt."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_DIR = REPO_ROOT / "scripts" / "invoice_fetch" / "gui"
SERVICES_PATH = REPO_ROOT / "scripts" / "invoice_fetch" / "services.py"
FORBIDDEN_PATCH_SUFFIXES = (
    "_closure.py",
    "_fix.py",
    "_fixes.py",
    "_baseline_pipeline.py",
)
WIDGET_CONSTRUCTORS = frozenset(
    {
        "QWidget",
        "QFrame",
        "QGroupBox",
        "QHBoxLayout",
        "QVBoxLayout",
        "QGridLayout",
        "QFormLayout",
    }
)

# Exact snapshot of existing debt. When an entry is removed from production,
# this baseline must shrink in the same PR.
FROZEN_PATCH_MODULES = frozenset(
    {
        "business_pages_baseline.py",
        "design_baseline_styles.py",
        "design_v1_review_task_closure.py",
        "hci_v1_closure.py",
        "review_baseline_pipeline.py",
        "review_detail_closure.py",
        "review_detail_width_fix.py",
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
        "settings_legacy_contract.py",
        "settings_pages_baseline.py",
        "settings_semantic_status_contract.py",
        "settings_token_contract.py",
        "ui_visibility_contracts.py",
    }
)

# Filled from the current production tree. The scanner is deliberately narrow:
# it requires a compatibility/legacy marker, widget construction, and an
# explicit hidden-state call in the same function scope.
FROZEN_HIDDEN_COMPAT_SCOPES = frozenset(
    {
        "preview_mixin.py:PreviewMixin._init_legacy_preview_controls",
        "preview_mixin.py:PreviewMixin._init_overlay_toolbar",
        "review_legacy_contract.py:install_claim_summary_layout_compatibility",
        "settings_dialog.py:SettingsDialog._init_settings_home_page",
    }
)


def find_patch_modules(
    gui_dir: Path = GUI_DIR,
    tracked_modules: frozenset[str] = FROZEN_PATCH_MODULES,
) -> set[str]:
    """Return forbidden modules plus explicitly tracked historical debt."""
    findings: set[str] = set()
    for path in gui_dir.rglob("*.py"):
        relative = path.relative_to(gui_dir).as_posix()
        if path.name.endswith(FORBIDDEN_PATCH_SUFFIXES):
            findings.add(relative)
        elif relative in tracked_modules:
            # Existing generic contract/baseline names remain tracked debt,
            # without banning every future domain *_contract.py/*_baseline.py.
            findings.add(relative)
    return findings


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_hidden_call(call: ast.Call) -> bool:
    name = _call_name(call)
    if name == "hide":
        return True
    if name == "setVisible" and call.args:
        return isinstance(call.args[0], ast.Constant) and call.args[0].value is False
    if name == "setHidden" and call.args:
        return isinstance(call.args[0], ast.Constant) and call.args[0].value is True
    return False


def _scope_has_hidden_compatibility(node: ast.AST) -> bool:
    names: list[str] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.append(node.name)
    calls: list[ast.Call] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.append(child.id)
        elif isinstance(child, ast.Attribute):
            names.append(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            names.append(child.value)
        elif isinstance(child, ast.Call):
            calls.append(child)
    marked = any(
        "legacy" in value.lower() or "compat" in value.lower()
        for value in names
    )
    constructs_widget = any(_call_name(call) in WIDGET_CONSTRUCTORS for call in calls)
    hides_widget = any(_is_hidden_call(call) for call in calls)
    return marked and constructs_widget and hides_widget


def _function_scopes(tree: ast.Module):
    def walk(body: list[ast.stmt], prefix: str = ""):
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{node.name}" if prefix else node.name
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield name, node
                yield from walk(node.body, name)

    yield from walk(tree.body)


def find_hidden_compat_scopes(gui_dir: Path = GUI_DIR) -> set[str]:
    """Find obvious hidden compatibility UI construction at function scope."""
    findings: set[str] = set()
    for path in gui_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(gui_dir).as_posix()
        for scope, node in _function_scopes(tree):
            if _scope_has_hidden_compatibility(node):
                findings.add(f"{relative}:{scope}")
    return findings


def find_main_imports(services_path: Path = SERVICES_PATH) -> set[str]:
    """Return services imports that point at the CLI entry-point module."""
    tree = ast.parse(
        services_path.read_text(encoding="utf-8"),
        filename=str(services_path),
    )
    findings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports_main_name = any(alias.name == "__main__" for alias in node.names)
            if (
                module == "__main__"
                or module.endswith(".__main__")
                or imports_main_name
            ):
                findings.add(f"line {node.lineno}: from {'.' * node.level}{module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "__main__" or alias.name.endswith(".__main__"):
                    findings.add(f"line {node.lineno}: import {alias.name}")
    return findings


def check_architecture_policy(
    gui_dir: Path = GUI_DIR,
    *,
    patch_baseline: frozenset[str] = FROZEN_PATCH_MODULES,
    hidden_baseline: frozenset[str] = FROZEN_HIDDEN_COMPAT_SCOPES,
    services_path: Path = SERVICES_PATH,
) -> list[str]:
    """Return policy violations without changing the source tree."""
    errors: list[str] = []
    current_modules = find_patch_modules(gui_dir, patch_baseline)
    new_modules = sorted(current_modules - patch_baseline)
    if new_modules:
        errors.append("新增 GUI 补丁式模块: " + ", ".join(new_modules))
    stale_modules = sorted(patch_baseline - current_modules)
    if stale_modules:
        errors.append(
            "GUI 历史债已删除；请在同一 PR 更新 FROZEN_PATCH_MODULES: "
            + ", ".join(stale_modules)
        )

    current_hidden = find_hidden_compat_scopes(gui_dir)
    new_hidden = sorted(current_hidden - hidden_baseline)
    if new_hidden:
        errors.append("新增 hidden compatibility UI: " + ", ".join(new_hidden))
    stale_hidden = sorted(hidden_baseline - current_hidden)
    if stale_hidden:
        errors.append(
            "hidden compatibility 历史债已删除；请在同一 PR 更新 "
            "FROZEN_HIDDEN_COMPAT_SCOPES: "
            + ", ".join(stale_hidden)
        )
    main_imports = sorted(find_main_imports(services_path))
    if main_imports:
        errors.append("services 不得依赖 CLI __main__: " + ", ".join(main_imports))
    return errors


def main() -> int:
    errors = check_architecture_policy()
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print(
        "[PASS] Architecture policy: "
        f"patch_modules={len(find_patch_modules())}, "
        f"hidden_compat_scopes={len(find_hidden_compat_scopes())}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
