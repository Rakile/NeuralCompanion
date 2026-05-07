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


def update_runtime_config_from_widgets(backend, runtime_config=None, *, tts_backend=""):
    from engine import update_runtime_config

    for key, value in collect_runtime_config(backend, runtime_config, tts_backend=tts_backend).items():
        update_runtime_config(key, value)
