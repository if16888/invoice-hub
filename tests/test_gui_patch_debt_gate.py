import tempfile
import unittest
from pathlib import Path

from scripts.check_gui_patch_debt import find_patch_debt


class GuiPatchDebtGateTests(unittest.TestCase):
    def test_finds_nested_and_extended_patch_module_names(self):
        with tempfile.TemporaryDirectory() as td:
            gui_dir = Path(td) / "gui"
            review_dir = gui_dir / "review"
            review_dir.mkdir(parents=True)
            names = (
                "future_fixes.py",
                "future_closure_v2.py",
                "review_baseline_pipeline.py",
                "ui_visibility_contracts.py",
            )
            for name in names:
                (review_dir / name).touch()
            (review_dir / "invoice_table_model.py").touch()

            self.assertEqual(
                find_patch_debt(gui_dir),
                {f"review/{name}" for name in names},
            )


if __name__ == "__main__":
    unittest.main()
