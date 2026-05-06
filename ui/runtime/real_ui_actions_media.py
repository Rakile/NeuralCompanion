"""RealUiActionsMediaMixin extracted from real_ui_actions.py."""

from PySide6 import QtCore


def configure_real_ui_actions_media_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiActionsMediaMixin:
    def _sync_audio_story_frontend_combo_to_controller(self):
            controller = self._audio_story_controller()
            frontend_combo = self._ui_object("audio_story_playback_combo")
            backend_combo = getattr(controller, "audio_story_playback_mode_combo", None) if controller is not None else None
            if frontend_combo is None or backend_combo is None:
                return
            self._sync_combo_like_widget(frontend_combo, backend_combo)
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _sync_audio_story_frontend_slider_to_controller(self, value):
            controller = self._audio_story_controller()
            backend_slider = getattr(controller, "audio_story_transcribe_seconds_slider", None) if controller is not None else None
            if backend_slider is None or not hasattr(backend_slider, "setValue"):
                return
            try:
                backend_slider.setValue(int(value))
            except Exception:
                return
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _apply_audio_story_seek_from_frontend(self):
            controller = self._audio_story_controller()
            frontend_slider = self._ui_object("audio_story_seek_slider")
            backend_slider = getattr(controller, "audio_story_position_slider", None) if controller is not None else None
            if frontend_slider is None or backend_slider is None or not hasattr(frontend_slider, "value") or not hasattr(backend_slider, "setValue"):
                return
            try:
                backend_slider.setValue(int(frontend_slider.value()))
            except Exception:
                return
            callback = getattr(controller, "_on_slider_released", None)
            if callable(callback):
                try:
                    callback()
                finally:
                    QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _set_frontend_musetalk_focus_button_text(self, text):
            focus_button = self._ui_object("btn_musetalk_avatar_focus")
            if focus_button is not None and hasattr(focus_button, "setText"):
                try:
                    focus_button.setText(str(text or "Avatar Focus"))
                except Exception:
                    pass

    def _show_frontend_musetalk_preview(self):
            if self.backend._current_avatar_mode_value() != "musetalk":
                return
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if bool(getattr(self.backend, "_musetalk_avatar_focus_active", False)):
                stage_window = self.backend._ensure_musetalk_stage_window()
                self.backend._attach_musetalk_preview_to_host("stage")
                stage_window.show()
                stage_window.raise_()
                stage_window.activateWindow()
            else:
                self.backend._attach_musetalk_preview_to_host("dock")
                preview_dock = self._ui_object("PreviewDock")
                if preview_dock is not None:
                    preview_dock.show()
                    preview_dock.raise_()
            if panel is not None:
                panel.show()
                if hasattr(panel, "set_focus_mode"):
                    panel.set_focus_mode(bool(getattr(self.backend, "_musetalk_avatar_focus_active", False)))
            self._refresh_musetalk_preview_frontend()

    def _enter_frontend_musetalk_avatar_focus(self):
            if self.backend._current_avatar_mode_value() != "musetalk":
                return
            self.backend._musetalk_avatar_focus_active = True
            self.backend._musetalk_main_window_was_maximized = bool(self.window.isMaximized())
            self.backend._musetalk_main_window_was_fullscreen = bool(self.window.isFullScreen())
            self._set_frontend_musetalk_focus_button_text("Exit Avatar Focus")
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if panel is not None and hasattr(panel, "set_focus_mode"):
                panel.set_focus_mode(True)
            self.backend._attach_musetalk_preview_to_host("stage")
            preview_dock = self._ui_object("PreviewDock")
            if preview_dock is not None:
                preview_dock.hide()
            stage_window = self.backend._ensure_musetalk_stage_window()
            self.backend._sync_musetalk_stage_window_geometry_from_preview()
            stage_window.show()
            stage_window.raise_()
            stage_window.activateWindow()
            self._hide_frontend_main_preserving_pinned_floating_docks()
            self._refresh_musetalk_preview_frontend()

    def _exit_frontend_musetalk_avatar_focus(self, *, raise_main=False):
            was_active = bool(getattr(self.backend, "_musetalk_avatar_focus_active", False))
            self.backend._musetalk_avatar_focus_active = False
            self._set_frontend_musetalk_focus_button_text("Avatar Focus")
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if panel is not None and hasattr(panel, "set_focus_mode"):
                panel.set_focus_mode(False)
            self.backend._attach_musetalk_preview_to_host("dock")
            stage_window = getattr(self.backend, "_musetalk_stage_window", None)
            if stage_window is not None:
                try:
                    stage_window.allow_internal_close(True)
                    stage_window.hide()
                    stage_window.allow_internal_close(False)
                except Exception:
                    pass
            preview_dock = self._ui_object("PreviewDock")
            if preview_dock is not None:
                preview_dock.show()
            visual_reply_dock = self._ui_object("VisualReplyDock")
            if preview_dock is not None and visual_reply_dock is not None:
                try:
                    self.window.tabifyDockWidget(preview_dock, visual_reply_dock)
                except Exception:
                    pass
            if raise_main or was_active or not self.window.isVisible():
                if bool(getattr(self.backend, "_musetalk_main_window_was_fullscreen", False)):
                    self.window.showFullScreen()
                elif bool(getattr(self.backend, "_musetalk_main_window_was_maximized", False)):
                    self.window.showMaximized()
                else:
                    self.window.showNormal()
                self.window.raise_()
                self.window.activateWindow()
            self._refresh_musetalk_preview_frontend()

    def _toggle_frontend_musetalk_avatar_focus(self):
            if bool(getattr(self.backend, "_musetalk_avatar_focus_active", False)):
                self._exit_frontend_musetalk_avatar_focus(raise_main=True)
            else:
                self._enter_frontend_musetalk_avatar_focus()

    def _show_frontend_main_interface_from_musetalk_focus(self):
            self._exit_frontend_musetalk_avatar_focus(raise_main=True)

    def _stop_frontend_musetalk_preview(self):
            self._exit_frontend_musetalk_avatar_focus(raise_main=False)
            preview_dock = self._ui_object("PreviewDock")
            if preview_dock is not None:
                preview_dock.hide()
            stage_window = getattr(self.backend, "_musetalk_stage_window", None)
            if stage_window is not None:
                try:
                    stage_window.allow_internal_close(True)
                    stage_window.hide()
                    stage_window.allow_internal_close(False)
                except Exception:
                    pass
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if panel is not None and hasattr(panel, "reset_preview"):
                panel.reset_preview()
            self._refresh_musetalk_preview_frontend()

    def _show_frontend_visual_reply_dock(self):
            dock = self._ui_object("VisualReplyDock")
            if dock is None:
                return
            try:
                dock.show()
                dock.raise_()
            except Exception:
                pass
