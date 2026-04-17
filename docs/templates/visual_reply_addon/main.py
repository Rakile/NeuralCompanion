from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from core.addons.base import BaseAddon


class VisualReplyPanel(QtWidgets.QWidget):
    loadRequested = QtCore.Signal()
    captionRequested = QtCore.Signal()
    clearRequested = QtCore.Signal()

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.status = QtWidgets.QLabel("Custom Visual Reply panel")
        self.status.setWordWrap(True)
        load_button = QtWidgets.QPushButton("Load Image")
        caption_button = QtWidgets.QPushButton("Caption")
        clear_button = QtWidgets.QPushButton("Clear")
        load_button.clicked.connect(self.loadRequested.emit)
        caption_button.clicked.connect(self.captionRequested.emit)
        clear_button.clicked.connect(self.clearRequested.emit)
        layout.addWidget(self.status)
        layout.addWidget(load_button)
        layout.addWidget(caption_button)
        layout.addWidget(clear_button)
        layout.addStretch(1)


class Addon(BaseAddon):
    TAB_ID = "my_visual_reply_extension_tab"

    def initialize(self, context):
        super().initialize(context)
        self._visual_service = context.get_service("qt.visual_reply")
        if self._visual_service is not None:
            self._visual_service.replace_panel(VisualReplyPanel())
        context.ui.register_tab(
            id=self.TAB_ID,
            title="Visuals",
            area="host_settings",
            order=130,
            tooltip="Template Visual Reply extension settings.",
            metadata={"nested_title": "Extension"},
            factory=self._build_tab,
        )
        return None

    def _build_tab(self, _context):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        snapshot = {}
        if self._visual_service is not None:
            snapshot = self._visual_service.settings_snapshot()
        label = QtWidgets.QLabel(f"Visual Reply snapshot: {snapshot}")
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
        return widget
