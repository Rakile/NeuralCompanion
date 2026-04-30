from PySide6 import QtCore, QtWidgets

from ui.designer_loader import ui_shell_find_object as _ui_shell_find_object
from ui.runtime.real_ui_actions import MainUiRealActionsMixin, configure_real_ui_actions_dependencies
from ui.runtime.real_ui_bindings import MainUiRealBindingMixin, configure_real_ui_binding_dependencies
from ui.runtime.real_ui_input import MainUiRealInputMixin, configure_real_ui_input_dependencies
from ui.runtime.real_ui_layout import MainUiRealLayoutMixin, configure_real_ui_layout_dependencies
from ui.runtime.real_ui_surfaces import MainUiRealSurfacesMixin, configure_real_ui_surfaces_dependencies
from ui.runtime.real_ui_sync import MainUiRealSyncMixin, configure_real_ui_sync_dependencies
from ui.runtime.real_ui_tabs import MainUiRealTabAdoptionMixin
from ui.runtime.real_ui_theme import MainUiRealThemeMixin, configure_real_ui_theme_dependencies
from ui.runtime.real_ui_tutorials import MainUiRealTutorialMixin, configure_real_ui_tutorial_dependencies


def configure_real_ui_bridge_dependencies(namespace):
    """Inject qt_app-owned bridge dependencies without importing qt_app from UI modules."""
    globals().update(dict(namespace or {}))


def _configure_real_ui_input_dependencies():
    configure_real_ui_input_dependencies({
        "engine": engine,
    })


def _configure_real_ui_layout_dependencies():
    configure_real_ui_layout_dependencies({
        "SESSION_PATH": SESSION_PATH,
        "_apply_workspace_view_constraints": _apply_workspace_view_constraints,
        "_split_collapsible_section_text": _split_collapsible_section_text,
    })


def _configure_real_ui_theme_dependencies():
    configure_real_ui_theme_dependencies({
        "APP_THEME_PRESET_LABELS": APP_THEME_PRESET_LABELS,
        "APP_THEME_PRESET_WIDGETS": APP_THEME_PRESET_WIDGETS,
        "DEFAULT_APP_THEME_PRESET": DEFAULT_APP_THEME_PRESET,
        "RUNTIME_CONFIG": RUNTIME_CONFIG,
        "_app_theme_palette": _app_theme_palette,
        "_apply_engine_action_button_accents": _apply_engine_action_button_accents,
        "_apply_inline_theme_styles": _apply_inline_theme_styles,
        "_apply_readable_input_palettes": _apply_readable_input_palettes,
        "_build_app_stylesheet_for_preset": _build_app_stylesheet_for_preset,
        "_normalize_app_theme_preset_id": _normalize_app_theme_preset_id,
    })


def _configure_real_ui_tutorial_dependencies():
    configure_real_ui_tutorial_dependencies({
        "tutorial_framework": tutorial_framework,
    })


def _configure_real_ui_binding_dependencies():
    configure_real_ui_binding_dependencies({
        "UI_SHELL_BODY_POSE_SPECS": UI_SHELL_BODY_POSE_SPECS,
        "UI_SHELL_CHUNKING_SPECS": UI_SHELL_CHUNKING_SPECS,
        "_ui_shell_body_value_to_slider_raw": _ui_shell_body_value_to_slider_raw,
    })


def _configure_real_ui_actions_dependencies():
    configure_real_ui_actions_dependencies({
        "RUNTIME_CONFIG": RUNTIME_CONFIG,
        "_read_ui_shell_session_snapshot": _read_ui_shell_session_snapshot,
        "_ui_shell_audio_device_labels": _ui_shell_audio_device_labels,
        "_ui_shell_body_slider_raw_to_value": _ui_shell_body_slider_raw_to_value,
        "_ui_shell_chunking_slider_spec": _ui_shell_chunking_slider_spec,
        "_ui_shell_combo_select_label": _ui_shell_combo_select_label,
        "_ui_shell_combo_set_items": _ui_shell_combo_set_items,
        "_ui_shell_update_body_label": _ui_shell_update_body_label,
        "_ui_shell_update_chunking_label": _ui_shell_update_chunking_label,
        "update_runtime_config": update_runtime_config,
    })


def _configure_real_ui_sync_dependencies():
    configure_real_ui_sync_dependencies({
        "RUNTIME_CONFIG": RUNTIME_CONFIG,
        "UI_SHELL_BODY_POSE_SPECS": UI_SHELL_BODY_POSE_SPECS,
        "UI_SHELL_CHUNKING_SPECS": UI_SHELL_CHUNKING_SPECS,
        "_split_collapsible_section_text": _split_collapsible_section_text,
        "_ui_shell_body_value_to_slider_raw": _ui_shell_body_value_to_slider_raw,
        "_ui_shell_update_body_label": _ui_shell_update_body_label,
        "_ui_shell_update_chunking_label": _ui_shell_update_chunking_label,
        "engine": engine,
    })


def _configure_real_ui_surfaces_dependencies():
    configure_real_ui_surfaces_dependencies({
        "AddonCapabilityBridgeService": AddonCapabilityBridgeService,
        "QtVisualReplyPanel": QtVisualReplyPanel,
        "UI_REAL_PREVIEW_ONLY_ROOTS": UI_REAL_PREVIEW_ONLY_ROOTS,
        "__file__": __file__,
    })


class MainUiRealRuntimeBridge(MainUiRealLayoutMixin, MainUiRealInputMixin, MainUiRealTabAdoptionMixin, MainUiRealThemeMixin, MainUiRealTutorialMixin, MainUiRealBindingMixin, MainUiRealActionsMixin, MainUiRealSyncMixin, MainUiRealSurfacesMixin, QtCore.QObject):
    """Opt-in runtime-backed `main.ui` front-end backed by a hidden legacy window."""

    POLL_INTERVAL_MS = 180
    FRONTEND_LAYOUT_SESSION_KEY = "main_ui_real_layout"

    def __init__(self, raw_ui_path, *, session_read_only=False):
        super().__init__()
        self.ui_path = _resolve_ui_path(raw_ui_path)
        if not self.ui_path.exists():
            raise FileNotFoundError(f"UI file not found: {self.ui_path}")
        self._closing = False
        self._session_read_only = bool(session_read_only)
        self._restoring_frontend_layout = False
        self.backend = CompanionQtMainWindow()
        self.backend._session_read_only = self._session_read_only
        self.backend.frontend_layout_resync_callback = self._fix_system_shaping_scroll_content_size
        self.backend.first_run = False
        self.backend.hide()
        self.window = _load_ui_preview_window(self.ui_path)
        if not isinstance(self.window, QtWidgets.QMainWindow):
            raise RuntimeError(f"`--ui-real` requires a QMainWindow root UI: {self.ui_path}")
        _configure_real_ui_input_dependencies()
        self.window.installEventFilter(self)
        self.window.setWindowTitle(f"{APP_TITLE} [main.ui Runtime]")
        self.window.setProperty("nc_ui_real_runtime", True)
        self.window.setDockNestingEnabled(True)
        self.window.setTabPosition(QtCore.Qt.AllDockWidgetAreas, QtWidgets.QTabWidget.North)
        setattr(self.window, "_nc_ui_real_bridge", self)
        self._app = QtWidgets.QApplication.instance()
        if self._app is not None:
            self._app.installEventFilter(self)

        self._engine_lifecycle_service = QtEngineLifecycleService(self.backend)
        self._runtime_control_service = QtRuntimeControlService(self.backend)
        self._chat_context_service = QtChatContextService(self.backend)
        self._input_action_service = QtInputActionService(self.backend)
        self._model_refresh_service = QtModelRefreshService(self.backend)
        self._runtime_status_service = QtRuntimeStatusService(self.backend)
        self._provider_runtime_redirected = False
        self._chat_session_runtime_redirected = False
        self._sensory_runtime_redirected = False
        self._musetalk_preview_runtime_redirected = False
        self._visual_reply_runtime_redirected = False
        self._adopted_runtime_tabs = {}
        self._frontend_theme_apply_in_progress = False
        self._frontend_system_prompt_commit_timer = QtCore.QTimer(self.window)
        self._frontend_system_prompt_commit_timer.setSingleShot(True)
        self._frontend_system_prompt_commit_timer.timeout.connect(self._commit_frontend_system_prompt_to_runtime)
        self._frontend_layout_save_timer = QtCore.QTimer(self.window)
        self._frontend_layout_save_timer.setSingleShot(True)
        self._frontend_layout_save_timer.setInterval(650)
        self._frontend_layout_save_timer.timeout.connect(self._save_frontend_layout_state)
        self._frontend_active_tutorial_overlay = None

        _configure_real_ui_layout_dependencies()
        _configure_real_ui_theme_dependencies()
        _configure_real_ui_tutorial_dependencies()
        _configure_real_ui_binding_dependencies()
        _configure_real_ui_actions_dependencies()
        _configure_real_ui_sync_dependencies()
        _configure_real_ui_surfaces_dependencies()
        self._bind_frontend_workspace_constraint_hooks()
        self._configure_frontend_runtime_slice()
        self._configure_frontend_tab_bars()
        self._normalize_frontend_chat_runtime_editor_widths()
        self._bind_frontend_layout_persistence_hooks()
        self._restore_frontend_layout_state()
        self._sync_backend_to_ui(force=True)

        # Fix Designer-loaded scroll/content/tab sizing after runtime state has populated the UI.
        #self._fix_system_shaping_scroll_content_size()
        #QtCore.QTimer.singleShot(0, self._fix_system_shaping_scroll_content_size)

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_backend_state)
        self._poll_timer.start()

        print("[UI Real] Loaded runtime-backed main.ui front-end.")
        print("[UI Real] Stable default app startup remains python qt_app.py.")
        print("[UI Real] Phase 5 slice is live: engine lifecycle, runtime controls, chat-context actions, status, and console/chat mirroring.")

    def _ui(self, name, cls=None):
        if not hasattr(self, "window") or self.window is None:
            return None
        return self.window.findChild(cls or QtWidgets.QWidget, name)


    def eventFilter(self, watched, event):
        if event is not None and event.type() == QtCore.QEvent.Wheel:
            try:
                if isinstance(watched, QtWidgets.QTabBar):
                    return True
            except Exception:
                pass
        if event is not None and self._watched_belongs_to_frontend(watched):
            try:
                if self._consume_frontend_push_to_talk_event(event):
                    return True
            except Exception:
                pass
        if watched is self.window and event is not None:
            try:
                if event.type() == QtCore.QEvent.Close:
                    self._save_frontend_layout_state()
                    self.close()
                elif event.type() in {QtCore.QEvent.Move, QtCore.QEvent.Resize, QtCore.QEvent.WindowStateChange}:
                    self._schedule_frontend_layout_save()
            except Exception:
                pass
        elif event is not None and event.type() == QtCore.QEvent.Resize:
            try:
                if isinstance(watched, QtWidgets.QDockWidget) and watched.window() is self.window:
                    self._schedule_frontend_layout_save()
            except Exception:
                pass
        return super().eventFilter(watched, event)

    def show(self):
        self.window.show()

    def _configure_frontend_tab_bars(self):
        for tab_widget in self.window.findChildren(QtWidgets.QTabWidget):
            try:
                tab_bar = tab_widget.tabBar()
            except Exception:
                tab_bar = None
            if tab_bar is None:
                continue
            try:
                tab_bar.setExpanding(False)
            except Exception:
                pass
            try:
                tab_bar.setUsesScrollButtons(True)
            except Exception:
                pass
            try:
                tab_bar.setElideMode(QtCore.Qt.ElideNone)
            except Exception:
                pass
            try:
                tab_widget.setUsesScrollButtons(True)
            except Exception:
                pass
            try:
                tab_widget.setElideMode(QtCore.Qt.ElideNone)
            except Exception:
                pass
            try:
                tab_bar.installEventFilter(self)
            except Exception:
                pass

    def close(self):
        if self._closing:
            return
        self._closing = True
        try:
            timer = getattr(self, "_frontend_system_prompt_commit_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
            self._commit_frontend_system_prompt_to_runtime()
        except Exception:
            pass
        self._save_frontend_layout_state()
        try:
            timer = getattr(self, "_poll_timer", None)
            if timer is not None:
                timer.stop()
        except Exception:
            pass
        try:
            self.window.removeEventFilter(self)
        except Exception:
            pass
        try:
            if self._app is not None:
                self._app.removeEventFilter(self)
        except Exception:
            pass
        try:
            overlay = getattr(self, "_frontend_active_tutorial_overlay", None)
            if overlay is not None:
                overlay.finish("closed")
        except Exception:
            pass
        try:
            if self.backend is not None:
                self.backend.close()
        except Exception:
            pass










    def smoke_summary(self):
        return {
            "ui_path": str(self.ui_path),
            "window_class": self.window.__class__.__name__,
            "backend_hidden": bool(self.backend is not None and not self.backend.isVisible()),
            "lifecycle_buttons": [
                name
                for name in ("btn_start_engine", "btn_stop_engine", "btn_reset_chat")
                if self._ui_object(name) is not None
            ],
            "runtime_action_buttons": [
                name
                for name in ("btn_regenerate", "btn_retry", "btn_pause", "btn_skip", "btn_skip_user")
                if self._ui_object(name) is not None
            ],
            "chat_context_buttons": [
                name
                for name in (
                    "chat_quick_save_button",
                    "chat_quick_load_button",
                    "btn_save_chat_session",
                    "btn_load_chat_session",
                    "btn_reset_chat_session",
                )
                if self._ui_object(name) is not None
            ],
            "console_chat_bound": bool(self._ui_object("console_edit") is not None and self._ui_object("chat_edit") is not None),
            "runtime_status": self._runtime_status_service.status_line(),
            "provider_runtime_redirected": bool(self._provider_runtime_redirected),
            "chat_session_runtime_redirected": bool(self._chat_session_runtime_redirected),
            "sensory_runtime_redirected": bool(self._sensory_runtime_redirected),
            "musetalk_preview_runtime_redirected": bool(self._musetalk_preview_runtime_redirected),
            "visual_reply_runtime_redirected": bool(self._visual_reply_runtime_redirected),
            "visual_reply_panel_class": (
                getattr(getattr(self, "_frontend_visual_reply_panel", None), "__class__", type(None)).__name__
                if getattr(self, "_frontend_visual_reply_panel", None) is not None
                else ""
            ),
            "adopted_runtime_tabs": {
                target: list(titles or [])
                for target, titles in dict(self._adopted_runtime_tabs or {}).items()
                if titles
            },
            "sensory_runtime_tabs": self._tab_titles(self._ui_object("sensory_feedback_tabs")),
        }

    def _ui_object(self, object_name):
        return _ui_shell_find_object(self.window, object_name)






    def _configure_frontend_runtime_slice(self):
        self._apply_theme_to_frontend_window()
        self._configure_frontend_runtime_group_boxes()
        self._redirect_backend_provider_runtime_surface()
        self._redirect_backend_chat_session_runtime_surface()
        self._redirect_backend_pipeline_telemetry_surface()
        self._redirect_backend_sensory_runtime_surface()
        self._redirect_backend_addons_management_surface()
        self._redirect_backend_musetalk_preview_runtime_surface()
        self._redirect_backend_visual_reply_runtime_surface()
        self._adopt_backend_runtime_tabs()
        self._cleanup_frontend_preview_only_roots()
        self._disable_unwired_phase5_controls()
        self._prime_frontend_audio_device_controls()
        self._bind_basic_runtime_mirrors()
        self._bind_lifecycle_controls()
        self._bind_runtime_action_controls()
        self._bind_chat_context_controls()
        self._bind_tutorial_runtime_controls()
        self._bind_model_refresh_control()
        self._bind_push_to_talk_control()
        self._bind_chat_edit_controls()
        self._bind_dry_run_controls()
        self._bind_response_length_runtime_controls()
        self._bind_host_input_runtime_controls()
        self._bind_musetalk_visual_runtime_controls()
        self._bind_avatar_body_vam_runtime_controls()
        self._bind_profile_utility_runtime_controls()
        self._bind_chunking_runtime_controls()
        self._bind_frontend_theme_controls()
        self._bind_chat_session_runtime_controls()
        self._bind_sensory_runtime_controls()
        self._bind_audio_story_duplicate_controls()
        self._bind_musetalk_preview_controls()
        self._bind_visual_reply_controls()
        self._bind_provider_model_workflow_controls()
        self._bind_frontend_to_backend_sync()
        self._configure_phase5_placeholders()
        self._apply_theme_to_runtime_panels()
        self._apply_frontend_workspace_view_constraints()
        self._refresh_frontend_theme_controls()












































































































































































































    def _poll_backend_state(self):
        if self._closing:
            return
        self._sync_backend_to_ui(force=False)

    def _start_engine_from_ui_real(self):
        self._sync_frontend_to_backend()
        self._engine_lifecycle_service.start_engine()
        QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _request_model_refresh_from_ui_real(self):
        self._sync_frontend_to_backend()
        self._model_refresh_service.refresh(quiet=False, wait_for_reachable=False)
        QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
        QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))
