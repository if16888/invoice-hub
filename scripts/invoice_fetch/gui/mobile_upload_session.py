# -*- coding: utf-8 -*-
"""Shared controller and embedded surface for mobile upload sessions."""

from io import BytesIO
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, QThread, QTimer, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QComboBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..config import RUNTIME_DIR
from .ui_components import (
    MiddleElidedTextLabel,
    WrappedTextLabel,
    make_badge,
    make_button,
)


class _MobileUploadStartWorker(QObject):
    def __init__(self, runtime_dir: Path, db_path: Path, host: str | None):
        super().__init__()
        self.runtime_dir = runtime_dir
        self.db_path = db_path
        self.host = host
        self.result = None
        self.error = ""

    @Slot()
    def run(self):
        try:
            from ..mobile_upload import MobileUploadServer, enumerate_upload_hosts, log_upload_host_candidates
            options = enumerate_upload_hosts()
            log_upload_host_candidates(options)
            selected_option = next((option for option in options if option.host == self.host), None)
            if selected_option is None and self.host is None and options:
                selected_option = options[0]
            selected = self.host or (selected_option.host if selected_option else None)
            server = MobileUploadServer(
                runtime_dir=self.runtime_dir, db_path=self.db_path, host=selected,
                port=0, import_on_upload=True,
                interface_name=selected_option.interface_name if selected_option else "",
                network_priority=selected_option.priority if selected_option else 50,
                network_virtual=selected_option.is_virtual if selected_option else False,
            )
            session = server.start()
            server.run_local_self_check()
            self.result = (server, session, options)
        except Exception as exc:
            self.error = str(exc)
        finally:
            QThread.currentThread().quit()


class MobileUploadSessionController(QObject):
    starting = Signal()
    started = Signal(object)
    stats_changed = Signal(dict)
    upload_received = Signal(dict)
    firewall_status_changed = Signal(object)
    firewall_action_finished = Signal(object)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, db_path: Path, parent=None, runtime_dir: Path = RUNTIME_DIR, operation_gate=None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.runtime_dir = Path(runtime_dir)
        self.operation_gate = operation_gate
        self._gate_acquired = False
        self._operation_name = "手机上传"
        self.server = None
        self.session = None
        self.host_options = []
        self._last_total = 0
        self._starting = False
        self._stop_requested = False
        self._start_thread = None
        self._start_worker = None
        self.firewall_status = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh_status)

    def enumerate_hosts(self):
        from ..mobile_upload import enumerate_upload_hosts
        self.host_options = enumerate_upload_hosts()
        return self.host_options

    @property
    def is_starting(self) -> bool:
        return self._starting

    def start(self, host: str | None = None):
        if self.server is not None or self._starting:
            return self.session
        if self.operation_gate is not None:
            if not self.operation_gate.try_acquire(self._operation_name):
                busy = self.operation_gate.busy_reason() or "其他数据操作"
                self.failed.emit(f"{busy}正在运行，请完成后再试。")
                return None
            self._gate_acquired = True
        self._starting = True
        self._stop_requested = False
        self.starting.emit()
        thread = QThread(self)
        worker = _MobileUploadStartWorker(self.runtime_dir, self.db_path, host)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.finished.connect(self._finish_start)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._start_thread = thread
        self._start_worker = worker
        try:
            thread.start()
        except Exception:
            self._starting = False
            self._release_operation_gate()
            raise
        return None

    @Slot()
    def _finish_start(self):
        worker = self._start_worker
        if worker is None:
            return
        if worker.error:
            self._start_failed(worker.error)
        elif worker.result is not None:
            self._start_succeeded(*worker.result)
        self._clear_start_worker()

    @Slot(object, object, list)
    def _start_succeeded(self, server, session, options):
        self._starting = False
        if self._stop_requested:
            server.stop()
            self._stop_requested = False
            self._release_operation_gate()
            self.stopped.emit()
            return
        self.server = server
        self.session = session
        self.host_options = list(options)
        self._last_total = 0
        self.refresh_firewall_status()
        self.timer.start()
        self.started.emit(session)

    @Slot(str)
    def _start_failed(self, message: str):
        self._starting = False
        self.server = None
        self.session = None
        self._release_operation_gate()
        self.failed.emit(message)
        # If shutdown() timed out and set _stop_requested while the thread was
        # still running, the closeEvent is stuck with _close_pending=True waiting
        # for `stopped`.  Emit it now so the window can finish closing.
        if self._stop_requested:
            self._stop_requested = False
            self.stopped.emit()

    @Slot()
    def _clear_start_worker(self):
        self._start_thread = None
        self._start_worker = None

    def _release_operation_gate(self):
        if not self._gate_acquired or self.operation_gate is None:
            return
        self._gate_acquired = False
        try:
            self.operation_gate.release(self._operation_name)
        except RuntimeError:
            # Window shutdown may have already released the gate after waiting
            # for the start worker; cleanup must remain idempotent.
            pass

    def set_public_host(self, host: str):
        if self.server is None:
            return None
        try:
            option = next((item for item in self.host_options if item.host == host), None)
            if option is not None:
                self.server.set_network_metadata(
                    interface_name=option.interface_name,
                    priority=option.priority,
                    is_virtual=option.is_virtual,
                )
            self.session = self.server.set_public_host(host)
            self.server.run_local_self_check()
            self.started.emit(self.session)
            return self.session
        except Exception as exc:
            self.failed.emit(str(exc))
            return None

    def refresh_firewall_status(self):
        from ..windows_firewall import (
            get_current_invoicehub_executable,
            get_mobile_upload_firewall_status,
        )

        self.firewall_status = get_mobile_upload_firewall_status(
            get_current_invoicehub_executable()
        )
        self.firewall_status_changed.emit(self.firewall_status)
        return self.firewall_status

    def request_firewall_access(self):
        from ..windows_firewall import (
            get_current_invoicehub_executable,
            request_mobile_upload_firewall_access,
        )

        result = request_mobile_upload_firewall_access(
            get_current_invoicehub_executable()
        )
        self.firewall_status = result.status
        self.firewall_status_changed.emit(self.firewall_status)
        self.firewall_action_finished.emit(result)
        return result

    def refresh_status(self):
        if self.server is None:
            return
        status = dict(self.server.status())
        if self.firewall_status is not None:
            status["firewall"] = self.firewall_status.as_dict()
        self.stats_changed.emit(status)
        total = sum(int(status.get(k, 0) or 0) for k in ("accepted", "duplicate", "failed", "imported"))
        if total and total != self._last_total:
            self._last_total = total
            self.upload_received.emit(status)

    def stop(self):
        if self._starting:
            self._stop_requested = True
        if self.server is not None:
            self.server.stop()
        self.server = None
        self.session = None
        self.timer.stop()
        self._release_operation_gate()
        self.stopped.emit()

    def shutdown(self, timeout_ms: int = 5000):
        """Release the owned service before the application closes its DB."""
        self._stop_requested = True
        self.timer.stop()
        thread = self._start_thread
        if thread is not None and thread.isRunning():
            if not thread.wait(timeout_ms):
                return False
            QCoreApplication.processEvents()
        self.stop()
        thread = self._start_thread
        return not (thread is not None and thread.isRunning()) and self.server is None and not self.timer.isActive()

    @staticmethod
    def qr_png(url: str) -> bytes:
        import qrcode
        image = qrcode.make(url)
        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()


class MobileUploadSessionPanel(QFrame):
    def __init__(self, controller: MobileUploadSessionController, parent=None):
        super().__init__(parent)
        self.setObjectName("MobileUploadSessionPanel")
        self.controller = controller
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.stack = QStackedWidget(self)
        root.addWidget(self.stack, 0, Qt.AlignTop)
        self.idle_page = self._build_idle()
        self.starting_page = self._build_starting()
        self.active_page = self._build_active()
        self.error_page = self._build_error()
        self.stack.addWidget(self.idle_page)
        self.stack.addWidget(self.starting_page)
        self.stack.addWidget(self.active_page)
        self.stack.addWidget(self.error_page)
        controller.starting.connect(self.show_starting)
        controller.started.connect(self._show_active)
        controller.stats_changed.connect(self._set_stats)
        controller.firewall_status_changed.connect(self._set_firewall_status)
        controller.firewall_action_finished.connect(self._firewall_action_finished)
        controller.failed.connect(self._show_error)
        controller.stopped.connect(self.show_idle)
        controller.refresh_firewall_status()

    def _build_idle(self):
        page = QWidget(self)
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        title = QLabel("手机扫码上传"); title.setProperty("class", "SectionTitle")
        desc = QLabel("从手机上传发票原件、行程单或证明材料。\n手机和电脑需要连接同一局域网。")
        desc.setWordWrap(True); desc.setProperty("class", "SectionHint")
        self.lbl_idle_network = QLabel("网络：局域网 · 自动检测\n支持：PDF / OFD / XML / 图片\n上传后：自动进入审核队列")
        self.lbl_idle_network.setWordWrap(True)
        self.lbl_idle_firewall = QLabel("Windows 防火墙：检查中")
        self.lbl_idle_firewall.setWordWrap(True)
        self.lbl_idle_firewall.setProperty("class", "SectionHint")
        self.btn_idle_firewall_authorize = make_button("允许手机访问", variant="secondary")
        self.btn_idle_firewall_authorize.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.btn_idle_firewall_authorize.clicked.connect(self._request_firewall_access)
        self.btn_start = make_button("启动手机上传", variant="primary")
        self.btn_start.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.btn_start.clicked.connect(lambda _checked=False: self.controller.start())
        layout.addWidget(title); layout.addWidget(desc); layout.addWidget(self.lbl_idle_network)
        layout.addWidget(self.lbl_idle_firewall)
        layout.addWidget(self.btn_idle_firewall_authorize, 0, Qt.AlignLeft)
        layout.addWidget(self.btn_start, 0, Qt.AlignLeft); layout.addStretch(1)
        return page

    def _build_starting(self):
        page = QWidget(self)
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        title = QLabel("正在启动手机上传…"); title.setProperty("class", "SectionTitle")
        description = QLabel("正在检测局域网并创建临时上传地址。")
        description.setProperty("class", "SectionHint")
        layout.addWidget(title); layout.addWidget(description); layout.addStretch(1)
        return page

    def _build_active(self):
        page = QWidget(self)
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(10)
        header = QHBoxLayout(); title = QLabel("手机扫码上传"); title.setProperty("class", "SectionTitle")
        self.status_badge = make_badge("运行中", "success")
        header.addWidget(title); header.addWidget(self.status_badge); header.addStretch(1)
        body = QBoxLayout(QBoxLayout.LeftToRight); body.setSpacing(16)
        self._active_body_layout = body
        self.lbl_qr = QLabel(); self.lbl_qr.setObjectName("MobileUploadQr")
        self.lbl_qr.setAlignment(Qt.AlignCenter); self.lbl_qr.setFixedSize(240, 240)
        details = QWidget(); details.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        form = QFormLayout(details); form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self._active_details = details
        self._active_details_form = form
        self.txt_url = MiddleElidedTextLabel("—", details)
        self.txt_url.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo_upload_host = QComboBox(); self.combo_upload_host.currentIndexChanged.connect(self._host_changed)
        self.combo_upload_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_service_address = self._responsive_label("—")
        self.lbl_network_interface = self._responsive_label("—")
        self.lbl_service_state = self._responsive_label("运行中")
        self.lbl_local_self_check = self._responsive_label("检查中")
        self.lbl_lan_client_access = self._responsive_label("尚未确认")
        self.lbl_last_access = self._responsive_label("—")
        self.lbl_lan_access_hint = WrappedTextLabel(
            "手机打不开？请确认手机和电脑连接到可互通的同一 Wi-Fi，并检查 Windows 网络/防火墙设置。"
        )
        self.lbl_lan_access_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_firewall_state = self._responsive_label("检查中")
        self.lbl_firewall_hint = WrappedTextLabel("")
        self.lbl_firewall_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.btn_firewall_authorize = make_button("允许手机访问", variant="secondary")
        self.btn_firewall_authorize.clicked.connect(self._request_firewall_access)
        firewall_details = QWidget(details)
        firewall_layout = QVBoxLayout(firewall_details)
        firewall_layout.setContentsMargins(0, 0, 0, 0)
        firewall_layout.setSpacing(4)
        firewall_layout.addWidget(self.lbl_firewall_state)
        firewall_layout.addWidget(self.lbl_firewall_hint)
        firewall_layout.addWidget(self.btn_firewall_authorize, 0, Qt.AlignLeft)
        self.lbl_stats = self._responsive_label("成功 0 · 重复 0 · 失败 0 · 入库 0")
        operation = self._responsive_label("手机扫描二维码，在浏览器中选择文件上传。")
        form.addRow("操作", operation)
        form.addRow("上传 URL", self.txt_url); form.addRow("切换网络", self.combo_upload_host)
        form.addRow("当前网络", self.lbl_network_interface)
        form.addRow("服务状态", self.lbl_service_state)
        form.addRow("服务地址", self.lbl_service_address)
        form.addRow("本机访问", self.lbl_local_self_check)
        form.addRow("局域网访问", self.lbl_lan_client_access)
        form.addRow("最近访问", self.lbl_last_access)
        form.addRow("访问提示", self.lbl_lan_access_hint)
        form.addRow("Windows 防火墙", firewall_details)
        form.addRow("本次上传", self.lbl_stats)
        details_scroll = QScrollArea(page)
        details_scroll.setObjectName("MobileUploadDetailsScroll")
        details_scroll.setFrameShape(QFrame.NoFrame)
        details_scroll.setWidgetResizable(True)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        details_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        details_scroll.setWidget(details)
        self._active_details_scroll = details_scroll
        body.addWidget(self.lbl_qr, 0, Qt.AlignTop)
        body.addWidget(details_scroll, 1)
        footer = QBoxLayout(QBoxLayout.LeftToRight)
        self._active_footer_layout = footer
        self.btn_copy_url = make_button("复制链接", variant="secondary"); self.btn_copy_url.clicked.connect(self._copy_url)
        self.btn_change_network = make_button("更换网络", variant="ghost"); self.btn_change_network.clicked.connect(self.combo_upload_host.showPopup)
        self.btn_stop = make_button("停止服务", variant="secondary"); self.btn_stop.setProperty("danger", True); self.btn_stop.clicked.connect(self.controller.stop)
        footer.addWidget(self.btn_copy_url); footer.addWidget(self.btn_change_network); footer.addStretch(1); footer.addWidget(self.btn_stop)
        layout.addLayout(header); layout.addLayout(body); layout.addLayout(footer)
        return page

    def _build_error(self):
        page = QWidget(self)
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        title = QLabel("无法启动手机上传"); title.setProperty("class", "SectionTitle")
        self.lbl_error = QLabel("未找到可用网络，或端口启动失败。")
        self.lbl_error.setWordWrap(True); self.lbl_error.setProperty("class", "SectionHint")
        actions = QHBoxLayout()
        self.btn_retry = make_button("重试", variant="primary")
        self.btn_retry.clicked.connect(lambda _checked=False: self.controller.start())
        self.btn_network_settings = make_button("网络设置", variant="secondary")
        self.btn_network_settings.clicked.connect(self.show_idle)
        actions.addWidget(self.btn_retry); actions.addWidget(self.btn_network_settings); actions.addStretch(1)
        layout.addWidget(title); layout.addWidget(self.lbl_error); layout.addLayout(actions); layout.addStretch(1)
        return page

    def show_idle(self):
        self.btn_start.setEnabled(True)
        self.stack.setCurrentWidget(self.idle_page)

    def show_starting(self):
        self.btn_start.setEnabled(False)
        self.stack.setCurrentWidget(self.starting_page)

    def _show_active(self, session):
        self.combo_upload_host.blockSignals(True); self.combo_upload_host.clear()
        for option in self.controller.host_options:
            self.combo_upload_host.addItem(option.label, option.host)
        selected_index = self.combo_upload_host.findData(session.host)
        if selected_index >= 0:
            self.combo_upload_host.setCurrentIndex(selected_index)
        self.combo_upload_host.blockSignals(False)
        self.txt_url.set_value(session.upload_url)
        self.txt_url.setToolTip(session.upload_url)
        self.lbl_service_address.setText(f"bind 0.0.0.0:{session.port}\npublic {session.host}:{session.port}")
        self.lbl_service_state.setText("运行中")
        try:
            pixmap = QPixmap(); pixmap.loadFromData(self.controller.qr_png(session.upload_url), "PNG")
            self.lbl_qr.setPixmap(pixmap.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.lbl_qr.setText("二维码不可用\n请复制上传链接")
        self.stack.setCurrentWidget(self.active_page)
        self._apply_responsive_layout()
        if self.controller.server is not None:
            self._set_stats(self.controller.server.status())

    def _set_stats(self, stats):
        self.lbl_stats.setText("成功 {accepted} · 重复 {duplicate} · 失败 {failed} · 入库 {imported}".format(
            accepted=stats.get("accepted", 0), duplicate=stats.get("duplicate", 0),
            failed=stats.get("failed", 0), imported=stats.get("imported", 0)))
        interface = str(stats.get("interface_name") or "").strip()
        host = str(stats.get("public_host") or "").strip()
        self.lbl_network_interface.setText(
            f"{interface or '网络接口'} · {host}" if host else (interface or "自动检测")
        )
        self.lbl_local_self_check.setText({
            "pass": "正常",
            "fail": "失败",
            "pending": "检查中",
        }.get(str(stats.get("local_self_check") or "pending"), "检查中"))
        confirmed = bool(stats.get("lan_client_access_confirmed"))
        self.lbl_lan_client_access.setText("已确认" if confirmed else "尚未确认")
        self.lbl_lan_access_hint.setVisible(not confirmed)
        last_access = str(stats.get("last_lan_client_access_at") or "").strip()
        self.lbl_last_access.setText(last_access[11:19] if len(last_access) >= 19 else (last_access or "—"))
        self.lbl_service_state.setText("运行中" if stats.get("active", True) else "已停止")
        firewall = stats.get("firewall")
        if isinstance(firewall, dict):
            self._set_firewall_status(firewall)

    def _show_error(self, message):
        self.btn_start.setEnabled(True)
        self.lbl_error.setText(message or "未找到可用网络，或端口启动失败。")
        self.stack.setCurrentWidget(self.error_page)

    def _copy_url(self):
        QApplication.clipboard().setText(self.txt_url.text())

    def _host_changed(self):
        host = self.combo_upload_host.currentData()
        if host: self.controller.set_public_host(str(host))

    @staticmethod
    def _responsive_label(text: str) -> QLabel:
        label = WrappedTextLabel(text)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        return label

    def _set_firewall_status(self, status):
        data = status.as_dict() if hasattr(status, "as_dict") else dict(status or {})
        state = str(data.get("state") or "unknown")
        development_mode = bool(data.get("development_mode"))
        if state == "rule_present":
            summary = "已允许 · 仅私人网络"
            hint = "仅正式 InvoiceHub.exe 的 Private 网络 TCP 入站规则生效。"
            button_visible = False
        elif state in {"rule_missing", "rule_disabled"}:
            summary = "未授权"
            hint = "允许后仅对当前正式程序开放 Private 网络 TCP 入站访问。"
            button_visible = True
        elif state == "supported" and development_mode:
            summary = "开发运行模式"
            hint = "当前为开发运行模式，请手动允许测试端口或使用正式构建验证。"
            button_visible = False
        elif state == "non_windows":
            summary = "当前系统不支持"
            hint = "请在 Windows 正式构建中验证局域网访问。"
            button_visible = False
        else:
            summary = "无法确认"
            hint = "无法读取 Windows 防火墙状态，仍可使用本地导入或邮箱扫描。"
            button_visible = True
        self._firewall_status = status
        self.lbl_idle_firewall.setText(f"Windows 防火墙：{summary}")
        self.btn_idle_firewall_authorize.setVisible(button_visible)
        self.btn_idle_firewall_authorize.setEnabled(button_visible)
        if hasattr(self, "lbl_firewall_state"):
            self.lbl_firewall_state.setText(summary)
            self.lbl_firewall_hint.setText(hint)
            self.btn_firewall_authorize.setVisible(button_visible)
            self.btn_firewall_authorize.setEnabled(button_visible)

    def _firewall_action_finished(self, result):
        self._set_firewall_status(result.status)
        if not result.success and hasattr(self, "lbl_firewall_hint"):
            self.lbl_firewall_hint.setText(
                "未授权。你仍可使用本地导入或邮箱扫描。"
                if result.message
                else "未授权。"
            )

    def _request_firewall_access(self):
        status = getattr(self, "_firewall_status", None)
        data = status.as_dict() if hasattr(status, "as_dict") else dict(status or {})
        if data.get("development_mode") or data.get("state") in {"non_windows", "rule_present"}:
            return
        answer = QMessageBox.question(
            self,
            "允许手机访问",
            "将请求 Windows 管理员授权，创建仅对正式 InvoiceHub.exe、Private 网络、TCP 入站生效的规则。\n"
            "不会开放 Public 网络。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            self.lbl_firewall_hint.setText("未授权。你仍可使用本地导入或邮箱扫描。")
            self.lbl_idle_firewall.setText("Windows 防火墙：未授权")
            return
        self.btn_idle_firewall_authorize.setEnabled(False)
        self.btn_firewall_authorize.setEnabled(False)
        self.lbl_firewall_hint.setText("正在请求 Windows 授权…")
        self.controller.request_firewall_access()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _apply_responsive_layout(self):
        if not hasattr(self, "_active_body_layout"):
            return
        available_width = self.active_page.width() or self.width()
        narrow = available_width < 700
        self._active_body_layout.setDirection(
            QBoxLayout.TopToBottom if narrow else QBoxLayout.LeftToRight
        )
        self._active_footer_layout.setDirection(
            QBoxLayout.TopToBottom if narrow else QBoxLayout.LeftToRight
        )
        self._active_details_form.setRowWrapPolicy(
            QFormLayout.WrapAllRows if narrow else QFormLayout.WrapLongRows
        )
        self._active_details_scroll.setMinimumHeight(0)
        self.lbl_qr.setAlignment(Qt.AlignCenter)
