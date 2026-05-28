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

class BackendChatRuntimeEventsMixin:
    def _refresh_chat_runtime_summary(self):
        if not hasattr(self, "chat_runtime_section"):
            return
        provider_value = self._current_chat_provider_value()
        provider_label = self._chat_provider_label_from_value(provider_value)
        state_getter = getattr(self, "_current_chat_provider_model_state_for", None)
        state = state_getter(provider_value) if callable(state_getter) else {}
        model_name = str((state or {}).get("model_name") or _runtime_config().get("model_name", "") or "").strip()
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
        self.request_model_list_refresh(quiet=True, wait_for_reachable=False, force=True)
        self.save_session()

    def _on_chat_provider_generation_field_changed(self, provider_id, field_id, widget, field_meta=None):
        if widget is None:
            return
        field_id = str(field_id or "").strip()
        if not field_id:
            return
        current_widgets = getattr(self, "_chat_provider_generation_field_widgets", {}) or {}
        if current_widgets.get(field_id) is not widget:
            return
        if bool(getattr(self, "_restoring_preset", False)):
            return
        settings = self._current_chat_provider_generation_settings_for(provider_id)
        value = self._generation_field_widget_value(dict(field_meta or {}), widget)
        if value is None or value == "":
            settings.pop(field_id, None)
        else:
            settings[field_id] = value
        self._set_current_chat_provider_generation_settings_for(provider_id, settings)
        self.save_session()

    def on_chat_provider_changed(self, _choice):
        provider_value = self._current_chat_provider_value()
        self._chat_runtime_editor_provider = provider_value
        _update_runtime_config("chat_provider", provider_value)
        state = self._sync_active_provider_model_state_to_runtime(provider_value) if hasattr(self, "_sync_active_provider_model_state_to_runtime") else {}
        wanted_model = str((state or {}).get("model_name") or "").strip()
        self._pending_restored_model_name = wanted_model
        if hasattr(self, "model_requires_vision_checkbox"):
            self.model_requires_vision_checkbox.blockSignals(True)
            try:
                self.model_requires_vision_checkbox.setChecked(bool((state or {}).get("model_requires_vision", False)))
            finally:
                self.model_requires_vision_checkbox.blockSignals(False)
        self._refresh_chat_provider_card()
        self._refresh_chat_runtime_summary()
        self.request_model_list_refresh(quiet=True, wait_for_reachable=False)
        self.update_model_budget_hint()
        self.save_session()

    def on_model_selection_changed(self, choice):
        selected_model = str(choice or "").strip()
        if self._is_model_catalog_placeholder(selected_model):
            self._refresh_chat_runtime_summary()
            return
        editor_getter = getattr(self, "_current_chat_provider_editor_value", None)
        provider_value = editor_getter() if callable(editor_getter) else self._current_chat_provider_value()
        active_provider = self._current_chat_provider_value()
        model_supports_images = self._current_model_supports_images_value(selected_model)
        model_supports_reasoning = self._current_model_supports_reasoning_value(selected_model)
        model_supports_reasoning_toggle = self._current_model_supports_reasoning_toggle_value(selected_model)
        if hasattr(self, "_set_current_chat_provider_model_state_for"):
            self._set_current_chat_provider_model_state_for(
                provider_value,
                model_name=selected_model,
                model_requires_vision=bool(self.model_requires_vision_checkbox.isChecked()) if hasattr(self, "model_requires_vision_checkbox") else False,
                model_supports_images=model_supports_images,
                model_supports_reasoning=model_supports_reasoning,
                model_supports_reasoning_toggle=model_supports_reasoning_toggle,
            )
        if provider_value == active_provider:
            _update_runtime_config("model_name", selected_model)
            _update_runtime_config("model_supports_images", model_supports_images)
            _update_runtime_config("model_supports_reasoning", model_supports_reasoning)
            _update_runtime_config("model_supports_reasoning_toggle", model_supports_reasoning_toggle)
        self._advisor_context_manual_override = False
        self.update_model_budget_hint()
        self._refresh_chat_provider_generation_card()
        self._refresh_chat_runtime_summary()
        self.save_session()

    def on_model_context_input_changed(self, _value):
        if not self._advisor_context_updating:
            self._advisor_context_manual_override = True
        self.update_model_budget_hint()
