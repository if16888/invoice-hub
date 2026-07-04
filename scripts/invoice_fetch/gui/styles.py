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
    background-color: #F6F8FB;
}
QFrame#WorkbenchNav {
    background-color: #FFFFFF;
    border-right: 1px solid #E5EAF2;
}
QLabel#WorkbenchNavTitle {
    color: #172033;
    background: transparent;
    font-size: 18px;
    font-weight: 700;
}
QLabel#WorkbenchNavSubtitle {
    color: #667085;
    background: transparent;
    font-size: 12px;
    font-weight: 500;
}
QPushButton.WorkbenchNavButton {
    background-color: transparent;
    color: #344054;
    border: none;
    border-radius: 8px;
    padding: 8px 12px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    min-height: 40px;
}
QPushButton.WorkbenchNavButton:hover {
    background-color: #F8FAFC;
    color: #172033;
}
QPushButton.WorkbenchNavButton[collapsed="true"] {
    padding: 10px 0;
    text-align: center;
}
QPushButton.WorkbenchNavButton:checked {
    background-color: #EFF6FF;
    border-left: 3px solid #2563EB;
    color: #2563EB;
    font-weight: 700;
}
QFrame#WorkbenchTopToolbar {
    background-color: #FFFFFF;
    border: 1px solid #E5EAF2;
    border-radius: 12px;
    padding: 6px 12px;
    min-height: 56px;
    max-height: 56px;
}
QFrame.WorkbenchCard, QFrame#WorkbenchCard {
    background-color: #FFFFFF;
    border: 1px solid #E5EAF2;
    border-radius: 12px;
}
QSplitter::handle {
    background: transparent;
}
QToolButton#WorkbenchTopIconButton {
    background-color: #FFFFFF;
    color: #475569;
    border: 1px solid #E5EAF2;
    border-radius: 8px;
    padding: 0;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QToolButton#WorkbenchTopIconButton:hover {
    background-color: #F8FAFC;
    border-color: #CBD5E1;
    color: #172033;
}
QPushButton#WorkbenchUserButton {
    background-color: #FFFFFF;
    color: #172033;
    border: 1px solid #E5EAF2;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#WorkbenchUserButton:hover {
    background-color: #F8FAFC;
    border-color: #CBD5E1;
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
    font-size: 16px;
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
QFrame#InvoiceRecordHeader {
    background-color: transparent;
    border: none;
}
QLabel#InvoiceRecordTitle {
    color: #111827;
    font-size: 13px;
    font-weight: 700;
}
QLabel#InvoiceRecordMeta,
QLabel#InvoiceRecordSort,
QLabel#InvoiceRecordSelection {
    color: #64748B;
    font-size: 11px;
    font-weight: 600;
}
QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    gridline-color: #F1F5F9;
    selection-background-color: #EFF6FF;
    selection-color: #2563EB;
    font-size: 12px;
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
    padding: 6px 8px;
    font-weight: 600;
    color: #4B5563;
    font-size: 12px;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #E5EAF2;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    color: #172033;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1.5px solid #2563EB;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #111827;
    border: 1px solid #D1D5DB;
    selection-background-color: #DBEAFE;
    selection-color: #1D4ED8;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 4px 8px;
    background-color: #FFFFFF;
    color: #111827;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #DBEAFE;
    color: #1D4ED8;
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
QFrame.DetailRowCard {
    background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
QFrame.DetailSection QLineEdit,
QFrame.DetailSection QComboBox,
QFrame.DetailSection QTextEdit {
    font-size: 12px;
}
QFrame.DetailWorkbench {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 12px;
}
QFrame.SummaryCard[variant="embedded"] {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 12px;
}
QFrame#DetailSummaryCard {
    background-color: #FFFFFF;
    border: none;
    border-radius: 12px;
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
QLabel.DetailFieldKey {
    color: #64748B;
    font-size: 12px;
    font-weight: 500;
}
QLabel.DetailAmount {
    color: #1D4ED8;
    font-size: 22px;
    font-weight: 800;
}
QLabel.DetailMeta {
    color: #64748B;
    font-size: 12px;
    font-weight: 500;
}
QLabel.DetailSeller {
    color: #111827;
    font-size: 16px;
    font-weight: 700;
}
QLabel.DetailCaption {
    color: #94A3B8;
    font-size: 11px;
    font-weight: 400;
}
QLabel.InlineWarning {
    min-height: 44px;
    max-height: 56px;
    padding: 8px 12px;
    margin-top: 8px;
    margin-bottom: 8px;
    border-radius: 8px;
    background-color: #FFF7ED;
    border: 1px solid #FED7AA;
    color: #C2410C;
    font-size: 12px;
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
    font-weight: 600;
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

/* Variant-based buttons used by new code paths. Keep class selectors below for compatibility. */
QPushButton[variant="primary"] {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #2563EB;
}
QPushButton[variant="primary"]:hover {
    background-color: #1D4ED8;
    color: #FFFFFF;
    border: 1px solid #1D4ED8;
}
QPushButton[variant="primary"]:pressed {
    background-color: #1E40AF;
    color: #FFFFFF;
    border: 1px solid #1E40AF;
}
QPushButton[variant="primary"]:focus {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 2px solid #60A5FA;
}
QPushButton[variant="primary"]:disabled {
    background-color: #CBD5E1;
    color: #64748B;
    border: 1px solid #CBD5E1;
}

QPushButton[variant="secondary"] {
    background-color: #FFFFFF;
    color: #374151;
    border: 1px solid #E5E7EB;
}
QPushButton[variant="secondary"]:hover {
    background-color: #F9FAFB;
    color: #111827;
    border-color: #D1D5DB;
}
QPushButton[variant="secondary"]:pressed {
    background-color: #F3F4F6;
    color: #111827;
    border-color: #D1D5DB;
}
QPushButton[variant="secondary"]:disabled {
    background-color: #F9FAFB;
    color: #6B7280;
    border-color: #E5E7EB;
}

QPushButton[variant="accent"] {
    background-color: #F8FBFF;
    color: #2563EB;
    border: 1px solid #BFDBFE;
}
QPushButton[variant="accent"]:hover {
    background-color: #E8F1FF;
    color: #1D4ED8;
    border: 1px solid #60A5FA;
}
QPushButton[variant="accent"]:pressed {
    background-color: #DBEAFE;
    color: #1D4ED8;
    border: 1px solid #3B82F6;
}
QPushButton[variant="accent"]:focus {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border: 2px solid #60A5FA;
}
QPushButton[variant="accent"]:disabled {
    background-color: #F8FAFC;
    color: #94A3B8;
    border: 1px solid #E2E8F0;
}

QPushButton[variant="danger"] {
    background-color: #FEF2F2;
    color: #B91C1C;
    border: 1px solid #FCA5A5;
}
QPushButton[variant="danger"]:hover {
    background-color: #FEE2E2;
    color: #991B1B;
    border: 1px solid #F87171;
}
QPushButton[variant="danger"]:pressed {
    background-color: #FECACA;
    color: #7F1D1D;
    border: 1px solid #EF4444;
}
QPushButton[variant="danger"]:focus {
    background-color: #FFF1F2;
    color: #991B1B;
    border: 2px solid #FB7185;
}
QPushButton[variant="danger"]:disabled {
    background-color: #FFF7F7;
    color: #FCA5A5;
    border: 1px solid #FECACA;
}

QPushButton[variant="toolbar"] {
    min-height: 20px;
    min-width: 86px;
    background-color: #FFFFFF;
    color: #374151;
    border: 1px solid #D1D5DB;
    padding: 6px 14px;
}
QPushButton[variant="toolbar"]:hover {
    background-color: #F8FAFC;
    color: #1D4ED8;
    border-color: #93C5FD;
}
QPushButton[variant="toolbar"]:focus {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border: 2px solid #60A5FA;
    font-weight: 700;
}
QPushButton[variant="toolbar"]:pressed {
    background-color: #DBEAFE;
    color: #1D4ED8;
    border: 2px solid #2563EB;
}
QPushButton[variant="toolbar"]:disabled {
    background-color: #F8FAFC;
    color: #9CA3AF;
    border-color: #E5E7EB;
}
QPushButton[variant="toolbar"][emphasis="primary"] {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #2563EB;
    font-weight: 700;
}
QPushButton[variant="toolbar"][emphasis="primary"]:hover {
    background-color: #1D4ED8;
    color: #FFFFFF;
    border-color: #1D4ED8;
}
QPushButton[variant="toolbar"][emphasis="primary"]:focus {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 2px solid #93C5FD;
}
QPushButton[variant="toolbar"][emphasis="primary"]:pressed {
    background-color: #1E40AF;
    color: #FFFFFF;
    border: 2px solid #1E3A8A;
}
QPushButton[variant="toolbar"][busy="true"] {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1.5px solid #1D4ED8;
    font-weight: 700;
}
QPushButton[variant="toolbar"][busy="true"]:disabled {
    background-color: #2563EB;
    color: #FFFFFF;
    border-color: #1D4ED8;
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
QFrame#CompactStatCard, QFrame.CompactStatCard {
    background-color: #FFFFFF;
    color: #111827;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    text-align: left;
    padding: 0px;
}
QFrame#CompactStatCard:hover, QFrame.CompactStatCard:hover {
    background-color: #F8FAFC;
    border-color: #BFDBFE;
}
QFrame#CompactStatCard[selected="true"], QFrame.CompactStatCard[selected="true"] {
    border: 2px solid #2563EB;
    background-color: #EFF6FF;
}
QFrame#CompactStatCard[state="success"], QFrame.CompactStatCard[state="success"] { color: #065F46; }
QFrame#CompactStatCard[state="warning"], QFrame.CompactStatCard[state="warning"] { color: #92400E; }
QFrame#CompactStatCard[state="danger"], QFrame.CompactStatCard[state="danger"] { color: #B91C1C; }
QFrame#CompactStatCard[state="muted"], QFrame.CompactStatCard[state="muted"] { color: #374151; }
QLabel.CompactStatCardTitle {
    background: transparent;
    color: inherit;
    font-size: 12px;
    font-weight: 600;
}
QLabel.CompactStatCardValue {
    background: transparent;
    color: inherit;
    font-size: 18px;
    font-weight: 700;
}
QToolButton#ShortcutDisclosure, QToolButton.ShortcutDisclosure {
    color: #4B5563;
    background: transparent;
    border: none;
    padding: 4px 2px;
    font-weight: 600;
}
QToolButton#ShortcutDisclosure:hover, QToolButton.ShortcutDisclosure:hover { color: #111827; }
QToolButton#ShortcutDisclosure[expanded="true"], QToolButton.ShortcutDisclosure[expanded="true"] { color: #111827; }
QWidget#ShortcutDisclosureContent, QWidget.ShortcutDisclosureContent { background: transparent; }
QLabel.ShortcutBadge {
    color: #374151;
    background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 500;
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
QPushButton[class="SettingsNavButton"] {
    background-color: transparent;
    color: #334155;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 10px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}
QPushButton[class="SettingsNavButton"]:hover {
    background-color: #F8FAFC;
    color: #0F172A;
    border-color: #E2E8F0;
}
QPushButton[class="SettingsNavButton"]:checked {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border-color: #BFDBFE;
}
QPushButton[class="SettingsNavButton"]:checked:hover {
    background-color: #DBEAFE;
    color: #1D4ED8;
    border-color: #93C5FD;
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

/* Settings Center Components */
QFrame.SettingsListRow {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
QFrame.SettingsListRow:hover {
    border-color: #3B82F6;
    background-color: #F9FAFB;
}
QLabel.SettingsListRowName {
    font-weight: bold;
    font-size: 13px;
    color: #111827;
}
QLabel.SettingsListRowDesc {
    color: #6B7280;
    font-size: 11px;
}
QLabel.SettingsListRowMeta {
    color: #374151;
    font-size: 12px;
    padding: 2px 6px;
}
QLabel.SettingsListHeader {
    font-weight: bold;
    font-size: 13px;
    color: #374151;
}
QLabel.SettingsSectionTitle {
    font-size: 16px;
    font-weight: bold;
    color: #1E3A8A;
}
QLabel.EmptyStateText {
    color: #6B7280;
    font-size: 13px;
    padding: 20px;
}
QPushButton.SettingsDangerBtn {
    background-color: #FEE2E2;
    color: #DC2626;
    border: 1px solid #FCA5A5;
    border-radius: 4px;
}
QPushButton.SettingsDangerBtn:hover {
    background-color: #FEF2F2;
    color: #B91C1C;
    border-color: #EF4444;
}
QPushButton.SettingsDangerBtn:pressed {
    background-color: #FDE8E8;
    color: #991B1B;
}

/* StatusBadge Variants */
QLabel.StatusBadge[variant="active"] {
    background-color: #DBEAFE;
    color: #1D4ED8;
    border: 1px solid #93C5FD;
}
QLabel.StatusBadge[variant="success"] {
    background-color: #DCFCE7;
    color: #166534;
    border: 1px solid #86EFAC;
}
QLabel.StatusBadge[variant="warning"] {
    background-color: #FEF3C7;
    color: #92400E;
    border: 1px solid #FCD34D;
}
QLabel.StatusBadge[variant="info"] {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border: 1px solid #BFDBFE;
}
QLabel.StatusBadge[variant="muted"] {
    background-color: #F3F4F6;
    color: #4B5563;
    border: 1px solid #E5E7EB;
}
QLabel.StatusBadge[variant="danger"] {
    background-color: #FEE2E2;
    color: #DC2626;
    border: 1px solid #FCA5A5;
}
QLabel.StatusBadge[variant="placeholder"] {
    background-color: transparent;
    color: #9CA3AF;
    border: 1px dashed #D1D5DB;
}

/* Button Variants */
QPushButton[variant="primary"] {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #2563EB;
    border-radius: 6px;
    font-weight: 500;
}
QPushButton[variant="primary"]:hover {
    background-color: #1D4ED8;
    border-color: #1D4ED8;
}
QPushButton[variant="primary"]:pressed {
    background-color: #1E40AF;
    border-color: #1E40AF;
}
QPushButton[variant="primary"]:disabled {
    background-color: #93C5FD;
    border-color: #93C5FD;
    color: #EFF6FF;
}

QPushButton[variant="secondary"] {
    background-color: #FFFFFF;
    color: #374151;
    border: 1px solid #D1D5DB;
    border-radius: 6px;
    font-weight: 500;
}
QPushButton[variant="secondary"]:hover {
    background-color: #F9FAFB;
    color: #111827;
    border-color: #C4C6CA;
}
QPushButton[variant="secondary"]:pressed {
    background-color: #F3F4F6;
    border-color: #B2B4B7;
}
QPushButton[variant="secondary"]:disabled {
    background-color: #F3F4F6;
    color: #9CA3AF;
    border-color: #E5E7EB;
}

QPushButton[variant="accent"] {
    background-color: #F8FBFF;
    color: #1D4ED8;
    border: 1px solid #BFDBFE;
    border-radius: 6px;
    font-weight: 600;
}
QPushButton[variant="accent"]:hover {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border-color: #93C5FD;
}
QPushButton[variant="accent"]:pressed {
    background-color: #DBEAFE;
    color: #1E40AF;
    border-color: #60A5FA;
}
QPushButton[variant="accent"]:focus {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border-color: #2563EB;
}
QPushButton[variant="accent"]:disabled {
    background-color: #F8FAFF;
    color: #93C5FD;
    border-color: #DBEAFE;
}

QPushButton[variant="danger"] {
    background-color: #FEE2E2;
    color: #DC2626;
    border: 1px solid #FCA5A5;
    border-radius: 6px;
    font-weight: 500;
}
QPushButton[variant="danger"]:hover {
    background-color: #FEF2F2;
    color: #B91C1C;
    border-color: #EF4444;
}
QPushButton[variant="danger"]:pressed {
    background-color: #FDE8E8;
    color: #991B1B;
    border-color: #F87171;
}
QPushButton[variant="danger"]:disabled {
    background-color: #F3F4F6;
    color: #9CA3AF;
    border-color: #E5E7EB;
}

QPushButton[variant="ghost"] {
    background-color: transparent;
    color: #4B5563;
    border: none;
    border-radius: 6px;
}
QPushButton[variant="ghost"]:hover {
    background-color: #F3F4F6;
    color: #111827;
}
QPushButton[variant="ghost"]:pressed {
    background-color: #E5E7EB;
}
QPushButton[variant="ghost"]:disabled {
    color: #9CA3AF;
}

QPushButton[variant="toolbar"] {
    background-color: #FFFFFF;
    color: #374151;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 500;
}
QPushButton[variant="toolbar"]:hover {
    background-color: #F9FAFB;
    border-color: #D1D5DB;
    color: #111827;
}
QPushButton[variant="toolbar"]:pressed {
    background-color: #F3F4F6;
}
QPushButton[variant="toolbar"]:disabled {
    background-color: #F3F4F6;
    color: #9CA3AF;
    border-color: #E5E7EB;
}
QPushButton[variant="toolbar"][emphasis="primary"] {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #2563EB;
    font-weight: 700;
}
QPushButton[variant="toolbar"][emphasis="primary"]:hover {
    background-color: #1D4ED8;
    color: #FFFFFF;
    border-color: #1D4ED8;
}
QPushButton[variant="toolbar"][emphasis="primary"]:pressed {
    background-color: #1E40AF;
    color: #FFFFFF;
    border-color: #1E3A8A;
}
QPushButton[variant="toolbar"][emphasis="primary"]:disabled {
    background-color: #CBD5E1;
    color: #FFFFFF;
    border-color: #CBD5E1;
}

QPushButton[variant="chip"] {
    background-color: #EFF6FF;
    color: #1D4ED8;
    border: 1px solid #BFDBFE;
    border-radius: 9999px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton[variant="chip"]:hover {
    background-color: #DBEAFE;
}
QPushButton[variant="chip"]:pressed {
    background-color: #BFDBFE;
}

/* Row states and Action clusters */
QFrame.SettingsListRow[active="true"] {
    border-color: #3B82F6;
    background-color: #EFF6FF;
}
QFrame.SettingsListRow[disabled="true"] {
    background-color: #F9FAFB;
    border-color: #E5E7EB;
}
QFrame.SettingsListRow[disabled="true"] QLabel {
    color: #9CA3AF;
}
QFrame.ActionCluster {
    border: none;
    background: transparent;
}

/* Inline warnings and hints */
QLabel.InlineWarning {
    min-height: 44px;
    max-height: 56px;
    padding: 8px 12px;
    margin-top: 8px;
    margin-bottom: 8px;
    border-radius: 8px;
    background-color: #FFF7ED;
    border: 1px solid #FED7AA;
    color: #C2410C;
    font-size: 12px;
    font-weight: 500;
}
QLabel.InlineHint {
    color: #D97706;
    font-size: 11px;
}
QLabel.StatusHint {
    font-size: 11px;
    color: #374151;
}
QLabel.StatusHint[variant="success"] {
    color: #10B981;
    font-weight: bold;
}
QLabel.StatusHint[variant="danger"] {
    color: #EF4444;
    font-weight: bold;
}
QLabel.StatusHint[variant="warning"] {
    color: #D97706;
}
QLabel.StatusHint[variant="muted"] {
    color: #6B7280;
}
QLabel.EmptyTitle {
    color: #111827;
    font-size: 14px;
    font-weight: bold;
}
QLabel.EmptyDesc {
    color: #6B7280;
    font-size: 12px;
}
QLabel.PreviewEmptyState {
    color: #64748B;
    font-size: 13px;
    font-weight: 500;
    background-color: #F8FAFC;
    border: 1px dashed #E2E8F0;
    border-radius: 12px;
    padding: 18px 20px;
}
QStackedWidget#PreviewSurface {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 12px;
}
QLabel.Separator {
    color: #D1D5DB;
}
QLabel.ClaimTotal {
    color: #64748B;
    font-size: 12px;
}
QLabel.ExportSummary {
    color: #9CA3AF;
}
QLabel.NoteSummary {
    color: #475569;
    font-size: 12px;
}
QLabel.ClosingDesc {
    color: #4B5563;
}
QPushButton[variant="toolbar"][busy="true"] {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1.5px solid #1D4ED8;
    font-weight: 700;
}
QPushButton[variant="toolbar"][busy="true"]:disabled {
    background-color: #2563EB;
    color: #FFFFFF;
    border-color: #1D4ED8;
}

/* CompactStatCard — workbench filter bar status cards */
QFrame#CompactStatCard {
    background-color: #FFFFFF;
    border: 1px solid #E5EAF2;
    border-radius: 10px;
    min-width: 132px;
    min-height: 48px;
    max-height: 48px;
    padding: 0px 4px;
}
QFrame#CompactStatCard:hover {
    border-color: #BFDBFE;
    background-color: #F8FAFC;
}
QFrame#CompactStatCard[selected="true"] {
    background-color: #EFF6FF;
    border: 2px solid #2563EB;
}
QFrame#CompactStatCard[state="warning"] {
    border-color: #FCD34D;
}
QFrame#CompactStatCard[state="warning"][selected="true"] {
    background-color: #FFFBEB;
    border-color: #D97706;
}
QFrame#CompactStatCard[state="success"] {
    border-color: #A7F3D0;
}
QFrame#CompactStatCard[state="success"][selected="true"] {
    background-color: #F0FDF4;
    border-color: #059669;
}
QFrame#CompactStatCard[state="danger"] {
    border-color: #FCA5A5;
}
QFrame#CompactStatCard[state="danger"][selected="true"] {
    background-color: #FEF2F2;
    border-color: #DC2626;
}
QFrame#CompactStatCard[state="muted"] {
    border-color: #E5EAF2;
}
QFrame#CompactStatCard[state="info"] {
    border-color: #BFDBFE;
}
QLabel.CompactStatCardTitle {
    color: #667085;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
    letter-spacing: 0.2px;
}
QLabel.CompactStatCardIcon {
    color: #94A3B8;
    font-size: 12px;
    font-weight: 800;
    background: transparent;
    margin-right: 2px;
}
QLabel.CompactStatCardValue {
    color: #172033;
    font-size: 16px;
    font-weight: 800;
    background: transparent;
}
QFrame#CompactStatCard[state="warning"] QLabel.CompactStatCardIcon {
    color: #D97706;
}
QFrame#CompactStatCard[state="success"] QLabel.CompactStatCardIcon {
    color: #059669;
}
QFrame#CompactStatCard[state="danger"] QLabel.CompactStatCardIcon {
    color: #DC2626;
}
QFrame#CompactStatCard[state="info"] QLabel.CompactStatCardIcon {
    color: #2563EB;
}
QFrame#CompactStatCard[selected="true"] QLabel.CompactStatCardTitle {
    color: #1D4ED8;
}
QFrame#CompactStatCard[selected="true"] QLabel.CompactStatCardValue {
    color: #1D4ED8;
}

/* ShortcutDisclosure — collapsible keyboard shortcut help */
QFrame#ShortcutDisclosure {
    background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 4px 6px;
}
QFrame#ShortcutDisclosure[expanded="true"] {
    background-color: #F1F5F9;
    border-color: #CBD5E1;
}
QToolButton#WorkbenchShortcutEntry {
    background-color: transparent;
    color: #334155;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 8px;
    font-weight: 600;
}
QToolButton#WorkbenchShortcutEntry:hover {
    background-color: #F8FAFC;
    border-color: #E5E7EB;
}
QLabel.ShortcutKey {
    color: #1D4ED8;
    font-weight: 600;
}
QLabel.ShortcutAction {
    color: #475569;
}
QScrollArea#PreviewThumbnailRail {
    background-color: #F8FAFC;
    border: 0;
    border-right: 1px solid #E5E7EB;
}
QPushButton#PreviewThumbnail {
    min-height: 52px;
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    color: #475569;
    padding: 3px;
    font-size: 11px;
}
QPushButton#PreviewThumbnail[selected="true"] {
    border: 2px solid #2563EB;
    color: #1D4ED8;
}
QPushButton#PreviewAddAttachment {
    min-height: 40px;
    border: 1px dashed #CBD5E1;
    background-color: #FFFFFF;
    color: #475569;
    font-size: 11px;
}
QFrame#DetailFixedHeader {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 12px;
}
QTabWidget#DetailTabs::pane {
    border: 0;
}
QTabBar::tab {
    background-color: transparent;
    color: #64748B;
    padding: 10px 8px 8px 8px;
    margin-right: 4px;
    border-bottom: 2px solid transparent;
    font-weight: 600;
    min-width: 0;
}
QTabBar::tab:selected {
    color: #2563EB;
    border-bottom-color: #2563EB;
}
QTabBar::tab:hover:!selected {
    color: #334155;
    border-bottom-color: #CBD5E1;
}
QFrame#DetailFieldStack {
    background: transparent;
}
QFrame.DetailValueRow {
    background: transparent;
    border: none;
}
QLineEdit.DetailFieldInput,
QComboBox.DetailFieldInput {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 7px 10px;
    color: #0F172A;
    font-size: 13px;
}
QLineEdit.DetailFieldInput:focus,
QComboBox.DetailFieldInput:focus {
    background-color: #FFFFFF;
    border: 1.5px solid #93C5FD;
}
QLineEdit.DetailValueField {
    background-color: transparent;
    border: none;
    padding: 0;
    color: #111827;
    font-size: 13px;
}
QFrame#DetailOriginalRowCard QLabel.FieldLabel,
QFrame#DetailEvidenceRowCard QLabel.FieldLabel {
    color: #64748B;
    font-size: 12px;
    font-weight: 500;
}
QFrame#DetailOriginalRowCard,
QFrame#DetailEvidenceRowCard {
    background-color: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
""" + MENU_STYLE + """
"""
