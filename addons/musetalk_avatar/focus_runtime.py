from addons.vseeface_avatar.hand_doctor_dialog import HandDoctorDialog


class BackendMuseTalkPreviewRuntimeMixin:
    """Host-facing MuseTalk preview, avatar focus, and hand-debugger controls."""

    def open_hand_debugger(self):
        dialog = HandDoctorDialog(self, self)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.hand_doctor_dialog = dialog

    def show_musetalk_preview(self):
        if self._current_avatar_mode_value() != "musetalk":
            return
        if self._musetalk_avatar_focus_active:
            stage_window = self._ensure_musetalk_stage_window()
            self._attach_musetalk_preview_to_host("stage")
            stage_window.show()
            stage_window.raise_()
            stage_window.activateWindow()
        else:
            self._attach_musetalk_preview_to_host("dock")
            self.preview_dock.show()
            self.preview_dock.raise_()
        self.embedded_musetalk_preview.show()
        if hasattr(self.embedded_musetalk_preview, "set_focus_mode"):
            self.embedded_musetalk_preview.set_focus_mode(bool(self._musetalk_avatar_focus_active))
        if self.active_tutorial_overlay is not None:
            try:
                self.active_tutorial_overlay.raise_()
                self.active_tutorial_overlay.panel.raise_()
            except Exception:
                pass
        print("[QtGUI] MuseTalk preview dock shown.")

    def enter_musetalk_avatar_focus(self):
        if self._current_avatar_mode_value() != "musetalk":
            return
        self._musetalk_avatar_focus_active = True
        self._musetalk_main_window_was_maximized = bool(self.isMaximized())
        self._musetalk_main_window_was_fullscreen = bool(self.isFullScreen())
        if hasattr(self, "btn_musetalk_avatar_focus"):
            self.btn_musetalk_avatar_focus.setText("Exit Avatar Focus")
        if hasattr(self, "embedded_musetalk_preview"):
            self.embedded_musetalk_preview.set_focus_mode(True)
        self._attach_musetalk_preview_to_host("stage")
        if hasattr(self, "preview_dock"):
            self.preview_dock.hide()
        stage_window = self._ensure_musetalk_stage_window()
        self._sync_musetalk_stage_window_geometry_from_preview()
        stage_window.show()
        stage_window.raise_()
        stage_window.activateWindow()
        self._hide_main_preserving_pinned_floating_docks()
        print("[QtGUI] MuseTalk avatar focus entered.")

    def exit_musetalk_avatar_focus(self, *, raise_main=False):
        was_active = bool(self._musetalk_avatar_focus_active)
        self._musetalk_avatar_focus_active = False
        if hasattr(self, "btn_musetalk_avatar_focus"):
            self.btn_musetalk_avatar_focus.setText("Avatar Focus")
        if hasattr(self, "embedded_musetalk_preview"):
            self.embedded_musetalk_preview.set_focus_mode(False)
        self._attach_musetalk_preview_to_host("dock")
        if hasattr(self, "_musetalk_stage_window") and self._musetalk_stage_window is not None:
            self._musetalk_stage_window.allow_internal_close(True)
            self._musetalk_stage_window.hide()
            self._musetalk_stage_window.allow_internal_close(False)
        if hasattr(self, "preview_dock"):
            self.preview_dock.show()
        if hasattr(self, "visual_reply_dock"):
            try:
                self.tabifyDockWidget(self.preview_dock, self.visual_reply_dock)
            except Exception:
                pass
        if raise_main or was_active or not self.isVisible():
            if self._musetalk_main_window_was_fullscreen:
                self.showFullScreen()
            elif self._musetalk_main_window_was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.raise_()
            self.activateWindow()
        if was_active:
            print("[QtGUI] MuseTalk avatar focus exited.")

    def toggle_musetalk_avatar_focus(self):
        if self._musetalk_avatar_focus_active:
            self.exit_musetalk_avatar_focus(raise_main=True)
        else:
            self.enter_musetalk_avatar_focus()

    def show_main_interface_from_musetalk_focus(self):
        self.exit_musetalk_avatar_focus(raise_main=True)

    def stop_musetalk_preview(self):
        self.exit_musetalk_avatar_focus(raise_main=False)
        if hasattr(self, "preview_dock"):
            self.preview_dock.hide()
        if hasattr(self, "_musetalk_stage_window") and self._musetalk_stage_window is not None:
            self._musetalk_stage_window.allow_internal_close(True)
            self._musetalk_stage_window.hide()
            self._musetalk_stage_window.allow_internal_close(False)
        if hasattr(self, "embedded_musetalk_preview"):
            self.embedded_musetalk_preview.reset_preview()
