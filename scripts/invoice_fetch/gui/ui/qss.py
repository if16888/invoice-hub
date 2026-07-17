# -*- coding: utf-8 -*-
"""Invoice Hub UI Kit - Central QSS Stylesheet Builder."""

from __future__ import annotations

from .theme import Theme


def build_qss() -> str:
    """Build the application UI Kit stylesheet from Design v1 aliases."""
    return f"""
    /* --------------------------------------------------------------------- */
    /* Global base and semantic typography                                   */
    /* --------------------------------------------------------------------- */
    QWidget {{
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: {Theme.TYPE_BODY}px;
        color: {Theme.TEXT_MAIN};
    }}

    QMainWindow, QWidget#PageRoot {{
        background-color: {Theme.BG_PAGE};
    }}

    QLabel[role="section-title"] {{
        color: {Theme.TEXT_MAIN};
        font-size: {Theme.TYPE_SECTION_TITLE}px;
        font-weight: 600;
    }}
    QLabel[role="secondary"], QLabel[role="field-label"] {{
        color: {Theme.TEXT_SUB};
        font-size: {Theme.TYPE_SECONDARY}px;
        font-weight: 500;
    }}
    QLabel[role="hint"] {{
        color: {Theme.TEXT_HINT};
        font-size: {Theme.TYPE_CAPTION}px;
        font-weight: 400;
    }}
    QLabel[role="status"], QLabel[role="secondary"] {{ color: {Theme.TEXT_SUB}; }}
    QLabel[role="caption"] {{ color: {Theme.TEXT_HINT}; font-size: {Theme.TYPE_CAPTION}px; }}
    QLabel[role="emphasis"], QLabel[role="strong"] {{ color: {Theme.TEXT_MAIN}; font-weight: 600; }}
    QLabel[role="guide"] {{ color: {Theme.TEXT_SUB}; padding: 15px; border: 1px dashed {Theme.BORDER_STRONG}; border-radius: {Theme.RADIUS_SM}px; background: {Theme.BG_SUBTLE}; }}
    QLabel[role="guidePlain"] {{ color: {Theme.TEXT_SUB}; }}
    QLabel[status="success"] {{ color: {Theme.GREEN_TEXT}; }}
    QLabel[status="warning"] {{ color: {Theme.ORANGE_TEXT}; }}
    QLabel[status="danger"] {{ color: {Theme.RED_TEXT}; }}
    QLabel[status="info"] {{ color: {Theme.BLUE}; }}
    QTextEdit#LogView {{ background: {Theme.BG_SUBTLE}; border: 1px solid {Theme.BORDER}; color: {Theme.TEXT_SUB}; }}

    /* --------------------------------------------------------------------- */
    /* Card containers                                                       */
    /* --------------------------------------------------------------------- */
    QFrame#Card, QWidget#Card, .WorkbenchCard {{
        background-color: {Theme.BG_CARD};
        border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CARD}px;
    }}

    /* --------------------------------------------------------------------- */
    /* Buttons                                                               */
    /* Reserve the final focus-border width in every state to avoid jitter.  */
    /* --------------------------------------------------------------------- */
    QPushButton {{
        min-height: {Theme.CONTROL_HEIGHT}px;
        max-height: {Theme.CONTROL_HEIGHT}px;
        border-radius: {Theme.RADIUS_CONTROL}px;
        padding: 0 13px;
        border: {Theme.FOCUS_BORDER_WIDTH}px solid {Theme.BORDER_STRONG};
        background-color: {Theme.BG_CARD};
        color: {Theme.TEXT_MAIN};
        font-size: {Theme.TYPE_BODY}px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {Theme.BG_SUBTLE};
        border-color: {Theme.BLUE};
    }}
    QPushButton:focus {{
        border-color: {Theme.FOCUS_RING};
    }}
    QPushButton:disabled {{
        background-color: {Theme.BG_SUBTLE};
        border-color: {Theme.BORDER};
        color: {Theme.TEXT_MUTED};
    }}

    QPushButton[variant="primary"] {{
        background-color: {Theme.BLUE};
        border-color: {Theme.BLUE};
        color: {Theme.TEXT_ON_ACCENT};
        font-weight: 600;
    }}
    QPushButton[variant="primary"]:hover {{
        background-color: {Theme.BLUE_HOVER};
        border-color: {Theme.BLUE_HOVER};
    }}
    QPushButton[variant="primary"]:focus {{
        background-color: {Theme.BLUE_HOVER};
        border-color: {Theme.FOCUS_RING_INVERSE};
    }}

    QPushButton[variant="danger"] {{
        background-color: {Theme.RED_BG};
        border-color: {Theme.RED_BORDER};
        color: {Theme.RED_TEXT};
        font-weight: 600;
    }}
    QPushButton[variant="danger"]:hover {{
        background-color: {Theme.RED_BG};
        border-color: {Theme.RED};
    }}
    QPushButton[variant="danger"]:focus {{
        border-color: {Theme.FOCUS_RING};
    }}

    QPushButton[variant="ghost"] {{
        background-color: transparent;
        border-color: transparent;
        color: {Theme.TEXT_SUB};
    }}
    QPushButton[variant="ghost"]:hover {{
        background-color: {Theme.BLUE_BG};
        color: {Theme.BLUE};
    }}
    QPushButton[variant="ghost"]:focus {{
        border-color: {Theme.FOCUS_RING};
    }}

    QPushButton[variant="toolbar"] {{
        min-height: {Theme.TOOLBAR_CONTROL_HEIGHT}px;
        max-height: {Theme.TOOLBAR_CONTROL_HEIGHT}px;
        border-radius: {Theme.RADIUS_SM}px;
        padding: 0 11px;
        font-size: {Theme.TYPE_SECONDARY}px;
    }}

    /* --------------------------------------------------------------------- */
    /* Side navigation                                                       */
    /* --------------------------------------------------------------------- */
    QFrame#WorkbenchNav {{
        background-color: {Theme.BG_CARD};
        border-right: 1px solid {Theme.BORDER};
    }}

    QPushButton.WorkbenchNavButton {{
        background-color: transparent;
        color: {Theme.TEXT_SUB};
        border: {Theme.FOCUS_BORDER_WIDTH}px solid transparent;
        border-radius: {Theme.RADIUS_CONTROL}px;
        padding: 0 11px;
        text-align: left;
        font-size: {Theme.TYPE_BODY}px;
        font-weight: 500;
        min-height: {Theme.NAV_ITEM_HEIGHT}px;
        max-height: {Theme.NAV_ITEM_HEIGHT}px;
    }}
    QPushButton.WorkbenchNavButton:hover {{
        background-color: {Theme.BG_SUBTLE};
        color: {Theme.TEXT_MAIN};
    }}
    QPushButton.WorkbenchNavButton:focus {{
        border-color: {Theme.FOCUS_RING};
    }}
    QPushButton.WorkbenchNavButton:checked {{
        background-color: {Theme.BLUE_BG};
        border-left: 3px solid {Theme.BLUE};
        color: {Theme.BLUE};
        font-weight: 700;
        padding-left: 10px;
    }}
    QPushButton.WorkbenchNavButton:checked:focus {{
        border-color: {Theme.FOCUS_RING};
        border-left-color: {Theme.BLUE};
    }}

    /* --------------------------------------------------------------------- */
    /* Status badges                                                         */
    /* --------------------------------------------------------------------- */
    QLabel[badge="pending"] {{
        background-color: {Theme.ORANGE_BG};
        color: {Theme.ORANGE_TEXT};
        border: 1px solid {Theme.ORANGE_BORDER};
        border-radius: {Theme.RADIUS_BADGE}px;
        padding: 2px 10px;
        font-size: {Theme.TYPE_BADGE}px;
        font-weight: 600;
    }}
    QLabel[badge="passed"] {{
        background-color: {Theme.GREEN_BG};
        color: {Theme.GREEN_TEXT};
        border: 1px solid {Theme.GREEN_BORDER};
        border-radius: {Theme.RADIUS_BADGE}px;
        padding: 2px 10px;
        font-size: {Theme.TYPE_BADGE}px;
        font-weight: 600;
    }}
    QLabel[badge="danger"] {{
        background-color: {Theme.RED_BG};
        color: {Theme.RED_TEXT};
        border: 1px solid {Theme.RED_BORDER};
        border-radius: {Theme.RADIUS_BADGE}px;
        padding: 2px 10px;
        font-size: {Theme.TYPE_BADGE}px;
        font-weight: 600;
    }}
    QLabel[badge="muted"] {{
        background-color: {Theme.GRAY_BG};
        color: {Theme.GRAY_TEXT};
        border: 1px solid {Theme.GRAY_BORDER};
        border-radius: {Theme.RADIUS_BADGE}px;
        padding: 2px 10px;
        font-size: {Theme.TYPE_BADGE}px;
        font-weight: 500;
    }}

    /* --------------------------------------------------------------------- */
    /* StatCard component                                                    */
    /* --------------------------------------------------------------------- */
    QFrame#CompactStatCard {{
        background-color: {Theme.BG_CARD};
        border: {Theme.FOCUS_BORDER_WIDTH}px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CARD}px;
        min-height: 44px;
        max-height: {Theme.STAT_CARD_HEIGHT}px;
    }}
    QFrame#CompactStatCard:hover {{
        border-color: {Theme.BORDER_STRONG};
        background-color: {Theme.BG_SUBTLE};
    }}
    QFrame#CompactStatCard:focus {{
        border-color: {Theme.FOCUS_RING};
    }}
    QFrame#CompactStatCard[selected="true"] {{
        background-color: {Theme.BLUE_BG};
        border-color: {Theme.BLUE};
    }}
    QFrame#CompactStatCard[selected="true"]:focus {{
        border-color: {Theme.FOCUS_RING};
    }}
    QFrame#CompactStatCard[selected="true"] QLabel.CompactStatCardTitle,
    QFrame#CompactStatCard[selected="true"] QLabel.CompactStatCardValue {{
        color: {Theme.BLUE_HOVER};
        font-weight: 700;
    }}

    /* --------------------------------------------------------------------- */
    /* Form inputs                                                           */
    /* --------------------------------------------------------------------- */
    QLineEdit, QComboBox, QLineEdit.DetailFieldInput, QComboBox.DetailFieldInput {{
        min-height: {Theme.CONTROL_HEIGHT}px;
        max-height: {Theme.CONTROL_HEIGHT}px;
        border: {Theme.FOCUS_BORDER_WIDTH}px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CONTROL}px;
        background-color: {Theme.BG_CARD};
        padding: 0 9px;
        color: {Theme.TEXT_MAIN};
        font-size: {Theme.TYPE_BODY}px;
        selection-background-color: {Theme.BLUE_BG};
        selection-color: {Theme.BLUE};
    }}
    QTextEdit {{
        border: {Theme.FOCUS_BORDER_WIDTH}px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CONTROL}px;
        background-color: {Theme.BG_CARD};
        padding: 5px 9px;
        color: {Theme.TEXT_MAIN};
        font-size: {Theme.TYPE_BODY}px;
    }}
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus,
    QLineEdit.DetailFieldInput:focus, QComboBox.DetailFieldInput:focus {{
        border-color: {Theme.FOCUS_RING};
        background-color: {Theme.BG_CARD};
    }}
    QLineEdit:read-only, QLineEdit:disabled, QComboBox:disabled, QTextEdit:read-only, QTextEdit:disabled,
    QLineEdit.DetailFieldInput:read-only, QLineEdit.DetailFieldInput:disabled, QComboBox.DetailFieldInput:disabled {{
        background-color: {Theme.BG_SUBTLE};
        color: {Theme.TEXT_SUB};
        border-color: {Theme.BORDER};
    }}
    QLabel.FormFieldLabel {{
        color: {Theme.TEXT_SUB};
        font-size: {Theme.TYPE_SECONDARY}px;
        font-weight: 500;
    }}

    /* --------------------------------------------------------------------- */
    /* AlertBanner component                                                 */
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
        font-size: {Theme.TYPE_SECONDARY}px;
        font-weight: 500;
    }}
    QFrame#AlertBanner[tone="danger"] {{
        background-color: {Theme.RED_BG};
        border: 1px solid {Theme.RED_BORDER};
    }}
    QLabel#AlertBannerText[tone="danger"] {{
        color: {Theme.RED_TEXT};
        font-size: {Theme.TYPE_SECONDARY}px;
        font-weight: 500;
    }}
    QFrame#AlertBanner[tone="info"] {{
        background-color: {Theme.BLUE_BG};
        border: 1px solid {Theme.BLUE_BORDER};
    }}
    QLabel#AlertBannerText[tone="info"] {{
        color: {Theme.BLUE};
        font-size: {Theme.TYPE_SECONDARY}px;
        font-weight: 500;
    }}
    QFrame#AlertBanner[tone="success"] {{
        background-color: {Theme.GREEN_BG};
        border: 1px solid {Theme.GREEN_BORDER};
    }}
    QLabel#AlertBannerText[tone="success"] {{
        color: {Theme.GREEN_TEXT};
        font-size: {Theme.TYPE_SECONDARY}px;
        font-weight: 500;
    }}

    /* --------------------------------------------------------------------- */
    /* Data tables                                                           */
    /* --------------------------------------------------------------------- */
    QTableView, QTableWidget {{
        background-color: {Theme.BG_CARD};
        border: none;
        gridline-color: {Theme.BG_CANVAS};
        selection-background-color: {Theme.BLUE_BG};
        selection-color: {Theme.BLUE};
    }}
    QTableView::item:selected, QTableWidget::item:selected {{
        background-color: {Theme.BLUE_BG};
        color: {Theme.BLUE};
    }}
    QTableView::item:hover, QTableWidget::item:hover {{
        background-color: {Theme.BG_SUBTLE};
    }}
    QTableView::item:selected:hover, QTableWidget::item:selected:hover {{
        background-color: {Theme.BLUE_BG};
        color: {Theme.BLUE};
    }}
    QHeaderView::section {{
        background-color: {Theme.BG_SUBTLE};
        color: {Theme.TEXT_SUB};
        font-weight: 600;
        font-size: {Theme.TYPE_SECONDARY}px;
        height: {Theme.TABLE_HEADER_HEIGHT}px;
        border: none;
        border-bottom: 1px solid {Theme.BORDER};
        padding: 0 8px;
    }}

    /* --------------------------------------------------------------------- */
    /* Tabs and scrollbars                                                   */
    /* --------------------------------------------------------------------- */
    QTabWidget::pane {{
        border: none;
        background-color: transparent;
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {Theme.TEXT_SUB};
        padding: 6px 14px 8px 14px;
        font-weight: 500;
        border: {Theme.FOCUS_BORDER_WIDTH}px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {Theme.BLUE};
        font-weight: 700;
        border-bottom-color: {Theme.BLUE};
    }}
    QTabBar::tab:hover:!selected {{
        color: {Theme.TEXT_MAIN};
    }}
    QTabBar::tab:focus {{
        border-color: {Theme.FOCUS_RING};
        border-bottom-color: transparent;
    }}
    QTabBar::tab:selected:focus {{
        border-color: {Theme.FOCUS_RING};
        border-bottom-color: {Theme.BLUE};
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: {Theme.SCROLLBAR_WIDTH}px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {Theme.BORDER_STRONG};
        border-radius: {Theme.SCROLLBAR_WIDTH // 2}px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {Theme.TEXT_MUTED};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QSplitter::handle {{
        background: transparent;
    }}
    """
