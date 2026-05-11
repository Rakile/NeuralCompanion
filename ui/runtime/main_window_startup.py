"""Startup and shutdown lifecycle for the runtime-backed main window."""

import os
import sys
import threading

from PySide6 import QtCore

from ui.runtime import engine_access as engine
import tutorial_framework
from core import expression_state
from core.expression_api import start_expression_api
from ui.runtime.engine_access import RUNTIME_CONFIG
from ui.runtime.console_redirect import QtConsoleBridge, QtTextRedirector
from ui.runtime.main_window_theme import (
    DEFAULT_APP_THEME_PRESET,
    _app_theme_palette,
    _apply_engine_action_button_accents,
    _apply_inline_theme_styles,
    _apply_readable_input_palettes,
    _normalize_app_theme_preset_id,
)


def start_api(preview_state_getter=None):
    start_expression_api(expression_state, preview_state_getter=preview_state_getter, port=5005)


class MainWindowStartupMixin:
    def _initialize_runtime_state(self, *, suppress_restored_aux_docks=False):
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
        self._mounted_avatar_tools_addon_tab_ids = set()
        self._mounted_musetalk_addon_tab_ids = self._mounted_avatar_tools_addon_tab_ids
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

    def _initialize_console_redirect(self):
        self._console_bridge = QtConsoleBridge()
        self._console_redirect = QtTextRedirector(self._console_bridge, mirror_stream=sys.__stdout__)
        self._previous_stdout = sys.stdout
        self._previous_stderr = sys.stderr
        sys.stdout = self._console_redirect
        sys.stderr = self._console_redirect

    def _initialize_floating_panel_state(self):
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

    def _finish_startup(self):
        self._initialize_addon_manager()
        self._build_ui()
        self._apply_workspace_view_constraints()
        _apply_inline_theme_styles(self, _app_theme_palette(self.current_app_theme_preset()))
        _apply_readable_input_palettes(self, _app_theme_palette(self.current_app_theme_preset()))
        _apply_engine_action_button_accents(self)
        self._apply_legacy_dock_title_widgets()
        self._connect_console_bridge()
        self._build_status_timer()
        self._mount_initialized_addons()
        self._build_ui_hotkey_timer()
        self._build_preview_dock()
        self._apply_disabled_addon_surfaces()
        _apply_inline_theme_styles(self, _app_theme_palette(self.current_app_theme_preset()))
        _apply_readable_input_palettes(self, _app_theme_palette(self.current_app_theme_preset()))
        _apply_engine_action_button_accents(self)
        self._apply_legacy_dock_title_widgets()

        os.makedirs("presets", exist_ok=True)
        os.makedirs("voices", exist_ok=True)
        os.makedirs("body_configs", exist_ok=True)

        threading.Thread(
            target=start_api,
            kwargs={"preview_state_getter": self._musetalk_preview_state_for_api},
            daemon=True,
        ).start()
        print("📡 [API] Expression server running on port 5005")

        self.refresh_resources()
        self.restore_session()
        self.refresh_tutorial_list()
        QtCore.QTimer.singleShot(250, self.maybe_prompt_first_run_tutorial)

    def _musetalk_preview_state_for_api(self):
        if hasattr(self, "_invoke_addon_service_capability"):
            return self._invoke_addon_service_capability(
                "avatar_provider_registry",
                "runtime.preview.current_state",
                {},
                default={},
                provider_id="musetalk",
            )
        return {}

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
