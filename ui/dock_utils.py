"""Shared dock-window helpers for Designer preview and real UI modes."""


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
