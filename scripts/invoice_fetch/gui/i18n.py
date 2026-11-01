"""Qt standard-button translations for the Chinese desktop UI."""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator


def install_chinese_translations(app) -> QTranslator | None:
    """Load Qt's zh_CN catalog so built-in buttons and dialogs stay Chinese."""
    try:
        translator = QTranslator()
        loaded = translator.load(
            QLocale(QLocale.Chinese, QLocale.China),
            "qtbase",
            "_",
            QLibraryInfo.path(QLibraryInfo.TranslationsPath),
        )
        if not loaded:
            return None
        app.installTranslator(translator)
        return translator
    except Exception:
        # Startup probes and tests may stub the application object.
        return None
