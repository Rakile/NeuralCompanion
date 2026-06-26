from core.addons.contributions import ui_mount_adoption_specs, ui_mount_targets


class MainUiRealTabAdoptionMixin:
    """Helpers that adopt addon/runtime tabs from the hidden backend into main.ui."""

    def _tab_titles(self, tabs):
            titles = []
            if tabs is None or not hasattr(tabs, "count"):
                return titles
            for index in range(tabs.count()):
                try:
                    title = str(tabs.tabText(index) or "").strip()
                except Exception:
                    title = ""
                if title:
                    titles.append(title)
            return titles

    def _current_frontend_tab_title(self, object_name):
            tabs = self._ui_object(object_name)
            if tabs is None or not hasattr(tabs, "currentIndex") or not hasattr(tabs, "tabText"):
                return ""
            try:
                index = int(tabs.currentIndex())
            except Exception:
                return ""
            if index < 0:
                return ""
            try:
                title = str(tabs.tabText(index) or "").strip()
            except Exception:
                title = ""
            if title:
                return title
            try:
                return str(tabs.tabToolTip(index) or "").strip()
            except Exception:
                return ""

    def _audio_story_controller(self):
            addon_id = self._addon_id_for_ui_role("audio_story", fallback="")
            if not addon_id:
                return None
            try:
                return self.backend._get_addon_controller(addon_id)
            except Exception:
                return None

    def _tab_contribution_titles(self, area):
            manager = getattr(self.backend, "_addon_manager", None)
            if manager is None:
                return set()
            titles = set()
            for contribution in list(manager.get_tab_contributions(area=area) or []):
                if str(getattr(contribution, "parent_tab_id", "") or "").strip():
                    continue
                title = str(getattr(contribution, "title", "") or "").strip()
                if title:
                    titles.add(title)
            return titles

    def _collect_source_tab_items(self, source_tabs, *, titles=None, start_index=0):
            if source_tabs is None or not hasattr(source_tabs, "count"):
                return []
            wanted_titles = {str(title or "").strip() for title in (titles or []) if str(title or "").strip()}
            matches = []
            for index in range(max(int(start_index), 0), source_tabs.count()):
                try:
                    title = str(source_tabs.tabText(index) or "").strip()
                except Exception:
                    title = ""
                if not title:
                    continue
                if wanted_titles and title not in wanted_titles:
                    continue
                matches.append(
                    {
                        "index": index,
                        "title": title,
                        "widget": source_tabs.widget(index),
                        "tooltip": str(source_tabs.tabToolTip(index) or "").strip(),
                        "icon": source_tabs.tabIcon(index),
                    }
                )
                widget = matches[-1].get("widget")
                if widget is not None and hasattr(widget, "property"):
                    for property_name in ("addon_id", "addon_tab_id", "addon_area", "addon_ui_kind"):
                        try:
                            value = str(widget.property(property_name) or "").strip()
                        except Exception:
                            value = ""
                        if value:
                            matches[-1][property_name] = value
            return matches

    def _target_tab_match(self, target_tabs, title, *, allow_tooltip_match=False):
            wanted = str(title or "").strip()
            if target_tabs is None or not wanted:
                return -1, "", "", None
            for index in range(target_tabs.count()):
                try:
                    target_title = str(target_tabs.tabText(index) or "").strip()
                    target_tooltip = str(target_tabs.tabToolTip(index) or "").strip()
                    candidate = target_title or target_tooltip if allow_tooltip_match else target_title
                    if candidate == wanted:
                        return index, target_title, target_tooltip, target_tabs.tabIcon(index)
                except Exception:
                    continue
            return -1, "", "", None

    def _adopt_collected_source_tabs(self, source_tabs, target_tabs, matches, *, preserve_placeholder_metadata=False):
            adopted = []
            if source_tabs is None or target_tabs is None or not matches:
                return adopted
            for item in reversed(matches):
                try:
                    source_tabs.removeTab(int(item["index"]))
                except Exception:
                    continue
            for item in matches:
                widget = item.get("widget")
                title = str(item.get("title") or "").strip()
                if widget is None or not title:
                    continue
                for property_name in ("addon_id", "addon_tab_id", "addon_area", "addon_ui_kind"):
                    value = str(item.get(property_name) or "").strip()
                    if not value:
                        continue
                    try:
                        widget.setProperty(property_name, value)
                    except Exception:
                        pass
                target_index, preserved_title, preserved_tooltip, preserved_icon = self._target_tab_match(
                    target_tabs,
                    title,
                    allow_tooltip_match=preserve_placeholder_metadata,
                )
                if target_index >= 0:
                    try:
                        old_widget = target_tabs.widget(target_index)
                        target_tabs.removeTab(target_index)
                        if old_widget is not None and old_widget is not widget:
                            old_widget.setParent(None)
                            old_widget.deleteLater()
                    except Exception:
                        pass
                    insert_title = preserved_title if preserve_placeholder_metadata else title
                    new_index = target_tabs.insertTab(target_index, widget, insert_title)
                else:
                    new_index = target_tabs.addTab(widget, title)
                tooltip = preserved_tooltip or str(item.get("tooltip") or "").strip()
                if tooltip:
                    try:
                        target_tabs.setTabToolTip(new_index, tooltip)
                    except Exception:
                        pass
                icon = preserved_icon if preserved_icon is not None and not preserved_icon.isNull() else item.get("icon")
                try:
                    if icon is not None and not icon.isNull():
                        target_tabs.setTabIcon(new_index, icon)
                except Exception:
                    pass
                self._apply_adopted_icon_sidebar_tab_label(target_tabs, new_index, title)
                binder = getattr(self, "_bind_adopted_addon_tab_session_save", None)
                if callable(binder):
                    binder(widget)
                adopted.append(title)
            try:
                target_tabs.setVisible(target_tabs.count() > 0)
            except Exception:
                pass
            return adopted

    def _apply_adopted_icon_sidebar_tab_label(self, target_tabs, index, title):
            try:
                object_name = str(target_tabs.objectName() or "")
            except Exception:
                object_name = ""
            if object_name not in {"left_tabs", "host_settings_tabs"}:
                return
            try:
                icon = target_tabs.tabIcon(int(index))
            except Exception:
                icon = None
            if icon is None or icon.isNull():
                return
            label = str(title or "").strip()
            try:
                if label and not str(target_tabs.tabToolTip(int(index)) or "").strip():
                    target_tabs.setTabToolTip(int(index), label)
            except Exception:
                pass
            try:
                tab_bar = target_tabs.tabBar()
                if tab_bar is not None and label:
                    tab_bar.setTabData(int(index), label)
            except Exception:
                pass
            try:
                target_tabs.setTabText(int(index), "")
            except Exception:
                pass

    def _take_matching_tabs(self, source_tabs, target_tabs, titles):
            if source_tabs is None or target_tabs is None or not titles:
                return []
            matches = self._collect_source_tab_items(source_tabs, titles=titles)
            return self._adopt_collected_source_tabs(
                source_tabs,
                target_tabs,
                matches,
                preserve_placeholder_metadata=True,
            )

    def _take_tabs_after_index(self, source_tabs, target_tabs, start_index=0):
            if source_tabs is None or target_tabs is None:
                return []
            matches = self._collect_source_tab_items(source_tabs, start_index=start_index)
            return self._adopt_collected_source_tabs(source_tabs, target_tabs, matches)

    def _addon_effectively_enabled(self, addon_id):
            manager = getattr(self.backend, "_addon_manager", None)
            if manager is None:
                return True
            target = str(addon_id or "").strip()
            if not target:
                return True
            try:
                return bool(manager.is_addon_effectively_enabled(target))
            except Exception:
                return True

    def _addon_surface_runtime_available(self, addon_id):
            target = str(addon_id or "").strip()
            if not target:
                return True
            if not self._addon_effectively_enabled(target):
                return False
            manager = getattr(self.backend, "_addon_manager", None)
            if manager is None:
                return True
            try:
                record = manager.get_addon_record(target)
            except Exception:
                return True
            return bool(record is not None and str(getattr(record, "state", "") or "").strip() == "initialized")

    def _addon_id_for_ui_role(self, role, fallback=""):
            manager = getattr(self.backend, "_addon_manager", None)
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
            return self._addon_surface_runtime_available(addon_id)

    def _remove_static_addon_placeholder_tab(self, tab_widget_name, placeholder_name, fallback_title=""):
            tabs = self._ui_object(tab_widget_name)
            if tabs is None or not hasattr(tabs, "count"):
                return False
            placeholder = None
            if placeholder_name:
                try:
                    from PySide6 import QtWidgets

                    placeholder = tabs.findChild(QtWidgets.QWidget, str(placeholder_name))
                except Exception:
                    placeholder = None
            target_index = -1
            if placeholder is not None:
                try:
                    target_index = tabs.indexOf(placeholder)
                except Exception:
                    target_index = -1
            if target_index < 0 and fallback_title:
                title = str(fallback_title or "").strip()
                for index in range(tabs.count()):
                    try:
                        tab_title = str(tabs.tabText(index) or "").strip()
                        tooltip = str(tabs.tabToolTip(index) or "").strip()
                    except Exception:
                        continue
                    if title and title in {tab_title, tooltip}:
                        target_index = index
                        placeholder = tabs.widget(index)
                        break
            if target_index < 0:
                return False
            try:
                tabs.removeTab(target_index)
                if placeholder is not None:
                    placeholder.setParent(None)
                    placeholder.deleteLater()
                tabs.setVisible(tabs.count() > 0)
                return True
            except Exception:
                return False

    def _manifest_static_addon_placeholder_specs(self):
            manager = getattr(self.backend, "_addon_manager", None)
            if manager is None:
                return []
            try:
                raw_specs = list(manager.get_ui_placeholder_specs() or [])
            except Exception:
                return []
            specs = []
            for item in raw_specs:
                specs.append(
                    {
                        "addon_id": str(item.get("addon_id") or "").strip(),
                        "tabs": str(item.get("target") or "").strip(),
                        "placeholder": str(item.get("placeholder") or "").strip(),
                        "title": str(item.get("title") or "").strip(),
                    }
                )
            return specs

    def _remove_disabled_static_addon_placeholders(self):
            # main.ui contains a few static placeholder tabs so Designer preview
            # remains useful. Remove them when the matching addon is disabled or
            # absent, otherwise the disabled addon still appears in the real UI.
            placeholders = list(self._manifest_static_addon_placeholder_specs())
            for item in placeholders:
                if self._addon_surface_runtime_available(item.get("addon_id")):
                    continue
                self._remove_static_addon_placeholder_tab(
                    item.get("tabs"),
                    item.get("placeholder"),
                    fallback_title=item.get("title"),
                )

    def _adopt_backend_runtime_tabs(self):
            mappings = ui_mount_adoption_specs()
            adopted_report = {}
            for mapping in mappings:
                source_name = str(mapping.get("source_name") or "").strip()
                target_name = str(mapping.get("target_name") or "").strip()
                source_tabs = getattr(self.backend, source_name, None)
                target_tabs = self._ui_object(target_name)
                if str(mapping.get("mode") or "").strip() == "after_index":
                    adopted = self._take_tabs_after_index(
                        source_tabs,
                        target_tabs,
                        start_index=int(mapping.get("start_index", 0) or 0),
                    )
                else:
                    titles = self._tab_contribution_titles(mapping.get("area"))
                    adopted = self._take_matching_tabs(source_tabs, target_tabs, titles)
                if adopted:
                    adopted_report[target_name] = adopted
            self._remove_disabled_static_addon_placeholders()
            self._adopted_runtime_tabs = adopted_report
            frontend_left_tabs = self._ui_object("left_tabs")
            addon_context_menu_installer = getattr(self.backend, "_install_addon_tab_context_menu", None)
            if frontend_left_tabs is not None:
                self.backend.tabs = frontend_left_tabs
                setattr(self.backend, "left_tabs", frontend_left_tabs)
                if callable(addon_context_menu_installer):
                    addon_context_menu_installer(frontend_left_tabs)
            for target_name in ui_mount_targets():
                if target_name == "left_tabs":
                    continue
                frontend_tabs = self._ui_object(target_name)
                if frontend_tabs is not None:
                    setattr(self.backend, target_name, frontend_tabs)
                    if callable(addon_context_menu_installer):
                        addon_context_menu_installer(frontend_tabs)
            if frontend_left_tabs is not None and hasattr(frontend_left_tabs, "currentChanged"):
                frontend_left_tabs.currentChanged.connect(self._on_frontend_left_tab_changed)
            frontend_right_tabs = self._ui_object("right_tabs")
            if frontend_right_tabs is not None and hasattr(frontend_right_tabs, "currentChanged"):
                frontend_right_tabs.currentChanged.connect(self.backend._on_right_tab_changed)
            frontend_tts_tabs = self._ui_object("tts_runtime_addon_tabs")
            if frontend_tts_tabs is not None and hasattr(frontend_tts_tabs, "currentChanged"):
                frontend_tts_tabs.currentChanged.connect(self.backend._on_tts_runtime_addon_tab_changed)
            frontend_host_tabs = self._ui_object("host_settings_tabs")
            if frontend_host_tabs is not None and hasattr(frontend_host_tabs, "currentChanged"):
                frontend_host_tabs.currentChanged.connect(lambda _index, tabs=frontend_host_tabs: self.backend._sync_tab_widget_height(tabs))
            frontend_sensory_tabs = self._ui_object("sensory_feedback_tabs")
            if frontend_sensory_tabs is not None and hasattr(frontend_sensory_tabs, "currentChanged"):
                frontend_sensory_tabs.currentChanged.connect(lambda _index, tabs=frontend_sensory_tabs: self.backend._sync_tab_widget_height(tabs))
            try:
                self.backend._refresh_tts_runtime_card(activate_tab=True)
            except Exception:
                pass
            try:
                self._configure_frontend_tab_bars()
            except Exception:
                pass
            try:
                self._normalize_system_shaping_fixed_tab_layout()
            except Exception:
                pass
            try:
                self._fix_workspace_tab_content_layouts()
            except Exception:
                pass
            self._refresh_audio_story_runtime_enabled()

    def _refresh_audio_story_runtime_enabled(self):
            try:
                controller = self._audio_story_controller()
                refresh = getattr(controller, "_force_audio_story_runtime_enabled", None)
                if callable(refresh):
                    refresh()
            except Exception:
                pass

    def _on_frontend_left_tab_changed(self, index):
            try:
                self.backend._on_left_tab_changed(index)
            except Exception:
                pass
            tabs = self._ui_object("left_tabs")
            if tabs is not None:
                try:
                    self.backend._sync_tab_widget_height(tabs)
                except Exception:
                    pass
            try:
                self._fix_workspace_tab_content_layouts()
            except Exception:
                pass
