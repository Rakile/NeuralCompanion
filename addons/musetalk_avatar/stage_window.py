"""Top-level MuseTalk avatar focus window owned by the MuseTalk addon."""

from PySide6 import QtCore, QtWidgets


class QtMuseTalkStageWindow(QtWidgets.QMainWindow):
    closeRequested = QtCore.Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("Neural Companion - MuseTalk Avatar")
        self.resize(1280, 920)
        self._allow_internal_close = False
        container = QtWidgets.QWidget()
        self._layout = QtWidgets.QVBoxLayout(container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setCentralWidget(container)

    def attach_preview_widget(self, widget):
        if widget is None:
            return
        old_parent = widget.parentWidget()
        if old_parent is not None and old_parent.layout() is not None:
            old_parent.layout().removeWidget(widget)
        widget.setParent(None)
        self._layout.addWidget(widget)
        widget.show()

    def allow_internal_close(self, allowed):
        self._allow_internal_close = bool(allowed)

    def closeEvent(self, event):
        if self._allow_internal_close:
            super().closeEvent(event)
            return
        self.closeRequested.emit()
        event.ignore()
