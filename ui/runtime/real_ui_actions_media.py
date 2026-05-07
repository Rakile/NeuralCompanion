"""RealUiActionsMediaMixin extracted from real_ui_actions.py."""

from addons.audio_story_mode import real_ui_bridge as audio_story_real_ui_bridge
from addons.musetalk_avatar import real_ui_bridge as musetalk_real_ui_bridge


def configure_real_ui_actions_media_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiActionsMediaMixin:
    def _sync_audio_story_frontend_combo_to_controller(self):
            audio_story_real_ui_bridge.sync_frontend_combo_to_controller(self)

    def _sync_audio_story_frontend_slider_to_controller(self, value):
            audio_story_real_ui_bridge.sync_frontend_slider_to_controller(self, value)

    def _apply_audio_story_seek_from_frontend(self):
            audio_story_real_ui_bridge.apply_seek_from_frontend(self)

    def _set_frontend_musetalk_focus_button_text(self, text):
            musetalk_real_ui_bridge.set_focus_button_text(self, text)

    def _show_frontend_musetalk_preview(self):
            musetalk_real_ui_bridge.show_preview(self)

    def _enter_frontend_musetalk_avatar_focus(self):
            musetalk_real_ui_bridge.enter_avatar_focus(self)

    def _exit_frontend_musetalk_avatar_focus(self, *, raise_main=False):
            musetalk_real_ui_bridge.exit_avatar_focus(self, raise_main=raise_main)

    def _toggle_frontend_musetalk_avatar_focus(self):
            musetalk_real_ui_bridge.toggle_avatar_focus(self)

    def _show_frontend_main_interface_from_musetalk_focus(self):
            musetalk_real_ui_bridge.show_main_interface_from_focus(self)

    def _stop_frontend_musetalk_preview(self):
            musetalk_real_ui_bridge.stop_preview(self)

    def _show_frontend_visual_reply_dock(self):
            dock = self._ui_object("VisualReplyDock")
            if dock is None:
                return
            try:
                dock.show()
                dock.raise_()
            except Exception:
                pass
