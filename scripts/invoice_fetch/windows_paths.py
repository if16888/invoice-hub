"""Resolve Windows system programs without trusting PATH or environment variables."""

import ctypes
import os
from pathlib import Path


def windows_system_executable(relative_path: str) -> str:
    """Return an existing program inside the OS-reported Windows directory."""
    if os.name != "nt":
        raise OSError("Windows system programs are unavailable on this platform")
    relative = Path(relative_path)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("Expected a relative Windows system program path")
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer))
    if not size or size >= len(buffer):
        raise OSError("Cannot resolve the Windows directory")
    executable = Path(buffer.value) / relative
    if not executable.is_file():
        raise OSError("Windows system program is unavailable")
    return str(executable)
