"""Historical v0.1.3 source-shape checks.

This module is intentionally outside ``tests/`` and is not part of CI discovery.
The assertions below inspected implementation source text rather than exercising
observable behavior. They are retained only as migration history.
"""

import inspect
import unittest


class ArchivedSourceContractTests(unittest.TestCase):
    def test_manual_attachment_refresh_used_selection_callback(self):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        for method_name in (
            "_add_attachment_manually",
            "_add_evidence_manually",
            "_retry_download_link",
        ):
            source = inspect.getsource(getattr(InvoiceReviewApp, method_name))
            self.assertNotIn("_update_detail_fields", source)
            self.assertIn("_on_table_selection_changed", source)

    def test_manual_evidence_used_db_path_and_flag_methods(self):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        source = inspect.getsource(InvoiceReviewApp._add_evidence_manually)
        self.assertIn("update_invoice_file_paths(inv_id, extra_paths=extra_paths)", source)
        self.assertNotIn("update_invoice_file_paths(inv_id, extra_paths=extra_paths_str)", source)
        self.assertIn("update_invoice_extra_flags", source)
        self.assertIn("has_extra=True", source)
        self.assertIn("missing_extra=False", source)

    def test_supporting_document_refresh_named_baseline_method(self):
        from scripts.invoice_fetch.gui.preview_mixin import PreviewMixin

        source = inspect.getsource(PreviewMixin._update_supporting_docs_selector)
        self.assertIn("update_evidence_row(self.supporting_doc_items)", source)

    def test_gui_export_forwarded_preflight_directory_by_source_text(self):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        source = inspect.getsource(InvoiceReviewApp._export_claim_package)
        self.assertIn("export_root=Path(configured_export_dir)", source)


if __name__ == "__main__":
    unittest.main()
