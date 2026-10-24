"""Test-package bootstrap: non-blocking Qt modal dialogs.

``unittest discover`` executes the whole suite in one Python process. A test
that leaves a window (or a pending ``QTimer``) behind can make a later test
enter an error path that shows a modal ``QMessageBox``. Under the offscreen Qt
platform nobody can click it, so ``QMessageBox.critical()`` / ``QDialog.exec()``
blocks forever and the run appears to deadlock at 0% CPU.

Importing the ``tests`` package (which happens before any test module runs)
replaces those blocking entry points with fast stubs that

* return immediately without opening a native dialog or running a modal event
  loop, and
* record the call, so tests can still assert that a dialog was shown.

Recorder API (import from ``tests``)::

    modal_dialog_calls()           -> tuple[ModalDialogCall, ...]
    find_modal_dialog_calls(name)  -> tuple[ModalDialogCall, ...]
    take_modal_dialog_calls()      -> tuple[ModalDialogCall, ...] (also clears)
    reset_modal_dialog_calls()     -> clear the recorder
    is_modal_guard_installed()     -> bool (False when PySide6 is unavailable)

Qt object arguments are recorded as weak references so the recorder can never
keep a leaked window (and its pending timers) alive.

Set ``INVOICE_HUB_DISABLE_MODAL_GUARD=1`` to keep the real dialogs while
debugging locally; the full-suite command can hang again in that mode.

The guard lives entirely in the test package: production code is unchanged.
"""

from __future__ import annotations

import os
import weakref
from dataclasses import dataclass, field
from typing import Any

_MODAL_GUARD_ENV = "INVOICE_HUB_DISABLE_MODAL_GUARD"
_MAX_RECORDED_CALLS = 500


@dataclass(frozen=True)
class ModalDialogCall:
    """One intercepted Qt dialog entry-point call."""

    name: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        """The user-facing title of a message box call, when present."""
        return str(self.args[1]) if len(self.args) > 1 else ""

    @property
    def text(self) -> str:
        """The user-facing message text of a message box call, when present."""
        return str(self.args[2]) if len(self.args) > 2 else ""


_modal_calls: list[ModalDialogCall] = []
_guard_installed = False
_ORIGINAL_ENTRY_POINTS: dict[str, Any] = {}


def _snapshot_argument(value: Any) -> Any:
    """Record primitives verbatim and Qt objects as weak references."""
    if isinstance(value, (str, bytes, int, float, bool, type(None))):
        return value
    try:
        from PySide6.QtCore import QObject  # type: ignore
    except Exception:
        return value
    if isinstance(value, QObject):
        try:
            return weakref.ref(value)
        except TypeError:
            return value
    return value


def _record(name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    if len(_modal_calls) >= _MAX_RECORDED_CALLS:
        del _modal_calls[: _MAX_RECORDED_CALLS // 2]
    _modal_calls.append(
        ModalDialogCall(
            name=name,
            args=tuple(_snapshot_argument(arg) for arg in args),
            kwargs={key: _snapshot_argument(val) for key, val in kwargs.items()},
        )
    )


def _install_modal_guard() -> None:
    """Replace blocking QMessageBox/QDialog entry points with recording stubs.

    Import-safe when PySide6 is not installed (data-only test runs then keep
    using the real unittest behaviour and never touch Qt).
    """
    global _guard_installed
    if _guard_installed or os.environ.get(_MODAL_GUARD_ENV) == "1":
        return
    try:
        from PySide6.QtWidgets import QDialog, QMessageBox
    except ImportError:
        return

    def _static_stub(name: str, result: Any):
        def stub(*args: Any, **kwargs: Any) -> Any:
            _record(name, args, kwargs)
            return result

        stub.__name__ = f"modal_guard_{name}"
        stub.modal_guard_stub = True  # type: ignore[attr-defined]
        return stub

    def _instance_stub(name: str, result: Any):
        def stub(_self: Any, *args: Any, **kwargs: Any) -> Any:
            _record(name, args, kwargs)
            return result

        stub.__name__ = f"modal_guard_{name}"
        stub.modal_guard_stub = True  # type: ignore[attr-defined]
        return stub

    originals = {
        "QMessageBox.critical": QMessageBox.critical,
        "QMessageBox.warning": QMessageBox.warning,
        "QMessageBox.information": QMessageBox.information,
        "QMessageBox.question": QMessageBox.question,
        "QMessageBox.exec": QMessageBox.exec,
        "QDialog.exec": QDialog.exec,
    }
    _ORIGINAL_ENTRY_POINTS.update(originals)

    QMessageBox.critical = _static_stub("critical", QMessageBox.Ok)
    QMessageBox.warning = _static_stub("warning", QMessageBox.Ok)
    QMessageBox.information = _static_stub("information", QMessageBox.Ok)
    # Cancelling harmless confirmations is the safe test default; tests that
    # exercise a confirmed path patch this stub explicitly.
    QMessageBox.question = _static_stub("question", QMessageBox.No)
    QMessageBox.exec = _instance_stub("QMessageBox.exec", QMessageBox.Ok)
    QDialog.exec = _instance_stub("QDialog.exec", QDialog.Accepted)

    _guard_installed = True


def is_modal_guard_installed() -> bool:
    """Return True when the non-blocking dialog guard replaced the Qt entry points."""
    return _guard_installed


def modal_dialog_calls() -> tuple[ModalDialogCall, ...]:
    """Return every intercepted dialog call recorded so far."""
    return tuple(_modal_calls)


def find_modal_dialog_calls(name: str = "") -> tuple[ModalDialogCall, ...]:
    """Return recorded calls, optionally filtered by entry-point name."""
    if not name:
        return tuple(_modal_calls)
    return tuple(call for call in _modal_calls if call.name == name)


def take_modal_dialog_calls() -> tuple[ModalDialogCall, ...]:
    """Return and clear the recorded calls (useful in tearDown/setUp)."""
    calls = tuple(_modal_calls)
    _modal_calls.clear()
    return calls


def reset_modal_dialog_calls() -> None:
    """Clear the recorded calls."""
    _modal_calls.clear()


def original_modal_entry_points() -> dict[str, Any]:
    """Return the replaced Qt entry points, for debugging only."""
    return dict(_ORIGINAL_ENTRY_POINTS)


_install_modal_guard()
