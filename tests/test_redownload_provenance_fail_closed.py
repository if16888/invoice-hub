import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch import redownload


class RedownloadProvenanceFailClosedTests(unittest.TestCase):
    def test_unknown_provenance_never_allows_delete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "attachments"
            root.mkdir()
            existing = root / "existing.pdf"
            existing.write_bytes(b"keep")

            self.assertFalse(
                redownload._rollback_created_attachment(
                    existing,
                    attachments_root=root,
                    preexisting_files=None,
                )
            )
            self.assertTrue(existing.exists())


if __name__ == "__main__":
    unittest.main()
