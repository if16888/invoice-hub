"""Pytest fixtures and configuration for HCI acceptance testing."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

# Ensure Qt runs offscreen in headless test environments
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from .fixtures import populate_synthetic_db
from .harness import cleanup_window, find_running_qthreads


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Ensure a singleton QApplication instance exists for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def mock_msgbox() -> Generator[None, None, None]:
    """Auto-mock QMessageBox dialogs to prevent modal blocking during headless tests."""
    with (
        patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes),
        patch("PySide6.QtWidgets.QMessageBox.warning", return_value=QMessageBox.Ok),
        patch("PySide6.QtWidgets.QMessageBox.information", return_value=QMessageBox.Ok),
        patch("PySide6.QtWidgets.QMessageBox.critical", return_value=QMessageBox.Ok),
    ):
        yield


@pytest.fixture
def synthetic_env() -> Generator[tuple[Path, InvoiceDB, Path], None, None]:
    """Provide an isolated temporary directory, synthetic DB, and runtime root."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "invoices.db"
        runtime_dir = root / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        with InvoiceDB(db_path) as db:
            populate_synthetic_db(db, runtime_dir)

        # Yield path and fresh handle
        yield db_path, None, runtime_dir


@pytest.fixture
def review_window(qapp: QApplication, synthetic_env) -> Generator[InvoiceReviewApp, None, None]:
    """Create, display, and properly clean up an InvoiceReviewApp instance."""
    db_path, _, runtime_dir = synthetic_env
    window = InvoiceReviewApp(db_path)
    window.resize(1600, 900)
    window.show()

    for _ in range(5):
        qapp.processEvents()

    try:
        yield window
    finally:
        cleanup_window(window, qapp)
        running = find_running_qthreads()
        if running:
            pytest.fail(f"Residual running QThreads after test: {running}")
