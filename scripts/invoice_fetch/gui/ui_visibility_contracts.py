"""Visibility contracts for stateful desktop surfaces.

These helpers keep visibility changes co-located with the state transitions that
own them. They are intentionally small and idempotent so legacy construction
order cannot leave a correctly populated child hidden behind an empty-state
ancestor.
"""

from __future__ import annotations

from functools import wraps

from PySide6.QtWidgets import QStackedWidget, QTabWidget

from .invoice_detail_panel import InvoiceDetailPanel


_INVOICE_DETAIL_PATCHED = False


def _stack_contains(stack: QStackedWidget, widget) -> bool:
    """Return True only when *widget* is an actual page owned by *stack*."""
    return widget is not None and stack.indexOf(widget) >= 0


def _is_tab_internal_stack(stack: QStackedWidget) -> bool:
    """Identify the private QStackedWidget managed by a QTabWidget.

    Switching that internal stack directly bypasses QTabBar state updates and
    can leave the highlighted tab label out of sync with the visible page.
    """
    return isinstance(stack.parentWidget(), QTabWidget)


def _reveal_widget(widget, boundary=None) -> None:
    """Reveal *widget* without changing the user's selected detail tab.

    Only select pages that are actually owned by an application-level
    QStackedWidget.  The private stack inside QTabWidget must be left alone;
    QTabWidget is the sole owner of synchronising its tab bar and page index.
    """
    if widget is None:
        return
    child = widget
    child.show()
    parent = child.parentWidget()
    while parent is not None:
        if isinstance(parent, QStackedWidget):
            if not _is_tab_internal_stack(parent) and _stack_contains(parent, child):
                parent.setCurrentWidget(child)
        parent.show()
        if parent is boundary:
            break
        child = parent
        parent = parent.parentWidget()


def install_invoice_detail_visibility_contract() -> None:
    """Make a single-invoice selection reveal the populated detail surface."""
    global _INVOICE_DETAIL_PATCHED
    if _INVOICE_DETAIL_PATCHED:
        return
    _INVOICE_DETAIL_PATCHED = True

    original = InvoiceDetailPanel.set_single_selection_state

    @wraps(original)
    def set_single_selection_state(self: InvoiceDetailPanel):
        detail_tabs = getattr(self, "detail_tabs", None)
        selected_tab = detail_tabs.currentIndex() if detail_tabs is not None else -1

        result = original(self)

        # right_content_widget is moved into detail_tabs during finalisation, so
        # it is no longer a page of right_stack.  Select the real detail page
        # and never call setCurrentWidget() with a foreign widget.
        right_stack = getattr(self, "right_stack", None)
        detail_page = getattr(self, "detail_page", None)
        if isinstance(right_stack, QStackedWidget) and _stack_contains(right_stack, detail_page):
            right_stack.setCurrentWidget(detail_page)

        # Attachment state is populated before the selection state is applied.
        # Reassert the one active StatusLine action, but do not force the Basic
        # Info tab when the user is currently reviewing reimbursement details.
        status_line = getattr(self, "original_status_line", None)
        retry = getattr(self, "btn_retry_download", None)
        add_attachment = getattr(self, "btn_add_attachment", None)
        open_file = getattr(self, "btn_open_file", None)
        detail_files = getattr(self, "detail_files_section", None)
        if detail_files is not None:
            detail_files.show()
        if status_line is not None:
            status_line.show()
            active_action = None
            if retry is not None and retry.isEnabled():
                active_action = retry
            elif open_file is not None and open_file.isEnabled():
                active_action = open_file
            elif add_attachment is not None and add_attachment.isEnabled():
                active_action = add_attachment
            if active_action is not None:
                status_line.replace_action(active_action)
                _reveal_widget(active_action, boundary=self)

        if detail_tabs is not None and 0 <= selected_tab < detail_tabs.count():
            detail_tabs.setCurrentIndex(selected_tab)
        return result

    InvoiceDetailPanel.set_single_selection_state = set_single_selection_state


def install_settings_visibility_contract(page) -> None:
    """Keep mailbox detail/empty surfaces aligned with the selected account."""
    if page is None or page.property("settingsVisibilityContractInstalled"):
        return

    window = page.window()
    loader = getattr(window, "_load_settings_mailbox_form", None)
    if loader is None:
        return

    page.setProperty("settingsVisibilityContractInstalled", True)

    @wraps(loader)
    def load_settings_mailbox_form(row: int):
        result = loader(row)
        accounts = window._mailbox_accounts_for_settings()
        has_selection = 0 <= int(row) < len(accounts)

        surface = getattr(window, "mailbox_detail_surface", None)
        empty_state = getattr(window, "settings_mailbox_empty_state", None)
        account_list = getattr(window, "settings_mailbox_list", None)
        if surface is not None:
            surface.setVisible(has_selection)
        if empty_state is not None:
            empty_state.setVisible(not has_selection)
        if account_list is not None:
            account_list.setVisible(bool(accounts))
        return result

    window._load_settings_mailbox_form = load_settings_mailbox_form


install_invoice_detail_visibility_contract()


__all__ = [
    "install_invoice_detail_visibility_contract",
    "install_settings_visibility_contract",
]
