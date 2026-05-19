from core.addons.qt_host_services import QtRuntimeConfigService
from core.pocket_tts_voices import normalize_pocket_tts_builtin_voice


def _live_combo_value(backend, object_name, default):
    widget = backend._live_widget_attr(object_name)
    try:
        if widget is not None and hasattr(widget, "currentData"):
            data = widget.currentData()
            if data is not None and str(data).strip():
                return str(data).strip()
        if widget is not None and hasattr(widget, "currentText"):
            text = str(widget.currentText() or "").strip()
            if text:
                return text
    except Exception:
        pass
    return str(default or "").strip()


def collect_runtime_config(backend, runtime_config=None):
    runtime = dict(runtime_config or {})
    return {
        "pocket_tts_multilingual_language": _live_combo_value(
            backend,
            "pockettts_multilingual_language_combo",
            runtime.get("pocket_tts_multilingual_language", "en"),
        ),
        "pocket_tts_python": backend._live_text(
            "pockettts_multilingual_python_edit",
            runtime.get("pocket_tts_python", ""),
        ).strip(),
        "pocket_tts_multilingual_temperature": _live_float(
            backend,
            "pockettts_multilingual_temperature_spin",
            runtime.get("pocket_tts_multilingual_temperature", 0.7),
            minimum=0.05,
        ),
        "pocket_tts_multilingual_lsd_decode_steps": _live_int(
            backend,
            "pockettts_multilingual_lsd_steps_spin",
            runtime.get("pocket_tts_multilingual_lsd_decode_steps", 1),
            minimum=1,
        ),
        "pocket_tts_multilingual_eos_threshold": _live_float(
            backend,
            "pockettts_multilingual_eos_threshold_spin",
            runtime.get("pocket_tts_multilingual_eos_threshold", -4.0),
        ),
        "pocket_tts_multilingual_frames_after_eos": _live_int(
            backend,
            "pockettts_multilingual_frames_after_eos_spin",
            runtime.get("pocket_tts_multilingual_frames_after_eos", 0),
            minimum=0,
        ),
        "pocket_tts_multilingual_builtin_voice": normalize_pocket_tts_builtin_voice(
            _live_combo_value(
                backend,
                "pockettts_multilingual_builtin_voice_combo",
                runtime.get("pocket_tts_multilingual_builtin_voice", "auto"),
            )
        ),
        "pocket_tts_multilingual_use_cloned_voice": _live_checked(
            backend,
            "pockettts_multilingual_use_cloned_voice_checkbox",
            runtime.get("pocket_tts_multilingual_use_cloned_voice", True),
        ),
        "pocket_tts_multilingual_prewarm_on_start": _live_checked(
            backend,
            "pockettts_multilingual_prewarm_checkbox",
            runtime.get("pocket_tts_multilingual_prewarm_on_start", True),
        ),
    }


def _live_float(backend, object_name, default, *, minimum=None):
    widget = backend._live_widget_attr(object_name)
    try:
        value = float(widget.value()) if widget is not None and hasattr(widget, "value") else float(default)
    except Exception:
        value = float(default)
    if minimum is not None:
        value = max(float(minimum), value)
    return value


def _live_int(backend, object_name, default, *, minimum=None):
    widget = backend._live_widget_attr(object_name)
    try:
        value = int(widget.value()) if widget is not None and hasattr(widget, "value") else int(default)
    except Exception:
        value = int(default)
    if minimum is not None:
        value = max(int(minimum), value)
    return value


def _live_checked(backend, object_name, default):
    widget = backend._live_widget_attr(object_name)
    try:
        return bool(widget.isChecked()) if widget is not None and hasattr(widget, "isChecked") else bool(default)
    except Exception:
        return bool(default)


def estimated_runtime_overhead_gib():
    return 2.0


def build_status_snapshot(backend, runtime_config=None):
    return collect_runtime_config(backend, runtime_config)


def refresh_resource_widgets(backend, runtime_config=None):
    runtime = dict(runtime_config or {})
    combo = backend._live_widget_attr("pockettts_multilingual_language_combo")
    if combo is not None:
        value = str(runtime.get("pocket_tts_multilingual_language", "en") or "en")
        index = combo.findData(value) if hasattr(combo, "findData") else -1
        if index < 0 and hasattr(combo, "findText"):
            index = combo.findText(value)
        if index >= 0 and hasattr(combo, "setCurrentIndex"):
            combo.setCurrentIndex(index)
    edit = backend._live_widget_attr("pockettts_multilingual_python_edit")
    if edit is not None and hasattr(edit, "setText"):
        edit.setText(str(runtime.get("pocket_tts_python", "") or ""))
    for object_name, key, default in (
        ("pockettts_multilingual_temperature_spin", "pocket_tts_multilingual_temperature", 0.7),
        ("pockettts_multilingual_lsd_steps_spin", "pocket_tts_multilingual_lsd_decode_steps", 1),
        ("pockettts_multilingual_eos_threshold_spin", "pocket_tts_multilingual_eos_threshold", -4.0),
        ("pockettts_multilingual_frames_after_eos_spin", "pocket_tts_multilingual_frames_after_eos", 0),
    ):
        spin = backend._live_widget_attr(object_name)
        if spin is not None and hasattr(spin, "setValue"):
            spin.setValue(runtime.get(key, default))
    voice_combo = backend._live_widget_attr("pockettts_multilingual_builtin_voice_combo")
    if voice_combo is not None:
        value = normalize_pocket_tts_builtin_voice(runtime.get("pocket_tts_multilingual_builtin_voice", "auto"))
        index = voice_combo.findData(value) if hasattr(voice_combo, "findData") else -1
        if index >= 0 and hasattr(voice_combo, "setCurrentIndex"):
            voice_combo.setCurrentIndex(index)
    for object_name, key, default in (
        ("pockettts_multilingual_use_cloned_voice_checkbox", "pocket_tts_multilingual_use_cloned_voice", True),
        ("pockettts_multilingual_prewarm_checkbox", "pocket_tts_multilingual_prewarm_on_start", True),
    ):
        checkbox = backend._live_widget_attr(object_name)
        if checkbox is not None and hasattr(checkbox, "setChecked"):
            checkbox.setChecked(bool(runtime.get(key, default)))


def restart_sensitive_widgets(backend):
    names = (
        "pockettts_multilingual_language_combo",
        "pockettts_multilingual_python_edit",
        "btn_pockettts_multilingual_install",
    )
    return [
        widget
        for widget in (backend._live_widget_attr(name) for name in names)
        if widget is not None
    ]


def update_runtime_config_from_widgets(backend, runtime_config=None):
    service = QtRuntimeConfigService(backend)
    for key, value in collect_runtime_config(backend, runtime_config).items():
        service.update(key, value)
