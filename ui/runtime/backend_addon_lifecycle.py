from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import shiboken6
except Exception:
    shiboken6 = None

from ui.widgets.basic import NoWheelTabWidget

class BackendAddonLifecycleMixin:
    def _initialize_addons(self):
        import engine
        from core.addons.manager import AddonManager
        from core.addons.qt_host_services import (
            AddonCapabilityBridgeService,
            QtAvatarProviderService,
            QtChatContextService,
            QtChatProviderService,
            QtChatReplayService,
            QtDialogService,
            QtDryRunService,
            QtEngineLifecycleService,
            QtHotkeyService,
            QtInputActionService,
            QtInputSettingsService,
            QtModelRefreshService,
            QtMuseTalkUIService,
            QtPerformanceProfileService,
            QtPersonaAvatarService,
            QtRuntimeControlService,
            QtRuntimeStatusService,
            QtSensoryService,
            QtShellService,
            QtTutorialService,
            QtVisualReplyService,
        )

        try:
            app_root = Path(__file__).resolve().parents[2]
            runtime_config = getattr(engine, "RUNTIME_CONFIG", {})
            manager = AddonManager(
                app_root=app_root,
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
            self.refresh_avatar_engine_options(selected_provider_id=str(runtime_config.get("avatar_mode", "") or ""))
            self._mount_tts_runtime_addon_tabs()
            self._populate_tts_backend_combo(selected_value=self._current_tts_backend_value())
            self.refresh_sensory_feedback_source_options(selected_value=str(runtime_config.get("sensory_feedback_source", "off") or "off"))
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

    def _addon_contribution_icon(self, contribution):
        metadata = dict(getattr(contribution, "metadata", {}) or {})
        icon_path = str(metadata.get("icon_path") or "").strip()
        if not icon_path:
            return None
        manager = getattr(self, "_addon_manager", None)
        addon_id = str(getattr(contribution, "addon_id", "") or "").strip()
        root_dir = None
        if manager is not None and addon_id:
            try:
                record = manager.get_addon_record(addon_id)
                root_dir = getattr(getattr(record, "manifest", None), "root_dir", None)
            except Exception:
                root_dir = None
        raw_path = Path(icon_path)
        resolved_path = raw_path if raw_path.is_absolute() else Path(root_dir or Path(__file__).resolve().parents[2]) / raw_path
        try:
            icon = QtGui.QIcon(str(resolved_path))
            return icon if not icon.isNull() else None
        except Exception:
            return None

    def _set_addon_tab_icon(self, tab_widget, tab_index, contribution):
        if tab_widget is None or tab_index is None or int(tab_index) < 0:
            return
        icon = self._addon_contribution_icon(contribution)
        if icon is None:
            return
        try:
            tab_widget.setTabIcon(int(tab_index), icon)
        except Exception:
            pass

    def _addon_effectively_enabled(self, addon_id):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return True
        target = str(addon_id or "").strip()
        if not target:
            return True
        try:
            return bool(manager.is_addon_effectively_enabled(target))
        except Exception:
            return True

    def _invoke_addon_capability(self, addon_id, capability, payload=None, default=None):
        manager = getattr(self, "_addon_manager", None)
        if manager is None or not addon_id:
            return default
        try:
            result = manager.invoke_addon_capability(str(addon_id), str(capability), dict(payload or {}))
        except Exception:
            return default
        return default if result is None else result

    def _invoke_addon_service_capability(self, service_id, capability, payload=None, default=None, **metadata_match):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return default
        try:
            result = manager.invoke_service_capability(
                str(service_id),
                str(capability),
                dict(payload or {}),
                **dict(metadata_match or {}),
            )
        except Exception:
            return default
        return default if result is None else result

    def _addon_id_for_ui_role(self, role, fallback=""):
        manager = getattr(self, "_addon_manager", None)
        if manager is not None:
            try:
                addon_id = str(manager.get_addon_id_for_ui_role(role) or "").strip()
                if addon_id:
                    return addon_id
            except Exception:
                pass
        return str(fallback or "").strip()

    def _visual_reply_addon_enabled(self):
        addon_id = self._addon_id_for_ui_role("visual_reply", fallback="")
        return self._addon_effectively_enabled(addon_id)

    def _remove_tab_by_widget_name_or_title(self, tabs, widget_name, fallback_title=""):
        if tabs is None or not hasattr(tabs, "count"):
            return False
        target_index = -1
        target_widget = None
        try:
            target_widget = tabs.findChild(QtWidgets.QWidget, str(widget_name or ""))
        except Exception:
            target_widget = None
        if target_widget is not None:
            try:
                target_index = tabs.indexOf(target_widget)
            except Exception:
                target_index = -1
        if target_index < 0 and fallback_title:
            wanted = str(fallback_title or "").strip()
            for index in range(tabs.count()):
                try:
                    title = str(tabs.tabText(index) or "").strip()
                    tooltip = str(tabs.tabToolTip(index) or "").strip()
                except Exception:
                    continue
                if wanted and wanted in {title, tooltip}:
                    target_index = index
                    target_widget = tabs.widget(index)
                    break
        if target_index < 0:
            return False
        try:
            tabs.removeTab(target_index)
            if target_widget is not None:
                target_widget.setParent(None)
            return True
        except Exception:
            return False

    def _qt_object_alive(self, obj):
        if obj is None:
            return False
        if shiboken6 is None:
            return True
        try:
            return bool(shiboken6.isValid(obj))
        except Exception:
            return False

    def _live_widget_attr(self, name):
        try:
            widget = getattr(self, str(name or ""))
        except Exception:
            return None
        return widget if self._qt_object_alive(widget) else None

    def _live_checked(self, name, fallback=False):
        widget = self._live_widget_attr(name)
        if widget is None or not hasattr(widget, "isChecked"):
            return bool(fallback)
        try:
            return bool(widget.isChecked())
        except RuntimeError:
            return bool(fallback)

    def _live_text(self, name, fallback=""):
        widget = self._live_widget_attr(name)
        if widget is None or not hasattr(widget, "text"):
            return str(fallback or "")
        try:
            return str(widget.text() or "")
        except RuntimeError:
            return str(fallback or "")

    def _live_value(self, name, fallback=0):
        widget = self._live_widget_attr(name)
        if widget is None or not hasattr(widget, "value"):
            return fallback
        try:
            return widget.value()
        except RuntimeError:
            return fallback

    def _live_combo_text(self, name, fallback=""):
        widget = self._live_widget_attr(name)
        if widget is None or not hasattr(widget, "currentText"):
            return str(fallback or "")
        try:
            return str(widget.currentText() or "")
        except RuntimeError:
            return str(fallback or "")

    def _live_combo_data(self, name, fallback=""):
        widget = self._live_widget_attr(name)
        if widget is None or not hasattr(widget, "currentData"):
            return fallback
        try:
            data = widget.currentData()
            return fallback if data is None else data
        except RuntimeError:
            return fallback

    def _apply_disabled_addon_surfaces(self):
        manager = getattr(self, "_addon_manager", None)
        try:
            placeholder_specs = list(manager.get_ui_placeholder_specs() if manager is not None else [])
        except Exception:
            placeholder_specs = []
        tab_widgets = {
            "left_tabs": getattr(self, "tabs", None),
            "host_settings_tabs": getattr(self, "host_settings_tabs", None),
            "right_tabs": getattr(self, "right_tabs", None),
            "tts_runtime_addon_tabs": getattr(self, "tts_runtime_addon_tabs", None),
            "sensory_feedback_tabs": getattr(self, "sensory_feedback_tabs", None),
        }
        for spec in placeholder_specs:
            addon_id = str(spec.get("addon_id") or "").strip()
            if self._addon_effectively_enabled(addon_id):
                continue
            tabs = tab_widgets.get(str(spec.get("target") or "").strip())
            self._remove_tab_by_widget_name_or_title(
                tabs,
                str(spec.get("placeholder") or "").strip(),
                str(spec.get("title") or "").strip(),
            )
        if self._visual_reply_addon_enabled():
            return
        dock = getattr(self, "visual_reply_dock", None)
        if dock is not None:
            try:
                dock.hide()
            except Exception:
                pass
            try:
                action = dock.toggleViewAction()
                if action is not None:
                    action.setVisible(False)
                    action.setEnabled(False)
            except Exception:
                pass
        button = getattr(self, "btn_visual_reply", None)
        if button is not None:
            try:
                button.setVisible(False)
                button.setEnabled(False)
            except Exception:
                pass
