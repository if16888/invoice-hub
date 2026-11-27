"""Read-only, process-scoped native Windows observation of one startup sample.

The official checker still launches and judges the GUI. This observer does not
create Qt windows, change services, flush caches, or record system-wide traces.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import re
import subprocess
import time


POLL_SECONDS = 0.05
INVALID_HANDLE = ctypes.c_void_p(-1).value
FILETIME_UNIX_OFFSET = 116444736000000000


class ProcessEntry(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("usage", wt.DWORD), ("pid", wt.DWORD),
                ("heap", ctypes.c_size_t), ("module_id", wt.DWORD), ("threads", wt.DWORD),
                ("parent", wt.DWORD), ("priority", wt.LONG), ("flags", wt.DWORD), ("name", wt.WCHAR * 260)]


class ModuleEntry(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("module_id", wt.DWORD), ("pid", wt.DWORD),
                ("global_usage", wt.DWORD), ("process_usage", wt.DWORD), ("base", ctypes.c_void_p),
                ("image_size", wt.DWORD), ("module", wt.HMODULE), ("name", wt.WCHAR * 256), ("path", wt.WCHAR * 260)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class MemoryCounters(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("page_faults", wt.DWORD)] + [(name, ctypes.c_size_t) for name in
                ("peak_working_set", "working_set", "peak_paged_pool", "paged_pool", "peak_nonpaged_pool",
                 "nonpaged_pool", "pagefile", "peak_pagefile", "private_bytes")]


def filetime(value: wt.FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def bind(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = arguments
    return function


def descendant_depth(processes, root: int, target: int) -> int | None:
    parents = {p["pid"]: p.get("parent") for p in processes}
    visited = set()
    depth = 0
    current = target
    while current != root:
        if current in visited or current not in parents:
            return None
        visited.add(current)
        current = parents[current]
        depth += 1
    return depth


class WindowsApi:
    def __init__(self):
        # Loaded only after the official checker has been spawned. None of
        # these calls creates a window or queries a font database.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.snapshot = bind(kernel, "CreateToolhelp32Snapshot", wt.HANDLE, wt.DWORD, wt.DWORD)
        self.close = bind(kernel, "CloseHandle", wt.BOOL, wt.HANDLE)
        self.process_first = bind(kernel, "Process32FirstW", wt.BOOL, wt.HANDLE, ctypes.POINTER(ProcessEntry))
        self.process_next = bind(kernel, "Process32NextW", wt.BOOL, wt.HANDLE, ctypes.POINTER(ProcessEntry))
        self.module_first = bind(kernel, "Module32FirstW", wt.BOOL, wt.HANDLE, ctypes.POINTER(ModuleEntry))
        self.module_next = bind(kernel, "Module32NextW", wt.BOOL, wt.HANDLE, ctypes.POINTER(ModuleEntry))
        self.open_process = bind(kernel, "OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
        self.image_name = bind(kernel, "QueryFullProcessImageNameW", wt.BOOL, wt.HANDLE, wt.DWORD,
                               wt.LPWSTR, ctypes.POINTER(wt.DWORD))
        self.process_times = bind(kernel, "GetProcessTimes", wt.BOOL, wt.HANDLE,
                                  *([ctypes.POINTER(wt.FILETIME)] * 4))
        self.process_io = bind(kernel, "GetProcessIoCounters", wt.BOOL, wt.HANDLE, ctypes.POINTER(IoCounters))
        self.process_memory = bind(psapi, "GetProcessMemoryInfo", wt.BOOL, wt.HANDLE,
                                   ctypes.POINTER(MemoryCounters), wt.DWORD)
        self.wait = bind(kernel, "WaitForSingleObject", wt.DWORD, wt.HANDLE, wt.DWORD)
        self.create_file = bind(kernel, "CreateFileW", wt.HANDLE, wt.LPCWSTR, wt.DWORD, wt.DWORD,
                                ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE)
        self.read_file = bind(kernel, "ReadFile", wt.BOOL, wt.HANDLE, ctypes.c_void_p,
                              wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p)
        self.window_callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        self.enum_windows = bind(user, "EnumWindows", wt.BOOL, self.window_callback, wt.LPARAM)
        self.window_pid = bind(user, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
        self.visible = bind(user, "IsWindowVisible", wt.BOOL, wt.HWND)
        self.window_rect = bind(user, "GetWindowRect", wt.BOOL, wt.HWND, ctypes.POINTER(wt.RECT))
        self.window_style = bind(user, "GetWindowLongPtrW", ctypes.c_ssize_t, wt.HWND, ctypes.c_int)
        self.window_class = bind(user, "GetClassNameW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
        self.window_text = bind(user, "GetWindowTextW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)

    def processes(self) -> list[dict]:
        handle = self.snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if handle == INVALID_HANDLE or not handle:
            return []
        try:
            entry = ProcessEntry()
            entry.size = ctypes.sizeof(entry)
            result = []
            ok = self.process_first(handle, ctypes.byref(entry))
            while ok:
                result.append({"pid": int(entry.pid), "parent": int(entry.parent),
                               "threads": int(entry.threads), "name": str(entry.name)})
                ok = self.process_next(handle, ctypes.byref(entry))
            return result
        finally:
            self.close(handle)

    def open_exact_child(self, processes, checker_pid: int, exe: Path):
        # Only inspect a descendant of the checker with the expected basename;
        # confirm the full executable path before recording any process data.
        descendants = {checker_pid}
        for _ in range(len(processes)):
            added = {p["pid"] for p in processes if p["parent"] in descendants} - descendants
            if not added:
                break
            descendants.update(added)
        for p in processes:
            if p["pid"] == checker_pid or p["pid"] not in descendants or p["name"].lower() != exe.name.lower():
                continue
            handle = self.open_process(0x00100410, False, p["pid"])  # SYNCHRONIZE|QUERY_INFORMATION|VM_READ
            if not handle:
                handle = self.open_process(0x00101000, False, p["pid"])  # limited query + SYNCHRONIZE
            if not handle:
                continue
            size = wt.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if self.image_name(handle, 0, buffer, ctypes.byref(size)) and (
                    os.path.normcase(str(Path(buffer.value).resolve())) == os.path.normcase(str(exe.resolve()))):
                return int(p["pid"]), handle
            self.close(handle)
        return None, None

    def counters(self, handle) -> dict:
        # GetProcessTimes' exit FILETIME is undefined for a live process.
        # The owned SYNCHRONIZE handle gives the authoritative liveness state.
        wait_status = int(self.wait(handle, 0))
        result = {"exited": True if wait_status == 0 else False if wait_status == 258 else None,
                  "wait_status": wait_status}
        creation, exit_time, kernel, user = (wt.FILETIME() for _ in range(4))
        if self.process_times(handle, *(ctypes.byref(x) for x in (creation, exit_time, kernel, user))):
            result.update(creation_unix_ms=(filetime(creation) - FILETIME_UNIX_OFFSET) / 10000,
                          kernel_cpu_ms=filetime(kernel) / 10000, user_cpu_ms=filetime(user) / 10000)
        io = IoCounters()
        if self.process_io(handle, ctypes.byref(io)):
            result.update(read_ops=int(io.read_ops), read_bytes=int(io.read_bytes),
                          write_ops=int(io.write_ops), write_bytes=int(io.write_bytes))
        memory = MemoryCounters()
        memory.size = ctypes.sizeof(memory)
        if self.process_memory(handle, ctypes.byref(memory), memory.size):
            result.update(page_faults=int(memory.page_faults), working_set_bytes=int(memory.working_set),
                          private_bytes=int(memory.private_bytes))
        return result

    def read_probe(self, path: Path) -> bytes:
        # The official checker deletes this synthetic file as soon as it has
        # read its own evidence. Share deletion AND concurrent reads/writes.
        # A normal Python open on Windows can deny that unlink.
        handle = self.create_file(str(path), 0x80000000, 0x7, None, 3, 0x80, None)
        if not handle or handle == INVALID_HANDLE:
            return b""
        try:
            buffer = ctypes.create_string_buffer(65536)
            count = wt.DWORD()
            if self.read_file(handle, buffer, len(buffer), ctypes.byref(count), None):
                return buffer.raw[:count.value]
            return b""
        finally:
            self.close(handle)

    def windows(self, pid: int) -> list[dict] | None:
        result = []

        @self.window_callback
        def visit(hwnd, _argument):
            owner = wt.DWORD()
            thread = int(self.window_pid(hwnd, ctypes.byref(owner)))
            if owner.value != pid:
                return True
            rect = wt.RECT()
            rect_valid = bool(self.window_rect(hwnd, ctypes.byref(rect)))
            style = int(self.window_style(hwnd, -20))  # GWL_EXSTYLE
            title = ctypes.create_unicode_buffer(128)
            cls = ctypes.create_unicode_buffer(128)
            self.window_text(hwnd, title, len(title))
            self.window_class(hwnd, cls, len(cls))
            main_like = title.value.startswith("Invoice Hub ")
            tool = bool(style & 0x80)  # WS_EX_TOOLWINDOW
            width = int(rect.right - rect.left) if rect_valid else None
            height = int(rect.bottom - rect.top) if rect_valid else None
            splash_like = (tool and cls.value.lower().startswith("qt") and width and height
                           and width >= 200 and height >= 100 and 1.2 <= width / height <= 2.8)
            result.append({"hwnd": int(hwnd), "class": cls.value, "visible": bool(self.visible(hwnd)),
                           "thread_id": thread,
                           "width": width, "height": height,
                           "tool": tool, "layered": bool(style & 0x80000),
                           "role": "main-like" if main_like else "splash-like" if splash_like else "other"})
            # Do not record any captions, paths or windows of other processes.
            return True

        if not self.enum_windows(visit, 0):
            return None
        return result

    def modules(self, pid: int) -> dict:
        handle = self.snapshot(0x00000018, pid)  # SNAPMODULE|SNAPMODULE32
        if handle == INVALID_HANDLE or not handle:
            return {"unavailable": True}
        try:
            entry = ModuleEntry()
            entry.size = ctypes.sizeof(entry)
            names = set()
            ok = self.module_first(handle, ctypes.byref(entry))
            if not ok:
                return {"unavailable": True}
            while ok:
                names.add(str(entry.name))
                ok = self.module_next(handle, ctypes.byref(entry))
            return {"module_count": len(names), "notable_basenames": sorted(
                n for n in names if re.search(r"qt|font|dwrite|d2d|gdi|user32|win32u|dwm|python", n, re.I))}
        finally:
            self.close(handle)


def run_observed_checker(command, *, cwd: Path, env: dict, log: Path, exe: Path, trace_path: Path,
                         timeout: int = 75, etw=None) -> tuple[int, dict]:
    """Launch once; failures in observation never replace the checker's exit."""
    trace = {"requested_interval_ms": POLL_SECONDS * 1000, "clock": "observer monotonic plus OS process creation FILETIME",
             "scope": "verified descendant executable only", "samples": [], "events": {}, "module_snapshots": {},
             "limitations": "Sampled window visibility is not compositor/paint evidence. I/O counters are logical process I/O, page faults include soft/hard faults, and CPU is process-wide. No system-wide ETW or font filenames."}
    started = time.monotonic()
    handle = None
    api = None
    pid = None
    process_origin = None
    saw_probe = False
    saw_valid_probe = False
    ui_threads = set()
    event_fields = ("observer_ms", "process_ms", "kernel_cpu_ms", "user_cpu_ms", "read_ops", "read_bytes", "page_faults", "threads", "qpc_ms")
    with log.open("wb") as output:
        checker = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
        trace["checker_pid"] = checker.pid
        try:
            if etw is not None:
                etw.checker_started(checker.pid)
            api = WindowsApi()
            while checker.poll() is None and time.monotonic() - started < timeout:
                sample_started = time.monotonic()
                processes = api.processes()
                if handle is None:
                    pid, handle = api.open_exact_child(processes, checker.pid, exe)
                    if handle:
                        trace["gui_pid"] = pid
                        trace["checker_lineage_depth"] = descendant_depth(processes, checker.pid, pid)
                        trace["module_snapshots"]["pid_observed"] = api.modules(pid)
                if handle:
                    counters = api.counters(handle)
                    if process_origin is None and "creation_unix_ms" in counters:
                        process_origin = time.monotonic() - (time.time() * 1000 - counters["creation_unix_ms"]) / 1000
                        trace["gui_creation_unix_ms"] = counters["creation_unix_ms"]
                    windows = api.windows(pid) if not counters.get("exited") else []
                    point = {"observer_ms": round((sample_started - started) * 1000, 2),
                             "process_ms": round((sample_started - process_origin) * 1000, 2) if process_origin is not None else None,
                             "qpc_ms": time.perf_counter() * 1000,
                             **counters, "threads": next((p["threads"] for p in processes if p["pid"] == pid), None),
                             "windows": windows}
                    event_values = {key: point.get(key) for key in event_fields}
                    if "gui_pid_observed" not in trace["events"]:
                        trace["events"]["gui_pid_observed"] = dict(event_values)
                    for role in ("splash-like", "main-like"):
                        for state in ("seen", "visible"):
                            key = f"{role}_{state}"
                            matching = [w for w in (windows or []) if w["role"] == role and (state == "seen" or w["visible"])]
                            ui_threads.update(w["thread_id"] for w in matching if w.get("thread_id"))
                            if key not in trace["events"] and matching:
                                trace["events"][key] = {**event_values, "qpc_ms": time.perf_counter() * 1000,
                                                        "window_thread_id": matching[0].get("thread_id")}
                                if state == "visible":
                                    trace["module_snapshots"][key] = api.modules(pid)
                    if not saw_valid_probe:
                        # The checker owns and deletes this synthetic JSON. It
                        # may disappear between polls; absence is not failure.
                        for probe in (cwd / "tmp").glob("*_startup_probe.json"):
                            try:
                                if not probe.stat().st_size:
                                    continue
                                if not saw_probe:
                                    saw_probe = True
                                    trace["events"]["nonempty_probe_file_observed"] = dict(event_values)
                                data = json.loads(api.read_probe(probe))
                                if (data.get("PROBE_CONTRACT") == "main_window_first_paint_v1"
                                        and data.get("QT_PAINT_EVENT_COMPLETED") is True
                                        and type(data.get("FIRST_PAINT_MS")) is int and data["FIRST_PAINT_MS"] > 0):
                                    saw_valid_probe = True
                                    # Observation is an upper bound on the Paint
                                    # timestamp, and does not replace the checker.
                                    trace["events"]["valid_probe_file_observed"] = {
                                        **event_values, "qpc_ms": time.perf_counter() * 1000,
                                    }
                                    break
                            except (OSError, ValueError, AttributeError):
                                pass
                    point["observer_work_ms"] = round((time.monotonic() - sample_started) * 1000, 2)
                    trace["samples"].append(point)
                time.sleep(max(0, POLL_SECONDS - (time.monotonic() - sample_started)))
        except Exception as exc:
            trace["observer_error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            if handle and api:
                try:
                    trace["last_counters"] = api.counters(handle)
                    trace["last_counters_observer_ms"] = round((time.monotonic() - started) * 1000, 2)
                except Exception as exc:
                    trace["last_counters_error"] = type(exc).__name__
                finally:
                    try:
                        api.close(handle)
                    except Exception as exc:
                        trace["handle_close_error"] = type(exc).__name__
        try:
            code = checker.wait(timeout=max(0.1, timeout - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            checker.kill()
            checker.wait()
            output.write(b"\nDiagnostic checker exceeded its outer timeout.\n")
            code = 124
    trace["checker_exit"] = code
    trace["observer_elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    trace["observed_target"] = pid is not None
    if not trace["samples"] and "observer_error" not in trace:
        trace["observer_error"] = "Verified GUI process not sampled (possibly shorter than discovery interval)"
    # Keep the entire process-scoped series local to the compact diagnostic
    # evidence; never export an ETL, global process list, or other windows.
    summary = {"observed_target": trace["observed_target"], "sample_count": len(trace["samples"]),
               "events": trace["events"], "observer_error": trace.get("observer_error")}
    summary["gui_pid"] = trace.get("gui_pid")
    summary["gui_creation_unix_ms"] = trace.get("gui_creation_unix_ms")
    summary["checker_lineage_depth"] = trace.get("checker_lineage_depth")
    summary["ui_threads"] = sorted(ui_threads)
    trace["ui_threads"] = summary["ui_threads"]
    summary["module_snapshots"] = trace["module_snapshots"]
    summary["last_counters"] = trace.get("last_counters")
    summary["available_samples"] = {key: sum(point.get(key) is not None for point in trace["samples"])
                                    for key in event_fields[2:]}
    samples = trace["samples"]
    summary["max_observed_gap_ms"] = max((round(b["observer_ms"] - a["observer_ms"], 2)
                                          for a, b in zip(samples, samples[1:])), default=None)
    summary["max_observer_work_ms"] = max((p["observer_work_ms"] for p in samples), default=None)
    # Keep the last counter reading per elapsed second visible directly in the
    # job log, even if retrieving the compact raw trace artifact is unavailable.
    seconds = {}
    for point in samples:
        elapsed = point["process_ms"] if point["process_ms"] is not None else point["observer_ms"]
        seconds[max(0, int(elapsed / 1000))] = {**{k: point.get(k) for k in event_fields},
                                               "visible_roles": sorted({w["role"] for w in (point["windows"] or []) if w["visible"]})}
    summary["second_marks"] = [{"second": key, **value} for key, value in sorted(seconds.items())]
    try:
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        summary["trace_file"] = trace_path.name
    except Exception as exc:
        summary["observer_error"] = f"Trace write failed: {type(exc).__name__}"
    return code, summary


def system_state() -> dict:
    """Small read-only state snapshot. No usernames, service paths or GUI warmup."""
    state = {}

    def query(command):
        try:
            result = subprocess.run(command, capture_output=True, timeout=4, check=False)
            return result.returncode, result.stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, type(exc).__name__

    code, output = query(["sc.exe", "query", "FontCache"])
    font = {"query_exit": code, "exists": True if code == 0 else False if code == 1060 else None}
    match = re.search(r"STATE\s*:\s*(\d+)", output, re.I)
    if match:
        font["state_code"] = int(match[1])
    code, output = query(["sc.exe", "qc", "FontCache"])
    font["config_query_exit"] = code
    match = re.search(r"START_TYPE\s*:\s*(\d+)", output, re.I)
    if match:
        font["start_type_code"] = int(match[1])
    state["font_cache"] = font
    code, output = query(["powercfg.exe", "/GETACTIVESCHEME"])
    match = re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", output, re.I)
    state["power_scheme"] = {"query_exit": code, "guid": match[0] if match else None}
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        get_session = bind(kernel, "ProcessIdToSessionId", wt.BOOL, wt.DWORD, ctypes.POINTER(wt.DWORD))
        session = wt.DWORD()
        raw = os.environ.get("SESSIONNAME", "").lower()
        state["session"] = {"id": int(session.value) if get_session(os.getpid(), ctypes.byref(session)) else None,
                            "kind": "console" if raw == "console" else "rdp" if raw.startswith("rdp-") else "other/unknown"}
    except Exception as exc:
        state["session"] = {"unavailable": type(exc).__name__}
    return state
