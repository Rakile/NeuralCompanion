from __future__ import annotations

from pathlib import Path
import time

from PySide6 import QtCore, QtGui, QtQuick


class _SelectionBridge(QtCore.QObject):
    selection_completed = QtCore.Signal(list)
    selection_cancelled = QtCore.Signal()

    @QtCore.Slot(float, float, float, float)
    def complete(self, x: float, y: float, width: float, height: float) -> None:
        if width < 8 or height < 8:
            self.selection_cancelled.emit()
            return
        self.selection_completed.emit(
            [
                int(round(x)),
                int(round(y)),
                int(round(width)),
                int(round(height)),
            ]
        )

    @QtCore.Slot()
    def cancel(self) -> None:
        self.selection_cancelled.emit()


class ReadingRegionSelectionOverlay(QtCore.QObject):
    selection_completed = QtCore.Signal(list)
    selection_cancelled = QtCore.Signal()

    def __init__(self, geometry: QtCore.QRect, parent=None):
        super().__init__(parent)
        self.geometry = QtCore.QRect(geometry)
        self.selected_rect = QtCore.QRect()
        self._bridge = _SelectionBridge(self)
        self._bridge.selection_completed.connect(self._on_completed)
        self._bridge.selection_cancelled.connect(self._on_cancelled)
        self._view = QtQuick.QQuickView()
        self._view.setTitle("Select text area")
        self._view.setColor(QtGui.QColor(0, 0, 0, 0))
        self._view.setFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self._view.setResizeMode(QtQuick.QQuickView.SizeRootObjectToView)
        self._view.rootContext().setContextProperty("readingSelectionBridge", self._bridge)
        source = Path(__file__).resolve().parent / "qml" / "ReadingRegionSelection.qml"
        self._view.setSource(QtCore.QUrl.fromLocalFile(str(source)))
        if self._view.status() == QtQuick.QQuickView.Error:
            errors = "; ".join(error.toString() for error in self._view.errors())
            raise RuntimeError(errors or "Reading selection QML failed to load")
        self._view.setGeometry(self.geometry)

    def show(self) -> None:
        self._view.show()
        self._view.requestActivate()

    def close(self) -> None:
        self._view.hide()

    def deleteLater(self) -> None:
        self._view.close()
        self._view.deleteLater()
        super().deleteLater()

    def _on_completed(self, relative_bounds: list[int]) -> None:
        left, top, width, height = relative_bounds
        self.selected_rect = QtCore.QRect(
            self.geometry.x() + left,
            self.geometry.y() + top,
            width,
            height,
        )
        bounds = [
            self.selected_rect.x(),
            self.selected_rect.y(),
            self.selected_rect.width(),
            self.selected_rect.height(),
        ]
        self.selection_completed.emit(bounds)
        self.close()

    def _on_cancelled(self) -> None:
        self.selection_cancelled.emit()
        self.close()


def virtual_desktop_rect() -> QtCore.QRect | None:
    app = QtGui.QGuiApplication.instance()
    if app is None:
        return None
    screens = list(QtGui.QGuiApplication.screens() or [])
    if not screens:
        return None
    rect = QtCore.QRect(screens[0].geometry())
    for screen in screens[1:]:
        rect = rect.united(screen.geometry())
    return rect


def select_region(parent=None) -> list[int]:
    del parent
    geometry = virtual_desktop_rect()
    if geometry is None or geometry.isEmpty():
        return []
    overlay = ReadingRegionSelectionOverlay(geometry)
    event_loop = QtCore.QEventLoop()
    result: list[int] = []

    def complete(bounds: list[int]) -> None:
        result[:] = [int(value) for value in bounds[:4]]
        event_loop.quit()

    overlay.selection_completed.connect(complete)
    overlay.selection_cancelled.connect(event_loop.quit)
    overlay.show()
    event_loop.exec()
    overlay.deleteLater()
    return result


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
    cropped.save(output_path, format="JPEG", quality=100, optimize=True)
    return output_path
