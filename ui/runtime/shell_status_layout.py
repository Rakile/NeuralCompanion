"""Status, host-summary, and workspace layout helpers for the Designer UI shell."""


def configure_shell_status_layout_dependencies(namespace):
    """Inject qt_app-owned Qt objects and shell helpers without importing the app."""
    globals().update(dict(namespace or {}))


def _ui_shell_append_console(window, message):
    console_edit = _ui_shell_find_object(window, "console_edit")
    if console_edit is None:
        return
    try:
        if hasattr(console_edit, "appendPlainText"):
            console_edit.appendPlainText(str(message))
        elif hasattr(console_edit, "append"):
            console_edit.append(str(message))
    except Exception:
        pass

def _ui_shell_stream_mode_enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on", "stream", "enabled"}

_INPUT_MICROPHONE_HINTS = (
    "microphone",
    "headset",
    "mic array",
    "array mic",
    "built-in mic",
    "internal mic",
    "usb mic",
    "webcam",
    "camera",
)

_INPUT_MICROPHONE_TOKEN_HINTS = (" mic", "mic ")

_INPUT_NON_MICROPHONE_HINTS = (
    "cable output",
    "line ",
    "voicemeeter",
    "stereo mix",
    "what u hear",
    "loopback",
    "monitor",
    "wave out",
    "output",
)

SHOW_ALL_AUDIO_INPUT_DEVICES_LABEL = "Show all input devices..."
SHOW_MICROPHONE_AUDIO_INPUT_DEVICES_LABEL = "Show microphones only..."


def _ui_shell_input_label_looks_like_microphone(label):
    text = str(label or "").strip().casefold()
    if not text or text == "default input":
        return True
    if any(hint in text for hint in _INPUT_NON_MICROPHONE_HINTS):
        return False
    return any(hint in text for hint in _INPUT_MICROPHONE_HINTS) or any(hint in text for hint in _INPUT_MICROPHONE_TOKEN_HINTS)


def _ui_shell_filter_microphone_input_labels(input_labels):
    labels = list(input_labels or [])
    filtered = [label for label in labels if _ui_shell_input_label_looks_like_microphone(label)]
    return filtered if len(filtered) > 1 else labels


def _ui_shell_audio_device_labels(*, show_all_inputs=False, include_input_mode_actions=False):
    labels = {
        "inputs": ["Default Input"],
        "outputs": ["Default Output"],
    }
    def add_unique(target, value):
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)

    try:
        from PySide6 import QtMultimedia as _QtMultimedia

        for device in list(_QtMultimedia.QMediaDevices.audioInputs() or []):
            description = str(device.description() if hasattr(device, "description") else "").strip()
            add_unique(labels["inputs"], description)
        for device in list(_QtMultimedia.QMediaDevices.audioOutputs() or []):
            description = str(device.description() if hasattr(device, "description") else "").strip()
            add_unique(labels["outputs"], description)
    except Exception:
        pass
    try:
        import speech_recognition as _sr

        for name in list(_sr.Microphone.list_microphone_names() or []):
            add_unique(labels["inputs"], name)
    except Exception:
        pass
    try:
        import sounddevice as _sd

        for index, device in enumerate(list(_sd.query_devices() or [])):
            name = str(device.get("name", "") or "").strip()
            if int(device.get("max_input_channels", 0) or 0) > 0:
                add_unique(labels["inputs"], name)
            if int(device.get("max_output_channels", 0) or 0) > 0:
                add_unique(labels["outputs"], name)
    except Exception:
        pass
    if not show_all_inputs:
        labels["inputs"] = _ui_shell_filter_microphone_input_labels(labels.get("inputs"))
        if include_input_mode_actions:
            add_unique(labels["inputs"], SHOW_ALL_AUDIO_INPUT_DEVICES_LABEL)
    elif include_input_mode_actions:
        add_unique(labels["inputs"], SHOW_MICROPHONE_AUDIO_INPUT_DEVICES_LABEL)
    return labels

def _ui_shell_parse_sensory_source_values(value, available_provider_ids=None):
    available = {
        str(item or "").strip().lower()
        for item in list(available_provider_ids or [])
        if str(item or "").strip()
    }
    if value is None:
        return []
    raw_values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    selected = []
    seen = set()
    for item in raw_values:
        token = str(item or "").strip().lower()
        if not token or token == "off" or token in seen:
            continue
        if available and token not in available:
            continue
        selected.append(token)
        seen.add(token)
    return selected

def _ui_shell_sensory_source_options(sensory_providers=None, selected_value=None):
    providers = [
        {
            "id": str(item.get("id") or "").strip().lower(),
            "label": str(item.get("label") or item.get("id") or "").strip(),
        }
        for item in list(sensory_providers or [])
        if str(item.get("id") or "").strip()
    ]
    labels_by_id = {item["id"]: item["label"] or item["id"] for item in providers}
    selected = _ui_shell_parse_sensory_source_values(selected_value, labels_by_id.keys())
    options = [("Off", "off")]
    for item in providers:
        options.append((item["label"] or item["id"], item["id"]))
    if len(selected) > 1:
        selected_labels = [labels_by_id.get(item, item) for item in selected]
        summary = " + ".join(selected_labels[:2])
        if len(selected_labels) > 2:
            summary = f"{len(selected_labels)} sources selected"
        options.insert(1, (summary, ",".join(selected)))
    return options

def _ui_shell_musetalk_avatar_pack_options(session=None):
    payload = dict(session or _read_ui_shell_session_snapshot() or {})
    default_avatar_id = str(payload.get("musetalk_avatar_id", "default_avatar") or "default_avatar").strip() or "default_avatar"
    options = []
    try:
        packs = discover_avatar_packs(
            default_avatar_id=default_avatar_id,
            include_legacy=False,
            include_standalone=False,
        )
    except Exception:
        packs = {}
    for pack_id, pack in packs.items():
        clean_pack_id = str(pack_id or "").strip()
        if not clean_pack_id:
            continue
        label = f"{str(pack.display_name or clean_pack_id).strip() or clean_pack_id} | {str(pack.default_avatar_id or 'default_avatar').strip()} [{str(pack.source or 'manifest').strip() or 'manifest'}]"
        options.append({"id": clean_pack_id, "label": label})
    return options

def _ui_shell_host_core_state(window):
    session = dict(_read_ui_shell_session_snapshot() or {})

    def combo_text(name, fallback=""):
        widget = _ui_shell_find_object(window, name)
        if widget is not None and hasattr(widget, "currentText"):
            text = str(widget.currentText() or "").strip()
            if text:
                return text
        return str(fallback or "").strip()

    def combo_data(name, fallback=""):
        widget = _ui_shell_find_object(window, name)
        if widget is not None and hasattr(widget, "currentData"):
            data = widget.currentData()
            if data is not None and str(data or "").strip():
                return str(data).strip()
        return str(fallback or "").strip()

    def spin_value(name, fallback=0):
        widget = _ui_shell_find_object(window, name)
        if widget is not None and hasattr(widget, "value"):
            try:
                return int(widget.value())
            except Exception:
                pass
        try:
            return int(fallback)
        except Exception:
            return 0

    overflow_value = str(session.get("chat_context_overflow_policy", "rolling_window") or "rolling_window").strip()
    overflow_label = {
        "rolling_window": "Rolling Window",
        "truncate_middle": "Truncate Middle",
        "stop_at_limit": "Stop At Limit",
    }.get(overflow_value, overflow_value.replace("_", " ").title())

    input_mode = combo_text("input_mode_combo", session.get("input_mode", "Voice Activation"))
    input_role = combo_text("input_role_combo", session.get("input_message_role", "User Message"))
    stream_text = combo_text("stream_mode_combo", "On" if _ui_shell_stream_mode_enabled(session.get("stream_mode", False)) else "Off")
    return {
        "audio_input_device": combo_text("audio_input_device_combo", session.get("audio_input_device", "Default Input")),
        "audio_output_device": combo_text("audio_output_device_combo", session.get("audio_output_device", "Default Output")),
        "input_mode": input_mode,
        "input_message_role": input_role,
        "stream_mode": str(stream_text).strip().lower() == "on",
        "stream_mode_label": "On" if str(stream_text).strip().lower() == "on" else "Off",
        "musetalk_vram_mode": combo_text(
            "musetalk_vram_combo",
            str(session.get("musetalk_vram_mode", "quality") or "quality").replace("_", " ").title().replace("Vram", "VRAM"),
        ),
        "musetalk_avatar_pack_id": combo_data("musetalk_avatar_pack_combo", session.get("musetalk_avatar_pack_id", "")),
        "musetalk_avatar_pack_label": combo_text("musetalk_avatar_pack_combo", session.get("musetalk_avatar_pack_id", "")),
        "chat_context_window_messages": spin_value("chat_context_window_spin", session.get("chat_context_window_messages", 20) or 20),
        "stored_chat_history_limit": spin_value("stored_chat_history_limit_spin", session.get("stored_chat_history_limit", 0) or 0),
        "chat_context_overflow_policy": combo_text("chat_overflow_policy_combo", overflow_label),
        "allow_proactive_replies": bool(
            _ui_shell_find_object(window, "allow_proactive_checkbox").isChecked()
        ) if _ui_shell_find_object(window, "allow_proactive_checkbox") is not None and hasattr(_ui_shell_find_object(window, "allow_proactive_checkbox"), "isChecked") else bool(session.get("allow_proactive_replies", False)),
        "require_first_user_before_proactive": bool(
            _ui_shell_find_object(window, "require_first_user_checkbox").isChecked()
        ) if _ui_shell_find_object(window, "require_first_user_checkbox") is not None and hasattr(_ui_shell_find_object(window, "require_first_user_checkbox"), "isChecked") else bool(session.get("require_first_user_before_proactive", False)),
    }

def _ui_shell_refresh_host_core_status(window):
    state = _ui_shell_host_core_state(window)
    _ui_shell_runtime_status_service(window).set_session_overrides(
        input_mode=state.get("input_mode", ""),
        input_message_role=state.get("input_message_role", ""),
        stream_mode=bool(state.get("stream_mode", False)),
        audio_input_device=state.get("audio_input_device", ""),
        audio_output_device=state.get("audio_output_device", ""),
        musetalk_vram_mode=state.get("musetalk_vram_mode", ""),
        musetalk_avatar_pack_id=state.get("musetalk_avatar_pack_id", ""),
        chat_context_window_messages=int(state.get("chat_context_window_messages", 20) or 20),
        stored_chat_history_limit=int(state.get("stored_chat_history_limit", 0) or 0),
        chat_context_overflow_policy=state.get("chat_context_overflow_policy", ""),
    )
    return _ui_shell_refresh_status_labels(window)

def _ui_shell_compose_status_line(window):
    runtime_line = _ui_shell_runtime_status_service(window).status_line()
    state = _ui_shell_host_core_state(window)
    return (
        f"{runtime_line} | "
        f"{state['input_mode']} / {state['input_message_role']} / {'stream' if state['stream_mode'] else 'non-stream'} | "
        f"ctx {state['chat_context_window_messages']} / {state['chat_context_overflow_policy']}"
    )

def _ui_shell_refresh_status_labels(window):
    line = _ui_shell_compose_status_line(window)
    for label_name in ("console_status", "chat_status", "mic_status_label"):
        label = _ui_shell_find_object(window, label_name)
        if label is not None and hasattr(label, "setText"):
            try:
                label.setText(line)
            except Exception:
                pass
    return line

def _apply_ui_shell_preview_status(window):
    summary = _ui_shell_binding_summary(window)
    runtime_status = _ui_shell_runtime_status_service(window).snapshot()
    lines = [
        _ui_shell_compose_status_line(window),
        "addons: limited shell mounts only",
        "engine lifecycle: not connected",
        f"Bindings: {summary['bound']}/{summary['checked']} checked",
    ]
    if summary["missing"] or summary["mismatched"]:
        lines.append("Binding issues: yes, run --shell-smoke")
    else:
        lines.append("Binding issues: none")
    status_text = " | ".join(lines)

    for label_name in ("console_status", "chat_status", "mic_status_label"):
        label = _ui_shell_find_object(window, label_name)
        if label is not None and hasattr(label, "setText"):
            label.setText(status_text)
            if hasattr(label, "setToolTip"):
                label.setToolTip("Visual-only Designer shell preview. No runtime systems are connected.")

    for button_name in ("import_audio_button", "transcribe_audio_button"):
        button = _ui_shell_find_object(window, button_name)
        if button is None:
            continue
        if hasattr(button, "setEnabled"):
            button.setEnabled(False)
        if hasattr(button, "setToolTip"):
            button.setToolTip("Disabled in shell preview. Runtime wiring is intentionally deferred.")

    for button_name in ("btn_start_engine", "btn_stop_engine", "btn_reset_chat"):
        button = _ui_shell_find_object(window, button_name)
        if button is not None and hasattr(button, "setToolTip"):
            button.setToolTip("Shell-local lifecycle preview. No engine/runtime systems are started.")

    return summary

def _ui_shell_text_line_count(widget):
    if widget is None:
        return 0
    if hasattr(widget, "document"):
        try:
            text = widget.document().toPlainText()
        except Exception:
            text = ""
    elif hasattr(widget, "toPlainText"):
        try:
            text = widget.toPlainText()
        except Exception:
            text = ""
    else:
        text = ""
    return len([line for line in str(text or "").splitlines() if line.strip()])

def _apply_workspace_widget_bounds(widget, *, min_width=None, min_height=None, max_height=None, allow_shrink=False):
    if widget is None:
        return
    try:
        if min_width is not None and hasattr(widget, "setMinimumWidth"):
            if allow_shrink:
                widget.setMinimumWidth(max(0, int(min_width)))
            else:
                widget.setMinimumWidth(max(int(min_width), int(getattr(widget, "minimumWidth", lambda: 0)() or 0)))
        if min_height is not None and hasattr(widget, "setMinimumHeight"):
            if allow_shrink:
                widget.setMinimumHeight(max(0, int(min_height)))
            else:
                widget.setMinimumHeight(max(int(min_height), int(getattr(widget, "minimumHeight", lambda: 0)() or 0)))
        if max_height is not None and hasattr(widget, "setMaximumHeight"):
            current_max = int(getattr(widget, "maximumHeight", lambda: 16777215)() or 16777215)
            widget.setMaximumHeight(int(max_height) if current_max <= 0 or current_max >= 16777215 else min(current_max, int(max_height)))
    except Exception:
        pass

def _relax_docked_workspace_minimums(dock, *, min_width=None, min_height=None):
    """Keep docked panels movable by preventing oversized child minimums from forcing tabification."""
    if dock is None:
        return
    if min_width is None:
        min_width = WORKSPACE_DOCKED_VIEW_MIN_WIDTH
    if min_height is None:
        min_height = 180
    try:
        if hasattr(dock, "setMinimumWidth"):
            dock.setMinimumWidth(max(0, int(min_width)))
        if hasattr(dock, "setMinimumHeight"):
            dock.setMinimumHeight(max(0, int(min_height)))
        content = dock.widget() if hasattr(dock, "widget") else None
        if content is None:
            return
        if hasattr(content, "setMinimumWidth"):
            content.setMinimumWidth(max(0, int(min_width)))
        if hasattr(content, "setMinimumHeight"):
            content.setMinimumHeight(max(0, int(min_height)))
        for child in content.findChildren(QtWidgets.QWidget):
            if hasattr(child, "setMinimumWidth"):
                child.setMinimumWidth(0)
            if hasattr(child, "setMinimumHeight"):
                child.setMinimumHeight(0)
    except Exception:
        pass

def _apply_workspace_view_constraints(window, *, extra_widgets=None):
    from PySide6 import QtWidgets as _QtWidgets

    if window is None:
        return
    _apply_workspace_widget_bounds(
        window,
        min_width=WORKSPACE_VIEW_MIN_WIDTH,
        min_height=WORKSPACE_VIEW_MIN_HEIGHT,
        max_height=WORKSPACE_WINDOW_MAX_HEIGHT,
    )

    dock_specs = {
        "SystemShapingDock": WORKSPACE_VIEW_MIN_HEIGHT,
        "WorkspaceTabsDock": WORKSPACE_VIEW_MIN_HEIGHT,
        "OperationalViewDock": WORKSPACE_VIEW_MIN_HEIGHT,
        "MuseTalkPreviewDock": WORKSPACE_DOCKED_AUX_MIN_HEIGHT,
        "PreviewDock": WORKSPACE_DOCKED_AUX_MIN_HEIGHT,
        "VisualReplyDock": WORKSPACE_DOCKED_AUX_MIN_HEIGHT,
    }
    for object_name, docked_min_height in dock_specs.items():
        dock = _ui_shell_find_object(window, object_name)
        if dock is None or not isinstance(dock, _QtWidgets.QDockWidget):
            continue
        min_height = WORKSPACE_VIEW_MIN_HEIGHT if dock.isFloating() else docked_min_height
        min_width = WORKSPACE_VIEW_MIN_WIDTH if dock.isFloating() else WORKSPACE_DOCKED_VIEW_MIN_WIDTH
        _apply_workspace_widget_bounds(
            dock,
            min_width=min_width,
            min_height=min_height,
            max_height=WORKSPACE_VIEW_MAX_HEIGHT,
            allow_shrink=not dock.isFloating(),
        )
        content = dock.widget() if hasattr(dock, "widget") else None
        if content is not None:
            content_min_height = WORKSPACE_VIEW_MIN_HEIGHT if dock.isFloating() else max(docked_min_height, 360)
            _apply_workspace_widget_bounds(
                content,
                min_width=min_width,
                min_height=content_min_height,
                max_height=WORKSPACE_VIEW_MAX_HEIGHT,
                allow_shrink=not dock.isFloating(),
            )

    operational_dock = _ui_shell_find_object(window, "OperationalViewDock")
    operational_floating = bool(
        operational_dock is not None
        and isinstance(operational_dock, _QtWidgets.QDockWidget)
        and operational_dock.isFloating()
    )

    container_specs = (
        ("system_shaping_panel", WORKSPACE_VIEW_MIN_WIDTH, WORKSPACE_VIEW_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("system_shaping_scroll", WORKSPACE_VIEW_MIN_WIDTH, WORKSPACE_VIEW_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("system_shaping_content", WORKSPACE_VIEW_MIN_WIDTH, WORKSPACE_VIEW_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("workspace_tabs_panel", WORKSPACE_VIEW_MIN_WIDTH, WORKSPACE_VIEW_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("host_settings_tabs", WORKSPACE_INNER_MIN_WIDTH, WORKSPACE_INNER_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("left_tabs", WORKSPACE_INNER_MIN_WIDTH, WORKSPACE_INNER_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("vseeface_tabs", 760, 620, WORKSPACE_VIEW_MAX_HEIGHT),
        ("musetalk_tabs", 760, 620, WORKSPACE_VIEW_MAX_HEIGHT),
        ("tts_runtime_addon_tabs", 760, 620, WORKSPACE_VIEW_MAX_HEIGHT),
        ("sensory_feedback_tabs", 760, 620, WORKSPACE_VIEW_MAX_HEIGHT),
        ("audio_story_mode_tab", WORKSPACE_INNER_MIN_WIDTH, WORKSPACE_VIEW_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("preview_dock_content", WORKSPACE_VIEW_MIN_WIDTH, WORKSPACE_VIEW_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("visual_reply_panel", WORKSPACE_VIEW_MIN_WIDTH, WORKSPACE_VIEW_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("visual_reply_frame", WORKSPACE_INNER_MIN_WIDTH, WORKSPACE_PREVIEW_FRAME_MIN_HEIGHT, WORKSPACE_VIEW_MAX_HEIGHT),
        ("console_edit", 0, 280, WORKSPACE_VIEW_MAX_HEIGHT),
        ("chat_edit", 0, 280, WORKSPACE_VIEW_MAX_HEIGHT),
    )
    for object_name, min_width, min_height, max_height in container_specs:
        _apply_workspace_widget_bounds(
            _ui_shell_find_object(window, object_name),
            min_width=min_width,
            min_height=min_height,
            max_height=max_height,
        )

    operational_min_width = WORKSPACE_VIEW_MIN_WIDTH if operational_floating else 0
    operational_min_height = WORKSPACE_VIEW_MIN_HEIGHT if operational_floating else 0
    for object_name in ("operational_view_panel", "operational_scroll", "operational_content", "right_tabs"):
        _apply_workspace_widget_bounds(
            _ui_shell_find_object(window, object_name),
            min_width=operational_min_width,
            min_height=operational_min_height,
            max_height=WORKSPACE_VIEW_MAX_HEIGHT,
            allow_shrink=not operational_floating,
        )

    for widget in tuple(extra_widgets or ()):
        _apply_workspace_widget_bounds(
            widget,
            min_width=WORKSPACE_VIEW_MIN_WIDTH,
            min_height=WORKSPACE_VIEW_MIN_HEIGHT,
            max_height=WORKSPACE_VIEW_MAX_HEIGHT,
        )

    for object_name in dock_specs:
        dock = _ui_shell_find_object(window, object_name)
        if dock is not None and isinstance(dock, _QtWidgets.QDockWidget) and not dock.isFloating():
            _relax_docked_workspace_minimums(dock, min_height=180)
