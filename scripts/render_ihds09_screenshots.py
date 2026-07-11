"""Render the nine IHDS-09 visual-review checkpoints."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from scripts.invoice_fetch.gui.api_key_dialog import ApiKeyDialog
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


def main():
    app = QApplication.instance() or QApplication([])
    output = Path("artifacts/ihds09"); output.mkdir(parents=True, exist_ok=True)
    base_font = QFont(app.font())
    with tempfile.TemporaryDirectory() as td:
        window = InvoiceReviewApp(Path(td) / "preview.db")

        def save(name, width=1600, height=900):
            window.resize(width, height); window.show(); app.processEvents(); app.processEvents()
            window.grab().save(str(output / name))

        window._switch_main_page("overview"); save("01_1600x900_dashboard_100.png")
        window._switch_main_page("settings"); window.settings_tabs.setCurrentIndex(0); save("02_1600x900_mailbox_100.png")
        window.settings_tabs.setCurrentIndex(1); save("03_1600x900_ai_integration_100.png")

        dialog = ApiKeyDialog("DeepSeek", window, has_existing_key=True)
        dialog.show(); app.processEvents(); dialog.grab().save(str(output / "04_1600x900_api_key_dialog_100.png")); dialog.close()

        window._switch_main_page("imports"); window._set_import_source_selected("mobile")
        controller = window.mobile_upload_controller
        controller.host_options = [SimpleNamespace(label="WLAN · 192.168.31.251", host="192.168.31.251")]
        session = SimpleNamespace(upload_url="http://192.168.31.251:54867/u/review", host="192.168.31.251", port=54867)
        controller.started.emit(session); controller.stats_changed.emit({"accepted": 2, "duplicate": 0, "failed": 0, "imported": 2})
        save("05_1600x900_mobile_active_100.png")
        window._switch_main_page("export"); save("06_1600x900_export_100.png")

        scaled = QFont(base_font); scaled.setPointSizeF(max(9.0, scaled.pointSizeF()) * 1.25); app.setFont(scaled)
        window._switch_main_page("imports"); window._apply_workbench_metrics(1366, 768); save("07_1366x768_imports_125.png", 1366, 768)
        window._switch_main_page("settings"); window.settings_tabs.setCurrentIndex(0); save("08_1366x768_settings_125.png", 1366, 768)

        scaled150 = QFont(base_font); scaled150.setPointSizeF(max(9.0, scaled150.pointSizeF()) * 1.5); app.setFont(scaled150)
        window.resize(1920, 1080); window._apply_workbench_metrics(1920, 1080); window._switch_main_page("settings"); window.settings_tabs.setCurrentIndex(0)
        save("09_1920x1080_mailbox_150.png", 1920, 1080)
        app.setFont(base_font)
        window.close()
    print(f"rendered {len(list(output.glob('*.png')))} screenshots to {output}")


if __name__ == "__main__":
    main()
