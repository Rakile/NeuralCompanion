"""Runtime-backed Qt main window for Neural Companion.

The executable entrypoint lives in qt_app.py; this module owns the main window
class and its small local constants while the long-lived runtime behavior remains
in focused mixins under ui.runtime.
"""

import base64
import ctypes
import json
import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6 import QtCore, QtWidgets

import engine
import shared_state
import tutorial_framework
from core.expression_api import start_expression_api
from engine import RUNTIME_CONFIG, update_runtime_config
from ui.panels.avatar_windows import QtExternalAvatarReturnWindow, QtMuseTalkStageWindow
from ui.panels.musetalk_preview_panel import QtMuseTalkPreviewPanel
from ui.panels.visual_reply_panel import QtVisualReplyPanel
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
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES, UI_SHELL_MUSE_VRAM_MODE_LABELS
from ui.runtime.shell_status_layout import _apply_workspace_view_constraints
from ui.theme_support import (
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
from ui.widgets.basic import set_combo_popup_palette_callback
from ui.runtime.console_redirect import QtConsoleBridge, QtTextRedirector

APP_ROOT = Path(__file__).resolve().parents[1]
APP_TITLE = "Neural Companion"
SESSION_PATH = Path("qt_session.json")
DEFAULT_LOCAL_VAM_ROOT = ""
DEFAULT_LOCAL_VAM_EXECUTABLE = "VaM.exe"
DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER = "VaM (Desktop Mode).bat"
DEFAULT_LOCAL_VAM_VR_LAUNCHER = "VaM (OpenVR).bat"
QT_PREVIEW_CACHE_LIMIT = 384
QT_PREVIEW_INITIAL_PRELOAD = 96
QT_PREVIEW_AHEAD_PRELOAD = 72

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

def _apply_inline_theme_styles(root, palette):
    _theme_apply_inline_theme_styles(
        root,
        palette,
        theme_preset_widgets=APP_THEME_PRESET_WIDGETS,
        canonicalize_stylesheet=_canonical_theme_base_stylesheet,
        replace_theme_colors=_replace_theme_colors_in_stylesheet,
    )


def _apply_readable_input_palettes(root, palette):
    _theme_apply_readable_input_palettes(root, palette)


def _apply_engine_action_button_accents(root):
    _theme_apply_engine_action_button_accents(root)


def _split_collapsible_section_text(text, fallback_title):
    return _theme_split_collapsible_section_text(text, fallback_title)


def _apply_combo_popup_palette(combo):
    _apply_readable_input_palettes(combo.window(), _app_theme_palette())


configure_theme_support(RUNTIME_CONFIG)
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
        self.embedded_musetalk_preview = QtMuseTalkPreviewPanel(
            theme_provider=_app_theme_palette,
            runtime_config=RUNTIME_CONFIG,
        )
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
            storage_dir=APP_ROOT / "runtime" / "visual_replies",
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
