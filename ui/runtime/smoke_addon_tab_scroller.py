from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtCore, QtGui, QtWidgets

from ui.runtime import addon_tab_scroller as addon_tab_scroller_module
from ui.runtime.addon_tab_scroller import install_addon_tab_scroller
from ui.runtime.real_ui_bridge import MainUiRealRuntimeBridge


class _WheelEvent:
    def __init__(self, delta: int) -> None:
        self._delta = int(delta)
        self.accepted = False

    def pixelDelta(self) -> QtCore.QPoint:
        return QtCore.QPoint()

    def angleDelta(self) -> QtCore.QPoint:
        return QtCore.QPoint(0, self._delta)

    def accept(self) -> None:
        self.accepted = True


class _WheelBlocker(QtCore.QObject):
    def __init__(self, parent: QtCore.QObject) -> None:
        super().__init__(parent)
        self.wheel_events = 0

    def eventFilter(self, watched, event):
        if event is not None and event.type() == QtCore.QEvent.Wheel:
            self.wheel_events += 1
            return True
        return super().eventFilter(watched, event)


class _BridgeHarness(MainUiRealRuntimeBridge):
    def __init__(self, scroller) -> None:
        QtCore.QObject.__init__(self)
        self.window = QtWidgets.QWidget()
        self._frontend_dock_tab_drag = None
        self._closing = False
        self._addon_tab_scroller = scroller

    def _watched_belongs_to_frontend(self, watched) -> bool:
        return False

    def _consume_frontend_push_to_talk_event(self, event) -> bool:
        return False


def _app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _make_tabs(count: int, *, height: int = 360) -> QtWidgets.QTabWidget:
    tabs = QtWidgets.QTabWidget()
    tabs.setObjectName("left_tabs")
    tabs.setTabPosition(QtWidgets.QTabWidget.West)
    tabs.setUsesScrollButtons(True)
    tabs.setStyleSheet(
        "QTabWidget#left_tabs QTabBar::tab {"
        " width: 62px; min-width: 62px; max-width: 62px;"
        " height: 54px; min-height: 54px; max-height: 54px;"
        " margin-bottom: 4px;"
        "}"
    )
    for index in range(count):
        page = QtWidgets.QWidget()
        page.setObjectName(f"addon_{index}")
        tabs.addTab(page, "")
        tabs.setTabToolTip(index, f"Addon {index}")
    tabs.resize(420, height)
    tabs.show()
    _app().processEvents()
    return tabs


def _button(tab_bar: QtWidgets.QTabBar, name: str) -> QtWidgets.QToolButton:
    button = tab_bar.findChild(QtWidgets.QToolButton, name)
    assert button is not None
    return button


def _wheel_event(delta: int = -120) -> QtGui.QWheelEvent:
    return QtGui.QWheelEvent(
        QtCore.QPointF(20, 120),
        QtCore.QPointF(20, 120),
        QtCore.QPoint(),
        QtCore.QPoint(0, int(delta)),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.NoScrollPhase,
        False,
    )


def _make_scrollable_page_tabs() -> tuple[QtWidgets.QTabWidget, QtWidgets.QScrollArea]:
    tabs = _make_tabs(16)
    old_page = tabs.widget(0)
    tabs.removeTab(0)
    old_page.deleteLater()

    scroll_area = QtWidgets.QScrollArea()
    content = QtWidgets.QWidget()
    content.setFixedSize(300, 2400)
    scroll_area.setWidget(content)
    scroll_area.setWidgetResizable(False)
    tabs.insertTab(0, scroll_area, "")
    tabs.setCurrentIndex(0)
    _app().processEvents()
    scroll_area.verticalScrollBar().setValue(200)
    return tabs, scroll_area


def test_scroll_button_renderer_uses_complete_source_image() -> None:
    _app()
    temp_dir = QtCore.QTemporaryDir()
    assert temp_dir.isValid()
    source_path = Path(temp_dir.path()) / "scroll_button_source.png"
    source = QtGui.QImage(100, 50, QtGui.QImage.Format_RGBA8888)
    source.fill(QtGui.QColor("red"))
    painter = QtGui.QPainter(source)
    try:
        painter.fillRect(QtCore.QRect(20, 0, 60, 50), QtGui.QColor("green"))
    finally:
        painter.end()
    assert source.save(str(source_path))

    icon = addon_tab_scroller_module._render_scroll_button_icon(
        source_path,
        QtCore.QSize(100, 50),
    )
    assert not icon.isNull()
    rendered = icon.pixmap(QtCore.QSize(100, 50)).toImage()
    outer = rendered.pixelColor(10, 25)
    center = rendered.pixelColor(50, 25)
    assert outer.red() > outer.green()
    assert center.green() > center.red()


def test_overflow_controls_and_wheel_scrolling() -> None:
    _app()
    tabs = _make_tabs(16)
    tabs.setCurrentIndex(0)
    scroller = install_addon_tab_scroller(tabs)
    assert scroller is not None
    _app().processEvents()

    tab_bar = tabs.tabBar()
    up = _button(tab_bar, "ScrollLeftButton")
    down = _button(tab_bar, "ScrollRightButton")

    assets = getattr(addon_tab_scroller_module, "_SCROLL_BUTTON_ASSETS", {})
    assert assets, "scroll button assets are not configured"
    for asset_path in assets.values():
        assert asset_path.is_file()

    assert up.isVisible()
    assert down.isVisible()
    assert up.arrowType() == QtCore.Qt.NoArrow
    assert down.arrowType() == QtCore.Qt.NoArrow
    assert not up.icon().isNull()
    assert not down.icon().isNull()
    assert up.height() == 38
    assert down.height() == 38
    assert up.iconSize() == up.size()
    assert down.iconSize() == down.size()
    up_image = up.icon().pixmap(up.iconSize()).toImage()
    down_image = down.icon().pixmap(down.iconSize()).toImage()
    assert up_image.pixelColor(0, 0).alpha() == 0
    assert down_image.pixelColor(0, 0).alpha() == 0
    assert up.geometry().top() == 0
    assert down.geometry().bottom() == tab_bar.height() - 1
    assert not up.isEnabled()
    assert down.isEnabled()

    original_index = tabs.currentIndex()
    original_y = tab_bar.tabRect(0).y()
    event = _WheelEvent(-120)
    assert scroller.scroll_from_wheel(event)
    _app().processEvents()
    assert event.accepted
    assert tab_bar.tabRect(0).y() < original_y
    assert tabs.currentIndex() == original_index

    event = _WheelEvent(120)
    assert scroller.scroll_from_wheel(event)
    _app().processEvents()
    assert tab_bar.tabRect(0).y() == original_y
    assert tabs.currentIndex() == original_index

    for _index in range(100):
        if not down.isEnabled():
            break
        down.click()
        _app().processEvents()
    assert not down.isEnabled()
    assert up.isEnabled()
    assert tabs.currentIndex() == original_index


def test_installation_is_idempotent_and_refreshes_after_tab_additions() -> None:
    _app()
    tabs = _make_tabs(2)
    first = install_addon_tab_scroller(tabs)
    second = install_addon_tab_scroller(tabs)
    assert first is second
    assert first is not None

    tab_bar = tabs.tabBar()
    up = _button(tab_bar, "ScrollLeftButton")
    down = _button(tab_bar, "ScrollRightButton")
    assert not up.isVisible()
    assert not down.isVisible()
    assert tab_bar.tabRect(0).y() == 0

    for index in range(2, 16):
        tabs.addTab(QtWidgets.QWidget(), "")
        tabs.setTabToolTip(index, f"Addon {index}")
    _app().processEvents()
    first.refresh()
    _app().processEvents()

    assert up.isVisible()
    assert down.isVisible()
    assert tab_bar.tabRect(0).y() > 0


def test_refresh_does_not_reschedule_from_its_own_layout_changes() -> None:
    app = _app()
    tabs = _make_tabs(16)
    scroller = install_addon_tab_scroller(tabs)
    assert scroller is not None
    app.processEvents()

    refresh_calls = 0
    original_refresh = scroller.refresh

    def counted_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        original_refresh()

    scroller.refresh = counted_refresh
    scroller._schedule_refresh()
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(150, loop.quit)
    loop.exec()

    assert refresh_calls <= 2, f"Scroller refresh rescheduled itself {refresh_calls} times"


def test_event_filter_tolerates_qobject_teardown_without_tab_bar_reference() -> None:
    _app()
    tabs = _make_tabs(16)
    scroller = install_addon_tab_scroller(tabs)
    assert scroller is not None
    _app().processEvents()

    tab_bar = scroller._tab_bar
    del scroller._tab_bar
    try:
        assert not scroller.eventFilter(tab_bar, QtCore.QEvent(QtCore.QEvent.User))
    finally:
        scroller._tab_bar = tab_bar


def test_tab_bar_wheel_event_scrolls_without_changing_selection() -> None:
    _app()
    tabs = _make_tabs(16)
    tab_bar = tabs.tabBar()
    legacy_filter = _WheelBlocker(tab_bar)
    tab_bar.installEventFilter(legacy_filter)
    scroller = install_addon_tab_scroller(tabs)
    assert scroller is not None
    _app().processEvents()

    original_index = tabs.currentIndex()
    original_y = tab_bar.tabRect(0).y()
    event = QtGui.QWheelEvent(
        QtCore.QPointF(20, 120),
        QtCore.QPointF(20, 120),
        QtCore.QPoint(),
        QtCore.QPoint(0, -120),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.NoScrollPhase,
        False,
    )
    QtWidgets.QApplication.sendEvent(tab_bar, event)
    _app().processEvents()

    assert event.isAccepted()
    assert tab_bar.tabRect(0).y() < original_y
    assert tabs.currentIndex() == original_index
    assert legacy_filter.wheel_events == 0


def test_application_bridge_routes_tab_bar_wheel_before_page_scroll() -> None:
    app = _app()
    tabs, scroll_area = _make_scrollable_page_tabs()
    scroller = install_addon_tab_scroller(tabs)
    assert scroller is not None
    app.processEvents()

    bridge = _BridgeHarness(scroller)
    app.installEventFilter(bridge)
    try:
        tab_bar = tabs.tabBar()
        original_tab_y = tab_bar.tabRect(0).y()
        original_page_y = scroll_area.verticalScrollBar().value()
        event = _wheel_event()

        QtWidgets.QApplication.sendEvent(tab_bar, event)
        app.processEvents()

        assert event.isAccepted()
        assert tab_bar.tabRect(0).y() < original_tab_y
        assert scroll_area.verticalScrollBar().value() == original_page_y
    finally:
        app.removeEventFilter(bridge)


def test_application_bridge_routes_icon_label_wheel_to_tab_strip() -> None:
    app = _app()
    tabs, scroll_area = _make_scrollable_page_tabs()
    tab_bar = tabs.tabBar()
    icon_label = QtWidgets.QLabel()
    icon_label.setFixedSize(62, 54)
    tab_bar.setTabButton(0, QtWidgets.QTabBar.RightSide, icon_label)
    scroller = install_addon_tab_scroller(tabs)
    assert scroller is not None
    app.processEvents()

    bridge = _BridgeHarness(scroller)
    app.installEventFilter(bridge)
    try:
        original_tab_y = tab_bar.tabRect(0).y()
        original_page_y = scroll_area.verticalScrollBar().value()
        event = _wheel_event()

        QtWidgets.QApplication.sendEvent(icon_label, event)
        app.processEvents()

        assert event.isAccepted()
        assert tab_bar.tabRect(0).y() < original_tab_y
        assert scroll_area.verticalScrollBar().value() == original_page_y
    finally:
        app.removeEventFilter(bridge)


if __name__ == "__main__":
    test_scroll_button_renderer_uses_complete_source_image()
    test_overflow_controls_and_wheel_scrolling()
    test_installation_is_idempotent_and_refreshes_after_tab_additions()
    test_refresh_does_not_reschedule_from_its_own_layout_changes()
    test_event_filter_tolerates_qobject_teardown_without_tab_bar_reference()
    test_tab_bar_wheel_event_scrolls_without_changing_selection()
    test_application_bridge_routes_tab_bar_wheel_before_page_scroll()
    test_application_bridge_routes_icon_label_wheel_to_tab_strip()
    print("smoke_addon_tab_scroller: ok")
