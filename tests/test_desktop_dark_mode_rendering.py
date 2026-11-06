"""Check actual widget colors, including legacy labels, in the opt-in theme."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui import dark_mode, workbench_settings
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


def _contrast(first, second):
    def luminance(color):
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class DesktopDarkModeRenderingTests(unittest.TestCase):
    def test_real_shell_keeps_secondary_text_readable_after_theme_reapplication(self):
        app = QApplication.instance() or QApplication([])
        original_palette, original_style = app.palette(), app.styleSheet()
        original_filter = getattr(app, "_invoice_hub_dark_style_filter", None)
        original_themed_qss = getattr(app, "_dark_applied_qss", None)

        def settle():
            for _ in range(6):
                app.processEvents()

        try:
            with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"INVOICE_HUB_THEME": "dark"}), \
                    patch.object(workbench_settings, "RUNTIME_DIR", Path(td)), \
                    patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value={}):
                path = Path(td) / "theme.db"
                settings = workbench_settings.workbench_settings()
                settings.setValue("migration/legacy_qsettings_v1", True)
                settings.sync()
                with InvoiceDB(path) as db:
                    invoice = db.insert_invoice({"invoice_number": "DARK-1", "seller_name": "Synthetic seller",
                                                 "total_amount": "20.00", "review_status": "to_review"})
                    claim = db.create_claim_group("Synthetic claim")
                    self.assertTrue(db.add_invoice_to_claim(claim, invoice))
                window = InvoiceReviewApp(path)
                try:
                    window._deferred_init()
                    window.resize(1440, 900)
                    window.show()
                    surface = QColor(dark_mode.DARK_COLOR_MAP["#FFFFFF"])
                    for _ in range(2):
                        dark_mode.apply_app_theme(app)
                        for page in ("review", "export"):
                            window._switch_main_page(page)
                            settle()
                            labels = [label for label in window.findChildren(QLabel)
                                      if label.isVisible() and label.property("class") in {
                                          "DetailFieldKey", "FieldLabel", "SectionHint", "CompactStatCardTitle"}]
                            self.assertGreater(len(labels), 3, page)
                            for label in labels:
                                color = label.palette().color(QPalette.WindowText)
                                with self.subTest(page=page, label=label.text(), color=color.name()):
                                    self.assertGreaterEqual(_contrast(color, surface), 4.5)
                            if page == "review":
                                more = window._detail_panel.btn_more_source
                                self.assertTrue(more.isVisible())
                                self.assertGreaterEqual(_contrast(more.palette().color(QPalette.ButtonText), surface), 4.5)
                finally:
                    window.close()
                    window.deleteLater()
                    app.sendPostedEvents(None, QEvent.DeferredDelete)
                    settle()
        finally:
            current_filter = getattr(app, "_invoice_hub_dark_style_filter", None)
            if current_filter is not original_filter:
                app.removeEventFilter(current_filter)
                current_filter.deleteLater()
                if original_filter is None:
                    del app._invoice_hub_dark_style_filter
                else:
                    app._invoice_hub_dark_style_filter = original_filter
            if original_themed_qss is None:
                if hasattr(app, "_dark_applied_qss"):
                    del app._dark_applied_qss
            else:
                app._dark_applied_qss = original_themed_qss
            app.setStyleSheet(original_style)
            app.setPalette(original_palette)
            settle()
