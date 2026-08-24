"""Contracts for the opt-in v0.1.7 GUI performance observation layer."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget

from scripts.invoice_fetch.gui.performance_probe import (
    GuiStallDetector,
    PerformancePaintObserver,
    PerformanceProbe,
    format_performance_event,
    performance_stage,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance_ms(self, value: float) -> None:
        self.value += value / 1000.0


class PerformanceProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_disabled_probe_does_not_emit_or_record(self):
        messages = []
        probe = PerformanceProbe(enabled=False, sink=messages.append)
        self.assertIsNone(probe.begin("list_refresh"))
        probe.mark_event("list_refresh", "stage")
        self.assertEqual(messages, [])
        self.assertEqual(probe.records, [])

    def test_trace_has_monotonic_stage_durations_and_redacts_free_text(self):
        clock = _Clock()
        messages = []
        probe = PerformanceProbe(enabled=True, sink=messages.append, clock=clock)
        trace = probe.begin(
            "list_refresh",
            path=r"C:\private\invoice-123.pdf",
            seller="Synthetic Seller",
        )
        clock.advance_ms(12)
        trace.mark("db_query")
        clock.advance_ms(8)
        record = trace.finish("layout_schedule", rows=10)

        self.assertEqual(record["event"], "list_refresh")
        self.assertEqual(record["rows"], 10)
        self.assertGreaterEqual(record["total_ms"], 20)
        self.assertIn("db_query", record["stages"])
        self.assertNotIn("invoice-123", messages[0])
        self.assertNotIn("Synthetic Seller", messages[0])
        self.assertIn("[性能][列表刷新]", messages[0])

    def test_completion_event_uses_required_t0_to_t6_labels(self):
        clock = _Clock()
        messages = []
        probe = PerformanceProbe(enabled=True, sink=messages.append, clock=clock)
        trace = probe.begin("upload_complete")
        for stage in ("T1_gui_signal", "T2_state_update", "T3_db_list_refresh_complete", "T4_page_switch_requested"):
            clock.advance_ms(1)
            trace.mark(stage)
        clock.advance_ms(1)
        trace.mark("T5_first_paint")
        clock.advance_ms(1)
        trace.finish("T6_interactive", surface="review")
        stages = probe.records[0]["stages"]
        for stage in ("T1_gui_signal", "T2_state_update", "T3_db_list_refresh_complete", "T4_page_switch_requested", "T5_first_paint", "T6_interactive"):
            self.assertIn(stage, stages)
        self.assertIn("[性能][上传完成]", messages[0])

    def test_stall_detector_reports_threshold_buckets_and_percentile(self):
        messages = []
        probe = PerformanceProbe(enabled=True, sink=messages.append)
        detector = GuiStallDetector(probe)
        detector.record_gap(49, "idle")
        detector.record_gap(51, "list_refresh")
        detector.record_gap(101, "page_switch")
        detector.record_gap(301, "preview")
        summary = detector.summary()
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["max_ms"], 301)
        self.assertEqual(summary["by_threshold"]["50"], 3)
        self.assertEqual(summary["by_threshold"]["100"], 2)
        self.assertEqual(summary["by_threshold"]["300"], 1)

    def test_first_paint_observer_marks_paint_and_interactive_turn(self):
        messages = []
        probe = PerformanceProbe(enabled=True, sink=messages.append)
        widget = QWidget()
        observer = PerformancePaintObserver(probe)
        observer.observe("review", widget)
        trace = probe.begin("page_switch", page="review")
        observer.arm("review", trace)
        observer.eventFilter(widget, QEvent(QEvent.Paint))
        self.app.processEvents()

        self.assertEqual(len(probe.records), 1)
        stages = probe.records[0]["stages"]
        self.assertIn("first_paint", stages)
        self.assertIn("interactive", stages)
        self.assertIn("[性能][页面切换]", messages[0])
        widget.deleteLater()

    def test_event_formatter_rejects_unbounded_strings(self):
        line = format_performance_event(
            "preview",
            "load",
            filename="invoice-very-sensitive-name.pdf",
            rows=1,
        )
        self.assertNotIn("invoice-very-sensitive-name", line)
        self.assertIn("rows=1", line)

    def test_blocking_stage_emits_begin_end_with_elapsed_and_thread(self):
        messages = []
        with patch.dict(os.environ, {"INVOICE_HUB_PERFORMANCE": "1"}):
            with patch(
                "scripts.invoice_fetch.gui.performance_probe._log"
            ) as logger:
                logger.info.side_effect = messages.append
                with performance_stage(
                    "shutdown",
                    "sqlite_close_call",
                    active=True,
                    timeout_ms=0,
                ):
                    pass

        self.assertEqual(len(messages), 2)
        self.assertIn("stage=begin", messages[0])
        self.assertIn("stage=end", messages[1])
        self.assertIn("stage_name=sqlite_close_call", messages[1])
        self.assertIn("elapsed_ms=", messages[1])
        self.assertIn("thread_id=", messages[1])

    def test_blocking_stage_disabled_does_not_read_clock(self):
        with patch.dict(os.environ, {"INVOICE_HUB_PERFORMANCE": "0"}):
            with patch(
                "scripts.invoice_fetch.gui.performance_probe.time.perf_counter",
                side_effect=AssertionError("disabled stage must not read the clock"),
            ):
                with performance_stage("shutdown", "sqlite_close_call", active=False):
                    pass


if __name__ == "__main__":
    unittest.main()
