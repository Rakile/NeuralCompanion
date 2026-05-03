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
            try:
                return self.backend._get_addon_controller("nc.audio_story_mode")
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

    def _take_matching_tabs(self, source_tabs, target_tabs, titles):
            adopted = []
            if source_tabs is None or target_tabs is None or not titles:
                return adopted
            matches = []
            for index in range(source_tabs.count()):
                try:
                    title = str(source_tabs.tabText(index) or "").strip()
                except Exception:
                    title = ""
                if title not in titles:
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
                target_index = -1
                preserved_title = ""
                preserved_tooltip = ""
                preserved_icon = None
                for index in range(target_tabs.count()):
                    try:
                        target_title = str(target_tabs.tabText(index) or "").strip()
                        if not target_title:
                            target_title = str(target_tabs.tabToolTip(index) or "").strip()
                        if target_title == title:
                            target_index = index
                            preserved_title = str(target_tabs.tabText(index) or "").strip()
                            preserved_tooltip = str(target_tabs.tabToolTip(index) or "").strip()
                            preserved_icon = target_tabs.tabIcon(index)
                            break
                    except Exception:
                        continue
                if target_index >= 0:
                    try:
                        old_widget = target_tabs.widget(target_index)
                        target_tabs.removeTab(target_index)
                        if old_widget is not None and old_widget is not widget:
                            old_widget.setParent(None)
                            old_widget.deleteLater()
                    except Exception:
                        pass
                    insert_title = preserved_title
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
                binder = getattr(self, "_bind_adopted_addon_tab_session_save", None)
                if callable(binder):
                    binder(widget)
                adopted.append(title)
            try:
                target_tabs.setVisible(target_tabs.count() > 0)
            except Exception:
                pass
            return adopted

    def _take_tabs_after_index(self, source_tabs, target_tabs, start_index=0):
            adopted = []
            if source_tabs is None or target_tabs is None:
                return adopted
            matches = []
            for index in range(max(int(start_index), 0), source_tabs.count()):
                try:
                    title = str(source_tabs.tabText(index) or "").strip()
                except Exception:
                    title = ""
                if not title:
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
            if not matches:
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
                target_index = -1
                for index in range(target_tabs.count()):
                    try:
                        if str(target_tabs.tabText(index) or "").strip() == title:
                            target_index = index
                            break
                    except Exception:
                        continue
                if target_index >= 0:
                    try:
                        old_widget = target_tabs.widget(target_index)
                        target_tabs.removeTab(target_index)
                        if old_widget is not None and old_widget is not widget:
                            old_widget.setParent(None)
                            old_widget.deleteLater()
                    except Exception:
                        pass
                    new_index = target_tabs.insertTab(target_index, widget, title)
                else:
                    new_index = target_tabs.addTab(widget, title)
                tooltip = str(item.get("tooltip") or "").strip()
                if tooltip:
                    try:
                        target_tabs.setTabToolTip(new_index, tooltip)
                    except Exception:
                        pass
                icon = item.get("icon")
                try:
                    if icon is not None and not icon.isNull():
                        target_tabs.setTabIcon(new_index, icon)
                except Exception:
                    pass
                binder = getattr(self, "_bind_adopted_addon_tab_session_save", None)
                if callable(binder):
                    binder(widget)
                adopted.append(title)
            try:
                target_tabs.setVisible(target_tabs.count() > 0)
            except Exception:
                pass
            return adopted

    def _addon_effectively_enabled(self, addon_id):
            manager = getattr(self.backend, "_addon_manager", None)
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

    def _remove_disabled_static_addon_placeholders(self):
            # main.ui contains a few static placeholder tabs so Designer preview
            # remains useful. Remove them when the matching addon is disabled or
            # absent, otherwise the disabled addon still appears in the real UI.
            placeholders = (
                {
                    "addon_id": "nc.audio_story_mode",
                    "tabs": "right_tabs",
                    "placeholder": "audio_story_mode_tab",
                    "title": "Audio Story Mode",
                },
                {
                    "addon_id": "nc.hotkeys",
                    "tabs": "left_tabs",
                    "placeholder": "hotkeys_tab",
                    "title": "Hotkeys",
                },
                {
                    "addon_id": "nc.chat_session_player",
                    "tabs": "left_tabs",
                    "placeholder": "chat_player_tab",
                    "title": "Chat Player",
                },
                {
                    "addon_id": "nc.vseeface_avatar",
                    "tabs": "left_tabs",
                    "placeholder": "vseeface_tab",
                    "title": "VSeeFace",
                },
                {
                    "addon_id": "nc.musetalk_avatar",
                    "tabs": "left_tabs",
                    "placeholder": "musetalk_tab",
                    "title": "MuseTalk",
                },
                {
                    "addon_id": "nc.vam_avatar",
                    "tabs": "left_tabs",
                    "placeholder": "vam_tab",
                    "title": "VaM",
                },
                {
                    "addon_id": "nc.visual_reply",
                    "tabs": "host_settings_tabs",
                    "placeholder": "host_settings_visuals_tab",
                    "title": "Visuals",
                },
                {
                    "addon_id": "nc.visual_story_settings",
                    "tabs": "host_settings_tabs",
                    "placeholder": "host_settings_story_visuals_tab",
                    "title": "Story Visuals",
                },
                {
                    "addon_id": "nc.chatterbox_tts",
                    "tabs": "tts_runtime_addon_tabs",
                    "placeholder": "tts_chatterbox_tab",
                    "title": "Chatterbox",
                },
                {
                    "addon_id": "nc.pockettts",
                    "tabs": "tts_runtime_addon_tabs",
                    "placeholder": "tts_pockettts_tab",
                    "title": "PocketTTS",
                },
            )
            for item in placeholders:
                if self._addon_effectively_enabled(item.get("addon_id")):
                    continue
                self._remove_static_addon_placeholder_tab(
                    item.get("tabs"),
                    item.get("placeholder"),
                    fallback_title=item.get("title"),
                )

    def _adopt_backend_runtime_tabs(self):
            mappings = (
                {
                    "area": "top_level",
                    "source_name": "tabs",
                    "target_name": "left_tabs",
                    "mode": "titles",
                },
                {
                    "area": "host_settings",
                    "source_name": "host_settings_tabs",
                    "target_name": "host_settings_tabs",
                    "mode": "titles",
                },
                {
                    "area": "operational_view",
                    "source_name": "right_tabs",
                    "target_name": "right_tabs",
                    "mode": "titles",
                },
                {
                    "area": "musetalk",
                    "source_name": "musetalk_tabs",
                    "target_name": "musetalk_tabs",
                    "mode": "titles",
                },
                {
                    "area": "tts_runtime",
                    "source_name": "tts_runtime_addon_tabs",
                    "target_name": "tts_runtime_addon_tabs",
                    "mode": "titles",
                },
            )
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
            if frontend_left_tabs is not None:
                self.backend.tabs = frontend_left_tabs
                setattr(self.backend, "left_tabs", frontend_left_tabs)
            for target_name in (
                "host_settings_tabs",
                "right_tabs",
                "musetalk_tabs",
                "tts_runtime_addon_tabs",
                "sensory_feedback_tabs",
            ):
                frontend_tabs = self._ui_object(target_name)
                if frontend_tabs is not None:
                    setattr(self.backend, target_name, frontend_tabs)
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
            current_title = self._current_frontend_tab_title("left_tabs")
            if current_title == "Hotkeys":
                controller = None
                try:
                    controller = self.backend._get_addon_controller("nc.hotkeys")
                except Exception:
                    controller = None
                if controller is not None and hasattr(controller, "refresh_state"):
                    try:
                        controller.refresh_state()
                    except Exception:
                        pass
