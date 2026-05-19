from core.addons.qt_host_services import QtRuntimeConfigService

DEFAULT_TOP_P = 1.0
DEFAULT_REPEAT_PENALTY = 2.0


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


def _live_float(backend, object_name, default, *, minimum=None, maximum=None):
    widget = backend._live_widget_attr(object_name)
    try:
        value = float(widget.value()) if widget is not None and hasattr(widget, "value") else float(default)
    except Exception:
        value = float(default)
    if minimum is not None:
        value = max(float(minimum), value)
    if maximum is not None:
        value = min(float(maximum), value)
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


def collect_runtime_config(backend, runtime_config=None):
    runtime = dict(runtime_config or {})
    return {
        "chatterbox_multilingual_language": _live_combo_value(
            backend,
            "chatterbox_multilingual_language_combo",
            runtime.get("chatterbox_multilingual_language", "en"),
        ),
        "chatterbox_multilingual_seed": _live_int(
            backend,
            "chatterbox_multilingual_seed_spin",
            runtime.get("chatterbox_multilingual_seed", 0),
            minimum=0,
        ),
        "chatterbox_multilingual_temperature": _live_float(
            backend,
            "chatterbox_multilingual_temperature_spin",
            runtime.get("chatterbox_multilingual_temperature", 0.8),
            minimum=0.05,
        ),
        "chatterbox_multilingual_top_p": _live_float(
            backend,
            "chatterbox_multilingual_top_p_spin",
            runtime.get("chatterbox_multilingual_top_p", DEFAULT_TOP_P),
            minimum=0.0,
            maximum=1.0,
        ),
        "chatterbox_multilingual_top_k": _live_int(
            backend,
            "chatterbox_multilingual_top_k_spin",
            runtime.get("chatterbox_multilingual_top_k", 40),
            minimum=0,
        ),
        "chatterbox_multilingual_repeat_penalty": _live_float(
            backend,
            "chatterbox_multilingual_repeat_penalty_spin",
            runtime.get("chatterbox_multilingual_repeat_penalty", DEFAULT_REPEAT_PENALTY),
            minimum=1.0,
        ),
        "chatterbox_multilingual_normalize_loudness": _live_checked(
            backend,
            "chatterbox_multilingual_normalize_loudness_checkbox",
            runtime.get("chatterbox_multilingual_normalize_loudness", False),
        ),
        "chatterbox_multilingual_prewarm_on_start": _live_checked(
            backend,
            "chatterbox_multilingual_prewarm_checkbox",
            runtime.get("chatterbox_multilingual_prewarm_on_start", True),
        ),
        "chatterbox_multilingual_use_cloned_voice": _live_checked(
            backend,
            "chatterbox_multilingual_use_cloned_voice_checkbox",
            runtime.get("chatterbox_multilingual_use_cloned_voice", True),
        ),
        "chatterbox_multilingual_apply_watermark": _live_checked(
            backend,
            "chatterbox_multilingual_apply_watermark_checkbox",
            runtime.get("chatterbox_multilingual_apply_watermark", True),
        ),
    }


def estimated_runtime_overhead_gib():
    return 5.8


def build_status_snapshot(backend, runtime_config=None):
    return collect_runtime_config(backend, runtime_config)


def refresh_resource_widgets(backend, runtime_config=None):
    runtime = dict(runtime_config or {})
    combo = backend._live_widget_attr("chatterbox_multilingual_language_combo")
    if combo is not None:
        value = str(runtime.get("chatterbox_multilingual_language", "en") or "en")
        index = combo.findData(value) if hasattr(combo, "findData") else -1
        if index < 0 and hasattr(combo, "findText"):
            index = combo.findText(value)
        if index >= 0 and hasattr(combo, "setCurrentIndex"):
            combo.setCurrentIndex(index)
    for object_name, key, default in (
        ("chatterbox_multilingual_seed_spin", "chatterbox_multilingual_seed", 0),
        ("chatterbox_multilingual_temperature_spin", "chatterbox_multilingual_temperature", 0.8),
        ("chatterbox_multilingual_top_p_spin", "chatterbox_multilingual_top_p", DEFAULT_TOP_P),
        ("chatterbox_multilingual_top_k_spin", "chatterbox_multilingual_top_k", 40),
        ("chatterbox_multilingual_repeat_penalty_spin", "chatterbox_multilingual_repeat_penalty", DEFAULT_REPEAT_PENALTY),
    ):
        spin = backend._live_widget_attr(object_name)
        if spin is not None and hasattr(spin, "setValue"):
            spin.setValue(runtime.get(key, default))
    for object_name, key, default in (
        ("chatterbox_multilingual_normalize_loudness_checkbox", "chatterbox_multilingual_normalize_loudness", False),
        ("chatterbox_multilingual_prewarm_checkbox", "chatterbox_multilingual_prewarm_on_start", True),
        ("chatterbox_multilingual_use_cloned_voice_checkbox", "chatterbox_multilingual_use_cloned_voice", True),
        ("chatterbox_multilingual_apply_watermark_checkbox", "chatterbox_multilingual_apply_watermark", True),
    ):
        checkbox = backend._live_widget_attr(object_name)
        if checkbox is not None and hasattr(checkbox, "setChecked"):
            checkbox.setChecked(bool(runtime.get(key, default)))


def restart_sensitive_widgets(backend):
    names = (
        "chatterbox_multilingual_language_combo",
        "btn_chatterbox_multilingual_install",
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
