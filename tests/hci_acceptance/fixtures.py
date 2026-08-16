"""Synthetic data factory for HCI acceptance scenarios.

All invoice data is synthetic — no real invoices, emails, or user data.
Uses TemporaryDirectory for isolation; cleaned up after each test.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch import review_status

# ── Synthetic invoice templates ──────────────────────────────────────

SYNTHETIC_INVOICES: list[dict] = [
    # 5× TO_REVIEW (ordered with newest dates first so they are at table rows 0..4)
    {
        "invoice_number": "HCI-TR-001",
        "invoice_date": "2026-07-05",
        "total_amount": "100.00",
        "seller_name": "Synthetic Seller A",
        "buyer_name": "Synthetic Buyer",
        "category": "交通",
        "review_status": review_status.TO_REVIEW,
        "attachment_path": "synthetic/hci-tr-001.pdf",
    },
    {
        "invoice_number": "HCI-TR-002",
        "invoice_date": "2026-07-04",
        "total_amount": "200.00",
        "seller_name": "Synthetic Seller B",
        "buyer_name": "Synthetic Buyer",
        "category": "餐饮",
        "review_status": review_status.TO_REVIEW,
        "attachment_path": "synthetic/hci-tr-002.pdf",
    },
    {
        "invoice_number": "HCI-TR-003",
        "invoice_date": "2026-07-03",
        "total_amount": "300.00",
        "seller_name": "Synthetic Seller C",
        "buyer_name": "Synthetic Buyer",
        "category": "办公",
        "review_status": review_status.TO_REVIEW,
        "attachment_path": "synthetic/hci-tr-003.pdf",
    },
    {
        "invoice_number": "HCI-TR-004",
        "invoice_date": "2026-07-02",
        "total_amount": "400.00",
        "seller_name": "Synthetic Seller D",
        "buyer_name": "Synthetic Buyer",
        "category": "交通",
        "review_status": review_status.TO_REVIEW,
        "attachment_path": "synthetic/hci-tr-004.pdf",
    },
    {
        "invoice_number": "HCI-TR-005",
        "invoice_date": "2026-07-01",
        "total_amount": "500.00",
        "seller_name": "Synthetic Seller E",
        "buyer_name": "Synthetic Buyer",
        "category": "住宿",
        "review_status": review_status.TO_REVIEW,
        "attachment_path": "synthetic/hci-tr-005.pdf",
    },
    # 2× APPROVED
    {
        "invoice_number": "HCI-AP-001",
        "invoice_date": "2026-06-20",
        "total_amount": "150.00",
        "seller_name": "Approved Seller A",
        "buyer_name": "Synthetic Buyer",
        "category": "交通",
        "review_status": review_status.APPROVED,
        "attachment_path": "synthetic/hci-ap-001.pdf",
    },
    {
        "invoice_number": "HCI-AP-002",
        "invoice_date": "2026-06-15",
        "total_amount": "250.00",
        "seller_name": "Approved Seller B",
        "buyer_name": "Synthetic Buyer",
        "category": "餐饮",
        "review_status": review_status.APPROVED,
        "attachment_path": "synthetic/hci-ap-002.pdf",
    },
    # 1× IGNORED
    {
        "invoice_number": "HCI-IG-001",
        "invoice_date": "2026-06-10",
        "total_amount": "50.00",
        "seller_name": "Ignored Seller",
        "buyer_name": "Synthetic Buyer",
        "category": "其他",
        "review_status": review_status.IGNORED,
        "attachment_path": "synthetic/hci-ig-001.pdf",
    },
    # 1× ERROR
    {
        "invoice_number": "HCI-ER-001",
        "invoice_date": "2026-06-05",
        "total_amount": "999.99",
        "seller_name": "Error Seller",
        "buyer_name": "Synthetic Buyer",
        "category": "其他",
        "review_status": review_status.ERROR,
        "attachment_path": "synthetic/hci-er-001.pdf",
    },
    # 1× TO_REVIEW with missing evidence (older date so standard invoices are reviewed first)
    {
        "invoice_number": "HCI-EV-001",
        "invoice_date": "2026-05-01",
        "total_amount": "75.00",
        "seller_name": "Evidence Seller",
        "buyer_name": "Synthetic Buyer",
        "category": "交通",
        "review_status": review_status.TO_REVIEW,
        "invoice_type": "待关联证明材料",
        "attachment_path": "synthetic/hci-ev-001.pdf",
        "has_extra": True,
        "extra_type": "行程单",
        "missing_extra": True,
    },
]


def populate_synthetic_db(db: InvoiceDB, runtime_dir: Path) -> dict[str, int]:
    """Insert all synthetic invoices and create dummy attachment files.

    Returns a dict mapping review_status -> count for verification.
    """
    counts: dict[str, int] = {
        review_status.TO_REVIEW: 0,
        review_status.APPROVED: 0,
        review_status.IGNORED: 0,
        review_status.ERROR: 0,
    }

    for template in SYNTHETIC_INVOICES:
        payload = {
            "invoice_number": template["invoice_number"],
            "invoice_date": template["invoice_date"],
            "total_amount": template["total_amount"],
            "seller_name": template["seller_name"],
            "buyer_name": template.get("buyer_name", ""),
            "category": template.get("category", ""),
            "review_status": template.get("review_status", review_status.TO_REVIEW),
            "attachment_path": template.get("attachment_path", ""),
            "invoice_type": template.get("invoice_type", ""),
            "has_extra": template.get("has_extra", False),
            "extra_type": template.get("extra_type", ""),
            "missing_extra": template.get("missing_extra", False),
            "extra_paths": json.dumps([], ensure_ascii=False),
        }

        # Create dummy attachment file
        if payload["attachment_path"]:
            att_path = runtime_dir / payload["attachment_path"]
            att_path.parent.mkdir(parents=True, exist_ok=True)
            att_path.write_bytes(b"%PDF-1.4 synthetic test content")

        invoice_id = db.insert_invoice(payload)
        status = payload["review_status"]
        if status != review_status.TO_REVIEW:
            db.update_invoice_review_status(invoice_id, status)

        counts[status] = counts.get(status, 0) + 1

    return counts


def create_claim_with_invoices(db: InvoiceDB, name: str, invoice_ids: list[int]) -> int:
    """Create a claim group and link specified invoices."""
    claim_id = db.create_claim_group(name)
    for inv_id in invoice_ids:
        db.add_invoice_to_claim(claim_id, inv_id)
    return claim_id


EXPECTED_INITIAL_COUNTS = {
    review_status.TO_REVIEW: 6,
    review_status.APPROVED: 2,
    review_status.IGNORED: 1,
    review_status.ERROR: 1,
}
EXPECTED_TOTAL = sum(EXPECTED_INITIAL_COUNTS.values())
