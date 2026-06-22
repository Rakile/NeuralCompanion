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

class BackendChatModelCatalogMixin:
    def _is_model_catalog_placeholder(self, model_name):
        value = str(model_name or "").strip()
        lowered = value.lower()
        return (not value) or lowered in {"scanning...", "no models", "no vision models"} or lowered.startswith("error: check ")

    def _normalize_model_catalog_entry(self, item):
        if isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            inferred_reasoning = self._infer_model_supports_reasoning(model_id)
            supports_images = bool(item.get("supports_images", False))
            supports_reasoning = bool(item.get("supports_reasoning", inferred_reasoning))
            supports_reasoning_toggle = bool(item.get("supports_reasoning_toggle", inferred_reasoning))
            source = str(item.get("source") or "").strip().lower()
        else:
            model_id = str(item or "").strip()
            inferred_reasoning = self._infer_model_supports_reasoning(model_id)
            supports_images = self._infer_model_supports_images(model_id)
            supports_reasoning = inferred_reasoning
            supports_reasoning_toggle = bool(inferred_reasoning)
            source = ""
        if not model_id:
            return None
        return {
            "id": model_id,
            "supports_images": bool(supports_images),
            "supports_reasoning": bool(supports_reasoning),
            "supports_reasoning_toggle": bool(supports_reasoning_toggle),
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

    def _infer_model_supports_reasoning(self, model_name):
        value = str(model_name or "").strip().lower()
        if self._is_model_catalog_placeholder(model_name):
            return False
        negative_fragments = (
            "embedding", "rerank", "whisper", "tts", "audio", "transcribe", "grok-imagine"
        )
        if any(fragment in value for fragment in negative_fragments):
            return False
        positive_fragments = (
            "reasoning", "thinking", "think", "qwen3", "qwen-3", "qwen/qwen3", "qwen3.5",
            "qwen-3.5", "qwen3.6", "qwen-3.6", "qwq", "qvq", "deepseek-r1", "deepseek/r1",
            "r1-distill", "gpt-oss", "seed-oss", "gemma-4",
        )
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

    def _current_model_supports_reasoning_value(self, model_name=None):
        selected_model = str(model_name or (self.model_combo.currentText() if hasattr(self, "model_combo") else "") or "").strip()
        if not selected_model or self._is_model_catalog_placeholder(selected_model):
            return False
        for entry in list(getattr(self, "_all_model_catalog", []) or []):
            if str(entry.get("id") or "").strip() != selected_model:
                continue
            return bool(entry.get("supports_reasoning", False))
        return self._infer_model_supports_reasoning(selected_model)

    def _current_model_supports_reasoning_toggle_value(self, model_name=None):
        selected_model = str(model_name or (self.model_combo.currentText() if hasattr(self, "model_combo") else "") or "").strip()
        if not selected_model or self._is_model_catalog_placeholder(selected_model):
            return False
        for entry in list(getattr(self, "_all_model_catalog", []) or []):
            if str(entry.get("id") or "").strip() != selected_model:
                continue
            return bool(entry.get("supports_reasoning_toggle", False))
        return self._infer_model_supports_reasoning(selected_model)

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
            self.model_combo.blockSignals(True)
            try:
                self.model_combo.setCurrentIndex(index)
            finally:
                self.model_combo.blockSignals(False)
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
        provider_getter = getattr(self, "_current_chat_provider_editor_value", None)
        provider = provider_getter() if callable(provider_getter) else self._current_chat_provider_value()
        active_provider = self._current_chat_provider_value()
        if provider == active_provider:
            _update_runtime_config("model_requires_vision", bool(_checked))
        catalog_map = getattr(self, "_chat_provider_model_catalogs", {}) or {}
        provider_catalog = list(catalog_map.get(provider) or [])
        if not provider_catalog:
            provider_catalog = list(getattr(self, "_all_model_catalog", []) or [])
        self.refresh_model_list_quietly(quiet=True, preloaded_models=provider_catalog)
        selected_model = str(self.model_combo.currentText() if hasattr(self, "model_combo") else _runtime_config().get("model_name", "") or "").strip()
        if selected_model:
            model_supports_images = self._current_model_supports_images_value(selected_model)
            if provider == active_provider:
                _update_runtime_config("model_supports_images", model_supports_images)
            if hasattr(self, "_set_current_chat_provider_model_state_for"):
                self._set_current_chat_provider_model_state_for(
                    provider,
                    model_name=selected_model,
                    model_requires_vision=bool(_checked),
                    model_supports_images=model_supports_images,
                    model_supports_reasoning=self._current_model_supports_reasoning_value(selected_model),
                    model_supports_reasoning_toggle=self._current_model_supports_reasoning_toggle_value(selected_model),
                )
            self._refresh_chat_runtime_summary()
        self.save_session()

    def request_model_list_refresh(self, quiet=True, wait_for_reachable=False, force=False):
        provider_getter = getattr(self, "_current_chat_provider_editor_value", None)
        provider = provider_getter() if callable(provider_getter) else self._current_chat_provider_value()
        if hasattr(self, "_sync_chat_provider_settings_to_registry"):
            self._sync_chat_provider_settings_to_registry()
        if self._model_refresh_in_flight and str(getattr(self, "_model_refresh_provider", "") or "") == provider and not force:
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
        provider_getter = getattr(self, "_current_chat_provider_editor_value", None)
        current_provider = provider_getter() if callable(provider_getter) else self._current_chat_provider_value()
        if provider != current_provider or refresh_generation != int(getattr(self, "_model_refresh_generation", 0) or 0):
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
        provider_getter = getattr(self, "_current_chat_provider_editor_value", None)
        provider = provider_getter() if callable(provider_getter) else self._current_chat_provider_value()
        active_provider = self._current_chat_provider_value()
        raw_models = (
            list(_get_chat_models(provider=provider, quiet=quiet))
            if preloaded_models is None
            else list(preloaded_models or [])
        )
        available_catalog = self._set_model_catalog(raw_models)
        catalog_map = dict(getattr(self, "_chat_provider_model_catalogs", {}) or {})
        catalog_map[provider] = list(getattr(self, "_all_model_catalog", []) or [])
        self._chat_provider_model_catalogs = catalog_map
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

        provider_state = self._current_chat_provider_model_state_for(provider) if hasattr(self, "_current_chat_provider_model_state_for") else {}
        provider_wanted = str((provider_state or {}).get("model_name") or "").strip()
        pending_wanted = str(getattr(self, "_pending_restored_model_name", "") or "").strip() or provider_wanted
        if previous_items == new_items and (not pending_wanted or current == pending_wanted):
            if current and not self._is_model_catalog_placeholder(current):
                model_supports_images = self._current_model_supports_images_value(current)
                model_supports_reasoning = self._current_model_supports_reasoning_value(current)
                model_supports_reasoning_toggle = self._current_model_supports_reasoning_toggle_value(current)
                if provider == active_provider:
                    _update_runtime_config("model_name", current)
                    _update_runtime_config("model_supports_images", model_supports_images)
                    _update_runtime_config("model_supports_reasoning", model_supports_reasoning)
                    _update_runtime_config("model_supports_reasoning_toggle", model_supports_reasoning_toggle)
                if hasattr(self, "_set_current_chat_provider_model_state_for"):
                    self._set_current_chat_provider_model_state_for(
                        provider,
                        model_name=current,
                        model_requires_vision=bool(self.model_requires_vision_checkbox.isChecked()) if hasattr(self, "model_requires_vision_checkbox") else False,
                        model_supports_images=model_supports_images,
                        model_supports_reasoning=model_supports_reasoning,
                        model_supports_reasoning_toggle=model_supports_reasoning_toggle,
                    )
                self._refresh_chat_provider_generation_card()
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
        if filtered_models:
            wanted = str(getattr(self, "_pending_restored_model_name", "") or "").strip() or provider_wanted
            if wanted in filtered_models:
                target_index = filtered_models.index(wanted)
            elif current in filtered_models:
                target_index = filtered_models.index(current)
        self.model_combo.setCurrentIndex(max(0, min(target_index, self.model_combo.count() - 1)))
        self.model_combo.blockSignals(False)
        selected_model = str(self.model_combo.currentText() or "").strip()
        if selected_model and not self._is_model_catalog_placeholder(selected_model):
            model_supports_images = self._current_model_supports_images_value(selected_model)
            model_supports_reasoning = self._current_model_supports_reasoning_value(selected_model)
            model_supports_reasoning_toggle = self._current_model_supports_reasoning_toggle_value(selected_model)
            if provider == active_provider:
                _update_runtime_config("model_name", selected_model)
                _update_runtime_config("model_supports_images", model_supports_images)
                _update_runtime_config("model_supports_reasoning", model_supports_reasoning)
                _update_runtime_config("model_supports_reasoning_toggle", model_supports_reasoning_toggle)
            if hasattr(self, "_set_current_chat_provider_model_state_for"):
                self._set_current_chat_provider_model_state_for(
                    provider,
                    model_name=selected_model,
                    model_requires_vision=bool(self.model_requires_vision_checkbox.isChecked()) if hasattr(self, "model_requires_vision_checkbox") else False,
                    model_supports_images=model_supports_images,
                    model_supports_reasoning=model_supports_reasoning,
                    model_supports_reasoning_toggle=model_supports_reasoning_toggle,
                )
            self._refresh_chat_provider_generation_card()
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
