"""Semantic, monochrome Qt icon provider used across visible product navigation."""

from PySide6.QtWidgets import QApplication, QStyle


class IconProvider:
    _SEMANTIC = {
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
        "success": QStyle.SP_DialogApplyButton,
        "warning": QStyle.SP_MessageBoxWarning,
        "danger": QStyle.SP_MessageBoxCritical,
        "info": QStyle.SP_MessageBoxInformation,
    }

    @classmethod
    def icon(cls, semantic: str):
        app = QApplication.instance()
        style = app.style() if app is not None else None
        return style.standardIcon(cls._SEMANTIC.get(semantic, QStyle.SP_FileIcon)) if style else None

