import time
from pathlib import Path

from PySide6 import QtWidgets

from addons.visual_reply.runtime_config import (
    is_valid_visual_reply_size,
    normalize_visual_reply_size,
    size_labels_for_provider,
)
from addons.visual_reply import state as visual_reply_state
from addons.visual_reply.providers import (
    default_model_for_provider,
    known_default_models,
    model_override_for_provider,
    normalize_model_for_provider,
    provider_label_from_value,
    provider_setting_from_config,
    updated_provider_settings,
    provider_value_from_label,
)
from core.addons.qt_host_services import QtRuntimeConfigService
from ui.panels.input_dialog import QtInputDialog
try:
    import shiboken6
except Exception:  # pragma: no cover
    shiboken6 = None
try:
    from PySide6 import QtWidgets
except Exception:  # pragma: no cover
    QtWidgets = None


def _runtime_config_service(backend):
    return QtRuntimeConfigService(backend)


def _runtime_config(backend):
    return _runtime_config_service(backend).snapshot()


def _update_runtime_config(backend, key, value):
    key = str(key)
    service = _runtime_config_service(backend)
    snapshot = service.snapshot()
    if key in snapshot:
        return service.update(key, value)
    if key.startswith("visual_reply_"):
        engine = service._engine()
        config = getattr(engine, "RUNTIME_CONFIG", None)
        if isinstance(config, dict):
            config[key] = value
    return None


def _qt_widget_alive(widget):
    if widget is None:
        return False
    if shiboken6 is None:
        return True
    try:
        return bool(shiboken6.isValid(widget))
    except Exception:
        return False


def _backend_widget(backend, name):
    getter = getattr(backend, "_live_widget_attr", None)
    if callable(getter):
        try:
            widget = getter(str(name or ""))
        except Exception:
            widget = None
        if _qt_widget_alive(widget):
            return widget
    widget = getattr(backend, str(name or ""), None)
    return widget if _qt_widget_alive(widget) else None


def visual_reply_mode_label_from_value(value):
    return "Auto" if str(value or "off").strip().lower() == "auto" else "Off"


def visual_reply_mode_value_from_label(label):
    return "off" if str(label or "").strip().lower() == "off" else "auto"


def visual_reply_provider_label_from_value(value):
    return provider_label_from_value(value)


def visual_reply_provider_value_from_label(label):
    return provider_value_from_label(label)


def _visual_reply_provider_from_live_combo(backend):
    getter = getattr(backend, "_live_combo_text", None)
    text = ""
    if callable(getter):
        try:
            text = str(getter("visual_reply_provider_combo", "") or "").strip()
        except Exception:
            text = ""
    if not text:
        widget = _backend_widget(backend, "visual_reply_provider_combo")
        if widget is not None and hasattr(widget, "currentText"):
            try:
                text = str(widget.currentText() or "").strip()
            except Exception:
                text = ""
    return visual_reply_provider_value_from_label(text) if text else ""


def _visual_reply_active_provider(backend):
    combo_provider = _visual_reply_provider_from_live_combo(backend)
    if combo_provider:
        return combo_provider
    return str(
        getattr(backend, "_visual_reply_active_provider", "")
        or _runtime_config(backend).get("visual_reply_provider", "openai")
        or "openai"
    ).strip().lower()


def _visual_reply_view_provider(backend):
    view_provider = str(getattr(backend, "_visual_reply_view_provider", "") or "").strip()
    if view_provider:
        return visual_reply_provider_value_from_label(view_provider)
    return _visual_reply_active_provider(backend)


def _visual_reply_view_is_active(backend, provider=None):
    view_provider = str(provider or _visual_reply_view_provider(backend) or "openai").strip().lower()
    return view_provider == _visual_reply_active_provider(backend)


def _capture_visual_reply_provider_widgets(backend, provider):
    provider = str(provider or "").strip().lower()
    if not provider:
        return
    size_combo = _backend_widget(backend, "visual_reply_size_combo")
    if size_combo is not None and hasattr(size_combo, "currentText"):
        current_size = normalize_visual_reply_size(str(size_combo.currentText() or ""), provider)
        _update_visual_reply_provider_setting(backend, provider, "size", current_size)
    model_edit = _backend_widget(backend, "visual_reply_model_edit")
    if model_edit is not None and hasattr(model_edit, "text"):
        current_model = str(model_edit.text() or "").strip()
        _update_visual_reply_provider_setting(
            backend,
            provider,
            "model",
            visual_reply_model_override_for_provider(provider, current_model),
        )


def set_visual_reply_view_provider(backend, provider, *, refresh=True):
    previous_provider = _visual_reply_view_provider(backend)
    if previous_provider:
        _capture_visual_reply_provider_widgets(backend, previous_provider)
    provider = visual_reply_provider_value_from_label(provider)
    setattr(backend, "_visual_reply_view_provider", provider)
    if refresh:
        sync_visual_reply_size_field(backend, provider)
        sync_visual_reply_model_field(backend, provider)
        sync_visual_reply_api_key_field(backend, provider)
        sync_visual_reply_comfyui_cleanup_field(backend, provider)
        sync_visual_reply_comfyui_workflow_button(backend, provider)
        refresh_visual_reply_hint(backend)
    return provider


def visual_reply_size_label_from_value(value, provider=None):
    size = normalize_visual_reply_size(value, provider)
    return "Auto" if size == "auto" else size


def visual_reply_size_for_provider(backend, provider):
    provider = str(provider or "openai").strip().lower()
    config = _runtime_config(backend)
    provider_size = str(provider_setting_from_config(config, provider, "size", "") or "").strip()
    if provider_size:
        return normalize_visual_reply_size(provider_size, provider)
    active_provider = str(config.get("visual_reply_provider", "openai") or "openai").strip().lower()
    if active_provider == provider:
        return normalize_visual_reply_size(config.get("visual_reply_size", "1024x1024"), provider)
    return "1024x1024"


def visual_reply_default_model_for_provider(provider):
    return default_model_for_provider(provider)


def visual_reply_known_default_models():
    return known_default_models()


def visual_reply_model_override_for_provider(provider, model):
    return model_override_for_provider(provider, model)


def visual_reply_normalize_model_for_provider(provider, model):
    return normalize_model_for_provider(provider, model)


def visual_reply_model_for_provider(backend, provider):
    provider = str(provider or "openai").strip().lower()
    config = _runtime_config(backend)
    default_model = visual_reply_default_model_for_provider(provider)
    provider_model = str(provider_setting_from_config(config, provider, "model", "") or "").strip()
    if provider_model:
        return visual_reply_normalize_model_for_provider(provider, provider_model)
    active_provider = str(config.get("visual_reply_provider", "openai") or "openai").strip().lower()
    if active_provider == provider:
        return visual_reply_normalize_model_for_provider(provider, config.get("visual_reply_model", default_model))
    return default_model


def visual_reply_model_label_for_provider(provider):
    return "Workflow JSON" if str(provider or "").strip().lower() == "comfyui" else "Image Model"


def visual_reply_api_label_for_provider(provider):
    return "Server URL" if str(provider or "").strip().lower() == "comfyui" else "API Key"


def visual_reply_model_placeholder_for_provider(provider):
    if str(provider or "").strip().lower() == "comfyui":
        return "Local/UNC path, workflows/name.json, template:name, or JSON URL"
    return ""


def visual_reply_api_placeholder_for_provider(provider):
    if str(provider or "").strip().lower() == "comfyui":
        return "http://127.0.0.1:8188"
    return f"{visual_reply_provider_label_from_value(provider)} API key (optional; env vars still work)"


def visual_reply_api_key_for_provider(backend, provider):
    return str(provider_setting_from_config(_runtime_config(backend), provider, "api_key", "") or "").strip()


COMFYUI_CLEANUP_LABELS = {
    "keep_cache": "Keep cache",
    "free_memory": "Free memory",
    "unload_models": "Unload models + free memory",
}


def visual_reply_comfyui_cleanup_label_from_value(value):
    mode = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if mode in {"off", "none", "keep", "keep_loaded", "keep_models", "keep_cache"}:
        return COMFYUI_CLEANUP_LABELS["keep_cache"]
    if mode in {"free", "free_memory", "empty_cache", "soft_empty_cache"}:
        return COMFYUI_CLEANUP_LABELS["free_memory"]
    if mode in {"unload", "unload_models", "full", "full_cleanup", "unload_models_free_memory"}:
        return COMFYUI_CLEANUP_LABELS["unload_models"]
    return COMFYUI_CLEANUP_LABELS["keep_cache"]


def visual_reply_comfyui_cleanup_value_from_label(label):
    text = str(label or "").strip().lower()
    for value, known_label in COMFYUI_CLEANUP_LABELS.items():
        if text == known_label.lower():
            return value
    if "unload" in text:
        return "unload_models"
    if "free" in text:
        return "free_memory"
    return "keep_cache"


def visual_reply_comfyui_cleanup_for_backend(backend):
    raw = provider_setting_from_config(_runtime_config(backend), "comfyui", "cleanup_mode", "keep_cache")
    return visual_reply_comfyui_cleanup_value_from_label(visual_reply_comfyui_cleanup_label_from_value(raw))


def _update_visual_reply_provider_setting(backend, provider, role, value):
    settings = updated_provider_settings(_runtime_config(backend), provider, role, value)
    return _update_runtime_config(backend, "visual_reply_provider_settings", settings)


def sync_visual_reply_api_key_field(backend, provider=None):
    widget = _backend_widget(backend, "visual_reply_api_key_edit")
    if widget is None or not hasattr(widget, "setText"):
        return
    if provider is None:
        provider = _visual_reply_view_provider(backend)
    label = visual_reply_provider_label_from_value(provider)
    previous = False
    try:
        previous = bool(widget.blockSignals(True))
        widget.setText(visual_reply_api_key_for_provider(backend, provider))
        if QtWidgets is not None and hasattr(widget, "setEchoMode"):
            echo_mode = QtWidgets.QLineEdit.Normal if str(provider or "").strip().lower() == "comfyui" else QtWidgets.QLineEdit.Password
            widget.setEchoMode(echo_mode)
        if hasattr(widget, "setPlaceholderText"):
            widget.setPlaceholderText(visual_reply_api_placeholder_for_provider(provider))
        if hasattr(widget, "setToolTip"):
            if str(provider or "").strip().lower() == "comfyui":
                widget.setToolTip("ComfyUI server URL. Local default: http://127.0.0.1:8188")
            else:
                widget.setToolTip(f"Optional {label} API key saved in the local session for Visual Reply image generation.")
    finally:
        try:
            widget.blockSignals(previous)
        except Exception:
            pass


def sync_visual_reply_model_field(backend, provider=None):
    widget = _backend_widget(backend, "visual_reply_model_edit")
    if widget is None or not hasattr(widget, "setText"):
        return
    if provider is None:
        provider = _visual_reply_view_provider(backend)
    model_name = visual_reply_model_for_provider(backend, provider)
    previous = False
    try:
        previous = bool(widget.blockSignals(True))
        widget.setText(model_name)
        if hasattr(widget, "setPlaceholderText"):
            widget.setPlaceholderText(visual_reply_model_placeholder_for_provider(provider))
        if hasattr(widget, "setToolTip"):
            if str(provider or "").strip().lower() == "comfyui":
                widget.setToolTip(
                    "ComfyUI workflow JSON visible to NeuralCompanion. Use a local/UNC path, "
                    "an http(s) JSON URL, userdata:workflows/name.json, workflows/name.json, or template:name."
                )
            else:
                widget.setToolTip("Image model name used by the selected Visual Reply provider.")
    finally:
        try:
            widget.blockSignals(previous)
        except Exception:
            pass


def configure_visual_reply_size_field(widget, provider):
    if widget is None:
        return
    provider = str(provider or "openai").strip().lower()
    is_comfyui = provider == "comfyui"
    labels = size_labels_for_provider(provider)
    current_text = str(widget.currentText() if hasattr(widget, "currentText") else "").strip()
    previous = False
    try:
        if hasattr(widget, "blockSignals"):
            previous = bool(widget.blockSignals(True))
        if hasattr(widget, "setMinimumWidth"):
            widget.setMinimumWidth(146 if is_comfyui else 118)
        if hasattr(widget, "setMinimumContentsLength"):
            widget.setMinimumContentsLength(10 if is_comfyui else 8)
        if hasattr(widget, "setSizeAdjustPolicy") and QtWidgets is not None:
            widget.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        if hasattr(widget, "setEditable"):
            widget.setEditable(is_comfyui)
        if hasattr(widget, "clear") and hasattr(widget, "addItems"):
            widget.clear()
            widget.addItems(labels)
        if current_text and hasattr(widget, "setCurrentText"):
            normalized = normalize_visual_reply_size(current_text, provider)
            widget.setCurrentText(visual_reply_size_label_from_value(normalized, provider))
        if hasattr(widget, "lineEdit") and widget.lineEdit() is not None:
            line_edit = widget.lineEdit()
            line_edit.setPlaceholderText("WIDTHxHEIGHT" if is_comfyui else "")
            if hasattr(line_edit, "setMinimumWidth"):
                line_edit.setMinimumWidth(104 if is_comfyui else 80)
        if hasattr(widget, "setToolTip"):
            if is_comfyui:
                widget.setToolTip(
                    "ComfyUI image size. Pick a preset or type WIDTHxHEIGHT manually. "
                    "Custom dimensions must be multiples of 8 between 64 and 8192."
                )
            else:
                widget.setToolTip("Image size supported by the selected hosted image provider.")
    finally:
        try:
            widget.blockSignals(previous)
        except Exception:
            pass


def sync_visual_reply_size_field(backend, provider=None):
    widget = _backend_widget(backend, "visual_reply_size_combo")
    if widget is None or not hasattr(widget, "setCurrentText"):
        return
    if provider is None:
        provider = _visual_reply_view_provider(backend)
    size = visual_reply_size_for_provider(backend, provider)
    previous = False
    try:
        previous = bool(widget.blockSignals(True))
        configure_visual_reply_size_field(widget, provider)
        widget.setCurrentText(visual_reply_size_label_from_value(size, provider))
    finally:
        try:
            widget.blockSignals(previous)
        except Exception:
            pass


def sync_visual_reply_comfyui_cleanup_field(backend, provider=None):
    combo = _backend_widget(backend, "visual_reply_comfyui_cleanup_combo")
    label = _backend_widget(backend, "visual_reply_comfyui_cleanup_label")
    if provider is None:
        provider = _visual_reply_view_provider(backend)
    is_comfyui = str(provider or "").strip().lower() == "comfyui"
    for widget in (label, combo):
        if widget is not None and hasattr(widget, "setVisible"):
            widget.setVisible(is_comfyui)
    if combo is None or not hasattr(combo, "setCurrentText"):
        return
    previous = False
    try:
        previous = bool(combo.blockSignals(True))
        combo.setCurrentText(visual_reply_comfyui_cleanup_label_from_value(visual_reply_comfyui_cleanup_for_backend(backend)))
        if hasattr(combo, "setToolTip"):
            combo.setToolTip(
                "Keep cache is fastest. Free memory asks ComfyUI to clear unused VRAM/RAM after each image. "
                "Unload models frees more memory but the next image will reload models."
            )
    finally:
        try:
            combo.blockSignals(previous)
        except Exception:
            pass


def sync_visual_reply_comfyui_workflow_button(backend, provider=None):
    button = _backend_widget(backend, "visual_reply_comfyui_workflow_refresh_button")
    if button is None:
        return
    if provider is None:
        provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    is_comfyui = str(provider or "").strip().lower() == "comfyui"
    try:
        button.setVisible(is_comfyui)
        button.setEnabled(is_comfyui)
        button.setToolTip("Fetch workflow templates and saved workflow names from the configured ComfyUI server.")
    except Exception:
        pass


def refresh_visual_reply_comfyui_workflow_choices(backend):
    provider = _visual_reply_view_provider(backend)
    if provider != "comfyui":
        return
    model_edit = _backend_widget(backend, "visual_reply_model_edit")
    if model_edit is None or not hasattr(model_edit, "setText"):
        return
    server_url = visual_reply_api_key_for_provider(backend, "comfyui") or "http://127.0.0.1:8188"
    parent = model_edit.window() if hasattr(model_edit, "window") else None
    try:
        from addons.visual_reply.generation import list_comfyui_workflow_choices

        choices = list_comfyui_workflow_choices(server_url)
    except Exception as exc:
        if QtWidgets is not None:
            QtWidgets.QMessageBox.warning(parent, "ComfyUI Workflows", f"Could not read workflows from ComfyUI:\n{exc}")
        return
    if not choices:
        if QtWidgets is not None:
            QtWidgets.QMessageBox.information(
                parent,
                "ComfyUI Workflows",
                "No workflow templates or saved user workflows were returned by this ComfyUI server.",
            )
        return
    current = str(model_edit.text() or "").strip()
    default_index = choices.index(current) if current in choices else 0
    choice, accepted = QtWidgets.QInputDialog.getItem(
        parent,
        "ComfyUI Workflows",
        "Choose a workflow reference:",
        choices,
        default_index,
        False,
    )
    if accepted and str(choice or "").strip():
        model_edit.setText(str(choice or "").strip())
        on_visual_reply_model_changed(backend)


def on_visual_reply_api_key_changed(backend):
    provider = _visual_reply_view_provider(backend)
    edit = _backend_widget(backend, "visual_reply_api_key_edit")
    api_key = str(edit.text() if edit is not None and hasattr(edit, "text") else "").strip()
    _update_visual_reply_provider_setting(backend, provider, "api_key", api_key)
    refresh_hint = getattr(backend, "_refresh_visual_reply_hint", None)
    if callable(refresh_hint):
        refresh_hint()
    refresh_setup = getattr(backend, "_refresh_runtime_provider_setup_card", None)
    if callable(refresh_setup):
        refresh_setup("visual")
    save_session = getattr(backend, "save_session", None)
    if callable(save_session):
        save_session()


def refresh_visual_reply_hint(backend):
    hint = backend._live_widget_attr("visual_reply_hint")
    if hint is None:
        return
    mode = visual_reply_mode_value_from_label(backend._live_combo_text("visual_reply_mode_combo", "Auto"))
    provider = _visual_reply_view_provider(backend)
    active_provider = _visual_reply_active_provider(backend)
    size = normalize_visual_reply_size(
        backend._live_combo_text("visual_reply_size_combo", visual_reply_size_for_provider(backend, provider)),
        provider,
    )
    default_model = visual_reply_default_model_for_provider(provider)
    model = backend._live_text("visual_reply_model_edit", visual_reply_model_for_provider(backend, provider)).strip() or default_model
    auto_show = backend._live_checked("visual_reply_auto_show_checkbox", True)
    model_label = backend._live_widget_attr("visual_reply_model_label")
    if model_label is not None and hasattr(model_label, "setText"):
        model_label.setText(visual_reply_model_label_for_provider(provider))
    api_label = backend._live_widget_attr("visual_reply_api_key_label")
    if api_label is not None and hasattr(api_label, "setText"):
        api_label.setText(visual_reply_api_label_for_provider(provider))
    sync_visual_reply_size_field(backend, provider)
    sync_visual_reply_model_field(backend, provider)
    sync_visual_reply_api_key_field(backend, provider)
    sync_visual_reply_comfyui_cleanup_field(backend, provider)
    sync_visual_reply_comfyui_workflow_button(backend, provider)
    if mode == "off":
        title = "Visual Reply Runtime - Off"
        summary = "Visual replies are disabled. NC will not ask the LLM for [visualize: ...] tags or generate images automatically."
    else:
        dock_text = "The dock will auto-show when a request starts or finishes." if auto_show else "The dock stays where it is; use Show Visual Reply if you want to watch generation live."
        provider_text = visual_reply_provider_label_from_value(provider)
        active_note = ""
        request_label = "Current backend request"
        if provider != active_provider:
            active_label = visual_reply_provider_label_from_value(active_provider)
            active_note = f" Viewing {provider_text} settings; active runtime remains {active_label}."
            request_label = "Current tab settings"
        if provider == "comfyui":
            server_url = visual_reply_api_key_for_provider(backend, provider) or "http://127.0.0.1:8188"
            cleanup_label = visual_reply_comfyui_cleanup_label_from_value(visual_reply_comfyui_cleanup_for_backend(backend))
            title = f"Visual Reply Runtime - ComfyUI"
            summary = (
                "Visual replies are enabled through a local/LAN ComfyUI server. NC injects the prompt into the configured workflow, queues it through ComfyUI, "
                f"then displays the generated output image. {request_label}: ComfyUI at {server_url}, {size}, workflow '{model}', cleanup: {cleanup_label}. {dock_text}{active_note}"
            )
        else:
            title = f"Visual Reply Runtime - {provider_text} / {model}"
            key_text = "A local API key is set for this provider." if visual_reply_api_key_for_provider(backend, provider) else "API key can come from this field or the provider environment variable."
            summary = (
                f"Visual replies are enabled. Automatic image generation still follows the NC auto-visual toggle; when allowed, NC may append one [visualize: ...] tag when an image would help. "
                f"{request_label}: {provider_text}, {size}, model '{model}'. {key_text} {dock_text}{active_note}"
            )
    hint.setText(summary)
    runtime_box = backend._live_widget_attr("visual_reply_runtime_box")
    if runtime_box is not None and hasattr(runtime_box, "setTitle"):
        try:
            runtime_box.setTitle(title)
            runtime_box.setToolTip(summary)
        except Exception:
            pass


def on_visual_reply_mode_changed(backend, choice):
    mode = visual_reply_mode_value_from_label(choice)
    _update_runtime_config(backend, "visual_reply_mode", mode)
    _update_runtime_config(backend, "visual_replies_enabled", mode != "off")
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_mode", "value": mode})
    backend.save_session()


def on_visual_reply_provider_changed(backend, choice):
    provider = visual_reply_provider_value_from_label(choice)
    _capture_visual_reply_provider_widgets(backend, _visual_reply_view_provider(backend))
    next_size = visual_reply_size_for_provider(backend, provider)
    next_model = visual_reply_model_for_provider(backend, provider)
    _update_runtime_config(backend, "visual_reply_provider", provider)
    _update_runtime_config(backend, "visual_reply_size", next_size)
    _update_runtime_config(backend, "visual_reply_model", next_model)
    setattr(backend, "_visual_reply_active_provider", provider)
    setattr(backend, "_visual_reply_view_provider", provider)
    sync_visual_reply_size_field(backend, provider)
    sync_visual_reply_model_field(backend, provider)
    sync_visual_reply_api_key_field(backend, provider)
    sync_visual_reply_comfyui_cleanup_field(backend, provider)
    refresh_visual_reply_hint(backend)
    refresh_setup = getattr(backend, "_refresh_runtime_provider_setup_card", None)
    if callable(refresh_setup):
        refresh_setup("visual")
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_provider", "value": provider})
    backend.save_session()


def on_visual_reply_size_changed(backend, choice):
    provider = _visual_reply_view_provider(backend)
    raw_choice = str(choice or "").strip()
    if provider == "comfyui" and raw_choice and not is_valid_visual_reply_size(raw_choice, provider):
        return
    size = normalize_visual_reply_size(choice, provider)
    size_combo = _backend_widget(backend, "visual_reply_size_combo")
    if size_combo is not None:
        label = visual_reply_size_label_from_value(size, provider)
        if size_combo.currentText() != label:
            size_combo.setCurrentText(label)
    _update_visual_reply_provider_setting(backend, provider, "size", size)
    if _visual_reply_view_is_active(backend, provider):
        _update_runtime_config(backend, "visual_reply_size", size)
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_size", "value": size})
    backend.save_session()


def on_visual_reply_model_changed(backend):
    provider = _visual_reply_view_provider(backend)
    model_edit = _backend_widget(backend, "visual_reply_model_edit")
    raw_model_name = str(model_edit.text() if model_edit is not None and hasattr(model_edit, "text") else "").strip()
    if raw_model_name:
        model_name = visual_reply_normalize_model_for_provider(provider, raw_model_name)
        _update_visual_reply_provider_setting(backend, provider, "model", visual_reply_model_override_for_provider(provider, model_name))
    else:
        model_name = visual_reply_default_model_for_provider(provider)
        _update_visual_reply_provider_setting(backend, provider, "model", "")
    if model_edit is not None and model_edit.text().strip() != model_name:
        model_edit.setText(model_name)
    if _visual_reply_view_is_active(backend, provider):
        _update_runtime_config(backend, "visual_reply_model", model_name)
    refresh_visual_reply_hint(backend)
    refresh_setup = getattr(backend, "_refresh_runtime_provider_setup_card", None)
    if callable(refresh_setup):
        refresh_setup("visual")
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_model", "value": model_name})
    backend.save_session()


def on_visual_reply_auto_show_changed(backend, checked):
    enabled = bool(checked)
    _update_runtime_config(backend, "visual_reply_auto_show_dock", enabled)
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_auto_show_dock", "value": enabled})
    backend.save_session()


def on_visual_reply_comfyui_cleanup_changed(backend, choice):
    mode = visual_reply_comfyui_cleanup_value_from_label(choice)
    _update_visual_reply_provider_setting(backend, "comfyui", "cleanup_mode", mode)
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_comfyui_cleanup_mode", "value": mode})
    save_session = getattr(backend, "save_session", None)
    if callable(save_session):
        save_session()


class BackendVisualReplyRuntimeMixin:
    """Host-facing Visual Reply runtime settings and image/caption controls."""

    def _visual_reply_mode_label_from_value(self, value):
        return visual_reply_mode_label_from_value(value)

    def _visual_reply_mode_value_from_label(self, label):
        return visual_reply_mode_value_from_label(label)

    def _visual_reply_provider_label_from_value(self, value):
        return visual_reply_provider_label_from_value(value)

    def _visual_reply_provider_value_from_label(self, label):
        return visual_reply_provider_value_from_label(label)

    def _normalize_visual_reply_size(self, value, provider=None):
        return normalize_visual_reply_size(value, provider)

    def _visual_reply_size_label_from_value(self, value, provider=None):
        return visual_reply_size_label_from_value(value, provider)

    def _visual_reply_default_model_for_provider(self, provider):
        return visual_reply_default_model_for_provider(provider)

    def _visual_reply_api_key_for_provider(self, provider):
        return visual_reply_api_key_for_provider(self, provider)

    def _sync_visual_reply_api_key_field(self, provider=None):
        sync_visual_reply_api_key_field(self, provider)

    def _sync_visual_reply_model_field(self, provider=None):
        sync_visual_reply_model_field(self, provider)

    def _sync_visual_reply_size_field(self, provider=None):
        sync_visual_reply_size_field(self, provider)

    def _sync_visual_reply_comfyui_cleanup_field(self, provider=None):
        sync_visual_reply_comfyui_cleanup_field(self, provider)

    def _refresh_visual_reply_hint(self):
        refresh_visual_reply_hint(self)

    def _set_visual_reply_view_provider(self, provider, *, refresh=True):
        return set_visual_reply_view_provider(self, provider, refresh=refresh)

    def on_visual_reply_mode_changed(self, choice):
        on_visual_reply_mode_changed(self, choice)

    def on_visual_reply_provider_changed(self, choice):
        on_visual_reply_provider_changed(self, choice)

    def on_visual_reply_size_changed(self, choice):
        on_visual_reply_size_changed(self, choice)

    def on_visual_reply_model_changed(self):
        on_visual_reply_model_changed(self)

    def on_visual_reply_api_key_changed(self):
        on_visual_reply_api_key_changed(self)

    def on_visual_reply_auto_show_changed(self, checked):
        on_visual_reply_auto_show_changed(self, checked)

    def on_visual_reply_comfyui_cleanup_changed(self, choice):
        on_visual_reply_comfyui_cleanup_changed(self, choice)

    def show_visual_reply_dock(self):
        if not self._visual_reply_addon_enabled():
            return
        if hasattr(self, "visual_reply_dock"):
            self.visual_reply_dock.show()
            self.visual_reply_dock.raise_()
        if hasattr(self, "visual_reply_panel"):
            self.visual_reply_panel.show()
        print("[QtGUI] Visual Reply dock shown.")

    def clear_visual_reply(self, status_text="Visual Reply idle", detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.", *, auto_show=False):
        panel = getattr(self, "visual_reply_panel", None)
        if panel is None:
            return False
        panel.clear_visual_reply(status_text=status_text, detail_text=detail_text)
        visual_reply_state.set_current_visual_reply_data(
            {
                "status": "idle",
                "status_text": str(status_text or "Visual Reply idle"),
                "detail_text": str(detail_text or "No visual reply yet.\nWhen NC creates an image, it will appear here."),
                "image_path": "",
                "caption": "",
                "request_id": "",
                "updated_at": time.time(),
            }
        )
        if auto_show:
            self.show_visual_reply_dock()
        return True

    def set_visual_reply_loading(self, status_text="Visual Reply generating...", detail_text="Preparing image...", *, auto_show=True):
        panel = getattr(self, "visual_reply_panel", None)
        if panel is None:
            return False
        panel.set_loading_state(status_text=status_text, detail_text=detail_text)
        visual_reply_state.set_current_visual_reply_data(
            {
                "status": "loading",
                "status_text": str(status_text or "Visual Reply generating..."),
                "detail_text": str(detail_text or "Preparing image..."),
                "image_path": "",
                "caption": "",
                "request_id": "",
                "updated_at": time.time(),
            }
        )
        if auto_show:
            self.show_visual_reply_dock()
        return True

    def show_visual_reply_image(self, image_path, caption="", status_text="Visual Reply", *, auto_show=True):
        panel = getattr(self, "visual_reply_panel", None)
        if panel is None:
            return False
        loaded = bool(panel.show_image(image_path, status_text=status_text, caption=caption))
        if loaded:
            resolved_caption = str(getattr(panel, "current_caption", "") or "").strip()
            visual_reply_state.set_current_visual_reply_data(
                {
                    "status": "ready",
                    "status_text": str(status_text or "Visual Reply"),
                    "detail_text": "",
                    "image_path": str(image_path or ""),
                    "caption": resolved_caption,
                    "request_id": "",
                    "updated_at": time.time(),
                }
            )
        if loaded and auto_show:
            self.show_visual_reply_dock()
        return loaded

    def set_visual_reply_caption(self, caption=""):
        panel = getattr(self, "visual_reply_panel", None)
        if panel is None:
            return False
        updated = bool(panel.set_caption(caption))
        if updated:
            visual_reply_state.update_current_visual_reply_data(caption=str(caption or ""))
        return updated

    def prompt_visual_reply_image(self):
        panel = getattr(self, "visual_reply_panel", None)
        current_image_path = str(getattr(panel, "current_image_path", "") or "").strip()
        start_dir = str(Path(current_image_path).parent) if current_image_path else str(Path.cwd())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Visual Reply Image",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not path:
            return False
        loaded = self.show_visual_reply_image(path, status_text="Visual Reply", auto_show=True)
        if loaded:
            print(f"[QtGUI] Visual Reply image loaded: {path}")
        return loaded

    def prompt_visual_reply_caption(self):
        panel = getattr(self, "visual_reply_panel", None)
        current = panel.caption_label.text().strip() if panel is not None and hasattr(panel, "caption_label") else ""
        caption = QtInputDialog.get_text("Visual Reply Caption", "Enter Caption:", self, default_text=current)
        if caption is None:
            return False
        self.set_visual_reply_caption(caption)
        print("[QtGUI] Visual Reply caption updated.")
        return True
