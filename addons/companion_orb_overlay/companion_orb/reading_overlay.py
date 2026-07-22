from __future__ import annotations

from pathlib import Path
import time

from PySide6 import QtCore, QtGui, QtWidgets


class ReadingRegionSelectionOverlay(QtWidgets.QDialog):
    selection_completed = QtCore.Signal(list)
    selection_cancelled = QtCore.Signal()

    def __init__(self, geometry: QtCore.QRect):
        super().__init__(None)
        self.origin: QtCore.QPoint | None = None
        self.current: QtCore.QPoint | None = None
        self.selected_rect = QtCore.QRect()
        self._fade_animation: QtCore.QPropertyAnimation | None = None
        self.setWindowTitle("Select text area")
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setGeometry(geometry)
        self._opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

    def _selection_rect(self) -> QtCore.QRect:
        if self.origin is None or self.current is None:
            return QtCore.QRect()
        return QtCore.QRect(self.origin, self.current).normalized()

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 108))
        selection = self._selection_rect()
        if selection.isNull():
            painter.setPen(QtGui.QColor(219, 234, 254))
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignCenter,
                "Drag around the text to read. Esc or right-click cancels.",
            )
            return
        painter.fillRect(selection, QtGui.QColor(56, 189, 248, 42))
        outer = QtGui.QPen(QtGui.QColor(125, 211, 252), 2)
        inner = QtGui.QPen(QtGui.QColor(14, 165, 233), 1)
        painter.setPen(outer)
        painter.drawRoundedRect(selection.adjusted(0, 0, -1, -1), 7, 7)
        painter.setPen(inner)
        painter.drawRoundedRect(selection.adjusted(3, 3, -4, -4), 5, 5)
        painter.setPen(QtGui.QColor(241, 245, 249))
        painter.drawText(
            selection.adjusted(10, 9, -10, -9),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
            f"{selection.width()} x {selection.height()}",
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.RightButton:
            self.selection_cancelled.emit()
            event.accept()
            self.reject()
            return
        if event.button() != QtCore.Qt.LeftButton:
            return
        self.origin = event.position().toPoint()
        self.current = QtCore.QPoint(self.origin)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.origin is None:
            return
        self.current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != QtCore.Qt.LeftButton or self.origin is None:
            return
        self.current = event.position().toPoint()
        selected = self._selection_rect()
        if selected.width() < 8 or selected.height() < 8:
            self.selection_cancelled.emit()
            self.reject()
            return
        self.selected_rect = selected.translated(self.geometry().topLeft())
        bounds = [
            int(self.selected_rect.x()),
            int(self.selected_rect.y()),
            int(self.selected_rect.width()),
            int(self.selected_rect.height()),
        ]
        self.selection_completed.emit(bounds)
        self.setEnabled(False)
        self.fade_out_and_close()

    def keyPressEvent(self, event) -> None:
        if event.key() == QtCore.Qt.Key_Escape:
            self.selection_cancelled.emit()
            self.reject()
            return
        super().keyPressEvent(event)

    def fade_out_and_close(self) -> None:
        if (
            self._fade_animation is not None
            and self._fade_animation.state() == QtCore.QAbstractAnimation.Running
        ):
            return
        animation = QtCore.QPropertyAnimation(self._opacity_effect, b"opacity", self)
        animation.setDuration(180)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)

        def finish() -> None:
            self._fade_animation = None
            self.done(QtWidgets.QDialog.Accepted)

        animation.finished.connect(finish)
        self._fade_animation = animation
        animation.start()


def virtual_desktop_rect() -> QtCore.QRect | None:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return None
    screens = list(QtWidgets.QApplication.screens() or [])
    if not screens:
        return None
    rect = QtCore.QRect(screens[0].geometry())
    for screen in screens[1:]:
        rect = rect.united(screen.geometry())
    return rect


def select_region(parent: QtWidgets.QWidget | None = None) -> list[int]:
    geometry = virtual_desktop_rect()
    if geometry is None or geometry.isEmpty():
        return []
    overlay = ReadingRegionSelectionOverlay(geometry)
    if parent is not None:
        overlay.setParent(parent, overlay.windowFlags())
    accepted = overlay.exec() == QtWidgets.QDialog.Accepted
    bounds = [
        int(overlay.selected_rect.x()),
        int(overlay.selected_rect.y()),
        int(overlay.selected_rect.width()),
        int(overlay.selected_rect.height()),
    ] if accepted and not overlay.selected_rect.isNull() else []
    return bounds


def capture_region_image(bounds, output_dir: Path, *, grabber=None, virtual_bounds=None) -> Path:
    try:
        raw_values = list(bounds or [])
    except TypeError as exc:
        raise ValueError("Selected bounds must contain exactly four values.") from exc
    if len(raw_values) != 4:
        raise ValueError("Selected bounds must contain exactly four values.")
    try:
        values = [int(value) for value in raw_values]
    except (TypeError, ValueError) as exc:
        raise ValueError("Selected bounds must contain integer values.") from exc
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise ValueError("Selected bounds are empty.")
    if grabber is None:
        from PIL import ImageGrab

        grabber = ImageGrab.grab
    output_dir.mkdir(parents=True, exist_ok=True)
    image = grabber(all_screens=True).convert("RGB")
    if image.width <= 0 or image.height <= 0:
        raise ValueError("Desktop capture is empty.")
    virtual_values = []
    virtual_rect = None
    if virtual_bounds is not None:
        try:
            virtual_values = [int(value) for value in list(virtual_bounds)]
        except (TypeError, ValueError):
            virtual_values = []
    else:
        virtual_rect = virtual_desktop_rect()
    left, top, width, height = values
    if len(virtual_values) == 4 and virtual_values[2] > 0 and virtual_values[3] > 0:
        virtual_left, virtual_top, virtual_width, virtual_height = virtual_values
    elif virtual_rect is not None and virtual_rect.width() > 0 and virtual_rect.height() > 0:
        virtual_left = int(virtual_rect.x())
        virtual_top = int(virtual_rect.y())
        virtual_width = int(virtual_rect.width())
        virtual_height = int(virtual_rect.height())
    else:
        virtual_width = 0
        virtual_height = 0
    if virtual_width > 0 and virtual_height > 0:
        # ImageGrab(all_screens=True) returns one virtual-desktop bitmap; these scale
        # factors assume uniform mapping and validate overlap before edge clamping.
        x_scale = image.width / max(1, virtual_width)
        y_scale = image.height / max(1, virtual_height)
        crop = (
            int(round((left - virtual_left) * x_scale)),
            int(round((top - virtual_top) * y_scale)),
            int(round((left + width - virtual_left) * x_scale)),
            int(round((top + height - virtual_top) * y_scale)),
        )
    else:
        crop = (left, top, left + width, top + height)
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError("Selected bounds are empty.")
    if crop[0] >= image.width or crop[1] >= image.height or crop[2] <= 0 or crop[3] <= 0:
        raise ValueError("Selected region is outside the available desktop capture.")
    crop = (
        max(0, min(image.width, crop[0])),
        max(0, min(image.height, crop[1])),
        max(0, min(image.width, crop[2])),
        max(0, min(image.height, crop[3])),
    )
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError("Selected region is outside the available desktop capture.")
    cropped = image.crop(crop)
    output_path = output_dir / f"companion_orb_read_{int(time.time() * 1000)}.jpg"
    cropped.save(output_path, format="JPEG", quality=88, optimize=True)
    return output_path
