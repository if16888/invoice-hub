"""Semantic, monochrome Qt icon provider used across visible product navigation.

Priority:
1. assets/icons/<name>.svg — project-bundled monochrome SVGs (18×18, stroke-based)
2. QStyle.SP_* — system fallback so the app never crashes on missing assets
"""

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

_ASSETS_ICONS = Path(__file__).parent / "assets" / "icons"

_FALLBACK = {
    "dashboard": QStyle.SP_DesktopIcon,
    "review": QStyle.SP_FileDialogContentsView,
    "import": QStyle.SP_DialogOpenButton,
    "export": QStyle.SP_DialogSaveButton,
    "settings": QStyle.SP_ComputerIcon,
    "mail": QStyle.SP_MessageBoxInformation,
    "local_file": QStyle.SP_DirOpenIcon,
    "mobile": QStyle.SP_ArrowUp,
    "help": QStyle.SP_DialogHelpButton,
    "collapse": QStyle.SP_TitleBarShadeButton,
    "expand": QStyle.SP_TitleBarUnshadeButton,
    "more": QStyle.SP_FileDialogDetailedView,
    "copy": QStyle.SP_FileDialogNewFolder,
    "show": QStyle.SP_DialogYesButton,
    "hide": QStyle.SP_DialogNoButton,
    "filter": QStyle.SP_ArrowDown,
    "success": QStyle.SP_DialogApplyButton,
    "warning": QStyle.SP_MessageBoxWarning,
    "danger": QStyle.SP_MessageBoxCritical,
    "info": QStyle.SP_MessageBoxInformation,
}


class IconProvider:
    """Return a QIcon for a semantic name.

    Looks up a built-in SVG first so that all navigation icons are visually
    uniform regardless of OS theme, DPI, or Qt style. Falls back to the
    system's standard pixmap when an SVG is not available.
    """

    @classmethod
    def icon(cls, semantic: str) -> QIcon:
        svg_path = _ASSETS_ICONS / f"{semantic}.svg"
        if svg_path.exists():
            return QIcon(str(svg_path))
        app = QApplication.instance()
        style = app.style() if app is not None else None
        sp = _FALLBACK.get(semantic, QStyle.SP_FileIcon)
        return style.standardIcon(sp) if style else QIcon()
