from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import shiboken6
except Exception:
    shiboken6 = None

from ui.widgets.basic import NoWheelTabWidget

class BackendAddonTabMountMixin:
    def _split_addon_parent_child_contributions(self, area):
        if self._addon_manager is None:
            return [], {}
        child_contributions = {}
        parent_contributions = []
        for contribution in list(self._addon_manager.get_tab_contributions(area=area) or []):
            parent_tab_id = str(getattr(contribution, "parent_tab_id", "") or "").strip()
            if parent_tab_id:
                child_contributions.setdefault(parent_tab_id, []).append(contribution)
            else:
                parent_contributions.append(contribution)
        return parent_contributions, child_contributions

    def _tab_index_by_title(self, tabs, title):
        if tabs is None or not hasattr(tabs, "count"):
            return -1
        wanted = str(title or "").strip()
        if not wanted:
            return -1
        for index in range(tabs.count()):
            try:
                if str(tabs.tabText(index) or "").strip() == wanted:
                    return index
            except Exception:
                continue
        return -1

    def _install_addon_tab(self, tabs, contribution, widget, *, insert_index=None, replace_matching_title=False):
        if tabs is None or widget is None:
            return -1
        title = str(getattr(contribution, "title", "") or getattr(contribution, "id", "") or "Addon")
        metadata = dict(getattr(contribution, "metadata", {}) or {})
        for property_name, value in (
            ("addon_id", getattr(contribution, "addon_id", "")),
            ("addon_tab_id", getattr(contribution, "id", "")),
            ("addon_area", getattr(contribution, "area", "")),
            ("addon_ui_kind", metadata.get("ui_kind", "")),
        ):
            value = str(value or "").strip()
            if not value:
                continue
            try:
                widget.setProperty(property_name, value)
            except Exception:
                pass
        target_index = self._tab_index_by_title(tabs, title) if replace_matching_title else -1
        if target_index >= 0:
            old_widget = tabs.widget(target_index)
            tabs.removeTab(target_index)
            if old_widget is not None and old_widget is not widget:
                old_widget.setParent(None)
                old_widget.deleteLater()
            tab_index = tabs.insertTab(target_index, widget, title)
        elif insert_index is not None:
            safe_index = max(0, min(int(insert_index), tabs.count()))
            tab_index = tabs.insertTab(safe_index, widget, title)
        else:
            tab_index = tabs.addTab(widget, title)
        self._set_addon_tab_icon(tabs, tab_index, contribution)
        tooltip = str(getattr(contribution, "tooltip", "") or "").strip()
        if tooltip:
            tabs.setTabToolTip(tab_index, tooltip)
        return tab_index

    def _mount_simple_addon_tabs(
        self,
        *,
        area,
        tabs_attr,
        mounted_set_attr,
        log_label,
        insert_index_factory=None,
        replace_matching_title=False,
        configure_widget=None,
        on_mounted=None,
        fallback_factory=None,
    ):
        if self._addon_manager is None or not hasattr(self, tabs_attr):
            return []
        tabs = getattr(self, tabs_attr)
        mounted = getattr(self, mounted_set_attr)
        adopted = []
        for contribution in list(self._addon_manager.get_tab_contributions(area=area) or []):
            if contribution.id in mounted:
                continue
            try:
                widget = contribution.factory(None)
                if widget is None:
                    continue
                if callable(configure_widget):
                    configure_widget(contribution, widget)
                insert_index = insert_index_factory(contribution) if callable(insert_index_factory) else None
                tab_index = self._install_addon_tab(
                    tabs,
                    contribution,
                    widget,
                    insert_index=insert_index,
                    replace_matching_title=replace_matching_title,
                )
                if tab_index < 0:
                    continue
                if callable(on_mounted):
                    on_mounted(contribution, widget, tab_index)
                mounted.add(contribution.id)
                adopted.append(contribution.id)
            except Exception as exc:
                if callable(fallback_factory):
                    try:
                        widget = fallback_factory(contribution, exc)
                        tab_index = self._install_addon_tab(tabs, contribution, widget)
                        if callable(on_mounted):
                            on_mounted(contribution, widget, tab_index)
                        mounted.add(contribution.id)
                        adopted.append(contribution.id)
                        continue
                    except Exception:
                        pass
                print(f"⚠️ [Addons] Failed to mount {log_label} tab '{contribution.id}': {exc}")
        try:
            tabs.setVisible(tabs.count() > 0)
        except Exception:
            pass
        return adopted

    def _mount_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "tabs"):
            return
        top_level_contributions, child_contributions = self._split_addon_parent_child_contributions("top_level")
        for contribution in top_level_contributions:
            if contribution.id in self._mounted_addon_tab_ids:
                continue
            try:
                children = list(child_contributions.get(contribution.id, []))
                widget = self._build_addon_host_tab_widget(contribution, children) if children else contribution.factory(None)
                if widget is None:
                    continue
                self._install_addon_tab(
                    self.tabs,
                    contribution,
                    widget,
                    replace_matching_title=True,
                )
                self._mounted_addon_tab_ids.add(contribution.id)
            except Exception as exc:
                print(f"⚠️ [Addons] Failed to mount tab '{contribution.id}': {exc}")
        for parent_tab_id, children in child_contributions.items():
            if parent_tab_id in self._mounted_addon_tab_ids:
                continue
            child_ids = ", ".join(str(child.id or "") for child in children)
            print(f"⚠️ [Addons] Child tabs {child_ids} declared missing parent '{parent_tab_id}'.")

    def _mount_avatar_tools_addon_tabs(self):
        self._mount_simple_addon_tabs(
            area="avatar_tools",
            tabs_attr="musetalk_tabs",
            mounted_set_attr="_mounted_avatar_tools_addon_tab_ids",
            log_label="Avatar Tools",
        )

    def _mount_host_settings_addon_tabs(self):
        if self._addon_manager is None or not hasattr(self, "host_settings_tabs"):
            return
        top_level_contributions, child_contributions = self._split_addon_parent_child_contributions("host_settings")
        for contribution in top_level_contributions:
            if contribution.id in self._mounted_host_settings_addon_tab_ids:
                continue
            try:
                children = list(child_contributions.get(contribution.id, []))
                widget = self._build_addon_host_tab_widget(contribution, children) if children or getattr(contribution, "metadata", None) else contribution.factory(None)
                if widget is None:
                    continue
                insert_index = min(1 + len(self._mounted_host_settings_addon_tab_ids), self.host_settings_tabs.count())
                self._install_addon_tab(self.host_settings_tabs, contribution, widget, insert_index=insert_index)
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
        def backend_id_for(contribution):
            return str(
                dict(getattr(contribution, "metadata", {}) or {}).get("backend_id")
                or contribution.id
                or contribution.title
                or ""
            ).strip().lower()

        def configure_widget(contribution, widget):
            backend_id = backend_id_for(contribution)
            if backend_id:
                try:
                    widget.setProperty("backend_id", backend_id)
                except Exception:
                    pass

        def on_mounted(contribution, _widget, tab_index):
            backend_id = backend_id_for(contribution)
            if backend_id:
                self._tts_runtime_tab_index_by_backend[backend_id] = tab_index

        self._mount_simple_addon_tabs(
            area="tts_runtime",
            tabs_attr="tts_runtime_addon_tabs",
            mounted_set_attr="_mounted_tts_runtime_addon_tab_ids",
            log_label="TTS runtime",
            configure_widget=configure_widget,
            on_mounted=on_mounted,
            fallback_factory=self._build_tts_runtime_fallback_tab,
        )
        self._refresh_tts_runtime_card()

    def _build_tts_runtime_fallback_tab(self, contribution, exc):
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
        return fallback

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
        self._mount_simple_addon_tabs(
            area="operational_view",
            tabs_attr="right_tabs",
            mounted_set_attr="_mounted_operational_view_addon_tab_ids",
            log_label="operational",
        )
