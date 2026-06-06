from PySide6 import QtCore

from core import avatar_runtime


from ui.runtime.engine_access import engine_module as _engine


def _runtime_config():
    return getattr(_engine(), "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


class BackendAvatarRuntimeMixin:
    """Avatar provider selection and avatar-editing runtime controls."""

    _MUSETALK_VRAM_TOOLTIP = (
        "MuseTalk-only memory profile. Quality uses larger render batches and keeps MuseTalk's Whisper encoder on GPU; "
        "Balanced lowers batch size and enables VAE slicing; Low and Very Low use smaller batches and move MuseTalk's "
        "internal Whisper encoder to CPU. Main STT Whisper still uses GPU when available."
    )

    def _avatar_provider_options(self):
        providers = []
        for provider in avatar_runtime.list_providers():
            summary = provider.to_summary()
            provider_id = str(summary.get("id") or "").strip().lower()
            if provider_id:
                providers.append(summary)
        if providers or getattr(self, "_addon_manager", None) is not None:
            return sorted(
                providers,
                key=lambda item: (int(item.get("order", 1000) or 1000), str(item.get("label", "")).lower()),
            )
        legacy = {
            "vseeface": {"id": "vseeface", "label": "VSeeFace", "order": 100},
            "musetalk": {"id": "musetalk", "label": "MuseTalk", "order": 200},
            "vam": {"id": "vam", "label": "VaM", "order": 300},
            "none": {"id": "none", "label": "None", "order": 900},
        }
        return sorted(
            legacy.values(),
            key=lambda item: (int(item.get("order", 1000) or 1000), str(item.get("label", "")).lower()),
        )

    def _avatar_mode_value_from_label(self, label):
        raw = str(label or "").strip()
        legacy = {
            "vseeface": "vseeface",
            "musetalk": "musetalk",
            "vam": "vam",
            "none": "none",
        }
        return legacy.get(raw.lower(), raw.lower())

    def _current_avatar_mode_value(self):
        combo = getattr(self, "engine_combo", None)
        if combo is None:
            return str(_runtime_config().get("avatar_mode", "vseeface") or "vseeface").strip().lower()
        data = combo.currentData()
        if data:
            return str(data).strip().lower()
        return self._avatar_mode_value_from_label(combo.currentText())

    def _refresh_musetalk_runtime_visibility(self):
        mode = self._current_avatar_mode_value()
        visible = mode == "musetalk"
        for name in (
            "musetalk_vram_label",
            "musetalk_vram_combo",
            "musetalk_loop_fade_label",
            "musetalk_loop_fade_spin",
            "musetalk_frame_cache_label",
            "musetalk_use_frame_cache_checkbox",
            "musetalk_avatar_label",
            "musetalk_avatar_pack_row_widget",
            "musetalk_vram_hint",
        ):
            widget = getattr(self, name, None)
            if widget is not None and hasattr(widget, "setVisible"):
                widget.setVisible(visible)
        for name in ("musetalk_vram_label", "musetalk_vram_combo", "musetalk_vram_hint"):
            widget = getattr(self, name, None)
            if widget is not None and hasattr(widget, "setToolTip"):
                widget.setToolTip(self._MUSETALK_VRAM_TOOLTIP)
        scenic_visible = mode == "scenic"
        for name in (
            "scenic_pack_label",
            "scenic_pack_combo",
            "btn_scenic_pack_refresh",
            "scenic_pack_row_widget",
        ):
            widget = getattr(self, name, None)
            if widget is not None and hasattr(widget, "setVisible"):
                widget.setVisible(scenic_visible)

    def _refresh_musetalk_vram_visibility(self):
        self._refresh_musetalk_runtime_visibility()

    def _apply_avatar_provider_ui_selection(self, selected_provider_id):
        selected = str(selected_provider_id or "").strip().lower()
        for provider in self._avatar_provider_options():
            provider_id = str(provider.get("id") or "").strip().lower()
            if not provider_id:
                continue
            active = bool(provider_id and provider_id == selected)
            if active:
                self._invoke_addon_service_capability(
                    "avatar_provider_registry",
                    "real_ui.apply_provider_selected_defaults",
                    {"backend": self, "active": True},
                    provider_id=provider_id,
                )
            self._invoke_addon_service_capability(
                "avatar_provider_registry",
                "real_ui.set_provider_controls_enabled",
                {"backend": self, "enabled": active},
                provider_id=provider_id,
            )

    def refresh_avatar_engine_options(self, selected_provider_id=None):
        combo = getattr(self, "engine_combo", None)
        if combo is None:
            return
        selected = str(
            selected_provider_id
            or self._current_avatar_mode_value()
            or _runtime_config().get("avatar_mode", "vseeface")
            or "vseeface"
        ).strip().lower()
        combo.blockSignals(True)
        try:
            combo.clear()
            for provider in self._avatar_provider_options():
                provider_id = str(provider.get("id") or "").strip().lower()
                label = str(provider.get("label") or provider_id).strip() or provider_id
                combo.addItem(label, provider_id)
            index = combo.findData(selected)
            if index < 0:
                index = combo.findText(selected, QtCore.Qt.MatchFixedString)
            if index < 0 and combo.count() > 0:
                index = 0
            if index >= 0:
                combo.setCurrentIndex(index)
                provider_id = str(combo.currentData() or "").strip().lower()
                if provider_id:
                    _update_runtime_config("avatar_mode", provider_id)
        finally:
            combo.blockSignals(False)
            self._refresh_musetalk_runtime_visibility()

    def on_engine_change(self, choice):
        mode = self._current_avatar_mode_value()
        _update_runtime_config("avatar_mode", mode)
        self._apply_avatar_provider_ui_selection(mode)
        self._refresh_musetalk_runtime_visibility()
        self._advisor_context_manual_override = False
        self.emit_tutorial_event("ui_changed", {"field": "avatar_mode", "value": choice})
        self.update_model_budget_hint()
        print(f"[QtGUI] Avatar Engine set to {choice}.")
        self.save_session()

    def toggle_live_sync(self, checked):
        engine = _engine()
        if self._current_avatar_mode_value() != "vseeface":
            return
        engine.FORCE_EDIT_MODE = not checked
        status = "LIVE (Brain Controlled)" if checked else "EDITING (Manual)"
        print(f"[QtGUI] Body Mode: {status}")

    def on_emotion_change(self, choice):
        engine = _engine()
        avatar_profile = getattr(engine, "AVATAR_PROFILE", {})
        engine.EDIT_EMOTION = str(choice or "").lower()
        current_data = avatar_profile.get(engine.EDIT_EMOTION, avatar_profile.get("neutral", {}))
        for key, slider in self.pose_sliders.items():
            if self._qt_object_alive(slider):
                slider.set_value(current_data.get(key, 0.0))
        print(f"[QtGUI] Editing Pose: {choice}")
