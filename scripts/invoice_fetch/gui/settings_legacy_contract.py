"""Compatibility bridge for app-owned Settings refresh objects.

The Golden Page migration removes the old AI summary surface. ``app.py`` still
addresses the old empty label directly, so keep one hidden live label until the
refresh logic is moved into the final AI component. The obsolete summary
attribute is removed so guarded refresh code skips it and the old UI does not
remain part of the product tree.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget


def install_ai_refresh_compatibility(page: QWidget) -> None:
    """Keep the direct empty-label reference alive and remove the old summary."""
    if page is None or page.property("aiRefreshCompatibilityInstalled"):
        return
    window = page.window()
    if not hasattr(window, "settings_tabs"):
        return

    ai_page = window.settings_tabs.widget(1)
    if ai_page is None:
        return

    page.setProperty("aiRefreshCompatibilityInstalled", True)

    empty_label = QLabel("", ai_page)
    empty_label.setObjectName("LegacyAiEmptyLabelAdapter")
    empty_label.hide()
    window.lbl_settings_ai_empty = empty_label

    if hasattr(window, "settings_ai_summary_strip"):
        delattr(window, "settings_ai_summary_strip")


__all__ = ["install_ai_refresh_compatibility"]
