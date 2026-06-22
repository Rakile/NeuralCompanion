"""Static main-window dock layout helpers.

This mixin owns the fixed shell around the runtime-backed panels. The panel
contents still come from the existing backend/addon mixins.
"""

from PySide6 import QtCore, QtWidgets

from ui.theme_support import (
    build_app_stylesheet_for_preset as _build_app_stylesheet_for_preset,
    install_app_wide_slider_styling as _install_app_wide_slider_styling,
)


class MainWindowLayoutMixin:
    def _build_ui(self):
        self.setDockNestingEnabled(True)
        self.setStyleSheet(_build_app_stylesheet_for_preset(self.current_app_theme_preset()))
        _install_app_wide_slider_styling(self)

        central = QtWidgets.QWidget()
        central.setObjectName("workspace_central")
        central.setMinimumSize(0, 0)
        central.setMaximumSize(0, 0)
        central.hide()
        self.setCentralWidget(central)

        self.system_shaping_panel, self.workspace_tabs_panel = self._build_left_panel()
        self.right_panel = self._build_right_panel()

        self.system_shaping_dock = QtWidgets.QDockWidget("HOST", self)
        self.system_shaping_dock.setObjectName("SystemShapingDock")
        self.system_shaping_dock.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea
            | QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.TopDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
        )
        self.system_shaping_dock.setMinimumSize(0, 0)
        self.system_shaping_dock.setWidget(self.system_shaping_panel)
        self._register_workspace_dock(self.system_shaping_dock)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.system_shaping_dock)

        self.workspace_tabs_dock = QtWidgets.QDockWidget("ADDONS", self)
        self.workspace_tabs_dock.setObjectName("WorkspaceTabsDock")
        self.workspace_tabs_dock.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea
            | QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.TopDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
        )
        self.workspace_tabs_dock.setMinimumSize(0, 0)
        self.workspace_tabs_dock.setWidget(self.workspace_tabs_panel)
        self._register_workspace_dock(self.workspace_tabs_dock)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.workspace_tabs_dock)
        try:
            self.tabifyDockWidget(self.system_shaping_dock, self.workspace_tabs_dock)
        except Exception:
            pass
        self.workspace_tabs_dock.raise_()

        self.operational_dock = QtWidgets.QDockWidget("CHAT WINDOW", self)
        self.operational_dock.setObjectName("OperationalViewDock")
        self.operational_dock.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea
            | QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.TopDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
        )
        self.operational_dock.setMinimumSize(0, 0)
        self.operational_dock.setWidget(self.right_panel)
        self._register_workspace_dock(self.operational_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.operational_dock)
        try:
            self.resizeDocks(
                [self.system_shaping_dock, self.operational_dock],
                [520, 720],
                QtCore.Qt.Horizontal,
            )
        except Exception:
            pass
        self._build_workspace_menu()

    def _wrap_panel(self):
        panel = QtWidgets.QFrame()
        panel.setObjectName("Panel")
        return panel

    def _wrap_compact_form_field(self, widget):
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget, 0, QtCore.Qt.AlignLeft)
        layout.addStretch(1)
        return row

    def _make_header(self, eyebrow, title):
        frame = QtWidgets.QFrame()
        frame.setObjectName("HeaderCard")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        eyebrow_label = QtWidgets.QLabel(eyebrow)
        eyebrow_label.setStyleSheet("color: #7fb4ff; font-size: 11px; font-weight: 700; text-transform: uppercase;")
        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #f2f5f9;")
        layout.addWidget(eyebrow_label)
        layout.addWidget(title_label)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        frame.adjustSize()
        frame.setFixedHeight(frame.sizeHint().height())
        return frame
