"""Local control binders for the lightweight Designer UI shell."""


def configure_shell_local_bindings_dependencies(namespace):
    """Inject qt_app-owned Qt objects and shell services without importing the app."""
    globals().update(dict(namespace or {}))


def _bind_ui_shell_console_chat_local_controls(window):
    from PySide6 import QtCore as _QtCore
    from PySide6 import QtGui as _QtGui
    from PySide6 import QtWidgets as _QtWidgets

    console_edit = _ui_shell_find_object(window, "console_edit")
    chat_edit = _ui_shell_find_object(window, "chat_edit")
    console_status = _ui_shell_find_object(window, "console_status")
    chat_status = _ui_shell_find_object(window, "chat_status")
    console_autoscroll_button = _ui_shell_find_object(window, "console_autoscroll_button")
    chat_autoscroll_button = _ui_shell_find_object(window, "chat_autoscroll_button")
    console_clear_button = _ui_shell_find_object(window, "console_clear_button")
    chat_clear_button = _ui_shell_find_object(window, "chat_clear_button")
    chat_font_size_combo = _ui_shell_find_object(window, "chat_font_size_combo")
    chat_edit_mode_button = _ui_shell_find_object(window, "chat_edit_mode_button")
    chat_apply_edit_button = _ui_shell_find_object(window, "chat_apply_edit_button")
    chat_cancel_edit_button = _ui_shell_find_object(window, "chat_cancel_edit_button")
    quick_save_button = _ui_shell_find_object(window, "chat_quick_save_button")
    quick_load_button = _ui_shell_find_object(window, "chat_quick_load_button")

    state = {
        "console_autoscroll": True,
        "chat_autoscroll": True,
        "chat_editing": False,
        "chat_edit_snapshot": "",
    }

    def set_button_text(button, label, enabled):
        if button is not None and hasattr(button, "setText"):
            button.setText(f"{label}: {'On' if enabled else 'Off'}")

    def update_console_status():
        if console_status is not None and hasattr(console_status, "setText"):
            console_status.setText(
                f"{_ui_shell_text_line_count(console_edit)} lines | "
                f"autoscroll {'on' if state['console_autoscroll'] else 'off'} | shell-local"
            )

    def update_chat_status():
        if chat_status is not None and hasattr(chat_status, "setText"):
            mode = "edit mode" if state["chat_editing"] else "read-only"
            chat_status.setText(
                f"{_ui_shell_text_line_count(chat_edit)} lines | "
                f"autoscroll {'on' if state['chat_autoscroll'] else 'off'} | {mode} | shell-local"
            )

    def set_chat_editing(enabled):
        state["chat_editing"] = bool(enabled)
        if isinstance(chat_edit, _QtWidgets.QTextEdit):
            chat_edit.setReadOnly(not state["chat_editing"])
        if chat_edit_mode_button is not None:
            chat_edit_mode_button.setVisible(not state["chat_editing"])
        if chat_apply_edit_button is not None:
            chat_apply_edit_button.setVisible(state["chat_editing"])
        if chat_cancel_edit_button is not None:
            chat_cancel_edit_button.setVisible(state["chat_editing"])
        update_chat_status()

    if isinstance(console_edit, _QtWidgets.QPlainTextEdit):
        console_edit.setReadOnly(True)
        console_edit.textChanged.connect(update_console_status)
    if isinstance(chat_edit, _QtWidgets.QTextEdit):
        chat_edit.setReadOnly(True)
        chat_edit.textChanged.connect(update_chat_status)

    if console_clear_button is not None and hasattr(console_clear_button, "clicked"):
        console_clear_button.clicked.connect(lambda: (console_edit.clear(), update_console_status()) if console_edit is not None else None)
    if chat_clear_button is not None and hasattr(chat_clear_button, "clicked"):
        chat_clear_button.clicked.connect(lambda: (chat_edit.clear(), update_chat_status()) if chat_edit is not None else None)

    if console_autoscroll_button is not None and hasattr(console_autoscroll_button, "clicked"):
        console_autoscroll_button.clicked.connect(
            lambda: (
                state.__setitem__("console_autoscroll", not state["console_autoscroll"]),
                set_button_text(console_autoscroll_button, "Autoscroll", state["console_autoscroll"]),
                update_console_status(),
            )
        )
    if chat_autoscroll_button is not None and hasattr(chat_autoscroll_button, "clicked"):
        chat_autoscroll_button.clicked.connect(
            lambda: (
                state.__setitem__("chat_autoscroll", not state["chat_autoscroll"]),
                set_button_text(chat_autoscroll_button, "Autoscroll", state["chat_autoscroll"]),
                update_chat_status(),
            )
        )

    if isinstance(chat_font_size_combo, _QtWidgets.QComboBox):
        chat_font_size_combo.clear()
        for size in (10, 11, 12, 13, 14, 16, 18):
            chat_font_size_combo.addItem(str(size), size)
        index = chat_font_size_combo.findData(12)
        if index >= 0:
            chat_font_size_combo.setCurrentIndex(index)

        def apply_font_size():
            if not isinstance(chat_edit, _QtWidgets.QTextEdit):
                return
            size = chat_font_size_combo.currentData()
            try:
                point_size = int(size)
            except Exception:
                point_size = 12
            font = _QtGui.QFont(chat_edit.font())
            font.setPointSize(max(6, point_size))
            chat_edit.setFont(font)

        chat_font_size_combo.currentIndexChanged.connect(lambda _index: apply_font_size())
        apply_font_size()

    if chat_edit_mode_button is not None and hasattr(chat_edit_mode_button, "clicked"):
        chat_edit_mode_button.clicked.connect(
            lambda: (
                state.__setitem__("chat_edit_snapshot", chat_edit.toPlainText() if chat_edit is not None else ""),
                set_chat_editing(True),
            )
        )
    if chat_apply_edit_button is not None and hasattr(chat_apply_edit_button, "clicked"):
        chat_apply_edit_button.clicked.connect(lambda: set_chat_editing(False))
    if chat_cancel_edit_button is not None and hasattr(chat_cancel_edit_button, "clicked"):
        chat_cancel_edit_button.clicked.connect(
            lambda: (
                chat_edit.setPlainText(state["chat_edit_snapshot"]) if chat_edit is not None else None,
                set_chat_editing(False),
            )
        )

    set_button_text(console_autoscroll_button, "Autoscroll", state["console_autoscroll"])
    set_button_text(chat_autoscroll_button, "Autoscroll", state["chat_autoscroll"])
    set_chat_editing(False)
    update_console_status()
    update_chat_status()
    return {
        "bound": [
            name for name, widget in (
                ("console_clear_button", console_clear_button),
                ("console_autoscroll_button", console_autoscroll_button),
                ("chat_clear_button", chat_clear_button),
                ("chat_autoscroll_button", chat_autoscroll_button),
                ("chat_font_size_combo", chat_font_size_combo),
                ("chat_edit_mode_button", chat_edit_mode_button),
                ("chat_apply_edit_button", chat_apply_edit_button),
                ("chat_cancel_edit_button", chat_cancel_edit_button),
            ) if widget is not None
        ],
        "deferred": [],
    }

def _bind_ui_shell_lifecycle_local_controls(window):
    start_button = _ui_shell_find_object(window, "btn_start_engine")
    stop_button = _ui_shell_find_object(window, "btn_stop_engine")
    reset_button = _ui_shell_find_object(window, "btn_reset_chat")
    console_edit = _ui_shell_find_object(window, "console_edit")
    chat_edit = _ui_shell_find_object(window, "chat_edit")
    console_status = _ui_shell_find_object(window, "console_status")
    chat_status = _ui_shell_find_object(window, "chat_status")
    mic_status = _ui_shell_find_object(window, "mic_status_label")
    runtime_status = _ui_shell_runtime_status_service(window)
    lifecycle = _ui_shell_engine_lifecycle_service(window)

    state = {"running": False}

    def append_console(message):
        if console_edit is None:
            return
        try:
            if hasattr(console_edit, "appendPlainText"):
                console_edit.appendPlainText(str(message))
            elif hasattr(console_edit, "append"):
                console_edit.append(str(message))
        except Exception:
            pass

    def set_status(message):
        for label in (console_status, chat_status, mic_status):
            if label is not None and hasattr(label, "setText"):
                label.setText(str(message))

    def refresh_buttons():
        if start_button is not None and hasattr(start_button, "setEnabled"):
            start_button.setEnabled(not state["running"])
        if stop_button is not None and hasattr(stop_button, "setEnabled"):
            stop_button.setEnabled(state["running"])
        if reset_button is not None and hasattr(reset_button, "setEnabled"):
            reset_button.setEnabled(True)
        if start_button is not None and hasattr(start_button, "setToolTip"):
            start_button.setToolTip("Shell-local Initialize preview. Does not start the companion engine.")
        if stop_button is not None and hasattr(stop_button, "setToolTip"):
            stop_button.setToolTip("Shell-local Terminate preview. Does not stop any runtime system.")
        if reset_button is not None and hasattr(reset_button, "setToolTip"):
            reset_button.setToolTip("Shell-local reset preview. Clears only the Designer shell chat widget.")

    def start_preview():
        snapshot = lifecycle.start_engine()
        state["running"] = bool(snapshot.get("running"))
        refresh_buttons()
        set_status(runtime_status.status_line())
        append_console("[UI Shell] Initialize preview: no runtime systems were started.")

    def stop_preview():
        snapshot = lifecycle.stop_engine()
        state["running"] = bool(snapshot.get("running"))
        refresh_buttons()
        set_status(runtime_status.status_line())
        append_console("[UI Shell] Terminate preview: no runtime systems were stopped.")

    def reset_preview():
        lifecycle.reset_chat_memory()
        if chat_edit is not None and hasattr(chat_edit, "clear"):
            try:
                chat_edit.clear()
            except Exception:
                pass
        append_console("[UI Shell] Reset preview: shell chat widget cleared only.")

    if start_button is not None and hasattr(start_button, "clicked"):
        start_button.clicked.connect(start_preview)
    if stop_button is not None and hasattr(stop_button, "clicked"):
        stop_button.clicked.connect(stop_preview)
    if reset_button is not None and hasattr(reset_button, "clicked"):
        reset_button.clicked.connect(reset_preview)
    refresh_buttons()
    return {
        "bound": [
            name for name, widget in (
                ("btn_start_engine", start_button),
                ("btn_stop_engine", stop_button),
                ("btn_reset_chat", reset_button),
            )
            if widget is not None
        ],
        "mode": "shell-local",
    }

def _bind_ui_shell_runtime_action_controls(window):
    controls = _ui_shell_runtime_controls_service(window)
    console_edit = _ui_shell_find_object(window, "console_edit")
    action_buttons = {
        "btn_regenerate": "regenerate_response",
        "btn_retry": "retry_user_input",
        "btn_pause": "pause_speech",
        "btn_skip": "skip_speech",
        "btn_skip_user": "skip_user_reply",
    }
    bound = []

    def append_console(message):
        if console_edit is None:
            return
        try:
            if hasattr(console_edit, "appendPlainText"):
                console_edit.appendPlainText(str(message))
            elif hasattr(console_edit, "append"):
                console_edit.append(str(message))
        except Exception:
            pass

    for object_name, action in action_buttons.items():
        button = _ui_shell_find_object(window, object_name)
        if button is None or not callable(callback):
            continue
        bound.append(object_name)
        if hasattr(button, "setEnabled"):
            button.setEnabled(True)
        if hasattr(button, "setToolTip"):
            button.setToolTip("Shell-local control preview. No runtime action is sent.")
        if hasattr(button, "clicked") and not getattr(button, "_nc_ui_shell_runtime_control_bound", False):
            button.clicked.connect(
                lambda _checked=False, action_key=action: append_console(
                    f"[UI Shell] Control preview: {controls.trigger(action_key).get('action')} not sent to runtime."
                )
            )
            setattr(button, "_nc_ui_shell_runtime_control_bound", True)

    return {
        "bound": bound,
        "mode": "shell-local",
        "actions": list(controls.SUPPORTED_ACTIONS),
    }

def _bind_ui_shell_chat_context_controls(window):
    service = _ui_shell_chat_context_service(window)
    console_edit = _ui_shell_find_object(window, "console_edit")
    chat_edit = _ui_shell_find_object(window, "chat_edit")
    buttons = {
        "chat_quick_save_button": ("Quick Save", service.quick_save_chat_context),
        "chat_quick_load_button": ("Quick Load", service.quick_load_chat_context),
        "btn_save_chat_session": ("Save Chat Context", service.save_chat_context),
        "btn_save_chat_session_as": ("Save Chat Context As...", getattr(service, "save_chat_context_as", None)),
        "btn_load_chat_session": ("Load Chat Context", service.load_chat_context),
        "btn_reset_chat_session": ("Reset Chat Memory", service.reset_chat_memory),
    }
    bound = []

    def append_console(message):
        if console_edit is None:
            return
        try:
            if hasattr(console_edit, "appendPlainText"):
                console_edit.appendPlainText(str(message))
            elif hasattr(console_edit, "append"):
                console_edit.append(str(message))
        except Exception:
            pass

    def make_handler(label, callback, object_name):
        def handler():
            snapshot = callback()
            if object_name == "btn_reset_chat_session" and chat_edit is not None and hasattr(chat_edit, "clear"):
                try:
                    chat_edit.clear()
                except Exception:
                    pass
            append_console(f"[UI Shell] {label}: {snapshot.get('message')}")
        return handler

    for object_name, (label, callback) in buttons.items():
        button = _ui_shell_find_object(window, object_name)
        if button is None:
            continue
        bound.append(object_name)
        if hasattr(button, "setEnabled"):
            button.setEnabled(True)
        if hasattr(button, "setToolTip"):
            button.setToolTip("Shell-local chat context preview. No file/session data is read or written.")
        if hasattr(button, "clicked") and not getattr(button, "_nc_ui_shell_chat_context_bound", False):
            button.clicked.connect(make_handler(label, callback, object_name))
            setattr(button, "_nc_ui_shell_chat_context_bound", True)

    return {
        "bound": bound,
        "mode": "shell-local",
    }

def _bind_ui_shell_tutorial_controls(window):
    from PySide6 import QtCore as _QtCore
    from PySide6 import QtWidgets as _QtWidgets

    service = _ui_shell_tutorial_service(window)
    tutorials_list = _ui_shell_find_object(window, "tutorials_list")
    description = _ui_shell_find_object(window, "tutorial_description")
    refresh_button = _ui_shell_find_object(window, "btn_tutorial_refresh")
    start_button = _ui_shell_find_object(window, "btn_tutorial_start")
    console_edit = _ui_shell_find_object(window, "console_edit")
    bound = []

    def append_console(message):
        if console_edit is None:
            return
        try:
            if hasattr(console_edit, "appendPlainText"):
                console_edit.appendPlainText(str(message))
            elif hasattr(console_edit, "append"):
                console_edit.append(str(message))
        except Exception:
            pass

    def selected_tutorial_id():
        if tutorials_list is None or not hasattr(tutorials_list, "currentItem"):
            return ""
        item = tutorials_list.currentItem()
        if item is None:
            return ""
        try:
            return str(item.data(_QtCore.Qt.UserRole) or "").strip()
        except Exception:
            return ""

    def render_description():
        tutorial_id = selected_tutorial_id()
        payload = service.load_tutorial(tutorial_id)
        if description is not None and hasattr(description, "setPlainText"):
            if payload:
                text = (
                    f"{payload.get('title', tutorial_id)}\n\n"
                    f"{payload.get('description', '')}\n\n"
                    f"Steps: {len(list(payload.get('steps') or []))}\n\n"
                    "Shell preview: Start Tutorial logs a preview only; no overlay is created."
                )
                description.setPlainText(text.strip())
            else:
                description.setPlainText("Select a tutorial to see its description.")
        if start_button is not None and hasattr(start_button, "setEnabled"):
            start_button.setEnabled(bool(payload))

    def refresh_list():
        tutorials = service.list_tutorials()
        if tutorials_list is not None and hasattr(tutorials_list, "clear"):
            tutorials_list.blockSignals(True)
            try:
                tutorials_list.clear()
                for item in tutorials:
                    label = f"{item.get('title', item.get('id', 'Tutorial'))} ({int(item.get('step_count', 0) or 0)} steps)"
                    list_item = _QtWidgets.QListWidgetItem(label)
                    list_item.setData(_QtCore.Qt.UserRole, str(item.get("id") or ""))
                    list_item.setToolTip(str(item.get("description") or ""))
                    tutorials_list.addItem(list_item)
                if tutorials:
                    tutorials_list.setCurrentRow(0)
            finally:
                tutorials_list.blockSignals(False)
        render_description()

    def start_selected():
        tutorial_id = selected_tutorial_id()
        snapshot = service.start_tutorial(tutorial_id)
        append_console(f"[UI Shell] Tutorial preview: {snapshot.get('message')} ({tutorial_id or 'none'})")

    if tutorials_list is not None:
        bound.append("tutorials_list")
        if hasattr(tutorials_list, "currentRowChanged") and not getattr(tutorials_list, "_nc_ui_shell_tutorial_bound", False):
            tutorials_list.currentRowChanged.connect(lambda _row: render_description())
            setattr(tutorials_list, "_nc_ui_shell_tutorial_bound", True)
    if description is not None:
        bound.append("tutorial_description")
        if hasattr(description, "setReadOnly"):
            description.setReadOnly(True)
    if refresh_button is not None:
        bound.append("btn_tutorial_refresh")
        refresh_button.setEnabled(True)
        refresh_button.setToolTip("Shell-local tutorial list refresh from JSON files only.")
        if hasattr(refresh_button, "clicked") and not getattr(refresh_button, "_nc_ui_shell_tutorial_bound", False):
            refresh_button.clicked.connect(refresh_list)
            setattr(refresh_button, "_nc_ui_shell_tutorial_bound", True)
    if start_button is not None:
        bound.append("btn_tutorial_start")
        start_button.setToolTip("Shell-local tutorial preview. No overlay is created.")
        if hasattr(start_button, "clicked") and not getattr(start_button, "_nc_ui_shell_tutorial_bound", False):
            start_button.clicked.connect(start_selected)
            setattr(start_button, "_nc_ui_shell_tutorial_bound", True)

    refresh_list()
    return {
        "bound": bound,
        "tutorials": len(service.list_tutorials()),
        "mode": "shell-local",
    }
