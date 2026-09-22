import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.workers import ClaimExportWorker


class ClaimExportWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_qt_timer_keeps_ticking_during_slow_claim_export(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            export_dir = root / "exports" / "synthetic"
            export_dir.mkdir(parents=True)

            ticks = {"count": 0}
            timer = QTimer()
            timer.setInterval(20)
            timer.timeout.connect(lambda: ticks.__setitem__("count", ticks["count"] + 1))

            def slow_export(**kwargs):
                time.sleep(0.30)
                return export_dir

            worker = ClaimExportWorker(
                db_path=db_path,
                claim_id=1,
                project_root=root,
                runtime_dir=root,
                include_to_review=False,
                reimbursement_config={},
                export_root=root / "exports",
            )
            results = []
            errors = []
            worker.result.connect(results.append)
            worker.error.connect(errors.append)

            with patch(
                "scripts.invoice_fetch.claim_export.export_claim_package",
                side_effect=slow_export,
            ):
                timer.start()
                worker.start()
                deadline = time.monotonic() + 5
                while worker.isRunning() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.01)
                worker.wait(1000)
                self.app.processEvents()
                timer.stop()

            self.assertFalse(worker.isRunning())
            self.assertEqual(errors, [])
            self.assertEqual(results, [export_dir])
            self.assertGreaterEqual(
                ticks["count"],
                5,
                "Qt event loop should remain responsive while export runs in worker",
            )


if __name__ == "__main__":
    unittest.main()
