"""Non-blocking coordination for operations that read or mutate user data.

The GUI owns one gate for the lifetime of a window.  Workers acquire a named
operation before they start and release it from their completion path.  The
gate deliberately fails fast: a backup or restore must never race a scan,
import, migration, mobile upload, or another future data worker.
"""

from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import Iterator


class DataOperationGate:
    """A small, thread-safe, fail-fast single-owner operation gate."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._owner = ""

    @property
    def owner(self) -> str:
        with self._lock:
            return self._owner

    def busy_reason(self) -> str:
        return self.owner

    def try_acquire(self, operation: str) -> bool:
        name = str(operation or "").strip()
        if not name:
            raise ValueError("operation name is required")
        with self._lock:
            if self._owner:
                return False
            self._owner = name
            return True

    def release(self, operation: str) -> None:
        name = str(operation or "").strip()
        with self._lock:
            if self._owner != name:
                raise RuntimeError("data operation gate is not owned by this operation")
            self._owner = ""

    @contextmanager
    def operation(self, operation: str) -> Iterator[bool]:
        acquired = self.try_acquire(operation)
        try:
            yield acquired
        finally:
            if acquired:
                self.release(operation)


__all__ = ["DataOperationGate"]
