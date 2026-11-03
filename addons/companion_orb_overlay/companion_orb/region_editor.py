"""Temporary region-size controls and an input-transparent capture outline.

Uses the same desktop logical coordinates as window_target_resolver; Qt handles
display scaling. Draft edits are local until Done is pressed.
"""
from pathlib import Path

from PySide6 import QtCore, QtGui, QtQuick

from .window_target_resolver import resolve_target_at
from .reading_overlay import virtual_desktop_rect


class RegionSizeEditor(QtCore.QObject):
    changed = QtCore.Signal()
    accepted = QtCore.Signal(int, int)
    finished = QtCore.Signal()

    def __init__(self, center, width, height, parent=None, *, center_provider=None):
        super().__init__(parent)
        self._center = QtCore.QPoint(center)
        self._center_provider = center_provider
        self._width = max(64, min(2560, int(width)))
        self._height = max(64, min(1440, int(height)))
        self._finished = False
        self.preview = self._view('RegionSizePreview.qml', preview=True)
        self.view = self._view('RegionSizeEditor.qml', preview=False)
        self.view.installEventFilter(self)
        self.view.setTitle('Orb region size')
        self.view.resize(360, 250)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_preview)
        self._update_preview()
        screen = QtGui.QGuiApplication.screenAt(self._center) or QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            rect = screen.availableGeometry()
            self.view.setPosition(max(rect.left(), min(self._center.x() + 100, rect.right() - 360)),
                                  max(rect.top(), min(self._center.y() + 80, rect.bottom() - 250)))

    def _view(self, filename, *, preview):
        view = QtQuick.QQuickView()
        flags = QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint
        if preview:
            flags |= (QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowTransparentForInput
                      | QtCore.Qt.WindowDoesNotAcceptFocus)
        view.setFlags(flags)
        view.setColor(QtGui.QColor('transparent'))
        view.setResizeMode(QtQuick.QQuickView.SizeRootObjectToView)
        view.rootContext().setContextProperty('regionEditor', self)
        view.setSource(QtCore.QUrl.fromLocalFile(str(Path(__file__).parent / 'qml' / filename)))
        if view.status() == QtQuick.QQuickView.Error:
            errors = '; '.join(error.toString() for error in view.errors())
            view.deleteLater()
            raise RuntimeError(errors)
        return view

    @QtCore.Property(int, notify=changed)
    def regionWidth(self):
        return self._width

    @QtCore.Property(int, notify=changed)
    def regionHeight(self):
        return self._height

    @QtCore.Slot(int)
    def setWidth(self, value):
        self._width = max(64, min(2560, value))
        self._update_preview()
        self.changed.emit()

    @QtCore.Slot(int)
    def setHeight(self, value):
        self._height = max(64, min(1440, value))
        self._update_preview()
        self.changed.emit()

    def _update_preview(self):
        if self._center_provider is not None:
            self._center = QtCore.QPoint(self._center_provider())
        target = resolve_target_at(self._center.x(), self._center.y(),
                                   region_width=self._width, region_height=self._height, mode='region')
        screen = QtGui.QGuiApplication.screenAt(self._center)
        if screen is not None and self.preview.screen() != screen:
            self.preview.setScreen(screen)
        bounds = QtCore.QRect(*target['bounds'])
        desktop = virtual_desktop_rect()
        if desktop is not None:
            bounds = bounds.intersected(desktop)
        if not bounds.isEmpty():
            self.preview.setGeometry(bounds)

    def show(self):
        self.preview.show()
        self.view.show()
        self.view.requestActivate()
        self._timer.start()

    @QtCore.Slot()
    def accept(self):
        if self._finished:
            return
        self.accepted.emit(self._width, self._height)
        self.cancel()

    @QtCore.Slot()
    def cancel(self):
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        self.preview.hide()
        self.view.hide()
        self.finished.emit()

    def eventFilter(self, watched, event):
        if watched is self.view and event.type() == QtCore.QEvent.Close:
            self.cancel()
        return super().eventFilter(watched, event)

    def deleteLater(self):
        self._timer.stop()
        for view in (self.preview, self.view):
            view.removeEventFilter(self)
            view.close()
            view.deleteLater()
        super().deleteLater()
