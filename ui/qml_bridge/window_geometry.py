"""Recover unreachable window rectangles using connected screen work areas."""
from __future__ import annotations

from PySide6 import QtCore, QtGui


def recover_window_geometry(rect, work_areas, primary, minimum_width, minimum_height):
    geometry = {key: int(rect[key]) for key in ('x', 'y', 'width', 'height')}
    areas = [area for area in work_areas if area['width'] > 0 and area['height'] > 0]
    for area in areas:
        if (geometry['x'] < area['x'] + area['width']
                and geometry['x'] + geometry['width'] > area['x']
                and geometry['y'] < area['y'] + area['height']
                and geometry['y'] + geometry['height'] > area['y']):
            return {'geometry': geometry, 'workArea': dict(area)}
    if not areas or primary not in areas:
        return {'geometry': geometry, 'workArea': {}}
    width = min(primary['width'], max(minimum_width, geometry['width']))
    height = min(primary['height'], max(minimum_height, geometry['height']))
    return {'geometry': {'x': primary['x'] + (primary['width'] - width) // 2,
                         'y': primary['y'] + (primary['height'] - height) // 2,
                         'width': width, 'height': height}, 'workArea': dict(primary)}


class WindowGeometry(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None, *, application=None):
        super().__init__(parent)
        self._application = application if application is not None else QtGui.QGuiApplication.instance()
        self._screens = []
        if self._application is not None:
            self._application.screenAdded.connect(self._screens_changed)
            self._application.screenRemoved.connect(self._screens_changed)
            self._application.primaryScreenChanged.connect(self._work_areas_changed)
            self._screens_changed()

    def _screens_changed(self, *_):
        screens = self._application.screens()
        for screen in self._screens:
            if screen not in screens:
                try:
                    screen.availableGeometryChanged.disconnect(self._work_areas_changed)
                    screen.geometryChanged.disconnect(self._work_areas_changed)
                except RuntimeError:
                    pass  # Qt may already have destroyed a disconnected screen.
        for screen in screens:
            if screen not in self._screens:
                screen.availableGeometryChanged.connect(self._work_areas_changed)
                screen.geometryChanged.connect(self._work_areas_changed)
        self._screens = screens
        self.changed.emit()

    def _work_areas_changed(self, *_):
        self.changed.emit()

    @staticmethod
    def _area(screen):
        if screen is None:
            return {}
        rect = screen.availableGeometry()
        return {'x': rect.x(), 'y': rect.y(), 'width': rect.width(), 'height': rect.height()}

    @QtCore.Slot('QVariantMap', int, int, result='QVariantMap')
    def recover(self, rect, minimum_width, minimum_height):
        areas = [self._area(screen) for screen in self._application.screens()] if self._application else []
        primary = self._area(self._application.primaryScreen()) if self._application else {}
        return recover_window_geometry(rect, areas, primary, minimum_width, minimum_height)
