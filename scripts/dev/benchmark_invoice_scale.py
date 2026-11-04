"""Synthetic invoice-volume benchmark for the local database and Excel export.

This is a development baseline, not a release acceptance gate. It uses only
synthetic rows and a temporary database. Run it on the target Windows release
host when a platform-specific number is required.

Example:
    python scripts/dev/benchmark_invoice_scale.py --counts 100,500,2000
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.excel_export import export_excel


def _synthetic_invoice(index: int) -> dict[str, object]:
    month = (index % 12) + 1
    day = (index % 28) + 1
    date = f"2026-{month:02d}-{day:02d}"
    amount = f"{(index % 1000) + 1}.00"
    return {
        "invoice_number": f"BENCH-{index:06d}",
        "invoice_date": date,
        "expense_date": date,
        "seller_name": f"Synthetic Seller {index % 50}",
        "buyer_name": "Synthetic Buyer",
        "amount": amount,
        "total_amount": amount,
        "parse_success": 1,
        "category": "交通",
        "attachment_path": f"synthetic/bench-{index % 20}.pdf",
        "review_status": "to_review",
        "confirmed_note": f"synthetic note {index}",
    }


def _seed(db: InvoiceDB, count: int) -> float:
    started = time.perf_counter()
    for index in range(count):
        db.insert_invoice(_synthetic_invoice(index))
    return time.perf_counter() - started


def _best_of(action, repeat: int) -> float:
    best = float("inf")
    for _ in range(repeat):
        started = time.perf_counter()
        action()
        best = min(best, time.perf_counter() - started)
    return best


def _run_count(count: int, repeat: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="invoice-hub-bench-") as directory:
        root = Path(directory)
        db = InvoiceDB(root / "bench.db")
        try:
            insert_seconds = _seed(db, count)
            rows = db.get_all_invoices()
            list_seconds = _best_of(lambda: db.get_all_invoices(), repeat)
            page_seconds = _best_of(lambda: db.list_invoices(limit=50), repeat)
            filtered_seconds = _best_of(
                lambda: db.list_invoices(status="to_review", limit=50),
                repeat,
            )
            export_path = root / "bench.xlsx"
            export_seconds = _best_of(
                lambda: export_excel(rows, export_path),
                repeat,
            )
            export_bytes = export_path.stat().st_size
        finally:
            db.close()
    return {
        "invoices": count,
        "insert_total_s": round(insert_seconds, 3),
        "insert_per_invoice_ms": round(insert_seconds * 1000 / count, 3),
        "list_all_s": round(list_seconds, 3),
        "list_page_s": round(page_seconds, 4),
        "list_filtered_page_s": round(filtered_seconds, 4),
        "export_xlsx_s": round(export_seconds, 3),
        "export_xlsx_bytes": export_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--counts",
        default="100,500,2000",
        help="Comma-separated invoice counts (default: 100,500,2000)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Best-of repetitions for query/export operations (default: 3)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path; the result is always printed to stdout.",
    )
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")

    counts = [int(value) for value in args.counts.split(",") if value.strip()]
    if not counts or any(value <= 0 for value in counts):
        parser.error("--counts must contain positive integers")

    results = [_run_count(count, args.repeat) for count in counts]
    payload = {
        "environment": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
        },
        "repeat": args.repeat,
        "results": results,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
