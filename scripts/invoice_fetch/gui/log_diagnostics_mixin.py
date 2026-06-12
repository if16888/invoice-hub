# -*- coding: utf-8 -*-
"""Log drawer and diagnostic metadata behavior for the main window."""

import json
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSizePolicy

from .. import APP_VERSION
from ..config import RUNTIME_DIR
from ..diagnostics import collect_app_info
from ..log_privacy import sanitize_log_message

LOG_DRAWER_EXPANDED_HEIGHT = 120


def _runtime_dir_compat():
    app_module = sys.modules.get(f"{__package__}.app")
    return getattr(app_module, "RUNTIME_DIR", RUNTIME_DIR)


class LogDiagnosticsMixin:
    def _toggle_log(self):
        current = getattr(self, "_log_panel_visible", self.log_container.isVisible())
        self._set_log_panel_visible(not current)

    def _set_log_panel_visible(self, visible: bool):
        if not hasattr(self, "log_container"):
            return

        if getattr(self, "_log_panel_visible", None) == visible:
            if visible and self.log_container.isVisible() and self.log_container.maximumHeight() == LOG_DRAWER_EXPANDED_HEIGHT:
                self.btn_toggle_log.setText("收起日志")
                return
            if (
                not visible
                and not self.log_container.isVisible()
                and self.log_container.maximumHeight() == 0
                and hasattr(self, "log_drawer")
                and self.log_drawer.maximumHeight() == 0
            ):
                self.btn_toggle_log.setText("展开日志")
                return

        self._log_panel_visible = visible
        self.btn_toggle_log.setText("收起日志" if visible else "展开日志")

        if visible:
            self.log_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            self.log_container.setMinimumHeight(LOG_DRAWER_EXPANDED_HEIGHT)
            self.log_container.setMaximumHeight(LOG_DRAWER_EXPANDED_HEIGHT)
            self.log_container.setVisible(True)
            if hasattr(self, "log_drawer"):
                self.log_drawer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.log_drawer.setMinimumHeight(LOG_DRAWER_EXPANDED_HEIGHT)
                self.log_drawer.setMaximumHeight(LOG_DRAWER_EXPANDED_HEIGHT)
                self.log_drawer.setVisible(True)
        else:
            self.log_container.setVisible(False)
            self.log_container.setMinimumHeight(0)
            self.log_container.setMaximumHeight(0)
            self.log_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            if hasattr(self, "log_drawer"):
                self.log_drawer.setVisible(False)
                self.log_drawer.setMinimumHeight(0)
                self.log_drawer.setMaximumHeight(0)
        self._apply_log_layout_state(visible)
        if not visible and self.isMaximized():
            QTimer.singleShot(0, self._normalize_maximized_geometry)

    def _apply_log_layout_state(self, log_visible: bool):
        if hasattr(self, "preview_panel"):
            self.preview_panel.setMinimumHeight(180)
            self.preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if hasattr(self, "left_upper_widget"):
            self.left_upper_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.log_container.updateGeometry()
        if hasattr(self, "log_drawer"):
            self.log_drawer.updateGeometry()
            if self.log_drawer.layout() is not None:
                self.log_drawer.layout().invalidate()
        if hasattr(self, "bottom_panel"):
            self.bottom_panel.updateGeometry()
            if self.bottom_panel.layout() is not None:
                self.bottom_panel.layout().invalidate()
        if hasattr(self, "main_splitter"):
            self.main_splitter.updateGeometry()
            if self.main_splitter.layout() is not None:
                self.main_splitter.layout().invalidate()
        if hasattr(self, "left_splitter"):
            self.left_splitter.updateGeometry()
            if self.left_splitter.layout() is not None:
                self.left_splitter.layout().invalidate()
        if hasattr(self, "main_layout"):
            self.main_layout.invalidate()
        central = self.centralWidget()
        if central is not None and central.layout() is not None:
            central.layout().invalidate()
            central.updateGeometry()
            central.update()
        self.updateGeometry()

    def _normalize_maximized_geometry(self):
        if not self.isMaximized():
            return
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        if available.isEmpty():
            return
        toggle_bottom_right = self.btn_toggle_log.mapToGlobal(self.btn_toggle_log.rect().bottomRight())
        if not available.contains(toggle_bottom_right):
            self.setGeometry(available)
            self.showMaximized()

    def _copy_log_to_clipboard(self):
        log_text = self.txt_log.toPlainText()
        if log_text:
            QApplication.clipboard().setText(log_text)
            self.statusBar().showMessage("日志已复制到剪贴板", 2000)

    def write_log(self, text: str):
        """Append log line to bottom operation log panel."""
        self.txt_log.append(sanitize_log_message(text))
        self.txt_log.ensureCursorVisible()

    def _open_runtime_dir(self):
        """Open the local runtime directory safely."""
        self._open_local_path(_runtime_dir_compat())
        self.write_log("已打开本地 runtime/ 运行时数据存放目录。")
        self.statusBar().showMessage("已打开 runtime 目录", 3000)

    def _open_logs_directory(self):
        """Open the local logs directory."""
        log_dir = _runtime_dir_compat() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._open_local_path(log_dir)
        self.write_log("已打开本地日志目录。")
        self.statusBar().showMessage("已打开日志目录", 3000)

    def _copy_diagnostic_info(self):
        """Copy redacted app diagnostics metadata to the clipboard."""
        payload = json.dumps(self._collect_diagnostic_payload(), ensure_ascii=False, indent=2)
        QApplication.clipboard().setText(payload)
        self.write_log("已复制脱敏诊断信息到剪贴板。")
        self.statusBar().showMessage("已复制诊断信息", 3000)

    def _database_user_version(self) -> int | None:
        try:
            row = self.db._conn.execute("PRAGMA user_version").fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    def _current_filter_state(self) -> dict:
        return {
            "status": self.current_filter_status or "all",
            "search": self.txt_search.text().strip() if hasattr(self, "txt_search") else "",
            "unlinked_only": bool(self.chk_unlinked.isChecked()) if hasattr(self, "chk_unlinked") else False,
            "needs_fix_only": bool(self.chk_needs_fix.isChecked()) if hasattr(self, "chk_needs_fix") else False,
            "show_deleted": bool(self.chk_show_deleted.isChecked()) if hasattr(self, "chk_show_deleted") else False,
        }

    def _collect_diagnostic_payload(self) -> dict:
        payload = collect_app_info()
        payload["database_user_version"] = self._database_user_version()
        payload["current_filter_state"] = self._current_filter_state()
        payload["last_scan_summary"] = dict(getattr(self, "_last_scan_summary", {}) or {})
        return payload

    def _about_text(self) -> str:
        info = collect_app_info()
        runtime_dir = _runtime_dir_compat()
        return "\n".join([
            "Invoice Hub",
            f"Version: {APP_VERSION}",
            f"Build: {info.get('build_commit') or 'unavailable'}",
            f"Mode: {info.get('build_mode') or info.get('mode') or 'unknown'}",
            f"Data directory: {runtime_dir}",
            f"Log directory: {runtime_dir / 'logs'}",
        ])

    def _show_about_dialog(self):
        """Show app version and local support paths."""
        QMessageBox.information(self, "关于 Invoice Hub", self._about_text())
