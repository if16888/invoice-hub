"""Terminate untrusted PDF parsing without terminating the desktop process."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

MAX_PDF_BYTES = 50 * 1024 * 1024
PDF_MEMORY_BYTES = 768 * 1024 * 1024
PDF_TIMEOUT_SECONDS = 15.0
MAX_RESULT_BYTES = 4 * 1024 * 1024
_log = logging.getLogger(__name__)


def _publish_result(output_path, result):
    encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError("PDF result budget")
    staging = Path(output_path).with_suffix(".part")
    staging.write_bytes(encoded)
    os.replace(staging, output_path)


def _parse_child(output_path, path, mode):
    try:
        if os.name == "posix":
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (PDF_MEMORY_BYTES, PDF_MEMORY_BYTES))
            resource.setrlimit(resource.RLIMIT_CPU, (15, 16))
        if mode == "invoice":
            from .invoice_parser import InvoiceParser
            result = asdict(InvoiceParser().parse_pdf(path))
        else:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                if mode == "semantic_text" and (not pdf.pages or len(pdf.pages) > 32):
                    result = ""
                else:
                    pages = pdf.pages if mode == "semantic_text" else pdf.pages[:2]
                    parts = []
                    size = 0
                    for page in pages:
                        text = page.extract_text() or ""
                        size += len(text)
                        if size > 500_000:
                            raise ValueError("PDF text budget")
                        parts.append(text)
                    result = "\n".join(parts)
        _publish_result(output_path, [True, result])
    except Exception as exc:
        # Exception classes help diagnose platform failures without paths/text.
        _publish_result(output_path, [False, "PDF解析失败或超过资源限制，原件已保留，请人工检查", type(exc).__name__])


def _windows_private_bytes(pid):
    """Observe the Windows child memory budget; never constrain the GUI."""
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage", "PrivateUsage",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not api(handle, ctypes.byref(counters), counters.cb):
            error = ctypes.get_last_error()
            exit_code = wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            if kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value != 259:
                return 0
            raise ctypes.WinError(error)
        return counters.PrivateUsage
    finally:
        kernel.CloseHandle(handle)


def run_pdf_operation(path, *, mode="invoice", cancel_check=None, timeout=PDF_TIMEOUT_SECONDS, child_target=None):
    source = Path(path)
    if not source.is_file():
        return False, "文件不存在"
    if source.stat().st_size > MAX_PDF_BYTES:
        return False, "PDF超过50 MiB，原件已保留，请人工检查"
    context = multiprocessing.get_context("spawn")
    # No Pipe.recv(): a partial frame must never suspend timeout/cancellation.
    # Only a bounded, completely published JSON result is read by the parent.
    with tempfile.TemporaryDirectory(prefix="ih-pdf-") as temp:
        output = Path(temp) / "result.json"
        process = context.Process(target=child_target or _parse_child, args=(str(output), str(source), mode), daemon=True)
        stage = "start"
        try:
            deadline = time.monotonic() + timeout
            process.start()
            stage = "wait"
            while True:
                if cancel_check is not None and cancel_check():
                    return False, "解析已取消，原件已保留"
                if time.monotonic() >= deadline:
                    return False, "PDF解析超时，原件已保留，请人工检查"
                if output.is_file():
                    stage = "result"
                    if output.stat().st_size > MAX_RESULT_BYTES:
                        return False, "PDF解析结果超过预算，原件已保留"
                    with output.open("rb") as stream:
                        data = stream.read(MAX_RESULT_BYTES + 1)
                    if len(data) > MAX_RESULT_BYTES:
                        return False, "PDF解析结果超过预算，原件已保留"
                    result = json.loads(data)
                    if not isinstance(result, list) or len(result) not in (2, 3) or not isinstance(result[0], bool):
                        raise ValueError("invalid result")
                    if not result[0]:
                        _log.warning("PDF child failed category=%s", result[2] if len(result) == 3 else "unknown")
                    return result[0], result[1]
                if not process.is_alive():
                    # A process may publish its result between the check above
                    # and exit; inspect the atomic publication once more.
                    if output.is_file():
                        continue
                    _log.warning("PDF child exited without result exit_code=%s", process.exitcode)
                    return False, "PDF解析失败或超过资源限制，原件已保留"
                stage = "memory"
                try:
                    memory = _windows_private_bytes(process.pid)
                except OSError:
                    if output.is_file() or not process.is_alive():
                        continue
                    raise
                if memory > PDF_MEMORY_BYTES:
                    return False, "PDF解析超过内存预算，原件已保留"
                stage = "wait"
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        except Exception as exc:
            _log.warning("PDF boundary failed stage=%s category=%s winerror=%s", stage, type(exc).__name__, getattr(exc, "winerror", None))
            return False, "PDF解析进程未能完成，原件已保留，请重试"
        finally:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
                if not process.is_alive():
                    process.close()


def extract_pdf_text(path, *, semantic=False, cancel_check=None):
    ok, result = run_pdf_operation(path, mode="semantic_text" if semantic else "text", cancel_check=cancel_check)
    return result if ok else ""
