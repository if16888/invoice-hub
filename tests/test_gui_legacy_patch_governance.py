from pathlib import Path
import unittest


GUI_DIR = Path(__file__).resolve().parents[1] / "scripts" / "invoice_fetch" / "gui"
FROZEN_PATCH_MODULES = {
    "business_pages_baseline.py",
    "review_feedback_fixes.py",
    "review_settings_issue_fixes.py",
    "review_toolbar_filter_fixes.py",
    "review_workspace_baseline.py",
    "settings_baseline.py",
    "settings_pages_baseline.py",
}


class GuiLegacyPatchGovernanceTests(unittest.TestCase):
    def test_historical_patch_module_inventory_does_not_grow(self):
        discovered = {
            path.name
            for path in GUI_DIR.rglob("*.py")
            if path.name.endswith(("_fixes.py", "_baseline.py"))
        }
        self.assertEqual(
            discovered,
            FROZEN_PATCH_MODULES,
            "GUI legacy patch modules changed; update the frozen inventory and policy deliberately.",
        )

    def test_common_settings_is_a_standard_component(self):
        self.assertTrue((GUI_DIR / "settings_common.py").is_file())
        self.assertFalse((GUI_DIR / "settings_common_fixes.py").exists())


if __name__ == "__main__":
    unittest.main()
