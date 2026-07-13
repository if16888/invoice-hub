import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from scripts.invoice_fetch.gui import review_baseline_pipeline as pipeline
from scripts.invoice_fetch.gui.page_layouts import WorkspacePageLayout


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class ReviewBaselinePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_pipeline_runs_stages_in_order_once(self):
        page = QWidget()
        calls = []
        stages = tuple(
            (name, lambda _page, stage_name=name: calls.append(stage_name))
            for name in ("one", "two", "three")
        )
        try:
            with patch.object(pipeline, "REVIEW_BASELINE_STAGES", stages):
                pipeline.apply_review_baseline_pipeline(page)
                pipeline.apply_review_baseline_pipeline(page)

            self.assertEqual(calls, ["one", "two", "three"])
            self.assertTrue(page.property("reviewBaselinePipelineApplied"))
            self.assertEqual(
                tuple(page.property("reviewBaselinePipelineStages")),
                ("one", "two", "three"),
            )
            self.assertEqual(page.property("reviewBaselinePipelineActiveStage"), "")
            self.assertEqual(page.property("reviewBaselinePipelineFailedStage"), "")
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()

    def test_pipeline_records_the_failing_stage_and_can_be_retried(self):
        page = QWidget()
        calls = []

        def fail(_page):
            calls.append("broken")
            raise RuntimeError("synthetic stage failure")

        stages = (
            ("ready", lambda _page: calls.append("ready")),
            ("broken", fail),
            ("never", lambda _page: calls.append("never")),
        )
        try:
            with patch.object(pipeline, "REVIEW_BASELINE_STAGES", stages):
                with self.assertRaisesRegex(RuntimeError, "synthetic stage failure"):
                    pipeline.apply_review_baseline_pipeline(page)

            self.assertEqual(calls, ["ready", "broken"])
            self.assertFalse(page.property("reviewBaselinePipelineApplied"))
            self.assertEqual(page.property("reviewBaselinePipelineActiveStage"), "broken")
            self.assertEqual(page.property("reviewBaselinePipelineFailedStage"), "broken")
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()

    def test_scheduler_coalesces_to_one_deferred_callback(self):
        page = QWidget()
        calls = []
        queued = []
        stages = (("only", lambda _page: calls.append("only")),)
        try:
            with patch.object(pipeline, "REVIEW_BASELINE_STAGES", stages), patch.object(
                pipeline.QTimer,
                "singleShot",
                side_effect=lambda _delay, callback: queued.append(callback),
            ) as single_shot:
                pipeline.schedule_review_baseline_pipeline(page)
                pipeline.schedule_review_baseline_pipeline(page)

                single_shot.assert_called_once()
                self.assertTrue(page.property("reviewBaselinePipelineScheduled"))
                self.assertEqual(len(queued), 1)
                queued[0]()

            self.assertEqual(calls, ["only"])
            self.assertFalse(page.property("reviewBaselinePipelineScheduled"))
            self.assertTrue(page.property("reviewBaselinePipelineApplied"))
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()

    def test_workspace_layout_delegates_to_pipeline_scheduler(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        try:
            with patch(
                "scripts.invoice_fetch.gui.page_layouts.schedule_review_baseline_pipeline"
            ) as schedule, patch(
                "scripts.invoice_fetch.gui.page_layouts.QTimer.singleShot"
            ) as global_style_timer:
                WorkspacePageLayout.apply(page, layout)
            schedule.assert_called_once_with(page)
            global_style_timer.assert_called_once()
            self.assertEqual(page.property("pageArchetype"), "workspace")
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
