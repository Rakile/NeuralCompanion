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
        self._install_addon_tab_context_menu(tabs)
        self._set_addon_tab_icon(tabs, tab_index, contribution)
        tooltip = str(getattr(contribution, "tooltip", "") or "").strip()
        if tooltip:
            tabs.setTabToolTip(tab_index, tooltip)
        return tab_index

    def _install_addon_tab_context_menu(self, tabs):
        if tabs is None or not hasattr(tabs, "tabBar"):
            return
        try:
            tab_bar = tabs.tabBar()
        except Exception:
            tab_bar = None
        if tab_bar is None:
            return
        try:
            if bool(tab_bar.property("_nc_addon_tab_context_menu_installed")):
                return
            tab_bar.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            tab_bar.customContextMenuRequested.connect(
                lambda pos, tab_widget=tabs: self._show_addon_tab_context_menu(tab_widget, pos)
            )
            tab_bar.setProperty("_nc_addon_tab_context_menu_installed", True)
        except Exception:
            pass

    def _show_addon_tab_context_menu(self, tabs, position):
        if tabs is None or not hasattr(tabs, "tabBar"):
            return
        try:
            tab_bar = tabs.tabBar()
            tab_index = int(tab_bar.tabAt(position))
        except Exception:
            return
        labels = self._addon_tab_context_menu_action_labels(tabs, tab_index)
        if not labels:
            return
        menu = QtWidgets.QMenu(tab_bar)
        for label in labels:
            if label == "Hide tab button":
                action = menu.addAction(label)
                action.triggered.connect(
                    lambda _checked=False, tab_widget=tabs, index=tab_index: self._hide_addon_tab_button_at(
                        tab_widget,
                        index,
                    )
                )
            elif label == "Unhide hidden tab buttons":
                if menu.actions():
                    menu.addSeparator()
                action = menu.addAction(label)
                action.triggered.connect(
                    lambda _checked=False, tab_widget=tabs: self._restore_hidden_addon_tab_buttons(tab_widget)
                )
        try:
            menu.exec(tab_bar.mapToGlobal(position))
        except Exception:
            pass

    def _addon_tab_context_menu_action_labels(self, tabs, tab_index):
        labels = []
        if self._can_hide_addon_tab_button_at(tabs, tab_index):
            labels.append("Hide tab button")
        if self._hidden_addon_tab_indices(tabs):
            labels.append("Unhide hidden tab buttons")
        return labels

    def _is_addon_tab_index(self, tabs, tab_index):
        if tabs is None or not hasattr(tabs, "count"):
            return False
        try:
            index = int(tab_index)
        except Exception:
            return False
        if index < 0 or index >= tabs.count():
            return False
        try:
            widget = tabs.widget(index)
        except Exception:
            widget = None
        if widget is None or not hasattr(widget, "property"):
            return False
        for property_name in ("addon_tab_id", "addon_id"):
            try:
                if str(widget.property(property_name) or "").strip():
                    return True
            except Exception:
                continue
        return False

    def _tab_visible(self, tabs, tab_index):
        try:
            if hasattr(tabs, "isTabVisible"):
                return bool(tabs.isTabVisible(int(tab_index)))
        except Exception:
            pass
        return True

    def _set_tab_visible(self, tabs, tab_index, visible):
        try:
            if hasattr(tabs, "setTabVisible"):
                tabs.setTabVisible(int(tab_index), bool(visible))
                return True
        except Exception:
            pass
        return False

    def _visible_tab_indices(self, tabs):
        if tabs is None or not hasattr(tabs, "count"):
            return []
        visible = []
        for index in range(tabs.count()):
            if self._tab_visible(tabs, index):
                visible.append(index)
        return visible

    def _hidden_addon_tab_indices(self, tabs):
        if tabs is None or not hasattr(tabs, "count"):
            return []
        hidden = []
        for index in range(tabs.count()):
            if self._is_addon_tab_index(tabs, index) and not self._tab_visible(tabs, index):
                hidden.append(index)
        return hidden

    def _can_hide_addon_tab_button_at(self, tabs, tab_index):
        if not self._is_addon_tab_index(tabs, tab_index):
            return False
        if not self._tab_visible(tabs, tab_index):
            return False
        return len(self._visible_tab_indices(tabs)) > 1

    def _hide_addon_tab_button_at(self, tabs, tab_index):
        if not self._can_hide_addon_tab_button_at(tabs, tab_index):
            return False
        try:
            index = int(tab_index)
            current_index = int(tabs.currentIndex())
            if current_index == index:
                replacement = next(
                    (
                        candidate
                        for candidate in self._visible_tab_indices(tabs)
                        if candidate != index and candidate > index
                    ),
                    None,
                )
                if replacement is None:
                    replacement = next(
                        (
                            candidate
                            for candidate in reversed(self._visible_tab_indices(tabs))
                            if candidate != index
                        ),
                        None,
                    )
                if replacement is not None:
                    tabs.setCurrentIndex(int(replacement))
            return self._set_tab_visible(tabs, index, False)
        except Exception:
            return False

    def _restore_hidden_addon_tab_buttons(self, tabs):
        restored = 0
        for index in self._hidden_addon_tab_indices(tabs):
            if self._set_tab_visible(tabs, index, True):
                restored += 1
        return restored

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

        def configure_tabs():
            tabs = getattr(self, "tts_runtime_addon_tabs", None)
            if tabs is None:
                return
            try:
                tabs.setDocumentMode(False)
                tabs.setUsesScrollButtons(True)
                tabs.setElideMode(QtCore.Qt.ElideRight)
                tabs.setMinimumWidth(0)
                tabs_policy = tabs.sizePolicy()
                tabs_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
                tabs.setSizePolicy(tabs_policy)
            except Exception:
                pass
            try:
                tab_bar = tabs.tabBar()
                if tab_bar is not None:
                    tab_bar.setExpanding(False)
                    tab_bar.setUsesScrollButtons(True)
                    tab_bar.setElideMode(QtCore.Qt.ElideRight)
                    tab_bar.setMinimumWidth(0)
                    tab_policy = tab_bar.sizePolicy()
                    tab_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
                    tab_bar.setSizePolicy(tab_policy)
                    for index in range(tabs.count()):
                        label = str(tabs.tabText(index) or "").strip()
                        if label and not str(tabs.tabToolTip(index) or "").strip():
                            tabs.setTabToolTip(index, label)
            except Exception:
                pass
            try:
                existing = str(tabs.styleSheet() or "").strip()
                start = "/* nc-tts-runtime-tabs-label-fit:start */"
                end = "/* nc-tts-runtime-tabs-label-fit:end */"
                if start in existing and end in existing:
                    before, rest = existing.split(start, 1)
                    _old, after = rest.split(end, 1)
                    existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
                style = """
/* nc-tts-runtime-tabs-label-fit:start */
QTabWidget#tts_runtime_addon_tabs QTabBar::tab {
    width: 150px;
    min-width: 150px;
    max-width: 150px;
    min-height: 24px;
    padding: 5px 10px 6px 10px;
    margin-right: 1px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:selected {
    margin-right: 1px;
    padding-bottom: 6px;
}
/* nc-tts-runtime-tabs-label-fit:end */
""".strip()
                next_style = f"{existing}\n{style}".strip() if existing else style
                if str(tabs.styleSheet() or "") != next_style:
                    tabs.setStyleSheet(next_style)
            except Exception:
                pass

        self._mount_simple_addon_tabs(
            area="tts_runtime",
            tabs_attr="tts_runtime_addon_tabs",
            mounted_set_attr="_mounted_tts_runtime_addon_tab_ids",
            log_label="TTS runtime",
            configure_widget=configure_widget,
            on_mounted=on_mounted,
            fallback_factory=self._build_tts_runtime_fallback_tab,
        )
        configure_tabs()
        self._refresh_tts_runtime_card()

    def _mount_visual_reply_runtime_card(self):
        runtime_box = getattr(self, "visual_reply_runtime_box", None)
        host = getattr(self, "visual_reply_runtime_host", None)
        if self._addon_manager is None or runtime_box is None or host is None:
            if runtime_box is not None:
                try:
                    runtime_box.setVisible(False)
                except Exception:
                    pass
            return None

        contribution = None
        for candidate in list(self._addon_manager.get_tab_contributions(area="visual_reply_runtime") or []):
            metadata = dict(getattr(candidate, "metadata", {}) or {})
            if metadata.get("runtime_role") == "visual_reply" or str(getattr(candidate, "id", "") or "") == "visuals_host":
                contribution = candidate
                break

        if contribution is None:
            try:
                runtime_box.setVisible(False)
            except Exception:
                pass
            return None

        if contribution.id in self._mounted_host_settings_addon_tab_ids:
            try:
                runtime_box.setVisible(True)
            except Exception:
                pass
            return contribution.id

        layout = host.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

        try:
            placeholder = getattr(self, "visual_reply_runtime_placeholder", None)
            if placeholder is not None:
                placeholder.setParent(None)
                placeholder.deleteLater()
            widget = contribution.factory(None)
            if widget is None:
                raise RuntimeError("Visual Reply runtime contribution returned no widget.")
            try:
                widget.setProperty("addon_id", getattr(contribution, "addon_id", ""))
                widget.setProperty("addon_tab_id", getattr(contribution, "id", ""))
                widget.setProperty("addon_area", "visual_reply_runtime")
            except Exception:
                pass
            layout.addWidget(widget)
            self._mounted_host_settings_addon_tab_ids.add(contribution.id)
            try:
                runtime_box.setVisible(True)
            except Exception:
                pass
            try:
                self._refresh_visual_reply_hint()
            except Exception:
                pass
            return contribution.id
        except Exception as exc:
            print(f"⚠️ [Addons] Failed to mount Visual Reply runtime card: {exc}")
            try:
                runtime_box.setVisible(False)
            except Exception:
                pass
            return None

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

        if callable(getattr(self, "frontend_layout_resync_callback", None)):
            return

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
