from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import shiboken6
except Exception:
    shiboken6 = None

from ui.widgets.basic import NoWheelTabWidget

class BackendAddonTabMountMixin:
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
