"""Motion preferences: respect the system's reduced-animation setting."""

from __future__ import annotations

import sys

_DEFAULT_DURATION_MS = 190


def animations_enabled() -> bool:
    """Return False when Windows/animation preferences ask for reduced motion."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION = 0x1042
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0
        )
        return bool(enabled.value) if ok else True
    except Exception:
        return True


def motion_duration(default_ms: int = _DEFAULT_DURATION_MS) -> int:
    """Return 0 under reduced motion so transitions apply instantly."""
    return default_ms if animations_enabled() else 0
