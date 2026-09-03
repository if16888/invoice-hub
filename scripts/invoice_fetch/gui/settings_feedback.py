"""Settings information-page feedback presentation."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QWidget


_INFO_PAGE_ATTRS = (
    (2, "lbl_settings_runtime"),
    (3, "lbl_settings_privacy"),
    (4, "lbl_settings_data"),
    (5, "lbl_settings_about"),
)


def _deduplicate_surface_header(surface: QFrame) -> None:
    if surface.property("headerDeduplicated"):
        return
    surface.setProperty("headerDeduplicated", True)

    for label in surface.findChildren(QLabel):
        if label.property("class") in {"SettingsSurfaceTitle", "SettingsSurfaceHint"}:
            label.hide()
            label.setProperty("duplicateHeadingHidden", True)

    for divider in surface.findChildren(QFrame):
        if divider.property("class") == "SettingsSectionDivider":
            divider.hide()
            divider.setProperty("duplicateHeaderDividerHidden", True)
            break

    layout = surface.layout()
    if layout is not None:
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(10)


def apply_settings_feedback_fixes(page: QWidget) -> None:
    """Keep one page heading and one content surface on simple Settings pages."""
    if page is None or page.property("settingsFeedbackFixesApplied"):
        return
    window = page.window()
    settings_tabs = getattr(window, "settings_tabs", None)
    if settings_tabs is None or settings_tabs.count() < 6:
        return

    page.setProperty("settingsFeedbackFixesApplied", True)
    for index, attr in _INFO_PAGE_ATTRS:
        subpage = settings_tabs.widget(index)
        surface = getattr(window, attr, None)
        if subpage is None or not isinstance(surface, QFrame):
            continue
        _deduplicate_surface_header(surface)
        subpage.setProperty("singleHeadingContract", True)


__all__ = ["apply_settings_feedback_fixes"]
