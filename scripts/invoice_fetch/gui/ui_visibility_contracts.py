"""Visibility contracts for stateful desktop surfaces.

These helpers keep visibility changes co-located with the state transitions that
own them. They are intentionally small and idempotent so legacy construction
order cannot leave a correctly populated child hidden behind an empty-state
ancestor.
"""

from __future__ import annotations

from functools import wraps

from .invoice_detail_panel import InvoiceDetailPanel


_INVOICE_DETAIL_PATCHED = False


def install_invoice_detail_visibility_contract() -> None:
    """Make a single-invoice selection reveal the populated detail surface."""
    global _INVOICE_DETAIL_PATCHED
    if _INVOICE_DETAIL_PATCHED:
        return
    _INVOICE_DETAIL_PATCHED = True

    original = InvoiceDetailPanel.set_single_selection_state

    @wraps(original)
    def set_single_selection_state(self: InvoiceDetailPanel):
        result = original(self)
        if hasattr(self, "right_stack") and hasattr(self, "right_content_widget"):
            self.right_stack.setCurrentWidget(self.right_content_widget)

        # Attachment state is populated before the selection state is applied.
        # Reassert the one active StatusLine action after revealing the content;
        # otherwise a button that was reparented while the empty surface was
        # active can remain effectively hidden on Windows/Qt.
        status_line = getattr(self, "original_status_line", None)
        retry = getattr(self, "btn_retry_download", None)
        add_attachment = getattr(self, "btn_add_attachment", None)
        open_file = getattr(self, "btn_open_file", None)
        detail_files = getattr(self, "detail_files_section", None)
        if detail_files is not None:
            detail_files.show()
        if status_line is not None:
            status_line.show()
            if retry is not None and retry.isEnabled():
                status_line.replace_action(retry)
                retry.show()
            elif open_file is not None and open_file.isEnabled():
                status_line.replace_action(open_file)
                open_file.show()
            elif add_attachment is not None and add_attachment.isEnabled():
                status_line.replace_action(add_attachment)
                add_attachment.show()
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
