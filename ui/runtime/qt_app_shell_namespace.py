"""Compatibility namespace for qt_app.py shell/runtime wiring.

The shell configuration layer still consumes many historical globals. Keeping
them grouped here lets qt_app.py stay an entrypoint while preserving the old
dependency surface during the migration.
"""

import base64
import ctypes
import glob
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import threading
import time
import warnings
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

from core.expression_api import start_expression_api
from core.musetalk_avatar_packs import discover_avatar_packs
from core.runtime_paths import (
    derive_vam_bridge_root as _derive_vam_bridge_root_safe,
    legacy_vam_bridge_roots as _legacy_vam_bridge_roots_safe,
    normalize_vam_root as _normalize_vam_root_safe,
)
from core.runtime_status import build_runtime_status_snapshot
from ui.app_entry import configure_app_entry_dependencies, run_qt_app
from ui.designer_loader import (
    enable_stdio_unicode_fallback as _ui_shell_enable_stdio_unicode_fallback,
    install_no_wheel_input_guard as _install_no_wheel_input_guard,
    load_ui_preview_window as _load_ui_preview_window,
    load_ui_shell_for_smoke as _load_ui_shell_for_smoke,
    ui_shell_class_matches as _ui_shell_class_matches,
    ui_shell_find_object as _ui_shell_find_object,
)
from ui.dock_utils import configure_main_window_docking as _configure_main_window_docking
from addons.musetalk_avatar.stage_window import QtMuseTalkStageWindow
from ui.panels.avatar_windows import QtExternalAvatarReturnWindow
from addons.vseeface_avatar.hand_doctor_dialog import HandDoctorDialog
from ui.panels.input_dialog import QtInputDialog
from addons.musetalk_avatar.preview_panel import QtMuseTalkPreviewPanel
from addons.visual_reply.controller import AddonVisualReplyPanel as QtVisualReplyPanel
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
from ui.runtime.console_redirect import QtConsoleBridge, QtTextRedirector
from ui.runtime.legacy_dock_titles import LegacyDockTitleMixin, configure_legacy_dock_title_dependencies
from ui.runtime.legacy_workspace_docks import LegacyWorkspaceDockMixin, configure_legacy_workspace_dock_dependencies
from ui.runtime.real_ui_bridge import MainUiRealRuntimeBridge, configure_real_ui_bridge_dependencies
from ui.runtime.shell_addon_mounts import (
    _apply_ui_shell_addon_placeholders,
    _ui_shell_cleanup_live_addons,
    _ui_shell_mount_live_addons,
    configure_shell_addon_mount_dependencies,
)
from ui.runtime.shell_addon_reports import (
    _print_ui_shell_addon_mount_report,
    _print_ui_shell_static_addon_comparison,
    _read_ui_shell_session_snapshot,
    _ui_shell_addon_effectively_enabled,
    _ui_shell_addon_mount_report,
    _ui_shell_addon_registry_state,
    _ui_shell_addon_rows_text,
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
from ui.runtime.shell_persona_body_vam import (
    _bind_ui_shell_persona_body_vam_controls,
    _ui_shell_apply_body_profile_for_emotion,
    _ui_shell_body_pose_spec,
    _ui_shell_body_slider_raw_to_value,
    _ui_shell_body_slider_widget,
    _ui_shell_body_value_to_slider_raw,
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
from ui.shell_preview import configure_ui_shell_preview_dependencies, run_ui_shell_preview
from ui.shell_smoke import _ui_shell_binding_summary, configure_ui_shell_smoke_dependencies, run_ui_shell_smoke
from ui.shell_specs import (
    UI_SHELL_BODY_EMOTIONS,
    UI_SHELL_BODY_POSE_SPECS,
    UI_SHELL_CHUNKING_SPECS,
    UI_SHELL_DEFAULT_CHUNKING_VALUES,
    UI_SHELL_DEFAULT_LOCAL_VAM_ROOT,
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
from ui.theme_support import (
    APP_STYLESHEET,
    APP_THEME_PRESET_LABELS,
    APP_THEME_PRESET_WIDGETS,
    DEFAULT_APP_THEME_PRESET,
    app_theme_palette as _app_theme_palette,
    apply_engine_action_button_accents as _theme_apply_engine_action_button_accents,
    apply_inline_theme_styles as _theme_apply_inline_theme_styles,
    apply_readable_input_palettes as _theme_apply_readable_input_palettes,
    build_app_stylesheet_for_preset as _build_app_stylesheet_for_preset,
    canonical_theme_base_stylesheet as _canonical_theme_base_stylesheet,
    configure_theme_support,
    normalize_app_theme_preset_id as _normalize_app_theme_preset_id,
    replace_theme_colors_in_stylesheet as _replace_theme_colors_in_stylesheet,
    split_collapsible_section_text as _theme_split_collapsible_section_text,
)
from ui.validation import (
    UI_REAL_PREVIEW_ONLY_ROOTS,
    UI_SHELL_TAB_MOUNT_WIDGETS,
    UI_VALIDATION_REQUIRED_GROUPS,
    collect_ui_shell_static_tabs as _collect_ui_shell_static_tabs,
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


def export_qt_app_shell_namespace():
    return {name: value for name, value in globals().items() if not name.startswith("__") and name != "export_qt_app_shell_namespace"}
