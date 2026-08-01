# -*- coding: utf-8 -*-
"""Background GUI workers extracted from the main GUI assembly module."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal


class LocalImportWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, import_dir: Path, db_path: Path):
        super().__init__()
        self.import_dir = import_dir
        self.db_path = db_path

    def run(self):
        try:
            from ..services import import_local_directory
            stats = import_local_directory(self.import_dir, self.db_path)
            self.finished.emit(stats)
        except Exception as e:
            self.error.emit(str(e))
        except BaseException as e:
            self.error.emit(str(e))


class EmailScanWorker(QThread):
    log = Signal(str)
    stage = Signal(dict)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, db_path: Path, selected_keys: list[str] | None = None):
        super().__init__()
        self.db_path = db_path
        self.selected_keys = selected_keys
        self.summary_logs = []
        from ..scan_lifecycle import ScanControl
        self.control = ScanControl()

    def request_cancel(self):
        self.control.cancel()

    def run(self):
        try:
            from ..services import scan_email_and_download

            def gui_log(msg: str):
                self.summary_logs.append(str(msg or ""))
                self.log.emit(msg)

            res = scan_email_and_download(
                db_path=self.db_path,
                log_callback=gui_log,
                selected_keys=self.selected_keys,
                scan_control=self.control,
                progress_callback=self.stage.emit,
            )
            self.finished.emit(res)
        except Exception as e:
            from ..scan_lifecycle import ScanCancelled
            if isinstance(e, ScanCancelled):
                self.finished.emit({"cancelled": True, "reason": str(e)})
            else:
                self.error.emit(str(e))
        except BaseException as e:
            self.error.emit(str(e))
