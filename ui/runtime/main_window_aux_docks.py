"""Auxiliary dock and avatar-focus helpers for the runtime-backed main window."""

from pathlib import Path

from PySide6 import QtCore, QtWidgets

import shared_state
from addons.musetalk_avatar.preview_panel import QtMuseTalkPreviewPanel
from addons.musetalk_avatar.stage_window import QtMuseTalkStageWindow
from addons.visual_reply.controller import AddonVisualReplyPanel as QtVisualReplyPanel
from engine import RUNTIME_CONFIG
from ui.panels.avatar_windows import QtExternalAvatarReturnWindow
from ui.theme_support import app_theme_palette as _app_theme_palette

APP_ROOT = Path(__file__).resolve().parents[2]


class MainWindowAuxDocksMixin:
    def _build_preview_dock(self):
        self.preview_dock = QtWidgets.QDockWidget("MuseTalk Preview", self)
        self.preview_dock.setObjectName("MuseTalkPreviewDock")
        self.preview_dock.setAllowedAreas(
            QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
            | QtCore.Qt.LeftDockWidgetArea
        )
        self.preview_dock_container = QtWidgets.QWidget()
        self.preview_dock_container.setMinimumWidth(0)
        self.preview_dock_container.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.preview_dock_layout = QtWidgets.QVBoxLayout(self.preview_dock_container)
        self.preview_dock_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_dock_layout.setSpacing(0)
        self.embedded_musetalk_preview = QtMuseTalkPreviewPanel(
            theme_provider=_app_theme_palette,
            runtime_config=RUNTIME_CONFIG,
        )
        self.embedded_musetalk_preview.focusModeRequested.connect(self.toggle_musetalk_avatar_focus)
        self.embedded_musetalk_preview.showInterfaceRequested.connect(self.show_main_interface_from_musetalk_focus)
        self.preview_dock_layout.addWidget(self.embedded_musetalk_preview)
        self.preview_dock.setWidget(self.preview_dock_container)
        self._register_workspace_dock(self.preview_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.preview_dock)
        self.preview_dock.hide()
        self._ensure_musetalk_stage_window()
        if hasattr(self, "workspace_menu"):
            self.workspace_menu.insertAction(self.workspace_menu.actions()[-2], self.preview_dock.toggleViewAction())

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
        if self._musetalk_stage_window is None:
            self._musetalk_stage_window = QtMuseTalkStageWindow()
            self._musetalk_stage_window.closeRequested.connect(self.show_main_interface_from_musetalk_focus)
        return self._musetalk_stage_window

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
        panel = getattr(self, "embedded_musetalk_preview", None)
        if panel is None:
            return False
        target_layout = getattr(self, "preview_dock_layout", None)
        if host == "stage":
            stage_window = self._ensure_musetalk_stage_window()
            stage_window.attach_preview_widget(panel)
            return True
        if target_layout is None:
            return False
        old_parent = panel.parentWidget()
        if old_parent is not None and old_parent.layout() is not None:
            old_parent.layout().removeWidget(panel)
        panel.setParent(None)
        target_layout.addWidget(panel)
        panel.show()
        return True

    def _sync_musetalk_stage_window_geometry_from_preview(self):
        stage_window = self._ensure_musetalk_stage_window()
        source_rect = None
        preview_dock = getattr(self, "preview_dock", None)
        if preview_dock is not None:
            try:
                dock_rect = preview_dock.frameGeometry()
                if dock_rect.isValid() and dock_rect.width() > 120 and dock_rect.height() > 120:
                    source_rect = QtCore.QRect(dock_rect)
            except Exception:
                source_rect = None
        if source_rect is None:
            panel = getattr(self, "embedded_musetalk_preview", None)
            if panel is not None:
                try:
                    panel_size = panel.size()
                    if panel_size.width() <= 32 or panel_size.height() <= 32:
                        panel_size = panel.sizeHint()
                    top_left = panel.mapToGlobal(QtCore.QPoint(0, 0))
                    source_rect = QtCore.QRect(top_left, panel_size)
                except Exception:
                    source_rect = None
        if source_rect is None or source_rect.width() <= 32 or source_rect.height() <= 32:
            return False
        try:
            stage_window.showNormal()
        except Exception:
            pass
        stage_window.setGeometry(source_rect)
        return True

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

