from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import shiboken6
except Exception:
    shiboken6 = None

from ui.widgets.basic import NoWheelTabWidget


class BackendAddonMountMixin:
    """Mount addon-provided Qt tab contributions into backend tab containers."""

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
            snapshot = list(manager.get_addon_registry_snapshot() or [])
        except Exception:
            return True
        for category in snapshot:
            for addon in list(dict(category).get("addons") or []):
                if str(addon.get("id") or "").strip() == target:
                    return bool(addon.get("effective_enabled", False))
        return False

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
        tab_specs = (
            ("nc.vseeface_avatar", "vseeface_tab", "VSeeFace"),
            ("nc.musetalk_avatar", "musetalk_tab", "MuseTalk"),
            ("nc.vam_avatar", "vam_tab", "VaM"),
        )
        tabs = getattr(self, "tabs", None)
        for addon_id, widget_name, title in tab_specs:
            if self._addon_effectively_enabled(addon_id):
                continue
            self._remove_tab_by_widget_name_or_title(tabs, widget_name, title)
        if self._addon_effectively_enabled("nc.visual_reply"):
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

    def _get_addon_instance(self, addon_id):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return None
        return manager.get_addon_instance(str(addon_id or ""))

    def _get_addon_controller(self, addon_id):
        instance = self._get_addon_instance(addon_id)
        if instance is None:
            return None
        return getattr(instance, "controller", None)

    def _require_addon_controller(self, addon_id):
        controller = self._get_addon_controller(addon_id)
        if controller is None:
            raise RuntimeError(f"Addon controller is unavailable for {addon_id}")
        return controller

    def _addon_contribution_enabled(self, contribution):
        metadata = dict(getattr(contribution, "metadata", {}) or {})
        if not bool(metadata.get("checkable", False)):
            return True
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return bool(metadata.get("default_enabled", True))
        result = manager.invoke_capability(
            "ui.tab_enabled",
            {
                "addon_id": str(getattr(contribution, "addon_id", "") or ""),
                "tab_id": str(getattr(contribution, "id", "") or ""),
                "action": "get",
            },
        )
        if isinstance(result, dict) and "enabled" in result:
            return bool(result.get("enabled"))
        return bool(metadata.get("default_enabled", True))

    def _set_addon_contribution_enabled(self, contribution, enabled):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return bool(enabled)
        result = manager.invoke_capability(
            "ui.tab_enabled",
            {
                "addon_id": str(getattr(contribution, "addon_id", "") or ""),
                "tab_id": str(getattr(contribution, "id", "") or ""),
                "action": "set",
                "enabled": bool(enabled),
            },
        )
        if isinstance(result, dict) and "enabled" in result:
            return bool(result.get("enabled"))
        return bool(enabled)

    def _rebuild_addon_host_child_tabs(self, host_tab_id):
        group = dict(self._addon_host_tab_groups.get(str(host_tab_id or "")) or {})
        if not group:
            return
        nested_tabs = group.get("nested_tabs")
        if nested_tabs is None:
            return
        child_widgets = list(group.get("child_widgets", []))
        for widget in child_widgets:
            try:
                if widget is None:
                    continue
                index = nested_tabs.indexOf(widget)
                if index >= 0:
                    nested_tabs.removeTab(index)
                widget.deleteLater()
            except Exception:
                pass
        group["child_widgets"] = []
        host_widget = group.get("host_widget")
        if host_widget is not None and nested_tabs.indexOf(host_widget) < 0:
            label = str(group.get("host_child_title") or "Source").strip() or "Source"
            nested_tabs.addTab(host_widget, label)
        checkboxes = dict(group.get("checkboxes", {}) or {})
        for child in list(group.get("children", [])):
            child_id = str(getattr(child, "id", "") or "")
            enabled = self._addon_contribution_enabled(child)
            checkbox = checkboxes.get(child_id)
            if checkbox is not None:
                checkbox.blockSignals(True)
                checkbox.setChecked(bool(enabled))
                checkbox.blockSignals(False)
            if not enabled:
                continue
            try:
                child_widget = child.factory(None)
                if child_widget is None:
                    continue
                index = nested_tabs.addTab(child_widget, child.title)
                self._set_addon_tab_icon(nested_tabs, index, child)
                if child.tooltip:
                    nested_tabs.setTabToolTip(index, child.tooltip)
                group.setdefault("child_widgets", []).append(child_widget)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount child tab '{child_id}': {exc}")
        self._addon_host_tab_groups[str(host_tab_id or "")] = group

    def _build_addon_host_tab_widget(self, host_contribution, child_contributions):
        metadata = dict(getattr(host_contribution, "metadata", {}) or {})
        host_widget = host_contribution.factory(None)
        if host_widget is None:
            host_widget = QtWidgets.QWidget()
            host_layout = QtWidgets.QVBoxLayout(host_widget)
            placeholder = QtWidgets.QLabel("This foundational addon does not expose a source view.")
            placeholder.setWordWrap(True)
            host_layout.addWidget(placeholder)
            host_layout.addStretch(1)
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        checkboxes = {}
        checkable_children = [
            child for child in child_contributions if bool(dict(getattr(child, "metadata", {}) or {}).get("checkable", False))
        ]
        if checkable_children:
            header = QtWidgets.QLabel("Include")
            header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(header)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            for child in checkable_children:
                checkbox = QtWidgets.QCheckBox(child.title)
                checkbox.setChecked(bool(self._addon_contribution_enabled(child)))
                checkbox.toggled.connect(
                    lambda checked, host_id=host_contribution.id, child_id=child.id: self._on_addon_child_checkbox_toggled(host_id, child_id, checked)
                )
                row.addWidget(checkbox)
                checkboxes[str(child.id or "")] = checkbox
            row.addStretch(1)
            layout.addLayout(row)
        nested_tabs = NoWheelTabWidget()
        nested_tabs.setObjectName(f"addon_group_tabs_{host_contribution.id}")
        layout.addWidget(nested_tabs, 1)
        self._addon_host_tab_groups[str(host_contribution.id or "")] = {
            "container": container,
            "nested_tabs": nested_tabs,
            "host_widget": host_widget,
            "host_child_title": str(metadata.get("nested_title") or "Source").strip() or "Source",
            "children": list(child_contributions),
            "children_by_id": {str(child.id or ""): child for child in child_contributions},
            "checkboxes": checkboxes,
            "child_widgets": [],
        }
        self._rebuild_addon_host_child_tabs(host_contribution.id)
        return container

    def _on_addon_child_checkbox_toggled(self, host_tab_id, child_tab_id, checked):
        group = dict(self._addon_host_tab_groups.get(str(host_tab_id or "")) or {})
        if not group:
            return
        child = dict(group.get("children_by_id", {}) or {}).get(str(child_tab_id or ""))
        if child is None:
            return
        actual_enabled = self._set_addon_contribution_enabled(child, bool(checked))
        checkbox = dict(group.get("checkboxes", {}) or {}).get(str(child_tab_id or ""))
        if checkbox is not None:
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(actual_enabled))
            checkbox.blockSignals(False)
        self._rebuild_addon_host_child_tabs(host_tab_id)
        self.save_session()

    def _refresh_addon_group_tabs(self):
        for host_tab_id in list(getattr(self, "_addon_host_tab_groups", {}).keys()):
            self._rebuild_addon_host_child_tabs(host_tab_id)

    def _mount_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "tabs"):
            return
        contributions = list(self._addon_manager.get_tab_contributions(area="top_level"))
        child_contributions = {}
        top_level_contributions = []
        for contribution in contributions:
            parent_tab_id = str(getattr(contribution, "parent_tab_id", "") or "").strip()
            if parent_tab_id:
                child_contributions.setdefault(parent_tab_id, []).append(contribution)
            else:
                top_level_contributions.append(contribution)
        for contribution in top_level_contributions:
            if contribution.id in self._mounted_addon_tab_ids:
                continue
            try:
                children = list(child_contributions.get(contribution.id, []))
                widget = self._build_addon_host_tab_widget(contribution, children) if children else contribution.factory(None)
                if widget is None:
                    continue
                target_index = -1
                for index in range(self.tabs.count()):
                    try:
                        if str(self.tabs.tabText(index) or "").strip() == str(contribution.title or "").strip():
                            target_index = index
                            break
                    except Exception:
                        continue
                if target_index >= 0:
                    old_widget = self.tabs.widget(target_index)
                    self.tabs.removeTab(target_index)
                    if old_widget is not None and old_widget is not widget:
                        old_widget.setParent(None)
                        old_widget.deleteLater()
                    tab_index = self.tabs.insertTab(target_index, widget, contribution.title)
                else:
                    tab_index = self.tabs.addTab(widget, contribution.title)
                self._set_addon_tab_icon(self.tabs, tab_index, contribution)
                if contribution.tooltip:
                    self.tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount tab '{contribution.id}': {exc}")
        for parent_tab_id, children in child_contributions.items():
            if parent_tab_id in self._mounted_addon_tab_ids:
                continue
            child_ids = ", ".join(str(child.id or "") for child in children)
            print(f"⚠️ [Addons] Child tabs {child_ids} declared missing parent '{parent_tab_id}'.")

    def _mount_musetalk_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "musetalk_tabs"):
            return
        for contribution in self._addon_manager.get_tab_contributions(area="musetalk"):
            if contribution.id in self._mounted_musetalk_addon_tab_ids:
                continue
            try:
                widget = contribution.factory(None)
                if widget is None:
                    continue
                tab_index = self.musetalk_tabs.addTab(widget, contribution.title)
                self._set_addon_tab_icon(self.musetalk_tabs, tab_index, contribution)
                if contribution.tooltip:
                    self.musetalk_tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_musetalk_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount MuseTalk tab '{contribution.id}': {exc}")

    def _mount_host_settings_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "host_settings_tabs"):
            return
        contributions = list(self._addon_manager.get_tab_contributions(area="host_settings"))
        child_contributions = {}
        top_level_contributions = []
        for contribution in contributions:
            parent_tab_id = str(getattr(contribution, "parent_tab_id", "") or "").strip()
            if parent_tab_id:
                child_contributions.setdefault(parent_tab_id, []).append(contribution)
            else:
                top_level_contributions.append(contribution)
        for contribution in top_level_contributions:
            if contribution.id in self._mounted_host_settings_addon_tab_ids:
                continue
            try:
                children = list(child_contributions.get(contribution.id, []))
                widget = self._build_addon_host_tab_widget(contribution, children) if children or getattr(contribution, "metadata", None) else contribution.factory(None)
                if widget is None:
                    continue
                insert_index = min(1 + len(self._mounted_host_settings_addon_tab_ids), self.host_settings_tabs.count())
                tab_index = self.host_settings_tabs.insertTab(insert_index, widget, contribution.title)
                self._set_addon_tab_icon(self.host_settings_tabs, tab_index, contribution)
                if contribution.tooltip:
                    self.host_settings_tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_host_settings_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount host settings tab '{contribution.id}': {exc}")
        for parent_tab_id, children in child_contributions.items():
            if parent_tab_id in self._mounted_host_settings_addon_tab_ids:
                self._sync_existing_host_settings_child_tabs(parent_tab_id, children)
                continue
            child_ids = ", ".join(str(child.id or "") for child in children)
            print(f"⚠️ [Addons] Host settings child tabs {child_ids} declared missing parent '{parent_tab_id}'.")
        QtCore.QTimer.singleShot(0, lambda tabs=self.host_settings_tabs: self._sync_tab_widget_height(tabs))

    def _mount_tts_runtime_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "tts_runtime_addon_tabs"):
            return
        contributions = list(self._addon_manager.get_tab_contributions(area="tts_runtime"))
        for contribution in contributions:
            if contribution.id in self._mounted_tts_runtime_addon_tab_ids:
                continue
            try:
                widget = contribution.factory(None)
                if widget is None:
                    continue
                backend_id = str(
                    dict(getattr(contribution, "metadata", {}) or {}).get("backend_id")
                    or contribution.id
                    or contribution.title
                    or ""
                ).strip().lower()
                if backend_id:
                    try:
                        widget.setProperty("backend_id", backend_id)
                    except Exception:
                        pass
                tab_index = self.tts_runtime_addon_tabs.addTab(widget, contribution.title)
                self._set_addon_tab_icon(self.tts_runtime_addon_tabs, tab_index, contribution)
                if contribution.tooltip:
                    self.tts_runtime_addon_tabs.setTabToolTip(tab_index, contribution.tooltip)
                if backend_id:
                    self._tts_runtime_tab_index_by_backend[backend_id] = tab_index
                self._mounted_tts_runtime_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount TTS runtime tab '{contribution.id}': {exc}")
                fallback = QtWidgets.QWidget()
                fallback_layout = QtWidgets.QVBoxLayout(fallback)
                fallback_layout.setContentsMargins(10, 10, 10, 10)
                fallback_layout.setSpacing(8)
                title = QtWidgets.QLabel(str(contribution.title or contribution.id or "TTS Addon"))
                title.setStyleSheet("font-weight: 600; color: #d8dee9;")
                message = QtWidgets.QLabel(
                    f"Could not load the UI for '{contribution.title or contribution.id}'.\n\n{exc}"
                )
                message.setWordWrap(True)
                message.setStyleSheet("color: #8ea3b8;")
                fallback_layout.addWidget(title)
                fallback_layout.addWidget(message)
                fallback_layout.addStretch(1)
                tab_index = self.tts_runtime_addon_tabs.addTab(fallback, contribution.title)
                self._set_addon_tab_icon(self.tts_runtime_addon_tabs, tab_index, contribution)
                if contribution.tooltip:
                    self.tts_runtime_addon_tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_tts_runtime_addon_tab_ids.add(contribution.id)
        if hasattr(self, "tts_runtime_addon_tabs"):
            self.tts_runtime_addon_tabs.setVisible(self.tts_runtime_addon_tabs.count() > 0)
        self._refresh_tts_runtime_card()

    def _on_tts_runtime_addon_tab_changed_old(self, index):
        if not hasattr(self, "tts_runtime_addon_tabs"):
            return
        current = self.tts_runtime_addon_tabs.widget(index)
        if current is None:
            return
        backend_id = str(current.property("backend_id") or current.objectName() or "").strip().lower()
        if backend_id:
            self._tts_runtime_tab_index_by_backend[backend_id] = index

    def _on_tts_runtime_addon_tab_changed(self, index):
        if not hasattr(self, "tts_runtime_addon_tabs"):
            return
        current = self.tts_runtime_addon_tabs.widget(index)
        if current is None:
            return
        backend_id = str(current.property("backend_id") or current.objectName() or "").strip().lower()
        if backend_id:
            self._tts_runtime_tab_index_by_backend[backend_id] = index

        sync_func = getattr(self, "_sync_tts_runtime_fields_height", None)
        if not sync_func:
            backend = getattr(self, "backend", None)
            sync_func = getattr(backend, "_sync_tts_runtime_fields_height", None)

        if sync_func:
            QtCore.QTimer.singleShot(10, sync_func)

    def _sync_existing_host_settings_child_tabs(self, host_tab_id, children):
        host_tab_id = str(host_tab_id or "").strip()
        group = dict(self._addon_host_tab_groups.get(host_tab_id) or {})
        if not group:
            return
        existing_by_id = dict(group.get("children_by_id", {}) or {})
        changed = False
        for child in list(children or []):
            child_id = str(getattr(child, "id", "") or "").strip()
            if not child_id or child_id in existing_by_id:
                continue
            group.setdefault("children", []).append(child)
            existing_by_id[child_id] = child
            changed = True
        if not changed:
            return
        group["children_by_id"] = existing_by_id
        self._addon_host_tab_groups[host_tab_id] = group
        self._rebuild_addon_host_child_tabs(host_tab_id)

    def _mount_operational_view_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "right_tabs"):
            return
        contributions = list(self._addon_manager.get_tab_contributions(area="operational_view"))
        for contribution in contributions:
            if contribution.id in self._mounted_operational_view_addon_tab_ids:
                continue
            try:
                widget = contribution.factory(None)
                if widget is None:
                    continue
                tab_index = self.right_tabs.addTab(widget, contribution.title)
                self._set_addon_tab_icon(self.right_tabs, tab_index, contribution)
                if contribution.tooltip:
                    self.right_tabs.setTabToolTip(tab_index, contribution.tooltip)
                self._mounted_operational_view_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount operational tab '{contribution.id}': {exc}")
