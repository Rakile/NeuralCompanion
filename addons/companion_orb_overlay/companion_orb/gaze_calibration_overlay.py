from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6 import QtCore, QtGui, QtQuick


TARGET_DURATION_SECONDS = 3.0
SETTLING_DURATION_SECONDS = 0.6


def _no_shadow_window_hint():
    return getattr(
        QtCore.Qt,
        "NoDropShadowWindowHint",
        QtCore.Qt.WindowType(0),
    )


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


class _CalibrationBridge(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_x = 0.0
        self.target_y = 0.0
        self.progress_value = 0.0
        self.settling_value = True
        self.message_value = ""
        self.index_value = 0
        self.count_value = 0
        self.color_value = "#22d3ee"

    @QtCore.Property(float, notify=changed)
    def targetX(self) -> float:
        return self.target_x

    @QtCore.Property(float, notify=changed)
    def targetY(self) -> float:
        return self.target_y

    @QtCore.Property(float, notify=changed)
    def progress(self) -> float:
        return self.progress_value

    @QtCore.Property(bool, notify=changed)
    def settling(self) -> bool:
        return self.settling_value

    @QtCore.Property(str, notify=changed)
    def message(self) -> str:
        return self.message_value

    @QtCore.Property(int, notify=changed)
    def targetIndex(self) -> int:
        return self.index_value

    @QtCore.Property(int, notify=changed)
    def targetCount(self) -> int:
        return self.count_value

    @QtCore.Property(str, notify=changed)
    def themeColor(self) -> str:
        return self.color_value


class GazeCalibrationOverlay(QtCore.QObject):
    target_elapsed = QtCore.Signal(int)
    cancel_requested = QtCore.Signal()

    def __init__(
        self,
        parent=None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
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
        self._bridge = _CalibrationBridge(self)
        self._view = QtQuick.QQuickView()
        self._view.setTitle("Companion Orb gaze calibration")
        self._view.setColor(QtGui.QColor(0, 0, 0, 0))
        self._view.setFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.WindowTransparentForInput
            | _no_shadow_window_hint()
        )
        self._view.setResizeMode(QtQuick.QQuickView.SizeRootObjectToView)
        self._view.rootContext().setContextProperty("gazeCalibrationBridge", self._bridge)
        source = Path(__file__).resolve().parent / "qml" / "GazeCalibrationOverlay.qml"
        self._view.setSource(QtCore.QUrl.fromLocalFile(str(source)))
        if self._view.status() == QtQuick.QQuickView.Error:
            errors = "; ".join(error.toString() for error in self._view.errors())
            raise RuntimeError(errors or "Gaze calibration overlay QML failed to load")
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
        self._view.setGeometry(QtCore.QRect(*self._screen_geometry))
        self.show_target(0)
        self._view.show()
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
        self._sync_bridge()

    def restart_target(self, message: str = "Hold gaze steady") -> None:
        if self._target_index < 0:
            return
        self._target_started_at = float(self._clock())
        self._progress = 0.0
        self._settling = True
        self._elapsed_emitted = False
        self._message = str(message or "Hold gaze steady").strip() or "Hold gaze steady"
        self._sync_bridge()

    @QtCore.Slot()
    def update_progress(self) -> None:
        if self._target_index < 0 or not self._targets:
            return
        elapsed = max(0.0, float(self._clock()) - self._target_started_at)
        self._progress = max(0.0, min(1.0, elapsed / TARGET_DURATION_SECONDS))
        self._settling = elapsed < SETTLING_DURATION_SECONDS
        self._sync_bridge()
        if elapsed >= TARGET_DURATION_SECONDS and not self._elapsed_emitted:
            self._elapsed_emitted = True
            self.target_elapsed.emit(self._target_index)

    def _sync_bridge(self) -> None:
        target = self.target_point
        if target is None:
            return
        left, top, _width, _height = self._screen_geometry
        self._bridge.target_x = target[0] - left
        self._bridge.target_y = target[1] - top
        self._bridge.progress_value = self._progress
        self._bridge.settling_value = self._settling
        self._bridge.message_value = self._message
        self._bridge.index_value = self._target_index
        self._bridge.count_value = len(self._targets)
        self._bridge.color_value = self._theme_color.name()
        self._bridge.changed.emit()

    def finish(self) -> None:
        self._timer.stop()
        self._view.hide()
        self._target_index = -1
        self._progress = 0.0
        self._elapsed_emitted = False

    def deleteLater(self) -> None:
        self.finish()
        self._view.close()
        self._view.deleteLater()
        super().deleteLater()

