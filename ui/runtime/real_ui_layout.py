import base64
import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from core.ui_session_schema import group_ui_session, with_flat_ui_settings


def configure_real_ui_layout_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI layout mixin."""
    globals().update(dict(namespace or {}))


class _RuntimeProviderTabBar(QtWidgets.QTabBar):
    """Paint the active runtime tab independently from the currently viewed tab."""

    _ACTIVE_BG = QtGui.QColor("#123626")
    _ACTIVE_BORDER = QtGui.QColor("#2cc985")
    _ACTIVE_TEXT = QtGui.QColor("#f4fffa")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_runtime_value = ""

    def set_active_runtime_value(self, value):
        value = str(value or "").strip().lower()
        if value == self._active_runtime_value:
            return
        self._active_runtime_value = value
        self.update()

    def _is_active_runtime_tab(self, index):
        try:
            value = str(self.tabData(index) or "").strip().lower()
        except Exception:
            value = ""
        return bool(value and value == self._active_runtime_value)

    def sizeHint(self):
        return super().sizeHint()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def paintEvent(self, event):
        painter = QtWidgets.QStylePainter(self)
        for index in range(self.count()):
            option = QtWidgets.QStyleOptionTab()
            self.initStyleOption(option, index)
            if not self._is_active_runtime_tab(index):
                painter.drawControl(QtWidgets.QStyle.CE_TabBarTab, option)
                continue

            rect = option.rect.adjusted(0, 1, -1, 0)
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(rect), 6, 6)
            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.fillPath(path, self._ACTIVE_BG)
            painter.setPen(QtGui.QPen(self._ACTIVE_BORDER, 1))
            painter.drawPath(path)
            painter.restore()

            option.palette.setColor(QtGui.QPalette.ButtonText, self._ACTIVE_TEXT)
            option.palette.setColor(QtGui.QPalette.WindowText, self._ACTIVE_TEXT)
            option.palette.setColor(QtGui.QPalette.Text, self._ACTIVE_TEXT)
            painter.drawControl(QtWidgets.QStyle.CE_TabBarTabLabel, option)


class MainUiRealLayoutMixin:
    """Layout, docking, and collapsible-card helpers for the runtime-backed main.ui bridge."""

    def _ensure_runtime_provider_tab_bar(self, tabs, *, preserve_existing=False):
            if tabs is None:
                return None
            try:
                tab_bar = tabs.tabBar()
            except Exception:
                return None
            if isinstance(tab_bar, _RuntimeProviderTabBar):
                return tab_bar
            try:
                if int(tabs.count()) == 0:
                    tab_bar = _RuntimeProviderTabBar(tabs)
                    tabs.setTabBar(tab_bar)
                    return tab_bar
            except Exception:
                pass
            if not preserve_existing:
                return tab_bar
            try:
                current_index = int(tabs.currentIndex())
            except Exception:
                current_index = 0
            items = []
            try:
                count = int(tabs.count())
            except Exception:
                count = 0
            for index in range(count):
                try:
                    items.append(
                        {
                            "widget": tabs.widget(index),
                            "text": str(tabs.tabText(index) or ""),
                            "icon": tabs.tabIcon(index),
                            "tooltip": str(tabs.tabToolTip(index) or ""),
                            "enabled": bool(tabs.isTabEnabled(index)),
                            "data": tab_bar.tabData(index) if tab_bar is not None else None,
                        }
                    )
                except Exception:
                    pass
            if not items:
                return tab_bar
            blocker = None
            try:
                blocker = QtCore.QSignalBlocker(tabs)
                while tabs.count():
                    tabs.removeTab(0)
                tab_bar = _RuntimeProviderTabBar(tabs)
                tabs.setTabBar(tab_bar)
                for item in items:
                    widget = item.get("widget")
                    if widget is None:
                        continue
                    icon = item.get("icon")
                    text = str(item.get("text") or "")
                    if icon is not None and not icon.isNull():
                        new_index = tabs.addTab(widget, icon, text)
                    else:
                        new_index = tabs.addTab(widget, text)
                    tooltip = str(item.get("tooltip") or "")
                    if tooltip:
                        tabs.setTabToolTip(new_index, tooltip)
                    tabs.setTabEnabled(new_index, bool(item.get("enabled", True)))
                    data = item.get("data")
                    if data is not None:
                        tab_bar.setTabData(new_index, data)
                if tabs.count():
                    tabs.setCurrentIndex(max(0, min(current_index, tabs.count() - 1)))
                return tab_bar
            except Exception:
                return tabs.tabBar()
            finally:
                if blocker is not None:
                    del blocker
            return tab_bar

    def _sync_tts_runtime_tab_backend_data(self, tabs=None):
            tabs = tabs or self._ui("tts_runtime_addon_tabs", QtWidgets.QTabWidget)
            if tabs is None:
                return
            try:
                tab_bar = tabs.tabBar()
            except Exception:
                tab_bar = None
            backend = getattr(self, "backend", None)
            label_to_value = getattr(backend, "_tts_backend_value_from_label", None)
            try:
                count = int(tabs.count())
            except Exception:
                count = 0
            for index in range(count):
                page = tabs.widget(index)
                backend_id = ""
                if page is not None:
                    try:
                        backend_id = str(page.property("backend_id") or "").strip().lower()
                    except Exception:
                        backend_id = ""
                if not backend_id and tab_bar is not None:
                    try:
                        backend_id = str(tab_bar.tabData(index) or "").strip().lower()
                    except Exception:
                        backend_id = ""
                if not backend_id and callable(label_to_value):
                    try:
                        backend_id = str(label_to_value(tabs.tabText(index)) or "").strip().lower()
                    except Exception:
                        backend_id = ""
                if not backend_id:
                    continue
                try:
                    if page is not None:
                        page.setProperty("runtime_value", backend_id)
                except Exception:
                    pass
                try:
                    if tab_bar is not None:
                        tab_bar.setTabData(index, backend_id)
                except Exception:
                    pass

    def _refresh_tts_runtime_active_tab_marker(self):
            tabs = self._ui("tts_runtime_addon_tabs", QtWidgets.QTabWidget)
            combo = self._ui("tts_backend_combo", QtWidgets.QComboBox)
            if tabs is None or combo is None:
                return
            self._sync_tts_runtime_tab_backend_data(tabs)
            self._refresh_runtime_provider_active_tab_marker(tabs, combo)

    def _apply_tts_runtime_tab_shape(self, tabs=None, palette=None):
            tabs = tabs or self._ui("tts_runtime_addon_tabs", QtWidgets.QTabWidget)
            if tabs is None:
                return
            if palette is None:
                try:
                    current_preset = _normalize_app_theme_preset_id(
                        getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
                    )
                    palette = _app_theme_palette(current_preset)
                except Exception:
                    palette = {}
            field_bg = str((palette or {}).get("field_bg") or "#0f141b")
            tab_bg = str((palette or {}).get("tab_bg") or "#17212c")
            tab_hover = str((palette or {}).get("tab_hover_bg") or "#223247")
            border = str((palette or {}).get("surface_border") or "#273342")
            try:
                tabs.setDocumentMode(False)
                tabs.setUsesScrollButtons(True)
                tabs.setElideMode(QtCore.Qt.ElideRight)
                tabs.setMinimumWidth(0)
                tabs_policy = tabs.sizePolicy()
                tabs_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
                tabs.setSizePolicy(tabs_policy)
                tab_bar = self._ensure_runtime_provider_tab_bar(tabs, preserve_existing=True)
                if tab_bar is not None:
                    tab_bar.setExpanding(False)
                    tab_bar.setUsesScrollButtons(True)
                    tab_bar.setElideMode(QtCore.Qt.ElideRight)
                    tab_bar.setMinimumWidth(0)
                    tab_policy = tab_bar.sizePolicy()
                    tab_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
                    tab_bar.setSizePolicy(tab_policy)
                    tab_bar.setMinimumHeight(36)
                    tab_bar.setMaximumHeight(40)
            except Exception:
                pass
            runtime_palette = self._frontend_runtime_group_header_palette(self._ui_object("tts_runtime_box"))
            tab_bg = str(runtime_palette.get("background") or tab_bg)
            tab_checked = str(runtime_palette.get("checked") or tab_bg)
            tab_hover = str(runtime_palette.get("hover") or tab_hover)
            tab_border = str(runtime_palette.get("border") or border)
            tab_text = str(runtime_palette.get("text") or "#f2f5f9")
            style = """
/* nc-tts-runtime-tab-shape:start */
QTabWidget#tts_runtime_addon_tabs::tab-bar {
    left: 0px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar {
    background: FIELD_BG;
    qproperty-expanding: false;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::scroller {
    width: 34px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar QToolButton {
    background: FIELD_BG;
    color: TAB_TEXT;
    border: 1px solid TAB_BORDER;
    border-radius: 4px;
    width: 16px;
    min-width: 16px;
    max-width: 16px;
    padding: 0px;
    margin: 8px 1px 2px 1px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar QToolButton:hover {
    background: TAB_HOVER;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab {
    background: TAB_BG;
    color: TAB_TEXT;
    font-weight: 700;
    border: 1px solid TAB_BORDER;
    width: 118px;
    min-width: 118px;
    max-width: 118px;
    height: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0px 14px;
    margin-left: 0px;
    margin-right: 1px;
    margin-bottom: -1px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:!selected {
    margin-top: 1px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:selected {
    background: TAB_CHECKED;
    border-color: TAB_BORDER;
    border-bottom-color: FIELD_BG;
    margin-right: 1px;
    margin-bottom: -1px;
    padding-bottom: 0px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab:hover {
    background: TAB_HOVER;
}
QTabWidget#tts_runtime_addon_tabs::pane {
    top: -1px;
    background: FIELD_BG;
    border: 1px solid TAB_BORDER;
    border-top-left-radius: 0px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    padding: 8px;
}
QTabWidget#tts_runtime_addon_tabs QStackedWidget {
    padding: 4px;
    background: transparent;
}
/* nc-tts-runtime-tab-shape:end */
""".strip()
            style = (
                style.replace("FIELD_BG", field_bg)
                .replace("TAB_BG", tab_bg)
                .replace("TAB_CHECKED", tab_checked)
                .replace("TAB_HOVER", tab_hover)
                .replace("TAB_BORDER", tab_border)
                .replace("TAB_TEXT", tab_text)
                .replace("BORDER", border)
            )
            try:
                existing = str(tabs.styleSheet() or "").strip()
                start = "/* nc-tts-runtime-tab-shape:start */"
                end = "/* nc-tts-runtime-tab-shape:end */"
                if start in existing and end in existing:
                    before, rest = existing.split(start, 1)
                    _old, after = rest.split(end, 1)
                    existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
                next_style = f"{existing}\n{style}".strip() if existing else style
                if str(tabs.styleSheet() or "") != next_style:
                    tabs.setStyleSheet(next_style)
            except Exception:
                pass
            self._refresh_tts_runtime_active_tab_marker()

    def _apply_runtime_provider_tab_shape(self, tabs=None, palette=None):
            if tabs is None:
                return
            try:
                object_name = str(tabs.objectName() or "").strip()
            except Exception:
                object_name = ""
            if not object_name:
                return
            if palette is None:
                try:
                    current_preset = _normalize_app_theme_preset_id(
                        getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
                    )
                    palette = _app_theme_palette(current_preset)
                except Exception:
                    palette = {}
            field_bg = str((palette or {}).get("field_bg") or "#0f141b")
            tab_bg = str((palette or {}).get("tab_bg") or "#17212c")
            tab_hover = str((palette or {}).get("tab_hover_bg") or "#223247")
            border = str((palette or {}).get("surface_border") or "#273342")
            runtime_box_name = {
                "chat_runtime_provider_tabs": "chat_runtime_box",
                "stt_runtime_backend_tabs": "stt_runtime_box",
                "visual_reply_runtime_provider_tabs": "visual_reply_runtime_box",
            }.get(object_name, "")
            runtime_palette = self._frontend_runtime_group_header_palette(self._ui_object(runtime_box_name)) if runtime_box_name else {}
            tab_bg = str(runtime_palette.get("background") or tab_bg)
            tab_checked = str(runtime_palette.get("checked") or tab_bg)
            tab_hover = str(runtime_palette.get("hover") or tab_hover)
            tab_border = str(runtime_palette.get("border") or border)
            tab_text = str(runtime_palette.get("text") or "#f2f5f9")
            try:
                tabs.setDocumentMode(False)
                tabs.setUsesScrollButtons(True)
                tabs.setElideMode(QtCore.Qt.ElideRight)
                tabs.setMinimumWidth(0)
                tabs_policy = tabs.sizePolicy()
                tabs_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
                tabs.setSizePolicy(tabs_policy)
                tab_bar = self._ensure_runtime_provider_tab_bar(tabs)
                if tab_bar is not None:
                    tab_bar.setExpanding(False)
                    tab_bar.setUsesScrollButtons(True)
                    tab_bar.setElideMode(QtCore.Qt.ElideRight)
                    tab_bar.setMinimumWidth(0)
                    tab_policy = tab_bar.sizePolicy()
                    tab_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
                    tab_bar.setSizePolicy(tab_policy)
                    tab_bar.setMinimumHeight(36)
                    tab_bar.setMaximumHeight(40)
            except Exception:
                pass
            selector = f"QTabWidget#{object_name}"
            marker_id = f"nc-runtime-provider-tab-shape-{object_name}"
            style = """
/* MARKER_ID:start */
SELECTOR::tab-bar {
    left: 0px;
}
SELECTOR QTabBar {
    background: FIELD_BG;
    qproperty-expanding: false;
}
SELECTOR QTabBar::scroller {
    width: 34px;
}
SELECTOR QTabBar QToolButton {
    background: FIELD_BG;
    color: TAB_TEXT;
    border: 1px solid TAB_BORDER;
    border-radius: 4px;
    width: 16px;
    min-width: 16px;
    max-width: 16px;
    padding: 0px;
    margin: 8px 1px 2px 1px;
}
SELECTOR QTabBar QToolButton:hover {
    background: TAB_HOVER;
}
SELECTOR QTabBar::tab {
    background: TAB_BG;
    color: TAB_TEXT;
    font-weight: 700;
    border: 1px solid TAB_BORDER;
    width: 118px;
    min-width: 118px;
    max-width: 118px;
    height: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0px 14px;
    margin-left: 0px;
    margin-right: 1px;
    margin-bottom: -1px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
SELECTOR QTabBar::tab:!selected {
    margin-top: 1px;
}
SELECTOR QTabBar::tab:selected {
    background: TAB_CHECKED;
    border-color: TAB_BORDER;
    border-bottom-color: FIELD_BG;
    margin-right: 1px;
    margin-bottom: -1px;
    padding-bottom: 0px;
}
SELECTOR QTabBar::tab:hover {
    background: TAB_HOVER;
}
SELECTOR::pane {
    top: -1px;
    background: FIELD_BG;
    border: 1px solid TAB_BORDER;
    border-top-left-radius: 0px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    padding: 8px;
}
SELECTOR QStackedWidget {
    padding: 4px;
    background: transparent;
}
/* MARKER_ID:end */
""".strip()
            style = (
                style.replace("FIELD_BG", field_bg)
                .replace("TAB_BG", tab_bg)
                .replace("TAB_CHECKED", tab_checked)
                .replace("TAB_HOVER", tab_hover)
                .replace("TAB_BORDER", tab_border)
                .replace("TAB_TEXT", tab_text)
                .replace("BORDER", border)
                .replace("SELECTOR", selector)
                .replace("MARKER_ID", marker_id)
            )
            try:
                existing = str(tabs.styleSheet() or "").strip()
                start = f"/* {marker_id}:start */"
                end = f"/* {marker_id}:end */"
                if start in existing and end in existing:
                    before, rest = existing.split(start, 1)
                    _old, after = rest.split(end, 1)
                    existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
                next_style = f"{existing}\n{style}".strip() if existing else style
                if str(tabs.styleSheet() or "") != next_style:
                    tabs.setStyleSheet(next_style)
            except Exception:
                pass

    def _normalize_frontend_tts_runtime_layout(self):
            tts_box = self._ui("tts_runtime_box", QtWidgets.QGroupBox)
            tabs = self._ui("tts_runtime_addon_tabs", QtWidgets.QTabWidget)
            hint = self._ui("tts_runtime_hint_label", QtWidgets.QLabel)
            combo = self._ui("tts_backend_combo", QtWidgets.QComboBox)

            if tts_box is not None and tts_box.layout() is not None:
                layout = tts_box.layout()
                try:
                    layout.setAlignment(QtCore.Qt.AlignTop)
                    for index in range(layout.count()):
                        item = layout.itemAt(index)
                        if item is not None:
                            layout.setAlignment(item, QtCore.Qt.AlignTop)
                    for index in range(layout.count()):
                        layout.setStretch(index, 0)
                    layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
                except Exception:
                    pass

            for widget in (combo, hint):
                if widget is None or not hasattr(widget, "sizePolicy"):
                    continue
                try:
                    policy = widget.sizePolicy()
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Maximum)
                    widget.setSizePolicy(policy)
                    widget.setMinimumHeight(0 if widget is hint else widget.minimumHeight())
                    widget.updateGeometry()
                except Exception:
                    pass

            if tabs is None:
                return
            self._apply_tts_runtime_tab_shape(tabs)
            try:
                policy = tabs.sizePolicy()
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Maximum)
                tabs.setSizePolicy(policy)
                tabs.setMinimumHeight(0)
                active_page = tabs.currentWidget()
                if active_page is not None:
                    if active_page.layout() is not None:
                        active_page.layout().invalidate()
                        active_page.layout().activate()
                    active_page.adjustSize()
                    active_page.updateGeometry()
                    wanted = active_page.sizeHint().height() + tabs.tabBar().sizeHint().height() + 44
                    tabs.setMaximumHeight(max(160, min(900, int(wanted))))
                tabs.adjustSize()
                tabs.updateGeometry()
            except Exception:
                pass

    def _fix_system_shaping_scroll_content_size(self):
            if self._normalize_system_shaping_fixed_tab_layout():
                tabs = self._ui("host_settings_tabs", QtWidgets.QTabWidget)
                if tabs is not None:
                    try:
                        tabs.setMinimumHeight(0)
                        tabs.setMaximumHeight(16777215)
                        tabs.updateGeometry()
                    except Exception:
                        pass
                self._normalize_frontend_runtime_section_layouts()
                self._normalize_frontend_tts_runtime_layout()
                return

            scroll = self._ui("system_shaping_scroll", QtWidgets.QScrollArea)
            content = self._ui("system_shaping_content", QtWidgets.QWidget)
            tabs = self._ui("host_settings_tabs", QtWidgets.QTabWidget)
            host_tab = self._ui("host_settings_host_tab", QtWidgets.QWidget)

            chat_box = self._ui("chat_runtime_box", QtWidgets.QGroupBox)
            stt_box = self._ui("stt_runtime_box", QtWidgets.QGroupBox)
            tts_box = self._ui("tts_runtime_box", QtWidgets.QGroupBox)
            visual_reply_box = self._ui("visual_reply_runtime_box", QtWidgets.QGroupBox)
            perf_box = self._ui("performance_guidance_box", QtWidgets.QGroupBox)

            if scroll is not None:
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

            for w in (content, tabs, host_tab, chat_box, stt_box, tts_box, visual_reply_box, perf_box):
                if w is None:
                    continue

                w.setMinimumHeight(0)
                w.setMaximumHeight(16777215)

                policy = w.sizePolicy()
                policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Preferred)
                w.setSizePolicy(policy)

            self._normalize_frontend_runtime_section_layouts()
            self._normalize_frontend_tts_runtime_layout()

            for w in (content, host_tab):
                if w is None or w.layout() is None:
                    continue

                layout = w.layout()
                layout.setSizeConstraint(QtWidgets.QLayout.SetMinAndMaxSize)
                layout.setAlignment(QtCore.Qt.AlignTop)
                layout.invalidate()
                layout.activate()

            if host_tab is not None:
                host_tab.adjustSize()
                host_tab.updateGeometry()

            if tabs is not None:
                page = tabs.currentWidget()
                if page is not None:
                    if page.layout() is not None:
                        page.layout().invalidate()
                        page.layout().activate()

                    page.adjustSize()
                    page.updateGeometry()

                    wanted = (
                            page.sizeHint().height()
                            + tabs.tabBar().sizeHint().height()
                            + 24
                    )

                    tabs.setMinimumHeight(wanted)
                    tabs.setMaximumHeight(16777215)

                tabs.adjustSize()
                tabs.updateGeometry()

            if content is not None:
                content.adjustSize()
                content.updateGeometry()

            if scroll is not None:
                scroll.updateGeometry()
                scroll.viewport().update()

    def _normalize_system_shaping_fixed_tab_layout(self):
            tabs = self._ui("host_settings_tabs", QtWidgets.QTabWidget)
            panel = self._ui("system_shaping_panel", QtWidgets.QWidget)
            if tabs is None or panel is None:
                return False

            self._place_preset_buttons_under_selector()
            self._wrap_host_settings_tab_pages(tabs)
            self._apply_host_settings_tabs_corner_fix(tabs)
            left_tabs = self._ui("left_tabs", QtWidgets.QTabWidget)
            self._apply_host_settings_tabs_corner_fix(left_tabs)
            self._center_icon_sidebar_tabs(tabs)
            self._center_icon_sidebar_tabs(left_tabs)
            self._apply_sensory_feedback_tabs_alignment()
            self._apply_nested_horizontal_tab_facing()

            if bool(tabs.property("_nc_fixed_system_shaping_tabs")):
                return True

            scroll = self._ui("system_shaping_scroll", QtWidgets.QScrollArea)
            content = self._ui("system_shaping_content", QtWidgets.QWidget)
            mic_row = self._ui("micStatusRow", QtWidgets.QWidget)
            operational_content = self._ui("operational_content", QtWidgets.QWidget)
            right_tabs = self._ui("right_tabs", QtWidgets.QTabWidget)
            panel_layout = panel.layout()
            content_layout = content.layout() if content is not None and hasattr(content, "layout") else None
            operational_layout = operational_content.layout() if operational_content is not None and hasattr(operational_content, "layout") else None
            if scroll is None or panel_layout is None or content_layout is None:
                return False

            style = str(scroll.styleSheet() or "").strip()
            if style and not bool(panel.property("_nc_system_shaping_scroll_style_applied")):
                try:
                    existing = str(panel.styleSheet() or "").strip()
                    panel.setStyleSheet(f"{existing}\n{style}".strip() if existing else style)
                    panel.setProperty("_nc_system_shaping_scroll_style_applied", True)
                except Exception:
                    pass

            for widget in (mic_row, tabs):
                if widget is None:
                    continue
                try:
                    content_layout.removeWidget(widget)
                    widget.setParent(operational_content if widget is mic_row and operational_content is not None else panel)
                except Exception:
                    pass

            try:
                panel_layout.removeWidget(scroll)
                scroll.hide()
            except Exception:
                pass

            try:
                panel_layout.setContentsMargins(14, 14, 14, 14)
                panel_layout.setSpacing(12)
                panel_layout.addWidget(tabs, 1)
                if mic_row is not None and operational_layout is not None:
                    insert_index = operational_layout.indexOf(right_tabs) if right_tabs is not None else 1
                    operational_layout.insertWidget(max(0, insert_index), mic_row, 0)
                    operational_layout.setAlignment(mic_row, QtCore.Qt.AlignTop)
            except Exception:
                pass

            try:
                policy = tabs.sizePolicy()
                policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Expanding)
                tabs.setSizePolicy(policy)
                tabs.setMinimumHeight(0)
                tabs.setMaximumHeight(16777215)
                tabs.setProperty("_nc_fixed_system_shaping_tabs", True)
                tabs.updateGeometry()
            except Exception:
                pass
            return True

    def _apply_host_settings_tabs_corner_fix(self, tabs):
            if tabs is None:
                return
            try:
                current_preset = _normalize_app_theme_preset_id(
                    getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
                )
                palette = _app_theme_palette(current_preset)
            except Exception:
                palette = {}
            field_bg = str((palette or {}).get("field_bg") or "#0f141b")
            try:
                if tabs.property("_nc_host_settings_corner_fix_key") == field_bg:
                    return
            except Exception:
                pass
            style = """
/* nc-host-settings-tabs-runtime-style:start */
QTabWidget QTabBar {
    background: FIELD_BG;
}
QTabWidget QTabBar::tab {
    width: 62px;
    height: 54px;
    min-width: 62px;
    max-width: 62px;
    min-height: 54px;
    max-height: 54px;
    padding: 0px;
    text-align: center;
}
QTabWidget#host_settings_tabs QTabBar::tab {
    padding: 0px;
}
QTabWidget#left_tabs QTabBar::tab {
    padding: 0px;
}
QTabWidget QTabBar::tab:selected {
    background: FIELD_BG;
    border-right: 0px;
    margin-right: -1px;
    padding: 0px;
}
QTabWidget#host_settings_tabs QTabBar::tab:selected {
    padding: 0px;
}
QTabWidget::pane {
    background: FIELD_BG;
    border-radius: 0px;
    border-top-left-radius: 0px;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
QTabWidget QStackedWidget,
QTabWidget QScrollArea,
QTabWidget QScrollArea > QWidget,
QTabWidget QScrollArea > QWidget > QWidget {
    border-radius: 0px;
    border-top-left-radius: 0px;
}
/* nc-host-settings-tabs-runtime-style:end */
""".strip()
            try:
                existing = str(tabs.styleSheet() or "").strip()
                start = "/* nc-host-settings-tabs-runtime-style:start */"
                end = "/* nc-host-settings-tabs-runtime-style:end */"
                if start in existing and end in existing:
                    before, rest = existing.split(start, 1)
                    _old, after = rest.split(end, 1)
                    existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
                style = style.replace("FIELD_BG", field_bg)
                next_style = f"{existing}\n{style}".strip() if existing else style
                if str(tabs.styleSheet() or "") != next_style:
                    tabs.setStyleSheet(next_style)
                tabs.setProperty("_nc_host_settings_corner_fix", True)
                tabs.setProperty("_nc_host_settings_corner_fix_key", field_bg)
            except Exception:
                pass

    def _center_icon_sidebar_tabs(self, tabs):
            if tabs is None or not hasattr(tabs, "tabBar"):
                return
            try:
                object_name = str(tabs.objectName() or "")
            except Exception:
                object_name = ""
            if object_name not in {"host_settings_tabs", "left_tabs"}:
                return
            try:
                tab_bar = tabs.tabBar()
            except Exception:
                tab_bar = None
            if tab_bar is None:
                return
            try:
                icon_size = tabs.iconSize()
            except Exception:
                icon_size = QtCore.QSize(35, 35)
            label_size = QtCore.QSize(62, 54)
            host_icon_paths = (
                "ui_icons/side_tabs/host.png",
                "ui_icons/side_tabs/vision.png",
                "ui_icons/side_tabs/chat.png",
                "ui_icons/side_tabs/themes.png",
                "addons/visual_story_settings/ui/icons/story_visuals.png",
                "addons/rag_context/ui/icons/RAG.png",
            )
            for index in range(int(tabs.count())):
                try:
                    existing_button = tab_bar.tabButton(index, QtWidgets.QTabBar.LeftSide)
                    if existing_button is not None and bool(existing_button.property("_nc_centered_sidebar_icon")):
                        continue
                except Exception:
                    pass
                try:
                    existing_button = tab_bar.tabButton(index, QtWidgets.QTabBar.RightSide)
                    if existing_button is not None and bool(existing_button.property("_nc_centered_sidebar_icon")):
                        continue
                except Exception:
                    pass
                try:
                    icon = tabs.tabIcon(index)
                except Exception:
                    icon = QtGui.QIcon()
                if (icon is None or icon.isNull()) and object_name == "host_settings_tabs":
                    try:
                        saved_icon = tabs.property(f"_nc_sidebar_icon_source_{index}")
                        if isinstance(saved_icon, QtGui.QIcon) and not saved_icon.isNull():
                            icon = saved_icon
                    except Exception:
                        pass
                if (icon is None or icon.isNull()) and object_name == "host_settings_tabs" and index < len(host_icon_paths):
                    try:
                        icon_path = Path(host_icon_paths[index])
                        if icon_path.exists():
                            icon = QtGui.QIcon(str(icon_path))
                            if not icon.isNull():
                                tabs.setTabIcon(index, icon)
                    except Exception:
                        pass
                if icon is None or icon.isNull():
                    try:
                        existing_button = tab_bar.tabButton(index, QtWidgets.QTabBar.LeftSide)
                        if existing_button is not None and bool(existing_button.property("_nc_centered_sidebar_icon")):
                            continue
                    except Exception:
                        pass
                    continue
                try:
                    pixmap = icon.pixmap(icon_size)
                except Exception:
                    continue
                label = QtWidgets.QLabel()
                label.setProperty("_nc_centered_sidebar_icon", True)
                label.setFixedSize(label_size)
                label.setAlignment(QtCore.Qt.AlignCenter)
                label.setPixmap(pixmap)
                label.setStyleSheet("QLabel { background: transparent; border: 0px; padding: 0px; margin: 0px; }")
                try:
                    label.setToolTip(str(tabs.tabToolTip(index) or tab_bar.tabData(index) or ""))
                except Exception:
                    pass
                try:
                    tab_bar.setTabButton(index, QtWidgets.QTabBar.LeftSide, None)
                    tab_bar.setTabButton(index, QtWidgets.QTabBar.RightSide, label)
                    if object_name == "host_settings_tabs":
                        tabs.setProperty(f"_nc_sidebar_icon_source_{index}", icon)
                    if object_name in {"host_settings_tabs", "left_tabs"}:
                        tabs.setTabIcon(index, QtGui.QIcon())
                except Exception:
                    label.deleteLater()

    def _apply_sensory_feedback_tabs_alignment(self):
            tabs = self._ui("sensory_feedback_tabs", QtWidgets.QTabWidget)
            if tabs is None:
                return
            try:
                if bool(tabs.property("_nc_sensory_feedback_tabs_alignment_applied")):
                    return
            except Exception:
                pass
            style = """
/* nc-sensory-feedback-tabs-runtime-style:start */
QTabWidget::tab-bar {
    left: 0px;
}
QTabWidget QTabBar::tab:selected {
    border-bottom: 0px;
    margin-bottom: -1px;
    padding-bottom: 11px;
}
/* nc-sensory-feedback-tabs-runtime-style:end */
""".strip()
            try:
                existing = str(tabs.styleSheet() or "").strip()
                start = "/* nc-sensory-feedback-tabs-runtime-style:start */"
                end = "/* nc-sensory-feedback-tabs-runtime-style:end */"
                if start in existing and end in existing:
                    before, rest = existing.split(start, 1)
                    _old, after = rest.split(end, 1)
                    existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
                next_style = f"{existing}\n{style}".strip() if existing else style
                if str(tabs.styleSheet() or "") != next_style:
                    tabs.setStyleSheet(next_style)
                tabs.setProperty("_nc_sensory_feedback_tabs_alignment_applied", True)
            except Exception:
                pass

    def _apply_nested_horizontal_tab_facing(self):
            try:
                current_preset = _normalize_app_theme_preset_id(
                    getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
                )
                palette = _app_theme_palette(current_preset)
            except Exception:
                palette = {}
            field_bg = str((palette or {}).get("field_bg") or "#0f141b")
            tab_bg = str((palette or {}).get("tab_bg") or "#17212c")
            tab_hover = str((palette or {}).get("tab_hover_bg") or "#223247")
            border = str((palette or {}).get("surface_border") or "#273342")
            style_key = (field_bg, tab_bg, tab_hover, border)
            if getattr(self, "_nested_horizontal_tab_facing_style_key", None) == style_key:
                return
            style = """
/* nc-nested-horizontal-tabs-runtime-style:start */
QTabWidget::tab-bar {
    left: 0px;
}
QTabWidget QTabBar {
    background: FIELD_BG;
}
QTabWidget QTabBar::tab {
    background: TAB_BG;
    border: 1px solid BORDER;
    min-width: 96px;
    max-width: 220px;
    min-height: 0px;
    padding: 8px 14px;
    margin-right: 4px;
    margin-bottom: -1px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
QTabWidget QTabBar::tab:!selected {
    margin-top: 3px;
}
QTabWidget QTabBar::tab:selected {
    background: FIELD_BG;
    border-color: BORDER;
    border-bottom-color: FIELD_BG;
    border-right: 1px solid BORDER;
    margin-right: 4px;
    margin-bottom: -1px;
    padding-right: 14px;
    padding-bottom: 11px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}
QTabWidget QTabBar::tab:hover {
    background: TAB_HOVER;
}
QTabWidget::pane {
    top: -1px;
    background: FIELD_BG;
    border: 1px solid BORDER;
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
    padding: 12px 10px 10px 10px;
}
QTabWidget QStackedWidget {
    padding: 8px;
    background: transparent;
}
/* nc-nested-horizontal-tabs-runtime-style:end */
""".strip()
            style = (
                style.replace("FIELD_BG", field_bg)
                .replace("TAB_BG", tab_bg)
                .replace("TAB_HOVER", tab_hover)
                .replace("BORDER", border)
            )
            roots = []
            for name in ("host_settings_tabs", "left_tabs", "sensory_feedback_tabs", "right_tabs"):
                root = self._ui(name, QtWidgets.QTabWidget)
                if root is not None:
                    roots.append(root)
            targets = []
            for root in roots:
                try:
                    targets.append(root)
                    targets.extend(list(root.findChildren(QtWidgets.QTabWidget)))
                except Exception:
                    continue
            seen = set()
            applied_count = 0
            for tabs in targets:
                try:
                    object_name = str(tabs.objectName() or "")
                except Exception:
                    object_name = ""
                if not (
                    object_name in {"right_tabs", "vseeface_tabs", "musetalk_tabs", "tts_runtime_addon_tabs", "vam_setup_tabs"}
                    or object_name.startswith("addon_group_tabs_")
                    or object_name.startswith("vision_source_tabs_")
                ):
                    continue
                ident = id(tabs)
                if ident in seen:
                    continue
                seen.add(ident)
                try:
                    tabs.setTabPosition(QtWidgets.QTabWidget.North)
                    tabs.setTabShape(QtWidgets.QTabWidget.Rounded)
                except Exception:
                    pass
                try:
                    existing = str(tabs.styleSheet() or "").strip()
                    start = "/* nc-nested-horizontal-tabs-runtime-style:start */"
                    end = "/* nc-nested-horizontal-tabs-runtime-style:end */"
                    if start in existing and end in existing:
                        before, rest = existing.split(start, 1)
                        _old, after = rest.split(end, 1)
                        existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
                    next_style = f"{existing}\n{style}".strip() if existing else style
                    if str(tabs.styleSheet() or "") != next_style:
                        tabs.setStyleSheet(next_style)
                    tabs.setProperty("_nc_nested_horizontal_tab_facing", True)
                    applied_count += 1
                except Exception:
                    pass
                if object_name == "tts_runtime_addon_tabs":
                    self._apply_tts_runtime_tab_shape(tabs, palette)
            if applied_count:
                self._nested_horizontal_tab_facing_style_key = style_key

    def _place_preset_buttons_under_selector(self):
            host_tab = self._ui("host_settings_host_tab", QtWidgets.QWidget)
            if host_tab is None or bool(host_tab.property("_nc_preset_buttons_near_selector")):
                return
            host_layout = host_tab.layout()
            if host_layout is None:
                return
            form = host_tab.findChild(QtWidgets.QFormLayout, "hostRuntimeForm")
            button_row = host_tab.findChild(QtWidgets.QHBoxLayout, "presetButtonRow")
            if form is None or button_row is None:
                return

            form_index = -1
            button_index = -1
            for index in range(host_layout.count()):
                item = host_layout.itemAt(index)
                if item is None:
                    continue
                if item.layout() is form:
                    form_index = index
                if item.layout() is button_row:
                    button_index = index
            if form_index < 0 or button_index < 0 or button_index == form_index + 1:
                try:
                    host_tab.setProperty("_nc_preset_buttons_near_selector", True)
                except Exception:
                    pass
                return

            try:
                item = host_layout.takeAt(button_index)
                row_layout = item.layout() if item is not None else button_row
                insert_index = form_index + 1
                if button_index < insert_index:
                    insert_index -= 1
                host_layout.insertLayout(insert_index, row_layout)
                host_layout.invalidate()
                host_layout.activate()
                host_tab.setProperty("_nc_preset_buttons_near_selector", True)
                host_tab.updateGeometry()
            except Exception:
                pass

    def _wrap_host_settings_tab_pages(self, tabs):
            if tabs is None or not hasattr(tabs, "count"):
                return
            current_index = -1
            try:
                current_index = int(tabs.currentIndex())
            except Exception:
                current_index = -1
            index = 0
            while index < tabs.count():
                page = tabs.widget(index)
                if page is None:
                    index += 1
                    continue
                if isinstance(page, QtWidgets.QAbstractScrollArea) and bool(page.property("_nc_host_settings_page_scroll")):
                    index += 1
                    continue

                title = ""
                tooltip = ""
                data = None
                icon = None
                try:
                    title = str(tabs.tabText(index) or "")
                    tooltip = str(tabs.tabToolTip(index) or "")
                    icon = tabs.tabIcon(index)
                    tab_bar = tabs.tabBar()
                    if tab_bar is not None:
                        data = tab_bar.tabData(index)
                except Exception:
                    pass

                scroll = QtWidgets.QScrollArea()
                object_name = str(page.objectName() or f"host_settings_page_{index}").strip()
                scroll.setObjectName(f"{object_name}_scroll")
                scroll.setProperty("_nc_host_settings_page_scroll", True)
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
                scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
                scroll.setStyleSheet("QScrollArea { background: transparent; border: 0; } QScrollArea > QWidget > QWidget { background: transparent; }")
                try:
                    scroll.viewport().setAutoFillBackground(False)
                except Exception:
                    pass

                try:
                    tabs.removeTab(index)
                    page.setParent(None)
                    if hasattr(page, "layout") and page.layout() is not None:
                        page.layout().setAlignment(QtCore.Qt.AlignTop)
                    page.setMinimumHeight(0)
                    scroll.setWidget(page)
                    tabs.insertTab(index, scroll, title)
                    if icon is not None and not icon.isNull():
                        tabs.setTabIcon(index, icon)
                    if tooltip:
                        tabs.setTabToolTip(index, tooltip)
                    tab_bar = tabs.tabBar()
                    if tab_bar is not None and data is not None:
                        tab_bar.setTabData(index, data)
                    self._center_icon_sidebar_tabs(tabs)
                except Exception:
                    try:
                        scroll.deleteLater()
                    except Exception:
                        pass
                index += 1
            if current_index >= 0:
                try:
                    tabs.setCurrentIndex(min(current_index, tabs.count() - 1))
                except Exception:
                    pass

    def _resync_frontend_runtime_cards(self):
            self._frontend_runtime_cards_resync_pending = False
            backend = getattr(self, "backend", None)
            if backend is not None:
                for callback_name in ("_sync_chat_provider_generation_fields_height", "_sync_tts_runtime_fields_height"):
                    callback = getattr(backend, callback_name, None)
                    if callable(callback):
                        try:
                            callback()
                        except Exception:
                            pass
            self._fix_system_shaping_scroll_content_size()

    def _schedule_frontend_runtime_cards_resync(self, delay_ms=40):
            if bool(getattr(self, "_frontend_runtime_cards_resync_pending", False)):
                return
            self._frontend_runtime_cards_resync_pending = True
            try:
                QtCore.QTimer.singleShot(max(0, int(delay_ms or 0)), self._resync_frontend_runtime_cards)
            except Exception:
                self._frontend_runtime_cards_resync_pending = False
                pass

    def _resync_frontend_system_shaping_layout(self):
            self._frontend_system_shaping_resync_pending = False
            self._fix_system_shaping_scroll_content_size()

    def _schedule_frontend_system_shaping_resync(self, delay_ms=40):
            if bool(getattr(self, "_frontend_system_shaping_resync_pending", False)):
                return
            self._frontend_system_shaping_resync_pending = True
            try:
                QtCore.QTimer.singleShot(max(0, int(delay_ms or 0)), self._resync_frontend_system_shaping_layout)
            except Exception:
                self._frontend_system_shaping_resync_pending = False
                pass

    def _fix_sensory_feedback_initial_alignment(self):
            tabs = self._ui("sensory_feedback_tabs", QtWidgets.QTabWidget)
            if tabs is None:
                return
            parent = tabs.parentWidget()
            layout = parent.layout() if parent is not None and hasattr(parent, "layout") else None
            if layout is not None:
                try:
                    # Vertical-only alignment keeps startup from centering the Core tab,
                    # while still letting the tab widget consume the full row width.
                    layout.setAlignment(tabs, QtCore.Qt.AlignTop)
                except Exception:
                    pass
            available_width = 0
            if parent is not None:
                try:
                    margins = layout.contentsMargins() if layout is not None else QtCore.QMargins()
                    available_width = max(0, parent.width() - margins.left() - margins.right())
                except Exception:
                    available_width = 0
            for widget in (tabs, tabs.currentWidget()):
                if widget is None:
                    continue
                try:
                    policy = widget.sizePolicy()
                    policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Preferred)
                    widget.setSizePolicy(policy)
                    if available_width > 0:
                        widget.setMinimumWidth(available_width)
                    widget.setMinimumHeight(0)
                    widget.setMaximumWidth(16777215)
                    widget.adjustSize()
                    widget.updateGeometry()
                except Exception:
                    pass
            try:
                self.backend._sync_tab_widget_height(tabs)
            except Exception:
                pass

    def _fix_workspace_tab_content_layouts(self):
            """Keep sparse workspace tabs packed at the top instead of stretched apart."""
            def widget(name, cls=None):
                return self._ui(name, cls or QtWidgets.QWidget)

            def set_policy(target, *, vertical=QtWidgets.QSizePolicy.Preferred, horizontal=QtWidgets.QSizePolicy.Expanding):
                if target is None or not hasattr(target, "sizePolicy"):
                    return
                try:
                    policy = target.sizePolicy()
                    policy.setHorizontalPolicy(horizontal)
                    policy.setVerticalPolicy(vertical)
                    target.setSizePolicy(policy)
                    target.setMinimumHeight(0)
                    target.updateGeometry()
                except Exception:
                    pass

            def align_layout(name):
                owner = widget(name)
                layout = owner.layout() if owner is not None and hasattr(owner, "layout") else None
                if layout is None:
                    return
                try:
                    layout.setAlignment(QtCore.Qt.AlignTop)
                    layout.invalidate()
                    layout.activate()
                except Exception:
                    pass

            def align_named_layout(owner_name, layout_name):
                owner = widget(owner_name)
                if owner is None:
                    return
                layout = owner.findChild(QtWidgets.QLayout, layout_name)
                if layout is None:
                    return
                try:
                    layout.setAlignment(QtCore.Qt.AlignTop)
                    layout.invalidate()
                    layout.activate()
                except Exception:
                    pass

            for name in (
                "chunking_tab",
                "dry_run_tab",
                "vseeface_tab",
                "body_tab",
                "dynamics_tab",
            ):
                align_layout(name)
                set_policy(widget(name), vertical=QtWidgets.QSizePolicy.Preferred)

            for owner_name, layout_name in (
                ("chunking_tab", "chunkingLayout"),
                ("dry_run_tab", "dryRunLayout"),
                ("vseeface_tab", "vseefaceLayout"),
                ("body_tab", "bodyTabLayout"),
                ("body_tab", "bodyPresetsLayout"),
                ("body_tab", "bodyPoseSlidersSectionLayout"),
                ("dynamics_tab", "dynamicsTabLayout"),
            ):
                align_named_layout(owner_name, layout_name)

            for name in (
                "standard_chunking_box",
                "musetalk_chunking_box",
                "streaming_chunking_box",
                "chunking_profiles_box",
                "performance_profiles_box",
            ):
                box = widget(name, QtWidgets.QGroupBox)
                set_policy(box, vertical=QtWidgets.QSizePolicy.Maximum)

            dry_run_summary = widget("dry_run_summary", QtWidgets.QPlainTextEdit)
            if dry_run_summary is not None:
                set_policy(dry_run_summary, vertical=QtWidgets.QSizePolicy.Preferred)
                try:
                    dry_run_summary.setMinimumHeight(180)
                    dry_run_summary.setMaximumHeight(360)
                except Exception:
                    pass

            vseeface_tabs = widget("vseeface_tabs", QtWidgets.QTabWidget)
            if vseeface_tabs is not None:
                set_policy(vseeface_tabs, vertical=QtWidgets.QSizePolicy.Preferred)
                try:
                    vseeface_tabs.setMinimumHeight(0)
                    vseeface_tabs.setMaximumHeight(720)
                except Exception:
                    pass
                for index in range(vseeface_tabs.count()):
                    page = vseeface_tabs.widget(index)
                    set_policy(page, vertical=QtWidgets.QSizePolicy.Preferred)
                    if page is not None and page.layout() is not None:
                        try:
                            page.layout().setAlignment(QtCore.Qt.AlignTop)
                            page.layout().invalidate()
                            page.layout().activate()
                        except Exception:
                            pass

            for name in (
                "body_combo",
                "emotion_combo",
                "btn_hand_doctor",
                "btn_vseeface_hide_interface",
                "btn_reset_chunking_defaults",
            ):
                set_policy(widget(name), vertical=QtWidgets.QSizePolicy.Maximum)

            for name in ("left_tabs", "vseeface_tabs"):
                tabs = widget(name, QtWidgets.QTabWidget)
                if tabs is None:
                    continue
                try:
                    tabs.adjustSize()
                    tabs.updateGeometry()
                    current = tabs.currentWidget()
                    if current is not None:
                        current.adjustSize()
                        current.updateGeometry()
                except Exception:
                    pass
            self._center_icon_sidebar_tabs(widget("left_tabs", QtWidgets.QTabWidget))
            self._fix_operational_view_content_layouts()

    def _fix_operational_view_content_layouts(self):
            """Mirror shrink-friendly workspace pages for the Designer Operational View."""
            def widget(name, cls=None):
                return self._ui(name, cls or QtWidgets.QWidget)

            operational_dock = self._ui_object("OperationalViewDock")
            is_floating = bool(
                operational_dock is not None
                and isinstance(operational_dock, QtWidgets.QDockWidget)
                and operational_dock.isFloating()
            )
            shrink_horizontal = QtWidgets.QSizePolicy.Expanding if is_floating else QtWidgets.QSizePolicy.Ignored
            fill_vertical = QtWidgets.QSizePolicy.Expanding if is_floating else QtWidgets.QSizePolicy.Ignored
            button_horizontal = QtWidgets.QSizePolicy.Preferred if is_floating else QtWidgets.QSizePolicy.Ignored

            def set_policy(target, *, vertical=QtWidgets.QSizePolicy.Ignored, horizontal=None):
                if target is None or not hasattr(target, "sizePolicy"):
                    return
                try:
                    if horizontal is None:
                        horizontal = shrink_horizontal
                    policy = target.sizePolicy()
                    policy.setHorizontalPolicy(horizontal)
                    policy.setVerticalPolicy(vertical)
                    target.setSizePolicy(policy)
                    target.setMinimumSize(0, 0)
                    target.updateGeometry()
                except Exception:
                    pass

            scroll = widget("operational_scroll", QtWidgets.QScrollArea)
            if scroll is not None:
                try:
                    scroll.setWidgetResizable(True)
                    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
                except Exception:
                    pass

            for name in (
                "operational_view_panel",
                "operational_scroll",
                "operational_content",
                "right_tabs",
                "system_console_tab",
                "chat_runtime_tab",
                "console_edit",
                "chat_edit",
            ):
                set_policy(widget(name), vertical=fill_vertical)

            for name in (
                "pipeline_telemetry_box",
                "micStatusRow",
                "render_ready_bar",
                "preview_playback_bar",
                "input_device_combo",
                "output_device_combo",
            ):
                set_policy(widget(name), vertical=QtWidgets.QSizePolicy.Preferred)

            for name in (
                "btn_regenerate",
                "btn_retry",
                "btn_pause",
                "btn_skip",
                "btn_skip_user",
                "btn_start_engine",
                "btn_stop_engine",
                "btn_reset_chat",
            ):
                set_policy(
                    widget(name, QtWidgets.QPushButton),
                    vertical=QtWidgets.QSizePolicy.Fixed,
                    horizontal=button_horizontal,
                )

            for owner_name, layout_name in (
                ("operational_content", "operationalLayout"),
                ("system_console_tab", "systemConsoleLayout"),
                ("chat_runtime_tab", "chatRuntimeLayout"),
            ):
                owner = widget(owner_name)
                layout = owner.findChild(QtWidgets.QLayout, layout_name) if owner is not None else None
                if layout is None:
                    continue
                try:
                    if layout_name == "operationalLayout":
                        right_tabs = widget("right_tabs", QtWidgets.QTabWidget)
                        for index in range(layout.count()):
                            item = layout.itemAt(index)
                            layout.setStretch(index, 1 if item is not None and item.widget() is right_tabs else 0)
                    layout.invalidate()
                    layout.activate()
                except Exception:
                    pass

    def _load_frontend_session_payload(self):
            if not SESSION_PATH.exists():
                return {}
            try:
                payload = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    return {}
                return with_flat_ui_settings(payload)
            except Exception:
                return {}

    def _write_frontend_session_payload(self, payload):
            try:
                SESSION_PATH.write_text(json.dumps(group_ui_session(payload or {}), indent=4), encoding="utf-8")
            except Exception as exc:
                print(f"[UI Real] Failed to save frontend layout: {exc}")

    def _frontend_dock_layout_snapshot(self):
            docks = {}
            for dock in self.window.findChildren(QtWidgets.QDockWidget):
                object_name = str(dock.objectName() or "").strip()
                if not object_name:
                    continue
                if not self._frontend_dock_addon_enabled(object_name):
                    continue
                geometry = dock.geometry()
                floating_geometry = dock.frameGeometry()
                docks[object_name] = {
                    "visible": bool(dock.isVisible()),
                    "floating": bool(dock.isFloating()),
                    "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                    "floating_geometry": [
                        floating_geometry.x(),
                        floating_geometry.y(),
                        floating_geometry.width(),
                        floating_geometry.height(),
                    ],
                }
            return docks

    def _save_frontend_layout_state(self):
            if not bool(getattr(self, "_frontend_layout_persistence_ready", False)):
                return
            if bool(getattr(self, "_closing", False)):
                return
            if bool(getattr(self, "_session_read_only", False)):
                return
            if bool(getattr(self, "_restoring_frontend_layout", False)):
                return
            if self.window is None:
                return
            if self._frontend_dock_drag_active():
                self._schedule_frontend_layout_save(delay_ms=1200)
                return
            try:
                geometry = self.window.geometry()
                layout_state = {
                    "version": 1,
                    "ui_path": str(self.ui_path),
                    "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                    "window_geometry": base64.b64encode(self.window.saveGeometry().data()).decode("ascii"),
                    "window_state": base64.b64encode(self.window.saveState().data()).decode("ascii"),
                    "docks": self._frontend_dock_layout_snapshot(),
                }
                payload = self._load_frontend_session_payload()
                ui_settings = dict(payload.get("ui") or {})
                layout_settings = dict(ui_settings.get("layout") or {})
                layout_settings["main_ui_real"] = layout_state
                ui_settings["layout"] = layout_settings
                payload["ui"] = ui_settings
                payload.pop(self.FRONTEND_LAYOUT_SESSION_KEY, None)
                self._write_frontend_session_payload(payload)
            except Exception as exc:
                print(f"[UI Real] Failed to capture frontend layout: {exc}")

    def _restore_frontend_layout_state(self):
            payload = self._load_frontend_session_payload()
            layout_state = payload.get(self.FRONTEND_LAYOUT_SESSION_KEY)
            if not isinstance(layout_state, dict):
                return
            self._pending_frontend_layout_state = dict(layout_state)
            self._restoring_frontend_layout = True
            try:
                window_geometry = str(layout_state.get("window_geometry") or "").strip()
                if window_geometry:
                    try:
                        self.window.restoreGeometry(QtCore.QByteArray.fromBase64(window_geometry.encode("ascii")))
                    except Exception:
                        pass
                else:
                    geometry = layout_state.get("geometry")
                    if isinstance(geometry, list) and len(geometry) == 4:
                        try:
                            self.window.setGeometry(*[int(item) for item in geometry])
                        except Exception:
                            pass
                window_state = str(layout_state.get("window_state") or "").strip()
                if window_state:
                    try:
                        self.window.restoreState(QtCore.QByteArray.fromBase64(window_state.encode("ascii")))
                    except Exception:
                        pass
                docks = layout_state.get("docks")
                if isinstance(docks, dict):
                    for object_name, dock_state in docks.items():
                        if not self._frontend_dock_addon_enabled(str(object_name)):
                            dock = self._ui_object(str(object_name))
                            if dock is not None and isinstance(dock, QtWidgets.QDockWidget):
                                try:
                                    dock.hide()
                                except Exception:
                                    pass
                            continue
                        dock = self._ui_object(str(object_name))
                        if dock is None or not isinstance(dock, QtWidgets.QDockWidget) or not isinstance(dock_state, dict):
                            continue
                        try:
                            dock.setFloating(bool(dock_state.get("floating", False)))
                            if dock.isFloating():
                                geometry = dock_state.get("floating_geometry") or dock_state.get("geometry")
                                if isinstance(geometry, list) and len(geometry) == 4:
                                    dock.setGeometry(*[int(item) for item in geometry])
                            dock.setVisible(bool(dock_state.get("visible", True)))
                            if hasattr(self, "_apply_frontend_dock_window_flags"):
                                self._apply_frontend_dock_window_flags(dock)
                            if hasattr(self, "_schedule_frontend_dock_owner_refresh"):
                                self._schedule_frontend_dock_owner_refresh(dock)
                        except Exception:
                            continue
                QtCore.QTimer.singleShot(0, self._ensure_frontend_window_on_screen)
                QtCore.QTimer.singleShot(100, self._ensure_frontend_window_on_screen)
                QtCore.QTimer.singleShot(0, self._restore_frontend_dock_geometry_pass)
                QtCore.QTimer.singleShot(250, self._restore_frontend_dock_geometry_pass)
                QtCore.QTimer.singleShot(900, self._restore_frontend_dock_geometry_pass)
            finally:
                self._restoring_frontend_layout = False

    def _saved_frontend_dock_states(self):
            layout_state = getattr(self, "_pending_frontend_layout_state", None)
            if not isinstance(layout_state, dict):
                payload = self._load_frontend_session_payload()
                layout_state = payload.get(self.FRONTEND_LAYOUT_SESSION_KEY)
            if not isinstance(layout_state, dict):
                return {}
            docks = layout_state.get("docks")
            return docks if isinstance(docks, dict) else {}

    def _restore_frontend_dock_geometry_pass(self):
            docks = self._saved_frontend_dock_states()
            if not docks:
                return
            self._restoring_frontend_layout = True
            try:
                visible_docked = []
                for object_name, dock_state in docks.items():
                    if not self._frontend_dock_addon_enabled(str(object_name)):
                        dock = self._ui_object(str(object_name))
                        if dock is not None and isinstance(dock, QtWidgets.QDockWidget):
                            try:
                                dock.hide()
                            except Exception:
                                pass
                        continue
                    dock = self._ui_object(str(object_name))
                    if dock is None or not isinstance(dock, QtWidgets.QDockWidget) or not isinstance(dock_state, dict):
                        continue
                    try:
                        visible = bool(dock_state.get("visible", True))
                        floating = bool(dock_state.get("floating", False))
                        dock.setVisible(visible)
                        dock.setFloating(floating)
                        if floating:
                            geometry = dock_state.get("floating_geometry") or dock_state.get("geometry")
                            if isinstance(geometry, list) and len(geometry) == 4:
                                dock.setGeometry(*[int(item) for item in geometry])
                        elif visible:
                            visible_docked.append((dock, dock_state))
                        if hasattr(self, "_apply_frontend_dock_window_flags"):
                            self._apply_frontend_dock_window_flags(dock)
                        if hasattr(self, "_schedule_frontend_dock_owner_refresh"):
                            self._schedule_frontend_dock_owner_refresh(dock)
                    except Exception:
                        continue
                self._resize_frontend_docks_from_saved_geometry(visible_docked)
            finally:
                self._restoring_frontend_layout = False

    def _resize_frontend_docks_from_saved_geometry(self, dock_entries):
            if not dock_entries:
                return
            geometry_by_dock = {}
            for dock, dock_state in dock_entries:
                geometry = dock_state.get("geometry")
                if not isinstance(geometry, list) or len(geometry) != 4:
                    continue
                try:
                    x = int(geometry[0])
                    y = int(geometry[1])
                    width = max(1, int(geometry[2]))
                    height = max(1, int(geometry[3]))
                except Exception:
                    continue
                geometry_by_dock[dock] = (x, y, width, height)
            if not geometry_by_dock:
                return

            def tab_group_for(dock):
                group = [dock]
                try:
                    group.extend(self.window.tabifiedDockWidgets(dock))
                except Exception:
                    pass
                return frozenset(item for item in group if item in geometry_by_dock)

            def sane_geometry(item):
                x, y, width, height = item
                return width > 1 and height > 1 and x >= -64 and y >= -64

            tab_groups = {}
            for dock in geometry_by_dock:
                group = tab_group_for(dock)
                if not group:
                    continue
                tab_groups.setdefault(group, []).append(dock)

            representatives = []
            for group, docks in tab_groups.items():
                candidates = [(dock, geometry_by_dock[dock]) for dock in docks]
                sane_candidates = [(dock, geometry) for dock, geometry in candidates if sane_geometry(geometry)]
                if sane_candidates:
                    dock, geometry = sorted(sane_candidates, key=lambda item: (item[1][0], item[1][1]))[0]
                else:
                    dock, geometry = sorted(candidates, key=lambda item: (item[1][0], item[1][1]))[0]
                representatives.append((dock, geometry))

            column_tolerance = 48
            columns = []
            for dock, geometry in sorted(representatives, key=lambda item: (item[1][0], item[1][1])):
                if not sane_geometry(geometry):
                    continue
                x, _y, width, _height = geometry
                matched = None
                for column in columns:
                    if abs(x - column["x"]) <= column_tolerance:
                        matched = column
                        break
                if matched is None:
                    matched = {"x": x, "items": []}
                    columns.append(matched)
                matched["items"].append((dock, geometry))

            horizontal = []
            for column in columns:
                items = sorted(column["items"], key=lambda item: item[1][1])
                if not items:
                    continue
                dock, geometry = items[0]
                horizontal.append((dock, geometry[2]))
            if len(horizontal) >= 2:
                try:
                    self.window.resizeDocks(
                        [dock for dock, _width in horizontal],
                        [width for _dock, width in horizontal],
                        QtCore.Qt.Horizontal,
                    )
                except Exception:
                    pass
            for column in columns:
                vertical = []
                for dock, geometry in sorted(column["items"], key=lambda item: item[1][1]):
                    vertical.append((dock, geometry[3]))
                if len(vertical) >= 2:
                    try:
                        self.window.resizeDocks(
                            [dock for dock, _height in vertical],
                            [height for _dock, height in vertical],
                            QtCore.Qt.Vertical,
                        )
                    except Exception:
                        pass

    def _ensure_frontend_window_on_screen(self):
            if self.window is None:
                return
            screen = self.window.screen() or QtWidgets.QApplication.primaryScreen()
            if screen is None:
                return
            available = screen.availableGeometry()
            frame = self.window.frameGeometry()
            client = self.window.geometry()
            width = min(max(client.width(), 320), max(available.width(), 320))
            height = min(max(client.height(), 240), max(available.height(), 240))
            x = frame.x()
            y = frame.y()
            if x < available.left():
                x = available.left()
            if y < available.top():
                y = available.top()
            if x + width > available.right() + 1:
                x = max(available.left(), available.right() - width + 1)
            if y + height > available.bottom() + 1:
                y = max(available.top(), available.bottom() - height + 1)
            self.window.setGeometry(x, y, width, height)
            self.window.move(x, y)

    def _frontend_dock_drag_active(self):
            try:
                buttons = QtWidgets.QApplication.mouseButtons()
                return bool(buttons & (QtCore.Qt.LeftButton | QtCore.Qt.RightButton | QtCore.Qt.MiddleButton))
            except Exception:
                return False

    def _frontend_dock_for_tab_text(self, tab_text):
            wanted = str(tab_text or "").strip().casefold()
            if not wanted:
                return None
            for dock in self._frontend_workspace_docks():
                try:
                    if dock.isFloating():
                        continue
                    title = str(dock.windowTitle() or dock.objectName() or "").strip().casefold()
                except Exception:
                    continue
                if title == wanted:
                    return dock
            return None

    def _frontend_dock_tabbar_match_count(self, tab_bar):
            if tab_bar is None or not hasattr(tab_bar, "count"):
                return 0
            matched = 0
            try:
                count = int(tab_bar.count())
            except Exception:
                count = 0
            for index in range(count):
                try:
                    if self._frontend_dock_for_tab_text(tab_bar.tabText(index)) is not None:
                        matched += 1
                except Exception:
                    continue
            return matched

    def _event_position(self, event):
            try:
                return event.position().toPoint()
            except Exception:
                try:
                    return event.pos()
                except Exception:
                    return QtCore.QPoint()

    def _event_global_position(self, event):
            try:
                return event.globalPosition().toPoint()
            except Exception:
                try:
                    return event.globalPos()
                except Exception:
                    return QtGui.QCursor.pos()

    def _float_frontend_dock_from_tab_drag(self, dock, global_pos):
            if dock is None:
                return False
            try:
                if dock.isFloating():
                    return False
            except Exception:
                return False
            fallback_dock = None
            try:
                tab_siblings = list(self.window.tabifiedDockWidgets(dock))
            except Exception:
                tab_siblings = []
            for candidate in tab_siblings:
                try:
                    if candidate is dock or candidate.isFloating() or not candidate.isVisible():
                        continue
                    fallback_dock = candidate
                    break
                except Exception:
                    continue
            try:
                size = dock.size()
            except Exception:
                size = QtCore.QSize(420, 320)
            try:
                dock.setFloating(True)
                if callable(getattr(self, "_apply_frontend_dock_window_flags", None)):
                    self._apply_frontend_dock_window_flags(dock)
                if callable(getattr(self, "_schedule_frontend_dock_owner_refresh", None)):
                    self._schedule_frontend_dock_owner_refresh(dock)
                width = max(360, int(size.width() or 420))
                height = max(240, int(size.height() or 320))
                dock.resize(width, height)
                dock.move(max(0, int(global_pos.x()) - min(180, width // 2)), max(0, int(global_pos.y()) - 14))
                if fallback_dock is not None:
                    try:
                        fallback_dock.show()
                        fallback_dock.raise_()
                    except Exception:
                        pass
                dock.show()
                dock.raise_()
                self._schedule_frontend_layout_save(delay_ms=1200)
                if callable(getattr(self, "_schedule_frontend_workspace_dock_tab_refresh", None)):
                    self._schedule_frontend_workspace_dock_tab_refresh()
                QtCore.QTimer.singleShot(900, self._apply_frontend_workspace_view_constraints)
                return True
            except Exception:
                return False

    def _move_frontend_floating_dock_with_tab_drag(self, dock, global_pos):
            if dock is None:
                return False
            try:
                if not dock.isFloating():
                    return False
                size = dock.size()
                width = max(360, int(size.width() or 420))
                dock.move(max(0, int(global_pos.x()) - min(180, width // 2)), max(0, int(global_pos.y()) - 14))
                return True
            except Exception:
                return False

    def _handle_frontend_dock_tab_drag(self, watched, event):
            if event is None or not isinstance(watched, QtWidgets.QTabBar):
                return False
            event_type = event.type()
            if event_type not in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease}:
                return False
            if event_type == QtCore.QEvent.MouseButtonPress:
                try:
                    if event.button() != QtCore.Qt.LeftButton:
                        return False
                except Exception:
                    return False
                if self._frontend_dock_tabbar_match_count(watched) < 2:
                    self._frontend_dock_tab_drag = None
                    return False
                pos = self._event_position(event)
                try:
                    index = watched.tabAt(pos)
                except Exception:
                    index = -1
                if index < 0:
                    self._frontend_dock_tab_drag = None
                    return False
                dock = self._frontend_dock_for_tab_text(watched.tabText(index))
                if dock is None:
                    self._frontend_dock_tab_drag = None
                    return False
                self._frontend_dock_tab_drag = {
                    "tab_bar": watched,
                    "start_pos": pos,
                    "dock": dock,
                    "triggered": False,
                }
                return False
            state = getattr(self, "_frontend_dock_tab_drag", None)
            if not isinstance(state, dict) or state.get("tab_bar") is not watched:
                return False
            if event_type == QtCore.QEvent.MouseButtonRelease:
                self._frontend_dock_tab_drag = None
                return False
            try:
                if not bool(event.buttons() & QtCore.Qt.LeftButton):
                    self._frontend_dock_tab_drag = None
                    return False
            except Exception:
                return False
            if bool(state.get("triggered")):
                self._move_frontend_floating_dock_with_tab_drag(state.get("dock"), self._event_global_position(event))
                return True
            pos = self._event_position(event)
            start = state.get("start_pos") or pos
            delta = pos - start
            distance_squared = int(delta.x() * delta.x() + delta.y() * delta.y())
            try:
                outside_tab_strip = not watched.rect().adjusted(-24, -24, 24, 24).contains(pos)
            except Exception:
                outside_tab_strip = True
            if distance_squared < 80 * 80 or not outside_tab_strip:
                return False
            dock = state.get("dock")
            if self._float_frontend_dock_from_tab_drag(dock, self._event_global_position(event)):
                state["triggered"] = True
                try:
                    event.accept()
                except Exception:
                    pass
                return True
            return False

    def _schedule_frontend_layout_save(self, delay_ms=None):
            if (
                bool(getattr(self, "_session_read_only", False))
                or bool(getattr(self, "_restoring_frontend_layout", False))
                or bool(getattr(self, "_closing", False))
                or not bool(getattr(self, "_frontend_layout_persistence_ready", False))
            ):
                return
            timer = getattr(self, "_frontend_layout_save_timer", None)
            if timer is not None:
                if delay_ms is not None:
                    timer.setInterval(max(650, int(delay_ms)))
                elif self._frontend_dock_drag_active():
                    timer.setInterval(1200)
                else:
                    timer.setInterval(650)
                timer.start()

    def _bind_frontend_layout_persistence_hooks(self):
            for dock in self.window.findChildren(QtWidgets.QDockWidget):
                try:
                    dock.installEventFilter(self)
                except Exception:
                    pass
                for signal_name in ("topLevelChanged", "visibilityChanged", "dockLocationChanged"):
                    signal = getattr(dock, signal_name, None)
                    if signal is None:
                        continue
                    try:
                        signal.connect(lambda *args: self._schedule_frontend_layout_save(delay_ms=1200))
                    except Exception:
                        pass
            self._bind_frontend_workspace_menu_actions()

    def _bind_frontend_workspace_menu_actions(self):
            menu = self.window.findChild(QtWidgets.QMenu, "menuWorkspace")
            if menu is not None:
                try:
                    menu.setTitle("Workspace ▼")
                    self._populate_frontend_workspace_menu(menu)
                    if not bool(menu.property("nc_workspace_menu_populated")):
                        menu.aboutToShow.connect(lambda m=menu: self._populate_frontend_workspace_menu(m))
                        menu.setProperty("nc_workspace_menu_populated", True)
                except Exception:
                    pass
            action_map = {
                "actionShowAllPanels": self.show_all_frontend_workspace_panels,
                "actionResetWorkspaceLayout": self.reset_frontend_workspace_layout,
            }
            for object_name, handler in action_map.items():
                action = self._frontend_workspace_command_action(object_name, handler)
                if action is None:
                    continue

    def _frontend_workspace_command_action(self, object_name, handler=None):
            object_name = str(object_name or "").strip()
            if not object_name:
                return None
            attr_name = f"_frontend_{object_name}"
            action = getattr(self, attr_name, None)
            if action is not None:
                try:
                    action.text()
                except RuntimeError:
                    action = None
                except Exception:
                    pass
            if action is None:
                text = "Show All Panels" if object_name == "actionShowAllPanels" else "Reset Workspace Layout"
                action = QtGui.QAction(text, self.window)
                action.setObjectName(object_name)
            setattr(self, attr_name, action)
            try:
                connected = bool(action.property("nc_workspace_command_connected"))
            except RuntimeError:
                text = "Show All Panels" if object_name == "actionShowAllPanels" else "Reset Workspace Layout"
                action = QtGui.QAction(text, self.window)
                action.setObjectName(object_name)
                setattr(self, attr_name, action)
                connected = False
            except Exception:
                connected = False
            if callable(handler) and not connected:
                try:
                    action.triggered.connect(handler)
                    action.setProperty("nc_workspace_command_connected", True)
                except Exception:
                    pass
            return action

    def _populate_frontend_workspace_menu(self, menu):
            if menu is None:
                return
            show_all_action = self._frontend_workspace_command_action(
                "actionShowAllPanels",
                self.show_all_frontend_workspace_panels,
            )
            reset_action = self._frontend_workspace_command_action(
                "actionResetWorkspaceLayout",
                self.reset_frontend_workspace_layout,
            )
            menu.clear()
            seen = set()
            for object_name, label in (
                ("WorkspaceTabsDock", "Workspace Tabs"),
                ("SystemShapingDock", "System Shaping"),
                ("MuseTalkPreviewDock", "MuseTalk"),
                ("PreviewDock", "MuseTalk"),
                ("OperationalViewDock", "Operational View"),
                ("VisualReplyDock", "Visual Reply"),
            ):
                if object_name in seen or not self._frontend_dock_addon_enabled(object_name):
                    continue
                dock = self._ui_object(object_name)
                if dock is None or not isinstance(dock, QtWidgets.QDockWidget):
                    continue
                try:
                    action = dock.toggleViewAction()
                    if action is None:
                        continue
                    action.setText(label)
                    menu.addAction(action)
                    seen.add(object_name)
                    if label == "MuseTalk":
                        seen.add("MuseTalkPreviewDock")
                        seen.add("PreviewDock")
                except Exception:
                    continue
            if not menu.isEmpty():
                menu.addSeparator()
            for action in (show_all_action, reset_action):
                if action is not None:
                    try:
                        menu.addAction(action)
                    except Exception:
                        pass

    def _frontend_workspace_docks(self):
            names = [
                "SystemShapingDock",
                "WorkspaceTabsDock",
                "OperationalViewDock",
                "MuseTalkPreviewDock",
                "PreviewDock",
            ]
            if self._frontend_dock_addon_enabled("VisualReplyDock"):
                names.append("VisualReplyDock")
            docks = []
            for object_name in names:
                dock = self._ui_object(object_name)
                if dock is not None and isinstance(dock, QtWidgets.QDockWidget):
                    docks.append(dock)
            return docks

    def _frontend_dock_addon_enabled(self, object_name):
            object_name = str(object_name or "").strip()
            if object_name != "VisualReplyDock":
                return True
            checker = getattr(self, "_visual_reply_addon_enabled", None)
            return True if not callable(checker) else bool(checker())

    def _enforce_disabled_frontend_workspace_docks(self):
            if self._frontend_dock_addon_enabled("VisualReplyDock"):
                return
            dock = self._ui_object("VisualReplyDock")
            if dock is None or not isinstance(dock, QtWidgets.QDockWidget):
                return
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
            button = self._ui_object("btn_visual_reply")
            if button is not None:
                try:
                    button.setVisible(False)
                    button.setEnabled(False)
                except Exception:
                    pass

    def _begin_frontend_workspace_layout_operation(self, label):
            if bool(getattr(self, "_frontend_workspace_layout_busy", False)):
                print(f"[UI Real] Ignored {label}; workspace layout is still settling.")
                return False
            self._frontend_workspace_layout_busy = True
            # Dock mutations emit several Qt layout/visibility signals. Keep a
            # short settle window so rapid Reset/Show-All clicks do not stack
            # addDockWidget/tabifyDockWidget operations on top of each other.
            QtCore.QTimer.singleShot(450, self._end_frontend_workspace_layout_operation)
            return True

    def _end_frontend_workspace_layout_operation(self):
            self._frontend_workspace_layout_busy = False

    def _move_frontend_workspace_dock(self, dock, area):
            dock.setFloating(False)
            self.window.addDockWidget(area, dock)
            dock.show()

    def show_all_frontend_workspace_panels(self):
            if not self._begin_frontend_workspace_layout_operation("Show All Panels"):
                return
            for dock in self._frontend_workspace_docks():
                try:
                    dock.show()
                    dock.raise_()
                except Exception:
                    pass
            self._enforce_disabled_frontend_workspace_docks()
            self._apply_frontend_workspace_view_constraints()
            self._schedule_frontend_layout_save()
            print("[UI Real] Workspace panels shown.")

    def reset_frontend_workspace_layout(self):
            if not self._begin_frontend_workspace_layout_operation("Reset Workspace Layout"):
                return
            self._restoring_frontend_layout = True
            try:
                system_dock = self._ui_object("SystemShapingDock")
                workspace_dock = self._ui_object("WorkspaceTabsDock")
                operational_dock = self._ui_object("OperationalViewDock")
                preview_dock = self._ui_object("MuseTalkPreviewDock") or self._ui_object("PreviewDock")
                visual_dock = None
                checker = getattr(self, "_visual_reply_addon_enabled", None)
                if not callable(checker) or bool(checker()):
                    visual_dock = self._ui_object("VisualReplyDock")

                left_docks = [dock for dock in (system_dock, workspace_dock) if isinstance(dock, QtWidgets.QDockWidget)]
                right_docks = [dock for dock in (operational_dock, preview_dock, visual_dock) if isinstance(dock, QtWidgets.QDockWidget)]

                for dock in left_docks:
                    self._move_frontend_workspace_dock(dock, QtCore.Qt.LeftDockWidgetArea)
                for dock in right_docks:
                    self._move_frontend_workspace_dock(dock, QtCore.Qt.RightDockWidgetArea)

                # Avoid forcing tab groups during reset. With Designer-loaded
                # docks and live adopted widgets, rapid re-tabification can
                # crash in Qt's native docking code. Users can still dock/tab
                # panels manually after reset.
                for dock in left_docks + right_docks:
                    try:
                        dock.raise_()
                    except Exception:
                        pass
            finally:
                self._restoring_frontend_layout = False

            self._apply_frontend_workspace_view_constraints()
            self._enforce_disabled_frontend_workspace_docks()
            self._save_frontend_layout_state()
            print("[UI Real] Workspace layout reset.")

    def _bind_frontend_workspace_constraint_hooks(self):
            for object_name in ("SystemShapingDock", "WorkspaceTabsDock", "OperationalViewDock", "PreviewDock", "VisualReplyDock"):
                dock = self._ui_object(object_name)
                if dock is None or not hasattr(dock, "topLevelChanged"):
                    continue
                try:
                    dock.topLevelChanged.connect(lambda _floating: QtCore.QTimer.singleShot(900, self._apply_frontend_workspace_view_constraints))
                except Exception:
                    continue

    def _apply_frontend_workspace_view_constraints(self):
            if self._frontend_dock_drag_active():
                QtCore.QTimer.singleShot(900, self._apply_frontend_workspace_view_constraints)
                return
            self._enforce_disabled_frontend_workspace_docks()
            _apply_workspace_view_constraints(
                self.window,
                extra_widgets=(
                    getattr(self.backend, "embedded_musetalk_preview", None),
                    getattr(self.backend, "visual_reply_panel", None),
                    getattr(self, "_frontend_visual_reply_panel", None),
                ),
            )
            self._fix_operational_view_content_layouts()
            self._refresh_frontend_runtime_group_headers()
            self._enforce_frontend_runtime_collapsed_visibility()

    def _normalize_frontend_chat_runtime_editor_widths(self):
            for object_name in ("chat_provider_combo", "model_combo", "preset_combo"):
                widget = self._ui_object(object_name)
                if widget is None:
                    continue
                try:
                    widget.setMinimumWidth(260 if object_name != "preset_combo" else 320)
                    widget.setMaximumWidth(16777215)
                    if hasattr(widget, "setSizeAdjustPolicy"):
                        widget.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
                    if hasattr(widget, "setMinimumContentsLength"):
                        widget.setMinimumContentsLength(18 if object_name == "chat_provider_combo" else 34)
                except Exception:
                    pass
            for layout_name in ("chat_provider_fields_layout", "chat_provider_generation_fields_layout"):
                layout = self._ui_object(layout_name)
                if layout is None:
                    continue
                try:
                    layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                except Exception:
                    pass

    def _runtime_combo_options(self, combo, fallback_label):
            options = []
            if combo is not None and hasattr(combo, "count"):
                try:
                    count = int(combo.count())
                except Exception:
                    count = 0
                for index in range(count):
                    try:
                        label = str(combo.itemText(index) or "").strip()
                    except Exception:
                        label = ""
                    if not label:
                        continue
                    try:
                        data = combo.itemData(index)
                    except Exception:
                        data = None
                    value = str(data if data is not None else label).strip().lower()
                    options.append((label, value or label.lower()))
            if not options:
                current = ""
                try:
                    current = str(combo.currentText() or "").strip()
                except Exception:
                    current = ""
                label = current or str(fallback_label or "Runtime").strip() or "Runtime"
                options.append((label, label.lower()))
            return options

    def _runtime_combo_current_value(self, combo):
            if combo is None:
                return ""
            try:
                data = combo.currentData()
            except Exception:
                data = None
            if data is not None and str(data).strip():
                return str(data).strip().lower()
            try:
                text = str(combo.currentText() or "").strip()
            except Exception:
                text = ""
            return text.lower()

    def _rebuild_runtime_provider_tabs(self, tabs, options, page_prefix):
            if tabs is None:
                return False
            signature = json.dumps([(label, value) for label, value in list(options or [])], sort_keys=True)
            if str(tabs.property("_nc_runtime_provider_signature") or "") == signature:
                return False
            previous_value = ""
            previous_label = ""
            try:
                previous_index = int(tabs.currentIndex())
                previous_page = tabs.widget(previous_index)
                if previous_page is not None:
                    previous_value = str(previous_page.property("runtime_value") or "").strip().lower()
                previous_label = str(tabs.tabText(previous_index) or "").strip().lower()
            except Exception:
                previous_value = ""
                previous_label = ""
            blocker = None
            try:
                blocker = QtCore.QSignalBlocker(tabs)
                active_content = getattr(tabs, "_nc_runtime_active_content", None)
                if active_content is not None:
                    try:
                        active_content.setParent(None)
                    except Exception:
                        pass
                while tabs.count():
                    page = tabs.widget(0)
                    tabs.removeTab(0)
                    if page is not None:
                        page.deleteLater()
                tab_bar = self._ensure_runtime_provider_tab_bar(tabs)
                for index, (label, value) in enumerate(list(options or [])):
                    page = QtWidgets.QWidget(tabs)
                    safe_value = "".join(ch if ch.isalnum() else "_" for ch in str(value or label).lower()).strip("_") or str(index)
                    runtime_value = str(value or label).strip().lower()
                    page.setObjectName(f"{page_prefix}_{safe_value}_page")
                    page.setProperty("runtime_value", runtime_value)
                    layout = QtWidgets.QVBoxLayout(page)
                    layout.setContentsMargins(0, 0, 0, 0)
                    layout.setSpacing(8)
                    tab_index = tabs.addTab(page, str(label or value or "Runtime"))
                    tabs.setTabToolTip(tab_index, str(label or value or "Runtime"))
                    if tab_bar is not None:
                        tab_bar.setTabData(tab_index, runtime_value)
                tabs.setProperty("_nc_runtime_provider_signature", signature)
                restore_index = -1
                for index in range(tabs.count()):
                    page = tabs.widget(index)
                    try:
                        value = str(page.property("runtime_value") or "").strip().lower()
                    except Exception:
                        value = ""
                    try:
                        label = str(tabs.tabText(index) or "").strip().lower()
                    except Exception:
                        label = ""
                    if (previous_value and value == previous_value) or (previous_label and label == previous_label):
                        restore_index = index
                        break
                if restore_index >= 0:
                    tabs.setCurrentIndex(restore_index)
                return True
            except Exception:
                return False
            finally:
                if blocker is not None:
                    del blocker

    def _runtime_tab_index_for_combo(self, tabs, combo):
            if tabs is None:
                return -1
            current = self._runtime_combo_current_value(combo)
            try:
                count = int(tabs.count())
            except Exception:
                count = 0
            for index in range(count):
                page = tabs.widget(index)
                try:
                    value = str(page.property("runtime_value") or "").strip().lower()
                except Exception:
                    value = ""
                if value and value == current:
                    return index
                try:
                    tab_bar = tabs.tabBar()
                    data = str(tab_bar.tabData(index) or "").strip().lower() if tab_bar is not None else ""
                except Exception:
                    data = ""
                if data and data == current:
                    return index
                try:
                    if str(tabs.tabText(index) or "").strip().lower() == current:
                        return index
                except Exception:
                    pass
            return 0 if count else -1

    def _set_combo_to_runtime_tab_value(self, combo, tabs, tab_index):
            if combo is None or tabs is None:
                return
            page = tabs.widget(tab_index)
            try:
                value = str(page.property("runtime_value") or "").strip().lower() if page is not None else ""
            except Exception:
                value = ""
            if not value:
                return
            try:
                count = int(combo.count())
            except Exception:
                count = 0
            for index in range(count):
                try:
                    data = combo.itemData(index)
                    item_value = str(data if data is not None else combo.itemText(index)).strip().lower()
                except Exception:
                    item_value = ""
                if item_value == value:
                    if combo.currentIndex() != index:
                        combo.setCurrentIndex(index)
                    return

    def _runtime_combo_selection_snapshot(self, combo):
            if combo is None:
                return {}
            snapshot = {}
            try:
                snapshot["index"] = int(combo.currentIndex())
            except Exception:
                snapshot["index"] = -1
            try:
                snapshot["data"] = combo.currentData()
            except Exception:
                snapshot["data"] = None
            try:
                snapshot["text"] = str(combo.currentText() or "").strip()
            except Exception:
                snapshot["text"] = ""
            return snapshot

    def _restore_runtime_combo_selection(self, combo, snapshot):
            if combo is None or not isinstance(snapshot, dict):
                return
            try:
                current_data = combo.currentData() if hasattr(combo, "currentData") else None
                current_text = str(combo.currentText() or "").strip() if hasattr(combo, "currentText") else ""
                if snapshot.get("data") is not None and current_data == snapshot.get("data"):
                    return
                if snapshot.get("data") is None and current_text == str(snapshot.get("text") or "").strip():
                    return
            except Exception:
                pass
            target_index = -1
            data = snapshot.get("data")
            if data is not None and hasattr(combo, "findData"):
                try:
                    target_index = combo.findData(data)
                except Exception:
                    target_index = -1
            text = str(snapshot.get("text") or "").strip()
            if target_index < 0 and text and hasattr(combo, "findText"):
                try:
                    target_index = combo.findText(text)
                except Exception:
                    target_index = -1
            if target_index < 0:
                try:
                    index = int(snapshot.get("index", -1))
                    if 0 <= index < int(combo.count()):
                        target_index = index
                except Exception:
                    target_index = -1
            if target_index < 0:
                return
            try:
                blocker = QtCore.QSignalBlocker(combo)
                combo.setCurrentIndex(target_index)
                del blocker
            except Exception:
                pass

    def _set_frontend_runtime_combo_value(self, combo, value):
            if combo is None:
                return False
            target = "" if value is None else str(value).strip()
            index = -1
            if hasattr(combo, "findData"):
                try:
                    index = combo.findData(target)
                except Exception:
                    index = -1
            if index < 0 and hasattr(combo, "findText"):
                try:
                    index = combo.findText(target)
                except Exception:
                    index = -1
            if index < 0:
                return False
            try:
                blocker = QtCore.QSignalBlocker(combo)
                combo.setCurrentIndex(index)
                del blocker
                return True
            except Exception:
                return False

    def _refresh_frontend_stt_runtime_backend_values(self):
            backend = getattr(self, "backend", None)
            if backend is None:
                return
            editor_getter = getattr(backend, "_current_stt_editor_backend_value", None)
            settings_getter = getattr(backend, "_stt_backend_settings_for", None)
            model_default = getattr(backend, "_stt_backend_default_model_value", None)
            language_default = getattr(backend, "_stt_backend_default_language_value", None)
            if not callable(editor_getter) or not callable(settings_getter):
                return
            try:
                backend_id = str(editor_getter() or "").strip().lower()
                settings = dict(settings_getter(backend_id) or {})
            except Exception:
                return
            try:
                model = str(settings.get("model_size") or (model_default(backend_id) if callable(model_default) else "tiny.en") or "tiny.en").strip()
            except Exception:
                model = "tiny.en"
            try:
                language = settings.get("language")
                if language is None:
                    language = language_default(backend_id) if callable(language_default) else "en"
                language = str(language or "").strip()
            except Exception:
                language = "en"
            self._set_frontend_runtime_combo_value(self._ui_object("stt_model_combo"), model)
            self._set_frontend_runtime_combo_value(self._ui_object("stt_language_combo"), language)

    def _refresh_runtime_provider_active_tab_marker(self, tabs, combo):
            if tabs is None or combo is None:
                return
            active_value = self._runtime_combo_current_value(combo)
            active_index = self._runtime_tab_index_for_combo(tabs, combo)
            try:
                tab_bar = tabs.tabBar()
            except Exception:
                tab_bar = None
            if isinstance(tab_bar, _RuntimeProviderTabBar):
                tab_bar.set_active_runtime_value(active_value)
            try:
                count = int(tabs.count())
            except Exception:
                count = 0
            for index in range(count):
                try:
                    label = str(tabs.tabText(index) or "").strip() or "Runtime"
                    suffix = " (active runtime)" if index == active_index else ""
                    tabs.setTabToolTip(index, f"{label}{suffix}")
                except Exception:
                    pass
                if tab_bar is not None and not isinstance(tab_bar, _RuntimeProviderTabBar):
                    try:
                        color = QtGui.QColor("#2cc985") if index == active_index else QtGui.QColor()
                        tab_bar.setTabTextColor(index, color)
                    except Exception:
                        pass

    def _sync_runtime_provider_tabs_height(self, tabs):
            if tabs is None:
                return
            try:
                object_name = str(tabs.objectName() or "").strip()
            except Exception:
                object_name = ""
            if object_name not in {"chat_runtime_provider_tabs", "visual_reply_runtime_provider_tabs"}:
                return
            try:
                active_page = tabs.currentWidget()
                tab_bar = tabs.tabBar()
                if active_page is None or tab_bar is None:
                    return
                if active_page.layout() is not None:
                    active_page.layout().invalidate()
                    active_page.layout().activate()
                active_page.adjustSize()
                active_page.updateGeometry()
                content_hint = active_page.sizeHint().height()
                wanted = max(180, int(content_hint) + int(tab_bar.sizeHint().height()) + 38)
                tabs.setMinimumHeight(wanted)
                tabs.setMaximumHeight(16777215)
                policy = tabs.sizePolicy()
                policy.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
                tabs.setSizePolicy(policy)
                tabs.updateGeometry()
            except Exception:
                pass

    def _move_runtime_provider_content_to_active_tab(self, tabs, combo, content, select_tab=True, sync_combo_on_tab_change=True):
            if tabs is None or content is None:
                return
            preserve_combo = bool(not select_tab and not sync_combo_on_tab_change)
            preserved_combo = self._runtime_combo_selection_snapshot(combo) if preserve_combo else {}
            active_index = self._runtime_tab_index_for_combo(tabs, combo)
            if active_index < 0:
                return
            if preserve_combo:
                self._runtime_provider_tab_browse_in_progress = True
            try:
                if select_tab and tabs.currentIndex() != active_index:
                    blocker = QtCore.QSignalBlocker(tabs)
                    tabs.setCurrentIndex(active_index)
                    del blocker
            except Exception:
                pass
            if preserve_combo:
                self._restore_runtime_combo_selection(combo, preserved_combo)
                self._refresh_runtime_provider_active_tab_marker(tabs, combo)
            try:
                index = int(tabs.currentIndex())
            except Exception:
                index = active_index
            if index < 0:
                index = active_index
            page = tabs.widget(index)
            if page is None:
                return
            if not select_tab and sync_combo_on_tab_change:
                self._set_combo_to_runtime_tab_value(combo, tabs, index)
            try:
                view_value = str(page.property("runtime_value") or "").strip().lower()
            except Exception:
                view_value = ""
            layout = page.layout()
            if layout is None:
                layout = QtWidgets.QVBoxLayout(page)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(8)
            content_moved = False
            try:
                if content.parentWidget() is not page:
                    layout.addWidget(content)
                    content_moved = True
                if not content.isVisible():
                    content.setVisible(True)
                    content_moved = True
                if content_moved:
                    content.updateGeometry()
                    page.updateGeometry()
                    tabs.updateGeometry()
            except Exception:
                pass
            self._refresh_runtime_provider_active_tab_marker(tabs, combo)
            self._sync_runtime_provider_tabs_height(tabs)
            try:
                object_name = str(tabs.objectName() or "")
                backend = getattr(self, "backend", None)
                if object_name == "chat_runtime_provider_tabs":
                    setter = getattr(backend, "_set_chat_provider_editor_value", None)
                    if callable(setter):
                        setter(view_value)
                elif object_name == "stt_runtime_backend_tabs":
                    setter = getattr(backend, "_set_stt_backend_editor_value", None)
                    if callable(setter):
                        setter(view_value)
                    self._refresh_frontend_stt_runtime_backend_values()
                    self._refresh_frontend_stt_runtime_backend_controls()
                elif object_name == "visual_reply_runtime_provider_tabs":
                    setter = getattr(backend, "_set_visual_reply_view_provider", None)
                    if callable(setter):
                        setter(view_value)
            except Exception:
                pass
            if preserve_combo:
                self._restore_runtime_combo_selection(combo, preserved_combo)
                self._refresh_runtime_provider_active_tab_marker(tabs, combo)

                def _clear_runtime_tab_browse_guard():
                    try:
                        self._restore_runtime_combo_selection(combo, preserved_combo)
                        self._refresh_runtime_provider_active_tab_marker(tabs, combo)
                    finally:
                        self._runtime_provider_tab_browse_in_progress = False

                QtCore.QTimer.singleShot(0, _clear_runtime_tab_browse_guard)

    def _sync_chat_runtime_provider_tabs(self):
            tabs = self._ui_object("chat_runtime_provider_tabs")
            combo = self._ui_object("chat_provider_combo")
            if tabs is None or combo is None:
                return
            options = self._runtime_combo_options(combo, "Chat Provider")
            self._rebuild_runtime_provider_tabs(tabs, options, "chat_runtime_provider")
            self._apply_runtime_provider_tab_shape(tabs)
            if not bool(tabs.property("_nc_runtime_provider_combo_bound")):
                try:
                    tabs.currentChanged.connect(
                        lambda _index=0, tabs=tabs, combo=combo: self._move_runtime_provider_content_to_active_tab(
                            tabs,
                            combo,
                            getattr(tabs, "_nc_runtime_active_content", None),
                            select_tab=False,
                            sync_combo_on_tab_change=False,
                        )
                    )
                    combo.currentIndexChanged.connect(
                        lambda _index=0, tabs=tabs, combo=combo: self._move_runtime_provider_content_to_active_tab(
                            tabs,
                            combo,
                            getattr(tabs, "_nc_runtime_active_content", None),
                            select_tab=True,
                        )
                    )
                    tabs.setProperty("_nc_runtime_provider_combo_bound", True)
                except Exception:
                    pass
            initial_select = not bool(tabs.property("_nc_runtime_provider_initial_selection_done"))
            self._move_runtime_provider_content_to_active_tab(
                tabs,
                combo,
                getattr(tabs, "_nc_runtime_active_content", None),
                select_tab=initial_select,
                sync_combo_on_tab_change=False,
            )
            tabs.setProperty("_nc_runtime_provider_initial_selection_done", True)
            self._refresh_runtime_provider_active_tab_marker(tabs, combo)
            self._sync_runtime_provider_tabs_height(tabs)

    def _refresh_frontend_stt_runtime_backend_controls(self):
            combo = self._ui_object("stt_backend_combo")
            if combo is None:
                return
            backend_id = ""
            backend = getattr(self, "backend", None)
            editor_getter = getattr(backend, "_current_stt_editor_backend_value", None)
            if callable(editor_getter):
                try:
                    backend_id = str(editor_getter() or "").strip().lower()
                except Exception:
                    backend_id = ""
            if not backend_id:
                try:
                    data = combo.currentData()
                    backend_id = str(data if data is not None else combo.currentText() or "").strip().lower()
                except Exception:
                    backend_id = ""
            metadata = {}
            getter = getattr(backend, "_stt_backend_metadata", None)
            if callable(getter):
                try:
                    metadata = dict(getter(backend_id) or {})
                except Exception:
                    metadata = {}
            language_mode = str(metadata.get("language_mode") or "").strip().lower()
            show_model = bool(backend_id and backend_id != "none" and language_mode != "disabled")
            show_language = bool(language_mode == "multilingual")
            state_key = (backend_id, show_model, show_language)
            visibility_matches = True
            for object_name, expected in (
                ("stt_model_label", show_model),
                ("stt_model_combo", show_model),
                ("stt_language_label", show_language),
                ("stt_language_combo", show_language),
            ):
                widget = self._ui_object(object_name)
                if widget is None:
                    continue
                try:
                    if bool(widget.isVisible()) != bool(expected):
                        visibility_matches = False
                        break
                except Exception:
                    visibility_matches = False
                    break
            if getattr(self, "_frontend_stt_runtime_controls_state", None) == state_key and visibility_matches:
                return
            self._frontend_stt_runtime_controls_state = state_key
            changed = False
            for object_name in ("stt_model_label", "stt_model_combo"):
                widget = self._ui_object(object_name)
                if widget is not None:
                    try:
                        if widget.isVisible() != show_model:
                            widget.setVisible(show_model)
                            changed = True
                    except Exception:
                        pass
            for object_name in ("stt_language_label", "stt_language_combo"):
                widget = self._ui_object(object_name)
                if widget is not None:
                    try:
                        if widget.isVisible() != show_language:
                            widget.setVisible(show_language)
                            changed = True
                    except Exception:
                        pass
            if not changed:
                return
            tabs = self._ui_object("stt_runtime_backend_tabs")
            content = self._ui_object("stt_runtime_backend_active_content")
            for widget in (content, tabs):
                if widget is not None:
                    try:
                        widget.updateGeometry()
                    except Exception:
                        pass

    def _sync_stt_runtime_backend_tabs(self):
            tabs = self._ui_object("stt_runtime_backend_tabs")
            combo = self._ui_object("stt_backend_combo")
            if tabs is None or combo is None:
                return
            options = self._runtime_combo_options(combo, "STT Backend")
            self._rebuild_runtime_provider_tabs(tabs, options, "stt_runtime_backend")
            self._apply_runtime_provider_tab_shape(tabs)
            if not bool(tabs.property("_nc_runtime_backend_combo_bound")):
                try:
                    tabs.currentChanged.connect(
                        lambda _index=0, tabs=tabs, combo=combo: self._move_runtime_provider_content_to_active_tab(
                            tabs,
                            combo,
                            getattr(tabs, "_nc_runtime_active_content", None),
                            select_tab=False,
                            sync_combo_on_tab_change=False,
                        )
                    )
                    combo.currentIndexChanged.connect(
                        lambda _index=0, tabs=tabs, combo=combo: self._move_runtime_provider_content_to_active_tab(
                            tabs,
                            combo,
                            getattr(tabs, "_nc_runtime_active_content", None),
                            select_tab=True,
                        )
                    )
                    tabs.setProperty("_nc_runtime_backend_combo_bound", True)
                except Exception:
                    pass
            initial_select = not bool(tabs.property("_nc_runtime_provider_initial_selection_done"))
            self._move_runtime_provider_content_to_active_tab(
                tabs,
                combo,
                getattr(tabs, "_nc_runtime_active_content", None),
                select_tab=initial_select,
                sync_combo_on_tab_change=False,
            )
            tabs.setProperty("_nc_runtime_provider_initial_selection_done", True)
            self._refresh_runtime_provider_active_tab_marker(tabs, combo)
            self._refresh_frontend_stt_runtime_backend_controls()

    def _browse_visual_reply_runtime_provider_tab(self, tabs, combo, tab_index):
            if tabs is None:
                return
            try:
                index = int(tab_index)
            except Exception:
                index = -1
            if index < 0:
                return
            page = tabs.widget(index)
            content = getattr(tabs, "_nc_runtime_active_content", None)
            if page is None or content is None:
                return
            preserved_combo = self._runtime_combo_selection_snapshot(combo)
            self._runtime_provider_tab_browse_in_progress = True
            try:
                layout = page.layout()
                if layout is None:
                    layout = QtWidgets.QVBoxLayout(page)
                    layout.setContentsMargins(0, 0, 0, 0)
                    layout.setSpacing(8)
                if content.parentWidget() is not page:
                    layout.addWidget(content)
                try:
                    content.setVisible(True)
                    content.updateGeometry()
                    page.updateGeometry()
                    tabs.updateGeometry()
                except Exception:
                    pass
                try:
                    view_value = str(page.property("runtime_value") or "").strip().lower()
                except Exception:
                    view_value = ""
                setter = getattr(getattr(self, "backend", None), "_set_visual_reply_view_provider", None)
                if callable(setter):
                    setter(view_value)
                self._restore_runtime_combo_selection(combo, preserved_combo)
                self._refresh_runtime_provider_active_tab_marker(tabs, combo)
                self._sync_runtime_provider_tabs_height(tabs)
            finally:
                def _clear_runtime_tab_browse_guard():
                    try:
                        self._restore_runtime_combo_selection(combo, preserved_combo)
                        self._refresh_runtime_provider_active_tab_marker(tabs, combo)
                    finally:
                        self._runtime_provider_tab_browse_in_progress = False

                QtCore.QTimer.singleShot(0, _clear_runtime_tab_browse_guard)

    def _sync_visual_reply_runtime_provider_tabs(self):
            tabs = self._ui_object("visual_reply_runtime_provider_tabs")
            combo = self._ui_object("visual_reply_provider_combo")
            if tabs is None or combo is None:
                return
            options = self._runtime_combo_options(combo, "Visual Reply Provider")
            self._rebuild_runtime_provider_tabs(tabs, options, "visual_reply_runtime_provider")
            self._apply_runtime_provider_tab_shape(tabs)
            if not bool(tabs.property("_nc_runtime_provider_combo_bound")):
                try:
                    tabs.currentChanged.connect(
                        lambda index=0, tabs=tabs, combo=combo: self._browse_visual_reply_runtime_provider_tab(
                            tabs,
                            combo,
                            index,
                        )
                    )
                    combo.currentIndexChanged.connect(
                        lambda _index=0, tabs=tabs, combo=combo: self._move_runtime_provider_content_to_active_tab(
                            tabs,
                            combo,
                            getattr(tabs, "_nc_runtime_active_content", None),
                            select_tab=True,
                        )
                    )
                    tabs.setProperty("_nc_runtime_provider_combo_bound", True)
                except Exception:
                    pass
            initial_select = not bool(tabs.property("_nc_runtime_provider_initial_selection_done"))
            self._move_runtime_provider_content_to_active_tab(
                tabs,
                combo,
                getattr(tabs, "_nc_runtime_active_content", None),
                select_tab=initial_select,
                sync_combo_on_tab_change=False,
            )
            tabs.setProperty("_nc_runtime_provider_initial_selection_done", True)
            self._refresh_runtime_provider_active_tab_marker(tabs, combo)
            self._sync_runtime_provider_tabs_height(tabs)

    def _clear_form_rows_preserving_widgets(self, form):
            if form is None or not hasattr(form, "rowCount"):
                return
            try:
                preserved_widgets = []
                while form.count() > 0:
                    item = form.takeAt(0)
                    if item is None:
                        continue
                    widget = item.widget()
                    if widget is not None:
                        preserved_widgets.append(widget)
                        widget.setParent(None)
                    child_layout = item.layout()
                    if child_layout is not None:
                        while child_layout.count() > 0:
                            child_item = child_layout.takeAt(0)
                            child_widget = child_item.widget() if child_item is not None else None
                            if child_widget is not None:
                                preserved_widgets.append(child_widget)
                                child_widget.setParent(None)
                setattr(form, "_nc_preserved_widgets", preserved_widgets)
                return
            except Exception:
                pass
            try:
                while form.count() > 0:
                    item = form.takeAt(0)
                    widget = item.widget() if item is not None else None
                    if widget is not None:
                        widget.setParent(None)
            except Exception:
                pass

    def _normalize_frontend_chat_runtime_layout(self):
            form = self._ui_object("chatRuntimeForm")
            if form is None:
                return
            existing_selector = self._ui_object("chat_runtime_selector_row")
            existing_tabs = self._ui_object("chat_runtime_provider_tabs")
            if bool(getattr(form, "_nc_provider_tab_runtime_layout", False)) and existing_selector is not None and existing_tabs is not None:
                self._sync_chat_runtime_provider_tabs()
                return

            def _backend_attr(name):
                try:
                    return getattr(getattr(self, "backend", None), name, None)
                except Exception:
                    return None

            def _fallback_label(key, text):
                label = QtWidgets.QLabel(text)
                label.setObjectName(f"chat_runtime_{key}_fallback_label")
                setattr(form, f"_nc_chat_runtime_{key}_fallback_label", label)
                return label

            provider_label = self._ui_object("chat_provider_label") or _fallback_label("provider", "Chat Provider")
            provider_combo = self._ui_object("chat_provider_combo") or _backend_attr("chat_provider_combo")
            model_label = self._ui_object("model_label") or _fallback_label("model", "LLM Model")
            model_row = self._ui_object("chat_model_row_widget") or _backend_attr("model_row_widget")
            if model_row is None:
                model_combo = self._ui_object("model_combo") or _backend_attr("model_combo")
                refresh_button = self._ui_object("btn_model_refresh") or _backend_attr("btn_model_refresh")
                if model_combo is not None:
                    model_row = QtWidgets.QWidget()
                    model_row.setObjectName("chat_model_row_widget")
                    model_layout = QtWidgets.QHBoxLayout(model_row)
                    model_layout.setContentsMargins(0, 0, 0, 0)
                    model_layout.setSpacing(8)
                    model_layout.addWidget(model_combo, 1)
                    if refresh_button is not None:
                        model_layout.addWidget(refresh_button, 0)
                    setattr(form, "_nc_chat_runtime_model_row_fallback", model_row)
            widgets = {
                "provider_label": provider_label,
                "provider_combo": provider_combo,
                "model_label": model_label,
                "model_row": model_row,
                "vision_label": self._ui_object("model_requires_vision_label"),
                "vision_check": self._ui_object("model_requires_vision_checkbox"),
                "settings_label": self._ui_object("provider_settings_label"),
                "settings_widget": self._ui_object("chat_provider_fields_widget"),
                "generation_label": self._ui_object("provider_generation_label"),
                "generation_widget": self._ui_object("chat_provider_generation_fields_widget"),
            }
            if widgets["provider_combo"] is None or widgets["model_row"] is None:
                return

            self._clear_form_rows_preserving_widgets(form)

            selector = QtWidgets.QWidget()
            selector.setObjectName("chat_runtime_selector_row")
            selector_layout = QtWidgets.QGridLayout(selector)
            selector_layout.setContentsMargins(0, 0, 0, 0)
            selector_layout.setHorizontalSpacing(12)
            selector_layout.setVerticalSpacing(8)
            selector_layout.addWidget(widgets["provider_label"], 0, 0, QtCore.Qt.AlignVCenter)
            selector_layout.addWidget(widgets["provider_combo"], 0, 1)
            selector_layout.setColumnStretch(1, 1)
            for widget in (
                selector,
                widgets["provider_label"],
                widgets["provider_combo"],
            ):
                try:
                    widget.setVisible(True)
                    widget.setEnabled(True)
                except Exception:
                    pass

            hint = self._ui_object("chat_runtime_provider_hint_label")
            if hint is None:
                hint = QtWidgets.QLabel("Choose the active chat provider from the dropdown. Tabs browse provider settings without changing the active runtime.")
                hint.setObjectName("chat_runtime_provider_hint_label")
                hint.setWordWrap(True)
                hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            else:
                try:
                    hint.setText("Choose the active chat provider from the dropdown. Tabs browse provider settings without changing the active runtime.")
                except Exception:
                    pass

            tabs = self._ui_object("chat_runtime_provider_tabs")
            if tabs is None:
                tabs = QtWidgets.QTabWidget()
                tabs.setObjectName("chat_runtime_provider_tabs")
            self._apply_runtime_provider_tab_shape(tabs)

            content = self._ui_object("chat_runtime_provider_active_content")
            if content is None:
                content = QtWidgets.QWidget()
                content.setObjectName("chat_runtime_provider_active_content")
                content_layout = QtWidgets.QVBoxLayout(content)
                content_layout.setContentsMargins(0, 0, 0, 0)
                content_layout.setSpacing(8)
                provider_form = QtWidgets.QFormLayout()
                provider_form.setObjectName("chat_runtime_provider_active_form")
                provider_form.setContentsMargins(0, 0, 0, 0)
                provider_form.setHorizontalSpacing(12)
                provider_form.setVerticalSpacing(8)
                provider_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                content_layout.addLayout(provider_form)
            else:
                provider_form = content.findChild(QtWidgets.QFormLayout, "chat_runtime_provider_active_form")
                if provider_form is None:
                    provider_form = QtWidgets.QFormLayout()
                    provider_form.setObjectName("chat_runtime_provider_active_form")
                    provider_form.setContentsMargins(0, 0, 0, 0)
                    provider_form.setHorizontalSpacing(12)
                    provider_form.setVerticalSpacing(8)
                    provider_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                    if content.layout() is None:
                        content_layout = QtWidgets.QVBoxLayout(content)
                        content_layout.setContentsMargins(0, 0, 0, 0)
                        content_layout.setSpacing(8)
                    content.layout().addLayout(provider_form)
            self._clear_form_rows_preserving_widgets(provider_form)
            provider_form.addRow(widgets["model_label"], widgets["model_row"])
            if widgets["vision_label"] is not None and widgets["vision_check"] is not None:
                provider_form.addRow(widgets["vision_label"], widgets["vision_check"])
            if widgets["settings_label"] is not None and widgets["settings_widget"] is not None:
                provider_form.addRow(widgets["settings_label"], widgets["settings_widget"])
            if widgets["generation_label"] is not None and widgets["generation_widget"] is not None:
                provider_form.addRow(widgets["generation_label"], widgets["generation_widget"])

            try:
                form.setContentsMargins(8, 10, 8, 8)
                form.setHorizontalSpacing(12)
                form.setVerticalSpacing(10)
                form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                form.addRow(selector)
                form.addRow(hint)
                form.addRow(tabs)
                setattr(form, "_nc_provider_tab_runtime_layout", True)
                setattr(form, "_nc_horizontal_runtime_layout", True)
            except Exception:
                pass
            setattr(tabs, "_nc_runtime_active_content", content)
            self._sync_chat_runtime_provider_tabs()

    def _normalize_frontend_stt_runtime_layout(self):
            form = self._ui_object("sttRuntimeForm")
            if form is None:
                return
            existing_tabs = self._ui_object("stt_runtime_backend_tabs")
            if bool(getattr(form, "_nc_provider_tab_runtime_layout", False)) and existing_tabs is not None:
                self._sync_stt_runtime_backend_tabs()
                return
            widgets = {
                "backend_label": self._ui_object("stt_backend_label"),
                "backend_combo": self._ui_object("stt_backend_combo"),
                "model_label": self._ui_object("stt_model_label"),
                "model_combo": self._ui_object("stt_model_combo"),
                "language_label": self._ui_object("stt_language_label"),
                "language_combo": self._ui_object("stt_language_combo"),
            }
            if any(widgets[key] is None for key in ("backend_label", "backend_combo", "model_label", "model_combo")):
                return

            self._clear_form_rows_preserving_widgets(form)

            selector = QtWidgets.QWidget()
            selector.setObjectName("stt_runtime_selector_grid")
            selector_layout = QtWidgets.QGridLayout(selector)
            selector_layout.setContentsMargins(0, 0, 0, 0)
            selector_layout.setHorizontalSpacing(12)
            selector_layout.setVerticalSpacing(8)
            selector_layout.addWidget(widgets["backend_label"], 0, 0, QtCore.Qt.AlignVCenter)
            selector_layout.addWidget(widgets["backend_combo"], 0, 1)
            selector_layout.setColumnStretch(1, 1)

            hint = self._ui_object("stt_runtime_hint_label")
            if hint is not None:
                try:
                    hint.setText("Choose the active STT backend from the dropdown. Tabs browse backend settings without changing the active runtime.")
                except Exception:
                    pass
            tabs = self._ui_object("stt_runtime_backend_tabs")
            if tabs is None:
                tabs = QtWidgets.QTabWidget()
                tabs.setObjectName("stt_runtime_backend_tabs")
            self._apply_runtime_provider_tab_shape(tabs)

            content = self._ui_object("stt_runtime_backend_active_content")
            if content is None:
                content = QtWidgets.QWidget()
                content.setObjectName("stt_runtime_backend_active_content")
                content_layout = QtWidgets.QVBoxLayout(content)
                content_layout.setContentsMargins(0, 0, 0, 0)
                content_layout.setSpacing(8)
                backend_form = QtWidgets.QFormLayout()
                backend_form.setObjectName("stt_runtime_backend_active_form")
                backend_form.setContentsMargins(0, 0, 0, 0)
                backend_form.setHorizontalSpacing(12)
                backend_form.setVerticalSpacing(8)
                backend_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                content_layout.addLayout(backend_form)
            else:
                backend_form = content.findChild(QtWidgets.QFormLayout, "stt_runtime_backend_active_form")
                if backend_form is None:
                    backend_form = QtWidgets.QFormLayout()
                    backend_form.setObjectName("stt_runtime_backend_active_form")
                    backend_form.setContentsMargins(0, 0, 0, 0)
                    backend_form.setHorizontalSpacing(12)
                    backend_form.setVerticalSpacing(8)
                    backend_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                    if content.layout() is None:
                        content_layout = QtWidgets.QVBoxLayout(content)
                        content_layout.setContentsMargins(0, 0, 0, 0)
                        content_layout.setSpacing(8)
                    content.layout().addLayout(backend_form)
            self._clear_form_rows_preserving_widgets(backend_form)
            backend_form.addRow(widgets["model_label"], widgets["model_combo"])
            if widgets["language_label"] is not None and widgets["language_combo"] is not None:
                backend_form.addRow(widgets["language_label"], widgets["language_combo"])

            try:
                form.setContentsMargins(8, 10, 8, 0)
                form.setHorizontalSpacing(12)
                form.setVerticalSpacing(8)
                form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                form.addRow(selector)
                if hint is not None:
                    form.addRow(hint)
                form.addRow(tabs)
                setattr(form, "_nc_provider_tab_runtime_layout", True)
                setattr(form, "_nc_horizontal_runtime_layout", True)
            except Exception:
                pass
            setattr(tabs, "_nc_runtime_active_content", content)
            self._sync_stt_runtime_backend_tabs()

    def _normalize_frontend_visual_reply_runtime_layout(self):
            group = self._ui_object("visual_reply_group")
            if group is None or not hasattr(group, "layout"):
                return
            existing_tabs = self._ui_object("visual_reply_runtime_provider_tabs")
            if bool(getattr(group, "_nc_provider_tab_runtime_layout", False)) and existing_tabs is not None:
                self._sync_visual_reply_runtime_provider_tabs()
                return

            widgets = {
                "mode_label": self._ui_object("visual_reply_mode_label"),
                "mode_combo": self._ui_object("visual_reply_mode_combo"),
                "provider_label": self._ui_object("visual_reply_provider_label"),
                "provider_combo": self._ui_object("visual_reply_provider_combo"),
                "size_label": self._ui_object("visual_reply_size_label"),
                "size_combo": self._ui_object("visual_reply_size_combo"),
                "model_label": self._ui_object("visual_reply_model_label"),
                "model_row": self._ui_object("visual_reply_model_row"),
                "model_edit": self._ui_object("visual_reply_model_edit"),
                "workflow_button": self._ui_object("visual_reply_comfyui_workflow_refresh_button"),
                "api_key_label": self._ui_object("visual_reply_api_key_label"),
                "api_key_edit": self._ui_object("visual_reply_api_key_edit"),
                "cleanup_label": self._ui_object("visual_reply_comfyui_cleanup_label"),
                "cleanup_combo": self._ui_object("visual_reply_comfyui_cleanup_combo"),
                "auto_show": self._ui_object("visual_reply_auto_show_checkbox"),
                "hint": self._ui_object("visual_reply_hint_label") or self._ui_object("visual_reply_hint"),
            }
            if any(widgets[key] is None for key in ("mode_combo", "provider_combo", "size_combo", "model_edit")):
                return

            if widgets["model_row"] is None:
                model_row = QtWidgets.QWidget()
                model_row.setObjectName("visual_reply_model_row")
                model_row_layout = QtWidgets.QHBoxLayout(model_row)
                model_row_layout.setContentsMargins(0, 0, 0, 0)
                model_row_layout.setSpacing(6)
                model_row_layout.addWidget(widgets["model_edit"], 1)
                if widgets["workflow_button"] is not None:
                    model_row_layout.addWidget(widgets["workflow_button"], 0)
                widgets["model_row"] = model_row

            def _clear_layout(layout):
                if layout is None:
                    return
                try:
                    while layout.count():
                        item = layout.takeAt(0)
                        if item is None:
                            continue
                        widget = item.widget()
                        if widget is not None:
                            widget.setParent(None)
                        child_layout = item.layout()
                        if child_layout is not None:
                            _clear_layout(child_layout)
                except Exception:
                    pass

            _clear_layout(self._ui_object("visual_reply_form"))
            group_layout = group.layout()
            _clear_layout(group_layout)

            selector = QtWidgets.QWidget()
            selector.setObjectName("visual_reply_runtime_selector_row")
            selector_layout = QtWidgets.QGridLayout(selector)
            selector_layout.setContentsMargins(0, 0, 0, 0)
            selector_layout.setHorizontalSpacing(12)
            selector_layout.setVerticalSpacing(8)
            if widgets["mode_label"] is not None:
                selector_layout.addWidget(widgets["mode_label"], 0, 0, QtCore.Qt.AlignVCenter)
            selector_layout.addWidget(widgets["mode_combo"], 0, 1)
            if widgets["provider_label"] is not None:
                selector_layout.addWidget(widgets["provider_label"], 0, 2, QtCore.Qt.AlignVCenter)
            selector_layout.addWidget(widgets["provider_combo"], 0, 3)
            selector_layout.setColumnStretch(1, 1)
            selector_layout.setColumnStretch(3, 1)

            tabs = self._ui_object("visual_reply_runtime_provider_tabs")
            if tabs is None:
                tabs = QtWidgets.QTabWidget()
                tabs.setObjectName("visual_reply_runtime_provider_tabs")
            self._apply_runtime_provider_tab_shape(tabs)

            content = self._ui_object("visual_reply_runtime_provider_active_content")
            if content is None:
                content = QtWidgets.QWidget()
                content.setObjectName("visual_reply_runtime_provider_active_content")
                content_layout = QtWidgets.QVBoxLayout(content)
                content_layout.setContentsMargins(0, 0, 0, 0)
                content_layout.setSpacing(8)
                provider_form = QtWidgets.QFormLayout()
                provider_form.setObjectName("visual_reply_runtime_provider_active_form")
                provider_form.setContentsMargins(0, 0, 0, 0)
                provider_form.setHorizontalSpacing(12)
                provider_form.setVerticalSpacing(8)
                provider_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                content_layout.addLayout(provider_form)
            else:
                provider_form = content.findChild(QtWidgets.QFormLayout, "visual_reply_runtime_provider_active_form")
                if provider_form is None:
                    provider_form = QtWidgets.QFormLayout()
                    provider_form.setObjectName("visual_reply_runtime_provider_active_form")
                    provider_form.setContentsMargins(0, 0, 0, 0)
                    provider_form.setHorizontalSpacing(12)
                    provider_form.setVerticalSpacing(8)
                    provider_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                    if content.layout() is None:
                        content_layout = QtWidgets.QVBoxLayout(content)
                        content_layout.setContentsMargins(0, 0, 0, 0)
                        content_layout.setSpacing(8)
                    content.layout().addLayout(provider_form)
            self._clear_form_rows_preserving_widgets(provider_form)
            if widgets["size_label"] is not None:
                provider_form.addRow(widgets["size_label"], widgets["size_combo"])
            if widgets["model_label"] is not None:
                provider_form.addRow(widgets["model_label"], widgets["model_row"])
            if widgets["api_key_label"] is not None and widgets["api_key_edit"] is not None:
                provider_form.addRow(widgets["api_key_label"], widgets["api_key_edit"])
            if widgets["cleanup_label"] is not None and widgets["cleanup_combo"] is not None:
                provider_form.addRow(widgets["cleanup_label"], widgets["cleanup_combo"])
            if widgets["auto_show"] is not None:
                provider_form.addRow(widgets["auto_show"])
            if widgets["hint"] is not None:
                provider_form.addRow(widgets["hint"])

            try:
                group_layout.setContentsMargins(12, 14, 12, 12)
                group_layout.setSpacing(8)
                group_layout.addWidget(selector)
                group_layout.addWidget(tabs)
                setattr(group, "_nc_provider_tab_runtime_layout", True)
                setattr(group, "_nc_horizontal_runtime_layout", True)
            except Exception:
                pass
            setattr(tabs, "_nc_runtime_active_content", content)
            self._sync_visual_reply_runtime_provider_tabs()

    def _normalize_frontend_runtime_section_layouts(self):
            self._normalize_frontend_chat_runtime_layout()
            self._normalize_frontend_stt_runtime_layout()
            self._normalize_frontend_visual_reply_runtime_layout()
            self._normalize_frontend_chat_runtime_editor_widths()

    def _restore_frontend_expanded_runtime_group(self, group_box):
            if group_box is None:
                return
            object_name = str(group_box.objectName() or "").strip()
            if object_name != "stt_runtime_box":
                return
            for child_name in (
                "stt_runtime_selector_grid",
                "stt_backend_label",
                "stt_backend_combo",
                "stt_runtime_hint_label",
            ):
                widget = self._ui_object(child_name)
                if widget is None:
                    continue
                try:
                    widget.setVisible(True)
                    widget.updateGeometry()
                except Exception:
                    pass
            self._refresh_frontend_stt_runtime_backend_controls()
            for layout_name in ("sttRuntimeLayout", "sttRuntimeForm"):
                layout = self._ui_object(layout_name)
                if layout is None:
                    continue
                try:
                    layout.invalidate()
                    layout.activate()
                except Exception:
                    pass

    def _set_runtime_group_header_visible(self, group_box, visible):
            header = getattr(group_box, "_nc_runtime_header_button", None)
            if header is not None and hasattr(header, "setVisible"):
                try:
                    header.setVisible(bool(visible))
                except Exception:
                    pass

    def _set_frontend_runtime_group_geometry_collapsed(self, group_box, collapsed):
            if group_box is None:
                return
            try:
                group_box.setProperty("nc_runtime_collapsed", bool(collapsed))
                group_box.setMinimumHeight(0)
                policy = group_box.sizePolicy()
                if bool(collapsed):
                    group_box.setMaximumHeight(0)
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Fixed)
                else:
                    group_box.setMaximumHeight(16777215)
                    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Preferred)
                group_box.setSizePolicy(policy)
                group_box.updateGeometry()
            except Exception:
                pass

    def _refresh_frontend_runtime_group_region(self, group_box):
            candidates = []
            if group_box is not None:
                candidates.append(group_box)
                parent = group_box.parentWidget()
                if parent is not None:
                    candidates.append(parent)
            for object_name in ("system_shaping_scroll", "system_shaping_content", "SystemShapingDock"):
                widget = self._ui_object(object_name)
                if widget is not None:
                    candidates.append(widget)
                    try:
                        viewport = widget.viewport()
                    except Exception:
                        viewport = None
                    if viewport is not None:
                        candidates.append(viewport)
            seen = set()
            for widget in candidates:
                if widget is None or id(widget) in seen:
                    continue
                seen.add(id(widget))
                try:
                    widget.updateGeometry()
                except Exception:
                    pass
                try:
                    widget.update()
                except Exception:
                    pass
                try:
                    widget.repaint()
                except Exception:
                    pass

    def _frontend_runtime_group_specs(self):
            return (
                ("chat_runtime_box", "Chat Runtime"),
                ("stt_runtime_box", "STT Runtime"),
                ("tts_runtime_box", "TTS Runtime"),
                ("visual_reply_runtime_box", "Visual Reply Runtime"),
            )

    def _runtime_tab_button_name(self, object_name):
            base = str(object_name or "").strip()
            return base.replace("_box", "_tab_button") if base else "runtime_section_tab_button"

    def _runtime_tab_title_parts(self, group_box, fallback_title):
            try:
                title = str(group_box.property("nc_collapsible_base_title") or fallback_title or "").strip()
            except Exception:
                title = str(fallback_title or "").strip()
            try:
                summary = str(group_box.property("nc_collapsible_summary") or "").strip()
            except Exception:
                summary = ""
            title = title or str(fallback_title or "").strip()
            tooltip = f"{title}  -  {summary}" if summary else title
            return title, tooltip

    def _replace_marked_widget_stylesheet(self, widget, start_marker, end_marker, block):
            if widget is None or not hasattr(widget, "styleSheet") or not hasattr(widget, "setStyleSheet"):
                return
            try:
                existing = str(widget.styleSheet() or "").strip()
                if start_marker in existing and end_marker in existing:
                    before, rest = existing.split(start_marker, 1)
                    _old, after = rest.split(end_marker, 1)
                    existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
                next_style = f"{existing}\n{block}".strip() if existing else str(block or "").strip()
                if str(widget.styleSheet() or "") != next_style:
                    widget.setStyleSheet(next_style)
            except Exception:
                pass

    def _style_frontend_runtime_tab_container(self, container):
            if container is None:
                return
            style = """
/* nc-runtime-tabs-container:start */
QWidget#runtime_section_tabs {
    background: transparent;
}
QWidget#runtime_section_tab_bar {
    background: transparent;
}
QStackedWidget#runtime_section_stack {
    background: #0f141b;
    border: 1px solid #273342;
    border-top-left-radius: 0px;
    border-top-right-radius: 10px;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
QWidget#runtime_section_tab_page {
    background: transparent;
}
/* nc-runtime-tabs-container:end */
""".strip()
            self._replace_marked_widget_stylesheet(
                container,
                "/* nc-runtime-tabs-container:start */",
                "/* nc-runtime-tabs-container:end */",
                style,
            )

    def _style_frontend_runtime_tab_button(self, button, group_box):
            if button is None:
                return
            palette = self._frontend_runtime_group_header_palette(group_box)
            try:
                button.setStyleSheet(
                    "QToolButton {"
                    f" color: {palette['text']};"
                    " font-weight: 700;"
                    f" border: 1px solid {palette['border']};"
                    " border-bottom: 1px solid #273342;"
                    f" background: {palette['background']};"
                    " border-top-left-radius: 8px;"
                    " border-top-right-radius: 8px;"
                    " border-bottom-left-radius: 0px;"
                    " border-bottom-right-radius: 0px;"
                    " padding: 8px 14px;"
                    " text-align: center;"
                    "}"
                    f"QToolButton:hover {{ background: {palette['hover']}; }}"
                    f"QToolButton:checked {{ background: {palette['checked']}; border-bottom-color: #0f141b; padding-bottom: 10px; }}"
                )
                button.setMinimumHeight(36)
                button.setMinimumWidth(148)
                button.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
                button.setCursor(QtCore.Qt.PointingHandCursor)
                shadow = button.graphicsEffect()
                if not isinstance(shadow, QtWidgets.QGraphicsDropShadowEffect):
                    shadow = QtWidgets.QGraphicsDropShadowEffect(button)
                    button.setGraphicsEffect(shadow)
                shadow.setBlurRadius(12)
                shadow.setOffset(0, 2)
                shadow.setColor(palette["shadow"])
            except Exception:
                pass

    def _style_frontend_runtime_tab_content_group(self, group_box):
            if group_box is None:
                return
            try:
                object_name = str(group_box.objectName() or "").strip()
            except Exception:
                object_name = ""
            if not object_name:
                return
            style = f"""
/* nc-runtime-tab-content:start */
QGroupBox#{object_name} {{
    margin-top: 0px;
    padding: 0px;
    background: transparent;
    border: 0px;
    border-radius: 0px;
}}
QGroupBox#{object_name}::title {{
    height: 0px;
    margin: 0px;
    padding: 0px;
}}
QGroupBox#{object_name}::indicator {{
    width: 0px;
    height: 0px;
}}
/* nc-runtime-tab-content:end */
""".strip()
            self._replace_marked_widget_stylesheet(
                group_box,
                "/* nc-runtime-tab-content:start */",
                "/* nc-runtime-tab-content:end */",
                style,
            )

    def _hide_existing_frontend_runtime_headers(self, parent_layout=None):
            header_names = (
                "chat_runtime_header_button",
                "stt_runtime_header_button",
                "tts_runtime_header_button",
                "visual_reply_runtime_header_button",
                "runtime_section_header_button",
            )
            for header_name in header_names:
                header = self._ui_object(header_name)
                if header is None:
                    continue
                try:
                    if parent_layout is not None:
                        parent_layout.removeWidget(header)
                except Exception:
                    pass
                try:
                    header.hide()
                    header.setParent(None)
                    header.deleteLater()
                except Exception:
                    pass

    def _update_frontend_runtime_tab_text(self, group_box, fallback_title=None):
            button = getattr(group_box, "_nc_runtime_tab_button", None) if group_box is not None else None
            if button is None:
                return False
            title, tooltip = self._runtime_tab_title_parts(group_box, fallback_title)
            try:
                button.setText(title)
                button.setToolTip(tooltip)
            except Exception:
                pass
            return True

    def _refresh_frontend_runtime_tab_buttons(self):
            buttons = getattr(self, "_frontend_runtime_tab_buttons", None) or {}
            for object_name, fallback_title in self._frontend_runtime_group_specs():
                group_box = self._ui_object(object_name)
                button = buttons.get(object_name) or getattr(group_box, "_nc_runtime_tab_button", None)
                if group_box is None or button is None:
                    continue
                self._update_frontend_runtime_tab_text(group_box, fallback_title)
                self._style_frontend_runtime_tab_button(button, group_box)
                try:
                    button.updateGeometry()
                except Exception:
                    pass

    def _select_frontend_runtime_tab(self, index):
            stack = getattr(self, "_frontend_runtime_tab_stack", None)
            pages = list(getattr(self, "_frontend_runtime_tab_pages", []) or [])
            buttons = dict(getattr(self, "_frontend_runtime_tab_buttons", {}) or {})
            try:
                index = int(index)
            except Exception:
                index = 0
            if stack is None or not pages:
                return
            index = max(0, min(index, len(pages) - 1))
            try:
                stack.setCurrentIndex(index)
            except Exception:
                pass
            for item_index, (object_name, fallback_title) in enumerate(self._frontend_runtime_group_specs()):
                group_box = self._ui_object(object_name)
                button = buttons.get(object_name) or getattr(group_box, "_nc_runtime_tab_button", None)
                if button is not None:
                    try:
                        blocker = QtCore.QSignalBlocker(button)
                        button.setChecked(item_index == index)
                        del blocker
                    except Exception:
                        pass
                if group_box is None:
                    continue
                try:
                    group_box.setVisible(True)
                    group_box.setProperty("nc_collapsible_expanded", True)
                    group_box.setProperty("nc_runtime_collapsed", False)
                    self._set_layout_item_tree_visible(group_box.layout(), True)
                    self._set_frontend_runtime_group_geometry_collapsed(group_box, False)
                    self._restore_frontend_expanded_runtime_group(group_box)
                    group_box.updateGeometry()
                except Exception:
                    pass
            try:
                self._refresh_frontend_runtime_group_region(pages[index])
            except Exception:
                pass

    def _ensure_frontend_runtime_tab_selection(self):
            stack = getattr(self, "_frontend_runtime_tab_stack", None)
            if stack is None:
                return False
            try:
                current = int(stack.currentIndex())
            except Exception:
                current = 0
            self._select_frontend_runtime_tab(current if current >= 0 else 0)
            return True

    def _ensure_frontend_runtime_group_tabs(self):
            specs = self._frontend_runtime_group_specs()
            group_boxes = []
            for object_name, fallback_title in specs:
                group_box = self._ui_object(object_name)
                if group_box is None:
                    return False
                base_title = self._frontend_runtime_group_designer_title(object_name, fallback_title)
                group_boxes.append((object_name, base_title, group_box))

            existing_container = getattr(self, "_frontend_runtime_tab_container", None) or self._ui_object("runtime_section_tabs")
            if existing_container is not None:
                stack = existing_container.findChild(QtWidgets.QStackedWidget, "runtime_section_stack")
                if stack is not None:
                    self._frontend_runtime_tab_container = existing_container
                    self._frontend_runtime_tab_stack = stack
                    self._style_frontend_runtime_tab_container(existing_container)
                    self._refresh_frontend_runtime_tab_buttons()
                    self._ensure_frontend_runtime_tab_selection()
                    return True

            parent_layout = None
            insert_index = -1
            for _object_name, _fallback_title, group_box in group_boxes:
                parent = group_box.parentWidget()
                layout = parent.layout() if parent is not None else None
                if layout is None:
                    continue
                try:
                    index = layout.indexOf(group_box)
                except Exception:
                    index = -1
                if index >= 0:
                    parent_layout = layout
                    insert_index = index if insert_index < 0 else min(insert_index, index)
            if parent_layout is None or insert_index < 0:
                return False

            self._hide_existing_frontend_runtime_headers(parent_layout)

            container = QtWidgets.QWidget()
            container.setObjectName("runtime_section_tabs")
            outer_layout = QtWidgets.QVBoxLayout(container)
            outer_layout.setContentsMargins(0, 0, 0, 0)
            outer_layout.setSpacing(0)

            tab_bar = QtWidgets.QWidget(container)
            tab_bar.setObjectName("runtime_section_tab_bar")
            tab_layout = QtWidgets.QHBoxLayout(tab_bar)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            tab_layout.setSpacing(4)
            outer_layout.addWidget(tab_bar, 0)

            stack = QtWidgets.QStackedWidget(container)
            stack.setObjectName("runtime_section_stack")
            stack.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
            outer_layout.addWidget(stack, 1)

            buttons = {}
            pages = []
            for index, (object_name, fallback_title, group_box) in enumerate(group_boxes):
                button = QtWidgets.QToolButton(tab_bar)
                button.setObjectName(self._runtime_tab_button_name(object_name))
                button.setCheckable(True)
                button.setAutoRaise(False)
                button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
                button.clicked.connect(lambda _checked=False, wanted=index: self._select_frontend_runtime_tab(wanted))
                tab_layout.addWidget(button)
                buttons[object_name] = button
                setattr(group_box, "_nc_runtime_tab_button", button)

                page = QtWidgets.QWidget(stack)
                page.setObjectName("runtime_section_tab_page")
                page_layout = QtWidgets.QVBoxLayout(page)
                page_layout.setContentsMargins(10, 10, 10, 10)
                page_layout.setSpacing(0)

                try:
                    parent_layout.removeWidget(group_box)
                except Exception:
                    pass
                page_layout.addWidget(group_box)
                stack.addWidget(page)
                pages.append(page)

                try:
                    group_box.setCheckable(False)
                    group_box.setChecked(True)
                    group_box.setTitle("")
                    group_box.setProperty("nc_runtime_content_group", True)
                    group_box.setProperty("nc_collapsible_base_title", fallback_title)
                    group_box.setProperty("nc_collapsible_summary", "")
                    group_box.setToolTip("")
                    group_box.setVisible(True)
                    self._set_layout_item_tree_visible(group_box.layout(), True)
                    self._set_frontend_runtime_group_geometry_collapsed(group_box, False)
                    self._style_frontend_runtime_tab_content_group(group_box)
                except Exception:
                    pass

            tab_layout.addStretch(1)
            try:
                parent_layout.insertWidget(insert_index, container)
            except TypeError:
                parent_layout.insertWidget(insert_index, container)

            self._frontend_runtime_tab_container = container
            self._frontend_runtime_tab_stack = stack
            self._frontend_runtime_tab_pages = pages
            self._frontend_runtime_tab_buttons = buttons
            self._style_frontend_runtime_tab_container(container)
            self._refresh_frontend_runtime_tab_buttons()
            self._select_frontend_runtime_tab(0)
            return True

    def _refresh_frontend_runtime_group_headers(self):
            if getattr(self, "_frontend_runtime_tab_container", None) is not None:
                self._refresh_frontend_runtime_tab_buttons()
                return
            for object_name in ("chat_runtime_box", "stt_runtime_box", "tts_runtime_box", "visual_reply_runtime_box"):
                group_box = self._ui_object(object_name)
                header = getattr(group_box, "_nc_runtime_header_button", None) if group_box is not None else None
                if header is None:
                    continue
                try:
                    header.setMinimumSize(260, 34)
                    header.setMaximumWidth(560)
                    header.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
                    uses_default_style = bool(header.property("nc_runtime_header_uses_default_style"))
                    has_designer_style = bool(str(header.styleSheet() if hasattr(header, "styleSheet") else "").strip())
                    if uses_default_style or not has_designer_style:
                        self._style_frontend_runtime_group_header(header, group_box)
                    header.updateGeometry()
                except Exception:
                    pass

    def _frontend_runtime_group_header_palette(self, group_box):
            object_name = str(group_box.objectName() or "").strip() if group_box is not None else ""
            palettes = {
                "chat_runtime_box": {
                    "background": "#21122f",
                    "checked": "#291641",
                    "hover": "#351a55",
                    "border": "#ff3fbf",
                    "text": "#fff7ff",
                    "shadow": QtGui.QColor(255, 63, 191, 75),
                },
                "stt_runtime_box": {
                    "background": "#09283a",
                    "checked": "#0b3148",
                    "hover": "#0d3d59",
                    "border": "#00e5ff",
                    "text": "#f0fdff",
                    "shadow": QtGui.QColor(0, 229, 255, 70),
                },
                "tts_runtime_box": {
                    "background": "#1a1644",
                    "checked": "#211b5d",
                    "hover": "#2a2375",
                    "border": "#8b5cf6",
                    "text": "#fbf8ff",
                    "shadow": QtGui.QColor(139, 92, 246, 75),
                },
                "visual_reply_runtime_box": {
                    "background": "#2d1730",
                    "checked": "#3a1d3d",
                    "hover": "#4a254f",
                    "border": "#ff9f1c",
                    "text": "#fff8ed",
                    "shadow": QtGui.QColor(255, 159, 28, 70),
                },
            }
            return palettes.get(object_name) or {
                "background": "#21122f",
                "checked": "#291641",
                "hover": "#351a55",
                "border": "#ff3fbf",
                "text": "#fff7ff",
                "shadow": QtGui.QColor(255, 63, 191, 75),
            }

    def _style_frontend_runtime_group_header(self, header, group_box):
            if header is None:
                return
            palette = self._frontend_runtime_group_header_palette(group_box)
            try:
                header.setStyleSheet(
                    "QToolButton {"
                    f" color: {palette['text']};"
                    " font-weight: 700;"
                    f" border: 1px solid {palette['border']};"
                    f" background: {palette['background']};"
                    " border-radius: 8px;"
                    " padding: 6px 12px;"
                    " text-align: left;"
                    "}"
                    f"QToolButton:hover {{ background: {palette['hover']}; }}"
                    f"QToolButton:checked {{ background: {palette['checked']}; }}"
                )
            except Exception:
                pass
            try:
                shadow = header.graphicsEffect()
                if not isinstance(shadow, QtWidgets.QGraphicsDropShadowEffect):
                    shadow = QtWidgets.QGraphicsDropShadowEffect(header)
                    header.setGraphicsEffect(shadow)
                shadow.setBlurRadius(14)
                shadow.setOffset(0, 2)
                shadow.setColor(palette["shadow"])
            except Exception:
                pass

    def _enforce_frontend_runtime_collapsed_visibility(self):
            if getattr(self, "_frontend_runtime_tab_container", None) is not None:
                self._ensure_frontend_runtime_tab_selection()
                return
            for object_name in ("chat_runtime_box", "stt_runtime_box", "tts_runtime_box", "visual_reply_runtime_box"):
                group_box = self._ui_object(object_name)
                header = getattr(group_box, "_nc_runtime_header_button", None) if group_box is not None else None
                if group_box is None or header is None:
                    continue
                try:
                    header_visible = bool(header.isVisible())
                except Exception:
                    header_visible = True
                try:
                    expanded = bool(group_box.property("nc_collapsible_expanded"))
                except Exception:
                    expanded = True
                try:
                    if not header_visible:
                        self._set_layout_item_tree_visible(group_box.layout(), False)
                        self._set_frontend_runtime_group_geometry_collapsed(group_box, True)
                        group_box.setVisible(False)
                    elif expanded:
                        self._set_frontend_runtime_group_geometry_collapsed(group_box, False)
                        group_box.setVisible(True)
                        self._restore_frontend_expanded_runtime_group(group_box)
                    else:
                        self._set_layout_item_tree_visible(group_box.layout(), False)
                        self._set_frontend_runtime_group_geometry_collapsed(group_box, True)
                        group_box.setVisible(False)
                        blocker = QtCore.QSignalBlocker(header)
                        header.setChecked(False)
                        del blocker
                        header.setArrowType(QtCore.Qt.RightArrow)
                    self._refresh_frontend_runtime_group_region(group_box)
                except Exception:
                    pass

    def _collapse_frontend_runtime_groups(self):
            if self._ensure_frontend_runtime_group_tabs():
                self._ensure_frontend_runtime_tab_selection()
                return
            for object_name in ("chat_runtime_box", "stt_runtime_box", "tts_runtime_box", "visual_reply_runtime_box"):
                group_box = self._ui_object(object_name)
                if group_box is None:
                    continue
                self._apply_frontend_collapsible_group_state(group_box, False)

    def _frontend_runtime_group_header_object_name(self, object_name):
            return {
                "chat_runtime_box": "chat_runtime_header_button",
                "stt_runtime_box": "stt_runtime_header_button",
                "tts_runtime_box": "tts_runtime_header_button",
                "visual_reply_runtime_box": "visual_reply_runtime_header_button",
            }.get(str(object_name or "").strip(), "")

    def _frontend_runtime_group_designer_title(self, object_name, fallback_title):
            header_name = self._frontend_runtime_group_header_object_name(object_name)
            header = self._ui_object(header_name) if header_name else None
            if header is not None and hasattr(header, "text"):
                text = str(header.text() or "").strip()
                if text:
                    return text
            return fallback_title

    def _ensure_frontend_runtime_group_header(self, group_box, fallback_title):
            if group_box is None:
                return None
            header = getattr(group_box, "_nc_runtime_header_button", None)
            if header is not None:
                return header
            object_name = str(group_box.objectName() or "").strip()
            header_name = self._frontend_runtime_group_header_object_name(object_name)
            header = self._ui_object(header_name) if header_name else None
            created_header = False
            parent = group_box.parentWidget()
            parent_layout = parent.layout() if parent is not None else None
            if header is None:
                if parent_layout is None or not hasattr(parent_layout, "insertWidget"):
                    return None
                insert_index = -1
                try:
                    for index in range(parent_layout.count()):
                        item = parent_layout.itemAt(index)
                        if item is not None and item.widget() is group_box:
                            insert_index = index
                            break
                except Exception:
                    insert_index = -1
                if insert_index < 0:
                    return None

                header = QtWidgets.QToolButton(parent)
                header.setObjectName(header_name or "runtime_section_header_button")
                created_header = True
                try:
                    parent_layout.insertWidget(insert_index, header, 0, QtCore.Qt.AlignLeft)
                except TypeError:
                    parent_layout.insertWidget(insert_index, header)

            try:
                if hasattr(header, "setText") and not str(header.text() if hasattr(header, "text") else "").strip():
                    header.setText(str(fallback_title or "Runtime"))
                header.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
                header.setCheckable(True)
                header.setAutoRaise(False)
                header.setMinimumSize(260, 34)
                header.setMaximumWidth(560)
                header.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
                header.setCursor(QtCore.Qt.PointingHandCursor)
                uses_default_style = created_header or not str(header.styleSheet() if hasattr(header, "styleSheet") else "").strip()
                header.setProperty("nc_runtime_header_uses_default_style", uses_default_style)
                if uses_default_style:
                    self._style_frontend_runtime_group_header(header, group_box)
                if not getattr(header, "_nc_runtime_group_header_bound", False):
                    header.toggled.connect(lambda checked, box=group_box: self._apply_frontend_collapsible_group_state(box, checked))
                    setattr(header, "_nc_runtime_group_header_bound", True)
            except Exception:
                pass

            setattr(group_box, "_nc_runtime_header_button", header)
            try:
                group_box.setProperty("nc_runtime_content_group", True)
                group_box.setCheckable(False)
                group_box.setTitle("")
                group_box.setFlat(False)
                if object_name:
                    existing = str(group_box.styleSheet() or "").strip()
                    marker = "/* nc-runtime-content-group */"
                    if marker not in existing:
                        content_style = f"""
{marker}
QGroupBox#{object_name} {{
    margin-top: 6px;
    padding: 8px;
    background: #0f141b;
    border: 1px solid #273342;
    border-radius: 10px;
}}
QGroupBox#{object_name}::title {{
    height: 0px;
    margin: 0px;
    padding: 0px;
}}
QGroupBox#{object_name}::indicator {{
    width: 0px;
    height: 0px;
}}
""".strip()
                        group_box.setStyleSheet(f"{existing}\n{content_style}".strip() if existing else content_style)
                if not str(group_box.property("nc_collapsible_base_title") or "").strip():
                    group_box.setProperty("nc_collapsible_base_title", fallback_title)
                group_box.style().unpolish(group_box)
                group_box.style().polish(group_box)
            except Exception:
                pass
            return header

    def _set_layout_item_tree_visible(self, layout, visible):
            if layout is None:
                return
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item is None:
                    continue
                widget = item.widget()
                if widget is not None:
                    try:
                        widget.setVisible(bool(visible))
                    except Exception:
                        pass
                    continue
                child_layout = item.layout()
                if child_layout is not None:
                    self._set_layout_item_tree_visible(child_layout, visible)

    def _update_frontend_collapsible_group_title(self, group_box):
            if group_box is None or not hasattr(group_box, "setTitle"):
                return
            try:
                base_title = str(group_box.property("nc_collapsible_base_title") or group_box.title() or "").strip()
            except Exception:
                base_title = str(group_box.title() or "").strip()
            try:
                summary = str(group_box.property("nc_collapsible_summary") or "").strip()
            except Exception:
                summary = ""
            expanded = True
            try:
                expanded_property = group_box.property("nc_collapsible_expanded")
                if expanded_property is not None:
                    expanded = bool(expanded_property)
                elif hasattr(group_box, "isChecked"):
                    expanded = bool(group_box.isChecked())
            except Exception:
                expanded = True
            if self._update_frontend_runtime_tab_text(group_box, base_title):
                try:
                    group_box.setTitle("")
                except Exception:
                    pass
                return
            arrow = "▼" if expanded else "▶"
            title = f"{arrow} {base_title}".strip()
            if summary:
                title = f"{title}  -  {summary}"
            header = getattr(group_box, "_nc_runtime_header_button", None)
            if header is not None:
                header_title = base_title
                if summary:
                    header_title = f"{header_title}  -  {summary}"
                try:
                    header.setText(header_title)
                    header.setToolTip(header_title)
                    header.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
                    blocker = QtCore.QSignalBlocker(header)
                    header.setChecked(bool(expanded))
                    del blocker
                    group_box.setTitle("")
                except Exception:
                    pass
                return
            try:
                group_box.setTitle(title)
            except Exception:
                pass

    def _apply_frontend_collapsible_group_state(self, group_box, expanded):
            if group_box is None:
                return

            layout = getattr(group_box, "layout", lambda: None)()
            try:
                group_box.setUpdatesEnabled(False)
            except Exception:
                pass
            try:
                self._set_layout_item_tree_visible(layout, bool(expanded))
                try:
                    group_box.setProperty("nc_collapsible_expanded", bool(expanded))
                    header = getattr(group_box, "_nc_runtime_header_button", None)
                    if header is not None:
                        blocker = QtCore.QSignalBlocker(header)
                        header.setChecked(bool(expanded))
                        del blocker
                        header.setArrowType(QtCore.Qt.DownArrow if bool(expanded) else QtCore.Qt.RightArrow)
                        if bool(expanded):
                            self._set_frontend_runtime_group_geometry_collapsed(group_box, False)
                            group_box.setVisible(True)
                            self._restore_frontend_expanded_runtime_group(group_box)
                        else:
                            self._set_frontend_runtime_group_geometry_collapsed(group_box, True)
                            group_box.setVisible(False)
                    else:
                        group_box.setFlat(not bool(expanded))
                except Exception:
                    pass
                self._update_frontend_collapsible_group_title(group_box)
            finally:
                try:
                    group_box.setUpdatesEnabled(True)
                    group_box.updateGeometry()
                except Exception:
                    pass

            try:
                QtCore.QTimer.singleShot(0, self._apply_frontend_workspace_view_constraints)
                self._schedule_frontend_system_shaping_resync(80 if bool(expanded) else 40)
                QtCore.QTimer.singleShot(0, lambda box=group_box: self._enforce_frontend_runtime_collapsed_visibility())
                QtCore.QTimer.singleShot(60, lambda box=group_box: self._enforce_frontend_runtime_collapsed_visibility())
            except Exception:
                pass
            self._refresh_frontend_runtime_group_region(group_box)

    def _apply_frontend_collapsible_group_state_old(self, group_box, expanded):
            if group_box is None:
                return
            layout = getattr(group_box, "layout", lambda: None)()
            self._set_layout_item_tree_visible(layout, bool(expanded))
            try:
                group_box.setFlat(not bool(expanded))
            except Exception:
                pass
            self._update_frontend_collapsible_group_title(group_box)
            QtCore.QTimer.singleShot(0, self._apply_frontend_workspace_view_constraints)

    def _set_frontend_collapsible_group_summary(self, group_box, text, fallback_title):
            if group_box is None:
                return
            title, summary = _split_collapsible_section_text(text, fallback_title)
            try:
                group_box.setProperty("nc_collapsible_base_title", title)
                group_box.setProperty("nc_collapsible_summary", summary)
                group_box.setToolTip("")
            except Exception:
                pass
            if self._update_frontend_runtime_tab_text(group_box, fallback_title):
                return
            self._update_frontend_collapsible_group_title(group_box)

    def _configure_frontend_runtime_group_boxes(self):
            if self._ensure_frontend_runtime_group_tabs():
                return
            group_specs = (
                ("chat_runtime_box", "Chat Runtime"),
                ("stt_runtime_box", "STT Runtime"),
                ("tts_runtime_box", "TTS Runtime"),
                ("visual_reply_runtime_box", "Visual Reply Runtime"),
            )
            for object_name, fallback_title in group_specs:
                group_box = self._ui_object(object_name)
                if group_box is None:
                    continue
                base_title = self._frontend_runtime_group_designer_title(object_name, fallback_title)
                try:
                    group_box.setCheckable(True)
                    group_box.setChecked(False)
                    group_box.setProperty("nc_collapsible_base_title", base_title)
                    group_box.setProperty("nc_collapsible_summary", "")
                    group_box.setToolTip("")
                    header = self._ensure_frontend_runtime_group_header(group_box, base_title)
                    if header is None:
                        group_box.toggled.connect(
                            lambda checked, box=group_box: self._apply_frontend_collapsible_group_state(box, checked)
                        )
                except Exception:
                    continue
                self._apply_frontend_collapsible_group_state(group_box, False)
