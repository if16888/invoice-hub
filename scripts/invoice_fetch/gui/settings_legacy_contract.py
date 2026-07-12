"""Compatibility bridge for app-owned Settings refresh objects.

The Golden Page migration replaces the visible AI tree, but ``app.py`` still
updates two legacy presentation objects during refresh.  Keep lightweight,
hidden live objects behind those references until the refresh logic is moved
into the final AI component.  This avoids retaining the old visible UI tree.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

from .ui_components import SummaryStrip


def install_ai_refresh_compatibility(page: QWidget) -> None:
    """Replace deleted legacy AI references with hidden live adapters."""
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

    summary = SummaryStrip(ai_page)
    summary.setObjectName("LegacyAiSummaryAdapter")
    for key, title in (
        ("enabled", "AI 状态"),
        ("provider", "Provider"),
        ("model", "模型"),
        ("key", "API Key"),
        ("paused", "会话状态"),
    ):
        summary.add_metric(key, title, "—", state="muted")
    summary.hide()
    window.settings_ai_summary_strip = summary


__all__ = ["install_ai_refresh_compatibility"]
