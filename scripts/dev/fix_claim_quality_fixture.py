"""One-shot PR #101 fixture correction for claim-quality GUI coverage."""

from pathlib import Path


path = Path("tests/test_claim_groups.py")
text = path.read_text(encoding="utf-8")
start = text.index("    def test_claim_quality_report_gui_prompt(self):")
end = text.index("\n\nif __name__ == \"__main__\":", start)
chunk = text[start:end]

# Keep the warning oracle focused on exactly one condition: empty seller.
if '"expense_date": "2026-06-01",' not in chunk.split("# Create dummy attachment", 1)[0]:
    old = '''                        "total_amount": "100.00",\n                        "seller_name": "",\n'''
    new = '''                        "total_amount": "100.00",\n                        "expense_date": "2026-06-01",\n                        "seller_name": "",\n'''
    if old not in chunk:
        raise SystemExit("claim-quality invoice fixture seam not found")
    chunk = chunk.replace(old, new, 1)

# Embedded PDF rendering is not part of this export-dialog contract. Isolate it
# so Windows temp-file cleanup cannot turn an otherwise valid test into a
# resource-lock failure.
if "window._update_document_preview = Mock()" not in chunk:
    old = '''                        window = InvoiceReviewApp(db_path, splash=None)\n                        try:\n                            window._deferred_init()\n'''
    new = '''                        window = InvoiceReviewApp(db_path, splash=None)\n                        try:\n                            window._update_document_preview = Mock()\n                            window._deferred_init()\n'''
    if old not in chunk:
        raise SystemExit("claim-quality preview isolation seam not found")
    chunk = chunk.replace(old, new, 1)

if "except (ImportError, RuntimeError, OSError)" in chunk:
    raise SystemExit("OSError must not be masked as skip")

updated = text[:start] + chunk + text[end:]
if updated != text:
    path.write_text(updated, encoding="utf-8", newline="")
    print("claim_quality_fixture_fix=changed")
else:
    print("claim_quality_fixture_fix=none")
