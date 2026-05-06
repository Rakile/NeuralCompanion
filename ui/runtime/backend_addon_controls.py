from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import shiboken6
except Exception:
    shiboken6 = None

from ui.widgets.basic import NoWheelTabWidget

class BackendAddonControlMixin:
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
