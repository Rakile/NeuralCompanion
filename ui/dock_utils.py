"""Shared dock-window helpers for Designer preview and real UI modes."""


def _install_floating_dock_resize_filter(window, *, margin=8):
    from PySide6 import QtCore, QtGui, QtWidgets

    if not isinstance(window, QtWidgets.QMainWindow):
        return None

    class _FloatingDockResizeFilter(QtCore.QObject):
        def __init__(self, owner, resize_margin):
            super().__init__(owner)
            self._owner = owner
            self._margin = max(4, int(resize_margin or 8))
            self._resizing = False
            self._resize_edges = set()
            self._resize_dock = None
            self._start_global = QtCore.QPoint()
            self._start_geometry = QtCore.QRect()
            self._override_cursor_active = False

        def _global_pos(self, event):
            if hasattr(event, "globalPosition"):
                return event.globalPosition().toPoint()
            if hasattr(event, "globalPos"):
                return event.globalPos()
            return QtGui.QCursor.pos()

        def _dock_for_widget(self, widget):
            current = widget
            while current is not None:
                if isinstance(current, QtWidgets.QDockWidget):
                    return current
                current = current.parentWidget()
            return None

        def _edges_for_pos(self, dock, global_pos):
            if dock is None or not dock.isFloating():
                return set()
            local = dock.mapFromGlobal(global_pos)
            rect = dock.rect()
            if not rect.contains(local):
                return set()
            margin = self._margin
            edges = set()
            if local.x() <= margin:
                edges.add("left")
            elif local.x() >= rect.width() - margin:
                edges.add("right")
            if local.y() <= margin:
                edges.add("top")
            elif local.y() >= rect.height() - margin:
                edges.add("bottom")
            return edges

        def _cursor_for_edges(self, edges):
            if {"left", "top"} <= edges or {"right", "bottom"} <= edges:
                return QtCore.Qt.SizeFDiagCursor
            if {"right", "top"} <= edges or {"left", "bottom"} <= edges:
                return QtCore.Qt.SizeBDiagCursor
            if "left" in edges or "right" in edges:
                return QtCore.Qt.SizeHorCursor
            if "top" in edges or "bottom" in edges:
                return QtCore.Qt.SizeVerCursor
            return None

        def _set_resize_cursor(self, edges):
            cursor_shape = self._cursor_for_edges(edges)
            if cursor_shape is None:
                self._restore_cursor()
                return
            cursor = QtGui.QCursor(cursor_shape)
            if self._override_cursor_active:
                QtWidgets.QApplication.changeOverrideCursor(cursor)
            else:
                QtWidgets.QApplication.setOverrideCursor(cursor)
                self._override_cursor_active = True

        def _restore_cursor(self):
            if self._override_cursor_active:
                try:
                    QtWidgets.QApplication.restoreOverrideCursor()
                except Exception:
                    pass
                self._override_cursor_active = False

        def _resize_to(self, global_pos):
            if self._resize_dock is None:
                return
            delta = global_pos - self._start_global
            geometry = QtCore.QRect(self._start_geometry)
            minimum = self._resize_dock.minimumSize()
            if "left" in self._resize_edges:
                new_left = min(geometry.right() - minimum.width() + 1, geometry.left() + delta.x())
                geometry.setLeft(new_left)
            if "right" in self._resize_edges:
                new_right = max(geometry.left() + minimum.width() - 1, geometry.right() + delta.x())
                geometry.setRight(new_right)
            if "top" in self._resize_edges:
                new_top = min(geometry.bottom() - minimum.height() + 1, geometry.top() + delta.y())
                geometry.setTop(new_top)
            if "bottom" in self._resize_edges:
                new_bottom = max(geometry.top() + minimum.height() - 1, geometry.bottom() + delta.y())
                geometry.setBottom(new_bottom)
            self._resize_dock.setGeometry(geometry)

        def eventFilter(self, obj, event):
            if not isinstance(obj, QtWidgets.QWidget):
                return False
            event_type = event.type()
            if self._resizing:
                if event_type == QtCore.QEvent.MouseMove:
                    self._resize_to(self._global_pos(event))
                    return True
                if event_type == QtCore.QEvent.MouseButtonRelease:
                    self._resizing = False
                    self._resize_edges = set()
                    self._resize_dock = None
                    self._restore_cursor()
                    return True
                return False

            if event_type not in {QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.Leave}:
                return False
            if event_type == QtCore.QEvent.Leave:
                self._restore_cursor()
                return False
            dock = self._dock_for_widget(obj)
            if dock is None or not dock.isFloating():
                self._restore_cursor()
                return False
            global_pos = self._global_pos(event)
            edges = self._edges_for_pos(dock, global_pos)
            if event_type == QtCore.QEvent.MouseMove:
                self._set_resize_cursor(edges)
                return False
            if event_type == QtCore.QEvent.MouseButtonPress and edges and event.button() == QtCore.Qt.LeftButton:
                self._resizing = True
                self._resize_edges = set(edges)
                self._resize_dock = dock
                self._start_global = global_pos
                self._start_geometry = QtCore.QRect(dock.geometry())
                self._set_resize_cursor(edges)
                return True
            return False

    resize_filter = getattr(window, "_nc_floating_dock_resize_filter", None)
    if resize_filter is None:
        resize_filter = _FloatingDockResizeFilter(window, margin)
        setattr(window, "_nc_floating_dock_resize_filter", resize_filter)
    app = QtWidgets.QApplication.instance()
    if app is not None and not bool(getattr(window, "_nc_floating_dock_resize_filter_installed", False)):
        app.installEventFilter(resize_filter)
        setattr(window, "_nc_floating_dock_resize_filter_installed", True)
    return resize_filter


def configure_main_window_docking(window):
    """Apply the common dock behavior used by Designer preview and real UI shells."""
    from PySide6 import QtCore, QtWidgets

    if not isinstance(window, QtWidgets.QMainWindow):
        return
    options = (
        QtWidgets.QMainWindow.AnimatedDocks
        | QtWidgets.QMainWindow.AllowNestedDocks
        | QtWidgets.QMainWindow.AllowTabbedDocks
    )
    if hasattr(QtWidgets.QMainWindow, "GroupedDragging"):
        options |= QtWidgets.QMainWindow.GroupedDragging
    window.setDockOptions(options)
    window.setDockNestingEnabled(True)

    dock_areas = (
        QtCore.Qt.LeftDockWidgetArea
        | QtCore.Qt.RightDockWidgetArea
        | QtCore.Qt.TopDockWidgetArea
        | QtCore.Qt.BottomDockWidgetArea
    )
    dock_features = (
        QtWidgets.QDockWidget.DockWidgetClosable
        | QtWidgets.QDockWidget.DockWidgetMovable
        | QtWidgets.QDockWidget.DockWidgetFloatable
    )
    for dock in window.findChildren(QtWidgets.QDockWidget):
        dock.setAllowedAreas(dock_areas)
        dock.setFeatures(dock_features)
        dock.setMinimumSize(220, 160)
    _install_floating_dock_resize_filter(window)


def install_floating_dock_resize_filter(window, *, margin=8):
    """Give floating dock widgets a wider internal resize hit area."""
    return _install_floating_dock_resize_filter(window, margin=margin)
