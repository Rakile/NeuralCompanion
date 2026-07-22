from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence

from PySide6 import QtCore, QtGui, QtWidgets


TARGET_DURATION_SECONDS = 3.0
SETTLING_DURATION_SECONDS = 0.6


def _no_shadow_window_hint():
    return getattr(QtCore.Qt, "NoDropShadowWindowHint", QtCore.Qt.WindowType(0))


def _rect(values) -> tuple[int, int, int, int]:
    items = [int(round(float(value))) for value in list(values or [])[:4]]
    if len(items) != 4 or items[2] <= 0 or items[3] <= 0:
        raise ValueError("Calibration overlay geometry must have four positive values.")
    return items[0], items[1], items[2], items[3]


def _point(values) -> tuple[float, float]:
    items = [float(value) for value in list(values or [])[:2]]
    if len(items) != 2 or not all(math.isfinite(value) for value in items):
        raise ValueError("Calibration target must contain two finite coordinates.")
    return items[0], items[1]


class GazeCalibrationOverlay(QtWidgets.QWidget):
    target_elapsed = QtCore.Signal(int)
    cancel_requested = QtCore.Signal()

    def __init__(
        self,
        parent=None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        flags = (
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.WindowTransparentForInput
            | _no_shadow_window_hint()
        )
        super().__init__(parent, flags)
        self._clock = clock
        self._screen_geometry = (0, 0, 1, 1)
        self._calibration_rect = (0.0, 0.0, 1.0, 1.0)
        self._targets: tuple[tuple[float, float], ...] = ()
        self._target_index = -1
        self._target_started_at = 0.0
        self._progress = 0.0
        self._settling = True
        self._elapsed_emitted = False
        self._message = "Hold your gaze on the target"
        self._theme_color = QtGui.QColor("#22d3ee")

        self.setObjectName("companion_orb_gaze_calibration_overlay")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setWindowOpacity(1.0)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update_progress)

    @property
    def target_index(self) -> int:
        return self._target_index

    @property
    def target_point(self) -> tuple[float, float] | None:
        if 0 <= self._target_index < len(self._targets):
            return self._targets[self._target_index]
        return None

    @property
    def progress(self) -> float:
        return self._progress

    @property
    def settling(self) -> bool:
        return self._settling

    @property
    def message(self) -> str:
        return self._message

    @property
    def timer_active(self) -> bool:
        return self._timer.isActive()

    def begin(
        self,
        *,
        screen_geometry: Sequence[float],
        calibration_rect: Sequence[float],
        targets: Sequence[Sequence[float]],
        theme_color: str,
    ) -> None:
        self._screen_geometry = _rect(screen_geometry)
        self._calibration_rect = tuple(
            float(value) for value in list(calibration_rect or [])[:4]
        )
        if (
            len(self._calibration_rect) != 4
            or self._calibration_rect[2] <= 0.0
            or self._calibration_rect[3] <= 0.0
            or not all(math.isfinite(value) for value in self._calibration_rect)
        ):
            raise ValueError("Calibration rectangle must have four finite positive values.")
        self._targets = tuple(_point(target) for target in targets or ())
        if len(self._targets) != 5:
            raise ValueError("Calibration overlay requires exactly five targets.")
        color = QtGui.QColor(str(theme_color or ""))
        self._theme_color = color if color.isValid() else QtGui.QColor("#22d3ee")
        self.setGeometry(QtCore.QRect(*self._screen_geometry))
        self.show_target(0)
        self.show()
        self.raise_()
        self._timer.start()

    def show_target(self, index: int) -> None:
        target_index = int(index)
        if target_index < 0 or target_index >= len(self._targets):
            raise IndexError("Calibration target index is outside the target sequence.")
        self._target_index = target_index
        self._target_started_at = float(self._clock())
        self._progress = 0.0
        self._settling = True
        self._elapsed_emitted = False
        self._message = "Hold your gaze on the target"
        self.update()

    def restart_target(self, message: str = "Hold gaze steady") -> None:
        if self._target_index < 0:
            return
        self._target_started_at = float(self._clock())
        self._progress = 0.0
        self._settling = True
        self._elapsed_emitted = False
        self._message = str(message or "Hold gaze steady").strip() or "Hold gaze steady"
        self.update()

    @QtCore.Slot()
    def update_progress(self) -> None:
        if self._target_index < 0 or not self._targets:
            return
        elapsed = max(0.0, float(self._clock()) - self._target_started_at)
        self._progress = max(0.0, min(1.0, elapsed / TARGET_DURATION_SECONDS))
        self._settling = elapsed < SETTLING_DURATION_SECONDS
        self.update()
        if elapsed >= TARGET_DURATION_SECONDS and not self._elapsed_emitted:
            self._elapsed_emitted = True
            self.target_elapsed.emit(self._target_index)

    def finish(self) -> None:
        self._timer.stop()
        self.hide()
        self._target_index = -1
        self._progress = 0.0
        self._elapsed_emitted = False

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.finish()
        event.accept()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        target = self.target_point
        if target is None:
            return
        screen_left, screen_top, _screen_width, _screen_height = self._screen_geometry
        local_center = QtCore.QPointF(
            target[0] - screen_left,
            target[1] - screen_top,
        )
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        theme = QtGui.QColor(self._theme_color)
        active = QtGui.QColor("#f59e0b") if self._settling else theme
        shadow = QtGui.QColor(active)
        shadow.setAlpha(70)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(local_center, 30.0, 30.0)

        quiet_ring = QtGui.QColor(theme)
        quiet_ring.setAlpha(90)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(quiet_ring, 3.0))
        painter.drawEllipse(local_center, 24.0, 24.0)

        progress_pen = QtGui.QPen(active, 5.0)
        progress_pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(progress_pen)
        arc_rect = QtCore.QRectF(
            local_center.x() - 25.0,
            local_center.y() - 25.0,
            50.0,
            50.0,
        )
        painter.drawArc(
            arc_rect,
            90 * 16,
            int(round(-360.0 * self._progress * 16.0)),
        )

        core = QtGui.QColor(active)
        core.setAlpha(235)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(core)
        painter.drawEllipse(local_center, 9.0, 9.0)

        font = painter.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        text_color = QtGui.QColor("#f8fafc")
        painter.setPen(text_color)
        label_rect = QtCore.QRectF(
            local_center.x() - 125.0,
            local_center.y() + 38.0,
            250.0,
            22.0,
        )
        painter.drawText(
            label_rect,
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
            f"Target {self._target_index + 1} of {len(self._targets)}",
        )

        detail_font = QtGui.QFont(font)
        detail_font.setBold(False)
        detail_font.setPointSize(9)
        painter.setFont(detail_font)
        detail_color = QtGui.QColor("#d7e3f0")
        painter.setPen(detail_color)
        detail_rect = QtCore.QRectF(
            local_center.x() - 180.0,
            local_center.y() + 59.0,
            360.0,
            24.0,
        )
        painter.drawText(
            detail_rect,
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
            self._message,
        )
