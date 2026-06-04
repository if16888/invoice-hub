# -*- coding: utf-8 -*-
"""
Invoice Hub PySide6 QSS StyleSheet
"""

APP_STYLESHEET = """
QMainWindow {
    background-color: #F8FAFC;
}
QWidget {
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
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
    font-size: 9px;
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
QLineEdit, QTextEdit, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 6px;
    font-size: 13px;
    color: #111827;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1.5px solid #2563EB;
}
QLineEdit:read-only, QTextEdit:read-only {
    background-color: #F8FAFC;
    color: #374151;
    border: 1px solid #E5E7EB;
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
    color: #9CA3AF;
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
    color: #94A3B8;
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
    border: 1.5px solid #2563EB;
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
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background-color: #F8FAFC;
    color: #6B7280;
    border: 1px solid #E5E7EB;
    border-bottom-color: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 16px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #2563EB;
    border-bottom-color: #FFFFFF;
    font-weight: bold;
}
QTabBar::tab:hover {
    background-color: #F9FAFB;
    color: #111827;
}

/* QMenu dropdown styling */
QMenu {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 4px 0px;
}
QMenu::item {
    padding: 6px 20px;
    color: #374151;
}
QMenu::item:selected {
    background-color: #EFF6FF;
    color: #2563EB;
}
QMenu::separator {
    height: 1px;
    background-color: #E5E7EB;
    margin: 4px 0px;
}
"""
