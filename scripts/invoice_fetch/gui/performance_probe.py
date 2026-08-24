"""Opt-in GUI performance observation helpers.

The first v0.1.7 performance pass deliberately measures existing behaviour.  The
helpers in this module do not schedule work differently, change data flow, or
retain application data.  They only collect monotonic timings when
``INVOICE_HUB_PERFORMANCE=1`` is set (or when a test explicitly enables a
probe).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Callable

from PySide6.QtCore import QEvent, QObject, QTimer


PERFORMANCE_ENV = "INVOICE_HUB_PERFORMANCE"
_SAFE_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_DEFAULT_THRESHOLDS_MS = (50.0, 100.0, 300.0)

EVENT_LABELS = {
    "upload_complete": "上传完成",
    "mail_complete": "邮箱完成",
    "local_import": "本地导入",
    "list_refresh": "列表刷新",
    "page_switch": "页面切换",
    "preview": "预览",
    "mobile_diagnostics": "手机诊断",
    "shutdown": "退出",
    "review_action": "审核操作",
    "stall": "stall",
}

_log = logging.getLogger("invoice_fetch.gui.performance")


def performance_mode_enabled(value: object | None = None) -> bool:
    """Return whether opt-in performance observation is enabled."""

    if value is None:
        value = os.environ.get(PERFORMANCE_ENV, "")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_token(value: object, fallback: str = "redacted") -> str:
    text = str(value or "")
    return text if _SAFE_TOKEN.fullmatch(text) else fallback


def _safe_field(value: object) -> str:
    """Format only non-sensitive scalar fields for a diagnostic line.

    Performance logs intentionally never accept arbitrary paths, filenames,
    invoice fields, URLs, or free-form exception text.  Non-token strings are
    replaced rather than partially copied into the log.
    """

    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if value is None:
        return ""
    return _safe_token(value)


def _format_fields(fields: dict[str, object]) -> str:
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        key_token = _safe_token(key)
        sensitive_key = any(
            marker in key_token.lower()
            for marker in ("path", "file", "invoice", "seller", "buyer", "mailbox", "credential", "token", "url", "secret")
        )
        safe_value = "redacted" if sensitive_key else _safe_field(value)
        parts.append(f"{key_token}={safe_value}")
    return " ".join(parts)


def format_performance_event(event: str, stage: str, **fields: object) -> str:
    """Build a privacy-safe one-line event marker."""

    label = EVENT_LABELS.get(event, _safe_token(event))
    payload = _format_fields({"stage": stage, **fields})
    return f"[性能][{label}] {payload}".rstrip()


def emit_performance_event(event: str, stage: str, **fields: object) -> None:
    """Emit a worker-side marker without importing a window instance."""

    if not performance_mode_enabled():
        return
    _log.info(format_performance_event(event, stage, **fields))


@contextmanager
def performance_stage(event: str, stage_name: str, **fields: object):
    """Measure one potentially blocking stage when opt-in tracing is enabled.

    The context deliberately does no clock work when performance mode is off.
    Stage fields are limited by :func:`format_performance_event`, so this is
    safe for shutdown diagnostics that must not carry paths, filenames, or
    other user data.
    """

    if not performance_mode_enabled():
        yield
        return

    thread = threading.current_thread()
    common = {
        "stage_name": stage_name,
        "thread_name": thread.name,
        "thread_id": threading.get_ident(),
        **fields,
    }
    started_at = time.perf_counter()
    emit_performance_event(event, "begin", **common)
    try:
        yield
    finally:
        emit_performance_event(
            event,
            "end",
            elapsed_ms=(time.perf_counter() - started_at) * 1000.0,
            **common,
        )


@dataclass
class PerformanceTrace:
    probe: "PerformanceProbe"
    event: str
    started_at: float
    fields: dict[str, object] = field(default_factory=dict)
    _last_mark: float | None = None
    _stages: list[tuple[str, float]] = field(default_factory=list)
    _finished: bool = False

    def __post_init__(self) -> None:
        self._last_mark = self.started_at

    def mark(self, stage: str) -> float:
        """Close the previous stage and start *stage*; return elapsed ms."""

        if self._finished:
            return 0.0
        now = self.probe.clock()
        previous = self._last_mark if self._last_mark is not None else self.started_at
        elapsed_ms = max(0.0, (now - previous) * 1000.0)
        self._stages.append((_safe_token(stage), elapsed_ms))
        self._last_mark = now
        return elapsed_ms

    def finish(self, stage: str | None = None, **fields: object) -> dict[str, object]:
        if stage:
            self.mark(stage)
        return self.probe.finish(self, **fields)


class PerformanceProbe:
    """Collect and emit opt-in monotonic timing traces."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        sink: Callable[[str], None] | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.enabled = performance_mode_enabled(enabled)
        self.sink = sink
        self.logger = logger or _log
        self.clock = clock or time.perf_counter
        self.records: list[dict[str, object]] = []
        self.messages: list[str] = []
        self.active_stage = "event_loop"

    def set_sink(self, sink: Callable[[str], None] | None) -> None:
        self.sink = sink

    def begin(
        self,
        event: str,
        *,
        started_at: float | None = None,
        **fields: object,
    ) -> PerformanceTrace | None:
        if not self.enabled:
            return None
        now = self.clock()
        if started_at is None:
            trace_started_at = now
        else:
            try:
                candidate = float(started_at)
            except (TypeError, ValueError):
                candidate = now
            # Worker and GUI threads share the monotonic clock, but a malformed
            # or future marker must never make a trace report negative time.
            trace_started_at = min(now, candidate)
        return PerformanceTrace(self, event, trace_started_at, fields=dict(fields))

    def mark_event(self, event: str, stage: str, **fields: object) -> None:
        if not self.enabled:
            return
        message = format_performance_event(event, stage, **fields)
        self._emit(message)

    def finish(self, trace: PerformanceTrace, **fields: object) -> dict[str, object]:
        if trace._finished:
            return self.records[-1] if self.records else {}
        now = self.clock()
        previous = trace._last_mark if trace._last_mark is not None else trace.started_at
        if now > previous:
            trace._stages.append(("total_tail", max(0.0, (now - previous) * 1000.0)))
        trace._finished = True
        total_ms = max(0.0, (now - trace.started_at) * 1000.0)
        stage_values: dict[str, float] = {}
        for stage, elapsed_ms in trace._stages:
            stage_values[stage] = stage_values.get(stage, 0.0) + elapsed_ms
        record: dict[str, object] = {
            "event": trace.event,
            "total_ms": total_ms,
            "stages": stage_values,
            **trace.fields,
            **fields,
        }
        self.records.append(record)
        stage_text = " ".join(
            f"{_safe_token(stage)}={elapsed_ms:.0f}ms"
            for stage, elapsed_ms in trace._stages
        )
        extra = _format_fields({**trace.fields, **fields})
        message = f"[性能][{EVENT_LABELS.get(trace.event, _safe_token(trace.event))}] total={total_ms:.0f}ms"
        if stage_text:
            message += f" {stage_text}"
        if extra:
            message += f" {extra}"
        self._emit(message)
        return record

    def _emit(self, message: str) -> None:
        self.messages.append(message)
        if self.sink is not None:
            self.sink(message)
        else:
            self.logger.info(message)

    def summary(self, event: str | None = None) -> dict[str, object]:
        records = [r for r in self.records if event is None or r.get("event") == event]
        values = sorted(float(r.get("total_ms", 0.0)) for r in records)
        if not values:
            return {"count": 0, "median_ms": 0.0, "p90_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}

        def percentile(p: float) -> float:
            index = min(len(values) - 1, max(0, int((len(values) - 1) * p)))
            return values[index]

        return {
            "count": len(values),
            "median_ms": median(values),
            "p90_ms": percentile(0.90),
            "p95_ms": percentile(0.95),
            "max_ms": max(values),
        }


class GuiStallDetector(QObject):
    """Opt-in event-loop gap detector for test/performance runs."""

    def __init__(
        self,
        probe: PerformanceProbe,
        parent: QObject | None = None,
        *,
        interval_ms: int = 20,
        thresholds_ms: tuple[float, ...] = _DEFAULT_THRESHOLDS_MS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(parent)
        self.probe = probe
        self.interval_ms = max(5, int(interval_ms))
        self.thresholds_ms = tuple(sorted(float(t) for t in thresholds_ms))
        self.clock = clock or time.perf_counter
        self.timer = QTimer(self)
        self.timer.setInterval(self.interval_ms)
        self.timer.timeout.connect(self._tick)
        self._last_tick: float | None = None
        self.gaps_ms: list[float] = []
        self.stages: list[str] = []

    def start(self) -> None:
        if not self.probe.enabled:
            return
        self._last_tick = self.clock()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self._last_tick = None

    def record_gap(self, elapsed_ms: float, stage: str = "event_loop") -> None:
        elapsed_ms = max(0.0, float(elapsed_ms))
        self.gaps_ms.append(elapsed_ms)
        if not self.thresholds_ms or elapsed_ms <= self.thresholds_ms[0]:
            return
        threshold = max(t for t in self.thresholds_ms if elapsed_ms > t)
        self.stages.append(_safe_token(stage))
        self.probe.mark_event(
            "stall",
            "gap",
            threshold_ms=threshold,
            elapsed_ms=elapsed_ms,
            source_stage=stage,
        )

    def _tick(self) -> None:
        now = self.clock()
        if self._last_tick is None:
            self._last_tick = now
            return
        elapsed_ms = (now - self._last_tick) * 1000.0
        self._last_tick = now
        self.record_gap(elapsed_ms, self.probe.active_stage)

    def summary(self) -> dict[str, object]:
        stalled = sorted(value for value in self.gaps_ms if value > self.thresholds_ms[0]) if self.thresholds_ms else []
        if not stalled:
            return {"count": 0, "max_ms": 0.0, "p95_ms": 0.0, "by_threshold": {}}
        index = min(len(stalled) - 1, max(0, int((len(stalled) - 1) * 0.95)))
        by_threshold = {
            str(int(threshold)): sum(1 for value in stalled if value > threshold)
            for threshold in self.thresholds_ms
        }
        return {
            "count": len(stalled),
            "max_ms": max(stalled),
            "p95_ms": stalled[index],
            "by_threshold": by_threshold,
        }


@dataclass
class _PendingPaint:
    trace: PerformanceTrace
    first_paint_stage: str
    interactive_stage: str


class PerformancePaintObserver(QObject):
    """Mark the first Qt paint and the next event-loop turn for a surface."""

    def __init__(self, probe: PerformanceProbe, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.probe = probe
        self.widgets: dict[str, QObject] = {}
        self.pending: dict[str, list[_PendingPaint]] = {}

    def observe(self, surface: str, widget: QObject) -> None:
        if not self.probe.enabled:
            return
        self.widgets[surface] = widget
        self.pending.setdefault(surface, [])
        widget.installEventFilter(self)

    def arm(
        self,
        surface: str,
        trace: PerformanceTrace | None,
        *,
        first_paint_stage: str = "first_paint",
        interactive_stage: str = "interactive",
    ) -> None:
        if not self.probe.enabled or trace is None:
            return
        if surface not in self.widgets:
            trace.finish("paint_unobserved", surface=surface)
            return
        self.pending.setdefault(surface, []).append(
            _PendingPaint(trace, first_paint_stage, interactive_stage)
        )
        widget = self.widgets[surface]
        if hasattr(widget, "update"):
            widget.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Paint:
            return False
        surface = next((key for key, widget in self.widgets.items() if widget is watched), None)
        if surface is None:
            return False
        pending = self.pending.pop(surface, [])
        if not pending:
            return False
        for item in pending:
            item.trace.mark(item.first_paint_stage)

        def finish_interactive() -> None:
            for item in pending:
                item.trace.finish(item.interactive_stage, surface=surface)

        QTimer.singleShot(0, finish_interactive)
        return False


__all__ = [
    "EVENT_LABELS",
    "GuiStallDetector",
    "PerformancePaintObserver",
    "PerformanceProbe",
    "PerformanceTrace",
    "emit_performance_event",
    "format_performance_event",
    "performance_stage",
    "performance_mode_enabled",
]
