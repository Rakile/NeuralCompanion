"""Reusable low-level Qt widgets.

This module deliberately avoids importing qt_app.py. The one place where the
legacy combo box wants app theme assistance is handled through a small callback.
"""

import ctypes
import math
import os

from PySide6 import QtCore, QtGui, QtWidgets


_popup_palette_callback = None


def set_combo_popup_palette_callback(callback):
    global _popup_palette_callback
    _popup_palette_callback = callback if callable(callback) else None


class LabeledSlider(QtWidgets.QWidget):
    value_changed = QtCore.Signal(float)

    def __init__(self, title, minimum, maximum, value, is_int=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.is_int = is_int
        self.minimum = minimum
        self.maximum = maximum
        self.scale = 100 if not is_int else 1

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.label = QtWidgets.QLabel()
        self.label.setStyleSheet("font-weight: 600; color: #d8dee9;")
        self.slider = NoWheelSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimum(int(minimum * self.scale))
        self.slider.setMaximum(int(maximum * self.scale))
        self.slider.valueChanged.connect(self._on_value_changed)

        layout.addWidget(self.label)
        layout.addWidget(self.slider)
        self.set_value(value)
        self._refresh_label()

    def _normalized_value(self):
        raw = self.slider.value() / self.scale
        return int(raw) if self.is_int else round(raw, 2)

    def _refresh_label(self):
        self.label.setText(f"{self.title}: {self._normalized_value()}")

    def _on_value_changed(self, _):
        self._refresh_label()
        self.value_changed.emit(float(self._normalized_value()))

    def set_value(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(int(value * self.scale))
        self.slider.blockSignals(False)
        self._refresh_label()

    def value(self):
        return self._normalized_value()


class NoWheelSlider(QtWidgets.QSlider):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpinBox(QtWidgets.QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelComboBox(QtWidgets.QComboBox):
    def wheelEvent(self, event):
        event.ignore()

    def showPopup(self):
        if _popup_palette_callback is not None:
            try:
                _popup_palette_callback(self)
            except Exception:
                pass
        super().showPopup()


class CollapsibleSection(QtWidgets.QWidget):
    def __init__(self, title, content_widget=None, *, expanded=True, parent=None):
        super().__init__(parent)
        self._title = str(title or "").strip()
        self._summary = ""

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.toggle_button = QtWidgets.QToolButton()
        self.toggle_button.setObjectName("collapsible_section_toggle")
        self.toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(bool(expanded))
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.setMinimumSize(260, 34)
        self.toggle_button.setMaximumWidth(520)
        self.toggle_button.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        self.toggle_button.clicked.connect(self._on_toggled)
        self.toggle_button.setStyleSheet(
            "QToolButton { color: #fff7ff; font-weight: 700; border: 1px solid #ff3fbf; "
            "background: #21122f; border-radius: 8px; padding: 6px 12px; text-align: left; }"
            "QToolButton:hover { background: #351a55; }"
        )
        shadow = QtWidgets.QGraphicsDropShadowEffect(self.toggle_button)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 2)
        shadow.setColor(QtGui.QColor(255, 63, 191, 70))
        self.toggle_button.setGraphicsEffect(shadow)
        layout.addWidget(self.toggle_button)

        self.content_widget = content_widget or QtWidgets.QWidget()
        layout.addWidget(self.content_widget)
        self._refresh()

    def setContentWidget(self, widget):
        if widget is None or widget is self.content_widget:
            return
        layout = self.layout()
        old_widget = self.content_widget
        self.content_widget = widget
        layout.insertWidget(1, self.content_widget)
        if old_widget is not None:
            old_widget.setParent(None)
            old_widget.deleteLater()
        self._refresh()

    def setSummary(self, summary):
        self._summary = str(summary or "").strip()
        self._refresh()

    def isExpanded(self):
        return bool(self.toggle_button.isChecked())

    def setExpanded(self, expanded):
        self.toggle_button.setChecked(bool(expanded))
        self._refresh()

    def _on_toggled(self, _checked):
        self._refresh()

    def _refresh(self):
        expanded = bool(self.toggle_button.isChecked())
        self.toggle_button.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        label = self._title
        if self._summary:
            label = f"{label}  -  {self._summary}"
        self.toggle_button.setText(label)
        self.content_widget.setVisible(expanded)


class NoWheelTabWidget(QtWidgets.QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(NoWheelTabBar())
        self.currentChanged.connect(self._on_current_tab_changed)

    def _on_current_tab_changed(self, _index):
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None:
            parent.updateGeometry()

    def _current_page_height_hint(self):
        page = self.currentWidget()
        if page is None:
            return 0
        if isinstance(page, QtWidgets.QScrollArea):
            try:
                return int(page.sizeHint().height() or page.minimumSizeHint().height() or 0)
            except Exception:
                pass
            page = page.widget()
            if page is None:
                return 0
        layout = page.layout()
        if layout is not None:
            try:
                return int(layout.sizeHint().height() or page.minimumSizeHint().height() or page.sizeHint().height() or 0)
            except Exception:
                pass
        try:
            return int(page.minimumSizeHint().height() or page.sizeHint().height() or 0)
        except Exception:
            return 0

    def _adaptive_height_hint(self):
        tab_bar = self.tabBar()
        tab_height = int(tab_bar.sizeHint().height()) if tab_bar is not None else 0
        frame_width = int(self.style().pixelMetric(QtWidgets.QStyle.PM_DefaultFrameWidth, None, self) or 0)
        page_height = self._current_page_height_hint()
        return max(tab_height + page_height + (frame_width * 4) + 12, tab_height + 72)

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(self._adaptive_height_hint())
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setHeight(self._adaptive_height_hint())
        return hint

    def wheelEvent(self, event):
        event.ignore()


class NoWheelTabBar(QtWidgets.QTabBar):
    def wheelEvent(self, event):
        event.ignore()


class AltWheelZoomScrollArea(QtWidgets.QScrollArea):
    zoomRequested = QtCore.Signal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    def _handle_alt_zoom_event(self, event):
        modifiers = event.modifiers()
        if not modifiers:
            try:
                modifiers = QtWidgets.QApplication.keyboardModifiers()
            except Exception:
                modifiers = QtCore.Qt.NoModifier
        if not modifiers:
            try:
                modifiers = QtGui.QGuiApplication.queryKeyboardModifiers()
            except Exception:
                modifiers = QtCore.Qt.NoModifier
        alt_down = bool(modifiers & QtCore.Qt.AltModifier)
        if not alt_down and os.name == "nt":
            try:
                alt_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000)
            except Exception:
                alt_down = False
        if not alt_down:
            return False
        angle_delta = event.angleDelta()
        delta_value = angle_delta.y()
        if not delta_value:
            delta_value = angle_delta.x()
        if not delta_value:
            pixel_delta = event.pixelDelta()
            if pixel_delta is not None:
                delta_value = pixel_delta.y() or pixel_delta.x()
        if not delta_value:
            return False
        pos = event.position() if hasattr(event, "position") else QtCore.QPointF()
        self.zoomRequested.emit(1.12 if delta_value > 0 else (1.0 / 1.12), float(pos.x()), float(pos.y()))
        event.accept()
        return True

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QtCore.QEvent.Wheel:
            if self._handle_alt_zoom_event(event):
                return True
        return super().eventFilter(watched, event)

    def viewportEvent(self, event):
        if event.type() == QtCore.QEvent.Wheel and self._handle_alt_zoom_event(event):
            return True
        return super().viewportEvent(event)

    def wheelEvent(self, event):
        if self._handle_alt_zoom_event(event):
            return
        super().wheelEvent(event)


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
        button_column.setFixedWidth(28)
        button_column.setFixedHeight(28)
        button_column.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
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
        self.up_button.setFixedSize(26, 13)
        self.up_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.up_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.up_button.clicked.connect(lambda: self.stepBy(1))

        self.down_button = QtWidgets.QToolButton()
        self.down_button.setArrowType(QtCore.Qt.DownArrow)
        self.down_button.setAutoRepeat(True)
        self.down_button.setFixedSize(26, 13)
        self.down_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.down_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.down_button.clicked.connect(lambda: self.stepBy(-1))

        divider = QtWidgets.QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #273342;")

        button_layout.addWidget(self.up_button)
        button_layout.addWidget(divider)
        button_layout.addWidget(self.down_button)

        self.setFixedHeight(28)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
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

    def setMaximumWidth(self, width):
        self.line_edit.setMaximumWidth(max(48, int(width) - 28))

    def _emit_value_changed(self):
        if not self._suppress_signal:
            self.valueChanged.emit(int(self._value))

    def _clamp(self, value):
        return max(self._minimum, min(self._maximum, int(value)))

    def _refresh_text(self):
        self.line_edit.setText(str(int(self._value)))

    def _commit_text(self):
        raw = str(self.line_edit.text() or "").strip()
        try:
            value = int(raw)
        except Exception:
            value = self._value
        self.setValue(value)

    def setValue(self, value):
        clamped = self._clamp(value)
        changed = clamped != self._value
        self._value = clamped
        self._suppress_signal = True
        try:
            self._refresh_text()
        finally:
            self._suppress_signal = False
        if changed:
            self._emit_value_changed()

    def value(self):
        return int(self._value)

    def stepBy(self, delta_steps):
        self.setValue(self._value + int(delta_steps) * self._step)

    def wheelEvent(self, event):
        event.ignore()


class DecimalStepper(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minimum = 0.0
        self._maximum = 999999.0
        self._step = 1.0
        self._decimals = 1
        self._value = 0.0
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
        button_column.setFixedWidth(28)
        button_column.setFixedHeight(28)
        button_column.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
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
        self.up_button.setFixedSize(26, 13)
        self.up_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.up_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.up_button.clicked.connect(lambda: self.stepBy(1))

        self.down_button = QtWidgets.QToolButton()
        self.down_button.setArrowType(QtCore.Qt.DownArrow)
        self.down_button.setAutoRepeat(True)
        self.down_button.setFixedSize(26, 13)
        self.down_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.down_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.down_button.clicked.connect(lambda: self.stepBy(-1))

        divider = QtWidgets.QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #273342;")

        button_layout.addWidget(self.up_button)
        button_layout.addWidget(divider)
        button_layout.addWidget(self.down_button)

        self.setFixedHeight(28)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.line_edit)
        layout.addWidget(button_column)

    def setRange(self, minimum, maximum):
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self.setValue(self._value)

    def setSingleStep(self, step):
        self._step = max(0.001, float(step))

    def setDecimals(self, decimals):
        self._decimals = max(0, int(decimals))
        self._refresh_text()

    def setAccelerated(self, _enabled):
        pass

    def setMinimumWidth(self, width):
        self.line_edit.setMinimumWidth(max(48, int(width) - 28))

    def setMaximumWidth(self, width):
        self.line_edit.setMaximumWidth(max(48, int(width) - 28))

    def _emit_value_changed(self):
        if not self._suppress_signal:
            self.valueChanged.emit(float(self._value))

    def _clamp(self, value):
        numeric = float(value)
        return max(self._minimum, min(self._maximum, numeric))

    def _refresh_text(self):
        self.line_edit.setText(f"{self._value:.{self._decimals}f}")

    def _commit_text(self):
        raw = str(self.line_edit.text() or "").strip().replace(",", ".")
        try:
            value = float(raw)
        except Exception:
            value = self._value
        self.setValue(value)

    def setValue(self, value):
        clamped = round(self._clamp(value), self._decimals)
        changed = not math.isclose(clamped, self._value, rel_tol=1e-9, abs_tol=10 ** (-(self._decimals + 1)))
        self._value = clamped
        self._suppress_signal = True
        try:
            self._refresh_text()
        finally:
            self._suppress_signal = False
        if changed:
            self._emit_value_changed()

    def value(self):
        return float(self._value)

    def stepBy(self, delta_steps):
        self.setValue(self._value + float(delta_steps) * self._step)

    def wheelEvent(self, event):
        event.ignore()
