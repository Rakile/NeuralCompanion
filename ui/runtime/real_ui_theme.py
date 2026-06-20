import json

from PySide6 import QtCore, QtGui, QtWidgets

from core.ui_session_schema import group_ui_session, with_flat_ui_settings


def configure_real_ui_theme_dependencies(namespace):
    """Inject qt_app-owned theme globals used by the extracted real-UI theme mixin."""
    globals().update(dict(namespace or {}))


class _WorkspaceDockTabPaintFilter(QtCore.QObject):
    def __init__(self, palettes, aliases=None, parent=None, display_aliases=None):
        super().__init__(parent)
        self._palettes = dict(palettes or {})
        self._aliases = dict(aliases or {})
        self._display_aliases = dict(display_aliases or {})
        self._fallback = {
            "background": "#17212c",
            "checked": "#223247",
            "hover": "#29405b",
            "border": "#273342",
            "text": "#e5e9f0",
        }

    def _canonical_title(self, title):
        raw = str(title or "").strip()
        return self._aliases.get(raw, raw)

    def _display_title(self, title):
        raw = str(title or "").strip()
        return self._display_aliases.get(raw, raw)

    def _palette_for_title(self, title):
        return self._palettes.get(self._canonical_title(title)) or self._fallback

    def _moving_tab_proxy_widgets(self, tab_bar):
        if tab_bar is None:
            return []
        proxies = []
        try:
            children = tab_bar.findChildren(QtWidgets.QWidget, options=QtCore.Qt.FindDirectChildrenOnly)
        except Exception:
            return proxies
        for child in children:
            if child is None or isinstance(child, QtWidgets.QToolButton):
                continue
            try:
                if str(child.objectName() or "").strip():
                    continue
            except Exception:
                pass
            proxies.append(child)
        return proxies

    def _active_moving_tab_title(self, tab_bar):
        try:
            title = str(tab_bar.property("nc_workspace_dock_tab_drag_title") or "").strip()
        except Exception:
            title = ""
        if not title:
            return ""
        try:
            if any(proxy.isVisible() for proxy in self._moving_tab_proxy_widgets(tab_bar)):
                return title
        except Exception:
            return title
        return ""

    def _install_moving_tab_proxy_filter(self, tab_bar):
        title = self._active_moving_tab_title(tab_bar)
        if not title:
            return
        for proxy in self._moving_tab_proxy_widgets(tab_bar):
            try:
                proxy.setProperty("nc_workspace_dock_tab_proxy", True)
                proxy.setProperty("nc_workspace_dock_tab_proxy_title", title)
                proxy.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                proxy.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
                if not bool(proxy.property("nc_workspace_dock_tab_proxy_filtered")):
                    proxy.installEventFilter(self)
                    proxy.setProperty("nc_workspace_dock_tab_proxy_filtered", True)
                height = max(int(tab_bar.minimumHeight() or 0), int(tab_bar.height() or 0))
                if height > 0 and proxy.height() < height:
                    geom = proxy.geometry()
                    proxy.setGeometry(geom.x(), 0, geom.width(), height)
                proxy.raise_()
                proxy.update()
            except Exception:
                continue

    def _tab_path(self, rect, radius):
        path = QtGui.QPainterPath()
        left = float(rect.left())
        top = float(rect.top())
        right = float(rect.right())
        bottom = float(rect.bottom())
        radius = max(0.0, min(float(radius), rect.width() / 2.0, rect.height()))
        path.moveTo(left, bottom)
        path.lineTo(left, top + radius)
        path.quadTo(left, top, left + radius, top)
        path.lineTo(right - radius, top)
        path.quadTo(right, top, right, top + radius)
        path.lineTo(right, bottom)
        path.lineTo(left, bottom)
        path.closeSubpath()
        return path

    def _draw_tab_glow(self, painter, rect, color, selected):
        glow_color = QtGui.QColor(color)
        spreads = (7, 5, 3) if selected else (4, 2)
        base_alpha = 42 if selected else 22
        for step, spread in enumerate(spreads):
            glow_color.setAlpha(max(8, base_alpha - step * 10))
            glow_rect = QtCore.QRectF(rect).adjusted(-spread, -spread + 1, spread, spread)
            painter.fillPath(self._tab_path(glow_rect, 9 + spread), glow_color)

    def _draw_tab_bar(self, tab_bar):
        painter = QtGui.QPainter(tab_bar)
        try:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            base_bg = QtGui.QColor("#11161d")
            panel_bg = QtGui.QColor("#0f141b")
            baseline = QtGui.QColor("#273342")
            painter.fillRect(tab_bar.rect(), base_bg)
            baseline_y = tab_bar.rect().bottom() - 1
            painter.fillRect(QtCore.QRect(0, baseline_y, tab_bar.width(), 2), baseline)
            try:
                hover_index = tab_bar.tabAt(tab_bar.mapFromGlobal(QtGui.QCursor.pos()))
            except Exception:
                hover_index = -1
            moving_title = self._active_moving_tab_title(tab_bar)
            for index in range(tab_bar.count()):
                rect = tab_bar.tabRect(index)
                if not rect.isValid():
                    continue
                title = str(tab_bar.tabText(index) or "")
                if moving_title and self._canonical_title(title) == self._canonical_title(moving_title):
                    continue
                palette = self._palette_for_title(title)
                selected = index == tab_bar.currentIndex()
                hovered = index == hover_index
                background = palette["checked"] if selected else palette["hover"] if hovered else palette["background"]
                top_offset = 4 if selected else 7
                tab_rect = QtCore.QRectF(rect.adjusted(1, top_offset, -1, 2 if selected else -1))
                path = self._tab_path(tab_rect, 8)
                self._draw_tab_glow(painter, tab_rect, palette["border"], selected)
                painter.fillPath(path, QtGui.QColor(background))
                painter.setPen(QtGui.QPen(QtGui.QColor(palette["border"]), 1))
                painter.drawPath(path)
                if selected:
                    painter.fillRect(
                        QtCore.QRectF(tab_rect.left() + 1, baseline_y - 1, tab_rect.width() - 2, 4),
                        QtGui.QColor(background),
                    )
                    painter.setPen(QtGui.QPen(QtGui.QColor(palette["border"]), 1))
                    painter.drawLine(QtCore.QPointF(tab_rect.left(), tab_rect.bottom()), QtCore.QPointF(tab_rect.left(), baseline_y))
                    painter.drawLine(QtCore.QPointF(tab_rect.right(), tab_rect.bottom()), QtCore.QPointF(tab_rect.right(), baseline_y))
                else:
                    painter.fillRect(
                        QtCore.QRectF(tab_rect.left() + 1, baseline_y, tab_rect.width() - 2, 2),
                        panel_bg,
                    )
                font = tab_bar.font()
                try:
                    desired_font_px = int(tab_bar.property("nc_workspace_dock_tab_font_pixel_size") or 0)
                except Exception:
                    desired_font_px = 0
                if desired_font_px > 0:
                    font.setPixelSize(desired_font_px)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(palette["text"]))
                painter.drawText(rect.adjusted(12, top_offset - 1, -12, -4), QtCore.Qt.AlignCenter, self._display_title(title))
        finally:
            painter.end()

    def _draw_tab_proxy(self, proxy):
        tab_bar = proxy.parentWidget() if proxy is not None else None
        if not isinstance(tab_bar, QtWidgets.QTabBar):
            return False
        try:
            title = str(proxy.property("nc_workspace_dock_tab_proxy_title") or "").strip()
        except Exception:
            title = ""
        title = title or self._active_moving_tab_title(tab_bar)
        if not title:
            return False
        palette = self._palette_for_title(title)
        painter = QtGui.QPainter(proxy)
        try:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            rect = QtCore.QRectF(proxy.rect().adjusted(1, 4, -1, -2))
            path = self._tab_path(rect, 8)
            self._draw_tab_glow(painter, rect, palette["border"], True)
            painter.fillPath(path, QtGui.QColor(palette["checked"]))
            painter.setPen(QtGui.QPen(QtGui.QColor(palette["border"]), 1))
            painter.drawPath(path)
            font = tab_bar.font()
            try:
                desired_font_px = int(tab_bar.property("nc_workspace_dock_tab_font_pixel_size") or 0)
            except Exception:
                desired_font_px = 0
            if desired_font_px > 0:
                font.setPixelSize(desired_font_px)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QtGui.QColor(palette["text"]))
            painter.drawText(proxy.rect().adjusted(12, 3, -12, -4), QtCore.Qt.AlignCenter, self._display_title(title))
            return True
        finally:
            painter.end()

    def eventFilter(self, obj, event):
        if event is not None:
            if isinstance(obj, QtWidgets.QTabBar):
                event_type = event.type()
                if event_type == QtCore.QEvent.MouseButtonPress:
                    try:
                        if event.button() == QtCore.Qt.LeftButton:
                            index = obj.tabAt(event.pos())
                            obj.setProperty("nc_workspace_dock_tab_drag_title", obj.tabText(index) if index >= 0 else "")
                    except Exception:
                        obj.setProperty("nc_workspace_dock_tab_drag_title", "")
                elif event_type in {QtCore.QEvent.MouseMove, QtCore.QEvent.ChildAdded}:
                    try:
                        if event_type == QtCore.QEvent.MouseMove and event.buttons() & QtCore.Qt.LeftButton:
                            obj.setProperty("nc_workspace_dock_tab_native_drag_paint", True)
                    except Exception:
                        pass
                    QtCore.QTimer.singleShot(0, lambda tab_bar=obj: self._install_moving_tab_proxy_filter(tab_bar))
                elif event_type == QtCore.QEvent.MouseButtonRelease:
                    try:
                        obj.setProperty("nc_workspace_dock_tab_native_drag_paint", False)
                    except Exception:
                        pass
                    QtCore.QTimer.singleShot(0, lambda tab_bar=obj: tab_bar.setProperty("nc_workspace_dock_tab_drag_title", ""))
                if event_type == QtCore.QEvent.Paint:
                    if bool(obj.property("nc_workspace_dock_tab_native_drag_paint")):
                        if QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton:
                            return False
                        try:
                            obj.setProperty("nc_workspace_dock_tab_native_drag_paint", False)
                            obj.setProperty("nc_workspace_dock_tab_drag_title", "")
                        except Exception:
                            pass
                    self._draw_tab_bar(obj)
                    return True
            elif (
                isinstance(obj, QtWidgets.QWidget)
                and bool(obj.property("nc_workspace_dock_tab_proxy"))
                and event.type() == QtCore.QEvent.Paint
            ):
                return self._draw_tab_proxy(obj)
        return super().eventFilter(obj, event)


class MainUiRealThemeMixin:
    """Theme binding and runtime-panel restyling helpers for the runtime-backed main.ui bridge."""

    def _bind_frontend_theme_controls(self):
            for preset_id, button_name, _edit_name in APP_THEME_PRESET_WIDGETS:
                button = self._ui_object(button_name)
                if button is None or not hasattr(button, "clicked"):
                    continue
                if hasattr(button, "setCheckable"):
                    try:
                        button.setCheckable(True)
                    except Exception:
                        pass
                button.clicked.connect(lambda _checked=False, wanted=preset_id: self._apply_frontend_theme_preset(wanted))

    def _theme_stylesheet_for_current_preset(self):
            current_preset = _normalize_app_theme_preset_id(
                getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
            )
            return _build_app_stylesheet_for_preset(current_preset)

    def _apply_theme_to_frontend_window(self):
            stylesheet = self._theme_stylesheet_for_current_preset()
            palette = _app_theme_palette(
                getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
            )
            dock_stylesheet = self._frontend_dock_title_stylesheet(palette)
            tab_stylesheet = self._frontend_horizontal_tab_stylesheet()
            if self.window is not None and hasattr(self.window, "setStyleSheet"):
                try:
                    self.window.setStyleSheet(f"{stylesheet}\n{dock_stylesheet}\n{tab_stylesheet}")
                    tabs = self._ui_object("host_settings_tabs")
                    if tabs is not None and hasattr(self, "_apply_host_settings_tabs_corner_fix"):
                        self._apply_host_settings_tabs_corner_fix(tabs)
                    if hasattr(self, "_apply_nested_horizontal_tab_facing"):
                        self._apply_nested_horizontal_tab_facing()
                except Exception:
                    pass
                try:
                    _apply_inline_theme_styles(self.window, palette)
                    _apply_readable_input_palettes(self.window, palette)
                    _apply_engine_action_button_accents(self.window)
                    self._apply_frontend_dock_title_widgets(palette)
                    self._normalize_frontend_workspace_dock_titles()
                    self._apply_frontend_workspace_dock_tab_styles()
                except Exception:
                    pass

    def _frontend_workspace_default_dock_titles(self):
            return {
                "SystemShapingDock": "HOST",
                "WorkspaceTabsDock": "ADDONS",
                "OperationalViewDock": "CHAT WINDOW",
                "VisualReplyDock": "VISUAL REPLY",
                "MuseTalkPreviewDock": "MUSETALK",
                "PreviewDock": "MUSETALK",
            }

    def _frontend_workspace_legacy_dock_title_aliases(self):
            return {
                "System Shaping": "HOST",
                "Workspace Tabs": "ADDONS",
                "Operational View": "CHAT WINDOW",
                "CHAT INTERFACE": "CHAT WINDOW",
                "Visual Reply": "VISUAL REPLY",
                "MuseTalk Preview": "MUSETALK",
                "MuseTalk": "MUSETALK",
            }

    def _frontend_workspace_dock_tab_palettes(self):
            return {
                "HOST": {
                    "background": "#2f1214",
                    "checked": "#42191d",
                    "hover": "#552026",
                    "border": "#ff5f6d",
                    "text": "#fff4f5",
                },
                "ADDONS": {
                    "background": "#0b203f",
                    "checked": "#12315e",
                    "hover": "#164274",
                    "border": "#4d8dff",
                    "text": "#f1f7ff",
                },
                "CHAT WINDOW": {
                    "background": "#0d2b20",
                    "checked": "#123b2c",
                    "hover": "#184d39",
                    "border": "#2cc985",
                    "text": "#f4fffa",
                },
                "VISUAL REPLY": {
                    "background": "#2d2110",
                    "checked": "#3f2e16",
                    "hover": "#564020",
                    "border": "#ffb347",
                    "text": "#fff8ed",
                },
                "MUSETALK": {
                    "background": "#1d183b",
                    "checked": "#282153",
                    "hover": "#342b70",
                    "border": "#b085ff",
                    "text": "#fbf8ff",
                },
            }

    def _normalize_frontend_workspace_dock_titles(self):
            defaults = self._frontend_workspace_default_dock_titles()
            legacy_aliases = self._frontend_workspace_legacy_dock_title_aliases()
            for object_name, default_title in defaults.items():
                dock = self._ui_object(object_name)
                if dock is None or not hasattr(dock, "setWindowTitle"):
                    continue
                try:
                    if bool(dock.property("nc_workspace_dock_custom_title")):
                        continue
                    title = str(dock.windowTitle() or "").strip()
                    if object_name in {"PreviewDock", "MuseTalkPreviewDock"}:
                        wanted = legacy_aliases.get(title, default_title)
                    else:
                        wanted = legacy_aliases.get(title, default_title if not title or title == object_name else title)
                    if title != wanted:
                        dock.setWindowTitle(wanted)
                except Exception:
                    pass

    def _is_frontend_workspace_dock_tab_bar(self, tab_bar, target_titles):
            if tab_bar is None or not hasattr(tab_bar, "count"):
                return False
            for index in range(tab_bar.count()):
                title = str(tab_bar.tabText(index) or "").strip()
                if title in target_titles:
                    return True
            return False

    def _frontend_workspace_dock_tab_title_maps(self, palettes):
            aliases = self._frontend_workspace_legacy_dock_title_aliases()
            display_aliases = dict(aliases)
            target_titles = set(palettes) | set(aliases)
            defaults = self._frontend_workspace_default_dock_titles()
            for object_name, default_title in defaults.items():
                dock = self._ui_object(object_name)
                if dock is None or not hasattr(dock, "windowTitle"):
                    continue
                try:
                    title = str(dock.windowTitle() or "").strip()
                except Exception:
                    title = ""
                if not title:
                    continue
                target_titles.add(title)
                if title not in palettes and title not in aliases:
                    aliases[title] = default_title
            return aliases, display_aliases, target_titles

    def _connect_frontend_workspace_tab_rename(self, tab_bar):
            if tab_bar is None or bool(tab_bar.property("nc_workspace_dock_tab_rename_connected")):
                return
            signal = getattr(tab_bar, "tabBarDoubleClicked", None)
            if signal is None:
                return
            try:
                signal.connect(lambda index, bar=tab_bar: self._rename_frontend_workspace_dock_tab(bar, index))
                tab_bar.setProperty("nc_workspace_dock_tab_rename_connected", True)
            except Exception:
                pass

    def _rename_frontend_workspace_dock_tab(self, tab_bar, index):
            try:
                index = int(index)
            except Exception:
                index = -1
            if tab_bar is None or index < 0:
                return
            try:
                tab_text = str(tab_bar.tabText(index) or "").strip()
            except Exception:
                tab_text = ""
            if not tab_text:
                return
            dock = None
            finder = getattr(self, "_frontend_dock_for_tab_text", None)
            if callable(finder):
                try:
                    dock = finder(tab_text)
                except Exception:
                    dock = None
            if dock is None:
                return
            current_title = str(dock.windowTitle() or tab_text).strip() or tab_text
            parent = self.window if self.window is not None else dock
            try:
                new_title, accepted = QtWidgets.QInputDialog.getText(
                    parent,
                    "Rename Tab",
                    "Tab name:",
                    QtWidgets.QLineEdit.Normal,
                    current_title,
                )
            except Exception:
                return
            if not accepted:
                return
            new_title = " ".join(str(new_title or "").split())
            if not new_title or new_title == current_title:
                return
            try:
                dock.setProperty("nc_workspace_dock_custom_title", True)
                dock.setWindowTitle(new_title)
                action = dock.toggleViewAction()
                if action is not None:
                    action.setText(new_title)
            except Exception:
                return
            scheduler = getattr(self, "_schedule_frontend_workspace_dock_tab_refresh", None)
            if callable(scheduler):
                scheduler()
            layout_scheduler = getattr(self, "_schedule_frontend_layout_save", None)
            if callable(layout_scheduler):
                layout_scheduler(delay_ms=650)

    def _apply_frontend_workspace_dock_tab_styles(self):
            if self.window is None:
                return
            self._normalize_frontend_workspace_dock_titles()
            palettes = self._frontend_workspace_dock_tab_palettes()
            aliases, display_aliases, target_titles = self._frontend_workspace_dock_tab_title_maps(palettes)
            paint_filter = getattr(self, "_frontend_workspace_dock_tab_paint_filter", None)
            if paint_filter is None:
                paint_filter = _WorkspaceDockTabPaintFilter(palettes, aliases, self.window, display_aliases)
                self._frontend_workspace_dock_tab_paint_filter = paint_filter
            try:
                paint_filter._palettes = dict(palettes)
                paint_filter._aliases = dict(aliases)
                paint_filter._display_aliases = dict(display_aliases)
            except Exception:
                pass
            for tab_bar in self.window.findChildren(QtWidgets.QTabBar):
                if not self._is_frontend_workspace_dock_tab_bar(tab_bar, target_titles):
                    continue
                try:
                    if not bool(tab_bar.property("nc_workspace_dock_tab_styled")):
                        tab_bar.installEventFilter(paint_filter)
                        tab_bar.setProperty("nc_workspace_dock_tab_styled", True)
                    self._connect_frontend_workspace_tab_rename(tab_bar)
                    font = tab_bar.font()
                    base_font_height = tab_bar.property("nc_workspace_dock_tab_base_font_height")
                    try:
                        base_font_height = float(base_font_height)
                    except Exception:
                        base_font_height = 0.0
                    if base_font_height <= 0.0:
                        base_font_height = float(max(1, tab_bar.fontMetrics().height()))
                        tab_bar.setProperty("nc_workspace_dock_tab_base_font_height", base_font_height)
                    font_px = max(1, int(round(base_font_height * 1.1625)))
                    height_px = max(1, int(round(base_font_height * 2.1 * 1.1625)))
                    tab_bar.setProperty("nc_workspace_dock_tab_font_pixel_size", font_px)
                    font.setPixelSize(font_px)
                    font.setBold(True)
                    tab_bar.setFont(font)
                    tab_bar.setStyleSheet(
                        "QTabBar {"
                        " background: #11161d;"
                        " font-weight: 700;"
                        f" font-size: {font_px}px;"
                        f" min-height: {height_px}px;"
                        "}"
                        "QTabBar::tab {"
                        f" min-height: {max(1, height_px - 8)}px;"
                        " padding-left: 16px;"
                        " padding-right: 16px;"
                        "}"
                    )
                    tab_bar.setDrawBase(False)
                    tab_bar.setExpanding(False)
                    tab_bar.setUsesScrollButtons(True)
                    tab_bar.setMinimumHeight(max(tab_bar.minimumHeight(), height_px))
                    if bool(tab_bar.property("nc_workspace_dock_tab_native_drag_paint")):
                        if QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton:
                            QtCore.QTimer.singleShot(120, self._apply_frontend_workspace_dock_tab_styles)
                            continue
                        tab_bar.setProperty("nc_workspace_dock_tab_native_drag_paint", False)
                        tab_bar.setProperty("nc_workspace_dock_tab_drag_title", "")
                    if tab_bar.count() > 0 and tab_bar.currentIndex() < 0:
                        tab_bar.setCurrentIndex(0)
                    tab_bar.updateGeometry()
                    tab_bar.repaint()
                    tab_bar.update()
                except Exception:
                    continue

    def _schedule_frontend_workspace_dock_tab_refresh(self):
            QtCore.QTimer.singleShot(0, self._apply_frontend_workspace_dock_tab_styles)
            QtCore.QTimer.singleShot(50, self._apply_frontend_workspace_dock_tab_styles)
            QtCore.QTimer.singleShot(150, self._apply_frontend_workspace_dock_tab_styles)
            QtCore.QTimer.singleShot(350, self._apply_frontend_workspace_dock_tab_styles)
            QtCore.QTimer.singleShot(700, self._apply_frontend_workspace_dock_tab_styles)

    def _frontend_dock_title_stylesheet(self, palette):
            window_bg = palette.get("window_bg", "#11161d")
            panel_bg = palette.get("panel_bg", "#18202a")
            header_bg = palette.get("panel_bg", palette.get("header_bg", palette.get("field_bg", "#131a23")))
            border = palette.get("surface_border", "#273342")
            text = palette.get("text", "#e5e9f0")
            text_strong = palette.get("text_strong", "#f2f5f9")
            return f"""
QDockWidget {{
    background: {window_bg};
    color: {text};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {header_bg};
    color: {text_strong};
    border: 1px solid {border};
    padding: 4px 8px;
    text-align: left;
}}
QDockWidget::close-button,
QDockWidget::float-button {{
    background: {panel_bg};
    border: 1px solid {border};
    border-radius: 4px;
    width: 14px;
    height: 14px;
}}
QDockWidget::close-button:hover,
QDockWidget::float-button:hover {{
    background: {palette.get("button_hover_bg", "#29405b")};
}}
QMainWindow::separator {{
    background: transparent;
    width: 5px;
    height: 5px;
}}
QMainWindow::separator:vertical {{
    border-left: 1px solid {border};
    margin-left: 2px;
    margin-right: 2px;
}}
QMainWindow::separator:horizontal {{
    border-top: 1px solid {border};
    margin-top: 2px;
    margin-bottom: 2px;
}}
QMainWindow::separator:hover {{
    background: transparent;
}}
QMainWindow::separator:vertical:hover {{
    border-left-color: {palette.get("button_hover_bg", "#29405b")};
}}
QMainWindow::separator:horizontal:hover {{
    border-top-color: {palette.get("button_hover_bg", "#29405b")};
}}
"""

    def _apply_frontend_dock_title_widgets(self, palette):
            if self.window is None:
                return
            for dock in self.window.findChildren(QtWidgets.QDockWidget):
                title_bar = dock.titleBarWidget()
                if title_bar is None or not bool(title_bar.property("nc_custom_dock_title")):
                    title_bar = self._create_frontend_dock_title_widget(dock)
                    dock.setTitleBarWidget(title_bar)
                    try:
                        dock.topLevelChanged.connect(lambda _floating=False, d=dock: self._update_frontend_dock_title_widget(d))
                    except Exception:
                        pass
                    try:
                        dock.topLevelChanged.connect(lambda _floating=False, d=dock: self._schedule_frontend_dock_owner_refresh(d))
                    except Exception:
                        pass
                    try:
                        dock.windowTitleChanged.connect(lambda _title="", d=dock: self._update_frontend_dock_title_widget(d))
                    except Exception:
                        pass
                if not bool(dock.property("nc_workspace_dock_tab_refresh_connected")):
                    try:
                        dock.topLevelChanged.connect(lambda _floating=False: self._schedule_frontend_workspace_dock_tab_refresh())
                        dock.setProperty("nc_workspace_dock_tab_refresh_connected", True)
                    except Exception:
                        pass
                title_bar.setProperty("nc_theme_palette", dict(palette or {}))
                self._update_frontend_dock_title_widget(dock)
                self._schedule_frontend_dock_owner_refresh(dock)

    def _create_frontend_dock_title_widget(self, dock):
            title_bar = QtWidgets.QWidget()
            title_bar.setObjectName("ncDockTitleBar")
            title_bar.setProperty("nc_custom_dock_title", True)
            layout = QtWidgets.QHBoxLayout(title_bar)
            layout.setContentsMargins(8, 3, 5, 3)
            layout.setSpacing(6)

            label = QtWidgets.QLabel(str(dock.windowTitle() or dock.objectName() or "Panel"))
            label.setObjectName("ncDockTitleLabel")
            label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
            layout.addWidget(label, 1)

            float_button = QtWidgets.QToolButton()
            float_button.setObjectName("ncDockFloatButton")
            float_button.setAutoRaise(True)
            float_button.clicked.connect(lambda _checked=False, d=dock: self._toggle_frontend_dock_floating(d))
            layout.addWidget(float_button)

            pin_button = QtWidgets.QToolButton()
            pin_button.setObjectName("ncDockPinButton")
            pin_button.setCheckable(True)
            pin_button.setAutoRaise(True)
            pin_button.clicked.connect(lambda _checked=False, d=dock: self._toggle_frontend_dock_pinned(d))
            layout.addWidget(pin_button)

            top_button = QtWidgets.QToolButton()
            top_button.setObjectName("ncDockTopButton")
            top_button.setCheckable(True)
            top_button.setAutoRaise(True)
            top_button.clicked.connect(lambda _checked=False, d=dock: self._toggle_frontend_dock_always_on_top(d))
            layout.addWidget(top_button)

            close_button = QtWidgets.QToolButton()
            close_button.setObjectName("ncDockCloseButton")
            close_button.setText("X")
            close_button.setToolTip("Close panel")
            close_button.setAutoRaise(True)
            close_button.clicked.connect(dock.close)
            layout.addWidget(close_button)

            return title_bar

    def _toggle_frontend_dock_floating(self, dock):
            if dock is None:
                return
            try:
                dock.setFloating(not bool(dock.isFloating()))
                self._apply_frontend_dock_window_flags(dock)
                self._schedule_frontend_dock_owner_refresh(dock)
                dock.show()
                dock.raise_()
            except Exception:
                pass

    def _frontend_session_payload(self):
            try:
                payload = json.loads(SESSION_PATH.read_text(encoding="utf-8")) if SESSION_PATH.exists() else {}
                return with_flat_ui_settings(payload) if isinstance(payload, dict) else {}
            except Exception:
                return {}

    def _write_frontend_session_payload_for_dock_flags(self, payload):
            try:
                payload = dict(payload or {})
                ui_settings = dict(payload.get("ui") or {})
                dock_settings = dict(ui_settings.get("docks") or {})
                if "pinned_floating_docks" in payload:
                    dock_settings["pinned_floating"] = list(payload.get("pinned_floating_docks") or [])
                if "always_on_top_floating_docks" in payload:
                    dock_settings["always_on_top"] = list(payload.get("always_on_top_floating_docks") or [])
                ui_settings["docks"] = dock_settings
                payload["ui"] = ui_settings
                SESSION_PATH.write_text(json.dumps(group_ui_session(payload), indent=4), encoding="utf-8")
            except Exception:
                pass

    def _frontend_dock_flag_names(self, key):
            payload = self._frontend_session_payload()
            values = payload.get(key, [])
            return {
                str(item or "").strip()
                for item in list(values or [])
                if str(item or "").strip()
            }

    def _sync_frontend_dock_flags_to_backend(self, key, names):
            backend = getattr(self, "backend", None)
            if backend is None:
                return
            attr = "_pinned_floating_dock_names" if key == "pinned_floating_docks" else "_always_on_top_floating_dock_names"
            try:
                setattr(backend, attr, set(names or []))
            except Exception:
                pass

    def _set_frontend_dock_flag(self, dock, key, enabled):
            if dock is None:
                return
            object_name = str(dock.objectName() or "").strip()
            if not object_name:
                return
            payload = self._frontend_session_payload()
            names = {
                str(item or "").strip()
                for item in list(payload.get(key, []) or [])
                if str(item or "").strip()
            }
            if enabled:
                names.add(object_name)
            else:
                names.discard(object_name)
            payload[key] = sorted(names)
            self._sync_frontend_dock_flags_to_backend(key, names)
            self._write_frontend_session_payload_for_dock_flags(payload)
            self._apply_frontend_dock_window_flags(dock)
            self._schedule_frontend_dock_owner_refresh(dock)
            self._update_frontend_dock_title_widget(dock)
            try:
                if hasattr(self, "_save_frontend_layout_state"):
                    self._save_frontend_layout_state()
            except Exception:
                pass

    def _toggle_frontend_dock_pinned(self, dock):
            object_name = str(dock.objectName() or "").strip() if dock is not None else ""
            self._set_frontend_dock_flag(dock, "pinned_floating_docks", object_name not in self._frontend_dock_flag_names("pinned_floating_docks"))

    def _toggle_frontend_dock_always_on_top(self, dock):
            object_name = str(dock.objectName() or "").strip() if dock is not None else ""
            self._set_frontend_dock_flag(dock, "always_on_top_floating_docks", object_name not in self._frontend_dock_flag_names("always_on_top_floating_docks"))

    def _apply_frontend_dock_window_flags(self, dock):
            if dock is None:
                return
            object_name = str(dock.objectName() or "").strip()
            always_on_top = bool(object_name and object_name in self._frontend_dock_flag_names("always_on_top_floating_docks"))
            try:
                was_visible = bool(dock.isVisible())
                dock.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, bool(always_on_top and dock.isFloating()))
                if was_visible and dock.isFloating():
                    dock.show()
            except Exception:
                pass

    def _schedule_frontend_dock_owner_refresh(self, dock):
            if dock is None or not bool(globals().get("_WIN32_DOCK_OWNER_SUPPORTED", False)):
                return
            QtCore.QTimer.singleShot(0, lambda d=dock: self._refresh_frontend_native_dock_owner(d))

    def _refresh_frontend_native_dock_owner(self, dock):
            if dock is None or self.window is None or not bool(globals().get("_WIN32_DOCK_OWNER_SUPPORTED", False)):
                return
            try:
                object_name = str(dock.objectName() or "").strip()
                pinned = bool(object_name and object_name in self._frontend_dock_flag_names("pinned_floating_docks"))
                owner = 0 if dock.isFloating() and pinned else int(self.window.winId())
                setter = globals().get("_win32_set_window_owner")
                ctypes_module = globals().get("ctypes")
                if setter is None or ctypes_module is None:
                    return
                setter(int(dock.winId()), int(globals().get("_WIN32_GWLP_HWNDPARENT", -8)), ctypes_module.c_void_p(owner))
            except Exception:
                pass

    def _collect_frontend_pinned_floating_docks(self):
            pinned_names = self._frontend_dock_flag_names("pinned_floating_docks")
            panels = []
            seen = set()
            if self.window is None:
                return panels
            for dock in self.window.findChildren(QtWidgets.QDockWidget):
                object_name = str(dock.objectName() or "").strip()
                if not object_name or object_name not in pinned_names:
                    continue
                if not dock.isFloating() or not dock.isVisible():
                    continue
                key = id(dock)
                if key in seen:
                    continue
                seen.add(key)
                panels.append(dock)
            return panels

    def _hide_frontend_main_preserving_pinned_floating_docks(self):
            preserved = self._collect_frontend_pinned_floating_docks()
            self.window.hide()
            QtCore.QTimer.singleShot(0, lambda items=preserved: self._restore_frontend_pinned_floating_docks(items))

    def _restore_frontend_pinned_floating_docks(self, panels):
            for dock in list(panels or []):
                try:
                    if dock is None or not isinstance(dock, QtWidgets.QDockWidget) or not dock.isFloating():
                        continue
                    self._apply_frontend_dock_window_flags(dock)
                    dock.showNormal()
                    dock.show()
                    dock.raise_()
                except Exception:
                    continue

    def _update_frontend_dock_title_widget(self, dock):
            title_bar = dock.titleBarWidget() if dock is not None else None
            if title_bar is None or not bool(title_bar.property("nc_custom_dock_title")):
                return
            palette = title_bar.property("nc_theme_palette") or {}
            header_bg = palette.get("panel_bg", palette.get("header_bg", palette.get("field_bg", "#131a23")))
            panel_bg = palette.get("panel_bg", "#18202a")
            button_bg = palette.get("button_bg", "#223247")
            button_hover_bg = palette.get("button_hover_bg", "#29405b")
            border = palette.get("surface_border", "#273342")
            text = palette.get("text", "#e5e9f0")
            text_strong = palette.get("text_strong", "#f2f5f9")
            title_bar.setStyleSheet(
                f"""
QWidget#ncDockTitleBar {{
    background: {header_bg};
    border: 1px solid {border};
}}
QLabel#ncDockTitleLabel {{
    color: {text_strong};
    font-weight: 600;
    background: transparent;
    border: 0;
}}
QToolButton#ncDockFloatButton,
QToolButton#ncDockPinButton,
QToolButton#ncDockTopButton,
QToolButton#ncDockCloseButton {{
    color: {text};
    background: {button_bg};
    border: 1px solid {border};
    border-radius: 5px;
    padding: 1px 8px;
    min-width: 42px;
}}
QToolButton#ncDockFloatButton:hover,
QToolButton#ncDockPinButton:hover,
QToolButton#ncDockTopButton:hover,
QToolButton#ncDockCloseButton:hover {{
    background: {button_hover_bg};
}}
QToolButton#ncDockPinButton:checked,
QToolButton#ncDockTopButton:checked {{
    background: {button_hover_bg};
    border-color: {palette.get("accent", "#4d8dff")};
}}
QToolButton#ncDockCloseButton {{
    background: {panel_bg};
}}
"""
            )
            label = title_bar.findChild(QtWidgets.QLabel, "ncDockTitleLabel")
            if label is not None:
                label.setText(str(dock.windowTitle() or dock.objectName() or "Panel"))
            float_button = title_bar.findChild(QtWidgets.QToolButton, "ncDockFloatButton")
            if float_button is not None:
                floating = bool(dock.isFloating())
                float_button.setText("Dock" if floating else "Float")
                float_button.setToolTip("Dock panel" if floating else "Undock panel")
            object_name = str(dock.objectName() or "")
            pinned = object_name in self._frontend_dock_flag_names("pinned_floating_docks")
            always_on_top = object_name in self._frontend_dock_flag_names("always_on_top_floating_docks")
            pin_button = title_bar.findChild(QtWidgets.QToolButton, "ncDockPinButton")
            if pin_button is not None:
                pin_button.setText("Pinned" if pinned else "Pin")
                pin_button.setToolTip("Keep this floating panel visible when the main window is hidden")
                pin_button.setChecked(bool(pinned))
            top_button = title_bar.findChild(QtWidgets.QToolButton, "ncDockTopButton")
            if top_button is not None:
                top_button.setText("Top")
                top_button.setToolTip("Keep this floating panel above other windows")
                top_button.setChecked(bool(always_on_top))
            self._apply_frontend_dock_window_flags(dock)

    def _frontend_horizontal_tab_stylesheet(self):
            # The Designer/runtime theme intentionally keeps icon-sidebar tabs narrow,
            # but text tabs need enough width after dynamic addon pages are adopted.
            return """
QTabWidget#sensory_feedback_tabs QTabBar::tab {
    min-width: 132px;
    max-width: 320px;
    padding-left: 18px;
    padding-right: 18px;
}
QTabWidget#sensory_feedback_tabs QTabBar::tab:selected {
    padding-right: 18px;
}
QTabWidget#vseeface_tabs QTabBar::tab,
QTabWidget#musetalk_tabs QTabBar::tab,
QTabWidget#vam_setup_tabs QTabBar::tab {
    min-width: 96px;
    max-width: 220px;
    padding-left: 14px;
    padding-right: 14px;
}
QTabWidget#tts_runtime_addon_tabs QTabBar::tab {
    width: 150px;
    min-width: 150px;
    max-width: 150px;
    padding-left: 10px;
    padding-right: 10px;
}
QTabWidget#right_tabs QTabBar::tab {
    min-width: 118px;
    max-width: 240px;
    padding-left: 14px;
    padding-right: 14px;
}
"""

    def _apply_theme_to_runtime_panels(self):
            palette = _app_theme_palette(
                getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
            )
            preview_bg = palette.get("preview_bg", palette.get("panel_bg", palette.get("field_bg", "#18202a")))
            field_bg = palette.get("field_bg", "#0f141b")
            border = palette.get("surface_border", "#273342")
            text = palette.get("text", "#e5e9f0")
            text_strong = palette.get("text_strong", "#f2f5f9")

            for panel in (
                getattr(self, "_frontend_musetalk_preview_panel", None),
                getattr(self.backend, "embedded_musetalk_preview", None),
            ):
                if panel is None:
                    continue
                label = getattr(panel, "preview_label", None)
                if label is not None and hasattr(label, "setStyleSheet"):
                    try:
                        label.setStyleSheet(f"font-weight: 600; color: {text_strong};")
                    except Exception:
                        pass
                scroll = getattr(panel, "image_scroll", None)
                if scroll is not None and hasattr(scroll, "setStyleSheet"):
                    try:
                        focus_mode = bool(getattr(panel, "focus_mode_active", False))
                        if focus_mode:
                            scroll.setStyleSheet(
                                f"QScrollArea {{ background: {palette.get('window_bg', '#11161d')}; border: 0; border-radius: 0; }}"
                            )
                        else:
                            scroll.setStyleSheet(
                                f"QScrollArea {{ background: {preview_bg}; border: 1px solid {border}; border-radius: 10px; }}"
                            )
                    except Exception:
                        pass

            for panel in (
                getattr(self, "_frontend_visual_reply_panel", None),
                getattr(self.backend, "visual_reply_panel", None),
            ):
                if panel is None:
                    continue
                status_label = getattr(panel, "status_label", None)
                if status_label is not None and hasattr(status_label, "setStyleSheet"):
                    try:
                        status_label.setStyleSheet(f"font-weight: 600; color: {text_strong};")
                    except Exception:
                        pass
                storage_label = getattr(panel, "storage_label", None)
                if storage_label is not None and hasattr(storage_label, "setStyleSheet"):
                    try:
                        storage_label.setStyleSheet(f"color: {text}; font-size: 11px;")
                    except Exception:
                        pass
                caption_label = getattr(panel, "caption_label", None)
                if caption_label is not None and hasattr(caption_label, "setStyleSheet"):
                    try:
                        caption_label.setStyleSheet(f"color: {text}; font-size: 11px; padding: 2px 2px 0 2px;")
                    except Exception:
                        pass
                placeholder = getattr(panel, "placeholder", None)
                if placeholder is not None and hasattr(placeholder, "setStyleSheet"):
                    try:
                        placeholder.setStyleSheet(
                            f"background: {preview_bg}; border: 1px solid {border}; border-radius: 10px; color: {text}; padding: 18px;"
                        )
                    except Exception:
                        pass
                scroll = getattr(panel, "image_scroll", None)
                if scroll is not None and hasattr(scroll, "setStyleSheet"):
                    try:
                        scroll.setStyleSheet(
                            f"QScrollArea {{ background: {preview_bg}; border: 1px solid {border}; border-radius: 10px; }}"
                        )
                    except Exception:
                        pass
            audio_story_controller = self._audio_story_controller()
            if audio_story_controller is not None and hasattr(audio_story_controller, "apply_theme_palette"):
                try:
                    audio_story_controller.apply_theme_palette(palette)
                except Exception:
                    pass

    def _refresh_frontend_theme_controls(self):
            active_preset = _normalize_app_theme_preset_id(
                getattr(self.backend, "_active_app_theme_preset", RUNTIME_CONFIG.get("ui_theme_preset", DEFAULT_APP_THEME_PRESET))
            )
            for preset_id, button_name, edit_name in APP_THEME_PRESET_WIDGETS:
                button = self._ui_object(button_name)
                edit = self._ui_object(edit_name)
                if edit is not None and hasattr(edit, "setToolTip"):
                    edit.setToolTip("Theme note for this preset. The Apply button now switches the live app theme.")
                if button is None:
                    continue
                label = APP_THEME_PRESET_LABELS.get(preset_id, preset_id.replace("_", " ").title())
                if hasattr(button, "blockSignals"):
                    button.blockSignals(True)
                try:
                    if hasattr(button, "setCheckable"):
                        button.setCheckable(True)
                    if hasattr(button, "setChecked"):
                        button.setChecked(preset_id == active_preset)
                    if hasattr(button, "setText"):
                        button.setText(f"Applied {label}" if preset_id == active_preset else f"Apply {label}")
                    if hasattr(button, "setToolTip"):
                        button.setToolTip(
                            f"Currently active theme preset: {label}." if preset_id == active_preset else f"Apply the {label} theme preset."
                        )
                finally:
                    if hasattr(button, "blockSignals"):
                        button.blockSignals(False)

    def _apply_frontend_theme_preset(self, preset_id):
            if bool(getattr(self, "_frontend_theme_apply_in_progress", False)):
                return
            self._frontend_theme_apply_in_progress = True
            callback = getattr(self.backend, "apply_app_theme_preset", None)
            previous_backend_theme_apply = bool(getattr(self.backend, "_theme_apply_in_progress", False))
            try:
                if callable(callback):
                    callback(preset_id, save_session=True)
                if self.backend is not None:
                    self.backend._theme_apply_in_progress = True
                self._apply_theme_to_frontend_window()
                self._apply_theme_to_runtime_panels()
                self._refresh_frontend_theme_controls()
                if self.backend is not None:
                    self.backend._theme_apply_in_progress = previous_backend_theme_apply
                self._sync_backend_to_ui(force=True)
            finally:
                if self.backend is not None:
                    try:
                        self.backend._theme_apply_in_progress = previous_backend_theme_apply
                    except Exception:
                        pass
                self._frontend_theme_apply_in_progress = False
