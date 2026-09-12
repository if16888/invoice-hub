from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    with (ROOT / path).open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path: str, text: str) -> None:
    with (ROOT / path).open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 exact match, found {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, replacement, label: str, *, flags: int = 0) -> str:
    matches = list(re.finditer(pattern, text, flags))
    if len(matches) != 1:
        raise RuntimeError(f"{label}: expected 1 regex match, found {len(matches)}")
    match = matches[0]
    value = replacement(match) if callable(replacement) else replacement
    return text[: match.start()] + value + text[match.end() :]


# ---------------------------------------------------------------------------
# 1. Browser scan cancellation / launch boundedness.
# ---------------------------------------------------------------------------
link_path = "scripts/invoice_fetch/link_downloader.py"
text = read(link_path)

text = replace_once(
    text,
    """                attempted_count += 1\n                r = self._download_url(url, mail_uid, len(results), date_str, disable_fallback=has_official_success)\n                if r:\n""",
    """                self._check_cancelled()\n                attempted_count += 1\n                r = self._download_url(url, mail_uid, len(results), date_str, disable_fallback=has_official_success)\n                self._check_cancelled()\n                if r:\n""",
    "low-priority scan cancellation",
)

text = replace_once(
    text,
    """        except Exception as exc:\n            _log.error(\"Playwright start failed: %s\", exc)\n            return None\n""",
    """        except Exception as exc:\n            # Cancellation is control flow, not a browser-start failure.  Re-check\n            # after any launch exception so a close/cancel request cannot be swallowed.\n            self._check_cancelled()\n            _log.error(\"Playwright start failed: %s\", exc)\n            return None\n""",
    "browser-start cancellation propagation",
)

text = replace_once(
    text,
    """            kwargs = {\n                \"headless\": not self._headed,\n                \"args\": launch_args,\n            }\n""",
    """            kwargs = {\n                \"headless\": not self._headed,\n                \"args\": launch_args,\n                \"timeout\": self._timeout,\n            }\n""",
    "browser launch timeout",
)
write(link_path, text)


# ---------------------------------------------------------------------------
# 2. Evidence idempotency: byte hash first, stable visible-PDF-text fingerprint
#    as a second exact-content signal for regenerated PDFs whose metadata differs.
# ---------------------------------------------------------------------------
services_path = "scripts/invoice_fetch/services.py"
text = read(services_path)

helper = '''\n\ndef _semantic_evidence_fingerprint(path: str | Path) -> str:\n    """Return a stable fingerprint for PDFs with identical visible text."""\n    p = Path(path)\n    if not p.exists() or p.suffix.lower() != ".pdf":\n        return ""\n    try:\n        visible_text = _extract_pdf_text_simple(p)\n    except Exception:\n        return ""\n    normalized = re.sub(r"\\s+", " ", str(visible_text or "")).strip().casefold()\n    # Avoid treating tiny/blank extraction results as identity evidence.\n    if len(normalized) < 32:\n        return ""\n    digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()\n    return f"pdftext:{digest}"\n'''

text = sub_once(
    text,
    r"(?m)^def _attach_evidence_to_invoice\(",
    lambda m: helper + "\n" + m.group(0),
    "semantic evidence helper insertion",
)

text = sub_once(
    text,
    r'''(?s)(def _attach_evidence_to_invoice\(.*?    att_dir = RUNTIME_DIR / "attachments"\r?\n)(\r?\n    renamed_rel = _rename_by_invoice_code\()''',
    lambda m: m.group(1)
    + '''\n    extra_paths = _normalize_path_list(invoice.get("extra_paths"))\n    incoming_semantic = _semantic_evidence_fingerprint(file_path)\n    if incoming_semantic:\n        for existing_path in extra_paths:\n            resolved = _resolve_runtime_path(existing_path)\n            if resolved and _semantic_evidence_fingerprint(resolved) == incoming_semantic:\n                _log.info(\n                    "  检测到语义相同证明材料，复用已有关联: invoice_id=%s file=%s",\n                    invoice["id"],\n                    mask_filename(file_path.name),\n                )\n                return False\n'''
    + m.group(2),
    "single evidence semantic precheck",
)

text = sub_once(
    text,
    r'''(?s)(def _attach_evidence_to_invoice\(.*?    stored_path = renamed_rel\r?\n\r?\n)    extra_paths = _normalize_path_list\(invoice.get\("extra_paths"\)\)\r?\n(    if stored_path in extra_paths:)''',
    lambda m: m.group(1) + m.group(2),
    "single evidence duplicate extra_paths declaration",
)

text = replace_once(
    text,
    '''    # Pre-calculate hashes of existing extras\n    existing_hashes = set()\n    for ep in current_extras:\n        res = _resolve_runtime_path(ep)\n        if res and res.exists():\n            try:\n                existing_hashes.add(_sha256_file(res))\n            except Exception:\n                pass\n\n    updated = False\n''',
    '''    # Pre-calculate byte and visible-text fingerprints of existing extras.\n    existing_hashes = set()\n    existing_semantic_fingerprints = set()\n    for ep in current_extras:\n        res = _resolve_runtime_path(ep)\n        if res and res.exists():\n            try:\n                existing_hashes.add(_sha256_file(res))\n            except Exception:\n                pass\n            semantic = _semantic_evidence_fingerprint(res)\n            if semantic:\n                existing_semantic_fingerprints.add(semantic)\n\n    updated = False\n''',
    "existing evidence fingerprint set",
)

text = replace_once(
    text,
    '''        e_path = Path(e.file_path)\n        source_path = ""\n        if e_path.exists():\n            source_path = str(e_path.resolve())\n            kept_paths.add(source_path)\n            try:\n                h = _sha256_file(e_path)\n                if h in existing_hashes:\n                    if attached_source_paths is not None:\n                        attached_source_paths.add(source_path)\n                    continue\n            except Exception:\n                pass\n\n        ep = _rename_by_invoice_code(\n''',
    '''        e_path = Path(e.file_path)\n        source_path = ""\n        incoming_semantic = ""\n        if e_path.exists():\n            source_path = str(e_path.resolve())\n            incoming_semantic = _semantic_evidence_fingerprint(e_path)\n            if incoming_semantic and incoming_semantic in existing_semantic_fingerprints:\n                if attached_source_paths is not None:\n                    attached_source_paths.add(source_path)\n                _log.info(\n                    "  检测到语义相同证明材料，跳过重复追加: invoice_id=%s file=%s",\n                    invoice_id,\n                    mask_filename(getattr(e, "original_name", e_path.name)),\n                )\n                continue\n            kept_paths.add(source_path)\n            try:\n                h = _sha256_file(e_path)\n                if h in existing_hashes:\n                    if attached_source_paths is not None:\n                        attached_source_paths.add(source_path)\n                    continue\n            except Exception:\n                pass\n\n        ep = _rename_by_invoice_code(\n''',
    "incoming evidence semantic precheck",
)

text = replace_once(
    text,
    '''            current_extras.append(ep)\n            updated = True\n            if attached_source_paths is not None and source_path:\n''',
    '''            current_extras.append(ep)\n            if incoming_semantic:\n                existing_semantic_fingerprints.add(incoming_semantic)\n            updated = True\n            if attached_source_paths is not None and source_path:\n''',
    "new evidence semantic fingerprint registration",
)
write(services_path, text)


# ---------------------------------------------------------------------------
# 3. Closing the main window must never perform an unbounded QThread.wait().
#    Give active workers a tiny cooperative grace period; if still running,
#    return to the Qt event loop and retry later while keeping SQLite open.
# ---------------------------------------------------------------------------
app_path = "scripts/invoice_fetch/gui/app.py"
text = read(app_path)

shutdown_helper_pattern = r'''(?s)    def _shutdown_background_workers\(self\) -> None:\n        """Cooperatively stop all window-owned workers before closing SQLite\.""".*?\n\n    def _try_begin_data_operation\('''

def build_shutdown_helper(match: re.Match[str]) -> str:
    return '''    def _shutdown_background_workers(self, wait_ms: int = 50) -> bool:\n        """Request cooperative worker shutdown without blocking the GUI indefinitely."""\n        running = []\n        for attr, label, worker in self._active_background_workers():\n            is_running = getattr(worker, "isRunning", None)\n            if not callable(is_running) or not is_running():\n                self._disconnect_worker_signals(worker)\n                self._end_data_operation(label)\n                continue\n            self._disconnect_worker_signals(worker)\n            block_signals = getattr(worker, "blockSignals", None)\n            if callable(block_signals):\n                block_signals(True)\n            request_cancel = getattr(worker, "request_cancel", None)\n            if callable(request_cancel):\n                request_cancel()\n            running.append((attr, label, worker))\n\n        all_stopped = True\n        bounded_wait_ms = max(0, int(wait_ms))\n        for attr, label, worker in running:\n            wait = getattr(worker, "wait", None)\n            if callable(wait) and bounded_wait_ms:\n                try:\n                    wait(bounded_wait_ms)\n                except TypeError:\n                    # Never fall back to wait() without a timeout.  Non-QThread\n                    # test doubles or foreign workers are handled by polling.\n                    pass\n            is_running = getattr(worker, "isRunning", None)\n            if callable(is_running) and is_running():\n                all_stopped = False\n                continue\n            if attr == "_export_migration_worker" and getattr(worker, "result", None) is not None:\n                self._export_migration = worker.result\n            self._end_data_operation(label)\n\n        return all_stopped\n\n    def _try_begin_data_operation('''

text = sub_once(text, shutdown_helper_pattern, build_shutdown_helper, "bounded background-worker shutdown")

text = replace_once(
    text,
    '''        with performance_stage(\n            "shutdown",\n            "background_worker_shutdown",\n            active=bool(running_workers),\n            worker_count=len(running_workers),\n            timeout_requested="none",\n        ):\n            self._shutdown_background_workers()\n        if shutdown_trace is not None and running_workers:\n            shutdown_trace.mark("worker_shutdown")\n''',
    '''        with performance_stage(\n            "shutdown",\n            "background_worker_shutdown",\n            active=bool(running_workers),\n            worker_count=len(running_workers),\n            timeout_requested=50,\n        ):\n            workers_stopped = self._shutdown_background_workers(wait_ms=50)\n        if not workers_stopped:\n            self._close_pending = True\n            self.statusBar().showMessage("正在安全停止后台操作，窗口仍可响应，请稍候…")\n            event.ignore()\n            if not getattr(self, "_worker_shutdown_retry_scheduled", False):\n                self._worker_shutdown_retry_scheduled = True\n                QTimer.singleShot(100, self._retry_close_after_worker_shutdown)\n            return\n        if shutdown_trace is not None and running_workers:\n            shutdown_trace.mark("worker_shutdown")\n''',
    "closeEvent bounded worker handshake",
)

text = replace_once(
    text,
    '''        if shutdown_trace is not None:\n            self._performance_probe.active_stage = "close_event_accept"\n            shutdown_trace.mark("close_event_accepted")\n        event.accept()\n''',
    '''        if shutdown_trace is not None:\n            self._performance_probe.active_stage = "close_event_accept"\n            shutdown_trace.mark("close_event_accepted")\n        self._close_pending = False\n        self._worker_shutdown_retry_scheduled = False\n        event.accept()\n''',
    "closeEvent final pending-state clear",
)

text = replace_once(
    text,
    '''    def _retry_close_after_mobile_shutdown(self):\r\n        if getattr(self, "_close_pending", False):\r\n            QTimer.singleShot(0, self.close)\r\n''',
    '''    def _retry_close_after_mobile_shutdown(self):\r\n        if getattr(self, "_close_pending", False):\r\n            QTimer.singleShot(0, self.close)\r\n\r\n    def _retry_close_after_worker_shutdown(self):\r\n        """Poll worker completion without blocking the Qt GUI thread."""\r\n        self._worker_shutdown_retry_scheduled = False\r\n        if not getattr(self, "_close_pending", False):\r\n            return\r\n        running = [\r\n            worker\r\n            for _attr, _label, worker in self._active_background_workers()\r\n            if callable(getattr(worker, "isRunning", None)) and worker.isRunning()\r\n        ]\r\n        if running:\r\n            self._worker_shutdown_retry_scheduled = True\r\n            QTimer.singleShot(100, self._retry_close_after_worker_shutdown)\r\n            return\r\n        QTimer.singleShot(0, self.close)\r\n''',
    "background worker close retry",
)
write(app_path, text)


# ---------------------------------------------------------------------------
# 4. Regression coverage for the reproduced PERF-SHUTDOWN-002 path.
# ---------------------------------------------------------------------------
test_path = "tests/test_runtime_safety.py"
text = read(test_path)
text = replace_once(
    text,
    '''    def wait(self):\n        self.wait_calls += 1\n        self.db_open_during_wait.append(self.window.db.is_open)\n        self._running = False\n        return True\n''',
    '''    def wait(self, *_args, **_kwargs):\n        self.wait_calls += 1\n        self.db_open_during_wait.append(self.window.db.is_open)\n        self._running = False\n        return True\n''',
    "controlled worker bounded wait signature",
)

new_test = '''\n    def test_stuck_scan_close_returns_to_event_loop_and_keeps_db_open(self):\n        class StuckWorker(_ControlledWorker):\n            def wait(self, *_args, **_kwargs):\n                self.wait_calls += 1\n                self.db_open_during_wait.append(self.window.db.is_open)\n                return False\n\n        with tempfile.TemporaryDirectory() as td:\n            window = self._window(td)\n            worker = StuckWorker(window, running=True, cancellable=True)\n            self.assertTrue(window._try_begin_data_operation("邮箱扫描", notify=False))\n            window.scan_worker = worker\n\n            event = self._QCloseEvent()\n            started = time.monotonic()\n            window.closeEvent(event)\n            elapsed = time.monotonic() - started\n\n            self.assertFalse(event.isAccepted())\n            self.assertLess(elapsed, 0.5)\n            self.assertEqual(worker.cancel_calls, 1)\n            self.assertEqual(worker.wait_calls, 1)\n            self.assertEqual(worker.db_open_during_wait, [True])\n            self.assertTrue(window.db.is_open)\n            self.assertTrue(window._close_pending)\n\n            # Once the worker exits, the next close finalizes state and SQLite.\n            worker._running = False\n            final_event = self._QCloseEvent()\n            window.closeEvent(final_event)\n            self.assertTrue(final_event.isAccepted())\n            self.assertFalse(window.db.is_open)\n            self.assertEqual(window._data_operation_gate.owner, "")\n            self.assertFalse(window._close_pending)\n\n            window.deleteLater()\n            self._QCoreApplication.processEvents()\n'''

text = replace_once(
    text,
    '''    def test_no_active_worker_closes_immediately(self):\n''',
    new_test + '''\n    def test_no_active_worker_closes_immediately(self):\n''',
    "stuck scan shutdown regression test",
)
write(test_path, text)

print("v0.1.8 bounded scan + responsive shutdown patch applied")
