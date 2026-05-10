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

class BackendChatProviderSelectionMixin:
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
