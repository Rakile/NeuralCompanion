import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "PySide6" not in sys.modules:
    qtcore = types.ModuleType("PySide6.QtCore")

    def _slot(*_args, **_kwargs):
        def _decorator(func):
            return func

        return _decorator

    qtcore.Slot = _slot
    qtcore.QMetaObject = types.SimpleNamespace(invokeMethod=lambda *_args, **_kwargs: None)
    qtcore.Qt = types.SimpleNamespace(QueuedConnection=object())
    pyside6 = types.ModuleType("PySide6")
    pyside6.QtCore = qtcore
    pyside6.QtWidgets = types.ModuleType("PySide6.QtWidgets")
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtWidgets"] = pyside6.QtWidgets
if "openai" not in sys.modules:
    openai = types.ModuleType("openai")
    openai.OpenAI = object
    sys.modules["openai"] = openai
if "ui.widgets.basic" not in sys.modules:
    basic = types.ModuleType("ui.widgets.basic")
    basic.NoWheelComboBox = object
    basic.NoWheelDoubleSpinBox = object
    basic.NoWheelSpinBox = object
    sys.modules["ui.widgets.basic"] = basic
if "ui.runtime.engine_access" not in sys.modules:
    engine_access = types.ModuleType("ui.runtime.engine_access")
    engine_access.update_runtime_config = lambda *_args, **_kwargs: None
    sys.modules["ui.runtime.engine_access"] = engine_access

from ui.runtime.backend_chat_model_catalog import BackendChatModelCatalogMixin
from ui.runtime.backend_chat_provider_fields import BackendChatProviderFieldsMixin
from core import chat_providers


for _provider_id, _label in (("lmstudio", "LM Studio"), ("openai", "OpenAI")):
    if chat_providers.get_provider(_provider_id) is None:
        chat_providers.register_provider(provider_id=_provider_id, label=_label)


class _FakeCombo:
    def __init__(self, items=None, current_index=0):
        self.items = list(items or [])
        self.index = int(current_index)

    def blockSignals(self, _blocked):
        return None

    def clear(self):
        self.items = []
        self.index = -1

    def addItems(self, items):
        self.items.extend(list(items or []))
        if self.index < 0 and self.items:
            self.index = 0

    def count(self):
        return len(self.items)

    def currentText(self):
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return ""

    def itemText(self, index):
        return self.items[int(index)]

    def findText(self, text):
        try:
            return self.items.index(str(text))
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self.index = int(index)


class _FakeCheckBox:
    def __init__(self, checked=False):
        self.checked = bool(checked)

    def blockSignals(self, _blocked):
        return None

    def isChecked(self):
        return bool(self.checked)

    def setChecked(self, checked):
        self.checked = bool(checked)


class _Harness(BackendChatProviderFieldsMixin, BackendChatModelCatalogMixin):
    def __init__(self):
        self.model_combo = _FakeCombo(["google/gemma-4-12b-qat", "gpt-4o-mini"], 0)
        self.model_requires_vision_checkbox = _FakeCheckBox(False)
        self._chat_runtime_editor_provider = "lmstudio"
        self._pending_restored_model_name = ""
        self._model_refresh_in_flight = False
        self._settings = {
            "lmstudio": {"model_name": "google/gemma-4-12b-qat"},
            "openai": {"model_name": "gpt-4o-mini"},
        }
        self.events = []
        self.refresh_requests = []

    def _current_chat_provider_value(self):
        return "lmstudio"

    def _current_chat_provider_settings_map(self):
        return {key: dict(value) for key, value in self._settings.items()}

    def _set_current_chat_provider_settings_for(self, provider_id, updates):
        self._settings[str(provider_id)] = dict(updates or {})

    def _chat_provider_error_placeholder(self, provider):
        return f"Error: check {provider}"

    def _refresh_chat_provider_card(self):
        return None

    def _refresh_chat_provider_generation_card(self):
        return None

    def _refresh_chat_runtime_summary(self):
        return None

    def emit_tutorial_event(self, event_name, payload=None):
        self.events.append((event_name, dict(payload or {})))

    def update_model_budget_hint(self):
        return None

    def _finalize_pending_preset_clean_if_ready(self):
        return False

    def _refresh_preset_dirty_state(self):
        return None

    def request_model_list_refresh(self, **_kwargs):
        self.refresh_requests.append(dict(_kwargs))

    def save_session(self):
        return None


def test_browse_provider_restores_saved_model_without_refresh():
    harness = _Harness()
    harness._chat_provider_model_catalogs = {
        "openai": [
            {"id": "gpt-4o-mini"},
            {"id": "chatgpt-image-latest"},
        ],
    }

    harness._set_chat_provider_editor_value("openai", refresh_models=False)

    assert harness._current_chat_provider_editor_value() == "openai"
    assert harness._current_chat_provider_value() == "lmstudio"
    assert harness.model_combo.currentText() == "gpt-4o-mini"
    assert harness.model_combo.items == ["gpt-4o-mini", "chatgpt-image-latest"]
    assert harness.refresh_requests == []


def test_cold_browse_provider_requests_model_refresh_once():
    harness = _Harness()

    harness._set_chat_provider_editor_value("openai", refresh_models=False)

    assert harness.model_combo.currentText() == "gpt-4o-mini"
    assert len(harness.refresh_requests) == 1
    assert harness.refresh_requests[0]["quiet"] is True


def test_model_refresh_prefers_pending_provider_model_over_previous_combo_text():
    harness = _Harness()
    harness._chat_runtime_editor_provider = "openai"
    harness._pending_restored_model_name = "gpt-4o-mini"

    harness.refresh_model_list_quietly(
        quiet=True,
        preloaded_models=["google/gemma-4-12b-qat", "gpt-4o-mini"],
    )

    assert harness.model_combo.currentText() == "gpt-4o-mini"


def test_browse_provider_without_saved_model_clears_previous_provider_model():
    harness = _Harness()
    harness._settings["openai"].pop("model_name", None)

    harness._set_chat_provider_editor_value("openai", refresh_models=False)

    assert harness._current_chat_provider_editor_value() == "openai"
    assert harness.model_combo.currentText() == "No Models"
    assert "google/gemma-4-12b-qat" not in harness.model_combo.items


def test_repeated_browse_provider_refreshes_stale_model_display():
    harness = _Harness()
    harness._chat_runtime_editor_provider = "openai"
    harness._chat_provider_model_catalogs = {
        "openai": [
            {"id": "gpt-4o-mini"},
            {"id": "chatgpt-image-latest"},
        ],
    }
    harness.model_combo.clear()
    harness.model_combo.addItems(["google/gemma-4-12b-qat"])
    harness.model_combo.setCurrentIndex(0)

    harness._set_chat_provider_editor_value("openai", refresh_models=False)

    assert harness.model_combo.currentText() == "gpt-4o-mini"
    assert "google/gemma-4-12b-qat" not in harness.model_combo.items
    assert harness.model_combo.items == ["gpt-4o-mini", "chatgpt-image-latest"]
    assert harness.refresh_requests == []


def test_model_refresh_caches_provider_model_list_for_browsing():
    harness = _Harness()
    harness._chat_runtime_editor_provider = "openai"
    harness._pending_restored_model_name = "gpt-4o-mini"

    harness.refresh_model_list_quietly(
        quiet=True,
        preloaded_models=["gpt-4o-mini", "chatgpt-image-latest"],
    )

    cached = harness._chat_provider_model_catalogs.get("openai")
    assert [entry["id"] for entry in cached] == ["gpt-4o-mini", "chatgpt-image-latest"]


def test_vision_filter_uses_current_provider_catalog_not_last_refreshed_catalog():
    harness = _Harness()
    harness._chat_runtime_editor_provider = "lmstudio"
    harness._all_model_catalog = [
        {"id": "grok-4.20-0309-non-reasoning", "supports_images": False},
        {"id": "grok-vision-latest", "supports_images": True},
    ]
    harness._chat_provider_model_catalogs = {
        "lmstudio": [
            {"id": "google/gemma-4-12b-qat", "supports_images": False},
            {"id": "local-vision-model", "supports_images": True},
        ],
        "xai": list(harness._all_model_catalog),
    }
    harness.model_requires_vision_checkbox.setChecked(True)

    harness.on_model_requires_vision_changed(True)

    assert harness.model_combo.items == ["local-vision-model"]
    assert harness.model_combo.currentText() == "local-vision-model"
    assert "grok-vision-latest" not in harness.model_combo.items


if __name__ == "__main__":
    test_browse_provider_restores_saved_model_without_refresh()
    test_cold_browse_provider_requests_model_refresh_once()
    test_model_refresh_prefers_pending_provider_model_over_previous_combo_text()
    test_browse_provider_without_saved_model_clears_previous_provider_model()
    test_repeated_browse_provider_refreshes_stale_model_display()
    test_model_refresh_caches_provider_model_list_for_browsing()
    test_vision_filter_uses_current_provider_catalog_not_last_refreshed_catalog()
    print("smoke_chat_provider_model_tabs: ok")
