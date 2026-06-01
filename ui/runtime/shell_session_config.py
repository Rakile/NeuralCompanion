"""Preset, session, and config helpers for the lightweight Designer UI shell."""

import json
from pathlib import Path

_APP_FILE = None


def configure_shell_session_config_dependencies(namespace):
    """Inject qt_app-owned helpers without importing the heavy app module."""
    global _APP_FILE
    namespace = dict(namespace or {})
    globals().update(namespace)
    _APP_FILE = namespace.get("__file__", _APP_FILE)


def _app_root():
    if _APP_FILE:
        return Path(_APP_FILE).resolve().parent
    return Path.cwd()


def _ui_shell_preset_names():
    presets_dir = _app_root() / "presets"
    names = []
    try:
        for item in sorted(presets_dir.glob("*.json"), key=lambda path: path.stem.lower()):
            names.append(item.stem)
    except Exception:
        pass
    return names


def _ui_shell_load_preset_payload(name):
    preset_name = str(name or "").strip()
    if not preset_name or preset_name.lower() in {"select preset...", "no presets", "no presets found"}:
        return {}
    path = _app_root() / "presets" / f"{preset_name}.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _bind_ui_shell_preset_session_controls(window, providers):
    preset_combo = _ui_shell_find_object(window, "preset_combo")
    preset_label = _ui_shell_find_object(window, "preset_label")
    load_button = _ui_shell_find_object(window, "btn_preset_load")
    save_button = _ui_shell_find_object(window, "btn_preset_save")
    save_as_button = _ui_shell_find_object(window, "btn_preset_save_as")
    delete_button = _ui_shell_find_object(window, "btn_preset_delete")
    session_hint = _ui_shell_find_object(window, "session_hint_label")
    session_buttons = [
        _ui_shell_find_object(window, "btn_save_chat_session"),
        _ui_shell_find_object(window, "btn_save_chat_session_as"),
        _ui_shell_find_object(window, "btn_load_chat_session"),
        _ui_shell_find_object(window, "btn_reset_chat_session"),
    ]

    presets = _ui_shell_preset_names()
    session = _read_ui_shell_session_snapshot()
    selected = str(session.get("last_preset") or session.get("active_preset_name") or "").strip()
    if preset_combo is not None and hasattr(preset_combo, "clear"):
        _ui_shell_combo_set_items(preset_combo, presets or ["No presets found"])
        if selected:
            _ui_shell_combo_select_label(preset_combo, selected)
        preset_combo.setToolTip("Shell-local preset selector. Load previews a preset without saving or mutating runtime state.")
    if preset_label is not None and hasattr(preset_label, "setText"):
        preset_label.setText("Preset")

    state = {"loaded_preset": ""}

    def update_load_button():
        if load_button is None or not hasattr(load_button, "setEnabled"):
            return
        current = str(preset_combo.currentText() if preset_combo is not None and hasattr(preset_combo, "currentText") else "").strip()
        enabled = bool(current and current in presets)
        load_button.setEnabled(enabled)
        load_button.setToolTip(
            "Preview this preset in the Designer shell. No session file or runtime config is changed."
            if enabled
            else "No preset is available to preview."
        )

    def preview_selected_preset():
        current = str(preset_combo.currentText() if preset_combo is not None and hasattr(preset_combo, "currentText") else "").strip()
        payload = _ui_shell_load_preset_payload(current)
        if not payload:
            return
        state["loaded_preset"] = current
        _bind_ui_shell_chat_runtime(window, providers, session_override=payload)
        if session_hint is not None and hasattr(session_hint, "setText"):
            provider = str(payload.get("chat_provider") or "").strip() or "saved provider"
            model = str(payload.get("model_name") or "").strip() or "saved model"
            session_hint.setText(
                f"Shell preview loaded preset '{current}' into Chat Runtime controls "
                f"({provider} / {model}). Runtime state was not changed."
            )

    if preset_combo is not None and hasattr(preset_combo, "currentTextChanged"):
        preset_combo.currentTextChanged.connect(lambda _text: update_load_button())
    if load_button is not None and hasattr(load_button, "clicked"):
        load_button.clicked.connect(preview_selected_preset)
    update_load_button()

    for button, label in (
        (save_button, "Preset Save is deferred in shell mode."),
        (save_as_button, "Preset Save As is deferred in shell mode."),
        (delete_button, "Preset Delete is deferred in shell mode."),
    ):
        if button is not None and hasattr(button, "setEnabled"):
            button.setEnabled(False)
            button.setToolTip(label)

    for button in session_buttons:
        if button is not None and hasattr(button, "setEnabled"):
            button.setEnabled(False)
            button.setToolTip("Chat session file/runtime mutation is deferred in shell mode.")
    if session_hint is not None and hasattr(session_hint, "setText"):
        session_hint.setText(
            "Shell-local session binding: preset Load previews saved Chat Runtime values; "
            "Save/Delete and chat-context file operations remain deferred."
        )

    return {
        "bound": preset_combo is not None,
        "presets": len(presets),
        "selected": str(preset_combo.currentText() if preset_combo is not None and hasattr(preset_combo, "currentText") else "").strip(),
        "session_buttons_deferred": sum(1 for button in session_buttons if button is not None),
    }


def _ui_shell_combo_set_items(combo, labels):
    if combo is None or not hasattr(combo, "clear"):
        return
    combo.blockSignals(True)
    try:
        combo.clear()
        for label in labels:
            combo.addItem(str(label))
    finally:
        combo.blockSignals(False)


def _ui_shell_combo_select_label(combo, label):
    if combo is None or not hasattr(combo, "count"):
        return False
    target = str(label or "").strip()
    if not target:
        return False
    combo.blockSignals(True)
    try:
        for index in range(combo.count()):
            if str(combo.itemText(index) or "").strip().lower() == target.lower():
                combo.setCurrentIndex(index)
                return True
        if hasattr(combo, "addItem"):
            combo.addItem(target)
            combo.setCurrentIndex(combo.count() - 1)
            return True
    finally:
        combo.blockSignals(False)
    return False


def _ui_shell_set_spin_value(widget, value):
    if widget is None or not hasattr(widget, "setValue"):
        return False
    try:
        widget.blockSignals(True)
        widget.setValue(int(value))
        return True
    except Exception:
        return False
    finally:
        try:
            widget.blockSignals(False)
        except Exception:
            pass


def _ui_shell_set_slider_value(widget, value):
    if widget is None or not hasattr(widget, "setValue"):
        return False
    try:
        widget.blockSignals(True)
        widget.setValue(int(value))
        return True
    except Exception:
        return False
    finally:
        try:
            widget.blockSignals(False)
        except Exception:
            pass


def _ui_shell_set_double_value(widget, value):
    if widget is None or not hasattr(widget, "setValue"):
        return False
    try:
        widget.blockSignals(True)
        widget.setValue(float(value))
        return True
    except Exception:
        return False
    finally:
        try:
            widget.blockSignals(False)
        except Exception:
            pass


def _ui_shell_set_checked(widget, value):
    if widget is None or not hasattr(widget, "setChecked"):
        return False
    try:
        widget.blockSignals(True)
        widget.setChecked(bool(value))
        return True
    except Exception:
        return False
    finally:
        try:
            widget.blockSignals(False)
        except Exception:
            pass


def _ui_shell_set_read_only_tooltip(widget, detail=""):
    if widget is None or not hasattr(widget, "setToolTip"):
        return
    suffix = f" {detail}" if detail else ""
    widget.setToolTip(f"Read-only shell preview. Changes are not saved or applied.{suffix}")


def _ui_shell_performance_profiles_dir():
    return _app_root() / "performance_profiles"


def _ui_shell_body_configs_dir():
    return _app_root() / "body_configs"


def _ui_shell_load_json(path: Path, default=None):
    fallback = {} if default is None else default
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, type(fallback)) else fallback
    except Exception:
        return fallback


def _ui_shell_list_performance_profiles():
    root = _ui_shell_performance_profiles_dir()
    items = []
    try:
        paths = sorted(
            [path for path in root.glob("*.json") if path.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        paths = []
    for path in paths:
        payload = _ui_shell_load_json(path, {})
        name = str(path.stem or "").strip()
        settings = dict(payload.get("settings_to_apply") or {})
        items.append({
            "name": name,
            "display_name": str(payload.get("display_name", payload.get("saved_name", name)) or name),
            "description": str(payload.get("description", "") or ""),
            "bundled": bool(payload.get("bundled", False)),
            "recommended": bool(payload.get("recommended", False)),
            "path": str(path),
            "updated_at": float(payload.get("updated_at", path.stat().st_mtime) or path.stat().st_mtime),
            "stream_mode": bool(settings.get("stream_mode", False)),
            "tts_backend": str(settings.get("tts_backend", "") or ""),
            "musetalk_vram_mode": str(settings.get("musetalk_vram_mode", "") or ""),
            "confidence": float(payload.get("confidence", 0.0) or 0.0),
            "stability": float(payload.get("stability", 0.0) or 0.0),
            "sample_count": int(payload.get("sample_count", 0) or 0),
        })
    return items


def _ui_shell_performance_profile_label(item):
    name = str(item.get("display_name") or item.get("name") or "Profile").strip() or "Profile"
    prefix = "Recommended: " if item.get("recommended") else ("Starter: " if item.get("bundled") else "")
    backend = str(item.get("tts_backend") or "").title()
    vram = str(item.get("musetalk_vram_mode") or "").replace("_", " ").title()
    stream_label = "Stream" if bool(item.get("stream_mode")) else "Non-stream"
    confidence = float(item.get("confidence", 0.0) or 0.0)
    return f"{prefix}{name} | {stream_label} | {backend} | {vram} | c={confidence:.2f}"


def _ui_shell_performance_profile_payload(name):
    key = str(name or "").strip()
    if not key:
        return {}
    path = _ui_shell_performance_profiles_dir() / f"{key}.json"
    if not path.exists():
        return {}
    payload = _ui_shell_load_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _ui_shell_latest_performance_profile_payload():
    profiles = _ui_shell_list_performance_profiles()
    if not profiles:
        return {}
    return _ui_shell_performance_profile_payload(str((profiles[0] or {}).get("name") or ""))


def _ui_shell_list_body_configs():
    root = _ui_shell_body_configs_dir()
    items = []
    try:
        paths = sorted([path for path in root.glob("*.json") if path.is_file()], key=lambda item: item.stem.lower())
    except Exception:
        paths = []
    for path in paths:
        items.append(str(path.stem or "").strip())
    return [item for item in items if item]


def _ui_shell_body_config_payload(name):
    key = str(name or "").strip()
    if not key:
        return {}
    path = _ui_shell_body_configs_dir() / f"{key}.json"
    if not path.exists():
        return {}
    payload = _ui_shell_load_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _ui_shell_voice_options(window=None):
    session = dict(_read_ui_shell_session_snapshot() or {})
    names = []
    try:
        for path in sorted((_app_root() / "voices").glob("*.wav"), key=lambda item: item.name.lower()):
            names.append(path.name)
    except Exception:
        names = []
    selected = str(session.get("voice_file", "") or "").strip()
    if selected and selected not in names:
        names.append(selected)
    return names or ["No .wav found"]


def _ui_shell_combo_text_value(window, object_name, default=""):
    widget = _ui_shell_find_object(window, object_name)
    if widget is not None and hasattr(widget, "currentText"):
        try:
            text = str(widget.currentText() or "").strip()
            if text:
                return text
        except Exception:
            pass
    return str(default or "").strip()


def _ui_shell_checkbox_value(window, object_name, default=False):
    widget = _ui_shell_find_object(window, object_name)
    if widget is not None and hasattr(widget, "isChecked"):
        try:
            return bool(widget.isChecked())
        except Exception:
            pass
    return bool(default)


def _ui_shell_line_edit_value(window, object_name, default=""):
    widget = _ui_shell_find_object(window, object_name)
    if widget is not None and hasattr(widget, "text"):
        try:
            return str(widget.text() or "").strip()
        except Exception:
            pass
    return str(default or "").strip()


def _ui_shell_plain_text_value(window, object_name, default=""):
    widget = _ui_shell_find_object(window, object_name)
    if widget is not None and hasattr(widget, "toPlainText"):
        try:
            return str(widget.toPlainText() or "").strip()
        except Exception:
            pass
    return str(default or "").strip()


def _ui_shell_format_clock_seconds(seconds) -> str:
    total = max(0, int(seconds or 0))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def _ui_shell_selected_body_name(window):
    combo = _ui_shell_find_object(window, "body_combo")
    if combo is None or not hasattr(combo, "currentText"):
        return ""
    try:
        return str(combo.currentText() or "").strip()
    except Exception:
        return ""


def _ui_shell_current_voice_file(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    return _ui_shell_combo_text_value(window, "voice_combo", str(session.get("voice_file", "") or ""))
