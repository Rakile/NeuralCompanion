from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import LabeledSlider, NoWheelComboBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    # Imported lazily because qt_app imports this mixin before it imports engine.
    from ui.runtime import engine_access as engine

    return engine.RUNTIME_CONFIG

class BackendWorkspaceFocusMixin:
    def _avatar_tools_tabs(self):
        return getattr(self, "musetalk_tabs", None)

    def _current_ui_focus_path(self):
        path = []
        top_title = ""
        if hasattr(self, "tabs"):
            top_index = self.tabs.currentIndex()
            if top_index >= 0:
                top_title = str(self.tabs.tabText(top_index) or "").strip()
                if top_title:
                    path.append(top_title)
        avatar_tools_tabs = self._avatar_tools_tabs()
        if top_title.lower() == "musetalk" and avatar_tools_tabs is not None:
            nested_index = avatar_tools_tabs.currentIndex()
            if nested_index >= 0:
                nested_title = str(avatar_tools_tabs.tabText(nested_index) or "").strip()
                if nested_title:
                    path.append(nested_title)
        return path

    def _emit_tab_focus_changed_event(self, *, scope, container, previous_title, current_title):
        current_path = self._current_ui_focus_path()
        payload = {
            "scope": str(scope or ""),
            "container": str(container or ""),
            "previous_tab_title": str(previous_title or ""),
            "current_tab_title": str(current_title or ""),
            "current_path": current_path,
        }
        self._publish_addon_event("ui.tab_focus_changed", payload)

    def _on_left_tab_changed(self, index):
        if not hasattr(self, "tabs"):
            return
        current_title = str(self.tabs.tabText(index) or "").strip()
        previous_title = getattr(self, "_last_left_tab_title", "")
        self._last_left_tab_title = current_title
        self._emit_tab_focus_changed_event(
            scope="top_level",
            container="left_tabs",
            previous_title=previous_title,
            current_title=current_title,
        )

    def _on_avatar_tools_tab_changed(self, index):
        avatar_tools_tabs = self._avatar_tools_tabs()
        if avatar_tools_tabs is None:
            return
        current_title = str(avatar_tools_tabs.tabText(index) or "").strip()
        previous_title = getattr(self, "_last_avatar_tools_tab_title", getattr(self, "_last_musetalk_tab_title", ""))
        self._last_avatar_tools_tab_title = current_title
        self._last_musetalk_tab_title = current_title
        self._emit_tab_focus_changed_event(
            scope="nested",
            container="musetalk_tabs",
            previous_title=previous_title,
            current_title=current_title,
        )

    def _on_musetalk_tab_changed(self, index):
        return self._on_avatar_tools_tab_changed(index)

    def _sync_tab_widget_height(self, tabs):
        if tabs is None:
            return
        try:
            tabs.setMinimumHeight(0)
            tabs.setMaximumHeight(16777215)
            tabs.adjustSize()
            tabs.updateGeometry()
            parent = tabs.parentWidget()
            if parent is not None:
                parent.updateGeometry()
        except Exception:
            pass

    def _sync_host_settings_tabs_height(self):
        self._sync_tab_widget_height(getattr(self, "host_settings_tabs", None))
