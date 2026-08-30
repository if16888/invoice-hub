import tempfile
import unittest
from pathlib import Path

from scripts.check_architecture_policy import (
    check_architecture_policy,
    find_hidden_compat_scopes,
    find_patch_modules,
)


class ArchitecturePolicyTests(unittest.TestCase):
    def test_current_legacy_baseline_passes(self):
        self.assertEqual(check_architecture_policy(), [])

    def test_finds_nested_forbidden_patch_modules(self):
        with tempfile.TemporaryDirectory() as td:
            gui_dir = Path(td) / "gui"
            review_dir = gui_dir / "review"
            review_dir.mkdir(parents=True)
            names = (
                "foo_closure.py",
                "foo_v12_closure.py",
                "foo_fix.py",
                "foo_fixes.py",
                "review_baseline_pipeline.py",
            )
            for name in names:
                (review_dir / name).touch()
            (review_dir / "invoice_table_model.py").touch()

            self.assertEqual(
                find_patch_modules(gui_dir),
                {f"review/{name}" for name in names},
            )

            errors = check_architecture_policy(gui_dir)
            self.assertEqual(len(errors), 1)
            for name in names:
                with self.subTest(name=name):
                    self.assertIn(f"review/{name}", errors[0])

    def test_finds_obvious_hidden_compatibility_widget(self):
        with tempfile.TemporaryDirectory() as td:
            gui_dir = Path(td) / "gui"
            gui_dir.mkdir()
            (gui_dir / "legacy_adapter.py").write_text(
                "from PySide6.QtWidgets import QWidget\n"
                "def build_legacy_compatibility_widget():\n"
                "    widget = QWidget()\n"
                "    widget.hide()\n",
                encoding="utf-8",
            )
            (gui_dir / "normal_panel.py").write_text(
                "def update_busy_indicator(widget):\n"
                "    widget.hide()\n",
                encoding="utf-8",
            )

            self.assertEqual(
                find_hidden_compat_scopes(gui_dir),
                {"legacy_adapter.py:build_legacy_compatibility_widget"},
            )


if __name__ == "__main__":
    unittest.main()
