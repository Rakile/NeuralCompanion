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
from ui.runtime.backend_avatar_runtime import BackendAvatarRuntimeMixin
from ui.runtime.backend_chat_runtime import BackendChatRuntimeMixin
from ui.runtime.backend_chat_session_runtime import BackendChatSessionRuntimeMixin
from ui.runtime.backend_console_chat import BackendConsoleChatMixin
from ui.runtime.backend_dry_run_runtime import BackendDryRunRuntimeMixin
from ui.runtime.backend_engine_lifecycle import BackendEngineLifecycleMixin
from ui.runtime.backend_hotkeys import BackendHotkeyMixin
from ui.runtime.backend_model_advisor_runtime import BackendModelAdvisorRuntimeMixin
from ui.runtime.backend_musetalk_preview_runtime import BackendMuseTalkPreviewRuntimeMixin
from ui.runtime.backend_operational_panel import BackendOperationalPanelMixin
from ui.runtime.backend_preset_body_runtime import BackendPresetBodyRuntimeMixin
from ui.runtime.backend_resource_refresh import BackendResourceRefreshMixin
from ui.runtime.backend_runtime_controls import BackendRuntimeControlsMixin
from ui.runtime.backend_runtime_status import BackendRuntimeStatusMixin
from ui.runtime.backend_sensory_sources import BackendSensorySourcesMixin
from ui.runtime.backend_system_shaping_panel import BackendSystemShapingPanelMixin
from ui.runtime.backend_tutorial_runtime import BackendTutorialRuntimeMixin
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
from ui.runtime.shell_persona_body_vam import (
    _bind_ui_shell_persona_body_vam_controls,
    _ui_shell_apply_body_profile_for_emotion,
    _ui_shell_body_pose_spec,
    _ui_shell_body_value_to_slider_raw,
    _ui_shell_body_slider_raw_to_value,
    _ui_shell_body_slider_widget,
    _ui_shell_configure_body_slider,
    _ui_shell_current_body_pose_values,
    _ui_shell_current_vam_settings,
    _ui_shell_derive_vam_bridge_root,
    _ui_shell_format_body_value,
    _ui_shell_load_body_preview,
    _ui_shell_normalize_vam_root,
    _ui_shell_refresh_body_combo,
    _ui_shell_refresh_vam_status_labels,
    _ui_shell_set_selected_body_profile,
    _ui_shell_update_body_label,
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


class CompanionQtMainWindow(BackendAddonMountMixin, BackendAvatarRuntimeMixin, BackendChatRuntimeMixin, BackendChatSessionRuntimeMixin, BackendConsoleChatMixin, BackendDryRunRuntimeMixin, BackendEngineLifecycleMixin, BackendHotkeyMixin, BackendModelAdvisorRuntimeMixin, BackendMuseTalkPreviewRuntimeMixin, BackendOperationalPanelMixin, BackendPresetBodyRuntimeMixin, BackendResourceRefreshMixin, BackendRuntimeControlsMixin, BackendRuntimeStatusMixin, BackendSensorySourcesMixin, BackendSystemShapingPanelMixin, BackendTutorialRuntimeMixin, BackendTtsRuntimeMixin, BackendVamRuntimeMixin, BackendVisualReplyRuntimeMixin, BackendWorkspaceTabsMixin, LegacyWorkspaceDockMixin, LegacyDockTitleMixin, QtWidgets.QMainWindow):
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
