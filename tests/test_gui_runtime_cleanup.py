from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parent.parent


class GuiRuntimeCleanupTests(unittest.TestCase):
    def test_preview_top_level_helpers_are_defined_once(self):
        path = REPO_ROOT / "scripts" / "invoice_fetch" / "gui" / "preview_mixin.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]

        for helper in ("_runtime_dir_compat", "check_has_qt_pdf", "get_qt_pdf_classes"):
            self.assertEqual(names.count(helper), 1, f"{helper} must have exactly one top-level definition")

    def test_workers_do_not_catch_baseexception(self):
        path = REPO_ROOT / "scripts" / "invoice_fetch" / "gui" / "workers.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        handlers = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id == "BaseException"
        ]
        self.assertEqual(handlers, [], f"workers.py must not swallow BaseException: {handlers}")

    def test_export_migration_worker_propagates_system_exit(self):
        try:
            from scripts.invoice_fetch.gui.workers import ExportMigrationWorker
        except ImportError as exc:
            raise unittest.SkipTest(f"PySide6 unavailable: {exc}")

        worker = ExportMigrationWorker(Path("unused-source"), Path("unused-destination"))
        with patch(
            "scripts.invoice_fetch.export_paths.migrate_legacy_exports",
            side_effect=SystemExit(42),
        ):
            with self.assertRaises(SystemExit) as ctx:
                worker.run()
        self.assertEqual(ctx.exception.code, 42)


if __name__ == "__main__":
    unittest.main()
