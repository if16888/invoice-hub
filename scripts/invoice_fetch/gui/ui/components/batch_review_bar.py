"""Compact, wrapping batch actions for the existing review table panel."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from .button import AppButton


class BatchReviewBar(QFrame):
    approve_requested = Signal()
    link_requested = Signal()
    ignore_requested = Signal()
    clear_requested = Signal()
    evidence_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BatchReviewBar")
        self.setProperty("class", "SubtleSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "status")
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.approve = AppButton("通过所选", variant="primary", parent=self)
        self.link = AppButton("加入报销组", parent=self)
        self.ignore = AppButton("忽略所选", parent=self)
        self.clear = AppButton("清空选择", parent=self)
        for button, signal in ((self.approve, self.approve_requested), (self.link, self.link_requested),
                               (self.ignore, self.ignore_requested), (self.clear, self.clear_requested)):
            button.setMinimumWidth(0)
            button.clicked.connect(lambda checked=False, target=signal: target.emit())
            actions.addWidget(button)
        layout.addLayout(actions)
        sharing = QHBoxLayout()
        self.evidence = AppButton("共享证明材料", parent=self)
        self.evidence.clicked.connect(self.evidence_requested.emit)
        sharing.addWidget(self.evidence)
        sharing.addStretch(1)
        layout.addLayout(sharing)
        self.hide()

    def set_selection(self, count: int, amounts: str) -> None:
        self.summary.setText(f"已选择 {count} 张（已加载记录）｜{amounts}")
        self.approve.setText(f"通过所选 ({count})")
        self.setVisible(count > 1)
