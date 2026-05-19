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

    def _current_stt_model_value(self):
        combo = getattr(self, "stt_model_combo", None)
        if combo is not None and combo.currentData() is not None:
            return str(combo.currentData() or "tiny.en").strip() or "tiny.en"
        return str(_runtime_config().get("stt_model_size", "tiny.en") or "tiny.en").strip()

    def _current_stt_language_value(self):
        combo = getattr(self, "stt_language_combo", None)
        if combo is not None and combo.currentData() is not None:
            return normalize_whisper_language(combo.currentData()) or ""
        return normalize_whisper_language(_runtime_config().get("stt_language", "en")) or ""

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
        backend = self.stt_backend_combo.currentText() if hasattr(self, "stt_backend_combo") else "Local Whisper"
        if self._current_stt_backend_value() == "none":
            section.setSummary("Microphone disabled")
            return
        language = self.stt_language_combo.currentText() if hasattr(self, "stt_language_combo") else "English"
        model = self._current_stt_model_value()
        section.setSummary(f"{backend} / {model} / {language}")

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
        metadata = self._stt_backend_metadata(backend)
        default_model = str(metadata.get("default_model_size") or "").strip()
        default_language = str(metadata.get("default_language") or "").strip()
        if not default_language and str(metadata.get("language_mode") or "").strip().lower() == "multilingual":
            default_language = ""
        if default_model and hasattr(self, "stt_model_combo"):
            index = self.stt_model_combo.findData(default_model)
            if index >= 0:
                self.stt_model_combo.blockSignals(True)
                self.stt_model_combo.setCurrentIndex(index)
                self.stt_model_combo.blockSignals(False)
                _update_runtime_config("stt_model_size", default_model)
        if hasattr(self, "stt_language_combo") and (
            default_language or str(metadata.get("language_mode") or "").strip().lower() == "multilingual"
        ):
            normalized = normalize_whisper_language(default_language) or ""
            index = self.stt_language_combo.findData(normalized)
            if index >= 0:
                self.stt_language_combo.blockSignals(True)
                self.stt_language_combo.setCurrentIndex(index)
                self.stt_language_combo.blockSignals(False)
                _update_runtime_config("stt_language", normalized)
        self._refresh_stt_runtime_summary()
        self._reload_stt_runtime_if_available()
        self.save_session()

    def on_stt_model_change(self, _choice=None):
        _update_runtime_config("stt_model_size", self._current_stt_model_value())
        self._refresh_stt_runtime_summary()
        self._reload_stt_runtime_if_available()
        self.save_session()

    def on_stt_language_change(self, _choice=None):
        _update_runtime_config("stt_language", self._current_stt_language_value())
        self._refresh_stt_runtime_summary()
        self._reload_stt_runtime_if_available()
        self.save_session()
