"""Weak similarity keys for unnumbered invoices, never an identity assertion."""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json


def soft_invoice_fingerprint(invoice: dict) -> str | None:
    from .evidence import is_evidence_record
    if is_evidence_record(invoice):
        return None
    if str(invoice.get('invoice_number') or '').strip():
        return None
    seller = ''.join(str(invoice.get('seller_name') or '').split()).casefold()
    raw_date = str(invoice.get('expense_date') or invoice.get('invoice_date') or '').strip()
    try:
        normalized_date = date.fromisoformat(raw_date).isoformat()
        raw_amount = invoice.get('total_amount')
        amount = Decimal(str(raw_amount if raw_amount is not None else '').replace(',', '').strip())
        if (not seller or not amount.is_finite() or abs(amount.adjusted()) > 128
                or len(amount.as_tuple().digits) > 128):
            return None
        with localcontext() as context:
            context.prec = 256
            normalized_amount = '0' if amount == 0 else format(amount.normalize(), 'f')
    except (ValueError, InvalidOperation):
        return None
    currency = str(invoice.get('currency') or '').strip().upper()
    key = json.dumps([seller, normalized_date, normalized_amount, currency], ensure_ascii=False)
    return hashlib.sha256(key.encode('utf-8')).hexdigest()
