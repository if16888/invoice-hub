"""One-shot test-hygiene migration for PR #101.

This script is intentionally idempotent. It removes obsolete skipped tests,
merges provably duplicate GUI contracts, and prevents path/export tests from
opening synthetic PDFs as an unrelated side effect.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return raw.decode("utf-8").replace("\r\n", "\n"), newline


def _write(path: Path, text: str, newline: str) -> None:
    normalized = text.replace("\r\n", "\n")
    payload = normalized if newline == "\n" else normalized.replace("\n", "\r\n")
    path.write_bytes(payload.encode("utf-8"))


def _function_span(text: str, name: str):
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            start = node.lineno - 1
            if node.decorator_list:
                start = min(item.lineno for item in node.decorator_list) - 1
            end = node.end_lineno
            while end < len(lines) and not lines[end].strip():
                end += 1
            return start, end, lines
    return None


def _remove_functions(text: str, names: set[str]) -> str:
    while True:
        found = None
        for name in names:
            span = _function_span(text, name)
            if span is not None:
                found = (name, *span)
                break
        if found is None:
            return text
        _name, start, end, lines = found
        text = "".join(lines[:start] + lines[end:])


def _mutate_function(text: str, name: str, mutate) -> str:
    span = _function_span(text, name)
    if span is None:
        return text
    start, end, lines = span
    original = "".join(lines[start:end])
    updated = mutate(original)
    return "".join(lines[:start]) + updated + "".join(lines[end:])


def _replace_once_or_already(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if marker in text:
        return text
    raise RuntimeError(f"expected hygiene seam not found: {marker}")


def _clean_column_filters(path: Path) -> bool:
    text, newline = _read(path)
    before = text
    text = _remove_functions(
        text,
        {"test_filtering_and_load_all_cover_rows_beyond_first_100"},
    )
    ast.parse(text)
    if text != before:
        _write(path, text, newline)
        return True
    return False


def _clean_ihds09(path: Path) -> bool:
    text, newline = _read(path)
    before = text
    text = _remove_functions(
        text,
        {
            "test_mailbox_page_uses_master_detail",
            "test_mailbox_page_has_no_visible_summary_strip",
            "test_api_key_dialog_supports_show_hide",
        },
    )
    text = _replace_once_or_already(
        text,
        '''                self.assertEqual(window.settings_mailbox_list.width(), 280)\n                self.assertFalse(hasattr(window, "stat_box_overview"))\n                self.assertTrue(hasattr(window, "lbl_detail_email"))\n''',
        '''                self.assertEqual(window.settings_mailbox_list.width(), 280)\n                self.assertFalse(hasattr(window, "stat_box_overview"))\n                self.assertTrue(hasattr(window, "lbl_detail_email"))\n                self.assertTrue(hasattr(window, "lbl_detail_server"))\n                self.assertTrue(hasattr(window, "lbl_settings_mailbox_scan_result"))\n''',
        'hasattr(window, "lbl_settings_mailbox_scan_result")',
    )
    text = _replace_once_or_already(
        text,
        '''        dialog.btn_show_hide.setChecked(True)\n        self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Normal)\n        self.assertTrue(is_visual_primary(dialog.btn_save_and_test))\n''',
        '''        dialog.btn_show_hide.setChecked(True)\n        self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Normal)\n        dialog.btn_show_hide.setChecked(False)\n        self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Password)\n        self.assertTrue(is_visual_primary(dialog.btn_save_and_test))\n''',
        'dialog.btn_show_hide.setChecked(False)',
    )
    ast.parse(text)
    if text != before:
        _write(path, text, newline)
        return True
    return False


def _isolate_gui_preview(func: str, *, quality: bool = False) -> str:
    marker = "window._update_document_preview = Mock()"
    if marker not in func:
        if quality:
            old = '''                        window = InvoiceReviewApp(db_path, splash=None)\n                        try:\n                            window._deferred_init()\n'''
            new = '''                        window = InvoiceReviewApp(db_path, splash=None)\n                        try:\n                            # This test does not exercise embedded preview rendering.\n                            # Avoid opening the synthetic PDF so Windows can remove the\n                            # temporary directory deterministically.\n                            window._update_document_preview = Mock()\n                            window._deferred_init()\n'''
        else:
            old = '''                    window = InvoiceReviewApp(db_path, splash=None)\n                    try:\n                        window._deferred_init()\n'''
            new = '''                    window = InvoiceReviewApp(db_path, splash=None)\n                    try:\n                        # Path-resolution behavior is independent of embedded PDF\n                        # rendering. Do not open the synthetic attachment in QPdfDocument;\n                        # that file handle would make Windows temp cleanup nondeterministic.\n                        window._update_document_preview = Mock()\n                        window._deferred_init()\n'''
        if old not in func:
            raise RuntimeError("preview isolation seam not found")
        func = func.replace(old, new, 1)

    if "window.pdf_document.close()" not in func:
        indent = 28 if quality else 24
        spaces = " " * indent
        old = f'''{spaces}if hasattr(window, "db") and window.db is not None:\n{spaces}    window.db.close()\n'''
        new = f'''{spaces}if hasattr(window, "pdf_document") and window.pdf_document is not None:\n{spaces}    window.pdf_document.close()\n{spaces}if hasattr(window, "db") and window.db is not None:\n{spaces}    window.db.close()\n'''
        if old not in func:
            raise RuntimeError("GUI cleanup seam not found")
        func = func.replace(old, new, 1)

    old_catch = '''        except (ImportError, RuntimeError, OSError) as e:\n            self.skipTest(f"Skipping GUI test: {e}")\n'''
    new_catch = '''        except Exception as e:\n            if isinstance(e, (ImportError, RuntimeError)):\n                self.skipTest(f"Skipping GUI test: {e}")\n            raise\n'''
    if old_catch in func:
        func = func.replace(old_catch, new_catch, 1)
    elif "except Exception as e:" not in func or "OSError" in func:
        raise RuntimeError("GUI skip seam not found")
    return func


def _clean_claim_groups(path: Path) -> bool:
    text, newline = _read(path)
    before = text
    text = _remove_functions(
        text,
        {"test_gui_shell_version_about_and_more_menu_actions"},
    )
    for name in (
        "test_gui_open_attachment_resolves_nested_relative_path",
        "test_gui_open_attachment_resolves_mainrepo_nested_relative_path",
        "test_gui_open_attachment_recovers_from_stale_filename_only_path",
    ):
        text = _mutate_function(text, name, _isolate_gui_preview)
    text = _mutate_function(
        text,
        "test_claim_quality_report_gui_prompt",
        lambda func: _isolate_gui_preview(func, quality=True),
    )
    ast.parse(text)
    if '@unittest.skip("cross-workflow toolbar widgets were replaced by QAction commands")' in text:
        raise RuntimeError("obsolete toolbar skip survived hygiene pass")
    if text != before:
        _write(path, text, newline)
        return True
    return False


def main() -> int:
    changed = []
    candidates = (
        (ROOT / "tests/test_claim_groups.py", _clean_claim_groups),
        (ROOT / "tests/test_gui_column_filters.py", _clean_column_filters),
        (ROOT / "tests/test_ihds09.py", _clean_ihds09),
    )
    for path, cleaner in candidates:
        if cleaner(path):
            changed.append(path.relative_to(ROOT).as_posix())
    print("test_hygiene_round2_changed=" + (",".join(changed) if changed else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
