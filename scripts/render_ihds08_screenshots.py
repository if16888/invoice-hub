"""Render IHDS-08 review screenshots without starting network services."""
import os
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


def main():
    app = QApplication.instance() or QApplication([])
    output = Path("artifacts/ihds08")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        window = InvoiceReviewApp(Path(td) / "preview.db")
        window._switch_main_page("imports")
        for width, height in ((1366, 768), (1600, 900), (1920, 1080)):
            def save(name):
                app.processEvents()
                window.grab().save(str(output / f"{width}x{height}_{name}.png"))

            window.resize(width, height); window.show(); app.processEvents()
            window._nav_collapsed_manual = False; window._apply_workbench_metrics(width, height)
            window._select_import_source("mobile"); save("01_expanded_mobile_idle")
            window._nav_collapsed_manual = True; window._apply_workbench_metrics(width, height); save("02_collapsed_mobile_idle")
            session = SimpleNamespace(upload_url="http://192.168.1.8:8765/u/review", host="192.168.1.8", port=8765)
            window.mobile_upload_controller.started.emit(session); save("03_mobile_active_qr")
            window.mobile_upload_controller.stats_changed.emit({"accepted": 2, "duplicate": 0, "failed": 0, "imported": 2})
            save("04_mobile_completed")
            window.mobile_upload_controller.stopped.emit()
            window._select_import_source("local"); save("05_local_import_task")
            window._select_import_source("mail"); save("06_mail_scan_task")
        window.close()
    print(f"rendered {len(list(output.glob('*.png')))} screenshots to {output}")


if __name__ == "__main__":
    main()
