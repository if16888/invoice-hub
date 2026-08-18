"""Parent Watchdog Runner for Invoice Hub HCI Acceptance Harness.

Executes all 19 HCI scenarios in an isolated child process with:
- Win32 Toolhelp tree tracking (python.exe, pythonw.exe, InvoiceHub.exe, QtWebEngineProcess.exe)
- Periodic background sampling of child descendants during execution
- Precise child-tree isolation (only tracks processes derived from the test child)
- Windows native crash code detection (0xC0000005 Access Violation, etc.)
- Parent watchdog timeout protection and tree-kill
- Machine-readable report.json & human-readable HCI_ACCEPTANCE.md generation
- Repetition loop runner support (--repeat N)

Usage:
    python scripts/dev/run_hci_acceptance.py
    python scripts/dev/run_hci_acceptance.py --repeat 20
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Known Windows abnormal termination exit codes
KNOWN_NATIVE_CRASH_CODES = {
    -1073741819: "0xC0000005 (Access Violation)",
    3221225477: "0xC0000005 (Access Violation)",
    -1073741571: "0xC00000FD (Stack Overflow)",
    3221225725: "0xC00000FD (Stack Overflow)",
    -1073740791: "0xC0000409 (Stack Buffer Overrun)",
    3221226505: "0xC0000409 (Stack Buffer Overrun)",
    -1073740940: "0xC0000374 (Heap Corruption)",
    3221226356: "0xC0000374 (Heap Corruption)",
}


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _get_process_tree() -> dict[int, tuple[int, str]]:
    """Capture snapshot of all active Windows processes: PID -> (PPID, ExeName)."""
    if sys.platform != "win32":
        return {}
    h_snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if h_snapshot == -1:
        return {}
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    tree: dict[int, tuple[int, str]] = {}
    if ctypes.windll.kernel32.Process32First(h_snapshot, ctypes.byref(pe)):
        while True:
            pid = int(pe.th32ProcessID)
            ppid = int(pe.th32ParentProcessID)
            name = pe.szExeFile.decode("mbcs", errors="replace")
            tree[pid] = (ppid, name)
            if not ctypes.windll.kernel32.Process32Next(h_snapshot, ctypes.byref(pe)):
                break
    ctypes.windll.kernel32.CloseHandle(h_snapshot)
    return tree


def _get_child_descendant_pids(parent_pid: int, tree: dict[int, tuple[int, str]]) -> set[int]:
    """Find all transitive child and grandchild process IDs for parent_pid."""
    children = set()
    to_check = {parent_pid}
    while to_check:
        next_check = set()
        for pid, (ppid, _name) in tree.items():
            if ppid in to_check and pid not in children and pid != parent_pid:
                children.add(pid)
                next_check.add(pid)
        to_check = next_check
    return children


def _sample_descendants_loop(
    child_pid: int,
    known_pids: set[int],
    stop_event: threading.Event,
    interval_sec: float = 0.2,
) -> None:
    """Continuously sample process tree during child execution to register spawned descendants."""
    while not stop_event.is_set():
        try:
            tree = _get_process_tree()
            descendants = _get_child_descendant_pids(child_pid, tree)
            known_pids.update(descendants)
            for pid, (ppid, _name) in tree.items():
                if ppid in known_pids:
                    known_pids.add(pid)
        except Exception:
            pass
        stop_event.wait(interval_sec)


def _run_child_suite() -> int:
    """Child process execution: runs all 19 scenarios and dumps JSON to stdout."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QMessageBox

    from scripts.invoice_fetch.db import InvoiceDB
    from scripts.invoice_fetch.gui.app import InvoiceReviewApp
    from tests.hci_acceptance.fixtures import populate_synthetic_db
    from tests.hci_acceptance.harness import (
        HarnessReport,
        ScenarioResult,
        cleanup_window,
        find_running_qthreads,
    )
    from tests.hci_acceptance.scenarios import ALL_SCENARIOS

    app = QApplication.instance() or QApplication([])
    report = HarnessReport()

    with (
        patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes),
        patch("PySide6.QtWidgets.QMessageBox.warning", return_value=QMessageBox.Ok),
        patch("PySide6.QtWidgets.QMessageBox.information", return_value=QMessageBox.Ok),
        patch("PySide6.QtWidgets.QMessageBox.critical", return_value=QMessageBox.Ok),
    ):
        for scenario_id, title, runner in ALL_SCENARIOS:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                db_path = root / "invoices.db"
                runtime_dir = root / "runtime"
                runtime_dir.mkdir(parents=True, exist_ok=True)

                with InvoiceDB(db_path) as seed_db:
                    populate_synthetic_db(seed_db, runtime_dir)

                window = InvoiceReviewApp(db_path)
                window.resize(1600, 900)
                window.show()

                for _ in range(5):
                    app.processEvents()

                try:
                    res: ScenarioResult = runner(window, window.db, app)
                except Exception as exc:
                    res = ScenarioResult(
                        id=scenario_id,
                        title=title,
                        passed=False,
                        error_message=str(exc),
                        broken_invariant=f"Unhandled exception: {exc}",
                    )

                cleanup_window(window, app)

            report.scenarios.append(res)
            status = "PASS" if res.passed else "FAIL"
            print(f"  {res.id:<10} {res.title:<30} {status}", flush=True)

    report.residual_threads = len(find_running_qthreads())
    report.native_crash = False

    print("--- HCI_REPORT_JSON_START ---", flush=True)
    print(json.dumps(report.to_json(), ensure_ascii=False), flush=True)
    print("--- HCI_REPORT_JSON_END ---", flush=True)

    return 0 if report.accepted else 1


def run_single_watchdog(timeout_seconds: int = 120, verbose: bool = True) -> tuple[int, dict]:
    """Execute a single child run monitored by the parent watchdog with active descendant sampling."""
    start_time = time.monotonic()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    child_cmd = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--child-mode"]
    proc = subprocess.Popen(
        child_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    child_pid = proc.pid

    # Actively sample tree during runtime to record any direct child / grandchild / descendant PIDs
    known_spawned_pids: set[int] = set()
    timed_out = False
    stop_sampler = threading.Event()
    sampler_thread = threading.Thread(
        target=_sample_descendants_loop,
        args=(child_pid, known_spawned_pids, stop_sampler),
        daemon=True,
    )
    sampler_thread.start()

    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(child_pid)], capture_output=True)
        except Exception:
            proc.kill()
        stdout, stderr = proc.communicate()
        timed_out = True
        exit_code = -999
    finally:
        stop_sampler.set()
        sampler_thread.join(timeout=1.0)

    duration = time.monotonic() - start_time

    # Inspect process tree post-execution for any residual children derived from child_pid
    after_tree = _get_process_tree()
    residual_pids = set()

    # 1. Did the child process itself fail to terminate?
    if child_pid in after_tree:
        residual_pids.add(child_pid)

    # 2. Are there any orphan descendants in known_spawned_pids that remain active?
    for kpid in known_spawned_pids:
        if kpid in after_tree:
            residual_pids.add(kpid)

    # 3. Are there any orphan descendants whose PPID was child_pid or in known_spawned_pids?
    for pid, (ppid, _name) in after_tree.items():
        if ppid == child_pid or ppid in known_spawned_pids:
            residual_pids.add(pid)

    # Categorize residual processes
    residual_python = 0
    residual_invoicehub = 0
    residual_qtwebengine = 0

    for rpid in residual_pids:
        exe_name = after_tree.get(rpid, (0, ""))[1].lower()
        if "python" in exe_name:
            residual_python += 1
        elif "invoicehub" in exe_name:
            residual_invoicehub += 1
        elif "qtwebengine" in exe_name:
            residual_qtwebengine += 1
        # Kill orphan residual
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(rpid)], capture_output=True)
        except Exception:
            pass

    # Check for native crash
    is_native_crash = False
    crash_reason = ""
    if exit_code in KNOWN_NATIVE_CRASH_CODES:
        is_native_crash = True
        crash_reason = KNOWN_NATIVE_CRASH_CODES[exit_code]
    elif exit_code < 0 and not timed_out:
        is_native_crash = True
        crash_reason = f"Abnormal negative exit code {exit_code}"

    # Parse JSON report
    parsed_report = None
    if "--- HCI_REPORT_JSON_START ---" in stdout:
        try:
            start_idx = stdout.index("--- HCI_REPORT_JSON_START ---") + len("--- HCI_REPORT_JSON_START ---")
            end_idx = stdout.index("--- HCI_REPORT_JSON_END ---")
            json_str = stdout[start_idx:end_idx].strip()
            parsed_report = json.loads(json_str)
        except Exception:
            pass

    if verbose:
        for line in stdout.splitlines():
            if "--- HCI_REPORT_JSON_" in line:
                break
            print(line)

    from tests.hci_acceptance.harness import HarnessReport, ScenarioResult, write_report

    report = HarnessReport()
    report.native_crash = is_native_crash
    report.timeout = timed_out
    report.residual_python = residual_python
    report.residual_invoicehub = residual_invoicehub
    report.residual_qtwebengine = residual_qtwebengine

    if parsed_report:
        report.residual_threads = parsed_report.get("summary", {}).get("residual_threads", 0)
        for item in parsed_report.get("scenarios", []):
            report.scenarios.append(
                ScenarioResult(
                    id=item["id"],
                    title=item["title"],
                    passed=item["passed"],
                    backend_expected=item.get("backend_expected", {}),
                    backend_actual=item.get("backend_actual", {}),
                    ui_expected=item.get("ui_expected", {}),
                    ui_actual=item.get("ui_actual", {}),
                    broken_invariant=item.get("broken_invariant"),
                    duration_ms=item.get("duration_ms", 0),
                    error_message=item.get("error_message"),
                )
            )
    else:
        report.scenarios.append(
            ScenarioResult(
                id="HARNESS-WATCHDOG",
                title="Child Process Execution",
                passed=False,
                broken_invariant=f"Child execution failed (exit={exit_code}, crash={crash_reason or 'None'}, timeout={timed_out})",
                error_message=stderr[:1000] if stderr else "No stderr captured",
            )
        )

    artifact_override = os.environ.get("HCI_ARTIFACT_DIR")
    artifact_dir = (
        Path(artifact_override)
        if artifact_override
        else PROJECT_ROOT / "artifacts" / "hci_acceptance"
    )
    json_path, md_path = write_report(report, artifact_dir)

    metrics = {
        "passed": report.passed,
        "failed": report.failed,
        "total": report.total,
        "native_crash": is_native_crash,
        "crash_reason": crash_reason,
        "timeout": timed_out,
        "residual_threads": report.residual_threads,
        "residual_python": residual_python,
        "residual_invoicehub": residual_invoicehub,
        "residual_qtwebengine": residual_qtwebengine,
        "duration_seconds": duration,
        "json_path": str(json_path),
        "md_path": str(md_path),
    }

    if verbose:
        print("=" * 60)
        print(f"\n{report.passed} / {report.total} PASS\n")
        print(f"Backend/UI invariant failures: {report.failed}")
        print(f"Residual QThreads: {report.residual_threads}")
        print(f"Residual Python: {residual_python}")
        print(f"Residual InvoiceHub: {residual_invoicehub}")
        print(f"Residual QtWebEngine: {residual_qtwebengine}")
        print(f"Native crashes: {int(is_native_crash)} {f'({crash_reason})' if crash_reason else ''}")
        print(f"Timeout: {timed_out}")
        print(f"Execution duration: {duration:.2f}s")
        print(f"\nReport written to: {json_path}")
        print(f"Markdown written to: {md_path}\n")

    status_ok = report.accepted
    return (0 if status_ok else 1), metrics


def run_parent_watchdog(repeat_count: int = 1, timeout_seconds: int = 120) -> int:
    """Run watchdog suite with optional repetition loop."""
    print("=" * 60, flush=True)
    print(f"Invoice Hub HCI Acceptance Harness (Watchdog - {repeat_count} Run{'s' if repeat_count > 1 else ''})", flush=True)
    print("=" * 60, flush=True)

    total_pass = 0
    total_fail = 0
    total_timeout = 0
    total_native_crash = 0
    max_res_python = 0
    max_res_invoicehub = 0
    max_res_qtwebengine = 0
    max_res_threads = 0
    last_metrics: dict = {}

    for i in range(1, repeat_count + 1):
        if repeat_count > 1:
            print(f"\n>>> [Run {i}/{repeat_count}] Starting...", flush=True)
        code, m = run_single_watchdog(timeout_seconds=timeout_seconds, verbose=(repeat_count == 1))
        last_metrics = m
        if code == 0:
            total_pass += 1
            if repeat_count > 1:
                print(f">>> [Run {i}/{repeat_count}] PASS ({m['passed']}/{m['total']} scenarios, {m['duration_seconds']:.1f}s)", flush=True)
        else:
            total_fail += 1
            if repeat_count > 1:
                print(f">>> [Run {i}/{repeat_count}] FAIL (failed={m['failed']}, crash={m['native_crash']}, timeout={m['timeout']})", flush=True)

        if m["timeout"]:
            total_timeout += 1
        if m["native_crash"]:
            total_native_crash += 1

        max_res_python = max(max_res_python, m["residual_python"])
        max_res_invoicehub = max(max_res_invoicehub, m["residual_invoicehub"])
        max_res_qtwebengine = max(max_res_qtwebengine, m["residual_qtwebengine"])
        max_res_threads = max(max_res_threads, m["residual_threads"])

    if repeat_count > 1:
        print("\n" + "=" * 60, flush=True)
        print("20-RUN RELIABILITY SUMMARY", flush=True)
        print("=" * 60, flush=True)
        print(f"Runs: {repeat_count}", flush=True)
        print(f"Pass: {total_pass}", flush=True)
        print(f"Fail: {total_fail}", flush=True)
        print(f"Timeout: {total_timeout}", flush=True)
        print(f"Native crash: {total_native_crash}", flush=True)
        print(f"Residual Python: {max_res_python}", flush=True)
        print(f"Residual InvoiceHub: {max_res_invoicehub}", flush=True)
        print(f"Residual QtWebEngine: {max_res_qtwebengine}", flush=True)
        print(f"Residual QThreads: {max_res_threads}", flush=True)
        print("=" * 60, flush=True)

    all_runs_accepted = total_pass == repeat_count and total_fail == 0
    final_exit_code = 0 if all_runs_accepted else 1
    if repeat_count == 1:
        print(
            "HCI_ACCEPTANCE_SUMMARY "
            f"actual_scenarios={last_metrics.get('total', 0)} "
            f"actual_passed={last_metrics.get('passed', 0)} "
            f"actual_failed={last_metrics.get('failed', 0)} "
            f"exit_code={final_exit_code}",
            flush=True,
        )
    if all_runs_accepted:
        print("HCI ACCEPTANCE: PASS\n", flush=True)
        return final_exit_code
    else:
        print("HCI ACCEPTANCE: FAIL\n", flush=True)
        return final_exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoice Hub HCI Acceptance Runner")
    parser.add_argument("--child-mode", action="store_true", help="Internal child runner mode")
    parser.add_argument("--repeat", type=int, default=1, help="Number of repetitions to run")
    parser.add_argument("--timeout", type=int, default=120, help="Parent watchdog timeout in seconds")
    args = parser.parse_args()

    if args.child_mode:
        code = _run_child_suite()
        sys.exit(code)
    else:
        code = run_parent_watchdog(repeat_count=args.repeat, timeout_seconds=args.timeout)
        sys.exit(code)


if __name__ == "__main__":
    main()
