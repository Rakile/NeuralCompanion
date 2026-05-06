"""Runtime-backed Qt main window for Neural Companion.

The executable entrypoint lives in qt_app.py; this module owns the main window
class and its small local constants while the long-lived runtime behavior remains
in focused mixins under ui.runtime.
"""

from PySide6 import QtWidgets

from engine import update_runtime_config
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
from ui.runtime.main_window_aux_docks import MainWindowAuxDocksMixin
from ui.runtime.main_window_layout import MainWindowLayoutMixin
from ui.runtime.main_window_session import MainWindowSessionMixin
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES
from ui.runtime.shell_status_layout import _apply_workspace_view_constraints
from ui.runtime.main_window_constants import (
    APP_ROOT,
    APP_TITLE,
    SESSION_PATH,
    DEFAULT_LOCAL_VAM_ROOT,
    DEFAULT_LOCAL_VAM_EXECUTABLE,
    DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER,
    DEFAULT_LOCAL_VAM_VR_LAUNCHER,
    QT_PREVIEW_CACHE_LIMIT,
    QT_PREVIEW_INITIAL_PRELOAD,
    QT_PREVIEW_AHEAD_PRELOAD,
    QT_MUSETALK_LOOP_FADE_MS,
    DEFAULT_MAX_RESPONSE_TOKENS,
    DRY_RUN_MAX_RESPONSE_TOKENS,
    MUSE_VRAM_MODE_LABELS,
    MUSE_AVATAR_RESULTS_DIR,
    MODEL_ADVISOR_BUILTIN_FINGERPRINTS_GIB,
    MODEL_ADVISOR_TTS_OVERHEAD_GIB,
    MODEL_ADVISOR_STREAM_OVERHEAD_GIB,
    MODEL_ADVISOR_SAFETY_MARGIN_GIB,
    PERFORMANCE_PROFILE_APPLY_KEYS,
    _WIN32_DOCK_OWNER_SUPPORTED,
    _WIN32_GWLP_HWNDPARENT,
    _win32_set_window_owner,
    ctypes,
)
from ui.runtime.main_window_theme import (
    _app_theme_palette,
    _apply_engine_action_button_accents,
    _apply_inline_theme_styles,
    _apply_readable_input_palettes,
    _build_app_stylesheet_for_preset,
    _canonical_theme_base_stylesheet,
    _normalize_app_theme_preset_id,
    _replace_theme_colors_in_stylesheet,
    _split_collapsible_section_text,
    configure_main_window_theme_support,
    MainWindowThemeMixin,
)
from ui.runtime.main_window_startup import MainWindowStartupMixin, start_api

DEFAULT_CHUNKING_VALUES = UI_SHELL_DEFAULT_CHUNKING_VALUES

configure_main_window_theme_support()

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

class CompanionQtMainWindow(MainWindowStartupMixin, MainWindowThemeMixin, MainWindowLayoutMixin, MainWindowAuxDocksMixin, MainWindowSessionMixin, BackendAddonMountMixin, BackendAvatarRuntimeMixin, BackendChatRuntimeMixin, BackendChatSessionRuntimeMixin, BackendConsoleChatMixin, BackendDryRunRuntimeMixin, BackendEngineLifecycleMixin, BackendHotkeyMixin, BackendModelAdvisorRuntimeMixin, BackendMuseTalkPreviewRuntimeMixin, BackendOperationalPanelMixin, BackendPresetBodyRuntimeMixin, BackendResourceRefreshMixin, BackendRuntimeControlsMixin, BackendRuntimeStatusMixin, BackendSensorySourcesMixin, BackendSystemShapingPanelMixin, BackendTutorialRuntimeMixin, BackendTtsRuntimeMixin, BackendVamRuntimeMixin, BackendVisualReplyRuntimeMixin, BackendWorkspaceTabsMixin, LegacyWorkspaceDockMixin, LegacyDockTitleMixin, QtWidgets.QMainWindow):
    def __init__(self, *, suppress_restored_aux_docks=False):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 980)
        self._initialize_runtime_state(suppress_restored_aux_docks=suppress_restored_aux_docks)
        self._initialize_console_redirect()
        self._initialize_floating_panel_state()
        self._finish_startup()




__all__ = [
    'APP_TITLE',
    'SESSION_PATH',
    'DEFAULT_LOCAL_VAM_ROOT',
    'DEFAULT_LOCAL_VAM_EXECUTABLE',
    'DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER',
    'DEFAULT_LOCAL_VAM_VR_LAUNCHER',
    'QT_PREVIEW_CACHE_LIMIT',
    'QT_PREVIEW_INITIAL_PRELOAD',
    'QT_PREVIEW_AHEAD_PRELOAD',
    'QT_MUSETALK_LOOP_FADE_MS',
    'DEFAULT_CHUNKING_VALUES',
    'DEFAULT_MAX_RESPONSE_TOKENS',
    'MUSE_VRAM_MODE_LABELS',
    'MUSE_AVATAR_RESULTS_DIR',
    '_WIN32_DOCK_OWNER_SUPPORTED',
    '_WIN32_GWLP_HWNDPARENT',
    '_win32_set_window_owner',
    '_app_theme_palette',
    '_apply_inline_theme_styles',
    '_apply_readable_input_palettes',
    '_apply_engine_action_button_accents',
    '_split_collapsible_section_text',
    '_build_app_stylesheet_for_preset',
    '_normalize_app_theme_preset_id',
    '_replace_theme_colors_in_stylesheet',
    '_canonical_theme_base_stylesheet',
    'start_api',
    'CompanionQtMainWindow',
]
