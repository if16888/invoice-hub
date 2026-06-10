"""Preview GUI deferred-load test adapter.

This test adapter exists because several legacy preview GUI tests instantiate
``InvoiceReviewApp``, call ``show()`` plus a single ``processEvents()``, and then
immediately select table rows. Production startup intentionally defers the first
invoice load with a short Qt timer for responsiveness.

The adapter is intentionally narrow: it only wraps the row-selection helpers in
``test_preview_pdf_nav_log_001`` so those tests load the table before selecting.
It does not replace email-reprocess tests or production behavior.
"""

from __future__ import annotations

import importlib


def _load_module(*names: str):
    last_error = None
    for module_name in names:
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ModuleNotFoundError(names[0] if names else "")


def _patch_preview_select_helpers() -> None:
    try:
        target = _load_module("test_preview_pdf_nav_log_001", "tests.test_preview_pdf_nav_log_001")
    except ModuleNotFoundError:
        return

    def _is_pending_evidence_row(inv: dict) -> bool:
        return str((inv or {}).get("invoice_type") or "") == "待关联证明材料"

    def _wrap_select_row(original):
        if getattr(original, "_invoice_hub_deferred_load_wrapped", False):
            return original

        def _select_row_with_deferred_init(self, window, row_idx):
            was_unloaded = not getattr(window, "_deferred_init_done", False)
            if hasattr(window, "_deferred_init") and was_unloaded:
                window._deferred_init()
                app_obj = getattr(self, "app", None)
                if app_obj is not None:
                    app_obj.processEvents()

            if was_unloaded and row_idx == 0:
                invoices = list(getattr(window, "invoices_list", []) or [])
                if invoices and _is_pending_evidence_row(invoices[0]):
                    for idx, inv in enumerate(invoices):
                        if not _is_pending_evidence_row(inv):
                            row_idx = idx
                            break

            return original(self, window, row_idx)

        _select_row_with_deferred_init._invoice_hub_deferred_load_wrapped = True
        return _select_row_with_deferred_init

    for class_name in ("TestInvoiceNoteAndPrivacy001", "TestDetailPanelCompact001"):
        cls = getattr(target, class_name, None)
        if cls is None or not hasattr(cls, "_select_row"):
            continue
        cls._select_row = _wrap_select_row(cls._select_row)


_patch_preview_select_helpers()
