import threading
import time

from PySide6 import QtCore, QtWidgets

from core import chat_providers
from ui.widgets.basic import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    from ui.runtime import engine_access as engine

    return getattr(engine, "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


def _get_chat_models(provider=None, quiet=True):
    from ui.runtime.engine_access import get_chat_models

    return get_chat_models(provider=provider, quiet=quiet)

class BackendChatProviderFieldsMixin:
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
        filtered = []
        for item in fields:
            if not isinstance(item, dict):
                continue
            field = dict(item)
            required_support = str(field.get("requires_model_support") or "").strip().lower()
            if required_support:
                support_attr = f"_current_model_supports_{required_support}_value"
                support_getter = getattr(self, support_attr, None)
                if callable(support_getter):
                    try:
                        if not bool(support_getter()):
                            continue
                    except Exception:
                        continue
            filtered.append(field)
        return filtered

    def _bool_generation_value(self, value, default=False):
        if value is None or value == "":
            return bool(default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

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
                editor.setChecked(self._bool_generation_value(value, field.get("default", False)))
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
            self._request_frontend_layout_resync()
            try:
                QtCore.QTimer.singleShot(75, self._request_frontend_layout_resync)
                QtCore.QTimer.singleShot(200, self._request_frontend_layout_resync)
            except Exception:
                pass
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
