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
from collections import OrderedDict
from pathlib import Path
import xml.etree.ElementTree as ET

from core.musetalk_avatar_packs import discover_avatar_packs
from core.expression_api import start_expression_api
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
from ui.runtime.backend_addon_mounts import BackendAddonMountMixin
from ui.runtime.backend_chat_runtime import BackendChatRuntimeMixin
from ui.runtime.backend_console_chat import BackendConsoleChatMixin
from ui.runtime.backend_hotkeys import BackendHotkeyMixin
from ui.runtime.backend_operational_panel import BackendOperationalPanelMixin
from ui.runtime.backend_sensory_sources import BackendSensorySourcesMixin
from ui.runtime.backend_system_shaping_panel import BackendSystemShapingPanelMixin
from ui.runtime.backend_tts_runtime import BackendTtsRuntimeMixin
from ui.runtime.backend_vam_runtime import BackendVamRuntimeMixin
from ui.runtime.backend_visual_reply_runtime import BackendVisualReplyRuntimeMixin
from ui.runtime.backend_workspace_tabs import BackendWorkspaceTabsMixin
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
from ui.runtime.shell_addon_mounts import (
    _apply_ui_shell_addon_placeholders,
    _ui_shell_cleanup_live_addons,
    _ui_shell_mount_live_addons,
    configure_shell_addon_mount_dependencies,
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
    configure_shell_addon_mount_dependencies(globals())


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
try:
    import cv2
except Exception:
    cv2 = None
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
try:
    import shiboken6
except Exception:  # pragma: no cover - defensive for tooling without full PySide install
    shiboken6 = None
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
warnings.filterwarnings(
    "ignore",
    message=r".*pkg_resources is deprecated as an API.*",
    category=UserWarning,
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


APP_TITLE = "Neural Companion"
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
    # The top-level window stylesheet is rebuilt from APP_STYLESHEET on every
    # theme apply. Do not re-canonicalize it here from the currently active
    # themed stylesheet; themes that intentionally reuse colors can poison the
    # cached base stylesheet and make later theme changes unrecoverable.
    widgets = []
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

def start_api():
    start_expression_api(shared_state, port=5005)


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


class CompanionQtMainWindow(BackendAddonMountMixin, BackendChatRuntimeMixin, BackendConsoleChatMixin, BackendHotkeyMixin, BackendOperationalPanelMixin, BackendSensorySourcesMixin, BackendSystemShapingPanelMixin, BackendTtsRuntimeMixin, BackendVamRuntimeMixin, BackendVisualReplyRuntimeMixin, BackendWorkspaceTabsMixin, LegacyWorkspaceDockMixin, LegacyDockTitleMixin, QtWidgets.QMainWindow):
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

    def _avatar_provider_options(self):
        providers = []
        for provider in avatar_runtime.list_providers():
            summary = provider.to_summary()
            provider_id = str(summary.get("id") or "").strip().lower()
            if provider_id:
                providers.append(summary)
        if providers or getattr(self, "_addon_manager", None) is not None:
            return sorted(
                providers,
                key=lambda item: (int(item.get("order", 1000) or 1000), str(item.get("label", "")).lower()),
            )
        legacy = {
            "vseeface": {"id": "vseeface", "label": "VSeeFace", "order": 100},
            "musetalk": {"id": "musetalk", "label": "MuseTalk", "order": 200},
            "vam": {"id": "vam", "label": "VaM", "order": 300},
            "none": {"id": "none", "label": "None", "order": 900},
        }
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
            if index < 0 and combo.count() > 0:
                index = 0
            if index >= 0:
                combo.setCurrentIndex(index)
                provider_id = str(combo.currentData() or "").strip().lower()
                if provider_id:
                    update_runtime_config("avatar_mode", provider_id)
        finally:
            combo.blockSignals(False)

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


    def _is_model_catalog_placeholder(self, model_name):
        value = str(model_name or "").strip()
        lowered = value.lower()
        return (not value) or lowered in {"scanning...", "no models", "no vision models"} or lowered.startswith("error: check ")

    def _on_runtime_section_toggled(self):
        self._sync_host_settings_tabs_height()
        self.save_session()

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
        musetalk_vram_label = self._live_combo_text("musetalk_vram_combo", "")
        visual_reply_mode = self._visual_reply_mode_value_from_label(self._live_combo_text("visual_reply_mode_combo", "Auto"))
        visual_reply_provider = self._visual_reply_provider_value_from_label(self._live_combo_text("visual_reply_provider_combo", "OpenAI"))
        return {
            "engine": self._current_avatar_mode_value() if hasattr(self, "engine_combo") else "",
            "musetalk_vram_mode": musetalk_vram_label,
            "musetalk_avatar_pack": self._live_combo_text("musetalk_avatar_pack_combo", ""),
            "musetalk_loop_fade_ms": int(self._live_value("musetalk_loop_fade_spin", RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS)),
            "musetalk_use_frame_cache": self._live_checked("musetalk_use_frame_cache_checkbox", RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)),
            "visual_reply_mode": visual_reply_mode,
            "visual_reply_provider": visual_reply_provider,
            "visual_reply_size": self._normalize_visual_reply_size(self._live_combo_text("visual_reply_size_combo", RUNTIME_CONFIG.get("visual_reply_size", "1024x1024"))),
            "visual_reply_model": self._live_text("visual_reply_model_edit", RUNTIME_CONFIG.get("visual_reply_model", "gpt-image-1")).strip() or "gpt-image-1",
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {}) or {}),
            "musetalk_vram_mode_key": next((key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == musetalk_vram_label), "quality"),
            "preview_visible": bool(hasattr(self, "preview_dock") and self.preview_dock.isVisible()),
            "visual_reply_visible": bool(
                self._addon_effectively_enabled("nc.visual_reply")
                and hasattr(self, "visual_reply_dock")
                and self.visual_reply_dock.isVisible()
            ),
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
                    "qt.bind_designer_widgets": self._bind_designer_widgets,
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
            self.refresh_avatar_engine_options(selected_provider_id=str(RUNTIME_CONFIG.get("avatar_mode", "") or ""))
            self._mount_tts_runtime_addon_tabs()
            self._populate_tts_backend_combo(selected_value=self._current_tts_backend_value())
            self.refresh_sensory_feedback_source_options(selected_value=str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"))
            self._mount_addon_tabs()
            self._mount_host_settings_addon_tabs()
            self._mount_operational_view_addon_tabs()
            self._mount_musetalk_addon_tabs()
            self._apply_disabled_addon_surfaces()
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

    def _bind_designer_widgets(self, root_widget):
        if root_widget is None:
            return
        widgets = [root_widget]
        try:
            widgets.extend(root_widget.findChildren(QtWidgets.QWidget))
        except Exception:
            pass
        for widget in widgets:
            try:
                object_name = str(widget.objectName() or "").strip()
            except Exception:
                object_name = ""
            if not object_name:
                continue
            setattr(self, object_name, widget)

    def _status_diode_style(self, active, active_fill, active_border):
        if active:
            return (
                f"background: {active_fill}; border: 1px solid {active_border}; border-radius: 8px;"
            )
        return "background: #4b5563; border: 1px solid #6b7280; border-radius: 8px;"

    def _build_preset_payload(self, ensure_pocket_tts_path=False):
        pocket_tts_python = self._live_text("pocket_tts_python_edit", "")
        if ensure_pocket_tts_path and self._current_tts_backend_value() == "pockettts":
            pocket_tts_python = self._ensure_pocket_tts_python_path()
        chat_provider_generation_settings = dict(RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {})
        payload = {
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}),
            "model_name": self.model_combo.currentText(),
            "voice_file": self._current_voice_file_value(),
            "input_mode": "push_to_talk" if self.input_mode_combo.currentText() == "Push-to-Talk" else "voice_activation",
            "input_message_role": self._input_role_value_from_label(self.input_role_combo.currentText()),
            "stream_mode": self.stream_mode_combo.currentText() == "On",
            "tts_backend": self._current_tts_backend_value(),
            "tts_seed": int(self._live_value("tts_seed_spin", RUNTIME_CONFIG.get("tts_seed", 0) or 0)),
            "tts_temperature": float(self._live_value("tts_temperature_spin", RUNTIME_CONFIG.get("tts_temperature", 0.8) or 0.8)),
            "tts_top_p": float(self._live_value("tts_top_p_spin", RUNTIME_CONFIG.get("tts_top_p", 0.9) or 0.9)),
            "tts_top_k": int(self._live_value("tts_top_k_spin", RUNTIME_CONFIG.get("tts_top_k", 40) or 40)),
            "tts_repeat_penalty": float(self._live_value("tts_repeat_penalty_spin", RUNTIME_CONFIG.get("tts_repeat_penalty", 1.2) or 1.2)),
            "tts_min_p": float(self._live_value("tts_min_p_spin", RUNTIME_CONFIG.get("tts_min_p", 0.0) or 0.0)),
            "tts_normalize_loudness": self._live_checked("tts_normalize_loudness_checkbox", RUNTIME_CONFIG.get("tts_normalize_loudness", False)),
            "musetalk_avatar_pack_id": str(self._live_combo_data("musetalk_avatar_pack_combo", RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "")) or ""),
            "musetalk_loop_fade_ms": int(self._live_value("musetalk_loop_fade_spin", RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS) or QT_MUSETALK_LOOP_FADE_MS)),
            "musetalk_use_frame_cache": self._live_checked("musetalk_use_frame_cache_checkbox", RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)),
            "visual_reply_mode": self._visual_reply_mode_value_from_label(self._live_combo_text("visual_reply_mode_combo", "Auto")),
            "visual_reply_provider": self._visual_reply_provider_value_from_label(self._live_combo_text("visual_reply_provider_combo", "OpenAI")),
            "visual_reply_size": self._normalize_visual_reply_size(self._live_combo_text("visual_reply_size_combo", RUNTIME_CONFIG.get("visual_reply_size", "1024x1024"))),
            "visual_reply_model": self._live_text("visual_reply_model_edit", RUNTIME_CONFIG.get("visual_reply_model", "gpt-image-1")).strip() or "gpt-image-1",
            "visual_reply_auto_show_dock": self._live_checked("visual_reply_auto_show_checkbox", RUNTIME_CONFIG.get("visual_reply_auto_show_dock", True)),
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
        combo = self._live_widget_attr("musetalk_avatar_pack_combo")
        if combo is None:
            return
        requested = str(selected_pack_id or combo.currentData() or RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "") or "").strip()
        catalog = list(engine.get_musetalk_avatar_pack_catalog() or [])
        combo.blockSignals(True)
        combo.clear()
        for item in catalog:
            pack_id = str(item.get("id") or "").strip()
            if not pack_id:
                continue
            display_name = str(item.get("display_name") or pack_id).strip()
            default_avatar_id = str(item.get("default_avatar_id") or "default_avatar").strip()
            source = str(item.get("source") or "manifest").strip()
            label = f"{display_name} | {default_avatar_id} [{source}]"
            combo.addItem(label, pack_id)
        if combo.count() <= 0:
            combo.addItem("No avatar packs found", "")
        target_index = -1
        for index in range(combo.count()):
            if str(combo.itemData(index) or "") == requested:
                target_index = index
                break
        combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        combo.blockSignals(False)

    def on_musetalk_avatar_pack_change(self, _choice):
        pack_id = str(self._live_combo_data("musetalk_avatar_pack_combo", "") or "").strip()
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

    def on_chat_font_size_changed(self, _index):
        if not hasattr(self, "chat_font_size_combo"):
            return
        size = self.chat_font_size_combo.currentData()
        if size is None:
            return
        self._apply_chat_font_size(size, update_combo=False)
        self.save_session()

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
            "musetalk_avatar_pack_id": str(self._live_combo_data("musetalk_avatar_pack_combo", RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "")) or ""),
            "musetalk_vram_mode": next(
                (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self._live_combo_text("musetalk_vram_combo", "")),
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
        widget = self._live_widget_attr("musetalk_vram_combo")
        if "musetalk_vram_mode" in settings and widget is not None:
            widget.setCurrentText(MUSE_VRAM_MODE_LABELS.get(str(settings["musetalk_vram_mode"]).lower(), "Quality"))
        widget = self._live_widget_attr("musetalk_loop_fade_spin")
        if "musetalk_loop_fade_ms" in settings and widget is not None:
            fade_ms = max(0, int(settings["musetalk_loop_fade_ms"] or 0))
            widget.setValue(fade_ms)
            self.on_musetalk_loop_fade_changed(fade_ms)
        widget = self._live_widget_attr("musetalk_use_frame_cache_checkbox")
        if "musetalk_use_frame_cache" in settings and widget is not None:
            widget.setChecked(bool(settings["musetalk_use_frame_cache"]))
            self.on_musetalk_use_frame_cache_changed(bool(settings["musetalk_use_frame_cache"]))
        widget = self._live_widget_attr("visual_reply_mode_combo")
        if "visual_reply_mode" in settings and widget is not None:
            mode_text = self._visual_reply_mode_label_from_value(settings["visual_reply_mode"])
            widget.setCurrentText(mode_text)
            self.on_visual_reply_mode_changed(mode_text)
        widget = self._live_widget_attr("visual_reply_provider_combo")
        if "visual_reply_provider" in settings and widget is not None:
            provider_text = self._visual_reply_provider_label_from_value(settings["visual_reply_provider"])
            widget.setCurrentText(provider_text)
            self.on_visual_reply_provider_changed(provider_text)
        widget = self._live_widget_attr("visual_reply_size_combo")
        if "visual_reply_size" in settings and widget is not None:
            size_text = self._normalize_visual_reply_size(settings["visual_reply_size"])
            widget.setCurrentText(self._visual_reply_size_label_from_value(size_text))
            self.on_visual_reply_size_changed(size_text)
        widget = self._live_widget_attr("visual_reply_model_edit")
        if "visual_reply_model" in settings and widget is not None:
            widget.setText(str(settings["visual_reply_model"] or "gpt-image-1"))
            self.on_visual_reply_model_changed()
        widget = self._live_widget_attr("visual_reply_auto_show_checkbox")
        if "visual_reply_auto_show_dock" in settings and widget is not None:
            auto_show = bool(settings["visual_reply_auto_show_dock"])
            widget.setChecked(auto_show)
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
            (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self._live_combo_text("musetalk_vram_combo", "")),
            "quality",
        )
        update_runtime_config("input_mode", mode)
        update_runtime_config("input_message_role", role)
        update_runtime_config("stream_mode", stream_mode)
        update_runtime_config("tts_backend", tts_backend)
        update_runtime_config("musetalk_vram_mode", musetalk_vram_mode)
        update_runtime_config("musetalk_use_frame_cache", self._live_checked("musetalk_use_frame_cache_checkbox", RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)))
        update_runtime_config("musetalk_avatar_pack_id", str(self._live_combo_data("musetalk_avatar_pack_combo", RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "")) or ""))
        update_runtime_config("allow_proactive_replies", self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else True)
        update_runtime_config("require_first_user_before_proactive", self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False)
        update_runtime_config("listen_idle_window_seconds", round(float(self.listen_idle_window_spin.value()), 1) if hasattr(self, "listen_idle_window_spin") else 5.0)
        update_runtime_config("proactive_delay_seconds", round(float(self.proactive_delay_spin.value()), 1) if hasattr(self, "proactive_delay_spin") else 10.0)
        update_runtime_config("chat_context_window_messages", max(4, int(self.chat_context_window_spin.value())) if hasattr(self, "chat_context_window_spin") else 20)
        update_runtime_config("stored_chat_history_limit", max(0, int(self.stored_chat_history_limit_spin.value())) if hasattr(self, "stored_chat_history_limit_spin") else 0)
        update_runtime_config("chat_context_overflow_policy", self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window")
        update_runtime_config("pocket_tts_python", self._live_text("pocket_tts_python_edit", RUNTIME_CONFIG.get("pocket_tts_python", "")).strip())
        update_runtime_config("vam_vmc_enabled", self._live_checked("vam_vmc_enabled_checkbox", True))
        update_runtime_config("vam_bridge_enabled", self._live_checked("vam_bridge_enabled_checkbox", True))
        update_runtime_config("vam_play_audio_in_vam", True if avatar_mode == "vam" else self._live_checked("vam_play_audio_in_vam_checkbox", False))
        update_runtime_config("vam_timeline_auto_resume", self._live_checked("vam_timeline_auto_resume_checkbox", True))
        update_runtime_config("vam_vmc_host", self._live_text("vam_vmc_host_edit", RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1")).strip() or "127.0.0.1")
        update_runtime_config("vam_vmc_port", int(self._live_value("vam_vmc_port_spin", RUNTIME_CONFIG.get("vam_vmc_port", 39539) or 39539)))
        update_runtime_config("vam_root", self._current_vam_root_value())
        update_runtime_config("vam_bridge_root", self._current_vam_bridge_root_value())
        update_runtime_config("vam_target_atom_uid", self._live_text("vam_target_atom_uid_edit", RUNTIME_CONFIG.get("vam_target_atom_uid", "Person")).strip() or "Person")
        update_runtime_config("vam_target_storable_id", self._live_text("vam_target_storable_id_edit", RUNTIME_CONFIG.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge")).strip())
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
        vam_play_audio = self._live_widget_attr("vam_play_audio_in_vam_checkbox")
        if mode == "vam" and vam_play_audio is not None and not vam_play_audio.isChecked():
            vam_play_audio.setChecked(True)
            update_runtime_config("vam_play_audio_in_vam", True)
        controls_enabled = mode == "vseeface"
        for widget in [
            self._live_widget_attr("body_combo"),
            self._live_widget_attr("btn_body_load"),
            self._live_widget_attr("btn_body_save"),
            self._live_widget_attr("btn_body_save_as"),
            self._live_widget_attr("btn_body_delete"),
            self._live_widget_attr("btn_hand_doctor"),
            self._live_widget_attr("emotion_combo"),
            self._live_widget_attr("live_sync_checkbox"),
        ]:
            if widget is not None:
                widget.setEnabled(controls_enabled)
        for slider in self.pose_sliders.values():
            if self._qt_object_alive(slider):
                slider.setEnabled(controls_enabled)
        preview_button = self._live_widget_attr("btn_musetalk_preview")
        if preview_button is not None:
            preview_button.setEnabled(mode == "musetalk")
        focus_button = self._live_widget_attr("btn_musetalk_avatar_focus")
        if focus_button is not None:
            focus_button.setEnabled(mode == "musetalk")
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
            if self._qt_object_alive(slider):
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
        else:
            update_runtime_config("voice_path", "")

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
        musetalk_vram_combo = self._live_widget_attr("musetalk_vram_combo")
        if musetalk_vram_combo is not None:
            musetalk_vram_combo.setCurrentText(MUSE_VRAM_MODE_LABELS.get(vram_mode, "Quality"))
        for key, slider in self.brain_sliders.items():
            slider.set_value(RUNTIME_CONFIG.get(key, slider.value()))
        for key, slider in self.chunking_sliders.items():
            slider.set_value(RUNTIME_CONFIG.get(key, slider.value()))
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()
        emotion_combo = self._live_widget_attr("emotion_combo")
        if emotion_combo is not None:
            self.on_emotion_change(emotion_combo.currentText())
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
        if self._is_model_catalog_placeholder(selected_model):
            return False
        if hasattr(self, "model_requires_vision_checkbox") and self.model_requires_vision_checkbox.isChecked():
            return True
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
        update_runtime_config("model_requires_vision", bool(_checked))
        self.refresh_model_list_quietly(quiet=True, preloaded_models=list(getattr(self, "_all_model_catalog", []) or []))
        selected_model = str(self.model_combo.currentText() if hasattr(self, "model_combo") else RUNTIME_CONFIG.get("model_name", "") or "").strip()
        if selected_model:
            update_runtime_config("model_supports_images", self._current_model_supports_images_value(selected_model))
            self._refresh_chat_runtime_summary()
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
            if current:
                update_runtime_config("model_name", current)
                update_runtime_config("model_supports_images", self._current_model_supports_images_value(current))
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
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is None:
            return
        bodies = [Path(path).stem for path in glob.glob("body_configs/*.json")]
        body_combo.clear()
        body_combo.addItems(bodies or ["No Configs"])

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
            "musetalk_vram_mode": self._live_combo_text("musetalk_vram_combo", ""),
            "musetalk_avatar_pack": self._live_combo_text("musetalk_avatar_pack_combo", ""),
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
        vram_mode_label = self._live_combo_text("musetalk_vram_combo", "Very Low VRAM").strip() or "Very Low VRAM"

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
        widget = self._live_widget_attr("musetalk_vram_combo")
        if widget is not None:
            widget.setCurrentText("Very Low VRAM")
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
            voice_file = str(data.get("voice_file") or "").strip()
            if voice_file and voice_file != "No .wav found" and self.voice_combo.findText(voice_file) >= 0:
                index = self.voice_combo.findText(voice_file)
                self.voice_combo.setCurrentIndex(index)
            else:
                update_runtime_config("voice_path", "")
        if "input_mode" in data:
            mode_text = "Push-to-Talk" if str(data["input_mode"]).lower() == "push_to_talk" else "Voice Activation"
            self.input_mode_combo.setCurrentText(mode_text)
        if "input_message_role" in data:
            role_text = self._input_role_label_from_value(data["input_message_role"])
            self.input_role_combo.setCurrentText(role_text)
        if "stream_mode" in data:
            self.stream_mode_combo.setCurrentText("On" if bool(data["stream_mode"]) else "Off")
        widget = self._live_widget_attr("musetalk_loop_fade_spin")
        if "musetalk_loop_fade_ms" in data and widget is not None:
            fade_ms = max(0, int(data["musetalk_loop_fade_ms"] or 0))
            widget.setValue(fade_ms)
            self.on_musetalk_loop_fade_changed(fade_ms)
        widget = self._live_widget_attr("musetalk_use_frame_cache_checkbox")
        if "musetalk_use_frame_cache" in data and widget is not None:
            widget.setChecked(bool(data["musetalk_use_frame_cache"]))
            self.on_musetalk_use_frame_cache_changed(bool(data["musetalk_use_frame_cache"]))
        widget = self._live_widget_attr("visual_reply_mode_combo")
        if "visual_reply_mode" in data and widget is not None:
            mode_text = self._visual_reply_mode_label_from_value(data["visual_reply_mode"])
            widget.setCurrentText(mode_text)
            self.on_visual_reply_mode_changed(mode_text)
        widget = self._live_widget_attr("visual_reply_provider_combo")
        if "visual_reply_provider" in data and widget is not None:
            provider_text = self._visual_reply_provider_label_from_value(data["visual_reply_provider"])
            widget.setCurrentText(provider_text)
            self.on_visual_reply_provider_changed(provider_text)
        widget = self._live_widget_attr("visual_reply_size_combo")
        if "visual_reply_size" in data and widget is not None:
            size_text = self._normalize_visual_reply_size(data["visual_reply_size"])
            widget.setCurrentText(self._visual_reply_size_label_from_value(size_text))
            self.on_visual_reply_size_changed(size_text)
        widget = self._live_widget_attr("visual_reply_model_edit")
        if "visual_reply_model" in data and widget is not None:
            widget.setText(str(data["visual_reply_model"] or "gpt-image-1"))
            self.on_visual_reply_model_changed()
        widget = self._live_widget_attr("visual_reply_auto_show_checkbox")
        if "visual_reply_auto_show_dock" in data and widget is not None:
            auto_show = bool(data["visual_reply_auto_show_dock"])
            widget.setChecked(auto_show)
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
        widget = self._live_widget_attr("tts_seed_spin")
        if "tts_seed" in data and widget is not None:
            widget.setValue(max(0, int(data["tts_seed"] or 0)))
            self.on_tts_seed_changed(widget.value())
        widget = self._live_widget_attr("tts_temperature_spin")
        if "tts_temperature" in data and widget is not None:
            widget.setValue(max(0.05, float(data["tts_temperature"] or 0.8)))
            self.on_tts_temperature_changed(widget.value())
        widget = self._live_widget_attr("tts_top_p_spin")
        if "tts_top_p" in data and widget is not None:
            widget.setValue(max(0.0, min(1.0, float(data["tts_top_p"] or 0.9))))
            self.on_tts_top_p_changed(widget.value())
        widget = self._live_widget_attr("tts_top_k_spin")
        if "tts_top_k" in data and widget is not None:
            widget.setValue(max(0, int(data["tts_top_k"] or 0)))
            self.on_tts_top_k_changed(widget.value())
        widget = self._live_widget_attr("tts_repeat_penalty_spin")
        if "tts_repeat_penalty" in data and widget is not None:
            widget.setValue(max(1.0, float(data["tts_repeat_penalty"] or 1.2)))
            self.on_tts_repeat_penalty_changed(widget.value())
        widget = self._live_widget_attr("tts_min_p_spin")
        if "tts_min_p" in data and widget is not None:
            widget.setValue(max(0.0, min(1.0, float(data["tts_min_p"] or 0.0))))
            self.on_tts_min_p_changed(widget.value())
        widget = self._live_widget_attr("tts_normalize_loudness_checkbox")
        if "tts_normalize_loudness" in data and widget is not None:
            widget.setChecked(bool(data["tts_normalize_loudness"]))
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
        widget = self._live_widget_attr("musetalk_avatar_pack_combo")
        if "musetalk_avatar_pack_id" in data and widget is not None:
            self.refresh_musetalk_avatar_pack_list(selected_pack_id=data["musetalk_avatar_pack_id"])
            widget = self._live_widget_attr("musetalk_avatar_pack_combo")
            if widget is not None:
                for index in range(widget.count()):
                    if str(widget.itemData(index) or "") == str(data["musetalk_avatar_pack_id"] or ""):
                        widget.setCurrentIndex(index)
                        break
                self.on_musetalk_avatar_pack_change(widget.currentText())
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
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is None:
            return
        name = body_combo.currentText()
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
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is not None:
            index = body_combo.findText(name)
            if index >= 0:
                body_combo.setCurrentIndex(index)
        print(f"[QtGUI] Saved Full Body & Hands: {path}")
        self.save_session()

    def load_body_config_from_combo(self):
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is None:
            return
        name = body_combo.currentText()
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
        emotion_combo = self._live_widget_attr("emotion_combo")
        if emotion_combo is not None:
            self.on_emotion_change(emotion_combo.currentText())
        print(f"[QtGUI] Loading Config: {name}...")
        self.save_session()

    def delete_current_body(self):
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is None:
            return
        name = body_combo.currentText()
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
        if not self._addon_effectively_enabled("nc.visual_reply"):
            return
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
            "musetalk_avatar_pack_id": str(self._live_combo_data("musetalk_avatar_pack_combo", RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "")) or ""),
            "musetalk_vram_mode": next(
                (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self._live_combo_text("musetalk_vram_combo", "")),
                "quality",
            ),
            "musetalk_use_frame_cache": self._live_checked("musetalk_use_frame_cache_checkbox", RUNTIME_CONFIG.get("musetalk_use_frame_cache", True)),
            "vam_vmc_enabled": self._live_checked("vam_vmc_enabled_checkbox", RUNTIME_CONFIG.get("vam_vmc_enabled", True)),
            "vam_vmc_host": self._live_text("vam_vmc_host_edit", RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1")).strip() or "127.0.0.1",
            "vam_vmc_port": int(self._live_value("vam_vmc_port_spin", RUNTIME_CONFIG.get("vam_vmc_port", 39539) or 39539)),
            "vam_bridge_enabled": self._live_checked("vam_bridge_enabled_checkbox", RUNTIME_CONFIG.get("vam_bridge_enabled", True)),
            "vam_root": self._current_vam_root_value(),
            "vam_bridge_root": self._current_vam_bridge_root_value(),
            "vam_play_audio_in_vam": True if mode == "vam" else self._live_checked("vam_play_audio_in_vam_checkbox", RUNTIME_CONFIG.get("vam_play_audio_in_vam", False)),
            "vam_target_atom_uid": self._live_text("vam_target_atom_uid_edit", RUNTIME_CONFIG.get("vam_target_atom_uid", "Person")).strip() or "Person",
            "vam_target_storable_id": self._live_text("vam_target_storable_id_edit", RUNTIME_CONFIG.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge")).strip(),
            "vam_timeline_auto_resume": self._live_checked("vam_timeline_auto_resume_checkbox", RUNTIME_CONFIG.get("vam_timeline_auto_resume", True)),
            "pocket_tts_python": (
                self._ensure_pocket_tts_python_path()
                if self._current_tts_backend_value() == "pockettts" and self._live_widget_attr("pocket_tts_python_edit") is not None
                else self._live_text("pocket_tts_python_edit", RUNTIME_CONFIG.get("pocket_tts_python", "")).strip()
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
            "voice_file": self._current_voice_file_value() if hasattr(self, "voice_combo") else "",
            "input_mode": self.input_mode_combo.currentText(),
            "input_message_role": self.input_role_combo.currentText(),
            "push_to_talk_hotkey": engine.get_push_to_talk_hotkey(),
            "manual_action_hotkeys": dict(engine.get_manual_action_hotkeys()),
            "ui_action_hotkeys": dict(engine.get_ui_action_hotkeys()),
            "stream_mode": self.stream_mode_combo.currentText(),
            "tts_backend": self._current_tts_backend_value(),
            "tts_seed": int(self._live_value("tts_seed_spin", RUNTIME_CONFIG.get("tts_seed", 0) or 0)),
            "tts_temperature": float(self._live_value("tts_temperature_spin", RUNTIME_CONFIG.get("tts_temperature", 0.8) or 0.8)),
            "tts_top_p": float(self._live_value("tts_top_p_spin", RUNTIME_CONFIG.get("tts_top_p", 0.9) or 0.9)),
            "tts_top_k": int(self._live_value("tts_top_k_spin", RUNTIME_CONFIG.get("tts_top_k", 40) or 40)),
            "tts_repeat_penalty": float(self._live_value("tts_repeat_penalty_spin", RUNTIME_CONFIG.get("tts_repeat_penalty", 1.2) or 1.2)),
            "tts_min_p": float(self._live_value("tts_min_p_spin", RUNTIME_CONFIG.get("tts_min_p", 0.0) or 0.0)),
            "tts_normalize_loudness": self._live_checked("tts_normalize_loudness_checkbox", RUNTIME_CONFIG.get("tts_normalize_loudness", False)),
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}),
            "chat_provider_generation_settings": dict(RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {}),
            "chat_font_size": int(self.chat_font_size_combo.currentData() or 12) if hasattr(self, "chat_font_size_combo") else 12,
            "chat_runtime_expanded": self.chat_runtime_section.isExpanded() if hasattr(self, "chat_runtime_section") else True,
            "tts_runtime_expanded": self.tts_runtime_section.isExpanded() if hasattr(self, "tts_runtime_section") else True,
            "model_name": self.model_combo.currentText() if hasattr(self, "model_combo") else str(RUNTIME_CONFIG.get("model_name", "") or ""),
            "model_requires_vision": self.model_requires_vision_checkbox.isChecked() if hasattr(self, "model_requires_vision_checkbox") else False,
            "model_supports_images": self._current_model_supports_images_value(self.model_combo.currentText()) if hasattr(self, "model_combo") else RUNTIME_CONFIG.get("model_supports_images", None),
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
                (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self._live_combo_text("musetalk_vram_combo", "")),
                "quality",
            ),
            "musetalk_loop_fade_ms": int(self._live_value("musetalk_loop_fade_spin", RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS))),
            "musetalk_use_frame_cache": bool(self._live_checked("musetalk_use_frame_cache_checkbox", RUNTIME_CONFIG.get("musetalk_use_frame_cache", True))),
            "musetalk_avatar_pack_id": str(self._live_combo_data("musetalk_avatar_pack_combo", RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "")) or ""),
            "vam_vmc_enabled": self._live_checked("vam_vmc_enabled_checkbox", RUNTIME_CONFIG.get("vam_vmc_enabled", True)),
            "vam_vmc_host": self._live_text("vam_vmc_host_edit", RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1")).strip() or "127.0.0.1",
            "vam_vmc_port": int(self._live_value("vam_vmc_port_spin", RUNTIME_CONFIG.get("vam_vmc_port", 39539) or 39539)),
            "vam_bridge_enabled": self._live_checked("vam_bridge_enabled_checkbox", RUNTIME_CONFIG.get("vam_bridge_enabled", True)),
            "vam_root": self._current_vam_root_value() if self._live_widget_attr("vam_root_edit") is not None else str(RUNTIME_CONFIG.get("vam_root", getattr(engine, "DEFAULT_VAM_ROOT", "")) or getattr(engine, "DEFAULT_VAM_ROOT", "")),
            "vam_bridge_root": self._current_vam_bridge_root_value() if self._live_widget_attr("vam_bridge_root_edit") is not None else str(RUNTIME_CONFIG.get("vam_bridge_root", getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")) or getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")),
            "vam_play_audio_in_vam": self._live_checked("vam_play_audio_in_vam_checkbox", RUNTIME_CONFIG.get("vam_play_audio_in_vam", False)),
            "vam_target_atom_uid": self._live_text("vam_target_atom_uid_edit", RUNTIME_CONFIG.get("vam_target_atom_uid", "Person")).strip() or "Person",
            "vam_target_storable_id": self._live_text("vam_target_storable_id_edit", RUNTIME_CONFIG.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge")).strip() or "plugin#0_NeuralCompanionBridge",
            "vam_timeline_auto_resume": self._live_checked("vam_timeline_auto_resume_checkbox", RUNTIME_CONFIG.get("vam_timeline_auto_resume", True)),
            "visual_reply_mode": self._visual_reply_mode_value_from_label(self._live_combo_text("visual_reply_mode_combo", RUNTIME_CONFIG.get("visual_reply_mode", "auto"))),
            "visual_reply_provider": self._visual_reply_provider_value_from_label(self._live_combo_text("visual_reply_provider_combo", RUNTIME_CONFIG.get("visual_reply_provider", "openai"))),
            "visual_reply_size": self._normalize_visual_reply_size(self._live_combo_text("visual_reply_size_combo", RUNTIME_CONFIG.get("visual_reply_size", "1024x1024"))),
            "visual_reply_model": self._live_text("visual_reply_model_edit", RUNTIME_CONFIG.get("visual_reply_model", "gpt-image-1")).strip() or "gpt-image-1",
            "visual_reply_auto_show_dock": self._live_checked("visual_reply_auto_show_checkbox", RUNTIME_CONFIG.get("visual_reply_auto_show_dock", True)),
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
                if self._current_tts_backend_value() == "pockettts" and self._live_widget_attr("pocket_tts_python_edit") is not None
                else self._live_text("pocket_tts_python_edit", RUNTIME_CONFIG.get("pocket_tts_python", "")).strip()
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
            "last_body": self._live_combo_text("body_combo", RUNTIME_CONFIG.get("last_body", "")),
            "live_sync": self._live_checked("live_sync_checkbox", RUNTIME_CONFIG.get("live_sync", False)),
            "geometry": [self.x(), self.y(), self.width(), self.height()],
            "main_splitter_sizes": self.main_splitter.sizes() if hasattr(self, "main_splitter") else [400, 980],
            "pinned_floating_docks": sorted(getattr(self, "_pinned_floating_dock_names", set()) or []),
            "always_on_top_floating_docks": sorted(getattr(self, "_always_on_top_floating_dock_names", set()) or []),
            "preview_visible": bool(hasattr(self, "preview_dock") and self.preview_dock.isVisible()),
            "visual_reply_visible": bool(
                self._addon_effectively_enabled("nc.visual_reply")
                and hasattr(self, "visual_reply_dock")
                and self.visual_reply_dock.isVisible()
            ),
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
            vam_play_audio = self._live_widget_attr("vam_play_audio_in_vam_checkbox")
            if str(engine_choice or "").strip().lower() == "vam" and vam_play_audio is not None:
                vam_play_audio.setChecked(True)
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
            if voice_file and voice_file != "No .wav found" and hasattr(self, "voice_combo"):
                index = self.voice_combo.findText(voice_file)
                if index >= 0:
                    self.voice_combo.blockSignals(True)
                    try:
                        self.voice_combo.setCurrentIndex(index)
                    finally:
                        self.voice_combo.blockSignals(False)
                    update_runtime_config("voice_path", os.path.join("voices", voice_file))
                else:
                    update_runtime_config("voice_path", "")
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
            widget = self._live_widget_attr("tts_seed_spin")
            if tts_seed is not None and widget is not None:
                widget.setValue(max(0, int(tts_seed)))
                self.on_tts_seed_changed(widget.value())
            tts_temperature = session.get("tts_temperature")
            widget = self._live_widget_attr("tts_temperature_spin")
            if tts_temperature is not None and widget is not None:
                widget.setValue(max(0.05, float(tts_temperature)))
                self.on_tts_temperature_changed(widget.value())
            tts_top_p = session.get("tts_top_p")
            widget = self._live_widget_attr("tts_top_p_spin")
            if tts_top_p is not None and widget is not None:
                widget.setValue(max(0.0, min(1.0, float(tts_top_p))))
                self.on_tts_top_p_changed(widget.value())
            tts_top_k = session.get("tts_top_k")
            widget = self._live_widget_attr("tts_top_k_spin")
            if tts_top_k is not None and widget is not None:
                widget.setValue(max(0, int(tts_top_k)))
                self.on_tts_top_k_changed(widget.value())
            tts_repeat_penalty = session.get("tts_repeat_penalty")
            widget = self._live_widget_attr("tts_repeat_penalty_spin")
            if tts_repeat_penalty is not None and widget is not None:
                widget.setValue(max(1.0, float(tts_repeat_penalty)))
                self.on_tts_repeat_penalty_changed(widget.value())
            tts_min_p = session.get("tts_min_p")
            widget = self._live_widget_attr("tts_min_p_spin")
            if tts_min_p is not None and widget is not None:
                widget.setValue(max(0.0, min(1.0, float(tts_min_p))))
                self.on_tts_min_p_changed(widget.value())
            tts_normalize_loudness = session.get("tts_normalize_loudness")
            widget = self._live_widget_attr("tts_normalize_loudness_checkbox")
            if tts_normalize_loudness is not None and widget is not None:
                widget.setChecked(bool(tts_normalize_loudness))
                self.on_tts_normalize_loudness_changed(bool(tts_normalize_loudness))
            vam_vmc_enabled = session.get("vam_vmc_enabled")
            widget = self._live_widget_attr("vam_vmc_enabled_checkbox")
            if vam_vmc_enabled is not None and widget is not None:
                widget.setChecked(bool(vam_vmc_enabled))
                self.on_vam_vmc_enabled_changed(bool(vam_vmc_enabled))
            vam_bridge_enabled = session.get("vam_bridge_enabled")
            widget = self._live_widget_attr("vam_bridge_enabled_checkbox")
            if vam_bridge_enabled is not None and widget is not None:
                widget.setChecked(bool(vam_bridge_enabled))
                self.on_vam_bridge_enabled_changed(bool(vam_bridge_enabled))
            vam_play_audio_in_vam = session.get("vam_play_audio_in_vam")
            widget = self._live_widget_attr("vam_play_audio_in_vam_checkbox")
            if vam_play_audio_in_vam is not None and widget is not None:
                widget.setChecked(bool(vam_play_audio_in_vam))
                self.on_vam_play_audio_in_vam_changed(bool(vam_play_audio_in_vam))
            vam_timeline_auto_resume = session.get("vam_timeline_auto_resume")
            widget = self._live_widget_attr("vam_timeline_auto_resume_checkbox")
            if vam_timeline_auto_resume is not None and widget is not None:
                widget.setChecked(bool(vam_timeline_auto_resume))
                self.on_vam_timeline_auto_resume_changed(bool(vam_timeline_auto_resume))
            vam_vmc_host = session.get("vam_vmc_host")
            widget = self._live_widget_attr("vam_vmc_host_edit")
            if vam_vmc_host and widget is not None:
                widget.setText(str(vam_vmc_host))
                self.on_vam_vmc_host_changed()
            vam_vmc_port = session.get("vam_vmc_port")
            widget = self._live_widget_attr("vam_vmc_port_spin")
            if vam_vmc_port is not None and widget is not None:
                widget.setValue(int(vam_vmc_port))
                self.on_vam_vmc_port_changed(int(vam_vmc_port))
            vam_root = session.get("vam_root") or session.get("vam_bridge_root")
            widget = self._live_widget_attr("vam_root_edit")
            if vam_root and widget is not None:
                widget.setText(engine.normalize_vam_root(vam_root))
                self.on_vam_root_changed()
            vam_target_atom_uid = session.get("vam_target_atom_uid")
            widget = self._live_widget_attr("vam_target_atom_uid_edit")
            if vam_target_atom_uid and widget is not None:
                widget.setText(str(vam_target_atom_uid))
                self.on_vam_target_atom_uid_changed()
            vam_target_storable_id = session.get("vam_target_storable_id")
            widget = self._live_widget_attr("vam_target_storable_id_edit")
            if vam_target_storable_id and widget is not None:
                widget.setText(str(vam_target_storable_id))
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
                update_runtime_config("model_requires_vision", bool(model_requires_vision))
            if "model_supports_images" in session:
                update_runtime_config("model_supports_images", session.get("model_supports_images"))
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
                widget = self._live_widget_attr("musetalk_vram_combo")
                if label and widget is not None:
                    index = widget.findText(label)
                    if index >= 0:
                        widget.setCurrentIndex(index)
            musetalk_loop_fade_ms = session.get("musetalk_loop_fade_ms")
            widget = self._live_widget_attr("musetalk_loop_fade_spin")
            if musetalk_loop_fade_ms is not None and widget is not None:
                fade_ms = max(0, int(musetalk_loop_fade_ms))
                widget.setValue(fade_ms)
                self.on_musetalk_loop_fade_changed(fade_ms)
            musetalk_use_frame_cache = session.get("musetalk_use_frame_cache")
            widget = self._live_widget_attr("musetalk_use_frame_cache_checkbox")
            if musetalk_use_frame_cache is not None and widget is not None:
                widget.setChecked(bool(musetalk_use_frame_cache))
                self.on_musetalk_use_frame_cache_changed(bool(musetalk_use_frame_cache))
            visual_reply_mode = session.get("visual_reply_mode")
            widget = self._live_widget_attr("visual_reply_mode_combo")
            if visual_reply_mode is not None and widget is not None:
                mode_text = self._visual_reply_mode_label_from_value(visual_reply_mode)
                widget.setCurrentText(mode_text)
                self.on_visual_reply_mode_changed(mode_text)
            visual_reply_provider = session.get("visual_reply_provider")
            widget = self._live_widget_attr("visual_reply_provider_combo")
            if visual_reply_provider is not None and widget is not None:
                provider_text = self._visual_reply_provider_label_from_value(visual_reply_provider)
                widget.setCurrentText(provider_text)
                self.on_visual_reply_provider_changed(provider_text)
            visual_reply_size = session.get("visual_reply_size")
            widget = self._live_widget_attr("visual_reply_size_combo")
            if visual_reply_size is not None and widget is not None:
                size_text = self._normalize_visual_reply_size(visual_reply_size)
                widget.setCurrentText(self._visual_reply_size_label_from_value(size_text))
                self.on_visual_reply_size_changed(size_text)
            visual_reply_model = session.get("visual_reply_model")
            widget = self._live_widget_attr("visual_reply_model_edit")
            if visual_reply_model is not None and widget is not None:
                widget.setText(str(visual_reply_model or "gpt-image-1"))
                self.on_visual_reply_model_changed()
            visual_reply_auto_show = session.get("visual_reply_auto_show_dock")
            widget = self._live_widget_attr("visual_reply_auto_show_checkbox")
            if visual_reply_auto_show is not None and widget is not None:
                auto_show = bool(visual_reply_auto_show)
                widget.setChecked(auto_show)
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
            widget = self._live_widget_attr("musetalk_avatar_pack_combo")
            if musetalk_avatar_pack_id is not None and widget is not None:
                self.refresh_musetalk_avatar_pack_list(selected_pack_id=musetalk_avatar_pack_id)
                widget = self._live_widget_attr("musetalk_avatar_pack_combo")
                if widget is not None:
                    for index in range(widget.count()):
                        if str(widget.itemData(index) or "") == str(musetalk_avatar_pack_id or ""):
                            widget.setCurrentIndex(index)
                            break
                    self.on_musetalk_avatar_pack_change(widget.currentText())
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
            body_combo = self._live_widget_attr("body_combo")
            if body and body_combo is not None:
                index = body_combo.findText(body)
                if index >= 0:
                    body_combo.setCurrentIndex(index)
                    self.load_body_config_from_combo()
            if self._addon_manager is not None:
                self._addon_manager.import_session_state(session)
                self._refresh_addon_group_tabs()
            live_sync_checkbox = self._live_widget_attr("live_sync_checkbox")
            if live_sync_checkbox is not None:
                live_sync_checkbox.setChecked(bool(session.get("live_sync", False)))
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
            if (
                bool(session.get("visual_reply_visible", False))
                and not suppress_aux_docks
                and self._addon_effectively_enabled("nc.visual_reply")
            ):
                self.visual_reply_dock.show()
            else:
                self.visual_reply_dock.hide()
            performance_guidance_visible = bool(session.get("performance_guidance_visible", False))
            if hasattr(self, "performance_guidance_toggle"):
                self.performance_guidance_toggle.setChecked(performance_guidance_visible)
                self._toggle_performance_guidance(performance_guidance_visible)
            self._refresh_hotkey_shortcuts()
            self._refresh_hotkey_labels()
            self._apply_disabled_addon_surfaces()
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
