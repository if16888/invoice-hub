# -*- coding: utf-8 -*-
"""
Invoice Hub PySide6 QSS StyleSheet
"""

PRIMARY_BUTTON_STYLE = "QPushButton.PrimaryBtn"
SECONDARY_BUTTON_STYLE = "QPushButton.SecondaryBtn"
TOOLBAR_ACTION_STYLE = "QPushButton.ToolbarActionBtn"
FILTER_BUTTON_STYLE = "QPushButton.FilterBtn"
ACTIVE_FILTER_STYLE = "QPushButton.FilterBtn:checked"
DISABLED_BUTTON_STYLE = "QPushButton:disabled"
MENU_STYLE = """
/* QMenu dropdown styling */
QMenu {
    background-color: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    min-height: 28px;
    padding: 6px 24px 6px 16px;
    color: #374151;
    background: transparent;
    border-radius: 6px;
}
QMenu::icon {
    padding-left: 8px;
}
QMenu::item:selected {
    background-color: #F3F4F6;
    color: #111827;
}
QMenu::separator {
    height: 1px;
    background: #E5E7EB;
    margin: 6px 8px;
}
"""

APP_STYLESHEET = """
QMainWindow {
    background-color: #F8FAFC;
}
QWidget {
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 9pt;
    color: #111827;
}
QLabel {
    font-size: 13px;
    font-weight: 500;
    color: #374151;
}
QLabel.StatusBadge {
    background-color: #F3F4F6;
    color: #6B7280;
    border: 1px solid #E5E7EB;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 12px;
    font-weight: bold;
}
QLabel.StatusBadge[variant="review"] {
    background-color: #FEF3C7;
    color: #D97706;
    border-color: #FCD34D;
}
QLabel.StatusBadge[variant="approved"] {
    background-color: #D1FAE5;
    color: #059669;
    border-color: #A7F3D0;
}
QLabel.StatusBadge[variant="ignored"] {
    background-color: #F3F4F6;
    color: #6B7280;
    border-color: #E5E7EB;
}
QLabel.StatusBadge[variant="error"] {
    background-color: #FEE2E2;
    color: #DC2626;
    border-color: #FCA5A5;
}
QLabel.SummaryAmount {
    color: #111827;
    font-size: 18px;
    font-weight: 700;
    margin-top: 1px;
    margin-bottom: 1px;
}
QLabel.SummaryMeta {
    color: #4B5563;
    font-size: 10px;
}
QLabel.SummarySeller {
    color: #111827;
    font-size: 11px;
    font-weight: 700;
}
QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    gridline-color: #F8FAFC;
    selection-background-color: #EFF6FF;
    selection-color: #2563EB;
    font-size: 13px;
}
QTableWidget::item:hover {
    background-color: #F8FAFC;
}
QTableWidget::item:selected {
    background-color: #DBEAFE;
    color: #1D4ED8;
}
QTableWidget::item:selected:active {
    background-color: #BFDBFE;
}
QHeaderView::section {
    background-color: #F8FAFC;
    border: none;
    border-bottom: 1.5px solid #E5E7EB;
    padding: 8px;
    font-weight: bold;
    color: #4B5563;
    font-size: 13px;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 6px;
    font-size: 13px;
    color: #111827;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1.5px solid #2563EB;
}
QLineEdit:read-only, QTextEdit:read-only, QPlainTextEdit:read-only {
    background-color: #F8FAFC;
    color: #374151;
    border: 1px solid #E5E7EB;
}
QFrame.DetailSection {
    background-color: #FFFFFF;
    border: none;
    border-radius: 0;
}
QFrame.DetailSection QLineEdit,
QFrame.DetailSection QComboBox,
QFrame.DetailSection QTextEdit {
    font-size: 12px;
}
QFrame.DetailWorkbench {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
}
QFrame.SummaryCard[variant="embedded"] {
    background-color: #FFFFFF;
    border: none;
    border-radius: 8px;
}
QFrame.DetailSection[variant="flat"] {
    background-color: #FFFFFF;
    border: none;
    border-radius: 0;
}
QFrame.DetailDivider {
    background-color: #E5E7EB;
    border: none;
    margin-left: 16px;
    margin-right: 16px;
}
QFrame.DetailSubDivider {
    background-color: #EEF2F7;
    border: none;
    margin-top: 4px;
    margin-bottom: 2px;
}
QFrame.DetailStatus {
    background-color: #F8FAFC;
    border: none;
    border-top: 1px solid #E5E7EB;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}
QLabel.SectionTitle {
    color: #111827;
    font-size: 13px;
    font-weight: 600;
}
QLabel.SectionEyebrow {
    color: #64748B;
    font-size: 11px;
    font-weight: 600;
}
QLabel.SectionHint {
    color: #6B7280;
    font-size: 12px;
    font-weight: 400;
}
QLabel.FieldLabel {
    color: #475569;
    font-size: 12px;
    font-weight: 500;
}
QLabel.DetailAmount {
    color: #0F172A;
    font-size: 18px;
    font-weight: 700;
}
QLabel.DetailMeta {
    color: #475569;
    font-size: 12px;
    font-weight: 500;
}
QLabel.DetailSeller {
    color: #111827;
    font-size: 13px;
    font-weight: 600;
}
QLabel.DetailCaption {
    color: #64748B;
    font-size: 12px;
    font-weight: 400;
}
QLabel.InlineWarning {
    color: #92400E;
    background-color: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: 6px;
    padding: 6px 8px;
    font-weight: 500;
}
QLabel.EvidenceMissing {
    background-color: #FFFBEB;
    color: #B45309;
    border: 1px solid #FCD34D;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 700;
}
QLabel.EvidenceFileName {
    color: #374151;
    font-size: 12px;
    background: transparent;
    border: none;
    padding: 0;
}
QLabel.EvidenceDotMissing {
    color: #D97706;
    font-size: 14px;
    background: transparent;
    border: none;
}
QLabel.EvidenceDotPresent {
    color: #10B981;
    font-size: 14px;
    background: transparent;
    border: none;
}
QLabel.InfoPanel {
    color: #4B5563;
    background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 8px;
    font-size: 12px;
    font-weight: 400;
}
QToolButton.Disclosure {
    color: #4B5563;
    background: transparent;
    border: none;
    padding: 4px 2px;
    font-weight: 600;
}
QToolButton.Disclosure:hover {
    color: #111827;
}
QGroupBox {
    font-weight: bold;
    font-size: 13px;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    background-color: #FFFFFF;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #111827;
}

/* Default Button (looks like Secondary neutral) */
QPushButton {
    background-color: #FFFFFF;
    color: #374151;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #F9FAFB;
    color: #111827;
    border-color: #D1D5DB;
}
QPushButton:pressed {
    background-color: #F3F4F6;
}
QPushButton:disabled {
    background-color: #F9FAFB;
    color: #6B7280;
    border-color: #E5E7EB;
}
QPushButton::menu-indicator {
    image: none;
}

/* Primary Button (solid blue) */
QPushButton.PrimaryBtn {
    background-color: #2563EB;
    color: #FFFFFF;
    border: none;
}
QPushButton.PrimaryBtn:hover {
    background-color: #1D4ED8;
}
QPushButton.PrimaryBtn:pressed {
    background-color: #1E40AF;
}
QPushButton.PrimaryBtn:disabled {
    background-color: #CBD5E1;
    color: #64748B;
}

/* Outline Button (light blue bg, blue border) */
QPushButton.OutlineBtn {
    background-color: #EFF6FF;
    color: #2563EB;
    border: 1px solid #BFDBFE;
}
QPushButton.OutlineBtn:hover {
    background-color: #DBEAFE;
    border-color: #2563EB;
}
QPushButton.OutlineBtn:pressed {
    background-color: #BFDBFE;
}
QPushButton.OutlineBtn:disabled {
    background-color: #F1F5F9;
    color: #6B7280;
    border-color: #E2E8F0;
}

/* Secondary Button (explicitly white bg, gray border) */
QPushButton.SecondaryBtn {
    background-color: #FFFFFF;
    color: #374151;
    border: 1px solid #E5E7EB;
}
QPushButton.SecondaryBtn:hover {
    background-color: #F9FAFB;
    color: #111827;
    border-color: #D1D5DB;
}
QPushButton.SecondaryBtn:pressed {
    background-color: #F3F4F6;
}

/* Work-entry buttons are peers, not competing primary actions. */
QPushButton.ToolbarActionBtn {
    min-height: 20px;
    min-width: 86px;
    background-color: #FFFFFF;
    color: #374151;
    border: 1px solid #D1D5DB;
    padding: 6px 14px;
}
QPushButton.ToolbarActionBtn:hover {
    background-color: #F8FAFC;
    color: #1D4ED8;
    border-color: #93C5FD;
}
QPushButton.ToolbarActionBtn:focus {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border: 2px solid #60A5FA;
    font-weight: 700;
}
QPushButton.ToolbarActionBtn:pressed {
    background-color: #DBEAFE;
    color: #1D4ED8;
    border: 2px solid #2563EB;
}
QPushButton.ToolbarActionBtn:disabled {
    background-color: #F8FAFC;
    color: #9CA3AF;
    border-color: #E5E7EB;
}
/* Busy = active action running: stays visually blue to indicate progress */
QPushButton.ToolbarActionBtn[busy="true"] {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1.5px solid #1D4ED8;
    font-weight: 700;
}
QPushButton.ToolbarActionBtn[busy="true"]:disabled {
    background-color: #2563EB;
    color: #FFFFFF;
    border-color: #1D4ED8;
}

QPushButton.SelectionCard {
    background-color: #FFFFFF;
    color: #111827;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    text-align: left;
}
QPushButton.SelectionCard:hover {
    background-color: #F8FAFC;
    border-color: #93C5FD;
}
QPushButton.SelectionCard:checked {
    background-color: #E8F1FF;
    color: #1D4ED8;
    border: 2px solid #2563EB;
}
QLabel.SelectionCardTitle {
    color: #1F2937;
    background: transparent;
    font-size: 12px;
    font-weight: 700;
}
QLabel.SelectionCardTitle[selected="true"] {
    color: #1D4ED8;
}
QLabel.SelectionCardDescription {
    color: #6B7280;
    background: transparent;
    font-size: 10px;
    font-weight: 400;
}

QPushButton.TextBtn {
    background-color: transparent;
    color: #2563EB;
    border: none;
    padding: 4px 2px;
}
QPushButton.TextBtn:hover {
    background-color: #EFF6FF;
    color: #1D4ED8;
}

QLabel.DialogTitle {
    color: #111827;
    font-size: 16px;
    font-weight: 700;
}
QLabel.DialogInfo {
    color: #4B5563;
    background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 8px 10px;
    font-weight: 400;
}
QLabel.WizardSteps {
    color: #6B7280;
    background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 8px 10px;
    font-weight: 500;
}
QLabel.QrPanel {
    background-color: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    padding: 8px;
}
QFrame.PrivacyPanel {
    background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
QScrollArea.SettingsScroll,
QScrollArea.SettingsScroll > QWidget > QWidget,
QWidget.DialogCanvas {
    background-color: #FFFFFF;
}

/* Success Button (solid green) */
QPushButton.SuccessBtn {
    background-color: #059669;
    color: #FFFFFF;
    border: none;
}
QPushButton.SuccessBtn:hover {
    background-color: #047857;
}
QPushButton.SuccessBtn:pressed {
    background-color: #065F46;
}

/* Danger Button (solid red) */
QPushButton.DangerBtn {
    background-color: #DC2626;
    color: #FFFFFF;
    border: none;
}
QPushButton.DangerBtn:hover {
    background-color: #B91C1C;
}
QPushButton.DangerBtn:pressed {
    background-color: #991B1B;
}

/* Ignored Button (solid gray) */
QPushButton.IgnoredBtn {
    background-color: #6B7280;
    color: #FFFFFF;
    border: none;
}
QPushButton.IgnoredBtn:hover {
    background-color: #4B5563;
}
QPushButton.IgnoredBtn:pressed {
    background-color: #374151;
}

/* Warning Outline Button (white bg, orange border/color) */
QPushButton.WarningOutlineBtn {
    background-color: #FFFFFF;
    color: #D97706;
    border: 1px solid #FCD34D;
}
QPushButton.WarningOutlineBtn:hover {
    background-color: #FEF3C7;
    border-color: #D97706;
}
QPushButton.WarningOutlineBtn:pressed {
    background-color: #FDE68A;
}
QPushButton.DangerOutlineBtn {
    background-color: #FFFFFF;
    color: #B91C1C;
    border: 1px solid #FCA5A5;
}
QPushButton.DangerOutlineBtn:hover {
    background-color: #FEF2F2;
    border-color: #EF4444;
}
QPushButton.TextDangerBtn {
    background-color: transparent;
    color: #B91C1C;
    border: none;
    padding: 6px 8px;
}
QPushButton.TextDangerBtn:hover {
    background-color: #FEF2F2;
    color: #991B1B;
}

/* Calmer Segmented Style Filter Tab Buttons */
QPushButton.FilterBtn {
    background-color: #FFFFFF;
    color: #4B5563;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    font-weight: 500;
    padding: 6px 12px;
}
QPushButton.FilterBtn:hover {
    background-color: #F9FAFB;
    color: #111827;
    border-color: #D1D5DB;
}
QPushButton.FilterBtn:checked {
    background-color: #EFF6FF;
    color: #2563EB;
    border: 1px solid #93C5FD;
    font-weight: bold;
}

/* Summary Card Styling */
QGroupBox.SummaryCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    margin-top: 0px;
    padding-top: 8px;
}

/* QTabWidget Styling */
QTabWidget::pane {
    border: 1px solid #E5E7EB;
    background-color: #FFFFFF;
    border-radius: 0 6px 6px 6px;
    top: -1px;
}
QTabBar::tab {
    background-color: #F3F4F6;
    color: #6B7280;
    border: 1px solid #E5E7EB;
    border-bottom-color: #E5E7EB;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    min-width: 72px;
    padding: 7px 14px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #111827;
    border-bottom-color: #FFFFFF;
    font-weight: 700;
}
QTabBar::tab:hover {
    background-color: #F9FAFB;
    color: #111827;
}
""" + MENU_STYLE + """
"""
