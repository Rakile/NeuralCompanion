import time

from PySide6 import QtCore, QtGui, QtWidgets

from ui.designer_loader import ui_shell_find_object as _ui_shell_find_object
from ui.dock_utils import install_floating_dock_resize_filter
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
        "DEFAULT_APP_THEME_PRESET": DEFAULT_APP_THEME_PRESET,
        "RUNTIME_CONFIG": RUNTIME_CONFIG,
        "SESSION_PATH": SESSION_PATH,
        "_app_theme_palette": _app_theme_palette,
        "_apply_workspace_view_constraints": _apply_workspace_view_constraints,
        "_normalize_app_theme_preset_id": _normalize_app_theme_preset_id,
        "_split_collapsible_section_text": _split_collapsible_section_text,
    })


def _configure_real_ui_theme_dependencies():
    configure_real_ui_theme_dependencies({
        "APP_THEME_PRESET_LABELS": APP_THEME_PRESET_LABELS,
        "APP_THEME_PRESET_WIDGETS": APP_THEME_PRESET_WIDGETS,
        "DEFAULT_APP_THEME_PRESET": DEFAULT_APP_THEME_PRESET,
        "RUNTIME_CONFIG": RUNTIME_CONFIG,
        "SESSION_PATH": SESSION_PATH,
        "_WIN32_DOCK_OWNER_SUPPORTED": bool(globals().get("_WIN32_DOCK_OWNER_SUPPORTED", False)),
        "_WIN32_GWLP_HWNDPARENT": int(globals().get("_WIN32_GWLP_HWNDPARENT", -8)),
        "_win32_set_window_owner": globals().get("_win32_set_window_owner"),
        "ctypes": globals().get("ctypes"),
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
        "_ui_shell_body_slider_raw_to_value": _ui_shell_body_slider_raw_to_value,
        "_ui_shell_body_value_to_slider_raw": _ui_shell_body_value_to_slider_raw,
        "_ui_shell_update_body_label": _ui_shell_update_body_label,
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
        "musetalk_state": musetalk_state,
    })


def _configure_real_ui_surfaces_dependencies():
    configure_real_ui_surfaces_dependencies({
        "UI_REAL_PREVIEW_ONLY_ROOTS": UI_REAL_PREVIEW_ONLY_ROOTS,
        "__file__": __file__,
    })


class MainUiRealRuntimeBridge(MainUiRealLayoutMixin, MainUiRealInputMixin, MainUiRealTabAdoptionMixin, MainUiRealThemeMixin, MainUiRealTutorialMixin, MainUiRealBindingMixin, MainUiRealActionsMixin, MainUiRealSyncMixin, MainUiRealSurfacesMixin, QtCore.QObject):
    """Opt-in runtime-backed `main.ui` front-end backed by a hidden legacy window."""

    system_prompt_refined = QtCore.Signal(str, str)

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
        self._frontend_layout_persistence_ready = False
        self.backend = CompanionQtMainWindow(suppress_restored_aux_docks=True)
        self.backend._session_read_only = self._session_read_only
        self.backend.frontend_layout_resync_callback = self._schedule_frontend_runtime_layout_pass
        self._frontend_should_prompt_first_run = bool(getattr(self.backend, "first_run", False)) and not self._session_read_only
        self._frontend_first_run_prompt_scheduled = False
        self.backend.first_run = False
        self.backend.hide()
        self.window = _load_ui_preview_window(self.ui_path)
        if not isinstance(self.window, QtWidgets.QMainWindow):
            raise RuntimeError(f"`--ui-real` requires a QMainWindow root UI: {self.ui_path}")
        _configure_real_ui_input_dependencies()
        self.window.installEventFilter(self)
        self.window.setWindowTitle(APP_TITLE)
        try:
            icon = QtGui.QIcon(str(APP_ICON_PATH))
            if not icon.isNull():
                self.window.setWindowIcon(icon)
        except Exception:
            pass
        self.window.setProperty("nc_ui_real_runtime", True)
        # main.ui is authored with Qt's more aggressive dock flags
        # (GroupedDragging/AnimatedDocks). Those can become unstable once the
        # runtime bridge starts replacing dock contents with live widgets, so
        # keep the real UI close to the legacy window's simpler dock behavior.
        self.window.setDockOptions(
            QtWidgets.QMainWindow.AllowNestedDocks
            | QtWidgets.QMainWindow.AllowTabbedDocks
        )
        self.window.setDockNestingEnabled(True)
        self.window.setTabPosition(QtCore.Qt.AllDockWidgetAreas, QtWidgets.QTabWidget.North)
        install_floating_dock_resize_filter(self.window)
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
        self.system_prompt_refined.connect(self._on_frontend_system_prompt_refined)
        self._frontend_layout_save_timer = QtCore.QTimer(self.window)
        self._frontend_layout_save_timer.setSingleShot(True)
        self._frontend_layout_save_timer.setInterval(650)
        self._frontend_layout_save_timer.timeout.connect(self._save_frontend_layout_state)
        self._frontend_addon_session_save_timer = QtCore.QTimer(self.window)
        self._frontend_addon_session_save_timer.setSingleShot(True)
        self._frontend_addon_session_save_timer.setInterval(450)
        self._frontend_addon_session_save_timer.timeout.connect(self._save_backend_session_from_adopted_addons)
        self._frontend_active_tutorial_overlay = None
        self._last_frontend_heavy_sync_at = 0.0
        self._musetalk_preview_heavy_sync_interval_s = 1.25
        self._frontend_workspace_layout_busy = False

        _configure_real_ui_layout_dependencies()
        _configure_real_ui_theme_dependencies()
        _configure_real_ui_tutorial_dependencies()
        _configure_real_ui_binding_dependencies()
        _configure_real_ui_actions_dependencies()
        _configure_real_ui_sync_dependencies()
        _configure_real_ui_surfaces_dependencies()
        self._bind_frontend_workspace_constraint_hooks()
        self._configure_frontend_runtime_slice()
        self._normalize_system_shaping_fixed_tab_layout()
        self._configure_frontend_tab_bars()
        self._normalize_frontend_chat_runtime_editor_widths()
        self._normalize_frontend_runtime_section_layouts()
        self._bind_frontend_layout_persistence_hooks()
        if not self._restore_frontend_layout_state():
            self._apply_frontend_default_workspace_layout(save=False)
        self._apply_frontend_workspace_dock_tab_styles()
        QtCore.QTimer.singleShot(0, self._apply_frontend_workspace_dock_tab_styles)
        QtCore.QTimer.singleShot(150, self._apply_frontend_workspace_dock_tab_styles)
        self._sync_backend_to_ui(force=True)
        self._collapse_frontend_runtime_groups()
        QtCore.QTimer.singleShot(0, self._collapse_frontend_runtime_groups)
        QtCore.QTimer.singleShot(150, self._collapse_frontend_runtime_groups)
        QtCore.QTimer.singleShot(0, self._refresh_audio_story_runtime_enabled)
        QtCore.QTimer.singleShot(600, self._refresh_audio_story_runtime_enabled)
        QtCore.QTimer.singleShot(1500, self._refresh_audio_story_runtime_enabled)
        self._fix_sensory_feedback_initial_alignment()
        QtCore.QTimer.singleShot(0, self._fix_sensory_feedback_initial_alignment)
        QtCore.QTimer.singleShot(100, self._fix_sensory_feedback_initial_alignment)
        QtCore.QTimer.singleShot(0, self._normalize_system_shaping_fixed_tab_layout)
        QtCore.QTimer.singleShot(150, self._normalize_system_shaping_fixed_tab_layout)
        self._fix_workspace_tab_content_layouts()
        QtCore.QTimer.singleShot(0, self._fix_workspace_tab_content_layouts)
        QtCore.QTimer.singleShot(150, self._fix_workspace_tab_content_layouts)

        # Fix Designer-loaded scroll/content/tab sizing after runtime state has populated the UI.
        #self._fix_system_shaping_scroll_content_size()
        #QtCore.QTimer.singleShot(0, self._fix_system_shaping_scroll_content_size)

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_backend_state)
        self._poll_timer.start()

        print("[UI Real] Loaded runtime-backed main.ui front-end.")
        print("[UI Real] Phase 5 slice is live: engine lifecycle, runtime controls, chat-context actions, status, and console/chat mirroring.")

    def _mark_frontend_layout_persistence_ready(self):
        self._frontend_layout_persistence_ready = True

    def _ui(self, name, cls=None):
        if not hasattr(self, "window") or self.window is None:
            return None
        return self.window.findChild(cls or QtWidgets.QWidget, name)

    def _forward_tabbar_wheel_to_parent_scroll_area(self, tab_bar, event):
        if tab_bar is None or event is None:
            return False
        scroll_area = None
        tab_widget = tab_bar.parentWidget()
        if isinstance(tab_widget, QtWidgets.QTabWidget):
            try:
                current_page = tab_widget.currentWidget()
            except Exception:
                current_page = None
            if isinstance(current_page, QtWidgets.QAbstractScrollArea):
                scroll_area = current_page
            elif current_page is not None:
                try:
                    scroll_area = current_page.findChild(QtWidgets.QAbstractScrollArea)
                except Exception:
                    scroll_area = None

        if scroll_area is None:
            current = tab_widget
            while current is not None:
                if isinstance(current, QtWidgets.QAbstractScrollArea):
                    scroll_area = current
                    break
                current = current.parentWidget()
        if scroll_area is None:
            return False

        try:
            pixel_delta = event.pixelDelta()
        except Exception:
            pixel_delta = QtCore.QPoint()
        try:
            angle_delta = event.angleDelta()
        except Exception:
            angle_delta = QtCore.QPoint()

        horizontal = bool(event.modifiers() & QtCore.Qt.ShiftModifier)
        if horizontal and pixel_delta.x() == 0 and angle_delta.x() == 0:
            horizontal = False
        scrollbar = scroll_area.horizontalScrollBar() if horizontal else scroll_area.verticalScrollBar()
        if scrollbar is None or not scrollbar.isEnabled() or not scrollbar.isVisible():
            fallback = scroll_area.verticalScrollBar() if horizontal else scroll_area.horizontalScrollBar()
            if fallback is None or not fallback.isEnabled() or not fallback.isVisible():
                return False
            scrollbar = fallback
            horizontal = scrollbar.orientation() == QtCore.Qt.Horizontal

        raw_delta = pixel_delta.x() if horizontal and pixel_delta.x() else pixel_delta.y()
        if not raw_delta:
            raw_delta = angle_delta.x() if horizontal and angle_delta.x() else angle_delta.y()
            if raw_delta:
                step = max(int(scrollbar.singleStep() or 0) * 3, int(scrollbar.pageStep() or 0) // 12, 24)
                raw_delta = int(raw_delta / 120) * step
        if not raw_delta:
            return False
        scrollbar.setValue(int(scrollbar.value() - raw_delta))
        return True


    def eventFilter(self, watched, event):
        if event is not None:
            try:
                if self._handle_frontend_dock_tab_drag(watched, event):
                    return True
            except Exception:
                pass
        if event is not None and event.type() == QtCore.QEvent.Wheel:
            try:
                if isinstance(watched, QtWidgets.QTabBar):
                    self._forward_tabbar_wheel_to_parent_scroll_area(watched, event)
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
                    if (
                        event.type() == QtCore.QEvent.WindowStateChange
                        and bool(self.window.windowState() & QtCore.Qt.WindowMinimized)
                        and hasattr(self, "_collect_frontend_pinned_floating_docks")
                    ):
                        preserved = self._collect_frontend_pinned_floating_docks()
                        QtCore.QTimer.singleShot(0, lambda items=preserved: self._restore_frontend_pinned_floating_docks(items))
                        QtCore.QTimer.singleShot(250, lambda items=preserved: self._restore_frontend_pinned_floating_docks(items))
                        QtCore.QTimer.singleShot(900, lambda items=preserved: self._restore_frontend_pinned_floating_docks(items))
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
        QtCore.QTimer.singleShot(1200, self._mark_frontend_layout_persistence_ready)
        if self._frontend_should_prompt_first_run and not self._frontend_first_run_prompt_scheduled:
            self._frontend_first_run_prompt_scheduled = True
            QtCore.QTimer.singleShot(350, self._maybe_prompt_first_run_tutorial_from_ui_real)

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

    def _bind_adopted_addon_tab_session_save(self, root_widget):
        if root_widget is None:
            return
        widgets = [root_widget]
        try:
            widgets.extend(root_widget.findChildren(QtWidgets.QWidget))
        except Exception:
            pass
        for widget in widgets:
            try:
                if bool(widget.property("_nc_real_ui_session_save_bound")):
                    continue
                widget.setProperty("_nc_real_ui_session_save_bound", True)
            except Exception:
                continue
            for signal_name in ("valueChanged", "currentIndexChanged", "toggled", "textChanged"):
                signal = getattr(widget, signal_name, None)
                if signal is None:
                    continue
                try:
                    signal.connect(lambda *args: self._schedule_adopted_addon_session_save())
                except Exception:
                    pass
            signal = getattr(widget, "editingFinished", None)
            if signal is not None:
                try:
                    signal.connect(self._schedule_adopted_addon_session_save)
                except Exception:
                    pass

    def _schedule_adopted_addon_session_save(self):
        if self._closing:
            return
        timer = getattr(self, "_frontend_addon_session_save_timer", None)
        if timer is None:
            return
        try:
            timer.start()
        except Exception:
            pass

    def _save_backend_session_from_adopted_addons(self):
        if self._closing or self.backend is None:
            return
        try:
            self.backend.save_session()
        except Exception:
            pass

    def close(self):
        if self._closing:
            return
        try:
            timer = getattr(self, "_frontend_layout_save_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
        except Exception:
            pass
        try:
            timer = getattr(self, "_frontend_system_prompt_commit_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
            self._commit_frontend_system_prompt_to_runtime()
        except Exception:
            pass
        self._frontend_layout_persistence_ready = True
        self._save_frontend_layout_state()
        self._closing = True
        try:
            self._sync_frontend_to_backend()
            if self.backend is not None:
                self.backend.save_session()
        except Exception:
            pass
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
                # The real UI has already saved the adopted addon widgets above.
                # Do not let the hidden legacy window's closeEvent write a later
                # addon-empty snapshot after frontend-owned tabs begin closing.
                try:
                    self.backend._session_read_only = True
                except Exception:
                    pass
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
                    "btn_save_chat_session_as",
                    "btn_load_chat_session",
                    "btn_reset_chat_session",
                    "btn_batch_update_long_term_memory",
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
        self._redirect_backend_visual_reply_settings_surface()
        self._adopt_backend_runtime_tabs()
        self._normalize_frontend_runtime_section_layouts()
        self._cleanup_frontend_preview_only_roots()
        self._disable_unwired_phase5_controls()
        self._prime_frontend_audio_device_controls()
        self._redirect_backend_audio_device_controls()
        self._bind_basic_runtime_mirrors()
        self._bind_lifecycle_controls()
        self._bind_runtime_action_controls()
        self._bind_chat_context_controls()
        self._bind_tutorial_runtime_controls()
        self._bind_model_refresh_control()
        self._bind_push_to_talk_control()
        self._bind_chat_edit_controls()
        self._bind_performance_guidance_controls()
        self._bind_dry_run_controls()
        self._bind_response_length_runtime_controls()
        self._bind_host_input_runtime_controls()
        self._bind_addon_owned_runtime_controls()
        self._bind_musetalk_visual_runtime_controls()
        self._bind_avatar_body_vam_runtime_controls()
        self._bind_profile_utility_runtime_controls()
        self._bind_chunking_runtime_controls()
        self._bind_frontend_theme_controls()
        self._bind_chat_session_runtime_controls()
        self._bind_sensory_runtime_controls()
        self._bind_provider_model_workflow_controls()
        self._bind_frontend_to_backend_sync()
        self._configure_phase5_placeholders()
        self._apply_theme_to_runtime_panels()
        self._collapse_frontend_runtime_groups()
        self._apply_frontend_workspace_view_constraints()
        self._refresh_frontend_theme_controls()












































































































































































































    def _poll_backend_state(self):
        if self._closing:
            return
        if bool(getattr(self.backend, "_engine_stop_in_progress", False)):
            self._mirror_runtime_status_widgets()
            self._mirror_pipeline_telemetry_widgets()
            return
        if self._should_lightweight_sync_for_musetalk_preview():
            now = time.monotonic()
            last_sync = float(getattr(self, "_last_frontend_heavy_sync_at", 0.0) or 0.0)
            if now - last_sync < float(getattr(self, "_musetalk_preview_heavy_sync_interval_s", 0.75) or 0.75):
                self._sync_backend_to_ui(force=False, lightweight=True)
                return
            self._last_frontend_heavy_sync_at = now
        else:
            self._last_frontend_heavy_sync_at = time.monotonic()
        self._sync_backend_to_ui(force=False)

    def _should_lightweight_sync_for_pipeline_telemetry(self):
        try:
            snapshot = self.backend._invoke_addon_service_capability(
                "avatar_provider_registry",
                "runtime.pipeline_snapshot",
                {},
                default={},
                provider_id="musetalk",
            )
        except Exception:
            return False
        snapshot = dict(snapshot or {})
        if not bool(snapshot.get("active")):
            return False
        engine_mode = str(snapshot.get("engine_mode", "") or "").strip().lower()
        if engine_mode not in {"musetalk", "vam", "none"}:
            return False
        for chunk in list(snapshot.get("chunks", []) or []):
            chunk = dict(chunk or {})
            if str(chunk.get("playback_state", "") or "") in {"playing", "buffered"}:
                return True
            if str(chunk.get("status", "") or "") in {"generating_audio", "queued_for_render", "rendering"}:
                return True
        return False

    def _should_lightweight_sync_for_musetalk_preview(self):
        if self._should_lightweight_sync_for_pipeline_telemetry():
            return True
        try:
            if self.backend._current_avatar_mode_value() != "musetalk":
                return False
        except Exception:
            return False
        panel = getattr(self.backend, "embedded_musetalk_preview", None)
        if panel is None:
            return False
        try:
            if not panel.isVisible():
                return False
        except Exception:
            return False
        if bool(getattr(panel, "loop_fade_active", False)):
            return True
        if bool(getattr(panel, "frame_paths", None)):
            return True
        try:
            return int(getattr(panel, "current_frame_index", -1) or -1) >= 0
        except Exception:
            return False

    def _start_engine_from_ui_real(self):
        self._sync_frontend_to_backend()
        self._redirect_backend_audio_device_controls()
        self._commit_frontend_audio_device_selection("audio_input_device_combo", "audio_input_device", "Default Input")
        self._commit_frontend_audio_device_selection("audio_output_device_combo", "audio_output_device", "Default Output")
        self._engine_lifecycle_service.start_engine()
        QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _request_model_refresh_from_ui_real(self):
        self._sync_frontend_to_backend()
        self._model_refresh_service.refresh(quiet=False, wait_for_reachable=False)
        QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
        QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))
