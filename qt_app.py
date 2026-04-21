import glob
import base64
import json
import logging
import math
import os
import ctypes
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import warnings
import importlib.util
from collections import OrderedDict
from pathlib import Path
import xml.etree.ElementTree as ET


UI_VALIDATION_REQUIRED_GROUPS = (
    (
        "Core Shell",
        (
            ("CompanionQtMainWindow", "QMainWindow"),
            ("workspace_central", "QWidget"),
            ("SystemShapingDock", "QDockWidget"),
            ("WorkspaceTabsDock", "QDockWidget"),
            ("OperationalViewDock", "QDockWidget"),
            ("PreviewDock", "QDockWidget"),
            ("VisualReplyDock", "QDockWidget"),
        ),
    ),
    (
        "Stable Tab Mounts",
        (
            ("host_settings_tabs", "QTabWidget"),
            ("left_tabs", "QTabWidget"),
            ("right_tabs", "QTabWidget"),
            ("musetalk_tabs", "QTabWidget"),
            ("sensory_feedback_tabs", "QTabWidget"),
            ("vseeface_tabs", "QTabWidget"),
        ),
    ),
    (
        "Dynamic Mount Points",
        (
            ("left_tabs", "QTabWidget"),
            ("host_settings_tabs", "QTabWidget"),
            ("right_tabs", "QTabWidget"),
            ("musetalk_tabs", "QTabWidget"),
            ("tts_runtime_addon_tabs", "QTabWidget"),
            ("sensory_feedback_tabs", "QTabWidget"),
            ("sensory_feedback_sources_widget", "QWidget"),
            ("chat_provider_fields_widget", "QWidget"),
            ("chat_provider_generation_fields_widget", "QWidget"),
            ("chat_provider_fields_layout", "QFormLayout"),
            ("chat_provider_generation_fields_layout", "QFormLayout"),
        ),
    ),
    (
        "Stable Runtime Controls",
        (
            ("listen_diode", "QFrame"),
            ("mic_diode", "QFrame"),
            ("mic_status_label", "QLabel"),
            ("audio_input_device_combo", "QComboBox"),
            ("audio_output_device_combo", "QComboBox"),
            ("engine_combo", "QComboBox"),
            ("input_mode_combo", "QComboBox"),
            ("input_role_combo", "QComboBox"),
            ("stream_mode_combo", "QComboBox"),
            ("tts_backend_combo", "QComboBox"),
            ("musetalk_vram_combo", "QComboBox"),
            ("musetalk_loop_fade_spin", "QSpinBox"),
            ("musetalk_avatar_pack_combo", "QComboBox"),
            ("preset_combo", "QComboBox"),
            ("chat_provider_combo", "QComboBox"),
            ("model_combo", "QComboBox"),
            ("visual_reply_mode_combo", "QComboBox"),
            ("visual_reply_provider_combo", "QComboBox"),
            ("visual_reply_size_combo", "QComboBox"),
            ("visual_reply_model_edit", "QLineEdit"),
            ("sensory_feedback_source_combo", "QComboBox"),
            ("sensory_feedback_sources_widget", "QWidget"),
            ("console_status", "QLabel"),
            ("console_autoscroll_button", "QPushButton"),
            ("console_clear_button", "QPushButton"),
            ("console_edit", "QPlainTextEdit"),
            ("chat_status", "QLabel"),
            ("chat_font_size_combo", "QComboBox"),
            ("chat_quick_save_button", "QPushButton"),
            ("chat_quick_load_button", "QPushButton"),
            ("chat_edit_mode_button", "QPushButton"),
            ("chat_apply_edit_button", "QPushButton"),
            ("chat_cancel_edit_button", "QPushButton"),
            ("chat_autoscroll_button", "QPushButton"),
            ("chat_clear_button", "QPushButton"),
            ("chat_edit", "QTextEdit"),
            ("btn_regenerate", "QPushButton"),
            ("btn_retry", "QPushButton"),
            ("btn_pause", "QPushButton"),
            ("btn_skip", "QPushButton"),
            ("btn_skip_user", "QPushButton"),
            ("btn_start_engine", "QPushButton"),
            ("btn_stop_engine", "QPushButton"),
            ("btn_reset_chat", "QPushButton"),
        ),
    ),
)

UI_VALIDATION_DYNAMIC_OWNED_PREFIXES = (
    "audio_story_",
)

UI_VALIDATION_DYNAMIC_OWNED_NAMES = {
    "story_mode_button",
    "visual_master_prompt_label",
    "visual_master_prompt_no_speech_bubbles_button",
    "visual_master_prompt_safe_button",
    "visual_master_prompt_text",
    "visual_reply_caption_button",
    "visual_reply_clear_button",
    "visual_reply_delete_all_button",
    "visual_reply_delete_button",
    "visual_reply_frame",
    "visual_reply_image_label",
    "visual_reply_load_button",
    "visual_reply_load_current_story_button",
    "visual_reply_next_button",
    "visual_reply_panel",
    "visual_reply_previous_button",
    "visual_reply_status",
    "visual_reply_storage_label",
    "visual_reply_story_max_images_spin",
    "visual_reply_use_current_style_button",
    "theme_anime",
    "theme_anime_edit",
    "theme_cartoon",
    "theme_cartoon_edit",
    "theme_cyberpunk",
    "theme_cyberpunk_edit",
    "theme_realistic",
    "theme_realistic_edit",
    "theme_retro",
    "theme_retro_edit",
    "theme_storybook",
    "theme_storybook_edit",
}

UI_SHELL_LIVE_ADDON_IDS = {
    "nc.audio_story_mode",
    "nc.chatterbox_tts",
    "nc.chat_provider_lmstudio",
    "nc.chat_provider_openai",
    "nc.chat_provider_xai",
    "nc.chat_session_player",
    "nc.claude_provider",
    "nc.clipboard_source",
    "nc.clipboard_supervisor",
    "nc.gemini_tts_preview",
    "nc.heart_rate_behavior",
    "nc.hotkeys",
    "nc.loop_authoring",
    "nc.mock_heart_rate",
    "nc.musetalk_preprocess",
    "nc.pockettts",
    "nc.screen_supervisor",
    "nc.visual_reply",
    "nc.visual_story_settings",
    "nc.webcam_supervisor",
}

UI_SHELL_TAB_MOUNT_WIDGETS = (
    "left_tabs",
    "host_settings_tabs",
    "right_tabs",
    "musetalk_tabs",
    "tts_runtime_addon_tabs",
    "sensory_feedback_tabs",
    "vseeface_tabs",
)


def _resolve_ui_path(raw_path):
    ui_path = Path(str(raw_path or "").strip() or "main.ui")
    return ui_path if ui_path.is_absolute() else (Path(__file__).resolve().parent / ui_path)


def _collect_ui_object_classes(ui_path):
    tree = ET.parse(ui_path)
    objects = {}
    duplicates = []
    seen = {}
    for element in tree.getroot().iter():
        if element.tag not in {"widget", "layout", "action"}:
            continue
        object_name = str(element.attrib.get("name") or "").strip()
        if not object_name:
            continue
        object_class = str(element.attrib.get("class") or element.tag or "").strip()
        if object_name in seen:
            duplicates.append((object_name, seen[object_name], object_class))
        else:
            seen[object_name] = object_class
        objects[object_name] = object_class
    return objects, duplicates


def _ui_shell_tab_page_title(tab_page):
    for attribute_element in tab_page.findall("attribute"):
        if str(attribute_element.attrib.get("name") or "") != "title":
            continue
        string_element = attribute_element.find("string")
        if string_element is not None and string_element.text is not None:
            return str(string_element.text or "").strip()
    for property_element in tab_page.findall("property"):
        if str(property_element.attrib.get("name") or "") != "title":
            continue
        string_element = property_element.find("string")
        if string_element is not None and string_element.text is not None:
            return str(string_element.text or "").strip()
    for attribute_element in tab_page.findall("attribute"):
        if str(attribute_element.attrib.get("name") or "") != "toolTip":
            continue
        string_element = attribute_element.find("string")
        if string_element is not None and string_element.text is not None:
            return str(string_element.text or "").strip()
    return ""


def _collect_ui_shell_static_tabs(ui_path):
    try:
        tree = ET.parse(ui_path)
    except Exception:
        return {}
    tab_widgets = {}
    for widget in tree.getroot().iter("widget"):
        if str(widget.attrib.get("class") or "") != "QTabWidget":
            continue
        object_name = str(widget.attrib.get("name") or "").strip()
        if object_name not in UI_SHELL_TAB_MOUNT_WIDGETS:
            continue
        pages = []
        for child in list(widget):
            if child.tag != "widget":
                continue
            page_name = str(child.attrib.get("name") or "").strip()
            page_title = _ui_shell_tab_page_title(child) or page_name or "(untitled)"
            pages.append({"object_name": page_name, "title": page_title})
        tab_widgets[object_name] = pages
    return tab_widgets


def validate_ui_file(raw_path):
    ui_path = _resolve_ui_path(raw_path)
    print(f"[UI Validation] File: {ui_path}")
    if not ui_path.exists():
        print("[UI Validation] ERROR: UI file not found.")
        return 2
    try:
        objects, duplicates = _collect_ui_object_classes(ui_path)
    except Exception as exc:
        print(f"[UI Validation] ERROR: Could not parse UI file: {exc}")
        return 2

    missing = []
    mismatched = []
    required_names = {
        object_name
        for _group_name, requirements in UI_VALIDATION_REQUIRED_GROUPS
        for object_name, _expected_class in requirements
    }
    print(f"[UI Validation] Object names: {len(objects)}")
    if duplicates:
        print("[UI Validation] Duplicate widget/layout/action objectNames:")
        for object_name, first_class, duplicate_class in duplicates:
            print(f"  - {object_name}: {first_class} and {duplicate_class}")
    else:
        print("[UI Validation] Duplicate widget/layout/action objectNames: none")

    for group_name, requirements in UI_VALIDATION_REQUIRED_GROUPS:
        group_missing = []
        group_mismatched = []
        for object_name, expected_class in requirements:
            actual_class = objects.get(object_name)
            if actual_class is None:
                group_missing.append((object_name, expected_class))
                missing.append((group_name, object_name, expected_class))
            elif actual_class != expected_class:
                group_mismatched.append((object_name, expected_class, actual_class))
                mismatched.append((group_name, object_name, expected_class, actual_class))
        print(f"[UI Validation] {group_name}:")
        if not group_missing and not group_mismatched:
            print("  OK")
        for object_name, expected_class in group_missing:
            print(f"  MISSING {object_name} ({expected_class})")
        for object_name, expected_class, actual_class in group_mismatched:
            print(f"  TYPE {object_name}: expected {expected_class}, found {actual_class}")

    dynamic_owned = []
    for object_name in sorted(objects):
        if object_name in required_names:
            continue
        if object_name in UI_VALIDATION_DYNAMIC_OWNED_NAMES or any(
            object_name.startswith(prefix) for prefix in UI_VALIDATION_DYNAMIC_OWNED_PREFIXES
        ):
            dynamic_owned.append((object_name, objects[object_name]))
    print("[UI Validation] Dynamic addon-owned UI present in main.ui; keep as preview/static shell until later binding:")
    if dynamic_owned:
        for object_name, object_class in dynamic_owned:
            print(f"  - {object_name} ({object_class})")
    else:
        print("  none")

    if missing or mismatched or duplicates:
        print("[UI Validation] Result: NOT READY for safe real-logic binding.")
    else:
        print("[UI Validation] Result: READY for the checked Phase 1 binding prerequisites.")
    return 0


if len(sys.argv) >= 2 and str(sys.argv[1] or "").strip().lower() == "--validate-ui":
    ui_arg = sys.argv[2] if len(sys.argv) >= 3 else "main.ui"
    sys.exit(validate_ui_file(ui_arg))


def _load_ui_shell_for_smoke(ui_path):
    from PySide6 import QtCore as _QtCore
    from PySide6 import QtUiTools as _QtUiTools
    from PySide6 import QtWidgets as _QtWidgets

    app = _QtWidgets.QApplication.instance() or _QtWidgets.QApplication(sys.argv)
    ui_file = _QtCore.QFile(str(ui_path))
    if not ui_file.open(_QtCore.QIODevice.ReadOnly):
        raise RuntimeError(f"Could not open UI file: {ui_path}")
    try:
        window = _QtUiTools.QUiLoader().load(ui_file)
    finally:
        ui_file.close()
    if window is None:
        raise RuntimeError(f"Qt Designer UI did not produce a window: {ui_path}")
    return app, window


def _ui_shell_find_object(window, object_name):
    from PySide6 import QtCore as _QtCore

    if str(window.objectName() or "") == object_name:
        return window
    return window.findChild(_QtCore.QObject, object_name)


def _ui_shell_enable_stdio_unicode_fallback():
    """Shell mode may import modules that print emoji on Windows cp1252 consoles."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors="replace")
        except TypeError:
            try:
                reconfigure(encoding=getattr(stream, "encoding", None) or "utf-8", errors="replace")
            except Exception:
                pass
        except Exception:
            pass


def _ui_shell_class_matches(obj, expected_class):
    if obj is None:
        return False
    return any(cls.__name__ == expected_class for cls in obj.__class__.mro())


def run_ui_shell_smoke(raw_path):
    ui_path = _resolve_ui_path(raw_path)
    print(f"[UI Shell Smoke] File: {ui_path}")
    if not ui_path.exists():
        print("[UI Shell Smoke] ERROR: UI file not found.")
        return 2
    app = None
    window = None
    try:
        app, window = _load_ui_shell_for_smoke(ui_path)
    except Exception as exc:
        print(f"[UI Shell Smoke] ERROR: Could not load Designer shell: {exc}")
        return 2

    missing = []
    mismatched = []
    bound_total = 0
    for group_name, requirements in UI_VALIDATION_REQUIRED_GROUPS:
        group_bound = 0
        group_missing = []
        group_mismatched = []
        for object_name, expected_class in requirements:
            obj = _ui_shell_find_object(window, object_name)
            if obj is None:
                group_missing.append((object_name, expected_class))
                missing.append((group_name, object_name, expected_class))
                continue
            if not _ui_shell_class_matches(obj, expected_class):
                actual_class = obj.__class__.__name__
                group_mismatched.append((object_name, expected_class, actual_class))
                mismatched.append((group_name, object_name, expected_class, actual_class))
                continue
            group_bound += 1
        bound_total += group_bound
        print(f"[UI Shell Smoke] {group_name}: bound {group_bound}/{len(requirements)}")
        for object_name, expected_class in group_missing:
            print(f"  MISSING {object_name} ({expected_class})")
        for object_name, expected_class, actual_class in group_mismatched:
            print(f"  TYPE {object_name}: expected {expected_class}, found {actual_class}")

    deferred_controls = (
        "btn_start_engine",
        "btn_stop_engine",
        "btn_reset_chat",
        "import_audio_button",
        "transcribe_audio_button",
    )
    present_deferred = [
        name for name in deferred_controls
        if _ui_shell_find_object(window, name) is not None
    ]
    print(f"[UI Shell Smoke] Total checked bindings: {bound_total}")
    print(
        "[UI Shell Smoke] Deferred runtime controls found but intentionally not connected: "
        + (", ".join(present_deferred) if present_deferred else "none")
    )
    print("[UI Shell Smoke] Runtime started: no")
    print("[UI Shell Smoke] Broad addons initialized: no")
    print("[UI Shell Smoke] Engine lifecycle connected: no")
    config_summary = _apply_ui_shell_read_only_config(window)
    print(
        f"[UI Shell Smoke] Read-only session config: "
        f"{'loaded' if config_summary['session_loaded'] else 'not found'} "
        f"({len(config_summary['applied'])} widget(s) populated)"
    )
    addon_report = _ui_shell_addon_mount_report(window)
    _print_ui_shell_addon_mount_report(addon_report)
    live_mount_report = _ui_shell_mount_live_addons(window, addon_report)
    chat_runtime_summary = _bind_ui_shell_chat_runtime(window, live_mount_report.get("chat_providers", []))
    print(
        "[UI Shell Smoke] Chat Runtime binding: "
        + (
            f"{chat_runtime_summary['providers']} provider(s), selected={chat_runtime_summary['selected_provider'] or '<none>'}"
            if chat_runtime_summary.get("bound")
            else "deferred"
        )
    )
    print(
        "[UI Shell Smoke] Live addon mounts: "
        + (", ".join(live_mount_report["mounted"]) if live_mount_report["mounted"] else "none")
    )
    print(
        "[UI Shell Smoke] Live chat providers: "
        + (
            ", ".join(
                str(provider.get("label") or provider.get("id") or "")
                for provider in live_mount_report.get("chat_providers", [])
            )
            if live_mount_report.get("chat_providers")
            else "none"
        )
    )
    if live_mount_report["failures"]:
        print("[UI Shell Smoke] Live addon mount failures:")
        for failure in live_mount_report["failures"]:
            print(f"  - {failure}")
    placeholder_targets = _apply_ui_shell_addon_placeholders(
        window,
        addon_report,
        exclude_addon_ids=set(live_mount_report["mounted_ids"]),
        live_chat_providers=[] if chat_runtime_summary.get("bound") else live_mount_report.get("chat_providers", []),
    )
    print(
        "[UI Shell Smoke] Addon mount placeholders: "
        + (", ".join(placeholder_targets) if placeholder_targets else "none")
    )
    _print_ui_shell_static_addon_comparison(ui_path, addon_report, live_mount_report)

    try:
        _ui_shell_cleanup_live_addons(window)
        window.close()
        if app is not None:
            app.quit()
    except Exception:
        pass

    if missing or mismatched:
        print("[UI Shell Smoke] Result: NOT READY for shell binding.")
        return 1
    print("[UI Shell Smoke] Result: READY for the checked shell binding surface.")
    return 0


def _ui_shell_binding_summary(window):
    checked = 0
    bound = 0
    missing = []
    mismatched = []
    for group_name, requirements in UI_VALIDATION_REQUIRED_GROUPS:
        for object_name, expected_class in requirements:
            checked += 1
            obj = _ui_shell_find_object(window, object_name)
            if obj is None:
                missing.append(f"{group_name}:{object_name}")
                continue
            if not _ui_shell_class_matches(obj, expected_class):
                mismatched.append(f"{group_name}:{object_name}")
                continue
            bound += 1
    return {
        "checked": checked,
        "bound": bound,
        "missing": missing,
        "mismatched": mismatched,
    }


def _apply_ui_shell_preview_status(window):
    summary = _ui_shell_binding_summary(window)
    lines = [
        "Shell Preview",
        "Runtime: not started",
        "Addons: limited shell mounts only",
        "Engine lifecycle: not connected",
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

    for button_name in ("btn_start_engine", "btn_stop_engine", "btn_reset_chat", "import_audio_button", "transcribe_audio_button"):
        button = _ui_shell_find_object(window, button_name)
        if button is not None and hasattr(button, "setToolTip"):
            button.setToolTip("Disabled in shell preview. Runtime wiring is intentionally deferred.")

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

    for button in (quick_save_button, quick_load_button):
        if button is not None:
            button.setEnabled(False)
            button.setToolTip("Disabled in the main.ui shell preview because file/session operations are deferred.")

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
        "deferred": ["chat_quick_save_button", "chat_quick_load_button"],
    }


def _read_ui_shell_session_snapshot():
    session_path = Path(__file__).resolve().parent / "qt_session.json"
    try:
        with session_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _ui_shell_addon_registry_state(session=None):
    payload = dict(session or _read_ui_shell_session_snapshot() or {})
    registry = payload.get("addon_registry_state")
    if isinstance(registry, dict):
        return registry
    registry_path = Path(__file__).resolve().parent / "runtime" / "addons" / "addon_registry.json"
    try:
        with registry_path.open("r", encoding="utf-8") as handle:
            registry = json.load(handle)
            return registry if isinstance(registry, dict) else {}
    except Exception:
        return {}


def _ui_shell_addon_effectively_enabled(manifest, registry_state):
    addon_id = str(manifest.get("id", "") or "").strip()
    category = str(manifest.get("category", "") or "other").strip().lower() or "other"
    manifest_enabled = bool(manifest.get("enabled", True))
    category_overrides = dict((registry_state or {}).get("categories", {}) or {})
    addon_overrides = dict((registry_state or {}).get("addons", {}) or {})
    category_enabled = bool(category_overrides.get(category, True))
    addon_enabled = bool(addon_overrides.get(addon_id, manifest_enabled))
    return bool(category_enabled and addon_enabled)


def _ui_shell_static_tab_areas(addon_dir):
    main_path = Path(addon_dir) / "main.py"
    try:
        text = main_path.read_text(encoding="utf-8")
    except Exception:
        return []
    areas = []
    for match in re.finditer(r"register_tab\s*\((?P<body>.*?)\)", text, re.DOTALL):
        body = match.group("body") or ""
        area_match = re.search(r"area\s*=\s*[\"']([^\"']+)[\"']", body)
        if area_match:
            areas.append(area_match.group(1).strip())
    return sorted(set(item for item in areas if item))


def _ui_shell_static_service_hints(addon_dir, manifest):
    addon_id = str(manifest.get("id", "") or "").strip().lower()
    name = str(manifest.get("name", "") or "").strip().lower()
    hints = []
    if addon_id.startswith("nc.chat_provider_") or "chat provider" in name or addon_id == "nc.claude_provider":
        hints.append("chat_provider_registry")
    main_path = Path(addon_dir) / "main.py"
    try:
        text = main_path.read_text(encoding="utf-8")
    except Exception:
        text = ""
    if "services.register" in text:
        if '"kind": "tts"' in text or "'kind': 'tts'" in text:
            hints.append("tts_backend_service")
        else:
            hints.append("service_registry")
    return sorted(set(hints))


def _ui_shell_discover_addon_manifests():
    addons_dir = Path(__file__).resolve().parent / "addons"
    discovered = []
    if not addons_dir.exists():
        return discovered
    for addon_dir in sorted((path for path in addons_dir.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
        manifest_path = addon_dir / "addon.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            discovered.append({
                "id": addon_dir.name,
                "name": addon_dir.name,
                "category": "other",
                "enabled": False,
                "error": str(exc),
                "areas": [],
                "service_hints": [],
            })
            continue
        if not isinstance(manifest, dict):
            continue
        manifest = dict(manifest)
        manifest["root"] = str(addon_dir)
        manifest["areas"] = _ui_shell_static_tab_areas(addon_dir)
        manifest["service_hints"] = _ui_shell_static_service_hints(addon_dir, manifest)
        discovered.append(manifest)
    return discovered


def _ui_shell_mount_target_for_area(area):
    mapping = {
        "top_level": "left_tabs",
        "host_settings": "host_settings_tabs",
        "musetalk": "musetalk_tabs",
        "tts_runtime": "tts_runtime_addon_tabs",
        "vision_source": "sensory_feedback_tabs",
        "operational_view": "right_tabs",
    }
    return mapping.get(str(area or "").strip(), "")


def _ui_shell_fallback_targets_for_manifest(manifest):
    addon_id = str(manifest.get("id", "") or "").strip().lower()
    category = str(manifest.get("category", "") or "other").strip().lower()
    if addon_id.startswith("nc.chat_provider_") or addon_id == "nc.claude_provider":
        return ["chat_provider_combo"]
    if category == "vision":
        return ["sensory_feedback_tabs"]
    if category == "musetalk":
        return ["musetalk_tabs"]
    if category == "visuals":
        return ["host_settings_tabs"]
    if category == "chat":
        return ["left_tabs"]
    if category == "global":
        return ["left_tabs"]
    return []


def _ui_shell_addon_mount_report(window):
    session = _read_ui_shell_session_snapshot()
    registry_state = _ui_shell_addon_registry_state(session)
    manifests = _ui_shell_discover_addon_manifests()
    mount_points = {
        "left_tabs": _ui_shell_find_object(window, "left_tabs") is not None,
        "host_settings_tabs": _ui_shell_find_object(window, "host_settings_tabs") is not None,
        "right_tabs": _ui_shell_find_object(window, "right_tabs") is not None,
        "tts_runtime_addon_tabs": _ui_shell_find_object(window, "tts_runtime_addon_tabs") is not None,
        "musetalk_tabs": _ui_shell_find_object(window, "musetalk_tabs") is not None,
        "sensory_feedback_tabs": _ui_shell_find_object(window, "sensory_feedback_tabs") is not None,
        "sensory_feedback_sources_widget": _ui_shell_find_object(window, "sensory_feedback_sources_widget") is not None,
        "chat_provider_combo": _ui_shell_find_object(window, "chat_provider_combo") is not None,
        "chat_provider_fields_widget": _ui_shell_find_object(window, "chat_provider_fields_widget") is not None,
        "chat_provider_generation_fields_widget": _ui_shell_find_object(window, "chat_provider_generation_fields_widget") is not None,
        "OperationalViewDock": _ui_shell_find_object(window, "OperationalViewDock") is not None,
    }
    rows = []
    for manifest in manifests:
        areas = list(manifest.get("areas", []) or [])
        service_hints = list(manifest.get("service_hints", []) or [])
        targets = []
        for area in areas:
            target = _ui_shell_mount_target_for_area(area)
            if target:
                targets.append(target)
        if not targets:
            targets = _ui_shell_fallback_targets_for_manifest(manifest)
        rows.append({
            "id": str(manifest.get("id", "") or ""),
            "name": str(manifest.get("name", "") or manifest.get("id", "") or ""),
            "category": str(manifest.get("category", "") or "other"),
            "root": str(manifest.get("root", "") or ""),
            "enabled": _ui_shell_addon_effectively_enabled(manifest, registry_state),
            "areas": areas,
            "service_hints": service_hints,
            "targets": sorted(set(targets)),
            "missing_targets": sorted(set(target for target in targets if not mount_points.get(target, False))),
            "error": str(manifest.get("error", "") or ""),
        })
    enabled_count = sum(1 for row in rows if row["enabled"])
    return {
        "mount_points": mount_points,
        "addons": rows,
        "enabled_count": enabled_count,
        "total_count": len(rows),
    }


def _print_ui_shell_addon_mount_report(report, prefix="[UI Shell Smoke]"):
    print(f"{prefix} Addon manifests discovered: {report['total_count']} ({report['enabled_count']} effectively enabled)")
    print(f"{prefix} Addon mount points:")
    for name, present in sorted((report.get("mount_points") or {}).items()):
        print(f"  - {name}: {'present' if present else 'missing'}")
    print(f"{prefix} Would mount/register:")
    for row in report.get("addons", []):
        status = "enabled" if row.get("enabled") else "disabled"
        areas = ", ".join(row.get("areas") or [])
        hints = ", ".join(row.get("service_hints") or [])
        targets = ", ".join(row.get("targets") or [])
        missing = ", ".join(row.get("missing_targets") or [])
        detail_bits = []
        if areas:
            detail_bits.append(f"areas={areas}")
        if hints:
            detail_bits.append(f"services={hints}")
        if targets:
            detail_bits.append(f"targets={targets}")
        if missing:
            detail_bits.append(f"missing_targets={missing}")
        if row.get("error"):
            detail_bits.append(f"error={row['error']}")
        detail = "; ".join(detail_bits) if detail_bits else "manifest-only"
        print(f"  - {row.get('id') or row.get('name')} [{status}]: {detail}")


def _ui_shell_rows_for_target(report, target, exclude_addon_ids=None):
    target = str(target or "").strip()
    excluded = {str(item or "").strip() for item in (exclude_addon_ids or set()) if str(item or "").strip()}
    rows = []
    for row in report.get("addons", []):
        if str(row.get("id") or "").strip() in excluded:
            continue
        if target in set(row.get("targets") or []):
            rows.append(row)
    return rows


def _ui_shell_addon_rows_text(rows):
    if not rows:
        return "No addon manifests currently target this mount point."
    lines = []
    for row in rows:
        status = "enabled" if row.get("enabled") else "disabled"
        name = str(row.get("name") or row.get("id") or "Unnamed addon").strip()
        addon_id = str(row.get("id") or "").strip()
        areas = ", ".join(row.get("areas") or [])
        services = ", ".join(row.get("service_hints") or [])
        details = [f"{name} [{status}]"]
        if addon_id and addon_id != name:
            details.append(addon_id)
        if areas:
            details.append(f"area: {areas}")
        if services:
            details.append(f"services: {services}")
        lines.append(" - " + " | ".join(details))
    return "\n".join(lines)


def _ui_shell_norm_label(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _ui_shell_target_addon_rows(report, target):
    target = str(target or "").strip()
    return [
        row
        for row in report.get("addons", [])
        if row.get("enabled") and target in set(row.get("targets") or [])
    ]


def _ui_shell_static_addon_comparison(ui_path, report, live_mount_report):
    static_tabs = _collect_ui_shell_static_tabs(ui_path)
    live_tabs = list((live_mount_report or {}).get("live_tabs") or [])
    live_by_target = {}
    for live_tab in live_tabs:
        target = str(live_tab.get("target") or "").strip()
        if not target:
            continue
        live_by_target.setdefault(target, []).append(live_tab)

    rows = []
    for target in UI_SHELL_TAB_MOUNT_WIDGETS:
        static_pages = list(static_tabs.get(target, []) or [])
        addon_rows = _ui_shell_target_addon_rows(report, target)
        live_target_tabs = list(live_by_target.get(target, []) or [])
        static_titles = [str(page.get("title") or "").strip() for page in static_pages if str(page.get("title") or "").strip()]
        static_norms = {_ui_shell_norm_label(title) for title in static_titles}
        live_titles = [str(tab.get("title") or "").strip() for tab in live_target_tabs if str(tab.get("title") or "").strip()]
        live_norms = {_ui_shell_norm_label(title) for title in live_titles}
        replaced_norms = {
            _ui_shell_norm_label(str(tab.get("title") or "").strip())
            for tab in live_target_tabs
            if tab.get("replaced_static_placeholder") and str(tab.get("title") or "").strip()
        }
        manifest_names = [str(row.get("name") or row.get("id") or "").strip() for row in addon_rows]
        manifest_norms = {_ui_shell_norm_label(name) for name in manifest_names}
        duplicate_candidates = [
            title for title in static_titles
            if _ui_shell_norm_label(title) not in replaced_norms
            and (_ui_shell_norm_label(title) in live_norms or _ui_shell_norm_label(title) in manifest_norms)
        ]
        placeholder_only = [
            str(row.get("name") or row.get("id") or "").strip()
            for row in addon_rows
            if str(row.get("id") or "").strip() not in set((live_mount_report or {}).get("mounted_ids") or [])
        ]
        if static_titles or addon_rows or live_target_tabs:
            rows.append({
                "target": target,
                "static_titles": static_titles,
                "live_titles": live_titles,
                "addon_names": manifest_names,
                "duplicate_candidates": duplicate_candidates,
                "placeholder_only": placeholder_only,
            })
    return rows


def _print_ui_shell_static_addon_comparison(ui_path, report, live_mount_report, prefix="[UI Shell Smoke]"):
    rows = _ui_shell_static_addon_comparison(ui_path, report, live_mount_report)
    print(f"{prefix} Static-vs-addon tab comparison:")
    if not rows:
        print("  none")
        return
    for row in rows:
        static_text = ", ".join(row.get("static_titles") or []) or "none"
        live_text = ", ".join(row.get("live_titles") or []) or "none"
        addon_text = ", ".join(row.get("addon_names") or []) or "none"
        duplicate_text = ", ".join(row.get("duplicate_candidates") or []) or "none"
        placeholder_text = ", ".join(row.get("placeholder_only") or []) or "none"
        print(f"  - {row.get('target')}: static=[{static_text}]")
        print(f"    addon targets=[{addon_text}]")
        print(f"    live-mounted=[{live_text}]")
        print(f"    static duplicate candidates=[{duplicate_text}]")
        print(f"    placeholder-only addon targets=[{placeholder_text}]")


class _UiShellChatProviderRegistry:
    """Shell-only provider registry: accept addon metadata without invoking handlers."""

    def __init__(self):
        self._providers = OrderedDict()
        self._registrations = {}

    def register_provider(
        self,
        *,
        provider_id,
        label,
        description="",
        order=1000,
        client_factory=None,
        model_list_handler=None,
        completion_handler=None,
        stream_handler=None,
        connection_check_handler=None,
        api_key_getter=None,
        base_url_getter=None,
        metadata=None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Chat provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_model_list_handler": callable(model_list_handler),
            "has_completion_handler": callable(completion_handler),
            "has_stream_handler": callable(stream_handler),
            "has_connection_check_handler": callable(connection_check_handler),
            "has_api_key_getter": callable(api_key_getter),
            "has_base_url_getter": callable(base_url_getter),
        }
        self._providers[provider_id] = summary
        self._registrations[provider_id] = {
            "client_factory": client_factory,
            "model_list_handler": model_list_handler,
            "completion_handler": completion_handler,
            "stream_handler": stream_handler,
            "connection_check_handler": connection_check_handler,
            "api_key_getter": api_key_getter,
            "base_url_getter": base_url_getter,
        }
        return dict(summary)

    def unregister_provider(self, provider_id):
        provider_id = str(provider_id or "").strip()
        existed = provider_id in self._providers
        self._providers.pop(provider_id, None)
        self._registrations.pop(provider_id, None)
        return existed

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(
                self._providers.values(),
                key=lambda provider: (int(provider.get("order", 1000)), str(provider.get("label", ""))),
            )
        ]

    def provider_ids(self):
        return set(self._providers.keys())

    def get_provider_settings(self, provider_id=None):
        if provider_id:
            return {}
        return {provider_id: {} for provider_id in self._providers}

    def get_provider_setting(self, provider_id, field_id):
        return ""


class _UiShellHotkeyService:
    """Read-only shell hotkey service: expose bindings without mutating runtime state."""

    def list_bindings(self):
        try:
            import engine as _engine

            entries = [
                {
                    "action": "push_to_talk",
                    "label": str(_engine.HOTKEY_ACTION_LABELS.get("push_to_talk", "Push-to-Talk")),
                    "binding": str(_engine.get_push_to_talk_hotkey() or ""),
                    "default_binding": str(_engine.DEFAULT_PUSH_TO_TALK_HOTKEY),
                    "category": "input",
                    "scope": "global",
                    "description": "Read-only shell preview of the Push-to-Talk binding.",
                }
            ]
            manual_bindings = _engine.get_manual_action_hotkeys()
            for action, default_binding in _engine.DEFAULT_MANUAL_ACTION_HOTKEYS.items():
                entries.append(
                    {
                        "action": action,
                        "label": str(_engine.HOTKEY_ACTION_LABELS.get(action, action)),
                        "binding": str(manual_bindings.get(action, "") or ""),
                        "default_binding": str(default_binding or ""),
                        "category": "manual_controls",
                        "scope": "global_and_window",
                        "description": "Read-only shell preview of a manual control binding.",
                    }
                )
            ui_bindings = _engine.get_ui_action_hotkeys()
            for action, default_binding in _engine.DEFAULT_UI_ACTION_HOTKEYS.items():
                entries.append(
                    {
                        "action": action,
                        "label": str(_engine.HOTKEY_ACTION_LABELS.get(action, action)),
                        "binding": str(ui_bindings.get(action, "") or ""),
                        "default_binding": str(default_binding or ""),
                        "category": "ui_actions",
                        "scope": "window",
                        "description": "Read-only shell preview of a focused-window shortcut.",
                    }
                )
            return entries
        except Exception:
            return []

    def set_binding(self, action, binding):
        action_key = str(action or "").strip()
        for entry in self.list_bindings():
            if str(entry.get("action", "") or "") == action_key:
                return str(entry.get("binding", "") or "")
        return ""

    def reset_defaults(self):
        return self.list_bindings()


class _UiShellShellService:
    """Shell-preview service: allow addon UI refresh notifications without saving state."""

    def open_local_path(self, path):
        return False

    def notify_settings_changed(self):
        return None


class _UiShellVisualReplyService:
    """Shell-only visual reply service: render settings UI without image/runtime side effects."""

    _THEME_PRESETS = (
        {"id": "realistic", "label": "Realistic", "prompt": "realistic cinematic lighting, natural textures, grounded detail"},
        {"id": "cartoon", "label": "Cartoon", "prompt": "cartoon illustration, bold shapes, clean outlines"},
        {"id": "retro", "label": "Retro", "prompt": "retro halftone print texture, vintage color palette"},
        {"id": "cyberpunk", "label": "Cyberpunk", "prompt": "neon atmosphere, vivid contrast, futuristic detail"},
        {"id": "anime", "label": "Anime", "prompt": "anime key art, expressive characters, dynamic framing"},
        {"id": "storybook", "label": "Storybook", "prompt": "illustrated fantasy look, painterly storybook texture"},
    )

    def __init__(self, window):
        self._window = window
        self._state = self._initial_state()
        self._hint_label = None
        self._settings_widgets = {}
        self._panel = None

    def _initial_state(self):
        session = _read_ui_shell_session_snapshot()
        state = {
            "visual_reply_mode": str(session.get("visual_reply_mode", "auto") or "auto"),
            "visual_reply_provider": str(session.get("visual_reply_provider", "openai") or "openai"),
            "visual_reply_size": str(session.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "visual_reply_model": str(session.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "visual_reply_auto_show_dock": bool(session.get("visual_reply_auto_show_dock", True)),
            "visual_reply_story_mode": bool(session.get("visual_reply_story_mode", False)),
            "visual_reply_story_max_images": session.get("visual_reply_story_max_images", 3),
            "visual_reply_story_continuity_strength": session.get("visual_reply_story_continuity_strength", 0.8),
            "visual_reply_story_theme_prompts": dict(session.get("visual_reply_story_theme_prompts") or {}),
            "visual_reply_story_theme_enabled": list(session.get("visual_reply_story_theme_enabled") or []),
            "visual_reply_master_style_prompt": str(session.get("visual_reply_master_style_prompt", "") or ""),
            "visual_reply_master_prompt_safe": bool(session.get("visual_reply_master_prompt_safe", False)),
            "visual_reply_master_prompt_no_speech_bubbles": bool(session.get("visual_reply_master_prompt_no_speech_bubbles", False)),
        }
        if str(state["visual_reply_provider"]).strip().lower() not in {"openai", "xai"}:
            state["visual_reply_provider"] = "openai"
        return state

    def _theme_prompts(self):
        raw = dict(self._state.get("visual_reply_story_theme_prompts") or {})
        prompts = {}
        for theme in self._THEME_PRESETS:
            theme_id = str(theme.get("id") or "").strip().lower()
            if theme_id:
                prompts[theme_id] = str(raw.get(theme_id, theme.get("prompt", "")) or theme.get("prompt", "")).strip()
        return prompts

    def _theme_enabled(self):
        raw = self._state.get("visual_reply_story_theme_enabled", [])
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            raw = []
        valid = {str(theme.get("id") or "").strip().lower() for theme in self._THEME_PRESETS}
        enabled = []
        seen = set()
        for item in raw:
            theme_id = str(item or "").strip().lower()
            if theme_id in valid and theme_id not in seen:
                enabled.append(theme_id)
                seen.add(theme_id)
        return enabled

    def _story_continuity_strength(self):
        try:
            value = float(self._state.get("visual_reply_story_continuity_strength", 0.8) or 0.8)
        except Exception:
            value = 0.8
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def _story_max_images(self):
        try:
            return max(1, int(self._state.get("visual_reply_story_max_images", 3) or 3))
        except Exception:
            return 3

    def settings_snapshot(self):
        prompts = self._theme_prompts()
        enabled = set(self._theme_enabled())
        return {
            "mode_value": str(self._state.get("visual_reply_mode", "auto") or "auto"),
            "provider_value": str(self._state.get("visual_reply_provider", "openai") or "openai"),
            "size_value": str(self._state.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "model_name": str(self._state.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "auto_show": bool(self._state.get("visual_reply_auto_show_dock", True)),
            "master_prompt_safe": bool(self._state.get("visual_reply_master_prompt_safe", False)),
            "master_prompt_no_speech_bubbles": bool(self._state.get("visual_reply_master_prompt_no_speech_bubbles", False)),
            "story_mode": bool(self._state.get("visual_reply_story_mode", False)),
            "story_max_images": self._story_max_images(),
            "story_continuity_strength": self._story_continuity_strength(),
            "story_themes": [
                {
                    "id": str(theme.get("id") or "").strip().lower(),
                    "label": str(theme.get("label") or theme.get("id") or "").strip(),
                    "prompt": prompts.get(str(theme.get("id") or "").strip().lower(), ""),
                    "enabled": str(theme.get("id") or "").strip().lower() in enabled,
                }
                for theme in self._THEME_PRESETS
            ],
        }

    def mode_labels(self):
        return ["Off", "Auto"]

    def provider_labels(self):
        return ["OpenAI", "xAI / Grok"]

    def size_labels(self):
        return ["Auto", "1024x1024", "1024x1536", "1536x1024"]

    def mode_label_from_value(self, value):
        return "Off" if str(value or "").strip().lower() == "off" else "Auto"

    def provider_label_from_value(self, value):
        provider = str(value or "").strip().lower()
        return "xAI / Grok" if provider == "xai" else "OpenAI"

    def size_label_from_value(self, value):
        size = self.normalize_size(value)
        return "Auto" if size == "auto" else size

    def normalize_size(self, value):
        size = str(value or "1024x1024").strip().lower().replace(" ", "")
        if size in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
            return size
        if size in {"1024 1024", "1024*1024"}:
            return "1024x1024"
        return "1024x1024"

    def attach_settings_widgets(self, **widgets):
        self._settings_widgets = dict(widgets or {})
        self._hint_label = widgets.get("hint_label")
        for widget in widgets.values():
            if widget is not None and hasattr(widget, "setToolTip"):
                widget.setToolTip("Shell-local Visual Reply preview. Changes are not saved and no image generation is started.")

    def _set_state(self, key, value):
        self._state[str(key)] = value
        self.refresh_hint()

    def apply_mode(self, choice):
        self._set_state("visual_reply_mode", "off" if str(choice or "").strip().lower() == "off" else "auto")

    def apply_provider(self, choice):
        label = str(choice or "").strip().lower()
        self._set_state("visual_reply_provider", "xai" if "grok" in label or "xai" in label else "openai")

    def apply_size(self, choice):
        self._set_state("visual_reply_size", self.normalize_size(choice))

    def apply_model(self):
        edit = self._settings_widgets.get("model_edit")
        text = str(edit.text() if edit is not None and hasattr(edit, "text") else "").strip()
        self._set_state("visual_reply_model", text or "gpt-image-1")

    def apply_auto_show(self, checked):
        self._set_state("visual_reply_auto_show_dock", bool(checked))

    def apply_story_mode(self, checked):
        self._set_state("visual_reply_story_mode", bool(checked))

    def apply_story_max_images(self, value):
        try:
            self._set_state("visual_reply_story_max_images", max(1, int(value or 1)))
        except Exception:
            self._set_state("visual_reply_story_max_images", 3)

    def apply_story_continuity_strength(self, value):
        try:
            strength = max(0.0, min(1.0, float(value or 0) / 100.0))
        except Exception:
            strength = 0.8
        self._set_state("visual_reply_story_continuity_strength", strength)

    def apply_story_theme_toggle(self, theme_id, checked):
        enabled = set(self._theme_enabled())
        theme_id = str(theme_id or "").strip().lower()
        if checked:
            enabled.add(theme_id)
        else:
            enabled.discard(theme_id)
        self._set_state("visual_reply_story_theme_enabled", sorted(enabled))

    def apply_story_theme_text(self, theme_id, text):
        prompts = self._theme_prompts()
        theme_id = str(theme_id or "").strip().lower()
        if theme_id:
            prompts[theme_id] = str(text or "").strip()
        self._set_state("visual_reply_story_theme_prompts", prompts)

    def refresh_hint(self):
        label = self._hint_label
        if label is None or not hasattr(label, "setText"):
            return
        snapshot = self.settings_snapshot()
        mode = str(snapshot.get("mode_value") or "auto")
        provider = self.provider_label_from_value(snapshot.get("provider_value"))
        model = str(snapshot.get("model_name") or "gpt-image-1")
        label.setText(
            "Shell-local Visual Reply settings preview. "
            f"Mode: {mode}; Provider: {provider}; Model: {model}. "
            "No image generation, dock replacement, or session save is connected."
        )

    def replace_panel(self, panel):
        self._panel = panel
        try:
            timer = getattr(panel, "poll_timer", None)
            if timer is not None and hasattr(timer, "stop"):
                timer.stop()
        except Exception:
            pass
        try:
            panel.setParent(self._window)
            panel.hide()
        except Exception:
            pass
        for name in (
            "prev_button",
            "load_button",
            "next_button",
            "load_story_button",
            "use_style_button",
            "caption_button",
            "delete_button",
            "clear_button",
            "delete_all_button",
        ):
            try:
                button = getattr(panel, name, None)
                if button is not None:
                    button.setEnabled(False)
                    button.setToolTip("Disabled in the main.ui shell preview; Visual Reply dock/image history remains Designer-owned.")
            except Exception:
                pass
        return False

    def show(self):
        return None

    def hide(self):
        return None

    def clear(self, *args, **kwargs):
        return False

    def set_loading(self, *args, **kwargs):
        return False

    def show_image(self, *args, **kwargs):
        return False


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


def _bind_ui_shell_chat_runtime(window, providers):
    from PySide6 import QtWidgets as _QtWidgets

    providers = list(providers or [])
    provider_by_id = _ui_shell_chat_provider_map(providers)
    if not provider_by_id:
        return {"bound": False, "providers": 0, "selected_provider": ""}

    session = _read_ui_shell_session_snapshot()
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
        saved_model = str(session.get("model_name", "") or "").strip()
        model_combo.blockSignals(True)
        try:
            model_combo.clear()
            if saved_model:
                model_combo.addItem(saved_model)
            model_combo.addItem("Model refresh deferred in shell preview")
            model_combo.setCurrentIndex(0)
        finally:
            model_combo.blockSignals(False)
        _ui_shell_set_read_only_tooltip(model_combo, "Live model refresh remains deferred for this binding slice.")

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

    render_provider(selected_provider_id)
    setattr(window, "_nc_ui_shell_chat_runtime_state", local_state)
    return {
        "bound": True,
        "providers": len(providers),
        "selected_provider": selected_provider_id,
    }


def _ui_shell_tab_title_exists(tab_widget, title):
    if tab_widget is None or not hasattr(tab_widget, "count"):
        return False
    expected = str(title or "")
    for index in range(tab_widget.count()):
        try:
            if str(tab_widget.tabText(index) or "") == expected:
                return True
        except Exception:
            continue
    return False


def _ui_shell_add_placeholder_tab(tab_widget, title, body_text):
    from PySide6 import QtWidgets as _QtWidgets

    if tab_widget is None or not hasattr(tab_widget, "addTab"):
        return False
    if _ui_shell_tab_title_exists(tab_widget, title):
        return False
    panel = _QtWidgets.QWidget()
    layout = _QtWidgets.QVBoxLayout(panel)
    layout.setContentsMargins(12, 12, 12, 12)
    heading = _QtWidgets.QLabel("Read-only addon mount preview")
    heading.setStyleSheet("font-weight: 700; color: #cbd5e1;")
    layout.addWidget(heading)
    text = _QtWidgets.QPlainTextEdit()
    text.setReadOnly(True)
    text.setPlainText(str(body_text or ""))
    text.setToolTip("Shell-only preview. Addon modules are not imported and no runtime systems are started.")
    layout.addWidget(text, 1)
    tab_widget.addTab(panel, title)
    if hasattr(tab_widget, "setVisible"):
        tab_widget.setVisible(True)
    return True


def _ui_shell_static_addon_placeholder_name(addon_id):
    addon_id = str(addon_id or "").strip().lower()
    if addon_id == "nc.chat_session_player":
        return "chat_player_tab"
    if addon_id == "nc.hotkeys":
        return "hotkeys_tab"
    if addon_id == "nc.visual_reply":
        return "host_settings_visuals_tab"
    if addon_id == "nc.audio_story_mode":
        return "audio_story_mode_tab"
    if addon_id == "nc.chatterbox_tts":
        return "tts_chatterbox_tab"
    if addon_id == "nc.pockettts":
        return "tts_pockettts_tab"
    return ""


def _ui_shell_replace_static_addon_placeholder(tab_widget, placeholder_name, widget, title, tooltip=""):
    if tab_widget is None or widget is None or not placeholder_name:
        return -1
    from PySide6 import QtWidgets as _QtWidgets

    placeholder = tab_widget.findChild(_QtWidgets.QWidget, str(placeholder_name))
    if placeholder is None:
        return -1
    index = tab_widget.indexOf(placeholder)
    if index < 0:
        return -1
    tab_icon = tab_widget.tabIcon(index)
    tab_text = str(tab_widget.tabText(index) or "").strip() or str(title or "").strip()
    tab_tooltip = str(tab_widget.tabToolTip(index) or "").strip() or str(tooltip or "").strip()
    tab_widget.removeTab(index)
    placeholder.setParent(None)
    placeholder.deleteLater()
    new_index = tab_widget.insertTab(index, widget, tab_text)
    if not tab_icon.isNull():
        tab_widget.setTabIcon(new_index, tab_icon)
    if tab_tooltip:
        tab_widget.setTabToolTip(new_index, tab_tooltip)
    return new_index


def _ui_shell_prepare_live_addon_widget(addon_id, widget):
    if str(addon_id or "").strip().lower() != "nc.hotkeys" or widget is None:
        return
    from PySide6 import QtWidgets as _QtWidgets

    disabled_actions = {
        "Record Binding",
        "Apply Binding",
        "Clear",
        "Reset To Default",
        "Reset All Defaults",
    }
    for button in widget.findChildren(_QtWidgets.QPushButton):
        if str(button.text() or "").strip() in disabled_actions:
            button.setEnabled(False)
            button.setToolTip("Disabled in the main.ui shell preview; the real Python-built UI owns hotkey mutation and capture.")
    for edit in widget.findChildren(_QtWidgets.QLineEdit):
        edit.setReadOnly(True)
        edit.setToolTip("Read-only in the main.ui shell preview.")


def _ui_shell_contribution_title(contribution, manifest):
    title = str(getattr(contribution, "title", "") or getattr(contribution, "id", "") or getattr(manifest, "name", "") or "Addon").strip()
    parent = str(getattr(contribution, "parent_tab_id", "") or "").strip().lower()
    parent_labels = {
        "screen": "Screen",
        "webcam": "Webcam",
        "clipboard": "Clipboard",
        "heart_rate": "Heart Rate",
    }
    if parent in parent_labels:
        return f"{parent_labels[parent]} / {title}"
    return title


def _apply_ui_shell_addon_placeholders(window, report, exclude_addon_ids=None, live_chat_providers=None):
    placeholders = {
        "left_tabs": "Addon Mounts",
        "host_settings_tabs": "Addon Preview",
        "right_tabs": "Addon Preview",
        "musetalk_tabs": "Addon Preview",
        "tts_runtime_addon_tabs": "Addon Preview",
        "sensory_feedback_tabs": "Addon Preview",
    }
    added = []
    for target, title in placeholders.items():
        rows = _ui_shell_rows_for_target(report, target, exclude_addon_ids=exclude_addon_ids)
        if not rows:
            continue
        tab_widget = _ui_shell_find_object(window, target)
        if _ui_shell_add_placeholder_tab(tab_widget, title, _ui_shell_addon_rows_text(rows)):
            added.append(target)

    live_provider_text = _ui_shell_chat_provider_rows_text(live_chat_providers)
    chat_provider_rows = _ui_shell_rows_for_target(report, "chat_provider_combo", exclude_addon_ids=exclude_addon_ids)
    if live_provider_text or chat_provider_rows:
        parts = []
        if live_provider_text:
            parts.append(live_provider_text)
        if chat_provider_rows:
            parts.append(
                "Read-only shell preview. Placeholder-only chat provider addons discovered:\n"
                + _ui_shell_addon_rows_text(chat_provider_rows)
            )
        text = "\n\n".join(parts)
        for object_name in ("chat_provider_fields_placeholder", "chat_provider_generation_fields_placeholder"):
            placeholder = _ui_shell_find_object(window, object_name)
            if placeholder is not None and hasattr(placeholder, "setText"):
                placeholder.setText(text)
                if hasattr(placeholder, "setToolTip"):
                    placeholder.setToolTip("Shell-only provider addon preview. Registered provider handlers are not invoked.")
                added.append(object_name)
    return sorted(set(added))


def _ui_shell_load_addon_module(manifest):
    root = Path(str(manifest.get("root") or "")).resolve()
    entry_point = str(manifest.get("entry_point") or "main.py").strip() or "main.py"
    entry_path = root / entry_point
    module_name = "nc_ui_shell_addon_" + re.sub(r"[^a-zA-Z0-9_]", "_", str(manifest.get("id") or root.name))
    spec = importlib.util.spec_from_file_location(module_name, entry_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load addon entry point: {entry_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ui_shell_mount_live_addons(window, report):
    from PySide6 import QtWidgets as _QtWidgets
    from core.addons.context import AddonContext, AddonEventBus, AddonServiceRegistry
    from core.addons.manifest import AddonManifest

    _ui_shell_enable_stdio_unicode_fallback()

    mounted = []
    mounted_ids = []
    failures = []
    live_refs = []
    live_tabs = []
    app_root = Path(__file__).resolve().parent
    storage_root = app_root / "runtime" / "addons" / "ui_shell"
    event_bus = AddonEventBus()
    service_registry = AddonServiceRegistry()
    chat_provider_registry = _UiShellChatProviderRegistry()
    host_services = {
        "qt.chat_providers": chat_provider_registry,
        "qt.hotkeys": _UiShellHotkeyService(),
        "qt.shell": _UiShellShellService(),
        "qt.visual_reply": _UiShellVisualReplyService(window),
        "qt.audio_story_mode_shell_preview": True,
        "qt.chatterbox_tts_shell_preview": True,
        "qt.pockettts_shell_preview": True,
        "qt.clipboard_source_shell_preview": True,
        "qt.gemini_tts_preview_shell_preview": True,
        "qt.loop_authoring_shell_preview": True,
        "qt.musetalk_preprocess_shell_preview": True,
        "qt.shell_session_snapshot": _read_ui_shell_session_snapshot,
    }

    rows_by_id = {
        str(row.get("id") or "").strip(): row
        for row in report.get("addons", [])
    }
    for addon_id in sorted(UI_SHELL_LIVE_ADDON_IDS):
        row = rows_by_id.get(addon_id)
        if not row or not row.get("enabled"):
            continue
        try:
            manifest_path = Path(str(row.get("root") or "")) / "addon.json"
            manifest = AddonManifest.from_file(manifest_path)
            context = AddonContext(
                manifest=manifest,
                app_root=app_root,
                event_bus=event_bus,
                service_registry=service_registry,
                storage_root=storage_root,
                llm_snapshot_getter=lambda: {},
                tts_snapshot_getter=lambda: {},
                avatar_snapshot_getter=lambda: {},
                host_services=host_services,
            )
            provider_ids_before = chat_provider_registry.provider_ids()
            module = _ui_shell_load_addon_module(row)
            addon_cls = getattr(module, "Addon", None)
            if addon_cls is None:
                raise RuntimeError("Addon class is missing.")
            addon = addon_cls()
            addon.initialize(context)
            provider_ids_after = chat_provider_registry.provider_ids()
            added_provider_ids = sorted(provider_ids_after - provider_ids_before)
            contributions = sorted(context.ui.get_tab_contributions(), key=lambda item: (int(item.order), str(item.title or item.id)))
            added_tabs = []
            for contribution in contributions:
                target = _ui_shell_mount_target_for_area(str(contribution.area or "top_level"))
                if not target:
                    continue
                tab_widget = _ui_shell_find_object(window, target)
                if tab_widget is None or not hasattr(tab_widget, "addTab"):
                    failures.append(f"{addon_id}: mount point unavailable for area {contribution.area!r}")
                    continue
                widget = contribution.factory(context)
                if not isinstance(widget, _QtWidgets.QWidget):
                    raise RuntimeError(f"Tab factory for {contribution.id} did not return a QWidget.")
                _ui_shell_prepare_live_addon_widget(addon_id, widget)
                title = _ui_shell_contribution_title(contribution, manifest)
                placeholder_name = _ui_shell_static_addon_placeholder_name(addon_id)
                tab_index = _ui_shell_replace_static_addon_placeholder(
                    tab_widget,
                    placeholder_name,
                    widget,
                    title,
                    str(contribution.tooltip or ""),
                )
                replaced_static_placeholder = tab_index >= 0
                if tab_index < 0:
                    tab_widget.addTab(widget, title)
                    tab_index = tab_widget.indexOf(widget)
                if tab_index >= 0 and contribution.tooltip:
                    tab_widget.setTabToolTip(tab_index, str(contribution.tooltip or ""))
                if hasattr(tab_widget, "setVisible"):
                    tab_widget.setVisible(True)
                added_tabs.append(f"{target}/{title}")
                live_tabs.append({
                    "addon_id": addon_id,
                    "target": target,
                    "title": title,
                    "replaced_static_placeholder": replaced_static_placeholder,
                    "placeholder_name": placeholder_name,
                })
            added_provider_summaries = [
                provider
                for provider in chat_provider_registry.list_providers()
                if str(provider.get("id") or "").strip() in set(added_provider_ids)
            ]
            if added_tabs or added_provider_summaries:
                details = []
                if added_tabs:
                    details.append(", ".join(added_tabs))
                if added_provider_summaries:
                    labels = ", ".join(
                        f"chat_provider/{provider.get('label') or provider.get('id')}"
                        for provider in added_provider_summaries
                    )
                    details.append(labels)
                mounted.append(f"{addon_id}: {'; '.join(details)}")
                mounted_ids.append(addon_id)
                live_refs.append({"addon": addon, "context": context, "tabs": added_tabs, "providers": added_provider_ids})
            else:
                context.close()
                failures.append(f"{addon_id}: no supported top-level tabs registered")
        except Exception as exc:
            failures.append(f"{addon_id}: {exc}")
    setattr(window, "_nc_ui_shell_live_addons", live_refs)
    setattr(window, "_nc_ui_shell_live_services", {"chat_provider_registry": chat_provider_registry})
    return {
        "mounted": mounted,
        "failures": failures,
        "mounted_ids": sorted(set(mounted_ids)),
        "chat_providers": chat_provider_registry.list_providers(),
        "live_tabs": live_tabs,
    }


def _ui_shell_cleanup_live_addons(window):
    refs = list(getattr(window, "_nc_ui_shell_live_addons", []) or [])
    setattr(window, "_nc_ui_shell_live_addons", [])
    setattr(window, "_nc_ui_shell_live_services", {})
    for ref in refs:
        addon = ref.get("addon")
        context = ref.get("context")
        try:
            if addon is not None and hasattr(addon, "shutdown"):
                addon.shutdown()
        except Exception:
            pass
        try:
            if context is not None and hasattr(context, "close"):
                context.close()
        except Exception:
            pass


def _ui_shell_preset_names():
    presets_dir = Path(__file__).resolve().parent / "presets"
    names = []
    try:
        for item in sorted(presets_dir.glob("*.json"), key=lambda path: path.stem.lower()):
            names.append(item.stem)
    except Exception:
        pass
    return names


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


def _apply_ui_shell_read_only_config(window):
    session = _read_ui_shell_session_snapshot()
    provider_labels = {
        "lmstudio": "LM Studio",
        "openai": "OpenAI",
        "xai": "xAI / Grok",
        "claude": "Claude",
    }
    visual_mode_labels = {
        "off": "Off",
        "manual": "Manual",
        "auto": "Auto",
    }
    tts_labels = {
        "chatterbox": "Chatterbox",
        "pockettts": "PocketTTS",
        "gemini_tts_preview": "Gemini TTS Preview",
    }
    avatar_labels = {
        "vseeface": "VSeeFace",
        "musetalk": "MuseTalk",
        "vam": "VaM",
        "none": "None",
    }
    applied = []

    combo_specs = (
        ("engine_combo", list(avatar_labels.values()), avatar_labels.get(str(session.get("avatar_mode", "")).strip().lower(), session.get("avatar_mode", ""))),
        ("input_mode_combo", ["Voice Activation", "Push-to-Talk"], session.get("input_mode", "")),
        ("input_role_combo", ["User Message", "System Message", "Assistant Message"], session.get("input_message_role", "")),
        ("stream_mode_combo", ["Off", "On"], session.get("stream_mode", "")),
        ("tts_backend_combo", list(tts_labels.values()), tts_labels.get(str(session.get("tts_backend", "")).strip().lower(), session.get("tts_backend", ""))),
        ("chat_provider_combo", list(provider_labels.values()), provider_labels.get(str(session.get("chat_provider", "")).strip().lower(), session.get("chat_provider", ""))),
        ("musetalk_vram_combo", ["Quality", "Balanced", "Low VRAM", "Very Low VRAM"], str(session.get("musetalk_vram_mode", "") or "").replace("_", " ").title().replace("Vram", "VRAM")),
        ("musetalk_avatar_pack_combo", [str(session.get("musetalk_avatar_pack_id", "") or "No avatar pack saved")], session.get("musetalk_avatar_pack_id", "")),
        ("visual_reply_mode_combo", ["Off", "Manual", "Auto"], visual_mode_labels.get(str(session.get("visual_reply_mode", "")).strip().lower(), session.get("visual_reply_mode", ""))),
        ("visual_reply_provider_combo", ["OpenAI", "xAI / Grok"], provider_labels.get(str(session.get("visual_reply_provider", "")).strip().lower(), session.get("visual_reply_provider", ""))),
        ("visual_reply_size_combo", ["1024x1024", "1024x1792", "1792x1024"], session.get("visual_reply_size", "")),
    )
    for object_name, labels, selected in combo_specs:
        combo = _ui_shell_find_object(window, object_name)
        _ui_shell_combo_set_items(combo, labels)
        if _ui_shell_combo_select_label(combo, selected):
            applied.append(object_name)
        _ui_shell_set_read_only_tooltip(combo)

    preset_combo = _ui_shell_find_object(window, "preset_combo")
    preset_names = _ui_shell_preset_names()
    _ui_shell_combo_set_items(preset_combo, preset_names or ["No presets found"])
    if _ui_shell_combo_select_label(preset_combo, session.get("last_preset", "")):
        applied.append("preset_combo")
    _ui_shell_set_read_only_tooltip(preset_combo)

    model_combo = _ui_shell_find_object(window, "model_combo")
    model_name = str(session.get("model_name", "") or "").strip()
    _ui_shell_combo_set_items(model_combo, [model_name] if model_name else ["No model saved"])
    if model_name and _ui_shell_combo_select_label(model_combo, model_name):
        applied.append("model_combo")
    _ui_shell_set_read_only_tooltip(model_combo, "Model refresh is not connected.")

    visual_model = _ui_shell_find_object(window, "visual_reply_model_edit")
    if visual_model is not None and hasattr(visual_model, "setText"):
        visual_model.setText(str(session.get("visual_reply_model", "") or ""))
        _ui_shell_set_read_only_tooltip(visual_model)
        applied.append("visual_reply_model_edit")

    numeric_specs = (
        ("musetalk_loop_fade_spin", session.get("musetalk_loop_fade_ms")),
        ("tts_seed_spin", session.get("tts_seed")),
    )
    for object_name, value in numeric_specs:
        if value is None:
            continue
        widget = _ui_shell_find_object(window, object_name)
        if _ui_shell_set_spin_value(widget, value):
            _ui_shell_set_read_only_tooltip(widget)
            applied.append(object_name)

    double_specs = (
        ("tts_temperature_spin", session.get("tts_temperature")),
        ("tts_top_p_spin", session.get("tts_top_p")),
        ("tts_repeat_penalty_spin", session.get("tts_repeat_penalty")),
        ("tts_min_p_spin", session.get("tts_min_p")),
    )
    for object_name, value in double_specs:
        if value is None:
            continue
        widget = _ui_shell_find_object(window, object_name)
        if _ui_shell_set_double_value(widget, value):
            _ui_shell_set_read_only_tooltip(widget)
            applied.append(object_name)

    top_k_spin = _ui_shell_find_object(window, "tts_top_k_spin")
    if _ui_shell_set_spin_value(top_k_spin, session.get("tts_top_k", 0)):
        _ui_shell_set_read_only_tooltip(top_k_spin)
        applied.append("tts_top_k_spin")

    normalize_checkbox = _ui_shell_find_object(window, "tts_normalize_loudness_checkbox")
    if _ui_shell_set_checked(normalize_checkbox, session.get("tts_normalize_loudness", False)):
        _ui_shell_set_read_only_tooltip(normalize_checkbox)
        applied.append("tts_normalize_loudness_checkbox")

    provider_placeholder = _ui_shell_find_object(window, "chat_provider_fields_placeholder")
    if provider_placeholder is not None and hasattr(provider_placeholder, "setText"):
        provider_placeholder.setText("Read-only shell preview. Provider-specific fields mount here in the live app.")
    generation_placeholder = _ui_shell_find_object(window, "chat_provider_generation_fields_placeholder")
    if generation_placeholder is not None and hasattr(generation_placeholder, "setText"):
        generation_placeholder.setText("Read-only shell preview. Generation controls mount here in the live app.")

    return {
        "session_loaded": bool(session),
        "applied": sorted(set(applied)),
        "session_path": str(Path(__file__).resolve().parent / "qt_session.json"),
    }


def run_ui_shell_preview(raw_path):
    from PySide6 import QtCore as _QtCore
    from PySide6 import QtWidgets as _QtWidgets

    ui_path = _resolve_ui_path(raw_path)
    print(f"[UI Shell] Loading visual-only Designer shell: {ui_path}")
    if not ui_path.exists():
        raise FileNotFoundError(f"UI file not found: {ui_path}")
    app, window = _load_ui_shell_for_smoke(ui_path)
    current_title = str(window.windowTitle() or "").strip()
    window.setWindowTitle(f"{current_title} [UI Shell Preview]" if current_title else "UI Shell Preview")
    if isinstance(window, _QtWidgets.QMainWindow):
        window.setTabPosition(_QtCore.Qt.AllDockWidgetAreas, _QtWidgets.QTabWidget.North)
    summary = _apply_ui_shell_preview_status(window)
    config_summary = _apply_ui_shell_read_only_config(window)
    console_chat_summary = _bind_ui_shell_console_chat_local_controls(window)
    addon_report = _ui_shell_addon_mount_report(window)
    live_mount_report = _ui_shell_mount_live_addons(window, addon_report)
    chat_runtime_summary = _bind_ui_shell_chat_runtime(window, live_mount_report.get("chat_providers", []))
    placeholder_targets = _apply_ui_shell_addon_placeholders(
        window,
        addon_report,
        exclude_addon_ids=set(live_mount_report["mounted_ids"]),
        live_chat_providers=[] if chat_runtime_summary.get("bound") else live_mount_report.get("chat_providers", []),
    )
    try:
        app.aboutToQuit.connect(lambda: _ui_shell_cleanup_live_addons(window))
    except Exception:
        pass
    print("[UI Shell] Runtime started: no")
    print("[UI Shell] Broad addons initialized: no")
    print("[UI Shell] Engine lifecycle connected: no")
    print(f"[UI Shell] Bindings checked: {summary['bound']}/{summary['checked']}")
    print(
        f"[UI Shell] Read-only session config: "
        f"{'loaded' if config_summary['session_loaded'] else 'not found'} "
        f"({len(config_summary['applied'])} widget(s) populated)"
    )
    print(
        "[UI Shell] Console/chat shell-local controls: "
        + ", ".join(console_chat_summary.get("bound") or ["none"])
    )
    print(
        "[UI Shell] Console/chat deferred controls: "
        + ", ".join(console_chat_summary.get("deferred") or ["none"])
    )
    print(
        "[UI Shell] Chat Runtime binding: "
        + (
            f"{chat_runtime_summary['providers']} provider(s), selected={chat_runtime_summary['selected_provider'] or '<none>'}"
            if chat_runtime_summary.get("bound")
            else "deferred"
        )
    )
    print(
        f"[UI Shell] Addon manifests discovered: "
        f"{addon_report['total_count']} ({addon_report['enabled_count']} effectively enabled)"
    )
    print(
        "[UI Shell] Live addon mounts: "
        + (", ".join(live_mount_report["mounted"]) if live_mount_report["mounted"] else "none")
    )
    print(
        "[UI Shell] Live chat providers: "
        + (
            ", ".join(
                str(provider.get("label") or provider.get("id") or "")
                for provider in live_mount_report.get("chat_providers", [])
            )
            if live_mount_report.get("chat_providers")
            else "none"
        )
    )
    if live_mount_report["failures"]:
        print("[UI Shell] Live addon mount failures:")
        for failure in live_mount_report["failures"]:
            print(f"  - {failure}")
    print(
        "[UI Shell] Addon mount placeholders: "
        + (", ".join(placeholder_targets) if placeholder_targets else "none")
    )
    _print_ui_shell_static_addon_comparison(ui_path, addon_report, live_mount_report, prefix="[UI Shell]")
    print("[UI Shell] Close the shell window to return to the terminal.")
    window.show()
    return app.exec()


if len(sys.argv) >= 2 and str(sys.argv[1] or "").strip().lower() == "--ui-shell":
    shell_smoke = any(str(item or "").strip().lower() == "--shell-smoke" for item in sys.argv[2:])
    ui_arg = sys.argv[2] if len(sys.argv) >= 3 and not str(sys.argv[2] or "").startswith("--") else "main.ui"
    if shell_smoke:
        sys.exit(run_ui_shell_smoke(ui_arg))
    sys.exit(run_ui_shell_preview(ui_arg))

import dry_run
import tutorial_framework
import loop_authoring
import cv2
import numpy as np
from flask import Flask, jsonify
from flask_cors import CORS
from PySide6 import QtCore, QtGui, QtWidgets
from PIL import Image

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
warnings.filterwarnings(
    "ignore",
    message=r".*LoRACompatibleLinear.*deprecated.*",
    category=FutureWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r".*Reference mel length is not equal to 2 \* reference token length\..*",
)
try:
    from pynvml import (
        nvmlInit,
        nvmlShutdown,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetMemoryInfo,
    )
except Exception:
    nvmlInit = None
    nvmlShutdown = None
    nvmlDeviceGetHandleByIndex = None
    nvmlDeviceGetMemoryInfo = None

import engine
import shared_state
from core import sensory, chat_providers
from core.addons import AddonManager
from core.addons.qt_host_services import AddonCapabilityBridgeService, QtChatProviderService, QtChatReplayService, QtDialogService, QtHotkeyService, QtMuseTalkUIService, QtSensoryService, QtShellService, QtVisualReplyService
from musetalk_bridge import MuseTalkBridge
from engine import (
    AVATAR_PROFILE,
    HAND_CALIBRATION,
    RUNTIME_CONFIG,
    collect_replayable_assistant_messages,
    export_chat_session_state,
    get_chat_models,
    import_chat_session_state,
    replace_chat_conversation_history,
    reset_session_state,
    run_companion,
    shutdown_avatar_engine,
    stop_flag,
    trigger_manual_action,
    update_runtime_config,
)


APP_TITLE = "Neural Interface Qt (Experimental)"
SESSION_PATH = Path("qt_session.json")
DEFAULT_LOCAL_VAM_ROOT = r"I:\wam\VaM 1.20.0.6"
DEFAULT_LOCAL_VAM_EXECUTABLE = "VaM.exe"
DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER = "VaM (Desktop Mode).bat"
DEFAULT_LOCAL_VAM_VR_LAUNCHER = "VaM (OpenVR).bat"
QT_PREVIEW_CACHE_LIMIT = 384
QT_PREVIEW_INITIAL_PRELOAD = 96
QT_PREVIEW_AHEAD_PRELOAD = 72

def _load_ui_preview_window(ui_path):
    try:
        from PySide6 import QtUiTools
    except Exception as exc:
        raise RuntimeError("QtUiTools is unavailable, so Designer UI preview mode cannot start.") from exc
    ui_file = QtCore.QFile(str(ui_path))
    if not ui_file.open(QtCore.QIODevice.ReadOnly):
        raise RuntimeError(f"Could not open UI file: {ui_path}")
    try:
        window = QtUiTools.QUiLoader().load(ui_file)
    finally:
        ui_file.close()
    if window is None:
        raise RuntimeError(f"Qt Designer UI did not produce a window: {ui_path}")
    return window

_WIN32_DOCK_OWNER_SUPPORTED = False
_WIN32_GWLP_HWNDPARENT = -8
try:
    if os.name == "nt":
        _win32_user32 = ctypes.windll.user32
        _win32_get_window_owner = getattr(_win32_user32, "GetWindowLongPtrW", None) or getattr(_win32_user32, "GetWindowLongW", None)
        _win32_set_window_owner = getattr(_win32_user32, "SetWindowLongPtrW", None) or getattr(_win32_user32, "SetWindowLongW", None)
        if _win32_get_window_owner is not None and _win32_set_window_owner is not None:
            _win32_get_window_owner.argtypes = [ctypes.c_void_p, ctypes.c_int]
            _win32_get_window_owner.restype = ctypes.c_void_p
            _win32_set_window_owner.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            _win32_set_window_owner.restype = ctypes.c_void_p
            _WIN32_DOCK_OWNER_SUPPORTED = True
except Exception:
    _WIN32_DOCK_OWNER_SUPPORTED = False


def build_vam_launch_icon(size=28):
    size = max(18, int(size or 28))
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    top_gradient = QtGui.QLinearGradient(0, 0, size, size * 0.55)
    top_gradient.setColorAt(0.0, QtGui.QColor("#4d8dff"))
    top_gradient.setColorAt(1.0, QtGui.QColor("#6d6bff"))
    bottom_gradient = QtGui.QLinearGradient(0, size * 0.45, size, size)
    bottom_gradient.setColorAt(0.0, QtGui.QColor("#7d6cff"))
    bottom_gradient.setColorAt(1.0, QtGui.QColor("#ff56c5"))

    stroke = max(2.2, size * 0.11)
    top_pen = QtGui.QPen(QtGui.QBrush(top_gradient), stroke, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
    bottom_pen = QtGui.QPen(QtGui.QBrush(bottom_gradient), stroke, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)

    w = float(size)
    # Stylized "V"
    painter.setPen(top_pen)
    painter.drawPolyline(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(w * 0.12, w * 0.18),
                QtCore.QPointF(w * 0.22, w * 0.42),
                QtCore.QPointF(w * 0.32, w * 0.18),
            ]
        )
    )
    # Stylized "A"
    painter.drawPolyline(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(w * 0.46, w * 0.42),
                QtCore.QPointF(w * 0.56, w * 0.18),
                QtCore.QPointF(w * 0.66, w * 0.42),
            ]
        )
    )
    painter.drawLine(
        QtCore.QPointF(w * 0.50, w * 0.31),
        QtCore.QPointF(w * 0.62, w * 0.31),
    )

    # Stylized "M"
    painter.setPen(bottom_pen)
    painter.drawPolyline(
        QtGui.QPolygonF(
            [
                QtCore.QPointF(w * 0.17, w * 0.82),
                QtCore.QPointF(w * 0.17, w * 0.54),
                QtCore.QPointF(w * 0.33, w * 0.72),
                QtCore.QPointF(w * 0.50, w * 0.54),
                QtCore.QPointF(w * 0.50, w * 0.82),
            ]
        )
    )
    painter.end()
    return QtGui.QIcon(pixmap)
QT_MUSETALK_LOOP_FADE_MS = 180
DEFAULT_CHUNKING_VALUES = {
    "chunk_target_chars": 100,
    "chunk_max_chars": 200,
    "musetalk_chunk_target_chars": 110,
    "musetalk_chunk_max_chars": 220,
    "musetalk_quickstart_1_target_chars": 170,
    "musetalk_quickstart_1_max_chars": 320,
    "musetalk_quickstart_2_target_chars": 130,
    "musetalk_quickstart_2_max_chars": 240,
    "stream_chunk_target_chars": 85,
    "stream_chunk_max_chars": 170,
    "stream_first_chunk_min_chars": 28,
    "stream_force_flush_seconds": 0.9,
    "stream_force_flush_later_seconds": 1.4,
}
DEFAULT_MAX_RESPONSE_TOKENS = 600
DRY_RUN_MAX_RESPONSE_TOKENS = 600
MUSE_VRAM_MODE_LABELS = OrderedDict([
    ("quality", "Quality"),
    ("balanced", "Balanced"),
    ("low", "Low VRAM"),
    ("very_low", "Very Low VRAM"),
])
MUSE_AVATAR_RESULTS_DIR = Path("MuseTalk") / "results" / "v15" / "avatars"
MODEL_ADVISOR_BUILTIN_FINGERPRINTS_GIB = {
    "musetalk": {
        "Quality": 5.8,
        "Balanced": 4.0,
        "Low VRAM": 2.3,
        "Very Low VRAM": 1.5,
    },
    "vseeface": 0.8,
    "vam": 1.0,
}
MODEL_ADVISOR_TTS_OVERHEAD_GIB = {
    "pockettts": 2.0,
    "chatterbox": 5.2,
}
MODEL_ADVISOR_STREAM_OVERHEAD_GIB = 0.5
MODEL_ADVISOR_SAFETY_MARGIN_GIB = 1.5
PERFORMANCE_PROFILE_APPLY_KEYS = {
    "avatar_mode",
    "stream_mode",
    "tts_backend",
    "musetalk_vram_mode",
    "model_name",
    "chunk_target_chars",
    "chunk_max_chars",
    "musetalk_chunk_target_chars",
    "musetalk_chunk_max_chars",
    "musetalk_quickstart_1_target_chars",
    "musetalk_quickstart_1_max_chars",
    "musetalk_quickstart_2_target_chars",
    "musetalk_quickstart_2_max_chars",
    "stream_chunk_target_chars",
    "stream_chunk_max_chars",
    "stream_first_chunk_min_chars",
    "stream_force_flush_seconds",
    "stream_force_flush_later_seconds",
}
APP_STYLESHEET = """
QMainWindow { background: #11161d; }
QWidget { color: #e5e9f0; font-family: "Segoe UI"; font-size: 12px; }
QFrame#Panel { background: #18202a; border: 1px solid #283342; border-radius: 14px; }
QFrame#HeaderCard { background: #131a23; border: 1px solid #243244; border-radius: 12px; }
QScrollArea { background: #18202a; border: 1px solid #273342; border-radius: 10px; }
QScrollArea > QWidget > QWidget { background: #18202a; color: #e5e9f0; }
QPushButton {
    background: #223247;
    border: 1px solid #324b69;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover { background: #29405b; }
QPushButton:disabled { color: #7f8791; background: #1a2028; border-color: #27303b; }
QComboBox, QTextEdit, QPlainTextEdit, QLineEdit, QListWidget, QSpinBox, QDoubleSpinBox, QGroupBox, QTabWidget::pane {
    background: #0f141b;
    border: 1px solid #273342;
    border-radius: 10px;
}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    color: #f2f5f9;
    padding: 4px 8px;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button, QSpinBox::up-button, QSpinBox::down-button {
    background: #17212c;
    border-left: 1px solid #324055;
    width: 18px;
}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover, QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #223247;
}
QComboBox QAbstractItemView, QListWidget {
    background: #16202b;
    color: #f2f5f9;
    selection-background-color: #29405b;
    selection-color: #ffffff;
    border: 1px solid #324b69;
    outline: 0;
}
QMenu {
    background: #16202b;
    color: #f2f5f9;
    border: 1px solid #324b69;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    background: transparent;
    color: #f2f5f9;
    padding: 6px 24px 6px 10px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #29405b;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #7f8791;
    background: transparent;
}
QMenu::separator {
    height: 1px;
    background: #2c3a4b;
    margin: 6px 4px;
}
QTabBar::tab {
    background: #18202a;
    border: 1px solid #2a3544;
    padding: 8px 12px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
}
QTabBar::tab:selected { background: #233245; }
QMessageBox, QDialog {
    background: #11161d;
}
QMessageBox QLabel, QDialog QLabel {
    color: #e5e9f0;
}
QMessageBox QPushButton, QDialog QPushButton {
    min-width: 90px;
}
QGroupBox {
    margin-top: 10px;
    padding-top: 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
"""


flask_app = Flask(__name__)
CORS(flask_app)


@flask_app.route("/get-expression")
def get_expression():
    return jsonify(shared_state.current_expression_data)


@flask_app.route("/get-musetalk-preview")
def get_musetalk_preview():
    return jsonify(shared_state.current_musetalk_frame_data)


def start_api():
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    flask_app.run(port=5005, debug=False, use_reloader=False)


class QtConsoleBridge(QtCore.QObject):
    text_ready = QtCore.Signal(str)
    chat_ready = QtCore.Signal(str)
    status_ready = QtCore.Signal(int, int)
    chat_status_ready = QtCore.Signal(int, int)
    rebuild_chat_ready = QtCore.Signal()


class QtTextRedirector:
    _ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    _CHAT_REBUILD_SENTINEL = "[[CHAT_REBUILD]]"

    def __init__(self, bridge, mirror_stream=None):
        self.bridge = bridge
        self.mirror_stream = mirror_stream
        self.line_count = 0
        self.chat_line_count = 0
        self._chat_buffer = ""
        self._line_buffer = ""
        self._discard_line = False
        self._progress_patterns = [
            re.compile(r"^\s*Fetching \d+ files:"),
            re.compile(r"^\s*\d+%[\|#]"),
            re.compile(r"^\s*\d+%\|"),
            re.compile(r"^\s*\|\s*\d+/\d+"),
            re.compile(r"^\s*\d+/\d+\s*\["),
        ]

    def _should_skip_line(self, line):
        stripped = self._ANSI_ESCAPE_RE.sub("", str(line or "")).replace("\r", "").strip()
        if not stripped:
            return False
        if "Reference mel length is not equal to 2 * reference token length." in stripped:
            return True
        if any(pattern.search(stripped) for pattern in self._progress_patterns):
            return True
        if "it/s" in stripped and (re.search(r"\b\d+/\d+\b", stripped) or "%|" in stripped or "#|" in stripped):
            return True
        return False

    def _emit_text(self, value):
        if not value:
            return
        self.bridge.text_ready.emit(value)
        self.line_count += value.count("\n") or 1
        self.bridge.status_ready.emit(self.line_count, 1)
        if self.mirror_stream:
            try:
                self.mirror_stream.write(value)
            except Exception:
                pass

    def write(self, value):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        elif not isinstance(value, str):
            value = str(value)
        if not value:
            return
        if self._CHAT_REBUILD_SENTINEL in value:
            self.bridge.rebuild_chat_ready.emit()
            value = value.replace(self._CHAT_REBUILD_SENTINEL, "")
        if not value:
            return
        if re.search(r"💬 You(?: \([^)]*\))?:|🤖 Assistant:", value):
            self._append_chat_stream(value)
        parts = re.split(r"(\r|\n)", value)
        for part in parts:
            if part in {"\r", "\n"}:
                line = self._line_buffer
                self._line_buffer = ""
                should_emit = (not self._discard_line) and (not self._should_skip_line(line))
                self._discard_line = False
                if should_emit:
                    self._emit_text(line + "\n")
                continue
            if self._discard_line:
                continue
            self._line_buffer += part
            if self._should_skip_line(self._line_buffer):
                self._line_buffer = ""
                self._discard_line = True

    def flush(self):
        if self._line_buffer and not self._discard_line and not self._should_skip_line(self._line_buffer):
            self._emit_text(self._line_buffer)
        self._line_buffer = ""
        self._discard_line = False
        if self.mirror_stream:
            try:
                self.mirror_stream.flush()
            except Exception:
                pass

    def _append_chat_stream(self, value):
        self._chat_buffer += value
        normalized = re.sub(r"(?<!\n)(💬 You(?: \([^)]*\))?:|🤖 Assistant:)", r"\n\1", self._chat_buffer)
        if normalized.startswith("\n"):
            normalized = normalized[1:]
        self._chat_buffer = ""
        self.bridge.chat_ready.emit(normalized)
        emitted_lines = sum(1 for line in normalized.splitlines() if line.strip())
        self.chat_line_count += emitted_lines or 1
        self.bridge.chat_status_ready.emit(self.chat_line_count, 1)


class LabeledSlider(QtWidgets.QWidget):
    value_changed = QtCore.Signal(float)

    def __init__(self, title, minimum, maximum, value, is_int=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.is_int = is_int
        self.minimum = minimum
        self.maximum = maximum
        self.scale = 100 if not is_int else 1

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.label = QtWidgets.QLabel()
        self.label.setStyleSheet("font-weight: 600; color: #d8dee9;")
        self.slider = NoWheelSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimum(int(minimum * self.scale))
        self.slider.setMaximum(int(maximum * self.scale))
        self.slider.valueChanged.connect(self._on_value_changed)

        layout.addWidget(self.label)
        layout.addWidget(self.slider)
        self.set_value(value)
        self._refresh_label()

    def _normalized_value(self):
        raw = self.slider.value() / self.scale
        return int(raw) if self.is_int else round(raw, 2)

    def _refresh_label(self):
        self.label.setText(f"{self.title}: {self._normalized_value()}")

    def _on_value_changed(self, _):
        self._refresh_label()
        self.value_changed.emit(float(self._normalized_value()))

    def set_value(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(int(value * self.scale))
        self.slider.blockSignals(False)
        self._refresh_label()

    def value(self):
        return self._normalized_value()


class NoWheelSlider(QtWidgets.QSlider):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpinBox(QtWidgets.QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelComboBox(QtWidgets.QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class CollapsibleSection(QtWidgets.QWidget):
    def __init__(self, title, content_widget=None, *, expanded=True, parent=None):
        super().__init__(parent)
        self._title = str(title or "").strip()
        self._summary = ""

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.toggle_button = QtWidgets.QToolButton()
        self.toggle_button.setObjectName("collapsible_section_toggle")
        self.toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(bool(expanded))
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.clicked.connect(self._on_toggled)
        self.toggle_button.setStyleSheet(
            "QToolButton { color: #d8dee9; font-weight: 600; border: 1px solid #273342; "
            "background: #111923; border-radius: 8px; padding: 6px 8px; text-align: left; }"
            "QToolButton:hover { background: #182331; }"
        )
        layout.addWidget(self.toggle_button)

        self.content_widget = content_widget or QtWidgets.QWidget()
        layout.addWidget(self.content_widget)
        self._refresh()

    def setContentWidget(self, widget):
        if widget is None or widget is self.content_widget:
            return
        layout = self.layout()
        old_widget = self.content_widget
        self.content_widget = widget
        layout.insertWidget(1, self.content_widget)
        if old_widget is not None:
            old_widget.setParent(None)
            old_widget.deleteLater()
        self._refresh()

    def setSummary(self, summary):
        self._summary = str(summary or "").strip()
        self._refresh()

    def isExpanded(self):
        return bool(self.toggle_button.isChecked())

    def setExpanded(self, expanded):
        self.toggle_button.setChecked(bool(expanded))
        self._refresh()

    def _on_toggled(self, _checked):
        self._refresh()

    def _refresh(self):
        expanded = bool(self.toggle_button.isChecked())
        self.toggle_button.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        label = self._title
        if self._summary:
            label = f"{label}  -  {self._summary}"
        self.toggle_button.setText(label)
        self.content_widget.setVisible(expanded)


class NoWheelTabWidget(QtWidgets.QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(NoWheelTabBar())
        self.currentChanged.connect(self._on_current_tab_changed)

    def _on_current_tab_changed(self, _index):
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None:
            parent.updateGeometry()

    def _current_page_height_hint(self):
        page = self.currentWidget()
        if page is None:
            return 0
        if isinstance(page, QtWidgets.QScrollArea):
            try:
                return int(page.sizeHint().height() or page.minimumSizeHint().height() or 0)
            except Exception:
                pass
            page = page.widget()
            if page is None:
                return 0
        layout = page.layout()
        if layout is not None:
            try:
                return int(layout.sizeHint().height() or page.minimumSizeHint().height() or page.sizeHint().height() or 0)
            except Exception:
                pass
        try:
            return int(page.minimumSizeHint().height() or page.sizeHint().height() or 0)
        except Exception:
            return 0

    def _adaptive_height_hint(self):
        tab_bar = self.tabBar()
        tab_height = int(tab_bar.sizeHint().height()) if tab_bar is not None else 0
        frame_width = int(self.style().pixelMetric(QtWidgets.QStyle.PM_DefaultFrameWidth, None, self) or 0)
        page_height = self._current_page_height_hint()
        return max(tab_height + page_height + (frame_width * 4) + 12, tab_height + 72)

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(self._adaptive_height_hint())
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setHeight(self._adaptive_height_hint())
        return hint

    def wheelEvent(self, event):
        event.ignore()


class NoWheelTabBar(QtWidgets.QTabBar):
    def wheelEvent(self, event):
        event.ignore()


class AltWheelZoomScrollArea(QtWidgets.QScrollArea):
    zoomRequested = QtCore.Signal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    def _handle_alt_zoom_event(self, event):
        modifiers = event.modifiers()
        if not modifiers:
            try:
                modifiers = QtWidgets.QApplication.keyboardModifiers()
            except Exception:
                modifiers = QtCore.Qt.NoModifier
        if not modifiers:
            try:
                modifiers = QtGui.QGuiApplication.queryKeyboardModifiers()
            except Exception:
                modifiers = QtCore.Qt.NoModifier
        alt_down = bool(modifiers & QtCore.Qt.AltModifier)
        if not alt_down and os.name == "nt":
            try:
                alt_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000)
            except Exception:
                alt_down = False
        if not alt_down:
            return False
        angle_delta = event.angleDelta()
        delta_value = angle_delta.y()
        if not delta_value:
            delta_value = angle_delta.x()
        if not delta_value:
            pixel_delta = event.pixelDelta()
            if pixel_delta is not None:
                delta_value = pixel_delta.y() or pixel_delta.x()
        if not delta_value:
            return False
        pos = event.position() if hasattr(event, "position") else QtCore.QPointF()
        self.zoomRequested.emit(1.12 if delta_value > 0 else (1.0 / 1.12), float(pos.x()), float(pos.y()))
        event.accept()
        return True

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QtCore.QEvent.Wheel:
            if self._handle_alt_zoom_event(event):
                return True
        return super().eventFilter(watched, event)

    def viewportEvent(self, event):
        if event.type() == QtCore.QEvent.Wheel and self._handle_alt_zoom_event(event):
            return True
        return super().viewportEvent(event)

    def wheelEvent(self, event):
        if self._handle_alt_zoom_event(event):
            return
        super().wheelEvent(event)


class ContextTokenStepper(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minimum = 0
        self._maximum = 999999
        self._step = 1
        self._value = 0
        self._suppress_signal = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.line_edit = QtWidgets.QLineEdit()
        self.line_edit.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.line_edit.setMinimumWidth(94)
        self.line_edit.setStyleSheet(
            "QLineEdit {"
            " background: #0f141b; border: 1px solid #273342; border-right: 0;"
            " border-top-left-radius: 10px; border-bottom-left-radius: 10px;"
            " border-top-right-radius: 0; border-bottom-right-radius: 0;"
            " padding: 4px 10px; color: #f2f5f9; }"
        )
        self.line_edit.editingFinished.connect(self._commit_text)

        button_column = QtWidgets.QFrame()
        button_column.setFixedWidth(28)
        button_column.setFixedHeight(28)
        button_column.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        button_column.setStyleSheet(
            "QFrame { background: #0f141b; border: 1px solid #273342;"
            " border-top-right-radius: 10px; border-bottom-right-radius: 10px; }"
        )
        button_layout = QtWidgets.QVBoxLayout(button_column)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(0)

        self.up_button = QtWidgets.QToolButton()
        self.up_button.setArrowType(QtCore.Qt.UpArrow)
        self.up_button.setAutoRepeat(True)
        self.up_button.setFixedSize(26, 13)
        self.up_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.up_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.up_button.clicked.connect(lambda: self.stepBy(1))

        self.down_button = QtWidgets.QToolButton()
        self.down_button.setArrowType(QtCore.Qt.DownArrow)
        self.down_button.setAutoRepeat(True)
        self.down_button.setFixedSize(26, 13)
        self.down_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.down_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.down_button.clicked.connect(lambda: self.stepBy(-1))

        divider = QtWidgets.QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #273342;")

        button_layout.addWidget(self.up_button)
        button_layout.addWidget(divider)
        button_layout.addWidget(self.down_button)

        self.setFixedHeight(28)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.line_edit)
        layout.addWidget(button_column)

    def setRange(self, minimum, maximum):
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self.setValue(self._value)

    def setSingleStep(self, step):
        self._step = max(1, int(step))

    def setAccelerated(self, _enabled):
        pass

    def setMinimumWidth(self, width):
        self.line_edit.setMinimumWidth(max(48, int(width) - 28))

    def setMaximumWidth(self, width):
        self.line_edit.setMaximumWidth(max(48, int(width) - 28))

    def _emit_value_changed(self):
        if not self._suppress_signal:
            self.valueChanged.emit(int(self._value))

    def _clamp(self, value):
        return max(self._minimum, min(self._maximum, int(value)))

    def _refresh_text(self):
        self.line_edit.setText(str(int(self._value)))

    def _commit_text(self):
        raw = str(self.line_edit.text() or "").strip()
        try:
            value = int(raw)
        except Exception:
            value = self._value
        self.setValue(value)

    def setValue(self, value):
        clamped = self._clamp(value)
        changed = clamped != self._value
        self._value = clamped
        self._suppress_signal = True
        try:
            self._refresh_text()
        finally:
            self._suppress_signal = False
        if changed:
            self._emit_value_changed()

    def value(self):
        return int(self._value)

    def stepBy(self, delta_steps):
        self.setValue(self._value + int(delta_steps) * self._step)

    def wheelEvent(self, event):
        event.ignore()


class DecimalStepper(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minimum = 0.0
        self._maximum = 999999.0
        self._step = 1.0
        self._decimals = 1
        self._value = 0.0
        self._suppress_signal = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.line_edit = QtWidgets.QLineEdit()
        self.line_edit.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.line_edit.setMinimumWidth(94)
        self.line_edit.setStyleSheet(
            "QLineEdit {"
            " background: #0f141b; border: 1px solid #273342; border-right: 0;"
            " border-top-left-radius: 10px; border-bottom-left-radius: 10px;"
            " border-top-right-radius: 0; border-bottom-right-radius: 0;"
            " padding: 4px 10px; color: #f2f5f9; }"
        )
        self.line_edit.editingFinished.connect(self._commit_text)

        button_column = QtWidgets.QFrame()
        button_column.setFixedWidth(28)
        button_column.setFixedHeight(28)
        button_column.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        button_column.setStyleSheet(
            "QFrame { background: #0f141b; border: 1px solid #273342;"
            " border-top-right-radius: 10px; border-bottom-right-radius: 10px; }"
        )
        button_layout = QtWidgets.QVBoxLayout(button_column)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(0)

        self.up_button = QtWidgets.QToolButton()
        self.up_button.setArrowType(QtCore.Qt.UpArrow)
        self.up_button.setAutoRepeat(True)
        self.up_button.setFixedSize(26, 13)
        self.up_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.up_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.up_button.clicked.connect(lambda: self.stepBy(1))

        self.down_button = QtWidgets.QToolButton()
        self.down_button.setArrowType(QtCore.Qt.DownArrow)
        self.down_button.setAutoRepeat(True)
        self.down_button.setFixedSize(26, 13)
        self.down_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.down_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; min-width: 26px; min-height: 13px; }"
            "QToolButton:hover { background: #182331; }"
        )
        self.down_button.clicked.connect(lambda: self.stepBy(-1))

        divider = QtWidgets.QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #273342;")

        button_layout.addWidget(self.up_button)
        button_layout.addWidget(divider)
        button_layout.addWidget(self.down_button)

        self.setFixedHeight(28)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.line_edit)
        layout.addWidget(button_column)

    def setRange(self, minimum, maximum):
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self.setValue(self._value)

    def setSingleStep(self, step):
        self._step = max(0.001, float(step))

    def setDecimals(self, decimals):
        self._decimals = max(0, int(decimals))
        self._refresh_text()

    def setAccelerated(self, _enabled):
        pass

    def setMinimumWidth(self, width):
        self.line_edit.setMinimumWidth(max(48, int(width) - 28))

    def setMaximumWidth(self, width):
        self.line_edit.setMaximumWidth(max(48, int(width) - 28))

    def _emit_value_changed(self):
        if not self._suppress_signal:
            self.valueChanged.emit(float(self._value))

    def _clamp(self, value):
        numeric = float(value)
        return max(self._minimum, min(self._maximum, numeric))

    def _refresh_text(self):
        self.line_edit.setText(f"{self._value:.{self._decimals}f}")

    def _commit_text(self):
        raw = str(self.line_edit.text() or "").strip().replace(",", ".")
        try:
            value = float(raw)
        except Exception:
            value = self._value
        self.setValue(value)

    def setValue(self, value):
        clamped = round(self._clamp(value), self._decimals)
        changed = not math.isclose(clamped, self._value, rel_tol=1e-9, abs_tol=10 ** (-(self._decimals + 1)))
        self._value = clamped
        self._suppress_signal = True
        try:
            self._refresh_text()
        finally:
            self._suppress_signal = False
        if changed:
            self._emit_value_changed()

    def value(self):
        return float(self._value)

    def stepBy(self, delta_steps):
        self.setValue(self._value + float(delta_steps) * self._step)

    def wheelEvent(self, event):
        event.ignore()


class ChunkProgressTelemetryBar(QtWidgets.QWidget):
    def __init__(self, title, mode="preview", parent=None):
        super().__init__(parent)
        self.title = str(title or "")
        self.mode = str(mode or "preview")
        self._snapshot = {}
        self._preview_state = {}
        self.setMinimumHeight(26)

    def set_snapshot(self, snapshot, preview_state):
        self._snapshot = dict(snapshot or {})
        self._preview_state = dict(preview_state or {})
        self.update()

    def _ordered_chunks(self):
        chunks = list((self._snapshot or {}).get("chunks", []) or [])
        chunks.sort(key=lambda item: int((item or {}).get("sequence_index", 0) or 0))
        return chunks

    def _chunk_render_progress(self, chunk):
        chunk = dict(chunk or {})
        status = str(chunk.get("status", "") or "")
        if status in {"rendered"}:
            return 1.0
        expected = int(chunk.get("expected_frame_count", 0) or 0)
        rendered = int(chunk.get("rendered_frame_count", 0) or 0)
        if expected > 0 and rendered > 0:
            return max(0.0, min(float(rendered) / float(expected), 1.0))
        if status == "rendering":
            return 0.0
        return 0.0

    def _chunk_stage(self, chunk):
        chunk = dict(chunk or {})
        status = str(chunk.get("status", "") or "")
        playback_state = str(chunk.get("playback_state", "") or "")
        rendered = int(chunk.get("rendered_frame_count", 0) or 0)
        if status in {"failed"} or playback_state == "failed":
            return "failed"
        if status in {"cancelled"} or playback_state == "cancelled":
            return "cancelled"
        if playback_state in {"completed"}:
            return "completed"
        if playback_state in {"playing"}:
            return "playing"
        if status in {"rendered"}:
            return "rendered"
        if status == "rendering":
            return "rendering_frames" if rendered > 0 else "rendering_setup"
        if status == "queued_for_render":
            return "queued"
        if status == "generating_audio":
            return "tts"
        return "planned"

    def _render_bar_stage(self, chunk):
        stage = self._chunk_stage(chunk)
        if stage == "playing":
            return "rendered"
        if stage == "completed":
            return "completed"
        return stage

    def _stage_colors(self, stage):
        stage = str(stage or "planned")
        if stage == "tts":
            return (QtGui.QColor("#34255a"), QtGui.QColor("#8b6cf0"))
        if stage == "queued":
            return (QtGui.QColor("#4b3317"), QtGui.QColor("#d69c42"))
        if stage == "rendering_setup":
            return (QtGui.QColor("#4e2218"), QtGui.QColor("#ef8a5b"))
        if stage == "rendering_frames":
            return (QtGui.QColor("#18344f"), QtGui.QColor("#4fc3f7"))
        if stage == "rendered":
            return (QtGui.QColor("#1b3348"), QtGui.QColor("#70d6ff"))
        if stage == "playing":
            return (QtGui.QColor("#1f3d2a"), QtGui.QColor("#58d68d"))
        if stage == "completed":
            return (QtGui.QColor("#24303d"), QtGui.QColor("#8aa0b5"))
        if stage == "failed":
            return (QtGui.QColor("#4a1a20"), QtGui.QColor("#ff6b81"))
        if stage == "cancelled":
            return (QtGui.QColor("#2a2f36"), QtGui.QColor("#7f8a96"))
        return (QtGui.QColor("#223042"), QtGui.QColor("#3a4d63"))

    def _chunk_preview_progress(self, chunk):
        chunk = dict(chunk or {})
        playback_state = str(chunk.get("playback_state", "") or "")
        if playback_state == "completed":
            return 1.0
        state = dict(self._preview_state or {})
        try:
            active_index = int(state.get("sequence_index"))
        except Exception:
            active_index = None
        chunk_index = int(chunk.get("sequence_index", 0) or 0)
        if active_index is not None:
            if chunk_index < active_index:
                return 1.0
            if chunk_index > active_index:
                return 0.0
            preview_frame_index = int(state.get("preview_frame_index", -1) or -1)
            expected_frames = int(state.get("expected_frame_count", 0) or state.get("frame_count", 0) or chunk.get("expected_frame_count", 0) or 0)
            if preview_frame_index < 0 or expected_frames <= 1:
                return 0.0
            return max(0.0, min(float(preview_frame_index) / max(expected_frames - 1, 1), 1.0))
        return 1.0 if playback_state == "completed" else 0.0

    def _segment_count(self):
        if bool((self._snapshot or {}).get("stream_mode")):
            chunks = self._ordered_chunks()
            return max(1, len(chunks))
        return max(1, len(self._visual_segments()))

    def _ready_progress(self):
        progress = 0.0
        for chunk in self._ordered_chunks():
            status = str(chunk.get("status", "") or "")
            if status == "rendered":
                progress += 1.0
                continue
            partial = self._chunk_render_progress(chunk)
            if partial > 0.0:
                progress += partial
            break
        return progress

    def _preview_progress(self):
        chunks = self._ordered_chunks()
        completed_progress = 0.0
        for chunk in chunks:
            if str(chunk.get("playback_state", "") or "") == "completed":
                completed_progress += 1.0
            else:
                break
        state = dict(self._preview_state or {})
        sequence_index = state.get("sequence_index")
        preview_frame_index = int(state.get("preview_frame_index", -1) or -1)
        expected_frames = int(state.get("expected_frame_count", 0) or state.get("frame_count", 0) or 0)
        if sequence_index is None or preview_frame_index < 0 or expected_frames <= 1:
            return completed_progress
        try:
            sequence_index = int(sequence_index)
        except Exception:
            return completed_progress
        intra = max(0.0, min(float(preview_frame_index) / max(expected_frames - 1, 1), 1.0))
        return max(completed_progress, float(sequence_index) + intra)

    def _startup_gate_fraction(self, chunk):
        chunk = dict(chunk or {})
        startup_frames = int(chunk.get("startup_buffer_frames", 0) or 0)
        expected = int(chunk.get("expected_frame_count", 0) or 0)
        if startup_frames <= 0 or expected <= 0:
            return 0.0
        return max(0.0, min(float(startup_frames) / float(expected), 1.0))

    def _visual_segments(self):
        segments = []
        for chunk in self._ordered_chunks():
            gate_fraction = self._startup_gate_fraction(chunk)
            sequence_index = int(chunk.get("sequence_index", -1) or -1)
            expected = int(chunk.get("expected_frame_count", 0) or 0)
            total_weight = float(expected if expected > 0 else 1.0)
            if sequence_index == 0 and 0.0 < gate_fraction < 1.0:
                startup_weight = max(total_weight * gate_fraction, 1.0)
                remainder_weight = max(total_weight - startup_weight, 1.0)
                segments.append(
                    {
                        "chunk": chunk,
                        "part": "startup",
                        "start_fraction": 0.0,
                        "end_fraction": gate_fraction,
                        "weight": startup_weight,
                    }
                )
                segments.append(
                    {
                        "chunk": chunk,
                        "part": "remainder",
                        "start_fraction": gate_fraction,
                        "end_fraction": 1.0,
                        "weight": remainder_weight,
                    }
                )
            else:
                segments.append(
                    {
                        "chunk": chunk,
                        "part": "whole",
                        "start_fraction": 0.0,
                        "end_fraction": 1.0,
                        "weight": total_weight,
                    }
                )
        return segments

    def _segment_fill_fraction(self, segment, chunk_fraction):
        segment = dict(segment or {})
        start_fraction = float(segment.get("start_fraction", 0.0) or 0.0)
        end_fraction = float(segment.get("end_fraction", 1.0) or 1.0)
        span = max(end_fraction - start_fraction, 1e-6)
        if chunk_fraction <= start_fraction:
            return 0.0
        if chunk_fraction >= end_fraction:
            return 1.0
        return max(0.0, min((float(chunk_fraction) - start_fraction) / span, 1.0))

    def _progress_value(self):
        if self.mode == "ready":
            return self._ready_progress()
        return self._preview_progress()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QtGui.QPen(QtGui.QColor("#273342"), 1))
        painter.setBrush(QtGui.QColor("#10161f"))
        painter.drawRoundedRect(rect, 9, 9)

        title_rect = QtCore.QRectF(rect.left() + 8, rect.top() + 2, 100, 12)
        painter.setPen(QtGui.QColor("#8da6c1"))
        painter.setFont(QtGui.QFont("Segoe UI", 8))
        painter.drawText(title_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self.title)

        bar_rect = QtCore.QRectF(rect.left() + 8, rect.top() + 14, rect.width() - 16, rect.height() - 18)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#192331"))
        painter.drawRoundedRect(bar_rect, 6, 6)

        total_segments = self._segment_count()
        progress = max(0.0, min(self._progress_value(), float(total_segments)))
        stream_mode = bool((self._snapshot or {}).get("stream_mode"))

        fill_color = QtGui.QColor("#4fc3f7") if self.mode == "ready" else QtGui.QColor("#58d68d")
        border_color = QtGui.QColor("#8cc7ff") if self.mode == "ready" else QtGui.QColor("#9cf2bd")

        if stream_mode:
            fill_ratio = progress / max(float(total_segments), 1.0)
            filled_rect = QtCore.QRectF(bar_rect)
            filled_rect.setWidth(bar_rect.width() * fill_ratio)
            painter.setBrush(fill_color)
            painter.drawRoundedRect(filled_rect, 6, 6)

            if total_segments > 1:
                painter.setBrush(QtCore.Qt.NoBrush)
                separator_pen = QtGui.QPen(QtGui.QColor("#d7e3f1" if self.mode == "preview" else "#b8d4ea"))
                separator_pen.setWidth(1)
                separator_pen.setCosmetic(True)
                separator_pen.setStyle(QtCore.Qt.DotLine)
                separator_pen.setColor(QtGui.QColor(separator_pen.color().red(), separator_pen.color().green(), separator_pen.color().blue(), 90))
                painter.setPen(separator_pen)
                for index in range(1, total_segments):
                    x = bar_rect.left() + (bar_rect.width() * float(index) / float(total_segments))
                    painter.drawLine(
                        QtCore.QPointF(x, bar_rect.top() + 1.0),
                        QtCore.QPointF(x, bar_rect.bottom() - 1.0),
                    )
                painter.setPen(QtCore.Qt.NoPen)
        else:
            visual_segments = self._visual_segments()
            gap = 2.0
            total_gap = gap * max(total_segments - 1, 0)
            usable_width = max(12.0, bar_rect.width() - total_gap)
            total_weight = sum(max(float(seg.get("weight", 1.0) or 1.0), 0.001) for seg in visual_segments)
            seg_x = bar_rect.left()
            for index in range(total_segments):
                segment = visual_segments[index] if index < len(visual_segments) else {}
                weight = max(float(segment.get("weight", 1.0) or 1.0), 0.001)
                if index == total_segments - 1:
                    segment_width = max(3.0, (bar_rect.right() - seg_x))
                else:
                    segment_width = max(3.0, usable_width * (weight / max(total_weight, 0.001)))
                seg_rect = QtCore.QRectF(seg_x, bar_rect.top(), segment_width, bar_rect.height())
                chunk = dict(segment.get("chunk", {}) or {})
                if self.mode == "ready":
                    stage = self._render_bar_stage(chunk)
                    stage_bg, stage_fg = self._stage_colors(stage)
                else:
                    stage_fg = fill_color
                if self.mode == "ready":
                    painter.setBrush(stage_bg)
                else:
                    painter.setBrush(QtGui.QColor("#223042"))
                painter.drawRoundedRect(seg_rect, 4, 4)
                if self.mode == "ready":
                    chunk_fill_fraction = self._chunk_render_progress(chunk)
                else:
                    chunk_fill_fraction = self._chunk_preview_progress(chunk)
                fill_fraction = self._segment_fill_fraction(segment, chunk_fill_fraction)
                if fill_fraction <= 0:
                    if self.mode == "ready" and stage in {"tts", "queued", "rendering_setup"}:
                        painter.setPen(QtGui.QPen(stage_fg, 1))
                        painter.setBrush(QtCore.Qt.NoBrush)
                        painter.drawRoundedRect(seg_rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
                        painter.setPen(QtCore.Qt.NoPen)
                    continue
                if segment.get("part") == "startup":
                    painter.setPen(QtGui.QPen(QtGui.QColor("#9fdcff"), 1))
                else:
                    painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(stage_fg if self.mode == "ready" else fill_color)
                filled = QtCore.QRectF(seg_rect)
                filled.setWidth(max(1.0, seg_rect.width() * fill_fraction))
                painter.drawRoundedRect(filled, 4, 4)
                painter.setPen(QtCore.Qt.NoPen)
                seg_x += segment_width + gap

        painter.setPen(QtGui.QPen(border_color, 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(bar_rect, 6, 6)


class PipelineTelemetryWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.summary_label = QtWidgets.QLabel("Telemetry appears during MuseTalk and VaM replies.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #9fb2c6;")
        layout.addWidget(self.summary_label)

        self.legend_label = QtWidgets.QLabel(
            "<span style='color:#8b6cf0;'>TTS</span>  "
            "<span style='color:#d69c42;'>Queued</span>  "
            "<span style='color:#ef8a5b;'>Render Setup</span>  "
            "<span style='color:#4fc3f7;'>Frames</span>  "
            "<span style='color:#9fdcff;'>First chunk split at startup gate</span>"
        )
        self.legend_label.setStyleSheet("color: #7f95ab;")
        layout.addWidget(self.legend_label)

        self.ready_bar = ChunkProgressTelemetryBar("Render Ready", mode="ready")
        self.preview_bar = ChunkProgressTelemetryBar("Preview / Playback", mode="preview")
        layout.addWidget(self.ready_bar)
        layout.addWidget(self.preview_bar)

    def update_snapshot(self, snapshot, preview_state):
        snapshot = dict(snapshot or {})
        preview_state = dict(preview_state or {})
        self.ready_bar.set_snapshot(snapshot, preview_state)
        self.preview_bar.set_snapshot(snapshot, preview_state)

        chunks = list(snapshot.get("chunks", []) or [])
        chunk_total = len(chunks)
        if chunk_total <= 0:
            self.summary_label.setText("Telemetry appears during MuseTalk and VaM replies.")
            return

        ready_progress = self.ready_bar._ready_progress()
        preview_progress = self.preview_bar._preview_progress()
        lead_chunks = ready_progress - preview_progress
        stream_mode = bool(snapshot.get("stream_mode"))
        stream_open = bool(snapshot.get("stream_open"))
        engine_mode = str(snapshot.get("engine_mode", "") or "").strip().lower()
        if stream_mode and stream_open:
            phase = "Streaming"
        elif stream_mode:
            phase = "Stream settling"
        elif engine_mode == "vam":
            phase = "VaM delegated playback"
        else:
            phase = "Chunked reply"
        if lead_chunks >= 1.5:
            assessment = "Comfortable buffer lead"
            color = "#9cf2bd"
        elif lead_chunks >= 0.5:
            assessment = "Tight but healthy"
            color = "#f5d76e"
        else:
            assessment = "Preview is close to the buffer edge"
            color = "#ff8f8f"
        self.summary_label.setText(
            f"{phase}: preview {preview_progress:.2f}/{chunk_total} chunks, "
            f"render ready {ready_progress:.2f}/{chunk_total}, "
            f"lead {lead_chunks:.2f} chunks. "
            f"<span style='color:{color}; font-weight:700;'>{assessment}.</span>"
        )
        if not stream_mode and chunks:
            first_chunk = dict(chunks[0] or {})
            gate_frames = int(first_chunk.get("startup_buffer_frames", 0) or 0)
            expected_frames = int(first_chunk.get("expected_frame_count", 0) or 0)
            if gate_frames > 0 and expected_frames > 0:
                self.summary_label.setText(
                    self.summary_label.text()
                    + f" <span style='color:#9fdcff;'>Chunk 1 split: startup {gate_frames}/{expected_frames} frames.</span>"
                )

    def value(self):
        return int(self._value)

    def setValue(self, value):
        bounded = max(self._minimum, min(self._maximum, int(value)))
        changed = bounded != self._value
        self._value = bounded
        self.line_edit.setText(str(bounded))
        if changed and not self._suppress_signal:
            self.valueChanged.emit(self._value)

    def stepBy(self, amount):
        self.setValue(self._value + int(amount))

    def _commit_text(self):
        text = (self.line_edit.text() or "").replace(",", "").strip()
        try:
            value = int(text)
        except Exception:
            value = self._value
        self.setValue(value)


class QtInputDialog(QtWidgets.QDialog):
    def __init__(self, title, label, parent=None, default_text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(320, 120)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(label))
        self.line_edit = QtWidgets.QLineEdit()
        self.line_edit.setText(str(default_text or ""))
        layout.addWidget(self.line_edit)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def get_text(title, label, parent=None, default_text=""):
        dialog = QtInputDialog(title, label, parent, default_text=default_text)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            return dialog.line_edit.text().strip()
        return None


class HandDoctorDialog(QtWidgets.QDialog):
    HAND_KEYS = (
        ("Fingers", ("finger_x", "finger_y", "finger_z")),
        ("Thumb", ("thumb_x", "thumb_y", "thumb_z")),
    )

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.axis_controls = {}
        self.setWindowTitle("Hand Rotation Doctor")
        self.resize(420, 540)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setStyleSheet(
            """
            QDialog { background: #11161d; color: #e5e9f0; }
            QLabel { color: #e5e9f0; }
            QCheckBox { color: #f2f5f9; spacing: 8px; }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #4a5d73;
                background: #0f141b;
            }
            QCheckBox::indicator:checked {
                background: #2c7be5;
                border-color: #58a6ff;
            }
            QGroupBox {
                border: 1px solid #283342;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: 600;
                color: #d8dee9;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background: #223247;
                border: 1px solid #324b69;
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: 600;
                color: #f2f5f9;
            }
            QPushButton:hover { background: #29405b; }
            QSlider::groove:horizontal {
                border: 1px solid #273342;
                height: 6px;
                background: #0f141b;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #58a6ff;
                border: 1px solid #8cc2ff;
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            """
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.debug_toggle = QtWidgets.QCheckBox("Activate Debug Override")
        self.debug_toggle.setChecked(bool(engine.HAND_DEBUG.get("active", False)))
        self.debug_toggle.toggled.connect(self._on_toggle_debug)
        layout.addWidget(self.debug_toggle)

        preset_row = QtWidgets.QHBoxLayout()
        preset_label = QtWidgets.QLabel("Load preset to edit:")
        preset_label.setStyleSheet("font-weight: 600; color: #d8dee9;")
        preset_row.addWidget(preset_label)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        preset_buttons = QtWidgets.QHBoxLayout()
        relaxed_button = QtWidgets.QPushButton("Edit Relaxed")
        relaxed_button.clicked.connect(lambda: self.load_values("relaxed"))
        preset_buttons.addWidget(relaxed_button)
        fist_button = QtWidgets.QPushButton("Edit Fist")
        fist_button.clicked.connect(lambda: self.load_values("fist"))
        preset_buttons.addWidget(fist_button)
        layout.addLayout(preset_buttons)

        for section_title, keys in self.HAND_KEYS:
            section = QtWidgets.QGroupBox(section_title)
            section_layout = QtWidgets.QFormLayout(section)
            section_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
            section_layout.setFormAlignment(QtCore.Qt.AlignTop)
            section_layout.setHorizontalSpacing(10)
            section_layout.setVerticalSpacing(8)
            for key in keys:
                row = self._create_axis_row(key)
                section_layout.addRow(key.replace("_", " ").title(), row)
            layout.addWidget(section)

        button_row = QtWidgets.QHBoxLayout()
        self.relaxed_save_button = QtWidgets.QPushButton("Set Relaxed")
        self.relaxed_save_button.clicked.connect(lambda: self.save_as("relaxed"))
        button_row.addWidget(self.relaxed_save_button)

        self.fist_save_button = QtWidgets.QPushButton("Set Fist")
        self.fist_save_button.clicked.connect(lambda: self.save_as("fist"))
        button_row.addWidget(self.fist_save_button)
        layout.addLayout(button_row)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch(1)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self.refresh_from_debug_state()

    def _create_axis_row(self, key):
        row_widget = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(-1800, 1800)
        slider.setSingleStep(1)
        slider.setPageStep(100)
        value_label = QtWidgets.QLabel("0.0")
        value_label.setMinimumWidth(48)
        value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        value_label.setStyleSheet("color: #9fb3c8;")

        def on_value_changed(raw_value):
            value = raw_value / 10.0
            engine.HAND_DEBUG[key] = value
            value_label.setText(f"{value:.1f}")

        slider.valueChanged.connect(on_value_changed)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(value_label)
        self.axis_controls[key] = (slider, value_label)
        return row_widget

    def _on_toggle_debug(self, checked):
        engine.HAND_DEBUG["active"] = bool(checked)
        print(f"[QtGUI] Hand Debug Mode: {engine.HAND_DEBUG['active']}")

    def refresh_from_debug_state(self):
        for key, (slider, label) in self.axis_controls.items():
            value = float(engine.HAND_DEBUG.get(key, 0.0))
            slider.blockSignals(True)
            slider.setValue(int(round(value * 10.0)))
            slider.blockSignals(False)
            label.setText(f"{value:.1f}")

    def load_values(self, target_key):
        data = engine.HAND_CALIBRATION.get(target_key)
        if not data:
            print(f"[QtGUI] No calibration data for {target_key}")
            return
        print(f"[QtGUI] Loading '{target_key}' for editing...")
        engine.HAND_DEBUG.update(data)
        engine.HAND_DEBUG["active"] = True
        self.debug_toggle.setChecked(True)
        self.refresh_from_debug_state()

    def save_as(self, target_key):
        engine.HAND_CALIBRATION[target_key] = {
            "finger_x": float(engine.HAND_DEBUG["finger_x"]),
            "finger_y": float(engine.HAND_DEBUG["finger_y"]),
            "finger_z": float(engine.HAND_DEBUG["finger_z"]),
            "thumb_x": float(engine.HAND_DEBUG["thumb_x"]),
            "thumb_y": float(engine.HAND_DEBUG["thumb_y"]),
            "thumb_z": float(engine.HAND_DEBUG["thumb_z"]),
        }
        print(f"[QtGUI] Saved hand calibration for {target_key}")
        self.owner.save_current_body()
        if target_key == "relaxed":
            button = self.relaxed_save_button
            default_text = "Set Relaxed"
        else:
            button = self.fist_save_button
            default_text = "Set Fist"
        button.setText(f"{default_text} Saved!")
        QtCore.QTimer.singleShot(1800, lambda b=button, t=default_text: b.setText(t))


class QtMuseTalkPreviewPanel(QtWidgets.QWidget):
    focusModeRequested = QtCore.Signal()
    showInterfaceRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_layout = QtWidgets.QVBoxLayout(self)
        self._root_layout.setContentsMargins(10, 10, 10, 10)
        self._root_layout.setSpacing(8)
        self.focus_mode_active = False

        self.preview_label = QtWidgets.QLabel("MuseTalk preview idle")
        self.preview_label.setStyleSheet("font-weight: 600; color: #d8dee9;")
        self.show_interface_button = QtWidgets.QPushButton("Show Interface")
        self.show_interface_button.clicked.connect(self.showInterfaceRequested.emit)
        self.focus_mode_button = QtWidgets.QPushButton("Avatar Focus")
        self.focus_mode_button.clicked.connect(self.focusModeRequested.emit)
        self.reset_zoom_button = QtWidgets.QPushButton("Reset Zoom")
        self.reset_zoom_button.clicked.connect(self.reset_zoom)
        top_row = QtWidgets.QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        top_row.addWidget(self.preview_label, 1)
        top_row.addWidget(self.reset_zoom_button, 0)
        top_row.addWidget(self.show_interface_button, 0)
        top_row.addWidget(self.focus_mode_button, 0)
        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.image_label.setMinimumSize(0, 0)
        self.image_label.setStyleSheet("background: transparent; border: 0;")
        self.image_scroll = AltWheelZoomScrollArea()
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(QtCore.Qt.AlignCenter)
        self.image_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.image_scroll.setStyleSheet("QScrollArea { background: #0f141b; border: 1px solid #273342; border-radius: 10px; }")
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.zoomRequested.connect(self._handle_scroll_zoom_request)
        self._root_layout.addLayout(top_row)
        self._root_layout.addWidget(self.image_scroll, 1)

        self.current_sync_time = 0.0
        self.frame_paths = []
        self.frame_dir = ""
        self.current_frame_index = -1
        self.current_frame_path = None
        self.current_pixmap = None
        self.current_qimage = None
        self.last_avatar_id = None
        self.loop_fade_active = False
        self.loop_fade_from_image = None
        self.loop_fade_started_at = 0.0
        self.loop_fade_lock_until = 0.0
        self.loop_fade_duration_seconds = float(max(0, int(RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS))) / 1000.0
        self.loop_fade_timer = QtCore.QTimer(self)
        self.loop_fade_timer.setInterval(16)
        self.loop_fade_timer.timeout.connect(self._on_loop_fade_timer_tick)
        self.fps = 24
        self.duration_seconds = 0.0
        self.expected_frame_count = 0
        self.trim_start_frames = 0
        self.source_indices = []
        self.chunk_started_at = 0.0
        self.next_frame_dir_scan_at = 0.0
        self.last_chunk_id = None
        self.last_start_index = 0
        self.last_feed_seq = 0
        self.last_presented_source_index = None
        self.last_presented_chunk_id = None
        self.last_presented_at = 0.0
        self.last_slow_render_log_at = 0.0
        self.pending_handoff = None
        self.last_published_at = 0.0
        self.last_audio_started_at = 0.0
        self.last_is_first_reply_chunk = False
        self.static_preview_override = False
        self.static_preview_release_sync_time = None
        self.static_preview_resume_chunk_id = None
        self.debug_mask_editor_enabled = False
        self.debug_mask_drawing = False
        self.debug_mask_draw_value = 255
        self.debug_mask_brush_radius = 12
        self.debug_mask_brush_feather = 6
        self.debug_mask_base_frame = None
        self.debug_mask_full_mask = None
        self.debug_mask_bbox = None
        self.debug_mask_crop_box = None
        self.debug_mask_modified_path = None
        self.debug_mask_stroke_base_mask = None
        self.debug_mask_stroke_accumulator = None
        self.debug_mask_stroke_add_mask = True
        self.preview_zoom_factor = 1.0
        self.preloaded_frame_images = OrderedDict()
        self.preload_generation = 0
        self.preload_target_size = None
        self.preload_frontier = -1
        self.preload_lock = threading.Lock()
        self.preload_requests = queue.Queue(maxsize=256)
        self.preload_enqueued = set()
        self.preload_worker_thread = threading.Thread(target=self._preload_worker, daemon=True)
        self.preload_worker_thread.start()

        self.image_label.installEventFilter(self)
        self.image_scroll.installEventFilter(self)
        self.image_scroll.viewport().installEventFilter(self)

        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.poll_state)
        self.poll_timer.start(16)

    def set_focus_mode(self, enabled):
        self.focus_mode_active = bool(enabled)
        self.focus_mode_button.setText("Exit Avatar Focus" if self.focus_mode_active else "Avatar Focus")
        self.preview_label.setVisible(not self.focus_mode_active)
        if self.focus_mode_active:
            self._root_layout.setContentsMargins(4, 4, 4, 4)
            self.image_scroll.setStyleSheet("QScrollArea { background: #05070a; border: 0; border-radius: 0; }")
        else:
            self._root_layout.setContentsMargins(10, 10, 10, 10)
            self.image_scroll.setStyleSheet("QScrollArea { background: #0f141b; border: 1px solid #273342; border-radius: 10px; }")
        self._refresh_displayed_pixmap()
        return True

    def _publish_preview_position(self):
        state = getattr(shared_state, "current_musetalk_frame_data", None)
        if not isinstance(state, dict):
            return
        state["preview_chunk_id"] = self.last_chunk_id
        state["preview_frame_index"] = self.current_frame_index
        state["preview_source_index"] = self._source_index_for_frame(self.current_frame_index)
        with self.preload_lock:
            state["preview_cache_entries"] = len(self.preloaded_frame_images)
            state["preview_preload_pending"] = len(self.preload_enqueued)

    def eventFilter(self, watched, event):
        if watched is self.image_label or watched is self.image_scroll or watched is self.image_scroll.viewport():
            if event.type() == QtCore.QEvent.Resize:
                self._refresh_displayed_pixmap()
            elif watched is self.image_label and self.debug_mask_editor_enabled:
                if event.type() == QtCore.QEvent.MouseButtonPress:
                    button = event.button()
                    if button in (QtCore.Qt.LeftButton, QtCore.Qt.RightButton):
                        image_point = self._map_label_pos_to_image(event.position())
                        if image_point is not None:
                            self.debug_mask_drawing = True
                            self.debug_mask_draw_value = 255 if button == QtCore.Qt.LeftButton else 0
                            self.debug_mask_stroke_add_mask = self.debug_mask_draw_value > 0
                            self.debug_mask_stroke_base_mask = self.debug_mask_full_mask.copy() if self.debug_mask_full_mask is not None else None
                            self.debug_mask_stroke_accumulator = np.zeros_like(self.debug_mask_full_mask, dtype=np.uint8) if self.debug_mask_full_mask is not None else None
                            self._apply_debug_mask_brush(image_point[0], image_point[1], add_mask=self.debug_mask_stroke_add_mask)
                            return True
                elif event.type() == QtCore.QEvent.MouseMove and self.debug_mask_drawing:
                    image_point = self._map_label_pos_to_image(event.position())
                    if image_point is not None:
                        buttons = event.buttons()
                        add_mask = bool(buttons & QtCore.Qt.LeftButton) or not bool(buttons & QtCore.Qt.RightButton and not buttons & QtCore.Qt.LeftButton)
                        if buttons & (QtCore.Qt.LeftButton | QtCore.Qt.RightButton):
                            if buttons & QtCore.Qt.RightButton and not buttons & QtCore.Qt.LeftButton:
                                add_mask = False
                            self._apply_debug_mask_brush(image_point[0], image_point[1], add_mask=add_mask)
                            return True
                elif event.type() == QtCore.QEvent.MouseButtonRelease and self.debug_mask_drawing:
                    self.debug_mask_drawing = False
                    self.debug_mask_stroke_base_mask = None
                    self.debug_mask_stroke_accumulator = None
                    return True
        return super().eventFilter(watched, event)

    def _map_label_pos_to_image(self, pos):
        if self.current_pixmap is None or self.current_pixmap.isNull():
            return None
        display_pixmap = self.image_label.pixmap()
        if display_pixmap is None or display_pixmap.isNull():
            return None
        label_rect = self.image_label.contentsRect()
        display_size = display_pixmap.size()
        if display_size.width() <= 0 or display_size.height() <= 0:
            return None
        offset_x = label_rect.x() + max(0, (label_rect.width() - display_size.width()) // 2)
        offset_y = label_rect.y() + max(0, (label_rect.height() - display_size.height()) // 2)
        local_x = float(pos.x()) - float(offset_x)
        local_y = float(pos.y()) - float(offset_y)
        if local_x < 0 or local_y < 0 or local_x >= display_size.width() or local_y >= display_size.height():
            return None
        scale_x = float(self.current_pixmap.width()) / float(display_size.width())
        scale_y = float(self.current_pixmap.height()) / float(display_size.height())
        image_x = int(max(0, min(self.current_pixmap.width() - 1, round(local_x * scale_x))))
        image_y = int(max(0, min(self.current_pixmap.height() - 1, round(local_y * scale_y))))
        return image_x, image_y

    def _update_debug_mask_cursor(self):
        if not self.debug_mask_editor_enabled:
            self.image_label.setCursor(QtCore.Qt.ArrowCursor)
            return
        display_pixmap = self.image_label.pixmap()
        scale_x = 1.0
        if (
            display_pixmap is not None
            and not display_pixmap.isNull()
            and self.current_pixmap is not None
            and not self.current_pixmap.isNull()
            and self.current_pixmap.width() > 0
        ):
            scale_x = float(display_pixmap.width()) / float(self.current_pixmap.width())
        outer_radius = max(1.0, float(self.debug_mask_brush_radius) * scale_x)
        feather_width = max(0.0, float(self.debug_mask_brush_feather) * scale_x)
        inner_radius = max(0.0, outer_radius - feather_width)
        cursor_radius = max(6.0, outer_radius)
        size = max(24, int(round(cursor_radius * 2 + 10)))
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        center = QtCore.QPointF(size / 2.0, size / 2.0)
        if feather_width > 0.5 and inner_radius > 0.5:
            feather_pen = QtGui.QPen(QtGui.QColor(255, 190, 70, 180), max(1.0, min(feather_width, 4.0)))
            painter.setPen(feather_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            feather_mid_radius = inner_radius + feather_width / 2.0
            painter.drawEllipse(center, feather_mid_radius, feather_mid_radius)
        if inner_radius > 0.5:
            inner_pen = QtGui.QPen(QtGui.QColor(255, 245, 170), 1.2)
            painter.setPen(inner_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(center, inner_radius, inner_radius)
        outer_pen = QtGui.QPen(QtGui.QColor(255, 225, 120), 1.6)
        painter.setPen(outer_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(center, outer_radius, outer_radius)
        painter.end()
        self.image_label.setCursor(QtGui.QCursor(pixmap, int(size / 2), int(size / 2)))

    def _set_debug_mask_editor_enabled(self, enabled):
        self.debug_mask_editor_enabled = bool(enabled and self.debug_mask_base_frame is not None and self.debug_mask_full_mask is not None)
        self.debug_mask_drawing = False
        self.debug_mask_stroke_base_mask = None
        self.debug_mask_stroke_accumulator = None
        self._update_debug_mask_cursor()

    def set_debug_mask_brush(self, *, radius=None, feather=None):
        if radius is not None:
            self.debug_mask_brush_radius = max(1, int(radius))
        if feather is not None:
            self.debug_mask_brush_feather = max(0, int(feather))
        self._update_debug_mask_cursor()
        return True

    def _handle_scroll_zoom_request(self, factor_delta, anchor_x, anchor_y):
        self.adjust_zoom(factor_delta, QtCore.QPointF(float(anchor_x), float(anchor_y)))

    def set_zoom_factor(self, zoom_factor, anchor_pos=None):
        new_zoom = max(0.25, min(8.0, float(zoom_factor or 1.0)))
        old_display = self.image_label.pixmap()
        hbar = self.image_scroll.horizontalScrollBar() if hasattr(self, "image_scroll") else None
        vbar = self.image_scroll.verticalScrollBar() if hasattr(self, "image_scroll") else None
        anchor_ratio_x = None
        anchor_ratio_y = None
        anchor_point = None
        if anchor_pos is not None and old_display is not None and not old_display.isNull() and hbar is not None and vbar is not None:
            try:
                anchor_point = QtCore.QPointF(anchor_pos)
            except Exception:
                anchor_point = QtCore.QPointF(float(anchor_pos.x()), float(anchor_pos.y()))
            old_width = max(1, old_display.width())
            old_height = max(1, old_display.height())
            anchor_ratio_x = (hbar.value() + anchor_point.x()) / float(old_width)
            anchor_ratio_y = (vbar.value() + anchor_point.y()) / float(old_height)
        self.preview_zoom_factor = new_zoom
        self._refresh_displayed_pixmap()
        new_display = self.image_label.pixmap()
        if anchor_point is not None and new_display is not None and not new_display.isNull() and hbar is not None and vbar is not None:
            new_width = max(1, new_display.width())
            new_height = max(1, new_display.height())
            new_h = int(round(anchor_ratio_x * new_width - anchor_point.x()))
            new_v = int(round(anchor_ratio_y * new_height - anchor_point.y()))
            hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), new_h)))
            vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), new_v)))
        return True

    def adjust_zoom(self, factor_delta, anchor_pos=None):
        factor_delta = float(factor_delta or 1.0)
        if factor_delta <= 0:
            return False
        return self.set_zoom_factor(self.preview_zoom_factor * factor_delta, anchor_pos=anchor_pos)

    def reset_zoom(self):
        self.preview_zoom_factor = 1.0
        self._refresh_displayed_pixmap()
        return True

    def clear_debug_mask_editor(self):
        self.debug_mask_base_frame = None
        self.debug_mask_full_mask = None
        self.debug_mask_bbox = None
        self.debug_mask_crop_box = None
        self.debug_mask_modified_path = None
        self.debug_mask_stroke_base_mask = None
        self.debug_mask_stroke_accumulator = None
        self._set_debug_mask_editor_enabled(False)

    def configure_debug_mask_editor(self, *, base_frame_path, mask_frame_path, bbox, crop_box, modified_mask_path=None):
        base_frame_path = str(base_frame_path or "").strip()
        mask_frame_path = str(mask_frame_path or "").strip()
        modified_mask_path = str(modified_mask_path or "").strip()
        if not base_frame_path or not mask_frame_path or not os.path.isfile(base_frame_path) or not os.path.isfile(mask_frame_path):
            self.clear_debug_mask_editor()
            return False
        base_frame = cv2.imread(base_frame_path)
        mask_path = modified_mask_path if modified_mask_path and os.path.isfile(modified_mask_path) else mask_frame_path
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        if base_frame is None or mask is None:
            self.clear_debug_mask_editor()
            return False
        try:
            crop_values = [int(v) for v in list(crop_box or [])[:4]]
            bbox_values = [int(v) for v in list(bbox or [])[:4]]
        except Exception:
            self.clear_debug_mask_editor()
            return False
        if len(crop_values) != 4 or len(bbox_values) != 4:
            self.clear_debug_mask_editor()
            return False
        full_mask = np.zeros(base_frame.shape[:2], dtype=np.uint8)
        x_s, y_s, x_e, y_e = crop_values
        dest_x1 = max(0, x_s)
        dest_y1 = max(0, y_s)
        dest_x2 = min(base_frame.shape[1], x_e)
        dest_y2 = min(base_frame.shape[0], y_e)
        if dest_x2 > dest_x1 and dest_y2 > dest_y1:
            src_x1 = dest_x1 - x_s
            src_y1 = dest_y1 - y_s
            src_x2 = min(mask.shape[1], src_x1 + (dest_x2 - dest_x1))
            src_y2 = min(mask.shape[0], src_y1 + (dest_y2 - dest_y1))
            dest_x2 = dest_x1 + (src_x2 - src_x1)
            dest_y2 = dest_y1 + (src_y2 - src_y1)
            if src_x2 > src_x1 and src_y2 > src_y1 and dest_x2 > dest_x1 and dest_y2 > dest_y1:
                full_mask[dest_y1:dest_y2, dest_x1:dest_x2] = mask[src_y1:src_y2, src_x1:src_x2]
        self.debug_mask_base_frame = base_frame
        self.debug_mask_full_mask = full_mask
        self.debug_mask_bbox = bbox_values
        self.debug_mask_crop_box = crop_values
        self.debug_mask_modified_path = modified_mask_path or str(Path(mask_frame_path).with_name('debug_mask_modified.png'))
        self._set_debug_mask_editor_enabled(True)
        self._refresh_debug_mask_overlay_preview()
        return True

    def _save_debug_mask_modified(self):
        if self.debug_mask_full_mask is None or not self.debug_mask_modified_path or not self.debug_mask_crop_box:
            return False
        x_s, y_s, x_e, y_e = [int(v) for v in self.debug_mask_crop_box]
        crop_width = max(1, x_e - x_s)
        crop_height = max(1, y_e - y_s)
        crop_mask = np.zeros((crop_height, crop_width), dtype=np.uint8)
        dest_x1 = max(0, x_s)
        dest_y1 = max(0, y_s)
        dest_x2 = min(self.debug_mask_full_mask.shape[1], x_e)
        dest_y2 = min(self.debug_mask_full_mask.shape[0], y_e)
        if dest_x2 > dest_x1 and dest_y2 > dest_y1:
            src_x1 = dest_x1 - x_s
            src_y1 = dest_y1 - y_s
            src_x2 = src_x1 + (dest_x2 - dest_x1)
            src_y2 = src_y1 + (dest_y2 - dest_y1)
            crop_mask[src_y1:src_y2, src_x1:src_x2] = self.debug_mask_full_mask[dest_y1:dest_y2, dest_x1:dest_x2]
        Path(self.debug_mask_modified_path).parent.mkdir(parents=True, exist_ok=True)
        return bool(cv2.imwrite(self.debug_mask_modified_path, crop_mask))

    def _refresh_debug_mask_overlay_preview(self):
        if self.debug_mask_base_frame is None or self.debug_mask_full_mask is None:
            return False
        mask_overlay = self.debug_mask_base_frame.copy()
        alpha = (self.debug_mask_full_mask.astype(np.float32) / 255.0)[:, :, None] * 0.75
        overlay_color = np.zeros_like(mask_overlay)
        overlay_color[:, :, 2] = 255
        overlay_color[:, :, 1] = 40
        mask_overlay = (mask_overlay.astype(np.float32) * (1.0 - alpha) + overlay_color.astype(np.float32) * alpha).clip(0, 255).astype(np.uint8)
        if self.debug_mask_bbox and len(self.debug_mask_bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in self.debug_mask_bbox]
            cv2.rectangle(mask_overlay, (x1, y1), (x2, y2), (0, 220, 255), 3)
        cv2.putText(mask_overlay, 'MASK OVERLAY (EDIT)', (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 255), 2, cv2.LINE_AA)
        rgb = cv2.cvtColor(mask_overlay, cv2.COLOR_BGR2RGB)
        qimage = QtGui.QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QtGui.QImage.Format_RGB888).copy()
        self.current_pixmap = QtGui.QPixmap.fromImage(qimage)
        self._refresh_displayed_pixmap()
        self.preview_label.setText('MuseTalk debug mask overlay (editable)')
        return True

    def _apply_debug_mask_brush(self, image_x, image_y, *, add_mask):
        if self.debug_mask_full_mask is None or not self.debug_mask_bbox:
            return False
        x1, y1, x2, y2 = [int(v) for v in self.debug_mask_bbox]
        if image_x < x1 or image_x > x2 or image_y < y1 or image_y > y2:
            return False
        radius = max(1, int(self.debug_mask_brush_radius))
        feather = max(0, int(self.debug_mask_brush_feather))
        outer_radius = float(radius)
        inner_radius = max(0.0, float(radius - feather))
        x_start = max(0, int(image_x - radius))
        y_start = max(0, int(image_y - radius))
        x_end = min(self.debug_mask_full_mask.shape[1], int(image_x + radius + 1))
        y_end = min(self.debug_mask_full_mask.shape[0], int(image_y + radius + 1))
        brush = np.zeros_like(self.debug_mask_full_mask, dtype=np.uint8)
        if x_end <= x_start or y_end <= y_start:
            return False
        yy, xx = np.ogrid[y_start:y_end, x_start:x_end]
        distances = np.sqrt((xx - float(image_x)) ** 2 + (yy - float(image_y)) ** 2)
        alpha = np.zeros((y_end - y_start, x_end - x_start), dtype=np.float32)
        alpha[distances <= inner_radius] = 1.0
        if outer_radius > inner_radius:
            ring = (distances > inner_radius) & (distances <= outer_radius)
            alpha[ring] = ((outer_radius - distances[ring]) / max(0.001, outer_radius - inner_radius)).astype(np.float32)
        elif inner_radius <= 0:
            alpha[distances <= outer_radius] = 1.0
        brush_patch = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
        brush[y_start:y_end, x_start:x_end] = brush_patch
        brush[:max(0, y1), :] = 0
        brush[min(self.debug_mask_full_mask.shape[0], y2 + 1):, :] = 0
        brush[:, :max(0, x1)] = 0
        brush[:, min(self.debug_mask_full_mask.shape[1], x2 + 1):] = 0
        if self.debug_mask_stroke_base_mask is None or self.debug_mask_stroke_accumulator is None:
            self.debug_mask_stroke_base_mask = self.debug_mask_full_mask.copy()
            self.debug_mask_stroke_accumulator = np.zeros_like(self.debug_mask_full_mask, dtype=np.uint8)
            self.debug_mask_stroke_add_mask = bool(add_mask)
        self.debug_mask_stroke_accumulator = np.maximum(self.debug_mask_stroke_accumulator, brush)
        if self.debug_mask_stroke_add_mask:
            self.debug_mask_full_mask = np.maximum(self.debug_mask_stroke_base_mask, self.debug_mask_stroke_accumulator)
        else:
            base = self.debug_mask_stroke_base_mask.astype(np.float32)
            alpha_mask = self.debug_mask_stroke_accumulator.astype(np.float32) / 255.0
            self.debug_mask_full_mask = np.clip(base * (1.0 - alpha_mask), 0, 255).astype(np.uint8)
        self._save_debug_mask_modified()
        self._refresh_debug_mask_overlay_preview()
        return True

    def reset_preview(self):
        self.current_sync_time = 0.0
        self.frame_paths = []
        self.frame_dir = ""
        self.current_frame_index = -1
        self.current_frame_path = None
        self.current_pixmap = None
        self.current_qimage = None
        self.last_avatar_id = None
        self._stop_loop_fade()
        self.duration_seconds = 0.0
        self.expected_frame_count = 0
        self.trim_start_frames = 0
        self.source_indices = []
        self.chunk_started_at = 0.0
        self.next_frame_dir_scan_at = 0.0
        self.last_chunk_id = None
        self.last_start_index = 0
        self.last_feed_seq = 0
        self.last_presented_source_index = None
        self.last_presented_chunk_id = None
        self.last_presented_at = 0.0
        self.last_slow_render_log_at = 0.0
        self.pending_handoff = None
        self.last_published_at = 0.0
        self.last_audio_started_at = 0.0
        self.last_is_first_reply_chunk = False
        self.static_preview_override = False
        self.static_preview_release_sync_time = None
        self.static_preview_resume_chunk_id = None
        self._invalidate_cache_for_resize()
        self.image_label.clear()
        self.preview_label.setText("MuseTalk preview idle")
        state = getattr(shared_state, "current_musetalk_frame_data", None)
        if isinstance(state, dict):
            state["preview_chunk_id"] = None
            state["preview_frame_index"] = -1
            state["preview_source_index"] = None

    def _invalidate_cache_for_resize(self):
        self.preload_generation += 1
        self.preload_target_size = None
        self.preload_frontier = -1
        with self.preload_lock:
            self.preloaded_frame_images = OrderedDict()
            self.preload_enqueued = set()

    def _get_target_size(self):
        return None

    def _scaled_pixmap_for_label(self, pixmap):
        if pixmap is None or pixmap.isNull():
            return pixmap
        target_size = self.image_scroll.viewport().contentsRect().size() if hasattr(self, "image_scroll") else self.image_label.contentsRect().size()
        if not target_size.isValid() or target_size.width() <= 1 or target_size.height() <= 1:
            return pixmap
        fit_size = pixmap.size().scaled(target_size, QtCore.Qt.KeepAspectRatio)
        if fit_size.width() <= 0 or fit_size.height() <= 0:
            return pixmap
        zoom_factor = max(0.25, float(getattr(self, "preview_zoom_factor", 1.0) or 1.0))
        if abs(zoom_factor - 1.0) < 0.001:
            scaled_size = fit_size
        else:
            scaled_size = QtCore.QSize(
                max(1, int(round(fit_size.width() * zoom_factor))),
                max(1, int(round(fit_size.height() * zoom_factor))),
            )
        return pixmap.scaled(
            scaled_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )

    def _refresh_displayed_pixmap(self):
        if self.current_pixmap is None or self.current_pixmap.isNull():
            return
        display_pixmap = self._scaled_pixmap_for_label(self.current_pixmap)
        self.image_label.setPixmap(display_pixmap)
        self.image_label.resize(display_pixmap.size())
        if self.debug_mask_editor_enabled:
            self._update_debug_mask_cursor()

    def show_static_frame(self, frame_path, status_text=None):
        frame_path = str(frame_path or "").strip()
        if not frame_path or not os.path.isfile(frame_path):
            return False
        image = QtGui.QImage(frame_path)
        if image.isNull():
            return False
        self.current_sync_time = 0.0
        self.frame_paths = [frame_path]
        self.frame_dir = str(Path(frame_path).parent)
        self.current_frame_index = 0
        self.current_frame_path = frame_path
        self.current_qimage = image.copy()
        self.current_pixmap = QtGui.QPixmap.fromImage(self.current_qimage)
        self._stop_loop_fade()
        self.expected_frame_count = 1
        self.duration_seconds = 0.0
        self.trim_start_frames = 0
        self.source_indices = [0]
        self.last_chunk_id = Path(frame_path).parent.name
        self.last_start_index = 0
        self.pending_handoff = None
        self.last_presented_chunk_id = self.last_chunk_id
        self.last_presented_source_index = 0
        state = getattr(shared_state, "current_musetalk_frame_data", None)
        current_sync_time = None
        if isinstance(state, dict):
            try:
                current_sync_time = float(state.get("sync_time", 0.0) or 0.0)
            except Exception:
                current_sync_time = 0.0
            self.static_preview_resume_chunk_id = state.get("chunk_id")
        else:
            self.static_preview_resume_chunk_id = None
        self.static_preview_override = True
        self.static_preview_release_sync_time = current_sync_time
        self._refresh_displayed_pixmap()
        if status_text:
            self.preview_label.setText(str(status_text))
        else:
            self.preview_label.setText("MuseTalk first-frame test")
        return True

    def _source_index_for_frame(self, frame_index):
        if 0 <= frame_index < len(self.source_indices):
            try:
                return int(self.source_indices[frame_index])
            except Exception:
                pass
        return self.last_start_index + max(frame_index, 0)

    def _build_cached_preview_image(self, frame_path, _target_size):
        with Image.open(frame_path) as source_image:
            image = source_image.copy()
            qimage = QtGui.QImage(
                image.tobytes("raw", "RGBA") if image.mode == "RGBA" else image.convert("RGBA").tobytes("raw", "RGBA"),
                image.size[0],
                image.size[1],
                QtGui.QImage.Format_RGBA8888,
            ).copy()
        return qimage

    def _get_cached_preview_image(self, frame_path):
        with self.preload_lock:
            cached = self.preloaded_frame_images.get(frame_path)
            if cached is not None:
                self.preloaded_frame_images.move_to_end(frame_path)
                return cached
        return None

    def _store_cached_preview_image(self, frame_path, image):
        with self.preload_lock:
            self.preloaded_frame_images[frame_path] = image
            self.preloaded_frame_images.move_to_end(frame_path)
            while len(self.preloaded_frame_images) > QT_PREVIEW_CACHE_LIMIT:
                self.preloaded_frame_images.popitem(last=False)

    def _start_frame_preload(self, start_index=0, count=12):
        if not self.frame_paths or not self.isVisible():
            return
        target_size = self._get_target_size()
        if target_size != self.preload_target_size:
            self._invalidate_cache_for_resize()
            self.preload_target_size = target_size
        generation = self.preload_generation
        if start_index + count <= self.preload_frontier:
            return
        self.preload_frontier = max(self.preload_frontier, start_index + count)
        preload_paths = list(self.frame_paths[start_index:start_index + count])
        with self.preload_lock:
            for frame_path in preload_paths:
                key = (generation, frame_path)
                if key in self.preload_enqueued:
                    continue
                try:
                    self.preload_requests.put_nowait(key)
                    self.preload_enqueued.add(key)
                except queue.Full:
                    break

    def _preload_worker(self):
        while True:
            generation, frame_path = self.preload_requests.get()
            try:
                if generation != self.preload_generation:
                    continue
                if not frame_path or not os.path.exists(frame_path):
                    continue
                if self._get_cached_preview_image(frame_path) is not None:
                    continue
                try:
                    image = self._build_cached_preview_image(frame_path, self.preload_target_size)
                except Exception:
                    continue
                self._store_cached_preview_image(frame_path, image)
            finally:
                with self.preload_lock:
                    self.preload_enqueued.discard((generation, frame_path))
                self.preload_requests.task_done()

    def _refresh_frame_paths_from_dir(self):
        if not self.frame_dir or not os.path.isdir(self.frame_dir):
            return
        scanned = sorted(
            os.path.join(self.frame_dir, name)
            for name in os.listdir(self.frame_dir)
            if name.lower().endswith(".png")
        )
        if self.trim_start_frames > 0 and scanned:
            trimmed = scanned[min(self.trim_start_frames, len(scanned) - 1):]
            if trimmed:
                scanned = trimmed
        self.frame_paths = scanned
        if len(self.frame_paths) > self.expected_frame_count:
            self.expected_frame_count = len(self.frame_paths)

    def _ensure_preview_argb32(self, image):
        if image is None or image.isNull():
            return None
        if image.format() == QtGui.QImage.Format_ARGB32:
            return image
        return image.convertToFormat(QtGui.QImage.Format_ARGB32)

    def _compose_loop_fade_image(self, alpha):
        source = self._ensure_preview_argb32(self.loop_fade_from_image)
        target = self._ensure_preview_argb32(self.current_qimage)
        if source is None or target is None:
            return None
        target_size = target.size()
        if source.size() != target_size:
            source = source.scaled(target_size, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
        alpha = max(0.0, min(float(alpha), 1.0))
        composed = QtGui.QImage(target_size, QtGui.QImage.Format_ARGB32)
        composed.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(composed)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.setOpacity(max(0.0, 1.0 - alpha))
        painter.drawImage(0, 0, source)
        painter.setOpacity(alpha)
        painter.drawImage(0, 0, target)
        painter.end()
        return composed

    def _stop_loop_fade(self):
        self.loop_fade_active = False
        self.loop_fade_from_image = None
        self.loop_fade_lock_until = 0.0
        if hasattr(self, 'loop_fade_timer') and self.loop_fade_timer.isActive():
            self.loop_fade_timer.stop()

    def _on_loop_fade_timer_tick(self):
        if not self._update_loop_fade_display():
            self._stop_loop_fade()

    def _compute_runtime_frame_index(self, state=None, now=None):
        if not self.frame_paths or not self.chunk_started_at:
            return None
        state = state or (shared_state.current_musetalk_frame_data or {})
        now = time.time() if now is None else float(now)
        elapsed = max(0.0, now - self.chunk_started_at)
        if state.get("loop", False):
            return int(elapsed * max(self.fps, 1)) % len(self.frame_paths)
        if self.duration_seconds > 0:
            progress = min(elapsed / self.duration_seconds, 1.0)
            expected_count = max(self.expected_frame_count, len(self.frame_paths), 1)
            frame_span = max(expected_count - 1, 1)
            target_index = min(int(progress * frame_span), expected_count - 1)
            return min(target_index, len(self.frame_paths) - 1)
        return min(int(elapsed * max(self.fps, 1)), len(self.frame_paths) - 1)

    def _catch_up_preview_after_loop_fade(self):
        if self.loop_fade_active:
            return
        frame_index = self._compute_runtime_frame_index()
        if frame_index is None or frame_index == self.current_frame_index:
            return
        next_frame_path = self.frame_paths[frame_index]
        if not os.path.exists(next_frame_path):
            return
        self.current_frame_index = frame_index
        self.current_frame_path = next_frame_path
        state = shared_state.current_musetalk_frame_data or {}
        if not state.get("loop", False):
            self._start_frame_preload(
                start_index=frame_index + 1,
                count=min(
                    max(len(self.frame_paths) - (frame_index + 1), 0),
                    QT_PREVIEW_AHEAD_PRELOAD,
                ),
            )
        self.render_current_frame()

    def _update_loop_fade_display(self, *, force=False):
        if not self.loop_fade_active:
            return False
        if self.loop_fade_from_image is None or self.current_qimage is None:
            self._stop_loop_fade()
            return False
        elapsed = max(0.0, time.time() - float(self.loop_fade_started_at or 0.0))
        duration = max(0.001, float(self.loop_fade_duration_seconds or 0.001))
        alpha = 1.0 if force else min(elapsed / duration, 1.0)
        blended = self._compose_loop_fade_image(alpha)
        if blended is None:
            self._stop_loop_fade()
            return False
        self.current_pixmap = QtGui.QPixmap.fromImage(blended)
        self._refresh_displayed_pixmap()
        if alpha >= 1.0:
            self._stop_loop_fade()
            QtCore.QTimer.singleShot(0, self._catch_up_preview_after_loop_fade)
        return True

    def _start_loop_fade_if_needed(self, previous_avatar_id, next_avatar_id, state, previous_chunk_id=None):
        previous_avatar = str(previous_avatar_id or '').strip()
        next_avatar = str(next_avatar_id or '').strip()
        next_chunk_id = str((state or {}).get('chunk_id', '') or '')
        previous_chunk_id = str(previous_chunk_id or '').strip()
        is_plan_to_speech_handoff = bool(
            previous_chunk_id.startswith('first_chunk_plan:')
            and next_chunk_id
            and not next_chunk_id.startswith('first_chunk_plan:')
        )
        avatar_changed = bool(previous_avatar and next_avatar and previous_avatar != next_avatar)
        if not avatar_changed and not is_plan_to_speech_handoff:
            return False
        fade_ms = max(0, int(RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or 0))
        self.loop_fade_duration_seconds = float(fade_ms) / 1000.0
        if fade_ms <= 0:
            self.loop_fade_active = False
            self.loop_fade_from_image = None
            return False
        source_image = None
        if self.current_pixmap is not None and not self.current_pixmap.isNull():
            try:
                source_image = self.current_pixmap.toImage()
            except Exception:
                source_image = None
        if source_image is None or source_image.isNull():
            if self.current_qimage is None or self.current_qimage.isNull():
                self.loop_fade_active = False
                self.loop_fade_from_image = None
                return False
            source_image = self.current_qimage
        self.loop_fade_from_image = source_image.copy()
        self.loop_fade_started_at = time.time()
        self.loop_fade_lock_until = self.loop_fade_started_at + self.loop_fade_duration_seconds
        self.loop_fade_active = True
        if not self.loop_fade_timer.isActive():
            self.loop_fade_timer.start()
        return True

    def render_current_frame(self):
        if not self.current_frame_path or not os.path.exists(self.current_frame_path):
            return
        render_started_at = time.time()
        load_ms = 0.0
        cache_hit = False
        cached = self._get_cached_preview_image(self.current_frame_path)
        if cached is None:
            try:
                load_started_at = time.time()
                cached = self._build_cached_preview_image(self.current_frame_path, self._get_target_size())
                load_ms = (time.time() - load_started_at) * 1000.0
            except Exception:
                return
            self._store_cached_preview_image(self.current_frame_path, cached)
        else:
            cache_hit = True
        self.current_qimage = cached.copy()
        pixmap = QtGui.QPixmap.fromImage(self.current_qimage)
        if pixmap.isNull():
            return
        self.current_pixmap = pixmap
        set_started_at = time.time()
        if not self._update_loop_fade_display():
            self._refresh_displayed_pixmap()
        set_ms = (time.time() - set_started_at) * 1000.0
        render_ms = (time.time() - render_started_at) * 1000.0
        now = time.time()
        displayed_source = self._source_index_for_frame(self.current_frame_index)
        self.last_presented_source_index = displayed_source
        self.last_presented_chunk_id = self.last_chunk_id
        self.last_presented_at = now
        self._publish_preview_position()
        if self.pending_handoff and self.last_chunk_id == self.pending_handoff.get("chunk_id"):
            message = (
                f"🚪 [MuseTalkPreview] First-frame handoff: "
                f"from={self.pending_handoff.get('previous_chunk_id')} "
                f"to={self.pending_handoff.get('chunk_id')} "
                f"prev_source={self.pending_handoff.get('previous_source_index')} "
                f"next_start={self.pending_handoff.get('next_start_index')} "
                f"displayed_source={displayed_source} "
                f"present={(now - self.pending_handoff.get('armed_at', now)) * 1000.0:.1f} ms "
                f"render={render_ms:.1f} ms "
                f"load={load_ms:.1f} ms "
                f"set={set_ms:.1f} ms "
                f"cache={'hit' if cache_hit else 'miss'} "
                f"preview_cache_entries={len(self.preloaded_frame_images)} "
                f"preview_preload_pending={len(self.preload_enqueued)}"
            )
            if self.last_is_first_reply_chunk:
                if self.last_published_at:
                    message += f" publish_to_present={(now - self.last_published_at) * 1000.0:.1f} ms"
                if self.last_audio_started_at:
                    message += f" audio_to_present={(now - self.last_audio_started_at) * 1000.0:.1f} ms"
            shared_state.append_musetalk_preview_log(message)
            print(message)
            self.pending_handoff = None
        if render_ms >= 20.0 and (now - self.last_slow_render_log_at) > 0.25:
            self.last_slow_render_log_at = now
            message = (
                f"🖼️ [MuseTalkPreview] Slow frame render: {render_ms:.1f} ms "
                f"(chunk={self.last_chunk_id}, frame={self.current_frame_index}, "
                f"cache={'hit' if cache_hit else 'miss'}, load={load_ms:.1f} ms, set={set_ms:.1f} ms, "
                f"preview_cache_entries={len(self.preloaded_frame_images)}, preview_preload_pending={len(self.preload_enqueued)})"
            )
            shared_state.append_musetalk_preview_log(message)
            print(message)

    def _set_preview_status(self, state):
        status = state.get("status", "idle")
        should_loop = bool(state.get("loop", False))
        text = (state.get("text", "") or "").strip()
        chunk_id = state.get("chunk_id")
        if status == "ready":
            self.preview_label.setText(f"MuseTalk: {text[:60]}")
        elif chunk_id and str(chunk_id).startswith("first_chunk_plan:"):
            self.preview_label.setText("MuseTalk warming speech")
        elif should_loop:
            self.preview_label.setText("MuseTalk idle")
        else:
            self.preview_label.setText("MuseTalk preview idle")

    def _apply_new_state(self, state):
        previous_chunk_id = self.last_chunk_id
        previous_frame_index = self.current_frame_index
        previous_source = self.last_presented_source_index
        previous_avatar_id = self.last_avatar_id
        self.current_sync_time = float(state.get("sync_time", 0.0) or 0.0)
        self.frame_paths = list(state.get("frame_paths", []) or [])
        self.frame_dir = state.get("frame_dir", "")
        self.current_frame_index = -1
        self.current_frame_path = None
        self.fps = int(state.get("fps", 24) or 24)
        self.duration_seconds = float(state.get("duration_seconds", 0.0) or 0.0)
        self.expected_frame_count = int(state.get("expected_frame_count", 0) or len(self.frame_paths))
        self.trim_start_frames = int(state.get("trim_start_frames", 0) or 0)
        self.source_indices = list(state.get("source_indices", []) or [])
        self.chunk_started_at = self.current_sync_time
        self.next_frame_dir_scan_at = 0.0
        self.last_chunk_id = state.get("chunk_id")
        self.last_start_index = int(state.get("start_index", 0) or 0)
        self.last_published_at = float(state.get("published_at", 0.0) or 0.0)
        self.last_audio_started_at = float(state.get("audio_started_at", 0.0) or 0.0)
        self.last_is_first_reply_chunk = bool(state.get("is_first_reply_chunk", False))
        self.last_avatar_id = str(state.get("avatar_id", "") or "").strip() or None
        self._set_preview_status(state)
        if previous_chunk_id and self.last_chunk_id and previous_chunk_id != self.last_chunk_id:
            previous_source_index = previous_source
            if previous_source_index is None and previous_frame_index >= 0:
                previous_source_index = self.last_start_index + max(previous_frame_index, 0)
            message = (
                f"🧪 [MuseTalkPreview] Handoff {previous_chunk_id} -> {self.last_chunk_id}: "
                f"prev_frame={previous_frame_index}, prev_source={previous_source_index}, "
                f"next_start={self.last_start_index}, buffered={len(self.frame_paths)}, expected={self.expected_frame_count}, "
                f"preview_cache_entries={len(self.preloaded_frame_images)}, preview_preload_pending={len(self.preload_enqueued)}"
            )
            shared_state.append_musetalk_preview_log(message)
            print(message)
            self.pending_handoff = {
                "previous_chunk_id": previous_chunk_id,
                "previous_source_index": previous_source_index,
                "chunk_id": self.last_chunk_id,
                "next_start_index": self.last_start_index,
                "armed_at": time.time(),
            }

        if not self.frame_paths and self.frame_dir:
            self._refresh_frame_paths_from_dir()
        if not self.frame_paths:
            self.image_label.clear()
            return

        initial_frame_index = 0
        is_idle_to_first_plan = (
            previous_chunk_id == "idle"
            and self.last_chunk_id
            and str(self.last_chunk_id).startswith("first_chunk_plan:")
        )
        is_idle_to_speech = (
            previous_chunk_id == "idle"
            and self.last_chunk_id
            and not str(self.last_chunk_id).startswith("first_chunk_plan:")
            and not bool(state.get("loop", False))
        )
        is_first_plan_handoff = (
            previous_chunk_id
            and str(previous_chunk_id).startswith("first_chunk_plan:")
            and self.last_chunk_id
            and not str(self.last_chunk_id).startswith("first_chunk_plan:")
            and not bool(state.get("loop", False))
        )
        if is_idle_to_first_plan and self.source_indices:
            target_start = self.last_start_index
            for idx, source_index in enumerate(self.source_indices):
                try:
                    if int(source_index) >= int(target_start):
                        initial_frame_index = idx
                        break
                except Exception:
                    continue
        elif is_idle_to_speech:
            target_start = self.last_start_index
            if self.source_indices:
                for idx, source_index in enumerate(self.source_indices):
                    try:
                        if int(source_index) >= int(target_start):
                            initial_frame_index = idx
                            break
                    except Exception:
                        continue
            else:
                initial_frame_index = max(0, target_start - self.last_start_index)
                initial_frame_index = min(initial_frame_index, max(len(self.frame_paths) - 1, 0))
        elif not is_first_plan_handoff and previous_source is not None:
            for idx in range(len(self.frame_paths)):
                if self._source_index_for_frame(idx) > previous_source:
                    initial_frame_index = idx
                    break
        elif is_first_plan_handoff and self.source_indices:
            target_start = self.last_start_index
            for idx, source_index in enumerate(self.source_indices):
                try:
                    if int(source_index) >= int(target_start):
                        initial_frame_index = idx
                        break
                except Exception:
                    continue
        self.current_frame_index = initial_frame_index
        self.current_frame_path = self.frame_paths[initial_frame_index]
        self._start_loop_fade_if_needed(previous_avatar_id, self.last_avatar_id, state, previous_chunk_id=previous_chunk_id)
        self._start_frame_preload(
            start_index=initial_frame_index,
            count=min(max(len(self.frame_paths) - initial_frame_index, 1), QT_PREVIEW_INITIAL_PRELOAD),
        )
        self.render_current_frame()

    def poll_state(self):
        try:
            if self.loop_fade_active:
                self._update_loop_fade_display()
            fade_locked = bool(self.loop_fade_active and time.time() < float(self.loop_fade_lock_until or 0.0))
            state = shared_state.current_musetalk_frame_data or {}
            sync_time = float(state.get("sync_time", 0.0) or 0.0)
            if self.static_preview_override:
                incoming_chunk_id = state.get("chunk_id")
                if not incoming_chunk_id or incoming_chunk_id == self.static_preview_resume_chunk_id:
                    return
                self.static_preview_override = False
                self.static_preview_release_sync_time = None
                self.static_preview_resume_chunk_id = None
            if sync_time != self.current_sync_time:
                self._apply_new_state(state)

            feed_updates = shared_state.consume_musetalk_preview_feed(self.last_feed_seq)
            if feed_updates:
                latest = feed_updates[-1]
                self.last_feed_seq = int(latest.get("_seq", self.last_feed_seq) or self.last_feed_seq)
                frame_path = latest.get("frame_path")
                if frame_path and os.path.exists(frame_path) and not fade_locked:
                    next_chunk_id = latest.get("chunk_id", self.last_chunk_id)
                    next_frame_index = int(latest.get("frame_index", 0) or 0)
                    next_source_index = int(latest.get("source_index", next_frame_index) or next_frame_index)
                    if not (
                        next_chunk_id == self.last_presented_chunk_id
                        and next_source_index == self.last_presented_source_index
                    ):
                        self.last_chunk_id = next_chunk_id
                        self.current_frame_index = next_frame_index
                        self.last_start_index = next_source_index - next_frame_index
                        self.current_frame_path = frame_path
                        if self.frame_dir and (
                            not self.frame_paths
                            or self.current_frame_index + QT_PREVIEW_AHEAD_PRELOAD >= len(self.frame_paths)
                        ):
                            self._refresh_frame_paths_from_dir()
                        if self.frame_paths:
                            self._start_frame_preload(
                                start_index=self.current_frame_index + 1,
                                count=min(
                                    max(len(self.frame_paths) - (self.current_frame_index + 1), 0),
                                    QT_PREVIEW_AHEAD_PRELOAD,
                                ),
                            )
                        self.render_current_frame()

            now = time.time()
            should_scan = (
                self.frame_dir
                and os.path.isdir(self.frame_dir)
                and len(self.frame_paths) < max(self.expected_frame_count, len(self.frame_paths))
                and now >= self.next_frame_dir_scan_at
            )
            if should_scan:
                self._refresh_frame_paths_from_dir()
                buffered_ratio = len(self.frame_paths) / max(self.expected_frame_count, 1)
                self.next_frame_dir_scan_at = now + (0.08 if buffered_ratio >= 0.9 else 0.04)

            if self.frame_paths and self.chunk_started_at and not fade_locked:
                frame_index = self._compute_runtime_frame_index(state=state)
                if frame_index is not None and frame_index != self.current_frame_index:
                    self.current_frame_index = frame_index
                    next_frame_path = self.frame_paths[frame_index]
                    if os.path.exists(next_frame_path):
                        self.current_frame_path = next_frame_path
                        if not state.get("loop", False):
                            self._start_frame_preload(
                                start_index=frame_index + 1,
                                count=min(
                                    max(len(self.frame_paths) - (frame_index + 1), 0),
                                    QT_PREVIEW_AHEAD_PRELOAD,
                                ),
                            )
                        self.render_current_frame()
        except Exception:
            pass


class QtMuseTalkStageWindow(QtWidgets.QMainWindow):
    closeRequested = QtCore.Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("Neural Companion - MuseTalk Avatar")
        self.resize(1280, 920)
        self._allow_internal_close = False
        container = QtWidgets.QWidget()
        self._layout = QtWidgets.QVBoxLayout(container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setCentralWidget(container)

    def attach_preview_widget(self, widget):
        if widget is None:
            return
        old_parent = widget.parentWidget()
        if old_parent is not None and old_parent.layout() is not None:
            old_parent.layout().removeWidget(widget)
        widget.setParent(None)
        self._layout.addWidget(widget)
        widget.show()

    def allow_internal_close(self, allowed):
        self._allow_internal_close = bool(allowed)

    def closeEvent(self, event):
        if self._allow_internal_close:
            super().closeEvent(event)
            return
        self.closeRequested.emit()
        event.ignore()


class QtExternalAvatarReturnWindow(QtWidgets.QWidget):
    showInterfaceRequested = QtCore.Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("Neural Companion")
        self.setWindowFlag(QtCore.Qt.Tool, True)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self._drag_offset = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.surface = QtWidgets.QFrame()
        self.surface.setObjectName("external_avatar_return_surface")
        self.surface.setStyleSheet(
            "QFrame#external_avatar_return_surface {"
            "background: rgba(12, 18, 26, 232);"
            "border: 1px solid #314154;"
            "border-radius: 14px;"
            "}"
        )
        surface_layout = QtWidgets.QHBoxLayout(self.surface)
        surface_layout.setContentsMargins(10, 10, 10, 10)
        surface_layout.setSpacing(8)
        self.mode_badge = QtWidgets.QLabel("Avatar")
        self.mode_badge.setCursor(QtCore.Qt.OpenHandCursor)
        self.mode_badge.setStyleSheet(
            "color: #8ea3b8; font-size: 11px; font-weight: 600; padding: 0 2px;"
        )
        self.show_button = QtWidgets.QPushButton("Show NC")
        self.show_button.setMinimumHeight(30)
        self.show_button.setMinimumWidth(92)
        self.show_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.show_button.setStyleSheet(
            "QPushButton {"
            "padding: 4px 12px;"
            "border-radius: 10px;"
            "font-weight: 600;"
            "color: #ecf3fb;"
            "background: #223043;"
            "border: 1px solid #3a516d;"
            "}"
            "QPushButton:hover {"
            "background: #2b3d55;"
            "border-color: #4a6687;"
            "}"
            "QPushButton:pressed {"
            "background: #1b2635;"
            "}"
        )
        self.show_button.clicked.connect(self.showInterfaceRequested.emit)
        surface_layout.addWidget(self.mode_badge, 0)
        surface_layout.addWidget(self.show_button, 0)
        layout.addWidget(self.surface)
        self.surface.installEventFilter(self)
        self.mode_badge.installEventFilter(self)
        self.configure_for_mode("Avatar")

    def configure_for_mode(self, mode_label):
        label = str(mode_label or "avatar").strip() or "avatar"
        self.mode_badge.setText(label)
        tooltip = f"NC interface is hidden while {label} stays in focus. Click to bring Neural Companion back."
        self.setToolTip(tooltip)
        self.show_button.setToolTip(tooltip)
        self.mode_badge.setToolTip(tooltip)
        self.adjustSize()

    def closeEvent(self, event):
        self.showInterfaceRequested.emit()
        event.ignore()

    def eventFilter(self, watched, event):
        if watched in {self.surface, self.mode_badge}:
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
                self._drag_offset = global_pos - self.frameGeometry().topLeft()
                if watched is self.mode_badge:
                    self.mode_badge.setCursor(QtCore.Qt.ClosedHandCursor)
                return True
            if event.type() == QtCore.QEvent.MouseMove and self._drag_offset is not None:
                global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
                self.move(global_pos - self._drag_offset)
                return True
            if event.type() == QtCore.QEvent.MouseButtonRelease and self._drag_offset is not None:
                self._drag_offset = None
                self.mode_badge.setCursor(QtCore.Qt.OpenHandCursor)
                return True
        return super().eventFilter(watched, event)


class QtVisualReplyPanel(QtWidgets.QWidget):
    loadRequested = QtCore.Signal()
    captionRequested = QtCore.Signal()
    clearRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.status_label = QtWidgets.QLabel("Visual Reply idle")
        self.status_label.setStyleSheet("font-weight: 600; color: #d8dee9;")

        self.storage_label = QtWidgets.QLabel("Storage: empty")
        self.storage_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self.storage_label.setWordWrap(True)

        controls = QtWidgets.QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.prev_button = QtWidgets.QPushButton("Previous")
        self.prev_button.setToolTip("Show the previous stored visual reply.")
        self.next_button = QtWidgets.QPushButton("Next")
        self.next_button.setToolTip("Show the next stored visual reply.")
        self.load_button = QtWidgets.QPushButton("Load Image")
        self.caption_button = QtWidgets.QPushButton("Caption")
        self.delete_button = QtWidgets.QPushButton("Delete Image")
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.delete_all_button = QtWidgets.QPushButton("Delete All")
        self.prev_button.clicked.connect(self.show_previous_stored_image)
        self.next_button.clicked.connect(self.show_next_stored_image)
        self.load_button.clicked.connect(self.loadRequested.emit)
        self.caption_button.clicked.connect(self.captionRequested.emit)
        self.delete_button.clicked.connect(self.delete_current_image)
        self.clear_button.clicked.connect(self.clearRequested.emit)
        self.delete_all_button.clicked.connect(self.delete_all_stored_images)
        controls.addWidget(self.prev_button, 0)
        controls.addWidget(self.load_button, 0)
        controls.addWidget(self.next_button, 0)
        controls.addWidget(self.caption_button, 0)
        controls.addWidget(self.delete_button, 0)
        controls.addWidget(self.clear_button, 0)
        controls.addWidget(self.delete_all_button, 0)
        controls.addStretch(1)

        self.content_stack = QtWidgets.QStackedWidget()

        self.placeholder = QtWidgets.QLabel("No visual reply yet.\nWhen NC creates an image, it will appear here.")
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet(
            "background: #0f141b; border: 1px solid #273342; border-radius: 10px;"
            " color: #8ea3b8; padding: 18px;"
        )

        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.image_label.setMinimumSize(0, 0)
        self.image_label.setStyleSheet("background: transparent; border: 0;")

        self.image_scroll = AltWheelZoomScrollArea()
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(QtCore.Qt.AlignCenter)
        self.image_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.image_scroll.setStyleSheet("QScrollArea { background: #0f141b; border: 1px solid #273342; border-radius: 10px; }")
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.zoomRequested.connect(self._handle_scroll_zoom_request)

        self.content_stack.addWidget(self.placeholder)
        self.content_stack.addWidget(self.image_scroll)

        self.caption_label = QtWidgets.QLabel("")
        self.caption_label.setWordWrap(True)
        self.caption_label.setStyleSheet("color: #9fb3c8; font-size: 11px; padding: 2px 2px 0 2px;")
        self.caption_label.hide()

        layout.addWidget(self.status_label)
        layout.addWidget(self.storage_label)
        layout.addLayout(controls)
        layout.addWidget(self.content_stack, 1)
        layout.addWidget(self.caption_label)

        self.current_pixmap = None
        self.current_image_path = ""
        self.current_caption = ""
        self.preview_zoom_factor = 1.0
        self._last_visual_reply_updated_at = 0.0

        self.image_label.installEventFilter(self)
        self.image_scroll.installEventFilter(self)
        self.image_scroll.viewport().installEventFilter(self)
        self.clear_visual_reply()
        self._refresh_storage_summary()

        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.poll_state)
        self.poll_timer.start(250)

    def eventFilter(self, watched, event):
        if watched is self.image_label or watched is self.image_scroll or watched is self.image_scroll.viewport():
            if event.type() == QtCore.QEvent.Resize:
                self._refresh_displayed_pixmap()
        return super().eventFilter(watched, event)

    def _scaled_pixmap_for_label(self, pixmap):
        if pixmap is None or pixmap.isNull():
            return pixmap
        target_size = self.image_scroll.viewport().contentsRect().size() if hasattr(self, 'image_scroll') else self.image_label.contentsRect().size()
        if not target_size.isValid() or target_size.width() <= 1 or target_size.height() <= 1:
            return pixmap
        fit_size = pixmap.size().scaled(target_size, QtCore.Qt.KeepAspectRatio)
        if fit_size.width() <= 0 or fit_size.height() <= 0:
            return pixmap
        zoom_factor = max(0.25, float(getattr(self, 'preview_zoom_factor', 1.0) or 1.0))
        if abs(zoom_factor - 1.0) < 0.001:
            scaled_size = fit_size
        else:
            scaled_size = QtCore.QSize(
                max(1, int(round(fit_size.width() * zoom_factor))),
                max(1, int(round(fit_size.height() * zoom_factor))),
            )
        return pixmap.scaled(scaled_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

    def _refresh_displayed_pixmap(self):
        if self.current_pixmap is None or self.current_pixmap.isNull():
            return
        display_pixmap = self._scaled_pixmap_for_label(self.current_pixmap)
        self.image_label.setPixmap(display_pixmap)
        self.image_label.resize(display_pixmap.size())

    def _handle_scroll_zoom_request(self, delta):
        step = 0.1 if delta > 0 else -0.1
        return self.adjust_zoom(step)

    def _visual_reply_storage_dir(self):
        target = Path(__file__).resolve().parent / "runtime" / "visual_replies"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _visual_reply_image_paths(self):
        storage_dir = self._visual_reply_storage_dir()
        if not storage_dir.exists():
            return []
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        entries = []
        try:
            for item in storage_dir.iterdir():
                if item.is_file() and item.suffix.lower() in allowed:
                    entries.append(item)
        except Exception:
            return []
        entries.sort(key=lambda item: (item.stat().st_mtime, item.name.lower()))
        return entries

    def _visual_reply_storage_stats(self):
        entries = self._visual_reply_image_paths()
        total_bytes = 0
        for item in entries:
            try:
                total_bytes += int(item.stat().st_size)
            except Exception:
                pass
        return entries, total_bytes

    def _visual_reply_caption_from_image(self, image_path):
        path = str(image_path or "").strip()
        if not path or not os.path.isfile(path):
            return ""
        try:
            with Image.open(path) as image:
                candidates = []
                info = dict(getattr(image, "info", {}) or {})
                for key in ("Comment", "comment", "Description", "description", "Prompt", "prompt"):
                    value = info.get(key)
                    if value:
                        candidates.append(value)
                text_map = getattr(image, "text", None)
                if isinstance(text_map, dict):
                    for key in ("Comment", "comment", "Description", "description", "Prompt", "prompt"):
                        value = text_map.get(key)
                        if value:
                            candidates.append(value)
                for value in candidates:
                    if isinstance(value, bytes):
                        for encoding in ("utf-8", "utf-16", "latin-1"):
                            try:
                                value = value.decode(encoding, errors="ignore")
                                break
                            except Exception:
                                continue
                    caption_text = str(value or "").strip()
                    if caption_text:
                        return caption_text
        except Exception:
            return ""
        return ""

    def _format_storage_bytes(self, value):
        try:
            amount = float(value or 0.0)
        except Exception:
            amount = 0.0
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        unit_index = 0
        while amount >= 1024.0 and unit_index < len(units) - 1:
            amount /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{int(amount)} {units[unit_index]}"
        return f"{amount:.1f} {units[unit_index]}"

    def _current_storage_index(self, entries):
        if not entries:
            return -1
        current_path = str(getattr(self, "current_image_path", "") or "").strip()
        if current_path:
            current_abspath = os.path.abspath(current_path)
            for index, item in enumerate(entries):
                try:
                    if os.path.abspath(str(item)) == current_abspath:
                        return index
                except Exception:
                    continue
        return len(entries) - 1

    def _refresh_storage_summary(self):
        entries, total_bytes = self._visual_reply_storage_stats()
        if not entries:
            summary = "Storage: empty"
        else:
            current_index = self._current_storage_index(entries)
            if current_index >= 0:
                summary = (
                    f"Storage: {len(entries)} image(s), {self._format_storage_bytes(total_bytes)} total"
                    f" | Current: {current_index + 1}/{len(entries)}"
                )
            else:
                summary = f"Storage: {len(entries)} image(s), {self._format_storage_bytes(total_bytes)} total"
        self.storage_label.setText(summary)
        self.storage_label.update()
        return summary

    def _show_storage_image_by_offset(self, offset):
        entries, _ = self._visual_reply_storage_stats()
        if not entries:
            self._refresh_storage_summary()
            return False
        current_index = self._current_storage_index(entries)
        if current_index < 0:
            current_index = len(entries) - 1 if offset < 0 else 0
        target_index = max(0, min(len(entries) - 1, current_index + int(offset)))
        target_path = entries[target_index]
        caption_text = self._visual_reply_caption_from_image(target_path)
        loaded = self.show_image(
            str(target_path),
            status_text="Visual Reply history",
            caption=caption_text,
        )
        if loaded:
            shared_state.set_current_visual_reply_data(
                {
                    "status": "ready",
                    "status_text": "Visual Reply history",
                    "detail_text": "",
                    "image_path": str(target_path),
                    "caption": caption_text,
                    "request_id": "",
                    "updated_at": time.time(),
                }
            )
        self._refresh_storage_summary()
        return loaded

    def show_previous_stored_image(self):
        return self._show_storage_image_by_offset(-1)

    def show_next_stored_image(self):
        return self._show_storage_image_by_offset(1)

    def delete_all_stored_images(self):
        entries, _ = self._visual_reply_storage_stats()
        if not entries:
            self._refresh_storage_summary()
            return False
        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete Visual Reply Images",
            f"Delete all {len(entries)} stored visual reply image(s)?",
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return False
        removed = 0
        for item in entries:
            try:
                item.unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
        self.clear_visual_reply(
            status_text="Visual Reply storage cleared",
            detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.",
        )
        shared_state.set_current_visual_reply_data(
            {
                "status": "idle",
                "status_text": "Visual Reply storage cleared",
                "detail_text": "No visual reply yet.\nWhen NC creates an image, it will appear here.",
                "image_path": "",
                "caption": "",
                "request_id": "",
                "updated_at": time.time(),
            }
        )
        self._refresh_storage_summary()
        return bool(removed)

    def delete_current_image(self):
        current_path = str(getattr(self, "current_image_path", "") or "").strip()
        if not current_path or not os.path.isfile(current_path):
            return False
        storage_dir = os.path.abspath(str(self._visual_reply_storage_dir()))
        current_abs = os.path.abspath(current_path)
        try:
            within_storage = os.path.commonpath([current_abs, storage_dir]) == storage_dir
        except Exception:
            within_storage = False
        label = "Delete current image"
        if within_storage:
            entries, _ = self._visual_reply_storage_stats()
            current_index = self._current_storage_index(entries)
            if current_index < 0:
                current_index = 0
            prompt = f"Delete the currently displayed visual reply image?\n\n{current_path}"
            if len(entries) > 1:
                prompt += "\n\nThe browser will move to the next available image."
        else:
            prompt = f"Delete the currently displayed image file?\n\n{current_path}"
        answer = QtWidgets.QMessageBox.question(self, label, prompt)
        if answer != QtWidgets.QMessageBox.Yes:
            return False
        try:
            os.remove(current_path)
        except Exception:
            return False
        if within_storage:
            remaining = [item for item in self._visual_reply_image_paths() if os.path.abspath(str(item)) != current_abs]
            if remaining:
                entries = remaining
                if "current_index" not in locals():
                    current_index = 0
                target_index = min(current_index, len(entries) - 1)
                target_path = entries[target_index]
                caption_text = self._visual_reply_caption_from_image(target_path)
                self.show_image(str(target_path), status_text="Visual Reply history", caption=caption_text)
                shared_state.set_current_visual_reply_data(
                    {
                        "status": "ready",
                        "status_text": "Visual Reply history",
                        "detail_text": "",
                        "image_path": str(target_path),
                        "caption": caption_text,
                        "request_id": "",
                        "updated_at": time.time(),
                    }
                )
            else:
                self.clear_visual_reply(
                    status_text="Visual Reply image deleted",
                    detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.",
                )
                shared_state.set_current_visual_reply_data(
                    {
                        "status": "idle",
                        "status_text": "Visual Reply image deleted",
                        "detail_text": "No visual reply yet.\nWhen NC creates an image, it will appear here.",
                        "image_path": "",
                        "caption": "",
                        "request_id": "",
                        "updated_at": time.time(),
                    }
                )
            self._refresh_storage_summary()
        else:
            self.clear_visual_reply(
                status_text="Visual Reply image deleted",
                detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.",
            )
            shared_state.set_current_visual_reply_data(
                {
                    "status": "idle",
                    "status_text": "Visual Reply image deleted",
                    "detail_text": "No visual reply yet.\nWhen NC creates an image, it will appear here.",
                    "image_path": "",
                    "caption": "",
                    "request_id": "",
                    "updated_at": time.time(),
                }
            )
        return True

    def adjust_zoom(self, delta):
        updated = max(0.25, min(4.0, float(getattr(self, 'preview_zoom_factor', 1.0) or 1.0) + float(delta)))
        if abs(updated - float(getattr(self, 'preview_zoom_factor', 1.0) or 1.0)) < 0.001:
            return False
        self.preview_zoom_factor = updated
        self._refresh_displayed_pixmap()
        return True

    def reset_zoom(self):
        self.preview_zoom_factor = 1.0
        self._refresh_displayed_pixmap()
        return True

    def clear_visual_reply(self, status_text="Visual Reply idle", detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here."):
        self.current_pixmap = None
        self.current_image_path = ""
        self.current_caption = ""
        self.preview_zoom_factor = 1.0
        self.image_label.clear()
        self.placeholder.setText(str(detail_text or "No visual reply yet."))
        self.status_label.setText(str(status_text or "Visual Reply idle"))
        self.caption_label.clear()
        self.caption_label.hide()
        self.content_stack.setCurrentWidget(self.placeholder)
        self._refresh_storage_summary()

    def set_caption(self, caption=""):
        caption_text = str(caption or "").strip()
        self.current_caption = caption_text
        if caption_text:
            self.caption_label.setText(caption_text)
            self.caption_label.show()
        else:
            self.caption_label.clear()
            self.caption_label.hide()
        return True

    def set_loading_state(self, status_text="Visual Reply generating...", detail_text="Preparing image...", *, keep_current_image=False):
        keep_current = bool(
            (keep_current_image or self.current_image_path)
            and self.current_pixmap is not None
            and self.current_image_path
        )
        if not keep_current:
            self.current_pixmap = None
            self.current_image_path = ""
            self.current_caption = ""
            self.preview_zoom_factor = 1.0
            self.image_label.clear()
        self.placeholder.setText(str(detail_text or "Preparing image..."))
        self.status_label.setText(str(status_text or "Visual Reply generating..."))
        if keep_current:
            self.content_stack.setCurrentWidget(self.image_scroll)
        else:
            self.caption_label.clear()
            self.caption_label.hide()
            self.content_stack.setCurrentWidget(self.placeholder)
        self._refresh_storage_summary()

    def show_image(self, image_path, status_text="Visual Reply", caption=""):
        path = str(image_path or "").strip()
        if not path or not os.path.isfile(path):
            return False
        image = QtGui.QImage(path)
        if image.isNull():
            return False
        self.current_image_path = path
        self.current_pixmap = QtGui.QPixmap.fromImage(image)
        self.preview_zoom_factor = 1.0
        self.status_label.setText(str(status_text or "Visual Reply"))
        resolved_caption = str(caption or "").strip() or self._visual_reply_caption_from_image(path)
        self.current_caption = resolved_caption
        self.set_caption(resolved_caption)
        self.content_stack.setCurrentWidget(self.image_scroll)
        self._refresh_displayed_pixmap()
        self._refresh_storage_summary()
        return True

    def poll_state(self):
        try:
            state = dict(getattr(shared_state, "current_visual_reply_data", {}) or {})
            updated_at = float(state.get("updated_at", 0.0) or 0.0)
            if updated_at <= 0.0 or updated_at == self._last_visual_reply_updated_at:
                return
            self._last_visual_reply_updated_at = updated_at
            status = str(state.get("status", "idle") or "idle").strip().lower()
            host_window = self.window()
            auto_show_enabled = bool(RUNTIME_CONFIG.get("visual_reply_auto_show_dock", True))
            if auto_show_enabled and status in {"loading", "ready", "error"} and hasattr(host_window, "show_visual_reply_dock"):
                try:
                    host_window.show_visual_reply_dock()
                except Exception:
                    pass
            if status == "ready":
                image_path = str(state.get("image_path", "") or "").strip()
                if image_path and os.path.isfile(image_path):
                    self.show_image(
                        image_path,
                        status_text=str(state.get("status_text", "Visual Reply") or "Visual Reply"),
                        caption=str(state.get("caption", "") or ""),
                    )
                else:
                    self.clear_visual_reply(
                        status_text="Visual Reply unavailable",
                        detail_text=str(state.get("detail_text", "The requested image could not be loaded.") or "The requested image could not be loaded."),
                    )
            elif status == "loading":
                keep_current_image = bool(state.get("keep_current_image", False))
                retained_image_path = str(state.get("image_path", "") or "").strip()
                if keep_current_image and retained_image_path and os.path.isfile(retained_image_path):
                    if not self.current_image_path or self.current_image_path != retained_image_path or self.current_pixmap is None:
                        self.show_image(
                            retained_image_path,
                            status_text=str(state.get("status_text", "Visual Reply generating...") or "Visual Reply generating..."),
                            caption=str(state.get("caption", "") or ""),
                        )
                self.set_loading_state(
                    status_text=str(state.get("status_text", "Visual Reply generating...") or "Visual Reply generating..."),
                    detail_text=str(state.get("detail_text", "Preparing image...") or "Preparing image..."),
                    keep_current_image=keep_current_image,
                )
            elif status == "error":
                self.clear_visual_reply(
                    status_text=str(state.get("status_text", "Visual Reply failed") or "Visual Reply failed"),
                    detail_text=str(state.get("detail_text", "Image generation failed.") or "Image generation failed."),
                )
            else:
                self.clear_visual_reply(
                    status_text=str(state.get("status_text", "Visual Reply idle") or "Visual Reply idle"),
                    detail_text=str(state.get("detail_text", "No visual reply yet.\nWhen NC creates an image, it will appear here.") or "No visual reply yet.\nWhen NC creates an image, it will appear here."),
                )
        except Exception:
            pass


class CompanionQtMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 980)
        self.thread = None
        self._closing = False
        self.musetalk_preview_process = None
        self._musetalk_avatar_focus_active = False
        self._musetalk_stage_window = None
        self._musetalk_main_window_was_maximized = False
        self._musetalk_main_window_was_fullscreen = False
        self._external_avatar_focus_active = False
        self._external_avatar_focus_mode = ""
        self._external_avatar_return_window = None
        self._external_avatar_main_window_was_maximized = False
        self._external_avatar_main_window_was_fullscreen = False
        self.pose_sliders = {}
        self.brain_sliders = {}
        self.chunking_sliders = {}
        self.dry_run_recommended_settings = {}
        self.dry_run_last_applied_candidate_index = None
        self.first_run = True
        self.active_tutorial_overlay = None
        self.tutorial_event_bus = tutorial_framework.TutorialEventBus(self)
        self._tutorial_lm_studio_running = False
        self._model_refresh_in_flight = False
        self._model_refresh_provider = ""
        self._model_refresh_generation = 0
        self._pending_model_refresh = None
        self._pending_model_refresh_provider = ""
        self._pending_model_refresh_generation = 0
        self._model_refresh_lock = threading.Lock()
        self._model_catalog = []
        self._all_model_catalog = []
        self._model_estimate_cache = {}
        self._model_estimate_in_flight = False
        self._pending_model_estimate = None
        self._model_estimate_lock = threading.Lock()
        self._model_context_estimate_cache = {}
        self._model_context_estimate_in_flight = False
        self._pending_model_context_estimate = None
        self._model_context_estimate_lock = threading.Lock()
        self._model_single_context_estimate_cache = {}
        self._single_context_estimate_in_flight = False
        self._pending_single_context_estimate = None
        self._single_context_estimate_lock = threading.Lock()
        self._advisor_context_manual_override = False
        self._advisor_context_updating = False
        self._pipeline_frame_count_cache = {}
        self._addon_manager = None
        self._mounted_addon_tab_ids = set()
        self._mounted_musetalk_addon_tab_ids = set()
        self._mounted_host_settings_addon_tab_ids = set()
        self._mounted_tts_runtime_addon_tab_ids = set()
        self._mounted_operational_view_addon_tab_ids = set()
        self._addon_host_tab_groups = {}
        self._tts_runtime_tab_index_by_backend = {}
        self.console_auto_scroll = True
        self.chat_auto_scroll = True
        self.chat_edit_mode = False
        self._chat_edit_snapshot_text = ""
        self._chat_provider_field_widgets = {}
        self._chat_provider_field_meta = {}
        self._preset_reference_name = ""
        self._preset_reference_signature = ""
        self._preset_dirty_state = None
        self._pending_preset_clean_name = ""
        self._pending_preset_clean_provider = ""
        self._pending_preset_clean_model = ""
        self._restoring_session = False
        self._chat_runtime_border_paused = None
        self._console_bridge = QtConsoleBridge()
        self._console_redirect = QtTextRedirector(self._console_bridge, mirror_stream=sys.__stdout__)
        self._previous_stdout = sys.stdout
        self._previous_stderr = sys.stderr
        sys.stdout = self._console_redirect
        sys.stderr = self._console_redirect
        self._floating_panels_preserved = []
        self._restore_floating_panels_timer = QtCore.QTimer(self)
        self._restore_floating_panels_timer.setSingleShot(True)
        self._restore_floating_panels_timer.timeout.connect(self._restore_floating_panels_after_minimize)

        self._build_ui()
        self._build_preview_dock()
        self._connect_console_bridge()
        self._build_status_timer()
        self._build_ui_hotkey_timer()
        self._initialize_addons()

        os.makedirs("presets", exist_ok=True)
        os.makedirs("voices", exist_ok=True)
        os.makedirs("body_configs", exist_ok=True)

        threading.Thread(target=start_api, daemon=True).start()
        print("📡 [API] Expression server running on port 5005")

        self.refresh_resources()
        self.restore_session()
        self.refresh_tutorial_list()
        QtCore.QTimer.singleShot(250, self.maybe_prompt_first_run_tutorial)

    def _build_ui(self):
        self.setDockNestingEnabled(True)
        self.setStyleSheet(APP_STYLESHEET)

        central = QtWidgets.QWidget()
        central.setObjectName("workspace_central")
        central.setMinimumSize(0, 0)
        central.setMaximumSize(0, 0)
        central.hide()
        self.setCentralWidget(central)

        self.system_shaping_panel, self.workspace_tabs_panel = self._build_left_panel()
        self.right_panel = self._build_right_panel()

        self.system_shaping_dock = QtWidgets.QDockWidget("System Shaping", self)
        self.system_shaping_dock.setObjectName("SystemShapingDock")
        self.system_shaping_dock.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea
            | QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.TopDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
        )
        self.system_shaping_dock.setMinimumSize(0, 0)
        self.system_shaping_dock.setWidget(self.system_shaping_panel)
        self._register_workspace_dock(self.system_shaping_dock)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.system_shaping_dock)

        self.workspace_tabs_dock = QtWidgets.QDockWidget("Workspace Tabs", self)
        self.workspace_tabs_dock.setObjectName("WorkspaceTabsDock")
        self.workspace_tabs_dock.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea
            | QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.TopDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
        )
        self.workspace_tabs_dock.setMinimumSize(0, 0)
        self.workspace_tabs_dock.setWidget(self.workspace_tabs_panel)
        self._register_workspace_dock(self.workspace_tabs_dock)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.workspace_tabs_dock)
        try:
            self.tabifyDockWidget(self.system_shaping_dock, self.workspace_tabs_dock)
        except Exception:
            pass
        self.workspace_tabs_dock.raise_()

        self.operational_dock = QtWidgets.QDockWidget("Operational View", self)
        self.operational_dock.setObjectName("OperationalViewDock")
        self.operational_dock.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea
            | QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.TopDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
        )
        self.operational_dock.setMinimumSize(0, 0)
        self.operational_dock.setWidget(self.right_panel)
        self._register_workspace_dock(self.operational_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.operational_dock)
        try:
            self.resizeDocks(
                [self.system_shaping_dock, self.operational_dock],
                [520, 720],
                QtCore.Qt.Horizontal,
            )
        except Exception:
            pass
        self._build_workspace_menu()

    def _register_workspace_dock(self, dock):
        if dock is None:
            return
        try:
            dock.topLevelChanged.connect(lambda _floating, d=dock: self._schedule_dock_owner_refresh(d))
        except Exception:
            pass
        self._schedule_dock_owner_refresh(dock)

    def _schedule_dock_owner_refresh(self, dock):
        if dock is None or not _WIN32_DOCK_OWNER_SUPPORTED:
            return
        QtCore.QTimer.singleShot(0, lambda d=dock: self._refresh_native_dock_owner(d))

    def _refresh_native_dock_owner(self, dock):
        if dock is None or not _WIN32_DOCK_OWNER_SUPPORTED:
            return
        try:
            hwnd = int(dock.winId())
            owner = 0 if dock.isFloating() else int(self.winId())
            _win32_set_window_owner(hwnd, _WIN32_GWLP_HWNDPARENT, ctypes.c_void_p(owner))
        except Exception:
            pass

    def changeEvent(self, event):
        try:
            if event.type() == QtCore.QEvent.WindowStateChange:
                if bool(self.windowState() & QtCore.Qt.WindowMinimized):
                    self._capture_floating_panels_for_minimize()
                    self._restore_floating_panels_timer.start(0)
        except Exception:
            pass
        super().changeEvent(event)

    def _collect_preservable_floating_panels(self):
        panels = []
        seen = set()
        for dock in self.findChildren(QtWidgets.QDockWidget):
            if not dock.isFloating() or not dock.isVisible():
                continue
            key = id(dock)
            if key in seen:
                continue
            seen.add(key)
            panels.append(dock)
        stage = getattr(self, "_musetalk_stage_window", None)
        if stage is not None and stage.isVisible():
            panels.append(stage)
        external_return = getattr(self, "_external_avatar_return_window", None)
        if external_return is not None and external_return.isVisible():
            panels.append(external_return)
        return panels

    def _capture_floating_panels_for_minimize(self):
        self._floating_panels_preserved = self._collect_preservable_floating_panels()

    def _restore_floating_panels_after_minimize(self):
        preserved = list(getattr(self, "_floating_panels_preserved", []) or [])
        if not preserved:
            return
        for panel in preserved:
            try:
                if panel is None:
                    continue
                if isinstance(panel, QtWidgets.QDockWidget) and not panel.isFloating():
                    continue
                panel.setWindowState(panel.windowState() & ~QtCore.Qt.WindowMinimized)
                panel.showNormal()
                panel.show()
                panel.raise_()
                panel.activateWindow()
            except Exception:
                continue

    def _build_workspace_menu(self):
        menu_bar = self.menuBar()
        self.workspace_menu = menu_bar.addMenu("Workspace")
        if hasattr(self, "system_shaping_dock"):
            self.workspace_menu.addAction(self.system_shaping_dock.toggleViewAction())
        if hasattr(self, "workspace_tabs_dock"):
            self.workspace_menu.addAction(self.workspace_tabs_dock.toggleViewAction())
        if hasattr(self, "operational_dock"):
            self.workspace_menu.addAction(self.operational_dock.toggleViewAction())
        self.workspace_menu.addSeparator()
        reset_action = self.workspace_menu.addAction("Reset Workspace Layout")
        reset_action.triggered.connect(self.reset_workspace_layout)
        show_all_action = self.workspace_menu.addAction("Show All Panels")
        show_all_action.triggered.connect(self.show_all_workspace_panels)

    def show_all_workspace_panels(self):
        if hasattr(self, "system_shaping_dock"):
            self.system_shaping_dock.show()
            self.system_shaping_dock.raise_()
        if hasattr(self, "workspace_tabs_dock"):
            self.workspace_tabs_dock.show()
            self.workspace_tabs_dock.raise_()
        if hasattr(self, "operational_dock"):
            self.operational_dock.show()
            self.operational_dock.raise_()
        if hasattr(self, "preview_dock"):
            self.preview_dock.show()
        if hasattr(self, "visual_reply_dock"):
            self.visual_reply_dock.show()
        print("[QtGUI] Workspace panels shown.")

    def reset_workspace_layout(self):
        if getattr(self, "_musetalk_avatar_focus_active", False):
            self.exit_musetalk_avatar_focus(raise_main=False)
        if getattr(self, "_external_avatar_focus_active", False):
            self.exit_external_avatar_focus(raise_main=False)
        if hasattr(self, "system_shaping_dock"):
            self.system_shaping_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.system_shaping_dock)
            self.system_shaping_dock.show()
        if hasattr(self, "workspace_tabs_dock"):
            self.workspace_tabs_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.workspace_tabs_dock)
            self.workspace_tabs_dock.show()
            if hasattr(self, "system_shaping_dock"):
                try:
                    self.tabifyDockWidget(self.system_shaping_dock, self.workspace_tabs_dock)
                except Exception:
                    pass
        if hasattr(self, "operational_dock"):
            self.operational_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.operational_dock)
            self.operational_dock.show()
        if hasattr(self, "preview_dock"):
            self.preview_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.preview_dock)
            self.preview_dock.hide()
        if hasattr(self, "visual_reply_dock"):
            self.visual_reply_dock.setFloating(False)
            self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.visual_reply_dock)
            self.visual_reply_dock.hide()
        if hasattr(self, "preview_dock") and hasattr(self, "visual_reply_dock"):
            try:
                self.tabifyDockWidget(self.preview_dock, self.visual_reply_dock)
            except Exception:
                pass
        try:
            self.resizeDocks(
                [self.system_shaping_dock, self.operational_dock],
                [520, 720],
                QtCore.Qt.Horizontal,
            )
        except Exception:
            pass
        print("[QtGUI] Workspace layout reset.")

    def _build_preview_dock(self):
        self.preview_dock = QtWidgets.QDockWidget("MuseTalk Preview", self)
        self.preview_dock.setObjectName("MuseTalkPreviewDock")
        self.preview_dock.setAllowedAreas(
            QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
            | QtCore.Qt.LeftDockWidgetArea
        )
        self.preview_dock_container = QtWidgets.QWidget()
        self.preview_dock_layout = QtWidgets.QVBoxLayout(self.preview_dock_container)
        self.preview_dock_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_dock_layout.setSpacing(0)
        self.embedded_musetalk_preview = QtMuseTalkPreviewPanel()
        self.embedded_musetalk_preview.focusModeRequested.connect(self.toggle_musetalk_avatar_focus)
        self.embedded_musetalk_preview.showInterfaceRequested.connect(self.show_main_interface_from_musetalk_focus)
        self.preview_dock_layout.addWidget(self.embedded_musetalk_preview)
        self.preview_dock.setWidget(self.preview_dock_container)
        self._register_workspace_dock(self.preview_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.preview_dock)
        self.preview_dock.hide()
        self._ensure_musetalk_stage_window()
        if hasattr(self, "workspace_menu"):
            self.workspace_menu.insertAction(self.workspace_menu.actions()[-2], self.preview_dock.toggleViewAction())

        self.visual_reply_dock = QtWidgets.QDockWidget("Visual Reply", self)
        self.visual_reply_dock.setObjectName("VisualReplyDock")
        self.visual_reply_dock.setAllowedAreas(
            QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
            | QtCore.Qt.LeftDockWidgetArea
        )
        self.visual_reply_panel = QtVisualReplyPanel()
        self.visual_reply_panel.loadRequested.connect(self.prompt_visual_reply_image)
        self.visual_reply_panel.captionRequested.connect(self.prompt_visual_reply_caption)
        self.visual_reply_panel.clearRequested.connect(lambda: self.clear_visual_reply(auto_show=False))
        self.visual_reply_dock.setWidget(self.visual_reply_panel)
        self._register_workspace_dock(self.visual_reply_dock)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.visual_reply_dock)
        self.tabifyDockWidget(self.preview_dock, self.visual_reply_dock)
        self.visual_reply_dock.hide()
        if hasattr(self, "workspace_menu"):
            self.workspace_menu.insertAction(self.workspace_menu.actions()[-2], self.visual_reply_dock.toggleViewAction())

    def _ensure_musetalk_stage_window(self):
        if self._musetalk_stage_window is None:
            self._musetalk_stage_window = QtMuseTalkStageWindow()
            self._musetalk_stage_window.closeRequested.connect(self.show_main_interface_from_musetalk_focus)
        return self._musetalk_stage_window

    def _ensure_external_avatar_return_window(self):
        if self._external_avatar_return_window is None:
            self._external_avatar_return_window = QtExternalAvatarReturnWindow()
            self._external_avatar_return_window.showInterfaceRequested.connect(self.show_main_interface_from_external_avatar_focus)
        return self._external_avatar_return_window

    def _position_external_avatar_return_window(self):
        window = self._ensure_external_avatar_return_window()
        main_geometry = self.frameGeometry()
        anchor = main_geometry.topLeft() + QtCore.QPoint(40, 40)
        rect = QtCore.QRect(anchor, window.size())
        available = QtWidgets.QApplication.primaryScreen().availableGeometry() if QtWidgets.QApplication.primaryScreen() else None
        if available is not None:
            if rect.right() > available.right():
                rect.moveRight(available.right() - 16)
            if rect.bottom() > available.bottom():
                rect.moveBottom(available.bottom() - 16)
            if rect.left() < available.left():
                rect.moveLeft(available.left() + 16)
            if rect.top() < available.top():
                rect.moveTop(available.top() + 16)
        window.setGeometry(rect)
        return window

    def _attach_musetalk_preview_to_host(self, host):
        panel = getattr(self, "embedded_musetalk_preview", None)
        if panel is None:
            return False
        target_layout = getattr(self, "preview_dock_layout", None)
        if host == "stage":
            stage_window = self._ensure_musetalk_stage_window()
            stage_window.attach_preview_widget(panel)
            return True
        if target_layout is None:
            return False
        old_parent = panel.parentWidget()
        if old_parent is not None and old_parent.layout() is not None:
            old_parent.layout().removeWidget(panel)
        panel.setParent(None)
        target_layout.addWidget(panel)
        panel.show()
        return True

    def _sync_musetalk_stage_window_geometry_from_preview(self):
        stage_window = self._ensure_musetalk_stage_window()
        source_rect = None
        preview_dock = getattr(self, "preview_dock", None)
        if preview_dock is not None:
            try:
                dock_rect = preview_dock.frameGeometry()
                if dock_rect.isValid() and dock_rect.width() > 120 and dock_rect.height() > 120:
                    source_rect = QtCore.QRect(dock_rect)
            except Exception:
                source_rect = None
        if source_rect is None:
            panel = getattr(self, "embedded_musetalk_preview", None)
            if panel is not None:
                try:
                    panel_size = panel.size()
                    if panel_size.width() <= 32 or panel_size.height() <= 32:
                        panel_size = panel.sizeHint()
                    top_left = panel.mapToGlobal(QtCore.QPoint(0, 0))
                    source_rect = QtCore.QRect(top_left, panel_size)
                except Exception:
                    source_rect = None
        if source_rect is None or source_rect.width() <= 32 or source_rect.height() <= 32:
            return False
        try:
            stage_window.showNormal()
        except Exception:
            pass
        stage_window.setGeometry(source_rect)
        return True

    def enter_external_avatar_focus(self, mode_label=None):
        mode_label = str(mode_label or self.engine_combo.currentText() or "Avatar").strip() or "Avatar"
        self._external_avatar_focus_active = True
        self._external_avatar_focus_mode = mode_label
        self._external_avatar_main_window_was_maximized = bool(self.isMaximized())
        self._external_avatar_main_window_was_fullscreen = bool(self.isFullScreen())
        window = self._position_external_avatar_return_window()
        window.configure_for_mode(mode_label)
        window.show()
        window.raise_()
        window.activateWindow()
        self.hide()
        print(f"[QtGUI] External avatar focus entered for {mode_label}.")

    def exit_external_avatar_focus(self, *, raise_main=True):
        was_active = bool(self._external_avatar_focus_active)
        self._external_avatar_focus_active = False
        self._external_avatar_focus_mode = ""
        if self._external_avatar_return_window is not None:
            self._external_avatar_return_window.hide()
        if raise_main or was_active or not self.isVisible():
            if self._external_avatar_main_window_was_fullscreen:
                self.showFullScreen()
            elif self._external_avatar_main_window_was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.raise_()
            self.activateWindow()
        if was_active:
            print("[QtGUI] External avatar focus exited.")

    def show_main_interface_from_external_avatar_focus(self):
        self.exit_external_avatar_focus(raise_main=True)

    def _wrap_panel(self):
        panel = QtWidgets.QFrame()
        panel.setObjectName("Panel")
        return panel

    def _wrap_compact_form_field(self, widget):
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget, 0, QtCore.Qt.AlignLeft)
        layout.addStretch(1)
        return row

    def _make_header(self, eyebrow, title):
        frame = QtWidgets.QFrame()
        frame.setObjectName("HeaderCard")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        eyebrow_label = QtWidgets.QLabel(eyebrow)
        eyebrow_label.setStyleSheet("color: #7fb4ff; font-size: 11px; font-weight: 700; text-transform: uppercase;")
        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #f2f5f9;")
        layout.addWidget(eyebrow_label)
        layout.addWidget(title_label)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        frame.adjustSize()
        frame.setFixedHeight(frame.sizeHint().height())
        return frame

    def _build_left_panel(self):
        shaping_panel = self._wrap_panel()
        shaping_panel.setMinimumSize(0, 0)
        shaping_panel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        shaping_outer_layout = QtWidgets.QVBoxLayout(shaping_panel)
        shaping_outer_layout.setContentsMargins(0, 0, 0, 0)
        shaping_outer_layout.setSpacing(0)

        shaping_scroll = QtWidgets.QScrollArea()
        shaping_scroll.setWidgetResizable(True)
        shaping_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        shaping_scroll.setMinimumSize(0, 0)
        shaping_scroll.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.system_shaping_scroll = shaping_scroll
        shaping_outer_layout.addWidget(shaping_scroll)

        shaping_content = QtWidgets.QWidget()
        shaping_content.setMinimumSize(0, 0)
        shaping_scroll.setWidget(shaping_content)

        layout = QtWidgets.QVBoxLayout(shaping_content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(self._make_header("Experimental Qt Shell", "System Shaping"))

        mic_row = QtWidgets.QHBoxLayout()
        self.listen_diode = QtWidgets.QFrame()
        self.listen_diode.setFixedSize(16, 16)
        self.listen_diode.setStyleSheet(self._status_diode_style(False, "#39d98a", "#92f0bf"))
        self.mic_diode = QtWidgets.QFrame()
        self.mic_diode.setFixedSize(16, 16)
        self.mic_diode.setStyleSheet(self._status_diode_style(False, "#ff4d5e", "#ff96a0"))
        self.mic_status_label = QtWidgets.QLabel("Microphone idle")
        self.mic_status_label.setStyleSheet("color: #9fb3c8; font-weight: 600;")
        mic_row.addWidget(self.listen_diode)
        mic_row.addWidget(self.mic_diode)
        mic_row.addWidget(self.mic_status_label)
        mic_row.addStretch(1)
        layout.addLayout(mic_row)

        self.engine_combo = NoWheelComboBox()
        self.engine_combo.setObjectName("engine_combo")
        self.engine_combo.addItems(["VSeeFace", "MuseTalk", "VaM", "None"])
        self.engine_combo.currentTextChanged.connect(self.on_engine_change)

        self.input_mode_combo = NoWheelComboBox()
        self.input_mode_combo.setObjectName("input_mode_combo")
        self.input_mode_combo.addItems(["Voice Activation", "Push-to-Talk"])
        self.input_mode_combo.currentTextChanged.connect(self.on_input_mode_change)

        self.input_role_combo = NoWheelComboBox()
        self.input_role_combo.setObjectName("input_role_combo")
        self.input_role_combo.addItems(["User Message", "System Message", "Assistant Message"])
        self.input_role_combo.currentTextChanged.connect(self.on_input_role_change)

        self.stream_mode_combo = NoWheelComboBox()
        self.stream_mode_combo.setObjectName("stream_mode_combo")
        self.stream_mode_combo.addItems(["Off", "On"])
        self.stream_mode_combo.currentTextChanged.connect(self.on_stream_mode_change)

        self.tts_backend_combo = NoWheelComboBox()
        self.tts_backend_combo.setObjectName("tts_backend_combo")
        self.tts_backend_combo.currentTextChanged.connect(self.on_tts_backend_change)
        self._populate_tts_backend_combo()

        self.musetalk_vram_combo = NoWheelComboBox()
        self.musetalk_vram_combo.setObjectName("musetalk_vram_combo")
        self.musetalk_vram_combo.addItems(list(MUSE_VRAM_MODE_LABELS.values()))
        self.musetalk_vram_combo.currentTextChanged.connect(self.on_musetalk_vram_mode_change)

        self.musetalk_loop_fade_spin = ContextTokenStepper()
        self.musetalk_loop_fade_spin.setObjectName("musetalk_loop_fade_spin")
        self.musetalk_loop_fade_spin.setRange(0, 1000)
        self.musetalk_loop_fade_spin.setSingleStep(50)
        self.musetalk_loop_fade_spin.setValue(max(0, int(RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS)))
        self.musetalk_loop_fade_spin.valueChanged.connect(self.on_musetalk_loop_fade_changed)
        self.musetalk_loop_fade_spin.setMinimumWidth(112)
        self.musetalk_loop_fade_spin.setMaximumWidth(132)

        self.visual_reply_mode_combo = NoWheelComboBox()
        self.visual_reply_mode_combo.setObjectName("visual_reply_mode_combo")
        self.visual_reply_mode_combo.addItems(["Off", "Auto"])
        self.visual_reply_mode_combo.setCurrentText("Off" if str(RUNTIME_CONFIG.get("visual_reply_mode", "auto") or "auto").strip().lower() == "off" else "Auto")
        self.visual_reply_mode_combo.currentTextChanged.connect(self.on_visual_reply_mode_changed)

        self.visual_reply_provider_combo = NoWheelComboBox()
        self.visual_reply_provider_combo.setObjectName("visual_reply_provider_combo")
        self.visual_reply_provider_combo.addItems(["OpenAI", "xAI / Grok"])
        current_visual_provider = str(RUNTIME_CONFIG.get("visual_reply_provider", "openai") or "openai").strip().lower()
        self.visual_reply_provider_combo.setCurrentText("xAI / Grok" if current_visual_provider == "xai" else "OpenAI")
        self.visual_reply_provider_combo.currentTextChanged.connect(self.on_visual_reply_provider_changed)

        self.visual_reply_size_combo = NoWheelComboBox()
        self.visual_reply_size_combo.setObjectName("visual_reply_size_combo")
        self.visual_reply_size_combo.addItems(["Auto", "1024x1024", "1024x1536", "1536x1024"])
        current_visual_size = str(RUNTIME_CONFIG.get("visual_reply_size", "1024x1024") or "1024x1024").strip().lower()
        if current_visual_size not in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
            current_visual_size = "1024x1024"
        self.visual_reply_size_combo.setCurrentText("Auto" if current_visual_size == "auto" else current_visual_size)
        self.visual_reply_size_combo.currentTextChanged.connect(self.on_visual_reply_size_changed)

        self.visual_reply_model_edit = QtWidgets.QLineEdit()
        self.visual_reply_model_edit.setObjectName("visual_reply_model_edit")
        self.visual_reply_model_edit.setText(str(RUNTIME_CONFIG.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"))
        self.visual_reply_model_edit.editingFinished.connect(self.on_visual_reply_model_changed)

        self.visual_reply_auto_show_checkbox = QtWidgets.QCheckBox("Auto-show Visual Reply dock")
        self.visual_reply_auto_show_checkbox.setObjectName("visual_reply_auto_show_checkbox")
        self.visual_reply_auto_show_checkbox.setChecked(bool(RUNTIME_CONFIG.get("visual_reply_auto_show_dock", True)))
        self.visual_reply_auto_show_checkbox.toggled.connect(self.on_visual_reply_auto_show_changed)

        self.sensory_feedback_source_combo = NoWheelComboBox()
        self.sensory_feedback_source_combo.setObjectName("sensory_feedback_source_combo")
        self.sensory_feedback_source_combo.setEnabled(False)
        self.sensory_feedback_source_combo.currentTextChanged.connect(self.on_sensory_feedback_source_changed)
        self.sensory_feedback_sources_widget = QtWidgets.QWidget()
        self.sensory_feedback_sources_widget.setObjectName("sensory_feedback_sources_widget")
        self.sensory_feedback_sources_layout = QtWidgets.QVBoxLayout(self.sensory_feedback_sources_widget)
        self.sensory_feedback_sources_layout.setContentsMargins(0, 0, 0, 0)
        self.sensory_feedback_sources_layout.setSpacing(4)
        self._sensory_feedback_source_checkboxes = {}
        self._sensory_source_prompt_editors = {}
        self._sensory_source_prompt_tabs = {}
        self.refresh_sensory_feedback_source_options(selected_value=str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"))

        self.sensory_feedback_interval_spin = DecimalStepper()
        self.sensory_feedback_interval_spin.setObjectName("sensory_feedback_interval_spin")
        self.sensory_feedback_interval_spin.setRange(2.0, 60.0)
        self.sensory_feedback_interval_spin.setSingleStep(0.5)
        self.sensory_feedback_interval_spin.setDecimals(1)
        self.sensory_feedback_interval_spin.setValue(float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0))
        self.sensory_feedback_interval_spin.valueChanged.connect(self.on_sensory_feedback_interval_changed)
        self.sensory_feedback_interval_spin.setMinimumWidth(112)
        self.sensory_feedback_interval_spin.setMaximumWidth(132)

        self.sensory_pingpong_checkbox = QtWidgets.QCheckBox("Enable hidden PING/PONG loop")
        self.sensory_pingpong_checkbox.setObjectName("sensory_pingpong_checkbox")
        self.sensory_pingpong_checkbox.setChecked(bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)))
        self.sensory_pingpong_checkbox.toggled.connect(self.on_sensory_pingpong_enabled_changed)

        self.sensory_allow_hidden_proactive_checkbox = QtWidgets.QCheckBox("Allow hidden PONGs to trigger proactive speech")
        self.sensory_allow_hidden_proactive_checkbox.setObjectName("sensory_allow_hidden_proactive_checkbox")
        self.sensory_allow_hidden_proactive_checkbox.setChecked(bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)))
        self.sensory_allow_hidden_proactive_checkbox.toggled.connect(self.on_sensory_allow_hidden_proactive_changed)

        self.sensory_allow_hidden_visual_checkbox = QtWidgets.QCheckBox("Allow NC to generate visual replies automatically")
        self.sensory_allow_hidden_visual_checkbox.setObjectName("sensory_allow_hidden_visual_checkbox")
        self.sensory_allow_hidden_visual_checkbox.setChecked(bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)))
        self.sensory_allow_hidden_visual_checkbox.toggled.connect(self.on_sensory_allow_hidden_visual_changed)

        self.sensory_pingpong_history_spin = ContextTokenStepper()
        self.sensory_pingpong_history_spin.setObjectName("sensory_pingpong_history_spin")
        self.sensory_pingpong_history_spin.setRange(0, 20)
        self.sensory_pingpong_history_spin.setSingleStep(1)
        self.sensory_pingpong_history_spin.setValue(max(0, int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3)))
        self.sensory_pingpong_history_spin.valueChanged.connect(self.on_sensory_pingpong_history_depth_changed)
        self.sensory_pingpong_history_spin.setMinimumWidth(112)
        self.sensory_pingpong_history_spin.setMaximumWidth(132)

        self.sensory_pingpong_prompt_text = QtWidgets.QPlainTextEdit()
        self.sensory_pingpong_prompt_text.setObjectName("sensory_pingpong_prompt_text")
        self.sensory_pingpong_prompt_text.setPlainText(str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")))
        self.sensory_pingpong_prompt_text.setPlaceholderText("Hidden PING/PONG prompt")
        self.sensory_pingpong_prompt_text.setMinimumHeight(0)
        self.sensory_pingpong_prompt_text.textChanged.connect(self.on_sensory_pingpong_prompt_changed)
        self.btn_sensory_pingpong_prompt_reset = QtWidgets.QPushButton("Use Recommended")
        self.btn_sensory_pingpong_prompt_reset.setObjectName("btn_sensory_pingpong_prompt_reset")
        self.btn_sensory_pingpong_prompt_reset.clicked.connect(self.reset_sensory_pingpong_prompt_to_default)

        self.musetalk_avatar_pack_combo = NoWheelComboBox()
        self.musetalk_avatar_pack_combo.setObjectName("musetalk_avatar_pack_combo")
        self.musetalk_avatar_pack_combo.currentTextChanged.connect(self.on_musetalk_avatar_pack_change)
        self.btn_musetalk_avatar_pack_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_musetalk_avatar_pack_refresh.setObjectName("btn_musetalk_avatar_pack_refresh")
        self.btn_musetalk_avatar_pack_refresh.clicked.connect(self.refresh_musetalk_avatar_pack_list)
        pack_row = QtWidgets.QHBoxLayout()
        pack_row.setContentsMargins(0, 0, 0, 0)
        pack_row.setSpacing(8)
        pack_row.addWidget(self.musetalk_avatar_pack_combo, 1)
        pack_row.addWidget(self.btn_musetalk_avatar_pack_refresh, 0)
        pack_row_widget = QtWidgets.QWidget()
        pack_row_widget.setLayout(pack_row)
        self.musetalk_avatar_pack_row_widget = pack_row_widget

        self.vam_vmc_enabled_checkbox = QtWidgets.QCheckBox("Relay motion to VaM over VMC")
        self.vam_vmc_enabled_checkbox.setObjectName("vam_vmc_enabled_checkbox")
        self.vam_vmc_enabled_checkbox.setChecked(bool(RUNTIME_CONFIG.get("vam_vmc_enabled", True)))
        self.vam_vmc_enabled_checkbox.toggled.connect(self.on_vam_vmc_enabled_changed)

        self.vam_bridge_enabled_checkbox = QtWidgets.QCheckBox("Enable VaM file bridge")
        self.vam_bridge_enabled_checkbox.setObjectName("vam_bridge_enabled_checkbox")
        self.vam_bridge_enabled_checkbox.setChecked(bool(RUNTIME_CONFIG.get("vam_bridge_enabled", True)))
        self.vam_bridge_enabled_checkbox.toggled.connect(self.on_vam_bridge_enabled_changed)

        self.vam_play_audio_in_vam_checkbox = QtWidgets.QCheckBox("Play speech audio through VaM head audio")
        self.vam_play_audio_in_vam_checkbox.setObjectName("vam_play_audio_in_vam_checkbox")
        self.vam_play_audio_in_vam_checkbox.setChecked(bool(RUNTIME_CONFIG.get("vam_play_audio_in_vam", True)))
        self.vam_play_audio_in_vam_checkbox.toggled.connect(self.on_vam_play_audio_in_vam_changed)

        self.vam_timeline_auto_resume_checkbox = QtWidgets.QCheckBox("Allow VaM Timeline auto-resume hooks")
        self.vam_timeline_auto_resume_checkbox.setObjectName("vam_timeline_auto_resume_checkbox")
        self.vam_timeline_auto_resume_checkbox.setChecked(bool(RUNTIME_CONFIG.get("vam_timeline_auto_resume", True)))
        self.vam_timeline_auto_resume_checkbox.toggled.connect(self.on_vam_timeline_auto_resume_changed)

        self.vam_vmc_host_edit = QtWidgets.QLineEdit()
        self.vam_vmc_host_edit.setObjectName("vam_vmc_host_edit")
        self.vam_vmc_host_edit.setText(str(RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1"))
        self.vam_vmc_host_edit.editingFinished.connect(self.on_vam_vmc_host_changed)

        self.vam_vmc_port_spin = NoWheelSpinBox()
        self.vam_vmc_port_spin.setObjectName("vam_vmc_port_spin")
        self.vam_vmc_port_spin.setRange(1, 65535)
        self.vam_vmc_port_spin.setSingleStep(1)
        self.vam_vmc_port_spin.setValue(int(RUNTIME_CONFIG.get("vam_vmc_port", 39539) or 39539))
        self.vam_vmc_port_spin.valueChanged.connect(self.on_vam_vmc_port_changed)

        self.vam_root_edit = QtWidgets.QLineEdit()
        self.vam_root_edit.setObjectName("vam_root_edit")
        self.vam_root_edit.setText(engine.normalize_vam_root(RUNTIME_CONFIG.get("vam_root", getattr(engine, "DEFAULT_VAM_ROOT", "")) or getattr(engine, "DEFAULT_VAM_ROOT", "")))
        if not self.vam_root_edit.text().strip():
            self.vam_root_edit.setText(engine.normalize_vam_root(DEFAULT_LOCAL_VAM_ROOT))
        self.vam_root_edit.setToolTip("Path to the VaM installation root. NC derives the bridge folder from this.")
        self.vam_root_edit.editingFinished.connect(self.on_vam_root_changed)

        self.vam_bridge_root_edit = QtWidgets.QLineEdit()
        self.vam_bridge_root_edit.setObjectName("vam_bridge_root_edit")
        self.vam_bridge_root_edit.setReadOnly(True)
        self.vam_bridge_root_edit.setText(engine.derive_vam_bridge_root(self.vam_root_edit.text().strip()))
        self.vam_bridge_root_edit.setToolTip("Derived from the VaM Root. The plugin's default Bridge Root already matches this location inside VaM.")

        self.vam_target_atom_uid_edit = QtWidgets.QLineEdit()
        self.vam_target_atom_uid_edit.setObjectName("vam_target_atom_uid_edit")
        self.vam_target_atom_uid_edit.setText(str(RUNTIME_CONFIG.get("vam_target_atom_uid", "Person") or "Person"))
        self.vam_target_atom_uid_edit.editingFinished.connect(self.on_vam_target_atom_uid_changed)

        self.vam_target_storable_id_edit = QtWidgets.QLineEdit()
        self.vam_target_storable_id_edit.setObjectName("vam_target_storable_id_edit")
        self.vam_target_storable_id_edit.setText(str(RUNTIME_CONFIG.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"))
        self.vam_target_storable_id_edit.editingFinished.connect(self.on_vam_target_storable_id_changed)

        self.chat_provider_combo = NoWheelComboBox()
        self.chat_provider_combo.setObjectName("chat_provider_combo")
        self._populate_chat_provider_combo(RUNTIME_CONFIG.get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID))
        self.chat_provider_combo.currentTextChanged.connect(self.on_chat_provider_changed)

        self.model_combo = NoWheelComboBox()
        self.model_combo.setObjectName("model_combo")
        self.model_combo.addItem("Scanning...")
        self.model_combo.currentTextChanged.connect(self.on_model_selection_changed)
        self.btn_model_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_model_refresh.setObjectName("btn_model_refresh")
        self.btn_model_refresh.clicked.connect(lambda: self.request_model_list_refresh(quiet=False, wait_for_reachable=True))
        self.model_requires_vision_checkbox = QtWidgets.QCheckBox("Must have image processing capabilities")
        self.model_requires_vision_checkbox.setObjectName("model_requires_vision_checkbox")
        self.model_requires_vision_checkbox.toggled.connect(self.on_model_requires_vision_changed)
        model_row = QtWidgets.QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(8)
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.btn_model_refresh, 0)
        model_row_widget = QtWidgets.QWidget()
        model_row_widget.setLayout(model_row)
        model_column = QtWidgets.QVBoxLayout()
        model_column.setContentsMargins(0, 0, 0, 0)
        model_column.setSpacing(4)
        model_column.addWidget(model_row_widget)
        model_column.addWidget(self.model_requires_vision_checkbox)
        self.model_row_widget = QtWidgets.QWidget()
        self.model_row_widget.setLayout(model_column)

        self.preset_combo = NoWheelComboBox()
        self.preset_combo.setObjectName("preset_combo")
        self.preset_combo.addItem("Select Preset...")
        self.preset_combo.currentTextChanged.connect(self.on_preset_selection_changed)
        self.btn_preset_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_preset_refresh.setObjectName("btn_preset_refresh")
        self.btn_preset_refresh.clicked.connect(self.refresh_preset_list)
        preset_row = QtWidgets.QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.btn_preset_refresh, 0)
        preset_row_widget = QtWidgets.QWidget()
        preset_row_widget.setLayout(preset_row)
        self.preset_row_widget = preset_row_widget

        self.allow_proactive_checkbox = QtWidgets.QCheckBox("Allow proactive replies after silence")
        self.allow_proactive_checkbox.setObjectName("allow_proactive_checkbox")
        self.allow_proactive_checkbox.setChecked(bool(RUNTIME_CONFIG.get("allow_proactive_replies", True)))
        self.allow_proactive_checkbox.toggled.connect(self.on_allow_proactive_replies_changed)

        self.require_first_user_checkbox = QtWidgets.QCheckBox("Wait for the first user message before any proactive reply")
        self.require_first_user_checkbox.setObjectName("require_first_user_checkbox")
        self.require_first_user_checkbox.setChecked(bool(RUNTIME_CONFIG.get("require_first_user_before_proactive", False)))
        self.require_first_user_checkbox.toggled.connect(self.on_require_first_user_before_proactive_changed)

        self.listen_idle_window_spin = DecimalStepper()
        self.listen_idle_window_spin.setObjectName("listen_idle_window_spin")
        self.listen_idle_window_spin.setRange(0.5, 30.0)
        self.listen_idle_window_spin.setSingleStep(0.5)
        self.listen_idle_window_spin.setDecimals(1)
        self.listen_idle_window_spin.setValue(float(RUNTIME_CONFIG.get("listen_idle_window_seconds", 5.0) or 5.0))
        self.listen_idle_window_spin.valueChanged.connect(self.on_listen_idle_window_changed)
        self.listen_idle_window_spin.setMinimumWidth(112)
        self.listen_idle_window_spin.setMaximumWidth(132)

        self.proactive_delay_spin = DecimalStepper()
        self.proactive_delay_spin.setObjectName("proactive_delay_spin")
        self.proactive_delay_spin.setRange(0.5, 180.0)
        self.proactive_delay_spin.setSingleStep(0.5)
        self.proactive_delay_spin.setDecimals(1)
        self.proactive_delay_spin.setValue(float(RUNTIME_CONFIG.get("proactive_delay_seconds", 10.0) or 10.0))
        self.proactive_delay_spin.valueChanged.connect(self.on_proactive_delay_changed)
        self.proactive_delay_spin.setMinimumWidth(112)
        self.proactive_delay_spin.setMaximumWidth(132)

        self.chat_context_window_spin = ContextTokenStepper()
        self.chat_context_window_spin.setObjectName("chat_context_window_spin")
        self.chat_context_window_spin.setRange(4, 200)
        self.chat_context_window_spin.setSingleStep(1)
        self.chat_context_window_spin.setValue(int(RUNTIME_CONFIG.get("chat_context_window_messages", 20) or 20))
        self.chat_context_window_spin.valueChanged.connect(self.on_chat_context_window_changed)
        self.chat_context_window_spin.setMinimumWidth(112)
        self.chat_context_window_spin.setMaximumWidth(132)

        self.stored_chat_history_limit_spin = ContextTokenStepper()
        self.stored_chat_history_limit_spin.setObjectName("stored_chat_history_limit_spin")
        self.stored_chat_history_limit_spin.setRange(0, 5000)
        self.stored_chat_history_limit_spin.setSingleStep(1)
        self.stored_chat_history_limit_spin.setValue(max(0, int(RUNTIME_CONFIG.get("stored_chat_history_limit", 0) or 0)))
        self.stored_chat_history_limit_spin.valueChanged.connect(self.on_stored_chat_history_limit_changed)
        self.stored_chat_history_limit_spin.setMinimumWidth(112)
        self.stored_chat_history_limit_spin.setMaximumWidth(132)

        self.chat_overflow_policy_combo = NoWheelComboBox()
        self.chat_overflow_policy_combo.setObjectName("chat_overflow_policy_combo")
        self.chat_overflow_policy_combo.addItems(["Rolling Window", "Truncate Middle", "Stop At Limit"])
        self.chat_overflow_policy_combo.setCurrentText(self._chat_overflow_policy_label_from_value(RUNTIME_CONFIG.get("chat_context_overflow_policy", "rolling_window")))
        self.chat_overflow_policy_combo.currentTextChanged.connect(self.on_chat_overflow_policy_changed)

        self.btn_save_chat_session = QtWidgets.QPushButton("Save Chat Context")
        self.btn_save_chat_session.setObjectName("btn_save_chat_session")
        self.btn_save_chat_session.clicked.connect(self.save_chat_context)

        self.btn_load_chat_session = QtWidgets.QPushButton("Load Chat Context")
        self.btn_load_chat_session.setObjectName("btn_load_chat_session")
        self.btn_load_chat_session.clicked.connect(self.load_chat_context)

        self.btn_reset_chat_session = QtWidgets.QPushButton("Reset Chat Memory")
        self.btn_reset_chat_session.setObjectName("btn_reset_chat_session")
        self.btn_reset_chat_session.clicked.connect(self.reset_chat_session)

        self.chat_session_hint = QtWidgets.QLabel()
        self.chat_session_hint.setObjectName("chat_session_hint")
        self.chat_session_hint.setWordWrap(True)
        self.chat_session_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")

        self.refresh_musetalk_avatar_pack_list()

        self.host_settings_tabs = NoWheelTabWidget()
        self.host_settings_tabs.setObjectName("host_settings_tabs")
        self.host_settings_tabs.setMinimumSize(0, 0)
        self.host_settings_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
        self.host_settings_tabs.currentChanged.connect(lambda _index, tabs=self.host_settings_tabs: self._sync_tab_widget_height(tabs))
        self.host_settings_tabs.addTab(self._build_runtime_shell_tab(), "Host")
        self.host_settings_tabs.addTab(self._build_sensory_feedback_tab(), "Vision")
        self.host_settings_tabs.addTab(self._build_chat_session_tab(), "Chat")
        layout.addWidget(self.host_settings_tabs, 0, QtCore.Qt.AlignTop)
        QtCore.QTimer.singleShot(0, lambda tabs=self.host_settings_tabs: self._sync_tab_widget_height(tabs))
        layout.addStretch(1)

        self.tabs = NoWheelTabWidget()
        self.tabs.setObjectName("left_tabs")
        self.tabs.setMinimumSize(0, 0)
        self.tabs.currentChanged.connect(self._on_left_tab_changed)
        self.tabs.addTab(self._build_persona_tab(), "Persona")
        self.tabs.addTab(self._build_vseeface_tab(), "VSeeFace")
        self.tabs.addTab(self._build_musetalk_parent_tab(), "MuseTalk")
        self.tabs.addTab(self._build_vam_tab(), "VaM")
        self._legacy_brain_tab = self._build_brain_tab()
        self._legacy_brain_tab.setVisible(False)
        self.tabs.addTab(self._build_chunking_tab(), "Chunking")
        self.tabs.addTab(self._build_dry_run_tab(), "Dry Run")
        self.tabs.addTab(self._build_tutorials_tab(), "Tutorials")
        self.tabs.addTab(self._build_addons_tab(), "Addons")
        self.tabs.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        workspace_panel = self._wrap_panel()
        workspace_panel.setMinimumSize(0, 0)
        workspace_panel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        workspace_outer_layout = QtWidgets.QVBoxLayout(workspace_panel)
        workspace_outer_layout.setContentsMargins(0, 0, 0, 0)
        workspace_outer_layout.setSpacing(0)
        workspace_outer_layout.addWidget(self.tabs, 1)

        return shaping_panel, workspace_panel

    def _build_runtime_shell_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        form.addRow("Avatar Engine", self.engine_combo)
        form.addRow("Input Mode", self.input_mode_combo)
        form.addRow("Input Role", self.input_role_combo)
        form.addRow("Stream Mode", self.stream_mode_combo)
        form.addRow("MuseTalk VRAM", self.musetalk_vram_combo)
        form.addRow("Loop Fade (ms)", self._wrap_compact_form_field(self.musetalk_loop_fade_spin))
        form.addRow("MuseTalk Avatar", self.musetalk_avatar_pack_row_widget)
        form.addRow("Preset", self.preset_row_widget if hasattr(self, "preset_row_widget") else self.preset_combo)
        layout.addLayout(form)
        layout.addWidget(self._build_chat_runtime_card())
        layout.addWidget(self._build_tts_runtime_card())

        preset_buttons = QtWidgets.QHBoxLayout()
        for label, object_name, handler in [
            ("Load", "btn_preset_load", self.load_preset),
            ("Save", "btn_preset_save", self.save_current_preset),
            ("Save As", "btn_preset_save_as", self.save_preset_dialog),
            ("Delete", "btn_preset_delete", self.delete_current_preset),
        ]:
            button = QtWidgets.QPushButton(label)
            button.setObjectName(object_name)
            button.clicked.connect(handler)
            if object_name == "btn_preset_save":
                self.btn_preset_save = button
            elif object_name == "btn_preset_save_as":
                self.btn_preset_save_as = button
            preset_buttons.addWidget(button)
        layout.addLayout(preset_buttons)

        self.input_mode_hint = QtWidgets.QLabel("Push-to-Talk hotkey: Right Ctrl (fallback button below)")
        self.input_mode_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(self.input_mode_hint)

        utility_row = QtWidgets.QHBoxLayout()
        utility_row.setSpacing(8)
        self.btn_musetalk_preview = QtWidgets.QPushButton("Show MuseTalk Preview")
        self.btn_musetalk_preview.setObjectName("btn_musetalk_preview")
        self.btn_musetalk_preview.clicked.connect(self.show_musetalk_preview)
        self.btn_musetalk_preview.setEnabled(False)
        self.btn_musetalk_avatar_focus = QtWidgets.QPushButton("Avatar Focus")
        self.btn_musetalk_avatar_focus.setObjectName("btn_musetalk_avatar_focus")
        self.btn_musetalk_avatar_focus.clicked.connect(self.toggle_musetalk_avatar_focus)
        self.btn_musetalk_avatar_focus.setEnabled(False)
        self.btn_visual_reply = QtWidgets.QPushButton("Show Visual Reply")
        self.btn_visual_reply.setObjectName("btn_visual_reply")
        self.btn_visual_reply.clicked.connect(self.show_visual_reply_dock)
        self.btn_push_to_talk = QtWidgets.QPushButton("Hold To Talk")
        self.btn_push_to_talk.setObjectName("btn_push_to_talk")
        self.btn_push_to_talk.pressed.connect(lambda: engine.set_push_to_talk_hold(True))
        self.btn_push_to_talk.released.connect(lambda: engine.set_push_to_talk_hold(False))
        self.btn_push_to_talk.setEnabled(False)
        utility_row.addWidget(self.btn_musetalk_preview)
        utility_row.addWidget(self.btn_musetalk_avatar_focus)
        utility_row.addWidget(self.btn_visual_reply)
        utility_row.addWidget(self.btn_push_to_talk)
        layout.addLayout(utility_row)

        self.performance_guidance_toggle = QtWidgets.QPushButton("Show Performance Guidance")
        self.performance_guidance_toggle.setObjectName("btn_toggle_performance_guidance")
        self.performance_guidance_toggle.setCheckable(True)
        self.performance_guidance_toggle.toggled.connect(self._toggle_performance_guidance)
        layout.addWidget(self.performance_guidance_toggle)

        self.guidance_box = QtWidgets.QGroupBox("Performance Guidance")
        guidance_layout = QtWidgets.QVBoxLayout(self.guidance_box)
        guidance_layout.setContentsMargins(12, 14, 12, 12)
        guidance_layout.setSpacing(8)

        self.stream_hint_label = QtWidgets.QLabel("Chatterbox sounds more expressive; PocketTTS may start faster.")
        self.stream_hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self.stream_hint_label.setWordWrap(True)
        guidance_layout.addWidget(self.stream_hint_label)

        self.musetalk_vram_hint = QtWidgets.QLabel(
            "Quality keeps Whisper on GPU and larger batches; lower VRAM modes trade speed/quality for memory."
        )
        self.musetalk_vram_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self.musetalk_vram_hint.setWordWrap(True)
        guidance_layout.addWidget(self.musetalk_vram_hint)

        context_row = QtWidgets.QHBoxLayout()
        context_row.setSpacing(8)
        context_label = QtWidgets.QLabel("Check context:")
        context_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
        self.model_context_input = ContextTokenStepper()
        self.model_context_input.setObjectName("model_context_input")
        self.model_context_input.setRange(512, 131072)
        self.model_context_input.setSingleStep(512)
        self.model_context_input.setAccelerated(True)
        self.model_context_input.setValue(8192)
        self.model_context_input.valueChanged.connect(self.on_model_context_input_changed)
        self.model_context_input.setMinimumWidth(132)
        context_suffix = QtWidgets.QLabel("tokens")
        context_suffix.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        context_row.addWidget(context_label)
        context_row.addWidget(self.model_context_input, 0)
        context_row.addWidget(context_suffix)
        context_row.addStretch(1)
        guidance_layout.addLayout(context_row)

        self.model_budget_label = QtWidgets.QLabel("Model advisor: checking hardware budget...")
        self.model_budget_label.setObjectName("model_budget_label")
        self.model_budget_label.setWordWrap(True)
        self.model_budget_label.setTextFormat(QtCore.Qt.RichText)
        self.model_budget_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        guidance_layout.addWidget(self.model_budget_label)

        self.guidance_box.setVisible(False)
        layout.addWidget(self.guidance_box)
        layout.addStretch(1)
        return tab

    def _build_visual_reply_settings_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        visual_box = QtWidgets.QGroupBox("Visual Replies")
        visual_layout = QtWidgets.QVBoxLayout(visual_box)
        visual_layout.setContentsMargins(12, 14, 12, 12)
        visual_layout.setSpacing(8)

        visual_form = QtWidgets.QFormLayout()
        visual_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        visual_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        visual_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        visual_form.addRow("Mode", self.visual_reply_mode_combo)
        visual_form.addRow("Provider", self.visual_reply_provider_combo)
        visual_form.addRow("Image Size", self.visual_reply_size_combo)
        visual_form.addRow("Image Model", self.visual_reply_model_edit)
        visual_layout.addLayout(visual_form)
        visual_layout.addWidget(self.visual_reply_auto_show_checkbox)

        self.visual_reply_hint = QtWidgets.QLabel()
        self.visual_reply_hint.setObjectName("visual_reply_hint")
        self.visual_reply_hint.setWordWrap(True)
        self.visual_reply_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        visual_layout.addWidget(self.visual_reply_hint)
        self._refresh_visual_reply_hint()

        layout.addWidget(visual_box)
        layout.addStretch(1)
        return tab

    def _build_chat_runtime_card(self):
        self.chat_runtime_box = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.chat_runtime_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        def _make_inner_card(object_name):
            card = QtWidgets.QFrame()
            card.setObjectName(object_name)
            card.setStyleSheet(
                f"QFrame#{object_name} {{"
                "  background: rgba(12, 18, 26, 0.35);"
                "  border: 1px solid #273342;"
                "  border-radius: 10px;"
                "}"
            )
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(8)
            return card, card_layout

        self.chat_runtime_inner_card = QtWidgets.QFrame()
        self.chat_runtime_inner_card.setObjectName("chat_runtime_inner_card")
        self.chat_runtime_inner_card.setStyleSheet(
            "QFrame#chat_runtime_inner_card {"
            "  background: rgba(12, 18, 26, 0.55);"
            "  border: 1px solid #273342;"
            "  border-radius: 12px;"
            "}"
        )
        inner_layout = QtWidgets.QVBoxLayout(self.chat_runtime_inner_card)
        inner_layout.setContentsMargins(12, 12, 12, 12)
        inner_layout.setSpacing(10)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        form.addRow("Chat Provider", self.chat_provider_combo)
        form.addRow("LLM Model", self.model_row_widget)
        inner_layout.addLayout(form)

        self.chat_provider_fields_widget = QtWidgets.QWidget()
        self.chat_provider_fields_layout = QtWidgets.QFormLayout(self.chat_provider_fields_widget)
        self.chat_provider_fields_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_provider_fields_layout.setSpacing(8)
        self.chat_provider_fields_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.chat_provider_fields_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.chat_provider_settings_card, self.chat_provider_settings_card_layout = _make_inner_card(
            "chat_provider_settings_card"
        )
        self.chat_provider_settings_card_layout.addWidget(self.chat_provider_fields_widget)
        self.chat_provider_settings_section = CollapsibleSection(
            "Provider Settings",
            self.chat_provider_settings_card,
            expanded=True,
        )
        inner_layout.addWidget(self.chat_provider_settings_section)

        self.chat_provider_generation_fields_widget = QtWidgets.QWidget()
        self.chat_provider_generation_fields_layout = QtWidgets.QFormLayout(self.chat_provider_generation_fields_widget)
        self.chat_provider_generation_fields_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_provider_generation_fields_layout.setSpacing(8)
        self.chat_provider_generation_fields_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.chat_provider_generation_fields_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.chat_provider_generation_card, self.chat_provider_generation_card_layout = _make_inner_card(
            "chat_provider_generation_card"
        )
        self.chat_provider_generation_card_layout.addWidget(self.chat_provider_generation_fields_widget)
        self.chat_provider_generation_section = CollapsibleSection(
            "Generation Settings",
            self.chat_provider_generation_card,
            expanded=False,
        )
        inner_layout.addWidget(self.chat_provider_generation_section)

        self.chat_provider_hint_label = QtWidgets.QLabel()
        self.chat_provider_hint_label.setWordWrap(True)
        self.chat_provider_hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        inner_layout.addWidget(self.chat_provider_hint_label)

        layout.addWidget(self.chat_runtime_inner_card)

        self._refresh_chat_provider_card()
        self.chat_runtime_section = CollapsibleSection("Chat Runtime", self.chat_runtime_box, expanded=True)
        self.chat_runtime_section.toggle_button.toggled.connect(lambda _checked: self._on_runtime_section_toggled())
        self._refresh_chat_runtime_summary()
        return self.chat_runtime_section

    def _build_tts_runtime_card(self):
        self.tts_runtime_box = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.tts_runtime_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.tts_runtime_inner_card = QtWidgets.QFrame()
        self.tts_runtime_inner_card.setObjectName("tts_runtime_inner_card")
        self.tts_runtime_inner_card.setStyleSheet(
            "QFrame#tts_runtime_inner_card {"
            "  background: rgba(12, 18, 26, 0.35);"
            "  border: 1px solid #273342;"
            "  border-radius: 10px;"
            "}"
        )
        inner_layout = QtWidgets.QVBoxLayout(self.tts_runtime_inner_card)
        inner_layout.setContentsMargins(10, 10, 10, 10)
        inner_layout.setSpacing(12)

        backend_block = QtWidgets.QWidget()
        backend_form = QtWidgets.QFormLayout(backend_block)
        backend_form.setContentsMargins(0, 0, 0, 0)
        backend_form.setSpacing(8)
        backend_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        backend_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        backend_form.addRow("TTS Backend", self.tts_backend_combo)
        inner_layout.addWidget(backend_block)
        inner_layout.addSpacing(2)

        self.tts_runtime_addon_tabs = QtWidgets.QTabWidget()
        self.tts_runtime_addon_tabs.setDocumentMode(True)
        self.tts_runtime_addon_tabs.currentChanged.connect(self._on_tts_runtime_addon_tab_changed)
        self.tts_runtime_addon_tabs.setVisible(False)
        inner_layout.addWidget(self.tts_runtime_addon_tabs)

        self.tts_runtime_hint_label = QtWidgets.QLabel(
            "TTS backend controls are now provided by addon tabs in this card."
        )
        self.tts_runtime_hint_label.setWordWrap(True)
        self.tts_runtime_hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        inner_layout.addWidget(self.tts_runtime_hint_label)

        layout.addWidget(self.tts_runtime_inner_card)

        self._refresh_tts_runtime_card()
        self.tts_runtime_section = CollapsibleSection("TTS Runtime", self.tts_runtime_box, expanded=True)
        self.tts_runtime_section.toggle_button.toggled.connect(lambda _checked: self._on_runtime_section_toggled())
        self._refresh_tts_runtime_summary()
        return self.tts_runtime_section

    def _build_sensory_feedback_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.sensory_feedback_tabs = NoWheelTabWidget()
        self.sensory_feedback_tabs.setObjectName("sensory_feedback_tabs")
        self.sensory_feedback_tabs.setMinimumSize(0, 0)
        self.sensory_feedback_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.sensory_feedback_tabs.currentChanged.connect(lambda _index, tabs=self.sensory_feedback_tabs: self._sync_tab_widget_height(tabs))

        core_tab = QtWidgets.QWidget()
        core_layout = QtWidgets.QVBoxLayout(core_tab)
        core_layout.setContentsMargins(8, 8, 8, 8)
        core_layout.setSpacing(10)

        sensory_box = QtWidgets.QGroupBox("Hidden Sensory Feedback")
        sensory_layout = QtWidgets.QVBoxLayout(sensory_box)
        sensory_layout.setContentsMargins(12, 14, 12, 12)
        sensory_layout.setSpacing(8)

        sensory_form = QtWidgets.QFormLayout()
        sensory_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        sensory_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        sensory_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        sensory_form.addRow("Include", self.sensory_feedback_sources_widget)
        sensory_form.addRow("Refresh (s)", self._wrap_compact_form_field(self.sensory_feedback_interval_spin))
        sensory_form.addRow("Retain PONGs", self._wrap_compact_form_field(self.sensory_pingpong_history_spin))
        sensory_layout.addWidget(self.sensory_pingpong_checkbox)
        sensory_layout.addWidget(self.sensory_allow_hidden_proactive_checkbox)
        sensory_layout.addWidget(self.sensory_allow_hidden_visual_checkbox)
        sensory_layout.addLayout(sensory_form)

        self.sensory_feedback_hint = QtWidgets.QLabel()
        self.sensory_feedback_hint.setObjectName("sensory_feedback_hint")
        self.sensory_feedback_hint.setWordWrap(True)
        self.sensory_feedback_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        sensory_layout.addWidget(self.sensory_feedback_hint)
        self._refresh_sensory_feedback_hint()

        self.sensory_pingpong_prompt_label = QtWidgets.QLabel("Core Hidden PING/PONG Prompt")
        self.sensory_pingpong_prompt_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
        prompt_header = QtWidgets.QHBoxLayout()
        prompt_header.setContentsMargins(0, 0, 0, 0)
        prompt_header.setSpacing(8)
        prompt_header.addWidget(self.sensory_pingpong_prompt_label)
        prompt_header.addStretch(1)
        prompt_header.addWidget(self.btn_sensory_pingpong_prompt_reset, 0)
        sensory_layout.addLayout(prompt_header)
        sensory_layout.addWidget(self.sensory_pingpong_prompt_text)

        self.sensory_pingpong_prompt_hint = QtWidgets.QLabel("Core prompt defines the shared JSON contract. Source tabs add source-specific guidance. Use __EMOTION_LIST__ to inject the currently available avatar emotion tags.")
        self.sensory_pingpong_prompt_hint.setWordWrap(True)
        self.sensory_pingpong_prompt_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        sensory_layout.addWidget(self.sensory_pingpong_prompt_hint)

        core_layout.addWidget(sensory_box)
        self.sensory_feedback_tabs.addTab(core_tab, "Core")
        self._refresh_sensory_feedback_source_tabs()
        layout.addWidget(self.sensory_feedback_tabs, 0, QtCore.Qt.AlignTop)
        return tab

    def _build_chat_session_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        behavior_box = QtWidgets.QGroupBox("Conversation Flow")
        behavior_layout = QtWidgets.QVBoxLayout(behavior_box)
        behavior_layout.setContentsMargins(12, 14, 12, 12)
        behavior_layout.setSpacing(8)
        behavior_layout.addWidget(self.allow_proactive_checkbox)
        behavior_layout.addWidget(self.require_first_user_checkbox)

        timing_form = QtWidgets.QFormLayout()
        timing_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        timing_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        timing_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        timing_form.addRow("Idle wait window (s)", self.listen_idle_window_spin)
        timing_form.addRow("Proactive delay (s)", self.proactive_delay_spin)
        timing_form.addRow("Context window (msgs)", self.chat_context_window_spin)
        timing_form.addRow("Stored history limit", self.stored_chat_history_limit_spin)
        timing_form.addRow("Overflow policy", self.chat_overflow_policy_combo)
        behavior_layout.addLayout(timing_form)
        behavior_layout.addWidget(self.chat_session_hint)
        layout.addWidget(behavior_box)

        actions_box = QtWidgets.QGroupBox("Session")
        actions_layout = QtWidgets.QVBoxLayout(actions_box)
        actions_layout.setContentsMargins(12, 14, 12, 12)
        actions_layout.setSpacing(8)
        reset_hint = QtWidgets.QLabel("Clear conversation memory when you want to restart the current chat without restarting the whole app.")
        reset_hint.setWordWrap(True)
        reset_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        actions_layout.addWidget(reset_hint)
        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self.btn_save_chat_session)
        button_row.addWidget(self.btn_load_chat_session)
        button_row.addWidget(self.btn_reset_chat_session)
        button_row.addStretch(1)
        actions_layout.addLayout(button_row)
        layout.addWidget(actions_box)

        self._refresh_chat_session_hint()
        layout.addStretch(1)
        return tab

    def _chat_overflow_policy_value_from_label(self, label):
        text = str(label or "").strip().lower()
        if text == "truncate middle":
            return "truncate_middle"
        if text == "stop at limit":
            return "stop_at_limit"
        return "rolling_window"

    def _chat_overflow_policy_label_from_value(self, value):
        policy = str(value or "rolling_window").strip().lower()
        if policy == "truncate_middle":
            return "Truncate Middle"
        if policy == "stop_at_limit":
            return "Stop At Limit"
        return "Rolling Window"

    def _chat_font_size_choices(self):
        return [8, 10, 12, 14, 16, 18, 20]

    def _current_chat_font_size(self):
        if hasattr(self, "chat_font_size_combo"):
            data = self.chat_font_size_combo.currentData()
            if data is not None:
                try:
                    return max(8, min(20, int(data)))
                except Exception:
                    pass
        if hasattr(self, "chat_edit"):
            size = int(self.chat_edit.font().pointSize() or 0)
            if size > 0:
                return size
        return 12

    def _apply_chat_font_size(self, size, *, update_combo=True):
        font_size = max(8, min(20, int(size)))
        font = QtGui.QFont("Segoe UI", font_size)
        if hasattr(self, "chat_edit"):
            self.chat_edit.setFont(font)
            if hasattr(self.chat_edit, "document"):
                self.chat_edit.document().setDefaultFont(font)
        if update_combo and hasattr(self, "chat_font_size_combo"):
            index = self.chat_font_size_combo.findData(font_size)
            if index >= 0 and self.chat_font_size_combo.currentIndex() != index:
                previous = self.chat_font_size_combo.blockSignals(True)
                try:
                    self.chat_font_size_combo.setCurrentIndex(index)
                finally:
                    self.chat_font_size_combo.blockSignals(previous)

    def _chat_context_usage_label(self):
        used = len(list(getattr(engine, "conversation_history", []) or []))
        limit = int(RUNTIME_CONFIG.get("chat_context_window_messages", 20) or 20)
        capped = used > limit
        text = f"context {used}/{limit}"
        if capped:
            policy = self._chat_overflow_policy_label_from_value(RUNTIME_CONFIG.get("chat_context_overflow_policy", "rolling_window"))
            text = f"{text} ({policy})"
        return text, capped


    def _chat_provider_label_from_value(self, value):
        return chat_providers.provider_label(value or chat_providers.DEFAULT_PROVIDER_ID)

    def _chat_provider_value_from_label(self, label):
        text = str(label or "").strip()
        if hasattr(self, "chat_provider_combo"):
            for index in range(self.chat_provider_combo.count()):
                if str(self.chat_provider_combo.itemText(index) or "").strip() == text:
                    data = self.chat_provider_combo.itemData(index)
                    return chat_providers.normalize_provider_id(data, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        return chat_providers.normalize_provider_id(text, fallback=chat_providers.DEFAULT_PROVIDER_ID)

    def _current_chat_provider_value(self):
        if hasattr(self, "chat_provider_combo"):
            provider_value = self.chat_provider_combo.currentData()
            if provider_value:
                return chat_providers.normalize_provider_id(provider_value, fallback=chat_providers.DEFAULT_PROVIDER_ID)
            return self._chat_provider_value_from_label(self.chat_provider_combo.currentText())
        return chat_providers.normalize_provider_id(
            RUNTIME_CONFIG.get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )

    def _chat_provider_summaries(self):
        return [provider.to_summary() for provider in chat_providers.list_providers()]

    def _populate_chat_provider_combo(self, selected_value=None):
        if not hasattr(self, "chat_provider_combo"):
            return
        current_value = chat_providers.normalize_provider_id(
            selected_value if selected_value is not None else RUNTIME_CONFIG.get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )
        summaries = list(self._chat_provider_summaries())
        self.chat_provider_combo.blockSignals(True)
        self.chat_provider_combo.clear()
        for summary in summaries:
            label = str(summary.get("label") or summary.get("id") or "").strip()
            provider_id = str(summary.get("id") or "").strip()
            if label and provider_id:
                self.chat_provider_combo.addItem(label, provider_id)
        target_index = self.chat_provider_combo.findData(current_value)
        if target_index < 0 and self.chat_provider_combo.count():
            target_index = 0
        if target_index >= 0:
            self.chat_provider_combo.setCurrentIndex(target_index)
        self.chat_provider_combo.blockSignals(False)

    def _set_chat_provider_selection(self, provider_value):
        if not hasattr(self, "chat_provider_combo"):
            return chat_providers.normalize_provider_id(provider_value, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        normalized = chat_providers.normalize_provider_id(provider_value, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        index = self.chat_provider_combo.findData(normalized)
        if index < 0:
            self._populate_chat_provider_combo(normalized)
            index = self.chat_provider_combo.findData(normalized)
        if index >= 0:
            self.chat_provider_combo.setCurrentIndex(index)
        return normalized

    def _chat_provider_error_placeholder(self, provider_value=None):
        target = provider_value if provider_value is not None else self._current_chat_provider_value()
        return chat_providers.provider_model_error(target)

    def _is_model_catalog_placeholder(self, model_name):
        value = str(model_name or "").strip()
        lowered = value.lower()
        return (not value) or lowered in {"scanning...", "no models", "no vision models"} or lowered.startswith("error: check ")

    def _current_chat_provider_settings_map(self):
        raw = RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}
        return {str(key or "").strip().lower(): dict(value or {}) for key, value in raw.items() if str(key or "").strip()}

    def _current_chat_provider_settings_for(self, provider_id=None):
        provider_key = self._current_chat_provider_value() if provider_id is None else chat_providers.normalize_provider_id(provider_id, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        return dict(self._current_chat_provider_settings_map().get(provider_key, {}))

    def _set_current_chat_provider_settings_for(self, provider_id, updates):
        provider_key = chat_providers.normalize_provider_id(provider_id, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        settings_map = self._current_chat_provider_settings_map()
        next_values = {
            str(field_id or "").strip(): str(value or "").strip()
            for field_id, value in dict(updates or {}).items()
            if str(field_id or "").strip()
        }
        if next_values:
            settings_map[provider_key] = next_values
        elif provider_key in settings_map:
            settings_map.pop(provider_key, None)
        update_runtime_config("chat_provider_settings", settings_map)

    def _chat_provider_metadata(self, provider_id=None):
        target = provider_id if provider_id is not None else self._current_chat_provider_value()
        return chat_providers.provider_metadata(target)

    def _chat_provider_config_fields(self, provider_id=None):
        metadata = self._chat_provider_metadata(provider_id)
        fields = list(metadata.get("config_fields") or [])
        return [dict(item) for item in fields if isinstance(item, dict)]

    def _current_chat_provider_generation_settings_map(self):
        raw = RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {}
        return {
            str(key or "").strip().lower(): dict(value or {})
            for key, value in raw.items()
            if str(key or "").strip() and isinstance(value, dict)
        }

    def _current_chat_provider_generation_settings_for(self, provider_id=None):
        provider_key = self._current_chat_provider_value() if provider_id is None else chat_providers.normalize_provider_id(provider_id, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        return dict(self._current_chat_provider_generation_settings_map().get(provider_key, {}))

    def _set_current_chat_provider_generation_settings_for(self, provider_id, updates):
        provider_key = chat_providers.normalize_provider_id(provider_id, fallback=chat_providers.DEFAULT_PROVIDER_ID)
        settings_map = self._current_chat_provider_generation_settings_map()
        next_values = {}
        for field_id, value in dict(updates or {}).items():
            key = str(field_id or "").strip()
            if not key:
                continue
            if value is None or value == "":
                continue
            next_values[key] = value
        if next_values:
            settings_map[provider_key] = next_values
        else:
            settings_map.pop(provider_key, None)
        update_runtime_config("chat_provider_generation_settings", settings_map)

    def _chat_provider_generation_fields(self, provider_id=None):
        metadata = self._chat_provider_metadata(provider_id)
        fields = list(metadata.get("generation_fields") or [])
        return [dict(item) for item in fields if isinstance(item, dict)]

    def _legacy_generation_value_for_field(self, provider_id, field):
        field_id = str(field.get("id") or "").strip()
        if field_id in {"temperature", "top_p", "repeat_penalty", "min_p"}:
            return float(RUNTIME_CONFIG.get(field_id, field.get("default", 0.0)) or 0.0)
        if field_id == "top_k":
            return int(RUNTIME_CONFIG.get("top_k", field.get("default", 0)) or 0)
        if field_id in {"max_tokens", "max_completion_tokens"}:
            provider_settings = self._current_chat_provider_settings_for(provider_id)
            if "max_tokens" in provider_settings:
                return provider_settings.get("max_tokens")
            if bool(RUNTIME_CONFIG.get("limit_response_length", False)):
                return int(RUNTIME_CONFIG.get("max_response_tokens", field.get("default", DEFAULT_MAX_RESPONSE_TOKENS)) or DEFAULT_MAX_RESPONSE_TOKENS)
        return field.get("default", "")

    def _generation_field_display_value(self, provider_id, field, current_settings):
        field_id = str(field.get("id") or "").strip()
        if field_id in current_settings:
            return current_settings.get(field_id)
        return self._legacy_generation_value_for_field(provider_id, field)

    def _generation_field_widget_value(self, field, widget):
        kind = str(field.get("kind") or "text").strip().lower()
        if isinstance(widget, QtWidgets.QCheckBox):
            return bool(widget.isChecked())
        if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, QtWidgets.QComboBox):
            data = widget.currentData()
            return data if data is not None else widget.currentText()
        if isinstance(widget, QtWidgets.QLineEdit):
            value = widget.text().strip()
            if kind == "int" and value:
                try:
                    return int(value)
                except ValueError:
                    return value
            if kind == "float" and value:
                try:
                    return float(value)
                except ValueError:
                    return value
            return value
        return None

    def _apply_legacy_generation_mirror(self, field_id, value):
        try:
            if field_id in {"temperature", "top_p", "repeat_penalty", "min_p"}:
                update_runtime_config(field_id, float(value))
                if field_id in getattr(self, "brain_sliders", {}):
                    self.brain_sliders[field_id].set_value(float(value))
            elif field_id == "top_k":
                update_runtime_config("top_k", int(value))
                if "top_k" in getattr(self, "brain_sliders", {}):
                    self.brain_sliders["top_k"].set_value(int(value))
            elif field_id in {"max_tokens", "max_completion_tokens"} and int(value) > 0:
                update_runtime_config("limit_response_length", True)
                update_runtime_config("max_response_tokens", int(value))
                if hasattr(self, "limit_response_checkbox"):
                    self.limit_response_checkbox.blockSignals(True)
                    self.limit_response_checkbox.setChecked(True)
                    self.limit_response_checkbox.blockSignals(False)
                if hasattr(self, "max_response_tokens_spin"):
                    self.max_response_tokens_spin.blockSignals(True)
                    self.max_response_tokens_spin.setValue(int(value))
                    self.max_response_tokens_spin.blockSignals(False)
        except Exception:
            pass

    def _refresh_chat_provider_generation_card(self):
        if not hasattr(self, "chat_provider_generation_fields_layout"):
            return
        while self.chat_provider_generation_fields_layout.rowCount():
            self.chat_provider_generation_fields_layout.removeRow(0)
        self._chat_provider_generation_field_widgets = {}
        self._chat_provider_generation_field_meta = {}

        provider_id = self._current_chat_provider_value()
        current_settings = self._current_chat_provider_generation_settings_for(provider_id)
        fields = list(self._chat_provider_generation_fields(provider_id))

        if not fields:
            hint = QtWidgets.QLabel("This provider uses legacy generation controls internally.")
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            hint.setWordWrap(True)
            self.chat_provider_generation_fields_layout.addRow("", hint)
            if hasattr(self, "chat_provider_generation_section"):
                self.chat_provider_generation_section.setSummary("legacy fallback controls")
            return

        active_labels = []
        for field in fields:
            field_id = str(field.get("id") or "").strip()
            if not field_id:
                continue
            label = str(field.get("label") or field_id.replace("_", " ").title()).strip()
            kind = str(field.get("kind") or "text").strip().lower()
            value = self._generation_field_display_value(provider_id, field, current_settings)
            if kind == "note":
                editor = QtWidgets.QLabel(str(field.get("text") or field.get("description") or ""))
                editor.setWordWrap(True)
                editor.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            elif kind == "bool":
                editor = QtWidgets.QCheckBox(label)
                editor.setChecked(bool(value))
                editor.toggled.connect(lambda _checked, fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))
                label = ""
            elif kind == "select":
                editor = NoWheelComboBox()
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
                editor.currentIndexChanged.connect(lambda _index, fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))
            elif kind == "int":
                editor = NoWheelSpinBox()
                min_value = field.get("min", -999999)
                max_value = field.get("max", 999999)
                step_value = field.get("step", 1)
                editor.setRange(int(min_value), int(max_value))
                editor.setSingleStep(int(step_value or 1))
                editor.setValue(int(value if value not in {None, ""} else field.get("default", 0)))
                editor.valueChanged.connect(lambda _value, fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))
            elif kind == "float":
                editor = NoWheelDoubleSpinBox()
                min_value = field.get("min", -999999.0)
                max_value = field.get("max", 999999.0)
                step_value = field.get("step", 0.01)
                editor.setRange(float(min_value), float(max_value))
                editor.setDecimals(int(field.get("decimals", 2) or 2))
                editor.setSingleStep(float(step_value or 0.01))
                editor.setValue(float(value if value not in {None, ""} else field.get("default", 0.0)))
                editor.valueChanged.connect(lambda _value, fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))
            else:
                editor = QtWidgets.QLineEdit()
                editor.setText(str(value if value is not None else ""))
                placeholder = field.get("placeholder")
                if placeholder:
                    editor.setPlaceholderText(str(placeholder))
                editor.editingFinished.connect(lambda fid=field_id, widget=editor, meta=dict(field), pid=provider_id: self._on_chat_provider_generation_field_changed(pid, fid, widget, meta))

            tooltip = str(field.get("description") or "").strip()
            if tooltip:
                editor.setToolTip(tooltip)
            self.chat_provider_generation_fields_layout.addRow(label, editor)
            if kind != "note":
                self._chat_provider_generation_field_widgets[field_id] = editor
                self._chat_provider_generation_field_meta[field_id] = dict(field)
                active_labels.append(label or str(field.get("label") or field_id))

        if hasattr(self, "chat_provider_generation_section"):
            summary = ", ".join(active_labels[:3])
            if len(active_labels) > 3:
                summary += f", +{len(active_labels) - 3}"
            self.chat_provider_generation_section.setSummary(summary)

    def _refresh_chat_provider_card(self):
        if not hasattr(self, "chat_provider_fields_layout"):
            return
        while self.chat_provider_fields_layout.rowCount():
            self.chat_provider_fields_layout.removeRow(0)
        self._chat_provider_field_widgets = {}
        self._chat_provider_field_meta = {}

        provider_id = self._current_chat_provider_value()
        current_settings = self._current_chat_provider_settings_for(provider_id)
        fields = list(self._chat_provider_config_fields(provider_id))

        if fields:
            for field in fields:
                field_id = str(field.get("id") or "").strip()
                if not field_id:
                    continue
                label = str(field.get("label") or field_id.replace("_", " ").title()).strip()
                kind = str(field.get("kind") or "").strip().lower()
                if not kind:
                    kind = "password" if "key" in field_id.lower() or "token" in field_id.lower() else "text"
                editor = QtWidgets.QLineEdit()
                editor.setObjectName(f"chat_provider_field_{field_id}")
                if kind == "password":
                    editor.setEchoMode(QtWidgets.QLineEdit.Password)
                default_value = str(current_settings.get(field_id) or field.get("default") or "").strip()
                editor.setText(default_value)
                placeholder = field.get("placeholder")
                if placeholder:
                    editor.setPlaceholderText(str(placeholder))
                env_names = list(field.get("env") or [])
                tooltip_parts = []
                if env_names:
                    tooltip_parts.append("Env: " + ", ".join(str(name) for name in env_names if str(name or "").strip()))
                if field.get("default"):
                    tooltip_parts.append(f"Default: {field.get('default')}")
                if tooltip_parts:
                    editor.setToolTip("\n".join(tooltip_parts))
                editor.editingFinished.connect(lambda fid=field_id, widget=editor, pid=provider_id: self._on_chat_provider_field_changed(pid, fid, widget))
                self.chat_provider_fields_layout.addRow(label, editor)
                self._chat_provider_field_widgets[field_id] = editor
                self._chat_provider_field_meta[field_id] = dict(field)
            if hasattr(self, "chat_provider_settings_section"):
                self.chat_provider_settings_section.setSummary(f"{len(fields)} field(s)")
        else:
            hint = QtWidgets.QLabel("This provider does not expose extra runtime fields yet.")
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            hint.setWordWrap(True)
            self.chat_provider_fields_layout.addRow("", hint)
            if hasattr(self, "chat_provider_settings_section"):
                self.chat_provider_settings_section.setSummary("no extra fields")

        if hasattr(self, "chat_provider_hint_label"):
            metadata = self._chat_provider_metadata(provider_id)
            description = str(metadata.get("hint") or metadata.get("description") or "").strip()
            if not description:
                provider_label = self._chat_provider_label_from_value(provider_id)
                description = f"{provider_label} is selected."
            self.chat_provider_hint_label.setText(description)
        self._refresh_chat_provider_generation_card()
        self._refresh_chat_runtime_summary()

    def _refresh_chat_runtime_summary(self):
        if not hasattr(self, "chat_runtime_section"):
            return
        provider_label = self._chat_provider_label_from_value(self._current_chat_provider_value())
        model_name = str(self.model_combo.currentText() if hasattr(self, "model_combo") else RUNTIME_CONFIG.get("model_name", "") or "").strip()
        summary = provider_label
        if model_name and not self._is_model_catalog_placeholder(model_name):
            summary = f"{provider_label} / {model_name}"
        self.chat_runtime_section.setSummary(summary)

    def _refresh_tts_runtime_summary(self):
        if not hasattr(self, "tts_runtime_section"):
            return
        backend_value = self._current_tts_backend_value()
        backend_label = self._tts_backend_label_from_value(backend_value)
        if backend_value == "chatterbox":
            voice_name = str(self.voice_combo.currentText() if hasattr(self, "voice_combo") else "" or "").strip()
            self.tts_runtime_section.setSummary(f"{backend_label} / {voice_name}" if voice_name else backend_label)
        else:
            self.tts_runtime_section.setSummary(backend_label)

    def _on_runtime_section_toggled(self):
        self._sync_host_settings_tabs_height()
        self.save_session()

    def _refresh_tts_runtime_card(self, activate_tab=True):
        if not hasattr(self, "tts_runtime_addon_tabs"):
            return

        backend = self._current_tts_backend_value()
        backend_label = self._tts_backend_label_from_value(backend)
        tab_index = self._tts_runtime_tab_index_by_backend.get(backend)
        if tab_index is None:
            for index in range(self.tts_runtime_addon_tabs.count()):
                tab_widget = self.tts_runtime_addon_tabs.widget(index)
                backend_id = ""
                try:
                    backend_id = str(tab_widget.property("backend_id") or "").strip().lower()
                except Exception:
                    backend_id = ""
                candidates = {
                    backend_id,
                    str(tab_widget.objectName() or "").strip().lower(),
                }
                if backend in candidates:
                    tab_index = index
                    self._tts_runtime_tab_index_by_backend[backend] = index
                    break
        if activate_tab and tab_index is not None and 0 <= int(tab_index) < self.tts_runtime_addon_tabs.count():
            self.tts_runtime_addon_tabs.blockSignals(True)
            self.tts_runtime_addon_tabs.setCurrentIndex(int(tab_index))
            self.tts_runtime_addon_tabs.blockSignals(False)
        if hasattr(self, "tts_runtime_hint_label"):
            if backend in self._tts_runtime_tab_index_by_backend:
                self.tts_runtime_hint_label.setText(f"{backend_label} backend settings are shown in the addon tab below.")
            else:
                self.tts_runtime_hint_label.setText(
                    f"Backend '{backend_label}' does not have a mounted addon tab right now; core fallback settings may be in use."
                )
        self._refresh_tts_runtime_summary()

    def _available_tts_backend_options(self):
        options = []
        try:
            backend_specs = list(engine.list_available_tts_backends() or [])
        except Exception:
            backend_specs = []
        if not backend_specs:
            backend_specs = [
                {"id": "chatterbox", "label": "Chatterbox"},
                {"id": "pockettts", "label": "PocketTTS"},
            ]
        seen = set()
        for spec in backend_specs:
            backend_id = str(spec.get("id") or "").strip().lower()
            if not backend_id or backend_id in seen:
                continue
            label = str(spec.get("label") or backend_id or "").strip() or backend_id
            options.append((label, backend_id))
            seen.add(backend_id)
        return options

    def _populate_tts_backend_combo(self, selected_value=None):
        combo = getattr(self, "tts_backend_combo", None)
        if combo is None:
            return
        desired = str(
            selected_value
            or self._current_tts_backend_value()
            or RUNTIME_CONFIG.get("tts_backend", "chatterbox")
            or "chatterbox"
        ).strip().lower()
        combo.blockSignals(True)
        try:
            combo.clear()
            for label, backend_id in self._available_tts_backend_options():
                combo.addItem(label, backend_id)
            index = combo.findData(desired)
            if index < 0:
                index = combo.findData("chatterbox")
            if index < 0 and combo.count() > 0:
                index = 0
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _current_tts_backend_value(self):
        combo = getattr(self, "tts_backend_combo", None)
        if combo is not None:
            data = combo.currentData()
            if data is not None and str(data).strip():
                return str(data).strip().lower()
            text = str(combo.currentText() or "").strip()
            if text:
                return self._tts_backend_value_from_label(text)
        return str(RUNTIME_CONFIG.get("tts_backend", "chatterbox") or "chatterbox").strip().lower()

    def _tts_backend_value_from_label(self, label):
        normalized = str(label or "").strip().lower()
        for display_label, backend_id in self._available_tts_backend_options():
            if normalized == str(display_label or "").strip().lower():
                return str(backend_id or "").strip().lower()
            if normalized == str(backend_id or "").strip().lower():
                return str(backend_id or "").strip().lower()
        if normalized in {"chatterbox", "pockettts"}:
            return normalized
        return normalized

    def _tts_backend_label_from_value(self, value):
        normalized = str(value or "").strip().lower()
        for display_label, backend_id in self._available_tts_backend_options():
            if normalized == str(backend_id or "").strip().lower():
                return str(display_label or backend_id).strip()
        if normalized == "chatterbox":
            return "Chatterbox"
        if normalized == "pockettts":
            return "PocketTTS"
        return str(value or "").strip() or "External TTS"

    def on_tts_seed_changed(self, value):
        update_runtime_config("tts_seed", max(0, int(value or 0)))
        self.save_session()

    def on_tts_temperature_changed(self, value):
        update_runtime_config("tts_temperature", max(0.05, float(value or 0.8)))
        self.save_session()

    def on_tts_top_p_changed(self, value):
        update_runtime_config("tts_top_p", max(0.0, min(1.0, float(value or 0.9))))
        self.save_session()

    def on_tts_top_k_changed(self, value):
        update_runtime_config("tts_top_k", max(0, int(value or 0)))
        self.save_session()

    def on_tts_repeat_penalty_changed(self, value):
        update_runtime_config("tts_repeat_penalty", max(1.0, float(value or 1.2)))
        self.save_session()

    def on_tts_min_p_changed(self, value):
        update_runtime_config("tts_min_p", max(0.0, min(1.0, float(value or 0.0))))
        self.save_session()

    def on_tts_normalize_loudness_changed(self, checked):
        update_runtime_config("tts_normalize_loudness", bool(checked))
        self.save_session()

    def _on_chat_provider_field_changed(self, provider_id, field_id, widget):
        if widget is None:
            return
        settings = self._current_chat_provider_settings_for(provider_id)
        value = widget.text().strip()
        if value:
            settings[str(field_id or "").strip()] = value
        else:
            settings.pop(str(field_id or "").strip(), None)
        self._set_current_chat_provider_settings_for(provider_id, settings)
        self.request_model_list_refresh(quiet=True, wait_for_reachable=False)
        self.save_session()

    def _on_chat_provider_generation_field_changed(self, provider_id, field_id, widget, field_meta=None):
        if widget is None:
            return
        field_id = str(field_id or "").strip()
        if not field_id:
            return
        settings = self._current_chat_provider_generation_settings_for(provider_id)
        value = self._generation_field_widget_value(dict(field_meta or {}), widget)
        if value is None or value == "":
            settings.pop(field_id, None)
        else:
            settings[field_id] = value
        self._set_current_chat_provider_generation_settings_for(provider_id, settings)
        self._apply_legacy_generation_mirror(field_id, value)
        self.save_session()

    def _visual_reply_mode_label_from_value(self, value):
        return "Off" if str(value or "auto").strip().lower() == "off" else "Auto"

    def _visual_reply_mode_value_from_label(self, label):
        return "off" if str(label or "").strip().lower() == "off" else "auto"

    def _visual_reply_provider_label_from_value(self, value):
        return "xAI / Grok" if str(value or "openai").strip().lower() == "xai" else "OpenAI"

    def _visual_reply_provider_value_from_label(self, label):
        return "xai" if "grok" in str(label or "").strip().lower() or "xai" in str(label or "").strip().lower() else "openai"

    def _sensory_provider_summaries(self):
        return [provider.to_summary() for provider in sensory.list_providers()]

    def _parse_sensory_feedback_source_values(self, value):
        if isinstance(value, (list, tuple, set)):
            tokens = [str(item or "").strip().lower() for item in list(value or [])]
        else:
            tokens = [part.strip().lower() for part in str(value or "off").split(",")]
        selected = []
        seen = set()
        for token in tokens:
            if not token or token == "off" or token in seen:
                continue
            if sensory.get_provider(token) is None:
                continue
            selected.append(token)
            seen.add(token)
        return selected

    def _selected_sensory_feedback_sources(self):
        checkboxes = getattr(self, "_sensory_feedback_source_checkboxes", {}) or {}
        selected = [provider_id for provider_id, checkbox in checkboxes.items() if bool(checkbox.isChecked())]
        return self._parse_sensory_feedback_source_values(selected)

    def _sensory_feedback_config_value(self, values=None):
        selected = self._parse_sensory_feedback_source_values(values if values is not None else self._selected_sensory_feedback_sources())
        return ",".join(selected) if selected else "off"

    def _sync_sensory_feedback_source_summary(self, selected_values=None):
        if not hasattr(self, "sensory_feedback_source_combo"):
            return
        selected = self._parse_sensory_feedback_source_values(selected_values if selected_values is not None else self._selected_sensory_feedback_sources())
        summary_label = self._sensory_feedback_source_label_from_value(selected)
        summary_value = self._sensory_feedback_config_value(selected)
        combo = self.sensory_feedback_source_combo
        previous = combo.blockSignals(True)
        combo.clear()
        combo.addItem(summary_label, summary_value)
        combo.setCurrentIndex(0)
        combo.blockSignals(previous)

    def refresh_sensory_feedback_source_options(self, selected_value=None):
        target_provider_id = ""
        tabs = getattr(self, "sensory_feedback_tabs", None)
        if tabs is not None and tabs.count() > 1:
            current_widget = tabs.currentWidget()
            for provider_id, widget in dict(getattr(self, "_sensory_source_prompt_tabs", {}) or {}).items():
                if widget is current_widget:
                    target_provider_id = str(provider_id or "").strip().lower()
                    break
        source_value = selected_value if selected_value is not None else RUNTIME_CONFIG.get("sensory_feedback_source", "off")
        requested = self._parse_sensory_feedback_source_values(source_value)
        entries = []
        for provider in self._sensory_provider_summaries():
            provider_id = str(provider.get("id", "") or "").strip()
            label = str(provider.get("label", provider_id) or provider_id).strip()
            if provider_id:
                entries.append((provider_id, label))
        selected_set = set(requested)
        if hasattr(self, "sensory_feedback_sources_layout"):
            layout = self.sensory_feedback_sources_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self._sensory_feedback_source_checkboxes = {}
            self._sensory_source_prompt_editors = {}
            self._sensory_source_prompt_tabs = {}
            for provider_id, label in entries:
                checkbox = QtWidgets.QCheckBox(label)
                checkbox.setChecked(provider_id in selected_set)
                checkbox.toggled.connect(self._on_sensory_feedback_source_checkbox_toggled)
                layout.addWidget(checkbox)
                self._sensory_feedback_source_checkboxes[provider_id] = checkbox
            layout.addStretch(1)
        self._sync_sensory_feedback_source_summary(requested)
        self._refresh_sensory_feedback_hint()
        self._refresh_sensory_feedback_source_tabs(selected_provider_id=target_provider_id)
        self._sync_tab_widget_height(getattr(self, "sensory_feedback_tabs", None))
        self._sync_host_settings_tabs_height()

    def _sensory_feedback_source_label_from_value(self, value):
        selected = self._parse_sensory_feedback_source_values(value)
        if not selected:
            return "Off"
        labels = []
        for provider_id in selected:
            provider = sensory.get_provider(provider_id)
            labels.append(str(getattr(provider, "label", provider_id) or provider_id))
        if len(labels) == 1:
            return labels[0]
        if len(labels) == 2:
            return f"{labels[0]} + {labels[1]}"
        return f"{len(labels)} sources selected"

    def _sensory_feedback_source_value_from_label(self, label):
        if hasattr(self, "sensory_feedback_source_combo"):
            index = self.sensory_feedback_source_combo.findText(str(label or ""))
            if index >= 0:
                return str(self.sensory_feedback_source_combo.itemData(index) or "off")
        selected = self._parse_sensory_feedback_source_values(label)
        return ",".join(selected) if selected else "off"

    def _on_sensory_feedback_source_checkbox_toggled(self, _checked):
        selected = self._selected_sensory_feedback_sources()
        config_value = self._sensory_feedback_config_value(selected)
        self._sync_sensory_feedback_source_summary(selected)
        update_runtime_config("sensory_feedback_source", config_value)
        self._refresh_sensory_feedback_hint()
        self._refresh_sensory_feedback_source_tabs()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_feedback_source", "value": config_value})
        self.save_session()

    def _normalize_sensory_pingpong_source_prompt_map(self, payload=None):
        raw = payload if payload is not None else RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {})
        if not isinstance(raw, dict):
            return {}
        result = {}
        for key, value in list(raw.items()):
            provider_id = str(key or "").strip().lower()
            if not provider_id:
                continue
            result[provider_id] = str(value or "").strip()
        return result

    def _current_sensory_pingpong_source_prompt_map(self):
        editors = getattr(self, "_sensory_source_prompt_editors", {}) or {}
        current_map = self._normalize_sensory_pingpong_source_prompt_map()
        for provider_id, editor in editors.items():
            current_map[str(provider_id or "").strip().lower()] = str(editor.toPlainText() or "").strip()
        return current_map

    def _provider_sensory_pingpong_prompt_default(self, provider_id):
        provider = sensory.get_provider(str(provider_id or "").strip().lower())
        metadata = dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}
        return str(metadata.get("pingpong_prompt") or "").strip()

    def _provider_uses_source_prompt_fragment(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        return metadata.get("prompt_fragment_enabled", True) is not False

    def _provider_sensory_metadata(self, provider_id):
        provider = sensory.get_provider(str(provider_id or "").strip().lower())
        return dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}

    def _provider_declared_ping_payload(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("ping_payload", [])
        payload_lines = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    field_name = str(item.get("field") or "").strip()
                    description = str(item.get("description") or "").strip()
                    text = field_name
                    if field_name and description:
                        text = f"{field_name}: {description}"
                    elif description:
                        text = description
                else:
                    text = str(item or "").strip()
                if text and text not in payload_lines:
                    payload_lines.append(text)
        return payload_lines

    def _provider_declared_pong_influences(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("pong_influences", metadata.get("pong_outputs", []))
        outputs = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    field_name = str(item.get("field") or "").strip()
                    description = str(item.get("description") or "").strip()
                    text = field_name
                    if field_name and description:
                        text = f"{field_name}: {description}"
                    elif description:
                        text = description
                else:
                    text = str(item or "").strip()
                if text and text not in outputs:
                    outputs.append(text)
        return outputs

    def _provider_prompt_contributors(self, provider_id):
        provider_key = str(provider_id or "").strip().lower()
        items = []
        for contributor in sensory.list_prompt_contributors(provider_key):
            if hasattr(contributor, "to_summary"):
                items.append(contributor.to_summary())
            elif isinstance(contributor, dict):
                items.append(dict(contributor))
        return items

    def _provider_declared_tag_subscriptions(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("tag_subscriptions", [])
        tags = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    tag_name = str(item.get("tag") or "").strip()
                    action = str(item.get("action") or "").strip()
                    text = tag_name
                    if tag_name and action:
                        text = f"{tag_name}: {action}"
                    elif action:
                        text = action
                else:
                    text = str(item or "").strip()
                if text and text not in tags:
                    tags.append(text)
        return tags

    def _on_sensory_source_prompt_changed(self, provider_id):
        prompt_map = self._current_sensory_pingpong_source_prompt_map()
        update_runtime_config("sensory_pingpong_source_prompts", prompt_map)
        self.emit_tutorial_event("ui_changed", {"field": f"sensory_pingpong_source_prompt:{provider_id}", "value": "edited"})
        self.save_session()

    def _reset_sensory_source_prompt_to_default(self, provider_id):
        editors = getattr(self, "_sensory_source_prompt_editors", {}) or {}
        editor = editors.get(str(provider_id or "").strip().lower())
        if editor is None:
            return
        default_prompt = self._provider_sensory_pingpong_prompt_default(provider_id)
        editor.setPlainText(default_prompt)
        self._on_sensory_source_prompt_changed(provider_id)

    def _vision_source_tab_contributions(self, provider_id):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return []
        provider_key = str(provider_id or "").strip().lower()
        items = []
        for contribution in manager.get_tab_contributions(area="vision_source"):
            parent_tab_id = str(getattr(contribution, "parent_tab_id", "") or "").strip().lower()
            if parent_tab_id == provider_key:
                items.append(contribution)
        return items

    def _build_sensory_source_foundation_widget(
        self,
        provider_key,
        label,
        *,
        prompt_text="",
        description="",
        declared_ping_payload=None,
        declared_outputs=None,
        declared_tags=None,
        contributors=None,
        include_behavior_contributors=False,
    ):
        declared_ping_payload = list(declared_ping_payload or [])
        declared_outputs = list(declared_outputs or [])
        declared_tags = list(declared_tags or [])
        contributors = list(contributors or [])

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        editor = None
        if self._provider_uses_source_prompt_fragment(provider_key):
            prompt_header = QtWidgets.QLabel(f"Source guidance for {label}")
            prompt_header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(prompt_header)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addStretch(1)
            reset_button = QtWidgets.QPushButton("Use Recommended")
            reset_button.clicked.connect(lambda _=False, pid=provider_key: self._reset_sensory_source_prompt_to_default(pid))
            row.addWidget(reset_button, 0)
            layout.addLayout(row)
            editor = QtWidgets.QPlainTextEdit()
            editor.setMinimumHeight(0)
            editor.setPlaceholderText(f"Prompt fragment for {label}")
            editor.setPlainText(str(prompt_text or "").strip())
            editor.textChanged.connect(lambda pid=provider_key: self._on_sensory_source_prompt_changed(pid))
            layout.addWidget(editor)
            hint = QtWidgets.QLabel("This fragment is appended after the core hidden PING/PONG prompt whenever this source is enabled.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(hint)

        info_items_added = False

        def add_info_header(text):
            nonlocal info_items_added
            header = QtWidgets.QLabel(text)
            header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(header)
            info_items_added = True

        def add_info_label(text):
            nonlocal info_items_added
            label_widget = QtWidgets.QLabel(text)
            label_widget.setWordWrap(True)
            label_widget.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(label_widget)
            info_items_added = True

        if description or declared_ping_payload or declared_outputs or declared_tags or (contributors and include_behavior_contributors):
            about_header = QtWidgets.QLabel(f"About {label}")
            about_header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(about_header)
            if description:
                add_info_label(description)

        if declared_ping_payload:
            add_info_header("Declared PING payload")
            add_info_label("\n".join([f"- {item}" for item in declared_ping_payload]))

        if declared_outputs:
            add_info_header("May influence PONG")
            add_info_label("\n".join([f"- {item}" for item in declared_outputs]))

        if contributors and include_behavior_contributors:
            add_info_header("Active behavior contributors")
            contributor_lines = []
            for item in contributors:
                label_text = str(item.get("label") or item.get("id") or "Behavior")
                contributor_prompt_text = str(item.get("prompt") or "").strip()
                if contributor_prompt_text:
                    contributor_lines.append(f"- {label_text}: {contributor_prompt_text}")
                else:
                    contributor_lines.append(f"- {label_text}")
            add_info_label("\n".join(contributor_lines))

        if declared_tags:
            add_info_header("Declared tag subscriptions")
            add_info_label("\n".join([f"- {item}" for item in declared_tags]))

        if not info_items_added and editor is None:
            empty = QtWidgets.QLabel(f"No additional source guidance is declared for {label}.")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(empty)

        layout.addStretch(1)
        return widget, editor

    def _on_vision_source_child_checkbox_toggled(self, provider_id, contribution_id, checked):
        contribution_id = str(contribution_id or "").strip()
        contribution = next((item for item in self._vision_source_tab_contributions(provider_id) if str(getattr(item, "id", "") or "") == contribution_id), None)
        if contribution is None:
            return
        self._set_addon_contribution_enabled(contribution, bool(checked))
        self._refresh_sensory_feedback_source_tabs(selected_provider_id=str(provider_id or "").strip().lower())
        self.save_session()

    def _build_sensory_source_prompt_tab(self, provider_id, label):
        provider_key = str(provider_id or "").strip().lower()
        prompt_map = self._normalize_sensory_pingpong_source_prompt_map()
        prompt_text = str(prompt_map.get(provider_key) or self._provider_sensory_pingpong_prompt_default(provider_key) or "").strip()
        provider = sensory.get_provider(provider_key)
        description = str(getattr(provider, "description", "") or "").strip() if provider is not None else ""
        declared_ping_payload = self._provider_declared_ping_payload(provider_key)
        declared_outputs = self._provider_declared_pong_influences(provider_key)
        declared_tags = self._provider_declared_tag_subscriptions(provider_key)
        addon_contributions = self._vision_source_tab_contributions(provider_key)
        contributors = self._provider_prompt_contributors(provider_key)
        has_custom_source_tab = any(str(getattr(item, "title", "") or "").strip().lower() == "source" for item in addon_contributions)
        use_nested_source_tab = bool(
            (not has_custom_source_tab) and addon_contributions and (
                self._provider_uses_source_prompt_fragment(provider_key)
                or description
                or declared_ping_payload
                or declared_outputs
                or declared_tags
            )
        )

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        widget = QtWidgets.QWidget()
        scroll.setWidget(widget)
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        editor = None

        if addon_contributions:
            checkable_children = [
                item for item in addon_contributions
                if bool(dict(getattr(item, "metadata", {}) or {}).get("checkable", False))
            ]
            static_tabs = [item for item in addon_contributions if item not in checkable_children]
            if checkable_children:
                include_row = QtWidgets.QHBoxLayout()
                include_row.setContentsMargins(0, 0, 0, 0)
                include_row.setSpacing(8)
                for item in checkable_children:
                    checkbox = QtWidgets.QCheckBox(item.title)
                    checkbox.setChecked(bool(self._addon_contribution_enabled(item)))
                    checkbox.toggled.connect(lambda checked, pid=provider_key, cid=item.id: self._on_vision_source_child_checkbox_toggled(pid, cid, checked))
                    include_row.addWidget(checkbox)
                include_row.addStretch(1)
                layout.addLayout(include_row)
            nested_tabs = NoWheelTabWidget()
            nested_tabs.setObjectName(f"vision_source_tabs_{provider_key}")
            nested_tabs.setMinimumSize(0, 0)
            nested_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
            nested_tabs.currentChanged.connect(lambda _index, tabs=nested_tabs: self._sync_tab_widget_height(tabs))
            if use_nested_source_tab:
                source_widget, editor = self._build_sensory_source_foundation_widget(
                    provider_key,
                    label,
                    prompt_text=prompt_text,
                    description=description,
                    declared_ping_payload=declared_ping_payload,
                    declared_outputs=declared_outputs,
                    declared_tags=declared_tags,
                    contributors=contributors,
                    include_behavior_contributors=False,
                )
                tab_index = nested_tabs.addTab(source_widget, "Source")
                nested_tabs.setTabToolTip(tab_index, f"Source guidance and declared payload for {label}.")
            for item in static_tabs:
                try:
                    child_widget = item.factory(None)
                    if child_widget is None:
                        continue
                    tab_index = nested_tabs.addTab(child_widget, item.title)
                    if item.tooltip:
                        nested_tabs.setTabToolTip(tab_index, item.tooltip)
                except Exception as exc:
                    print(f"⚠️ [Addons] Failed to mount Vision source tab '{item.id}': {exc}")
            for item in checkable_children:
                if not self._addon_contribution_enabled(item):
                    continue
                try:
                    child_widget = item.factory(None)
                    if child_widget is None:
                        continue
                    tab_index = nested_tabs.addTab(child_widget, item.title)
                    if item.tooltip:
                        nested_tabs.setTabToolTip(tab_index, item.tooltip)
                except Exception as exc:
                    print(f"⚠️ [Addons] Failed to mount Vision child tab '{item.id}': {exc}")
            if nested_tabs.count() > 0:
                layout.addWidget(nested_tabs, 0, QtCore.Qt.AlignTop)
                self._sync_tab_widget_height(nested_tabs)

        if not use_nested_source_tab:
            foundation_widget, foundation_editor = self._build_sensory_source_foundation_widget(
                provider_key,
                label,
                prompt_text=prompt_text,
                description=description,
                declared_ping_payload=declared_ping_payload,
                declared_outputs=declared_outputs,
                declared_tags=declared_tags,
                contributors=contributors,
                include_behavior_contributors=not addon_contributions,
            )
            layout.addWidget(foundation_widget)
            if foundation_editor is not None:
                editor = foundation_editor

        if editor is not None:
            self._sensory_source_prompt_editors[provider_key] = editor
        self._sensory_source_prompt_tabs[provider_key] = scroll
        return scroll

    def _refresh_sensory_feedback_source_tabs(self, selected_provider_id=None):
        tabs = getattr(self, "sensory_feedback_tabs", None)
        if tabs is None:
            return
        target_provider_id = str(selected_provider_id or "").strip().lower()
        if not target_provider_id and tabs.count() > 1:
            current_widget = tabs.currentWidget()
            for provider_id, widget in dict(getattr(self, "_sensory_source_prompt_tabs", {}) or {}).items():
                if widget is current_widget:
                    target_provider_id = str(provider_id or "").strip().lower()
                    break
        while tabs.count() > 1:
            widget = tabs.widget(1)
            tabs.removeTab(1)
            if widget is not None:
                widget.deleteLater()
        self._sensory_source_prompt_editors = {}
        self._sensory_source_prompt_tabs = {}
        for provider_id in self._selected_sensory_feedback_sources():
            provider = sensory.get_provider(provider_id)
            label = str(getattr(provider, "label", provider_id) or provider_id)
            widget = self._build_sensory_source_prompt_tab(provider_id, label)
            tabs.addTab(widget, label)
            self._sensory_source_prompt_tabs[str(provider_id or "").strip().lower()] = widget
        if target_provider_id:
            target_widget = self._sensory_source_prompt_tabs.get(target_provider_id)
            if target_widget is not None:
                for index in range(1, tabs.count()):
                    if tabs.widget(index) is target_widget:
                        tabs.setCurrentIndex(index)
                        break
        self._sync_tab_widget_height(getattr(self, "sensory_feedback_tabs", None))
        self._sync_host_settings_tabs_height()

    def _normalize_visual_reply_size(self, value):
        size = str(value or "1024x1024").strip().lower()
        if size in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
            return size
        return "1024x1024"

    def _visual_reply_size_label_from_value(self, value):
        size = self._normalize_visual_reply_size(value)
        return "Auto" if size == "auto" else size

    def _refresh_visual_reply_hint(self):
        if not hasattr(self, "visual_reply_hint"):
            return
        mode = self._visual_reply_mode_value_from_label(self.visual_reply_mode_combo.currentText()) if hasattr(self, "visual_reply_mode_combo") else "auto"
        provider = self._visual_reply_provider_value_from_label(self.visual_reply_provider_combo.currentText()) if hasattr(self, "visual_reply_provider_combo") else "openai"
        size = self._normalize_visual_reply_size(self.visual_reply_size_combo.currentText() if hasattr(self, "visual_reply_size_combo") else "1024x1024")
        model = str(self.visual_reply_model_edit.text() if hasattr(self, "visual_reply_model_edit") else RUNTIME_CONFIG.get("visual_reply_model", "gpt-image-1")).strip() or "gpt-image-1"
        auto_show = bool(self.visual_reply_auto_show_checkbox.isChecked()) if hasattr(self, "visual_reply_auto_show_checkbox") else True
        if mode == "off":
            summary = "Visual replies are disabled. NC will not ask the LLM for [visualize: ...] tags or generate images automatically."
        else:
            dock_text = "The dock will auto-show when a request starts or finishes." if auto_show else "The dock stays where it is; use Show Visual Reply if you want to watch generation live."
            provider_text = "xAI / Grok" if provider == "xai" else "OpenAI"
            summary = (
                f"Visual replies are enabled. Automatic image generation still follows the NC auto-visual toggle; when allowed, NC may append one [visualize: ...] tag when an image would help. "
                f"Current backend request: {provider_text}, {size}, model '{model}'. {dock_text}"
            )
        self.visual_reply_hint.setText(summary)

    def _refresh_sensory_feedback_hint(self):
        if not hasattr(self, "sensory_feedback_hint"):
            return
        sources = self._parse_sensory_feedback_source_values(self.sensory_feedback_source_combo.currentData() if hasattr(self, "sensory_feedback_source_combo") and self.sensory_feedback_source_combo.count() else RUNTIME_CONFIG.get("sensory_feedback_source", "off"))
        interval = float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else 7.0
        pingpong_enabled = bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False))
        pingpong_depth = int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3)
        hidden_proactive = bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False))
        hidden_visual = bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False))
        if not sources:
            summary = "Hidden sensory feedback is disabled. No addon or built-in sensory provider will attach hidden context to LLM requests."
        else:
            labels = []
            descriptions = []
            for source in sources:
                provider = sensory.get_provider(source)
                labels.append(str(getattr(provider, "label", source) or source))
                description = str(getattr(provider, "description", "") or "").strip() if provider is not None else ""
                if description:
                    descriptions.append(description)
            summary = (
                f"NC will refresh hidden sensory input from {', '.join(repr(label) for label in labels)} when building an LLM request if the last capture is older than about "
                f"{interval:.1f}s. Each selected source may contribute its own image or text payload as ambient context, not as a user request."
            )
            if descriptions:
                summary += " " + " ".join(descriptions)
            if pingpong_enabled:
                summary += (
                    f" Hidden PING/PONG is enabled, so while NC is idle it may send background sensory PINGs and retain up to "
                    f"{pingpong_depth} meaningful hidden PONG event(s)."
                )
                summary += (
                    f" Auto-speech from hidden PONGs is {'enabled' if hidden_proactive else 'disabled'}. "
                    f"Automatic visual replies are {'enabled' if hidden_visual else 'disabled'} for both hidden PONGs and assistant [visualize: ...] tags."
                )
            else:
                summary += " Hidden PING/PONG is off, so sensory updates are only attached during normal visible requests."
        self.sensory_feedback_hint.setText(summary)

    def _refresh_chat_session_hint(self):
        if not hasattr(self, "chat_session_hint"):
            return
        proactive_enabled = self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else True
        require_first = self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False
        idle_window = float(self.listen_idle_window_spin.value()) if hasattr(self, "listen_idle_window_spin") else 5.0
        proactive_delay = float(self.proactive_delay_spin.value()) if hasattr(self, "proactive_delay_spin") else 10.0
        context_window = int(self.chat_context_window_spin.value()) if hasattr(self, "chat_context_window_spin") else 20
        stored_limit = int(self.stored_chat_history_limit_spin.value()) if hasattr(self, "stored_chat_history_limit_spin") else 0
        stored_limit_text = "unlimited" if stored_limit <= 0 else f"{stored_limit} message(s)"
        overflow_policy = self._chat_overflow_policy_label_from_value(self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText())) if hasattr(self, "chat_overflow_policy_combo") else "Rolling Window"
        if not proactive_enabled:
            summary = "The assistant will wait for user input and will not speak first on silence."
        else:
            first_turn = "after the first user message" if require_first else "even at the very start of a session"
            summary = (
                f"The assistant checks for speech every {idle_window:.1f}s and may speak first after about "
                f"{proactive_delay:.1f}s of silence, {first_turn}. "
                f"Current model window: about {context_window} message(s) using {overflow_policy}. "
                f"Stored chat history: {stored_limit_text}."
            )
        self.chat_session_hint.setText(summary)

    def _build_status_timer(self):
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.timeout.connect(self._poll_runtime_status)
        self.status_timer.start(120)

    def _build_addon_llm_snapshot(self):
        return {
            "chat_provider": self._current_chat_provider_value() if hasattr(self, "chat_provider_combo") else str(RUNTIME_CONFIG.get("chat_provider", "lmstudio") or "lmstudio"),
            "selected_model": self.model_combo.currentText() if hasattr(self, "model_combo") else "",
            "stream_mode": bool(RUNTIME_CONFIG.get("stream_mode", False)),
            "input_mode": str(RUNTIME_CONFIG.get("input_mode", "") or ""),
            "input_role": str(RUNTIME_CONFIG.get("input_message_role", "") or ""),
            "temperature": float(RUNTIME_CONFIG.get("temperature", 0.0) or 0.0),
            "top_p": float(RUNTIME_CONFIG.get("top_p", 0.0) or 0.0),
            "top_k": int(RUNTIME_CONFIG.get("top_k", 0) or 0),
            "min_p": float(RUNTIME_CONFIG.get("min_p", 0.0) or 0.0),
            "repeat_penalty": float(RUNTIME_CONFIG.get("repeat_penalty", 0.0) or 0.0),
        }

    def _build_addon_tts_snapshot(self):
        return {
            "backend": self._current_tts_backend_value(),
            "voice_path": str(RUNTIME_CONFIG.get("voice_path", "") or ""),
            "pocket_tts_python": str(RUNTIME_CONFIG.get("pocket_tts_python", "") or ""),
        }

    def _build_addon_avatar_snapshot(self):
        return {
            "engine": self.engine_combo.currentText() if hasattr(self, "engine_combo") else "",
            "musetalk_vram_mode": self.musetalk_vram_combo.currentText() if hasattr(self, "musetalk_vram_combo") else "",
            "musetalk_avatar_pack": self.musetalk_avatar_pack_combo.currentText() if hasattr(self, "musetalk_avatar_pack_combo") else "",
            "musetalk_loop_fade_ms": int(self.musetalk_loop_fade_spin.value()) if hasattr(self, "musetalk_loop_fade_spin") else int(RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS),
            "visual_reply_mode": self._visual_reply_mode_value_from_label(self.visual_reply_mode_combo.currentText()) if hasattr(self, "visual_reply_mode_combo") else str(RUNTIME_CONFIG.get("visual_reply_mode", "auto") or "auto"),
            "visual_reply_provider": self._visual_reply_provider_value_from_label(self.visual_reply_provider_combo.currentText()) if hasattr(self, "visual_reply_provider_combo") else str(RUNTIME_CONFIG.get("visual_reply_provider", "openai") or "openai"),
            "visual_reply_size": self._normalize_visual_reply_size(self.visual_reply_size_combo.currentText()) if hasattr(self, "visual_reply_size_combo") else str(RUNTIME_CONFIG.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "visual_reply_model": self.visual_reply_model_edit.text().strip() if hasattr(self, "visual_reply_model_edit") else str(RUNTIME_CONFIG.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {}) or {}),
            "musetalk_vram_mode_key": next((key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self.musetalk_vram_combo.currentText()), "quality") if hasattr(self, "musetalk_vram_combo") else "quality",
            "preview_visible": bool(hasattr(self, "preview_dock") and self.preview_dock.isVisible()),
            "visual_reply_visible": bool(hasattr(self, "visual_reply_dock") and self.visual_reply_dock.isVisible()),
            "detected_gpu_vram_gib": self._detected_gpu_vram_gib(),
        }

    def _initialize_addons(self):
        try:
            manager = AddonManager(
                app_root=Path(__file__).resolve().parent,
                llm_snapshot_getter=self._build_addon_llm_snapshot,
                tts_snapshot_getter=self._build_addon_tts_snapshot,
                avatar_snapshot_getter=self._build_addon_avatar_snapshot,
                host_services={
                    "qt.dialogs": QtDialogService(self),
                    "qt.hotkeys": QtHotkeyService(self),
                    "qt.shell": QtShellService(self),
                    "qt.musetalk_ui": QtMuseTalkUIService(self),
                    "qt.visual_reply": QtVisualReplyService(self),
                    "qt.sensory": QtSensoryService(self),
                    "qt.chat_providers": QtChatProviderService(self),
                    "qt.chat_replay": QtChatReplayService(self),
                    "addons.capabilities": AddonCapabilityBridgeService(lambda: self._addon_manager),
                },
            )
            manager.discover()
            manager.load_all()
            manager.initialize_all()
            self._addon_manager = manager
            if hasattr(engine, "set_addon_event_publisher"):
                engine.set_addon_event_publisher(manager.publish_event)
            if hasattr(engine, "set_addon_manager_getter"):
                engine.set_addon_manager_getter(lambda: self._addon_manager)
            self._mount_tts_runtime_addon_tabs()
            self._populate_tts_backend_combo(selected_value=self._current_tts_backend_value())
            self.refresh_sensory_feedback_source_options(selected_value=str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"))
            self._mount_addon_tabs()
            self._mount_host_settings_addon_tabs()
            self._mount_operational_view_addon_tabs()
            self._mount_musetalk_addon_tabs()
            self._refresh_addons_management_ui()
            loaded = [record.manifest.id for record in manager.get_loaded_addons() if record.state == "initialized"]
            if loaded:
                print(f"🧩 [Addons] Loaded: {', '.join(loaded)}")
        except Exception as exc:
            if hasattr(engine, "set_addon_event_publisher"):
                engine.set_addon_event_publisher(None)
            if hasattr(engine, "set_addon_manager_getter"):
                engine.set_addon_manager_getter(None)
            print(f"⚠️ [Addons] Initialization failed: {exc}")
            self._refresh_addons_management_ui()
    def _get_addon_instance(self, addon_id):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return None
        return manager.get_addon_instance(str(addon_id or ""))

    def _get_addon_controller(self, addon_id):
        instance = self._get_addon_instance(addon_id)
        if instance is None:
            return None
        return getattr(instance, "controller", None)

    def _require_addon_controller(self, addon_id):
        controller = self._get_addon_controller(addon_id)
        if controller is None:
            raise RuntimeError(f"Addon controller is unavailable for {addon_id}")
        return controller

    def _addon_contribution_enabled(self, contribution):
        metadata = dict(getattr(contribution, "metadata", {}) or {})
        if not bool(metadata.get("checkable", False)):
            return True
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return bool(metadata.get("default_enabled", True))
        result = manager.invoke_capability(
            "ui.tab_enabled",
            {
                "addon_id": str(getattr(contribution, "addon_id", "") or ""),
                "tab_id": str(getattr(contribution, "id", "") or ""),
                "action": "get",
            },
        )
        if isinstance(result, dict) and "enabled" in result:
            return bool(result.get("enabled"))
        return bool(metadata.get("default_enabled", True))

    def _set_addon_contribution_enabled(self, contribution, enabled):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return bool(enabled)
        result = manager.invoke_capability(
            "ui.tab_enabled",
            {
                "addon_id": str(getattr(contribution, "addon_id", "") or ""),
                "tab_id": str(getattr(contribution, "id", "") or ""),
                "action": "set",
                "enabled": bool(enabled),
            },
        )
        if isinstance(result, dict) and "enabled" in result:
            return bool(result.get("enabled"))
        return bool(enabled)

    def _rebuild_addon_host_child_tabs(self, host_tab_id):
        group = dict(self._addon_host_tab_groups.get(str(host_tab_id or "")) or {})
        if not group:
            return
        nested_tabs = group.get("nested_tabs")
        if nested_tabs is None:
            return
        child_widgets = list(group.get("child_widgets", []))
        for widget in child_widgets:
            try:
                if widget is None:
                    continue
                index = nested_tabs.indexOf(widget)
                if index >= 0:
                    nested_tabs.removeTab(index)
                widget.deleteLater()
            except Exception:
                pass
        group["child_widgets"] = []
        host_widget = group.get("host_widget")
        if host_widget is not None and nested_tabs.indexOf(host_widget) < 0:
            label = str(group.get("host_child_title") or "Source").strip() or "Source"
            nested_tabs.addTab(host_widget, label)
        checkboxes = dict(group.get("checkboxes", {}) or {})
        for child in list(group.get("children", [])):
            child_id = str(getattr(child, "id", "") or "")
            enabled = self._addon_contribution_enabled(child)
            checkbox = checkboxes.get(child_id)
            if checkbox is not None:
                checkbox.blockSignals(True)
                checkbox.setChecked(bool(enabled))
                checkbox.blockSignals(False)
            if not enabled:
                continue
            try:
                child_widget = child.factory(None)
                if child_widget is None:
                    continue
                index = nested_tabs.addTab(child_widget, child.title)
                if child.tooltip:
                    nested_tabs.setTabToolTip(index, child.tooltip)
                group.setdefault("child_widgets", []).append(child_widget)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount child tab '{child_id}': {exc}")
        self._addon_host_tab_groups[str(host_tab_id or "")] = group

    def _build_addon_host_tab_widget(self, host_contribution, child_contributions):
        metadata = dict(getattr(host_contribution, "metadata", {}) or {})
        host_widget = host_contribution.factory(None)
        if host_widget is None:
            host_widget = QtWidgets.QWidget()
            host_layout = QtWidgets.QVBoxLayout(host_widget)
            placeholder = QtWidgets.QLabel("This foundational addon does not expose a source view.")
            placeholder.setWordWrap(True)
            host_layout.addWidget(placeholder)
            host_layout.addStretch(1)
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        checkboxes = {}
        checkable_children = [
            child for child in child_contributions if bool(dict(getattr(child, "metadata", {}) or {}).get("checkable", False))
        ]
        if checkable_children:
            header = QtWidgets.QLabel("Include")
            header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(header)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            for child in checkable_children:
                checkbox = QtWidgets.QCheckBox(child.title)
                checkbox.setChecked(bool(self._addon_contribution_enabled(child)))
                checkbox.toggled.connect(
                    lambda checked, host_id=host_contribution.id, child_id=child.id: self._on_addon_child_checkbox_toggled(host_id, child_id, checked)
                )
                row.addWidget(checkbox)
                checkboxes[str(child.id or "")] = checkbox
            row.addStretch(1)
            layout.addLayout(row)
        nested_tabs = NoWheelTabWidget()
        nested_tabs.setObjectName(f"addon_group_tabs_{host_contribution.id}")
        layout.addWidget(nested_tabs, 1)
        self._addon_host_tab_groups[str(host_contribution.id or "")] = {
            "container": container,
            "nested_tabs": nested_tabs,
            "host_widget": host_widget,
            "host_child_title": str(metadata.get("nested_title") or "Source").strip() or "Source",
            "children": list(child_contributions),
            "children_by_id": {str(child.id or ""): child for child in child_contributions},
            "checkboxes": checkboxes,
            "child_widgets": [],
        }
        self._rebuild_addon_host_child_tabs(host_contribution.id)
        return container

    def _on_addon_child_checkbox_toggled(self, host_tab_id, child_tab_id, checked):
        group = dict(self._addon_host_tab_groups.get(str(host_tab_id or "")) or {})
        if not group:
            return
        child = dict(group.get("children_by_id", {}) or {}).get(str(child_tab_id or ""))
        if child is None:
            return
        actual_enabled = self._set_addon_contribution_enabled(child, bool(checked))
        checkbox = dict(group.get("checkboxes", {}) or {}).get(str(child_tab_id or ""))
        if checkbox is not None:
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(actual_enabled))
            checkbox.blockSignals(False)
        self._rebuild_addon_host_child_tabs(host_tab_id)
        self.save_session()

    def _refresh_addon_group_tabs(self):
        for host_tab_id in list(getattr(self, "_addon_host_tab_groups", {}).keys()):
            self._rebuild_addon_host_child_tabs(host_tab_id)

    def _mount_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "tabs"):
            return
        contributions = list(self._addon_manager.get_tab_contributions(area="top_level"))
        child_contributions = {}
        top_level_contributions = []
        for contribution in contributions:
            parent_tab_id = str(getattr(contribution, "parent_tab_id", "") or "").strip()
            if parent_tab_id:
                child_contributions.setdefault(parent_tab_id, []).append(contribution)
            else:
                top_level_contributions.append(contribution)
        for contribution in top_level_contributions:
            if contribution.id in self._mounted_addon_tab_ids:
                continue
            try:
                children = list(child_contributions.get(contribution.id, []))
                widget = self._build_addon_host_tab_widget(contribution, children) if children else contribution.factory(None)
                if widget is None:
                    continue
                tab_index = self.tabs.addTab(widget, contribution.title)
                if contribution.tooltip:
                    self.tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount tab '{contribution.id}': {exc}")
        for parent_tab_id, children in child_contributions.items():
            if parent_tab_id in self._mounted_addon_tab_ids:
                continue
            child_ids = ", ".join(str(child.id or "") for child in children)
            print(f"⚠️ [Addons] Child tabs {child_ids} declared missing parent '{parent_tab_id}'.")

    def _mount_musetalk_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "musetalk_tabs"):
            return
        for contribution in self._addon_manager.get_tab_contributions(area="musetalk"):
            if contribution.id in self._mounted_musetalk_addon_tab_ids:
                continue
            try:
                widget = contribution.factory(None)
                if widget is None:
                    continue
                tab_index = self.musetalk_tabs.addTab(widget, contribution.title)
                if contribution.tooltip:
                    self.musetalk_tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_musetalk_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount MuseTalk tab '{contribution.id}': {exc}")

    def _mount_host_settings_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "host_settings_tabs"):
            return
        contributions = list(self._addon_manager.get_tab_contributions(area="host_settings"))
        child_contributions = {}
        top_level_contributions = []
        for contribution in contributions:
            parent_tab_id = str(getattr(contribution, "parent_tab_id", "") or "").strip()
            if parent_tab_id:
                child_contributions.setdefault(parent_tab_id, []).append(contribution)
            else:
                top_level_contributions.append(contribution)
        for contribution in top_level_contributions:
            if contribution.id in self._mounted_host_settings_addon_tab_ids:
                continue
            try:
                children = list(child_contributions.get(contribution.id, []))
                widget = self._build_addon_host_tab_widget(contribution, children) if children or getattr(contribution, "metadata", None) else contribution.factory(None)
                if widget is None:
                    continue
                insert_index = min(1 + len(self._mounted_host_settings_addon_tab_ids), self.host_settings_tabs.count())
                tab_index = self.host_settings_tabs.insertTab(insert_index, widget, contribution.title)
                if contribution.tooltip:
                    self.host_settings_tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_host_settings_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount host settings tab '{contribution.id}': {exc}")
        for parent_tab_id, children in child_contributions.items():
            if parent_tab_id in self._mounted_host_settings_addon_tab_ids:
                self._sync_existing_host_settings_child_tabs(parent_tab_id, children)
                continue
            child_ids = ", ".join(str(child.id or "") for child in children)
            print(f"⚠️ [Addons] Host settings child tabs {child_ids} declared missing parent '{parent_tab_id}'.")
        QtCore.QTimer.singleShot(0, lambda tabs=self.host_settings_tabs: self._sync_tab_widget_height(tabs))

    def _mount_tts_runtime_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "tts_runtime_addon_tabs"):
            return
        contributions = list(self._addon_manager.get_tab_contributions(area="tts_runtime"))
        for contribution in contributions:
            if contribution.id in self._mounted_tts_runtime_addon_tab_ids:
                continue
            try:
                widget = contribution.factory(None)
                if widget is None:
                    continue
                backend_id = str(
                    dict(getattr(contribution, "metadata", {}) or {}).get("backend_id")
                    or contribution.id
                    or contribution.title
                    or ""
                ).strip().lower()
                if backend_id:
                    try:
                        widget.setProperty("backend_id", backend_id)
                    except Exception:
                        pass
                tab_index = self.tts_runtime_addon_tabs.addTab(widget, contribution.title)
                if contribution.tooltip:
                    self.tts_runtime_addon_tabs.setTabToolTip(tab_index, contribution.tooltip)
                if backend_id:
                    self._tts_runtime_tab_index_by_backend[backend_id] = tab_index
                self._mounted_tts_runtime_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount TTS runtime tab '{contribution.id}': {exc}")
                fallback = QtWidgets.QWidget()
                fallback_layout = QtWidgets.QVBoxLayout(fallback)
                fallback_layout.setContentsMargins(10, 10, 10, 10)
                fallback_layout.setSpacing(8)
                title = QtWidgets.QLabel(str(contribution.title or contribution.id or "TTS Addon"))
                title.setStyleSheet("font-weight: 600; color: #d8dee9;")
                message = QtWidgets.QLabel(
                    f"Could not load the UI for '{contribution.title or contribution.id}'.\n\n{exc}"
                )
                message.setWordWrap(True)
                message.setStyleSheet("color: #8ea3b8;")
                fallback_layout.addWidget(title)
                fallback_layout.addWidget(message)
                fallback_layout.addStretch(1)
                tab_index = self.tts_runtime_addon_tabs.addTab(fallback, contribution.title)
                if contribution.tooltip:
                    self.tts_runtime_addon_tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_tts_runtime_addon_tab_ids.add(contribution.id)
        if hasattr(self, "tts_runtime_addon_tabs"):
            self.tts_runtime_addon_tabs.setVisible(self.tts_runtime_addon_tabs.count() > 0)
        self._refresh_tts_runtime_card()

    def _on_tts_runtime_addon_tab_changed(self, index):
        if not hasattr(self, "tts_runtime_addon_tabs"):
            return
        current = self.tts_runtime_addon_tabs.widget(index)
        if current is None:
            return
        backend_id = str(current.property("backend_id") or current.objectName() or "").strip().lower()
        if backend_id:
            self._tts_runtime_tab_index_by_backend[backend_id] = index

    def _sync_existing_host_settings_child_tabs(self, host_tab_id, children):
        host_tab_id = str(host_tab_id or "").strip()
        group = dict(self._addon_host_tab_groups.get(host_tab_id) or {})
        if not group:
            return
        existing_by_id = dict(group.get("children_by_id", {}) or {})
        changed = False
        for child in list(children or []):
            child_id = str(getattr(child, "id", "") or "").strip()
            if not child_id or child_id in existing_by_id:
                continue
            group.setdefault("children", []).append(child)
            existing_by_id[child_id] = child
            changed = True
        if not changed:
            return
        group["children_by_id"] = existing_by_id
        self._addon_host_tab_groups[host_tab_id] = group
        self._rebuild_addon_host_child_tabs(host_tab_id)

    def _mount_operational_view_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "right_tabs"):
            return
        contributions = list(self._addon_manager.get_tab_contributions(area="operational_view"))
        for contribution in contributions:
            if contribution.id in self._mounted_operational_view_addon_tab_ids:
                continue
            try:
                widget = contribution.factory(None)
                if widget is None:
                    continue
                tab_index = self.right_tabs.addTab(widget, contribution.title)
                if contribution.tooltip:
                    self.right_tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_operational_view_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount operational tab '{contribution.id}': {exc}")

    def _status_diode_style(self, active, active_fill, active_border):
        if active:
            return (
                f"background: {active_fill}; border: 1px solid {active_border}; border-radius: 8px;"
            )
        return "background: #4b5563; border: 1px solid #6b7280; border-radius: 8px;"

    def _build_preset_payload(self, ensure_pocket_tts_path=False):
        pocket_tts_python = self.pocket_tts_python_edit.text().strip() if hasattr(self, "pocket_tts_python_edit") else ""
        if ensure_pocket_tts_path and self._current_tts_backend_value() == "pockettts":
            pocket_tts_python = self._ensure_pocket_tts_python_path()
        chat_provider_generation_settings = dict(RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {})
        payload = {
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}),
            "model_name": self.model_combo.currentText(),
            "voice_file": self.voice_combo.currentText(),
            "input_mode": "push_to_talk" if self.input_mode_combo.currentText() == "Push-to-Talk" else "voice_activation",
            "input_message_role": self._input_role_value_from_label(self.input_role_combo.currentText()),
            "stream_mode": self.stream_mode_combo.currentText() == "On",
            "tts_backend": self._current_tts_backend_value(),
            "tts_seed": int(self.tts_seed_spin.value()) if hasattr(self, "tts_seed_spin") else int(RUNTIME_CONFIG.get("tts_seed", 0) or 0),
            "tts_temperature": float(self.tts_temperature_spin.value()) if hasattr(self, "tts_temperature_spin") else float(RUNTIME_CONFIG.get("tts_temperature", 0.8) or 0.8),
            "tts_top_p": float(self.tts_top_p_spin.value()) if hasattr(self, "tts_top_p_spin") else float(RUNTIME_CONFIG.get("tts_top_p", 0.9) or 0.9),
            "tts_top_k": int(self.tts_top_k_spin.value()) if hasattr(self, "tts_top_k_spin") else int(RUNTIME_CONFIG.get("tts_top_k", 40) or 40),
            "tts_repeat_penalty": float(self.tts_repeat_penalty_spin.value()) if hasattr(self, "tts_repeat_penalty_spin") else float(RUNTIME_CONFIG.get("tts_repeat_penalty", 1.2) or 1.2),
            "tts_min_p": float(self.tts_min_p_spin.value()) if hasattr(self, "tts_min_p_spin") else float(RUNTIME_CONFIG.get("tts_min_p", 0.0) or 0.0),
            "tts_normalize_loudness": self.tts_normalize_loudness_checkbox.isChecked() if hasattr(self, "tts_normalize_loudness_checkbox") else bool(RUNTIME_CONFIG.get("tts_normalize_loudness", False)),
            "musetalk_avatar_pack_id": str(self.musetalk_avatar_pack_combo.currentData() or RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or ""),
            "musetalk_loop_fade_ms": int(self.musetalk_loop_fade_spin.value()) if hasattr(self, "musetalk_loop_fade_spin") else int(RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS),
            "visual_reply_mode": self._visual_reply_mode_value_from_label(self.visual_reply_mode_combo.currentText()) if hasattr(self, "visual_reply_mode_combo") else str(RUNTIME_CONFIG.get("visual_reply_mode", "auto") or "auto"),
            "visual_reply_provider": self._visual_reply_provider_value_from_label(self.visual_reply_provider_combo.currentText()) if hasattr(self, "visual_reply_provider_combo") else str(RUNTIME_CONFIG.get("visual_reply_provider", "openai") or "openai"),
            "visual_reply_size": self._normalize_visual_reply_size(self.visual_reply_size_combo.currentText()) if hasattr(self, "visual_reply_size_combo") else str(RUNTIME_CONFIG.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "visual_reply_model": self.visual_reply_model_edit.text().strip() if hasattr(self, "visual_reply_model_edit") else str(RUNTIME_CONFIG.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "visual_reply_auto_show_dock": self.visual_reply_auto_show_checkbox.isChecked() if hasattr(self, "visual_reply_auto_show_checkbox") else bool(RUNTIME_CONFIG.get("visual_reply_auto_show_dock", True)),
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {}) or {}),
            "allow_proactive_replies": self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else True,
            "require_first_user_before_proactive": self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False,
            "listen_idle_window_seconds": float(self.listen_idle_window_spin.value()) if hasattr(self, "listen_idle_window_spin") else 5.0,
            "proactive_delay_seconds": float(self.proactive_delay_spin.value()) if hasattr(self, "proactive_delay_spin") else 10.0,
            "chat_context_window_messages": int(self.chat_context_window_spin.value()) if hasattr(self, "chat_context_window_spin") else 20,
            "stored_chat_history_limit": int(self.stored_chat_history_limit_spin.value()) if hasattr(self, "stored_chat_history_limit_spin") else 0,
            "chat_context_overflow_policy": self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window",
            "pocket_tts_python": pocket_tts_python,
            "emotional_instructions": self.emotional_text.toPlainText().strip(),
            "system_prompt": self.system_prompt_text.toPlainText().strip(),
            "temperature": self.brain_sliders["temperature"].value(),
            "top_p": self.brain_sliders["top_p"].value(),
            "top_k": self.brain_sliders["top_k"].value(),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value(),
            "min_p": self.brain_sliders["min_p"].value(),
            "limit_response_length": self.limit_response_checkbox.isChecked(),
            "max_response_tokens": int(self.max_response_tokens_spin.value()),
        }
        if chat_provider_generation_settings:
            payload["chat_provider_generation_settings"] = chat_provider_generation_settings
        if self._addon_manager is not None:
            try:
                payload.update(self._addon_manager.export_preset_state())
            except Exception:
                pass
        return payload

    def _preset_payload_signature(self, payload):
        return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _refresh_preset_dirty_state(self):
        if not hasattr(self, "btn_preset_save") or not hasattr(self, "btn_preset_save_as"):
            return
        if bool(getattr(self, "_restoring_session", False)):
            return
        current_signature = self._preset_payload_signature(self._build_preset_payload())
        if self._preset_reference_signature:
            dirty = current_signature != self._preset_reference_signature
        else:
            dirty = False
            self._preset_reference_signature = current_signature
            self._preset_reference_name = str(self.preset_combo.currentText() or "")
        if dirty != self._preset_dirty_state:
            self._preset_dirty_state = dirty
            style = "border: 2px solid #d84a4a; border-radius: 10px;" if dirty else ""
            self.btn_preset_save.setStyleSheet(style)
            self.btn_preset_save_as.setStyleSheet(style)

    def _update_preset_reference_from_selection(self, preset_name=None):
        name = str(preset_name or self.preset_combo.currentText() or "").strip()
        if name in {"", "Select Preset...", "No Presets"}:
            self._preset_reference_name = ""
            self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
        else:
            path = Path("presets") / f"{name}.json"
            self._preset_reference_name = name
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self._preset_reference_signature = self._preset_payload_signature(data)
                except Exception:
                    self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
            else:
                self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
        self._refresh_preset_dirty_state()

    def _update_preset_reference_from_current_state(self, preset_name=None):
        name = str(preset_name or self.preset_combo.currentText() or "").strip()
        if name in {"", "Select Preset...", "No Presets"}:
            self._preset_reference_name = ""
        else:
            self._preset_reference_name = name
        self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
        self._refresh_preset_dirty_state()

    def _queue_preset_clean_after_model_refresh(self, preset_name, provider_id="", model_name=""):
        self._pending_preset_clean_name = str(preset_name or "").strip()
        self._pending_preset_clean_provider = chat_providers.normalize_provider_id(
            provider_id or self._current_chat_provider_value(),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )
        self._pending_preset_clean_model = str(model_name or "").strip()

    def _finalize_pending_preset_clean_if_ready(self, *, force=False):
        name = str(getattr(self, "_pending_preset_clean_name", "") or "").strip()
        if not name:
            return False
        provider_id = str(getattr(self, "_pending_preset_clean_provider", "") or "").strip()
        model_name = str(getattr(self, "_pending_preset_clean_model", "") or "").strip()
        if provider_id and self._current_chat_provider_value() != provider_id:
            return False
        if model_name and hasattr(self, "model_combo"):
            current_model = str(self.model_combo.currentText() or "").strip()
            if current_model != model_name and not force:
                return False
        self._pending_preset_clean_name = ""
        self._pending_preset_clean_provider = ""
        self._pending_preset_clean_model = ""
        self._update_preset_reference_from_current_state(name)
        return True

    def _finalize_session_restore_dirty_state(self):
        self._restoring_session = False
        self._update_preset_reference_from_selection(self.preset_combo.currentText() if hasattr(self, "preset_combo") else "")
        self._refresh_preset_dirty_state()

    def on_preset_selection_changed(self, text):
        selected = str(text or "").strip()
        if selected in {"", "Select Preset...", "No Presets"}:
            update_runtime_config("active_preset_name", "")
        else:
            update_runtime_config("active_preset_name", selected)
        self._update_preset_reference_from_selection(selected)

    def _poll_runtime_status(self):
        listening = bool(getattr(engine, "listening_active", None) and engine.listening_active.is_set())
        recording = bool(getattr(engine, "microphone_active", None) and engine.microphone_active.is_set())
        if hasattr(self, "listen_diode"):
            self.listen_diode.setStyleSheet(self._status_diode_style(listening, "#39d98a", "#92f0bf"))
        if hasattr(self, "mic_diode"):
            self.mic_diode.setStyleSheet(self._status_diode_style(recording, "#ff4d5e", "#ff96a0"))
        if hasattr(self, "mic_status_label"):
            if recording:
                label = "Recording"
            elif listening:
                label = "Listening"
            else:
                label = "Microphone idle"
            self.mic_status_label.setText(label)
        if hasattr(self, "pipeline_telemetry_widget"):
            pipeline_snapshot = self._build_pipeline_visual_snapshot(
                shared_state.get_musetalk_pipeline_snapshot()
            )
            self.pipeline_telemetry_widget.update_snapshot(
                pipeline_snapshot,
                getattr(shared_state, "current_musetalk_frame_data", {}) or {},
            )
        paused = bool(getattr(engine, "playback_paused", None) and engine.playback_paused.is_set())
        paused = paused or bool(getattr(engine, "pause_after_chunk", None) and engine.pause_after_chunk.is_set())
        if paused != self._chat_runtime_border_paused:
            self._chat_runtime_border_paused = paused
            border_style = "border: 2px solid #d84a4a; border-radius: 10px;" if paused else ""
            for widget in (getattr(self, "system_console_tab", None), getattr(self, "chat_tab", None)):
                if widget is not None:
                    widget.setStyleSheet(border_style)
        self._refresh_preset_dirty_state()
        self.refresh_dry_run_status()

    def _count_rendered_chunk_frames(self, frame_dir, use_cache=True):
        frame_dir = str(frame_dir or "").strip()
        if not frame_dir or not os.path.isdir(frame_dir):
            return 0
        try:
            if not use_cache:
                count = 0
                with os.scandir(frame_dir) as entries:
                    for entry in entries:
                        if entry.is_file() and entry.name.lower().endswith(".png"):
                            count += 1
                return count
            stat = os.stat(frame_dir)
            cache_key = os.path.abspath(frame_dir)
            signature = (int(stat.st_mtime_ns), int(stat.st_size))
            cached = self._pipeline_frame_count_cache.get(cache_key)
            if cached and cached.get("signature") == signature:
                return int(cached.get("count", 0) or 0)
            count = 0
            with os.scandir(frame_dir) as entries:
                for entry in entries:
                    if entry.is_file() and entry.name.lower().endswith(".png"):
                        count += 1
            self._pipeline_frame_count_cache[cache_key] = {"signature": signature, "count": count}
            return count
        except Exception:
            return 0

    def _build_pipeline_visual_snapshot(self, snapshot):
        snapshot = dict(snapshot or {})
        chunks = [dict(item or {}) for item in snapshot.get("chunks", [])]
        for chunk in chunks:
            frame_dir = str(chunk.get("frame_dir", "") or "")
            rendered_count = 0
            if frame_dir:
                status = str(chunk.get("status", "") or "")
                rendered_count = self._count_rendered_chunk_frames(
                    frame_dir,
                    use_cache=status not in {"rendering"},
                )
            chunk["rendered_frame_count"] = rendered_count
            expected = int(chunk.get("expected_frame_count", 0) or 0)
            fps = int(chunk.get("fps", 0) or 0)
            duration = float(chunk.get("duration_seconds", 0.0) or 0.0)
            if expected <= 0 and fps > 0 and duration > 0:
                chunk["expected_frame_count"] = max(1, int(round(duration * fps)))
            elif expected <= 0 and rendered_count > 0 and str(chunk.get("status", "") or "") in {"rendered", "ready", "playing", "completed"}:
                chunk["expected_frame_count"] = rendered_count
        snapshot["chunks"] = chunks
        return snapshot

    def _build_persona_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("persona_tab")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMinimumSize(0, 0)

        widget = QtWidgets.QWidget()
        widget.setMinimumSize(0, 0)
        scroll.setWidget(widget)

        layout = QtWidgets.QVBoxLayout(widget)

        self.voice_combo = NoWheelComboBox()
        self.voice_combo.setObjectName("voice_combo")
        self.voice_combo.currentTextChanged.connect(self.on_voice_changed)
        layout.addWidget(QtWidgets.QLabel("Voice Clone"))
        layout.addWidget(self.voice_combo)

        self.emotional_text = QtWidgets.QPlainTextEdit()
        self.emotional_text.setObjectName("emotional_text")
        self.emotional_text.setPlaceholderText("Technical rules / expressive tags")
        self.emotional_text.setMinimumHeight(0)
        self.emotional_text.setMinimumSize(0, 90)
        self.system_prompt_text = QtWidgets.QPlainTextEdit()
        self.system_prompt_text.setObjectName("system_prompt_text")
        self.system_prompt_text.setPlaceholderText("System prompt")
        self.system_prompt_text.setMinimumHeight(0)
        self.system_prompt_text.setMinimumSize(0, 90)

        text_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        text_splitter.setChildrenCollapsible(False)
        text_splitter.setMinimumHeight(230)

        technical_group = QtWidgets.QGroupBox("Technical Rules (Tags)")
        technical_layout = QtWidgets.QVBoxLayout(technical_group)
        technical_layout.setContentsMargins(8, 10, 8, 8)
        technical_layout.addWidget(self.emotional_text)

        prompt_group = QtWidgets.QGroupBox("System Prompt")
        prompt_layout = QtWidgets.QVBoxLayout(prompt_group)
        prompt_layout.setContentsMargins(8, 10, 8, 8)
        prompt_layout.addWidget(self.system_prompt_text)

        text_splitter.addWidget(technical_group)
        text_splitter.addWidget(prompt_group)
        text_splitter.setStretchFactor(0, 1)
        text_splitter.setStretchFactor(1, 1)
        layout.addWidget(text_splitter, 1)

        apply_button = QtWidgets.QPushButton("Apply Changes")
        apply_button.setObjectName("btn_apply_text_config")
        apply_button.clicked.connect(self.apply_text_config)
        layout.addWidget(apply_button)
        return scroll

    def _build_body_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("body_tab")
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        self._body_tab_layout = layout

        config_box = QtWidgets.QGroupBox("Body Presets")
        config_layout = QtWidgets.QVBoxLayout(config_box)
        self.body_combo = NoWheelComboBox()
        self.body_combo.setObjectName("body_combo")
        self.body_combo.addItem("Default")
        config_layout.addWidget(self.body_combo)

        body_buttons = QtWidgets.QHBoxLayout()
        self.btn_body_load = QtWidgets.QPushButton("Load")
        self.btn_body_load.clicked.connect(self.load_body_config_from_combo)
        self.btn_body_save = QtWidgets.QPushButton("Save")
        self.btn_body_save.clicked.connect(self.save_current_body)
        self.btn_body_save_as = QtWidgets.QPushButton("Save As")
        self.btn_body_save_as.clicked.connect(self.save_body_dialog)
        self.btn_body_delete = QtWidgets.QPushButton("Delete")
        self.btn_body_delete.clicked.connect(self.delete_current_body)
        for widget in [self.btn_body_load, self.btn_body_save, self.btn_body_save_as, self.btn_body_delete]:
            body_buttons.addWidget(widget)
        config_layout.addLayout(body_buttons)
        layout.addWidget(config_box)

        top = QtWidgets.QHBoxLayout()
        self.emotion_combo = NoWheelComboBox()
        self.emotion_combo.addItems(["Neutral", "Happy", "Sad", "Angry", "Shy", "Surprised"])
        self.emotion_combo.currentTextChanged.connect(self.on_emotion_change)
        self.live_sync_checkbox = QtWidgets.QCheckBox("Live Sync")
        self.live_sync_checkbox.toggled.connect(self.toggle_live_sync)
        top.addWidget(self.emotion_combo)
        top.addStretch(1)
        top.addWidget(self.live_sync_checkbox)
        layout.addLayout(top)

        body_tools = QtWidgets.QHBoxLayout()
        self.btn_hand_doctor = QtWidgets.QPushButton("Hand Doctor")
        self.btn_hand_doctor.setObjectName("btn_hand_doctor")
        self.btn_hand_doctor.clicked.connect(self.open_hand_debugger)
        body_tools.addWidget(self.btn_hand_doctor)
        body_tools.addStretch(1)
        layout.addLayout(body_tools)

        # MuseTalk preprocessing moved into the MuseTalk addon system.


        # Loop Authoring moved into the MuseTalk addon system.

        for label, key, minimum, maximum in [
            ("L Depth", "idle_fwd_left", -200, 200),
            ("R Depth", "idle_fwd_right", -100, 100),
            ("Shoulder Down", "idle_arm_down", -100, 100),
            ("Shoulder Back", "idle_shoulder_back", -100, 100),
            ("Elbow Bend", "idle_elbow_bend", -250, 250),
            ("Arm Twist", "idle_arm_twist", -100, 100),
            ("Spine Sway", "spine_sway_mult", 0.0, 3.0),
            ("Spine Twist", "spine_twist_mult", 0.0, 3.0),
            ("Head Stabilize", "neck_stabilize", 0.0, 3.0),
        ]:
            slider = LabeledSlider(label, minimum, maximum, 0.0)
            slider.value_changed.connect(lambda value, k=key: self.update_pose_value(k, value))
            self.pose_sliders[key] = slider
            layout.addWidget(slider)

        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _build_vseeface_tab(self):
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        nested_tabs = NoWheelTabWidget()
        nested_tabs.setObjectName("vseeface_tabs")
        nested_tabs.addTab(self._build_body_tab(), "Body")
        nested_tabs.addTab(self._build_dynamics_tab(), "Dynamics")
        nested_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        layout.addWidget(nested_tabs, 1)

        controls_box = QtWidgets.QGroupBox("VSeeFace View")
        controls_layout = QtWidgets.QVBoxLayout(controls_box)
        controls_layout.setContentsMargins(12, 14, 12, 12)
        controls_layout.setSpacing(8)
        hint = QtWidgets.QLabel(
            "Hide NC and leave a tiny return window while VSeeFace stays on screen as the only visible avatar view."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        controls_layout.addWidget(hint)
        actions = QtWidgets.QHBoxLayout()
        self.btn_vseeface_hide_interface = QtWidgets.QPushButton("Hide NC Interface")
        self.btn_vseeface_hide_interface.clicked.connect(lambda: self.enter_external_avatar_focus("VSeeFace"))
        actions.addWidget(self.btn_vseeface_hide_interface)
        actions.addStretch(1)
        controls_layout.addLayout(actions)
        layout.addWidget(controls_box, 0)
        return container

    def _build_musetalk_parent_tab(self):
        nested_tabs = NoWheelTabWidget()
        nested_tabs.setObjectName("musetalk_tabs")
        nested_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        nested_tabs.currentChanged.connect(self._on_musetalk_tab_changed)
        self.musetalk_tabs = nested_tabs
        return nested_tabs

    def _build_vam_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("vam_tab")
        scroll.setWidgetResizable(True)

        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        summary = QtWidgets.QLabel(
            "VaM uses two channels: VMC for motion/head/hands, and a file bridge for emotion, speaking, and optional in-VaM audio."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(summary)

        bridge_box = QtWidgets.QGroupBox("VaM Bridge")
        bridge_layout = QtWidgets.QVBoxLayout(bridge_box)
        bridge_layout.setContentsMargins(12, 14, 12, 12)
        bridge_layout.setSpacing(8)

        bridge_form = QtWidgets.QFormLayout()
        bridge_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        bridge_form.addRow("VaM Root", self.vam_root_edit)
        bridge_form.addRow("Bridge Path", self.vam_bridge_root_edit)
        bridge_form.addRow("Target Atom UID", self.vam_target_atom_uid_edit)
        bridge_form.addRow("Target Storable ID", self.vam_target_storable_id_edit)
        bridge_form.addRow("VMC Host", self.vam_vmc_host_edit)
        bridge_form.addRow("VMC Port", self.vam_vmc_port_spin)
        bridge_layout.addLayout(bridge_form)
        bridge_layout.addWidget(self.vam_vmc_enabled_checkbox)
        bridge_layout.addWidget(self.vam_bridge_enabled_checkbox)
        bridge_layout.addWidget(self.vam_play_audio_in_vam_checkbox)
        bridge_layout.addWidget(self.vam_timeline_auto_resume_checkbox)

        vam_actions = QtWidgets.QHBoxLayout()
        vam_launch_icon = build_vam_launch_icon()
        self.btn_start_vam_desktop = QtWidgets.QPushButton("Start VaM Desktop")
        self.btn_start_vam_desktop.setObjectName("btn_start_vam_desktop")
        self.btn_start_vam_desktop.setToolTip(f"Launch {DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER} from the configured VaM Root.")
        self.btn_start_vam_desktop.setIcon(vam_launch_icon)
        self.btn_start_vam_desktop.setIconSize(QtCore.QSize(24, 24))
        self.btn_start_vam_desktop.clicked.connect(self.on_start_vam_desktop_clicked)
        vam_actions.addWidget(self.btn_start_vam_desktop)
        self.btn_start_vam_vr = QtWidgets.QPushButton("Start VaM VR")
        self.btn_start_vam_vr.setObjectName("btn_start_vam_vr")
        self.btn_start_vam_vr.setToolTip(f"Launch {DEFAULT_LOCAL_VAM_VR_LAUNCHER} from the configured VaM Root.")
        self.btn_start_vam_vr.setIcon(vam_launch_icon)
        self.btn_start_vam_vr.setIconSize(QtCore.QSize(24, 24))
        self.btn_start_vam_vr.clicked.connect(self.on_start_vam_vr_clicked)
        vam_actions.addWidget(self.btn_start_vam_vr)
        self.btn_vam_hide_interface = QtWidgets.QPushButton("Hide NC Interface")
        self.btn_vam_hide_interface.clicked.connect(lambda: self.enter_external_avatar_focus("VaM"))
        vam_actions.addWidget(self.btn_vam_hide_interface)
        vam_actions.addStretch(1)
        bridge_layout.addLayout(vam_actions)

        hint = QtWidgets.QLabel(
            "Recommended VaM setup: point NC at the VaM install root, keep VMC and bridge on, and let VaM head audio handle speech so the avatar remains the real speaker."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        bridge_layout.addWidget(hint)

        layout.addWidget(bridge_box)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _rehome_body_section_to_tab(self, section_widget, object_name):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        if section_widget is not None:
            try:
                body_layout = getattr(self, "_body_tab_layout", None)
                if body_layout is not None:
                    body_layout.removeWidget(section_widget)
            except Exception:
                pass
            section_widget.setParent(None)
            layout.addWidget(section_widget)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _build_dynamics_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("dynamics_tab")
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        for label, key, minimum, maximum in [
            ("Eye Activity", "eye_activity", 0.0, 3.0),
            ("Breath Speed", "breath_speed", 0.1, 4.0),
            ("Shoulder Lift", "shoulder_lift", 0.0, 5.0),
            ("Body Sway Speed", "idle_speed", 0.2, 3.0),
            ("Body Sway Intensity", "idle_intensity", 0.5, 10.0),
        ]:
            slider = LabeledSlider(label, minimum, maximum, 0.0)
            slider.value_changed.connect(lambda value, k=key: self.update_pose_value(k, value))
            self.pose_sliders[key] = slider
            layout.addWidget(slider)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _build_brain_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("brain_tab")
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        for label, key, minimum, maximum, default, is_int in [
            ("Temperature", "temperature", 0.1, 2.0, 1.22, False),
            ("Top P", "top_p", 0.1, 1.0, 0.9, False),
            ("Top K", "top_k", 0, 100, 40, True),
            ("Repeat Penalty", "repeat_penalty", 1.0, 2.0, 1.15, False),
            ("Min P", "min_p", 0.0, 0.5, 0.05, False),
        ]:
            slider = LabeledSlider(label, minimum, maximum, default, is_int=is_int)
            slider.value_changed.connect(lambda value, k=key, integer=is_int: self.update_brain_value(k, value, integer))
            self.brain_sliders[key] = slider
            layout.addWidget(slider)

        response_group = QtWidgets.QGroupBox("Response Length")
        response_layout = QtWidgets.QFormLayout(response_group)
        response_layout.setContentsMargins(10, 10, 10, 10)
        response_layout.setSpacing(8)

        self.limit_response_checkbox = QtWidgets.QCheckBox("Limit Response Length")
        self.limit_response_checkbox.setObjectName("limit_response_checkbox")
        self.limit_response_checkbox.setChecked(bool(RUNTIME_CONFIG.get("limit_response_length", False)))
        self.limit_response_checkbox.toggled.connect(self.on_limit_response_length_changed)
        response_layout.addRow(self.limit_response_checkbox)

        self.max_response_tokens_spin = NoWheelSpinBox()
        self.max_response_tokens_spin.setObjectName("max_response_tokens_spin")
        self.max_response_tokens_spin.setRange(32, 8192)
        self.max_response_tokens_spin.setSingleStep(32)
        self.max_response_tokens_spin.setValue(int(RUNTIME_CONFIG.get("max_response_tokens", DEFAULT_MAX_RESPONSE_TOKENS) or DEFAULT_MAX_RESPONSE_TOKENS))
        self.max_response_tokens_spin.valueChanged.connect(self.on_max_response_tokens_changed)
        response_layout.addRow("Maximum response length (tokens)", self.max_response_tokens_spin)

        self.max_response_tokens_spin.setEnabled(self.limit_response_checkbox.isChecked())
        layout.addWidget(response_group)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _build_chunking_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("chunking_tab")
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)

        hint = QtWidgets.QLabel(
            "Global pipeline tuning. These values affect chunking behavior system-wide and are not saved with personas."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(hint)

        groups = [
            (
                "Standard",
                [
                    ("Target Chars", "chunk_target_chars", 40, 220, int(RUNTIME_CONFIG.get("chunk_target_chars", 100) or 100), True),
                    ("Max Chars", "chunk_max_chars", 60, 320, int(RUNTIME_CONFIG.get("chunk_max_chars", 200) or 200), True),
                ],
            ),
            (
                "MuseTalk Non-Stream",
                [
                    ("Target Chars", "musetalk_chunk_target_chars", 60, 220, int(RUNTIME_CONFIG.get("musetalk_chunk_target_chars", 110) or 110), True),
                    ("Max Chars", "musetalk_chunk_max_chars", 80, 320, int(RUNTIME_CONFIG.get("musetalk_chunk_max_chars", 220) or 220), True),
                    ("Quickstart 1 Target", "musetalk_quickstart_1_target_chars", 60, 260, int(RUNTIME_CONFIG.get("musetalk_quickstart_1_target_chars", 170) or 170), True),
                    ("Quickstart 1 Max", "musetalk_quickstart_1_max_chars", 80, 360, int(RUNTIME_CONFIG.get("musetalk_quickstart_1_max_chars", 320) or 320), True),
                    ("Quickstart 2 Target", "musetalk_quickstart_2_target_chars", 60, 240, int(RUNTIME_CONFIG.get("musetalk_quickstart_2_target_chars", 130) or 130), True),
                    ("Quickstart 2 Max", "musetalk_quickstart_2_max_chars", 80, 320, int(RUNTIME_CONFIG.get("musetalk_quickstart_2_max_chars", 240) or 240), True),
                ],
            ),
            (
                "Streaming",
                [
                    ("Target Chars", "stream_chunk_target_chars", 40, 220, int(RUNTIME_CONFIG.get("stream_chunk_target_chars", 85) or 85), True),
                    ("Max Chars", "stream_chunk_max_chars", 60, 320, int(RUNTIME_CONFIG.get("stream_chunk_max_chars", 170) or 170), True),
                    ("First Chunk Min", "stream_first_chunk_min_chars", 10, 80, int(RUNTIME_CONFIG.get("stream_first_chunk_min_chars", 28) or 28), True),
                    ("First Flush (s)", "stream_force_flush_seconds", 0.2, 2.5, float(RUNTIME_CONFIG.get("stream_force_flush_seconds", 0.9) or 0.9), False),
                    ("Later Flush (s)", "stream_force_flush_later_seconds", 0.3, 4.0, float(RUNTIME_CONFIG.get("stream_force_flush_later_seconds", 1.4) or 1.4), False),
                ],
            ),
        ]

        for title, items in groups:
            box = QtWidgets.QGroupBox(title)
            box_layout = QtWidgets.QVBoxLayout(box)
            for label, key, minimum, maximum, default, is_int in items:
                slider = LabeledSlider(label, minimum, maximum, default, is_int=is_int)
                slider.value_changed.connect(lambda value, k=key, integer=is_int: self.update_chunking_value(k, value, integer))
                self.chunking_sliders[key] = slider
                box_layout.addWidget(slider)
            layout.addWidget(box)

        reset_row = QtWidgets.QHBoxLayout()
        reset_row.addStretch(1)
        reset_button = QtWidgets.QPushButton("Reset Chunking Defaults")
        reset_button.clicked.connect(self.reset_chunking_defaults)
        reset_row.addWidget(reset_button)
        layout.addLayout(reset_row)

        profile_box = QtWidgets.QGroupBox("Performance Profiles")
        profile_layout = QtWidgets.QVBoxLayout(profile_box)
        profile_row = QtWidgets.QHBoxLayout()
        self.chunking_profile_combo = NoWheelComboBox()
        self.chunking_profile_combo.setObjectName("chunking_profile_combo")
        self.chunking_profile_combo.addItem("No Saved Profiles")
        profile_row.addWidget(self.chunking_profile_combo, 1)
        self.btn_chunking_profile_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_chunking_profile_refresh.setObjectName("btn_chunking_profile_refresh")
        self.btn_chunking_profile_refresh.clicked.connect(self.refresh_performance_profile_list)
        profile_row.addWidget(self.btn_chunking_profile_refresh)
        profile_layout.addLayout(profile_row)

        profile_buttons = QtWidgets.QHBoxLayout()
        self.btn_chunking_profile_load = QtWidgets.QPushButton("Load Profile")
        self.btn_chunking_profile_load.setObjectName("btn_chunking_profile_load")
        self.btn_chunking_profile_load.clicked.connect(self.load_selected_chunking_profile)
        self.btn_chunking_profile_save = QtWidgets.QPushButton("Save Current As")
        self.btn_chunking_profile_save.setObjectName("btn_chunking_profile_save")
        self.btn_chunking_profile_save.clicked.connect(self.save_current_chunking_profile)
        self.btn_chunking_profile_delete = QtWidgets.QPushButton("Delete")
        self.btn_chunking_profile_delete.setObjectName("btn_chunking_profile_delete")
        self.btn_chunking_profile_delete.clicked.connect(self.delete_selected_chunking_profile)
        profile_buttons.addWidget(self.btn_chunking_profile_load)
        profile_buttons.addWidget(self.btn_chunking_profile_save)
        profile_buttons.addWidget(self.btn_chunking_profile_delete)
        profile_layout.addLayout(profile_buttons)
        layout.addWidget(profile_box)

        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _build_dry_run_tab(self):
        widget = QtWidgets.QWidget()
        widget.setObjectName("dry_run_tab")
        layout = QtWidgets.QVBoxLayout(widget)

        intro = QtWidgets.QLabel(
            "Dry Run profiles your current hardware and recommends safer startup/chunking values without changing the live pipeline while it measures."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        self.dry_run_target_spin = QtWidgets.QSpinBox()
        self.dry_run_target_spin.setObjectName("dry_run_target_spin")
        self.dry_run_target_spin.setRange(0, 12)
        self.dry_run_target_spin.setSpecialValueText("Auto")
        self.dry_run_target_spin.setValue(0)
        self.dry_run_target_spin.valueChanged.connect(lambda _: self.save_session())
        form.addRow("Target Reply Samples", self.dry_run_target_spin)
        self.dry_run_auto_replies_checkbox = QtWidgets.QCheckBox("Auto-generate follow-up replies")
        self.dry_run_auto_replies_checkbox.setObjectName("dry_run_auto_replies_checkbox")
        self.dry_run_auto_replies_checkbox.setChecked(True)
        self.dry_run_auto_replies_checkbox.toggled.connect(lambda _: self.save_session())
        form.addRow("Hands-Free", self.dry_run_auto_replies_checkbox)
        layout.addLayout(form)

        controls = QtWidgets.QHBoxLayout()
        self.btn_dry_run_start = QtWidgets.QPushButton("Arm Dry Run")
        self.btn_dry_run_start.setObjectName("btn_dry_run_start")
        self.btn_dry_run_start.clicked.connect(self.start_dry_run_session)
        self.btn_dry_run_stop = QtWidgets.QPushButton("Stop Dry Run")
        self.btn_dry_run_stop.setObjectName("btn_dry_run_stop")
        self.btn_dry_run_stop.clicked.connect(self.stop_dry_run_session)
        self.btn_dry_run_apply = QtWidgets.QPushButton("Apply Recommendation")
        self.btn_dry_run_apply.setObjectName("btn_dry_run_apply")
        self.btn_dry_run_apply.clicked.connect(self.apply_dry_run_recommendation)
        controls.addWidget(self.btn_dry_run_start)
        controls.addWidget(self.btn_dry_run_stop)
        controls.addWidget(self.btn_dry_run_apply)
        layout.addLayout(controls)

        self.dry_run_status_label = QtWidgets.QLabel("Dry Run idle.")
        self.dry_run_status_label.setStyleSheet("color: #d8dee9; font-weight: 600;")
        layout.addWidget(self.dry_run_status_label)

        self.dry_run_summary = QtWidgets.QPlainTextEdit()
        self.dry_run_summary.setReadOnly(True)
        self.dry_run_summary.setPlaceholderText("Recommendations and measured startup metrics will appear here.")
        layout.addWidget(self.dry_run_summary, 1)

        profile_box = QtWidgets.QGroupBox("Performance Profiles")
        profile_layout = QtWidgets.QVBoxLayout(profile_box)
        profile_row = QtWidgets.QHBoxLayout()
        self.performance_profile_combo = NoWheelComboBox()
        self.performance_profile_combo.setObjectName("performance_profile_combo")
        self.performance_profile_combo.addItem("No Saved Profiles")
        profile_row.addWidget(self.performance_profile_combo, 1)
        self.btn_profile_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_profile_refresh.setObjectName("btn_profile_refresh")
        self.btn_profile_refresh.clicked.connect(self.refresh_performance_profile_list)
        profile_row.addWidget(self.btn_profile_refresh)
        profile_layout.addLayout(profile_row)

        profile_buttons = QtWidgets.QHBoxLayout()
        self.btn_profile_load = QtWidgets.QPushButton("Load Profile")
        self.btn_profile_load.setObjectName("btn_profile_load")
        self.btn_profile_load.clicked.connect(self.load_selected_performance_profile)
        self.btn_profile_save = QtWidgets.QPushButton("Save Latest As")
        self.btn_profile_save.setObjectName("btn_profile_save_latest")
        self.btn_profile_save.clicked.connect(self.save_latest_performance_profile)
        self.btn_profile_delete = QtWidgets.QPushButton("Delete")
        self.btn_profile_delete.setObjectName("btn_profile_delete")
        self.btn_profile_delete.clicked.connect(self.delete_selected_performance_profile)
        profile_buttons.addWidget(self.btn_profile_load)
        profile_buttons.addWidget(self.btn_profile_save)
        profile_buttons.addWidget(self.btn_profile_delete)
        profile_layout.addLayout(profile_buttons)
        layout.addWidget(profile_box)
        return widget

    def _build_tutorials_tab(self):
        widget = QtWidgets.QWidget()
        widget.setObjectName("tutorials_tab")
        layout = QtWidgets.QVBoxLayout(widget)

        intro = QtWidgets.QLabel(
            "Tutorials are loaded from JSON files, so new walkthroughs can be added over time without hardcoding them into the application."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(intro)

        self.tutorials_list = QtWidgets.QListWidget()
        self.tutorials_list.setObjectName("tutorials_list")
        self.tutorials_list.currentRowChanged.connect(self.on_tutorial_selection_changed)
        layout.addWidget(self.tutorials_list, 1)

        self.tutorial_description = QtWidgets.QPlainTextEdit()
        self.tutorial_description.setObjectName("tutorial_description")
        self.tutorial_description.setReadOnly(True)
        self.tutorial_description.setPlaceholderText("Select a tutorial to see its description.")
        layout.addWidget(self.tutorial_description, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.btn_tutorial_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_tutorial_refresh.setObjectName("btn_tutorial_refresh")
        self.btn_tutorial_refresh.clicked.connect(self.refresh_tutorial_list)
        self.btn_tutorial_start = QtWidgets.QPushButton("Start Tutorial")
        self.btn_tutorial_start.setObjectName("btn_tutorial_start")
        self.btn_tutorial_start.clicked.connect(self.start_selected_tutorial)
        buttons.addWidget(self.btn_tutorial_refresh)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_tutorial_start)
        layout.addLayout(buttons)
        return widget

    def _build_addons_tab(self):
        widget = QtWidgets.QWidget()
        widget.setObjectName("addons_tab")
        layout = QtWidgets.QVBoxLayout(widget)

        intro = QtWidgets.QLabel(
            "Manage addon loading here. Category toggles act like parent switches: if a parent category is off, all child addons under it are effectively off too. Changes here are global and apply on next launch."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(intro)

        controls = QtWidgets.QHBoxLayout()
        self.btn_addons_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_addons_refresh.setObjectName("btn_addons_refresh")
        self.btn_addons_refresh.clicked.connect(self._refresh_addons_management_ui)
        controls.addWidget(self.btn_addons_refresh)
        self.addons_restart_badge = QtWidgets.QLabel("Restart required")
        self.addons_restart_badge.setObjectName("addons_restart_badge")
        self.addons_restart_badge.setVisible(False)
        self.addons_restart_badge.setStyleSheet(
            "color: #ffb4b4; background: rgba(216, 74, 74, 0.16); border: 1px solid #d84a4a; border-radius: 10px; padding: 4px 10px; font-weight: 700;"
        )
        controls.addWidget(self.addons_restart_badge)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.addons_restart_note = QtWidgets.QLabel(
            "These toggles are saved in the session, not in presets. Already loaded addons keep running until you restart Neural Companion."
        )
        self.addons_restart_note.setWordWrap(True)
        self.addons_restart_note.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(self.addons_restart_note)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        layout.addWidget(scroll, 1)

        content = QtWidgets.QWidget()
        scroll.setWidget(content)
        self.addons_management_layout = QtWidgets.QVBoxLayout(content)
        self.addons_management_layout.setContentsMargins(0, 0, 0, 0)
        self.addons_management_layout.setSpacing(10)
        self._refresh_addons_management_ui()
        return widget

    def _on_addon_category_toggled(self, category_id, checked):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return
        manager.set_category_enabled(str(category_id or ""), bool(checked))
        self._refresh_addons_management_ui()
        self.save_session()

    def _on_addon_global_toggled(self, addon_id, checked):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return
        manager.set_addon_enabled(str(addon_id or ""), bool(checked))
        self._refresh_addons_management_ui()
        self.save_session()

    def _refresh_addons_management_ui(self):
        layout = getattr(self, "addons_management_layout", None)
        manager = getattr(self, "_addon_manager", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        snapshot = manager.get_addon_registry_snapshot() if manager is not None else []
        if hasattr(self, "addons_restart_badge"):
            pending = bool(manager.has_pending_restart_changes()) if manager is not None else False
            self.addons_restart_badge.setVisible(pending)
            if pending and manager is not None:
                summary = manager.get_pending_restart_changes_summary()
                addon_changes = int(summary.get("addon_changes", 0) or 0)
                category_changes = int(summary.get("category_changes", 0) or 0)
                parts = []
                if addon_changes:
                    parts.append(f"{addon_changes} addon{'s' if addon_changes != 1 else ''}")
                if category_changes:
                    parts.append(f"{category_changes} categor{'y' if category_changes == 1 else 'ies'}")
                suffix = ", ".join(parts) if parts else "changes"
                self.addons_restart_badge.setText(f"Restart required: {suffix}")
        if not snapshot:
            empty = QtWidgets.QLabel("No addons discovered yet.")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #8ea3b8;")
            layout.addWidget(empty)
            layout.addStretch(1)
            return
        for category in snapshot:
            category_box = QtWidgets.QGroupBox(str(category.get("label") or "Addons"))
            category_layout = QtWidgets.QVBoxLayout(category_box)
            category_layout.setContentsMargins(12, 12, 12, 12)
            category_layout.setSpacing(8)

            header_row = QtWidgets.QHBoxLayout()
            enabled_checkbox = QtWidgets.QCheckBox("Enabled")
            enabled_checkbox.setChecked(bool(category.get("enabled", True)))
            enabled_checkbox.toggled.connect(
                lambda checked, category_id=str(category.get("id") or ""): self._on_addon_category_toggled(category_id, checked)
            )
            header_row.addWidget(enabled_checkbox)
            header_row.addStretch(1)
            category_layout.addLayout(header_row)

            category_hint = QtWidgets.QLabel(
                "Turning this parent category off disables all child addons under it on next launch."
            )
            category_hint.setWordWrap(True)
            category_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            category_layout.addWidget(category_hint)

            category_enabled = bool(category.get("enabled", True))
            for addon in list(category.get("addons", []) or []):
                row_frame = QtWidgets.QFrame()
                row_frame.setObjectName("Panel")
                row_layout = QtWidgets.QVBoxLayout(row_frame)
                row_layout.setContentsMargins(10, 10, 10, 10)
                row_layout.setSpacing(4)

                top_row = QtWidgets.QHBoxLayout()
                addon_checkbox = QtWidgets.QCheckBox(str(addon.get("name") or addon.get("id") or "Addon"))
                addon_checkbox.setChecked(bool(addon.get("enabled", True)))
                addon_checkbox.setEnabled(category_enabled)
                addon_checkbox.toggled.connect(
                    lambda checked, addon_id=str(addon.get("id") or ""): self._on_addon_global_toggled(addon_id, checked)
                )
                top_row.addWidget(addon_checkbox)

                status_bits = []
                if not category_enabled:
                    status_bits.append("inactive: parent category disabled")
                elif not bool(addon.get("effective_enabled", True)):
                    status_bits.append("inactive on next launch")
                else:
                    status_bits.append("active on next launch")
                record_state = str(addon.get("state") or "").strip()
                if record_state:
                    status_bits.append(f"current state: {record_state}")
                status = QtWidgets.QLabel(" | ".join(status_bits))
                status.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                top_row.addStretch(1)
                top_row.addWidget(status, 0, QtCore.Qt.AlignRight)
                row_layout.addLayout(top_row)

                meta_bits = [str(addon.get("id") or "").strip()]
                version = str(addon.get("version") or "").strip()
                if version:
                    meta_bits.append(f"v{version}")
                permissions = list(addon.get("permissions", []) or [])
                if permissions:
                    meta_bits.append(", ".join(permissions))
                meta = QtWidgets.QLabel(" | ".join([bit for bit in meta_bits if bit]))
                meta.setWordWrap(True)
                meta.setStyleSheet("color: #6f8599; font-size: 11px;")
                row_layout.addWidget(meta)

                description = str(addon.get("description") or "").strip()
                if description:
                    description_label = QtWidgets.QLabel(description)
                    description_label.setWordWrap(True)
                    description_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
                    row_layout.addWidget(description_label)

                category_layout.addWidget(row_frame)
            layout.addWidget(category_box)
        layout.addStretch(1)

    def _build_right_panel(self):
        panel = self._wrap_panel()
        panel.setMinimumSize(0, 0)
        panel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        outer_layout = QtWidgets.QVBoxLayout(panel)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMinimumSize(0, 0)
        scroll.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        outer_layout.addWidget(scroll)

        content = QtWidgets.QWidget()
        content.setMinimumSize(0, 0)
        scroll.setWidget(content)

        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(self._make_header("Operational View", "Conversation + Telemetry"))

        self.pipeline_telemetry_box = QtWidgets.QGroupBox("Buffer Race")
        self.pipeline_telemetry_box.setMinimumSize(0, 0)
        self.pipeline_telemetry_box.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        telemetry_layout = QtWidgets.QVBoxLayout(self.pipeline_telemetry_box)
        telemetry_layout.setContentsMargins(10, 12, 10, 10)
        telemetry_layout.setSpacing(8)
        self.pipeline_telemetry_widget = PipelineTelemetryWidget()
        telemetry_layout.addWidget(self.pipeline_telemetry_widget)
        layout.addWidget(self.pipeline_telemetry_box)

        self.right_tabs = NoWheelTabWidget()
        self.right_tabs.setObjectName("right_tabs")
        self.right_tabs.setMinimumSize(0, 0)
        self.right_tabs.setMinimumHeight(230)
        self.right_tabs.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.right_tabs.currentChanged.connect(self._on_right_tab_changed)
        layout.addWidget(self.right_tabs, 1)

        system_tab = QtWidgets.QWidget()
        system_tab.setObjectName("system_console_tab")
        system_tab.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        system_layout = QtWidgets.QVBoxLayout(system_tab)
        console_header = QtWidgets.QHBoxLayout()
        self.console_status = QtWidgets.QLabel("0 lines | autoscroll on")
        console_header.addWidget(self.console_status)
        console_header.addStretch(1)
        self.console_autoscroll_button = QtWidgets.QPushButton("Autoscroll: On")
        self.console_autoscroll_button.clicked.connect(self.toggle_console_autoscroll)
        console_header.addWidget(self.console_autoscroll_button)
        self.console_clear_button = QtWidgets.QPushButton("Clear")
        self.console_clear_button.clicked.connect(self.clear_console)
        console_header.addWidget(self.console_clear_button)
        self.console_edit = QtWidgets.QPlainTextEdit()
        self.console_edit.setObjectName("console_edit")
        self.console_edit.setReadOnly(True)
        self.console_edit.setMinimumSize(0, 0)
        self.console_edit.setMinimumHeight(90)
        system_layout.addLayout(console_header)
        system_layout.addWidget(self.console_edit, 1)
        self.system_console_tab = system_tab
        self.right_tabs.addTab(system_tab, "System Console")

        chat_tab = QtWidgets.QWidget()
        chat_tab.setObjectName("chat_runtime_tab")
        chat_tab.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        chat_layout = QtWidgets.QVBoxLayout(chat_tab)
        chat_header = QtWidgets.QHBoxLayout()
        self.chat_status = QtWidgets.QLabel("autoscroll on | context 0/20")
        chat_header.addWidget(self.chat_status)
        chat_header.addStretch(1)
        chat_font_label = QtWidgets.QLabel("Font Size")
        chat_header.addWidget(chat_font_label)
        self.chat_font_size_combo = NoWheelComboBox()
        self.chat_font_size_combo.setObjectName("chat_font_size_combo")
        self.chat_font_size_combo.setMinimumWidth(74)
        for size in self._chat_font_size_choices():
            self.chat_font_size_combo.addItem(str(size), size)
        self.chat_font_size_combo.blockSignals(True)
        try:
            default_index = self.chat_font_size_combo.findData(12)
            if default_index >= 0:
                self.chat_font_size_combo.setCurrentIndex(default_index)
        finally:
            self.chat_font_size_combo.blockSignals(False)
        self.chat_font_size_combo.currentIndexChanged.connect(self.on_chat_font_size_changed)
        chat_header.addWidget(self.chat_font_size_combo)
        self.chat_quick_save_button = QtWidgets.QPushButton("Quick Save")
        self.chat_quick_save_button.clicked.connect(self.quick_save_chat_context)
        chat_header.addWidget(self.chat_quick_save_button)
        self.chat_quick_load_button = QtWidgets.QPushButton("Quick Load")
        self.chat_quick_load_button.clicked.connect(self.quick_load_chat_context)
        chat_header.addWidget(self.chat_quick_load_button)
        self.chat_edit_mode_button = QtWidgets.QPushButton("Edit Mode")
        self.chat_edit_mode_button.clicked.connect(self.enter_chat_edit_mode)
        chat_header.addWidget(self.chat_edit_mode_button)
        self.chat_apply_edit_button = QtWidgets.QPushButton("Apply Edit")
        self.chat_apply_edit_button.clicked.connect(self.apply_chat_edit_mode)
        self.chat_apply_edit_button.setVisible(False)
        chat_header.addWidget(self.chat_apply_edit_button)
        self.chat_cancel_edit_button = QtWidgets.QPushButton("Cancel Edit")
        self.chat_cancel_edit_button.clicked.connect(self.cancel_chat_edit_mode)
        self.chat_cancel_edit_button.setVisible(False)
        chat_header.addWidget(self.chat_cancel_edit_button)
        self.chat_autoscroll_button = QtWidgets.QPushButton("Autoscroll: On")
        self.chat_autoscroll_button.clicked.connect(self.toggle_chat_autoscroll)
        chat_header.addWidget(self.chat_autoscroll_button)
        self.chat_clear_button = QtWidgets.QPushButton("Clear")
        self.chat_clear_button.clicked.connect(self.clear_chat)
        chat_header.addWidget(self.chat_clear_button)
        self.chat_edit = QtWidgets.QTextEdit()
        self.chat_edit.setObjectName("chat_edit")
        self.chat_edit.setReadOnly(True)
        self.chat_edit.setMinimumSize(0, 0)
        self.chat_edit.setMinimumHeight(90)
        self._apply_chat_font_size(12, update_combo=False)
        self.chat_edit.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.chat_edit.customContextMenuRequested.connect(self._show_chat_context_menu)
        chat_layout.addLayout(chat_header)
        chat_layout.addWidget(self.chat_edit, 1)
        self.chat_tab = chat_tab
        self.right_tabs.addTab(chat_tab, "Chat")

        controls = QtWidgets.QGridLayout()
        self.btn_regenerate = self._make_action_button("Regenerate", lambda: self.trigger_control_action("regenerate_response"))
        self.btn_retry = self._make_action_button("Retry Input", lambda: self.trigger_control_action("retry_user_input"))
        self.btn_pause = self._make_action_button("Pause / Resume", lambda: self.trigger_control_action("pause_speech"))
        self.btn_skip = self._make_action_button("Skip Speech", lambda: self.trigger_control_action("skip_speech"))
        self.btn_skip_user = self._make_action_button("Skip User Reply", lambda: self.trigger_control_action("skip_user_reply"))
        self._control_action_buttons = {
            "regenerate_response": self.btn_regenerate,
            "retry_user_input": self.btn_retry,
            "pause_speech": self.btn_pause,
            "skip_speech": self.btn_skip,
            "skip_user_reply": self.btn_skip_user,
        }
        for index, button in enumerate([self.btn_regenerate, self.btn_retry, self.btn_pause, self.btn_skip, self.btn_skip_user]):
            controls.addWidget(button, 0, index)
        layout.addLayout(controls)

        self.btn_start = QtWidgets.QPushButton("INITIALIZE SYSTEM")
        self.btn_start.setObjectName("btn_start_engine")
        self.btn_start.clicked.connect(self.start_engine)
        self.btn_start.setStyleSheet("background: #1d6e52; border: 1px solid #2cc985; font-size: 13px; min-height: 44px;")
        self.btn_stop = QtWidgets.QPushButton("TERMINATE")
        self.btn_stop.setObjectName("btn_stop_engine")
        self.btn_stop.clicked.connect(self.stop_engine)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("background: #6f2222; border: 1px solid #c92c2c; min-height: 42px;")
        self.btn_reset = QtWidgets.QPushButton("RESET CHAT MEMORY")
        self.btn_reset.setObjectName("btn_reset_chat")
        self.btn_reset.clicked.connect(self.reset_chat_session)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_reset)

        self._qt_hotkey_shortcuts = {}
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()

        return panel

    def _make_action_button(self, text, handler):
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(handler)
        button.setEnabled(False)
        button.setMinimumHeight(50)
        return button

    def _build_ui_hotkey_timer(self):
        self._ui_hotkey_last_triggered_at = {}
        self._ui_hotkey_poll_timer = QtCore.QTimer(self)
        self._ui_hotkey_poll_timer.setInterval(45)
        self._ui_hotkey_poll_timer.timeout.connect(self._poll_exact_ui_hotkeys)
        self._ui_hotkey_poll_timer.start()

    def _connect_console_bridge(self):
        self._console_bridge.text_ready.connect(self._append_console_text)
        self._console_bridge.chat_ready.connect(self._append_chat_text)
        self._console_bridge.status_ready.connect(self._update_console_status)
        self._console_bridge.chat_status_ready.connect(self._update_chat_status)
        self._console_bridge.rebuild_chat_ready.connect(self._on_chat_rebuild_requested)

    def _on_chat_rebuild_requested(self):
        scroll_state = self._capture_vertical_scroll_state(self.chat_edit) if hasattr(self, "chat_edit") else None
        self._rebuild_chat_view_from_history(force=True, preserve_scroll_state=scroll_state)

    def _update_readonly_text_safely(self, widget, text):
        current_text = widget.toPlainText()
        if current_text == text:
            return
        scrollbar = widget.verticalScrollBar()
        old_value = scrollbar.value()
        old_maximum = scrollbar.maximum()
        cursor = widget.textCursor()
        has_selection = cursor.hasSelection()
        if widget.hasFocus() or has_selection:
            return
        widget.setPlainText(text)
        new_scrollbar = widget.verticalScrollBar()
        if old_value >= max(old_maximum - 2, 0):
            new_scrollbar.setValue(new_scrollbar.maximum())
        else:
            new_scrollbar.setValue(min(old_value, new_scrollbar.maximum()))

    def _append_console_text(self, text):
        cursor = self.console_edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(text)
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "✓ Connected to LM Studio" in line:
                self._tutorial_lm_studio_running = True
                self.emit_tutorial_event("lm_studio_connected", {"line": line})
            elif "✗ Could not connect to LM Studio" in line:
                self._tutorial_lm_studio_running = False
                self.emit_tutorial_event("lm_studio_disconnected", {"line": line})
                self.emit_tutorial_event("error_detected", {"line": line})
            elif "VOICE ASSISTANT READY" in line:
                self.emit_tutorial_event("engine_initialized", {"line": line})
            elif "✓ PocketTTS backend loaded successfully" in line or "✓ ChatterboxTurboTTS loaded successfully" in line:
                self.emit_tutorial_event("tts_initialized", {"line": line})
            elif "✅ [MuseTalk] Avatar prepared:" in line:
                self.emit_tutorial_event("avatar_initialized", {"line": line})
            elif any(marker in line for marker in ("ERROR", "Error", "Failed", "CRITICAL", "Traceback", "✗", "Exception")):
                self.emit_tutorial_event("error_detected", {"line": line})
        if self.console_auto_scroll:
            self.console_edit.setTextCursor(cursor)
            self.console_edit.ensureCursorVisible()
            QtCore.QTimer.singleShot(0, lambda w=self.console_edit: self._force_scroll_to_bottom(w))

    def _force_scroll_to_bottom(self, widget):
        scrollbar = widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _capture_vertical_scroll_state(self, widget):
        scrollbar = widget.verticalScrollBar()
        maximum = max(1, int(scrollbar.maximum()))
        value = int(scrollbar.value())
        return {"value": value, "ratio": float(value) / float(maximum)}

    def _restore_vertical_scroll_state(self, widget, state):
        if not state:
            return
        scrollbar = widget.verticalScrollBar()
        if not scrollbar:
            return
        value = int(state.get("value", 0) or 0)
        ratio = float(state.get("ratio", 0.0) or 0.0)
        maximum = int(scrollbar.maximum())
        target = min(max(value, 0), maximum)
        if maximum > 0:
            target = min(max(target, 0), maximum)
        scrollbar.setValue(target)
        if maximum > 0 and target == 0 and ratio > 0.0:
            scrollbar.setValue(int(round(maximum * ratio)))

    def _restore_system_shaping_scroll_state(self, state):
        if not state or not hasattr(self, "system_shaping_scroll"):
            return
        self._restore_vertical_scroll_state(self.system_shaping_scroll, state)

    def _append_chat_text(self, text):
        if getattr(self, "chat_edit_mode", False):
            return
        text = re.sub(r"(?<!\n)(💬 You(?: \([^)]*\))?:|🤖 Assistant:)", r"\n\1", text)
        if not self.chat_edit.toPlainText():
            text = text.lstrip()
        cursor = self.chat_edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        default_format = QtGui.QTextCharFormat()
        default_format.setForeground(QtGui.QColor("#e5e9f0"))
        default_format.setFont(QtGui.QFont("Segoe UI", self._current_chat_font_size()))
        speaker_format = QtGui.QTextCharFormat()
        speaker_format.setForeground(QtGui.QColor("#f2f5f9"))
        speaker_format.setFont(QtGui.QFont("Segoe UI", self._current_chat_font_size()))
        speaker_format.setFontWeight(QtGui.QFont.Bold)

        for chunk in re.split(r"(\n)", text):
            if chunk == "":
                continue
            if chunk == "\n":
                cursor.insertText(chunk, default_format)
                continue
            speaker_match = re.match(r"(💬 You(?: \([^)]*\))?:)", chunk)
            if speaker_match:
                speaker = speaker_match.group(1)
                cursor.insertText(speaker, speaker_format)
                remainder = chunk[len(speaker):]
                if remainder:
                    cursor.insertText(remainder, default_format)
                continue
            if chunk.startswith("🤖 Assistant:"):
                cursor.insertText("🤖 Assistant:", speaker_format)
                remainder = chunk[len("🤖 Assistant:"):]
                if remainder:
                    cursor.insertText(remainder, default_format)
                continue
            cursor.insertText(chunk, default_format)
        if self.chat_auto_scroll:
            self.chat_edit.setTextCursor(cursor)
            self.chat_edit.ensureCursorVisible()
            QtCore.QTimer.singleShot(0, lambda w=self.chat_edit: self._force_scroll_to_bottom(w))

    def _update_console_status(self, lines, _auto_scroll):
        state = "on" if self.console_auto_scroll else "off"
        self.console_status.setText(f"{lines} lines | autoscroll {state}")
        self.console_autoscroll_button.setText(f"Autoscroll: {'On' if self.console_auto_scroll else 'Off'}")

    def _update_chat_status(self, lines, _auto_scroll):
        state = "on" if self.chat_auto_scroll else "off"
        edit_suffix = " | edit mode" if getattr(self, "chat_edit_mode", False) else ""
        context_text, capped = self._chat_context_usage_label() if hasattr(self, "chat_status") else ("", False)
        context_suffix = f" | {context_text}" if context_text else ""
        self.chat_status.setText(f"autoscroll {state}{context_suffix}{edit_suffix}")
        self.chat_status.setStyleSheet("color: #ff6b6b;" if capped else "")
        self.chat_autoscroll_button.setText(f"Autoscroll: {'On' if self.chat_auto_scroll else 'Off'}")

    def toggle_console_autoscroll(self):
        self.console_auto_scroll = not self.console_auto_scroll
        self._update_console_status(self._console_redirect.line_count, int(self.console_auto_scroll))
        if self.console_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.console_edit: self._force_scroll_to_bottom(w))

    def toggle_chat_autoscroll(self):
        self.chat_auto_scroll = not self.chat_auto_scroll
        self._update_chat_status(self._console_redirect.chat_line_count, int(self.chat_auto_scroll))
        if self.chat_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.chat_edit: self._force_scroll_to_bottom(w))

    def _on_right_tab_changed(self, index):
        if not hasattr(self, "right_tabs"):
            return
        tab_text = str(self.right_tabs.tabText(index) or "").strip().lower()
        if tab_text == "system console" and self.console_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.console_edit: self._force_scroll_to_bottom(w))
        elif tab_text == "chat" and self.chat_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.chat_edit: self._force_scroll_to_bottom(w))

    def _publish_addon_event(self, event_name, payload=None):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return
        try:
            manager.publish_event(str(event_name), dict(payload or {}))
        except Exception as exc:
            print(f"⚠️ [Addons] Event publish failed for {event_name}: {exc}")

    def _current_ui_focus_path(self):
        path = []
        top_title = ""
        if hasattr(self, "tabs"):
            top_index = self.tabs.currentIndex()
            if top_index >= 0:
                top_title = str(self.tabs.tabText(top_index) or "").strip()
                if top_title:
                    path.append(top_title)
        if top_title.lower() == "musetalk" and hasattr(self, "musetalk_tabs"):
            nested_index = self.musetalk_tabs.currentIndex()
            if nested_index >= 0:
                nested_title = str(self.musetalk_tabs.tabText(nested_index) or "").strip()
                if nested_title:
                    path.append(nested_title)
        return path

    def _emit_tab_focus_changed_event(self, *, scope, container, previous_title, current_title):
        current_path = self._current_ui_focus_path()
        payload = {
            "scope": str(scope or ""),
            "container": str(container or ""),
            "previous_tab_title": str(previous_title or ""),
            "current_tab_title": str(current_title or ""),
            "current_path": current_path,
        }
        self._publish_addon_event("ui.tab_focus_changed", payload)

    def _on_left_tab_changed(self, index):
        if not hasattr(self, "tabs"):
            return
        current_title = str(self.tabs.tabText(index) or "").strip()
        previous_title = getattr(self, "_last_left_tab_title", "")
        self._last_left_tab_title = current_title
        self._emit_tab_focus_changed_event(
            scope="top_level",
            container="left_tabs",
            previous_title=previous_title,
            current_title=current_title,
        )

    def _on_musetalk_tab_changed(self, index):
        if not hasattr(self, "musetalk_tabs"):
            return
        current_title = str(self.musetalk_tabs.tabText(index) or "").strip()
        previous_title = getattr(self, "_last_musetalk_tab_title", "")
        self._last_musetalk_tab_title = current_title
        self._emit_tab_focus_changed_event(
            scope="nested",
            container="musetalk_tabs",
            previous_title=previous_title,
            current_title=current_title,
        )

    def clear_console(self):
        self.console_edit.clear()
        self._console_redirect.line_count = 0
        self._update_console_status(0, int(self.console_auto_scroll))

    def clear_chat(self):
        self.chat_edit.clear()
        self._console_redirect.chat_line_count = 0
        self._update_chat_status(0, int(self.chat_auto_scroll))

    def on_voice_changed(self, voice_name):
        if voice_name and voice_name != "No .wav found":
            update_runtime_config("voice_path", os.path.join("voices", voice_name))
        self._refresh_tts_runtime_summary()

    def browse_pocket_tts_python(self):
        pocket_tts_python_edit = getattr(self, "pocket_tts_python_edit", None)
        start_dir = pocket_tts_python_edit.text().strip() if pocket_tts_python_edit is not None else ""
        path, _ = QtDialogService(self).open_file(
            "Select PocketTTS Python",
            start_dir or "",
            "Python (*.exe);;All Files (*.*)",
        )
        if not path:
            return
        if pocket_tts_python_edit is not None:
            pocket_tts_python_edit.setText(path)
        self.on_pocket_tts_python_changed()

    def on_pocket_tts_python_changed(self):
        pocket_tts_python_edit = getattr(self, "pocket_tts_python_edit", None)
        if pocket_tts_python_edit is None:
            return
        update_runtime_config("pocket_tts_python", pocket_tts_python_edit.text().strip())
        self.save_session()

    def on_vam_vmc_enabled_changed(self, enabled):
        update_runtime_config("vam_vmc_enabled", bool(enabled))
        self.save_session()

    def on_vam_bridge_enabled_changed(self, enabled):
        update_runtime_config("vam_bridge_enabled", bool(enabled))
        self.save_session()

    def on_vam_play_audio_in_vam_changed(self, enabled):
        update_runtime_config("vam_play_audio_in_vam", bool(enabled))
        self.save_session()

    def on_vam_timeline_auto_resume_changed(self, enabled):
        update_runtime_config("vam_timeline_auto_resume", bool(enabled))
        self.save_session()

    def on_vam_vmc_host_changed(self):
        update_runtime_config("vam_vmc_host", self.vam_vmc_host_edit.text().strip() or "127.0.0.1")
        self.save_session()

    def on_vam_vmc_port_changed(self, value):
        update_runtime_config("vam_vmc_port", int(value))
        self.save_session()

    def _current_vam_root_value(self):
        raw = self.vam_root_edit.text().strip() if hasattr(self, "vam_root_edit") else str(RUNTIME_CONFIG.get("vam_root", getattr(engine, "DEFAULT_VAM_ROOT", "")) or getattr(engine, "DEFAULT_VAM_ROOT", ""))
        return engine.normalize_vam_root(raw)

    def _current_vam_bridge_root_value(self):
        return engine.derive_vam_bridge_root(self._current_vam_root_value())

    def _refresh_vam_path_widgets(self):
        if hasattr(self, "vam_root_edit"):
            self.vam_root_edit.setText(self._current_vam_root_value())
        if hasattr(self, "vam_bridge_root_edit"):
            self.vam_bridge_root_edit.setText(self._current_vam_bridge_root_value())

    def _ensure_vam_root_for_launch(self):
        current_root = self._current_vam_root_value()
        if str(current_root or "").strip():
            return current_root
        fallback_root = engine.normalize_vam_root(DEFAULT_LOCAL_VAM_ROOT)
        if hasattr(self, "vam_root_edit"):
            self.vam_root_edit.setText(fallback_root)
        self.on_vam_root_changed()
        return fallback_root

    def on_vam_root_changed(self):
        normalized_root = self._current_vam_root_value()
        derived_bridge_root = engine.derive_vam_bridge_root(normalized_root)
        if hasattr(self, "vam_root_edit"):
            self.vam_root_edit.setText(normalized_root)
        if hasattr(self, "vam_bridge_root_edit"):
            self.vam_bridge_root_edit.setText(derived_bridge_root)
        update_runtime_config("vam_root", normalized_root)
        update_runtime_config("vam_bridge_root", derived_bridge_root)
        self.save_session()

    def on_vam_bridge_root_changed(self):
        self.on_vam_root_changed()

    def _launch_vam_target(self, launch_name, title):
        vam_root = self._ensure_vam_root_for_launch()
        target_path = Path(vam_root) / str(launch_name or "").strip()
        if not target_path.exists():
            QtWidgets.QMessageBox.warning(
                self,
                title,
                f"Could not find {launch_name} at:\n{target_path}",
            )
            return
        try:
            if target_path.suffix.lower() == ".bat":
                subprocess.Popen(["cmd", "/c", str(target_path)], cwd=str(target_path.parent))
            else:
                subprocess.Popen([str(target_path)], cwd=str(target_path.parent))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                title,
                f"Failed to launch {launch_name}.\n\n{exc}",
            )

    def on_start_vam_desktop_clicked(self):
        self._launch_vam_target(DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER, "Start VaM Desktop")

    def on_start_vam_vr_clicked(self):
        self._launch_vam_target(DEFAULT_LOCAL_VAM_VR_LAUNCHER, "Start VaM VR")

    def on_vam_target_atom_uid_changed(self):
        update_runtime_config("vam_target_atom_uid", self.vam_target_atom_uid_edit.text().strip() or "Person")
        self.save_session()

    def on_vam_target_storable_id_changed(self):
        update_runtime_config("vam_target_storable_id", self.vam_target_storable_id_edit.text().strip())
        self.save_session()

    def _toggle_pocket_tts_advanced(self, checked):
        if hasattr(self, "pocket_tts_advanced_group"):
            self.pocket_tts_advanced_group.setVisible(bool(checked))
        if hasattr(self, "pocket_tts_advanced_toggle"):
            self.pocket_tts_advanced_toggle.setText(
                "Hide Advanced PocketTTS Override" if checked else "Show Advanced PocketTTS Override"
            )

    def _sync_tab_widget_height(self, tabs):
        if tabs is None:
            return
        try:
            tabs.setMinimumHeight(0)
            tabs.setMaximumHeight(16777215)
            tabs.adjustSize()
            tabs.updateGeometry()
            parent = tabs.parentWidget()
            if parent is not None:
                parent.updateGeometry()
        except Exception:
            pass

    def _sync_host_settings_tabs_height(self):
        self._sync_tab_widget_height(getattr(self, "host_settings_tabs", None))

    def _toggle_performance_guidance(self, checked):
        if hasattr(self, "guidance_box"):
            self.guidance_box.setVisible(bool(checked))
        if hasattr(self, "performance_guidance_toggle"):
            self.performance_guidance_toggle.setText(
                "Hide Performance Guidance" if checked else "Show Performance Guidance"
            )
        self._sync_host_settings_tabs_height()

    def _ensure_pocket_tts_python_path(self):
        pocket_tts_python_edit = getattr(self, "pocket_tts_python_edit", None)
        if pocket_tts_python_edit is None:
            fallback = str(getattr(engine, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
            if fallback and os.path.exists(fallback):
                update_runtime_config("pocket_tts_python", fallback)
                return fallback
            return ""
        current = pocket_tts_python_edit.text().strip()
        if current:
            return current
        fallback = str(getattr(engine, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
        if fallback and os.path.exists(fallback):
            pocket_tts_python_edit.setText(fallback)
            self.on_pocket_tts_python_changed()
            print(f"[QtGUI] PocketTTS Python was empty. Using default path: {fallback}")
            return fallback
        return ""

    def reset_pocket_tts_python_to_default(self):
        fallback = str(getattr(engine, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
        pocket_tts_python_edit = getattr(self, "pocket_tts_python_edit", None)
        if fallback and os.path.exists(fallback) and pocket_tts_python_edit is not None:
            pocket_tts_python_edit.setText(fallback)
            self.on_pocket_tts_python_changed()
            print(f"[QtGUI] PocketTTS Python reset to bundled interpreter: {fallback}")
        else:
            print("[QtGUI] Bundled PocketTTS interpreter was not found.")

    def on_input_mode_change(self, choice):
        mode = "push_to_talk" if choice == "Push-to-Talk" else "voice_activation"
        update_runtime_config("input_mode", mode)
        self._refresh_hotkey_labels()
        self._update_push_to_talk_button()
        self.save_session()

    def on_input_role_change(self, choice):
        role = self._input_role_value_from_label(choice)
        update_runtime_config("input_message_role", role)
        self.save_session()

    def _input_role_value_from_label(self, label):
        text = str(label or "").strip().lower()
        if text == "system message":
            return "system"
        if text == "assistant message":
            return "assistant"
        return "user"

    def _input_role_label_from_value(self, value):
        role = str(value or "user").strip().lower()
        if role == "system":
            return "System Message"
        if role == "assistant":
            return "Assistant Message"
        return "User Message"

    def on_stream_mode_change(self, choice):
        enabled = choice == "On"
        update_runtime_config("stream_mode", enabled)
        current_backend = self._current_tts_backend_value()
        if current_backend in {"chatterbox", "pockettts"}:
            desired_backend = "pockettts" if enabled else "chatterbox"
            if current_backend != desired_backend and hasattr(self, "tts_backend_combo"):
                self.tts_backend_combo.setCurrentIndex(max(self.tts_backend_combo.findData(desired_backend), 0))
        self._advisor_context_manual_override = False
        self.emit_tutorial_event("ui_changed", {"field": "stream_mode", "value": choice})
        self.save_session()

    def on_tts_backend_change(self, choice):
        backend = self._current_tts_backend_value()
        update_runtime_config("tts_backend", backend)
        if backend == "pockettts" and hasattr(self, "pocket_tts_python_edit"):
            self._ensure_pocket_tts_python_path()
        try:
            if hasattr(engine, "init_tts"):
                engine.init_tts()
        except Exception as exc:
            print(f"⚠️ [TTS] Failed to reload backend '{backend}': {exc}")
        self._refresh_tts_runtime_card(activate_tab=not bool(getattr(self, "_restoring_preset", False)))
        self._refresh_tts_runtime_summary()
        self._advisor_context_manual_override = False
        self.emit_tutorial_event("ui_changed", {"field": "tts_backend", "value": backend})
        self.update_model_budget_hint()
        self.save_session()

    def on_musetalk_vram_mode_change(self, choice):
        reverse = {label: key for key, label in MUSE_VRAM_MODE_LABELS.items()}
        update_runtime_config("musetalk_vram_mode", reverse.get(choice, "quality"))
        self._advisor_context_manual_override = False
        self.emit_tutorial_event("ui_changed", {"field": "musetalk_vram_mode", "value": choice})
        self.update_model_budget_hint()
        self.save_session()

    def on_musetalk_loop_fade_changed(self, value):
        fade_ms = max(0, int(value or 0))
        update_runtime_config("musetalk_loop_fade_ms", fade_ms)
        self.emit_tutorial_event("ui_changed", {"field": "musetalk_loop_fade_ms", "value": fade_ms})
        self.save_session()

    def on_visual_reply_mode_changed(self, choice):
        mode = self._visual_reply_mode_value_from_label(choice)
        update_runtime_config("visual_reply_mode", mode)
        update_runtime_config("visual_replies_enabled", mode != "off")
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_mode", "value": mode})
        self.save_session()

    def on_visual_reply_provider_changed(self, choice):
        provider = self._visual_reply_provider_value_from_label(choice)
        update_runtime_config("visual_reply_provider", provider)
        current_model = str(self.visual_reply_model_edit.text() if hasattr(self, "visual_reply_model_edit") else "").strip()
        if provider == "xai":
            if not current_model or current_model == "gpt-image-1":
                self.visual_reply_model_edit.setText("grok-imagine-image")
                update_runtime_config("visual_reply_model", "grok-imagine-image")
        else:
            if not current_model or current_model == "grok-imagine-image":
                self.visual_reply_model_edit.setText("gpt-image-1")
                update_runtime_config("visual_reply_model", "gpt-image-1")
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_provider", "value": provider})
        self.save_session()

    def on_visual_reply_size_changed(self, choice):
        size = self._normalize_visual_reply_size(choice)
        if hasattr(self, "visual_reply_size_combo"):
            label = self._visual_reply_size_label_from_value(size)
            if self.visual_reply_size_combo.currentText() != label:
                self.visual_reply_size_combo.setCurrentText(label)
        update_runtime_config("visual_reply_size", size)
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_size", "value": size})
        self.save_session()

    def on_visual_reply_model_changed(self):
        model_name = str(self.visual_reply_model_edit.text() if hasattr(self, "visual_reply_model_edit") else "").strip() or "gpt-image-1"
        if hasattr(self, "visual_reply_model_edit") and self.visual_reply_model_edit.text().strip() != model_name:
            self.visual_reply_model_edit.setText(model_name)
        update_runtime_config("visual_reply_model", model_name)
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_model", "value": model_name})
        self.save_session()

    def on_visual_reply_auto_show_changed(self, checked):
        enabled = bool(checked)
        update_runtime_config("visual_reply_auto_show_dock", enabled)
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_auto_show_dock", "value": enabled})
        self.save_session()

    def on_sensory_feedback_source_changed(self, choice):
        selected = self._parse_sensory_feedback_source_values(choice)
        checkboxes = getattr(self, "_sensory_feedback_source_checkboxes", {}) or {}
        for provider_id, checkbox in checkboxes.items():
            desired = provider_id in set(selected)
            if bool(checkbox.isChecked()) == desired:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(desired)
            checkbox.blockSignals(False)
        config_value = self._sensory_feedback_config_value(selected)
        self._sync_sensory_feedback_source_summary(selected)
        update_runtime_config("sensory_feedback_source", config_value)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_feedback_source", "value": config_value})
        self.save_session()

    def on_sensory_feedback_interval_changed(self, value):
        seconds = max(2.0, float(value or 7.0))
        update_runtime_config("sensory_feedback_interval_seconds", seconds)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_feedback_interval_seconds", "value": seconds})
        self.save_session()

    def on_sensory_pingpong_enabled_changed(self, checked):
        enabled = bool(checked)
        update_runtime_config("sensory_pingpong_enabled", enabled)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_pingpong_enabled", "value": enabled})
        self.save_session()

    def on_sensory_allow_hidden_proactive_changed(self, checked):
        enabled = bool(checked)
        update_runtime_config("sensory_allow_hidden_proactive_speech", enabled)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_allow_hidden_proactive_speech", "value": enabled})
        self.save_session()

    def on_sensory_allow_hidden_visual_changed(self, checked):
        enabled = bool(checked)
        update_runtime_config("sensory_allow_hidden_visual_generation", enabled)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_allow_hidden_visual_generation", "value": enabled})
        self.save_session()

    def on_sensory_pingpong_history_depth_changed(self, value):
        depth = max(0, int(value or 0))
        update_runtime_config("sensory_pingpong_history_depth", depth)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_pingpong_history_depth", "value": depth})
        self.save_session()


    def on_sensory_pingpong_prompt_changed(self):
        prompt_text = self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else ""
        update_runtime_config("sensory_pingpong_prompt", prompt_text or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", ""))

    def reset_sensory_pingpong_prompt_to_default(self):
        default_prompt = str(getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "") or "").strip()
        if not default_prompt or not hasattr(self, "sensory_pingpong_prompt_text"):
            return
        self.sensory_pingpong_prompt_text.setPlainText(default_prompt)
        self.on_sensory_pingpong_prompt_changed()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_pingpong_prompt_reset", "value": "recommended"})
        self.save_session()
    def refresh_musetalk_avatar_pack_list(self, selected_pack_id=None):
        if not hasattr(self, "musetalk_avatar_pack_combo"):
            return
        requested = str(selected_pack_id or self.musetalk_avatar_pack_combo.currentData() or RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or "").strip()
        catalog = list(engine.get_musetalk_avatar_pack_catalog() or [])
        self.musetalk_avatar_pack_combo.blockSignals(True)
        self.musetalk_avatar_pack_combo.clear()
        for item in catalog:
            pack_id = str(item.get("id") or "").strip()
            if not pack_id:
                continue
            display_name = str(item.get("display_name") or pack_id).strip()
            default_avatar_id = str(item.get("default_avatar_id") or "default_avatar").strip()
            source = str(item.get("source") or "manifest").strip()
            label = f"{display_name} | {default_avatar_id} [{source}]"
            self.musetalk_avatar_pack_combo.addItem(label, pack_id)
        if self.musetalk_avatar_pack_combo.count() <= 0:
            self.musetalk_avatar_pack_combo.addItem("No avatar packs found", "")
        target_index = -1
        for index in range(self.musetalk_avatar_pack_combo.count()):
            if str(self.musetalk_avatar_pack_combo.itemData(index) or "") == requested:
                target_index = index
                break
        self.musetalk_avatar_pack_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.musetalk_avatar_pack_combo.blockSignals(False)

    def on_musetalk_avatar_pack_change(self, _choice):
        pack_id = str(self.musetalk_avatar_pack_combo.currentData() or "").strip()
        if not pack_id:
            return
        selected_pack_id = engine.apply_musetalk_avatar_pack_selection(pack_id)
        update_runtime_config("musetalk_avatar_pack_id", selected_pack_id)
        self.emit_tutorial_event("ui_changed", {"field": "musetalk_avatar_pack_id", "value": selected_pack_id})
        self.save_session()

    def on_allow_proactive_replies_changed(self, checked):
        update_runtime_config("allow_proactive_replies", bool(checked))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_require_first_user_before_proactive_changed(self, checked):
        update_runtime_config("require_first_user_before_proactive", bool(checked))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_listen_idle_window_changed(self, value):
        update_runtime_config("listen_idle_window_seconds", round(float(value), 1))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_proactive_delay_changed(self, value):
        update_runtime_config("proactive_delay_seconds", round(float(value), 1))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_chat_context_window_changed(self, value):
        update_runtime_config("chat_context_window_messages", max(4, int(value)))
        self._refresh_chat_session_hint()
        self._update_chat_status(self._console_redirect.chat_line_count, int(self.chat_auto_scroll))
        self.save_session()

    def on_stored_chat_history_limit_changed(self, value):
        update_runtime_config("stored_chat_history_limit", max(0, int(value)))
        self._refresh_chat_session_hint()
        self._update_chat_status(self._console_redirect.chat_line_count, int(self.chat_auto_scroll))
        self.save_session()

    def on_chat_overflow_policy_changed(self, choice):
        update_runtime_config("chat_context_overflow_policy", self._chat_overflow_policy_value_from_label(choice))
        self._refresh_chat_session_hint()
        self.save_session()

    def on_chat_provider_changed(self, _choice):
        provider_value = self._current_chat_provider_value()
        update_runtime_config("chat_provider", provider_value)
        self._refresh_chat_provider_card()
        self._refresh_chat_runtime_summary()
        self.request_model_list_refresh(quiet=True, wait_for_reachable=False)
        self.update_model_budget_hint()
        self.save_session()

    def on_chat_font_size_changed(self, _index):
        if not hasattr(self, "chat_font_size_combo"):
            return
        size = self.chat_font_size_combo.currentData()
        if size is None:
            return
        self._apply_chat_font_size(size, update_combo=False)
        self.save_session()

    def on_model_selection_changed(self, choice):
        update_runtime_config("model_name", str(choice or "").strip())
        self._advisor_context_manual_override = False
        self.update_model_budget_hint()
        self._refresh_chat_runtime_summary()
        self.save_session()

    def on_model_context_input_changed(self, _value):
        if not self._advisor_context_updating:
            self._advisor_context_manual_override = True
        self.update_model_budget_hint()

    def _update_push_to_talk_button(self):
        enabled = (
            bool(self.thread and self.thread.is_alive())
            and self.input_mode_combo.currentText() == "Push-to-Talk"
            and not self._dry_run_is_active()
        )
        if hasattr(self, "btn_push_to_talk"):
            self.btn_push_to_talk.setEnabled(enabled)

    def _dry_run_is_active(self):
        status = dry_run.get_status()
        return bool(status and status.get("active"))

    def _update_restart_sensitive_controls(self):
        running = bool(self.thread and self.thread.is_alive())
        controls = [
            getattr(self, "engine_combo", None),
            getattr(self, "model_combo", None),
            getattr(self, "tts_backend_combo", None),
            getattr(self, "musetalk_vram_combo", None),
            getattr(self, "pocket_tts_python_edit", None),
            getattr(self, "pocket_tts_browse_button", None),
        ]
        for control in controls:
            if control is not None:
                control.setEnabled(not running)

    def _engine_is_offline_replay_only(self):
        return bool(self.thread and self.thread.is_alive() and RUNTIME_CONFIG.get("offline_replay_only", False))

    def _update_control_action_buttons(self):
        running = bool(self.thread and self.thread.is_alive())
        dry_run_active = self._dry_run_is_active()
        offline_replay_only = self._engine_is_offline_replay_only()
        enabled = running and not dry_run_active and not offline_replay_only
        replay_runtime_enabled = running and not dry_run_active and offline_replay_only
        for name in ["btn_regenerate", "btn_retry", "btn_skip_user"]:
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(enabled)
        for name in ["btn_pause", "btn_skip"]:
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled((running and not dry_run_active and not offline_replay_only) or replay_runtime_enabled)

    def _hotkey_button_titles(self):
        return {
            "regenerate_response": "Regenerate",
            "retry_user_input": "Retry Input",
            "pause_speech": "Pause / Resume",
            "skip_speech": "Skip Speech",
            "skip_user_reply": "Skip User Reply",
        }

    def _supported_ui_hotkey_actions(self):
        return OrderedDict(
            [
                ("start_engine", lambda: self.start_engine()),
                ("stop_engine", lambda: self.stop_engine()),
                ("reset_chat_session", lambda: self.reset_chat_session()),
                ("clear_console", lambda: self.clear_console()),
                ("clear_chat", lambda: self.clear_chat()),
                ("show_musetalk_preview", lambda: self.show_musetalk_preview()),
                ("toggle_musetalk_avatar_focus", lambda: self.toggle_musetalk_avatar_focus()),
                ("show_visual_reply", lambda: self.show_visual_reply_dock()),
                ("start_vam_desktop", lambda: self.on_start_vam_desktop_clicked()),
                ("start_vam_vr", lambda: self.on_start_vam_vr_clicked()),
            ]
        )

    def _dispatch_hotkey_action(self, action):
        action_key = str(action or "").strip()
        if action_key in engine.DEFAULT_MANUAL_ACTION_HOTKEYS:
            self.trigger_control_action(action_key)
            return
        handler = self._supported_ui_hotkey_actions().get(action_key)
        if callable(handler):
            handler()

    def _refresh_hotkey_shortcuts(self):
        shortcuts = getattr(self, "_qt_hotkey_shortcuts", None)
        if shortcuts is None:
            self._qt_hotkey_shortcuts = {}
            return
        for shortcut in shortcuts.values():
            try:
                shortcut.setEnabled(False)
                shortcut.setKey(QtGui.QKeySequence())
            except Exception:
                pass

    def _poll_exact_ui_hotkeys(self):
        if not self.isVisible() or not self.isActiveWindow():
            return
        if self._closing:
            return
        actions = self._supported_ui_hotkey_actions()
        bindings = engine.get_ui_action_hotkeys()
        now = time.time()
        debounce_seconds = 0.35
        for action, handler in actions.items():
            binding = str(bindings.get(action, "") or "").strip()
            if not binding:
                continue
            if not engine.is_hotkey_binding_pressed(binding):
                continue
            last_triggered = float(self._ui_hotkey_last_triggered_at.get(action, 0.0) or 0.0)
            if now - last_triggered < debounce_seconds:
                continue
            self._ui_hotkey_last_triggered_at[action] = now
            if callable(handler):
                handler()

    def _refresh_hotkey_labels(self):
        if hasattr(self, "input_mode_hint"):
            mode = "push_to_talk" if self.input_mode_combo.currentText() == "Push-to-Talk" else "voice_activation"
            if mode == "push_to_talk":
                binding = engine.get_push_to_talk_hotkey()
                self.input_mode_hint.setText(f"Push-to-Talk hotkey: {binding} (fallback button below)")
            else:
                self.input_mode_hint.setText("Voice activation listens for speech automatically")
        button_titles = self._hotkey_button_titles()
        button_map = getattr(self, "_control_action_buttons", {}) or {}
        configured = engine.get_manual_action_hotkeys()
        for action, button in button_map.items():
            title = str(button_titles.get(action, engine.HOTKEY_ACTION_LABELS.get(action, action)) or action)
            binding = str(configured.get(action, "") or "").strip()
            button.setText(f"{title}\n{binding}" if binding else title)

    def hotkey_catalog(self):
        entries = [
            {
                "action": "push_to_talk",
                "label": str(engine.HOTKEY_ACTION_LABELS.get("push_to_talk", "Push-to-Talk")),
                "binding": engine.get_push_to_talk_hotkey(),
                "default_binding": str(engine.DEFAULT_PUSH_TO_TALK_HOTKEY),
                "category": "input",
                "scope": "global",
                "description": "Hold this key to talk while input mode is Push-to-Talk.",
            }
        ]
        manual_bindings = engine.get_manual_action_hotkeys()
        for action, default_binding in engine.DEFAULT_MANUAL_ACTION_HOTKEYS.items():
            entries.append(
                {
                    "action": action,
                    "label": str(engine.HOTKEY_ACTION_LABELS.get(action, action)),
                    "binding": str(manual_bindings.get(action, "") or ""),
                    "default_binding": str(default_binding or ""),
                    "category": "manual_controls",
                    "scope": "global_and_window",
                    "description": "Manual runtime control handled by the core hotkey spine.",
                }
            )
        ui_bindings = engine.get_ui_action_hotkeys()
        for action, default_binding in engine.DEFAULT_UI_ACTION_HOTKEYS.items():
            entries.append(
                {
                    "action": action,
                    "label": str(engine.HOTKEY_ACTION_LABELS.get(action, action)),
                    "binding": str(ui_bindings.get(action, "") or ""),
                    "default_binding": str(default_binding or ""),
                    "category": "ui_actions",
                    "scope": "window",
                    "description": "Qt window shortcut active while NC is focused.",
                }
            )
        return entries

    def set_hotkey_binding(self, action, binding):
        action_key = str(action or "").strip()
        binding_text = engine.normalize_hotkey_text(binding)
        if action_key == "push_to_talk":
            value = engine.set_push_to_talk_hotkey(binding_text or engine.DEFAULT_PUSH_TO_TALK_HOTKEY)
        elif action_key in engine.DEFAULT_MANUAL_ACTION_HOTKEYS:
            value = engine.set_manual_action_hotkey(action_key, binding_text)
        elif action_key in engine.DEFAULT_UI_ACTION_HOTKEYS:
            value = engine.set_ui_action_hotkey(action_key, binding_text)
        else:
            raise KeyError(f"Unknown hotkey action: {action_key}")
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()
        self.save_session()
        return value

    def reset_hotkey_bindings(self):
        bindings = engine.reset_hotkeys_to_defaults()
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()
        self.save_session()
        return bindings

    def update_pose_value(self, key, value):
        value = round(float(value), 2)
        target = engine.EDIT_EMOTION if engine.FORCE_EDIT_MODE else "neutral"
        if target in engine.AVATAR_PROFILE:
            engine.AVATAR_PROFILE[target][key] = value
        engine.CURRENT_BODY_STATE[key] = value

    def update_brain_value(self, key, value, is_int):
        update_runtime_config(key, int(value) if is_int else round(float(value), 2))

    def on_limit_response_length_changed(self, checked):
        checked = bool(checked)
        update_runtime_config("limit_response_length", checked)
        if hasattr(self, "max_response_tokens_spin"):
            self.max_response_tokens_spin.setEnabled(checked)
        self.save_session()

    def on_max_response_tokens_changed(self, value):
        update_runtime_config("max_response_tokens", int(value))
        self.save_session()

    def update_chunking_value(self, key, value, is_int):
        update_runtime_config(key, int(value) if is_int else round(float(value), 2))
        self.save_session()

    def reset_chunking_defaults(self):
        for key, value in DEFAULT_CHUNKING_VALUES.items():
            if key in self.chunking_sliders:
                self.chunking_sliders[key].set_value(value)
            update_runtime_config(key, value)
        self.save_session()
        print("[QtGUI] Chunking settings reset to defaults.")

    def start_dry_run_session(self):
        self._publish_addon_event("runtime.heavy_task_starting", {"source": "dry_run"})
        status = dry_run.start_session(
            RUNTIME_CONFIG,
            target_samples=self.dry_run_target_spin.value(),
            label=f"{self.engine_combo.currentText()} / {self.tts_backend_combo.currentText()} / {'Stream' if self.stream_mode_combo.currentText() == 'On' else 'Non-stream'}",
            auto_replies=self.dry_run_auto_replies_checkbox.isChecked(),
        )
        update_runtime_config("limit_response_length", True)
        update_runtime_config("max_response_tokens", DRY_RUN_MAX_RESPONSE_TOKENS)
        dry_run.log_event(
            "[DryRun] Brain snapshot "
            f"preset={self.preset_combo.currentText()} "
            f"model={self.model_combo.currentText()} "
            f"temperature={self.brain_sliders['temperature'].value()} "
            f"top_p={self.brain_sliders['top_p'].value()} "
            f"top_k={int(self.brain_sliders['top_k'].value())} "
            f"repeat_penalty={self.brain_sliders['repeat_penalty'].value()} "
            f"min_p={self.brain_sliders['min_p'].value()} "
            f"user_limit_response_length={self.limit_response_checkbox.isChecked()} "
            f"user_max_response_tokens={int(self.max_response_tokens_spin.value())} "
            f"dry_run_limit_response_length=True "
            f"dry_run_max_response_tokens={DRY_RUN_MAX_RESPONSE_TOKENS} "
            f"system_prompt={self.system_prompt_text.toPlainText().strip()[:220]!r} "
            f"emotional_instructions={self.emotional_text.toPlainText().strip()[:220]!r}"
        )
        shared_state.append_musetalk_preview_log(
            f"🧪 [DryRun] Session armed: id={status.get('session_id')} profile={status.get('profile_key')} target_samples={status.get('target_samples')} max_tokens={DRY_RUN_MAX_RESPONSE_TOKENS}"
        )
        if bool(status.get("auto_mode")):
            print("[QtGUI] Dry Run armed in auto mode.")
        else:
            print(f"[QtGUI] Dry Run armed for {status.get('target_samples')} reply sample(s).")
        self.emit_tutorial_event("dry_run_started", {"session_id": status.get("session_id"), "auto_mode": bool(status.get("auto_mode"))})
        self._apply_dry_run_candidate_settings()
        self.refresh_dry_run_status()

    def stop_dry_run_session(self):
        status = dry_run.stop_session(reason="manual_stop")
        if status:
            self.dry_run_last_applied_candidate_index = None
            self._apply_runtime_settings_dict(status.get("config_snapshot", {}) or {})
            self.save_session()
            shared_state.append_musetalk_preview_log(
                f"🧪 [DryRun] Session stopped: id={status.get('session_id')} confidence={status.get('confidence')}"
            )
            print("[QtGUI] Dry Run stopped.")
            self.emit_tutorial_event("dry_run_stopped", {"session_id": status.get("session_id"), "confidence": status.get("confidence")})
        self.refresh_dry_run_status()

    def apply_dry_run_recommendation(self):
        if not self.dry_run_recommended_settings:
            print("[QtGUI] Dry Run has no recommendation to apply yet.")
            return
        settings = dict(self.dry_run_recommended_settings)
        self._apply_runtime_settings_dict(settings)
        self.save_session()
        print("[QtGUI] Dry Run recommendation applied.")
        self.refresh_dry_run_status()

    def refresh_performance_profile_list(self):
        combos = []
        if hasattr(self, "performance_profile_combo"):
            combos.append(self.performance_profile_combo)
        if hasattr(self, "chunking_profile_combo"):
            combos.append(self.chunking_profile_combo)
        if not combos:
            return
        profiles = dry_run.list_performance_profiles()
        preferred_name = ""
        for combo in combos:
            data = combo.currentData()
            if data:
                preferred_name = str(data)
                break
        for combo in combos:
            combo.blockSignals(True)
            combo.clear()
            if not profiles:
                combo.addItem("No Saved Profiles")
            else:
                for item in profiles:
                    name = str(item.get("display_name") or item["name"])
                    prefix = "Recommended: " if item.get("recommended") else ("Starter: " if item.get("bundled") else "")
                    label = (
                        f"{prefix}{name} | "
                        f"{'Stream' if item.get('stream_mode') else 'Non-stream'} | "
                        f"{str(item.get('tts_backend') or '').title()} | "
                        f"{str(item.get('musetalk_vram_mode') or '').replace('_', ' ').title()} | "
                        f"c={float(item.get('confidence', 0.0) or 0.0):.2f}"
                    )
                    combo.addItem(label, item["name"])
                target_index = 0
                if preferred_name:
                    for index in range(combo.count()):
                        if combo.itemData(index) == preferred_name:
                            target_index = index
                            break
                combo.setCurrentIndex(target_index)
            combo.blockSignals(False)
        has_profiles = bool(profiles)
        if hasattr(self, "btn_profile_load"):
            self.btn_profile_load.setEnabled(has_profiles)
        if hasattr(self, "btn_profile_delete"):
            self.btn_profile_delete.setEnabled(has_profiles)
        if hasattr(self, "btn_chunking_profile_load"):
            self.btn_chunking_profile_load.setEnabled(has_profiles)
        if hasattr(self, "btn_chunking_profile_delete"):
            self.btn_chunking_profile_delete.setEnabled(has_profiles)

    def _get_selected_performance_profile_name(self, source="dry_run"):
        if source == "chunking":
            combo = getattr(self, "chunking_profile_combo", None)
        else:
            combo = getattr(self, "performance_profile_combo", None)
        if combo is None:
            return ""
        return str(combo.currentData() or "").strip()

    def _build_current_performance_override(self, include_chunking=True):
        override = {
            "avatar_mode": self.engine_combo.currentText().lower(),
            "stream_mode": self.stream_mode_combo.currentText() == "On",
            "tts_backend": self._current_tts_backend_value(),
            "musetalk_avatar_pack_id": str(self.musetalk_avatar_pack_combo.currentData() or RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or ""),
            "musetalk_vram_mode": next(
                (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self.musetalk_vram_combo.currentText()),
                "quality",
            ),
            "model_name": self.model_combo.currentText(),
            "temperature": self.brain_sliders["temperature"].value(),
            "top_p": self.brain_sliders["top_p"].value(),
            "top_k": int(self.brain_sliders["top_k"].value()),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value(),
            "min_p": self.brain_sliders["min_p"].value(),
            "limit_response_length": self.limit_response_checkbox.isChecked(),
            "max_response_tokens": int(self.max_response_tokens_spin.value()),
        }
        if include_chunking:
            override.update({key: slider.value() for key, slider in self.chunking_sliders.items()})
        return override

    def save_latest_performance_profile(self):
        latest = dry_run.get_latest_profile()
        if not latest:
            print("[QtGUI] No completed Dry Run profile is available to save.")
            return
        suggested = dry_run.suggest_profile_name(latest)
        name = QtInputDialog.get_text("Save Performance Profile", "Enter Profile Name:", self) or suggested
        name = str(name or "").strip()
        if not name:
            print("[QtGUI] Performance profile save cancelled.")
            return
        current_override = self._build_current_performance_override(include_chunking=False)
        dry_run.save_named_performance_profile(name, latest, settings_override=current_override)
        print(f"[QtGUI] Saved performance profile: {name}")
        self.refresh_performance_profile_list()

    def load_selected_performance_profile(self):
        name = self._get_selected_performance_profile_name("dry_run")
        if not name:
            print("[QtGUI] No performance profile selected.")
            return
        self.load_performance_profile_by_id(name)

    def delete_selected_performance_profile(self):
        name = self._get_selected_performance_profile_name("dry_run")
        if not name:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Performance Profile", f"Delete '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        if dry_run.delete_performance_profile(name):
            print(f"[QtGUI] Deleted performance profile: {name}")
        self.refresh_performance_profile_list()

    def save_current_chunking_profile(self):
        source_name = self._get_selected_performance_profile_name("chunking")
        source_profile = dry_run.load_performance_profile(source_name) if source_name else dry_run.get_latest_profile()
        suggested = dry_run.suggest_profile_name(source_profile or {"profile_key": "manual_chunking", "config_snapshot": self._build_current_performance_override(include_chunking=True)})
        name = QtInputDialog.get_text("Save Chunking Profile", "Enter Profile Name:", self) or suggested
        name = str(name or "").strip()
        if not name:
            print("[QtGUI] Chunking profile save cancelled.")
            return
        if not source_profile:
            source_profile = {
                "profile_key": "manual_chunking",
                "hardware": {},
                "updated_at": time.time(),
                "sample_count": 0,
                "confidence": 0.0,
                "stability": 0.0,
                "completion_reason": "manual_save",
                "config_snapshot": self._build_current_performance_override(include_chunking=True),
                "recommendation": {},
                "summary": {},
            }
        current_override = self._build_current_performance_override(include_chunking=True)
        dry_run.save_named_performance_profile(name, source_profile=source_profile, settings_override=current_override)
        print(f"[QtGUI] Saved chunking profile: {name}")
        self.refresh_performance_profile_list()

    def load_selected_chunking_profile(self):
        name = self._get_selected_performance_profile_name("chunking")
        if not name:
            print("[QtGUI] No performance profile selected.")
            return
        self.load_performance_profile_by_id(name)

    def delete_selected_chunking_profile(self):
        name = self._get_selected_performance_profile_name("chunking")
        if not name:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Performance Profile", f"Delete '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        if dry_run.delete_performance_profile(name):
            print(f"[QtGUI] Deleted performance profile: {name}")
        self.refresh_performance_profile_list()

    def _apply_runtime_settings_dict(self, settings):
        for key, value in settings.items():
            update_runtime_config(key, value)
            if key in self.chunking_sliders:
                self.chunking_sliders[key].set_value(value)
        if "tts_backend" in settings and hasattr(self, "tts_backend_combo"):
            desired_backend = str(settings["tts_backend"] or "").strip().lower()
            self._populate_tts_backend_combo(selected_value=desired_backend)
            index = self.tts_backend_combo.findData(desired_backend)
            if index >= 0:
                self.tts_backend_combo.setCurrentIndex(index)
            self.on_tts_backend_change(self.tts_backend_combo.currentText())
        if "stream_mode" in settings:
            self.stream_mode_combo.setCurrentText("On" if bool(settings["stream_mode"]) else "Off")
        if "musetalk_vram_mode" in settings and hasattr(self, "musetalk_vram_combo"):
            self.musetalk_vram_combo.setCurrentText(MUSE_VRAM_MODE_LABELS.get(str(settings["musetalk_vram_mode"]).lower(), "Quality"))
        if "musetalk_loop_fade_ms" in settings and hasattr(self, "musetalk_loop_fade_spin"):
            fade_ms = max(0, int(settings["musetalk_loop_fade_ms"] or 0))
            self.musetalk_loop_fade_spin.setValue(fade_ms)
            self.on_musetalk_loop_fade_changed(fade_ms)
        if "visual_reply_mode" in settings and hasattr(self, "visual_reply_mode_combo"):
            mode_text = self._visual_reply_mode_label_from_value(settings["visual_reply_mode"])
            self.visual_reply_mode_combo.setCurrentText(mode_text)
            self.on_visual_reply_mode_changed(mode_text)
        if "visual_reply_provider" in settings and hasattr(self, "visual_reply_provider_combo"):
            provider_text = self._visual_reply_provider_label_from_value(settings["visual_reply_provider"])
            self.visual_reply_provider_combo.setCurrentText(provider_text)
            self.on_visual_reply_provider_changed(provider_text)
        if "visual_reply_size" in settings and hasattr(self, "visual_reply_size_combo"):
            size_text = self._normalize_visual_reply_size(settings["visual_reply_size"])
            self.visual_reply_size_combo.setCurrentText(self._visual_reply_size_label_from_value(size_text))
            self.on_visual_reply_size_changed(size_text)
        if "visual_reply_model" in settings and hasattr(self, "visual_reply_model_edit"):
            self.visual_reply_model_edit.setText(str(settings["visual_reply_model"] or "gpt-image-1"))
            self.on_visual_reply_model_changed()
        if "visual_reply_auto_show_dock" in settings and hasattr(self, "visual_reply_auto_show_checkbox"):
            auto_show = bool(settings["visual_reply_auto_show_dock"])
            self.visual_reply_auto_show_checkbox.setChecked(auto_show)
            self.on_visual_reply_auto_show_changed(auto_show)
        if "sensory_feedback_source" in settings and hasattr(self, "sensory_feedback_source_combo"):
            source_value = str(settings["sensory_feedback_source"] or "off")
            self.refresh_sensory_feedback_source_options(selected_value=source_value)
            self.on_sensory_feedback_source_changed(source_value)
        if "sensory_feedback_interval_seconds" in settings and hasattr(self, "sensory_feedback_interval_spin"):
            interval_seconds = max(2.0, float(settings["sensory_feedback_interval_seconds"] or 7.0))
            self.sensory_feedback_interval_spin.setValue(interval_seconds)
            self.on_sensory_feedback_interval_changed(interval_seconds)
    def _apply_saved_model_name(self, model_name):
        wanted = str(model_name or "").strip()
        if not wanted or not hasattr(self, "model_combo"):
            return False
        index = self.model_combo.findText(wanted)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
            return True
        current = self.model_combo.currentText().strip() if self.model_combo.currentText() else "<none>"
        print(f"[QtGUI] Saved model not available: {wanted}. Keeping current model: {current}")
        return False

    def _apply_dry_run_candidate_settings(self):
        candidate = dry_run.get_current_candidate_settings()
        if not candidate:
            return
        candidate_index = candidate.get("index")
        if candidate_index == self.dry_run_last_applied_candidate_index:
            return
        settings = candidate.get("settings") or {}
        self._apply_runtime_settings_dict(settings)
        self.dry_run_last_applied_candidate_index = candidate_index
        self.save_session()
        dry_run.log_event(
            "[DryRun] Applying candidate "
            f"label={candidate.get('label')} "
            f"stream_target={settings.get('stream_chunk_target_chars')} "
            f"stream_max={settings.get('stream_chunk_max_chars')} "
            f"first_min={settings.get('stream_first_chunk_min_chars')} "
            f"flush={settings.get('stream_force_flush_seconds')}/{settings.get('stream_force_flush_later_seconds')} "
            f"muse_target={settings.get('musetalk_chunk_target_chars')} "
            f"muse_max={settings.get('musetalk_chunk_max_chars')} "
            f"qs1={settings.get('musetalk_quickstart_1_target_chars')}/{settings.get('musetalk_quickstart_1_max_chars')} "
            f"qs2={settings.get('musetalk_quickstart_2_target_chars')}/{settings.get('musetalk_quickstart_2_max_chars')}"
        )
        shared_state.append_musetalk_preview_log(
            f"🧪 [DryRun] Applying {candidate.get('label')}: "
            f"stream_target={settings.get('stream_chunk_target_chars')} "
            f"stream_max={settings.get('stream_chunk_max_chars')} "
            f"first_min={settings.get('stream_first_chunk_min_chars')} "
            f"flush={settings.get('stream_force_flush_seconds')}/{settings.get('stream_force_flush_later_seconds')} "
            f"muse_target={settings.get('musetalk_chunk_target_chars')} "
            f"muse_max={settings.get('musetalk_chunk_max_chars')} "
            f"qs1={settings.get('musetalk_quickstart_1_target_chars')}/{settings.get('musetalk_quickstart_1_max_chars')} "
            f"qs2={settings.get('musetalk_quickstart_2_target_chars')}/{settings.get('musetalk_quickstart_2_max_chars')}"
        )

    def refresh_dry_run_status(self):
        if not hasattr(self, "dry_run_status_label"):
            return
        status = dry_run.get_status()
        self.dry_run_recommended_settings = {}
        if not status:
            self.dry_run_last_applied_candidate_index = None
            latest = dry_run.get_latest_profile()
            self.btn_dry_run_start.setEnabled(True)
            self.btn_dry_run_stop.setEnabled(False)
            self.btn_dry_run_apply.setEnabled(bool(latest and (latest.get("recommendation") or {}).get("settings")))
            self._update_control_action_buttons()
            if latest:
                recommendation = latest.get("recommendation", {}) or {}
                self.dry_run_recommended_settings = dict(recommendation.get("settings") or {})
                summary = latest.get("summary", {}) or {}
                self.dry_run_status_label.setText(
                    f"Dry Run idle. Last profile confidence {float(latest.get('confidence', 0.0) or 0.0):.2f}, stability {float(latest.get('stability', 0.0) or 0.0):.2f}."
                )
                self._update_readonly_text_safely(
                    self.dry_run_summary,
                    self._format_dry_run_summary(summary, recommendation, latest.get("completion_reason", ""), latest.get("stability"))
                )
            else:
                self.dry_run_status_label.setText("Dry Run idle.")
                self._update_readonly_text_safely(
                    self.dry_run_summary,
                    "Arm a Dry Run to collect reply samples and generate machine-specific recommendations.",
                )
            return

        recommendation = status.get("recommendation", {}) or {}
        self.dry_run_recommended_settings = dict(recommendation.get("settings") or {})
        observations = status.get("observations", []) or []
        sample_count = len(observations)
        target = int(status.get("target_samples", self.dry_run_target_spin.value()) or self.dry_run_target_spin.value())
        auto_mode = bool(status.get("auto_mode"))
        auto_replies = bool(status.get("auto_replies"))
        confidence = float(status.get("confidence", 0.0) or 0.0)
        stability = float(status.get("stability", 0.0) or 0.0)
        candidate_plan = status.get("candidate_plan", []) or []
        active_candidate_index = int(status.get("active_candidate_index", 0) or 0)
        candidate_label = ""
        if candidate_plan:
            candidate_index = max(0, min(active_candidate_index, len(candidate_plan) - 1))
            candidate_label = str((candidate_plan[candidate_index] or {}).get("label") or f"Candidate {candidate_index + 1}")
        state_text = "complete" if status.get("complete") else ("running" if status.get("active") else "idle")
        sample_text = f"{sample_count} samples" if auto_mode else f"{sample_count}/{target} samples"
        self.dry_run_status_label.setText(
            f"Dry Run {state_text}: {sample_text}, confidence {confidence:.2f}, stability {stability:.2f}"
            + (f" ({candidate_label})" if candidate_label and not status.get("complete") else "")
            + (" | hands-free" if auto_replies else "")
        )
        self.btn_dry_run_start.setEnabled(not status.get("active"))
        self.btn_dry_run_stop.setEnabled(bool(status.get("active")))
        self.btn_dry_run_apply.setEnabled(bool(self.dry_run_recommended_settings))
        self._update_control_action_buttons()
        self._update_readonly_text_safely(
            self.dry_run_summary,
            self._format_dry_run_summary(
                dry_run.summarize_observations(observations),
                recommendation,
                status.get("completion_reason", ""),
                stability,
            )
        )
        if status.get("active") and not status.get("complete"):
            self._apply_dry_run_candidate_settings()
        elif status.get("complete") and status.get("active"):
            final_status = dry_run.stop_session(reason="complete")
            if final_status:
                self.dry_run_last_applied_candidate_index = None
                self._apply_runtime_settings_dict(final_status.get("config_snapshot", {}) or {})
                self.save_session()
                self.emit_tutorial_event(
                    "dry_run_completed",
                    {
                        "session_id": final_status.get("session_id"),
                        "confidence": final_status.get("confidence"),
                        "stability": final_status.get("stability"),
                        "reason": final_status.get("completion_reason", ""),
                    },
                )
                if self.thread and self.thread.is_alive():
                    print("[QtGUI] Dry Run complete. Terminating active session...")
                    self.stop_engine()
            self.refresh_dry_run_status()

    def _format_dry_run_summary(self, summary, recommendation, completion_reason="", stability=None):
        summary = summary or {}
        recommendation = recommendation or {}
        settings = recommendation.get("settings", {}) or {}
        lines = [
            "Measured startup profile:",
            f"- Avg first audio chunk: {self._fmt_ms(summary.get('avg_first_audio_chunk_ms'))}",
            f"- Avg first visual buffer wait: {self._fmt_ms(summary.get('avg_buffer_wait_ms'))}",
            f"- Avg first chunk audio start: {self._fmt_ms(summary.get('avg_audio_start_ms'))}",
            f"- Avg first chunk render ready: {self._fmt_ms(summary.get('avg_render_ready_ms'))}",
            f"- Avg first chunk ms/frame: {self._fmt_ms(summary.get('avg_spf_ms'))}",
            f"- Avg plan sync wait: {self._fmt_ms(summary.get('avg_plan_sync_ms'))}",
            f"- Avg idle sync wait: {self._fmt_ms(summary.get('avg_idle_sync_ms'))}",
            f"- Avg chunk quality: {self._fmt_ratio(summary.get('avg_chunk_quality'))}",
            f"- Avg emitted chunk chars: {self._fmt_num(summary.get('avg_chunk_chars'))}",
        ]
        if stability is not None:
            lines.append(f"- Stability: {float(stability):.2f}")
        lines.extend([
            "",
            "Recommended settings:",
        ])
        for key in [
            "tts_backend",
            "stream_chunk_target_chars",
            "stream_chunk_max_chars",
            "stream_first_chunk_min_chars",
            "stream_force_flush_seconds",
            "stream_force_flush_later_seconds",
            "musetalk_chunk_target_chars",
            "musetalk_chunk_max_chars",
            "musetalk_quickstart_1_target_chars",
            "musetalk_quickstart_1_max_chars",
            "musetalk_quickstart_2_target_chars",
            "musetalk_quickstart_2_max_chars",
        ]:
            if key in settings:
                lines.append(f"- {key}: {settings[key]}")
        notes = recommendation.get("notes", []) or []
        if notes:
            lines.append("")
            lines.append("Notes:")
            for note in notes:
                lines.append(f"- {note}")
        if completion_reason:
            lines.append(f"- Completion reason: {completion_reason}")
        return "\n".join(lines)

    def _fmt_ms(self, value):
        if value is None:
            return "n/a"
        return f"{float(value):.1f} ms"

    def _fmt_ratio(self, value):
        if value is None:
            return "n/a"
        return f"{float(value):.2f}"

    def _fmt_num(self, value):
        if value is None:
            return "n/a"
        return f"{float(value):.1f}"

    def apply_text_config(self):
        avatar_mode = self.engine_combo.currentText().lower() if hasattr(self, "engine_combo") else str(RUNTIME_CONFIG.get("avatar_mode", "vseeface") or "vseeface").strip().lower()
        mode = "push_to_talk" if self.input_mode_combo.currentText() == "Push-to-Talk" else "voice_activation"
        role = self._input_role_value_from_label(self.input_role_combo.currentText())
        stream_mode = self.stream_mode_combo.currentText() == "On"
        tts_backend = self._current_tts_backend_value()
        musetalk_vram_mode = next(
            (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self.musetalk_vram_combo.currentText()),
            "quality",
        )
        update_runtime_config("input_mode", mode)
        update_runtime_config("input_message_role", role)
        update_runtime_config("stream_mode", stream_mode)
        update_runtime_config("tts_backend", tts_backend)
        update_runtime_config("musetalk_vram_mode", musetalk_vram_mode)
        update_runtime_config("musetalk_avatar_pack_id", str(self.musetalk_avatar_pack_combo.currentData() or RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or ""))
        update_runtime_config("allow_proactive_replies", self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else True)
        update_runtime_config("require_first_user_before_proactive", self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False)
        update_runtime_config("listen_idle_window_seconds", round(float(self.listen_idle_window_spin.value()), 1) if hasattr(self, "listen_idle_window_spin") else 5.0)
        update_runtime_config("proactive_delay_seconds", round(float(self.proactive_delay_spin.value()), 1) if hasattr(self, "proactive_delay_spin") else 10.0)
        update_runtime_config("chat_context_window_messages", max(4, int(self.chat_context_window_spin.value())) if hasattr(self, "chat_context_window_spin") else 20)
        update_runtime_config("stored_chat_history_limit", max(0, int(self.stored_chat_history_limit_spin.value())) if hasattr(self, "stored_chat_history_limit_spin") else 0)
        update_runtime_config("chat_context_overflow_policy", self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window")
        pocket_tts_python_edit = getattr(self, "pocket_tts_python_edit", None)
        update_runtime_config(
            "pocket_tts_python",
            pocket_tts_python_edit.text().strip() if pocket_tts_python_edit is not None else str(RUNTIME_CONFIG.get("pocket_tts_python", "") or ""),
        )
        update_runtime_config("vam_vmc_enabled", self.vam_vmc_enabled_checkbox.isChecked() if hasattr(self, "vam_vmc_enabled_checkbox") else True)
        update_runtime_config("vam_bridge_enabled", self.vam_bridge_enabled_checkbox.isChecked() if hasattr(self, "vam_bridge_enabled_checkbox") else True)
        update_runtime_config("vam_play_audio_in_vam", True if avatar_mode == "vam" else (self.vam_play_audio_in_vam_checkbox.isChecked() if hasattr(self, "vam_play_audio_in_vam_checkbox") else False))
        update_runtime_config("vam_timeline_auto_resume", self.vam_timeline_auto_resume_checkbox.isChecked() if hasattr(self, "vam_timeline_auto_resume_checkbox") else True)
        update_runtime_config("vam_vmc_host", self.vam_vmc_host_edit.text().strip() if hasattr(self, "vam_vmc_host_edit") else str(RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1"))
        update_runtime_config("vam_vmc_port", int(self.vam_vmc_port_spin.value()) if hasattr(self, "vam_vmc_port_spin") else int(RUNTIME_CONFIG.get("vam_vmc_port", 39539) or 39539))
        update_runtime_config("vam_root", self._current_vam_root_value() if hasattr(self, "vam_root_edit") else str(RUNTIME_CONFIG.get("vam_root", getattr(engine, "DEFAULT_VAM_ROOT", "")) or getattr(engine, "DEFAULT_VAM_ROOT", "")))
        update_runtime_config("vam_bridge_root", self._current_vam_bridge_root_value() if hasattr(self, "vam_bridge_root_edit") else str(RUNTIME_CONFIG.get("vam_bridge_root", getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")) or getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")))
        update_runtime_config("vam_target_atom_uid", self.vam_target_atom_uid_edit.text().strip() if hasattr(self, "vam_target_atom_uid_edit") else str(RUNTIME_CONFIG.get("vam_target_atom_uid", "Person") or "Person"))
        update_runtime_config("vam_target_storable_id", self.vam_target_storable_id_edit.text().strip() if hasattr(self, "vam_target_storable_id_edit") else str(RUNTIME_CONFIG.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"))
        update_runtime_config("emotional_instructions", self.emotional_text.toPlainText().strip())
        update_runtime_config("system_prompt", self.system_prompt_text.toPlainText().strip())
        print("[QtGUI] Text Config Updated.")

    def _is_replay_control_action(self, action):
        raw = str(action or "").strip()
        return raw in {"replay_last_assistant", "replay_chat_session"} or engine.parse_replay_chat_session_start_index(raw) is not None

    def trigger_replay_from_assistant_index(self, replay_index):
        replayable_entries = list(engine.collect_replayable_assistant_entries() or [])
        if not replayable_entries:
            print("[QtGUI] Replay ignored: no assistant replies in current chat context.")
            return
        try:
            resolved_index = int(replay_index)
        except Exception:
            resolved_index = 1
        resolved_index = max(1, min(resolved_index, len(replayable_entries)))
        self.trigger_control_action(engine.build_replay_chat_session_from_action(resolved_index))

    def trigger_control_action(self, action):
        if self._dry_run_is_active():
            print(f"[QtGUI] Control action '{action}' ignored while Dry Run is active.")
            return
        if not self.thread or not self.thread.is_alive():
            if self._is_replay_control_action(action):
                replayable = collect_replayable_assistant_messages()
                if not replayable:
                    print("[QtGUI] Replay ignored: no assistant replies in current chat context.")
                    return
                trigger_manual_action(action)
                print(f"[QtGUI] Control action: {action} (offline replay bootstrap)")
                self.start_engine(offline_replay_only=True)
                return
            print("[QtGUI] Control panel ignored: engine not running.")
            return
        if self._engine_is_offline_replay_only() and action not in {"pause_speech", "skip_speech"} and not self._is_replay_control_action(action):
            print(f"[QtGUI] Control action '{action}' is unavailable during offline replay mode.")
            return
        trigger_manual_action(action)
        print(f"[QtGUI] Control action: {action}")

    def on_engine_change(self, choice):
        mode = choice.lower()
        update_runtime_config("avatar_mode", mode)
        if mode == "vam" and hasattr(self, "vam_play_audio_in_vam_checkbox") and not self.vam_play_audio_in_vam_checkbox.isChecked():
            self.vam_play_audio_in_vam_checkbox.setChecked(True)
            update_runtime_config("vam_play_audio_in_vam", True)
        controls_enabled = mode == "vseeface"
        for widget in [
            self.body_combo,
            self.btn_body_load,
            self.btn_body_save,
            self.btn_body_save_as,
            self.btn_body_delete,
            self.btn_hand_doctor,
            self.emotion_combo,
            self.live_sync_checkbox,
        ]:
            widget.setEnabled(controls_enabled)
        for slider in self.pose_sliders.values():
            slider.setEnabled(controls_enabled)
        self.btn_musetalk_preview.setEnabled(mode == "musetalk")
        if hasattr(self, "btn_musetalk_avatar_focus"):
            self.btn_musetalk_avatar_focus.setEnabled(mode == "musetalk")
        self._advisor_context_manual_override = False
        self.emit_tutorial_event("ui_changed", {"field": "avatar_mode", "value": choice})
        self.update_model_budget_hint()
        print(f"[QtGUI] Avatar Engine set to {choice}.")
        self.save_session()

    def toggle_live_sync(self, checked):
        if self.engine_combo.currentText() != "VSeeFace":
            return
        engine.FORCE_EDIT_MODE = not checked
        status = "LIVE (Brain Controlled)" if checked else "EDITING (Manual)"
        print(f"[QtGUI] Body Mode: {status}")

    def on_emotion_change(self, choice):
        engine.EDIT_EMOTION = choice.lower()
        current_data = AVATAR_PROFILE.get(engine.EDIT_EMOTION, AVATAR_PROFILE["neutral"])
        for key, slider in self.pose_sliders.items():
            slider.set_value(current_data.get(key, 0.0))
        print(f"[QtGUI] Editing Pose: {choice}")

    def refresh_resources(self):
        self.refresh_model_list_quietly(quiet=False)

        voices = [os.path.basename(path) for path in glob.glob("voices/*.wav")]
        self.voice_combo.clear()
        self.voice_combo.addItems(voices or ["No .wav found"])
        if voices:
            self.voice_combo.setCurrentIndex(0)
            update_runtime_config("voice_path", os.path.join("voices", voices[0]))

        self.refresh_preset_list()
        self.refresh_body_list()
        self._populate_chat_provider_combo(RUNTIME_CONFIG.get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID))
        self._refresh_chat_provider_card()

        self.emotional_text.setPlainText(RUNTIME_CONFIG.get("emotional_instructions", ""))
        self.system_prompt_text.setPlainText(RUNTIME_CONFIG.get("system_prompt", ""))
        if hasattr(self, "sensory_pingpong_prompt_text"): self.sensory_pingpong_prompt_text.setPlainText(str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")))
        if hasattr(self, "pocket_tts_python_edit"):
            self.pocket_tts_python_edit.setText(str(RUNTIME_CONFIG.get("pocket_tts_python", "") or ""))
        input_mode = str(RUNTIME_CONFIG.get("input_mode", "voice_activation") or "voice_activation").lower()
        self.input_mode_combo.setCurrentText("Push-to-Talk" if input_mode == "push_to_talk" else "Voice Activation")
        input_role = str(RUNTIME_CONFIG.get("input_message_role", "user") or "user").lower()
        self.input_role_combo.setCurrentText(self._input_role_label_from_value(input_role))
        if hasattr(self, "chat_context_window_spin"):
            self.chat_context_window_spin.setValue(max(4, int(RUNTIME_CONFIG.get("chat_context_window_messages", 20) or 20)))
        if hasattr(self, "chat_overflow_policy_combo"):
            self.chat_overflow_policy_combo.setCurrentText(self._chat_overflow_policy_label_from_value(RUNTIME_CONFIG.get("chat_context_overflow_policy", "rolling_window")))
        self.stream_mode_combo.setCurrentText("On" if bool(RUNTIME_CONFIG.get("stream_mode", False)) else "Off")
        tts_backend = str(RUNTIME_CONFIG.get("tts_backend", "chatterbox") or "chatterbox").lower()
        self._populate_tts_backend_combo(selected_value=tts_backend)
        vram_mode = str(RUNTIME_CONFIG.get("musetalk_vram_mode", "quality") or "quality").lower()
        self.musetalk_vram_combo.setCurrentText(MUSE_VRAM_MODE_LABELS.get(vram_mode, "Quality"))
        for key, slider in self.brain_sliders.items():
            slider.set_value(RUNTIME_CONFIG.get(key, slider.value()))
        for key, slider in self.chunking_sliders.items():
            slider.set_value(RUNTIME_CONFIG.get(key, slider.value()))
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()
        self.on_emotion_change(self.emotion_combo.currentText())
        self.refresh_performance_profile_list()
        self.refresh_tutorial_list()
        self._update_restart_sensitive_controls()
        self.refresh_dry_run_status()
        self.update_model_budget_hint()
        self._publish_addon_event("app.resources_refreshed", {"source": "refresh_resources"})

    def _normalize_model_catalog_entry(self, item):
        if isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            supports_images = bool(item.get("supports_images", False))
            source = str(item.get("source") or "").strip().lower()
        else:
            model_id = str(item or "").strip()
            supports_images = self._infer_model_supports_images(model_id)
            source = ""
        if not model_id:
            return None
        return {
            "id": model_id,
            "supports_images": bool(supports_images),
            "source": source,
        }

    def _infer_model_supports_images(self, model_name):
        value = str(model_name or "").strip().lower()
        if self._is_model_catalog_placeholder(model_name):
            return False
        positive_fragments = (
            "vision", "image", "multimodal", "vl", "llava", "bakllava", "moondream", "pixtral",
            "minicpm-v", "internvl", "phi-3.5-vision", "phi-4-multimodal", "gemma-3", "gpt-4o",
            "gpt-4.1", "omni", "qwen/qwen3.5", "qwen3.5", "qwen2-vl", "qwen2.5-vl", "qvq",
            "grok-"
        )
        negative_fragments = (
            "embedding", "rerank", "whisper", "tts", "audio", "transcribe", "grok-imagine"
        )
        if any(fragment in value for fragment in negative_fragments):
            return False
        return any(fragment in value for fragment in positive_fragments)

    def _set_model_catalog(self, items):
        catalog = []
        seen = set()
        for item in list(items or []):
            entry = self._normalize_model_catalog_entry(item)
            if not entry:
                continue
            model_id = str(entry.get("id") or "")
            if model_id in seen:
                continue
            seen.add(model_id)
            catalog.append(entry)
        self._all_model_catalog = list(catalog)
        if hasattr(self, "model_requires_vision_checkbox") and self.model_requires_vision_checkbox.isChecked():
            catalog = [entry for entry in catalog if bool(entry.get("supports_images", False))]
        self._model_catalog = list(catalog)
        return list(catalog)

    def _current_model_display_items(self):
        catalog = list(getattr(self, "_model_catalog", []) or [])
        if catalog:
            return [str(entry.get("id") or "") for entry in catalog if str(entry.get("id") or "").strip()]
        return []

    def on_model_requires_vision_changed(self, _checked):
        self.refresh_model_list_quietly(quiet=True, preloaded_models=list(getattr(self, "_all_model_catalog", []) or []))
        self.save_session()

    def request_model_list_refresh(self, quiet=True, wait_for_reachable=False):
        provider = self._current_chat_provider_value()
        if self._model_refresh_in_flight and str(getattr(self, "_model_refresh_provider", "") or "") == provider:
            return
        self._model_refresh_generation = int(getattr(self, "_model_refresh_generation", 0) or 0) + 1
        refresh_generation = self._model_refresh_generation
        self._model_refresh_in_flight = True
        self._model_refresh_provider = provider
        if hasattr(self, "btn_model_refresh"):
            self.btn_model_refresh.setEnabled(False)
            self.btn_model_refresh.setText("Waiting..." if wait_for_reachable else "Refreshing...")

        def worker():
            error_placeholder = self._chat_provider_error_placeholder(provider)
            models = None
            first_attempt = True
            while True:
                try:
                    models = get_chat_models(provider=provider, quiet=quiet if first_attempt else True)
                except Exception:
                    models = [error_placeholder]
                    break
                valid_models = [item for item in list(models or []) if item and item != error_placeholder]
                if valid_models or not wait_for_reachable:
                    break
                first_attempt = False
                time.sleep(1.0)
            with self._model_refresh_lock:
                self._pending_model_refresh = list(models or [error_placeholder])
                self._pending_model_refresh_provider = provider
                self._pending_model_refresh_generation = refresh_generation
            QtCore.QMetaObject.invokeMethod(self, "_apply_pending_model_refresh", QtCore.Qt.QueuedConnection)

        threading.Thread(target=worker, daemon=True).start()

    @QtCore.Slot()
    def _apply_pending_model_refresh(self):
        with self._model_refresh_lock:
            models = list(self._pending_model_refresh or [])
            provider = str(getattr(self, "_pending_model_refresh_provider", "") or "")
            refresh_generation = int(getattr(self, "_pending_model_refresh_generation", 0) or 0)
            self._pending_model_refresh = None
            self._pending_model_refresh_provider = ""
            self._pending_model_refresh_generation = 0
        if provider != self._current_chat_provider_value() or refresh_generation != int(getattr(self, "_model_refresh_generation", 0) or 0):
            return
        self._model_refresh_in_flight = False
        self._model_refresh_provider = ""
        if hasattr(self, "btn_model_refresh"):
            self.btn_model_refresh.setEnabled(True)
            self.btn_model_refresh.setText("Refresh")
        self.refresh_model_list_quietly(quiet=True, preloaded_models=models)
        self._refresh_chat_runtime_summary()

    def refresh_model_list_quietly(self, quiet=True, preloaded_models=None):
        if not hasattr(self, "model_combo"):
            return
        provider = self._current_chat_provider_value()
        raw_models = list(preloaded_models or get_chat_models(provider=provider, quiet=quiet))
        available_catalog = self._set_model_catalog(raw_models)
        valid_models = [str(entry.get("id") or "") for entry in list(getattr(self, "_all_model_catalog", []) or []) if str(entry.get("id") or "")]
        self._tutorial_lm_studio_running = bool(valid_models)

        current = str(self.model_combo.currentText() or "").strip()
        previous_items = [self.model_combo.itemText(i) for i in range(self.model_combo.count())]
        filtered_models = [str(entry.get("id") or "") for entry in available_catalog if str(entry.get("id") or "")]
        if raw_models and not filtered_models and hasattr(self, "model_requires_vision_checkbox") and self.model_requires_vision_checkbox.isChecked():
            new_items = ["No Vision Models"]
        else:
            error_placeholder = self._chat_provider_error_placeholder(provider)
            new_items = filtered_models or (raw_models if any(str(item or "").strip() == error_placeholder for item in raw_models) else ["No Models"])

        pending_wanted = str(getattr(self, "_pending_restored_model_name", "") or "").strip()
        if previous_items == new_items and (not pending_wanted or current == pending_wanted):
            self.emit_tutorial_event(
                "model_list_refreshed",
                {"count": len(valid_models), "model_loaded": bool(valid_models), "lm_studio_running": bool(valid_models)},
            )
            if not self._finalize_pending_preset_clean_if_ready():
                self._refresh_preset_dirty_state()
            return

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(new_items)
        target_index = 0
        if filtered_models and current in filtered_models:
            target_index = filtered_models.index(current)
        elif filtered_models:
            wanted = str(getattr(self, "_pending_restored_model_name", "") or "").strip() or str(RUNTIME_CONFIG.get("model_name", "") or "").strip()
            if wanted in filtered_models:
                target_index = filtered_models.index(wanted)
        self.model_combo.setCurrentIndex(max(0, min(target_index, self.model_combo.count() - 1)))
        self.model_combo.blockSignals(False)
        selected_model = str(self.model_combo.currentText() or "").strip()
        if selected_model:
            update_runtime_config("model_name", selected_model)
        pending_wanted = str(getattr(self, "_pending_restored_model_name", "") or "").strip()
        if pending_wanted and selected_model == pending_wanted:
            self._pending_restored_model_name = ""

        self.emit_tutorial_event(
            "model_list_refreshed",
            {"count": len(valid_models), "model_loaded": bool(valid_models), "lm_studio_running": bool(valid_models)},
        )
        self.update_model_budget_hint()
        if not self._finalize_pending_preset_clean_if_ready():
            self._refresh_preset_dirty_state()
        self._refresh_preset_dirty_state()

    def refresh_preset_list(self):
        current = str(self.preset_combo.currentText() or "").strip() if hasattr(self, "preset_combo") else ""
        presets = [Path(path).stem for path in glob.glob("presets/*.json")]
        self.preset_combo.clear()
        self.preset_combo.addItems(presets or ["No Presets"])
        if current and current in presets:
            self.preset_combo.setCurrentText(current)

    def refresh_body_list(self):
        bodies = [Path(path).stem for path in glob.glob("body_configs/*.json")]
        self.body_combo.clear()
        self.body_combo.addItems(bodies or ["No Configs"])

    def emit_tutorial_event(self, event_name, payload=None):
        if not hasattr(self, "tutorial_event_bus") or self.tutorial_event_bus is None:
            return
        try:
            self.tutorial_event_bus.emit_event(str(event_name or ""), payload or {})
        except Exception:
            pass

    def _tutorial_model_loaded(self):
        if not hasattr(self, "model_combo"):
            return False
        current = str(self.model_combo.currentText() or "").strip()
        return not self._is_model_catalog_placeholder(current)

    def _tutorial_last_error_text(self):
        if not hasattr(self, "console_edit"):
            return ""
        lines = [line.strip() for line in self.console_edit.toPlainText().splitlines() if line.strip()]
        error_lines = [
            line for line in lines[-120:]
            if any(marker in line for marker in ("ERROR", "Error", "Failed", "CRITICAL", "Traceback", "✗", "Exception"))
        ]
        return error_lines[-1] if error_lines else ""

    def get_tutorial_runtime_state(self):
        return {
            "lm_studio_running": bool(getattr(self, "_tutorial_lm_studio_running", False)),
            "model_loaded": self._tutorial_model_loaded(),
            "engine_running": bool(self.thread and self.thread.is_alive()),
            "avatar_mode": self.engine_combo.currentText() if hasattr(self, "engine_combo") else "",
            "stream_mode": self.stream_mode_combo.currentText() if hasattr(self, "stream_mode_combo") else "",
            "tts_backend": self._current_tts_backend_value(),
            "musetalk_vram_mode": self.musetalk_vram_combo.currentText() if hasattr(self, "musetalk_vram_combo") else "",
            "musetalk_avatar_pack": self.musetalk_avatar_pack_combo.currentText() if hasattr(self, "musetalk_avatar_pack_combo") else "",
            "preview_visible": bool(hasattr(self, "preview_dock") and self.preview_dock.isVisible()),
            "dry_run_active": bool((dry_run.get_status() or {}).get("active")),
            "dry_run_complete": bool((dry_run.get_status() or {}).get("complete")),
            "performance_profile": self.performance_profile_combo.currentData() if hasattr(self, "performance_profile_combo") else "",
            "active_preset": self.preset_combo.currentText() if hasattr(self, "preset_combo") else "",
            "last_error_text": self._tutorial_last_error_text(),
        }

    def _detected_gpu_vram_gib(self):
        try:
            if nvmlInit and nvmlDeviceGetHandleByIndex and nvmlDeviceGetMemoryInfo:
                nvmlInit()
                try:
                    handle = nvmlDeviceGetHandleByIndex(0)
                    info = nvmlDeviceGetMemoryInfo(handle)
                    return float(info.total) / (1024 ** 3)
                finally:
                    if nvmlShutdown:
                        nvmlShutdown()
        except Exception:
            pass
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
                if lines:
                    return float(lines[0]) / 1024.0
        except Exception:
            pass
        try:
            if hasattr(engine, "torch") and engine.torch.cuda.is_available():
                props = engine.torch.cuda.get_device_properties(0)
                return float(props.total_memory) / (1024 ** 3)
        except Exception:
            pass
        return None

    def _current_gpu_memory_snapshot_gib(self):
        try:
            if nvmlInit and nvmlDeviceGetHandleByIndex and nvmlDeviceGetMemoryInfo:
                nvmlInit()
                try:
                    handle = nvmlDeviceGetHandleByIndex(0)
                    info = nvmlDeviceGetMemoryInfo(handle)
                    return {
                        "total_gib": float(info.total) / (1024 ** 3),
                        "free_gib": float(info.free) / (1024 ** 3),
                        "used_gib": float(info.used) / (1024 ** 3),
                        "source": "nvml",
                    }
                finally:
                    if nvmlShutdown:
                        nvmlShutdown()
        except Exception:
            pass
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.free,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
                if lines:
                    first = lines[0]
                    parts = [part.strip() for part in first.split(",")]
                    if len(parts) >= 3:
                        used_mib = float(parts[0])
                        free_mib = float(parts[1])
                        total_mib = float(parts[2])
                        return {
                            "total_gib": total_mib / 1024.0,
                            "free_gib": free_mib / 1024.0,
                            "used_gib": used_mib / 1024.0,
                            "source": "nvidia-smi",
                        }
        except Exception:
            pass
        try:
            if hasattr(engine, "torch") and engine.torch.cuda.is_available():
                free_bytes, total_bytes = engine.torch.cuda.mem_get_info()
                free_gib = float(free_bytes) / (1024 ** 3)
                total_gib = float(total_bytes) / (1024 ** 3)
                used_gib = max(0.0, total_gib - free_gib)
                return {
                    "total_gib": total_gib,
                    "free_gib": free_gib,
                    "used_gib": used_gib,
                    "source": "torch",
                }
        except Exception:
            pass
        total = self._detected_gpu_vram_gib()
        if total is None:
            return None
        return {
            "total_gib": total,
            "free_gib": None,
            "used_gib": None,
            "source": "total_only",
        }

    def _estimate_setup_increment_gib(self):
        avatar_mode = str(self.engine_combo.currentText() or "").strip().lower() if hasattr(self, "engine_combo") else "musetalk"
        tts_backend = self._current_tts_backend_value()
        vram_mode_label = str(self.musetalk_vram_combo.currentText() or "").strip() if hasattr(self, "musetalk_vram_combo") else "Very Low VRAM"

        if avatar_mode == "musetalk":
            budget = MODEL_ADVISOR_BUILTIN_FINGERPRINTS_GIB["musetalk"].get(vram_mode_label, 6.5)
        else:
            budget = float(MODEL_ADVISOR_BUILTIN_FINGERPRINTS_GIB.get("vseeface", 0.8))
        budget += float(MODEL_ADVISOR_TTS_OVERHEAD_GIB.get(tts_backend, 2.0))
        if hasattr(self, "stream_mode_combo") and self.stream_mode_combo.currentText() == "On":
            budget += MODEL_ADVISOR_STREAM_OVERHEAD_GIB
        return budget

    def _recommended_model_budget_gib(self):
        snapshot = self._current_gpu_memory_snapshot_gib()
        if not snapshot:
            return None, None, None, None, None
        total = float(snapshot.get("total_gib") or 0.0)
        used_now = snapshot.get("used_gib")
        setup_increment = self._estimate_setup_increment_gib()
        safety_margin = MODEL_ADVISOR_SAFETY_MARGIN_GIB
        projected_pre_llm_total = None
        if used_now is not None:
            if bool(self.thread and self.thread.is_alive()):
                projected_pre_llm_total = float(used_now)
            else:
                projected_pre_llm_total = float(used_now) + float(setup_increment)
        if projected_pre_llm_total is not None:
            remaining = max(0.5, total - projected_pre_llm_total - safety_margin)
        else:
            remaining = max(0.5, total - float(setup_increment) - safety_margin)
        return snapshot, remaining, setup_increment, projected_pre_llm_total, safety_margin

    def _parse_lms_estimate_output(self, output):
        text = str(output or "")
        gpu_match = re.search(r"Estimated GPU Memory:\s*([0-9.]+)\s*GiB", text, re.IGNORECASE)
        total_match = re.search(r"Estimated Total Memory:\s*([0-9.]+)\s*GiB", text, re.IGNORECASE)
        return {
            "gpu_gib": float(gpu_match.group(1)) if gpu_match else None,
            "total_gib": float(total_match.group(1)) if total_match else None,
            "raw": text.strip(),
        }

    def request_model_estimate(self, model_name):
        model_name = str(model_name or "").strip()
        if self._is_model_catalog_placeholder(model_name):
            return
        if model_name in self._model_estimate_cache or self._model_estimate_in_flight:
            return
        self._model_estimate_in_flight = True

        def worker():
            payload = {"model": model_name, "estimate": None}
            try:
                result = subprocess.run(
                    ["lms", "load", "--estimate-only", model_name],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode == 0:
                    payload["estimate"] = self._parse_lms_estimate_output((result.stdout or "") + "\n" + (result.stderr or ""))
                else:
                    payload["estimate"] = {"gpu_gib": None, "total_gib": None, "raw": (result.stdout or "") + "\n" + (result.stderr or "")}
            except Exception as exc:
                payload["estimate"] = {"gpu_gib": None, "total_gib": None, "raw": str(exc)}
            with self._model_estimate_lock:
                self._pending_model_estimate = payload
            QtCore.QMetaObject.invokeMethod(self, "_apply_pending_model_estimate", QtCore.Qt.QueuedConnection)

        threading.Thread(target=worker, daemon=True).start()

    def request_model_context_estimates(self, model_name):
        model_name = str(model_name or "").strip()
        if self._is_model_catalog_placeholder(model_name):
            return
        if model_name in self._model_context_estimate_cache or self._model_context_estimate_in_flight:
            return
        self._model_context_estimate_in_flight = True

        def worker():
            context_lengths = [4096, 8192, 16384, 32768]
            samples = []
            for context_length in context_lengths:
                try:
                    result = subprocess.run(
                        ["lms", "load", "--estimate-only", model_name, "--context-length", str(context_length)],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    combined = (result.stdout or "") + "\n" + (result.stderr or "")
                    estimate = self._parse_lms_estimate_output(combined)
                    if result.returncode == 0 and estimate.get("gpu_gib") is not None:
                        samples.append({"context_length": context_length, "gpu_gib": float(estimate["gpu_gib"])})
                except Exception:
                    continue
            with self._model_context_estimate_lock:
                self._pending_model_context_estimate = {"model": model_name, "samples": samples}
            QtCore.QMetaObject.invokeMethod(self, "_apply_pending_model_context_estimate", QtCore.Qt.QueuedConnection)

        threading.Thread(target=worker, daemon=True).start()

    def request_single_context_estimate(self, model_name, context_length):
        model_name = str(model_name or "").strip()
        try:
            context_length = int(context_length)
        except Exception:
            return
        if self._is_model_catalog_placeholder(model_name):
            return
        cache_key = (model_name, context_length)
        if cache_key in self._model_single_context_estimate_cache or self._single_context_estimate_in_flight:
            return
        self._single_context_estimate_in_flight = True

        def worker():
            payload = {"model": model_name, "context_length": context_length, "estimate": None}
            try:
                result = subprocess.run(
                    ["lms", "load", "--estimate-only", model_name, "--context-length", str(context_length)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                combined = (result.stdout or "") + "\n" + (result.stderr or "")
                estimate = self._parse_lms_estimate_output(combined)
                payload["estimate"] = estimate if result.returncode == 0 else {"gpu_gib": None, "total_gib": None, "raw": combined}
            except Exception as exc:
                payload["estimate"] = {"gpu_gib": None, "total_gib": None, "raw": str(exc)}
            with self._single_context_estimate_lock:
                self._pending_single_context_estimate = payload
            QtCore.QMetaObject.invokeMethod(self, "_apply_pending_single_context_estimate", QtCore.Qt.QueuedConnection)

        threading.Thread(target=worker, daemon=True).start()

    @QtCore.Slot()
    def _apply_pending_model_estimate(self):
        with self._model_estimate_lock:
            payload = dict(self._pending_model_estimate or {})
            self._pending_model_estimate = None
        self._model_estimate_in_flight = False
        model_name = str(payload.get("model") or "").strip()
        estimate = payload.get("estimate")
        if model_name:
            self._model_estimate_cache[model_name] = estimate
        self.update_model_budget_hint()

    @QtCore.Slot()
    def _apply_pending_model_context_estimate(self):
        with self._model_context_estimate_lock:
            payload = dict(self._pending_model_context_estimate or {})
            self._pending_model_context_estimate = None
        self._model_context_estimate_in_flight = False
        model_name = str(payload.get("model") or "").strip()
        samples = list(payload.get("samples") or [])
        if model_name:
            self._model_context_estimate_cache[model_name] = samples
        self.update_model_budget_hint()

    @QtCore.Slot()
    def _apply_pending_single_context_estimate(self):
        with self._single_context_estimate_lock:
            payload = dict(self._pending_single_context_estimate or {})
            self._pending_single_context_estimate = None
        self._single_context_estimate_in_flight = False
        model_name = str(payload.get("model") or "").strip()
        context_length = int(payload.get("context_length") or 0)
        estimate = payload.get("estimate")
        if model_name and context_length > 0:
            self._model_single_context_estimate_cache[(model_name, context_length)] = estimate
        self.update_model_budget_hint()

    def update_model_budget_hint(self):
        if not hasattr(self, "model_budget_label") or not hasattr(self, "model_combo"):
            return
        snapshot, suggested_budget, setup_increment, projected_pre_llm_total, safety_margin = self._recommended_model_budget_gib()
        model_name = str(self.model_combo.currentText() or "").strip()
        provider = self._current_chat_provider_value()
        stats_lines = []
        high_baseline_warning = ""
        available_total_vram = None
        if snapshot is not None:
            total_vram = float(snapshot.get("total_gib") or 0.0)
            available_total_vram = total_vram
            free_now = snapshot.get("free_gib")
            used_now = snapshot.get("used_gib")
            stats_lines.append(f"Total VRAM: {total_vram:.1f} GiB")
            if free_now is not None and used_now is not None:
                used_text = f"{used_now:.1f} GiB"
                if used_now >= 3.0:
                    used_text = f"<span style=\"color:#ff8f8f; font-weight:700;\">{used_text}</span>"
                    high_baseline_warning = (
                        "<span style=\"color:#ff6b6b; font-weight:800;\">"
                        "Baseline GPU usage is already quite high. "
                        "For the most reliable estimate, close other GPU-heavy applications and unload any already loaded LM Studio models."
                        "</span>"
                    )
                stats_lines.append(f"In use VRAM: {used_text}")
            else:
                stats_lines.append("In use VRAM: unavailable")
        else:
            stats_lines.append("Total VRAM: unavailable")
            stats_lines.append("In use VRAM: unavailable")

        if not model_name or model_name in {"Scanning...", "No Models", "Error: Check LM Studio", "Error: Check OpenAI", "Error: Check xAI / Grok", "No Vision Models"}:
            summary = self._format_model_advisor_bubbles(stats_lines, [], high_baseline_warning)
            if high_baseline_warning:
                summary += ""
            self.model_budget_label.setText(summary)
            return

        if provider != "lmstudio":
            remote_label = self._chat_provider_label_from_value(provider)
            summary = self._format_model_advisor_bubbles(
                stats_lines,
                [
                    f"Selected chat provider: {remote_label}.",
                    f"Remote model: {model_name}",
                    "Local LM Studio VRAM estimates do not apply to hosted providers.",
                ],
                "",
            )
            self.model_budget_label.setText(summary)
            return

        estimate = self._model_estimate_cache.get(model_name)
        if estimate is None:
            self.request_model_estimate(model_name)
            self.request_model_context_estimates(model_name)
            summary = self._format_model_advisor_bubbles(
                stats_lines,
                [f"Checking LM Studio estimate for '{model_name}'..."],
                high_baseline_warning,
            )
            self.model_budget_label.setText(summary)
            return

        gpu_gib = estimate.get("gpu_gib") if isinstance(estimate, dict) else None
        if gpu_gib is None:
            summary = self._format_model_advisor_bubbles(
                stats_lines,
                [f"LM Studio estimate for '{model_name}' is unavailable."],
                high_baseline_warning,
            )
            self.model_budget_label.setText(summary)
            return

        context_samples = self._model_context_estimate_cache.get(model_name)
        if context_samples is None:
            self.request_model_context_estimates(model_name)

        recommended_context = None
        estimate_lines = []
        if suggested_budget is not None and context_samples:
            for sample in sorted(context_samples, key=lambda item: int(item.get("context_length", 0) or 0)):
                if float(sample.get("gpu_gib", 0.0) or 0.0) <= suggested_budget:
                    recommended_context = int(sample.get("context_length", 0) or 0)
        if recommended_context and hasattr(self, "model_context_input") and not self._advisor_context_manual_override:
            current_context_value = int(self.model_context_input.value())
            if current_context_value != int(recommended_context):
                self._advisor_context_updating = True
                try:
                    self.model_context_input.setValue(int(recommended_context))
                finally:
                    self._advisor_context_updating = False

        verdict = "Comfortable for the current setup."
        if suggested_budget is not None:
            delta = gpu_gib - suggested_budget
            if delta > 0.75:
                verdict = "Likely beyond the recommended budget."
            elif delta > 0.15:
                verdict = "Slightly above the recommended budget."
            elif delta > -0.4:
                verdict = "Tight but workable."
            elif delta > -1.0:
                verdict = "Should fit, but still high-pressure."

        chosen_context = int(self.model_context_input.value()) if hasattr(self, "model_context_input") else int(recommended_context or 8192)
        exact_context_estimate = None
        if context_samples:
            matching_sample = next(
                (sample for sample in context_samples if int(sample.get("context_length", 0) or 0) == chosen_context),
                None,
            )
            if matching_sample is not None:
                exact_context_estimate = float(matching_sample.get("gpu_gib", 0.0) or 0.0)
        if exact_context_estimate is None:
            cached_exact = self._model_single_context_estimate_cache.get((model_name, chosen_context))
            if isinstance(cached_exact, dict) and cached_exact.get("gpu_gib") is not None:
                exact_context_estimate = float(cached_exact.get("gpu_gib") or 0.0)
            elif chosen_context > 0:
                self.request_single_context_estimate(model_name, chosen_context)

        exact_context_pending = exact_context_estimate is None
        if exact_context_estimate is not None:
            estimated_total_for_context = (
                float(projected_pre_llm_total or 0.0) + float(exact_context_estimate)
                if projected_pre_llm_total is not None
                else float(exact_context_estimate)
            )
        else:
            estimated_total_for_context = (
                float(projected_pre_llm_total or 0.0) + float(gpu_gib)
                if projected_pre_llm_total is not None
                else float(gpu_gib)
            )

        if exact_context_pending:
            estimate_lines.append("Estimated VRAM usage with current settings: checking selected context window...")
            if recommended_context:
                estimate_lines.append(f"- Recommended max context window: {recommended_context:,} tokens")
            else:
                estimate_lines.append("- Recommended max context window: checking...")
        elif available_total_vram is not None and estimated_total_for_context > available_total_vram:
            estimate_lines.append(
                f"Estimated VRAM usage with current settings: {estimated_total_for_context:.1f} GiB "
                f"<span style=\"color:#ff8f8f; font-weight:700;\">(more than available)</span>"
            )
        else:
            estimate_lines.append("Estimated VRAM usage with current settings:")
            estimate_lines.append(
                f"- {chosen_context:,} token context window: {estimated_total_for_context:.1f} GiB"
            )
            if recommended_context:
                estimate_lines.append(f"- Recommended max context window: {recommended_context:,} tokens")
            elif context_samples is None or exact_context_estimate is None:
                estimate_lines.append("- Recommended max context window: checking...")
        estimate_lines.append(f"Assessment: {verdict}")
        summary = self._format_model_advisor_bubbles(stats_lines, estimate_lines, high_baseline_warning)
        self.model_budget_label.setText(summary)

    def _format_model_advisor_bubbles(self, stats_lines, estimate_lines, warning_html=""):
        def bubble(lines, background, border):
            if not lines:
                return ""
            return (
                f"<div style=\"margin:0 0 8px 0; padding:8px 10px; "
                f"background:{background}; border:1px solid {border}; border-radius:8px;\">"
                + "<br>".join(lines)
                + "</div>"
            )

        parts = [
            bubble(stats_lines, "#111924", "#243243"),
            bubble(estimate_lines, "#101722", "#2b3950"),
        ]
        if warning_html:
            parts.append(
                f"<div style=\"margin:0 0 8px 0; padding:8px 10px; "
                f"background:#2a1214; border:1px solid #7a2f36; border-radius:8px;\">{warning_html}</div>"
            )
        return "".join(part for part in parts if part)

    def load_performance_profile_by_id(self, name):
        if not name:
            return False
        payload = dry_run.load_performance_profile(name)
        if not payload:
            print(f"[QtGUI] Could not load performance profile: {name}")
            return False
        for combo_name in ("performance_profile_combo", "chunking_profile_combo"):
            combo = getattr(self, combo_name, None)
            if combo is None:
                continue
            for index in range(combo.count()):
                if combo.itemData(index) == name:
                    combo.setCurrentIndex(index)
                    break
        raw_settings = dict(payload.get("settings_to_apply") or {})
        settings = {key: value for key, value in raw_settings.items() if key in PERFORMANCE_PROFILE_APPLY_KEYS}
        self._apply_runtime_settings_dict(settings)
        self.save_session()
        print(f"[QtGUI] Loaded performance profile: {name}")
        self.emit_tutorial_event("performance_profile_loaded", {"name": name})
        self.refresh_dry_run_status()
        return True

    def apply_safe_tutorial_defaults(self):
        if hasattr(self, "engine_combo"):
            self.engine_combo.setCurrentText("MuseTalk")
        if hasattr(self, "stream_mode_combo"):
            self.stream_mode_combo.setCurrentText("On")
        if hasattr(self, "musetalk_vram_combo"):
            self.musetalk_vram_combo.setCurrentText("Very Low VRAM")
        if hasattr(self, "tts_backend_combo"):
            self._populate_tts_backend_combo(selected_value="pockettts")
            index = self.tts_backend_combo.findData("pockettts")
            if index >= 0:
                self.tts_backend_combo.setCurrentIndex(index)
        self._ensure_pocket_tts_python_path()
        self.save_session()
        print("[QtGUI] Applied safe tutorial defaults.")
        self.emit_tutorial_event("safe_defaults_applied", self.get_tutorial_runtime_state())

    def refresh_tutorial_list(self):
        if not hasattr(self, "tutorials_list"):
            return
        tutorials = tutorial_framework.list_tutorials()
        self.tutorials_list.clear()
        for item in tutorials:
            label = f"{item['title']} ({item['step_count']} steps)"
            list_item = QtWidgets.QListWidgetItem(label)
            list_item.setData(QtCore.Qt.UserRole, item["id"])
            list_item.setToolTip(item.get("description", ""))
            self.tutorials_list.addItem(list_item)
        if tutorials:
            self.tutorials_list.setCurrentRow(0)
            self.btn_tutorial_start.setEnabled(True)
        else:
            self.tutorial_description.setPlainText("No tutorials found in the tutorials folder.")
            self.btn_tutorial_start.setEnabled(False)

    def on_tutorial_selection_changed(self, row):
        if row < 0 or not hasattr(self, "tutorials_list"):
            if hasattr(self, "tutorial_description"):
                self.tutorial_description.clear()
            return
        item = self.tutorials_list.item(row)
        tutorial_id = item.data(QtCore.Qt.UserRole) if item else ""
        payload = tutorial_framework.load_tutorial(tutorial_id)
        if not payload:
            self.tutorial_description.setPlainText("Could not load the selected tutorial.")
            return
        text = (
            f"{payload.get('title', tutorial_id)}\n\n"
            f"{payload.get('description', '')}\n\n"
            f"Steps: {len(payload.get('steps') or [])}"
        )
        self.tutorial_description.setPlainText(text.strip())

    def start_selected_tutorial(self):
        if not hasattr(self, "tutorials_list") or self.tutorials_list.currentRow() < 0:
            print("[QtGUI] No tutorial selected.")
            return
        item = self.tutorials_list.currentItem()
        tutorial_id = item.data(QtCore.Qt.UserRole) if item else ""
        self.start_tutorial(tutorial_id)

    def start_tutorial(self, tutorial_id):
        payload = tutorial_framework.load_tutorial(tutorial_id)
        if not payload:
            print(f"[QtGUI] Could not load tutorial: {tutorial_id}")
            return
        if self.active_tutorial_overlay is not None:
            try:
                self.active_tutorial_overlay.finish("restarted")
            except Exception:
                pass
        self.active_tutorial_overlay = tutorial_framework.TutorialOverlay(self, payload, self)
        self.active_tutorial_overlay.finished.connect(self.on_tutorial_finished)
        self.active_tutorial_overlay.start()
        self.emit_tutorial_event("tutorial_started", {"id": payload.get("id", tutorial_id), "title": payload.get("title", tutorial_id)})
        print(f"[QtGUI] Tutorial started: {payload.get('title', tutorial_id)}")

    def on_tutorial_finished(self, reason):
        if self.active_tutorial_overlay is not None:
            self.active_tutorial_overlay.deleteLater()
            self.active_tutorial_overlay = None
        self.emit_tutorial_event("tutorial_finished", {"reason": reason})
        print(f"[QtGUI] Tutorial finished: {reason}")

    def maybe_prompt_first_run_tutorial(self):
        if not self.first_run:
            return
        self.first_run = False
        self.save_session()
        choice = QtWidgets.QMessageBox.question(
            self,
            "Quick Start Tutorial",
            "Would you like to start the interactive First Run tutorial?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            self.start_tutorial("first_run")

    def load_preset(self):
        name = self.preset_combo.currentText()
        if not name or name in {"No Presets", "Select Preset..."}:
            return
        path = Path("presets") / f"{name}.json"
        if not path.exists():
            return
        scroll_state = (
            self._capture_vertical_scroll_state(self.system_shaping_scroll)
            if hasattr(self, "system_shaping_scroll")
            else None
        )
        update_runtime_config("active_preset_name", name)
        data = json.loads(path.read_text(encoding="utf-8"))
        preset_model_name = str(data.get("model_name") or "").strip()
        preset_provider_name = chat_providers.normalize_provider_id(
            data.get("chat_provider", self._current_chat_provider_value()),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )
        self._queue_preset_clean_after_model_refresh(name, preset_provider_name, preset_model_name)
        if preset_model_name:
            self._pending_restored_model_name = preset_model_name
            update_runtime_config("model_name", preset_model_name)
        if "chat_provider" in data and hasattr(self, "chat_provider_combo"):
            self._set_chat_provider_selection(data["chat_provider"])
            self.on_chat_provider_changed(self.chat_provider_combo.currentText())
        if "chat_provider_settings" in data:
            update_runtime_config("chat_provider_settings", data.get("chat_provider_settings", {}))
            self._refresh_chat_provider_card()
        update_runtime_config("chat_provider_generation_settings", data.get("chat_provider_generation_settings", {}))
        self._refresh_chat_provider_generation_card()
        if preset_model_name:
            self._apply_saved_model_name(preset_model_name)
        if "voice_file" in data:
            index = self.voice_combo.findText(data["voice_file"])
            if index >= 0:
                self.voice_combo.setCurrentIndex(index)
        if "input_mode" in data:
            mode_text = "Push-to-Talk" if str(data["input_mode"]).lower() == "push_to_talk" else "Voice Activation"
            self.input_mode_combo.setCurrentText(mode_text)
        if "input_message_role" in data:
            role_text = self._input_role_label_from_value(data["input_message_role"])
            self.input_role_combo.setCurrentText(role_text)
        if "stream_mode" in data:
            self.stream_mode_combo.setCurrentText("On" if bool(data["stream_mode"]) else "Off")
        if "musetalk_loop_fade_ms" in data and hasattr(self, "musetalk_loop_fade_spin"):
            fade_ms = max(0, int(data["musetalk_loop_fade_ms"] or 0))
            self.musetalk_loop_fade_spin.setValue(fade_ms)
            self.on_musetalk_loop_fade_changed(fade_ms)
        if "visual_reply_mode" in data and hasattr(self, "visual_reply_mode_combo"):
            mode_text = self._visual_reply_mode_label_from_value(data["visual_reply_mode"])
            self.visual_reply_mode_combo.setCurrentText(mode_text)
            self.on_visual_reply_mode_changed(mode_text)
        if "visual_reply_provider" in data and hasattr(self, "visual_reply_provider_combo"):
            provider_text = self._visual_reply_provider_label_from_value(data["visual_reply_provider"])
            self.visual_reply_provider_combo.setCurrentText(provider_text)
            self.on_visual_reply_provider_changed(provider_text)
        if "visual_reply_size" in data and hasattr(self, "visual_reply_size_combo"):
            size_text = self._normalize_visual_reply_size(data["visual_reply_size"])
            self.visual_reply_size_combo.setCurrentText(self._visual_reply_size_label_from_value(size_text))
            self.on_visual_reply_size_changed(size_text)
        if "visual_reply_model" in data and hasattr(self, "visual_reply_model_edit"):
            self.visual_reply_model_edit.setText(str(data["visual_reply_model"] or "gpt-image-1"))
            self.on_visual_reply_model_changed()
        if "visual_reply_auto_show_dock" in data and hasattr(self, "visual_reply_auto_show_checkbox"):
            auto_show = bool(data["visual_reply_auto_show_dock"])
            self.visual_reply_auto_show_checkbox.setChecked(auto_show)
            self.on_visual_reply_auto_show_changed(auto_show)
        if "sensory_pingpong_enabled" in data and hasattr(self, "sensory_pingpong_checkbox"):
            pingpong_enabled = bool(data["sensory_pingpong_enabled"])
            self.sensory_pingpong_checkbox.setChecked(pingpong_enabled)
            self.on_sensory_pingpong_enabled_changed(pingpong_enabled)
        if "sensory_allow_hidden_proactive_speech" in data and hasattr(self, "sensory_allow_hidden_proactive_checkbox"):
            proactive_enabled = bool(data["sensory_allow_hidden_proactive_speech"])
            self.sensory_allow_hidden_proactive_checkbox.setChecked(proactive_enabled)
            self.on_sensory_allow_hidden_proactive_changed(proactive_enabled)
        if "sensory_allow_hidden_visual_generation" in data and hasattr(self, "sensory_allow_hidden_visual_checkbox"):
            visual_enabled = bool(data["sensory_allow_hidden_visual_generation"])
            self.sensory_allow_hidden_visual_checkbox.setChecked(visual_enabled)
            self.on_sensory_allow_hidden_visual_changed(visual_enabled)
        if "sensory_pingpong_history_depth" in data and hasattr(self, "sensory_pingpong_history_spin"):
            pingpong_depth = max(0, int(data["sensory_pingpong_history_depth"] or 0))
            self.sensory_pingpong_history_spin.setValue(pingpong_depth)
            self.on_sensory_pingpong_history_depth_changed(pingpong_depth)
        if "sensory_pingpong_prompt" in data and hasattr(self, "sensory_pingpong_prompt_text"):
            prompt_text = str(data["sensory_pingpong_prompt"] or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")).strip() or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")
            self.sensory_pingpong_prompt_text.setPlainText(prompt_text)
            update_runtime_config("sensory_pingpong_prompt", prompt_text)
        if "sensory_pingpong_source_prompts" in data:
            prompt_map = self._normalize_sensory_pingpong_source_prompt_map(data.get("sensory_pingpong_source_prompts", {})) if hasattr(self, "_normalize_sensory_pingpong_source_prompt_map") else dict(data.get("sensory_pingpong_source_prompts", {}) or {})
            update_runtime_config("sensory_pingpong_source_prompts", prompt_map)
            self._refresh_sensory_feedback_source_tabs()
        if "sensory_feedback_source" in data and hasattr(self, "sensory_feedback_source_combo"):
            source_value = str(data["sensory_feedback_source"] or "off")
            self.refresh_sensory_feedback_source_options(selected_value=source_value)
            self.on_sensory_feedback_source_changed(source_value)
        if "sensory_feedback_interval_seconds" in data and hasattr(self, "sensory_feedback_interval_spin"):
            interval_seconds = max(2.0, float(data["sensory_feedback_interval_seconds"] or 7.0))
            self.sensory_feedback_interval_spin.setValue(interval_seconds)
            self.on_sensory_feedback_interval_changed(interval_seconds)
        if "tts_backend" in data and hasattr(self, "tts_backend_combo"):
            backend_value = str(data["tts_backend"]).strip().lower()
            combo = self.tts_backend_combo
            combo.blockSignals(True)
            try:
                self._populate_tts_backend_combo(selected_value=backend_value)
                index = combo.findData(backend_value)
                if index >= 0:
                    combo.setCurrentIndex(index)
            finally:
                combo.blockSignals(False)
        if "tts_seed" in data and hasattr(self, "tts_seed_spin"):
            self.tts_seed_spin.setValue(max(0, int(data["tts_seed"] or 0)))
            self.on_tts_seed_changed(self.tts_seed_spin.value())
        if "tts_temperature" in data and hasattr(self, "tts_temperature_spin"):
            self.tts_temperature_spin.setValue(max(0.05, float(data["tts_temperature"] or 0.8)))
            self.on_tts_temperature_changed(self.tts_temperature_spin.value())
        if "tts_top_p" in data and hasattr(self, "tts_top_p_spin"):
            self.tts_top_p_spin.setValue(max(0.0, min(1.0, float(data["tts_top_p"] or 0.9))))
            self.on_tts_top_p_changed(self.tts_top_p_spin.value())
        if "tts_top_k" in data and hasattr(self, "tts_top_k_spin"):
            self.tts_top_k_spin.setValue(max(0, int(data["tts_top_k"] or 0)))
            self.on_tts_top_k_changed(self.tts_top_k_spin.value())
        if "tts_repeat_penalty" in data and hasattr(self, "tts_repeat_penalty_spin"):
            self.tts_repeat_penalty_spin.setValue(max(1.0, float(data["tts_repeat_penalty"] or 1.2)))
            self.on_tts_repeat_penalty_changed(self.tts_repeat_penalty_spin.value())
        if "tts_min_p" in data and hasattr(self, "tts_min_p_spin"):
            self.tts_min_p_spin.setValue(max(0.0, min(1.0, float(data["tts_min_p"] or 0.0))))
            self.on_tts_min_p_changed(self.tts_min_p_spin.value())
        if "tts_normalize_loudness" in data and hasattr(self, "tts_normalize_loudness_checkbox"):
            self.tts_normalize_loudness_checkbox.setChecked(bool(data["tts_normalize_loudness"]))
            self.on_tts_normalize_loudness_changed(bool(data["tts_normalize_loudness"]))
        if "allow_proactive_replies" in data and hasattr(self, "allow_proactive_checkbox"):
            self.allow_proactive_checkbox.setChecked(bool(data["allow_proactive_replies"]))
            self.on_allow_proactive_replies_changed(bool(data["allow_proactive_replies"]))
        if "require_first_user_before_proactive" in data and hasattr(self, "require_first_user_checkbox"):
            self.require_first_user_checkbox.setChecked(bool(data["require_first_user_before_proactive"]))
            self.on_require_first_user_before_proactive_changed(bool(data["require_first_user_before_proactive"]))
        if "listen_idle_window_seconds" in data and hasattr(self, "listen_idle_window_spin"):
            listen_seconds = max(0.5, float(data["listen_idle_window_seconds"] or 5.0))
            self.listen_idle_window_spin.setValue(listen_seconds)
            self.on_listen_idle_window_changed(listen_seconds)
        if "proactive_delay_seconds" in data and hasattr(self, "proactive_delay_spin"):
            proactive_seconds = max(0.5, float(data["proactive_delay_seconds"] or 10.0))
            self.proactive_delay_spin.setValue(proactive_seconds)
            self.on_proactive_delay_changed(proactive_seconds)
        if "chat_context_window_messages" in data and hasattr(self, "chat_context_window_spin"):
            context_messages = max(4, int(data["chat_context_window_messages"] or 20))
            self.chat_context_window_spin.setValue(context_messages)
            self.on_chat_context_window_changed(context_messages)
        if "stored_chat_history_limit" in data and hasattr(self, "stored_chat_history_limit_spin"):
            stored_limit = max(0, int(data["stored_chat_history_limit"] or 0))
            self.stored_chat_history_limit_spin.setValue(stored_limit)
            self.on_stored_chat_history_limit_changed(stored_limit)
        if "chat_context_overflow_policy" in data and hasattr(self, "chat_overflow_policy_combo"):
            policy_text = self._chat_overflow_policy_label_from_value(data["chat_context_overflow_policy"])
            self.chat_overflow_policy_combo.setCurrentText(policy_text)
            self.on_chat_overflow_policy_changed(policy_text)
        if "musetalk_avatar_pack_id" in data and hasattr(self, "musetalk_avatar_pack_combo"):
            self.refresh_musetalk_avatar_pack_list(selected_pack_id=data["musetalk_avatar_pack_id"])
            for index in range(self.musetalk_avatar_pack_combo.count()):
                if str(self.musetalk_avatar_pack_combo.itemData(index) or "") == str(data["musetalk_avatar_pack_id"] or ""):
                    self.musetalk_avatar_pack_combo.setCurrentIndex(index)
                    break
            self.on_musetalk_avatar_pack_change(self.musetalk_avatar_pack_combo.currentText())
        if "pocket_tts_python" in data:
            preset_python = str(data["pocket_tts_python"] or "").strip()
            pocket_tts_python_edit = getattr(self, "pocket_tts_python_edit", None)
            if preset_python and pocket_tts_python_edit is not None:
                pocket_tts_python_edit.setText(preset_python)
                self.on_pocket_tts_python_changed()
            elif self._current_tts_backend_value() == "pockettts" and pocket_tts_python_edit is not None:
                current_python = pocket_tts_python_edit.text().strip()
                if current_python:
                    print(
                        "[QtGUI] Preset requested PocketTTS but did not include a PocketTTS Python path. "
                        f"Keeping current path: {current_python}"
                    )
                else:
                    self._ensure_pocket_tts_python_path()
        elif self._current_tts_backend_value() == "pockettts" and hasattr(self, "pocket_tts_python_edit"):
            self._ensure_pocket_tts_python_path()
        self.emotional_text.setPlainText(data.get("emotional_instructions", ""))
        self.system_prompt_text.setPlainText(data.get("system_prompt", ""))
        for key, slider in self.brain_sliders.items():
            if key in data:
                slider.set_value(data[key])
                self.update_brain_value(key, data[key], key == "top_k")
        if "limit_response_length" in data:
            self.limit_response_checkbox.setChecked(bool(data["limit_response_length"]))
            self.on_limit_response_length_changed(bool(data["limit_response_length"]))
        if "max_response_tokens" in data:
            tokens = max(32, int(data["max_response_tokens"] or DEFAULT_MAX_RESPONSE_TOKENS))
            self.max_response_tokens_spin.setValue(tokens)
            self.on_max_response_tokens_changed(tokens)
        self._refresh_chat_provider_generation_card()
        previous_restoring_preset = bool(getattr(self, "_restoring_preset", False))
        self._restoring_preset = True
        try:
            if self._addon_manager is not None:
                try:
                    self._addon_manager.import_preset_state(data)
                except Exception:
                    pass
            self._refresh_sensory_feedback_source_tabs()
            self._refresh_addon_group_tabs()
            self._refresh_tts_runtime_card(activate_tab=False)
        finally:
            self._restoring_preset = previous_restoring_preset
        print(f"[QtGUI] Loading preset: {name}...")
        self.emit_tutorial_event("preset_loaded", {"name": name})
        self._finalize_pending_preset_clean_if_ready()
        self.save_session()
        self._restore_system_shaping_scroll_state(scroll_state)
        QtCore.QTimer.singleShot(0, lambda state=scroll_state: self._restore_system_shaping_scroll_state(state))
        QtCore.QTimer.singleShot(150, lambda state=scroll_state: self._restore_system_shaping_scroll_state(state))

    def save_preset_dialog(self):
        name = QtInputDialog.get_text("Save Preset", "Enter Preset Name:", self)
        if name:
            self.save_preset(name)

    def save_current_preset(self):
        name = self.preset_combo.currentText()
        if not name or name in {"No Presets", "Select Preset..."}:
            self.save_preset_dialog()
            return
        self.save_preset(name)

    def save_preset(self, name):
        data = self._build_preset_payload(ensure_pocket_tts_path=True)
        path = Path("presets") / f"{name}.json"
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        self.refresh_preset_list()
        index = self.preset_combo.findText(name)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        self._update_preset_reference_from_selection(name)
        print(f"[QtGUI] Saved preset: {path}")
        self.save_session()

    def delete_current_preset(self):
        name = self.preset_combo.currentText()
        if not name or name in {"No Presets", "Select Preset..."}:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Preset", f"Delete '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        path = Path("presets") / f"{name}.json"
        if path.exists():
            path.unlink()
        self.refresh_preset_list()
        print(f"[QtGUI] Deleted preset: {path}")

    def save_body_dialog(self):
        name = QtInputDialog.get_text("Save Body Config", "Enter Body Config Name:", self)
        if name:
            self.save_body_config(name)

    def save_current_body(self):
        name = self.body_combo.currentText()
        if not name or name == "No Configs":
            self.save_body_dialog()
            return
        self.save_body_config(name)

    def save_body_config(self, name):
        data = {
            "profile": AVATAR_PROFILE,
            "hands": HAND_CALIBRATION,
        }
        path = Path("body_configs") / f"{name}.json"
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        self.refresh_body_list()
        index = self.body_combo.findText(name)
        if index >= 0:
            self.body_combo.setCurrentIndex(index)
        print(f"[QtGUI] Saved Full Body & Hands: {path}")
        self.save_session()

    def load_body_config_from_combo(self):
        name = self.body_combo.currentText()
        if not name or name == "No Configs":
            return
        path = Path("body_configs") / f"{name}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        if "profile" in data:
            AVATAR_PROFILE.update(data["profile"])
            if "hands" in data:
                engine.HAND_CALIBRATION.update(data["hands"])
        else:
            AVATAR_PROFILE.update(data)
        self.on_emotion_change(self.emotion_combo.currentText())
        print(f"[QtGUI] Loading Config: {name}...")
        self.save_session()

    def delete_current_body(self):
        name = self.body_combo.currentText()
        if not name or name in {"No Configs", "Default"}:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Body Config", f"Delete '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        path = Path("body_configs") / f"{name}.json"
        if path.exists():
            path.unlink()
        self.refresh_body_list()
        print(f"[QtGUI] Deleted body config: {path}")

    def open_hand_debugger(self):
        dialog = HandDoctorDialog(self, self)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.hand_doctor_dialog = dialog

    def show_musetalk_preview(self):
        if self.engine_combo.currentText() != "MuseTalk":
            return
        if self._musetalk_avatar_focus_active:
            stage_window = self._ensure_musetalk_stage_window()
            self._attach_musetalk_preview_to_host("stage")
            stage_window.show()
            stage_window.raise_()
            stage_window.activateWindow()
        else:
            self._attach_musetalk_preview_to_host("dock")
            self.preview_dock.show()
            self.preview_dock.raise_()
        self.embedded_musetalk_preview.show()
        if hasattr(self.embedded_musetalk_preview, "set_focus_mode"):
            self.embedded_musetalk_preview.set_focus_mode(bool(self._musetalk_avatar_focus_active))
        if self.active_tutorial_overlay is not None:
            try:
                self.active_tutorial_overlay.raise_()
                self.active_tutorial_overlay.panel.raise_()
            except Exception:
                pass
        print("[QtGUI] MuseTalk preview dock shown.")

    def enter_musetalk_avatar_focus(self):
        if self.engine_combo.currentText() != "MuseTalk":
            return
        self._musetalk_avatar_focus_active = True
        self._musetalk_main_window_was_maximized = bool(self.isMaximized())
        self._musetalk_main_window_was_fullscreen = bool(self.isFullScreen())
        if hasattr(self, "btn_musetalk_avatar_focus"):
            self.btn_musetalk_avatar_focus.setText("Exit Avatar Focus")
        if hasattr(self, "embedded_musetalk_preview"):
            self.embedded_musetalk_preview.set_focus_mode(True)
        self._attach_musetalk_preview_to_host("stage")
        if hasattr(self, "preview_dock"):
            self.preview_dock.hide()
        stage_window = self._ensure_musetalk_stage_window()
        self._sync_musetalk_stage_window_geometry_from_preview()
        stage_window.show()
        stage_window.raise_()
        stage_window.activateWindow()
        self.hide()
        print("[QtGUI] MuseTalk avatar focus entered.")

    def exit_musetalk_avatar_focus(self, *, raise_main=False):
        was_active = bool(self._musetalk_avatar_focus_active)
        self._musetalk_avatar_focus_active = False
        if hasattr(self, "btn_musetalk_avatar_focus"):
            self.btn_musetalk_avatar_focus.setText("Avatar Focus")
        if hasattr(self, "embedded_musetalk_preview"):
            self.embedded_musetalk_preview.set_focus_mode(False)
        self._attach_musetalk_preview_to_host("dock")
        if hasattr(self, "_musetalk_stage_window") and self._musetalk_stage_window is not None:
            self._musetalk_stage_window.allow_internal_close(True)
            self._musetalk_stage_window.hide()
            self._musetalk_stage_window.allow_internal_close(False)
        if hasattr(self, "preview_dock"):
            self.preview_dock.show()
        if hasattr(self, "visual_reply_dock"):
            try:
                self.tabifyDockWidget(self.preview_dock, self.visual_reply_dock)
            except Exception:
                pass
        if raise_main or was_active or not self.isVisible():
            if self._musetalk_main_window_was_fullscreen:
                self.showFullScreen()
            elif self._musetalk_main_window_was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self.raise_()
            self.activateWindow()
        if was_active:
            print("[QtGUI] MuseTalk avatar focus exited.")

    def toggle_musetalk_avatar_focus(self):
        if self._musetalk_avatar_focus_active:
            self.exit_musetalk_avatar_focus(raise_main=True)
        else:
            self.enter_musetalk_avatar_focus()

    def show_main_interface_from_musetalk_focus(self):
        self.exit_musetalk_avatar_focus(raise_main=True)

    def stop_musetalk_preview(self):
        self.exit_musetalk_avatar_focus(raise_main=False)
        if hasattr(self, "preview_dock"):
            self.preview_dock.hide()
        if hasattr(self, "_musetalk_stage_window") and self._musetalk_stage_window is not None:
            self._musetalk_stage_window.allow_internal_close(True)
            self._musetalk_stage_window.hide()
            self._musetalk_stage_window.allow_internal_close(False)
        if hasattr(self, "embedded_musetalk_preview"):
            self.embedded_musetalk_preview.reset_preview()

    def show_visual_reply_dock(self):
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
        shared_state.set_current_visual_reply_data(
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
        shared_state.set_current_visual_reply_data(
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
            shared_state.set_current_visual_reply_data(
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
            shared_state.update_current_visual_reply_data(caption=str(caption or ""))
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

    def start_engine(self, offline_replay_only=False):
        if self.thread and self.thread.is_alive():
            return
        self._publish_addon_event("runtime.heavy_task_starting", {"source": "engine_start"})
        mode = self.engine_combo.currentText().lower()
        update_runtime_config("avatar_mode", mode)
        self.apply_text_config()
        config = {
            "active_preset_name": str(RUNTIME_CONFIG.get("active_preset_name", "") or ""),
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}),
            "chat_provider_generation_settings": dict(RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {}),
            "model_name": self.model_combo.currentText(),
            "system_prompt": self.system_prompt_text.toPlainText().strip(),
            "temperature": self.brain_sliders["temperature"].value(),
            "top_p": self.brain_sliders["top_p"].value(),
            "top_k": int(self.brain_sliders["top_k"].value()),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value(),
            "min_p": self.brain_sliders["min_p"].value(),
            "limit_response_length": self.limit_response_checkbox.isChecked(),
            "max_response_tokens": int(self.max_response_tokens_spin.value()),
            "avatar_mode": mode,
            "input_mode": "push_to_talk" if self.input_mode_combo.currentText() == "Push-to-Talk" else "voice_activation",
            "input_message_role": self._input_role_value_from_label(self.input_role_combo.currentText()),
            "stream_mode": self.stream_mode_combo.currentText() == "On",
            "offline_replay_only": bool(offline_replay_only),
            "tts_backend": self._current_tts_backend_value(),
            "musetalk_avatar_pack_id": str(self.musetalk_avatar_pack_combo.currentData() or RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or ""),
            "musetalk_vram_mode": next(
                (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self.musetalk_vram_combo.currentText()),
                "quality",
            ),
            "vam_vmc_enabled": self.vam_vmc_enabled_checkbox.isChecked() if hasattr(self, "vam_vmc_enabled_checkbox") else bool(RUNTIME_CONFIG.get("vam_vmc_enabled", True)),
            "vam_vmc_host": self.vam_vmc_host_edit.text().strip() if hasattr(self, "vam_vmc_host_edit") else str(RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1"),
            "vam_vmc_port": int(self.vam_vmc_port_spin.value()) if hasattr(self, "vam_vmc_port_spin") else int(RUNTIME_CONFIG.get("vam_vmc_port", 39539) or 39539),
            "vam_bridge_enabled": self.vam_bridge_enabled_checkbox.isChecked() if hasattr(self, "vam_bridge_enabled_checkbox") else bool(RUNTIME_CONFIG.get("vam_bridge_enabled", True)),
            "vam_root": self._current_vam_root_value() if hasattr(self, "vam_root_edit") else str(RUNTIME_CONFIG.get("vam_root", getattr(engine, "DEFAULT_VAM_ROOT", "")) or getattr(engine, "DEFAULT_VAM_ROOT", "")),
            "vam_bridge_root": self._current_vam_bridge_root_value() if hasattr(self, "vam_bridge_root_edit") else str(RUNTIME_CONFIG.get("vam_bridge_root", getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")) or getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")),
            "vam_play_audio_in_vam": True if mode == "vam" else (self.vam_play_audio_in_vam_checkbox.isChecked() if hasattr(self, "vam_play_audio_in_vam_checkbox") else bool(RUNTIME_CONFIG.get("vam_play_audio_in_vam", False))),
            "vam_target_atom_uid": self.vam_target_atom_uid_edit.text().strip() if hasattr(self, "vam_target_atom_uid_edit") else str(RUNTIME_CONFIG.get("vam_target_atom_uid", "Person") or "Person"),
            "vam_target_storable_id": self.vam_target_storable_id_edit.text().strip() if hasattr(self, "vam_target_storable_id_edit") else str(RUNTIME_CONFIG.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"),
            "vam_timeline_auto_resume": self.vam_timeline_auto_resume_checkbox.isChecked() if hasattr(self, "vam_timeline_auto_resume_checkbox") else bool(RUNTIME_CONFIG.get("vam_timeline_auto_resume", True)),
            "pocket_tts_python": (
                self._ensure_pocket_tts_python_path()
                if self._current_tts_backend_value() == "pockettts" and hasattr(self, "pocket_tts_python_edit")
                else (self.pocket_tts_python_edit.text().strip() if hasattr(self, "pocket_tts_python_edit") else str(RUNTIME_CONFIG.get("pocket_tts_python", "") or ""))
            ),
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {}) or {}),
        }
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        if mode == "musetalk":
            self.show_musetalk_preview()
        self.thread = threading.Thread(target=self._run_engine_thread, args=(config,), daemon=True)
        self.thread.start()
        self.emit_tutorial_event("engine_start_requested", {"avatar_mode": mode, "tts_backend": config.get("tts_backend", "")})
        self._update_restart_sensitive_controls()
        self._update_control_action_buttons()
        self._update_push_to_talk_button()

    def _run_engine_thread(self, config):
        try:
            run_companion(config)
        except Exception as exc:
            print(f"CRITICAL ERROR: {exc}")
        finally:
            if self._closing:
                return
            try:
                QtCore.QMetaObject.invokeMethod(self, "reset_ui", QtCore.Qt.QueuedConnection)
            except RuntimeError:
                pass

    @QtCore.Slot()
    def reset_ui(self):
        if self._closing:
            return
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.emit_tutorial_event("engine_stopped", self.get_tutorial_runtime_state())
        self._update_restart_sensitive_controls()
        self._update_control_action_buttons()
        self._update_push_to_talk_button()
        print("[QtGUI] System Halted.")

    def stop_engine(self):
        print("[QtGUI] Stopping...")
        stop_flag.set()
        shutdown_avatar_engine()
        self.btn_stop.setEnabled(False)
        self.emit_tutorial_event("engine_stop_requested", self.get_tutorial_runtime_state())
        self._update_restart_sensitive_controls()
        self._update_control_action_buttons()
        self._update_push_to_talk_button()

    def reset_chat_session(self):
        reset_session_state()
        self.clear_chat()
        print("[QtGUI] Chat memory reset.")

    def _default_chat_context_path(self):
        chat_dir = Path("runtime") / "chat_contexts"
        chat_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
        return chat_dir / f"chat_context_{stamp}.json"

    def _quick_chat_context_path(self):
        runtime_dir = Path("runtime")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir / "chat_context_quick_save.json"

    def _chat_label_for_entry(self, entry):
        role = str((entry or {}).get("role", "") or "").strip().lower()
        origin = str((entry or {}).get("origin", "") or "").strip().lower()
        if role == "assistant" and origin != "assistant_reply":
            return "💬 You (assistant):"
        if role == "assistant":
            return "🤖 Assistant:"
        if role == "system":
            return "💬 You (system):"
        return "💬 You:"

    def _chat_entry_specs(self):
        return [
            ("💬 You (system):", {"role": "system", "origin": "input"}),
            ("💬 You (assistant):", {"role": "assistant", "origin": "input"}),
            ("🤖 Assistant:", {"role": "assistant", "origin": "assistant_reply"}),
            ("💬 You:", {"role": "user", "origin": "input"}),
        ]

    def _parse_chat_display_entries_with_spans(self, raw_text):
        entries = []
        current_entry = None
        current_lines = []
        current_start = 0
        raw = str(raw_text or "")
        offset = 0

        def _flush(end_offset):
            nonlocal current_entry, current_lines, current_start
            if current_entry is None:
                return
            content = "\n".join(current_lines).strip()
            if content:
                entry = dict(current_entry)
                entry["content"] = content
                entry["_start"] = int(current_start)
                entry["_end"] = int(end_offset)
                entries.append(entry)
            current_entry = None
            current_lines = []
            current_start = 0

        for segment in raw.splitlines(keepends=True):
            line = segment.rstrip("\r\n")
            matched = None
            for label, template in self._chat_entry_specs():
                if line.startswith(label):
                    matched = (label, template)
                    break
            if matched is not None:
                _flush(offset)
                label, template = matched
                current_entry = dict(template)
                current_lines = [line[len(label):].lstrip()]
                current_start = offset
            elif current_entry is not None:
                current_lines.append(line)
            offset += len(segment)

        _flush(len(raw))
        return entries

    def _assistant_replay_index_for_chat_position(self, position):
        entries = self._parse_chat_display_entries_with_spans(self.chat_edit.toPlainText())
        replay_index = 0
        total_entries = len(entries)
        for idx, entry in enumerate(entries):
            is_replayable = (
                str(entry.get("role", "") or "") == "assistant"
                and str(entry.get("origin", "") or "") == "assistant_reply"
            )
            if is_replayable:
                replay_index += 1
            start = int(entry.get("_start", 0) or 0)
            end = int(entry.get("_end", start) or start)
            in_entry = start <= position < end
            if not in_entry and idx == total_entries - 1:
                in_entry = start <= position <= end
            if in_entry:
                return replay_index if is_replayable else None
        return None

    def _show_chat_context_menu(self, point):
        menu = self.chat_edit.createStandardContextMenu()
        if not getattr(self, "chat_edit_mode", False):
            cursor = self.chat_edit.cursorForPosition(point)
            replay_index = self._assistant_replay_index_for_chat_position(cursor.position())
            if replay_index is not None:
                menu.addSeparator()
                replay_action = menu.addAction(f"Start Playing From This Message (#{replay_index})")
                replay_action.triggered.connect(lambda _checked=False, idx=replay_index: self.trigger_replay_from_assistant_index(idx))
        menu.exec(self.chat_edit.viewport().mapToGlobal(point))

    def _set_chat_edit_mode(self, enabled):
        self.chat_edit_mode = bool(enabled)
        if hasattr(self, "chat_edit"):
            self.chat_edit.setReadOnly(not self.chat_edit_mode)
        if hasattr(self, "chat_edit_mode_button"):
            self.chat_edit_mode_button.setVisible(not self.chat_edit_mode)
        if hasattr(self, "chat_apply_edit_button"):
            self.chat_apply_edit_button.setVisible(self.chat_edit_mode)
        if hasattr(self, "chat_cancel_edit_button"):
            self.chat_cancel_edit_button.setVisible(self.chat_edit_mode)
        self._update_chat_status(self._console_redirect.chat_line_count, int(self.chat_auto_scroll))

    def enter_chat_edit_mode(self):
        if getattr(self, "chat_edit_mode", False):
            return
        scroll_state = self._capture_vertical_scroll_state(self.chat_edit)
        current_font = QtGui.QFont(self.chat_edit.font())
        self._chat_edit_snapshot_text = self.chat_edit.toPlainText()
        self.chat_edit.setPlainText(self._chat_edit_snapshot_text)
        self.chat_edit.setFont(current_font)
        self.chat_edit.setCurrentFont(current_font)
        self._set_chat_edit_mode(True)
        self._restore_vertical_scroll_state(self.chat_edit, scroll_state)
        QtCore.QTimer.singleShot(0, lambda state=scroll_state: self._restore_vertical_scroll_state(self.chat_edit, state))
        print("[QtGUI] Chat edit mode enabled.")

    def cancel_chat_edit_mode(self):
        if not getattr(self, "chat_edit_mode", False):
            return
        scroll_state = self._capture_vertical_scroll_state(self.chat_edit)
        self._set_chat_edit_mode(False)
        self._rebuild_chat_view_from_history(force=True, preserve_scroll_state=scroll_state)
        print("[QtGUI] Chat edit mode cancelled.")

    def _parse_chat_edit_text(self, raw_text):
        entries = []
        current_entry = None
        current_lines = []
        specs = self._chat_entry_specs()
        for line_no, line in enumerate(str(raw_text or "").splitlines(), start=1):
            matched = None
            for label, template in specs:
                if line.startswith(label):
                    matched = (label, template)
                    break
            if matched is not None:
                if current_entry is not None:
                    content = "\n".join(current_lines).strip()
                    if content:
                        entry = dict(current_entry)
                        entry["content"] = content
                        entries.append(entry)
                label, template = matched
                current_entry = dict(template)
                current_lines = [line[len(label):].lstrip()]
                continue
            if current_entry is None:
                if not line.strip():
                    continue
                raise ValueError(f"Line {line_no} must start with a chat speaker label.")
            current_lines.append(line)
        if current_entry is not None:
            content = "\n".join(current_lines).strip()
            if content:
                entry = dict(current_entry)
                entry["content"] = content
                entries.append(entry)
        return entries

    def apply_chat_edit_mode(self):
        if not getattr(self, "chat_edit_mode", False):
            return
        scroll_state = self._capture_vertical_scroll_state(self.chat_edit)
        try:
            entries = self._parse_chat_edit_text(self.chat_edit.toPlainText())
            result = replace_chat_conversation_history(entries, allow_pending_loaded_user=False)
        except Exception as exc:
            print(f"[QtGUI] Chat edit apply failed: {exc}")
            return
        self._set_chat_edit_mode(False)
        self._rebuild_chat_view_from_history(force=True, preserve_scroll_state=scroll_state)
        print(f"[QtGUI] Chat context edited in place ({int(result.get('conversation_turns', 0))} turn(s)).")

    def _rebuild_chat_view_from_history(self, force=False, preserve_scroll_state=None):
        if getattr(self, "chat_edit_mode", False) and not force:
            return
        entries = list(getattr(engine, "conversation_history", []) or [])
        lines = []
        for entry in entries:
            content = str((entry or {}).get("content", "") or "").strip()
            attachment_image_path = str((entry or {}).get("attachment_image_path", "") or "").strip()
            if not content and not attachment_image_path:
                continue
            if attachment_image_path:
                content = (content or "Please respond to the image I just sent you.") + " [Image attached]"
            lines.append(f"{self._chat_label_for_entry(entry)} {content}")
        self.chat_edit.clear()
        if lines:
            self._append_chat_text("\n".join(lines))
        self._console_redirect.chat_line_count = len(lines)
        self._update_chat_status(len(lines), int(self.chat_auto_scroll))
        self._update_control_action_buttons()
        if preserve_scroll_state is not None:
            QtCore.QTimer.singleShot(0, lambda state=preserve_scroll_state, widget=self.chat_edit: self._restore_vertical_scroll_state(widget, state))
        if self.chat_auto_scroll:
            QtCore.QTimer.singleShot(0, lambda w=self.chat_edit: self._force_scroll_to_bottom(w))

    def save_chat_context(self):
        default_path = self._default_chat_context_path()
        path, _ = QtDialogService(self).save_file(
            "Save Chat Context",
            str(default_path),
            "Chat Context (*.json);;JSON (*.json);;All Files (*.*)",
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        payload = export_chat_session_state()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[QtGUI] Chat context saved: {target}")

    def quick_save_chat_context(self):
        target = self._quick_chat_context_path()
        payload = export_chat_session_state()
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[QtGUI] Quick chat context saved: {target}")

    def load_chat_context(self):
        path, _ = QtDialogService(self).open_file(
            "Load Chat Context",
            str(Path("runtime") / "chat_contexts"),
            "Chat Context (*.json);;JSON (*.json);;All Files (*.*)",
        )
        if not path:
            return
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        result = import_chat_session_state(payload)
        self._set_chat_edit_mode(False)
        self._rebuild_chat_view_from_history(force=True)
        print(f"[QtGUI] Chat context loaded: {path} ({int(result.get('conversation_turns', 0))} turn(s))")

    def quick_load_chat_context(self):
        path = self._quick_chat_context_path()
        if not path.exists():
            print(f"[QtGUI] Quick chat context not found: {path}")
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = import_chat_session_state(payload)
        self._set_chat_edit_mode(False)
        self._rebuild_chat_view_from_history(force=True)
        print(f"[QtGUI] Quick chat context loaded: {path} ({int(result.get('conversation_turns', 0))} turn(s))")

    def save_session(self):
        if bool(getattr(self, "_suspend_session_save", False)):
            return
        session = {
            "first_run": bool(self.first_run),
            "avatar_mode": self.engine_combo.currentText(),
            "voice_file": self.voice_combo.currentText() if hasattr(self, "voice_combo") else "",
            "input_mode": self.input_mode_combo.currentText(),
            "input_message_role": self.input_role_combo.currentText(),
            "push_to_talk_hotkey": engine.get_push_to_talk_hotkey(),
            "manual_action_hotkeys": dict(engine.get_manual_action_hotkeys()),
            "ui_action_hotkeys": dict(engine.get_ui_action_hotkeys()),
            "stream_mode": self.stream_mode_combo.currentText(),
            "tts_backend": self._current_tts_backend_value(),
            "tts_seed": int(self.tts_seed_spin.value()) if hasattr(self, "tts_seed_spin") else int(RUNTIME_CONFIG.get("tts_seed", 0) or 0),
            "tts_temperature": float(self.tts_temperature_spin.value()) if hasattr(self, "tts_temperature_spin") else float(RUNTIME_CONFIG.get("tts_temperature", 0.8) or 0.8),
            "tts_top_p": float(self.tts_top_p_spin.value()) if hasattr(self, "tts_top_p_spin") else float(RUNTIME_CONFIG.get("tts_top_p", 0.9) or 0.9),
            "tts_top_k": int(self.tts_top_k_spin.value()) if hasattr(self, "tts_top_k_spin") else int(RUNTIME_CONFIG.get("tts_top_k", 40) or 40),
            "tts_repeat_penalty": float(self.tts_repeat_penalty_spin.value()) if hasattr(self, "tts_repeat_penalty_spin") else float(RUNTIME_CONFIG.get("tts_repeat_penalty", 1.2) or 1.2),
            "tts_min_p": float(self.tts_min_p_spin.value()) if hasattr(self, "tts_min_p_spin") else float(RUNTIME_CONFIG.get("tts_min_p", 0.0) or 0.0),
            "tts_normalize_loudness": self.tts_normalize_loudness_checkbox.isChecked() if hasattr(self, "tts_normalize_loudness_checkbox") else bool(RUNTIME_CONFIG.get("tts_normalize_loudness", False)),
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}),
            "chat_provider_generation_settings": dict(RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {}),
            "chat_font_size": int(self.chat_font_size_combo.currentData() or 12) if hasattr(self, "chat_font_size_combo") else 12,
            "chat_runtime_expanded": self.chat_runtime_section.isExpanded() if hasattr(self, "chat_runtime_section") else True,
            "tts_runtime_expanded": self.tts_runtime_section.isExpanded() if hasattr(self, "tts_runtime_section") else True,
            "model_name": self.model_combo.currentText() if hasattr(self, "model_combo") else str(RUNTIME_CONFIG.get("model_name", "") or ""),
            "model_requires_vision": self.model_requires_vision_checkbox.isChecked() if hasattr(self, "model_requires_vision_checkbox") else False,
            "allow_proactive_replies": self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else True,
            "require_first_user_before_proactive": self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False,
            "listen_idle_window_seconds": float(self.listen_idle_window_spin.value()) if hasattr(self, "listen_idle_window_spin") else 5.0,
            "proactive_delay_seconds": float(self.proactive_delay_spin.value()) if hasattr(self, "proactive_delay_spin") else 10.0,
            "chat_context_window_messages": int(self.chat_context_window_spin.value()) if hasattr(self, "chat_context_window_spin") else 20,
            "stored_chat_history_limit": int(self.stored_chat_history_limit_spin.value()) if hasattr(self, "stored_chat_history_limit_spin") else 0,
            "chat_context_overflow_policy": self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window",
            "limit_response_length": self.limit_response_checkbox.isChecked() if hasattr(self, "limit_response_checkbox") else False,
            "max_response_tokens": int(self.max_response_tokens_spin.value()) if hasattr(self, "max_response_tokens_spin") else DEFAULT_MAX_RESPONSE_TOKENS,
            "musetalk_vram_mode": next(
                (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self.musetalk_vram_combo.currentText()),
                "quality",
            ),
            "musetalk_loop_fade_ms": int(self.musetalk_loop_fade_spin.value()) if hasattr(self, "musetalk_loop_fade_spin") else int(RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS),
            "musetalk_avatar_pack_id": str(self.musetalk_avatar_pack_combo.currentData() or RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or ""),
            "vam_vmc_enabled": self.vam_vmc_enabled_checkbox.isChecked() if hasattr(self, "vam_vmc_enabled_checkbox") else bool(RUNTIME_CONFIG.get("vam_vmc_enabled", True)),
            "vam_vmc_host": self.vam_vmc_host_edit.text().strip() if hasattr(self, "vam_vmc_host_edit") else str(RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1"),
            "vam_vmc_port": int(self.vam_vmc_port_spin.value()) if hasattr(self, "vam_vmc_port_spin") else int(RUNTIME_CONFIG.get("vam_vmc_port", 39539) or 39539),
            "vam_bridge_enabled": self.vam_bridge_enabled_checkbox.isChecked() if hasattr(self, "vam_bridge_enabled_checkbox") else bool(RUNTIME_CONFIG.get("vam_bridge_enabled", True)),
            "vam_root": self._current_vam_root_value() if hasattr(self, "vam_root_edit") else str(RUNTIME_CONFIG.get("vam_root", getattr(engine, "DEFAULT_VAM_ROOT", "")) or getattr(engine, "DEFAULT_VAM_ROOT", "")),
            "vam_bridge_root": self._current_vam_bridge_root_value() if hasattr(self, "vam_bridge_root_edit") else str(RUNTIME_CONFIG.get("vam_bridge_root", getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")) or getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")),
            "vam_play_audio_in_vam": self.vam_play_audio_in_vam_checkbox.isChecked() if hasattr(self, "vam_play_audio_in_vam_checkbox") else bool(RUNTIME_CONFIG.get("vam_play_audio_in_vam", False)),
            "vam_target_atom_uid": self.vam_target_atom_uid_edit.text().strip() if hasattr(self, "vam_target_atom_uid_edit") else str(RUNTIME_CONFIG.get("vam_target_atom_uid", "Person") or "Person"),
            "vam_target_storable_id": self.vam_target_storable_id_edit.text().strip() if hasattr(self, "vam_target_storable_id_edit") else str(RUNTIME_CONFIG.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"),
            "vam_timeline_auto_resume": self.vam_timeline_auto_resume_checkbox.isChecked() if hasattr(self, "vam_timeline_auto_resume_checkbox") else bool(RUNTIME_CONFIG.get("vam_timeline_auto_resume", True)),
            "visual_reply_mode": self._visual_reply_mode_value_from_label(self.visual_reply_mode_combo.currentText()) if hasattr(self, "visual_reply_mode_combo") else str(RUNTIME_CONFIG.get("visual_reply_mode", "auto") or "auto"),
            "visual_reply_provider": self._visual_reply_provider_value_from_label(self.visual_reply_provider_combo.currentText()) if hasattr(self, "visual_reply_provider_combo") else str(RUNTIME_CONFIG.get("visual_reply_provider", "openai") or "openai"),
            "visual_reply_size": self._normalize_visual_reply_size(self.visual_reply_size_combo.currentText()) if hasattr(self, "visual_reply_size_combo") else str(RUNTIME_CONFIG.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "visual_reply_model": self.visual_reply_model_edit.text().strip() if hasattr(self, "visual_reply_model_edit") else str(RUNTIME_CONFIG.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "visual_reply_auto_show_dock": self.visual_reply_auto_show_checkbox.isChecked() if hasattr(self, "visual_reply_auto_show_checkbox") else bool(RUNTIME_CONFIG.get("visual_reply_auto_show_dock", True)),
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {}) or {}),
            "performance_profile": self.performance_profile_combo.currentData() if hasattr(self, "performance_profile_combo") else "",
            "pocket_tts_python": (
                self._ensure_pocket_tts_python_path()
                if self._current_tts_backend_value() == "pockettts" and hasattr(self, "pocket_tts_python_edit")
                else (self.pocket_tts_python_edit.text().strip() if hasattr(self, "pocket_tts_python_edit") else str(RUNTIME_CONFIG.get("pocket_tts_python", "") or ""))
            ),
            "emotional_instructions": self.emotional_text.toPlainText().strip() if hasattr(self, "emotional_text") else str(RUNTIME_CONFIG.get("emotional_instructions", "") or ""),
            "system_prompt": self.system_prompt_text.toPlainText().strip() if hasattr(self, "system_prompt_text") else str(RUNTIME_CONFIG.get("system_prompt", "") or ""),
            "temperature": self.brain_sliders["temperature"].value() if "temperature" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("temperature", 1.22) or 1.22),
            "top_p": self.brain_sliders["top_p"].value() if "top_p" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("top_p", 0.9) or 0.9),
            "top_k": int(self.brain_sliders["top_k"].value()) if "top_k" in getattr(self, "brain_sliders", {}) else int(RUNTIME_CONFIG.get("top_k", 40) or 40),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value() if "repeat_penalty" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("repeat_penalty", 1.15) or 1.15),
            "min_p": self.brain_sliders["min_p"].value() if "min_p" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("min_p", 0.05) or 0.05),
            "chunking": {key: slider.value() for key, slider in self.chunking_sliders.items()},
            "dry_run_target_samples": self.dry_run_target_spin.value(),
            "dry_run_auto_replies": self.dry_run_auto_replies_checkbox.isChecked(),
            "last_preset": self.preset_combo.currentText(),
            "last_body": self.body_combo.currentText(),
            "live_sync": self.live_sync_checkbox.isChecked(),
            "geometry": [self.x(), self.y(), self.width(), self.height()],
            "main_splitter_sizes": self.main_splitter.sizes() if hasattr(self, "main_splitter") else [400, 980],
            "preview_visible": bool(hasattr(self, "preview_dock") and self.preview_dock.isVisible()),
            "visual_reply_visible": bool(hasattr(self, "visual_reply_dock") and self.visual_reply_dock.isVisible()),
            "performance_guidance_visible": bool(hasattr(self, "guidance_box") and self.guidance_box.isVisible()),
            "window_state": base64.b64encode(self.saveState().data()).decode("ascii"),
            "right_dock_state": (
                base64.b64encode(self.right_dock_host.saveState().data()).decode("ascii")
                if hasattr(self, "right_dock_host")
                else ""
            ),
        }
        if self._addon_manager is not None:
            session.update(self._addon_manager.export_session_state())
        SESSION_PATH.write_text(json.dumps(session, indent=4), encoding="utf-8")

    def _ensure_window_on_screen(self):
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        client = self.geometry()
        width = min(max(client.width(), 200), max(available.width(), 200))
        height = min(max(client.height(), 200), max(available.height(), 200))
        x = frame.x()
        y = frame.y()
        if x < available.left():
            x = available.left()
        if y < available.top():
            y = available.top()
        if x + width > available.right() + 1:
            x = max(available.left(), available.right() - width + 1)
        if y + height > available.bottom() + 1:
            y = max(available.top(), available.bottom() - height + 1)
        self.setGeometry(x, y, width, height)
        self.move(x, y)

    def restore_session(self):
        if not SESSION_PATH.exists():
            return
        try:
            session = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[QtGUI] Session Restore Failed: {exc}")
            return
        previous_suspend = bool(getattr(self, "_suspend_session_save", False))
        self._suspend_session_save = True
        self._restoring_session = True
        try:
            self.first_run = bool(session.get("first_run", True))
            geometry = session.get("geometry")
            if geometry and len(geometry) == 4:
                self.setGeometry(*geometry)
                self._ensure_window_on_screen()
            preset = session.get("last_preset")
            if preset:
                index = self.preset_combo.findText(preset)
                if index >= 0:
                    self.preset_combo.setCurrentIndex(index)
                    update_runtime_config("active_preset_name", preset)

            engine_choice = session.get("avatar_mode")
            if isinstance(engine_choice, str) and engine_choice.strip().lower() == "lam":
                engine_choice = "MuseTalk"
            if engine_choice:
                index = self.engine_combo.findText(engine_choice)
                if index >= 0:
                    self.engine_combo.setCurrentIndex(index)
            if str(engine_choice or "").strip().lower() == "vam" and hasattr(self, "vam_play_audio_in_vam_checkbox"):
                self.vam_play_audio_in_vam_checkbox.setChecked(True)
                self.on_vam_play_audio_in_vam_changed(True)
            input_mode = session.get("input_mode")
            if input_mode:
                index = self.input_mode_combo.findText(input_mode)
                if index >= 0:
                    self.input_mode_combo.setCurrentIndex(index)
            voice_file = str(session.get("voice_file", "") or "").strip()
            if voice_file and hasattr(self, "voice_combo"):
                index = self.voice_combo.findText(voice_file)
                if index >= 0:
                    self.voice_combo.blockSignals(True)
                    try:
                        self.voice_combo.setCurrentIndex(index)
                    finally:
                        self.voice_combo.blockSignals(False)
                    update_runtime_config("voice_path", os.path.join("voices", voice_file))
            push_to_talk_hotkey = session.get("push_to_talk_hotkey")
            if push_to_talk_hotkey is not None:
                engine.set_push_to_talk_hotkey(push_to_talk_hotkey)
            manual_action_hotkeys = session.get("manual_action_hotkeys")
            if manual_action_hotkeys is not None:
                update_runtime_config("manual_action_hotkeys", manual_action_hotkeys)
            ui_action_hotkeys = session.get("ui_action_hotkeys")
            if ui_action_hotkeys is not None:
                update_runtime_config("ui_action_hotkeys", ui_action_hotkeys)
            input_role = session.get("input_message_role")
            if input_role:
                index = self.input_role_combo.findText(input_role)
                if index >= 0:
                    self.input_role_combo.setCurrentIndex(index)
            stream_mode = session.get("stream_mode")
            if stream_mode is not None:
                if isinstance(stream_mode, str):
                    index = self.stream_mode_combo.findText(stream_mode)
                    if index >= 0:
                        self.stream_mode_combo.setCurrentIndex(index)
                else:
                    self.stream_mode_combo.setCurrentText("On" if bool(stream_mode) else "Off")
            tts_backend = session.get("tts_backend")
            if tts_backend:
                desired_backend = str(tts_backend or "").strip().lower()
                self._populate_tts_backend_combo(selected_value=desired_backend)
                index = self.tts_backend_combo.findData(desired_backend)
                if index >= 0:
                    self.tts_backend_combo.setCurrentIndex(index)
                self.on_tts_backend_change(self.tts_backend_combo.currentText())
            tts_seed = session.get("tts_seed")
            if tts_seed is not None and hasattr(self, "tts_seed_spin"):
                self.tts_seed_spin.setValue(max(0, int(tts_seed)))
                self.on_tts_seed_changed(self.tts_seed_spin.value())
            tts_temperature = session.get("tts_temperature")
            if tts_temperature is not None and hasattr(self, "tts_temperature_spin"):
                self.tts_temperature_spin.setValue(max(0.05, float(tts_temperature)))
                self.on_tts_temperature_changed(self.tts_temperature_spin.value())
            tts_top_p = session.get("tts_top_p")
            if tts_top_p is not None and hasattr(self, "tts_top_p_spin"):
                self.tts_top_p_spin.setValue(max(0.0, min(1.0, float(tts_top_p))))
                self.on_tts_top_p_changed(self.tts_top_p_spin.value())
            tts_top_k = session.get("tts_top_k")
            if tts_top_k is not None and hasattr(self, "tts_top_k_spin"):
                self.tts_top_k_spin.setValue(max(0, int(tts_top_k)))
                self.on_tts_top_k_changed(self.tts_top_k_spin.value())
            tts_repeat_penalty = session.get("tts_repeat_penalty")
            if tts_repeat_penalty is not None and hasattr(self, "tts_repeat_penalty_spin"):
                self.tts_repeat_penalty_spin.setValue(max(1.0, float(tts_repeat_penalty)))
                self.on_tts_repeat_penalty_changed(self.tts_repeat_penalty_spin.value())
            tts_min_p = session.get("tts_min_p")
            if tts_min_p is not None and hasattr(self, "tts_min_p_spin"):
                self.tts_min_p_spin.setValue(max(0.0, min(1.0, float(tts_min_p))))
                self.on_tts_min_p_changed(self.tts_min_p_spin.value())
            tts_normalize_loudness = session.get("tts_normalize_loudness")
            if tts_normalize_loudness is not None and hasattr(self, "tts_normalize_loudness_checkbox"):
                self.tts_normalize_loudness_checkbox.setChecked(bool(tts_normalize_loudness))
                self.on_tts_normalize_loudness_changed(bool(tts_normalize_loudness))
            vam_vmc_enabled = session.get("vam_vmc_enabled")
            if vam_vmc_enabled is not None and hasattr(self, "vam_vmc_enabled_checkbox"):
                self.vam_vmc_enabled_checkbox.setChecked(bool(vam_vmc_enabled))
                self.on_vam_vmc_enabled_changed(bool(vam_vmc_enabled))
            vam_bridge_enabled = session.get("vam_bridge_enabled")
            if vam_bridge_enabled is not None and hasattr(self, "vam_bridge_enabled_checkbox"):
                self.vam_bridge_enabled_checkbox.setChecked(bool(vam_bridge_enabled))
                self.on_vam_bridge_enabled_changed(bool(vam_bridge_enabled))
            vam_play_audio_in_vam = session.get("vam_play_audio_in_vam")
            if vam_play_audio_in_vam is not None and hasattr(self, "vam_play_audio_in_vam_checkbox"):
                self.vam_play_audio_in_vam_checkbox.setChecked(bool(vam_play_audio_in_vam))
                self.on_vam_play_audio_in_vam_changed(bool(vam_play_audio_in_vam))
            vam_timeline_auto_resume = session.get("vam_timeline_auto_resume")
            if vam_timeline_auto_resume is not None and hasattr(self, "vam_timeline_auto_resume_checkbox"):
                self.vam_timeline_auto_resume_checkbox.setChecked(bool(vam_timeline_auto_resume))
                self.on_vam_timeline_auto_resume_changed(bool(vam_timeline_auto_resume))
            vam_vmc_host = session.get("vam_vmc_host")
            if vam_vmc_host and hasattr(self, "vam_vmc_host_edit"):
                self.vam_vmc_host_edit.setText(str(vam_vmc_host))
                self.on_vam_vmc_host_changed()
            vam_vmc_port = session.get("vam_vmc_port")
            if vam_vmc_port is not None and hasattr(self, "vam_vmc_port_spin"):
                self.vam_vmc_port_spin.setValue(int(vam_vmc_port))
                self.on_vam_vmc_port_changed(int(vam_vmc_port))
            vam_root = session.get("vam_root") or session.get("vam_bridge_root")
            if vam_root and hasattr(self, "vam_root_edit"):
                self.vam_root_edit.setText(engine.normalize_vam_root(vam_root))
                self.on_vam_root_changed()
            vam_target_atom_uid = session.get("vam_target_atom_uid")
            if vam_target_atom_uid and hasattr(self, "vam_target_atom_uid_edit"):
                self.vam_target_atom_uid_edit.setText(str(vam_target_atom_uid))
                self.on_vam_target_atom_uid_changed()
            vam_target_storable_id = session.get("vam_target_storable_id")
            if vam_target_storable_id and hasattr(self, "vam_target_storable_id_edit"):
                self.vam_target_storable_id_edit.setText(str(vam_target_storable_id))
                self.on_vam_target_storable_id_changed()
            chat_provider = session.get("chat_provider")
            if chat_provider is not None and hasattr(self, "chat_provider_combo"):
                normalized_provider = self._set_chat_provider_selection(chat_provider)
                update_runtime_config("chat_provider", normalized_provider)
            chat_provider_settings = session.get("chat_provider_settings")
            if chat_provider_settings is not None:
                update_runtime_config("chat_provider_settings", chat_provider_settings)
                self._refresh_chat_provider_card()
            chat_provider_generation_settings = session.get("chat_provider_generation_settings")
            if chat_provider_generation_settings is None:
                preset_name = str(session.get("last_preset") or "").strip()
                preset_path = Path("presets") / f"{preset_name}.json" if preset_name else None
                if preset_path is not None and preset_path.exists():
                    try:
                        preset_data = json.loads(preset_path.read_text(encoding="utf-8"))
                        chat_provider_generation_settings = preset_data.get("chat_provider_generation_settings")
                    except Exception:
                        chat_provider_generation_settings = None
            if chat_provider_generation_settings is not None:
                update_runtime_config("chat_provider_generation_settings", chat_provider_generation_settings)
                self._refresh_chat_provider_generation_card()
            chat_font_size = session.get("chat_font_size")
            if chat_font_size is not None and hasattr(self, "chat_font_size_combo"):
                size = max(8, min(20, int(chat_font_size)))
                index = self.chat_font_size_combo.findData(size)
                if index >= 0:
                    self.chat_font_size_combo.setCurrentIndex(index)
                self._apply_chat_font_size(size, update_combo=False)
            if "chat_runtime_expanded" in session and hasattr(self, "chat_runtime_section"):
                self.chat_runtime_section.setExpanded(bool(session.get("chat_runtime_expanded", True)))
            if "tts_runtime_expanded" in session and hasattr(self, "tts_runtime_section"):
                self.tts_runtime_section.setExpanded(bool(session.get("tts_runtime_expanded", True)))
            saved_model_name = str(session.get("model_name") or "").strip()
            if saved_model_name:
                self._pending_restored_model_name = saved_model_name
                update_runtime_config("model_name", saved_model_name)
            self.request_model_list_refresh(quiet=True, wait_for_reachable=False)
            model_requires_vision = session.get("model_requires_vision")
            if model_requires_vision is not None and hasattr(self, "model_requires_vision_checkbox"):
                self.model_requires_vision_checkbox.setChecked(bool(model_requires_vision))
            allow_proactive_replies = session.get("allow_proactive_replies")
            if allow_proactive_replies is not None and hasattr(self, "allow_proactive_checkbox"):
                self.allow_proactive_checkbox.setChecked(bool(allow_proactive_replies))
                self.on_allow_proactive_replies_changed(bool(allow_proactive_replies))
            require_first_user_before_proactive = session.get("require_first_user_before_proactive")
            if require_first_user_before_proactive is not None and hasattr(self, "require_first_user_checkbox"):
                self.require_first_user_checkbox.setChecked(bool(require_first_user_before_proactive))
                self.on_require_first_user_before_proactive_changed(bool(require_first_user_before_proactive))
            listen_idle_window_seconds = session.get("listen_idle_window_seconds")
            if listen_idle_window_seconds is not None and hasattr(self, "listen_idle_window_spin"):
                listen_seconds = max(0.5, float(listen_idle_window_seconds))
                self.listen_idle_window_spin.setValue(listen_seconds)
                self.on_listen_idle_window_changed(listen_seconds)
            proactive_delay_seconds = session.get("proactive_delay_seconds")
            if proactive_delay_seconds is not None and hasattr(self, "proactive_delay_spin"):
                proactive_seconds = max(0.5, float(proactive_delay_seconds))
                self.proactive_delay_spin.setValue(proactive_seconds)
                self.on_proactive_delay_changed(proactive_seconds)
            chat_context_window_messages = session.get("chat_context_window_messages")
            if chat_context_window_messages is not None and hasattr(self, "chat_context_window_spin"):
                context_messages = max(4, int(chat_context_window_messages))
                self.chat_context_window_spin.setValue(context_messages)
                self.on_chat_context_window_changed(context_messages)
            stored_chat_history_limit = session.get("stored_chat_history_limit")
            if stored_chat_history_limit is not None and hasattr(self, "stored_chat_history_limit_spin"):
                stored_limit = max(0, int(stored_chat_history_limit))
                self.stored_chat_history_limit_spin.setValue(stored_limit)
                self.on_stored_chat_history_limit_changed(stored_limit)
            chat_context_overflow_policy = session.get("chat_context_overflow_policy")
            if chat_context_overflow_policy is not None and hasattr(self, "chat_overflow_policy_combo"):
                policy_text = self._chat_overflow_policy_label_from_value(chat_context_overflow_policy)
                self.chat_overflow_policy_combo.setCurrentText(policy_text)
                self.on_chat_overflow_policy_changed(policy_text)
            limit_response_length = session.get("limit_response_length")
            if limit_response_length is not None:
                self.limit_response_checkbox.setChecked(bool(limit_response_length))
                self.on_limit_response_length_changed(bool(limit_response_length))
            max_response_tokens = session.get("max_response_tokens")
            if max_response_tokens is not None:
                tokens = max(32, int(max_response_tokens))
                self.max_response_tokens_spin.setValue(tokens)
                self.on_max_response_tokens_changed(tokens)
            self.refresh_performance_profile_list()
            performance_profile = session.get("performance_profile")
            if performance_profile and hasattr(self, "performance_profile_combo"):
                for index in range(self.performance_profile_combo.count()):
                    if self.performance_profile_combo.itemData(index) == performance_profile:
                        self.performance_profile_combo.setCurrentIndex(index)
                        break
            musetalk_vram_mode = session.get("musetalk_vram_mode")
            if musetalk_vram_mode:
                label = MUSE_VRAM_MODE_LABELS.get(str(musetalk_vram_mode).strip().lower(), None)
                if label:
                    index = self.musetalk_vram_combo.findText(label)
                    if index >= 0:
                        self.musetalk_vram_combo.setCurrentIndex(index)
            musetalk_loop_fade_ms = session.get("musetalk_loop_fade_ms")
            if musetalk_loop_fade_ms is not None and hasattr(self, "musetalk_loop_fade_spin"):
                fade_ms = max(0, int(musetalk_loop_fade_ms))
                self.musetalk_loop_fade_spin.setValue(fade_ms)
                self.on_musetalk_loop_fade_changed(fade_ms)
            visual_reply_mode = session.get("visual_reply_mode")
            if visual_reply_mode is not None and hasattr(self, "visual_reply_mode_combo"):
                mode_text = self._visual_reply_mode_label_from_value(visual_reply_mode)
                self.visual_reply_mode_combo.setCurrentText(mode_text)
                self.on_visual_reply_mode_changed(mode_text)
            visual_reply_provider = session.get("visual_reply_provider")
            if visual_reply_provider is not None and hasattr(self, "visual_reply_provider_combo"):
                provider_text = self._visual_reply_provider_label_from_value(visual_reply_provider)
                self.visual_reply_provider_combo.setCurrentText(provider_text)
                self.on_visual_reply_provider_changed(provider_text)
            visual_reply_size = session.get("visual_reply_size")
            if visual_reply_size is not None and hasattr(self, "visual_reply_size_combo"):
                size_text = self._normalize_visual_reply_size(visual_reply_size)
                self.visual_reply_size_combo.setCurrentText(self._visual_reply_size_label_from_value(size_text))
                self.on_visual_reply_size_changed(size_text)
            visual_reply_model = session.get("visual_reply_model")
            if visual_reply_model is not None and hasattr(self, "visual_reply_model_edit"):
                self.visual_reply_model_edit.setText(str(visual_reply_model or "gpt-image-1"))
                self.on_visual_reply_model_changed()
            visual_reply_auto_show = session.get("visual_reply_auto_show_dock")
            if visual_reply_auto_show is not None and hasattr(self, "visual_reply_auto_show_checkbox"):
                auto_show = bool(visual_reply_auto_show)
                self.visual_reply_auto_show_checkbox.setChecked(auto_show)
                self.on_visual_reply_auto_show_changed(auto_show)
            sensory_feedback_source = session.get("sensory_feedback_source")
            if sensory_feedback_source is not None and hasattr(self, "sensory_feedback_source_combo"):
                source_value = str(sensory_feedback_source or "off")
                self.refresh_sensory_feedback_source_options(selected_value=source_value)
                self.on_sensory_feedback_source_changed(source_value)
            sensory_feedback_interval_seconds = session.get("sensory_feedback_interval_seconds")
            if sensory_feedback_interval_seconds is not None and hasattr(self, "sensory_feedback_interval_spin"):
                interval_seconds = max(2.0, float(sensory_feedback_interval_seconds))
                self.sensory_feedback_interval_spin.setValue(interval_seconds)
                self.on_sensory_feedback_interval_changed(interval_seconds)
            sensory_pingpong_enabled = session.get("sensory_pingpong_enabled")
            if sensory_pingpong_enabled is not None and hasattr(self, "sensory_pingpong_checkbox"):
                pingpong_enabled = bool(sensory_pingpong_enabled)
                self.sensory_pingpong_checkbox.setChecked(pingpong_enabled)
                self.on_sensory_pingpong_enabled_changed(pingpong_enabled)
            sensory_allow_hidden_proactive_speech = session.get("sensory_allow_hidden_proactive_speech")
            if sensory_allow_hidden_proactive_speech is not None and hasattr(self, "sensory_allow_hidden_proactive_checkbox"):
                proactive_enabled = bool(sensory_allow_hidden_proactive_speech)
                self.sensory_allow_hidden_proactive_checkbox.setChecked(proactive_enabled)
                self.on_sensory_allow_hidden_proactive_changed(proactive_enabled)
            sensory_allow_hidden_visual_generation = session.get("sensory_allow_hidden_visual_generation")
            if sensory_allow_hidden_visual_generation is not None and hasattr(self, "sensory_allow_hidden_visual_checkbox"):
                visual_enabled = bool(sensory_allow_hidden_visual_generation)
                self.sensory_allow_hidden_visual_checkbox.setChecked(visual_enabled)
                self.on_sensory_allow_hidden_visual_changed(visual_enabled)
            sensory_pingpong_history_depth = session.get("sensory_pingpong_history_depth")
            if sensory_pingpong_history_depth is not None and hasattr(self, "sensory_pingpong_history_spin"):
                pingpong_depth = max(0, int(sensory_pingpong_history_depth))
                self.sensory_pingpong_history_spin.setValue(pingpong_depth)
                self.on_sensory_pingpong_history_depth_changed(pingpong_depth)
            sensory_pingpong_prompt = session.get("sensory_pingpong_prompt")
            if sensory_pingpong_prompt is not None and hasattr(self, "sensory_pingpong_prompt_text"):
                prompt_text = str(sensory_pingpong_prompt or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")).strip() or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")
                self.sensory_pingpong_prompt_text.setPlainText(prompt_text)
                update_runtime_config("sensory_pingpong_prompt", prompt_text)
            sensory_pingpong_source_prompts = session.get("sensory_pingpong_source_prompts")
            if sensory_pingpong_source_prompts is not None:
                prompt_map = self._normalize_sensory_pingpong_source_prompt_map(sensory_pingpong_source_prompts) if hasattr(self, "_normalize_sensory_pingpong_source_prompt_map") else dict(sensory_pingpong_source_prompts or {})
                update_runtime_config("sensory_pingpong_source_prompts", prompt_map)
                self._refresh_sensory_feedback_source_tabs()
            saved_model_name = session.get("model_name")
            if saved_model_name:
                QtCore.QTimer.singleShot(400, lambda wanted=str(saved_model_name or ""): self._apply_saved_model_name(wanted))
            musetalk_avatar_pack_id = session.get("musetalk_avatar_pack_id")
            if musetalk_avatar_pack_id == "__standalone__":
                musetalk_avatar_pack_id = None
            if musetalk_avatar_pack_id is not None and hasattr(self, "musetalk_avatar_pack_combo"):
                self.refresh_musetalk_avatar_pack_list(selected_pack_id=musetalk_avatar_pack_id)
                for index in range(self.musetalk_avatar_pack_combo.count()):
                    if str(self.musetalk_avatar_pack_combo.itemData(index) or "") == str(musetalk_avatar_pack_id or ""):
                        self.musetalk_avatar_pack_combo.setCurrentIndex(index)
                        break
                self.on_musetalk_avatar_pack_change(self.musetalk_avatar_pack_combo.currentText())
            pocket_tts_python = session.get("pocket_tts_python")
            pocket_tts_python_edit = getattr(self, "pocket_tts_python_edit", None)
            if pocket_tts_python is not None and pocket_tts_python_edit is not None:
                pocket_tts_python_edit.setText(str(pocket_tts_python))
            if self._current_tts_backend_value() == "pockettts" and pocket_tts_python_edit is not None:
                self._ensure_pocket_tts_python_path()
            emotional_instructions = session.get("emotional_instructions")
            if emotional_instructions is not None and hasattr(self, "emotional_text"):
                self.emotional_text.setPlainText(str(emotional_instructions or ""))
                update_runtime_config("emotional_instructions", self.emotional_text.toPlainText().strip())
            system_prompt = session.get("system_prompt")
            if system_prompt is not None and hasattr(self, "system_prompt_text"):
                self.system_prompt_text.setPlainText(str(system_prompt or ""))
                update_runtime_config("system_prompt", self.system_prompt_text.toPlainText().strip())
            for key in ("temperature", "top_p", "top_k", "repeat_penalty", "min_p"):
                if key in session and key in getattr(self, "brain_sliders", {}):
                    self.brain_sliders[key].set_value(session[key])
                    self.update_brain_value(key, session[key], key == "top_k")
            chunking = session.get("chunking")
            if isinstance(chunking, dict):
                for key, value in chunking.items():
                    if key in self.chunking_sliders:
                        self.chunking_sliders[key].set_value(value)
                        update_runtime_config(key, value)
            dry_run_target = session.get("dry_run_target_samples")
            if dry_run_target is not None:
                self.dry_run_target_spin.setValue(max(0, min(12, int(dry_run_target))))
            dry_run_auto_replies = session.get("dry_run_auto_replies")
            if dry_run_auto_replies is not None:
                self.dry_run_auto_replies_checkbox.setChecked(bool(dry_run_auto_replies))
            body = session.get("last_body")
            if body:
                index = self.body_combo.findText(body)
                if index >= 0:
                    self.body_combo.setCurrentIndex(index)
                    self.load_body_config_from_combo()
            if self._addon_manager is not None:
                self._addon_manager.import_session_state(session)
                self._refresh_addon_group_tabs()
            self.live_sync_checkbox.setChecked(bool(session.get("live_sync", False)))
            splitter_sizes = session.get("main_splitter_sizes")
            if isinstance(splitter_sizes, list) and len(splitter_sizes) == 2 and hasattr(self, "main_splitter"):
                try:
                    self.main_splitter.setSizes([max(220, int(splitter_sizes[0])), max(320, int(splitter_sizes[1]))])
                except Exception:
                    pass
            window_state = session.get("window_state")
            if window_state:
                try:
                    self.restoreState(QtCore.QByteArray.fromBase64(window_state.encode("ascii")))
                except Exception:
                    pass
            right_dock_state = session.get("right_dock_state")
            if right_dock_state and hasattr(self, "right_dock_host"):
                try:
                    self.right_dock_host.restoreState(QtCore.QByteArray.fromBase64(right_dock_state.encode("ascii")))
                except Exception:
                    pass
            if bool(session.get("preview_visible", False)):
                self.preview_dock.show()
            else:
                self.preview_dock.hide()
            if bool(session.get("visual_reply_visible", False)):
                self.visual_reply_dock.show()
            else:
                self.visual_reply_dock.hide()
            performance_guidance_visible = bool(session.get("performance_guidance_visible", False))
            if hasattr(self, "performance_guidance_toggle"):
                self.performance_guidance_toggle.setChecked(performance_guidance_visible)
                self._toggle_performance_guidance(performance_guidance_visible)
            self._refresh_hotkey_shortcuts()
            self._refresh_hotkey_labels()
            self._update_restart_sensitive_controls()
            self.refresh_dry_run_status()
            QtCore.QTimer.singleShot(0, self._ensure_window_on_screen)
        finally:
            self._suspend_session_save = previous_suspend
        self.save_session()
        QtCore.QTimer.singleShot(700, self._finalize_session_restore_dirty_state)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._ensure_window_on_screen)

    def closeEvent(self, event):
        self._closing = True
        self.save_session()
        self.stop_musetalk_preview()
        self.stop_engine()
        if hasattr(engine, "set_addon_event_publisher"):
            engine.set_addon_event_publisher(None)
        if hasattr(engine, "set_addon_manager_getter"):
            engine.set_addon_manager_getter(None)
        if self._addon_manager is not None:
            self._addon_manager.unload_all()
        sys.stdout = self._previous_stdout
        sys.stderr = self._previous_stderr
        super().closeEvent(event)


def main():
    argv = list(sys.argv[1:])
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    if len(argv) >= 1 and str(argv[0] or "").strip().lower() in {"--ui-preview", "--ui-file"}:
        ui_path = _resolve_ui_path(argv[1] if len(argv) >= 2 else "main.ui")
        if not ui_path.exists():
            raise FileNotFoundError(f"UI file not found: {ui_path}")
        window = _load_ui_preview_window(ui_path)
        current_title = str(window.windowTitle() or "").strip()
        window.setWindowTitle(f"{current_title} [UI Preview]" if current_title else "UI Preview")
        if isinstance(window, QtWidgets.QMainWindow):
            _configure_main_window_docking(window)
            window.setTabPosition(QtCore.Qt.AllDockWidgetAreas, QtWidgets.QTabWidget.North)
        window.show()
        sys.exit(app.exec())
    window = CompanionQtMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
