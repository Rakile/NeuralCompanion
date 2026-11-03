from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtQuick


def virtual_desktop_geometry() -> QtCore.QRect:
    screens = QtGui.QGuiApplication.screens()
    if not screens:
        return QtCore.QRect()
    geometry = QtCore.QRect(screens[0].geometry())
    for screen in screens[1:]:
        geometry = geometry.united(screen.geometry())
    return geometry


class _RegionSelectorBridge(QtCore.QObject):
    completed = QtCore.Signal(list)
    cancelled = QtCore.Signal()

    def __init__(self, *, square: bool, parent=None):
        super().__init__(parent)
        self._square = bool(square)

    @QtCore.Property(bool, constant=True)
    def squareMode(self) -> bool:
        return self._square

    @QtCore.Slot(float, float, float, float)
    def complete(self, x: float, y: float, width: float, height: float) -> None:
        if width < 8 or height < 8:
            self.cancelled.emit()
            return
        self.completed.emit(
            [
                int(round(x)),
                int(round(y)),
                int(round(width)),
                int(round(height)),
            ]
        )

    @QtCore.Slot()
    def cancel(self) -> None:
        self.cancelled.emit()


class NativeRegionSelector(QtCore.QObject):
    completed = QtCore.Signal(list)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        geometry: QtCore.QRect,
        *,
        square: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.geometry = QtCore.QRect(geometry)
        self._bridge = _RegionSelectorBridge(square=square, parent=self)
        self._bridge.completed.connect(self._on_completed)
        self._bridge.cancelled.connect(self._on_cancelled)
        self._view = QtQuick.QQuickView()
        self._view.setTitle("Select screen area")
        self._view.setColor(QtGui.QColor(0, 0, 0, 0))
        self._view.setFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self._view.setResizeMode(QtQuick.QQuickView.SizeRootObjectToView)
        self._view.rootContext().setContextProperty(
            "nativeRegionSelector",
            self._bridge,
        )
        source = (
            Path(__file__).resolve().parent
            / "qml"
            / "NativeRegionSelector.qml"
        )
        self._view.setSource(QtCore.QUrl.fromLocalFile(str(source)))
        if self._view.status() == QtQuick.QQuickView.Error:
            errors = "; ".join(error.toString() for error in self._view.errors())
            raise RuntimeError(errors or "Native region selector QML failed to load")
        self._view.setGeometry(self.geometry)

    def show(self) -> None:
        self._view.show()
        self._view.requestActivate()

    def dispose(self) -> None:
        self._view.hide()
        self._view.close()
        self._view.deleteLater()
        self.deleteLater()

    def _on_completed(self, bounds: list[int]) -> None:
        left, top, width, height = [int(value) for value in bounds[:4]]
        self.completed.emit(
            [
                self.geometry.x() + left,
                self.geometry.y() + top,
                width,
                height,
            ]
        )
        self._view.hide()

    def _on_cancelled(self) -> None:
        self.cancelled.emit()
        self._view.hide()


def select_region(*, square: bool = False) -> list[int]:
    geometry = virtual_desktop_geometry()
    if geometry.isEmpty():
        return []
    selector = NativeRegionSelector(geometry, square=square)
    event_loop = QtCore.QEventLoop()
    result: list[int] = []

    def complete(bounds: list[int]) -> None:
        result[:] = [int(value) for value in bounds[:4]]
        event_loop.quit()

    selector.completed.connect(complete)
    selector.cancelled.connect(event_loop.quit)
    selector.show()
    event_loop.exec()
    selector.dispose()
    return result

