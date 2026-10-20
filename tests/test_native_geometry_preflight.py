"""Regression tests for the native GUI geometry preflight classifier."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.dev.check_native_gui_geometry import (
    seed_geometry_fixture,
    vertical_splitter_metrics,
)
from scripts.invoice_fetch.db import InvoiceDB

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLASSIFIER = PROJECT_ROOT / "scripts" / "dev" / "check_native_gui_geometry.py"


class NativeGeometryPreflightTests(unittest.TestCase):
    def test_classifier_probes_the_populated_workbench(self):
        """The empty-state onboarding collapses the panes under test."""
        source = CLASSIFIER.read_text(encoding="utf-8")
        seed_index = source.index("seed_geometry_fixture(db_path)")
        app_index = source.index("window = InvoiceReviewApp(db_path, splash=None)")
        self.assertLess(
            seed_index,
            app_index,
            "the classifier must seed the reviewed workbench before starting "
            "the window; an empty database now shows the first-run onboarding",
        )

    def test_seeded_fixture_is_the_native_contract_state(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "native-seed.db"
            seed_geometry_fixture(db_path)
            with InvoiceDB(db_path) as db:
                invoices = db.get_all_invoices()
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["invoice_number"], "NATIVE-001")
        self.assertEqual(invoices[0]["review_status"], "to_review")

    def test_positive_vertical_range_is_suitable(self):
        metrics = vertical_splitter_metrics(
            sizes=[300, 457],
            record_minimum=276,
            record_maximum=16777215,
            preview_minimum=240,
        )
        self.assertEqual((metrics["lower"], metrics["upper"]), (276, 517))
        self.assertEqual((metrics["down_room"], metrics["up_room"]), (24, 217))
        self.assertTrue(metrics["adjustable"])

    def test_slack_above_a_fixed_maximum_still_allows_a_drag(self):
        # The populated workbench pins the record pane to a 276px maximum;
        # the first layout may leave it a few pixels above that bound.
        metrics = vertical_splitter_metrics(
            sizes=[280, 385],
            record_minimum=276,
            record_maximum=276,
            preview_minimum=240,
        )
        self.assertEqual((metrics["lower"], metrics["upper"]), (276, 276))
        self.assertEqual(metrics["down_room"], 4)
        self.assertTrue(metrics["adjustable"])

    def test_hosted_1024x768_splitter_has_no_vertical_range(self):
        # GitHub's 1024x768 runner compresses the vertical splitter to ~474px;
        # the fixed 276px record pane plus the 240px preview leaves no drag
        # room, which is an environment limit rather than a product failure.
        metrics = vertical_splitter_metrics(
            sizes=[276, 198],
            record_minimum=276,
            record_maximum=276,
            preview_minimum=240,
        )
        self.assertEqual((metrics["lower"], metrics["upper"]), (276, 234))
        self.assertEqual((metrics["down_room"], metrics["up_room"]), (0, 0))
        self.assertFalse(metrics["adjustable"])

    def test_touching_range_is_not_adjustable(self):
        metrics = vertical_splitter_metrics(
            sizes=[276, 240],
            record_minimum=276,
            record_maximum=16777215,
            preview_minimum=240,
        )
        self.assertFalse(metrics["adjustable"])


if __name__ == "__main__":
    unittest.main()
