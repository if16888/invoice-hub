import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_architecture_policy import (
    check_architecture_policy,
    find_hidden_compat_scopes,
    find_main_imports,
    find_patch_modules,
    find_retired_production_symbols,
)


class ArchitecturePolicyTests(unittest.TestCase):
    def test_current_production_baseline_passes(self):
        self.assertEqual(check_architecture_policy(), [])

    def test_retired_review_symbols_are_absent_from_production(self):
        self.assertEqual(find_retired_production_symbols(), set())

    def test_retired_review_symbol_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            production_root = Path(td) / "invoice_fetch"
            production_root.mkdir()
            (production_root / "legacy.py").write_text(
                "def apply_review_detail_closure(page):\n"
                "    return page\n",
                encoding="utf-8",
            )

            findings = find_retired_production_symbols(production_root)

            self.assertEqual(
                findings,
                {"legacy.py:1:apply_review_detail_closure"},
            )

    def test_new_forbidden_patch_module_fails(self):
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

            errors = check_architecture_policy(
                gui_dir,
                patch_baseline=frozenset(),
                hidden_baseline=frozenset(),
            )
            self.assertEqual(len(errors), 1)
            for name in names:
                with self.subTest(name=name):
                    self.assertIn(f"review/{name}", errors[0])

    def test_stale_patch_module_baseline_fails(self):
        with tempfile.TemporaryDirectory() as td:
            gui_dir = Path(td) / "gui"
            gui_dir.mkdir()

            errors = check_architecture_policy(
                gui_dir,
                patch_baseline=frozenset({"retired_closure.py"}),
                hidden_baseline=frozenset(),
            )

            self.assertEqual(len(errors), 1)
            self.assertIn("更新 FROZEN_PATCH_MODULES", errors[0])
            self.assertIn("retired_closure.py", errors[0])

    def test_stale_hidden_compatibility_baseline_fails(self):
        with tempfile.TemporaryDirectory() as td:
            gui_dir = Path(td) / "gui"
            gui_dir.mkdir()

            errors = check_architecture_policy(
                gui_dir,
                patch_baseline=frozenset(),
                hidden_baseline=frozenset(
                    {"retired.py:build_legacy_compatibility_widget"}
                ),
            )

            self.assertEqual(len(errors), 1)
            self.assertIn("更新 FROZEN_HIDDEN_COMPAT_SCOPES", errors[0])
            self.assertIn(
                "retired.py:build_legacy_compatibility_widget", errors[0]
            )

    def test_hidden_compatibility_scope_is_detected_but_normal_hide_is_not(self):
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

            self.assertEqual(
                check_architecture_policy(
                    gui_dir,
                    patch_baseline=frozenset(),
                    hidden_baseline=frozenset(
                        {"legacy_adapter.py:build_legacy_compatibility_widget"}
                    ),
                ),
                [],
            )

    def test_generic_domain_contract_and_baseline_names_are_not_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            gui_dir = Path(td) / "gui"
            gui_dir.mkdir()
            (gui_dir / "invoice_contract.py").touch()
            (gui_dir / "pricing_baseline.py").touch()

            self.assertEqual(find_patch_modules(gui_dir), set())
            self.assertEqual(
                check_architecture_policy(
                    gui_dir,
                    patch_baseline=frozenset(),
                    hidden_baseline=frozenset(),
                ),
                [],
            )

    def test_services_cannot_import_main_relative_or_absolute(self):
        with tempfile.TemporaryDirectory() as td:
            services_path = Path(td) / "services.py"
            services_path.write_text(
                "from .__main__ import run_local\n"
                "import scripts.invoice_fetch.__main__ as cli\n",
                encoding="utf-8",
            )

            findings = find_main_imports(services_path)

            self.assertEqual(len(findings), 2)
            self.assertTrue(any("from .__main__" in item for item in findings))
            self.assertTrue(
                any("import scripts.invoice_fetch.__main__" in item for item in findings)
            )

            services_path.write_text(
                "from . import __main__\n"
                "from scripts.invoice_fetch import __main__ as cli_main\n",
                encoding="utf-8",
            )
            self.assertEqual(len(find_main_imports(services_path)), 2)

    def test_importing_services_does_not_load_main(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import scripts.invoice_fetch.services; "
                "assert 'scripts.invoice_fetch.__main__' not in sys.modules",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
