# -*- coding: utf-8 -*-
"""Mobile upload dialog extracted from the main GUI assembly module."""

from io import BytesIO
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..config import RUNTIME_DIR
from .mobile_upload_session import MobileUploadSessionController


class MobileUploadDialog(QDialog):

    def __init__(self, parent, db_path: Path):
        super().__init__(parent)
        self.setWindowTitle("扫码上传")
        self.resize(420, 560)
        self.setProperty("class", "WorkflowDialog")
        self.db_path = db_path
        shared_controller = getattr(parent, "mobile_upload_controller", None)
        self._owns_controller = shared_controller is None
        self.controller = shared_controller or MobileUploadSessionController(db_path, self)
        self.server = None
        self.session = None
        self._last_status_total = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("手机扫码上传")
        title.setProperty("class", "DialogTitle")
        layout.addWidget(title)

        self.lbl_status = QLabel("正在启动上传服务...")
        self.lbl_status.setProperty("class", "DialogInfo")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        network_row = QHBoxLayout()
        network_row.setSpacing(6)
        network_row.addWidget(QLabel("网络地址:"))
        self.combo_upload_host = QComboBox()
        self.combo_upload_host.currentIndexChanged.connect(self._network_host_changed)
        network_row.addWidget(self.combo_upload_host, 1)
        layout.addLayout(network_row)

        self.lbl_qr = QLabel()
        self.lbl_qr.setProperty("class", "QrPanel")
        self.lbl_qr.setAlignment(Qt.AlignCenter)
        self.lbl_qr.setMinimumSize(240, 240)
        layout.addWidget(self.lbl_qr)

        self.txt_url = QLineEdit()
        self.txt_url.setReadOnly(True)
        layout.addWidget(self.txt_url)

        stats_box = QGroupBox("上传统计")
        stats_box.setProperty("class", "CompactGroup")
        stats_layout = QFormLayout(stats_box)
        self.lbl_batch = QLabel("—")
        self.lbl_accepted = QLabel("0")
        self.lbl_duplicate = QLabel("0")
        self.lbl_failed = QLabel("0")
        self.lbl_imported = QLabel("0")
        stats_layout.addRow("批次:", self.lbl_batch)
        stats_layout.addRow("成功:", self.lbl_accepted)
        stats_layout.addRow("重复:", self.lbl_duplicate)
        stats_layout.addRow("失败:", self.lbl_failed)
        stats_layout.addRow("入库:", self.lbl_imported)
        layout.addWidget(stats_box)

        button_row = QHBoxLayout()
        self.btn_copy_url = QPushButton("复制链接")
        self.btn_copy_url.setProperty("class", "SecondaryBtn")
        self.btn_copy_url.clicked.connect(self._copy_url)
        button_row.addWidget(self.btn_copy_url)

        self.btn_stop = QPushButton("停止服务")
        self.btn_stop.setProperty("class", "DangerOutlineBtn")
        self.btn_stop.clicked.connect(self._stop_server)
        button_row.addStretch()
        button_row.addWidget(self.btn_stop)
        layout.addLayout(button_row)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_status)

        self.controller.started.connect(self._controller_started)
        self.controller.stats_changed.connect(self._apply_status)
        self.controller.failed.connect(self._controller_failed)
        self.controller.stopped.connect(self._controller_stopped)

        self._start_server()

    def _start_server(self):
        if self.controller.session is not None:
            self._controller_started(self.controller.session)
        else:
            self.controller.start()

    def _controller_started(self, session):
        self.session = session
        self.server = self.controller.server
        self.host_options = self.controller.host_options
        self._populate_upload_hosts()
        self.txt_url.setText(session.upload_url)
        self.lbl_batch.setText(session.batch_id)
        self.lbl_status.setText("请用手机扫描二维码。微信扫码后如文件不好选择，请点击右上角 … 在浏览器打开。\n手机打不开时，确认电脑和手机在同一 Wi-Fi，或切换网络地址。")
        self._render_qr(session.upload_url)
        self.btn_stop.setEnabled(True)

    def _controller_failed(self, message: str):
        self.lbl_status.setText(f"上传服务启动失败: {message}")
        self.btn_stop.setEnabled(False)

    def _controller_stopped(self):
        self.server = None
        self.session = None
        self.lbl_status.setText("上传服务已停止，二维码和链接已失效。")
        self.btn_stop.setEnabled(False)

    def _populate_upload_hosts(self):
        self.combo_upload_host.blockSignals(True)
        self.combo_upload_host.clear()
        if getattr(self, "host_options", None):
            for option in self.host_options:
                self.combo_upload_host.addItem(option.label, option.host)
        elif self.session:
            self.combo_upload_host.addItem(self.session.host, self.session.host)
        self.combo_upload_host.blockSignals(False)

    def _network_host_changed(self):
        if not self.server or self.combo_upload_host.currentIndex() < 0:
            return
        host = self.combo_upload_host.currentData()
        if not host:
            return
        try:
            self.session = self.controller.set_public_host(str(host))
            self.txt_url.setText(self.session.upload_url)
            self._render_qr(self.session.upload_url)
            self.lbl_status.setText("二维码地址已更新。手机打不开时请确认同一 Wi-Fi，或继续切换网络地址。")
        except Exception as exc:
            self.lbl_status.setText(f"切换网络地址失败: {exc}")

    def _render_qr(self, url: str):
        try:
            import qrcode

            image = qrcode.make(url)
            buf = BytesIO()
            image.save(buf, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue(), "PNG")
            self.lbl_qr.setPixmap(pixmap.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.lbl_qr.setText("未安装 qrcode 依赖。\n请复制下方链接到手机浏览器打开。")

    def _copy_url(self):
        QApplication.clipboard().setText(self.txt_url.text())
        self.lbl_status.setText("上传链接已复制。")

    def _refresh_status(self):
        if not self.server:
            return
        self._apply_status(self.server.status())

    def _apply_status(self, status):
        self.lbl_accepted.setText(str(status.get("accepted", 0)))
        self.lbl_duplicate.setText(str(status.get("duplicate", 0)))
        self.lbl_failed.setText(str(status.get("failed", 0)))
        self.lbl_imported.setText(str(status.get("imported", 0)))
        total = sum(int(status.get(k, 0) or 0) for k in ("accepted", "duplicate", "failed", "imported"))
        if total and total != self._last_status_total:
            self._last_status_total = total

    def _stop_server(self):
        if self.controller.server is not None or self.controller.is_starting:
            self.controller.stop()
        self.timer.stop()

    def closeEvent(self, event):
        self.timer.stop()
        if self._owns_controller:
            self.controller.shutdown()
        event.accept()
