from PySide6 import QtWidgets

from core.stt_runtime import WHISPER_LANGUAGE_OPTIONS, WHISPER_MODEL_SIZE_OPTIONS, normalize_whisper_language
from ui.runtime.engine_access import engine_module as _engine


def _runtime_config():
    return getattr(_engine(), "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


class BackendSttRuntimeMixin:
    """STT backend selection and Whisper language settings UI wiring."""

    def _populate_stt_backend_combo(self, selected_value=None):
        combo = getattr(self, "stt_backend_combo", None)
        if combo is None:
            return
        options = self._available_stt_backend_options()
        first_backend = str(options[0][1] if options else "none").strip().lower()
        desired = str(selected_value or _runtime_config().get("stt_backend", first_backend) or first_backend).strip().lower()
        combo.blockSignals(True)
        try:
            combo.clear()
            for label, backend_id in options:
                combo.addItem(label, backend_id)
            index = combo.findData(desired)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.setEnabled(bool(options))
        finally:
            combo.blockSignals(False)

    def _available_stt_backend_options(self):
        options = []
        try:
            specs = list(_engine().list_available_stt_backends() or [])
        except Exception:
            specs = []
        seen = set()
        for spec in specs:
            backend_id = str((spec or {}).get("id") or "").strip().lower()
            if not backend_id or backend_id in seen:
                continue
            label = str((spec or {}).get("label") or backend_id).strip() or backend_id
            options.append((label, backend_id))
            seen.add(backend_id)
        return options

    def _available_stt_backend_specs_by_id(self):
        specs_by_id = {}
        try:
            specs = list(_engine().list_available_stt_backends() or [])
        except Exception:
            specs = []
        for spec in specs:
            backend_id = str((spec or {}).get("id") or "").strip().lower()
            if backend_id:
                specs_by_id[backend_id] = dict(spec or {})
        return specs_by_id

    def _stt_backend_metadata(self, backend_id):
        spec = self._available_stt_backend_specs_by_id().get(str(backend_id or "").strip().lower(), {})
        return dict(spec.get("metadata") or {})

    def _stt_backend_settings_map(self):
        raw = _runtime_config().get("stt_backend_settings", {}) or {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(key or "").strip().lower(): dict(value or {})
            for key, value in raw.items()
            if str(key or "").strip() and isinstance(value, dict)
        }

    def _stt_backend_settings_for(self, backend_id):
        backend = str(backend_id or "").strip().lower() or "none"
        return dict(self._stt_backend_settings_map().get(backend, {}))

    def _set_stt_backend_settings_for(self, backend_id, updates):
        backend = str(backend_id or "").strip().lower() or "none"
        settings_map = self._stt_backend_settings_map()
        next_values = {}
        for key, value in dict(updates or {}).items():
            field = str(key or "").strip()
            if not field or value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
            next_values[field] = value
        if next_values and backend != "none":
            settings_map[backend] = next_values
        else:
            settings_map.pop(backend, None)
        try:
            _runtime_config()["stt_backend_settings"] = settings_map
        except Exception:
            pass
        _update_runtime_config("stt_backend_settings", settings_map)

    def _current_stt_editor_backend_value(self):
        backend = str(getattr(self, "_stt_runtime_editor_backend", "") or "").strip().lower()
        return backend or self._current_stt_backend_value()

    def _stt_backend_label_for(self, backend_id):
        backend = str(backend_id or "").strip().lower()
        combo = getattr(self, "stt_backend_combo", None)
        if combo is not None and hasattr(combo, "count"):
            try:
                count = int(combo.count())
            except Exception:
                count = 0
            for index in range(count):
                try:
                    data = combo.itemData(index)
                    value = str(data if data is not None else combo.itemText(index)).strip().lower()
                except Exception:
                    value = ""
                if value == backend:
                    try:
                        return str(combo.itemText(index) or backend).strip() or backend
                    except Exception:
                        return backend
        try:
            specs = self._available_stt_backend_specs_by_id()
            label = str((specs.get(backend, {}) or {}).get("label") or "").strip()
            if label:
                return label
        except Exception:
            pass
        return backend or "None"

    def _set_stt_backend_editor_value(self, backend_id, *, force=False):
        backend = str(backend_id or "").strip().lower() or self._current_stt_backend_value()
        previous = str(getattr(self, "_stt_runtime_editor_backend", "") or "").strip().lower()
        self._stt_runtime_editor_backend = backend
        if previous == backend and not force:
            return
        settings = self._stt_backend_settings_for(backend)
        model = str(settings.get("model_size") or self._stt_backend_default_model_value(backend)).strip()
        language = settings.get("language")
        if language is None:
            language = self._stt_backend_default_language_value(backend)
        language = normalize_whisper_language(language) or ""
        if hasattr(self, "stt_model_combo"):
            self._set_stt_combo_value(self.stt_model_combo, model)
        if hasattr(self, "stt_language_combo"):
            self._set_stt_combo_value(self.stt_language_combo, language)
        self._refresh_stt_runtime_summary()

    def _stt_backend_language_mode(self, backend_id):
        metadata = self._stt_backend_metadata(backend_id)
        return str(metadata.get("language_mode") or "").strip().lower()

    def _stt_backend_has_model_settings(self, backend_id):
        backend = str(backend_id or "").strip().lower()
        return bool(backend and backend != "none" and self._stt_backend_language_mode(backend) != "disabled")

    def _stt_backend_has_language_settings(self, backend_id):
        return self._stt_backend_language_mode(backend_id) == "multilingual"

    def _stt_backend_default_model_value(self, backend_id):
        metadata = self._stt_backend_metadata(backend_id)
        return str(metadata.get("default_model_size") or "tiny.en").strip() or "tiny.en"

    def _stt_backend_default_language_value(self, backend_id):
        metadata = self._stt_backend_metadata(backend_id)
        default_language = str(metadata.get("default_language") or "").strip()
        if default_language:
            return normalize_whisper_language(default_language) or ""
        if self._stt_backend_language_mode(backend_id) == "english":
            return "en"
        return ""

    def _set_stt_combo_value(self, combo, value):
        if combo is None:
            return False
        target = "" if value is None else str(value).strip()
        index = combo.findData(target)
        if index < 0:
            index = combo.findText(target)
        if index < 0:
            return False
        combo.blockSignals(True)
        try:
            combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)
        return True

    def _set_stt_editor_runtime_values(self, *, model_value=None, language_value=None):
        backend = self._current_stt_editor_backend_value()
        active_backend = self._current_stt_backend_value()
        settings = self._stt_backend_settings_for(backend)
        runtime_changed = False

        if model_value is not None and self._stt_backend_has_model_settings(backend):
            model = str(model_value or "").strip() or self._stt_backend_default_model_value(backend)
            settings["model_size"] = model
            if hasattr(self, "stt_model_combo"):
                self._set_stt_combo_value(self.stt_model_combo, model)
            if backend == active_backend:
                _update_runtime_config("stt_model_size", model)
                runtime_changed = True

        if language_value is not None:
            language = normalize_whisper_language(language_value)
            if self._stt_backend_has_language_settings(backend):
                language = language or ""
                settings["language"] = language
            else:
                language = self._stt_backend_default_language_value(backend)
            if hasattr(self, "stt_language_combo"):
                self._set_stt_combo_value(self.stt_language_combo, language)
            if backend == active_backend:
                _update_runtime_config("stt_language", language)
                runtime_changed = True

        if self._stt_backend_has_model_settings(backend):
            self._set_stt_backend_settings_for(backend, settings)
        self._refresh_stt_runtime_summary()
        if runtime_changed:
            self._reload_stt_runtime_if_available()
        self.save_session()

    def _populate_stt_model_combo(self, selected_value=None):
        combo = getattr(self, "stt_model_combo", None)
        if combo is None:
            return
        desired = str(selected_value or _runtime_config().get("stt_model_size", "tiny.en") or "tiny.en").strip()
        combo.blockSignals(True)
        try:
            combo.clear()
            for model_size in WHISPER_MODEL_SIZE_OPTIONS:
                combo.addItem(model_size, model_size)
            index = combo.findData(desired)
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _populate_stt_language_combo(self, selected_value=None):
        combo = getattr(self, "stt_language_combo", None)
        if combo is None:
            return
        normalized = normalize_whisper_language(selected_value if selected_value is not None else _runtime_config().get("stt_language", "en"))
        desired = normalized or ""
        combo.blockSignals(True)
        try:
            combo.clear()
            for label, code in WHISPER_LANGUAGE_OPTIONS:
                combo.addItem(label, code)
            index = combo.findData(desired)
            combo.setCurrentIndex(index if index >= 0 else 1)
        finally:
            combo.blockSignals(False)

    def _current_stt_backend_value(self):
        combo = getattr(self, "stt_backend_combo", None)
        if combo is not None and combo.currentData() is not None:
            return str(combo.currentData() or "none").strip().lower() or "none"
        return str(_runtime_config().get("stt_backend", "none") or "none").strip().lower()

    def _current_stt_editor_model_value(self):
        combo = getattr(self, "stt_model_combo", None)
        if combo is not None and combo.currentData() is not None:
            return str(combo.currentData() or "tiny.en").strip() or "tiny.en"
        return str(_runtime_config().get("stt_model_size", "tiny.en") or "tiny.en").strip()

    def _current_stt_editor_language_value(self):
        combo = getattr(self, "stt_language_combo", None)
        if combo is not None and combo.currentData() is not None:
            return normalize_whisper_language(combo.currentData()) or ""
        return normalize_whisper_language(_runtime_config().get("stt_language", "en")) or ""

    def _current_stt_model_value(self):
        backend = self._current_stt_backend_value()
        settings = self._stt_backend_settings_for(backend)
        model = settings.get("model_size")
        if model is None:
            model = _runtime_config().get("stt_model_size")
        return str(model or self._stt_backend_default_model_value(backend) or "tiny.en").strip()

    def _current_stt_language_value(self):
        backend = self._current_stt_backend_value()
        settings = self._stt_backend_settings_for(backend)
        language = settings.get("language")
        if language is None:
            language = _runtime_config().get("stt_language")
        if language is None:
            language = self._stt_backend_default_language_value(backend)
        return normalize_whisper_language(language) or ""

    def _first_voice_stt_backend_value(self):
        for _label, backend_id in self._available_stt_backend_options():
            backend = str(backend_id or "").strip().lower()
            if backend and backend != "none":
                return backend
        return "none"

    def _restore_stt_backend_for_voice_input(self):
        backend = self._current_stt_backend_value()
        if backend != "none":
            return backend
        fallback = self._first_voice_stt_backend_value()
        if fallback == "none":
            return backend
        combo = getattr(self, "stt_backend_combo", None)
        if combo is not None and hasattr(combo, "findData") and hasattr(combo, "setCurrentIndex"):
            try:
                index = combo.findData(fallback)
            except Exception:
                index = -1
            if index >= 0:
                combo.setCurrentIndex(index)
                backend = self._current_stt_backend_value()
        if backend == "none":
            _update_runtime_config("stt_backend", fallback)
            backend = fallback
        return backend

    def _refresh_stt_runtime_summary(self):
        section = getattr(self, "stt_runtime_section", None)
        if section is None:
            return
        backend_id = self._current_stt_backend_value()
        if backend_id == "none":
            section.setSummary("Microphone disabled")
            return
        backend = self._stt_backend_label_for(backend_id)
        model = self._current_stt_model_value()
        if self._stt_backend_has_language_settings(backend_id):
            language_value = self._current_stt_language_value()
            language = "Auto Detect"
            for label, code in WHISPER_LANGUAGE_OPTIONS:
                if str(code or "") == language_value:
                    language = str(label or language).strip() or language
                    break
            section.setSummary(f"{backend} / {model} / {language}")
        else:
            section.setSummary(f"{backend} / {model}")

    def _reload_stt_runtime_if_available(self):
        try:
            initializer = getattr(_engine(), "init_stt", None)
            if callable(initializer):
                initializer()
        except Exception as exc:
            try:
                self.append_console(f"⚠️ [STT] Runtime reload failed: {exc}")
            except Exception:
                pass

    def on_stt_backend_change(self, _choice=None):
        backend = self._current_stt_backend_value()
        _update_runtime_config("stt_backend", backend)
        self._stt_runtime_editor_backend = backend
        settings = self._stt_backend_settings_for(backend)
        model = str(settings.get("model_size") or self._stt_backend_default_model_value(backend)).strip()
        language = settings.get("language")
        if language is None:
            language = self._stt_backend_default_language_value(backend)
        language = normalize_whisper_language(language) or ""
        if self._stt_backend_has_model_settings(backend):
            if hasattr(self, "stt_model_combo"):
                self._set_stt_combo_value(self.stt_model_combo, model)
            _update_runtime_config("stt_model_size", model)
        if self._stt_backend_has_language_settings(backend):
            if hasattr(self, "stt_language_combo"):
                self._set_stt_combo_value(self.stt_language_combo, language)
            _update_runtime_config("stt_language", language)
        else:
            default_language = self._stt_backend_default_language_value(backend)
            if hasattr(self, "stt_language_combo"):
                self._set_stt_combo_value(self.stt_language_combo, default_language)
            _update_runtime_config("stt_language", default_language)
        self._refresh_stt_runtime_summary()
        refresh_setup = getattr(self, "_refresh_runtime_provider_setup_card", None)
        if callable(refresh_setup):
            refresh_setup("stt")
        self._reload_stt_runtime_if_available()
        self.save_session()

    def on_stt_model_change(self, _choice=None):
        language = self._current_stt_editor_language_value() if self._stt_backend_has_language_settings(self._current_stt_editor_backend_value()) else None
        self._set_stt_editor_runtime_values(model_value=self._current_stt_editor_model_value(), language_value=language)
        refresh_setup = getattr(self, "_refresh_runtime_provider_setup_card", None)
        if callable(refresh_setup):
            refresh_setup("stt")

    def on_stt_language_change(self, _choice=None):
        self._set_stt_editor_runtime_values(model_value=self._current_stt_editor_model_value(), language_value=self._current_stt_editor_language_value())
