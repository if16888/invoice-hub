from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scripts import check_startup_time
from scripts.invoice_fetch.gui import startup_probe


class StartupProbeMetricContractTests(unittest.TestCase):
    def _valid_metrics(self) -> dict[str, object]:
        return {
            "PROBE_CONTRACT": check_startup_time.PROBE_CONTRACT,
            "QT_PAINT_EVENT_COMPLETED": True,
            "APP_INIT_MS": 120,
            "DB_OPEN_MS": 10,
            "MAIN_WINDOW_SHOW_MS": 600,
            "STARTUP_MS": 750,
            "GUI_INIT_MS": 250,
            "FIRST_LOAD_MS": 80,
            "FIRST_PAINT_MS": 630,
            "TOTAL_STARTUP_MS": 750,
            "PROCESS_WALL_MS": 820,
            "PROCESS_RETURN_CODE": 0,
        }

    def test_metric_builder_marks_qt_paint_contract_and_total(self):
        metrics = startup_probe.build_startup_probe_metrics(
            app_init_ms=120,
            db_open_ms=10,
            gui_init_ms=250,
            first_load_ms=80,
            main_window_show_ms=600,
            first_paint_ms=630,
        )
        self.assertEqual(metrics["PROBE_CONTRACT"], startup_probe.PROBE_CONTRACT)
        self.assertIs(metrics["QT_PAINT_EVENT_COMPLETED"], True)
        self.assertEqual(metrics["FIRST_PAINT_MS"], 630)
        self.assertEqual(metrics["TOTAL_STARTUP_MS"], 750)
        self.assertEqual(metrics["STARTUP_MS"], 750)

    def test_checker_accepts_valid_qt_first_paint_evidence(self):
        self.assertEqual(check_startup_time._probe_truth_errors(self._valid_metrics()), [])

    def test_checker_rejects_legacy_zero_paint_probe(self):
        metrics = self._valid_metrics()
        metrics.update(
            {
                "PROBE_CONTRACT": "",
                "QT_PAINT_EVENT_COMPLETED": False,
                "MAIN_WINDOW_SHOW_MS": 0,
                "FIRST_PAINT_MS": 0,
                "STARTUP_MS": 120,
                "TOTAL_STARTUP_MS": 120,
            }
        )
        errors = check_startup_time._probe_truth_errors(metrics)
        self.assertTrue(any("PROBE_CONTRACT" in item for item in errors))
        self.assertTrue(any("QT_PAINT_EVENT_COMPLETED" in item for item in errors))
        self.assertTrue(any("FIRST_PAINT_MS" in item for item in errors))

    def test_checker_rejects_paint_before_show(self):
        metrics = self._valid_metrics()
        metrics["MAIN_WINDOW_SHOW_MS"] = 700
        metrics["FIRST_PAINT_MS"] = 630
        errors = check_startup_time._probe_truth_errors(metrics)
        self.assertTrue(any("cannot precede" in item for item in errors))

    def test_checker_rejects_nonzero_probe_process_exit(self):
        metrics = self._valid_metrics()
        metrics["PROCESS_RETURN_CODE"] = 2
        errors = check_startup_time._probe_truth_errors(metrics)
        self.assertTrue(any("exit with code 0" in item for item in errors))

    def test_checker_rejects_logical_total_that_disagrees_with_qt_paint_total(self):
        metrics = self._valid_metrics()
        metrics["STARTUP_MS"] = 700
        errors = check_startup_time._probe_truth_errors(metrics)
        self.assertTrue(any("STARTUP_MS must equal" in item for item in errors))


class StartupProbeExecutionBoundaryTests(unittest.TestCase):
    def test_public_gui_launcher_routes_flag_and_environment_to_first_paint_probe(self):
        source = Path("scripts/invoice_fetch/gui/__init__.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("INVOICE_HUB_STARTUP_PROBE") == "1"', source)
        self.assertIn("start_first_paint_startup_probe", source)
        self.assertIn("if is_probe:", source)

    def test_first_paint_probe_constructs_full_normal_workbench_path(self):
        source = inspect.getsource(startup_probe.start_first_paint_startup_probe)
        self.assertIn("StartupSplash()", source)
        self.assertIn("InvoiceReviewApp", source)
        self.assertIn("startup_probe=False", source)
        self.assertIn("session.start()", source)
        self.assertIn("app.exec()", source)

    def test_paint_is_confirmed_after_event_filter_returns(self):
        source = inspect.getsource(startup_probe.StartupProbeSession.eventFilter)
        self.assertIn("QEvent.Paint", source)
        self.assertIn("QTimer.singleShot(0, self._finish_after_paint)", source)
        finish_source = inspect.getsource(startup_probe.StartupProbeSession._finish_after_paint)
        builder_source = inspect.getsource(startup_probe.build_startup_probe_metrics)
        self.assertIn("QT_PAINT_EVENT_COMPLETED", builder_source)
        self.assertIn("_write_metrics", finish_source)
        self.assertIn("self._app.exit(0)", finish_source)

    def test_release_checker_does_not_overclaim_display_presentation(self):
        source = Path("scripts/check_startup_time.py").read_text(encoding="utf-8")
        self.assertNotIn("MAIN_WINDOW_SHOW_MS (首帧渲染展现)", source)
        self.assertNotIn("FIRST_PAINT_MS (物理渲染完成)", source)
        self.assertNotIn("PHYSICAL_PAINT_OBSERVED", source)
        self.assertIn("主窗口Show事件", source)
        self.assertIn("首次Qt Paint已返回", source)
        self.assertIn("OS compositor/display presentation is not asserted", source)

    def test_checker_decodes_probe_output_as_utf8_explicitly(self):
        source = inspect.getsource(check_startup_time.run_probe)
        self.assertIn('encoding="utf-8"', source)
        self.assertIn('errors="replace"', source)

    def test_python_probe_observes_nonzero_first_paint_end_to_end(self):
        with tempfile.TemporaryDirectory(prefix="invoice-hub-startup-probe-") as td:
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["INVOICE_HUB_TEST_MODE"] = "1"
            env["INVOICE_HUB_RUNTIME_DIR"] = str(Path(td) / "runtime")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/check_startup_time.py",
                    "--python",
                    "--threshold",
                    "60000",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )

        combined = (result.stdout or "") + (result.stderr or "")
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn(
            f"Probe contract: {check_startup_time.PROBE_CONTRACT}",
            combined,
        )
        self.assertIn("Qt paint event completed: True", combined)
        match = re.search(r"FIRST_PAINT_MS \(首次Qt Paint已返回\)\s+\|\s+(\d+)", combined)
        self.assertIsNotNone(match, combined)
        self.assertGreater(int(match.group(1)), 0)


if __name__ == "__main__":
    unittest.main()
