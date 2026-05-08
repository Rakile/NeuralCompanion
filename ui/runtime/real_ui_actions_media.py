"""RealUiActionsMediaMixin extracted from real_ui_actions.py."""


def configure_real_ui_actions_media_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiActionsMediaMixin:
    def _invoke_realtime_addon_capability(self, addon_id, capability, payload=None, default=None):
            callback = getattr(self.backend, "_invoke_addon_capability", None)
            if not callable(callback):
                return default
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(addon_id, capability, payload, default=default)

    def _invoke_realtime_avatar_capability(self, provider_id, capability, payload=None, default=None):
            callback = getattr(self.backend, "_invoke_addon_service_capability", None)
            if not callable(callback):
                return default
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(
                "avatar_provider_registry",
                capability,
                payload,
                default=default,
                provider_id=provider_id,
            )

    def _visual_reply_addon_id_for_media(self):
            callback = getattr(self.backend, "_addon_id_for_ui_role", None)
            if callable(callback):
                return callback("visual_reply", fallback="nc.visual_reply")
            return "nc.visual_reply"

    def _audio_story_addon_id_for_media(self):
            callback = getattr(self.backend, "_addon_id_for_ui_role", None)
            if callable(callback):
                return callback("audio_story", fallback="")
            return ""

    def _sync_audio_story_frontend_combo_to_controller(self):
            self._invoke_realtime_addon_capability(self._audio_story_addon_id_for_media(), "real_ui.sync_frontend_combo")

    def _sync_audio_story_frontend_slider_to_controller(self, value):
            self._invoke_realtime_addon_capability(
                self._audio_story_addon_id_for_media(),
                "real_ui.sync_frontend_slider",
                {"value": value},
            )

    def _apply_audio_story_seek_from_frontend(self):
            self._invoke_realtime_addon_capability(self._audio_story_addon_id_for_media(), "real_ui.apply_seek")

    def _set_frontend_musetalk_focus_button_text(self, text):
            self._invoke_realtime_avatar_capability(
                "musetalk",
                "real_ui.set_focus_button_text",
                {"text": text},
            )

    def _show_frontend_musetalk_preview(self):
            self._invoke_realtime_avatar_capability("musetalk", "real_ui.show_preview")

    def _enter_frontend_musetalk_avatar_focus(self):
            self._invoke_realtime_avatar_capability("musetalk", "real_ui.enter_avatar_focus")

    def _exit_frontend_musetalk_avatar_focus(self, *, raise_main=False):
            self._invoke_realtime_avatar_capability(
                "musetalk",
                "real_ui.exit_avatar_focus",
                {"raise_main": raise_main},
            )

    def _toggle_frontend_musetalk_avatar_focus(self):
            self._invoke_realtime_avatar_capability("musetalk", "real_ui.toggle_avatar_focus")

    def _show_frontend_main_interface_from_musetalk_focus(self):
            self._invoke_realtime_avatar_capability("musetalk", "real_ui.show_main_interface_from_focus")

    def _stop_frontend_musetalk_preview(self):
            self._invoke_realtime_avatar_capability("musetalk", "real_ui.stop_preview")

    def _show_frontend_visual_reply_dock(self):
            self._invoke_realtime_addon_capability(
                self._visual_reply_addon_id_for_media(),
                "real_ui.show_dock",
            )
