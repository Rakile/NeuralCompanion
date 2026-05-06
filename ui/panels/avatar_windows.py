"""Small top-level windows used by avatar focus modes."""

from PySide6 import QtCore, QtWidgets

from addons.musetalk_avatar.stage_window import QtMuseTalkStageWindow


class QtExternalAvatarReturnWindow(QtWidgets.QWidget):
    showInterfaceRequested = QtCore.Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("Neural Companion")
        self.setWindowFlag(QtCore.Qt.Tool, True)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self._drag_offset = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.surface = QtWidgets.QFrame()
        self.surface.setObjectName("external_avatar_return_surface")
        self.surface.setStyleSheet(
            "QFrame#external_avatar_return_surface {"
            "background: rgba(12, 18, 26, 232);"
            "border: 1px solid #314154;"
            "border-radius: 14px;"
            "}"
        )
        surface_layout = QtWidgets.QHBoxLayout(self.surface)
        surface_layout.setContentsMargins(10, 10, 10, 10)
        surface_layout.setSpacing(8)
        self.mode_badge = QtWidgets.QLabel("Avatar")
        self.mode_badge.setCursor(QtCore.Qt.OpenHandCursor)
        self.mode_badge.setStyleSheet(
            "color: #8ea3b8; font-size: 11px; font-weight: 600; padding: 0 2px;"
        )
        self.show_button = QtWidgets.QPushButton("Show NC")
        self.show_button.setMinimumHeight(30)
        self.show_button.setMinimumWidth(92)
        self.show_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.show_button.setStyleSheet(
            "QPushButton {"
            "padding: 4px 12px;"
            "border-radius: 10px;"
            "font-weight: 600;"
            "color: #ecf3fb;"
            "background: #223043;"
            "border: 1px solid #3a516d;"
            "}"
            "QPushButton:hover {"
            "background: #2b3d55;"
            "border-color: #4a6687;"
            "}"
            "QPushButton:pressed {"
            "background: #1b2635;"
            "}"
        )
        self.show_button.clicked.connect(self.showInterfaceRequested.emit)
        surface_layout.addWidget(self.mode_badge, 0)
        surface_layout.addWidget(self.show_button, 0)
        layout.addWidget(self.surface)
        self.surface.installEventFilter(self)
        self.mode_badge.installEventFilter(self)
        self.configure_for_mode("Avatar")

    def configure_for_mode(self, mode_label):
        label = str(mode_label or "avatar").strip() or "avatar"
        self.mode_badge.setText(label)
        tooltip = f"NC interface is hidden while {label} stays in focus. Click to bring Neural Companion back."
        self.setToolTip(tooltip)
        self.show_button.setToolTip(tooltip)
        self.mode_badge.setToolTip(tooltip)
        self.adjustSize()

    def closeEvent(self, event):
        self.showInterfaceRequested.emit()
        event.ignore()

    def eventFilter(self, watched, event):
        if watched in {self.surface, self.mode_badge}:
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
                self._drag_offset = global_pos - self.frameGeometry().topLeft()
                if watched is self.mode_badge:
                    self.mode_badge.setCursor(QtCore.Qt.ClosedHandCursor)
                return True
            if event.type() == QtCore.QEvent.MouseMove and self._drag_offset is not None:
                global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
                self.move(global_pos - self._drag_offset)
                return True
            if event.type() == QtCore.QEvent.MouseButtonRelease and self._drag_offset is not None:
                self._drag_offset = None
                self.mode_badge.setCursor(QtCore.Qt.OpenHandCursor)
                return True
        return super().eventFilter(watched, event)
