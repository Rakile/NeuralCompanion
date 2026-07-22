from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


_ROOT = Path(__file__).resolve().parents[2]
_SCROLL_BUTTON_ASSETS = {
    QtCore.Qt.UpArrow: _ROOT / "ui_icons" / "side_tabs" / "scroll_up.png",
    QtCore.Qt.DownArrow: _ROOT / "ui_icons" / "side_tabs" / "scroll_down.png",
}
_IMAGE_BUTTON_STYLE = (
    "QToolButton {"
    " background: transparent;"
    " border: none;"
    " border-radius: 6px;"
    " padding: 0px;"
    "}"
    "QToolButton:hover { background: rgba(90, 127, 168, 36); }"
    "QToolButton:pressed { background: rgba(15, 20, 27, 110); }"
)
_FALLBACK_BUTTON_STYLE = (
    "QToolButton {"
    " background: #18202a;"
    " color: #e5e9f0;"
    " border: 1px solid #416184;"
    " border-radius: 5px;"
    " padding: 0px;"
    "}"
    "QToolButton:hover { background: #223247; border-color: #5a7fa8; }"
    "QToolButton:pressed { background: #0f141b; }"
    "QToolButton:disabled {"
    " background: #11161d;"
    " color: #526273;"
    " border-color: #273342;"
    "}"
)


_VERTICAL_TAB_SHAPES = {
    QtWidgets.QTabBar.RoundedWest,
    QtWidgets.QTabBar.RoundedEast,
    QtWidgets.QTabBar.TriangularWest,
    QtWidgets.QTabBar.TriangularEast,
}


def _render_scroll_button_icon(path: Path, size: QtCore.QSize) -> QtGui.QIcon:
    source = QtGui.QPixmap(str(path))
    if source.isNull() or size.isEmpty():
        return QtGui.QIcon()

    source_rect = QtCore.QRectF(source.rect())
    target_rect = QtCore.QRectF(0.0, 0.0, float(size.width()), float(size.height()))

    normal = QtGui.QPixmap(size)
    normal.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(normal)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(target_rect, 6.0, 6.0)
        painter.setClipPath(clip)
        painter.drawPixmap(target_rect, source, source_rect)
    finally:
        painter.end()

    disabled = QtGui.QPixmap(size)
    disabled.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(disabled)
    try:
        painter.setOpacity(0.35)
        painter.drawPixmap(0, 0, normal)
    finally:
        painter.end()

    icon = QtGui.QIcon(normal)
    icon.addPixmap(disabled, QtGui.QIcon.Disabled, QtGui.QIcon.Off)
    return icon


class _VerticalTabScrollStyle(QtWidgets.QProxyStyle):
    def __init__(self, tab_bar: QtWidgets.QTabBar, button_extent: int) -> None:
        super().__init__()
        self._button_extent = max(24, int(button_extent))
        self.setParent(tab_bar)

    def subElementRect(self, element, option, widget=None):
        rect = super().subElementRect(element, option, widget)
        if not isinstance(widget, QtWidgets.QTabBar) or widget.shape() not in _VERTICAL_TAB_SHAPES:
            return rect
        horizontal_margin = 2
        width = max(0, widget.width() - (horizontal_margin * 2))
        height = max(0, min(self._button_extent, widget.height()))
        if element == QtWidgets.QStyle.SE_TabBarScrollLeftButton:
            return QtCore.QRect(horizontal_margin, 0, width, height)
        if element == QtWidgets.QStyle.SE_TabBarScrollRightButton:
            return QtCore.QRect(
                horizontal_margin,
                max(0, widget.height() - height),
                width,
                height,
            )
        return rect


class AddonTabScroller(QtCore.QObject):
    _BUTTON_EXTENT = 38
    _REFRESH_EVENTS = {
        QtCore.QEvent.ChildAdded,
        QtCore.QEvent.PaletteChange,
        QtCore.QEvent.Resize,
        QtCore.QEvent.Show,
        QtCore.QEvent.StyleChange,
    }

    def __init__(self, tab_widget: QtWidgets.QTabWidget) -> None:
        self._tab_widget = tab_widget
        self._tab_bar = tab_widget.tabBar()
        super().__init__(self._tab_bar)
        self._refresh_pending = False
        self._icon_cache: dict[
            tuple[QtCore.Qt.ArrowType, int, int],
            QtGui.QIcon,
        ] = {}
        self._style = _VerticalTabScrollStyle(self._tab_bar, self._BUTTON_EXTENT)
        self._tab_bar.setStyle(self._style)
        self._tab_bar.setUsesScrollButtons(True)
        self._tab_widget.setUsesScrollButtons(True)
        self._tab_bar.installEventFilter(self)
        self.refresh()
        self._schedule_refresh()

    def handles(self, tab_bar: QtWidgets.QTabBar) -> bool:
        return tab_bar is self._tab_bar

    def handles_widget(self, widget: QtCore.QObject | None) -> bool:
        if widget is self._tab_bar:
            return True
        if not isinstance(widget, QtWidgets.QWidget):
            return False
        try:
            return self._tab_bar.isAncestorOf(widget)
        except RuntimeError:
            return False

    def _button(self, object_name: str) -> QtWidgets.QToolButton | None:
        return self._tab_bar.findChild(QtWidgets.QToolButton, object_name)

    def _icon_for(
        self,
        arrow: QtCore.Qt.ArrowType,
        size: QtCore.QSize,
    ) -> QtGui.QIcon:
        key = (arrow, size.width(), size.height())
        icon = self._icon_cache.get(key)
        if icon is None:
            icon = _render_scroll_button_icon(_SCROLL_BUTTON_ASSETS[arrow], size)
            self._icon_cache[key] = icon
        return icon

    def _configure_button(
        self,
        button: QtWidgets.QToolButton | None,
        *,
        arrow: QtCore.Qt.ArrowType,
        tooltip: str,
        accessible_name: str,
        at_top: bool,
    ) -> None:
        if button is None:
            return
        button.setToolTip(tooltip)
        button.setAccessibleName(accessible_name)
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        button.setCursor(QtCore.Qt.PointingHandCursor)
        button.setProperty("_nc_addon_tab_scroll_control", True)
        horizontal_margin = 2
        width = max(0, self._tab_bar.width() - (horizontal_margin * 2))
        height = max(0, min(self._BUTTON_EXTENT, self._tab_bar.height()))
        y = 0 if at_top else max(0, self._tab_bar.height() - height)
        button.setGeometry(horizontal_margin, y, width, height)

        icon = self._icon_for(arrow, button.size())
        if icon.isNull():
            button.setIcon(QtGui.QIcon())
            button.setIconSize(QtCore.QSize())
            button.setArrowType(arrow)
            button.setStyleSheet(_FALLBACK_BUTTON_STYLE)
        else:
            button.setArrowType(QtCore.Qt.NoArrow)
            button.setIcon(icon)
            button.setIconSize(button.size())
            button.setStyleSheet(_IMAGE_BUTTON_STYLE)
        button.raise_()

    def refresh(self) -> None:
        self._refresh_pending = False
        if self._tab_bar is None:
            return
        self._configure_button(
            self._button("ScrollLeftButton"),
            arrow=QtCore.Qt.UpArrow,
            tooltip="Scroll addons up",
            accessible_name="Scroll addons up",
            at_top=True,
        )
        self._configure_button(
            self._button("ScrollRightButton"),
            arrow=QtCore.Qt.DownArrow,
            tooltip="Scroll addons down",
            accessible_name="Scroll addons down",
            at_top=False,
        )

    def _schedule_refresh(self) -> None:
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QtCore.QTimer.singleShot(0, self.refresh)

    def scroll_from_wheel(self, event) -> bool:
        try:
            pixel_delta = event.pixelDelta()
        except Exception:
            pixel_delta = QtCore.QPoint()
        try:
            angle_delta = event.angleDelta()
        except Exception:
            angle_delta = QtCore.QPoint()
        delta = int(pixel_delta.y() or angle_delta.y() or pixel_delta.x() or angle_delta.x())
        if not delta:
            return False
        button_name = "ScrollLeftButton" if delta > 0 else "ScrollRightButton"
        button = self._button(button_name)
        if button is not None and button.isVisible() and button.isEnabled():
            button.click()
            self._schedule_refresh()
        try:
            event.accept()
        except Exception:
            pass
        return True

    def eventFilter(self, watched, event):
        tab_bar = getattr(self, "_tab_bar", None)
        if watched is tab_bar and event is not None:
            if event.type() == QtCore.QEvent.Wheel:
                return self.scroll_from_wheel(event)
            if event.type() in self._REFRESH_EVENTS:
                self._schedule_refresh()
        return super().eventFilter(watched, event)


def install_addon_tab_scroller(
    tab_widget: QtWidgets.QTabWidget | None,
) -> AddonTabScroller | None:
    if tab_widget is None or str(tab_widget.objectName() or "") != "left_tabs":
        return None
    existing = getattr(tab_widget, "_nc_addon_tab_scroller", None)
    if isinstance(existing, AddonTabScroller):
        existing.refresh()
        return existing
    try:
        scroller = AddonTabScroller(tab_widget)
    except Exception:
        return None
    setattr(tab_widget, "_nc_addon_tab_scroller", scroller)
    return scroller
