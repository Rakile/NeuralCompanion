"""Chat, avatar, and TTS runtime card binders for the Designer UI shell."""


def configure_shell_runtime_cards_dependencies(namespace):
    """Inject qt_app-owned Qt objects and shell helpers without importing the app."""
    globals().update(dict(namespace or {}))


def _ui_shell_chat_provider_rows_text(providers):
    providers = list(providers or [])
    if not providers:
        return ""
    lines = ["Shell-live chat provider addons registered metadata only:"]
    for provider in providers:
        metadata = dict(provider.get("metadata") or {})
        config_count = len(list(metadata.get("config_fields") or []))
        generation_count = len(list(metadata.get("generation_fields") or []))
        labels = []
        if provider.get("has_model_list_handler"):
            labels.append("models")
        if provider.get("has_completion_handler"):
            labels.append("completion")
        if provider.get("has_stream_handler"):
            labels.append("stream")
        if provider.get("has_connection_check_handler"):
            labels.append("connection")
        capability_text = ", ".join(labels) if labels else "metadata"
        lines.append(
            f" - {provider.get('label') or provider.get('id')} ({provider.get('id')}): "
            f"{config_count} config field(s), {generation_count} generation field(s), handlers: {capability_text}"
        )
    lines.append("Handlers are intentionally not called in shell mode.")
    return "\n".join(lines)

def _ui_shell_chat_provider_map(providers):
    return {
        str(provider.get("id") or "").strip().lower(): dict(provider)
        for provider in list(providers or [])
        if str(provider.get("id") or "").strip()
    }

def _ui_shell_clear_form_layout(layout):
    if layout is None or not hasattr(layout, "rowCount"):
        return
    while layout.rowCount():
        try:
            layout.removeRow(0)
        except Exception:
            break

def _ui_shell_provider_label(provider):
    return str(provider.get("label") or provider.get("id") or "Provider").strip()

def _ui_shell_current_provider_id(combo, providers):
    provider_ids = set(_ui_shell_chat_provider_map(providers))
    if combo is None:
        return ""
    try:
        data = combo.currentData()
    except Exception:
        data = None
    provider_id = str(data or "").strip().lower()
    if provider_id in provider_ids:
        return provider_id
    current_text = str(combo.currentText() if hasattr(combo, "currentText") else "" or "").strip().lower()
    for provider in list(providers or []):
        if str(provider.get("label") or "").strip().lower() == current_text:
            return str(provider.get("id") or "").strip().lower()
    return ""

def _ui_shell_generation_default_value(field, settings, provider_settings):
    field_id = str(field.get("id") or "").strip()
    if field_id in settings:
        return settings.get(field_id)
    if field_id == "max_tokens" and field_id in provider_settings:
        return provider_settings.get(field_id)
    if "default" in field:
        return field.get("default")
    return ""

def _ui_shell_add_field_tooltip(widget, field, *, shell_local=True):
    if widget is None or not hasattr(widget, "setToolTip"):
        return
    tooltip_parts = []
    description = str(field.get("description") or "").strip()
    if description:
        tooltip_parts.append(description)
    env_names = [
        str(name or "").strip()
        for name in list(field.get("env") or [])
        if str(name or "").strip()
    ]
    if env_names:
        tooltip_parts.append("Env: " + ", ".join(env_names))
    if field.get("default") not in (None, ""):
        tooltip_parts.append(f"Default: {field.get('default')}")
    if shell_local:
        tooltip_parts.append("Shell-local preview only; not saved or applied.")
    widget.setToolTip("\n".join(tooltip_parts))

def _ui_shell_create_provider_config_editor(field, value):
    from PySide6 import QtWidgets as _QtWidgets

    field_id = str(field.get("id") or "").strip()
    kind = str(field.get("kind") or "").strip().lower()
    if not kind:
        kind = "password" if "key" in field_id.lower() or "token" in field_id.lower() else "text"
    editor = _QtWidgets.QLineEdit()
    editor.setObjectName(f"ui_shell_chat_provider_field_{field_id}")
    if kind == "password":
        editor.setEchoMode(_QtWidgets.QLineEdit.Password)
    editor.setText(str(value if value is not None else ""))
    placeholder = field.get("placeholder")
    if placeholder:
        editor.setPlaceholderText(str(placeholder))
    _ui_shell_add_field_tooltip(editor, field)
    return editor

def _ui_shell_create_generation_editor(field, value):
    from PySide6 import QtCore as _QtCore
    from PySide6 import QtWidgets as _QtWidgets

    field_id = str(field.get("id") or "").strip()
    kind = str(field.get("kind") or "text").strip().lower()
    if kind == "note":
        editor = _QtWidgets.QLabel(str(field.get("text") or field.get("description") or ""))
        editor.setWordWrap(True)
        editor.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        return editor
    if kind == "bool":
        editor = _QtWidgets.QCheckBox(str(field.get("label") or field_id.replace("_", " ").title()))
        editor.setChecked(bool(value))
        _ui_shell_add_field_tooltip(editor, field)
        return editor
    if kind == "select":
        editor = _QtWidgets.QComboBox()
        for option in list(field.get("options") or []):
            if isinstance(option, dict):
                editor.addItem(str(option.get("label") or option.get("value") or ""), option.get("value"))
            else:
                editor.addItem(str(option), option)
        index = editor.findData(value)
        if index < 0:
            index = editor.findText(str(value))
        if index >= 0:
            editor.setCurrentIndex(index)
        _ui_shell_add_field_tooltip(editor, field)
        return editor
    if kind == "int":
        editor = _QtWidgets.QSpinBox()
        editor.setRange(int(field.get("min", -999999)), int(field.get("max", 999999)))
        editor.setSingleStep(int(field.get("step", 1) or 1))
        try:
            editor.setValue(int(value if value not in (None, "") else field.get("default", 0)))
        except Exception:
            editor.setValue(int(field.get("default", 0) or 0))
        editor.setFocusPolicy(_QtCore.Qt.StrongFocus)
        _ui_shell_add_field_tooltip(editor, field)
        return editor
    if kind == "float":
        editor = _QtWidgets.QDoubleSpinBox()
        editor.setRange(float(field.get("min", -999999.0)), float(field.get("max", 999999.0)))
        editor.setDecimals(int(field.get("decimals", 2) or 2))
        editor.setSingleStep(float(field.get("step", 0.01) or 0.01))
        try:
            editor.setValue(float(value if value not in (None, "") else field.get("default", 0.0)))
        except Exception:
            editor.setValue(float(field.get("default", 0.0) or 0.0))
        editor.setFocusPolicy(_QtCore.Qt.StrongFocus)
        _ui_shell_add_field_tooltip(editor, field)
        return editor

    editor = _QtWidgets.QLineEdit()
    editor.setObjectName(f"ui_shell_chat_provider_generation_field_{field_id}")
    editor.setText(str(value if value is not None else ""))
    placeholder = field.get("placeholder")
    if placeholder:
        editor.setPlaceholderText(str(placeholder))
    _ui_shell_add_field_tooltip(editor, field)
    return editor

def _bind_ui_shell_chat_runtime(window, providers, session_override=None):
    from PySide6 import QtWidgets as _QtWidgets

    providers = list(providers or [])
    provider_by_id = _ui_shell_chat_provider_map(providers)
    if not provider_by_id:
        return {"bound": False, "providers": 0, "selected_provider": ""}

    session = dict(session_override or _read_ui_shell_session_snapshot() or {})
    settings_map = dict(session.get("chat_provider_settings") or {})
    generation_settings_map = dict(session.get("chat_provider_generation_settings") or {})
    saved_provider = str(session.get("chat_provider", "") or "").strip().lower()
    selected_provider_id = saved_provider if saved_provider in provider_by_id else str(providers[0].get("id") or "").strip().lower()

    combo = _ui_shell_find_object(window, "chat_provider_combo")
    model_combo = _ui_shell_find_object(window, "model_combo")
    settings_layout = _ui_shell_find_object(window, "chat_provider_fields_layout")
    generation_layout = _ui_shell_find_object(window, "chat_provider_generation_fields_layout")
    settings_label = _ui_shell_find_object(window, "provider_settings_label")
    generation_label = _ui_shell_find_object(window, "provider_generation_label")
    runtime_box = _ui_shell_find_object(window, "chat_runtime_box")
    refresh_button = _ui_shell_find_object(window, "btn_model_refresh")
    model_refresh = _ui_shell_model_refresh_service(window)

    if settings_layout is None or generation_layout is None:
        return {"bound": False, "providers": len(providers), "selected_provider": selected_provider_id}

    local_state = {
        "provider_settings": {
            str(provider_id or "").strip().lower(): dict(values or {})
            for provider_id, values in settings_map.items()
            if isinstance(values, dict)
        },
        "generation_settings": {
            str(provider_id or "").strip().lower(): dict(values or {})
            for provider_id, values in generation_settings_map.items()
            if isinstance(values, dict)
        },
    }

    def refresh_model_summary(provider_id):
        if model_combo is None or not hasattr(model_combo, "clear"):
            return
        snapshot = dict(model_refresh.snapshot(provider_id) or {})
        saved_model = str(snapshot.get("selected_model") or session.get("model_name", "") or "").strip()
        models = [str(item or "").strip() for item in list(snapshot.get("models") or []) if str(item or "").strip()]
        model_combo.blockSignals(True)
        try:
            model_combo.clear()
            for model in models:
                model_combo.addItem(model)
            if saved_model and saved_model not in models:
                model_combo.insertItem(0, saved_model)
            model_combo.addItem("Model refresh deferred in shell preview")
            model_combo.setCurrentIndex(0)
        finally:
            model_combo.blockSignals(False)
        _ui_shell_set_read_only_tooltip(model_combo, str(snapshot.get("message") or "Live model refresh remains deferred for this binding slice."))

    def refresh_runtime_title(provider_id):
        provider = provider_by_id.get(provider_id, {})
        provider_label = _ui_shell_provider_label(provider)
        model_name = str(session.get("model_name", "") or "").strip()
        title = f"Chat Runtime - {provider_label}"
        if model_name:
            title += f" / {model_name}"
        if runtime_box is not None and hasattr(runtime_box, "setTitle"):
            runtime_box.setTitle(title)

    def current_provider_settings(provider_id):
        return dict(local_state["provider_settings"].get(provider_id, {}))

    def current_generation_settings(provider_id):
        return dict(local_state["generation_settings"].get(provider_id, {}))

    def render_provider(provider_id):
        provider = provider_by_id.get(provider_id) or providers[0]
        provider_id = str(provider.get("id") or "").strip().lower()
        metadata = dict(provider.get("metadata") or {})
        config_fields = list(metadata.get("config_fields") or [])
        generation_fields = list(metadata.get("generation_fields") or [])
        provider_settings = current_provider_settings(provider_id)
        generation_settings = current_generation_settings(provider_id)

        _ui_shell_clear_form_layout(settings_layout)
        if config_fields:
            for field in config_fields:
                field_id = str(field.get("id") or "").strip()
                if not field_id:
                    continue
                label = str(field.get("label") or field_id.replace("_", " ").title()).strip()
                value = provider_settings.get(field_id, field.get("default", ""))
                editor = _ui_shell_create_provider_config_editor(field, value)

                def on_config_changed(fid=field_id, edit=editor, pid=provider_id):
                    local_state["provider_settings"].setdefault(pid, {})[fid] = str(edit.text() if hasattr(edit, "text") else "")

                editor.editingFinished.connect(on_config_changed)
                settings_layout.addRow(label, editor)
            if settings_label is not None and hasattr(settings_label, "setText"):
                settings_label.setText(f"Provider Settings - {len(config_fields)} field(s)")
        else:
            hint = _QtWidgets.QLabel("This provider does not expose extra runtime fields.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            settings_layout.addRow("", hint)
            if settings_label is not None and hasattr(settings_label, "setText"):
                settings_label.setText("Provider Settings")

        _ui_shell_clear_form_layout(generation_layout)
        active_generation_labels = []
        if generation_fields:
            for field in generation_fields:
                field_id = str(field.get("id") or "").strip()
                if not field_id:
                    continue
                label = str(field.get("label") or field_id.replace("_", " ").title()).strip()
                value = _ui_shell_generation_default_value(field, generation_settings, provider_settings)
                editor = _ui_shell_create_generation_editor(field, value)
                kind = str(field.get("kind") or "text").strip().lower()
                row_label = "" if kind == "bool" else label
                generation_layout.addRow(row_label, editor)
                if kind != "note":
                    active_generation_labels.append(label)

                    def on_generation_changed(_value=None, fid=field_id, edit=editor, pid=provider_id):
                        if hasattr(edit, "isChecked"):
                            new_value = bool(edit.isChecked())
                        elif hasattr(edit, "currentData"):
                            data = edit.currentData()
                            new_value = data if data is not None else str(edit.currentText())
                        elif hasattr(edit, "value"):
                            new_value = edit.value()
                        elif hasattr(edit, "text"):
                            new_value = str(edit.text())
                        else:
                            new_value = ""
                        local_state["generation_settings"].setdefault(pid, {})[fid] = new_value

                    if hasattr(editor, "toggled"):
                        editor.toggled.connect(on_generation_changed)
                    elif hasattr(editor, "currentIndexChanged"):
                        editor.currentIndexChanged.connect(on_generation_changed)
                    elif hasattr(editor, "valueChanged"):
                        editor.valueChanged.connect(on_generation_changed)
                    elif hasattr(editor, "editingFinished"):
                        editor.editingFinished.connect(on_generation_changed)
            summary = ", ".join(active_generation_labels[:3])
            if len(active_generation_labels) > 3:
                summary += f", +{len(active_generation_labels) - 3}"
            if generation_label is not None and hasattr(generation_label, "setText"):
                generation_label.setText(f"Generation Fields - {summary}" if summary else "Generation Fields")
        else:
            hint = _QtWidgets.QLabel("This provider does not expose provider-specific generation fields.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            generation_layout.addRow("", hint)
            if generation_label is not None and hasattr(generation_label, "setText"):
                generation_label.setText("Generation Fields")

        refresh_model_summary(provider_id)
        refresh_runtime_title(provider_id)
        _ui_shell_runtime_status_service(window).set_session_overrides(chat_provider=provider_id)
        _ui_shell_refresh_status_labels(window)

    def on_refresh_clicked():
        provider_id = _ui_shell_current_provider_id(combo, providers) if combo is not None else selected_provider_id
        snapshot = model_refresh.refresh(provider_id, quiet=False, wait_for_reachable=True)
        refresh_model_summary(provider_id)
        if refresh_button is not None and hasattr(refresh_button, "setToolTip"):
            refresh_button.setToolTip(str(snapshot.get("message") or "Live model refresh is deferred in shell preview."))
        status_label = _ui_shell_find_object(window, "console_status")
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setText("Shell preview: model refresh requested, but live provider calls are deferred.")

    if combo is not None and hasattr(combo, "clear"):
        combo.blockSignals(True)
        try:
            combo.clear()
            for provider in providers:
                provider_id = str(provider.get("id") or "").strip().lower()
                combo.addItem(_ui_shell_provider_label(provider), provider_id)
            index = combo.findData(selected_provider_id)
            combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            combo.blockSignals(False)
        combo.setToolTip("Shell-local provider binding. Provider handlers are not called yet.")

        def on_provider_changed(_index=None):
            provider_id = _ui_shell_current_provider_id(combo, providers)
            if provider_id:
                render_provider(provider_id)

        combo.currentIndexChanged.connect(on_provider_changed)

    if refresh_button is not None and hasattr(refresh_button, "clicked"):
        refresh_button.setEnabled(True)
        refresh_button.setText("Refresh")
        refresh_button.setToolTip("Shell-local model refresh facade. No provider handlers are called.")
        if not getattr(refresh_button, "_nc_ui_shell_model_refresh_bound", False):
            refresh_button.clicked.connect(on_refresh_clicked)
            setattr(refresh_button, "_nc_ui_shell_model_refresh_bound", True)

    render_provider(selected_provider_id)
    setattr(window, "_nc_ui_shell_chat_runtime_state", local_state)
    return {
        "bound": True,
        "providers": len(providers),
        "selected_provider": selected_provider_id,
    }

def _bind_ui_shell_avatar_runtime(window, avatar_providers, session_override=None):
    providers = list(avatar_providers or [])
    combo = _ui_shell_find_object(window, "engine_combo")
    if combo is None or not hasattr(combo, "clear"):
        return {"bound": False, "providers": len(providers), "selected_provider": ""}

    session = dict(session_override or _read_ui_shell_session_snapshot() or {})
    saved_provider = str(session.get("avatar_mode", "") or "").strip().lower()
    provider_ids = {
        str(provider.get("id") or "").strip().lower()
        for provider in providers
        if str(provider.get("id") or "").strip()
    }
    selected_provider_id = saved_provider if saved_provider in provider_ids else ""
    if not selected_provider_id and providers:
        selected_provider_id = str(providers[0].get("id") or "").strip().lower()

    combo.blockSignals(True)
    try:
        combo.clear()
        for provider in providers:
            provider_id = str(provider.get("id") or "").strip().lower()
            if not provider_id:
                continue
            label = str(provider.get("label") or provider_id).strip() or provider_id
            combo.addItem(label, provider_id)
        if not providers:
            combo.addItem("No avatar providers registered", "")
        index = combo.findData(selected_provider_id)
        combo.setCurrentIndex(index if index >= 0 else 0)
    finally:
        combo.blockSignals(False)

    if hasattr(combo, "setToolTip"):
        combo.setToolTip("Shell-local avatar provider binding. Avatar factories are not called.")

    def on_avatar_changed(_index=None):
        provider_id = str(combo.currentData() or "").strip().lower()
        label = str(combo.currentText() or provider_id or "Avatar").strip()
        _ui_shell_runtime_status_service(window).set_session_overrides(avatar_mode=provider_id)
        _ui_shell_refresh_status_labels(window)
        _ui_shell_append_console(
            window,
            f"[UI Shell] Avatar Engine preview: {label} selected; no avatar adapter was created.",
        )

    if hasattr(combo, "currentIndexChanged") and not getattr(combo, "_nc_ui_shell_avatar_runtime_bound", False):
        combo.currentIndexChanged.connect(on_avatar_changed)
        setattr(combo, "_nc_ui_shell_avatar_runtime_bound", True)

    _ui_shell_runtime_status_service(window).set_session_overrides(
        avatar_mode=str(combo.currentData() or selected_provider_id or "").strip().lower()
    )
    _ui_shell_refresh_status_labels(window)
    return {
        "bound": True,
        "providers": len(providers),
        "selected_provider": str(combo.currentData() or selected_provider_id or "").strip().lower(),
    }

def _bind_ui_shell_tts_runtime(window, tts_backends, session_override=None):
    backends = list(tts_backends or [])
    combo = _ui_shell_find_object(window, "tts_backend_combo")
    tabs = _ui_shell_find_object(window, "tts_runtime_addon_tabs")
    if combo is None or not hasattr(combo, "clear"):
        return {"bound": False, "backends": len(backends), "selected_backend": ""}

    session = dict(session_override or _read_ui_shell_session_snapshot() or {})
    saved_backend = str(session.get("tts_backend", "") or "").strip().lower()
    backend_ids = {
        str(backend.get("id") or "").strip().lower()
        for backend in backends
        if str(backend.get("id") or "").strip()
    }
    selected_backend_id = saved_backend if saved_backend in backend_ids else ""
    if not selected_backend_id and backends:
        selected_backend_id = str(backends[0].get("id") or "").strip().lower()

    combo.blockSignals(True)
    try:
        combo.clear()
        for backend in backends:
            backend_id = str(backend.get("id") or "").strip().lower()
            if not backend_id:
                continue
            label = str(backend.get("label") or backend_id).strip() or backend_id
            combo.addItem(label, backend_id)
        if not backends:
            combo.addItem("No TTS backends registered", "")
        index = combo.findData(selected_backend_id)
        combo.setCurrentIndex(index if index >= 0 else 0)
    finally:
        combo.blockSignals(False)

    if hasattr(combo, "setToolTip"):
        combo.setToolTip("Shell-local TTS backend binding. TTS backend services are not started.")

    label_by_id = {
        str(backend.get("id") or "").strip().lower(): str(backend.get("label") or backend.get("id") or "").strip()
        for backend in backends
    }

    def select_backend_tab(backend_id):
        if tabs is None or not hasattr(tabs, "count"):
            return
        label = str(label_by_id.get(str(backend_id or "").strip().lower()) or "").strip().lower()
        if not label:
            return
        for index in range(tabs.count()):
            try:
                title = str(tabs.tabText(index) or "").strip().lower()
            except Exception:
                title = ""
            if title == label or label in title or title in label:
                try:
                    tabs.setCurrentIndex(index)
                except Exception:
                    pass
                return

    def on_tts_changed(_index=None):
        backend_id = str(combo.currentData() or "").strip().lower()
        label = str(combo.currentText() or backend_id or "TTS").strip()
        select_backend_tab(backend_id)
        _ui_shell_runtime_status_service(window).set_session_overrides(tts_backend=backend_id)
        _ui_shell_refresh_status_labels(window)
        _ui_shell_append_console(
            window,
            f"[UI Shell] TTS Backend preview: {label} selected; no TTS service was started.",
        )

    if hasattr(combo, "currentIndexChanged") and not getattr(combo, "_nc_ui_shell_tts_runtime_bound", False):
        combo.currentIndexChanged.connect(on_tts_changed)
        setattr(combo, "_nc_ui_shell_tts_runtime_bound", True)

    select_backend_tab(str(combo.currentData() or selected_backend_id or "").strip().lower())
    _ui_shell_runtime_status_service(window).set_session_overrides(
        tts_backend=str(combo.currentData() or selected_backend_id or "").strip().lower()
    )
    _ui_shell_refresh_status_labels(window)
    return {
        "bound": True,
        "backends": len(backends),
        "selected_backend": str(combo.currentData() or selected_backend_id or "").strip().lower(),
    }
