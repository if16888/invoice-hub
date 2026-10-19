"""Resolve claim defaults without copying them into individual invoices."""
from __future__ import annotations


def resolve_claim_reason(invoice: dict, claim: dict | None = None) -> str:
    """NULL inherits; an explicit empty override deliberately clears the reason."""
    override = invoice.get('custom_reason')
    if override is not None:
        return str(override).strip()
    claim = claim or {}
    return ' · '.join(str(claim.get(key) or '').strip()
                      for key in ('reason_category', 'reason_detail')
                      if str(claim.get(key) or '').strip())
