"""Qt policy and fractional scaling checks independent of a Windows display."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class HighDpiTests(unittest.TestCase):
    def run_policy_probe(self, *, scale="1", rounding=None):
        env = os.environ.copy()
        for name in ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_AUTO_SCREEN_SCALE_FACTOR",
                     "QT_SCALE_FACTOR_ROUNDING_POLICY", "QT_ENABLE_HIGHDPI_SCALING"):
            env.pop(name, None)
        env.update(QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=scale, PYTHONUTF8="1")
        if rounding is not None:
            env["QT_SCALE_FACTOR_ROUNDING_POLICY"] = rounding
        code = """
import json
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget
from scripts.invoice_fetch.gui.high_dpi import configure_high_dpi_platform
QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)
configure_high_dpi_platform()
configure_high_dpi_platform()
app = QApplication([])
window = QWidget()
window.resize(400, 300)
window.show()
app.processEvents()
before = QGuiApplication.highDpiScaleFactorRoundingPolicy().name
configure_high_dpi_platform()
print(json.dumps({'policy': before,
                  'policy_after': QGuiApplication.highDpiScaleFactorRoundingPolicy().name,
                  'dpr': window.devicePixelRatioF(), 'logical_width': window.width()}))
window.close()
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("must be called before", result.stderr)
        self.assertNotIn("DeprecationWarning", result.stderr)
        return json.loads(result.stdout)

    def test_default_policy_is_passthrough_and_repeated_calls_are_safe(self):
        observed = self.run_policy_probe()
        self.assertEqual(observed["policy"], "PassThrough")
        self.assertEqual(observed["policy_after"], "PassThrough")

    def test_explicit_qt_environment_override_remains_effective(self):
        observed = self.run_policy_probe(rounding="Round")
        self.assertEqual(observed["policy"], "Round")
        self.assertEqual(observed["policy_after"], "Round")

    def test_fractional_scaling_preserves_logical_geometry(self):
        for scale in ("1", "1.25", "1.5", "2"):
            with self.subTest(scale=scale):
                observed = self.run_policy_probe(scale=scale)
                self.assertAlmostEqual(observed["dpr"], float(scale))
                self.assertEqual(observed["logical_width"], 400)

    def test_all_desktop_launchers_configure_policy_before_application(self):
        class StopBeforeWidgets(Exception):
            pass

        for module_name, launcher in (
            ("app", "start_gui_app"),
            ("startup_lifecycle", "start_first_paint_deferred_gui_app"),
            ("startup_probe", "start_first_paint_startup_probe"),
        ):
            with self.subTest(launcher=launcher):
                module = importlib.import_module("scripts.invoice_fetch.gui." + module_name)
                calls = []
                def application(*args):
                    calls.append("application")
                    raise StopBeforeWidgets
                with patch.object(module, "configure_high_dpi_platform", side_effect=lambda: calls.append("policy")), \
                     patch.object(module, "QApplication", side_effect=application):
                    with self.assertRaises(StopBeforeWidgets):
                        getattr(module, launcher)(Path("synthetic.db"))
                self.assertEqual(calls, ["policy", "application"])


if __name__ == "__main__":
    unittest.main()
