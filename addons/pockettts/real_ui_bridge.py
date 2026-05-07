import os

from core.addons.qt_host_services import QtDialogService


def collect_runtime_config(backend, runtime_config=None, *, tts_backend=""):
    """Collect PocketTTS-owned runtime config from the current backend widgets."""
    runtime = dict(runtime_config or {})
    backend_id = str(tts_backend or "").strip().lower()
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    if backend_id == "pockettts" and widget is not None:
        python_path = backend._ensure_pocket_tts_python_path()
    else:
        python_path = backend._live_text("pocket_tts_python_edit", runtime.get("pocket_tts_python", "")).strip()
    return {"pocket_tts_python": python_path}


def estimated_runtime_overhead_gib():
    return 2.0


def build_status_snapshot(backend, runtime_config=None):
    """Expose PocketTTS-owned fields for runtime/addon status snapshots."""
    runtime = dict(runtime_config or {})
    return {
        "pocket_tts_python": backend._live_text(
            "pocket_tts_python_edit",
            runtime.get("pocket_tts_python", ""),
        ).strip()
    }


def refresh_resource_widgets(backend, runtime_config=None):
    """Refresh PocketTTS-owned widgets from runtime/session config."""
    runtime = dict(runtime_config or {})
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    if widget is not None:
        widget.setText(str(runtime.get("pocket_tts_python", "") or ""))


def restart_sensitive_widgets(backend):
    """Return PocketTTS-owned controls that should lock while the engine is running."""
    names = ("pocket_tts_python_edit", "pocket_tts_browse_button")
    return [
        widget
        for widget in (backend._live_widget_attr(name) for name in names)
        if widget is not None
    ]


def _engine():
    import engine

    return engine


def _update_runtime_config(key, value):
    from engine import update_runtime_config

    return update_runtime_config(key, value)


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
    _update_runtime_config("pocket_tts_python", widget.text().strip())
    if hasattr(backend, "save_session"):
        backend.save_session()


def ensure_python_path(backend):
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    fallback = str(getattr(_engine(), "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
    if widget is None:
        if fallback and os.path.exists(fallback):
            _update_runtime_config("pocket_tts_python", fallback)
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
    fallback = str(getattr(_engine(), "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
    widget = backend._live_widget_attr("pocket_tts_python_edit")
    if fallback and os.path.exists(fallback) and widget is not None:
        widget.setText(fallback)
        apply_python_changed(backend)
        print(f"[QtGUI] PocketTTS Python reset to bundled interpreter: {fallback}")
    else:
        print("[QtGUI] Bundled PocketTTS interpreter was not found.")


def update_runtime_config_from_widgets(backend, runtime_config=None, *, tts_backend=""):
    from engine import update_runtime_config

    for key, value in collect_runtime_config(backend, runtime_config, tts_backend=tts_backend).items():
        update_runtime_config(key, value)
