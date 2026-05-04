import threading
import time

from PySide6 import QtCore, QtWidgets

from core import chat_providers
from ui.widgets.basic import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    import engine

    return getattr(engine, "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from engine import update_runtime_config

    return update_runtime_config(key, value)


def _get_chat_models(provider=None, quiet=True):
    from engine import get_chat_models

    return get_chat_models(provider=provider, quiet=quiet)


class BackendChatRuntimeMixin:
    """Chat provider/runtime card wiring for the backend compatibility window."""

    def _chat_provider_label_from_value(self, value):
        return chat_providers.provider_label(value or chat_providers.DEFAULT_PROVIDER_ID)

    def _chat_provider_value_from_label(self, label):
        text = str(label or "").strip()
        if hasattr(self, "chat_provider_combo"):
            for index in range(self.chat_provider_combo.count()):
                if str(self.chat_provider_combo.itemText(index) or "").strip() == text:
                    data = self.chat_provider_combo.itemData(index)
                    return chat_providers.normalize_provider_id(data, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        return chat_providers.normalize_provider_id(text, fallback=chat_providers.DEFAULT_PROVIDER_ID)

    def _current_chat_provider_value(self):
        if hasattr(self, "chat_provider_combo"):
            provider_value = self.chat_provider_combo.currentData()
            if provider_value:
                return chat_providers.normalize_provider_id(provider_value, fallback=chat_providers.DEFAULT_PROVIDER_ID)
            return self._chat_provider_value_from_label(self.chat_provider_combo.currentText())
        return chat_providers.normalize_provider_id(
            _runtime_config().get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )

    def _chat_provider_summaries(self):
        return [provider.to_summary() for provider in chat_providers.list_providers()]

    def _populate_chat_provider_combo(self, selected_value=None):
        if not hasattr(self, "chat_provider_combo"):
            return
        current_value = chat_providers.normalize_provider_id(
            selected_value if selected_value is not None else _runtime_config().get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )
        summaries = list(self._chat_provider_summaries())
        self.chat_provider_combo.blockSignals(True)
        self.chat_provider_combo.clear()
        for summary in summaries:
            label = str(summary.get("label") or summary.get("id") or "").strip()
            provider_id = str(summary.get("id") or "").strip()
            if label and provider_id:
                self.chat_provider_combo.addItem(label, provider_id)
        target_index = self.chat_provider_combo.findData(current_value)
        if target_index < 0 and self.chat_provider_combo.count():
            target_index = 0
        if target_index >= 0:
            self.chat_provider_combo.setCurrentIndex(target_index)
        self.chat_provider_combo.blockSignals(False)

    def _set_chat_provider_selection(self, provider_value):
        if not hasattr(self, "chat_provider_combo"):
            return chat_providers.normalize_provider_id(provider_value, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        normalized = chat_providers.normalize_provider_id(provider_value, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        index = self.chat_provider_combo.findData(normalized)
        if index < 0:
            self._populate_chat_provider_combo(normalized)
            index = self.chat_provider_combo.findData(normalized)
        if index >= 0:
            self.chat_provider_combo.setCurrentIndex(index)
        return normalized

    def _chat_provider_error_placeholder(self, provider_value=None):
        target = provider_value if provider_value is not None else self._current_chat_provider_value()
        return chat_providers.provider_model_error(target)

    def _is_model_catalog_placeholder(self, model_name):
        value = str(model_name or "").strip()
        lowered = value.lower()
        return (not value) or lowered in {"scanning...", "no models", "no vision models"} or lowered.startswith("error: check ")

    def _normalize_model_catalog_entry(self, item):
        if isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            supports_images = bool(item.get("supports_images", False))
            source = str(item.get("source") or "").strip().lower()
        else:
            model_id = str(item or "").strip()
            supports_images = self._infer_model_supports_images(model_id)
            source = ""
        if not model_id:
            return None
        return {
            "id": model_id,
            "supports_images": bool(supports_images),
            "source": source,
        }

    def _infer_model_supports_images(self, model_name):
        value = str(model_name or "").strip().lower()
        if self._is_model_catalog_placeholder(model_name):
            return False
        positive_fragments = (
            "vision", "image", "multimodal", "vl", "llava", "bakllava", "moondream", "pixtral",
            "minicpm-v", "internvl", "phi-3.5-vision", "phi-4-multimodal", "gemma-3", "gpt-4o",
            "gpt-4.1", "omni", "qwen/qwen3.5", "qwen3.5", "qwen2-vl", "qwen2.5-vl", "qvq",
        )
        negative_fragments = (
            "embedding", "rerank", "whisper", "tts", "audio", "transcribe", "grok-imagine"
        )
        if any(fragment in value for fragment in negative_fragments):
            return False
        return any(fragment in value for fragment in positive_fragments)

    def _current_model_supports_images_value(self, model_name=None):
        selected_model = str(model_name or (self.model_combo.currentText() if hasattr(self, "model_combo") else "") or "").strip()
        if not selected_model:
            return False
        if self._is_model_catalog_placeholder(selected_model):
            return False
        if hasattr(self, "model_requires_vision_checkbox") and self.model_requires_vision_checkbox.isChecked():
            return True
        for entry in list(getattr(self, "_all_model_catalog", []) or []):
            if str(entry.get("id") or "").strip() != selected_model:
                continue
            return bool(entry.get("supports_images", False))
        return self._infer_model_supports_images(selected_model)

    def _set_model_catalog(self, items):
        catalog = []
        seen = set()
        for item in list(items or []):
            entry = self._normalize_model_catalog_entry(item)
            if not entry:
                continue
            model_id = str(entry.get("id") or "")
            if model_id in seen:
                continue
            seen.add(model_id)
            catalog.append(entry)
        self._all_model_catalog = list(catalog)
        if hasattr(self, "model_requires_vision_checkbox") and self.model_requires_vision_checkbox.isChecked():
            catalog = [entry for entry in catalog if bool(entry.get("supports_images", False))]
        self._model_catalog = list(catalog)
        return list(catalog)

    def _current_model_display_items(self):
        catalog = list(getattr(self, "_model_catalog", []) or [])
        if catalog:
            return [str(entry.get("id") or "") for entry in catalog if str(entry.get("id") or "").strip()]
        return []

    def _apply_saved_model_name(self, model_name):
        wanted = str(model_name or "").strip()
        if not wanted or not hasattr(self, "model_combo"):
            return False
        index = self.model_combo.findText(wanted)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
            return True
        current = self.model_combo.currentText().strip() if self.model_combo.currentText() else "<none>"
        print(f"[QtGUI] Saved model not available: {wanted}. Keeping current model: {current}")
        return False

    def _tutorial_model_loaded(self):
        if not hasattr(self, "model_combo"):
            return False
        current = str(self.model_combo.currentText() or "").strip()
        return not self._is_model_catalog_placeholder(current)

    def on_model_requires_vision_changed(self, _checked):
        _update_runtime_config("model_requires_vision", bool(_checked))
        self.refresh_model_list_quietly(quiet=True, preloaded_models=list(getattr(self, "_all_model_catalog", []) or []))
        selected_model = str(self.model_combo.currentText() if hasattr(self, "model_combo") else _runtime_config().get("model_name", "") or "").strip()
        if selected_model:
            _update_runtime_config("model_supports_images", self._current_model_supports_images_value(selected_model))
            self._refresh_chat_runtime_summary()
        self.save_session()

    def request_model_list_refresh(self, quiet=True, wait_for_reachable=False):
        provider = self._current_chat_provider_value()
        if self._model_refresh_in_flight and str(getattr(self, "_model_refresh_provider", "") or "") == provider:
            return
        self._model_refresh_generation = int(getattr(self, "_model_refresh_generation", 0) or 0) + 1
        refresh_generation = self._model_refresh_generation
        self._model_refresh_in_flight = True
        self._model_refresh_provider = provider
        if hasattr(self, "btn_model_refresh"):
            self.btn_model_refresh.setEnabled(False)
            self.btn_model_refresh.setText("Waiting..." if wait_for_reachable else "Refreshing...")

        def worker():
            error_placeholder = self._chat_provider_error_placeholder(provider)
            models = None
            first_attempt = True
            while True:
                try:
                    models = _get_chat_models(provider=provider, quiet=quiet if first_attempt else True)
                except Exception:
                    models = [error_placeholder]
                    break
                valid_models = [item for item in list(models or []) if item and item != error_placeholder]
                if valid_models or not wait_for_reachable:
                    break
                first_attempt = False
                time.sleep(1.0)
            with self._model_refresh_lock:
                self._pending_model_refresh = list(models or [error_placeholder])
                self._pending_model_refresh_provider = provider
                self._pending_model_refresh_generation = refresh_generation
            if bool(getattr(self, "_closing", False)):
                return
            try:
                QtCore.QMetaObject.invokeMethod(self, "_apply_pending_model_refresh", QtCore.Qt.QueuedConnection)
            except RuntimeError:
                # The hidden backend can be destroyed during --ui-real smoke shutdown
                # while a provider model refresh is still returning.
                return

        threading.Thread(target=worker, daemon=True).start()

    @QtCore.Slot()
    def _apply_pending_model_refresh(self):
        with self._model_refresh_lock:
            models = list(self._pending_model_refresh or [])
            provider = str(getattr(self, "_pending_model_refresh_provider", "") or "")
            refresh_generation = int(getattr(self, "_pending_model_refresh_generation", 0) or 0)
            self._pending_model_refresh = None
            self._pending_model_refresh_provider = ""
            self._pending_model_refresh_generation = 0
        if provider != self._current_chat_provider_value() or refresh_generation != int(getattr(self, "_model_refresh_generation", 0) or 0):
            return
        self._model_refresh_in_flight = False
        self._model_refresh_provider = ""
        if hasattr(self, "btn_model_refresh"):
            self.btn_model_refresh.setEnabled(True)
            self.btn_model_refresh.setText("Refresh")
        self.refresh_model_list_quietly(quiet=True, preloaded_models=models)
        self._refresh_chat_runtime_summary()

    def refresh_model_list_quietly(self, quiet=True, preloaded_models=None):
        if not hasattr(self, "model_combo"):
            return
        provider = self._current_chat_provider_value()
        raw_models = list(preloaded_models or _get_chat_models(provider=provider, quiet=quiet))
        available_catalog = self._set_model_catalog(raw_models)
        valid_models = [str(entry.get("id") or "") for entry in list(getattr(self, "_all_model_catalog", []) or []) if str(entry.get("id") or "")]
        self._tutorial_lm_studio_running = bool(valid_models)

        current = str(self.model_combo.currentText() or "").strip()
        previous_items = [self.model_combo.itemText(i) for i in range(self.model_combo.count())]
        filtered_models = [str(entry.get("id") or "") for entry in available_catalog if str(entry.get("id") or "")]
        if raw_models and not filtered_models and hasattr(self, "model_requires_vision_checkbox") and self.model_requires_vision_checkbox.isChecked():
            new_items = ["No Vision Models"]
        else:
            error_placeholder = self._chat_provider_error_placeholder(provider)
            new_items = filtered_models or (raw_models if any(str(item or "").strip() == error_placeholder for item in raw_models) else ["No Models"])

        pending_wanted = str(getattr(self, "_pending_restored_model_name", "") or "").strip()
        if previous_items == new_items and (not pending_wanted or current == pending_wanted):
            if current:
                _update_runtime_config("model_name", current)
                _update_runtime_config("model_supports_images", self._current_model_supports_images_value(current))
            self.emit_tutorial_event(
                "model_list_refreshed",
                {"count": len(valid_models), "model_loaded": bool(valid_models), "lm_studio_running": bool(valid_models)},
            )
            if not self._finalize_pending_preset_clean_if_ready():
                self._refresh_preset_dirty_state()
            return

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(new_items)
        target_index = 0
        if filtered_models and current in filtered_models:
            target_index = filtered_models.index(current)
        elif filtered_models:
            wanted = str(getattr(self, "_pending_restored_model_name", "") or "").strip() or str(_runtime_config().get("model_name", "") or "").strip()
            if wanted in filtered_models:
                target_index = filtered_models.index(wanted)
        self.model_combo.setCurrentIndex(max(0, min(target_index, self.model_combo.count() - 1)))
        self.model_combo.blockSignals(False)
        selected_model = str(self.model_combo.currentText() or "").strip()
        if selected_model:
            _update_runtime_config("model_name", selected_model)
            _update_runtime_config("model_supports_images", self._current_model_supports_images_value(selected_model))
        pending_wanted = str(getattr(self, "_pending_restored_model_name", "") or "").strip()
        if pending_wanted and selected_model == pending_wanted:
            self._pending_restored_model_name = ""

        self.emit_tutorial_event(
            "model_list_refreshed",
            {"count": len(valid_models), "model_loaded": bool(valid_models), "lm_studio_running": bool(valid_models)},
        )
        self.update_model_budget_hint()
        if not self._finalize_pending_preset_clean_if_ready():
            self._refresh_preset_dirty_state()
        self._refresh_preset_dirty_state()

    def _current_chat_provider_settings_map(self):
        raw = _runtime_config().get("chat_provider_settings", {}) or {}
        return {str(key or "").strip().lower(): dict(value or {}) for key, value in raw.items() if str(key or "").strip()}

    def _current_chat_provider_settings_for(self, provider_id=None):
        provider_key = self._current_chat_provider_value() if provider_id is None else chat_providers.normalize_provider_id(provider_id, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        return dict(self._current_chat_provider_settings_map().get(provider_key, {}))

    def _set_current_chat_provider_settings_for(self, provider_id, updates):
        provider_key = chat_providers.normalize_provider_id(provider_id, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        settings_map = self._current_chat_provider_settings_map()
        next_values = {
            str(field_id or "").strip(): str(value or "").strip()
            for field_id, value in dict(updates or {}).items()
            if str(field_id or "").strip()
        }
        if next_values:
            settings_map[provider_key] = next_values
        elif provider_key in settings_map:
            settings_map.pop(provider_key, None)
        _update_runtime_config("chat_provider_settings", settings_map)

    def _chat_provider_metadata(self, provider_id=None):
        target = provider_id if provider_id is not None else self._current_chat_provider_value()
        return chat_providers.provider_metadata(target)

    def _chat_provider_config_fields(self, provider_id=None):
        metadata = self._chat_provider_metadata(provider_id)
        fields = list(metadata.get("config_fields") or [])
        return [dict(item) for item in fields if isinstance(item, dict)]

    def _current_chat_provider_generation_settings_map(self):
        raw = _runtime_config().get("chat_provider_generation_settings", {}) or {}
        return {
            str(key or "").strip().lower(): dict(value or {})
            for key, value in raw.items()
            if str(key or "").strip() and isinstance(value, dict)
        }

    def _current_chat_provider_generation_settings_for(self, provider_id=None):
        provider_key = self._current_chat_provider_value() if provider_id is None else chat_providers.normalize_provider_id(provider_id, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        return dict(self._current_chat_provider_generation_settings_map().get(provider_key, {}))

    def _set_current_chat_provider_generation_settings_for(self, provider_id, updates):
        provider_key = chat_providers.normalize_provider_id(provider_id, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        settings_map = self._current_chat_provider_generation_settings_map()
        next_values = {}
        for field_id, value in dict(updates or {}).items():
            key = str(field_id or "").strip()
            if not key:
                continue
            if value is None or value == "":
                continue
            next_values[key] = value
        if next_values:
            settings_map[provider_key] = next_values
        else:
            settings_map.pop(provider_key, None)
        _update_runtime_config("chat_provider_generation_settings", settings_map)

    def _chat_provider_generation_fields(self, provider_id=None):
        metadata = self._chat_provider_metadata(provider_id)
        fields = list(metadata.get("generation_fields") or [])
        return [dict(item) for item in fields if isinstance(item, dict)]

    def _legacy_generation_value_for_field(self, provider_id, field):
        field_id = str(field.get("id") or "").strip()
        if field_id in {"temperature", "top_p", "repeat_penalty", "min_p"}:
            return float(_runtime_config().get(field_id, field.get("default", 0.0)) or 0.0)
        if field_id == "top_k":
            return int(_runtime_config().get("top_k", field.get("default", 0)) or 0)
        if field_id in {"max_tokens", "max_completion_tokens"}:
            provider_settings = self._current_chat_provider_settings_for(provider_id)
            if "max_tokens" in provider_settings:
                return provider_settings.get("max_tokens")
            if bool(_runtime_config().get("limit_response_length", False)):
                return int(_runtime_config().get("max_response_tokens", field.get("default", DEFAULT_MAX_RESPONSE_TOKENS)) or DEFAULT_MAX_RESPONSE_TOKENS)
        return field.get("default", "")

    def _generation_field_display_value(self, provider_id, field, current_settings):
        field_id = str(field.get("id") or "").strip()
        if field_id in current_settings:
            return current_settings.get(field_id)
        return self._legacy_generation_value_for_field(provider_id, field)

    def _generation_field_widget_value(self, field, widget):
        kind = str(field.get("kind") or "text").strip().lower()
        if isinstance(widget, QtWidgets.QCheckBox):
            return bool(widget.isChecked())
        if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, QtWidgets.QComboBox):
            data = widget.currentData()
            return data if data is not None else widget.currentText()
        if isinstance(widget, QtWidgets.QLineEdit):
            value = widget.text().strip()
            if kind == "int" and value:
                try:
                    return int(value)
                except ValueError:
                    return value
            if kind == "float" and value:
                try:
                    return float(value)
                except ValueError:
                    return value
            return value
        return None

    def _apply_legacy_generation_mirror(self, field_id, value):
        try:
            if field_id in {"temperature", "top_p", "repeat_penalty", "min_p"}:
                _update_runtime_config(field_id, float(value))
                if field_id in getattr(self, "brain_sliders", {}):
                    self.brain_sliders[field_id].set_value(float(value))
            elif field_id == "top_k":
                _update_runtime_config("top_k", int(value))
                if "top_k" in getattr(self, "brain_sliders", {}):
                    self.brain_sliders["top_k"].set_value(int(value))
            elif field_id in {"max_tokens", "max_completion_tokens"} and int(value) > 0:
                _update_runtime_config("limit_response_length", True)
                _update_runtime_config("max_response_tokens", int(value))
                if hasattr(self, "limit_response_checkbox"):
                    self.limit_response_checkbox.blockSignals(True)
                    self.limit_response_checkbox.setChecked(True)
                    self.limit_response_checkbox.blockSignals(False)
                if hasattr(self, "max_response_tokens_spin"):
                    self.max_response_tokens_spin.blockSignals(True)
                    self.max_response_tokens_spin.setValue(int(value))
                    self.max_response_tokens_spin.blockSignals(False)
        except Exception:
            pass

    def _request_frontend_layout_resync(self):
        callback = getattr(self, "frontend_layout_resync_callback", None)
        if callback is None:
            return

        try:
            QtCore.QTimer.singleShot(10, callback)
        except Exception:
            pass

    def _refresh_chat_provider_generation_card(self):
        if not hasattr(self, "chat_provider_generation_fields_layout"):
            return
        while self.chat_provider_generation_fields_layout.rowCount():
            self.chat_provider_generation_fields_layout.removeRow(0)
        self._chat_provider_generation_field_widgets = {}
        self._chat_provider_generation_field_meta = {}

        provider_id = self._current_chat_provider_value()
        current_settings = self._current_chat_provider_generation_settings_for(provider_id)
        fields = list(self._chat_provider_generation_fields(provider_id))

        if not fields:
            hint = QtWidgets.QLabel("This provider uses legacy generation controls internally.")
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            hint.setWordWrap(True)
            self.chat_provider_generation_fields_layout.addRow("", hint)
            self._sync_chat_provider_generation_fields_height()
            if hasattr(self, "chat_provider_generation_section"):
                self.chat_provider_generation_section.setSummary("legacy fallback controls")
            return

        active_labels = []
        for field in fields:
            field_id = str(field.get("id") or "").strip()
            if not field_id:
                continue
            label = str(field.get("label") or field_id.replace("_", " ").title()).strip()
            kind = str(field.get("kind") or "text").strip().lower()
            value = self._generation_field_display_value(provider_id, field, current_settings)
            if kind == "note":
                editor = QtWidgets.QLabel(str(field.get("text") or field.get("description") or ""))
                editor.setWordWrap(True)
                editor.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            elif kind == "bool":
                editor = QtWidgets.QCheckBox(label)
                editor.setChecked(bool(value))
                editor.toggled.connect(lambda _checked, fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))
                label = ""
            elif kind == "select":
                editor = NoWheelComboBox()
                for option in list(field.get("options") or []):
                    if isinstance(option, dict):
                        editor.addItem(str(option.get("label") or option.get("value") or ""), option.get("value"))
                    else:
                        editor.addItem(str(option), option)
                index = editor.findData(value)
                if index < 0:
                    index = editor.findText(str(value))
                if index >= 0:
                    editor.setCurrentIndex(index)
                editor.currentIndexChanged.connect(lambda _index, fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))
            elif kind == "int":
                editor = NoWheelSpinBox()
                editor.setRange(int(field.get("min", -999999)), int(field.get("max", 999999)))
                editor.setSingleStep(int(field.get("step", 1) or 1))
                editor.setValue(int(value if value not in {None, ""} else field.get("default", 0)))
                editor.valueChanged.connect(lambda _value, fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))
            elif kind == "float":
                editor = NoWheelDoubleSpinBox()
                editor.setRange(float(field.get("min", -999999.0)), float(field.get("max", 999999.0)))
                editor.setDecimals(int(field.get("decimals", 2) or 2))
                editor.setSingleStep(float(field.get("step", 0.01) or 0.01))
                editor.setValue(float(value if value not in {None, ""} else field.get("default", 0.0)))
                editor.valueChanged.connect(lambda _value, fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))
            else:
                editor = QtWidgets.QLineEdit()
                editor.setText(str(value if value is not None else ""))
                placeholder = field.get("placeholder")
                if placeholder:
                    editor.setPlaceholderText(str(placeholder))
                editor.editingFinished.connect(lambda fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))

            tooltip = str(field.get("description") or "").strip()
            if tooltip:
                editor.setToolTip(tooltip)
            if kind != "note":
                try:
                    editor.setMinimumWidth(260)
                    editor.setMinimumHeight(34)
                    editor.setMaximumWidth(16777215)
                    if kind in {"int", "float"} and hasattr(editor, "setFixedHeight"):
                        editor.setFixedHeight(34)
                except Exception:
                    pass
            self.chat_provider_generation_fields_layout.addRow(label, editor)
            if kind != "note":
                self._chat_provider_generation_field_widgets[field_id] = editor
                self._chat_provider_generation_field_meta[field_id] = dict(field)
                active_labels.append(label or str(field.get("label") or field_id))

        self._sync_chat_provider_generation_fields_height()
        try:
            QtCore.QTimer.singleShot(0, self._sync_chat_provider_generation_fields_height)
        except Exception:
            pass

        if hasattr(self, "chat_provider_generation_section"):
            summary = ", ".join(active_labels[:3])
            if len(active_labels) > 3:
                summary += f", +{len(active_labels) - 3}"
            self.chat_provider_generation_section.setSummary(summary)

    def _sync_chat_provider_generation_fields_height(self):
        try:
            widget = getattr(self, "chat_provider_generation_fields_widget", None)
            if not widget:
                return
            current = widget
            while current:
                if current.maximumHeight() < 16777215:
                    current.setMaximumHeight(16777215)
                layout = current.layout()
                if layout and hasattr(layout, "sizeConstraint"):
                    if layout.sizeConstraint() == QtWidgets.QLayout.SetMinAndMaxSize:
                        layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
                current = current.parentWidget()

            runtime_box = getattr(self, "chat_runtime_box", None)
            tts_box = getattr(self, "tts_runtime_box", None)
            for box in filter(None, [runtime_box, tts_box, widget]):
                policy = box.sizePolicy()
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
                box.setSizePolicy(policy)
                if box.layout():
                    box.layout().setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)

            QtWidgets.QApplication.processEvents()
            current = widget
            while current:
                if current.layout():
                    current.layout().invalidate()
                    current.layout().activate()
                if hasattr(current, "updateGeometry"):
                    current.updateGeometry()
                current = current.parentWidget()
        except Exception:
            pass

    def _refresh_chat_provider_card(self):
        if not hasattr(self, "chat_provider_fields_layout"):
            return
        while self.chat_provider_fields_layout.rowCount():
            self.chat_provider_fields_layout.removeRow(0)
        self._chat_provider_field_widgets = {}
        self._chat_provider_field_meta = {}

        provider_id = self._current_chat_provider_value()
        current_settings = self._current_chat_provider_settings_for(provider_id)
        fields = list(self._chat_provider_config_fields(provider_id))

        if fields:
            for field in fields:
                field_id = str(field.get("id") or "").strip()
                if not field_id:
                    continue
                label = str(field.get("label") or field_id.replace("_", " ").title()).strip()
                kind = str(field.get("kind") or "").strip().lower()
                if not kind:
                    kind = "password" if "key" in field_id.lower() or "token" in field_id.lower() else "text"
                editor = QtWidgets.QLineEdit()
                editor.setObjectName(f"chat_provider_field_{field_id}")
                if kind == "password":
                    editor.setEchoMode(QtWidgets.QLineEdit.Password)
                default_value = str(current_settings.get(field_id) or field.get("default") or "").strip()
                editor.setText(default_value)
                placeholder = field.get("placeholder")
                if placeholder:
                    editor.setPlaceholderText(str(placeholder))
                env_names = list(field.get("env") or [])
                tooltip_parts = []
                if env_names:
                    tooltip_parts.append("Env: " + ", ".join(str(name) for name in env_names if str(name or "").strip()))
                if field.get("default"):
                    tooltip_parts.append(f"Default: {field.get('default')}")
                if tooltip_parts:
                    editor.setToolTip("\n".join(tooltip_parts))
                editor.editingFinished.connect(lambda fid=field_id, widget=editor, pid=provider_id: self._on_chat_provider_field_changed(pid, fid, widget))
                self.chat_provider_fields_layout.addRow(label, editor)
                self._chat_provider_field_widgets[field_id] = editor
                self._chat_provider_field_meta[field_id] = dict(field)
            if hasattr(self, "chat_provider_settings_section"):
                self.chat_provider_settings_section.setSummary(f"{len(fields)} field(s)")
        else:
            hint = QtWidgets.QLabel("This provider does not expose extra runtime fields yet.")
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            hint.setWordWrap(True)
            self.chat_provider_fields_layout.addRow("", hint)
            if hasattr(self, "chat_provider_settings_section"):
                self.chat_provider_settings_section.setSummary("no extra fields")

        if hasattr(self, "chat_provider_hint_label"):
            metadata = self._chat_provider_metadata(provider_id)
            description = str(metadata.get("hint") or metadata.get("description") or "").strip()
            if not description:
                provider_label = self._chat_provider_label_from_value(provider_id)
                description = f"{provider_label} is selected."
            self.chat_provider_hint_label.setText(description)
        self._refresh_chat_provider_generation_card()
        self._refresh_chat_runtime_summary()

    def _refresh_chat_runtime_summary(self):
        if not hasattr(self, "chat_runtime_section"):
            return
        provider_label = self._chat_provider_label_from_value(self._current_chat_provider_value())
        model_name = str(self.model_combo.currentText() if hasattr(self, "model_combo") else _runtime_config().get("model_name", "") or "").strip()
        summary = provider_label
        if model_name and not self._is_model_catalog_placeholder(model_name):
            summary = f"{provider_label} / {model_name}"
        self.chat_runtime_section.setSummary(summary)

    def _on_chat_provider_field_changed(self, provider_id, field_id, widget):
        if widget is None:
            return
        settings = self._current_chat_provider_settings_for(provider_id)
        value = widget.text().strip()
        if value:
            settings[str(field_id or "").strip()] = value
        else:
            settings.pop(str(field_id or "").strip(), None)
        self._set_current_chat_provider_settings_for(provider_id, settings)
        self.request_model_list_refresh(quiet=True, wait_for_reachable=False)
        self.save_session()

    def _on_chat_provider_generation_field_changed(self, provider_id, field_id, widget, field_meta=None):
        if widget is None:
            return
        field_id = str(field_id or "").strip()
        if not field_id:
            return
        settings = self._current_chat_provider_generation_settings_for(provider_id)
        value = self._generation_field_widget_value(dict(field_meta or {}), widget)
        if value is None or value == "":
            settings.pop(field_id, None)
        else:
            settings[field_id] = value
        self._set_current_chat_provider_generation_settings_for(provider_id, settings)
        self._apply_legacy_generation_mirror(field_id, value)
        self.save_session()
        self._refresh_preset_dirty_state()

    def on_chat_provider_changed(self, _choice):
        provider_value = self._current_chat_provider_value()
        _update_runtime_config("chat_provider", provider_value)
        self._refresh_chat_provider_card()
        self._refresh_chat_runtime_summary()
        self.request_model_list_refresh(quiet=True, wait_for_reachable=False)
        self.update_model_budget_hint()
        self.save_session()

    def on_model_selection_changed(self, choice):
        selected_model = str(choice or "").strip()
        _update_runtime_config("model_name", selected_model)
        _update_runtime_config("model_supports_images", self._current_model_supports_images_value(selected_model))
        self._advisor_context_manual_override = False
        self.update_model_budget_hint()
        self._refresh_chat_runtime_summary()
        self.save_session()

    def on_model_context_input_changed(self, _value):
        if not self._advisor_context_updating:
            self._advisor_context_manual_override = True
        self.update_model_budget_hint()
