from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class NoWheelComboBox(QtWidgets.QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class ContextTokenStepper(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minimum = 0
        self._maximum = 999999
        self._step = 1
        self._value = 0
        self._suppress_signal = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.line_edit = QtWidgets.QLineEdit()
        self.line_edit.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.line_edit.setMinimumWidth(94)
        self.line_edit.setStyleSheet(
            "QLineEdit {"
            " background: #0f141b; border: 1px solid #273342; border-right: 0;"
            " border-top-left-radius: 10px; border-bottom-left-radius: 10px;"
            " border-top-right-radius: 0; border-bottom-right-radius: 0;"
            " padding: 4px 10px; color: #f2f5f9; }"
        )
        self.line_edit.editingFinished.connect(self._commit_text)

        button_column = QtWidgets.QFrame()
        button_column.setStyleSheet(
            "QFrame { background: #0f141b; border: 1px solid #273342;"
            " border-top-right-radius: 10px; border-bottom-right-radius: 10px; }"
        )
        button_layout = QtWidgets.QVBoxLayout(button_column)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(0)

        self.up_button = QtWidgets.QToolButton()
        self.up_button.setArrowType(QtCore.Qt.UpArrow)
        self.up_button.setAutoRepeat(True)
        self.up_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.up_button.clicked.connect(lambda: self.stepBy(self._step))

        self.down_button = QtWidgets.QToolButton()
        self.down_button.setArrowType(QtCore.Qt.DownArrow)
        self.down_button.setAutoRepeat(True)
        self.down_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.down_button.clicked.connect(lambda: self.stepBy(-self._step))

        divider = QtWidgets.QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #273342;")

        button_layout.addWidget(self.up_button)
        button_layout.addWidget(divider)
        button_layout.addWidget(self.down_button)

        layout.addWidget(self.line_edit)
        layout.addWidget(button_column)

    def setRange(self, minimum, maximum):
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self.setValue(self._value)

    def setSingleStep(self, step):
        self._step = max(1, int(step))

    def setAccelerated(self, _enabled):
        pass

    def setMinimumWidth(self, width):
        self.line_edit.setMinimumWidth(max(48, int(width) - 28))

    def _emit_value_changed(self):
        if not self._suppress_signal:
            self.valueChanged.emit(int(self._value))

    def value(self):
        return int(self._value)

    def setValue(self, value):
        clamped = max(self._minimum, min(self._maximum, int(value)))
        changed = clamped != self._value
        self._value = clamped
        self.line_edit.setText(str(self._value))
        if changed:
            self._emit_value_changed()

    def stepBy(self, steps):
        self.setValue(self._value + int(steps) * self._step)

    def _commit_text(self):
        text = self.line_edit.text().strip()
        try:
            parsed = int(text)
        except Exception:
            parsed = self._value
        self.setValue(parsed)

    def blockSignals(self, block):
        previous = super().blockSignals(block)
        self._suppress_signal = bool(block)
        return previous

    def setFixedHeight(self, height):
        super().setFixedHeight(height)
        self.line_edit.setFixedHeight(max(20, int(height)))
