import os

from PySide6 import QtCore, QtWidgets


from ui.runtime.engine_access import engine_module as _engine


def _runtime_config():
    return getattr(_engine(), "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


class BackendTtsRuntimeMixin:
    """TTS backend selection and TTS runtime settings UI wiring."""

    _TTS_VOICE_REFERENCE_CONFIG_BY_BACKEND = {
        "chatterbox": "tts_use_cloned_voice",
        "chatterbox_multilingual": "chatterbox_multilingual_use_cloned_voice",
        "pockettts": "pocket_tts_use_cloned_voice",
        "pockettts_multilingual": "pocket_tts_multilingual_use_cloned_voice",
    }
    _TTS_VOICE_REFERENCE_CONFIG_KEYS = tuple(_TTS_VOICE_REFERENCE_CONFIG_BY_BACKEND.values())
    _TTS_VOICE_REFERENCE_CHECKBOX_NAMES = (
        "chatterbox_use_cloned_voice_checkbox",
        "chatterbox_multilingual_use_cloned_voice_checkbox",
        "pockettts_use_cloned_voice_checkbox",
        "pockettts_multilingual_use_cloned_voice_checkbox",
    )

    def _toggle_pocket_tts_advanced(self, checked):
        if hasattr(self, "pocket_tts_advanced_group"):
            self.pocket_tts_advanced_group.setVisible(bool(checked))
        if hasattr(self, "pocket_tts_advanced_toggle"):
            self.pocket_tts_advanced_toggle.setText(
                "Hide Advanced PocketTTS Override" if checked else "Show Advanced PocketTTS Override"
            )

    def _sync_tts_runtime_fields_height(self):
        try:
            tabs = getattr(self, "tts_runtime_addon_tabs", None)
            tts_box = getattr(self, "tts_runtime_box", None)

            if not tabs or not tts_box:
                return

            # Strip hardcoded Designer minimums so the active backend tab owns height.
            tts_box.setMinimumHeight(0)
            tabs.setMinimumHeight(0)

            current_idx = tabs.currentIndex()
            active_page = None

            for i in range(tabs.count()):
                page = tabs.widget(i)
                if not page:
                    continue

                policy = page.sizePolicy()
                if i == current_idx:
                    active_page = page
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
                    policy.setRetainSizeWhenHidden(False)
                    page.setMinimumHeight(0)
                    if page.layout():
                        page.layout().setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
                else:
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Ignored)
                    policy.setRetainSizeWhenHidden(False)

                page.setSizePolicy(policy)

            if active_page:
                if active_page.layout():
                    active_page.layout().invalidate()
                    active_page.layout().activate()
                true_height = active_page.sizeHint().height()
                tabs.setMaximumHeight(true_height + 100)

            current = tabs.parentWidget()
            while current and current.objectName() != "host_settings_host_tab":
                if current.maximumHeight() < 16777215:
                    current.setMaximumHeight(16777215)
                layout = current.layout()
                if layout and hasattr(layout, "sizeConstraint"):
                    if layout.sizeConstraint() == QtWidgets.QLayout.SetMinAndMaxSize:
                        layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
                current = current.parentWidget()

            policy = tts_box.sizePolicy()
            policy.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
            tts_box.setSizePolicy(policy)
            if tts_box.layout():
                tts_box.layout().setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)

            current = tabs
            while current:
                if current.layout():
                    current.layout().invalidate()
                    current.layout().activate()
                if hasattr(current, "updateGeometry"):
                    current.updateGeometry()
                current = current.parentWidget()
            callback = getattr(self, "frontend_layout_resync_callback", None)
            if callable(callback):
                callback()
        except Exception:
            pass

    def _refresh_tts_runtime_summary(self):
        if not hasattr(self, "tts_runtime_section"):
            return
        backend_value = self._current_tts_backend_value()
        backend_label = self._tts_backend_label_from_value(backend_value)
        if self._tts_backend_supports_voice_reference(backend_value):
            voice_name = self._current_voice_file_value()
            self.tts_runtime_section.setSummary(f"{backend_label} / {voice_name}" if voice_name else f"{backend_label} / Built-in voice")
        else:
            self.tts_runtime_section.setSummary(backend_label)

    def _current_voice_file_value(self):
        voice_name = str(self.voice_combo.currentText() if hasattr(self, "voice_combo") else "" or "").strip()
        if not voice_name or voice_name == "No .wav found":
            return ""
        return voice_name

    def _refresh_tts_runtime_card(self, activate_tab=True):
        if not hasattr(self, "tts_runtime_addon_tabs"):
            return

        backend = self._current_tts_backend_value()
        backend_label = self._tts_backend_label_from_value(backend)
        tab_index = self._find_tts_runtime_tab_index(backend)
        if activate_tab and tab_index is not None and 0 <= int(tab_index) < self.tts_runtime_addon_tabs.count():
            self.tts_runtime_addon_tabs.blockSignals(True)
            self.tts_runtime_addon_tabs.setCurrentIndex(int(tab_index))
            self.tts_runtime_addon_tabs.blockSignals(False)
        if hasattr(self, "tts_runtime_hint_label"):
            if backend in self._tts_runtime_tab_index_by_backend:
                self.tts_runtime_hint_label.setText(f"{backend_label} backend settings are shown in the addon tab below.")
            else:
                self.tts_runtime_hint_label.setText(
                    f"Backend '{backend_label}' does not have a mounted addon tab right now; core fallback settings may be in use."
                )
        self._refresh_tts_runtime_summary()
        self._sync_use_wav_file_checkbox()
        if not callable(getattr(self, "frontend_layout_resync_callback", None)):
            QtCore.QTimer.singleShot(0, self._sync_tts_runtime_fields_height)

    def _find_tts_runtime_tab_index(self, backend):
        if not hasattr(self, "tts_runtime_addon_tabs"):
            return None
        backend = str(backend or "").strip().lower()
        if not backend:
            return None
        cached = self._tts_runtime_tab_index_by_backend.get(backend)
        if cached is not None and 0 <= int(cached) < self.tts_runtime_addon_tabs.count():
            current_widget = self.tts_runtime_addon_tabs.widget(int(cached))
            try:
                cached_backend_id = str(current_widget.property("backend_id") or "").strip().lower()
            except Exception:
                cached_backend_id = ""
            if cached_backend_id == backend:
                return int(cached)
        for index in range(self.tts_runtime_addon_tabs.count()):
            tab_widget = self.tts_runtime_addon_tabs.widget(index)
            backend_id = ""
            try:
                backend_id = str(tab_widget.property("backend_id") or "").strip().lower()
            except Exception:
                backend_id = ""
            candidates = {
                backend_id,
                str(tab_widget.objectName() or "").strip().lower(),
            }
            if backend in candidates:
                self._tts_runtime_tab_index_by_backend[backend] = index
                return index
        return None

    def _available_tts_backend_options(self):
        options = []
        try:
            backend_specs = list(_engine().list_available_tts_backends() or [])
        except Exception:
            backend_specs = []
        seen = set()
        for spec in backend_specs:
            backend_id = str(spec.get("id") or "").strip().lower()
            if not backend_id or backend_id in seen:
                continue
            label = str(spec.get("label") or backend_id or "").strip() or backend_id
            options.append((label, backend_id))
            seen.add(backend_id)
        return options

    def _available_tts_backend_specs_by_id(self):
        specs = {}
        try:
            backend_specs = list(_engine().list_available_tts_backends() or [])
        except Exception:
            backend_specs = []
        for spec in backend_specs:
            backend_id = str((spec or {}).get("id") or "").strip().lower()
            if backend_id:
                specs[backend_id] = dict(spec or {})
        return specs

    def _tts_backend_metadata(self, backend_id):
        backend_id = str(backend_id or "").strip().lower()
        spec = self._available_tts_backend_specs_by_id().get(backend_id, {})
        return dict(spec.get("metadata") or {})

    def _tts_backend_supports_voice_reference(self, backend_id):
        metadata = self._tts_backend_metadata(backend_id)
        if "supports_voice_reference" in metadata:
            return bool(metadata.get("supports_voice_reference"))
        return False

    def _preferred_tts_backend_for_stream_mode(self, enabled):
        desired_key = "preferred_for_streaming" if enabled else "preferred_for_non_streaming"
        options = self._available_tts_backend_options()
        for _label, backend_id in options:
            metadata = self._tts_backend_metadata(backend_id)
            if bool(metadata.get(desired_key, False)):
                return str(backend_id or "").strip().lower()
        return ""

    def _populate_tts_backend_combo(self, selected_value=None):
        combo = getattr(self, "tts_backend_combo", None)
        if combo is None:
            return
        options = self._available_tts_backend_options()
        first_backend = str(options[0][1] if options else "none").strip().lower() or "none"
        desired = str(
            selected_value
            or self._current_tts_backend_value()
            or _runtime_config().get("tts_backend", first_backend)
            or first_backend
        ).strip().lower()
        combo.blockSignals(True)
        try:
            combo.clear()
            for label, backend_id in options:
                combo.addItem(label, backend_id)
            index = combo.findData(desired)
            if index < 0 and combo.count() > 0:
                index = 0
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _current_tts_backend_value(self):
        combo = getattr(self, "tts_backend_combo", None)
        if combo is not None:
            data = combo.currentData()
            if data is not None and str(data).strip():
                return str(data).strip().lower()
            text = str(combo.currentText() or "").strip()
            if text:
                return self._tts_backend_value_from_label(text)
        configured = str(_runtime_config().get("tts_backend", "") or "").strip().lower()
        if configured:
            return configured
        options = self._available_tts_backend_options()
        if options:
            return str(options[0][1] or "").strip().lower()
        return "none"

    def _tts_backend_value_from_label(self, label):
        normalized = str(label or "").strip().lower()
        for display_label, backend_id in self._available_tts_backend_options():
            if normalized == str(display_label or "").strip().lower():
                return str(backend_id or "").strip().lower()
            if normalized == str(backend_id or "").strip().lower():
                return str(backend_id or "").strip().lower()
        return normalized

    def _tts_backend_label_from_value(self, value):
        normalized = str(value or "").strip().lower()
        for display_label, backend_id in self._available_tts_backend_options():
            if normalized == str(backend_id or "").strip().lower():
                return str(display_label or backend_id).strip()
        return str(value or "").strip() or "External TTS"

    def on_tts_seed_changed(self, value):
        _update_runtime_config("tts_seed", max(0, int(value or 0)))
        self.save_session()

    def on_tts_temperature_changed(self, value):
        _update_runtime_config("tts_temperature", max(0.05, float(value or 0.8)))
        self.save_session()

    def on_tts_top_p_changed(self, value):
        _update_runtime_config("tts_top_p", max(0.0, min(1.0, float(value or 0.9))))
        self.save_session()

    def on_tts_top_k_changed(self, value):
        _update_runtime_config("tts_top_k", max(0, int(value or 0)))
        self.save_session()

    def on_tts_repeat_penalty_changed(self, value):
        _update_runtime_config("tts_repeat_penalty", max(1.0, float(value or 1.2)))
        self.save_session()

    def on_tts_min_p_changed(self, value):
        _update_runtime_config("tts_min_p", max(0.0, min(1.0, float(value or 0.0))))
        self.save_session()

    def on_tts_normalize_loudness_changed(self, checked):
        _update_runtime_config("tts_normalize_loudness", bool(checked))
        self.save_session()

    def _current_tts_voice_reference_config_key(self):
        backend = self._current_tts_backend_value()
        return self._TTS_VOICE_REFERENCE_CONFIG_BY_BACKEND.get(str(backend or "").strip().lower(), "tts_use_cloned_voice")

    def _sync_use_wav_file_checkbox(self, checked=None):
        checkbox = getattr(self, "use_wav_file_checkbox", None)
        if checkbox is None or not hasattr(checkbox, "setChecked"):
            return
        if checked is None:
            config = _runtime_config()
            checked = bool(config.get(self._current_tts_voice_reference_config_key(), True))
        was_blocked = bool(checkbox.blockSignals(True)) if hasattr(checkbox, "blockSignals") else False
        try:
            checkbox.setChecked(bool(checked))
        finally:
            if hasattr(checkbox, "blockSignals"):
                checkbox.blockSignals(was_blocked)

    def _sync_tts_use_cloned_voice_checkboxes(self, checked):
        for object_name in self._TTS_VOICE_REFERENCE_CHECKBOX_NAMES:
            widget = getattr(self, object_name, None)
            if widget is None and hasattr(self, "findChild"):
                widget = self.findChild(QtWidgets.QCheckBox, object_name)
            if widget is None or not hasattr(widget, "setChecked"):
                continue
            was_blocked = bool(widget.blockSignals(True)) if hasattr(widget, "blockSignals") else False
            try:
                widget.setChecked(bool(checked))
            finally:
                if hasattr(widget, "blockSignals"):
                    widget.blockSignals(was_blocked)

    def on_use_wav_file_changed(self, checked):
        value = bool(checked)
        for key in self._TTS_VOICE_REFERENCE_CONFIG_KEYS:
            _update_runtime_config(key, value)
        self._sync_use_wav_file_checkbox(value)
        self._sync_tts_use_cloned_voice_checkboxes(value)
        self._refresh_tts_runtime_summary()
        self.save_session()

    def on_voice_changed(self, voice_name):
        if voice_name and voice_name != "No .wav found":
            _update_runtime_config("voice_path", os.path.join("voices", voice_name))
        else:
            _update_runtime_config("voice_path", "")
        self._refresh_tts_runtime_summary()

    def browse_pocket_tts_python(self):
        self._invoke_addon_service_capability(
            "tts_backend_service",
            "ui.browse_python",
            {"backend": self},
            default=None,
            backend_id="pockettts",
        )

    def on_pocket_tts_python_changed(self):
        self._invoke_addon_service_capability(
            "tts_backend_service",
            "ui.apply_python_changed",
            {"backend": self},
            default=None,
            backend_id="pockettts",
        )

    def _ensure_pocket_tts_python_path(self):
        return self._invoke_addon_service_capability(
            "tts_backend_service",
            "ui.ensure_python_path",
            {"backend": self},
            default="",
            backend_id="pockettts",
        )

    def reset_pocket_tts_python_to_default(self):
        self._invoke_addon_service_capability(
            "tts_backend_service",
            "ui.reset_python_to_default",
            {"backend": self},
            default=None,
            backend_id="pockettts",
        )

    def on_tts_backend_change(self, choice):
        backend = self._current_tts_backend_value()
        _update_runtime_config("tts_backend", backend)
        self._invoke_addon_service_capability(
            "tts_backend_service",
            "ui.ensure_python_path",
            {"backend": self},
            default=None,
            backend_id=backend,
        )
        engine_running = bool(getattr(self, "thread", None) and self.thread.is_alive())
        if engine_running:
            try:
                if hasattr(_engine(), "init_tts"):
                    _engine().init_tts()
            except Exception as exc:
                print(f"⚠️ [TTS] Failed to reload backend '{backend}': {exc}")
        self._sync_use_wav_file_checkbox()
        self._refresh_tts_runtime_card(activate_tab=not bool(getattr(self, "_restoring_preset", False)))
        self._refresh_tts_runtime_summary()
        refresh_setup = getattr(self, "_refresh_runtime_provider_setup_card", None)
        if callable(refresh_setup):
            refresh_setup("tts")
        self._advisor_context_manual_override = False
        self.emit_tutorial_event("ui_changed", {"field": "tts_backend", "value": backend})
        self.update_model_budget_hint()
        self.save_session()
