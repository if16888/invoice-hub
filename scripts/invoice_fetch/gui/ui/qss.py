# -*- coding: utf-8 -*-
"""Invoice Hub UI Kit - Central QSS Stylesheet Builder."""

from __future__ import annotations
from .theme import Theme


def build_qss() -> str:
    """Build and return the complete application stylesheet using Theme tokens."""
    return f"""
    /* --------------------------------------------------------------------- */
    /* Global Base Rules                                                     */
    /* --------------------------------------------------------------------- */
    QWidget {{
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 13px;
        color: {Theme.TEXT_MAIN};
    }}

    QMainWindow, QWidget#PageRoot {{
        background-color: {Theme.BG_PAGE};
    }}

    /* --------------------------------------------------------------------- */
    /* Card Container (Card component)                                       */
    /* --------------------------------------------------------------------- */
    QFrame#Card, QWidget#Card, .WorkbenchCard {{
        background-color: {Theme.BG_CARD};
        border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CARD}px;
    }}

    /* --------------------------------------------------------------------- */
    /* Buttons (AppButton component)                                         */
    /* --------------------------------------------------------------------- */
    QPushButton {{
        min-height: {Theme.CONTROL_HEIGHT}px;
        max-height: {Theme.CONTROL_HEIGHT}px;
        border-radius: {Theme.RADIUS_CONTROL}px;
        padding: 0 14px;
        border: 1px solid {Theme.BORDER_STRONG};
        background-color: {Theme.BG_CARD};
        color: {Theme.TEXT_MAIN};
        font-size: 13px;
        font-weight: 500;
        outline: none;
    }}
    QPushButton:hover {{
        background-color: {Theme.BG_SUBTLE};
        border-color: {Theme.BLUE};
    }}
    QPushButton:disabled {{
        background-color: {Theme.BG_SUBTLE};
        border-color: {Theme.BORDER};
        color: {Theme.TEXT_MUTED};
    }}

    /* Button Variants */
    QPushButton[variant="primary"] {{
        background-color: {Theme.BLUE};
        border-color: {Theme.BLUE};
        color: #FFFFFF;
        font-weight: 600;
    }}
    QPushButton[variant="primary"]:hover {{
        background-color: {Theme.BLUE_HOVER};
        border-color: {Theme.BLUE_HOVER};
    }}

    QPushButton[variant="danger"] {{
        background-color: {Theme.RED_BG};
        border-color: {Theme.RED_BORDER};
        color: {Theme.RED_TEXT};
        font-weight: 600;
    }}
    QPushButton[variant="danger"]:hover {{
        background-color: #FEE2E2;
        border-color: {Theme.RED};
    }}

    QPushButton[variant="ghost"] {{
        background-color: transparent;
        border: none;
        color: {Theme.TEXT_SUB};
    }}
    QPushButton[variant="ghost"]:hover {{
        background-color: {Theme.BLUE_BG};
        color: {Theme.BLUE};
    }}

    QPushButton[variant="toolbar"] {{
        min-height: 32px;
        max-height: 32px;
        border-radius: {Theme.RADIUS_SM}px;
        padding: 0 12px;
        font-size: 12px;
    }}

    /* --------------------------------------------------------------------- */
    /* Side Navigation                                                       */
    /* --------------------------------------------------------------------- */
    QFrame#WorkbenchNav {{
        background-color: {Theme.BG_CARD};
        border-right: 1px solid {Theme.BORDER};
    }}

    QPushButton.WorkbenchNavButton {{
        background-color: transparent;
        color: {Theme.TEXT_SUB};
        border: none;
        border-radius: {Theme.RADIUS_CONTROL}px;
        padding: 0 12px;
        text-align: left;
        font-size: 13px;
        font-weight: 500;
        min-height: 40px;
        max-height: 40px;
    }}
    QPushButton.WorkbenchNavButton:hover {{
        background-color: {Theme.BG_SUBTLE};
        color: {Theme.TEXT_MAIN};
    }}
    QPushButton.WorkbenchNavButton:checked {{
        background-color: {Theme.BLUE_BG};
        border-left: 3px solid {Theme.BLUE};
        color: {Theme.BLUE};
        font-weight: 700;
    }}

    /* --------------------------------------------------------------------- */
    /* Status Badges (StatusBadge component)                                 */
    /* --------------------------------------------------------------------- */
    QLabel[badge="pending"] {{
        background-color: {Theme.ORANGE_BG};
        color: {Theme.ORANGE_TEXT};
        border: 1px solid {Theme.ORANGE_BORDER};
        border-radius: {Theme.RADIUS_BADGE}px;
        padding: 2px 10px;
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel[badge="passed"] {{
        background-color: {Theme.GREEN_BG};
        color: {Theme.GREEN_TEXT};
        border: 1px solid {Theme.GREEN_BORDER};
        border-radius: {Theme.RADIUS_BADGE}px;
        padding: 2px 10px;
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel[badge="danger"] {{
        background-color: {Theme.RED_BG};
        color: {Theme.RED_TEXT};
        border: 1px solid {Theme.RED_BORDER};
        border-radius: {Theme.RADIUS_BADGE}px;
        padding: 2px 10px;
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel[badge="muted"] {{
        background-color: {Theme.GRAY_BG};
        color: {Theme.GRAY_TEXT};
        border: 1px solid {Theme.GRAY_BORDER};
        border-radius: {Theme.RADIUS_BADGE}px;
        padding: 2px 10px;
        font-size: 12px;
        font-weight: 500;
    }}

    /* --------------------------------------------------------------------- */
    /* StatCard Component (Status Filter Chips)                              */
    /* --------------------------------------------------------------------- */
    QFrame#CompactStatCard {{
        background-color: {Theme.BG_CARD};
        border: 1px solid {Theme.BORDER};
        border-radius: 10px;
        min-height: 44px;
        max-height: 48px;
    }}
    QFrame#CompactStatCard:hover {{
        border-color: {Theme.BORDER_STRONG};
        background-color: {Theme.BG_SUBTLE};
    }}
    QFrame#CompactStatCard[selected="true"] {{
        background-color: {Theme.BLUE_BG};
        border: 1.5px solid {Theme.BLUE};
    }}
    QFrame#CompactStatCard[selected="true"] QLabel.CompactStatCardTitle,
    QFrame#CompactStatCard[selected="true"] QLabel.CompactStatCardValue {{
        color: {Theme.BLUE_HOVER};
        font-weight: 700;
    }}

    /* --------------------------------------------------------------------- */
    /* Form Inputs (FormField & DetailFieldInput)                            */
    /* --------------------------------------------------------------------- */
    QLineEdit, QComboBox, QLineEdit.DetailFieldInput, QComboBox.DetailFieldInput {{
        min-height: 34px;
        max-height: 34px;
        border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CONTROL}px;
        background-color: {Theme.BG_CARD};
        padding: 0 10px;
        color: {Theme.TEXT_MAIN};
        font-size: 13px;
        selection-background-color: {Theme.BLUE_BG};
        selection-color: {Theme.BLUE};
    }}
    QTextEdit {{
        border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CONTROL}px;
        background-color: {Theme.BG_CARD};
        padding: 6px 10px;
        color: {Theme.TEXT_MAIN};
        font-size: 13px;
    }}
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus,
    QLineEdit.DetailFieldInput:focus, QComboBox.DetailFieldInput:focus {{
        border: 1.5px solid {Theme.BLUE};
        background-color: #FFFFFF;
    }}
    QLineEdit:read-only, QLineEdit:disabled, QComboBox:disabled, QTextEdit:read-only, QTextEdit:disabled,
    QLineEdit.DetailFieldInput:read-only, QLineEdit.DetailFieldInput:disabled, QComboBox.DetailFieldInput:disabled {{
        background-color: {Theme.BG_SUBTLE};
        color: {Theme.TEXT_SUB};
        border-color: {Theme.BORDER};
    }}
    QLabel.FormFieldLabel {{
        color: {Theme.TEXT_SUB};
        font-size: 12px;
        font-weight: 500;
    }}

    /* --------------------------------------------------------------------- */
    /* AlertBanner Component                                                 */
    /* --------------------------------------------------------------------- */
    QFrame#AlertBanner {{
        border-radius: {Theme.RADIUS_CONTROL}px;
        padding: 8px 12px;
    }}
    QFrame#AlertBanner[tone="warning"] {{
        background-color: {Theme.ORANGE_BG};
        border: 1px solid {Theme.ORANGE_BORDER};
    }}
    QLabel#AlertBannerText[tone="warning"] {{
        color: {Theme.ORANGE_TEXT};
        font-size: 12px;
        font-weight: 500;
    }}

    QFrame#AlertBanner[tone="danger"] {{
        background-color: {Theme.RED_BG};
        border: 1px solid {Theme.RED_BORDER};
    }}
    QLabel#AlertBannerText[tone="danger"] {{
        color: {Theme.RED_TEXT};
        font-size: 12px;
        font-weight: 500;
    }}

    QFrame#AlertBanner[tone="info"] {{
        background-color: {Theme.BLUE_BG};
        border: 1px solid {Theme.BLUE_BORDER};
    }}
    QLabel#AlertBannerText[tone="info"] {{
        color: {Theme.BLUE};
        font-size: 12px;
        font-weight: 500;
    }}

    QFrame#AlertBanner[tone="success"] {{
        background-color: {Theme.GREEN_BG};
        border: 1px solid {Theme.GREEN_BORDER};
    }}
    QLabel#AlertBannerText[tone="success"] {{
        color: {Theme.GREEN_TEXT};
        font-size: 12px;
        font-weight: 500;
    }}

    /* --------------------------------------------------------------------- */
    /* Data Tables                                                           */
    /* --------------------------------------------------------------------- */
    QTableView, QTableWidget {{
        background-color: {Theme.BG_CARD};
        border: none;
        gridline-color: #F1F5F9;
        selection-background-color: {Theme.BLUE_BG};
        selection-color: {Theme.BLUE};
    }}
    QHeaderView::section {{
        background-color: {Theme.BG_SUBTLE};
        color: {Theme.TEXT_SUB};
        font-weight: 600;
        font-size: 12px;
        height: 34px;
        border: none;
        border-bottom: 1px solid {Theme.BORDER};
        padding: 0 8px;
    }}

    /* --------------------------------------------------------------------- */
    /* Tabs & ScrollBars                                                     */
    /* --------------------------------------------------------------------- */
    QTabWidget::pane {{
        border: none;
        background-color: transparent;
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {Theme.TEXT_SUB};
        padding: 8px 16px;
        font-weight: 500;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {Theme.BLUE};
        font-weight: 700;
        border-bottom: 2px solid {Theme.BLUE};
    }}
    QTabBar::tab:hover:!selected {{
        color: {Theme.TEXT_MAIN};
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #CBD5E1;
        border-radius: 3px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #94A3B8;
    }}

    QSplitter::handle {{
        background: transparent;
    }}
    """
