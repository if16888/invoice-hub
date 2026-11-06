# -*- coding: utf-8 -*-
"""Invoice Hub UI Kit - Central QSS Stylesheet Builder."""

from __future__ import annotations

from pathlib import Path
import sys

from .theme import Theme


def build_qss() -> str:
    """Build the application UI Kit stylesheet from Design v1 aliases."""
    from ..dark_mode import prefers_dark

    chevron_name = "chevron_down_dark.svg" if prefers_dark() else "chevron_down.svg"
    chevron = (Path(__file__).resolve().parent.parent / "assets" / "icons" / chevron_name).as_posix()
    icon_dir = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
    state_suffix = '_dark' if prefers_dark() else ''
    check_mark = (icon_dir / f'checkbox_checked{state_suffix}.svg').as_posix()
    partial_mark = (icon_dir / f'checkbox_partial{state_suffix}.svg').as_posix()
    up_arrow = (icon_dir / f'chevron_up{state_suffix}.svg').as_posix()
    font_family = {
        "win32": '"Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif',
        "darwin": '"SF Pro Text", "PingFang SC", sans-serif',
    }.get(sys.platform, '"Noto Sans", "Noto Sans CJK SC", sans-serif')
    return f"""
    /* --------------------------------------------------------------------- */
    /* Global base and semantic typography                                   */
    /* --------------------------------------------------------------------- */
    QWidget {{
        font-family: {font_family};
        font-size: {Theme.TYPE_BODY}px;
        font-weight: 400;
        color: {Theme.TEXT_MAIN};
    }}
    QLabel {{ font-weight: 400; }}

    QMainWindow, QWidget#PageRoot, QWidget[surfaceRole="page"] {{
        background-color: {Theme.BG_PAGE};
    }}
    QWidget[surfaceRole="content"] {{ background: {Theme.BG_CARD}; }}
    QWidget#ReviewEmptyState {{ background: {Theme.BG_PAGE}; }}
    QFrame#InvoiceTableCard[empty="true"] {{ background: {Theme.BG_PAGE}; }}
    QLabel[class="EmptyPageTitle"] {{ font-size: {Theme.TYPE_PAGE_TITLE}px; font-weight: 600; }}
    QFrame#EmptyOnboardingStep {{
        background: {Theme.BG_CARD};
        border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CARD}px;
    }}
    QFrame#EmptyOnboardingStep[step="followup"] {{ background: transparent; border: none; }}
    QFrame#EmptyOnboardingStep QLabel {{ border: none; background: transparent; }}
    QFrame#ImportSourceSelector {{ background: transparent; border: none; }}
    QWidget#ImportSourceSegment {{
        background: {Theme.BG_SUBTLE};
        border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CONTROL}px;
    }}
    QFrame#ImportSourceSelector QFrame#SelectableSourceCard {{
        background: transparent;
        border: 2px solid transparent;
        border-radius: {Theme.RADIUS_SM}px;
    }}
    QFrame#ImportSourceSelector QFrame#SelectableSourceCard[selected="true"] {{
        background: {Theme.BG_CARD};
        border-color: {Theme.BORDER};
    }}
    QFrame#ImportSourceSelector QFrame#SelectableSourceCard:focus {{ border-color: {Theme.FOCUS_RING}; }}
    QFrame#ImportSourceSelector QLabel {{ font-weight: 400; }}
    QFrame#ImportSourceSelector QFrame[selected="true"] QLabel {{ font-weight: 600; }}
    QToolButton#ExportPassedChecks {{
        text-align: left;
        padding: 2px 6px;
        border: 2px solid transparent;
        border-radius: {Theme.RADIUS_SM}px;
        color: {Theme.BLUE};
        background: transparent;
    }}
    QToolButton#ExportPassedChecks:focus {{ border-color: {Theme.FOCUS_RING}; }}
    QToolButton#WorkbenchTopIconButton::menu-indicator {{ image: none; width: 0; }}
    QFrame#WorkbenchTopToolbar {{
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 0;
        min-height: 40px;
        max-height: 40px;
    }}
    QFrame#InvoiceTableCard {{ border: none; border-radius: 0; }}
    QFrame#DetailSummaryCard {{
        border: none;
        border-bottom: 1px solid {Theme.BORDER};
        border-radius: 0;
        background: {Theme.BG_CARD};
    }}
    QFrame#ReviewActionRow QPushButton {{
        min-height: 28px;
        max-height: 28px;
        border-width: 2px;
    }}
    QTabWidget#DetailTabs::pane {{ border: none; background: {Theme.BG_CARD}; }}
    QTabWidget#DetailTabs QTabBar::tab {{
        background: {Theme.BG_SUBTLE};
        color: {Theme.TEXT_SUB};
        border: 1px solid transparent;
        border-radius: {Theme.RADIUS_SM}px;
        padding: 6px 12px;
        margin: 3px;
    }}
    QTabWidget#DetailTabs QTabBar::tab:selected {{
        background: {Theme.BG_CARD};
        border-color: {Theme.BORDER};
        color: {Theme.TEXT_MAIN};
    }}
    QFrame#SecondaryNavStack {{ border: none; background: {Theme.BG_PAGE}; }}
    QFrame#SecondaryNavStack QScrollArea,
    QFrame#SecondaryNavStack QWidget#SettingsPageStack {{ background: {Theme.BG_PAGE}; }}

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
    QPushButton,
    QPushButton.PrimaryBtn, QPushButton.SecondaryBtn,
    QPushButton.ToolbarActionBtn, QPushButton.FilterBtn,
    QPushButton[variant="primary"], QPushButton[variant="secondary"],
    QPushButton[variant="danger"], QPushButton[variant="ghost"],
    QPushButton[variant="toolbar"], QPushButton[variant="chip"],
    QPushButton[emphasis="primary"] {{
        min-height: {Theme.CONTROL_HEIGHT - 2 * Theme.FOCUS_BORDER_WIDTH}px;
        max-height: {Theme.CONTROL_HEIGHT - 2 * Theme.FOCUS_BORDER_WIDTH}px;
        border-radius: {Theme.RADIUS_CONTROL}px;
        padding: 0 13px;
        border: {Theme.FOCUS_BORDER_WIDTH}px solid {Theme.BORDER};
        background-color: {Theme.BG_CARD};
        color: {Theme.TEXT_MAIN};
        font-size: {Theme.TYPE_BODY}px;
        font-weight: 400;
    }}
    QPushButton:hover {{
        background-color: {Theme.BG_SUBTLE};
        border-color: {Theme.BORDER_STRONG};
    }}
    QPushButton:focus {{
        border-color: {Theme.FOCUS_RING};
    }}
    QPushButton:disabled {{
        background-color: #E4E7EC;
        border: 1px solid #E5E7EB;
        color: #667085;
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
        min-height: {Theme.TOOLBAR_CONTROL_HEIGHT - 2 * Theme.FOCUS_BORDER_WIDTH}px;
        max-height: {Theme.TOOLBAR_CONTROL_HEIGHT - 2 * Theme.FOCUS_BORDER_WIDTH}px;
        border-radius: {Theme.RADIUS_SM}px;
        padding: 0 11px;
        font-size: {Theme.TYPE_SECONDARY}px;
    }}
    QPushButton:pressed {{ background-color: {Theme.BG_CANVAS}; }}
    QPushButton[variant="primary"]:pressed {{ background-color: {Theme.BLUE_HOVER}; }}
    QPushButton:disabled, QPushButton[variant="primary"]:disabled,
    QPushButton[variant="ghost"]:disabled, QPushButton[variant="danger"]:disabled {{
        background-color: {Theme.BG_SUBTLE};
        border: {Theme.FOCUS_BORDER_WIDTH}px solid {Theme.BORDER};
        color: {Theme.TEXT_HINT};
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
        border-color: {Theme.BLUE_BORDER};
        color: {Theme.BLUE};
        font-weight: 600;
    }}
    QPushButton.WorkbenchNavButton:checked:focus {{
        border-color: {Theme.FOCUS_RING};
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
        min-height: {Theme.CONTROL_HEIGHT - 2 * Theme.FOCUS_BORDER_WIDTH}px;
        max-height: {Theme.CONTROL_HEIGHT - 2 * Theme.FOCUS_BORDER_WIDTH}px;
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
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 26px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}

    QFrame#InvoiceRecordHeader QToolButton {{
        padding: 0 12px;
        border: 1px solid transparent;
        border-radius: {Theme.RADIUS_SM}px;
        background: transparent;
        color: {Theme.TEXT_MAIN};
        font-size: {Theme.TYPE_SECONDARY}px;
    }}
    QFrame#InvoiceRecordHeader QToolButton:hover {{ background: {Theme.BG_SUBTLE}; }}
    QFrame#InvoiceRecordHeader QToolButton:focus {{ border-color: {Theme.FOCUS_RING}; }}
    QFrame#InvoiceRecordHeader QToolButton:disabled {{ color: {Theme.TEXT_HINT}; }}
    QFrame#InvoiceRecordHeader QToolButton::menu-indicator {{ image: none; width: 0; }}

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
        selection-background-color: {Theme.BLUE};
        selection-color: #FFFFFF;
    }}
    QTableView::item:selected, QTableWidget::item:selected {{
        background-color: {Theme.BLUE};
        color: #FFFFFF;
    }}
    QTableView::item:hover, QTableWidget::item:hover {{
        background-color: #EEF2F6;
    }}
    QTableView::item:selected:hover, QTableWidget::item:selected:hover {{
        background-color: {Theme.BLUE};
        color: #FFFFFF;
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
        border-radius: 999px;
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

    /* Task dialogs share the same surfaces, sizing and action hierarchy. */
    QDialog[dialogStyle="desktop"] {{ background: {Theme.BG_PAGE}; }}
    QDialog[dialogStyle="desktop"] QLabel {{ font-size: {Theme.TYPE_BODY}px; }}
    QDialog[dialogStyle="desktop"] QLabel[class="DialogTitle"] {{
        color: {Theme.TEXT_MAIN}; font-size: {Theme.TYPE_PAGE_TITLE}px; font-weight: 600;
    }}
    QDialog[dialogStyle="desktop"] QLabel[class="DialogHint"],
    QDialog[dialogStyle="desktop"] QLabel[class="SectionHint"] {{
        color: {Theme.TEXT_MUTED}; font-size: {Theme.TYPE_SECONDARY}px;
    }}
    QDialog[dialogStyle="desktop"] QWidget#DialogFormBody {{
        background: {Theme.BG_CARD}; border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CARD}px;
    }}
    QDialog[dialogStyle="desktop"] QScrollArea {{ background: transparent; border: none; }}
    QDialog[dialogStyle="desktop"] QFrame#DialogFooter {{
        background: transparent; border: none; border-top: 1px solid {Theme.BORDER};
    }}
    QDialog[dialogStyle="desktop"] QLineEdit,
    QDialog[dialogStyle="desktop"] QComboBox,
    QDialog[dialogStyle="desktop"] QAbstractSpinBox {{
        min-height: 28px; max-height: 28px; padding: 0 9px;
        border: 2px solid {Theme.BORDER}; border-radius: {Theme.RADIUS_CONTROL}px;
        background: {Theme.BG_CARD}; color: {Theme.TEXT_MAIN}; font-size: {Theme.TYPE_BODY}px;
        placeholder-text-color: {Theme.TEXT_HINT};
    }}
    QDialog[dialogStyle="desktop"] QAbstractSpinBox {{ padding-right: 30px; }}
    QDialog[dialogStyle="desktop"] QSpinBox::up-arrow {{ image: url("{up_arrow}"); width: 10px; height: 10px; }}
    QDialog[dialogStyle="desktop"] QSpinBox::down-arrow {{ image: url("{chevron}"); width: 10px; height: 10px; }}
    QDialog[dialogStyle="desktop"] QDateEdit::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right;
        width: 26px; border: none; background: transparent;
    }}
    QDialog[dialogStyle="desktop"] QDateEdit::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
    QDialog[dialogStyle="desktop"] QLineEdit:focus,
    QDialog[dialogStyle="desktop"] QComboBox:focus,
    QDialog[dialogStyle="desktop"] QAbstractSpinBox:focus {{ border-color: {Theme.FOCUS_RING}; }}
    QDialog[dialogStyle="desktop"] QLineEdit:disabled,
    QDialog[dialogStyle="desktop"] QComboBox:disabled,
    QDialog[dialogStyle="desktop"] QAbstractSpinBox:disabled {{
        background: {Theme.BG_SUBTLE}; color: {Theme.TEXT_SUB};
    }}
    QDialog[dialogStyle="desktop"] QPushButton {{
        min-height: 28px; max-height: 28px; min-width: 64px; padding: 0 12px;
        font-size: {Theme.TYPE_BODY}px; border: 2px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CONTROL}px; background: {Theme.BG_CARD}; color: {Theme.TEXT_MAIN};
    }}
    QDialog[dialogStyle="desktop"] QPushButton:hover {{ background: {Theme.BG_SUBTLE}; }}
    QDialog[dialogStyle="desktop"] QPushButton:focus {{ border-color: {Theme.FOCUS_RING}; }}
    QDialog[dialogStyle="desktop"] QPushButton[variant="primary"] {{
        background: {Theme.BLUE}; border-color: {Theme.BLUE}; color: {Theme.BG_CARD}; font-weight: 600;
    }}
    QDialog[dialogStyle="desktop"] QPushButton[variant="primary"]:hover {{
        background: {Theme.BLUE_HOVER}; border-color: {Theme.BLUE_HOVER};
    }}
    QDialog[dialogStyle="desktop"] QPushButton[variant="primary"]:focus {{ border-color: {Theme.BG_CARD}; }}
    QDialog[dialogStyle="desktop"] QPushButton[variant="danger"] {{ color: {Theme.RED_TEXT}; border-color: {Theme.RED_BORDER}; }}
    QDialog[dialogStyle="desktop"] QPushButton[variant="danger"]:focus {{ border-color: {Theme.FOCUS_RING}; }}
    QDialog[dialogStyle="desktop"] QPushButton:pressed {{ background: {Theme.BG_CANVAS}; }}
    QDialog[dialogStyle="desktop"] QPushButton[variant="primary"]:pressed {{ background: {Theme.BLUE_HOVER}; }}
    QDialog[dialogStyle="desktop"] QPushButton:disabled,
    QDialog[dialogStyle="desktop"] QPushButton[variant="primary"]:disabled,
    QDialog[dialogStyle="desktop"] QPushButton[variant="danger"]:disabled {{
        background: {Theme.BG_SUBTLE}; border-color: {Theme.BORDER}; color: {Theme.TEXT_SUB}; font-weight: 400;
    }}
    QDialog[dialogStyle="desktop"] QTableWidget {{
        background: {Theme.BG_CARD}; border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CONTROL}px; gridline-color: {Theme.BORDER};
        alternate-background-color: {Theme.BG_SUBTLE};
    }}
    QDialog[dialogStyle="desktop"] QPlainTextEdit {{
        background: {Theme.BG_CARD}; color: {Theme.TEXT_MAIN}; border: 1px solid {Theme.BORDER};
        border-radius: {Theme.RADIUS_CONTROL}px; padding: 10px;
    }}
    QDialog[dialogStyle="desktop"] QCheckBox::indicator,
    QDialog[dialogStyle="desktop"] QTableWidget::indicator,
    QDialog#columnFilterPopup QCheckBox::indicator,
    QDialog#columnFilterPopup QListWidget::indicator {{
        width: 14px; height: 14px; border: 1px solid {Theme.TEXT_MUTED};
        border-radius: 3px; background: {Theme.BG_CARD};
    }}
    QDialog[dialogStyle="desktop"] QCheckBox::indicator:checked,
    QDialog[dialogStyle="desktop"] QTableWidget::indicator:checked,
    QDialog#columnFilterPopup QCheckBox::indicator:checked,
    QDialog#columnFilterPopup QListWidget::indicator:checked {{
        border-color: {Theme.BLUE}; background: {Theme.BLUE}; image: url("{check_mark}");
    }}
    QDialog[dialogStyle="desktop"] QCheckBox::indicator:indeterminate,
    QDialog[dialogStyle="desktop"] QTableWidget::indicator:indeterminate,
    QDialog#columnFilterPopup QCheckBox::indicator:indeterminate,
    QDialog#columnFilterPopup QListWidget::indicator:indeterminate {{
        border-color: {Theme.BLUE}; background: {Theme.BLUE}; image: url("{partial_mark}");
    }}
    QDialog[dialogStyle="desktop"] QCheckBox::indicator:disabled {{ border-color: {Theme.BORDER}; background: {Theme.BG_SUBTLE}; }}
    QDialog[dialogStyle="desktop"] QCheckBox::indicator:checked:disabled,
    QDialog[dialogStyle="desktop"] QCheckBox::indicator:indeterminate:disabled {{ background: {Theme.TEXT_MUTED}; }}
    QMessageBox[dialogStyle="desktop"] QLabel#qt_msgbox_label {{ font-size: {Theme.TYPE_SURFACE_TITLE}px; font-weight: 600; }}
    QMessageBox[dialogStyle="desktop"] QLabel#qt_msgbox_informativelabel {{ color: {Theme.TEXT_SUB}; }}
    QCalendarWidget {{ background: {Theme.BG_CARD}; border: 1px solid {Theme.BORDER}; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {Theme.BG_SUBTLE}; }}
    QCalendarWidget QToolButton {{
        background: transparent; color: {Theme.TEXT_MAIN}; border: 2px solid transparent;
        border-radius: {Theme.RADIUS_SM}px; min-height: 24px; min-width: 24px;
        font-size: {Theme.TYPE_BODY}px;
    }}
    QCalendarWidget QToolButton:hover {{ background: {Theme.BG_CARD}; }}
    QCalendarWidget QToolButton:focus {{ border-color: {Theme.FOCUS_RING}; }}
    QCalendarWidget QAbstractItemView {{
        background: {Theme.BG_CARD}; color: {Theme.TEXT_MAIN};
        selection-background-color: {Theme.BLUE}; selection-color: {Theme.TEXT_ON_ACCENT};
    }}
    """
