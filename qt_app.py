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

from core.musetalk_avatar_packs import discover_avatar_packs
from core.runtime_paths import derive_vam_bridge_root as _derive_vam_bridge_root_safe, legacy_vam_bridge_roots as _legacy_vam_bridge_roots_safe, normalize_vam_root as _normalize_vam_root_safe
from core.runtime_status import build_runtime_status_snapshot
from ui.designer_loader import (
    enable_stdio_unicode_fallback as _ui_shell_enable_stdio_unicode_fallback,
    install_no_wheel_input_guard as _install_no_wheel_input_guard,
    load_ui_shell_for_smoke as _load_ui_shell_for_smoke,
    ui_shell_class_matches as _ui_shell_class_matches,
    ui_shell_find_object as _ui_shell_find_object,
)
from ui.dock_utils import configure_main_window_docking as _configure_main_window_docking
from ui.app_entry import configure_app_entry_dependencies, run_qt_app
from ui.panels.input_dialog import QtInputDialog
from ui.shell_preview import configure_ui_shell_preview_dependencies, run_ui_shell_preview
from ui.shell_smoke import _ui_shell_binding_summary, configure_ui_shell_smoke_dependencies, run_ui_shell_smoke
from ui.shell_specs import (
    UI_SHELL_BODY_EMOTIONS,
    UI_SHELL_BODY_POSE_SPECS,
    UI_SHELL_CHUNKING_SPECS,
    UI_SHELL_DEFAULT_CHUNKING_VALUES,
    UI_SHELL_DEFAULT_LOCAL_VAM_ROOT,
    UI_SHELL_LIVE_ADDON_IDS,
    UI_SHELL_MUSE_VRAM_MODE_LABELS,
    WORKSPACE_DOCKED_AUX_MIN_HEIGHT,
    WORKSPACE_DOCKED_VIEW_MIN_WIDTH,
    WORKSPACE_INNER_MIN_HEIGHT,
    WORKSPACE_INNER_MIN_WIDTH,
    WORKSPACE_PREVIEW_FRAME_MIN_HEIGHT,
    WORKSPACE_VIEW_MAX_HEIGHT,
    WORKSPACE_VIEW_MIN_HEIGHT,
    WORKSPACE_VIEW_MIN_WIDTH,
    WORKSPACE_WINDOW_MAX_HEIGHT,
)
from ui.validation import (
    UI_REAL_PREVIEW_ONLY_ROOTS,
    UI_SHELL_TAB_MOUNT_WIDGETS,
    UI_VALIDATION_REQUIRED_GROUPS,
    collect_ui_shell_static_tabs as _collect_ui_shell_static_tabs,
    resolve_ui_path as _resolve_ui_path_base,
    validate_ui_file as _validate_ui_file_base,
)
from ui.panels.avatar_windows import QtExternalAvatarReturnWindow, QtMuseTalkStageWindow
from ui.panels.hand_doctor_dialog import HandDoctorDialog
from ui.panels.visual_reply_panel import QtVisualReplyPanel
from ui.runtime.console_redirect import QtConsoleBridge, QtTextRedirector
from ui.runtime.legacy_dock_titles import LegacyDockTitleMixin, configure_legacy_dock_title_dependencies
from ui.runtime.legacy_workspace_docks import LegacyWorkspaceDockMixin, configure_legacy_workspace_dock_dependencies
from ui.runtime.real_ui_bridge import MainUiRealRuntimeBridge, configure_real_ui_bridge_dependencies
from ui.runtime.shell_addon_reports import (
    _print_ui_shell_addon_mount_report,
    _print_ui_shell_static_addon_comparison,
    _read_ui_shell_session_snapshot,
    _ui_shell_addon_mount_report,
    _ui_shell_addon_registry_state,
    _ui_shell_addon_rows_text,
    _ui_shell_addon_effectively_enabled,
    _ui_shell_discover_addon_manifests,
    _ui_shell_fallback_targets_for_manifest,
    _ui_shell_mount_target_for_area,
    _ui_shell_norm_label,
    _ui_shell_rows_for_target,
    _ui_shell_static_addon_comparison,
    _ui_shell_static_service_hints,
    _ui_shell_static_tab_areas,
    _ui_shell_target_addon_rows,
    configure_shell_addon_report_dependencies,
)
from ui.runtime.shell_chunking_profiles import (
    _bind_ui_shell_chunking_profile_controls,
    _ui_shell_apply_profile_settings,
    _ui_shell_chunking_slider_spec,
    _ui_shell_chunking_slider_widget,
    _ui_shell_configure_chunking_slider,
    _ui_shell_current_chunking_values,
    _ui_shell_format_chunking_value,
    _ui_shell_load_profile_preview,
    _ui_shell_reset_chunking_defaults,
    _ui_shell_update_chunking_label,
    configure_shell_chunking_profiles_dependencies,
)
from ui.runtime.shell_local_bindings import (
    _bind_ui_shell_chat_context_controls,
    _bind_ui_shell_console_chat_local_controls,
    _bind_ui_shell_lifecycle_local_controls,
    _bind_ui_shell_runtime_action_controls,
    _bind_ui_shell_tutorial_controls,
    configure_shell_local_bindings_dependencies,
)
from ui.runtime.shell_runtime_cards import (
    _bind_ui_shell_avatar_runtime,
    _bind_ui_shell_chat_runtime,
    _bind_ui_shell_tts_runtime,
    _ui_shell_chat_provider_map,
    _ui_shell_chat_provider_rows_text,
    _ui_shell_clear_form_layout,
    _ui_shell_current_provider_id,
    _ui_shell_generation_default_value,
    _ui_shell_provider_label,
    configure_shell_runtime_cards_dependencies,
)
from ui.runtime.shell_session_config import (
    _bind_ui_shell_preset_session_controls,
    _ui_shell_body_config_payload,
    _ui_shell_checkbox_value,
    _ui_shell_combo_select_label,
    _ui_shell_combo_set_items,
    _ui_shell_combo_text_value,
    _ui_shell_current_voice_file,
    _ui_shell_format_clock_seconds,
    _ui_shell_latest_performance_profile_payload,
    _ui_shell_line_edit_value,
    _ui_shell_list_body_configs,
    _ui_shell_list_performance_profiles,
    _ui_shell_load_json,
    _ui_shell_performance_profile_label,
    _ui_shell_performance_profile_payload,
    _ui_shell_plain_text_value,
    _ui_shell_preset_names,
    _ui_shell_selected_body_name,
    _ui_shell_set_checked,
    _ui_shell_set_double_value,
    _ui_shell_set_read_only_tooltip,
    _ui_shell_set_slider_value,
    _ui_shell_set_spin_value,
    _ui_shell_voice_options,
    configure_shell_session_config_dependencies,
)
from ui.runtime.shell_status_layout import (
    _apply_ui_shell_preview_status,
    _apply_workspace_view_constraints,
    _apply_workspace_widget_bounds,
    _relax_docked_workspace_minimums,
    _ui_shell_append_console,
    _ui_shell_audio_device_labels,
    _ui_shell_compose_status_line,
    _ui_shell_host_core_state,
    _ui_shell_musetalk_avatar_pack_options,
    _ui_shell_parse_sensory_source_values,
    _ui_shell_refresh_host_core_status,
    _ui_shell_refresh_status_labels,
    _ui_shell_sensory_source_options,
    _ui_shell_stream_mode_enabled,
    _ui_shell_text_line_count,
    configure_shell_status_layout_dependencies,
)
from ui.runtime.shell_services import (
    _UiShellAvatarProviderService,
    _UiShellChatContextService,
    _UiShellChatProviderRegistry,
    _UiShellChatReplayService,
    _UiShellDialogService,
    _UiShellDryRunService,
    _UiShellEngineLifecycleService,
    _UiShellHotkeyService,
    _UiShellInputActionService,
    _UiShellInputSettingsService,
    _UiShellModelRefreshService,
    _UiShellPerformanceProfileService,
    _UiShellPersonaAvatarService,
    _UiShellRuntimeControlService,
    _UiShellRuntimeStatusService,
    _UiShellSensoryService,
    _UiShellShellService,
    _UiShellTutorialService,
    _UiShellVisualReplyService,
    configure_shell_service_dependencies,
)
from ui.widgets.basic import (
    AltWheelZoomScrollArea,
    CollapsibleSection,
    ContextTokenStepper,
    DecimalStepper,
    LabeledSlider,
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSlider,
    NoWheelSpinBox,
    NoWheelTabWidget,
    set_combo_popup_palette_callback,
)
from ui.widgets.telemetry import ChunkProgressTelemetryBar, PipelineTelemetryWidget

def _resolve_ui_path(raw_path):
    return _resolve_ui_path_base(raw_path, base_path=__file__)


def validate_ui_file(raw_path):
    return _validate_ui_file_base(raw_path, base_path=__file__)


if len(sys.argv) >= 2 and str(sys.argv[1] or "").strip().lower() == "--validate-ui":
    ui_arg = sys.argv[2] if len(sys.argv) >= 3 else "main.ui"
    sys.exit(validate_ui_file(ui_arg))































def _configure_real_ui_bridge_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    configure_real_ui_bridge_dependencies({
        "APP_THEME_PRESET_LABELS": APP_THEME_PRESET_LABELS,
        "APP_THEME_PRESET_WIDGETS": APP_THEME_PRESET_WIDGETS,
        "APP_TITLE": APP_TITLE,
        "AddonCapabilityBridgeService": AddonCapabilityBridgeService,
        "CompanionQtMainWindow": CompanionQtMainWindow,
        "DEFAULT_APP_THEME_PRESET": DEFAULT_APP_THEME_PRESET,
        "QtChatContextService": QtChatContextService,
        "QtEngineLifecycleService": QtEngineLifecycleService,
        "QtInputActionService": QtInputActionService,
        "QtModelRefreshService": QtModelRefreshService,
        "QtRuntimeControlService": QtRuntimeControlService,
        "QtRuntimeStatusService": QtRuntimeStatusService,
        "QtVisualReplyPanel": QtVisualReplyPanel,
        "RUNTIME_CONFIG": RUNTIME_CONFIG,
        "SESSION_PATH": SESSION_PATH,
        "UI_REAL_PREVIEW_ONLY_ROOTS": UI_REAL_PREVIEW_ONLY_ROOTS,
        "UI_SHELL_BODY_POSE_SPECS": UI_SHELL_BODY_POSE_SPECS,
        "UI_SHELL_CHUNKING_SPECS": UI_SHELL_CHUNKING_SPECS,
        "__file__": __file__,
        "_WIN32_DOCK_OWNER_SUPPORTED": _WIN32_DOCK_OWNER_SUPPORTED,
        "_WIN32_GWLP_HWNDPARENT": _WIN32_GWLP_HWNDPARENT,
        "_win32_set_window_owner": _win32_set_window_owner,
        "_app_theme_palette": _app_theme_palette,
        "_apply_engine_action_button_accents": _apply_engine_action_button_accents,
        "_apply_inline_theme_styles": _apply_inline_theme_styles,
        "_apply_readable_input_palettes": _apply_readable_input_palettes,
        "_apply_workspace_view_constraints": _apply_workspace_view_constraints,
        "_build_app_stylesheet_for_preset": _build_app_stylesheet_for_preset,
        "_normalize_app_theme_preset_id": _normalize_app_theme_preset_id,
        "_read_ui_shell_session_snapshot": _read_ui_shell_session_snapshot,
        "_load_ui_preview_window": _load_ui_preview_window,
        "_resolve_ui_path": _resolve_ui_path,
        "_split_collapsible_section_text": _split_collapsible_section_text,
        "_ui_shell_audio_device_labels": _ui_shell_audio_device_labels,
        "_ui_shell_body_slider_raw_to_value": _ui_shell_body_slider_raw_to_value,
        "_ui_shell_body_value_to_slider_raw": _ui_shell_body_value_to_slider_raw,
        "_ui_shell_chunking_slider_spec": _ui_shell_chunking_slider_spec,
        "_ui_shell_combo_select_label": _ui_shell_combo_select_label,
        "_ui_shell_combo_set_items": _ui_shell_combo_set_items,
        "_ui_shell_update_body_label": _ui_shell_update_body_label,
        "_ui_shell_update_chunking_label": _ui_shell_update_chunking_label,
        "ctypes": ctypes,
        "engine": engine,
        "shared_state": shared_state,
        "tutorial_framework": tutorial_framework,
        "update_runtime_config": update_runtime_config,
    })


def _configure_app_entry_dependencies():
    configure_app_entry_dependencies({
        "APP_TITLE": APP_TITLE,
        "CompanionQtMainWindow": CompanionQtMainWindow,
        "MainUiRealRuntimeBridge": MainUiRealRuntimeBridge,
        "SESSION_PATH": SESSION_PATH,
        "_configure_main_window_docking": _configure_main_window_docking,
        "_configure_real_ui_bridge_dependencies": _configure_real_ui_bridge_dependencies,
        "_install_no_wheel_input_guard": _install_no_wheel_input_guard,
        "_load_ui_preview_window": _load_ui_preview_window,
        "_resolve_ui_path": _resolve_ui_path,
    })


def _configure_ui_shell_service_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    _configure_ui_shell_addon_report_dependencies()
    configure_shell_service_dependencies(globals())


def _configure_ui_shell_addon_report_dependencies():
    configure_shell_addon_report_dependencies(globals())


_configure_ui_shell_addon_report_dependencies()


def _configure_ui_shell_status_layout_dependencies():
    _configure_ui_shell_addon_report_dependencies()
    configure_shell_status_layout_dependencies(globals())


_configure_ui_shell_status_layout_dependencies()


def _configure_ui_shell_local_bindings_dependencies():
    _configure_ui_shell_status_layout_dependencies()
    configure_shell_local_bindings_dependencies(globals())


_configure_ui_shell_local_bindings_dependencies()


def _configure_ui_shell_runtime_cards_dependencies():
    _configure_ui_shell_local_bindings_dependencies()
    configure_shell_runtime_cards_dependencies(globals())


_configure_ui_shell_runtime_cards_dependencies()


def _configure_ui_shell_session_config_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    configure_shell_session_config_dependencies(globals())


_configure_ui_shell_session_config_dependencies()


def _configure_ui_shell_chunking_profiles_dependencies():
    _configure_ui_shell_session_config_dependencies()
    configure_shell_chunking_profiles_dependencies(globals())


_configure_ui_shell_chunking_profiles_dependencies()


def _ui_shell_runtime_status_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_runtime_status_service", None)
    if service is None:
        service = _UiShellRuntimeStatusService(window)
        setattr(window, "_nc_ui_shell_runtime_status_service", service)
    return service


def _ui_shell_model_refresh_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_model_refresh_service", None)
    if service is None:
        service = _UiShellModelRefreshService(window)
        setattr(window, "_nc_ui_shell_model_refresh_service", service)
    return service


def _ui_shell_chat_replay_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_chat_replay_service", None)
    if service is None:
        service = _UiShellChatReplayService(window)
        setattr(window, "_nc_ui_shell_chat_replay_service", service)
    return service


def _ui_shell_tutorial_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_tutorial_service", None)
    if service is None:
        service = _UiShellTutorialService(window)
        setattr(window, "_nc_ui_shell_tutorial_service", service)
    return service


def _ui_shell_chat_context_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_chat_context_service", None)
    if service is None:
        service = _UiShellChatContextService(window)
        setattr(window, "_nc_ui_shell_chat_context_service", service)
    return service


def _ui_shell_input_settings_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_input_settings_service", None)
    if service is None:
        service = _UiShellInputSettingsService(window)
        setattr(window, "_nc_ui_shell_input_settings_service", service)
    return service


def _ui_shell_performance_profile_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_performance_profile_service", None)
    if service is None:
        service = _UiShellPerformanceProfileService(window)
        setattr(window, "_nc_ui_shell_performance_profile_service", service)
    return service


def _ui_shell_dry_run_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_dry_run_service", None)
    if service is None:
        service = _UiShellDryRunService(window)
        setattr(window, "_nc_ui_shell_dry_run_service", service)
    return service


def _ui_shell_persona_avatar_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_persona_avatar_service", None)
    if service is None:
        service = _UiShellPersonaAvatarService(window)
        setattr(window, "_nc_ui_shell_persona_avatar_service", service)
    return service


def _ui_shell_input_actions_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_input_actions_service", None)
    if service is None:
        service = _UiShellInputActionService(window)
        setattr(window, "_nc_ui_shell_input_actions_service", service)
    return service


def _ui_shell_runtime_controls_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_runtime_controls_service", None)
    if service is None:
        service = _UiShellRuntimeControlService(window)
        setattr(window, "_nc_ui_shell_runtime_controls_service", service)
    return service


def _ui_shell_engine_lifecycle_service(window):
    _configure_ui_shell_service_dependencies()
    service = getattr(window, "_nc_ui_shell_engine_lifecycle_service", None)
    if service is None:
        service = _UiShellEngineLifecycleService(window)
        setattr(window, "_nc_ui_shell_engine_lifecycle_service", service)
    return service


































































































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
    configure_shell_service_dependencies(globals())

    mounted = []
    mounted_ids = []
    failures = []
    live_refs = []
    live_tabs = []
    tts_backends_by_id = OrderedDict()
    app_root = Path(__file__).resolve().parent
    storage_root = app_root / "runtime" / "addons" / "ui_shell"
    event_bus = AddonEventBus()
    service_registry = AddonServiceRegistry()
    chat_provider_registry = _UiShellChatProviderRegistry()
    sensory_registry = _UiShellSensoryService()
    avatar_provider_registry = _UiShellAvatarProviderService()
    host_services = {
        "qt.avatar_providers": avatar_provider_registry,
        "qt.chat_providers": chat_provider_registry,
        "qt.chat_context": _ui_shell_chat_context_service(window),
        "qt.chat_replay": _ui_shell_chat_replay_service(window),
        "qt.dialogs": _UiShellDialogService(window),
        "qt.dry_run": _ui_shell_dry_run_service(window),
        "qt.engine_lifecycle": _ui_shell_engine_lifecycle_service(window),
        "qt.hotkeys": _UiShellHotkeyService(),
        "qt.input_actions": _ui_shell_input_actions_service(window),
        "qt.input_settings": _ui_shell_input_settings_service(window),
        "qt.persona_avatar": _ui_shell_persona_avatar_service(window),
        "qt.performance_profiles": _ui_shell_performance_profile_service(window),
        "qt.model_refresh": _ui_shell_model_refresh_service(window),
        "qt.runtime_controls": _ui_shell_runtime_controls_service(window),
        "qt.runtime_status": _ui_shell_runtime_status_service(window),
        "qt.sensory": sensory_registry,
        "qt.shell": _UiShellShellService(),
        "qt.tutorials": _ui_shell_tutorial_service(window),
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
            avatar_provider_ids_before = {str(item.get("id") or "").strip() for item in avatar_provider_registry.list_providers()}
            sensory_provider_ids_before = {str(item.get("id") or "").strip() for item in sensory_registry.list_providers()}
            service_names_before = {str(item.get("name") or "").strip() for item in service_registry.list_entries()}
            module = _ui_shell_load_addon_module(row)
            addon_cls = getattr(module, "Addon", None)
            if addon_cls is None:
                raise RuntimeError("Addon class is missing.")
            addon = addon_cls()
            addon.initialize(context)
            provider_ids_after = chat_provider_registry.provider_ids()
            added_provider_ids = sorted(provider_ids_after - provider_ids_before)
            avatar_provider_ids_after = {str(item.get("id") or "").strip() for item in avatar_provider_registry.list_providers()}
            sensory_provider_ids_after = {str(item.get("id") or "").strip() for item in sensory_registry.list_providers()}
            service_entries_after = service_registry.list_entries()
            service_names_after = {str(item.get("name") or "").strip() for item in service_entries_after}
            added_avatar_provider_ids = sorted(avatar_provider_ids_after - avatar_provider_ids_before)
            added_sensory_provider_ids = sorted(sensory_provider_ids_after - sensory_provider_ids_before)
            added_tts_backend_summaries = []
            for entry in service_entries_after:
                service_name = str(entry.get("name") or "").strip()
                if not service_name or service_name not in (service_names_after - service_names_before):
                    continue
                metadata = dict(entry.get("metadata") or {})
                if str(metadata.get("kind") or "").strip().lower() != "tts":
                    continue
                backend_id = str(metadata.get("backend_id") or service_name).strip()
                if not backend_id:
                    continue
                summary = {
                    "id": backend_id,
                    "service_name": service_name,
                    "label": str(metadata.get("label") or backend_id).strip() or backend_id,
                    "provider": str(metadata.get("provider") or "").strip(),
                    "supports_streaming": bool(metadata.get("supports_streaming", False)),
                    "owner_addon_id": str(entry.get("owner_addon_id") or "").strip(),
                    "metadata": metadata,
                }
                tts_backends_by_id[backend_id] = summary
                added_tts_backend_summaries.append(dict(summary))
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
            added_avatar_provider_summaries = [
                provider
                for provider in avatar_provider_registry.list_providers()
                if str(provider.get("id") or "").strip() in set(added_avatar_provider_ids)
            ]
            added_sensory_provider_summaries = [
                provider
                for provider in sensory_registry.list_providers()
                if str(provider.get("id") or "").strip() in set(added_sensory_provider_ids)
            ]
            if added_tabs or added_provider_summaries or added_avatar_provider_summaries or added_sensory_provider_summaries or added_tts_backend_summaries:
                details = []
                if added_tabs:
                    details.append(", ".join(added_tabs))
                if added_provider_summaries:
                    labels = ", ".join(
                        f"chat_provider/{provider.get('label') or provider.get('id')}"
                        for provider in added_provider_summaries
                    )
                    details.append(labels)
                if added_avatar_provider_summaries:
                    labels = ", ".join(
                        f"avatar_provider/{provider.get('label') or provider.get('id')}"
                        for provider in added_avatar_provider_summaries
                    )
                    details.append(labels)
                if added_sensory_provider_summaries:
                    labels = ", ".join(
                        f"sensory_provider/{provider.get('label') or provider.get('id')}"
                        for provider in added_sensory_provider_summaries
                    )
                    details.append(labels)
                if added_tts_backend_summaries:
                    labels = ", ".join(
                        f"tts_backend/{backend.get('label') or backend.get('id')}"
                        for backend in added_tts_backend_summaries
                    )
                    details.append(labels)
                mounted.append(f"{addon_id}: {'; '.join(details)}")
                mounted_ids.append(addon_id)
                live_refs.append({
                    "addon": addon,
                    "context": context,
                    "tabs": added_tabs,
                    "providers": added_provider_ids,
                    "avatar_providers": added_avatar_provider_ids,
                    "sensory_providers": added_sensory_provider_ids,
                    "tts_backends": [str(item.get("id") or "").strip() for item in added_tts_backend_summaries],
                })
            else:
                context.close()
                failures.append(f"{addon_id}: no supported top-level tabs registered")
        except Exception as exc:
            failures.append(f"{addon_id}: {exc}")
    setattr(window, "_nc_ui_shell_live_addons", live_refs)
    setattr(window, "_nc_ui_shell_live_services", {
        "chat_provider_registry": chat_provider_registry,
        "avatar_provider_registry": avatar_provider_registry,
        "sensory_registry": sensory_registry,
    })
    return {
        "mounted": mounted,
        "failures": failures,
        "mounted_ids": sorted(set(mounted_ids)),
        "chat_providers": chat_provider_registry.list_providers(),
        "avatar_providers": avatar_provider_registry.list_providers(),
        "sensory_providers": sensory_registry.list_providers(),
        "tts_backends": list(tts_backends_by_id.values()),
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


def _ui_shell_body_pose_spec(key):
    return dict(UI_SHELL_BODY_POSE_SPECS.get(str(key), {}) or {})


def _ui_shell_body_slider_widget(window, key):
    spec = _ui_shell_body_pose_spec(key)
    return _ui_shell_find_object(window, spec.get("widget", ""))


def _ui_shell_body_label_widget(window, key):
    spec = _ui_shell_body_pose_spec(key)
    return _ui_shell_find_object(window, spec.get("label", ""))


def _ui_shell_body_value_to_slider_raw(key, value):
    spec = _ui_shell_body_pose_spec(key)
    scale = int(spec.get("scale", 1) or 1)
    try:
        return int(round(float(value) * scale))
    except Exception:
        return 0


def _ui_shell_body_slider_raw_to_value(key, raw_value):
    spec = _ui_shell_body_pose_spec(key)
    scale = float(spec.get("scale", 1) or 1)
    try:
        value = float(raw_value) / scale
    except Exception:
        value = float(spec.get("default", 0.0) or 0.0)
    if int(spec.get("scale", 1) or 1) == 1:
        return int(round(value))
    return round(value, 2)


def _ui_shell_format_body_value(key, value):
    spec = _ui_shell_body_pose_spec(key)
    if int(spec.get("scale", 1) or 1) == 1:
        try:
            return str(int(round(float(value))))
        except Exception:
            return str(value)
    try:
        return f"{float(value):.2f}"
    except Exception:
        return str(value)


def _ui_shell_update_body_label(window, key, value=None):
    label = _ui_shell_body_label_widget(window, key)
    if label is None or not hasattr(label, "setText"):
        return
    spec = _ui_shell_body_pose_spec(key)
    base_text = str(getattr(label, "_nc_ui_shell_base_text", "") or "").strip()
    if not base_text:
        base_text = str(label.text() or spec.get("title") or str(key)).strip() or str(key)
        setattr(label, "_nc_ui_shell_base_text", base_text)
    current = value
    if current is None:
        slider = _ui_shell_body_slider_widget(window, key)
        if slider is not None and hasattr(slider, "value"):
            try:
                current = _ui_shell_body_slider_raw_to_value(key, slider.value())
            except Exception:
                current = spec.get("default", 0.0)
    label.setText(f"{base_text}: {_ui_shell_format_body_value(key, current)}")


def _ui_shell_configure_body_slider(window, key, value=None):
    spec = _ui_shell_body_pose_spec(key)
    slider = _ui_shell_body_slider_widget(window, key)
    if slider is None:
        return False
    scale = int(spec.get("scale", 1) or 1)
    initial_value = spec.get("default", 0.0) if value is None else value
    minimum = _ui_shell_body_value_to_slider_raw(key, spec.get("minimum", 0.0))
    maximum = _ui_shell_body_value_to_slider_raw(key, spec.get("maximum", 0.0))
    raw_value = _ui_shell_body_value_to_slider_raw(key, initial_value)
    try:
        slider.blockSignals(True)
        if hasattr(slider, "setRange"):
            slider.setRange(minimum, maximum)
        if hasattr(slider, "setSingleStep"):
            slider.setSingleStep(max(1, scale // 10 if scale > 1 else 1))
        if hasattr(slider, "setPageStep"):
            page_step = max(1, int((maximum - minimum) / 10))
            slider.setPageStep(page_step)
        if hasattr(slider, "setValue"):
            slider.setValue(max(minimum, min(maximum, raw_value)))
        if hasattr(slider, "setToolTip"):
            slider.setToolTip("Shell-local body-pose preview. Changes are not saved or applied to runtime.")
    except Exception:
        return False
    finally:
        try:
            slider.blockSignals(False)
        except Exception:
            pass
    _ui_shell_update_body_label(window, key, initial_value)
    return True


def _ui_shell_current_body_pose_values(window):
    values = {}
    for key, spec in UI_SHELL_BODY_POSE_SPECS.items():
        slider = _ui_shell_body_slider_widget(window, key)
        if slider is not None and hasattr(slider, "value"):
            try:
                values[key] = _ui_shell_body_slider_raw_to_value(key, slider.value())
                continue
            except Exception:
                pass
        values[key] = spec.get("default", 0.0)
    return values


def _ui_shell_selected_body_profile(window):
    payload = getattr(window, "_nc_ui_shell_body_profile_payload", None)
    if isinstance(payload, dict):
        return payload
    return {}


def _ui_shell_set_selected_body_profile(window, payload):
    setattr(window, "_nc_ui_shell_body_profile_payload", dict(payload or {}))


def _ui_shell_apply_body_profile_for_emotion(window, emotion_label=None):
    emotion = str(emotion_label or _ui_shell_combo_text_value(window, "emotion_combo", "Neutral")).strip().lower() or "neutral"
    payload = _ui_shell_selected_body_profile(window)
    profile = dict(payload.get("profile") or payload or {})
    emotion_values = dict(profile.get(emotion) or profile.get("neutral") or {})
    applied = []
    for key in UI_SHELL_BODY_POSE_SPECS:
        if _ui_shell_configure_body_slider(window, key, value=emotion_values.get(key, UI_SHELL_BODY_POSE_SPECS[key].get("default", 0.0))):
            applied.append(key)
    return applied


def _ui_shell_refresh_body_combo(window, preferred_name=""):
    configs = _ui_shell_list_body_configs()
    combo = _ui_shell_find_object(window, "body_combo")
    if combo is None or not hasattr(combo, "addItem"):
        return configs
    preferred = str(preferred_name or _ui_shell_selected_body_name(window) or "").strip()
    combo.blockSignals(True)
    try:
        combo.clear()
        if configs:
            for name in configs:
                combo.addItem(name)
            target_index = 0
            if preferred and preferred in configs:
                target_index = configs.index(preferred)
            combo.setCurrentIndex(target_index)
        else:
            combo.addItem("No Configs")
            combo.setCurrentIndex(0)
        combo.setToolTip("Shell-local body preset list. Reads body_configs/*.json only.")
    finally:
        combo.blockSignals(False)
    return configs


def _ui_shell_load_body_preview(window, name=""):
    target = str(name or "").strip() or _ui_shell_selected_body_name(window)
    if not target or target == "No Configs":
        return {
            "accepted": False,
            "loaded": False,
            "body_name": "",
            "message": "No body preset selected.",
        }
    payload = _ui_shell_body_config_payload(target)
    if not payload:
        return {
            "accepted": False,
            "loaded": False,
            "body_name": target,
            "message": f"Could not load body preset: {target}",
        }
    _ui_shell_set_selected_body_profile(window, payload)
    _ui_shell_refresh_body_combo(window, preferred_name=target)
    applied = _ui_shell_apply_body_profile_for_emotion(window)
    return {
        "accepted": True,
        "loaded": True,
        "body_name": target,
        "applied_keys": applied,
        "message": f"Loaded shell preview for body preset: {target}",
    }


def _ui_shell_normalize_vam_root(raw_value=""):
    app_root = Path(__file__).resolve().parent
    default_root = str(_read_ui_shell_session_snapshot().get("vam_root", "") or UI_SHELL_DEFAULT_LOCAL_VAM_ROOT).strip()
    legacy_roots = _legacy_vam_bridge_roots_safe(app_root=app_root)
    return _normalize_vam_root_safe(raw_value, default_vam_root=default_root, legacy_roots=legacy_roots, migrate_legacy=True)


def _ui_shell_derive_vam_bridge_root(vam_root):
    return _derive_vam_bridge_root_safe(vam_root, app_root=Path(__file__).resolve().parent)


def _ui_shell_current_vam_settings(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    vam_root = _ui_shell_line_edit_value(window, "vam_root_edit", str(session.get("vam_root", "") or UI_SHELL_DEFAULT_LOCAL_VAM_ROOT))
    normalized_root = _ui_shell_normalize_vam_root(vam_root)
    return {
        "vam_root": normalized_root,
        "vam_bridge_root": _ui_shell_line_edit_value(window, "vam_bridge_root_edit", _ui_shell_derive_vam_bridge_root(normalized_root)),
        "vam_target_atom_uid": _ui_shell_line_edit_value(window, "vam_target_atom_uid_edit", str(session.get("vam_target_atom_uid", "Person") or "Person")),
        "vam_target_storable_id": _ui_shell_line_edit_value(window, "vam_target_storable_id_edit", str(session.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge")),
        "vam_vmc_host": _ui_shell_line_edit_value(window, "vam_vmc_host_edit", str(session.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1")),
        "vam_vmc_port": int(_ui_shell_find_object(window, "vam_vmc_port_spin").value()) if _ui_shell_find_object(window, "vam_vmc_port_spin") is not None and hasattr(_ui_shell_find_object(window, "vam_vmc_port_spin"), "value") else int(session.get("vam_vmc_port", 39539) or 39539),
        "vam_vmc_enabled": _ui_shell_checkbox_value(window, "vam_vmc_enabled_checkbox", bool(session.get("vam_vmc_enabled", True))),
        "vam_bridge_enabled": _ui_shell_checkbox_value(window, "vam_bridge_enabled_checkbox", bool(session.get("vam_bridge_enabled", True))),
        "vam_play_audio_in_vam": _ui_shell_checkbox_value(window, "vam_play_audio_in_vam_checkbox", bool(session.get("vam_play_audio_in_vam", False))),
        "vam_timeline_auto_resume": _ui_shell_checkbox_value(window, "vam_timeline_auto_resume_checkbox", bool(session.get("vam_timeline_auto_resume", True))),
    }


def _ui_shell_refresh_vam_status_labels(window):
    settings = _ui_shell_current_vam_settings(window)
    runtime_label = _ui_shell_find_object(window, "vam_runtime_label")
    bridge_status_label = _ui_shell_find_object(window, "vam_bridge_status_label")
    bridge_detail_label = _ui_shell_find_object(window, "vam_bridge_detail_label")
    runtime_text = "Runtime: shell preview only"
    bridge_modes = []
    if settings.get("vam_vmc_enabled"):
        bridge_modes.append("VMC on")
    if settings.get("vam_bridge_enabled"):
        bridge_modes.append("Bridge on")
    bridge_text = ", ".join(bridge_modes) if bridge_modes else "all off"
    if runtime_label is not None and hasattr(runtime_label, "setText"):
        runtime_label.setText(runtime_text)
    if bridge_status_label is not None and hasattr(bridge_status_label, "setText"):
        bridge_status_label.setText(f"Bridge status: {bridge_text}")
    if bridge_detail_label is not None and hasattr(bridge_detail_label, "setText"):
        bridge_detail_label.setText(
            f"Root: {settings.get('vam_root') or '<unset>'} | Bridge: {settings.get('vam_bridge_root') or '<unset>'}"
        )
    return settings


def _ui_shell_dry_run_status_text(latest, *, target_samples=0, auto_replies=True, preview_state="idle"):
    latest = dict(latest or {})
    if preview_state == "armed":
        target_text = "Auto" if int(target_samples or 0) <= 0 else str(int(target_samples))
        return f"Dry Run shell preview armed for {target_text} sample(s)." + (" Hands-free preview enabled." if auto_replies else "")
    if latest:
        confidence = float(latest.get("confidence", 0.0) or 0.0)
        stability = float(latest.get("stability", 0.0) or 0.0)
        return f"Dry Run idle. Last saved profile confidence {confidence:.2f}, stability {stability:.2f}."
    return "Dry Run idle."


def _ui_shell_dry_run_summary_text(latest, *, target_samples=0, auto_replies=True, preview_state="idle"):
    latest = dict(latest or {})
    if preview_state == "armed":
        target_text = "Auto" if int(target_samples or 0) <= 0 else str(int(target_samples))
        return (
            "Shell preview only.\n"
            f"- Requested target samples: {target_text}\n"
            f"- Hands-free preview: {'enabled' if auto_replies else 'disabled'}\n"
            "- Starting a real Dry Run session remains deferred in --ui-shell.\n"
            "- No engine, model, or profiling worker was started."
        )
    if not latest:
        return "Arm a Dry Run to collect reply samples and generate machine-specific recommendations."
    summary = dict(latest.get("summary") or {})
    recommendation = dict(latest.get("recommendation") or {})
    settings = dict(recommendation.get("settings") or {})
    lines = [
        "Latest saved Dry Run profile:",
        f"- Name: {str(latest.get('saved_name') or latest.get('display_name') or '<unnamed>').strip()}",
        f"- Sample count: {int(latest.get('sample_count', 0) or 0)}",
        f"- Confidence: {float(latest.get('confidence', 0.0) or 0.0):.2f}",
        f"- Stability: {float(latest.get('stability', 0.0) or 0.0):.2f}",
    ]
    updated_at = latest.get("updated_at")
    try:
        lines.append(f"- Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(updated_at)))}")
    except Exception:
        pass
    if summary:
        lines.extend([
            "",
            "Measured startup profile:",
            f"- Avg first audio chunk: {float(summary.get('avg_first_audio_chunk_ms', 0.0) or 0.0):.1f} ms",
            f"- Avg first visual buffer wait: {float(summary.get('avg_buffer_wait_ms', 0.0) or 0.0):.1f} ms",
            f"- Avg chunk quality: {float(summary.get('avg_chunk_quality', 0.0) or 0.0):.2f}",
            f"- Avg emitted chunk chars: {float(summary.get('avg_chunk_chars', 0.0) or 0.0):.1f}",
        ])
    if settings:
        lines.extend([
            "",
            "Recommended visible settings:",
            f"- Stream mode: {'On' if bool(settings.get('stream_mode')) else 'Off'}",
            f"- MuseTalk VRAM: {UI_SHELL_MUSE_VRAM_MODE_LABELS.get(str(settings.get('musetalk_vram_mode') or '').strip().lower(), 'Quality')}",
        ])
        for key in (
            "stream_chunk_target_chars",
            "stream_chunk_max_chars",
            "stream_first_chunk_min_chars",
            "musetalk_chunk_target_chars",
            "musetalk_chunk_max_chars",
            "musetalk_quickstart_1_target_chars",
        ):
            if key in settings:
                title = str(_ui_shell_chunking_slider_spec(key).get("title") or key).strip()
                lines.append(f"- {title}: {_ui_shell_format_chunking_value(settings.get(key))}")
        lines.extend([
            "",
            "Use Apply Recommendation to preview the shell-visible subset only.",
        ])
    else:
        lines.extend([
            "",
            "No saved recommendation settings were found in the latest profile.",
        ])
    lines.extend([
        "",
        "Shell preview note:",
        "- Dry Run start/stop remains deferred here.",
    ])
    return "\n".join(lines)




























def _apply_ui_shell_read_only_config(window):
    session = _read_ui_shell_session_snapshot()
    audio_devices = _ui_shell_audio_device_labels()
    avatar_pack_options = _ui_shell_musetalk_avatar_pack_options(session)
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
        ("audio_input_device_combo", list(audio_devices.get("inputs") or ["Default Input"]), session.get("audio_input_device", "Default Input")),
        ("audio_output_device_combo", list(audio_devices.get("outputs") or ["Default Output"]), session.get("audio_output_device", "Default Output")),
        ("engine_combo", list(avatar_labels.values()), avatar_labels.get(str(session.get("avatar_mode", "")).strip().lower(), session.get("avatar_mode", ""))),
        ("input_mode_combo", ["Voice Activation", "Push-to-Talk"], session.get("input_mode", "")),
        ("input_role_combo", ["User Message", "System Message", "Assistant Message"], session.get("input_message_role", "")),
        ("stream_mode_combo", ["Off", "On"], session.get("stream_mode", "")),
        ("tts_backend_combo", list(tts_labels.values()), tts_labels.get(str(session.get("tts_backend", "")).strip().lower(), session.get("tts_backend", ""))),
        ("chat_provider_combo", list(provider_labels.values()), provider_labels.get(str(session.get("chat_provider", "")).strip().lower(), session.get("chat_provider", ""))),
        ("musetalk_vram_combo", ["Quality", "Balanced", "Low VRAM", "Very Low VRAM"], str(session.get("musetalk_vram_mode", "") or "").replace("_", " ").title().replace("Vram", "VRAM")),
        (
            "musetalk_avatar_pack_combo",
            [str(item.get("label") or "").strip() for item in avatar_pack_options] or [str(session.get("musetalk_avatar_pack_id", "") or "No avatar packs found")],
            next(
                (
                    str(item.get("label") or "").strip()
                    for item in avatar_pack_options
                    if str(item.get("id") or "").strip() == str(session.get("musetalk_avatar_pack_id", "") or "").strip()
                ),
                session.get("musetalk_avatar_pack_id", ""),
            ),
        ),
        (
            "chat_overflow_policy_combo",
            ["Rolling Window", "Truncate Middle", "Stop At Limit"],
            {
                "rolling_window": "Rolling Window",
                "truncate_middle": "Truncate Middle",
                "stop_at_limit": "Stop At Limit",
            }.get(str(session.get("chat_context_overflow_policy", "rolling_window") or "rolling_window").strip(), session.get("chat_context_overflow_policy", "")),
        ),
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
        ("chat_context_window_spin", session.get("chat_context_window_messages")),
        ("stored_chat_history_limit_spin", session.get("stored_chat_history_limit")),
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


def _bind_ui_shell_host_core_controls(window, sensory_providers=None):
    _configure_ui_shell_service_dependencies()
    session = dict(_read_ui_shell_session_snapshot() or {})
    audio_devices = _ui_shell_audio_device_labels()
    avatar_pack_options = _ui_shell_musetalk_avatar_pack_options(session)
    visual_reply_service = _UiShellVisualReplyService(window)
    visual_reply_snapshot = dict(visual_reply_service.settings_snapshot() or {})
    sensory_options = _ui_shell_sensory_source_options(sensory_providers=sensory_providers, selected_value=session.get("sensory_feedback_source", "off"))
    default_max_response_tokens = 600

    audio_input_combo = _ui_shell_find_object(window, "audio_input_device_combo")
    audio_output_combo = _ui_shell_find_object(window, "audio_output_device_combo")
    input_mode_combo = _ui_shell_find_object(window, "input_mode_combo")
    input_role_combo = _ui_shell_find_object(window, "input_role_combo")
    stream_mode_combo = _ui_shell_find_object(window, "stream_mode_combo")
    musetalk_vram_combo = _ui_shell_find_object(window, "musetalk_vram_combo")
    musetalk_avatar_pack_combo = _ui_shell_find_object(window, "musetalk_avatar_pack_combo")
    context_window_spin = _ui_shell_find_object(window, "chat_context_window_spin")
    stored_history_spin = _ui_shell_find_object(window, "stored_chat_history_limit_spin")
    overflow_combo = _ui_shell_find_object(window, "chat_overflow_policy_combo")
    allow_proactive_checkbox = _ui_shell_find_object(window, "allow_proactive_checkbox")
    require_first_user_checkbox = _ui_shell_find_object(window, "require_first_user_checkbox")
    listen_idle_window_spin = _ui_shell_find_object(window, "listen_idle_window_spin")
    proactive_delay_spin = _ui_shell_find_object(window, "proactive_delay_spin")
    limit_response_checkbox = _ui_shell_find_object(window, "limit_response_checkbox")
    max_response_tokens_spin = _ui_shell_find_object(window, "max_response_tokens_spin")
    sensory_feedback_source_combo = _ui_shell_find_object(window, "sensory_feedback_source_combo")
    sensory_feedback_interval_spin = _ui_shell_find_object(window, "sensory_feedback_interval_spin")
    sensory_pingpong_checkbox = _ui_shell_find_object(window, "sensory_pingpong_checkbox")
    sensory_allow_hidden_proactive_checkbox = _ui_shell_find_object(window, "sensory_allow_hidden_proactive_checkbox")
    sensory_allow_hidden_visual_checkbox = _ui_shell_find_object(window, "sensory_allow_hidden_visual_checkbox")
    sensory_pingpong_history_spin = _ui_shell_find_object(window, "sensory_pingpong_history_spin")
    visual_reply_mode_combo = _ui_shell_find_object(window, "visual_reply_mode_combo")
    visual_reply_provider_combo = _ui_shell_find_object(window, "visual_reply_provider_combo")
    visual_reply_size_combo = _ui_shell_find_object(window, "visual_reply_size_combo")
    visual_reply_model_edit = _ui_shell_find_object(window, "visual_reply_model_edit")
    visual_reply_auto_show_checkbox = _ui_shell_find_object(window, "visual_reply_auto_show_checkbox")
    visual_reply_hint = _ui_shell_find_object(window, "visual_reply_hint")

    if audio_input_combo is not None:
        _ui_shell_combo_set_items(audio_input_combo, list(audio_devices.get("inputs") or ["Default Input"]))
        _ui_shell_combo_select_label(audio_input_combo, session.get("audio_input_device", "Default Input"))
        audio_input_combo.setToolTip("Shell-local audio input preview. No microphone capture is started.")
    if audio_output_combo is not None:
        _ui_shell_combo_set_items(audio_output_combo, list(audio_devices.get("outputs") or ["Default Output"]))
        _ui_shell_combo_select_label(audio_output_combo, session.get("audio_output_device", "Default Output"))
        audio_output_combo.setToolTip("Shell-local audio output preview. No playback device is opened.")
    if input_mode_combo is not None and hasattr(input_mode_combo, "setToolTip"):
        input_mode_combo.setToolTip("Shell-local input-mode preview. Changes update only the shell status line.")
    if input_role_combo is not None and hasattr(input_role_combo, "setToolTip"):
        input_role_combo.setToolTip("Shell-local input-role preview. Changes update only the shell status line.")
    if stream_mode_combo is not None and hasattr(stream_mode_combo, "setToolTip"):
        stream_mode_combo.setToolTip("Shell-local stream-mode preview. Changes update only the shell status line.")
    if musetalk_vram_combo is not None and hasattr(musetalk_vram_combo, "setToolTip"):
        musetalk_vram_combo.setToolTip("Shell-local MuseTalk VRAM preview. No runtime adapter is reconfigured.")
    if musetalk_avatar_pack_combo is not None and hasattr(musetalk_avatar_pack_combo, "clear"):
        saved_pack_id = str(session.get("musetalk_avatar_pack_id", "") or "").strip()
        musetalk_avatar_pack_combo.blockSignals(True)
        try:
            musetalk_avatar_pack_combo.clear()
            for item in avatar_pack_options:
                label = str(item.get("label") or item.get("id") or "").strip()
                pack_id = str(item.get("id") or "").strip()
                if not label:
                    continue
                musetalk_avatar_pack_combo.addItem(label, pack_id)
            if musetalk_avatar_pack_combo.count() <= 0:
                musetalk_avatar_pack_combo.addItem("No avatar packs found", "")
            index = musetalk_avatar_pack_combo.findData(saved_pack_id)
            musetalk_avatar_pack_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            musetalk_avatar_pack_combo.blockSignals(False)
        musetalk_avatar_pack_combo.setToolTip("Shell-local MuseTalk avatar-pack preview. No adapter or worker is started.")
    if context_window_spin is not None and hasattr(context_window_spin, "setToolTip"):
        context_window_spin.setToolTip("Shell-local chat-context preview. Changes are not saved or applied to runtime.")
    if stored_history_spin is not None and hasattr(stored_history_spin, "setToolTip"):
        stored_history_spin.setToolTip("Shell-local stored-history preview. Changes are not saved or applied to runtime.")
    if overflow_combo is not None and hasattr(overflow_combo, "setToolTip"):
        overflow_combo.setToolTip("Shell-local overflow-policy preview. Changes are not saved or applied to runtime.")
    if allow_proactive_checkbox is not None:
        _ui_shell_set_checked(allow_proactive_checkbox, session.get("allow_proactive_replies", True))
        allow_proactive_checkbox.setToolTip("Shell-local proactive-reply preview. Changes are not saved or applied to runtime.")
    if require_first_user_checkbox is not None:
        _ui_shell_set_checked(require_first_user_checkbox, session.get("require_first_user_before_proactive", False))
        require_first_user_checkbox.setToolTip("Shell-local proactive gating preview. Changes are not saved or applied to runtime.")
    if _ui_shell_set_double_value(listen_idle_window_spin, session.get("listen_idle_window_seconds", 5.0)) and listen_idle_window_spin is not None:
        listen_idle_window_spin.setToolTip("Shell-local idle-window preview. Changes are not saved or applied to runtime.")
    if _ui_shell_set_double_value(proactive_delay_spin, session.get("proactive_delay_seconds", 10.0)) and proactive_delay_spin is not None:
        proactive_delay_spin.setToolTip("Shell-local proactive-delay preview. Changes are not saved or applied to runtime.")
    if limit_response_checkbox is not None:
        _ui_shell_set_checked(limit_response_checkbox, session.get("limit_response_length", False))
        limit_response_checkbox.setToolTip("Shell-local response-length preview. Changes are not saved or applied to runtime.")
    if _ui_shell_set_spin_value(max_response_tokens_spin, session.get("max_response_tokens", default_max_response_tokens)) and max_response_tokens_spin is not None:
        max_response_tokens_spin.setToolTip("Shell-local max-response preview. Changes are not saved or applied to runtime.")
        try:
            max_response_tokens_spin.setEnabled(bool(limit_response_checkbox.isChecked()) if limit_response_checkbox is not None and hasattr(limit_response_checkbox, "isChecked") else False)
        except Exception:
            pass
    if sensory_feedback_source_combo is not None:
        sensory_feedback_source_combo.blockSignals(True)
        try:
            sensory_feedback_source_combo.clear()
            for label, value in sensory_options:
                sensory_feedback_source_combo.addItem(label, value)
            requested = str(session.get("sensory_feedback_source", "off") or "off").strip().lower()
            index = sensory_feedback_source_combo.findData(requested)
            sensory_feedback_source_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            sensory_feedback_source_combo.blockSignals(False)
        sensory_feedback_source_combo.setToolTip("Shell-local sensory-source preview. Capture and hidden-loop delivery remain deferred.")
    if _ui_shell_set_double_value(sensory_feedback_interval_spin, session.get("sensory_feedback_interval_seconds", 7.0)) and sensory_feedback_interval_spin is not None:
        sensory_feedback_interval_spin.setToolTip("Shell-local sensory refresh preview. Changes are not saved or applied to runtime.")
    if sensory_pingpong_checkbox is not None:
        _ui_shell_set_checked(sensory_pingpong_checkbox, session.get("sensory_pingpong_enabled", False))
        sensory_pingpong_checkbox.setToolTip("Shell-local hidden PING/PONG preview. No hidden runtime loop is started.")
    if sensory_allow_hidden_proactive_checkbox is not None:
        _ui_shell_set_checked(sensory_allow_hidden_proactive_checkbox, session.get("sensory_allow_hidden_proactive_speech", False))
        sensory_allow_hidden_proactive_checkbox.setToolTip("Shell-local sensory speech preview. Changes are not saved or applied to runtime.")
    if sensory_allow_hidden_visual_checkbox is not None:
        _ui_shell_set_checked(sensory_allow_hidden_visual_checkbox, session.get("sensory_allow_hidden_visual_generation", False))
        sensory_allow_hidden_visual_checkbox.setToolTip("Shell-local sensory image-generation preview. Changes are not saved or applied to runtime.")
    if _ui_shell_set_spin_value(sensory_pingpong_history_spin, session.get("sensory_pingpong_history_depth", 3)) and sensory_pingpong_history_spin is not None:
        sensory_pingpong_history_spin.setToolTip("Shell-local PING/PONG history preview. Changes are not saved or applied to runtime.")
    if visual_reply_mode_combo is not None:
        _ui_shell_combo_set_items(visual_reply_mode_combo, list(visual_reply_service.mode_labels()))
        _ui_shell_combo_select_label(visual_reply_mode_combo, visual_reply_service.mode_label_from_value(visual_reply_snapshot.get("mode_value", "auto")))
    if visual_reply_provider_combo is not None:
        _ui_shell_combo_set_items(visual_reply_provider_combo, list(visual_reply_service.provider_labels()))
        _ui_shell_combo_select_label(visual_reply_provider_combo, visual_reply_service.provider_label_from_value(visual_reply_snapshot.get("provider_value", "openai")))
    if visual_reply_size_combo is not None:
        _ui_shell_combo_set_items(visual_reply_size_combo, list(visual_reply_service.size_labels()))
        _ui_shell_combo_select_label(visual_reply_size_combo, visual_reply_service.size_label_from_value(visual_reply_snapshot.get("size_value", "1024x1024")))
    if visual_reply_model_edit is not None and hasattr(visual_reply_model_edit, "setText"):
        visual_reply_model_edit.setText(str(visual_reply_snapshot.get("model_name", "gpt-image-1") or "gpt-image-1"))
    if visual_reply_auto_show_checkbox is not None:
        _ui_shell_set_checked(visual_reply_auto_show_checkbox, visual_reply_snapshot.get("auto_show", True))
    visual_reply_service.attach_settings_widgets(
        mode_combo=visual_reply_mode_combo,
        provider_combo=visual_reply_provider_combo,
        size_combo=visual_reply_size_combo,
        model_edit=visual_reply_model_edit,
        auto_show_checkbox=visual_reply_auto_show_checkbox,
        hint_label=visual_reply_hint,
    )
    visual_reply_service.refresh_hint()

    def refresh_status():
        return _ui_shell_refresh_host_core_status(window)

    bound = []

    def bind_combo(combo, attr_name, message_factory, on_changed=None):
        if combo is None or not hasattr(combo, "currentIndexChanged"):
            return
        bound.append(str(combo.objectName() if hasattr(combo, "objectName") else attr_name))
        if getattr(combo, attr_name, False):
            return
        on_changed_callback = on_changed

        def handle(_index=None):
            if callable(on_changed_callback):
                on_changed_callback(_index)
            refresh_status()
            _ui_shell_append_console(window, message_factory())

        combo.currentIndexChanged.connect(handle)
        setattr(combo, attr_name, True)

    def bind_spin(widget, attr_name, message_factory):
        if widget is None or not hasattr(widget, "valueChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_changed(_value=None):
            refresh_status()
            _ui_shell_append_console(window, message_factory())

        widget.valueChanged.connect(on_changed)
        setattr(widget, attr_name, True)

    def bind_check(widget, attr_name, message_factory, on_changed=None):
        if widget is None or not hasattr(widget, "toggled"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_checked=False):
            if callable(on_changed):
                on_changed(bool(widget.isChecked()) if hasattr(widget, "isChecked") else bool(_checked))
            refresh_status()
            _ui_shell_append_console(window, message_factory())

        widget.toggled.connect(handle)
        setattr(widget, attr_name, True)

    bind_combo(
        audio_input_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Audio input preview: {str(audio_input_combo.currentText() or 'Default Input').strip()} selected; capture remains deferred.",
    )
    bind_combo(
        audio_output_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Audio output preview: {str(audio_output_combo.currentText() or 'Default Output').strip()} selected; playback remains deferred.",
    )
    bind_combo(
        input_mode_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Input Mode preview: {str(input_mode_combo.currentText() or 'Voice Activation').strip()} selected; runtime input handling remains disconnected.",
    )
    bind_combo(
        input_role_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Input Role preview: {str(input_role_combo.currentText() or 'User Message').strip()} selected; runtime message routing remains disconnected.",
    )
    bind_combo(
        stream_mode_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Stream Mode preview: {str(stream_mode_combo.currentText() or 'Off').strip()} selected; live provider streaming remains deferred.",
    )
    bind_combo(
        musetalk_vram_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] MuseTalk VRAM preview: {str(musetalk_vram_combo.currentText() or 'Quality').strip()} selected; no runtime reconfiguration was applied.",
    )
    bind_combo(
        musetalk_avatar_pack_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] MuseTalk avatar pack preview: {str(musetalk_avatar_pack_combo.currentText() or 'No avatar packs found').strip()} selected; no adapter was rebuilt.",
    )
    bind_combo(
        overflow_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Chat overflow preview: {str(overflow_combo.currentText() or 'Rolling Window').strip()} selected; chat-context files and runtime limits remain unchanged.",
    )
    bind_spin(
        context_window_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Chat context window preview: {int(context_window_spin.value()) if hasattr(context_window_spin, 'value') else 20} message(s); runtime context remains unchanged.",
    )
    bind_spin(
        stored_history_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Stored history preview: {int(stored_history_spin.value()) if hasattr(stored_history_spin, 'value') else 0} message(s); no session file was updated.",
    )
    bind_check(
        allow_proactive_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Proactive replies preview: {'enabled' if allow_proactive_checkbox.isChecked() else 'disabled'}; runtime behavior remains unchanged.",
    )
    bind_check(
        require_first_user_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] First-user gate preview: {'enabled' if require_first_user_checkbox.isChecked() else 'disabled'}; runtime behavior remains unchanged.",
    )
    bind_spin(
        listen_idle_window_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Idle wait preview: {float(listen_idle_window_spin.value()) if hasattr(listen_idle_window_spin, 'value') else 5.0:.1f}s; runtime behavior remains unchanged.",
    )
    bind_spin(
        proactive_delay_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Proactive delay preview: {float(proactive_delay_spin.value()) if hasattr(proactive_delay_spin, 'value') else 10.0:.1f}s; runtime behavior remains unchanged.",
    )
    bind_check(
        limit_response_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Response limit preview: {'enabled' if limit_response_checkbox.isChecked() else 'disabled'}; runtime behavior remains unchanged.",
        on_changed=lambda checked: max_response_tokens_spin.setEnabled(bool(checked)) if max_response_tokens_spin is not None and hasattr(max_response_tokens_spin, "setEnabled") else None,
    )
    bind_spin(
        max_response_tokens_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Max response preview: {int(max_response_tokens_spin.value()) if hasattr(max_response_tokens_spin, 'value') else default_max_response_tokens} token(s); runtime behavior remains unchanged.",
    )
    bind_combo(
        sensory_feedback_source_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Sensory source preview: {str(sensory_feedback_source_combo.currentText() or 'Off').strip()} selected; capture remains deferred.",
    )
    bind_spin(
        sensory_feedback_interval_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Sensory refresh preview: {float(sensory_feedback_interval_spin.value()) if hasattr(sensory_feedback_interval_spin, 'value') else 7.0:.1f}s; hidden capture remains deferred.",
    )
    bind_check(
        sensory_pingpong_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Hidden PING/PONG preview: {'enabled' if sensory_pingpong_checkbox.isChecked() else 'disabled'}; no hidden loop was started.",
    )
    bind_check(
        sensory_allow_hidden_proactive_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Hidden proactive speech preview: {'enabled' if sensory_allow_hidden_proactive_checkbox.isChecked() else 'disabled'}; no runtime behavior changed.",
    )
    bind_check(
        sensory_allow_hidden_visual_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Hidden visual generation preview: {'enabled' if sensory_allow_hidden_visual_checkbox.isChecked() else 'disabled'}; no runtime behavior changed.",
    )
    bind_spin(
        sensory_pingpong_history_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Hidden PING/PONG history preview: {int(sensory_pingpong_history_spin.value()) if hasattr(sensory_pingpong_history_spin, 'value') else 3}; runtime behavior remains unchanged.",
    )
    bind_combo(
        visual_reply_mode_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Visual Reply mode preview: {str(visual_reply_mode_combo.currentText() or 'Auto').strip()} selected; no image generation was started.",
        on_changed=lambda _checked=None: (visual_reply_service.apply_mode(visual_reply_mode_combo.currentText()), visual_reply_service.refresh_hint()),
    )
    bind_combo(
        visual_reply_provider_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Visual Reply provider preview: {str(visual_reply_provider_combo.currentText() or 'OpenAI').strip()} selected; no network call was made.",
        on_changed=lambda _checked=None: (visual_reply_service.apply_provider(visual_reply_provider_combo.currentText()), visual_reply_service.refresh_hint()),
    )
    bind_combo(
        visual_reply_size_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Visual Reply size preview: {str(visual_reply_size_combo.currentText() or '1024x1024').strip()} selected; no image generation was started.",
        on_changed=lambda _checked=None: (visual_reply_service.apply_size(visual_reply_size_combo.currentText()), visual_reply_service.refresh_hint()),
    )
    bind_check(
        visual_reply_auto_show_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Visual Reply auto-show preview: {'enabled' if visual_reply_auto_show_checkbox.isChecked() else 'disabled'}; dock behavior remains shell-local.",
        on_changed=lambda checked: (visual_reply_service.apply_auto_show(checked), visual_reply_service.refresh_hint()),
    )
    if visual_reply_model_edit is not None and hasattr(visual_reply_model_edit, "editingFinished"):
        bound.append(str(visual_reply_model_edit.objectName() if hasattr(visual_reply_model_edit, "objectName") else "visual_reply_model_edit"))
        if not getattr(visual_reply_model_edit, "_nc_ui_shell_host_core_bound", False):
            def on_visual_model_changed():
                visual_reply_service.apply_model()
                refresh_status()
                _ui_shell_append_console(window, f"[UI Shell] Visual Reply model preview: {str(visual_reply_model_edit.text() or 'gpt-image-1').strip()} selected; no image generation was started.")
            visual_reply_model_edit.editingFinished.connect(on_visual_model_changed)
            setattr(visual_reply_model_edit, "_nc_ui_shell_host_core_bound", True)

    refresh_status()
    return {
        "bound": bound,
        "audio_inputs": max(0, len(list(audio_devices.get("inputs") or [])) - 1),
        "audio_outputs": max(0, len(list(audio_devices.get("outputs") or [])) - 1),
        "avatar_packs": len(avatar_pack_options),
        "sensory_providers": len(list(sensory_providers or [])),
    }




def _bind_ui_shell_dry_run_controls(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    service = _ui_shell_dry_run_service(window)
    bound = []
    deferred = ["btn_dry_run_start", "btn_dry_run_stop"]

    target_spin = _ui_shell_find_object(window, "dry_run_target_spin")
    auto_replies_checkbox = _ui_shell_find_object(window, "dry_run_auto_replies_checkbox")
    start_button = _ui_shell_find_object(window, "btn_dry_run_start")
    stop_button = _ui_shell_find_object(window, "btn_dry_run_stop")
    apply_button = _ui_shell_find_object(window, "btn_dry_run_apply")
    status_label = _ui_shell_find_object(window, "dry_run_status_label")
    summary_edit = _ui_shell_find_object(window, "dry_run_summary")

    if target_spin is not None:
        _ui_shell_set_spin_value(target_spin, int(session.get("dry_run_target_samples", 0) or 0))
        if hasattr(target_spin, "setToolTip"):
            target_spin.setToolTip("Shell-local Dry Run preview target. No profiling session is started.")
    if auto_replies_checkbox is not None:
        _ui_shell_set_checked(auto_replies_checkbox, bool(session.get("dry_run_auto_replies", True)))
        if hasattr(auto_replies_checkbox, "setToolTip"):
            auto_replies_checkbox.setToolTip("Shell-local Dry Run hands-free preview. No profiling session is started.")
    if summary_edit is not None:
        try:
            summary_edit.setReadOnly(True)
        except Exception:
            pass
        if hasattr(summary_edit, "setToolTip"):
            summary_edit.setToolTip("Shell-local Dry Run preview summary. No profiling metrics are collected here.")

    def refresh_preview():
        snapshot = service.refresh_preview()
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setText(str(snapshot.get("status_text") or "Dry Run idle."))
        if summary_edit is not None and hasattr(summary_edit, "setPlainText"):
            summary_edit.setPlainText(str(snapshot.get("summary_text") or ""))
        if stop_button is not None and hasattr(stop_button, "setEnabled"):
            stop_button.setEnabled(str(snapshot.get("state") or "idle") == "armed")
        if start_button is not None and hasattr(start_button, "setEnabled"):
            start_button.setEnabled(str(snapshot.get("state") or "idle") != "armed")
        if apply_button is not None and hasattr(apply_button, "setEnabled"):
            apply_button.setEnabled(bool(snapshot.get("has_recommendation")))
        return snapshot

    def bind_spin(widget, attr_name, on_log):
        if widget is None or not hasattr(widget, "valueChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_value=None):
            refresh_preview()
            _ui_shell_append_console(window, on_log())

        widget.valueChanged.connect(handle)
        setattr(widget, attr_name, True)

    def bind_check(widget, attr_name, on_log):
        if widget is None or not hasattr(widget, "toggled"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_checked=False):
            refresh_preview()
            _ui_shell_append_console(window, on_log())

        widget.toggled.connect(handle)
        setattr(widget, attr_name, True)

    def bind_button(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "clicked"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_checked=False):
            handler()

        widget.clicked.connect(handle)
        setattr(widget, attr_name, True)

    bind_spin(
        target_spin,
        "_nc_ui_shell_dry_run_bound",
        lambda: f"[UI Shell] Dry Run target preview: {int(target_spin.value()) if hasattr(target_spin, 'value') else 0} sample(s); no profiling session was started.",
    )
    bind_check(
        auto_replies_checkbox,
        "_nc_ui_shell_dry_run_bound",
        lambda: f"[UI Shell] Dry Run hands-free preview: {'enabled' if auto_replies_checkbox.isChecked() else 'disabled'}; no profiling session was started.",
    )
    bind_button(
        start_button,
        "_nc_ui_shell_dry_run_bound",
        lambda: (
            service.start_session(),
            refresh_preview(),
            _ui_shell_append_console(window, "[UI Shell] Dry Run arm request deferred; no engine, model, or profiling worker was started."),
        ),
    )
    bind_button(
        stop_button,
        "_nc_ui_shell_dry_run_bound",
        lambda: (
            service.stop_session(),
            refresh_preview(),
            _ui_shell_append_console(window, "[UI Shell] Dry Run stop request deferred; no profiling session was running."),
        ),
    )

    def apply_recommendation():
        result = service.apply_recommendation()
        refresh_preview()
        if result.get("applied"):
            deferred_keys = [str(key) for key in list(result.get("deferred_keys") or []) if str(key).strip()]
            deferred_suffix = f" Deferred keys: {', '.join(deferred_keys)}." if deferred_keys else ""
            _ui_shell_append_console(window, f"[UI Shell] Dry Run recommendation preview applied to the shell-visible subset only.{deferred_suffix}")
        else:
            _ui_shell_append_console(window, f"[UI Shell] {result.get('message') or 'No saved Dry Run recommendation is available.'}")

    bind_button(apply_button, "_nc_ui_shell_dry_run_bound", apply_recommendation)

    refresh_preview()
    return {
        "bound": bound,
        "deferred": sorted(set(deferred)),
        "has_recommendation": bool(service.snapshot().get("has_recommendation")),
    }


def _bind_ui_shell_persona_body_vam_controls(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    service = _ui_shell_persona_avatar_service(window)
    bound = []
    deferred = [
        "btn_body_save",
        "btn_body_save_as",
        "btn_body_delete",
        "btn_hand_doctor",
        "btn_vseeface_hide_interface",
        "btn_start_vam_desktop",
        "btn_start_vam_vr",
        "btn_vam_hide_interface",
    ]

    voice_combo = _ui_shell_find_object(window, "voice_combo")
    emotional_text = _ui_shell_find_object(window, "emotional_text")
    system_prompt_text = _ui_shell_find_object(window, "system_prompt_text")
    apply_text_button = _ui_shell_find_object(window, "btn_apply_text_config")
    body_combo = _ui_shell_find_object(window, "body_combo")
    emotion_combo = _ui_shell_find_object(window, "emotion_combo")
    live_sync_checkbox = _ui_shell_find_object(window, "live_sync_checkbox")
    btn_body_load = _ui_shell_find_object(window, "btn_body_load")
    btn_body_save = _ui_shell_find_object(window, "btn_body_save")
    btn_body_save_as = _ui_shell_find_object(window, "btn_body_save_as")
    btn_body_delete = _ui_shell_find_object(window, "btn_body_delete")
    btn_hand_doctor = _ui_shell_find_object(window, "btn_hand_doctor")
    btn_vseeface_hide_interface = _ui_shell_find_object(window, "btn_vseeface_hide_interface")
    vam_root_edit = _ui_shell_find_object(window, "vam_root_edit")
    vam_bridge_root_edit = _ui_shell_find_object(window, "vam_bridge_root_edit")
    vam_target_atom_uid_edit = _ui_shell_find_object(window, "vam_target_atom_uid_edit")
    vam_target_storable_id_edit = _ui_shell_find_object(window, "vam_target_storable_id_edit")
    vam_vmc_host_edit = _ui_shell_find_object(window, "vam_vmc_host_edit")
    vam_vmc_port_spin = _ui_shell_find_object(window, "vam_vmc_port_spin")
    vam_vmc_enabled_checkbox = _ui_shell_find_object(window, "vam_vmc_enabled_checkbox")
    vam_bridge_enabled_checkbox = _ui_shell_find_object(window, "vam_bridge_enabled_checkbox")
    vam_play_audio_in_vam_checkbox = _ui_shell_find_object(window, "vam_play_audio_in_vam_checkbox")
    vam_timeline_auto_resume_checkbox = _ui_shell_find_object(window, "vam_timeline_auto_resume_checkbox")
    btn_start_vam_desktop = _ui_shell_find_object(window, "btn_start_vam_desktop")
    btn_start_vam_vr = _ui_shell_find_object(window, "btn_start_vam_vr")
    btn_vam_hide_interface = _ui_shell_find_object(window, "btn_vam_hide_interface")

    if voice_combo is not None:
        _ui_shell_combo_set_items(voice_combo, _ui_shell_voice_options(window))
        _ui_shell_combo_select_label(voice_combo, str(session.get("voice_file", "") or ""))
        voice_combo.setToolTip("Shell-local voice preview. No TTS backend is reloaded.")
    if emotional_text is not None and hasattr(emotional_text, "setPlainText"):
        emotional_text.setPlainText(str(session.get("emotional_instructions", "") or ""))
        emotional_text.setToolTip("Shell-local persona preview. Changes are not saved or applied to runtime.")
    if system_prompt_text is not None and hasattr(system_prompt_text, "setPlainText"):
        system_prompt_text.setPlainText(str(session.get("system_prompt", "") or ""))
        system_prompt_text.setToolTip("Shell-local system-prompt preview. Changes are not saved or applied to runtime.")

    configs = _ui_shell_refresh_body_combo(window, preferred_name=str(session.get("last_body", "") or ""))
    if emotion_combo is not None:
        _ui_shell_combo_set_items(emotion_combo, list(UI_SHELL_BODY_EMOTIONS))
        _ui_shell_combo_select_label(emotion_combo, "Neutral")
        emotion_combo.setToolTip("Shell-local emotion preview. Changes update only the visible shell sliders.")
    if live_sync_checkbox is not None:
        _ui_shell_set_checked(live_sync_checkbox, bool(session.get("live_sync", False)))
        live_sync_checkbox.setToolTip("Shell-local body sync preview. No avatar runtime mode changes occur.")
    for key in UI_SHELL_BODY_POSE_SPECS:
        _ui_shell_configure_body_slider(window, key)
    selected_body = str(session.get("last_body", "") or "").strip()
    if selected_body and selected_body in configs:
        _ui_shell_load_body_preview(window, selected_body)
    else:
        _ui_shell_set_selected_body_profile(window, {})
        _ui_shell_apply_body_profile_for_emotion(window)

    initial_vam_root = _ui_shell_normalize_vam_root(str(session.get("vam_root", "") or UI_SHELL_DEFAULT_LOCAL_VAM_ROOT))
    if vam_root_edit is not None and hasattr(vam_root_edit, "setText"):
        vam_root_edit.setText(initial_vam_root)
        vam_root_edit.setToolTip("Shell-local VaM root preview. Launch and bridge behavior remain deferred.")
    if vam_bridge_root_edit is not None and hasattr(vam_bridge_root_edit, "setText"):
        vam_bridge_root_edit.setText(_ui_shell_derive_vam_bridge_root(initial_vam_root))
        vam_bridge_root_edit.setReadOnly(True)
        vam_bridge_root_edit.setToolTip("Derived from VaM Root in shell preview.")
    if vam_target_atom_uid_edit is not None and hasattr(vam_target_atom_uid_edit, "setText"):
        vam_target_atom_uid_edit.setText(str(session.get("vam_target_atom_uid", "Person") or "Person"))
        vam_target_atom_uid_edit.setToolTip("Shell-local VaM target preview. Changes are not saved or applied to runtime.")
    if vam_target_storable_id_edit is not None and hasattr(vam_target_storable_id_edit, "setText"):
        vam_target_storable_id_edit.setText(str(session.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"))
        vam_target_storable_id_edit.setToolTip("Shell-local VaM target preview. Changes are not saved or applied to runtime.")
    if vam_vmc_host_edit is not None and hasattr(vam_vmc_host_edit, "setText"):
        vam_vmc_host_edit.setText(str(session.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1"))
        vam_vmc_host_edit.setToolTip("Shell-local VaM VMC host preview. No socket is opened.")
    if vam_vmc_port_spin is not None:
        _ui_shell_set_spin_value(vam_vmc_port_spin, int(session.get("vam_vmc_port", 39539) or 39539))
        vam_vmc_port_spin.setToolTip("Shell-local VaM VMC port preview. No socket is opened.")
    for object_name, default_value, detail in (
        ("vam_vmc_enabled_checkbox", bool(session.get("vam_vmc_enabled", True)), "Shell-local VaM VMC preview. No runtime connector is started."),
        ("vam_bridge_enabled_checkbox", bool(session.get("vam_bridge_enabled", True)), "Shell-local VaM bridge preview. No file bridge is started."),
        ("vam_play_audio_in_vam_checkbox", bool(session.get("vam_play_audio_in_vam", False)), "Shell-local VaM audio preview. No audio routing changes occur."),
        ("vam_timeline_auto_resume_checkbox", bool(session.get("vam_timeline_auto_resume", True)), "Shell-local VaM timeline preview. No runtime bridge is started."),
    ):
        widget = _ui_shell_find_object(window, object_name)
        if widget is not None:
            _ui_shell_set_checked(widget, default_value)
            widget.setToolTip(detail)

    _ui_shell_refresh_vam_status_labels(window)

    def bind_combo(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "currentIndexChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_changed(_index=None):
            handler()

        widget.currentIndexChanged.connect(on_changed)
        setattr(widget, attr_name, True)

    def bind_spin(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "valueChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_changed(_value=None):
            handler()

        widget.valueChanged.connect(on_changed)
        setattr(widget, attr_name, True)

    def bind_check(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "toggled"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_changed(_checked=False):
            handler()

        widget.toggled.connect(on_changed)
        setattr(widget, attr_name, True)

    def bind_button(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "clicked"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_clicked(_checked=False):
            handler()

        widget.clicked.connect(on_clicked)
        setattr(widget, attr_name, True)

    def bind_edit(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "editingFinished"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_finished():
            handler()

        widget.editingFinished.connect(on_finished)
        setattr(widget, attr_name, True)

    bind_combo(
        voice_combo,
        "_nc_ui_shell_persona_avatar_bound",
        lambda: _ui_shell_append_console(window, f"[UI Shell] Voice preview: {_ui_shell_current_voice_file(window) or 'No .wav found'} selected; no TTS backend was reloaded."),
    )
    bind_button(
        apply_text_button,
        "_nc_ui_shell_persona_avatar_bound",
        lambda: (
            service.apply_persona(),
            _ui_shell_append_console(window, f"[UI Shell] Persona/body/VaM preview applied locally only. Voice={_ui_shell_current_voice_file(window) or '<none>'}, body={_ui_shell_selected_body_name(window) or '<none>'}."),
        ),
    )
    bind_combo(
        body_combo,
        "_nc_ui_shell_persona_avatar_bound",
        lambda: _ui_shell_append_console(window, f"[UI Shell] Body preset selected: {_ui_shell_selected_body_name(window) or 'No Configs'}. Use Load to apply the shell-safe preview."),
    )
    bind_button(
        btn_body_load,
        "_nc_ui_shell_persona_avatar_bound",
        lambda: (
            _ui_shell_append_console(window, f"[UI Shell] {_ui_shell_load_body_preview(window).get('message') or 'No body preset selected.'}")
        ),
    )
    bind_button(btn_body_save, "_nc_ui_shell_persona_avatar_bound", lambda: _ui_shell_append_console(window, "[UI Shell] Body save is deferred in shell preview; no files were written."))
    bind_button(btn_body_save_as, "_nc_ui_shell_persona_avatar_bound", lambda: _ui_shell_append_console(window, "[UI Shell] Body save-as is deferred in shell preview; no files were written."))
    bind_button(btn_body_delete, "_nc_ui_shell_persona_avatar_bound", lambda: _ui_shell_append_console(window, "[UI Shell] Body delete is deferred in shell preview; no files were removed."))
    bind_combo(
        emotion_combo,
        "_nc_ui_shell_persona_avatar_bound",
        lambda: (
            _ui_shell_apply_body_profile_for_emotion(window),
            _ui_shell_append_console(window, f"[UI Shell] Body emotion preview: {_ui_shell_combo_text_value(window, 'emotion_combo', 'Neutral')} selected; visible shell sliders were updated."),
        ),
    )
    bind_check(
        live_sync_checkbox,
        "_nc_ui_shell_persona_avatar_bound",
        lambda: _ui_shell_append_console(window, f"[UI Shell] Live Sync preview: {'enabled' if _ui_shell_checkbox_value(window, 'live_sync_checkbox', False) else 'disabled'}; avatar runtime mode remains unchanged."),
    )
    bind_button(btn_hand_doctor, "_nc_ui_shell_persona_avatar_bound", lambda: _ui_shell_append_console(window, "[UI Shell] Hand Doctor is deferred in shell preview; no debugger window was opened."))
    bind_button(btn_vseeface_hide_interface, "_nc_ui_shell_persona_avatar_bound", lambda: _ui_shell_append_console(window, "[UI Shell] VSeeFace interface-hide action is deferred in shell preview."))

    for key in UI_SHELL_BODY_POSE_SPECS:
        slider = _ui_shell_body_slider_widget(window, key)
        bind_spin(
            slider,
            "_nc_ui_shell_persona_avatar_bound",
            lambda key_name=key, slider_widget=slider: (
                _ui_shell_update_body_label(window, key_name, _ui_shell_body_slider_raw_to_value(key_name, slider_widget.value() if slider_widget is not None and hasattr(slider_widget, 'value') else 0)),
                _ui_shell_append_console(window, f"[UI Shell] Body pose preview: {str(_ui_shell_body_pose_spec(key_name).get('title') or key_name)} -> {_ui_shell_format_body_value(key_name, _ui_shell_body_slider_raw_to_value(key_name, slider_widget.value() if slider_widget is not None and hasattr(slider_widget, 'value') else 0))}; runtime pose state remains unchanged."),
            ),
        )

    def on_vam_root_changed():
        normalized_root = _ui_shell_normalize_vam_root(_ui_shell_line_edit_value(window, "vam_root_edit", UI_SHELL_DEFAULT_LOCAL_VAM_ROOT))
        if vam_root_edit is not None and hasattr(vam_root_edit, "setText"):
            vam_root_edit.setText(normalized_root)
        if vam_bridge_root_edit is not None and hasattr(vam_bridge_root_edit, "setText"):
            vam_bridge_root_edit.setText(_ui_shell_derive_vam_bridge_root(normalized_root))
        _ui_shell_refresh_vam_status_labels(window)
        _ui_shell_append_console(window, f"[UI Shell] VaM root preview: {normalized_root or '<unset>'}; bridge path was derived locally only.")

    def on_vam_text_changed(label, object_name):
        _ui_shell_refresh_vam_status_labels(window)
        _ui_shell_append_console(window, f"[UI Shell] {label} preview: {_ui_shell_line_edit_value(window, object_name)}; runtime bridge settings remain unchanged.")

    def on_vam_check_changed(label, object_name):
        _ui_shell_refresh_vam_status_labels(window)
        _ui_shell_append_console(window, f"[UI Shell] {label} preview: {'enabled' if _ui_shell_checkbox_value(window, object_name, False) else 'disabled'}; no VaM connector was started.")

    bind_edit(vam_root_edit, "_nc_ui_shell_persona_avatar_bound", on_vam_root_changed)
    bind_edit(vam_target_atom_uid_edit, "_nc_ui_shell_persona_avatar_bound", lambda: on_vam_text_changed("VaM target atom UID", "vam_target_atom_uid_edit"))
    bind_edit(vam_target_storable_id_edit, "_nc_ui_shell_persona_avatar_bound", lambda: on_vam_text_changed("VaM target storable ID", "vam_target_storable_id_edit"))
    bind_edit(vam_vmc_host_edit, "_nc_ui_shell_persona_avatar_bound", lambda: on_vam_text_changed("VaM VMC host", "vam_vmc_host_edit"))
    bind_spin(
        vam_vmc_port_spin,
        "_nc_ui_shell_persona_avatar_bound",
        lambda: (
            _ui_shell_refresh_vam_status_labels(window),
            _ui_shell_append_console(window, f"[UI Shell] VaM VMC port preview: {int(vam_vmc_port_spin.value()) if vam_vmc_port_spin is not None and hasattr(vam_vmc_port_spin, 'value') else 39539}; no socket was opened."),
        ),
    )
    bind_check(vam_vmc_enabled_checkbox, "_nc_ui_shell_persona_avatar_bound", lambda: on_vam_check_changed("VaM VMC", "vam_vmc_enabled_checkbox"))
    bind_check(vam_bridge_enabled_checkbox, "_nc_ui_shell_persona_avatar_bound", lambda: on_vam_check_changed("VaM file bridge", "vam_bridge_enabled_checkbox"))
    bind_check(vam_play_audio_in_vam_checkbox, "_nc_ui_shell_persona_avatar_bound", lambda: on_vam_check_changed("VaM in-engine audio", "vam_play_audio_in_vam_checkbox"))
    bind_check(vam_timeline_auto_resume_checkbox, "_nc_ui_shell_persona_avatar_bound", lambda: on_vam_check_changed("VaM timeline auto-resume", "vam_timeline_auto_resume_checkbox"))
    bind_button(btn_start_vam_desktop, "_nc_ui_shell_persona_avatar_bound", lambda: _ui_shell_append_console(window, "[UI Shell] Start VaM Desktop is deferred in shell preview; no process was launched."))
    bind_button(btn_start_vam_vr, "_nc_ui_shell_persona_avatar_bound", lambda: _ui_shell_append_console(window, "[UI Shell] Start VaM VR is deferred in shell preview; no process was launched."))
    bind_button(btn_vam_hide_interface, "_nc_ui_shell_persona_avatar_bound", lambda: _ui_shell_append_console(window, "[UI Shell] VaM interface-hide action is deferred in shell preview."))

    return {
        "bound": bound,
        "deferred": sorted(set(deferred)),
        "voices": len([item for item in _ui_shell_voice_options(window) if item != "No .wav found"]),
        "body_configs": len(configs),
    }


def _bind_ui_shell_input_action_controls(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    service = _ui_shell_input_actions_service(window)
    bound = []
    deferred = [
        "btn_push_to_talk",
        "import_audio_button",
        "transcribe_audio_button",
        "audio_story_play_button",
        "audio_story_pause_button",
        "audio_story_stop_button",
    ]

    input_mode_combo = _ui_shell_find_object(window, "input_mode_combo")
    push_to_talk_button = _ui_shell_find_object(window, "btn_push_to_talk")
    audio_file_path_edit = _ui_shell_find_object(window, "audio_file_path_edit")
    import_audio_button = _ui_shell_find_object(window, "import_audio_button")
    audio_story_playback_combo = _ui_shell_find_object(window, "audio_story_playback_combo")
    transcribe_seconds_label = _ui_shell_find_object(window, "transcribe_seconds_label")
    transcribe_seconds_slider = _ui_shell_find_object(window, "transcribe_seconds_slider")
    transcribe_audio_button = _ui_shell_find_object(window, "transcribe_audio_button")
    audio_story_play_button = _ui_shell_find_object(window, "audio_story_play_button")
    audio_story_pause_button = _ui_shell_find_object(window, "audio_story_pause_button")
    audio_story_stop_button = _ui_shell_find_object(window, "audio_story_stop_button")
    audio_story_seek_slider = _ui_shell_find_object(window, "audio_story_seek_slider")
    audio_story_position_label = _ui_shell_find_object(window, "audio_story_position_label")

    if audio_file_path_edit is not None:
        if hasattr(audio_file_path_edit, "setReadOnly"):
            audio_file_path_edit.setReadOnly(False)
        if hasattr(audio_file_path_edit, "setText"):
            audio_file_path_edit.setText(str(session.get("audio_story_mode_audio_path", "") or ""))
        if hasattr(audio_file_path_edit, "setToolTip"):
            audio_file_path_edit.setToolTip("Shell-local Audio Story path preview. Paste a local path here; no file is opened or saved.")

    if audio_story_playback_combo is not None:
        _ui_shell_combo_set_items(audio_story_playback_combo, list(_UiShellInputActionService.AUDIO_STORY_PLAYBACK_MODES))
        _ui_shell_combo_select_label(audio_story_playback_combo, str(session.get("audio_story_mode_playback_mode", "Play Imported Audio") or "Play Imported Audio"))
        audio_story_playback_combo.setToolTip("Shell-local Audio Story playback mode preview. No player or TTS narration is started.")

    if transcribe_seconds_slider is not None:
        try:
            transcribe_seconds_slider.setRange(1, 60)
        except Exception:
            pass
        _ui_shell_set_slider_value(transcribe_seconds_slider, int(session.get("audio_story_mode_transcribe_seconds", _UiShellInputActionService.AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS) or _UiShellInputActionService.AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS))
        transcribe_seconds_slider.setToolTip("Shell-local transcription-window preview. No Whisper/STT runtime is started.")

    if audio_story_seek_slider is not None:
        try:
            audio_story_seek_slider.setRange(0, 100)
        except Exception:
            pass
        _ui_shell_set_slider_value(audio_story_seek_slider, 0)
        audio_story_seek_slider.setToolTip("Shell-local Audio Story seek preview. No playback runtime is connected.")

    def refresh_preview():
        snapshot = service.snapshot()
        if push_to_talk_button is not None:
            if hasattr(push_to_talk_button, "setEnabled"):
                push_to_talk_button.setEnabled(bool(snapshot.get("push_to_talk_enabled")))
            if hasattr(push_to_talk_button, "setText"):
                push_to_talk_button.setText("Talking..." if snapshot.get("push_to_talk_held") else "Hold To Talk")
            if hasattr(push_to_talk_button, "setToolTip"):
                if snapshot.get("push_to_talk_enabled"):
                    push_to_talk_button.setToolTip(
                        f"Shell-local push-to-talk preview. Hotkey: {snapshot.get('push_to_talk_hotkey') or 'Right Ctrl'}. No microphone capture is started."
                    )
                else:
                    push_to_talk_button.setToolTip("Switch Input Mode to Push-to-Talk to preview this button. No microphone capture is started.")

        base_transcribe_label = ""
        if transcribe_seconds_label is not None and hasattr(transcribe_seconds_label, "setText"):
            base_transcribe_label = str(getattr(transcribe_seconds_label, "_nc_ui_shell_base_text", "") or "").strip()
            if not base_transcribe_label:
                base_transcribe_label = str(transcribe_seconds_label.text() or "Transcribe Seconds").strip() or "Transcribe Seconds"
                setattr(transcribe_seconds_label, "_nc_ui_shell_base_text", base_transcribe_label)
            transcribe_seconds_label.setText(f"{base_transcribe_label} ({int(snapshot.get('audio_story_transcribe_seconds', 0) or 0)}s)")

        has_audio = bool(snapshot.get("audio_story_has_audio"))
        playback_state = str(snapshot.get("audio_story_playback_state") or "stopped").strip().lower()
        seek_percent = int(snapshot.get("audio_story_seek_percent", 0) or 0)
        if import_audio_button is not None and hasattr(import_audio_button, "setEnabled"):
            import_audio_button.setEnabled(True)
        if import_audio_button is not None and hasattr(import_audio_button, "setToolTip"):
            import_audio_button.setToolTip("Shell-local preview only. The import dialog remains deferred; paste a path into the field to simulate import.")
        if transcribe_audio_button is not None and hasattr(transcribe_audio_button, "setEnabled"):
            transcribe_audio_button.setEnabled(has_audio)
        if transcribe_audio_button is not None and hasattr(transcribe_audio_button, "setToolTip"):
            transcribe_audio_button.setToolTip("Shell-local preview only. No Whisper/STT runtime is started.")
        if audio_story_play_button is not None and hasattr(audio_story_play_button, "setEnabled"):
            audio_story_play_button.setEnabled(has_audio and playback_state != "playing")
        if audio_story_play_button is not None and hasattr(audio_story_play_button, "setToolTip"):
            audio_story_play_button.setToolTip("Shell-local playback preview only. No media player or TTS narration is started.")
        if audio_story_pause_button is not None and hasattr(audio_story_pause_button, "setEnabled"):
            audio_story_pause_button.setEnabled(has_audio and playback_state == "playing")
        if audio_story_pause_button is not None and hasattr(audio_story_pause_button, "setToolTip"):
            audio_story_pause_button.setToolTip("Shell-local playback preview only.")
        if audio_story_stop_button is not None and hasattr(audio_story_stop_button, "setEnabled"):
            audio_story_stop_button.setEnabled(has_audio and (playback_state in {"playing", "paused"} or seek_percent > 0))
        if audio_story_stop_button is not None and hasattr(audio_story_stop_button, "setToolTip"):
            audio_story_stop_button.setToolTip("Shell-local playback preview only.")
        if audio_story_seek_slider is not None:
            if hasattr(audio_story_seek_slider, "setEnabled"):
                audio_story_seek_slider.setEnabled(has_audio)
            if not (hasattr(audio_story_seek_slider, "isSliderDown") and audio_story_seek_slider.isSliderDown()):
                _ui_shell_set_slider_value(audio_story_seek_slider, seek_percent)
        if audio_story_position_label is not None and hasattr(audio_story_position_label, "setText"):
            audio_story_position_label.setText(str(snapshot.get("audio_story_position_text") or "00:00 / 01:00"))
        return snapshot

    def append_service_message(result):
        message = str(result.get("message") or "").strip()
        if message:
            _ui_shell_append_console(window, f"[UI Shell] {message}")

    def bind_line_edit(widget, attr_name):
        if widget is None:
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        text_attr = f"{attr_name}_text_changed"
        finished_attr = f"{attr_name}_editing_finished"
        if hasattr(widget, "textChanged") and not getattr(widget, text_attr, False):
            widget.textChanged.connect(lambda *_args: refresh_preview())
            setattr(widget, text_attr, True)
        if hasattr(widget, "editingFinished") and not getattr(widget, finished_attr, False):
            widget.editingFinished.connect(
                lambda: (
                    append_service_message(service.set_audio_file_path(_ui_shell_line_edit_value(window, "audio_file_path_edit", ""))),
                    refresh_preview(),
                )
            )
            setattr(widget, finished_attr, True)

    def bind_combo(widget, attr_name, on_log):
        if widget is None or not hasattr(widget, "currentIndexChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_changed(_index=None):
            snapshot = refresh_preview()
            _ui_shell_append_console(window, on_log(snapshot))

        widget.currentIndexChanged.connect(on_changed)
        setattr(widget, attr_name, True)

    def bind_slider(widget, attr_name, on_change=None, on_release=None):
        if widget is None:
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        change_attr = f"{attr_name}_value_changed"
        release_attr = f"{attr_name}_slider_released"
        if hasattr(widget, "valueChanged") and not getattr(widget, change_attr, False):
            widget.valueChanged.connect(lambda value=None: on_change(value) if callable(on_change) else refresh_preview())
            setattr(widget, change_attr, True)
        if hasattr(widget, "sliderReleased") and callable(on_release) and not getattr(widget, release_attr, False):
            widget.sliderReleased.connect(on_release)
            setattr(widget, release_attr, True)

    def bind_click(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "clicked"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return
        widget.clicked.connect(lambda _checked=False: handler())
        setattr(widget, attr_name, True)

    if push_to_talk_button is not None:
        bound.append(str(push_to_talk_button.objectName() if hasattr(push_to_talk_button, "objectName") else "btn_push_to_talk"))
        if hasattr(push_to_talk_button, "pressed") and not getattr(push_to_talk_button, "_nc_ui_shell_push_to_talk_press_bound", False):
            push_to_talk_button.pressed.connect(
                lambda: (
                    append_service_message(service.set_push_to_talk_hold(True)),
                    refresh_preview(),
                )
            )
            setattr(push_to_talk_button, "_nc_ui_shell_push_to_talk_press_bound", True)
        if hasattr(push_to_talk_button, "released") and not getattr(push_to_talk_button, "_nc_ui_shell_push_to_talk_release_bound", False):
            push_to_talk_button.released.connect(
                lambda: (
                    append_service_message(service.set_push_to_talk_hold(False)),
                    refresh_preview(),
                )
            )
            setattr(push_to_talk_button, "_nc_ui_shell_push_to_talk_release_bound", True)

    if input_mode_combo is not None and hasattr(input_mode_combo, "currentIndexChanged") and not getattr(input_mode_combo, "_nc_ui_shell_push_to_talk_mode_refresh_bound", False):
        input_mode_combo.currentIndexChanged.connect(lambda _index=None: refresh_preview())
        setattr(input_mode_combo, "_nc_ui_shell_push_to_talk_mode_refresh_bound", True)

    bind_line_edit(audio_file_path_edit, "_nc_ui_shell_audio_story_path_bound")
    bind_combo(
        audio_story_playback_combo,
        "_nc_ui_shell_audio_story_playback_bound",
        lambda snapshot: f"Audio Story playback preview mode: {snapshot.get('audio_story_playback_mode') or 'Play Imported Audio'}. No audio runtime changed.",
    )
    bind_slider(
        transcribe_seconds_slider,
        "_nc_ui_shell_audio_story_transcribe_slider_bound",
        on_change=lambda _value=None: refresh_preview(),
        on_release=lambda: _ui_shell_append_console(
            window,
            f"[UI Shell] Audio Story transcribe window preview: {int(service.snapshot().get('audio_story_transcribe_seconds', 0) or 0)} second(s). No STT runtime changed.",
        ),
    )
    bind_click(import_audio_button, "_nc_ui_shell_import_audio_bound", lambda: (append_service_message(service.request_audio_import()), refresh_preview()))
    bind_click(transcribe_audio_button, "_nc_ui_shell_transcribe_audio_bound", lambda: (append_service_message(service.request_audio_transcription()), refresh_preview()))
    bind_click(audio_story_play_button, "_nc_ui_shell_audio_story_play_bound", lambda: (append_service_message(service.play_audio_story()), refresh_preview()))
    bind_click(audio_story_pause_button, "_nc_ui_shell_audio_story_pause_bound", lambda: (append_service_message(service.pause_audio_story()), refresh_preview()))
    bind_click(audio_story_stop_button, "_nc_ui_shell_audio_story_stop_bound", lambda: (append_service_message(service.stop_audio_story()), refresh_preview()))
    bind_slider(
        audio_story_seek_slider,
        "_nc_ui_shell_audio_story_seek_bound",
        on_change=lambda value=None: (
            service.seek_audio_story(0 if value is None else int(value)),
            refresh_preview(),
        ),
        on_release=lambda: _ui_shell_append_console(
            window,
            f"[UI Shell] Audio Story seek preview: {int(service.snapshot().get('audio_story_seek_percent', 0) or 0)}%. No playback runtime was moved.",
        ),
    )

    snapshot = refresh_preview()
    return {
        "bound": bound,
        "deferred": sorted(set(deferred)),
        "push_to_talk_enabled": bool(snapshot.get("push_to_talk_enabled")),
        "audio_story_has_audio": bool(snapshot.get("audio_story_has_audio")),
        "audio_story_playback_state": str(snapshot.get("audio_story_playback_state") or "stopped"),
    }




def _configure_ui_shell_smoke_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    _configure_ui_shell_addon_report_dependencies()
    configure_ui_shell_smoke_dependencies({
        "UI_VALIDATION_REQUIRED_GROUPS": UI_VALIDATION_REQUIRED_GROUPS,
        "_apply_ui_shell_addon_placeholders": _apply_ui_shell_addon_placeholders,
        "_apply_ui_shell_read_only_config": _apply_ui_shell_read_only_config,
        "_bind_ui_shell_avatar_runtime": _bind_ui_shell_avatar_runtime,
        "_bind_ui_shell_chat_context_controls": _bind_ui_shell_chat_context_controls,
        "_bind_ui_shell_chat_runtime": _bind_ui_shell_chat_runtime,
        "_bind_ui_shell_chunking_profile_controls": _bind_ui_shell_chunking_profile_controls,
        "_bind_ui_shell_dry_run_controls": _bind_ui_shell_dry_run_controls,
        "_bind_ui_shell_host_core_controls": _bind_ui_shell_host_core_controls,
        "_bind_ui_shell_input_action_controls": _bind_ui_shell_input_action_controls,
        "_bind_ui_shell_lifecycle_local_controls": _bind_ui_shell_lifecycle_local_controls,
        "_bind_ui_shell_persona_body_vam_controls": _bind_ui_shell_persona_body_vam_controls,
        "_bind_ui_shell_preset_session_controls": _bind_ui_shell_preset_session_controls,
        "_bind_ui_shell_runtime_action_controls": _bind_ui_shell_runtime_action_controls,
        "_bind_ui_shell_tts_runtime": _bind_ui_shell_tts_runtime,
        "_bind_ui_shell_tutorial_controls": _bind_ui_shell_tutorial_controls,
        "_load_ui_shell_for_smoke": _load_ui_shell_for_smoke,
        "_print_ui_shell_addon_mount_report": _print_ui_shell_addon_mount_report,
        "_print_ui_shell_static_addon_comparison": _print_ui_shell_static_addon_comparison,
        "_resolve_ui_path": _resolve_ui_path,
        "_ui_shell_addon_mount_report": _ui_shell_addon_mount_report,
        "_ui_shell_class_matches": _ui_shell_class_matches,
        "_ui_shell_cleanup_live_addons": _ui_shell_cleanup_live_addons,
        "_ui_shell_compose_status_line": _ui_shell_compose_status_line,
        "_ui_shell_find_object": _ui_shell_find_object,
        "_ui_shell_mount_live_addons": _ui_shell_mount_live_addons,
    })


def _configure_ui_shell_preview_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    _configure_ui_shell_addon_report_dependencies()
    configure_ui_shell_preview_dependencies({
        "_QtWidgets": _QtWidgets,
        "_apply_ui_shell_addon_placeholders": _apply_ui_shell_addon_placeholders,
        "_apply_ui_shell_preview_status": _apply_ui_shell_preview_status,
        "_apply_ui_shell_read_only_config": _apply_ui_shell_read_only_config,
        "_bind_ui_shell_avatar_runtime": _bind_ui_shell_avatar_runtime,
        "_bind_ui_shell_chat_context_controls": _bind_ui_shell_chat_context_controls,
        "_bind_ui_shell_chat_runtime": _bind_ui_shell_chat_runtime,
        "_bind_ui_shell_chunking_profile_controls": _bind_ui_shell_chunking_profile_controls,
        "_bind_ui_shell_console_chat_local_controls": _bind_ui_shell_console_chat_local_controls,
        "_bind_ui_shell_dry_run_controls": _bind_ui_shell_dry_run_controls,
        "_bind_ui_shell_host_core_controls": _bind_ui_shell_host_core_controls,
        "_bind_ui_shell_input_action_controls": _bind_ui_shell_input_action_controls,
        "_bind_ui_shell_lifecycle_local_controls": _bind_ui_shell_lifecycle_local_controls,
        "_bind_ui_shell_persona_body_vam_controls": _bind_ui_shell_persona_body_vam_controls,
        "_bind_ui_shell_preset_session_controls": _bind_ui_shell_preset_session_controls,
        "_bind_ui_shell_runtime_action_controls": _bind_ui_shell_runtime_action_controls,
        "_bind_ui_shell_tts_runtime": _bind_ui_shell_tts_runtime,
        "_bind_ui_shell_tutorial_controls": _bind_ui_shell_tutorial_controls,
        "_load_ui_shell_for_smoke": _load_ui_shell_for_smoke,
        "_print_ui_shell_static_addon_comparison": _print_ui_shell_static_addon_comparison,
        "_resolve_ui_path": _resolve_ui_path,
        "_ui_shell_addon_mount_report": _ui_shell_addon_mount_report,
        "_ui_shell_cleanup_live_addons": _ui_shell_cleanup_live_addons,
        "_ui_shell_compose_status_line": _ui_shell_compose_status_line,
        "_ui_shell_mount_live_addons": _ui_shell_mount_live_addons,
    })


if len(sys.argv) >= 2 and str(sys.argv[1] or "").strip().lower() == "--ui-shell":
    shell_smoke = any(str(item or "").strip().lower() == "--shell-smoke" for item in sys.argv[2:])
    ui_arg = sys.argv[2] if len(sys.argv) >= 3 and not str(sys.argv[2] or "").startswith("--") else "main.ui"
    if shell_smoke:
        _configure_ui_shell_smoke_dependencies()
        sys.exit(run_ui_shell_smoke(ui_arg))
    _configure_ui_shell_preview_dependencies()
    sys.exit(run_ui_shell_preview(ui_arg))

_ui_shell_enable_stdio_unicode_fallback()

import dry_run
import tutorial_framework
import loop_authoring
try:
    import cv2
except Exception:
    cv2 = None
import numpy as np
try:
    from flask import Flask, jsonify
    from flask_cors import CORS
except Exception:
    Flask = None
    CORS = None
    def jsonify(payload):
        return payload
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
from core import avatar_runtime, sensory, chat_providers
from core.addons import AddonManager
from core.addons.qt_host_services import AddonCapabilityBridgeService, QtAvatarProviderService, QtChatContextService, QtChatProviderService, QtChatReplayService, QtDialogService, QtDryRunService, QtEngineLifecycleService, QtHotkeyService, QtInputActionService, QtInputSettingsService, QtModelRefreshService, QtMuseTalkUIService, QtPerformanceProfileService, QtPersonaAvatarService, QtRuntimeControlService, QtRuntimeStatusService, QtSensoryService, QtShellService, QtTutorialService, QtVisualReplyService
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
DEFAULT_LOCAL_VAM_ROOT = ""
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
APP_STYLESHEET_FALLBACK = """
QMainWindow { background: #11161d; }
QWidget { color: #e5e9f0; font-family: "Segoe UI"; font-size: 12px; }
QFrame#Panel { background: #18202a; border: 1px solid #283342; border-radius: 14px; padding: 8px; }
QFrame#HeaderCard { background: #131a23; border: 1px solid #243244; border-radius: 12px; padding: 4px; }
QScrollArea { background: #18202a; border: 1px solid #273342; border-radius: 10px; padding: 6px; }
QScrollArea > QWidget > QWidget { background: #18202a; color: #e5e9f0; }
QScrollBar:vertical {
    background: #131a23;
    border: 1px solid #273342;
    border-radius: 11px;
    width: 22px;
    margin: 2px 2px 2px 2px;
}
QScrollBar::handle:vertical {
    background: #3a516c;
    border: 1px solid #4b6889;
    border-radius: 9px;
    min-height: 52px;
    margin: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #4a6788;
}
QScrollBar::handle:vertical:pressed {
    background: #5b7ca2;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    background: #1a2430;
    border: 0;
    height: 16px;
    subcontrol-origin: margin;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: #131a23;
    border: 1px solid #273342;
    border-radius: 11px;
    height: 22px;
    margin: 2px 2px 2px 2px;
}
QScrollBar::handle:horizontal {
    background: #3a516c;
    border: 1px solid #4b6889;
    border-radius: 9px;
    min-width: 52px;
    margin: 3px;
}
QScrollBar::handle:horizontal:hover {
    background: #4a6788;
}
QScrollBar::handle:horizontal:pressed {
    background: #5b7ca2;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    background: #1a2430;
    border: 0;
    width: 16px;
    subcontrol-origin: margin;
}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
QStackedWidget {
    background: transparent;
    padding: 4px;
}
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
QGroupBox#chat_runtime_box, QGroupBox#tts_runtime_box {
    margin-top: 18px;
    padding-top: 12px;
}
QGroupBox#chat_runtime_box::title, QGroupBox#tts_runtime_box::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 8px 0 8px;
}
QGroupBox#chat_runtime_box::indicator, QGroupBox#tts_runtime_box::indicator {
    width: 0px;
    height: 0px;
}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    color: #f2f5f9;
    padding: 4px 8px;
    selection-background-color: #4d8dff;
    selection-color: #ffffff;
}
QComboBox QLabel,
QComboBox QLineEdit,
QAbstractSpinBox QLineEdit {
    color: #f2f5f9;
    background: transparent;
    selection-background-color: #4d8dff;
    selection-color: #ffffff;
}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #b7c1ce;
}
QComboBox:disabled QLabel,
QComboBox:disabled QLineEdit,
QAbstractSpinBox:disabled QLineEdit {
    color: #b7c1ce;
}
QLineEdit[readOnly="true"], QComboBox[editable="true"] QLineEdit[readOnly="true"] {
    color: #f2f5f9;
}
QLineEdit::placeholder, QComboBox QLineEdit::placeholder {
    color: #8ea3b8;
}
QComboBox {
    padding-right: 30px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    background: #17212c;
    border-left: 1px solid #273342;
    border-top-right-radius: 10px;
    border-bottom-right-radius: 10px;
}
QComboBox::drop-down:hover {
    background: #223247;
}
QComboBox::drop-down:pressed {
    background: #29405b;
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
    alternate-background-color: #1b2836;
}
QComboBox QAbstractItemView::item, QListWidget::item {
    color: #f2f5f9;
    background: transparent;
    min-height: 24px;
    padding: 4px 8px;
}
QComboBox QAbstractItemView::item:selected, QListWidget::item:selected {
    color: #ffffff;
    background: #29405b;
}
QComboBox QAbstractItemView::item:hover, QListWidget::item:hover {
    color: #ffffff;
    background: #223247;
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
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    margin-right: 4px;
}
QTabBar::tab:selected { background: #233245; }
QTabWidget#sensory_feedback_tabs::tab-bar,
QTabWidget#vseeface_tabs::tab-bar,
QTabWidget#musetalk_tabs::tab-bar,
QTabWidget#tts_runtime_addon_tabs::tab-bar,
QTabWidget#vam_setup_tabs::tab-bar,
QTabWidget#right_tabs::tab-bar {
    left: 8px;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab,
QTabWidget#vseeface_tabs QTabBar::tab,
QTabWidget#musetalk_tabs QTabBar::tab,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab,
QTabWidget#vam_setup_tabs QTabBar::tab,
QTabWidget#right_tabs QTabBar::tab {
    background: #17212c;
    border: 1px solid #273342;
    min-width: 0px;
    max-width: 16777215px;
    min-height: 0px;
    padding: 8px 14px;
    margin-right: 4px;
    margin-bottom: -1px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab:!selected,
QTabWidget#vseeface_tabs QTabBar::tab:!selected,
QTabWidget#musetalk_tabs QTabBar::tab:!selected,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:!selected,
QTabWidget#vam_setup_tabs QTabBar::tab:!selected,
QTabWidget#right_tabs QTabBar::tab:!selected {
    margin-top: 3px;
}
QTabWidget#sensory_feedback_tabs::pane,
QTabWidget#vseeface_tabs::pane,
QTabWidget#musetalk_tabs::pane,
QTabWidget#tts_runtime_addon_tabs::pane,
QTabWidget#vam_setup_tabs::pane,
QTabWidget#right_tabs::pane {
    top: -1px;
    background: #0f141b;
    border: 1px solid #273342;
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    padding: 12px 10px 10px 10px;
}
QTabWidget#sensory_feedback_tabs QStackedWidget,
QTabWidget#vseeface_tabs QStackedWidget,
QTabWidget#musetalk_tabs QStackedWidget,
QTabWidget#tts_runtime_addon_tabs QStackedWidget,
QTabWidget#vam_setup_tabs QStackedWidget,
QTabWidget#right_tabs QStackedWidget {
    padding: 8px;
    background: transparent;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab:selected,
QTabWidget#vseeface_tabs QTabBar::tab:selected,
QTabWidget#musetalk_tabs QTabBar::tab:selected,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:selected,
QTabWidget#vam_setup_tabs QTabBar::tab:selected,
QTabWidget#right_tabs QTabBar::tab:selected {
    background: #0f141b;
    border-color: #273342;
    border-bottom-color: #0f141b;
    margin-bottom: -1px;
    padding-bottom: 10px;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab:hover,
QTabWidget#vseeface_tabs QTabBar::tab:hover,
QTabWidget#musetalk_tabs QTabBar::tab:hover,
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:hover,
QTabWidget#vam_setup_tabs QTabBar::tab:hover,
QTabWidget#right_tabs QTabBar::tab:hover {
    background: #223247;
}
QTabWidget#host_settings_tabs QTabBar::tab,
QTabWidget#left_tabs QTabBar::tab {
    background: #18202a;
    border: 1px solid #273342;
    min-width: 92px;
    max-width: 180px;
    min-height: 34px;
    padding: 6px 12px 12px 12px;
    margin-bottom: 4px;
    margin-right: 0px;
    border-top-left-radius: 10px;
    border-bottom-left-radius: 10px;
    border-top-right-radius: 0px;
    border-bottom-right-radius: 0px;
}
QTabWidget#host_settings_tabs::pane,
QTabWidget#left_tabs::pane {
    margin-left: -1px;
    background: #0f141b;
    border: 1px solid #273342;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    padding: 6px;
}
QTabWidget#host_settings_tabs QStackedWidget,
QTabWidget#left_tabs QStackedWidget {
    padding: 0px;
    background: transparent;
}
QTabWidget#host_settings_tabs QTabBar::tab:selected,
QTabWidget#left_tabs QTabBar::tab:selected {
    background: #0f141b;
    border-right-color: #0f141b;
    margin-right: -1px;
}
QTabWidget#host_settings_tabs QTabBar::tab:hover,
QTabWidget#left_tabs QTabBar::tab:hover {
    background: #223247;
}
QTabWidget#host_settings_tabs QTabBar,
QTabWidget#left_tabs QTabBar {
    background: #18202a;
    border: 0;
}
QTabWidget#host_settings_tabs QTabBar {
    margin-top: 0px;
    padding-top: 4px;
}
QTabWidget#left_tabs QTabBar {
    margin-top: 0px;
    padding-top: 4px;
}
QTabWidget#left_tabs::pane {
    margin-top: 0px;
    border-top-left-radius: 0px;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
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
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
"""


def _load_qss_stylesheet(qss_path: Path, fallback: str) -> str:
    try:
        value = qss_path.read_text(encoding="utf-8")
        if str(value or "").strip():
            return str(value)
    except Exception:
        pass
    return str(fallback or "")


def _load_main_ui_stylesheet(ui_path: Path, fallback: str) -> str:
    try:
        tree = ET.parse(str(ui_path))
        root = tree.getroot()
        widget = root.find("./widget[@class='QMainWindow']")
        if widget is None:
            return str(fallback or "")
        for prop in widget.findall("./property[@name='styleSheet']"):
            string_node = prop.find("string")
            if string_node is None:
                continue
            value = str(string_node.text or "")
            if value.strip():
                return value
    except Exception:
        pass
    return str(fallback or "")


APP_STYLESHEET = _load_qss_stylesheet(
    Path(__file__).resolve().parent / "ui" / "styles" / "app.qss",
    APP_STYLESHEET_FALLBACK,
)

APP_THEME_PRESET_LABELS = {
    "light_gray": "Light Gray",
    "gray": "Gray",
    "dark_gray": "Dark Gray",
    "slate_blue": "Slate Blue",
    "warm_sand": "Warm Sand",
    "forest": "Forest",
    "ocean": "Ocean",
    "rose_smoke": "Rose Smoke",
    "midnight": "Midnight",
}

APP_THEME_PRESET_WIDGETS = (
    ("light_gray", "theme_light_gray_button", "theme_light_gray_edit"),
    ("gray", "theme_gray_button", "theme_gray_edit"),
    ("dark_gray", "theme_dark_gray_button", "theme_dark_gray_edit"),
    ("slate_blue", "theme_slate_blue_button", "theme_slate_blue_edit"),
    ("warm_sand", "theme_warm_sand_button", "theme_warm_sand_edit"),
    ("forest", "theme_forest_button", "theme_forest_edit"),
    ("ocean", "theme_ocean_button", "theme_ocean_edit"),
    ("rose_smoke", "theme_rose_smoke_button", "theme_rose_smoke_edit"),
    ("midnight", "theme_midnight_button", "theme_midnight_edit"),
)

DEFAULT_APP_THEME_PRESET = "dark_gray"

APP_THEME_STYLESHEET_BASE_TOKENS = {
    "#11161d": "window_bg",
    "#18202a": "panel_bg",
    "#131a23": "header_bg",
    "#1a2430": "scroll_button_bg",
    "#283342": "panel_border",
    "#243244": "header_border",
    "#273342": "surface_border",
    "#223247": "button_bg",
    "#324b69": "button_border",
    "#29405b": "button_hover",
    "#1a2028": "disabled_bg",
    "#27303b": "disabled_border",
    "#17212c": "spin_bg",
    "#324055": "spin_border",
    "#16202b": "menu_bg",
    "#2c3a4b": "menu_separator",
    "#2a3544": "tab_border",
    "#233245": "tab_selected_bg",
    "#3a516c": "scroll_handle_bg",
    "#4b6889": "scroll_handle_border",
    "#4a6788": "scroll_handle_hover",
    "#5b7ca2": "scroll_handle_pressed",
    "#4d8dff": "accent_bg",
    "#6ea4ff": "accent_border",
    "#6a95ff": "accent_border",
    "#0f141b": "field_bg",
    "#e5e9f0": "text",
    "#f2f5f9": "text_strong",
    "#7f8791": "text_disabled",
    "#b7c1ce": "text_muted",
    "#5b6675": "status_neutral_bg",
    "#8ea3b8": "text_muted",
    "#9fb3c8": "text_soft",
    "#cbd5e1": "text_soft",
    "#d8dee9": "text_title",
    "#dfe3e8": "text_title",
    "#81a1c1": "text_soft",
    "#88c0d0": "accent_info",
}

def _resolve_app_theme_palette(preset_id=None):
    resolved_preset = _normalize_app_theme_preset_id(
        preset_id if preset_id is not None else RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET)
    )
    palette = dict(APP_THEME_PRESET_PALETTES.get(DEFAULT_APP_THEME_PRESET, {}) or {})
    palette.update(dict(APP_THEME_PRESET_PALETTES.get(resolved_preset, {}) or {}))
    palette.setdefault("scroll_button_bg", palette.get("header_bg", "#131a23"))
    palette.setdefault("scroll_handle_bg", palette.get("button_bg", "#3a516c"))
    palette.setdefault("scroll_handle_border", palette.get("button_border", "#4b6889"))
    palette.setdefault("scroll_handle_hover", palette.get("button_hover", "#4a6788"))
    palette.setdefault("scroll_handle_pressed", palette.get("tab_selected_bg", "#5b7ca2"))
    palette.setdefault("status_neutral_bg", palette.get("spin_border", palette.get("text_disabled", "#5b6675")))
    palette.setdefault("text_muted", palette.get("text_disabled", "#8ea3b8"))
    palette.setdefault("text_soft", palette.get("text", "#9fb3c8"))
    palette.setdefault("text_title", palette.get("text_strong", "#d8dee9"))
    palette.setdefault("accent_bg", palette.get("button_border", "#4d8dff"))
    palette.setdefault("accent_border", palette.get("tab_selected_bg", palette.get("button_border", "#6a95ff")))
    palette.setdefault("accent_info", palette.get("button_border", "#88c0d0"))
    return palette


def _replace_theme_colors_in_stylesheet(stylesheet, palette):
    themed = str(stylesheet or "")
    if not themed.strip():
        return themed
    for source, token_name in APP_THEME_STYLESHEET_BASE_TOKENS.items():
        replacement = str(palette.get(token_name, source) or source)
        themed = themed.replace(source, replacement)
        themed = themed.replace(source.upper(), replacement)
    return themed


def _canonical_theme_base_stylesheet(stylesheet):
    canonical = str(stylesheet or "")
    if not canonical.strip():
        return canonical
    token_base_sources = {}
    for source, token_name in APP_THEME_STYLESHEET_BASE_TOKENS.items():
        token_base_sources.setdefault(str(token_name or ""), str(source or ""))
    replacement_pairs = []
    for token_name, base_source in token_base_sources.items():
        if not token_name or not base_source:
            continue
        for preset_id in APP_THEME_PRESET_LABELS:
            themed_value = str(_resolve_app_theme_palette(preset_id).get(token_name, "") or "").strip()
            if themed_value and themed_value.lower() != base_source.lower():
                replacement_pairs.append((themed_value, base_source))
    seen_pairs = set()
    for themed_value, base_source in replacement_pairs:
        pair_key = (themed_value.lower(), base_source.lower())
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        canonical = re.sub(re.escape(themed_value), base_source, canonical, flags=re.IGNORECASE)
    return canonical


def _apply_inline_theme_styles(root, palette):
    if root is None:
        return
    skip_object_names = {name for _preset, button_name, edit_name in APP_THEME_PRESET_WIDGETS for name in (button_name, edit_name)}
    widgets = [root]
    find_children = getattr(root, "findChildren", None)
    if callable(find_children):
        try:
            widgets.extend(list(find_children(QtCore.QObject)))
        except Exception:
            pass
    for widget in widgets:
        if widget is None or not hasattr(widget, "styleSheet") or not hasattr(widget, "setStyleSheet"):
            continue
        try:
            object_name = str(widget.objectName() or "").strip()
        except Exception:
            object_name = ""
        if object_name in skip_object_names or object_name.startswith("theme_"):
            continue
        try:
            base_stylesheet = widget.property("nc_base_stylesheet")
        except Exception:
            base_stylesheet = None
        if not base_stylesheet:
            try:
                current_stylesheet = str(widget.styleSheet() or "")
            except Exception:
                current_stylesheet = ""
            if not current_stylesheet.strip():
                continue
            base_stylesheet = _canonical_theme_base_stylesheet(current_stylesheet)
            try:
                widget.setProperty("nc_base_stylesheet", base_stylesheet)
            except Exception:
                pass
        else:
            base_stylesheet = _canonical_theme_base_stylesheet(str(base_stylesheet or ""))
            try:
                widget.setProperty("nc_base_stylesheet", base_stylesheet)
            except Exception:
                pass
        themed_stylesheet = _replace_theme_colors_in_stylesheet(str(base_stylesheet or ""), palette)
        try:
            if str(widget.styleSheet() or "") != themed_stylesheet:
                widget.setStyleSheet(themed_stylesheet)
        except Exception:
            continue


def _apply_readable_input_palettes(root, palette):
    if root is None or not hasattr(root, "findChildren"):
        return
    text = QtGui.QColor(str(palette.get("text_strong", palette.get("text", "#f2f5f9")) or "#f2f5f9"))
    soft_text = QtGui.QColor(str(palette.get("text", "#e5e9f0") or "#e5e9f0"))
    disabled_text = QtGui.QColor(str(palette.get("text_muted", palette.get("text_disabled", "#b7c1ce")) or "#b7c1ce"))
    field_bg = QtGui.QColor(str(palette.get("field_bg", "#0f141b") or "#0f141b"))
    menu_bg = QtGui.QColor(str(palette.get("menu_bg", palette.get("field_bg", "#16202b")) or "#16202b"))
    border = str(palette.get("button_border", palette.get("surface_border", "#324b69")) or "#324b69")
    hover = str(palette.get("button_hover", palette.get("tab_selected_bg", "#223247")) or "#223247")
    highlight = QtGui.QColor(str(palette.get("accent_bg", "#4d8dff") or "#4d8dff"))
    highlighted_text = QtGui.QColor("#ffffff")
    popup_stylesheet = (
        "QListView { "
        f"background: {menu_bg.name()}; color: {text.name()}; "
        f"selection-background-color: {highlight.name()}; selection-color: {highlighted_text.name()}; "
        f"border: 1px solid {border}; outline: 0; "
        "}"
        "QListView::item { "
        f"background: {menu_bg.name()}; color: {text.name()}; "
        "min-height: 24px; padding: 4px 8px; "
        "}"
        "QListView::item:selected { "
        f"background: {highlight.name()}; color: {highlighted_text.name()}; "
        "}"
        "QListView::item:hover { "
        f"background: {hover}; color: {highlighted_text.name()}; "
        "}"
    )
    widgets = []
    try:
        widgets.extend(root.findChildren(QtWidgets.QComboBox))
        widgets.extend(root.findChildren(QtWidgets.QLineEdit))
        widgets.extend(root.findChildren(QtWidgets.QAbstractSpinBox))
    except Exception:
        return
    for widget in widgets:
        try:
            pal = widget.palette()
            for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive):
                pal.setColor(group, QtGui.QPalette.Text, text)
                pal.setColor(group, QtGui.QPalette.WindowText, soft_text)
                pal.setColor(group, QtGui.QPalette.ButtonText, text)
                pal.setColor(group, QtGui.QPalette.Base, field_bg)
                pal.setColor(group, QtGui.QPalette.Window, field_bg)
                pal.setColor(group, QtGui.QPalette.Highlight, highlight)
                pal.setColor(group, QtGui.QPalette.HighlightedText, highlighted_text)
                if hasattr(QtGui.QPalette, "PlaceholderText"):
                    pal.setColor(group, QtGui.QPalette.PlaceholderText, disabled_text)
            for role in (QtGui.QPalette.Text, QtGui.QPalette.WindowText, QtGui.QPalette.ButtonText):
                pal.setColor(QtGui.QPalette.Disabled, role, disabled_text)
            if hasattr(QtGui.QPalette, "PlaceholderText"):
                pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.PlaceholderText, disabled_text)
            widget.setPalette(pal)
            if isinstance(widget, QtWidgets.QComboBox):
                model = widget.model()
                if model is not None:
                    text_brush = QtGui.QBrush(text)
                    bg_brush = QtGui.QBrush(menu_bg)
                    for row in range(int(widget.count())):
                        try:
                            model.setData(model.index(row, 0), text_brush, QtCore.Qt.ForegroundRole)
                            model.setData(model.index(row, 0), bg_brush, QtCore.Qt.BackgroundRole)
                        except Exception:
                            continue
                view = widget.view()
                if view is not None:
                    view.setPalette(pal)
                    view.setStyleSheet(popup_stylesheet)
                line_edit = widget.lineEdit() if widget.isEditable() else None
                if line_edit is not None:
                    line_edit.setPalette(pal)
        except Exception:
            continue


def _apply_engine_action_button_accents(root):
    if root is None or not hasattr(root, "findChild"):
        return
    accent_styles = {
        "btn_start_engine": (
            "QPushButton { background: #1d6e52; border: 1px solid #2cc985; color: #f4fffa; "
            "border-radius: 10px; padding: 8px 12px; font-weight: 700; min-height: 44px; }"
            "QPushButton:hover { background: #238462; border-color: #46dda0; }"
            "QPushButton:pressed { background: #195d46; border-color: #22b679; }"
            "QPushButton:disabled { background: #1d3a31; border: 1px solid #355e51; color: #a9c6ba; }"
        ),
        "btn_stop_engine": (
            "QPushButton { background: #7a2626; border: 1px solid #d64a4a; color: #fff5f5; "
            "border-radius: 10px; padding: 8px 12px; font-weight: 700; min-height: 44px; }"
            "QPushButton:hover { background: #923131; border-color: #ef6767; }"
            "QPushButton:pressed { background: #671f1f; border-color: #c43d3d; }"
            "QPushButton:disabled { background: #402525; border: 1px solid #6f4848; color: #d2bbbb; }"
        ),
    }
    for object_name, stylesheet in accent_styles.items():
        try:
            button = root.findChild(QtWidgets.QPushButton, object_name)
        except Exception:
            button = None
        if button is None:
            continue
        try:
            button.setStyleSheet(stylesheet)
        except Exception:
            continue


def _split_collapsible_section_text(text, fallback_title):
    raw = str(text or "").strip()
    if not raw:
        return str(fallback_title or "").strip(), ""
    separator = "  -  "
    if separator in raw:
        title, summary = raw.split(separator, 1)
        return str(title or fallback_title or "").strip(), str(summary or "").strip()
    return raw, ""


APP_THEME_PRESET_PALETTES = {
    "light_gray": {
        "window_bg": "#e7ebef",
        "panel_bg": "#f5f6f8",
        "header_bg": "#eef1f4",
        "panel_border": "#b9bec7",
        "header_border": "#c5cad2",
        "surface_border": "#c3c9d1",
        "button_bg": "#d8dde4",
        "button_border": "#aab2bc",
        "button_hover": "#cfd6de",
        "disabled_bg": "#dde1e6",
        "disabled_border": "#c2c8cf",
        "spin_bg": "#d7dde4",
        "spin_border": "#aab2bc",
        "menu_bg": "#edf1f5",
        "menu_separator": "#c7ced6",
        "tab_border": "#bcc4cd",
        "tab_selected_bg": "#dce2e9",
        "field_bg": "#ffffff",
        "preview_bg": "#f3f5f8",
        "text": "#20242a",
        "text_strong": "#111418",
        "text_disabled": "#717882",
    },
    "gray": {
        "window_bg": "#737780",
        "panel_bg": "#8b8e95",
        "header_bg": "#81858c",
        "panel_border": "#70737a",
        "header_border": "#6b6f76",
        "surface_border": "#7b7f87",
        "button_bg": "#d3d5d9",
        "button_border": "#7b7f87",
        "button_hover": "#c2c6cc",
        "disabled_bg": "#767981",
        "disabled_border": "#666a72",
        "spin_bg": "#c8ccd1",
        "spin_border": "#838892",
        "menu_bg": "#eceef1",
        "menu_separator": "#9ca1a9",
        "tab_border": "#6f737b",
        "tab_selected_bg": "#a0a4ab",
        "field_bg": "#eceef1",
        "preview_bg": "#e2e5ea",
        "text": "#1f2227",
        "text_strong": "#16181c",
        "text_disabled": "#5a5e66",
    },
    "dark_gray": {
        "window_bg": "#11161d",
        "panel_bg": "#18202a",
        "header_bg": "#131a23",
        "panel_border": "#283342",
        "header_border": "#243244",
        "surface_border": "#273342",
        "button_bg": "#223247",
        "button_border": "#324b69",
        "button_hover": "#29405b",
        "disabled_bg": "#1a2028",
        "disabled_border": "#27303b",
        "spin_bg": "#17212c",
        "spin_border": "#324055",
        "menu_bg": "#16202b",
        "menu_separator": "#2c3a4b",
        "tab_border": "#2a3544",
        "tab_selected_bg": "#233245",
        "field_bg": "#0f141b",
        "preview_bg": "#18202a",
        "text": "#e5e9f0",
        "text_strong": "#f2f5f9",
        "text_disabled": "#7f8791",
    },
    "slate_blue": {
        "window_bg": "#566376",
        "panel_bg": "#6d7789",
        "header_bg": "#627082",
        "panel_border": "#556071",
        "header_border": "#5c6778",
        "surface_border": "#6d7c93",
        "button_bg": "#dbe5f5",
        "button_border": "#6d7c93",
        "button_hover": "#cbd8ed",
        "disabled_bg": "#627081",
        "disabled_border": "#4d596b",
        "spin_bg": "#d4def0",
        "spin_border": "#6d7c93",
        "menu_bg": "#edf3fd",
        "menu_separator": "#8291a7",
        "tab_border": "#596578",
        "tab_selected_bg": "#7b8799",
        "field_bg": "#edf3fd",
        "preview_bg": "#dfe7f4",
        "text": "#172133",
        "text_strong": "#111824",
        "text_disabled": "#576579",
    },
    "warm_sand": {
        "window_bg": "#b9aa93",
        "panel_bg": "#c6b8a2",
        "header_bg": "#b7a690",
        "panel_border": "#9f927f",
        "header_border": "#a89882",
        "surface_border": "#a28f72",
        "button_bg": "#f4ead9",
        "button_border": "#a28f72",
        "button_hover": "#eadcbf",
        "disabled_bg": "#b7a890",
        "disabled_border": "#978772",
        "spin_bg": "#ebdfc9",
        "spin_border": "#a28f72",
        "menu_bg": "#fbf4ea",
        "menu_separator": "#b39f82",
        "tab_border": "#998a78",
        "tab_selected_bg": "#d2c2a8",
        "field_bg": "#fbf4ea",
        "preview_bg": "#efe2cf",
        "text": "#2f2417",
        "text_strong": "#2a2117",
        "text_disabled": "#6d6253",
    },
    "forest": {
        "window_bg": "#263830",
        "panel_bg": "#31463d",
        "header_bg": "#293d34",
        "panel_border": "#486256",
        "header_border": "#42594f",
        "surface_border": "#678677",
        "button_bg": "#496457",
        "button_border": "#678677",
        "button_hover": "#58786a",
        "disabled_bg": "#24342d",
        "disabled_border": "#3d554b",
        "spin_bg": "#3b5247",
        "spin_border": "#678677",
        "menu_bg": "#3a5147",
        "menu_separator": "#587468",
        "tab_border": "#42594f",
        "tab_selected_bg": "#415a4d",
        "field_bg": "#3a5147",
        "preview_bg": "#4a6457",
        "text": "#edf4ef",
        "text_strong": "#f5fbf6",
        "text_disabled": "#a4b6aa",
    },
    "ocean": {
        "window_bg": "#2c4e5e",
        "panel_bg": "#355d70",
        "header_bg": "#304f60",
        "panel_border": "#4a7f97",
        "header_border": "#426f84",
        "surface_border": "#69a1bc",
        "button_bg": "#47778e",
        "button_border": "#69a1bc",
        "button_hover": "#5689a2",
        "disabled_bg": "#2a4656",
        "disabled_border": "#3f6b81",
        "spin_bg": "#406d81",
        "spin_border": "#69a1bc",
        "menu_bg": "#3f6e82",
        "menu_separator": "#5f90a6",
        "tab_border": "#436f85",
        "tab_selected_bg": "#4a7c92",
        "field_bg": "#3f6e82",
        "preview_bg": "#4e8198",
        "text": "#eef8fb",
        "text_strong": "#ffffff",
        "text_disabled": "#b5c9d3",
    },
    "rose_smoke": {
        "window_bg": "#67575c",
        "panel_bg": "#7b686d",
        "header_bg": "#6f5d62",
        "panel_border": "#9a858b",
        "header_border": "#8e797f",
        "surface_border": "#bca4aa",
        "button_bg": "#a2868d",
        "button_border": "#bca4aa",
        "button_hover": "#b0939b",
        "disabled_bg": "#65555a",
        "disabled_border": "#896f77",
        "spin_bg": "#8c767d",
        "spin_border": "#bca4aa",
        "menu_bg": "#8c767d",
        "menu_separator": "#a28990",
        "tab_border": "#8b757d",
        "tab_selected_bg": "#947e86",
        "field_bg": "#8c767d",
        "preview_bg": "#a18b93",
        "text": "#fff5f7",
        "text_strong": "#ffffff",
        "text_disabled": "#d7c5ca",
    },
    "midnight": {
        "window_bg": "#10141b",
        "panel_bg": "#151b24",
        "header_bg": "#111720",
        "panel_border": "#283244",
        "header_border": "#223048",
        "surface_border": "#40536f",
        "button_bg": "#253247",
        "button_border": "#40536f",
        "button_hover": "#31425d",
        "disabled_bg": "#121820",
        "disabled_border": "#253347",
        "spin_bg": "#1a2330",
        "spin_border": "#40536f",
        "menu_bg": "#1d2837",
        "menu_separator": "#34465f",
        "tab_border": "#28374b",
        "tab_selected_bg": "#233245",
        "field_bg": "#1d2837",
        "preview_bg": "#253247",
        "text": "#edf2fb",
        "text_strong": "#ffffff",
        "text_disabled": "#9fa9b9",
    },
}


def _normalize_app_theme_preset_id(preset_id):
    normalized = str(preset_id or "").strip().lower()
    if normalized in APP_THEME_PRESET_LABELS:
        return normalized
    return DEFAULT_APP_THEME_PRESET


def _build_app_stylesheet_for_preset(preset_id):
    palette = _resolve_app_theme_palette(preset_id)
    return _replace_theme_colors_in_stylesheet(APP_STYLESHEET, palette)


def _app_theme_palette(preset_id=None):
    return _resolve_app_theme_palette(preset_id)


def _apply_combo_popup_palette(combo):
    _apply_readable_input_palettes(combo.window(), _app_theme_palette())


set_combo_popup_palette_callback(_apply_combo_popup_palette)

configure_legacy_dock_title_dependencies({
    "_app_theme_palette": _app_theme_palette,
    "update_runtime_config": update_runtime_config,
})
configure_legacy_workspace_dock_dependencies({
    "_apply_workspace_view_constraints": _apply_workspace_view_constraints,
    "_WIN32_DOCK_OWNER_SUPPORTED": _WIN32_DOCK_OWNER_SUPPORTED,
    "_WIN32_GWLP_HWNDPARENT": _WIN32_GWLP_HWNDPARENT,
    "_win32_set_window_owner": _win32_set_window_owner,
    "ctypes": ctypes,
})

flask_app = Flask(__name__) if Flask is not None else None
if flask_app is not None and callable(CORS):
    CORS(flask_app)


if flask_app is not None:
    @flask_app.route("/get-expression")
    def get_expression():
        return jsonify(shared_state.current_expression_data)


    @flask_app.route("/get-musetalk-preview")
    def get_musetalk_preview():
        return jsonify(shared_state.current_musetalk_frame_data)


def start_api():
    if flask_app is None:
        print("[API] Flask is unavailable in this environment; expression API server not started.")
        return
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    flask_app.run(port=5005, debug=False, use_reloader=False)


class QtMuseTalkPreviewPanel(QtWidgets.QWidget):
    focusModeRequested = QtCore.Signal()
    showInterfaceRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self._root_layout = QtWidgets.QVBoxLayout(self)
        self._root_layout.setContentsMargins(10, 10, 10, 10)
        self._root_layout.setSpacing(8)
        self.focus_mode_active = False

        self.preview_label = QtWidgets.QLabel("MuseTalk preview idle")
        self.preview_label.setMinimumWidth(0)
        self.preview_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
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
        top_row.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
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
        self.apply_theme_palette()

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

    def apply_theme_palette(self):
        palette = _app_theme_palette()
        self.preview_label.setStyleSheet(f"font-weight: 600; color: {palette.get('text_strong', '#f2f5f9')};")
        self._apply_image_scroll_theme()

    def _apply_image_scroll_theme(self):
        palette = _app_theme_palette()
        if self.focus_mode_active:
            background = palette.get("window_bg", "#11161d")
            border = "transparent"
            radius = "0"
            border_width = "0"
        else:
            background = palette.get("field_bg", "#0f141b")
            border = palette.get("surface_border", "#273342")
            radius = "10px"
            border_width = "1px"
        self.image_scroll.setStyleSheet(
            f"QScrollArea {{ background: {background}; border: {border_width} solid {border}; border-radius: {radius}; }}"
        )

    def set_focus_mode(self, enabled):
        self.focus_mode_active = bool(enabled)
        self.focus_mode_button.setText("Exit Avatar Focus" if self.focus_mode_active else "Avatar Focus")
        self.preview_label.setVisible(not self.focus_mode_active)
        if self.focus_mode_active:
            self._root_layout.setContentsMargins(4, 4, 4, 4)
        else:
            self._root_layout.setContentsMargins(10, 10, 10, 10)
        self._apply_image_scroll_theme()
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

    def _start_frame_preload(self, start_index=0, count=12, *, wrap=False):
        if not self.frame_paths or not self.isVisible():
            return
        target_size = self._get_target_size()
        if target_size != self.preload_target_size:
            self._invalidate_cache_for_resize()
            self.preload_target_size = target_size
        generation = self.preload_generation
        if wrap:
            total = len(self.frame_paths)
            if total <= 0:
                return
            start_index = int(start_index or 0) % total
            preload_paths = [self.frame_paths[(start_index + offset) % total] for offset in range(max(0, int(count or 0)))]
        else:
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
        elif state.get("loop", False) and previous_source is None and self.frame_paths:
            # If the preview is attached after the idle loop has already started,
            # begin near the live idle frame instead of frame 0. Otherwise the
            # next poll jumps far ahead of the preload window and every displayed
            # idle frame becomes a disk cache miss for a while.
            try:
                elapsed = max(0.0, time.time() - float(self.chunk_started_at or time.time()))
                initial_frame_index = int(elapsed * max(self.fps, 1)) % len(self.frame_paths)
            except Exception:
                initial_frame_index = 0
        self.current_frame_index = initial_frame_index
        self.current_frame_path = self.frame_paths[initial_frame_index]
        self._start_loop_fade_if_needed(previous_avatar_id, self.last_avatar_id, state, previous_chunk_id=previous_chunk_id)
        self._start_frame_preload(
            start_index=initial_frame_index,
            count=QT_PREVIEW_INITIAL_PRELOAD if bool(state.get("loop", False)) else min(max(len(self.frame_paths) - initial_frame_index, 1), QT_PREVIEW_INITIAL_PRELOAD),
            wrap=bool(state.get("loop", False)),
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
                                wrap=bool(state.get("loop", False)),
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
                        else:
                            self._start_frame_preload(
                                start_index=frame_index + 1,
                                count=QT_PREVIEW_AHEAD_PRELOAD,
                                wrap=True,
                            )
                        self.render_current_frame()
        except Exception:
            pass


class CompanionQtMainWindow(LegacyWorkspaceDockMixin, LegacyDockTitleMixin, QtWidgets.QMainWindow):
    def __init__(self, *, suppress_restored_aux_docks=False):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 980)
        self.frontend_layout_resync_callback = None
        self._suppress_restored_aux_docks = bool(suppress_restored_aux_docks)
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
        self._preset_dirty_tracking_ready = False
        self._pending_preset_clean_name = ""
        self._pending_preset_clean_provider = ""
        self._pending_preset_clean_model = ""
        self._restoring_session = False
        self._active_app_theme_preset = _normalize_app_theme_preset_id(RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
        self._theme_apply_in_progress = False
        self._chat_runtime_border_paused = None
        self._console_bridge = QtConsoleBridge()
        self._console_redirect = QtTextRedirector(self._console_bridge, mirror_stream=sys.__stdout__)
        self._previous_stdout = sys.stdout
        self._previous_stderr = sys.stderr
        sys.stdout = self._console_redirect
        sys.stderr = self._console_redirect
        self._floating_panels_preserved = []
        self._pinned_floating_panels_preserved = []
        self._pinned_floating_dock_names = set()
        self._always_on_top_floating_dock_names = set()
        self._restore_floating_panels_timer = QtCore.QTimer(self)
        self._restore_floating_panels_timer.setSingleShot(True)
        self._restore_floating_panels_timer.timeout.connect(self._restore_floating_panels_after_minimize)
        self._restore_pinned_floating_panels_timer = QtCore.QTimer(self)
        self._restore_pinned_floating_panels_timer.setSingleShot(True)
        self._restore_pinned_floating_panels_timer.timeout.connect(self._restore_pinned_floating_panels_after_main_hide)

        self._build_ui()
        self._build_preview_dock()
        self._apply_workspace_view_constraints()
        _apply_inline_theme_styles(self, _app_theme_palette(self.current_app_theme_preset()))
        _apply_readable_input_palettes(self, _app_theme_palette(self.current_app_theme_preset()))
        _apply_engine_action_button_accents(self)
        self._apply_legacy_dock_title_widgets()
        self._connect_console_bridge()
        self._build_status_timer()
        self._build_ui_hotkey_timer()
        self._initialize_addons()
        _apply_inline_theme_styles(self, _app_theme_palette(self.current_app_theme_preset()))
        _apply_readable_input_palettes(self, _app_theme_palette(self.current_app_theme_preset()))
        _apply_engine_action_button_accents(self)
        self._apply_legacy_dock_title_widgets()

        os.makedirs("presets", exist_ok=True)
        os.makedirs("voices", exist_ok=True)
        os.makedirs("body_configs", exist_ok=True)

        threading.Thread(target=start_api, daemon=True).start()
        print("📡 [API] Expression server running on port 5005")

        self.refresh_resources()
        self.restore_session()
        self.refresh_tutorial_list()
        QtCore.QTimer.singleShot(250, self.maybe_prompt_first_run_tutorial)

    def current_app_theme_preset(self):
        return _normalize_app_theme_preset_id(getattr(self, "_active_app_theme_preset", DEFAULT_APP_THEME_PRESET))

    def apply_app_theme_preset(self, preset_id, *, save_session=True):
        resolved_preset = _normalize_app_theme_preset_id(preset_id)
        if bool(getattr(self, "_theme_apply_in_progress", False)):
            self._active_app_theme_preset = resolved_preset
            update_runtime_config("ui_theme_preset", resolved_preset)
            return resolved_preset
        self._theme_apply_in_progress = True
        stylesheet = _build_app_stylesheet_for_preset(resolved_preset)
        try:
            self.setStyleSheet(stylesheet)
            self._active_app_theme_preset = resolved_preset
            update_runtime_config("ui_theme_preset", resolved_preset)
            _apply_inline_theme_styles(self, _app_theme_palette(resolved_preset))
            _apply_readable_input_palettes(self, _app_theme_palette(resolved_preset))
            _apply_engine_action_button_accents(self)
            self._apply_legacy_dock_title_widgets()
            for widget in (
                getattr(self, "embedded_musetalk_preview", None),
                getattr(self, "visual_reply_panel", None),
            ):
                if widget is not None and hasattr(widget, "apply_theme_palette"):
                    try:
                        widget.apply_theme_palette()
                    except Exception:
                        pass
            if save_session:
                self.save_session()
            print(f"[QtGUI] Applied UI theme: {APP_THEME_PRESET_LABELS.get(resolved_preset, resolved_preset.title())}")
            return resolved_preset
        finally:
            self._theme_apply_in_progress = False

    def _build_ui(self):
        self.setDockNestingEnabled(True)
        self.setStyleSheet(_build_app_stylesheet_for_preset(self.current_app_theme_preset()))

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

    def _build_preview_dock(self):
        self.preview_dock = QtWidgets.QDockWidget("MuseTalk Preview", self)
        self.preview_dock.setObjectName("MuseTalkPreviewDock")
        self.preview_dock.setAllowedAreas(
            QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
            | QtCore.Qt.LeftDockWidgetArea
        )
        self.preview_dock_container = QtWidgets.QWidget()
        self.preview_dock_container.setMinimumWidth(0)
        self.preview_dock_container.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
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
        self.visual_reply_panel = QtVisualReplyPanel(
            theme_provider=_app_theme_palette,
            runtime_config=RUNTIME_CONFIG,
            shared_state_module=shared_state,
            storage_dir=Path(__file__).resolve().parent / "runtime" / "visual_replies",
        )
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
        self._hide_main_preserving_pinned_floating_docks()
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

        audio_devices = _ui_shell_audio_device_labels()
        self.audio_input_device_combo = NoWheelComboBox()
        self.audio_input_device_combo.setObjectName("audio_input_device_combo")
        _ui_shell_combo_set_items(self.audio_input_device_combo, list(audio_devices.get("inputs") or ["Default Input"]))
        _ui_shell_combo_select_label(self.audio_input_device_combo, str(RUNTIME_CONFIG.get("audio_input_device", "Default Input") or "Default Input"))
        self.audio_input_device_combo.currentTextChanged.connect(self.on_audio_input_device_change)

        self.audio_output_device_combo = NoWheelComboBox()
        self.audio_output_device_combo.setObjectName("audio_output_device_combo")
        _ui_shell_combo_set_items(self.audio_output_device_combo, list(audio_devices.get("outputs") or ["Default Output"]))
        _ui_shell_combo_select_label(self.audio_output_device_combo, str(RUNTIME_CONFIG.get("audio_output_device", "Default Output") or "Default Output"))
        self.audio_output_device_combo.currentTextChanged.connect(self.on_audio_output_device_change)

        mic_row.addWidget(QtWidgets.QLabel("Input"))
        mic_row.addWidget(self.audio_input_device_combo, 1)
        mic_row.addWidget(QtWidgets.QLabel("Output"))
        mic_row.addWidget(self.audio_output_device_combo, 1)
        mic_row.addStretch(1)
        layout.addLayout(mic_row)

        self.engine_combo = NoWheelComboBox()
        self.engine_combo.setObjectName("engine_combo")
        self.refresh_avatar_engine_options()
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

        self.musetalk_use_frame_cache_checkbox = QtWidgets.QCheckBox("Use .npy startup cache")
        self.musetalk_use_frame_cache_checkbox.setObjectName("musetalk_use_frame_cache_checkbox")
        self.musetalk_use_frame_cache_checkbox.setChecked(bool(RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)))
        self.musetalk_use_frame_cache_checkbox.setToolTip(
            "Use/create MuseTalk NumPy frame caches during chat initialization. Disable to save disk space and always load PNG frames instead."
        )
        self.musetalk_use_frame_cache_checkbox.toggled.connect(self.on_musetalk_use_frame_cache_changed)

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
        self.chat_context_window_spin.setRange(4, 2147483647)
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

    def _avatar_provider_options(self):
        legacy = {
            "vseeface": {"id": "vseeface", "label": "VSeeFace", "order": 100},
            "musetalk": {"id": "musetalk", "label": "MuseTalk", "order": 200},
            "vam": {"id": "vam", "label": "VaM", "order": 300},
            "none": {"id": "none", "label": "None", "order": 900},
        }
        for provider in avatar_runtime.list_providers():
            summary = provider.to_summary()
            provider_id = str(summary.get("id") or "").strip().lower()
            if provider_id:
                legacy[provider_id] = summary
        return sorted(
            legacy.values(),
            key=lambda item: (int(item.get("order", 1000) or 1000), str(item.get("label", "")).lower()),
        )

    def _avatar_mode_value_from_label(self, label):
        raw = str(label or "").strip()
        legacy = {
            "vseeface": "vseeface",
            "musetalk": "musetalk",
            "vam": "vam",
            "none": "none",
        }
        return legacy.get(raw.lower(), raw.lower())

    def _current_avatar_mode_value(self):
        combo = getattr(self, "engine_combo", None)
        if combo is None:
            return str(RUNTIME_CONFIG.get("avatar_mode", "vseeface") or "vseeface").strip().lower()
        data = combo.currentData()
        if data:
            return str(data).strip().lower()
        return self._avatar_mode_value_from_label(combo.currentText())

    def refresh_avatar_engine_options(self, selected_provider_id=None):
        combo = getattr(self, "engine_combo", None)
        if combo is None:
            return
        selected = str(
            selected_provider_id
            or self._current_avatar_mode_value()
            or RUNTIME_CONFIG.get("avatar_mode", "vseeface")
            or "vseeface"
        ).strip().lower()
        combo.blockSignals(True)
        try:
            combo.clear()
            for provider in self._avatar_provider_options():
                provider_id = str(provider.get("id") or "").strip().lower()
                label = str(provider.get("label") or provider_id).strip() or provider_id
                combo.addItem(label, provider_id)
            index = combo.findData(selected)
            if index < 0:
                index = combo.findText(selected, QtCore.Qt.MatchFixedString)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

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
        form.addRow("Frame Cache", self.musetalk_use_frame_cache_checkbox)
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
        self.tts_runtime_addon_tabs.setMinimumHeight(420)
        self.tts_runtime_addon_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
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

    def _request_frontend_layout_resync(self):
        callback = getattr(self, "frontend_layout_resync_callback", None)
        if callback is None:
            return

        try:
            QtCore.QTimer.singleShot(10, callback)
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
            self._sync_chat_provider_generation_fields_height()
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
            if kind != "note":
                try:
                    editor.setMinimumWidth(260)
                    editor.setMinimumHeight(34)
                    editor.setMaximumWidth(16777215)
                    if kind in {"int", "float"} and hasattr(editor, "setFixedHeight"):
                        editor.setFixedHeight(34)
                except Exception:
                    pass
            self.chat_provider_generation_fields_layout.addRow(label, editor)
            if kind != "note":
                self._chat_provider_generation_field_widgets[field_id] = editor
                self._chat_provider_generation_field_meta[field_id] = dict(field)
                active_labels.append(label or str(field.get("label") or field_id))

        self._sync_chat_provider_generation_fields_height()
        try:
            QtCore.QTimer.singleShot(0, self._sync_chat_provider_generation_fields_height)
        except Exception:
            pass

        #self._request_frontend_layout_resync()

        if hasattr(self, "chat_provider_generation_section"):
            summary = ", ".join(active_labels[:3])
            if len(active_labels) > 3:
                summary += f", +{len(active_labels) - 3}"
            self.chat_provider_generation_section.setSummary(summary)

    def _sync_chat_provider_generation_fields_height(self):
        try:
            """runtime_box = getattr(self, "chat_runtime_box", None)
            if runtime_box and not runtime_box.isChecked():
                # Card is collapsed. Erase minimums and abort math.
                runtime_box.setMinimumHeight(0)
                return"""
            widget = getattr(self, "chat_provider_generation_fields_widget", None)
            if not widget:
                return

            # 1. SHATTER THE GLASS CEILING
            # Walk up the entire widget tree and delete the 1360px maximum limits
            # so the QScrollArea is finally allowed to expand!
            current = widget
            while current:
                if current.maximumHeight() < 16777215:
                    current.setMaximumHeight(16777215)

                # Erase the strict SetMinAndMaxSize constraint from the .ui file
                layout = current.layout()
                if layout and hasattr(layout, "sizeConstraint"):
                    if layout.sizeConstraint() == QtWidgets.QLayout.SetMinAndMaxSize:
                        layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)

                current = current.parentWidget()

            # 2. MAKE THE CARDS STUBBORN
            # Force the Chat and TTS boxes to refuse to be squished.
            runtime_box = getattr(self, "chat_runtime_box", None)
            tts_box = getattr(self, "tts_runtime_box", None)

            for box in filter(None, [runtime_box, tts_box, widget]):
                policy = box.sizePolicy()
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
                box.setSizePolicy(policy)

                # Tell the box layout to wrap its children perfectly
                if box.layout():
                    box.layout().setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)

            # 3. Allow Qt to draw the newly added LM Studio sliders
            QtWidgets.QApplication.processEvents()

            # 4. KICK THE LAYOUT ENGINE
            # Start from the sliders and push outwards, forcing every parent to recalculate
            current = widget
            while current:
                if current.layout():
                    current.layout().invalidate()
                    current.layout().activate()
                if hasattr(current, "updateGeometry"):
                    current.updateGeometry()
                current = current.parentWidget()

        except Exception as e:
            # print(f"[DEBUG] Layout error: {e}")
            pass

    def _sync_tts_runtime_fields_height(self):
        try:
            """tts_box = getattr(self, "tts_runtime_box", None)
            if tts_box and not tts_box.isChecked():
                # Card is collapsed. Erase minimums and abort math.
                tts_box.setMinimumHeight(0)
                tabs = getattr(self, "tts_runtime_addon_tabs", None)
                if tabs:
                    tabs.setMinimumHeight(0)
                return"""
            tabs = getattr(self, "tts_runtime_addon_tabs", None)
            tts_box = getattr(self, "tts_runtime_box", None)

            if not tabs or not tts_box:
                return

            # 0. Strip the 420px hardcoded minimum from the .ui file
            tts_box.setMinimumHeight(0)
            tabs.setMinimumHeight(0)

            # 1. THE QSTACKEDWIDGET HACK
            # Qt's QTabWidget uses a hidden QStackedWidget that caches the largest tab.
            # We must aggressively hide/show policies to break that cache.
            current_idx = tabs.currentIndex()
            active_page = None

            for i in range(tabs.count()):
                page = tabs.widget(i)
                if not page:
                    continue

                policy = page.sizePolicy()
                if i == current_idx:
                    active_page = page
                    # The active tab is allowed to shrink to its true size
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
                    policy.setRetainSizeWhenHidden(False)
                    page.setMinimumHeight(0)
                    if page.layout():
                        page.layout().setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
                else:
                    # Hidden tabs must be explicitly told NOT to retain their size
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Ignored)
                    policy.setRetainSizeWhenHidden(False)

                page.setSizePolicy(policy)

                # CRITICAL: Adjust the hidden widgets so they physically report 0 height
                if i != current_idx:
                    page.adjustSize()

                    # 2. FORCE THE TAB WIDGET TO RECALCULATE
            if active_page:
                # Force the specific active page layout to re-math itself immediately
                if active_page.layout():
                    active_page.layout().invalidate()
                    active_page.layout().activate()

                # Now that the hidden tabs are truly ignored, grab the true required height
                true_height = active_page.sizeHint().height()

                # Because the QStackedWidget refuses to shrink naturally, we will forcefully
                # clamp the QTabWidget's maximum height down to the exact size of the active tab
                # plus roughly ~40px for the tab bar itself.
                tabs.setMaximumHeight(true_height + 100)

            # 3. SHATTER THE GLASS CEILING
            current = tabs.parentWidget()
            while current and current.objectName() != "host_settings_host_tab":
                if current.maximumHeight() < 16777215:
                    current.setMaximumHeight(16777215)

                layout = current.layout()
                if layout and hasattr(layout, "sizeConstraint"):
                    if layout.sizeConstraint() == QtWidgets.QLayout.SetMinAndMaxSize:
                        layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)

                current = current.parentWidget()

            # 4. MAKE THE TTS BOX STUBBORN
            for box in [tts_box]:
                policy = box.sizePolicy()
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
                box.setSizePolicy(policy)

                if box.layout():
                    box.layout().setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)

            # 5. KICK THE LAYOUT ENGINE UPWARDS
            current = tabs
            while current:
                if current.layout():
                    current.layout().invalidate()
                    current.layout().activate()
                if hasattr(current, "updateGeometry"):
                    current.updateGeometry()
                current = current.parentWidget()

        except Exception as e:
            # print(f"[DEBUG] TTS Layout error: {e}")
            pass
    def _sync_chat_provider_generation_fields_height_xx(self):
        widget = getattr(self, "chat_provider_generation_fields_widget", None)
        layout = getattr(self, "chat_provider_generation_fields_layout", None)
        if widget is None or layout is None:
            return

        try:
            # 1. Reset any old constraints so Qt can breathe
            widget.setMinimumHeight(0)
            widget.setMaximumHeight(16777215)

            # Find the main Chat Runtime card
            runtime_box = getattr(self, "chat_runtime_box", None)
            if not runtime_box:
                parent = widget.parentWidget()
                while parent:
                    if str(parent.objectName() or "") == "chat_runtime_box":
                        runtime_box = parent
                        break
                    parent = parent.parentWidget()

            if runtime_box:
                runtime_box.setMinimumHeight(0)
                runtime_box.setMaximumHeight(16777215)

            # 2. CRITICAL: Force Qt to process the UI queue so the new fields actually "exist"
            QtWidgets.QApplication.processEvents()

            # 3. Calculate and lock the exact height needed for the inner fields
            layout.invalidate()
            layout.activate()
            inner_ideal = layout.sizeHint().height()
            widget.setMinimumHeight(inner_ideal)

            # 4. Calculate and lock the exact height needed for the OUTER box
            if runtime_box:
                box_layout = runtime_box.layout()
                if box_layout:
                    box_layout.invalidate()
                    box_layout.activate()

                # Because we reset constraints and processed events, sizeHint() will
                # now naturally include the space needed for the new sliders!
                box_ideal = runtime_box.sizeHint().height()
                runtime_box.setMinimumHeight(box_ideal)

                # Make the box stubborn so the master ScrollArea doesn't crush it
                try:
                    policy = runtime_box.sizePolicy()
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
                    runtime_box.setSizePolicy(policy)
                except Exception:
                    pass

            # 5. Kick every parent up the chain to tell the Scrollbar to adjust
            current = widget.parentWidget()
            while current:
                if hasattr(current, "updateGeometry"):
                    current.updateGeometry()
                if current.layout():
                    current.layout().activate()
                current = current.parentWidget()

        except Exception as e:
            # print(f"[DEBUG] Error resizing layout: {e}")
            pass

    def _sync_chat_provider_generation_fields_height_old(self):
        widget = getattr(self, "chat_provider_generation_fields_widget", None)
        layout = getattr(self, "chat_provider_generation_fields_layout", None)
        if widget is None or layout is None:
            return
        try:
            row_count = max(1, int(layout.rowCount() or 0))
            spacing = int(layout.verticalSpacing() if hasattr(layout, "verticalSpacing") else 6)
            if spacing < 0:
                spacing = 6
            spacing = max(6, spacing)
            margins = layout.contentsMargins()
            layout.setVerticalSpacing(spacing)
            row_height = 40
            height = (
                int(margins.top())
                + int(margins.bottom())
                + (row_count * row_height)
                + (max(0, row_count - 1) * spacing)
                + 8
            )
            widget.setMinimumHeight(height)
            widget.setMaximumHeight(16777215)
            try:
                widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.MinimumExpanding)
            except Exception:
                pass
            widget.updateGeometry()
            runtime_box = None
            parent = widget.parentWidget()
            while parent is not None:
                if str(parent.objectName() or "") == "chat_runtime_box":
                    runtime_box = parent
                    break
                parent = parent.parentWidget()
            if runtime_box is None:
                runtime_box = getattr(self, "chat_runtime_box", None)
            runtime_layout = runtime_box.layout() if runtime_box is not None and hasattr(runtime_box, "layout") else None
            if runtime_box is not None:
                box_height = max(
                    int(runtime_box.minimumHeight() or 0),
                    int(runtime_layout.sizeHint().height() if runtime_layout is not None else 0),
                    height + 150,
                )
                runtime_box.setMinimumHeight(box_height)
                runtime_box.setMaximumHeight(16777215)
                try:
                    runtime_box.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.MinimumExpanding)
                except Exception:
                    pass
                runtime_box.updateGeometry()
            parent = widget.parentWidget()
            while parent is not None:
                if hasattr(parent, "updateGeometry"):
                    parent.updateGeometry()
                parent = parent.parentWidget()
        except Exception:
            pass

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
        print(f"[UI Real] tts_sync _refresh_tts_runtime_card")
        QtCore.QTimer.singleShot(0, self._sync_tts_runtime_fields_height)

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
        self._refresh_preset_dirty_state()

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

    def build_runtime_status_snapshot(self):
        config = dict(RUNTIME_CONFIG or {})
        try:
            if hasattr(self, "chat_provider_combo"):
                config["chat_provider"] = self._current_chat_provider_value()
            if hasattr(self, "model_combo"):
                config["model_name"] = self.model_combo.currentText()
            if hasattr(self, "tts_backend_combo"):
                config["tts_backend"] = self._current_tts_backend_value()
            if hasattr(self, "engine_combo"):
                config["avatar_mode"] = self._current_avatar_mode_value()
        except Exception:
            pass
        running = bool(getattr(self, "thread", None) and self.thread.is_alive())
        listening = bool(getattr(engine, "listening_active", None) and engine.listening_active.is_set())
        recording = bool(getattr(engine, "microphone_active", None) and engine.microphone_active.is_set())
        paused = bool(getattr(engine, "playback_paused", None) and engine.playback_paused.is_set())
        paused = paused or bool(getattr(engine, "pause_after_chunk", None) and engine.pause_after_chunk.is_set())
        return build_runtime_status_snapshot(
            config,
            running=running,
            engine_connected=running,
            shell_mode=False,
            lifecycle_state="running" if running else "stopped",
            listening=listening,
            recording=recording,
            playback_paused=paused,
            source="qt_app",
        )

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
            "engine": self._current_avatar_mode_value() if hasattr(self, "engine_combo") else "",
            "musetalk_vram_mode": self.musetalk_vram_combo.currentText() if hasattr(self, "musetalk_vram_combo") else "",
            "musetalk_avatar_pack": self.musetalk_avatar_pack_combo.currentText() if hasattr(self, "musetalk_avatar_pack_combo") else "",
            "musetalk_loop_fade_ms": int(self.musetalk_loop_fade_spin.value()) if hasattr(self, "musetalk_loop_fade_spin") else int(RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS),
            "musetalk_use_frame_cache": bool(self.musetalk_use_frame_cache_checkbox.isChecked()) if hasattr(self, "musetalk_use_frame_cache_checkbox") else bool(RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)),
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
                    "qt.chat_context": QtChatContextService(self),
                    "qt.dialogs": QtDialogService(self),
                    "qt.dry_run": QtDryRunService(self),
                    "qt.engine_lifecycle": QtEngineLifecycleService(self),
                    "qt.hotkeys": QtHotkeyService(self),
                    "qt.input_actions": QtInputActionService(self),
                    "qt.input_settings": QtInputSettingsService(self),
                    "qt.persona_avatar": QtPersonaAvatarService(self),
                    "qt.performance_profiles": QtPerformanceProfileService(self),
                    "qt.model_refresh": QtModelRefreshService(self),
                    "qt.runtime_controls": QtRuntimeControlService(self),
                    "qt.runtime_status": QtRuntimeStatusService(self),
                    "qt.shell": QtShellService(self),
                    "qt.tutorials": QtTutorialService(self),
                    "qt.musetalk_ui": QtMuseTalkUIService(self),
                    "qt.visual_reply": QtVisualReplyService(self),
                    "qt.avatar_providers": QtAvatarProviderService(self),
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

    def _on_tts_runtime_addon_tab_changed_old(self, index):
        if not hasattr(self, "tts_runtime_addon_tabs"):
            return
        current = self.tts_runtime_addon_tabs.widget(index)
        if current is None:
            return
        backend_id = str(current.property("backend_id") or current.objectName() or "").strip().lower()
        if backend_id:
            self._tts_runtime_tab_index_by_backend[backend_id] = index

    def _on_tts_runtime_addon_tab_changed(self, index):
        if not hasattr(self, "tts_runtime_addon_tabs"):
            return
        current = self.tts_runtime_addon_tabs.widget(index)
        if current is None:
            return
        backend_id = str(current.property("backend_id") or current.objectName() or "").strip().lower()
        if backend_id:
            self._tts_runtime_tab_index_by_backend[backend_id] = index

        # NEW: Re-calculate the layout bounds for the newly selected tab
        sync_func = getattr(self, "_sync_tts_runtime_fields_height", None)
        if not sync_func:
            backend = getattr(self, "backend", None)
            sync_func = getattr(backend, "_sync_tts_runtime_fields_height", None)

        if sync_func:
            QtCore.QTimer.singleShot(10, sync_func)

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
            "musetalk_use_frame_cache": bool(self.musetalk_use_frame_cache_checkbox.isChecked()) if hasattr(self, "musetalk_use_frame_cache_checkbox") else bool(RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)),
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
        if not bool(getattr(self, "_preset_dirty_tracking_ready", False)):
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
        self._preset_dirty_tracking_ready = True
        self._refresh_preset_dirty_state()

    def _update_preset_reference_from_current_state(self, preset_name=None):
        name = str(preset_name or self.preset_combo.currentText() or "").strip()
        if name in {"", "Select Preset...", "No Presets"}:
            self._preset_reference_name = ""
        else:
            self._preset_reference_name = name
        self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
        self._preset_dirty_tracking_ready = True
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
        self._update_preset_reference_from_current_state(self.preset_combo.currentText() if hasattr(self, "preset_combo") else "")
        self._refresh_preset_dirty_state()

    def on_preset_selection_changed(self, text):
        selected = str(text or "").strip()
        if selected in {"", "Select Preset...", "No Presets"}:
            update_runtime_config("active_preset_name", "")
        else:
            update_runtime_config("active_preset_name", selected)
        self._update_preset_reference_from_selection(selected)

    def _poll_runtime_status(self):
        runtime_status = self.build_runtime_status_snapshot()
        listening = bool(runtime_status.listening)
        recording = bool(runtime_status.recording)
        if hasattr(self, "listen_diode"):
            self.listen_diode.setStyleSheet(self._status_diode_style(listening, "#39d98a", "#92f0bf"))
        if hasattr(self, "mic_diode"):
            self.mic_diode.setStyleSheet(self._status_diode_style(recording, "#ff4d5e", "#ff96a0"))
        if hasattr(self, "mic_status_label"):
            label = {"recording": "Recording", "listening": "Listening"}.get(runtime_status.microphone_state, "Microphone idle")
            self.mic_status_label.setText(label)
        if hasattr(self, "pipeline_telemetry_widget"):
            pipeline_snapshot = self._build_pipeline_visual_snapshot(
                shared_state.get_musetalk_pipeline_snapshot()
            )
            self.pipeline_telemetry_widget.update_snapshot(
                pipeline_snapshot,
                getattr(shared_state, "current_musetalk_frame_data", {}) or {},
            )
        paused = bool(runtime_status.playback_paused)
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

    def _resolve_audio_device_label(self, label, *, direction):
        default_label = "Default Output" if direction == "output" else "Default Input"
        selected = str(label or "").strip() or default_label
        options_key = "outputs" if direction == "output" else "inputs"
        options = list((_ui_shell_audio_device_labels().get(options_key) or [default_label]))
        for option in options:
            if str(option or "").strip().lower() == selected.lower():
                return str(option or "").strip() or default_label
        return default_label

    def on_audio_input_device_change(self, choice):
        resolved = self._resolve_audio_device_label(choice, direction="input")
        update_runtime_config("audio_input_device", resolved)
        self.save_session()

    def on_audio_output_device_change(self, choice):
        resolved = self._resolve_audio_device_label(choice, direction="output")
        update_runtime_config("audio_output_device", resolved)
        self.save_session()

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

    def on_musetalk_use_frame_cache_changed(self, checked):
        enabled = bool(checked)
        update_runtime_config("musetalk_use_frame_cache", enabled)
        self.emit_tutorial_event("ui_changed", {"field": "musetalk_use_frame_cache", "value": enabled})
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
        selected_model = str(choice or "").strip()
        update_runtime_config("model_name", selected_model)
        update_runtime_config("model_supports_images", self._current_model_supports_images_value(selected_model))
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
            "avatar_mode": self._current_avatar_mode_value(),
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
        if "musetalk_use_frame_cache" in settings and hasattr(self, "musetalk_use_frame_cache_checkbox"):
            self.musetalk_use_frame_cache_checkbox.setChecked(bool(settings["musetalk_use_frame_cache"]))
            self.on_musetalk_use_frame_cache_changed(bool(settings["musetalk_use_frame_cache"]))
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
        avatar_mode = self._current_avatar_mode_value() if hasattr(self, "engine_combo") else str(RUNTIME_CONFIG.get("avatar_mode", "vseeface") or "vseeface").strip().lower()
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
        update_runtime_config("musetalk_use_frame_cache", self.musetalk_use_frame_cache_checkbox.isChecked() if hasattr(self, "musetalk_use_frame_cache_checkbox") else bool(RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)))
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
        mode = self._current_avatar_mode_value()
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
        if self._current_avatar_mode_value() != "vseeface":
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
        )
        negative_fragments = (
            "embedding", "rerank", "whisper", "tts", "audio", "transcribe", "grok-imagine"
        )
        if any(fragment in value for fragment in negative_fragments):
            return False
        return any(fragment in value for fragment in positive_fragments)

    def _current_model_supports_images_value(self, model_name=None):
        selected_model = str(model_name or (self.model_combo.currentText() if hasattr(self, "model_combo") else "") or "").strip()
        if not selected_model:
            return False
        for entry in list(getattr(self, "_all_model_catalog", []) or []):
            if str(entry.get("id") or "").strip() != selected_model:
                continue
            return bool(entry.get("supports_images", False))
        return self._infer_model_supports_images(selected_model)

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
            if bool(getattr(self, "_closing", False)):
                return
            try:
                QtCore.QMetaObject.invokeMethod(self, "_apply_pending_model_refresh", QtCore.Qt.QueuedConnection)
            except RuntimeError:
                # The hidden backend can be destroyed during --ui-real smoke shutdown
                # while a provider model refresh is still returning.
                return

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
            update_runtime_config("model_supports_images", self._current_model_supports_images_value(selected_model))
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
            "avatar_mode": self._current_avatar_mode_value() if hasattr(self, "engine_combo") else "",
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
        avatar_mode = self._current_avatar_mode_value() if hasattr(self, "engine_combo") else "musetalk"
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
            self._populate_tts_backend_combo(selected_value="chatterbox")
            index = self.tts_backend_combo.findData("chatterbox")
            if index >= 0:
                self.tts_backend_combo.setCurrentIndex(index)
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
        if "musetalk_use_frame_cache" in data and hasattr(self, "musetalk_use_frame_cache_checkbox"):
            self.musetalk_use_frame_cache_checkbox.setChecked(bool(data["musetalk_use_frame_cache"]))
            self.on_musetalk_use_frame_cache_changed(bool(data["musetalk_use_frame_cache"]))
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
        if self._current_avatar_mode_value() != "musetalk":
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
        if self._current_avatar_mode_value() != "musetalk":
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
        self._hide_main_preserving_pinned_floating_docks()
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
        mode = self._current_avatar_mode_value()
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
            "audio_input_device": self.audio_input_device_combo.currentText() if hasattr(self, "audio_input_device_combo") else str(RUNTIME_CONFIG.get("audio_input_device", "Default Input") or "Default Input"),
            "audio_output_device": self.audio_output_device_combo.currentText() if hasattr(self, "audio_output_device_combo") else str(RUNTIME_CONFIG.get("audio_output_device", "Default Output") or "Default Output"),
            "offline_replay_only": bool(offline_replay_only),
            "tts_backend": self._current_tts_backend_value(),
            "musetalk_avatar_pack_id": str(self.musetalk_avatar_pack_combo.currentData() or RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or ""),
            "musetalk_vram_mode": next(
                (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self.musetalk_vram_combo.currentText()),
                "quality",
            ),
            "musetalk_use_frame_cache": bool(self.musetalk_use_frame_cache_checkbox.isChecked()) if hasattr(self, "musetalk_use_frame_cache_checkbox") else bool(RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)),
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
            if not self._closing:
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
        if bool(getattr(self, "_session_read_only", False)):
            return
        if bool(getattr(self, "_suspend_session_save", False)):
            return
        preserved_main_ui_real_layout = None
        try:
            if SESSION_PATH.exists():
                previous_session = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                if isinstance(previous_session, dict):
                    preserved_main_ui_real_layout = previous_session.get("main_ui_real_layout")
        except Exception:
            preserved_main_ui_real_layout = None
        session = {
            "first_run": bool(self.first_run),
            "ui_theme_preset": self.current_app_theme_preset(),
            "avatar_mode": self._current_avatar_mode_value(),
            "audio_input_device": self.audio_input_device_combo.currentText() if hasattr(self, "audio_input_device_combo") else str(RUNTIME_CONFIG.get("audio_input_device", "Default Input") or "Default Input"),
            "audio_output_device": self.audio_output_device_combo.currentText() if hasattr(self, "audio_output_device_combo") else str(RUNTIME_CONFIG.get("audio_output_device", "Default Output") or "Default Output"),
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
            "musetalk_use_frame_cache": bool(self.musetalk_use_frame_cache_checkbox.isChecked()) if hasattr(self, "musetalk_use_frame_cache_checkbox") else bool(RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)),
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
            "pinned_floating_docks": sorted(getattr(self, "_pinned_floating_dock_names", set()) or []),
            "always_on_top_floating_docks": sorted(getattr(self, "_always_on_top_floating_dock_names", set()) or []),
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
        if isinstance(preserved_main_ui_real_layout, dict):
            session["main_ui_real_layout"] = preserved_main_ui_real_layout
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
            ui_theme_preset = session.get("ui_theme_preset")
            if ui_theme_preset is not None:
                self.apply_app_theme_preset(ui_theme_preset, save_session=False)
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
                index = self.engine_combo.findData(str(engine_choice).strip().lower())
                if index < 0:
                    index = self.engine_combo.findText(engine_choice)
                if index >= 0:
                    self.engine_combo.setCurrentIndex(index)
            if str(engine_choice or "").strip().lower() == "vam" and hasattr(self, "vam_play_audio_in_vam_checkbox"):
                self.vam_play_audio_in_vam_checkbox.setChecked(True)
                self.on_vam_play_audio_in_vam_changed(True)
            audio_input_device = session.get("audio_input_device")
            if audio_input_device is not None:
                audio_input_device = self._resolve_audio_device_label(audio_input_device, direction="input")
                update_runtime_config("audio_input_device", str(audio_input_device or "Default Input") or "Default Input")
                if hasattr(self, "audio_input_device_combo"):
                    self.audio_input_device_combo.blockSignals(True)
                    index = self.audio_input_device_combo.findText(str(audio_input_device))
                    if index >= 0:
                        self.audio_input_device_combo.setCurrentIndex(index)
                    self.audio_input_device_combo.blockSignals(False)
            audio_output_device = session.get("audio_output_device")
            if audio_output_device is not None:
                audio_output_device = self._resolve_audio_device_label(audio_output_device, direction="output")
                update_runtime_config("audio_output_device", str(audio_output_device or "Default Output") or "Default Output")
                if hasattr(self, "audio_output_device_combo"):
                    self.audio_output_device_combo.blockSignals(True)
                    index = self.audio_output_device_combo.findText(str(audio_output_device))
                    if index >= 0:
                        self.audio_output_device_combo.setCurrentIndex(index)
                    self.audio_output_device_combo.blockSignals(False)
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
            musetalk_use_frame_cache = session.get("musetalk_use_frame_cache")
            if musetalk_use_frame_cache is not None and hasattr(self, "musetalk_use_frame_cache_checkbox"):
                self.musetalk_use_frame_cache_checkbox.setChecked(bool(musetalk_use_frame_cache))
                self.on_musetalk_use_frame_cache_changed(bool(musetalk_use_frame_cache))
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
            self._pinned_floating_dock_names = {
                str(item or "").strip()
                for item in list(session.get("pinned_floating_docks", []) or [])
                if str(item or "").strip()
            }
            self._always_on_top_floating_dock_names = {
                str(item or "").strip()
                for item in list(session.get("always_on_top_floating_docks", []) or [])
                if str(item or "").strip()
            }
            self._apply_legacy_dock_title_widgets()
            suppress_aux_docks = bool(getattr(self, "_suppress_restored_aux_docks", False))
            if bool(session.get("preview_visible", False)) and not suppress_aux_docks:
                self.preview_dock.show()
            else:
                self.preview_dock.hide()
            if bool(session.get("visual_reply_visible", False)) and not suppress_aux_docks:
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
    _configure_app_entry_dependencies()
    run_qt_app()


if __name__ == "__main__":
    main()
