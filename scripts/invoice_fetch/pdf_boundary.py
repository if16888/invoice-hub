"""Terminate untrusted PDF parsing without terminating the desktop process."""

from __future__ import annotations

import multiprocessing
import os
import time
from dataclasses import asdict
from pathlib import Path

MAX_PDF_BYTES = 50 * 1024 * 1024
PDF_MEMORY_BYTES = 768 * 1024 * 1024
PDF_TIMEOUT_SECONDS = 15.0


def _parse_child(connection, path, mode):
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
        connection.send((True, result))
    except Exception:
        # No document text or private paths cross the error/log boundary.
        connection.send((False, "PDF解析失败或超过资源限制，原件已保留，请人工检查"))
    finally:
        connection.close()


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
        raise OSError("PDF child memory monitor unavailable")
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not api(handle, ctypes.byref(counters), counters.cb):
            raise OSError("PDF child memory monitor unavailable")
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
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=child_target or _parse_child, args=(writer, str(source), mode), daemon=True)
    try:
        process.start()
        writer.close()
        deadline = time.monotonic() + timeout
        while True:
            if cancel_check is not None and cancel_check():
                return False, "解析已取消，原件已保留"
            if time.monotonic() >= deadline:
                return False, "PDF解析超时，原件已保留，请人工检查"
            if reader.poll(0.05):
                try:
                    return reader.recv()
                except EOFError:
                    return False, "PDF解析失败或超过资源限制，原件已保留"
            if not process.is_alive():
                return False, "PDF解析失败或超过资源限制，原件已保留"
            if _windows_private_bytes(process.pid) > PDF_MEMORY_BYTES:
                return False, "PDF解析超过内存预算，原件已保留"
    except Exception:
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
        reader.close()
        writer.close()


def extract_pdf_text(path, *, semantic=False, cancel_check=None):
    ok, result = run_pdf_operation(path, mode="semantic_text" if semantic else "text", cancel_check=cancel_check)
    return result if ok else ""
