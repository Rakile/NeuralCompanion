"""Dependency wiring for the runtime-backed Designer UI.

This module intentionally keeps the old qt_app wiring functions as thin,
relocatable glue. qt_app injects its current globals before using these
functions so the runtime bridge can be carved out without changing behavior.
"""

_DEPENDENCY_KEYS_TO_SKIP = {"__name__", "__package__", "__spec__", "__loader__", "__cached__"}

from ui.runtime.qt_app_shell_service_factories import (
    configure_qt_app_shell_service_factory_dependencies,
    _ui_shell_chat_context_service,
    _ui_shell_chat_replay_service,
    _ui_shell_dry_run_service,
    _ui_shell_engine_lifecycle_service,
    _ui_shell_input_actions_service,
    _ui_shell_input_settings_service,
    _ui_shell_model_refresh_service,
    _ui_shell_performance_profile_service,
    _ui_shell_persona_avatar_service,
    _ui_shell_runtime_controls_service,
    _ui_shell_runtime_status_service,
    _ui_shell_tutorial_service,
)
from ui.runtime.qt_app_shell_dry_run import (
    configure_qt_app_shell_dry_run_dependencies,
    _bind_ui_shell_dry_run_controls,
    _ui_shell_dry_run_status_text,
    _ui_shell_dry_run_summary_text,
)
from ui.runtime.qt_app_shell_host_core import (
    configure_qt_app_shell_host_core_dependencies,
    _bind_ui_shell_host_core_controls,
)
from ui.runtime.qt_app_shell_input_actions import (
    configure_qt_app_shell_input_action_dependencies,
    _bind_ui_shell_input_action_controls,
)
from ui.runtime.qt_app_shell_read_only import (
    configure_qt_app_shell_read_only_dependencies,
    _apply_ui_shell_read_only_config,
)


def configure_qt_app_shell_dependencies(dependencies):
    """Provide qt_app symbols used by the migrated wiring functions."""
    for key, value in dict(dependencies or {}).items():
        if key not in _DEPENDENCY_KEYS_TO_SKIP:
            globals()[key] = value
    configure_qt_app_shell_service_factory_dependencies(globals())
    configure_qt_app_shell_read_only_dependencies(globals())
    configure_qt_app_shell_host_core_dependencies(globals())
    configure_qt_app_shell_dry_run_dependencies(globals())
    configure_qt_app_shell_input_action_dependencies(globals())


def _configure_real_ui_bridge_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    configure_real_ui_bridge_dependencies({
        "APP_THEME_PRESET_LABELS": APP_THEME_PRESET_LABELS,
        "APP_THEME_PRESET_WIDGETS": APP_THEME_PRESET_WIDGETS,
        "APP_ICON_PATH": APP_ICON_PATH,
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
        "musetalk_state": musetalk_state,
        "visual_reply_state": visual_reply_state,
        "expression_state": expression_state,
        "tutorial_framework": tutorial_framework,
        "update_runtime_config": update_runtime_config,
    })


def _configure_app_entry_dependencies():
    configure_app_entry_dependencies({
        "APP_ICON_PATH": APP_ICON_PATH,
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
    configure_qt_app_shell_service_factory_dependencies(globals())
    configure_shell_service_dependencies(globals())


def _configure_ui_shell_addon_report_dependencies():
    configure_shell_addon_report_dependencies(globals())
    configure_shell_addon_mount_dependencies(globals())




def _configure_ui_shell_status_layout_dependencies():
    _configure_ui_shell_addon_report_dependencies()
    configure_shell_status_layout_dependencies(globals())




def _configure_ui_shell_local_bindings_dependencies():
    _configure_ui_shell_status_layout_dependencies()
    configure_shell_local_bindings_dependencies(globals())




def _configure_ui_shell_runtime_cards_dependencies():
    _configure_ui_shell_local_bindings_dependencies()
    configure_shell_runtime_cards_dependencies(globals())




def _configure_ui_shell_session_config_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    configure_shell_session_config_dependencies(globals())




def _configure_ui_shell_chunking_profiles_dependencies():
    _configure_ui_shell_session_config_dependencies()
    configure_shell_chunking_profiles_dependencies(globals())




































































































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
