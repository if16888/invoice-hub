"""Shared Qt 6 display policy for every desktop launch path."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


def configure_high_dpi_platform() -> None:
    """Keep fractional display scaling before constructing QApplication.

    Qt 6 enables high-DPI scaling and pixmaps by default, so the deprecated
    Qt 5 application attributes are unnecessary. An explicit Qt environment
    override retains Qt's normal precedence. A running application must not
    have its process-wide scaling policy changed.
    """
    if QGuiApplication.instance() is not None:
        return
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
