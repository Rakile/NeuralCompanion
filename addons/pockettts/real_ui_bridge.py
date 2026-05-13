import os

from core.addons.qt_host_services import QtDialogService, QtRuntimeConfigService


def collect_runtime_config(backend, runtime_config=None, *, tts_backend=""):
    """Collect PocketTTS-owned runtime config from the current backend widgets."""
    runtime = dict(runtime_config or {})
    backend_id = str(tts_backend or "").strip().lower()
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    if backend_id == "pockettts" and widget is not None:
        python_path = backend._ensure_pocket_tts_python_path()
    else:
        python_path = backend._live_text("pocket_tts_python_edit", runtime.get("pocket_tts_python", "")).strip()
    return {
        "pocket_tts_python": python_path,
        "pocket_tts_temperature": _live_float(backend, "pockettts_temperature_spin", runtime.get("pocket_tts_temperature", 0.7), minimum=0.05),
        "pocket_tts_lsd_decode_steps": _live_int(backend, "pockettts_lsd_steps_spin", runtime.get("pocket_tts_lsd_decode_steps", 1), minimum=1),
        "pocket_tts_eos_threshold": _live_float(backend, "pockettts_eos_threshold_spin", runtime.get("pocket_tts_eos_threshold", -4.0)),
        "pocket_tts_max_tokens": _live_int(backend, "pockettts_max_tokens_spin", runtime.get("pocket_tts_max_tokens", 50), minimum=1),
        "pocket_tts_frames_after_eos": _live_int(backend, "pockettts_frames_after_eos_spin", runtime.get("pocket_tts_frames_after_eos", 0), minimum=0),
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


def estimated_runtime_overhead_gib():
    return 2.0


def build_status_snapshot(backend, runtime_config=None):
    """Expose PocketTTS-owned fields for runtime/addon status snapshots."""
    runtime = dict(runtime_config or {})
    return {
        "pocket_tts_python": backend._live_text(
            "pocket_tts_python_edit",
            runtime.get("pocket_tts_python", ""),
        ).strip(),
        "pocket_tts_temperature": _live_float(backend, "pockettts_temperature_spin", runtime.get("pocket_tts_temperature", 0.7), minimum=0.05),
        "pocket_tts_lsd_decode_steps": _live_int(backend, "pockettts_lsd_steps_spin", runtime.get("pocket_tts_lsd_decode_steps", 1), minimum=1),
        "pocket_tts_eos_threshold": _live_float(backend, "pockettts_eos_threshold_spin", runtime.get("pocket_tts_eos_threshold", -4.0)),
        "pocket_tts_max_tokens": _live_int(backend, "pockettts_max_tokens_spin", runtime.get("pocket_tts_max_tokens", 50), minimum=1),
        "pocket_tts_frames_after_eos": _live_int(backend, "pockettts_frames_after_eos_spin", runtime.get("pocket_tts_frames_after_eos", 0), minimum=0),
    }


def refresh_resource_widgets(backend, runtime_config=None):
    """Refresh PocketTTS-owned widgets from runtime/session config."""
    runtime = dict(runtime_config or {})
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    if widget is not None:
        widget.setText(str(runtime.get("pocket_tts_python", "") or ""))
    for object_name, key, default in (
        ("pockettts_temperature_spin", "pocket_tts_temperature", 0.7),
        ("pockettts_lsd_steps_spin", "pocket_tts_lsd_decode_steps", 1),
        ("pockettts_eos_threshold_spin", "pocket_tts_eos_threshold", -4.0),
        ("pockettts_max_tokens_spin", "pocket_tts_max_tokens", 50),
        ("pockettts_frames_after_eos_spin", "pocket_tts_frames_after_eos", 0),
    ):
        spin = backend._live_widget_attr(object_name)
        if spin is not None and hasattr(spin, "setValue"):
            spin.setValue(runtime.get(key, default))


def restart_sensitive_widgets(backend):
    """Return PocketTTS-owned controls that should lock while the engine is running."""
    names = (
        "pocket_tts_python_edit",
        "pocket_tts_browse_button",
        "btn_pockettts_browse",
        "pockettts_temperature_spin",
        "pockettts_lsd_steps_spin",
        "pockettts_eos_threshold_spin",
        "pockettts_max_tokens_spin",
        "pockettts_frames_after_eos_spin",
    )
    return [
        widget
        for widget in (backend._live_widget_attr(name) for name in names)
        if widget is not None
    ]


def _runtime_config_service(backend):
    return QtRuntimeConfigService(backend)


def _update_runtime_config(backend, key, value):
    return _runtime_config_service(backend).update(key, value)


def _engine_attr(backend, name: str, default=None):
    return _runtime_config_service(backend).engine_attr(name, default)


def browse_python(backend):
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    start_dir = widget.text().strip() if widget is not None else ""
    path, _ = QtDialogService(backend).open_file(
        "Select PocketTTS Python",
        start_dir or "",
        "Python (*.exe);;All Files (*.*)",
    )
    if not path:
        return
    if widget is not None:
        widget.setText(path)
    apply_python_changed(backend)


def apply_python_changed(backend):
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    if widget is None:
        return
    _update_runtime_config(backend, "pocket_tts_python", widget.text().strip())
    if hasattr(backend, "save_session"):
        backend.save_session()


def ensure_python_path(backend):
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    fallback = str(_engine_attr(backend, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
    if widget is None:
        if fallback and os.path.exists(fallback):
            _update_runtime_config(backend, "pocket_tts_python", fallback)
            return fallback
        return ""
    current = widget.text().strip()
    if current:
        return current
    if fallback and os.path.exists(fallback):
        widget.setText(fallback)
        apply_python_changed(backend)
        print(f"[QtGUI] PocketTTS Python was empty. Using default path: {fallback}")
        return fallback
    return ""


def reset_python_to_default(backend):
    fallback = str(_engine_attr(backend, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    if fallback and os.path.exists(fallback) and widget is not None:
        widget.setText(fallback)
        apply_python_changed(backend)
        print(f"[QtGUI] PocketTTS Python reset to bundled interpreter: {fallback}")
    else:
        print("[QtGUI] Bundled PocketTTS interpreter was not found.")


def update_runtime_config_from_widgets(backend, runtime_config=None, *, tts_backend=""):
    for key, value in collect_runtime_config(backend, runtime_config, tts_backend=tts_backend).items():
        _update_runtime_config(backend, key, value)
