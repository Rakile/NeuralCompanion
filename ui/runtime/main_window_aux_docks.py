"""Auxiliary dock and avatar-focus helpers for the runtime-backed main window."""

from pathlib import Path

from PySide6 import QtCore, QtWidgets

import shared_state
from addons.musetalk_avatar import real_ui_bridge as musetalk_real_ui_bridge
from addons.visual_reply.controller import AddonVisualReplyPanel as QtVisualReplyPanel
from engine import RUNTIME_CONFIG
from ui.panels.avatar_windows import QtExternalAvatarReturnWindow
from ui.theme_support import app_theme_palette as _app_theme_palette

APP_ROOT = Path(__file__).resolve().parents[2]


class MainWindowAuxDocksMixin:
    def _build_preview_dock(self):
        musetalk_real_ui_bridge.build_preview_dock(
            self,
            theme_provider=_app_theme_palette,
            runtime_config=RUNTIME_CONFIG,
        )

        self.visual_reply_dock = QtWidgets.QDockWidget("Visual Reply", self)
        self.visual_reply_dock.setObjectName("VisualReplyDock")
        self.visual_reply_dock.setAllowedAreas(
            QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
            | QtCore.Qt.LeftDockWidgetArea
        )
        self.visual_reply_panel = QtVisualReplyPanel(
            theme_provider=_app_theme_palette,
            runtime_config=RUNTIME_CONFIG,
            shared_state_module=shared_state,
            storage_dir=APP_ROOT / "runtime" / "visual_replies",
        )
        self.visual_reply_panel.loadRequested.connect(self.prompt_visual_reply_image)
        self.visual_reply_panel.captionRequested.connect(self.prompt_visual_reply_caption)
        self.visual_reply_panel.clearRequested.connect(lambda: self.clear_visual_reply(auto_show=False))
        self.visual_reply_dock.setWidget(self.visual_reply_panel)
        self._register_workspace_dock(self.visual_reply_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.visual_reply_dock)
        self.tabifyDockWidget(self.preview_dock, self.visual_reply_dock)
        self.visual_reply_dock.hide()
        if hasattr(self, "workspace_menu"):
            self.workspace_menu.insertAction(self.workspace_menu.actions()[-2], self.visual_reply_dock.toggleViewAction())

    def _ensure_musetalk_stage_window(self):
        return musetalk_real_ui_bridge.ensure_stage_window(self)

    def _ensure_external_avatar_return_window(self):
        if self._external_avatar_return_window is None:
            self._external_avatar_return_window = QtExternalAvatarReturnWindow()
            self._external_avatar_return_window.showInterfaceRequested.connect(self.show_main_interface_from_external_avatar_focus)
        return self._external_avatar_return_window

    def _position_external_avatar_return_window(self):
        window = self._ensure_external_avatar_return_window()
        main_geometry = self.frameGeometry()
        anchor = main_geometry.topLeft() + QtCore.QPoint(40, 40)
        rect = QtCore.QRect(anchor, window.size())
        available = QtWidgets.QApplication.primaryScreen().availableGeometry() if QtWidgets.QApplication.primaryScreen() else None
        if available is not None:
            if rect.right() > available.right():
                rect.moveRight(available.right() - 16)
            if rect.bottom() > available.bottom():
                rect.moveBottom(available.bottom() - 16)
            if rect.left() < available.left():
                rect.moveLeft(available.left() + 16)
            if rect.top() < available.top():
                rect.moveTop(available.top() + 16)
        window.setGeometry(rect)
        return window

    def _attach_musetalk_preview_to_host(self, host):
        return musetalk_real_ui_bridge.attach_preview_to_host(self, host)

    def _sync_musetalk_stage_window_geometry_from_preview(self):
        return musetalk_real_ui_bridge.sync_stage_window_geometry_from_preview(self)

    def enter_external_avatar_focus(self, mode_label=None):
        mode_label = str(mode_label or self.engine_combo.currentText() or "Avatar").strip() or "Avatar"
        self._external_avatar_focus_active = True
        self._external_avatar_focus_mode = mode_label
        self._external_avatar_main_window_was_maximized = bool(self.isMaximized())
        self._external_avatar_main_window_was_fullscreen = bool(self.isFullScreen())
        window = self._position_external_avatar_return_window()
        window.configure_for_mode(mode_label)
        window.show()
        window.raise_()
        window.activateWindow()
        self._hide_main_preserving_pinned_floating_docks()
        print(f"[QtGUI] External avatar focus entered for {mode_label}.")

    def exit_external_avatar_focus(self, *, raise_main=True):
        was_active = bool(self._external_avatar_focus_active)
        self._external_avatar_focus_active = False
        self._external_avatar_focus_mode = ""
        if self._external_avatar_return_window is not None:
            self._external_avatar_return_window.hide()
        if raise_main or was_active or not self.isVisible():
            if self._external_avatar_main_window_was_fullscreen:
                self.showFullScreen()
            elif self._external_avatar_main_window_was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.raise_()
            self.activateWindow()
        if was_active:
            print("[QtGUI] External avatar focus exited.")

    def show_main_interface_from_external_avatar_focus(self):
        self.exit_external_avatar_focus(raise_main=True)

