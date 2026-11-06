"""Semantic, monochrome Qt icon provider used across visible product navigation.

Priority:
1. assets/icons/<name>.svg — project-bundled monochrome SVGs (18×18, stroke-based)
2. QStyle.SP_* — system fallback so the app never crashes on missing assets
"""

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

from .design_tokens import DESIGN_V1_COLORS

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

    _cache: dict[tuple[str, bool], QIcon] = {}

    @classmethod
    def icon(cls, semantic: str) -> QIcon:
        svg_path = _ASSETS_ICONS / f"{semantic}.svg"
        if svg_path.exists():
            from .dark_mode import dark_stylesheet, prefers_dark

            if QApplication.instance() is None:
                return QIcon(str(svg_path))
            key = (semantic, prefers_dark())
            if key in cls._cache:
                return QIcon(cls._cache[key])
            from PySide6.QtCore import QByteArray, Qt
            from PySide6.QtGui import QPainter, QPixmap
            from PySide6.QtSvg import QSvgRenderer

            source = svg_path.read_bytes()
            icon = QIcon()
            for mode, state, role in (
                (QIcon.Normal, QIcon.Off, "text_secondary"),
                (QIcon.Normal, QIcon.On, "accent"),
                (QIcon.Active, QIcon.Off, "accent"),
                (QIcon.Active, QIcon.On, "accent"),
                (QIcon.Selected, QIcon.Off, "accent"),
                (QIcon.Selected, QIcon.On, "accent"),
                (QIcon.Disabled, QIcon.Off, "muted"),
                (QIcon.Disabled, QIcon.On, "muted"),
            ):
                color = DESIGN_V1_COLORS[role]
                if key[1]:
                    color = dark_stylesheet(color)
                renderer = QSvgRenderer(QByteArray(source.replace(b"currentColor", color.encode("ascii"))))
                pixmap = QPixmap(72, 72)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                pixmap.setDevicePixelRatio(4)
                icon.addPixmap(pixmap, mode, state)
            cls._cache[key] = icon
            return QIcon(icon)
        app = QApplication.instance()
        style = app.style() if app is not None else None
        sp = _FALLBACK.get(semantic, QStyle.SP_FileIcon)
        return style.standardIcon(sp) if style else QIcon()
