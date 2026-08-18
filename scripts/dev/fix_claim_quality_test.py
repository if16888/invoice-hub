"""One-shot correction for PR #101 claim-quality GUI test isolation."""

from pathlib import Path


path = Path("tests/test_claim_groups.py")
text = path.read_text(encoding="utf-8")
start = text.index("    def test_claim_quality_report_gui_prompt(self):")
end = text.index("\n\nif __name__ == \"__main__\":", start)
chunk = text[start:end]
old = '''                            # This test does not exercise embedded preview rendering.\n                            # Avoid opening the synthetic PDF so Windows can remove the\n                            # temporary directory deterministically.\n                            window._update_document_preview = Mock()\n'''
if old in chunk:
    chunk = chunk.replace(old, "", 1)
elif "window._update_document_preview = Mock()" in chunk:
    raise SystemExit("unexpected quality-test preview isolation shape")

if "window.pdf_document.close()" not in chunk:
    raise SystemExit("explicit PDF cleanup is missing")
if "except (ImportError, RuntimeError, OSError)" in chunk:
    raise SystemExit("OSError is still masked as skip")

updated = text[:start] + chunk + text[end:]
if updated != text:
    path.write_text(updated, encoding="utf-8", newline="")
    print("claim_quality_test_fix=changed")
else:
    print("claim_quality_test_fix=none")
