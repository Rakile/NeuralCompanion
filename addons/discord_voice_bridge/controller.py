from __future__ import annotations

import json
import copy
import re
import shutil
import threading
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from addons.discord_voice_bridge.settings import load_settings, redacted_settings, save_local_settings


ADDON_DIR = Path(__file__).resolve().parent


class _DiscordVoiceSettingsTabBar(QtWidgets.QTabBar):
    """Draw Discord settings tabs as compact MPRC-style icon cards."""

    _MIN_WIDTH = 68
    _HEIGHT = 68
    _HORIZONTAL_PADDING = 7
    _TOP_PADDING = 5
    _TITLE_HEIGHT = 20
    _ICON_TEXT_GAP = 1

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("_discord_icon_over_text", True)
        self.setProperty("_discord_mprc_tab_style", True)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(QtCore.Qt.ElideNone)
        self.setIconSize(QtCore.QSize(36, 36))

    def tabSizeHint(self, index: int) -> QtCore.QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.tabText(index))
        icon_width = 0 if self.tabIcon(index).isNull() else self.iconSize().width()
        width = max(self._MIN_WIDTH, max(text_width, icon_width) + (self._HORIZONTAL_PADDING * 2))
        return QtCore.QSize(width, self._HEIGHT)

    def _tab_metadata(self, index: int) -> dict[str, Any]:
        try:
            data = self.tabData(index)
        except Exception:
            return {}
        return dict(data) if isinstance(data, dict) else {}

    def _tab_accent(self, index: int) -> QtGui.QColor:
        color = str(self._tab_metadata(index).get("accent") or "#60a5fa").strip()
        accent = QtGui.QColor(color)
        return accent if accent.isValid() else QtGui.QColor("#60a5fa")

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        title_font = QtGui.QFont(self.font())
        title_font.setBold(True)
        for index in range(self.count()):
            rect = self.tabRect(index).adjusted(0, 0, -1, -2)
            if not event.rect().intersects(rect):
                continue
            selected = index == self.currentIndex()
            enabled = self.isTabEnabled(index)
            accent = self._tab_accent(index)
            border = accent if selected else QtGui.QColor("#36506d")
            background = QtGui.QColor("#1c2d43" if selected else "#111b28")
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(rect), 9, 9)
            painter.fillPath(path, background)
            painter.setPen(QtGui.QPen(border, 1))
            painter.drawPath(path)

            content = rect.adjusted(self._HORIZONTAL_PADDING, self._TOP_PADDING, -self._HORIZONTAL_PADDING, -5)
            title_rect = QtCore.QRect(content.left(), content.top(), content.width(), self._TITLE_HEIGHT)
            painter.setFont(title_font)
            painter.setPen(accent if enabled else QtGui.QColor("#728095"))
            painter.drawText(
                title_rect,
                QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter | QtCore.Qt.TextSingleLine,
                self.tabText(index),
            )

            icon = self.tabIcon(index)
            if not icon.isNull():
                icon_size = self.iconSize()
                icon_top = title_rect.bottom() + self._ICON_TEXT_GAP
                icon_rect = QtCore.QRect(
                    content.center().x() - (icon_size.width() // 2),
                    icon_top,
                    icon_size.width(),
                    icon_size.height(),
                )
                icon_mode = QtGui.QIcon.Normal if enabled else QtGui.QIcon.Disabled
                icon_state = QtGui.QIcon.On if selected else QtGui.QIcon.Off
                icon.paint(painter, icon_rect, QtCore.Qt.AlignCenter, icon_mode, icon_state)
        painter.end()


class _DiscordVoiceCommandButton(QtWidgets.QToolButton):
    """Draw top command buttons with the same card language as the settings tabs."""

    _MIN_WIDTH = 68
    _HEIGHT = 68
    _HORIZONTAL_PADDING = 7
    _TOP_PADDING = 5
    _TITLE_HEIGHT = 20
    _ICON_TEXT_GAP = 1

    def __init__(self, text: str, icon: QtGui.QIcon, accent: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = QtGui.QColor(str(accent or "#60a5fa"))
        if not self._accent.isValid():
            self._accent = QtGui.QColor("#60a5fa")
        self.setProperty("_discord_command_card_button", True)
        self.setProperty("_discord_mprc_tab_style", True)
        self.setText(str(text or ""))
        self.setIcon(icon)
        self.setIconSize(QtCore.QSize(36, 36))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAutoRaise(False)
        font = QtGui.QFont(self.font())
        font.setBold(True)
        self.setFont(font)
        self.setMinimumSize(self.sizeHint())
        self.setMaximumHeight(self._HEIGHT)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self) -> QtCore.QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        icon_width = 0 if self.icon().isNull() else self.iconSize().width()
        width = max(self._MIN_WIDTH, text_width + (self._HORIZONTAL_PADDING * 2), icon_width + (self._HORIZONTAL_PADDING * 2))
        return QtCore.QSize(width, self._HEIGHT)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        if not event.rect().intersects(rect):
            painter.end()
            return

        enabled = self.isEnabled()
        active = self.isDown() or self.underMouse()
        accent = self._accent if enabled else QtGui.QColor("#728095")
        border = accent if active else QtGui.QColor("#36506d")
        background = QtGui.QColor("#1c2d43" if active else "#111b28")
        if not enabled:
            background = QtGui.QColor("#0f1722")
            border = QtGui.QColor("#2b4058")

        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(rect), 9, 9)
        painter.fillPath(path, background)
        painter.setPen(QtGui.QPen(border, 1))
        painter.drawPath(path)

        content = rect.adjusted(self._HORIZONTAL_PADDING, self._TOP_PADDING, -self._HORIZONTAL_PADDING, -5)
        title_rect = QtCore.QRect(content.left(), content.top(), content.width(), self._TITLE_HEIGHT)
        painter.setFont(self.font())
        painter.setPen(accent)
        painter.drawText(
            title_rect,
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter | QtCore.Qt.TextSingleLine,
            self.text(),
        )

        icon = self.icon()
        if not icon.isNull():
            icon_size = self.iconSize()
            icon_top = title_rect.bottom() + self._ICON_TEXT_GAP
            icon_rect = QtCore.QRect(
                content.center().x() - (icon_size.width() // 2),
                icon_top,
                icon_size.width(),
                icon_size.height(),
            )
            icon_mode = QtGui.QIcon.Normal if enabled else QtGui.QIcon.Disabled
            icon_state = QtGui.QIcon.On if self.isDown() else QtGui.QIcon.Off
            icon.paint(painter, icon_rect, QtCore.Qt.AlignCenter, icon_mode, icon_state)
        painter.end()


def _discord_settings_tab_icon(kind: str, color: str) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(50, 50)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    accent = QtGui.QColor(str(color or "#60a5fa"))
    if not accent.isValid():
        accent = QtGui.QColor("#60a5fa")
    painter.setPen(QtGui.QPen(accent, 3))
    painter.setBrush(QtGui.QColor(17, 27, 40))
    painter.drawRoundedRect(4, 4, 42, 42, 10, 10)
    painter.setBrush(accent)
    painter.setPen(QtGui.QPen(accent, 3))

    key = str(kind or "").strip().lower()
    if key == "save":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(13, 12, 24, 26, 4, 4)
        painter.drawLine(18, 12, 18, 21)
        painter.drawLine(18, 21, 31, 21)
        painter.drawLine(31, 12, 31, 21)
        painter.drawRoundedRect(17, 29, 16, 8, 2, 2)
    elif key == "start":
        points = [
            QtCore.QPointF(18, 14),
            QtCore.QPointF(18, 36),
            QtCore.QPointF(35, 25),
        ]
        painter.drawPolygon(QtGui.QPolygonF(points))
    elif key == "stop":
        painter.drawRoundedRect(15, 15, 20, 20, 4, 4)
    elif key == "restart":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawArc(12, 12, 26, 26, 35 * 16, 280 * 16)
        painter.drawLine(36, 14, 37, 24)
        painter.drawLine(36, 14, 27, 15)
    elif key == "refresh":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawArc(12, 12, 26, 18, 20 * 16, 180 * 16)
        painter.drawLine(36, 16, 37, 25)
        painter.drawLine(36, 16, 29, 16)
        painter.drawArc(12, 20, 26, 18, 200 * 16, 180 * 16)
        painter.drawLine(14, 34, 13, 25)
        painter.drawLine(14, 34, 21, 34)
    elif key == "general":
        painter.drawLine(14, 16, 36, 16)
        painter.drawLine(14, 25, 36, 25)
        painter.drawLine(14, 34, 36, 34)
        painter.drawEllipse(18, 13, 6, 6)
        painter.drawEllipse(28, 22, 6, 6)
        painter.drawEllipse(21, 31, 6, 6)
    elif key == "discord":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(12, 16, 26, 20, 6, 6)
        painter.drawLine(18, 16, 16, 12)
        painter.drawLine(32, 16, 34, 12)
        painter.drawEllipse(18, 24, 4, 4)
        painter.drawEllipse(28, 24, 4, 4)
        painter.drawArc(20, 24, 10, 8, 200 * 16, 140 * 16)
    elif key == "capture":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(19, 10, 12, 23, 6, 6)
        painter.drawArc(14, 19, 22, 18, 180 * 16, 180 * 16)
        painter.drawLine(25, 37, 25, 42)
        painter.drawLine(18, 42, 32, 42)
    elif key == "playback":
        points = [
            QtCore.QPointF(18, 14),
            QtCore.QPointF(18, 36),
            QtCore.QPointF(35, 25),
        ]
        painter.drawPolygon(QtGui.QPolygonF(points))
    elif key == "filter":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawLine(13, 14, 37, 14)
        painter.drawLine(37, 14, 28, 25)
        painter.drawLine(28, 25, 28, 37)
        painter.drawLine(28, 37, 21, 33)
        painter.drawLine(21, 33, 21, 25)
        painter.drawLine(21, 25, 13, 14)
    elif key == "persona":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(18, 11, 14, 14)
        painter.drawArc(13, 25, 24, 18, 20 * 16, 140 * 16)
    elif key == "bots":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(13, 16, 24, 20, 6, 6)
        painter.drawLine(25, 16, 25, 10)
        painter.drawEllipse(23, 8, 4, 4)
        painter.drawEllipse(19, 24, 3, 3)
        painter.drawEllipse(29, 24, 3, 3)
        painter.drawLine(20, 31, 30, 31)
    elif key == "runtime":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(12, 13, 26, 9, 3, 3)
        painter.drawRoundedRect(12, 28, 26, 9, 3, 3)
        painter.drawEllipse(17, 16, 3, 3)
        painter.drawEllipse(17, 31, 3, 3)
        painter.drawLine(24, 18, 34, 18)
        painter.drawLine(24, 33, 34, 33)
    elif key == "status":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(13, 13, 24, 24)
        painter.drawLine(25, 23, 25, 33)
        painter.drawLine(25, 18, 25, 18)
    elif key == "moderator":
        painter.setBrush(QtCore.Qt.NoBrush)
        points = [
            QtCore.QPointF(25, 11),
            QtCore.QPointF(37, 16),
            QtCore.QPointF(34, 34),
            QtCore.QPointF(25, 40),
            QtCore.QPointF(16, 34),
            QtCore.QPointF(13, 16),
        ]
        painter.drawPolygon(QtGui.QPolygonF(points))
        painter.drawLine(19, 26, 24, 31)
        painter.drawLine(24, 31, 32, 22)
    else:
        painter.drawRoundedRect(14, 13, 22, 24, 5, 5)
        painter.drawLine(18, 20, 32, 20)
        painter.drawLine(18, 27, 32, 27)

    painter.end()
    return QtGui.QIcon(pixmap)


def _plain_text_scroll_state(view: QtWidgets.QPlainTextEdit | None) -> dict[str, Any]:
    if view is None:
        return {}
    vertical_bar = view.verticalScrollBar()
    horizontal_bar = view.horizontalScrollBar()
    vertical_value = vertical_bar.value() if vertical_bar is not None else 0
    vertical_max = vertical_bar.maximum() if vertical_bar is not None else 0
    return {
        "vertical": int(vertical_value),
        "vertical_max": int(vertical_max),
        "horizontal": int(horizontal_bar.value()) if horizontal_bar is not None else 0,
        "at_bottom": bool(vertical_bar is not None and vertical_value >= max(0, vertical_max - 2)),
    }


def _restore_plain_text_scroll_state(
    view: QtWidgets.QPlainTextEdit | None,
    state: dict[str, Any],
) -> None:
    if view is None or not isinstance(state, dict) or not state:
        return
    vertical_bar = view.verticalScrollBar()
    horizontal_bar = view.horizontalScrollBar()
    if vertical_bar is not None:
        if bool(state.get("at_bottom")):
            vertical_target = vertical_bar.maximum()
        else:
            vertical_target = int(state.get("vertical", 0) or 0)
        vertical_bar.setValue(min(max(0, vertical_target), vertical_bar.maximum()))
    if horizontal_bar is not None:
        horizontal_target = int(state.get("horizontal", 0) or 0)
        horizontal_bar.setValue(min(max(0, horizontal_target), horizontal_bar.maximum()))


def _capture_table_refresh_state(table: QtWidgets.QTableWidget) -> dict[str, Any]:
    vertical_bar = table.verticalScrollBar()
    horizontal_bar = table.horizontalScrollBar()
    return {
        "vertical": vertical_bar.value() if vertical_bar is not None else 0,
        "horizontal": horizontal_bar.value() if horizontal_bar is not None else 0,
        "current_row": table.currentRow(),
        "current_col": table.currentColumn(),
        "column_widths": [table.columnWidth(col) for col in range(table.columnCount())],
    }


def _restore_table_refresh_state_now(table: QtWidgets.QTableWidget, state: dict[str, Any]) -> None:
    column_widths = state.get("column_widths") if isinstance(state, dict) else []
    if column_widths:
        for col, width in enumerate(column_widths[: table.columnCount()]):
            table.setColumnWidth(col, int(width))
    else:
        table.resizeColumnsToContents()

    current_row = int(state.get("current_row", -1)) if isinstance(state, dict) else -1
    current_col = int(state.get("current_col", -1)) if isinstance(state, dict) else -1
    if 0 <= current_row < table.rowCount():
        if 0 <= current_col < table.columnCount():
            table.setCurrentCell(current_row, current_col)
        else:
            table.selectRow(current_row)

    vertical_bar = table.verticalScrollBar()
    if vertical_bar is not None:
        vertical_bar.setValue(min(int(state.get("vertical", 0) or 0), vertical_bar.maximum()))
    horizontal_bar = table.horizontalScrollBar()
    if horizontal_bar is not None:
        horizontal_bar.setValue(min(int(state.get("horizontal", 0) or 0), horizontal_bar.maximum()))


def _restore_table_refresh_state(table: QtWidgets.QTableWidget, state: dict[str, Any]) -> None:
    snapshot = dict(state or {})
    _restore_table_refresh_state_now(table, snapshot)
    QtCore.QTimer.singleShot(0, lambda table=table, snapshot=snapshot: _restore_table_refresh_state_now(table, snapshot))


def _restore_scroll_bar_value(scrollbar: QtWidgets.QScrollBar | None, value: int) -> None:
    if scrollbar is not None:
        scrollbar.setValue(min(max(0, int(value)), scrollbar.maximum()))


def _restore_scroll_bar_value_deferred(scrollbar: QtWidgets.QScrollBar | None, value: int) -> None:
    _restore_scroll_bar_value(scrollbar, value)
    if scrollbar is not None:
        QtCore.QTimer.singleShot(0, lambda scrollbar=scrollbar, value=int(value): _restore_scroll_bar_value(scrollbar, value))


def _set_plain_text_preserving_scroll(view: QtWidgets.QPlainTextEdit, text: str) -> None:
    if view.toPlainText() == text:
        return
    state = _plain_text_scroll_state(view)

    view.setUpdatesEnabled(False)
    try:
        view.setPlainText(text)
        _restore_plain_text_scroll_state(view, state)
    finally:
        view.setUpdatesEnabled(True)


def _append_plain_text_lines_preserving_scroll(view: QtWidgets.QPlainTextEdit, lines: list[str]) -> None:
    if not lines:
        return
    vertical_bar = view.verticalScrollBar()
    vertical_value = vertical_bar.value() if vertical_bar is not None else 0
    was_at_bottom = bool(vertical_bar is not None and vertical_value >= max(0, vertical_bar.maximum() - 2))
    state = _plain_text_scroll_state(view)
    existing_text = view.toPlainText()
    insert_text = "\n".join(lines)
    if existing_text:
        insert_text = "\n" + insert_text

    view.setUpdatesEnabled(False)
    try:
        cursor = QtGui.QTextCursor(view.document())
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(insert_text)
        if was_at_bottom and vertical_bar is not None:
            vertical_bar.setValue(vertical_bar.maximum())
        else:
            _restore_plain_text_scroll_state(view, state)
    finally:
        view.setUpdatesEnabled(True)


def _route_flow_text_state(view: QtWidgets.QPlainTextEdit) -> dict[str, Any]:
    vertical_bar = view.verticalScrollBar()
    horizontal_bar = view.horizontalScrollBar()
    vertical_value = vertical_bar.value() if vertical_bar is not None else 0
    vertical_max = vertical_bar.maximum() if vertical_bar is not None else 0
    return {
        "vertical": int(vertical_value),
        "horizontal": int(horizontal_bar.value()) if horizontal_bar is not None else 0,
        "at_bottom": bool(vertical_bar is not None and vertical_value >= max(0, vertical_max - 2)),
    }


def _restore_route_flow_text_state(view: QtWidgets.QPlainTextEdit, state: dict[str, Any]) -> None:
    vertical_bar = view.verticalScrollBar()
    if vertical_bar is not None:
        was_at_bottom = bool(state.get("at_bottom"))
        if was_at_bottom:
            vertical_bar.setValue(vertical_bar.maximum())
        else:
            vertical_target = int(state.get("vertical", 0) or 0)
            vertical_bar.setValue(min(max(0, vertical_target), vertical_bar.maximum()))
    horizontal_bar = view.horizontalScrollBar()
    if horizontal_bar is not None:
        horizontal_target = int(state.get("horizontal", 0) or 0)
        horizontal_bar.setValue(min(max(0, horizontal_target), horizontal_bar.maximum()))


def _set_route_flow_text_preserving_scroll(view: QtWidgets.QPlainTextEdit, lines: list[str]) -> None:
    text = "\n".join(lines)
    if view.toPlainText() == text:
        return
    state = _route_flow_text_state(view)
    view.setUpdatesEnabled(False)
    try:
        view.setPlainText(text)
        _restore_route_flow_text_state(view, state)
    finally:
        view.setUpdatesEnabled(True)


def _append_route_flow_text_preserving_scroll(view: QtWidgets.QPlainTextEdit, lines: list[str]) -> None:
    if not lines:
        return
    state = _route_flow_text_state(view)
    existing_text = view.toPlainText()
    insert_text = "\n".join(lines)
    if existing_text:
        insert_text = "\n" + insert_text
    view.setUpdatesEnabled(False)
    try:
        cursor = QtGui.QTextCursor(view.document())
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(insert_text)
        _restore_route_flow_text_state(view, state)
    finally:
        view.setUpdatesEnabled(True)


def _route_flow_entry_key(entry: dict[str, Any], line: str) -> str:
    route_key = str(entry.get("route_key") or "").strip()
    if route_key:
        return f"route:{route_key}"
    at_ms = str(entry.get("at_ms") or "").strip()
    source = str(entry.get("source") or "").strip()
    speaker = str(entry.get("speaker_name") or entry.get("speaker_bot_id") or "").strip()
    target = str(entry.get("target_name") or entry.get("target_bot_id") or "").strip()
    reason = str(entry.get("reason") or "").strip()
    return f"flow:{at_ms}:{source}:{speaker}:{target}:{reason}:{line}"


class DiscordVoiceBridgeController(QtCore.QObject):
    operation_finished = QtCore.Signal(str, bool, str)
    bot_models_refreshed = QtCore.Signal(str, list, str)

    def __init__(self, context, addon):
        super().__init__()
        self.context = context
        self.addon = addon
        self.widget = None
        self.controls: dict[str, QtWidgets.QWidget] = {}
        self._bots_model: list[dict[str, Any]] = []
        self._current_bot_index = -1
        self._loading_bot_fields = False
        self._operation_running = False
        self._one_shot_test_tone_pending = False
        self._last_instances: list[dict[str, Any]] = []
        self._last_moderator_state: dict[str, Any] = {}
        self._status_timer: QtCore.QTimer | None = None
        self._advanced_control_groups: dict[str, list[str]] = {}
        self._instances_table_columns_sized = False
        self._route_flow_rendered_lines: list[str] = []
        self._route_flow_rendered_keys: set[str] = set()
        self._bot_editor_plain_text_fields = {"discord_bot_persona_prompt_edit"}
        self._bot_model_refresh_running = False
        self._node_dependency_prompt_scheduled = False
        self._node_dependency_prompt_shown = False
        self._global_live_apply_timer = QtCore.QTimer(self)
        self._global_live_apply_timer.setSingleShot(True)
        self._global_live_apply_timer.setInterval(600)
        self._global_live_apply_timer.timeout.connect(self._auto_apply_global_live_settings)
        self.operation_finished.connect(self._on_operation_finished, QtCore.Qt.QueuedConnection)
        self.bot_models_refreshed.connect(self._on_bot_models_refreshed, QtCore.Qt.QueuedConnection)

    def bind_widget(self, widget, _context=None):
        self.widget = widget
        self._collect_controls(widget)
        self._build_bot_editor()
        self._build_room_router_controls()
        self._build_runtime_endpoint_fields()
        self._build_tiny_mvp_controls()
        self._build_status_actions()
        self._build_status_progress_controls()
        self._build_live_controls()
        self._build_moderator_controls()
        self._build_validation_summary()
        self._collect_controls(widget)
        self._build_advanced_visibility_controls()
        self._hide_deprecated_response_filter_controls()
        self._collect_controls(widget)
        self._apply_tab_polish()
        self._populate_choices()
        self._apply_tooltips()
        self._connect_signals()
        self.refresh_from_settings()
        self.refresh_status()
        widget.installEventFilter(self)
        if widget.isVisible():
            self._schedule_node_dependency_prompt()
        self._start_status_timer()

    def eventFilter(self, watched, event):
        if watched is self.widget and event.type() == QtCore.QEvent.Show:
            self._schedule_node_dependency_prompt()
        return super().eventFilter(watched, event)

    def _apply_tab_polish(self) -> None:
        self._apply_command_button_polish()
        tabs = self._control("discord_bridge_settings_tabs", QtWidgets.QTabWidget)
        if tabs is None:
            return

        self._ensure_settings_tab_bar(tabs)
        tabs.setIconSize(QtCore.QSize(36, 36))
        tabs.setUsesScrollButtons(True)
        tab_bar = tabs.tabBar()
        if tab_bar is not None:
            tab_bar.setDrawBase(False)
            tab_bar.setExpanding(False)
            tab_bar.setUsesScrollButtons(True)

        self._apply_settings_tab_icons(tabs)
        style = """
/* nc-discord-settings-tabs-polish:start */
QTabWidget#discord_bridge_settings_tabs::tab-bar {
    left: 0px;
}
QTabWidget#discord_bridge_settings_tabs QTabBar {
    background: #122033;
}
QTabWidget#discord_bridge_settings_tabs QTabBar::scroller {
    width: 32px;
}
QTabWidget#discord_bridge_settings_tabs QTabBar QToolButton {
    background: #1b2b40;
    color: #d8e2ee;
    border: 1px solid #416184;
    border-radius: 8px;
    width: 20px;
    min-width: 20px;
    max-width: 20px;
    padding: 0px;
    margin: 8px 1px 8px 1px;
}
QTabWidget#discord_bridge_settings_tabs QTabBar QToolButton:hover {
    background: #243956;
}
QTabWidget#discord_bridge_settings_tabs QTabBar::tab {
    background: transparent;
    color: #d8e2ee;
    font-weight: 700;
    border: none;
    min-width: 0px;
    min-height: 68px;
    padding: 0px;
    margin-right: 5px;
    margin-bottom: 2px;
    border-radius: 9px;
}
QTabWidget#discord_bridge_settings_tabs QTabBar::tab:!selected {
    background: transparent;
}
QTabWidget#discord_bridge_settings_tabs QTabBar::tab:selected {
    background: transparent;
    color: #f2f6fb;
    border: none;
}
QTabWidget#discord_bridge_settings_tabs QTabBar::tab:hover {
    background: transparent;
}
QTabWidget#discord_bridge_settings_tabs QTabBar::tab:selected:hover {
    background: transparent;
}
QTabWidget#discord_bridge_settings_tabs::pane {
    top: 0px;
    background: #122033;
    border: 1px solid #2d4561;
    border-top-color: #36506d;
    border-radius: 10px;
    padding: 10px;
}
QTabWidget#discord_bridge_settings_tabs QStackedWidget {
    background: transparent;
    padding: 6px;
}
/* nc-discord-settings-tabs-polish:end */
""".strip()
        start = "/* nc-discord-settings-tabs-polish:start */"
        end = "/* nc-discord-settings-tabs-polish:end */"
        existing = str(tabs.styleSheet() or "").strip()
        if start in existing and end in existing:
            before, rest = existing.split(start, 1)
            _old, after = rest.split(end, 1)
            existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
        next_style = f"{existing}\n{style}".strip() if existing else style
        if str(tabs.styleSheet() or "") != next_style:
            tabs.setStyleSheet(next_style)

    def _apply_command_button_polish(self) -> None:
        specs = {
            "discord_bridge_save_button": ("save", "#38bdf8"),
            "discord_bridge_start_button": ("start", "#22c55e"),
            "discord_bridge_stop_button": ("stop", "#fb7185"),
            "discord_bridge_restart_button": ("restart", "#f97316"),
            "discord_bridge_refresh_button": ("refresh", "#60a5fa"),
        }
        for name, (icon_key, accent) in specs.items():
            current = self.controls.get(name)
            if isinstance(current, _DiscordVoiceCommandButton):
                current.setIcon(_discord_settings_tab_icon(icon_key, accent))
                current.setMinimumSize(current.sizeHint())
                continue
            if not isinstance(current, QtWidgets.QAbstractButton):
                continue

            parent = current.parentWidget()
            button = _DiscordVoiceCommandButton(
                str(current.text() or ""),
                _discord_settings_tab_icon(icon_key, accent),
                accent,
                parent,
            )
            button.setObjectName(name)
            button.setToolTip(str(current.toolTip() or ""))
            button.setEnabled(current.isEnabled())
            button.setVisible(not current.isHidden())
            button.setCheckable(current.isCheckable())
            button.setChecked(current.isChecked() if current.isCheckable() else False)

            replaced = self._replace_widget_in_parent_layout(current, button)
            if not replaced and parent is not None:
                button.setParent(parent)
            self.controls[name] = button
            current.setParent(None)
            current.deleteLater()

    def _replace_widget_in_parent_layout(self, old_widget: QtWidgets.QWidget, new_widget: QtWidgets.QWidget) -> bool:
        parent = old_widget.parentWidget()
        layout = parent.layout() if parent is not None else None
        if layout is None:
            return False
        return self._replace_widget_in_layout(layout, old_widget, new_widget)

    def _replace_widget_in_layout(
        self,
        layout: QtWidgets.QLayout,
        old_widget: QtWidgets.QWidget,
        new_widget: QtWidgets.QWidget,
    ) -> bool:
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None:
                continue
            if item.widget() is old_widget:
                layout.removeWidget(old_widget)
                if isinstance(layout, QtWidgets.QBoxLayout):
                    layout.insertWidget(index, new_widget)
                else:
                    layout.addWidget(new_widget)
                return True
            child_layout = item.layout()
            if child_layout is not None and self._replace_widget_in_layout(child_layout, old_widget, new_widget):
                return True
        return False

    def _ensure_settings_tab_bar(self, tabs: QtWidgets.QTabWidget) -> None:
        if isinstance(tabs.tabBar(), _DiscordVoiceSettingsTabBar):
            return

        previous_bar = tabs.tabBar()
        current_index = tabs.currentIndex()
        entries: list[dict[str, Any]] = []
        for index in range(tabs.count()):
            entries.append(
                {
                    "widget": tabs.widget(index),
                    "text": tabs.tabText(index),
                    "icon": tabs.tabIcon(index),
                    "tooltip": tabs.tabToolTip(index),
                    "enabled": tabs.isTabEnabled(index),
                    "data": previous_bar.tabData(index) if previous_bar is not None else None,
                }
            )

        while tabs.count():
            tabs.removeTab(0)

        tab_bar = _DiscordVoiceSettingsTabBar(tabs)
        tabs.setTabBar(tab_bar)
        for entry in entries:
            widget = entry["widget"]
            icon = entry["icon"]
            text = str(entry["text"] or "")
            if isinstance(icon, QtGui.QIcon) and not icon.isNull():
                index = tabs.addTab(widget, icon, text)
            else:
                index = tabs.addTab(widget, text)
            tooltip = str(entry["tooltip"] or "")
            if tooltip:
                tabs.setTabToolTip(index, tooltip)
            tabs.setTabEnabled(index, bool(entry["enabled"]))
            tab_bar.setTabData(index, entry["data"])

        if entries:
            tabs.setCurrentIndex(min(max(0, current_index), len(entries) - 1))

    def _apply_settings_tab_icons(self, tabs: QtWidgets.QTabWidget) -> None:
        tab_specs = {
            "discord_bridge_general_tab": (
                "general",
                "#38bdf8",
                "General bridge behavior and local test room defaults.",
            ),
            "discord_bridge_discord_tab": (
                "discord",
                "#5865f2",
                "Discord token, guild, voice channel, and answer mode.",
            ),
            "discord_bridge_capture_tab": (
                "capture",
                "#22c55e",
                "Voice capture timing, saved WAV, and microphone ownership.",
            ),
            "discord_bridge_playback_tab": (
                "playback",
                "#f97316",
                "Reply playback, queueing, and interruption behavior.",
            ),
            "discord_bridge_filter_tab": (
                "filter",
                "#facc15",
                "Response filtering and room routing rules.",
            ),
            "discord_bridge_persona_tab": (
                "persona",
                "#a78bfa",
                "Discord-only persona prompt and voice clone settings.",
            ),
            "discord_bridge_bots_tab": (
                "bots",
                "#06b6d4",
                "Configured bot instances and per-bot overrides.",
            ),
            "discord_bridge_runtime_tab": (
                "runtime",
                "#14b8a6",
                "Local NC runtime endpoint, cleanup, and RAG context.",
            ),
            "discord_bridge_status_tab": (
                "status",
                "#60a5fa",
                "Bridge status, diagnostics, validation, and live controls.",
            ),
            "discord_bridge_moderator_tab": (
                "moderator",
                "#fb7185",
                "Human moderator controls for room routing and speech flow.",
            ),
        }
        tab_bar = tabs.tabBar()
        for index in range(tabs.count()):
            page = tabs.widget(index)
            object_name = str(page.objectName() if page is not None else "")
            spec = tab_specs.get(object_name)
            if spec is None:
                continue
            icon_key, accent, tooltip = spec
            icon = _discord_settings_tab_icon(icon_key, accent)
            if not icon.isNull():
                tabs.setTabIcon(index, icon)
            if tab_bar is not None:
                tab_bar.setTabData(index, {"accent": accent, "icon": icon_key})
            if not str(tabs.tabToolTip(index) or "").strip():
                tabs.setTabToolTip(index, tooltip)

    def _standard_tab_icon(self, icon_key) -> QtGui.QIcon:
        widget_style = self.widget.style() if isinstance(self.widget, QtWidgets.QWidget) else None
        app = QtWidgets.QApplication.instance()
        app_style = app.style() if app is not None else None
        style = widget_style or app_style
        if style is None:
            return QtGui.QIcon()
        return style.standardIcon(icon_key)

    def refresh_from_settings(self):
        settings = load_settings()
        display_settings = redacted_settings(settings)
        self._set_checked("discord_enabled_checkbox", _get(settings, "enabled", False))
        self._set_checked("discord_start_on_launch_checkbox", _get(settings, "start_on_nc_launch", False))
        self._set_checked("discord_auto_start_checkbox", _get(settings, "auto_start_bridge", False))
        self._set_combo("discord_bridge_mode_combo", _get(settings, "bridge_mode", "mock"))
        self._set_text("discord_tiny_mvp_url_edit", _get(settings, "tiny_mvp.url", "http://127.0.0.1:8788"))
        self._set_checked("discord_tiny_mvp_start_with_gui_checkbox", _get(settings, "tiny_mvp.start_with_gui", True))
        self._set_text("discord_tiny_mvp_bridge_script_edit", _get(settings, "tiny_mvp.bridge_script", ""))
        self._set_spin("discord_tiny_mvp_poll_seconds_spin", _get(settings, "tiny_mvp.poll_seconds", 0.25))
        self._set_checked("discord_tiny_mvp_capture_mic_checkbox", _get(settings, "tiny_mvp.capture_mic", False))
        self._set_checked(
            "discord_route_protected_mic_speech_checkbox",
            _get(settings, "playback.route_protected_mic_speech", _get(settings, "tiny_mvp.route_protected_mic_speech", False)),
        )
        self._set_text("discord_tiny_mvp_mic_user_id_edit", _get(settings, "tiny_mvp.mic_user_id", "rakila"))
        self._set_text("discord_tiny_mvp_mic_user_name_edit", _get(settings, "tiny_mvp.mic_user_name", "Rakila"))
        self._set_spin("discord_tiny_mvp_mic_seconds_spin", _get(settings, "tiny_mvp.mic_seconds", 6.0))
        self._set_spin("discord_tiny_mvp_mic_sample_rate_spin", _get(settings, "tiny_mvp.mic_sample_rate", 16000))
        self._set_text("discord_tiny_mvp_mic_device_edit", _get(settings, "tiny_mvp.mic_device", ""))
        self._set_spin("discord_context_entries_spin", _get(settings, "chat.context_entries", 20))
        self._set_checked(
            "discord_persist_room_context_checkbox",
            _get(settings, "chat.persist_room_context_between_restarts", False),
        )

        self._set_text("discord_token_env_edit", _get(settings, "discord.token_env_var", "DISCORD_TOKEN"))
        self._set_text("discord_local_token_edit", "")
        self._set_text("discord_guild_id_edit", _get(settings, "discord.guild_id", ""))
        self._set_text("discord_voice_channel_id_edit", _get(settings, "discord.voice_channel_id", ""))
        self._set_text("discord_allowed_user_id_edit", _get(settings, "discord.allowed_user_id", ""))
        self._set_combo("discord_answer_mode_combo", _get(settings, "discord.answer_mode", "allowed_user_only"))

        self._set_spin("discord_silence_ms_spin", _get(settings, "capture.silence_ms", 900))
        self._set_spin("discord_min_turn_seconds_spin", _get(settings, "capture.min_turn_seconds", 0.6))
        self._set_spin("discord_max_turn_seconds_spin", _get(settings, "capture.max_turn_seconds", 30))
        self._set_spin("discord_bot_max_turn_seconds_spin", _get(settings, "capture.bot_max_turn_seconds", 120))
        self._set_spin("discord_bot_idle_finalize_ms_spin", _get(settings, "capture.bot_idle_finalize_ms", 4500))
        self._set_checked("discord_ignore_low_information_checkbox", _get(settings, "capture.ignore_low_information_transcripts", True))
        self._set_spin("discord_low_information_max_seconds_spin", _get(settings, "capture.low_information_max_seconds", 2.0))
        self._set_text(
            "discord_low_information_transcripts_edit",
            ", ".join(str(item) for item in _get(settings, "capture.low_information_transcripts", []) or []),
        )
        self._set_combo("discord_wav_sample_rate_combo", str(_get(settings, "capture.wav_sample_rate", 16000)))
        self._set_combo("discord_wav_channels_combo", str(_get(settings, "capture.wav_channels", 1)))
        self._set_checked("discord_save_captures_checkbox", _get(settings, "capture.save_captures", True))
        self._set_checked("discord_shared_capture_owner_checkbox", _get(settings, "capture.shared_capture_owner_enabled", True))
        self._set_spin("discord_capture_owner_ttl_spin", _get(settings, "capture.owner_ttl_seconds", 8.0))

        self._set_checked("discord_play_test_tone_checkbox", _get(settings, "playback.play_test_tone_on_join", False))
        self._set_checked("discord_queue_replies_checkbox", _get(settings, "playback.queue_replies", True))
        self._set_checked("discord_interrupt_reply_checkbox", _get(settings, "playback.interrupt_reply_on_user_speech", True))
        self._set_spin("discord_interrupt_after_seconds_spin", _get(settings, "playback.interrupt_after_seconds", 4.0))
        self._set_spin("discord_reply_immunity_seconds_spin", _get(settings, "playback.reply_immunity_seconds", 4.0))
        self._set_checked(
            "discord_discard_bot_speech_checkbox",
            _get(settings, "playback.discard_bot_speech_on_human_intervention", True),
        )
        self._set_checked("discord_coordinate_bot_replies_checkbox", _get(settings, "playback.coordinate_bot_replies", True))
        self._set_spin("discord_reply_floor_stale_seconds_spin", _get(settings, "playback.reply_floor_stale_seconds", 180.0))
        self._set_spin("discord_initial_buffer_chunks_spin", _get(settings, "playback.initial_buffer_chunks", 2))

        self._set_checked("discord_filter_enabled_checkbox", _get(settings, "response_filter.enabled", False))
        self._set_combo("discord_filter_mode_combo", _get(settings, "response_filter.mode", "llm_sentinel"))
        self._set_text("discord_bot_names_edit", _get(settings, "response_filter.bot_names", "Neural Companion, NC, Companion"))
        self._set_checked("discord_answer_uncertain_checkbox", _get(settings, "response_filter.default_when_uncertain", True))
        self._set_checked("discord_room_router_enabled_checkbox", _get(settings, "room_router.enabled", True))
        self._set_combo("discord_room_router_mode_combo", _get(settings, "room_router.mode", "llm_router"))
        self._set_checked("discord_room_router_human_to_bot_checkbox", _get(settings, "room_router.human_to_bot_routing", True))
        self._set_checked("discord_room_router_bot_to_bot_checkbox", _get(settings, "room_router.bot_to_bot_routing", True))
        self._set_checked("discord_room_router_exclude_speaker_checkbox", _get(settings, "room_router.exclude_speaker_from_targets", True))
        self._set_checked("discord_room_router_group_invite_checkbox", _get(settings, "room_router.allow_group_invitation_routing", True))
        self._set_checked("discord_room_router_open_room_checkbox", _get(settings, "room_router.allow_open_room_invitation_routing", True))
        self._set_combo("discord_room_router_self_route_combo", _get(settings, "room_router.self_route_policy", "ignore"))
        self._set_checked("discord_room_router_uncertain_checkbox", _get(settings, "room_router.default_when_uncertain", True))
        self._set_combo("discord_room_router_uncertain_target_combo", _get(settings, "room_router.uncertain_fallback_target", "self"))
        self._set_spin("discord_room_router_decision_timeout_spin", _get(settings, "room_router.decision_timeout_seconds", 20.0))
        self._set_spin("discord_room_router_decision_tokens_spin", _get(settings, "room_router.decision_max_tokens", 2048))
        self._set_spin("discord_room_router_route_window_spin", _get(settings, "room_router.route_window_ms", 4000))
        self._set_checked("discord_room_router_text_routing_checkbox", _get(settings, "room_router.route_bot_replies_from_text", True))
        self._set_checked("discord_room_router_prebuffer_checkbox", _get(settings, "room_router.prepare_bot_replies_ahead", True))
        self._set_combo("discord_room_router_competing_policy_combo", _get(settings, "room_router.competing_bot_reply_policy", "first_ready_wins"))
        self._set_combo("discord_room_router_floor_mode_combo", _get(settings, "room_router.reply_floor_mode", "first_ready_wins"))
        self._set_checked("discord_dead_air_enabled_checkbox", _get(settings, "room_router.dead_air_recovery.enabled", False))
        self._set_spin("discord_dead_air_cooldown_spin", _get(settings, "room_router.dead_air_recovery.cooldown_seconds", 0.0))
        self._set_spin("discord_dead_air_silence_timeout_spin", _get(settings, "room_router.dead_air_recovery.silence_timeout_seconds", 10.0))
        self._set_combo("discord_dead_air_trigger_combo", _get(settings, "room_router.dead_air_recovery.trigger_mode", "no_route_after_bot_speech"))
        self._set_combo("discord_dead_air_action_combo", _get(settings, "room_router.dead_air_recovery.action_mode", "moderator_speaks_and_calls_next"))
        self._set_combo("discord_dead_air_strategy_combo", _get(settings, "room_router.dead_air_recovery.next_speaker_strategy", "llm_choose"))
        self._set_combo_text("discord_dead_air_fallback_target_combo", _get(settings, "room_router.dead_air_recovery.selected_fallback_target", ""))
        self._set_spin("discord_room_router_poll_ms_spin", _get(settings, "room_router.routed_text_poll_ms", 250))
        self._set_spin("discord_room_router_text_age_spin", _get(settings, "room_router.routed_text_max_age_seconds", 30.0))
        self._set_plain_text("discord_room_router_rules_prompt_edit", _get(settings, "room_router.router_rules_prompt", ""))

        self._set_checked("discord_replace_nc_prompt_checkbox", _get(settings, "persona.replace_nc_system_prompt", False))
        self._set_plain_text("discord_persona_prompt_edit", _get(settings, "persona.system_prompt", ""))
        self._set_text("discord_voice_clone_wav_edit", _get(settings, "persona.voice_clone_wav", ""))

        self._bots_model = copy.deepcopy(_get(settings, "bots", []) or [])
        if not isinstance(self._bots_model, list):
            self._bots_model = []
        self._refresh_bot_list()
        self._sync_bots_json_editor()

        self._set_text("discord_runtime_host_edit", _get(settings, "nc_runtime.host", "127.0.0.1"))
        self._set_spin("discord_runtime_port_spin", _get(settings, "nc_runtime.port", 8768))
        self._set_combo("discord_session_mode_combo", _get(settings, "nc_runtime.session_mode", "isolated_discord"))
        runtime_host = self._text("discord_runtime_host_edit", "127.0.0.1") or "127.0.0.1"
        runtime_port = int(self._spin_value("discord_runtime_port_spin", 8768))
        self._set_text("discord_runtime_http_endpoint_edit", _get(settings, "nc_runtime.http_endpoint", f"http://{runtime_host}:{runtime_port}/turn"))
        self._set_text("discord_runtime_ws_endpoint_edit", _get(settings, "nc_runtime.endpoint", f"ws://{runtime_host}:{runtime_port}/discord-voice"))
        self._set_checked("discord_use_selected_stt_checkbox", _get(settings, "nc_runtime.use_selected_stt", True))
        self._set_checked("discord_use_selected_chat_checkbox", _get(settings, "nc_runtime.use_selected_chat_provider", True))
        self._set_checked("discord_use_selected_tts_checkbox", _get(settings, "nc_runtime.use_selected_tts", True))
        self._set_checked("discord_allow_non_localhost_checkbox", _get(settings, "nc_runtime.allow_non_localhost", False))
        self._set_checked("discord_use_rag_context_checkbox", _get(settings, "chat.use_selected_rag_context", True))
        self._set_text(
            "discord_rag_status_label",
            "Discord turns can use NC RAG Context when this is enabled and the RAG addon is active.",
        )

        self._set_spin("discord_wav_max_age_minutes_spin", _get(settings, "cleanup.wav_max_age_minutes", 60.0))
        self._set_spin("discord_cleanup_interval_minutes_spin", _get(settings, "cleanup.interval_minutes", 10.0))

    def save_settings(self) -> bool:
        try:
            updates = self._collect_settings()
            save_local_settings(updates, allow_secret_updates=True)
            self._set_status("Settings saved to local ignored settings file.")
            return True
        except Exception as exc:
            self._show_warning("Discord Voice Bridge", f"Could not save settings: {exc}")
            return False

    def _persist_start_on_launch_setting(self, checked: bool) -> None:
        try:
            save_local_settings({"start_on_nc_launch": bool(checked)})
            self._set_status("Start on NC launch setting saved.")
        except Exception as exc:
            self._show_warning("Discord Voice Bridge", f"Could not save Start on NC launch: {exc}")

    def refresh_status(self):
        status = {}
        try:
            status = self.addon.status_snapshot()
        except Exception as exc:
            status = {"status": "error", "error": str(exc), "instances": []}
        instances = list(status.get("instances") or [])
        self._last_instances = instances
        connected = sum(1 for item in instances if item.get("runtime_connected"))
        endpoints = sum(1 for item in instances if item.get("endpoint_running"))
        self._set_status(f"Status: {status.get('status', 'unknown')} | Node: {connected}/{len(instances)} | Endpoint: {endpoints}/{len(instances)}")
        self._refresh_validation_summary()
        self._refresh_live_bot_combo(instances)
        self._refresh_moderator_controls(instances)
        self._refresh_instances_table(instances)
        self._refresh_status_progress(instances)
        self._refresh_logs()

    def _collect_controls(self, widget):
        self.controls.clear()
        for child in widget.findChildren(QtWidgets.QWidget):
            name = str(child.objectName() or "")
            if name:
                self.controls[name] = child

    def _build_tiny_mvp_controls(self):
        tab = self.controls.get("discord_bridge_general_tab")
        if not isinstance(tab, QtWidgets.QWidget) or tab.findChild(QtWidgets.QWidget, "discord_tiny_mvp_group") is not None:
            return
        layout = tab.layout()
        if not isinstance(layout, QtWidgets.QVBoxLayout):
            return

        group = QtWidgets.QGroupBox("TinyMVP Local Room", tab)
        group.setObjectName("discord_tiny_mvp_group")
        group.setToolTip("Settings used only when Bridge mode is TinyMVP. This launches a local fake voice-room bridge instead of the Discord Node bridge.")
        form = QtWidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        url = QtWidgets.QLineEdit(group)
        url.setObjectName("discord_tiny_mvp_url_edit")
        url.setPlaceholderText("http://127.0.0.1:8788")
        form.addRow("TinyMVP room URL", url)

        start_gui = QtWidgets.QCheckBox("Open TinyMVP monitor window", group)
        start_gui.setObjectName("discord_tiny_mvp_start_with_gui_checkbox")
        form.addRow("Start With GUI", start_gui)

        script = QtWidgets.QLineEdit(group)
        script.setObjectName("discord_tiny_mvp_bridge_script_edit")
        script.setPlaceholderText("leave blank for sibling TinyMVP\\tiny_voice_bridge.py")
        form.addRow("Bridge script", script)

        poll = QtWidgets.QDoubleSpinBox(group)
        poll.setObjectName("discord_tiny_mvp_poll_seconds_spin")
        poll.setRange(0.05, 5.0)
        poll.setDecimals(2)
        poll.setSingleStep(0.05)
        form.addRow("Poll interval (s)", poll)

        capture = QtWidgets.QCheckBox("Use NC microphone input", group)
        capture.setObjectName("discord_tiny_mvp_capture_mic_checkbox")
        form.addRow("Microphone", capture)

        mic_user_id = QtWidgets.QLineEdit(group)
        mic_user_id.setObjectName("discord_tiny_mvp_mic_user_id_edit")
        mic_user_id.setPlaceholderText("rakila")
        form.addRow("Mic user ID", mic_user_id)

        mic_user_name = QtWidgets.QLineEdit(group)
        mic_user_name.setObjectName("discord_tiny_mvp_mic_user_name_edit")
        mic_user_name.setPlaceholderText("Rakila")
        form.addRow("Mic user name", mic_user_name)

        mic_seconds = QtWidgets.QDoubleSpinBox(group)
        mic_seconds.setObjectName("discord_tiny_mvp_mic_seconds_spin")
        mic_seconds.setRange(0.5, 60.0)
        mic_seconds.setDecimals(1)
        mic_seconds.setSingleStep(0.5)
        form.addRow("Max phrase seconds", mic_seconds)

        mic_rate = QtWidgets.QSpinBox(group)
        mic_rate.setObjectName("discord_tiny_mvp_mic_sample_rate_spin")
        mic_rate.setRange(8000, 48000)
        mic_rate.setSingleStep(1000)
        form.addRow("Mic sample rate", mic_rate)

        mic_device = QtWidgets.QLineEdit(group)
        mic_device.setObjectName("discord_tiny_mvp_mic_device_edit")
        mic_device.setPlaceholderText("optional microphone name or index")
        form.addRow("Mic device", mic_device)

        layout.insertWidget(1, group)

    def _build_bot_editor(self):
        tab = self.controls.get("discord_bridge_bots_tab")
        if not isinstance(tab, QtWidgets.QWidget) or tab.findChild(QtWidgets.QWidget, "discord_bot_editor_group") is not None:
            return
        layout = tab.layout()
        if not isinstance(layout, QtWidgets.QVBoxLayout):
            return

        group = QtWidgets.QGroupBox("Bot Instances", tab)
        group.setObjectName("discord_bot_editor_group")
        group.setToolTip("Structured editor for Discord bot instances. Use Advanced JSON below only for unusual overrides.")
        outer = QtWidgets.QVBoxLayout(group)
        outer.setContentsMargins(10, 10, 10, 10)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, group)
        splitter.setObjectName("discord_bot_editor_splitter")
        outer.addWidget(splitter)

        list_panel = QtWidgets.QWidget(splitter)
        list_layout = QtWidgets.QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 6, 0)
        bot_list = QtWidgets.QListWidget(list_panel)
        bot_list.setObjectName("discord_bot_list")
        bot_list.setMinimumWidth(180)
        bot_list.setToolTip("Configured Discord bot instances. Select one to edit its settings.")
        list_layout.addWidget(bot_list, 1)
        list_buttons = QtWidgets.QHBoxLayout()
        add_button = QtWidgets.QPushButton("Add New Bot", list_panel)
        add_button.setObjectName("discord_bot_add_button")
        duplicate_button = QtWidgets.QPushButton("Duplicate Bot", list_panel)
        duplicate_button.setObjectName("discord_bot_duplicate_button")
        remove_button = QtWidgets.QPushButton("Remove", list_panel)
        remove_button.setObjectName("discord_bot_remove_button")
        list_buttons.addWidget(add_button)
        list_buttons.addWidget(duplicate_button)
        list_buttons.addWidget(remove_button)
        list_layout.addLayout(list_buttons)
        remove_all_context_button = QtWidgets.QPushButton("Remove All Bot Context", list_panel)
        remove_all_context_button.setObjectName("discord_bot_remove_all_context_button")
        list_layout.addWidget(remove_all_context_button)
        splitter.addWidget(list_panel)

        form_panel = QtWidgets.QWidget(splitter)
        form_layout = QtWidgets.QVBoxLayout(form_panel)
        form_layout.setContentsMargins(6, 0, 0, 0)
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form_layout.addLayout(form)

        enabled = QtWidgets.QCheckBox(form_panel)
        enabled.setObjectName("discord_bot_enabled_checkbox")
        form.addRow("Enabled", enabled)

        for label, name, placeholder in (
            ("Bot ID", "discord_bot_id_edit", "echo"),
            ("Display name", "discord_bot_display_name_edit", "Echo"),
            ("Token env var", "discord_bot_token_env_edit", "DISCORD_TOKEN_ECHO"),
            ("Guild override", "discord_bot_guild_id_edit", "optional guild/server ID"),
            ("Voice channel override", "discord_bot_voice_channel_id_edit", "optional voice channel ID"),
            ("Call names", "discord_bot_call_names_edit", "Echo, NC, Companion"),
            ("Voice clone WAV", "discord_bot_voice_clone_wav_edit", "echo.wav"),
        ):
            edit = QtWidgets.QLineEdit(form_panel)
            edit.setObjectName(name)
            edit.setPlaceholderText(placeholder)
            form.addRow(label, edit)

        token = QtWidgets.QLineEdit(form_panel)
        token.setObjectName("discord_bot_local_token_edit")
        token.setEchoMode(QtWidgets.QLineEdit.Password)
        token.setPlaceholderText("leave blank to keep existing local token")
        form.addRow("Local token", token)

        port = QtWidgets.QSpinBox(form_panel)
        port.setObjectName("discord_bot_runtime_port_spin")
        port.setRange(1, 65535)
        form.addRow("Runtime port", port)

        context_entries = QtWidgets.QSpinBox(form_panel)
        context_entries.setObjectName("discord_bot_context_entries_spin")
        context_entries.setRange(1, 1000)
        form.addRow("Context entries", context_entries)

        use_global_chat = QtWidgets.QCheckBox(form_panel)
        use_global_chat.setObjectName("discord_bot_use_global_chat_model_checkbox")
        form.addRow("Use global chat model", use_global_chat)

        chat_provider = QtWidgets.QComboBox(form_panel)
        chat_provider.setObjectName("discord_bot_chat_provider_combo")
        form.addRow("Chat provider", chat_provider)

        chat_model_row = QtWidgets.QHBoxLayout()
        chat_model = QtWidgets.QComboBox(form_panel)
        chat_model.setObjectName("discord_bot_chat_model_combo")
        chat_model.setEditable(True)
        chat_model.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        chat_refresh = QtWidgets.QPushButton("Refresh", form_panel)
        chat_refresh.setObjectName("discord_bot_chat_model_refresh_button")
        chat_model_row.addWidget(chat_model, 1)
        chat_model_row.addWidget(chat_refresh)
        form.addRow("LLM model", chat_model_row)

        replace_prompt = QtWidgets.QCheckBox(form_panel)
        replace_prompt.setObjectName("discord_bot_replace_nc_prompt_checkbox")
        form.addRow("Replace NC prompt", replace_prompt)

        persona = QtWidgets.QPlainTextEdit(form_panel)
        persona.setObjectName("discord_bot_persona_prompt_edit")
        persona.setMinimumHeight(110)
        persona.setPlaceholderText("Per-bot persona/system prompt. Leave blank to inherit the global Discord persona.")
        form.addRow("Persona prompt", persona)

        load_json_button = QtWidgets.QPushButton("Load From JSON", form_panel)
        load_json_button.setObjectName("discord_bot_load_json_button")
        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(load_json_button)
        action_row.addStretch(1)
        form_layout.addLayout(action_row)

        splitter.addWidget(form_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.insertWidget(1, group)

        bot_list.currentRowChanged.connect(self._on_bot_selected)
        add_button.clicked.connect(self._add_structured_bot)
        duplicate_button.clicked.connect(self._duplicate_structured_bot)
        remove_button.clicked.connect(self._remove_selected_bot)
        remove_all_context_button.clicked.connect(self._remove_all_bot_context)
        chat_refresh.clicked.connect(self._refresh_current_bot_chat_models)
        load_json_button.clicked.connect(self._load_bots_from_json_editor)

    def _build_room_router_controls(self):
        tab = self.controls.get("discord_bridge_filter_tab")
        if not isinstance(tab, QtWidgets.QWidget) or tab.findChild(QtWidgets.QWidget, "discord_room_router_group") is not None:
            return
        layout = tab.layout()
        if not isinstance(layout, QtWidgets.QVBoxLayout):
            return

        group = QtWidgets.QGroupBox("Shared Room Router", tab)
        group.setObjectName("discord_room_router_group")
        outer = QtWidgets.QVBoxLayout(group)
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        outer.addLayout(form)

        def add_row(label: str, control: QtWidgets.QWidget) -> None:
            label_widget = QtWidgets.QLabel(label, group)
            label_widget.setObjectName(f"{control.objectName()}_label")
            form.addRow(label_widget, control)

        for label, name in (
            ("Enable shared room router", "discord_room_router_enabled_checkbox"),
            ("Route human speech to bots", "discord_room_router_human_to_bot_checkbox"),
            ("Route bot speech to bots", "discord_room_router_bot_to_bot_checkbox"),
            ("Exclude speaker from targets", "discord_room_router_exclude_speaker_checkbox"),
            ("Route group bot invitations", "discord_room_router_group_invite_checkbox"),
            ("Route open-room invitations", "discord_room_router_open_room_checkbox"),
            ("Route bot replies from text", "discord_room_router_text_routing_checkbox"),
            ("Prepare routed bot replies ahead", "discord_room_router_prebuffer_checkbox"),
        ):
            checkbox = QtWidgets.QCheckBox(group)
            checkbox.setObjectName(name)
            add_row(label, checkbox)

        for label, name in (
            ("Router mode", "discord_room_router_mode_combo"),
            ("Self-route policy", "discord_room_router_self_route_combo"),
            ("Uncertain fallback target", "discord_room_router_uncertain_target_combo"),
            ("Competing bot reply policy", "discord_room_router_competing_policy_combo"),
            ("Reply floor mode", "discord_room_router_floor_mode_combo"),
        ):
            combo = QtWidgets.QComboBox(group)
            combo.setObjectName(name)
            add_row(label, combo)

        uncertain = QtWidgets.QCheckBox(group)
        uncertain.setObjectName("discord_room_router_uncertain_checkbox")
        add_row("Answer when uncertain", uncertain)

        for label, name, minimum, maximum, decimals in (
            ("Router decision timeout (s)", "discord_room_router_decision_timeout_spin", 1.0, 120.0, 1),
            ("Routed text max age (s)", "discord_room_router_text_age_spin", 1.0, 600.0, 1),
        ):
            spin = QtWidgets.QDoubleSpinBox(group)
            spin.setObjectName(name)
            spin.setRange(minimum, maximum)
            spin.setDecimals(decimals)
            add_row(label, spin)

        for label, name, minimum, maximum in (
            ("Router decision max tokens", "discord_room_router_decision_tokens_spin", 80, 4096),
            ("Route grouping window (ms)", "discord_room_router_route_window_spin", 500, 30000),
            ("Routed text poll interval (ms)", "discord_room_router_poll_ms_spin", 100, 5000),
        ):
            spin = QtWidgets.QSpinBox(group)
            spin.setObjectName(name)
            spin.setRange(minimum, maximum)
            add_row(label, spin)

        prompt = QtWidgets.QPlainTextEdit(group)
        prompt.setObjectName("discord_room_router_rules_prompt_edit")
        prompt.setMinimumHeight(120)
        prompt.setPlaceholderText("Leave blank to use the built-in transparent router rules.")
        add_row("Router rules prompt", prompt)

        layout.addWidget(group)

    def _build_advanced_visibility_controls(self):
        self._advanced_control_groups.clear()
        self._add_advanced_toggle(
            tab_name="discord_bridge_capture_tab",
            button_name="discord_capture_advanced_toggle",
            button_text="Show Advanced Capture Settings",
            control_names=[
                "shared_capture_owner_label",
                "discord_shared_capture_owner_checkbox",
                "capture_owner_ttl_label",
                "discord_capture_owner_ttl_spin",
            ],
        )
        self._add_advanced_toggle(
            tab_name="discord_bridge_playback_tab",
            button_name="discord_playback_advanced_toggle",
            button_text="Show Advanced Speaker Coordination",
            control_names=[
                "discard_bot_label",
                "discord_discard_bot_speech_checkbox",
                "coordinate_label",
                "discord_coordinate_bot_replies_checkbox",
                "floor_stale_label",
                "discord_reply_floor_stale_seconds_spin",
            ],
        )
        self._add_advanced_toggle(
            tab_name="discord_bridge_filter_tab",
            button_name="discord_router_advanced_toggle",
            button_text="Show Advanced Router Policy",
            control_names=[
                "discord_room_router_exclude_speaker_checkbox_label",
                "discord_room_router_exclude_speaker_checkbox",
                "discord_room_router_group_invite_checkbox_label",
                "discord_room_router_group_invite_checkbox",
                "discord_room_router_open_room_checkbox_label",
                "discord_room_router_open_room_checkbox",
                "discord_room_router_text_routing_checkbox_label",
                "discord_room_router_text_routing_checkbox",
                "discord_room_router_prebuffer_checkbox_label",
                "discord_room_router_prebuffer_checkbox",
                "discord_room_router_self_route_combo_label",
                "discord_room_router_self_route_combo",
                "discord_room_router_uncertain_target_combo_label",
                "discord_room_router_uncertain_target_combo",
                "discord_room_router_competing_policy_combo_label",
                "discord_room_router_competing_policy_combo",
                "discord_room_router_floor_mode_combo_label",
                "discord_room_router_floor_mode_combo",
                "discord_room_router_uncertain_checkbox_label",
                "discord_room_router_uncertain_checkbox",
                "discord_room_router_decision_timeout_spin_label",
                "discord_room_router_decision_timeout_spin",
                "discord_room_router_text_age_spin_label",
                "discord_room_router_text_age_spin",
                "discord_room_router_decision_tokens_spin_label",
                "discord_room_router_decision_tokens_spin",
                "discord_room_router_route_window_spin_label",
                "discord_room_router_route_window_spin",
                "discord_room_router_poll_ms_spin_label",
                "discord_room_router_poll_ms_spin",
                "discord_room_router_rules_prompt_edit_label",
                "discord_room_router_rules_prompt_edit",
            ],
        )

    def _add_advanced_toggle(self, *, tab_name: str, button_name: str, button_text: str, control_names: list[str]):
        tab = self.controls.get(tab_name)
        if not isinstance(tab, QtWidgets.QWidget) or tab.findChild(QtWidgets.QWidget, button_name) is not None:
            self._advanced_control_groups[button_name] = control_names
            self._set_advanced_controls_visible(button_name, False)
            return
        layout = tab.layout()
        if not isinstance(layout, QtWidgets.QVBoxLayout):
            return
        button = QtWidgets.QPushButton(button_text, tab)
        button.setObjectName(button_name)
        button.setCheckable(True)
        button.setToolTip("Show rarely changed Discord bridge settings for troubleshooting or unusual multi-bot rooms.")
        layout.addWidget(button)
        self.controls[button_name] = button
        self._advanced_control_groups[button_name] = control_names
        button.toggled.connect(lambda checked, name=button_name: self._set_advanced_controls_visible(name, checked))
        self._set_advanced_controls_visible(button_name, False)

    def _set_advanced_controls_visible(self, button_name: str, visible: bool):
        names = self._advanced_control_groups.get(button_name, [])
        for name in names:
            control = self.controls.get(name)
            if control is not None:
                control.setVisible(bool(visible))
        button = self._control(button_name, QtWidgets.QPushButton)
        if button is not None:
            label = str(button.text() or "")
            if visible and label.startswith("Show "):
                button.setText("Hide " + label.removeprefix("Show "))
            elif not visible and label.startswith("Hide "):
                button.setText("Show " + label.removeprefix("Hide "))

    def _hide_deprecated_response_filter_controls(self):
        group = self._control("discord_bridge_filter_group", QtWidgets.QGroupBox)
        if group is not None:
            group.setVisible(False)

    def _build_runtime_endpoint_fields(self):
        tab = self.controls.get("discord_bridge_runtime_tab")
        if not isinstance(tab, QtWidgets.QWidget) or tab.findChild(QtWidgets.QWidget, "discord_runtime_http_endpoint_edit") is not None:
            return
        group = tab.findChild(QtWidgets.QGroupBox, "discord_bridge_runtime_group")
        form = group.layout() if isinstance(group, QtWidgets.QGroupBox) else None
        if not isinstance(form, QtWidgets.QFormLayout):
            return
        for label, name in (
            ("HTTP turn endpoint", "discord_runtime_http_endpoint_edit"),
            ("Bridge endpoint", "discord_runtime_ws_endpoint_edit"),
        ):
            edit = QtWidgets.QLineEdit(group)
            edit.setObjectName(name)
            edit.setReadOnly(True)
            form.addRow(label, edit)

    def _build_status_actions(self):
        tab = self.controls.get("discord_bridge_status_tab")
        if not isinstance(tab, QtWidgets.QWidget) or tab.findChild(QtWidgets.QWidget, "discord_status_actions_group") is not None:
            return
        layout = tab.layout()
        if not isinstance(layout, QtWidgets.QVBoxLayout):
            return
        group = QtWidgets.QGroupBox("Diagnostics", tab)
        group.setObjectName("discord_status_actions_group")
        row = QtWidgets.QHBoxLayout(group)
        restart_tone = QtWidgets.QPushButton("Play Test Tone On Restart", group)
        restart_tone.setObjectName("discord_test_tone_restart_button")
        validate = QtWidgets.QPushButton("Validate Settings", group)
        validate.setObjectName("discord_validate_settings_button")
        install_deps = QtWidgets.QPushButton("Install / Update Node Deps", group)
        install_deps.setObjectName("discord_install_node_deps_button")
        copy_diagnostics = QtWidgets.QPushButton("Copy Diagnostics", group)
        copy_diagnostics.setObjectName("discord_copy_diagnostics_button")
        open_logs = QtWidgets.QPushButton("Open Logs Folder", group)
        open_logs.setObjectName("discord_open_logs_button")
        row.addWidget(validate)
        row.addWidget(install_deps)
        row.addWidget(copy_diagnostics)
        row.addWidget(restart_tone)
        row.addWidget(open_logs)
        row.addStretch(1)
        layout.insertWidget(0, group)
        validate.clicked.connect(self._validate_settings_clicked)
        install_deps.clicked.connect(self._install_node_dependencies)
        copy_diagnostics.clicked.connect(self._copy_diagnostics)
        restart_tone.clicked.connect(self._restart_with_test_tone)
        open_logs.clicked.connect(self._open_logs_folder)

    def _build_live_controls(self):
        tab = self.controls.get("discord_bridge_status_tab")
        if not isinstance(tab, QtWidgets.QWidget) or tab.findChild(QtWidgets.QWidget, "discord_live_controls_group") is not None:
            return
        layout = tab.layout()
        if not isinstance(layout, QtWidgets.QVBoxLayout):
            return

        group = QtWidgets.QGroupBox("Per-Bot Live Controls", tab)
        group.setObjectName("discord_live_controls_group")
        outer = QtWidgets.QVBoxLayout(group)

        selector_row = QtWidgets.QHBoxLayout()
        selector_row.addWidget(QtWidgets.QLabel("Bot", group))
        combo = QtWidgets.QComboBox(group)
        combo.setObjectName("discord_live_bot_combo")
        combo.setMinimumWidth(220)
        selector_row.addWidget(combo, 1)
        state_label = QtWidgets.QLabel("No running bot selected.", group)
        state_label.setObjectName("discord_live_bot_state_label")
        state_label.setWordWrap(True)
        state_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        selector_row.addWidget(state_label, 2)
        outer.addLayout(selector_row)

        process_row = QtWidgets.QHBoxLayout()
        for text, name in (
            ("Start", "discord_live_start_button"),
            ("Stop", "discord_live_stop_button"),
            ("Restart", "discord_live_restart_button"),
            ("Disconnect", "discord_live_disconnect_button"),
            ("Reconnect", "discord_live_reconnect_button"),
        ):
            button = QtWidgets.QPushButton(text, group)
            button.setObjectName(name)
            process_row.addWidget(button)
        process_row.addStretch(1)
        outer.addLayout(process_row)

        runtime_row = QtWidgets.QHBoxLayout()
        for text, name in (
            ("Stop Speech", "discord_live_stop_speech_button"),
            ("Clear Queue", "discord_live_clear_queue_button"),
            ("Reset Context", "discord_live_reset_context_button"),
            ("Apply Selected Bot", "discord_live_apply_selected_button"),
            ("Apply Global Live Settings", "discord_live_apply_global_button"),
            ("Apply All Live Settings", "discord_live_apply_all_button"),
        ):
            button = QtWidgets.QPushButton(text, group)
            button.setObjectName(name)
            runtime_row.addWidget(button)
        runtime_row.addStretch(1)
        outer.addLayout(runtime_row)

        message_row = QtWidgets.QHBoxLayout()
        message_row.addWidget(QtWidgets.QLabel("Message", group))
        message_edit = QtWidgets.QLineEdit(group)
        message_edit.setObjectName("discord_live_message_edit")
        message_edit.setPlaceholderText("Text to speak through the selected bot...")
        send_message = QtWidgets.QPushButton("Send Message", group)
        send_message.setObjectName("discord_live_send_message_button")
        message_row.addWidget(message_edit, 1)
        message_row.addWidget(send_message)
        outer.addLayout(message_row)

        note = QtWidgets.QLabel(
            "Selected Bot pushes persona, voice, and context for the chosen bot. Global pushes shared routing, playback, capture, and cleanup to all running bots. "
            "All pushes every live-safe setting to all running bots. Token environment variables, runtime ports, guilds, and voice channels require restart or reconnect.",
            group,
        )
        note.setObjectName("discord_live_restart_hint_label")
        note.setWordWrap(True)
        outer.addWidget(note)

        layout.insertWidget(1, group)

    def _build_moderator_controls(self):
        tabs = self._control("discord_bridge_settings_tabs", QtWidgets.QTabWidget)
        if tabs is None or tabs.findChild(QtWidgets.QWidget, "discord_bridge_moderator_tab") is not None:
            return
        tab = QtWidgets.QWidget(tabs)
        tab.setObjectName("discord_bridge_moderator_tab")
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        group = QtWidgets.QGroupBox("Moderator", tab)
        group.setObjectName("discord_moderator_group")
        group.setToolTip(
            "Manual routing controls for a human moderator. Commands are queued through running bot processes and bypass the LLM router where active."
        )
        outer = QtWidgets.QVBoxLayout(group)

        target_row = QtWidgets.QHBoxLayout()
        target_row.addWidget(QtWidgets.QLabel("Selected bot target", group))
        target_combo = QtWidgets.QComboBox(group)
        target_combo.setObjectName("discord_moderator_target_combo")
        target_combo.setMinimumWidth(260)
        target_row.addWidget(target_combo, 1)
        state_label = QtWidgets.QLabel("Moderator state appears after a bot is running.", group)
        state_label.setObjectName("discord_moderator_state_label")
        state_label.setWordWrap(True)
        state_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        target_row.addWidget(state_label, 2)
        outer.addLayout(target_row)

        enforcer_row = QtWidgets.QHBoxLayout()
        enforcer_button = QtWidgets.QPushButton("Use Selected As Moderator Bot", group)
        enforcer_button.setObjectName("discord_moderator_set_enforcer_button")
        clear_enforcer_button = QtWidgets.QPushButton("Clear Moderator Bot", group)
        clear_enforcer_button.setObjectName("discord_moderator_clear_enforcer_button")
        enforce_mute_checkbox = QtWidgets.QCheckBox("Enforce Current With Discord Mute", group)
        enforce_mute_checkbox.setObjectName("discord_moderator_enforce_mute_checkbox")
        enforcer_row.addWidget(enforcer_button)
        enforcer_row.addWidget(clear_enforcer_button)
        enforcer_row.addWidget(enforce_mute_checkbox)
        enforcer_row.addStretch(1)
        outer.addLayout(enforcer_row)

        flow_group = QtWidgets.QGroupBox("Now / Next / Speaker Control", group)
        flow_group.setObjectName("discord_moderator_flow_group")
        flow_group.setToolTip("Plain-language debate flow summary for the human moderator.")
        flow_layout = QtWidgets.QGridLayout(flow_group)
        flow_items = (
            ("Now", "discord_moderator_now_label"),
            ("Next", "discord_moderator_next_label"),
            ("Badges", "discord_moderator_badges_label"),
            ("Speaker lock", "discord_moderator_bot_floor_label"),
            ("Speaker rule", "discord_moderator_human_floor_label"),
            ("Last command", "discord_moderator_last_command_label"),
            ("Last route", "discord_moderator_last_route_label"),
            ("Selected action", "discord_moderator_selected_action_label"),
            ("Warning", "discord_moderator_warning_label"),
            ("What happens next", "discord_moderator_next_action_label"),
        )
        for row, (caption, name) in enumerate(flow_items):
            title = QtWidgets.QLabel(f"{caption}:", flow_group)
            title.setObjectName(f"{name}_title")
            value = QtWidgets.QLabel("unknown", flow_group)
            value.setObjectName(name)
            value.setWordWrap(True)
            if name == "discord_moderator_badges_label":
                value.setTextFormat(QtCore.Qt.RichText)
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            flow_layout.addWidget(title, row, 0)
            flow_layout.addWidget(value, row, 1)
        flow_layout.setColumnStretch(1, 1)
        outer.addWidget(flow_group)

        route_flow_group = QtWidgets.QGroupBox("Route Flow", group)
        route_flow_group.setObjectName("discord_moderator_route_flow_group")
        route_flow_group.setToolTip("Shared chronological route path for the room. This is the authoritative debate flow, separate from per-bot diagnostic Last Route cells.")
        route_flow_layout = QtWidgets.QVBoxLayout(route_flow_group)
        route_flow_view = QtWidgets.QPlainTextEdit(route_flow_group)
        route_flow_view.setObjectName("discord_moderator_route_flow_view")
        route_flow_view.setFixedHeight(180)
        route_flow_view.setReadOnly(True)
        route_flow_view.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        route_flow_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        route_flow_view.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
        route_flow_view.setToolTip("Route decisions appear here as the debate moves between participants.")
        route_flow_layout.addWidget(route_flow_view)
        outer.addWidget(route_flow_group)

        recovery_group = QtWidgets.QGroupBox("Dead-Air Recovery", group)
        recovery_group.setObjectName("discord_dead_air_group")
        recovery_group.setToolTip("Optional moderator intervention when a completed turn produces no next speaker.")
        recovery_form = QtWidgets.QFormLayout(recovery_group)
        recovery_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        def add_recovery_row(label: str, control: QtWidgets.QWidget) -> None:
            label_widget = QtWidgets.QLabel(label, recovery_group)
            label_widget.setObjectName(f"{control.objectName()}_label")
            recovery_form.addRow(label_widget, control)

        dead_air_enabled = QtWidgets.QCheckBox(recovery_group)
        dead_air_enabled.setObjectName("discord_dead_air_enabled_checkbox")
        add_recovery_row("Enable recovery", dead_air_enabled)

        dead_air_cooldown = QtWidgets.QDoubleSpinBox(recovery_group)
        dead_air_cooldown.setObjectName("discord_dead_air_cooldown_spin")
        dead_air_cooldown.setRange(0.0, 3600.0)
        dead_air_cooldown.setDecimals(1)
        add_recovery_row("Cooldown (s)", dead_air_cooldown)

        dead_air_silence_timeout = QtWidgets.QDoubleSpinBox(recovery_group)
        dead_air_silence_timeout.setObjectName("discord_dead_air_silence_timeout_spin")
        dead_air_silence_timeout.setRange(0.0, 3600.0)
        dead_air_silence_timeout.setDecimals(1)
        dead_air_silence_timeout.setSpecialValueText("Immediate")
        add_recovery_row("Silence timeout (s)", dead_air_silence_timeout)

        for label, name in (
            ("Trigger mode", "discord_dead_air_trigger_combo"),
            ("Action mode", "discord_dead_air_action_combo"),
            ("Next speaker strategy", "discord_dead_air_strategy_combo"),
            ("Fallback target", "discord_dead_air_fallback_target_combo"),
        ):
            combo = QtWidgets.QComboBox(recovery_group)
            combo.setObjectName(name)
            if name == "discord_dead_air_fallback_target_combo":
                combo.setEditable(True)
            add_recovery_row(label, combo)

        recovery_status = QtWidgets.QLabel("Recovery status appears after a running bot reports moderator state.", recovery_group)
        recovery_status.setObjectName("discord_dead_air_status_label")
        recovery_status.setWordWrap(True)
        recovery_status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        add_recovery_row("Status", recovery_status)
        outer.addWidget(recovery_group)

        shortcut_group = QtWidgets.QGroupBox("Quick Turn Choices", group)
        shortcut_group.setObjectName("discord_moderator_shortcuts_group")
        shortcut_group.setToolTip(
            "One-click choices for the next speaker. Safe next-turn choices wait for the current vocalization to finish; active calls are only enabled while the room is quiet."
        )
        shortcut_outer = QtWidgets.QVBoxLayout(shortcut_group)
        shortcut_hint = QtWidgets.QLabel(
            "Start the bridge to show safe next-speaker choices and quiet-room call buttons.",
            shortcut_group,
        )
        shortcut_hint.setObjectName("discord_moderator_shortcuts_hint_label")
        shortcut_hint.setWordWrap(True)
        shortcut_outer.addWidget(shortcut_hint)
        shortcut_container = QtWidgets.QWidget(shortcut_group)
        shortcut_container.setObjectName("discord_moderator_shortcuts_container")
        shortcut_layout = QtWidgets.QGridLayout(shortcut_container)
        shortcut_layout.setContentsMargins(0, 0, 0, 0)
        shortcut_layout.setSpacing(6)
        shortcut_outer.addWidget(shortcut_container)
        outer.addWidget(shortcut_group)

        table = QtWidgets.QTableWidget(group)
        table.setObjectName("discord_moderator_instances_table")
        table.setColumnCount(9)
        table.setHorizontalHeaderLabels(["ID", "Name", "Discord", "Speaking", "Listening", "Queued", "Render", "Playback", "Last Route"])
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setMinimumHeight(120)
        outer.addWidget(table)

        participants = QtWidgets.QTableWidget(group)
        participants.setObjectName("discord_moderator_participants_table")
        participants.setColumnCount(8)
        participants.setHorizontalHeaderLabels(["Participant ID", "Name", "Type", "Connected", "Speaking", "Listening", "Queued", "Moderator State"])
        participants.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        participants.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        participants.setMinimumHeight(100)
        participants.setToolTip("Unified room participants. Select a human or bot, then use the participant-aware moderator actions below.")
        participants.setColumnHidden(2, True)
        outer.addWidget(participants)

        route_row = QtWidgets.QHBoxLayout()
        for text, name in (
            ("Set Next Speaker", "discord_moderator_route_next_button"),
            ("Allow Only This Speaker", "discord_moderator_give_floor_button"),
            ("Mute Participant", "discord_moderator_mute_button"),
            ("Unmute Participant", "discord_moderator_unmute_button"),
            ("Clear Pending", "discord_moderator_clear_pending_button"),
            ("Clear Speaker Locks", "discord_moderator_clear_floor_button"),
            ("Clear All", "discord_moderator_clear_button"),
        ):
            button = QtWidgets.QPushButton(text, group)
            button.setObjectName(name)
            route_row.addWidget(button)
        route_row.addStretch(1)
        outer.addLayout(route_row)

        playback_row = QtWidgets.QHBoxLayout()
        for text, name in (
            ("Stop All Speech", "discord_moderator_stop_all_button"),
            ("Clear All Queues", "discord_moderator_clear_all_queues_button"),
        ):
            button = QtWidgets.QPushButton(text, group)
            button.setObjectName(name)
            playback_row.addWidget(button)
        interrupt_checkbox = QtWidgets.QCheckBox("Allow Interrupt Current", group)
        interrupt_checkbox.setObjectName("discord_moderator_allow_interrupt_current_checkbox")
        interrupt_checkbox.setToolTip("When off, moderator Current speaker cannot be interrupted by normal playback speech-interrupt rules.")
        playback_row.addWidget(interrupt_checkbox)
        protected_speech = QtWidgets.QCheckBox("Route protected mic speech", group)
        protected_speech.setObjectName("discord_route_protected_mic_speech_checkbox")
        protected_speech.setToolTip(
            "When Current is protected, still transcribe and route microphone speech into context without stopping playback or taking the floor."
        )
        playback_row.addWidget(protected_speech)
        playback_row.addStretch(1)
        outer.addLayout(playback_row)

        announce_row = QtWidgets.QHBoxLayout()
        announce_row.addWidget(QtWidgets.QLabel("Announcement", group))
        announce_edit = QtWidgets.QLineEdit(group)
        announce_edit.setObjectName("discord_moderator_announcement_edit")
        announce_edit.setPlaceholderText("Text to speak through the selected target bot...")
        announce_button = QtWidgets.QPushButton("Speak Through Target", group)
        announce_button.setObjectName("discord_moderator_announce_button")
        call_button = QtWidgets.QPushButton("Call Target Now", group)
        call_button.setObjectName("discord_moderator_call_on_button")
        announce_row.addWidget(announce_edit, 1)
        announce_row.addWidget(announce_button)
        announce_row.addWidget(call_button)
        outer.addLayout(announce_row)

        note = QtWidgets.QLabel(
            "Select any room participant. Set Next Speaker is one-shot: the selected participant becomes Next, then Current when the active speaker finishes. Allow Only This Speaker is persistent until cleared. Call Target Now is bot-only and only available while no bot is speaking.",
            group,
        )
        note.setObjectName("discord_moderator_note_label")
        note.setWordWrap(True)
        outer.addWidget(note)

        layout.addWidget(group)
        layout.addStretch(1)
        tabs.addTab(tab, "Moderator")
        self.controls["discord_bridge_moderator_tab"] = tab
        self._apply_tab_polish()

    def _build_validation_summary(self):
        tab = self.controls.get("discord_bridge_status_tab")
        if not isinstance(tab, QtWidgets.QWidget) or tab.findChild(QtWidgets.QWidget, "discord_validation_summary_group") is not None:
            return
        layout = tab.layout()
        if not isinstance(layout, QtWidgets.QVBoxLayout):
            return
        group = QtWidgets.QGroupBox("Validation Summary", tab)
        group.setObjectName("discord_validation_summary_group")
        group.setToolTip("Saved-setting validation summary. Press Save Settings first if you want this to reflect edited fields.")
        outer = QtWidgets.QVBoxLayout(group)
        label = QtWidgets.QLabel("Validation has not run yet.", group)
        label.setObjectName("discord_validation_summary_label")
        label.setWordWrap(True)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        outer.addWidget(label)
        layout.insertWidget(1, group)

    def _populate_choices(self):
        self._combo_items("discord_bridge_mode_combo", [("Mock", "mock"), ("HTTP / Discord", "http"), ("TinyMVP local room", "tiny_mvp")])
        self._combo_items("discord_answer_mode_combo", [("Allowed user only", "allowed_user_only"), ("Anyone", "anyone")])
        self._combo_items(
            "discord_filter_mode_combo",
            [("LLM sentinel", "llm_sentinel"), ("LLM judge", "llm_judge"), ("Mention or question", "mention_or_question")],
        )
        self._combo_items("discord_wav_sample_rate_combo", [("16000", "16000"), ("48000", "48000")])
        self._combo_items("discord_wav_channels_combo", [("Mono", "1"), ("Stereo", "2")])
        self._combo_items("discord_session_mode_combo", [("Isolated Discord", "isolated_discord")])
        self._combo_items("discord_room_router_mode_combo", [("LLM router", "llm_router"), ("Mention or question", "mention_or_question")])
        self._combo_items("discord_room_router_self_route_combo", [("Ignore", "ignore"), ("Allow", "allow"), ("Error", "error")])
        self._combo_items("discord_room_router_uncertain_target_combo", [("This bot", "self"), ("First candidate", "first_candidate"), ("Nobody", "none")])
        self._combo_items(
            "discord_room_router_competing_policy_combo",
            [("First ready wins", "first_ready_wins"), ("Queue", "queue"), ("Disabled", "disabled")],
        )
        self._combo_items(
            "discord_room_router_floor_mode_combo",
            [("First ready wins", "first_ready_wins"), ("Queue", "queue"), ("Disabled", "disabled")],
        )
        self._combo_items(
            "discord_dead_air_trigger_combo",
            [
                ("No route after bot speech only", "no_route_after_bot_speech"),
                ("No route after bot or human speech", "no_route_after_any_speech"),
            ],
        )
        self._combo_items(
            "discord_dead_air_action_combo",
            [
                ("Moderator speaks and calls next", "moderator_speaks_and_calls_next"),
                ("Moderator speaks only", "moderator_speaks_only"),
                ("Silent call next", "silent_call_next"),
            ],
        )
        self._combo_items(
            "discord_dead_air_strategy_combo",
            [("LLM chooses", "llm_choose"), ("Round robin", "round_robin"), ("Selected fallback", "selected_fallback")],
        )
        self._populate_bot_chat_provider_combo()

    def _connect_signals(self):
        self._button("discord_bridge_save_button", self.save_settings)
        start_on_launch = self._control("discord_start_on_launch_checkbox", QtWidgets.QCheckBox)
        if start_on_launch is not None:
            start_on_launch.clicked.connect(self._persist_start_on_launch_setting)
        self._button("discord_bridge_start_button", lambda: self._run_bridge_operation("start", self.addon.start_bridge_instances))
        self._button("discord_bridge_stop_button", lambda: self._run_bridge_operation("stop", self.addon.stop_bridge_instances))
        self._button("discord_bridge_restart_button", lambda: self._run_bridge_operation("restart", self.addon.restart_bridge_instances))
        self._button("discord_bridge_refresh_button", self.refresh_status)
        self._button("discord_format_bots_button", self._format_bots_json)
        self._button("discord_live_start_button", self._start_selected_bot)
        self._button("discord_live_stop_button", self._stop_selected_bot)
        self._button("discord_live_restart_button", self._restart_selected_bot)
        self._button("discord_live_disconnect_button", lambda: self._send_selected_bot_command("disconnect"))
        self._button("discord_live_reconnect_button", lambda: self._send_selected_bot_command("reconnect"))
        self._button("discord_live_stop_speech_button", lambda: self._send_selected_bot_command("stop_speech"))
        self._button("discord_live_clear_queue_button", lambda: self._send_selected_bot_command("clear_queue"))
        self._button("discord_live_reset_context_button", self._reset_selected_bot_context)
        self._button("discord_live_apply_selected_button", self._apply_live_settings_to_selected_bot)
        self._button("discord_live_apply_global_button", self._apply_global_live_settings)
        self._button("discord_live_apply_all_button", self._apply_all_live_settings)
        self._button("discord_live_send_message_button", self._send_selected_bot_message)
        self._button("discord_moderator_route_next_button", self._send_moderator_set_next_speaker)
        self._button("discord_moderator_give_floor_button", self._send_moderator_allow_only_speaker)
        self._button("discord_moderator_mute_button", self._send_moderator_mute_selected)
        self._button("discord_moderator_unmute_button", self._send_moderator_unmute_selected)
        self._button("discord_moderator_clear_pending_button", lambda: self._send_moderator_command("moderator_clear_pending", require_target=False))
        self._button("discord_moderator_clear_floor_button", lambda: self._send_moderator_command("moderator_clear_floor", require_target=False))
        self._button("discord_moderator_clear_button", lambda: self._send_moderator_command("moderator_clear", require_target=False))
        self._button("discord_moderator_stop_all_button", lambda: self._send_all_bot_command("stop_speech", "stop all speech"))
        self._button("discord_moderator_clear_all_queues_button", lambda: self._send_all_bot_command("clear_queue", "clear all queues"))
        self._button("discord_moderator_set_enforcer_button", self._send_moderator_set_enforcer)
        self._button("discord_moderator_clear_enforcer_button", self._send_moderator_clear_enforcer)
        interrupt_checkbox = self._control("discord_moderator_allow_interrupt_current_checkbox", QtWidgets.QCheckBox)
        if interrupt_checkbox is not None:
            interrupt_checkbox.toggled.connect(self._send_moderator_current_interruption_changed)
        enforce_checkbox = self._control("discord_moderator_enforce_mute_checkbox", QtWidgets.QCheckBox)
        if enforce_checkbox is not None:
            enforce_checkbox.toggled.connect(self._send_moderator_enforce_mute_changed)
        self._button("discord_moderator_announce_button", self._send_moderator_announcement)
        self._button("discord_moderator_call_on_button", self._send_moderator_call_on)
        message_edit = self._control("discord_live_message_edit", QtWidgets.QLineEdit)
        if message_edit is not None:
            message_edit.returnPressed.connect(self._send_selected_bot_message)
        moderator_announce = self._control("discord_moderator_announcement_edit", QtWidgets.QLineEdit)
        if moderator_announce is not None:
            moderator_announce.returnPressed.connect(self._send_moderator_announcement)
        live_combo = self._control("discord_live_bot_combo", QtWidgets.QComboBox)
        if live_combo is not None:
            live_combo.currentIndexChanged.connect(lambda _index: self._refresh_live_bot_state_label())
        moderator_table = self._control("discord_moderator_instances_table", QtWidgets.QTableWidget)
        if moderator_table is not None:
            moderator_table.itemSelectionChanged.connect(self._on_moderator_bot_selection_changed)
        participant_table = self._control("discord_moderator_participants_table", QtWidgets.QTableWidget)
        if participant_table is not None:
            participant_table.itemSelectionChanged.connect(self._on_moderator_participant_selection_changed)
        self._connect_bot_editor_auto_apply_signals()
        host = self._control("discord_runtime_host_edit", QtWidgets.QLineEdit)
        if host is not None:
            host.textChanged.connect(self._sync_runtime_endpoint_fields)
        port = self._control("discord_runtime_port_spin", QtWidgets.QSpinBox)
        if port is not None:
            port.valueChanged.connect(self._sync_runtime_endpoint_fields)
        self._connect_dead_air_live_apply_signals()

    def _connect_dead_air_live_apply_signals(self):
        checkbox = self._control("discord_dead_air_enabled_checkbox", QtWidgets.QCheckBox)
        if checkbox is not None:
            checkbox.toggled.connect(lambda _checked: self._schedule_global_live_settings_apply())
        spin = self._control("discord_dead_air_cooldown_spin", QtWidgets.QDoubleSpinBox)
        if spin is not None:
            spin.valueChanged.connect(lambda _value: self._schedule_global_live_settings_apply())
        silence_spin = self._control("discord_dead_air_silence_timeout_spin", QtWidgets.QDoubleSpinBox)
        if silence_spin is not None:
            silence_spin.valueChanged.connect(lambda _value: self._schedule_global_live_settings_apply())
        for name in (
            "discord_dead_air_trigger_combo",
            "discord_dead_air_action_combo",
            "discord_dead_air_strategy_combo",
            "discord_dead_air_fallback_target_combo",
        ):
            combo = self._control(name, QtWidgets.QComboBox)
            if combo is not None:
                combo.currentTextChanged.connect(lambda _text: self._schedule_global_live_settings_apply())

    def _sync_runtime_endpoint_fields(self):
        host = self._text("discord_runtime_host_edit", "127.0.0.1") or "127.0.0.1"
        port = int(self._spin_value("discord_runtime_port_spin", 8768))
        self._set_text("discord_runtime_http_endpoint_edit", f"http://{host}:{port}/turn")
        self._set_text("discord_runtime_ws_endpoint_edit", f"ws://{host}:{port}/discord-voice")

    def _connect_bot_editor_auto_apply_signals(self):
        for name in (
            "discord_bot_id_edit",
            "discord_bot_display_name_edit",
            "discord_bot_token_env_edit",
            "discord_bot_guild_id_edit",
            "discord_bot_voice_channel_id_edit",
            "discord_bot_call_names_edit",
            "discord_bot_voice_clone_wav_edit",
        ):
            control = self._control(name, QtWidgets.QLineEdit)
            if control is not None:
                control.editingFinished.connect(self._auto_apply_current_bot_to_model)
        for name in ("discord_bot_runtime_port_spin", "discord_bot_context_entries_spin"):
            control = self.controls.get(name)
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(lambda _value: self._auto_apply_current_bot_to_model())
        for name in ("discord_bot_enabled_checkbox", "discord_bot_use_global_chat_model_checkbox", "discord_bot_replace_nc_prompt_checkbox"):
            control = self._control(name, QtWidgets.QCheckBox)
            if control is not None:
                control.stateChanged.connect(lambda _state: self._auto_apply_current_bot_to_model())
        provider_combo = self._control("discord_bot_chat_provider_combo", QtWidgets.QComboBox)
        if provider_combo is not None:
            provider_combo.currentIndexChanged.connect(lambda _index: self._on_bot_chat_provider_changed())
        model_combo = self._control("discord_bot_chat_model_combo", QtWidgets.QComboBox)
        if model_combo is not None:
            model_combo.currentTextChanged.connect(lambda _text: self._auto_apply_current_bot_to_model())
        for name in self._bot_editor_plain_text_fields:
            control = self._control(name, QtWidgets.QPlainTextEdit)
            if control is not None:
                control.installEventFilter(self)

    def _on_bot_chat_provider_changed(self):
        if self._loading_bot_fields:
            return
        self._auto_apply_current_bot_to_model()

    def _refresh_bot_chat_runtime_controls(self):
        enabled = (
            not self._checked("discord_bot_use_global_chat_model_checkbox")
            and not self._operation_running
            and not self._bot_model_refresh_running
        )
        for name in (
            "discord_bot_chat_provider_combo",
            "discord_bot_chat_model_combo",
            "discord_bot_chat_model_refresh_button",
        ):
            control = self.controls.get(name)
            if control is not None:
                control.setEnabled(enabled)

    def _populate_bot_chat_provider_combo(self):
        combo = self._control("discord_bot_chat_provider_combo", QtWidgets.QComboBox)
        if combo is None:
            return
        current = self._combo_value("discord_bot_chat_provider_combo", "")
        try:
            from core import chat_providers

            providers = [
                (str(item.label or item.id), str(item.id or ""))
                for item in chat_providers.list_providers()
                if str(item.id or "").strip()
            ]
        except Exception:
            providers = []
        if not providers:
            providers = [("LM Studio", "lmstudio")]
        self._combo_items("discord_bot_chat_provider_combo", providers)
        if current:
            self._set_combo("discord_bot_chat_provider_combo", current)

    def _refresh_current_bot_chat_models(self, quiet: bool = False):
        provider = self._combo_value("discord_bot_chat_provider_combo", "")
        model_combo = self._control("discord_bot_chat_model_combo", QtWidgets.QComboBox)
        if model_combo is None:
            return
        current = str(model_combo.currentText() or "").strip()
        button = self._control("discord_bot_chat_model_refresh_button", QtWidgets.QPushButton)
        self._bot_model_refresh_running = True
        if button is not None:
            button.setEnabled(False)
            button.setText("Refreshing...")
        if not quiet:
            self._set_status(f"Refreshing models for {provider or 'chat provider'}...")

        def _worker():
            error = ""
            models: list[str] = []
            try:
                from core import chat_providers

                models = [
                    self._chat_model_name_from_provider_item(item)
                    for item in chat_providers.list_models(provider, quiet=bool(quiet))
                    if self._chat_model_name_from_provider_item(item)
                ]
            except Exception as exc:
                error = str(exc)
            self.bot_models_refreshed.emit(current, models, error)

        threading.Thread(target=_worker, name="DiscordVoiceBridge-ModelRefresh", daemon=True).start()

    def _on_bot_models_refreshed(self, previous_model: str, models: list, error: str):
        self._bot_model_refresh_running = False
        button = self._control("discord_bot_chat_model_refresh_button", QtWidgets.QPushButton)
        if button is not None:
            button.setEnabled(True)
            button.setText("Refresh")
        self._refresh_bot_chat_runtime_controls()
        if error:
            self._show_warning("Discord Voice Bridge", f"Could not refresh bot chat models: {error}")
            return
        model_combo = self._control("discord_bot_chat_model_combo", QtWidgets.QComboBox)
        if model_combo is None:
            return
        current = str(previous_model or model_combo.currentText() or "").strip()
        model_combo.blockSignals(True)
        try:
            model_combo.clear()
            for model in models:
                model_combo.addItem(str(model or ""))
            if current:
                index = model_combo.findText(current)
                if index >= 0:
                    model_combo.setCurrentIndex(index)
                else:
                    model_combo.setEditText(current)
        finally:
            model_combo.blockSignals(False)
        self._auto_apply_current_bot_to_model()
        self._set_status(f"Refreshed {len(models)} bot chat model(s).")

    @staticmethod
    def _chat_model_name_from_provider_item(item: Any) -> str:
        if isinstance(item, dict):
            for key in ("id", "name", "model"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value
            return ""
        return str(item or "").strip()

    def _auto_apply_current_bot_to_model(self):
        self._refresh_bot_chat_runtime_controls()
        self._apply_current_bot_to_model(show_errors=False)

    def eventFilter(self, watched, event):
        if (
            event.type() == QtCore.QEvent.FocusOut
            and isinstance(watched, QtWidgets.QPlainTextEdit)
            and str(watched.objectName() or "") in self._bot_editor_plain_text_fields
        ):
            self._auto_apply_current_bot_to_model()
        return super().eventFilter(watched, event)

    def _start_status_timer(self):
        if self._status_timer is not None:
            return
        timer = QtCore.QTimer(self)
        timer.setInterval(2000)
        timer.timeout.connect(self.refresh_status)
        timer.start()
        self._status_timer = timer

    def _selected_live_bot_id(self) -> str:
        combo = self._control("discord_live_bot_combo", QtWidgets.QComboBox)
        if combo is None:
            return ""
        value = combo.currentData()
        return str(value if value is not None else combo.currentText()).strip()

    def _start_selected_bot(self):
        bot_id = self._selected_live_bot_id()
        if not bot_id:
            self._show_warning("Discord Voice Bridge", "Choose a bot instance first.")
            return
        if not self.save_settings():
            return
        self._run_bridge_operation(f"start {bot_id}", lambda: self.addon.start_bridge_instance(bot_id))

    def _stop_selected_bot(self):
        bot_id = self._selected_live_bot_id()
        if not bot_id:
            self._show_warning("Discord Voice Bridge", "Choose a bot instance first.")
            return
        self._run_bridge_operation(f"stop {bot_id}", lambda: self.addon.stop_bridge_instance(bot_id))

    def _restart_selected_bot(self):
        bot_id = self._selected_live_bot_id()
        if not bot_id:
            self._show_warning("Discord Voice Bridge", "Choose a bot instance first.")
            return
        if not self.save_settings():
            return
        self._run_bridge_operation(f"restart {bot_id}", lambda: self.addon.restart_bridge_instance(bot_id))

    def _send_selected_bot_command(self, action: str):
        bot_id = self._selected_live_bot_id()
        if not bot_id:
            self._show_warning("Discord Voice Bridge", "Choose a running bot instance first.")
            return
        label = f"{str(action or 'command').replace('_', ' ')} {bot_id}"
        self._run_bridge_operation(label, lambda: self.addon.send_instance_command(bot_id, action))

    def _selected_moderator_bot_id(self) -> str:
        combo = self._control("discord_moderator_target_combo", QtWidgets.QComboBox)
        if combo is None:
            return self._selected_live_bot_id()
        if combo.count() <= 0:
            return ""
        value = combo.currentData()
        selected = _safe_bot_id(value if value is not None else combo.currentText())
        if not selected or selected == "default":
            return ""
        valid = {
            _safe_bot_id(item.get("id") or "")
            for item in self._last_instances
            if _safe_bot_id(item.get("id") or "")
        }
        valid.update(
            _safe_bot_id(bot.get("id") or bot.get("name") or "")
            for bot in self._bots_model
            if isinstance(bot, dict) and bot.get("enabled") is not False
        )
        valid.discard("")
        return selected if not valid or selected in valid else ""

    def _running_instance_ids(self) -> list[str]:
        ids: list[str] = []
        for item in self._last_instances:
            if not item.get("runtime_connected"):
                continue
            instance_id = _safe_bot_id(item.get("id") or "")
            if instance_id:
                ids.append(instance_id)
        return ids

    def _send_all_bot_command(self, action: str, label: str, payload: dict[str, Any] | None = None):
        instance_ids = self._running_instance_ids()
        if not instance_ids:
            self._show_warning("Discord Voice Bridge", "No running bot instances are available for this command.")
            return

        def sender():
            result = None
            for instance_id in instance_ids:
                result = self.addon.send_instance_command(instance_id, action, payload or {})
            return result

        self._run_bridge_operation(label, sender)

    def _send_moderator_command(self, action: str, *, require_target: bool = True):
        target = self._selected_moderator_bot_or_participant_bot_id()
        if require_target and not target:
            self._show_warning("Discord Voice Bridge", "Choose a target bot for the moderator command.")
            return
        self._send_moderator_command_to(action, target)

    def _send_moderator_command_to(self, action: str, target: str):
        target = _safe_bot_id(target)
        payload = {"target_bot_id": target, "reason": "human moderator"}
        self._send_all_bot_command(action, str(action or "moderator command").replace("_", " "), payload)

    def _selected_moderator_bot_or_participant_bot_id(self) -> str:
        participant = self._selected_moderator_participant()
        if participant.get("kind") == "bot":
            return self._bot_id_for_participant(participant) or self._selected_moderator_bot_id()
        return self._selected_moderator_bot_id()

    def _send_moderator_set_next_speaker(self):
        participant = self._selected_moderator_participant()
        if participant.get("kind") == "human":
            self._send_moderator_human_next_for(participant.get("id", ""), participant.get("name", "") or participant.get("id", ""))
            return
        target = self._selected_moderator_bot_or_participant_bot_id()
        if not target:
            self._show_warning("Discord Voice Bridge", "Choose a connected bot or human participant for Set Next Speaker.")
            return
        self._send_moderator_command_to("moderator_route_next", target)

    def _send_moderator_allow_only_speaker(self):
        participant = self._selected_moderator_participant()
        if participant.get("kind") == "human":
            self._send_moderator_human_floor_for(participant.get("id", ""), participant.get("name", "") or participant.get("id", ""))
            return
        target = self._selected_moderator_bot_or_participant_bot_id()
        if not target:
            self._show_warning("Discord Voice Bridge", "Choose a connected bot or human participant to allow as speaker.")
            return
        self._send_moderator_command_to("moderator_give_floor", target)

    def _send_moderator_mute_selected(self):
        participant = self._selected_moderator_participant()
        if participant.get("kind") == "human":
            self._send_moderator_human_mute_for(participant.get("id", ""), participant.get("name", "") or participant.get("id", ""), True)
            return
        target = self._selected_moderator_bot_or_participant_bot_id()
        if not target:
            self._show_warning("Discord Voice Bridge", "Choose a connected bot or human participant to mute.")
            return
        self._send_moderator_command_to("moderator_mute", target)

    def _send_moderator_unmute_selected(self):
        participant = self._selected_moderator_participant()
        if participant.get("kind") == "human":
            self._send_moderator_human_mute_for(participant.get("id", ""), participant.get("name", "") or participant.get("id", ""), False)
            return
        target = self._selected_moderator_bot_or_participant_bot_id()
        if not target:
            self._show_warning("Discord Voice Bridge", "Choose a connected bot or human participant to unmute.")
            return
        self._send_moderator_command_to("moderator_unmute", target)

    def _send_moderator_human_floor_for(self, user_id: str, name: str):
        user_id = str(user_id or "").strip()
        if not user_id:
            self._show_warning("Discord Voice Bridge", "The selected human participant has no Discord user id.")
            return
        payload = {
            "speaker_user_id": user_id,
            "speaker_name": str(name or user_id).strip(),
            "reason": "human moderator speaker lock",
        }
        self._send_all_bot_command("moderator_give_human_floor", "accept human speaker", payload)

    def _send_moderator_human_next_for(self, user_id: str, name: str):
        user_id = str(user_id or "").strip()
        if not user_id:
            self._show_warning("Discord Voice Bridge", "The selected human participant has no Discord user id.")
            return
        payload = {
            "speaker_user_id": user_id,
            "speaker_name": str(name or user_id).strip(),
            "reason": "human moderator next speaker",
        }
        self._send_all_bot_command("moderator_route_next_human", "route next human speaker", payload)

    def _send_moderator_human_mute_for(self, user_id: str, name: str, muted: bool):
        user_id = str(user_id or "").strip()
        if not user_id:
            self._show_warning("Discord Voice Bridge", "The selected human participant has no Discord user id.")
            return
        payload = {
            "speaker_user_id": user_id,
            "speaker_name": str(name or user_id).strip(),
            "reason": "human moderator participant mute",
        }
        action = "moderator_mute_human" if muted else "moderator_unmute_human"
        label = "mute human participant" if muted else "unmute human participant"
        self._send_all_bot_command(action, label, payload)

    def _send_moderator_current_interruption_changed(self, checked: bool):
        payload = {"allow_current_interruption": bool(checked), "reason": "human moderator interruption policy"}
        label = "allow current interruption" if checked else "protect current speaker"
        self._send_all_bot_command("moderator_set_current_interruption", label, payload)

    def _send_moderator_set_enforcer(self):
        target = self._selected_moderator_bot_id()
        if not target:
            self._show_warning("Discord Voice Bridge", "Choose a running bot target to use as the Discord moderator bot.")
            return
        if target not in self._running_instance_ids():
            self._show_warning("Discord Voice Bridge", "The selected moderator bot must be running before hard moderation can be enabled.")
            return
        payload = {"target_bot_id": target, "reason": "human moderator selected Discord mute enforcer"}
        self._run_bridge_operation(
            f"set moderator bot {target}",
            lambda: self.addon.send_instance_command(target, "moderator_set_enforcer", payload),
        )

    def _send_moderator_clear_enforcer(self):
        state = self._last_moderator_state if isinstance(self._last_moderator_state, dict) else {}
        enforcer = _safe_bot_id(state.get("enforcer_bot_id") or "")
        if not enforcer:
            self._show_warning("Discord Voice Bridge", "No active Discord moderator bot is selected.")
            return
        self._run_bridge_operation(
            "clear Discord moderator bot",
            lambda: self.addon.send_instance_command(enforcer, "moderator_clear_enforcer", {}),
        )

    def _send_moderator_enforce_mute_changed(self, checked: bool):
        state = self._last_moderator_state if isinstance(self._last_moderator_state, dict) else {}
        enforcer = _safe_bot_id(state.get("enforcer_bot_id") or "")
        checkbox = self._control("discord_moderator_enforce_mute_checkbox", QtWidgets.QCheckBox)
        if checked and (not enforcer or enforcer not in self._running_instance_ids()):
            if checkbox is not None:
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
            self._show_warning("Discord Voice Bridge", "Select an active Moderator bot before enabling Discord mute enforcement.")
            return
        if not enforcer:
            return
        payload = {"enabled": bool(checked), "reason": "human moderator Discord mute enforcement"}
        label = "enable Discord mute enforcement" if checked else "disable Discord mute enforcement"
        self._run_bridge_operation(
            label,
            lambda: self.addon.send_instance_command(enforcer, "moderator_set_mute_enforcement", payload),
        )

    def _selected_moderator_participant(self) -> dict[str, str]:
        table = self._control("discord_moderator_participants_table", QtWidgets.QTableWidget)
        if table is None or table.currentRow() < 0:
            return {}
        row = table.currentRow()
        item_id = table.item(row, 0)
        item_name = table.item(row, 1)
        item_kind = table.item(row, 2)
        item_state = table.item(row, 7)
        return {
            "id": str(item_id.text() if item_id is not None else "").strip(),
            "name": str(item_name.text() if item_name is not None else "").strip(),
            "kind": str(item_kind.text() if item_kind is not None else "").strip().lower(),
            "moderator_state": str(item_state.text() if item_state is not None else "").strip().lower(),
        }

    def _set_moderator_target(self, bot_id: str):
        bot_id = _safe_bot_id(bot_id)
        if not bot_id:
            return
        combo = self._control("discord_moderator_target_combo", QtWidgets.QComboBox)
        if combo is None:
            return
        index = combo.findData(bot_id)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _on_moderator_bot_selection_changed(self):
        table = self._control("discord_moderator_instances_table", QtWidgets.QTableWidget)
        if table is None or table.currentRow() < 0:
            return
        participant_table = self._control("discord_moderator_participants_table", QtWidgets.QTableWidget)
        if participant_table is not None and participant_table.currentRow() >= 0:
            participant_table.blockSignals(True)
            participant_table.clearSelection()
            participant_table.setCurrentCell(-1, -1)
            participant_table.blockSignals(False)
        item = table.item(table.currentRow(), 0)
        self._set_moderator_target(str(item.text() if item is not None else ""))
        self._refresh_moderator_selected_action_label()
        self._refresh_moderator_action_buttons()

    def _bot_id_for_participant(self, participant: dict[str, str]) -> str:
        name_key = _safe_bot_id(participant.get("name") or "")
        id_key = _safe_bot_id(participant.get("id") or "")
        for item in self._last_instances:
            instance_id = _safe_bot_id(item.get("id") or "")
            node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
            keys = {
                instance_id,
                _safe_bot_id(item.get("name") or ""),
                _safe_bot_id(node_status.get("bot_tag") or ""),
                _safe_bot_id(node_status.get("bot_name") or ""),
            }
            if name_key in keys or id_key in keys:
                return instance_id
        for bot in self._bots_model:
            if not isinstance(bot, dict):
                continue
            instance_id = _safe_bot_id(bot.get("id") or bot.get("name") or "")
            keys = {instance_id, _safe_bot_id(bot.get("name") or "")}
            if name_key in keys or id_key in keys:
                return instance_id
        return ""

    def _on_moderator_participant_selection_changed(self):
        participant = self._selected_moderator_participant()
        if not participant:
            return
        bot_table = self._control("discord_moderator_instances_table", QtWidgets.QTableWidget)
        if bot_table is not None and bot_table.currentRow() >= 0:
            bot_table.blockSignals(True)
            bot_table.clearSelection()
            bot_table.setCurrentCell(-1, -1)
            bot_table.blockSignals(False)
        if participant.get("kind") == "bot":
            self._set_moderator_target(self._bot_id_for_participant(participant))
        self._refresh_moderator_selected_action_label()
        self._refresh_moderator_action_buttons()

    def _send_moderator_announcement(self):
        target = self._selected_moderator_bot_or_participant_bot_id()
        if not target:
            self._show_warning("Discord Voice Bridge", "Choose a target bot for the announcement.")
            return
        text = self._text("discord_moderator_announcement_edit", "")
        if not text:
            self._show_warning("Discord Voice Bridge", "Enter announcement text to speak.")
            return
        label = f"moderator announcement {target}"
        self._run_bridge_operation(
            label,
            lambda: self.addon.send_instance_command(target, "send_message", {"text": text, "moderator_announcement": True}),
        )
        self._set_text("discord_moderator_announcement_edit", "")

    def _send_moderator_call_on(self):
        target = self._selected_moderator_bot_or_participant_bot_id()
        if not target:
            self._show_warning("Discord Voice Bridge", "Choose a target bot to call on.")
            return
        self._send_moderator_call_on_to(target)

    def _send_moderator_call_on_to(self, target: str):
        target = _safe_bot_id(target)
        if not target:
            self._show_warning("Discord Voice Bridge", "Choose a target bot to call on.")
            return
        text = self._text("discord_moderator_announcement_edit", "")
        payload = {
            "target_bot_id": target,
            "text": text,
            "reason": "human moderator call on target",
        }
        label = f"call on {target}"
        self._run_bridge_operation(label, lambda: self.addon.send_instance_command(target, "moderator_call_on", payload))
        self._set_text("discord_moderator_announcement_edit", "")

    def _send_selected_bot_message(self):
        bot_id = self._selected_live_bot_id()
        if not bot_id:
            self._show_warning("Discord Voice Bridge", "Choose a running bot instance first.")
            return
        text = self._text("discord_live_message_edit", "")
        if not text:
            self._show_warning("Discord Voice Bridge", "Enter a message for the selected bot to speak.")
            return
        label = f"send message {bot_id}"
        self._run_bridge_operation(
            label,
            lambda: self.addon.send_instance_command(bot_id, "send_message", {"text": text}),
        )
        self._set_text("discord_live_message_edit", "")

    def _reset_selected_bot_context(self):
        bot_id = self._selected_live_bot_id()
        if not bot_id:
            self._show_warning("Discord Voice Bridge", "Choose a running bot instance first.")
            return
        resetter = getattr(self.addon, "reset_instance_context", None)
        if not callable(resetter):
            self._send_selected_bot_command("reset_context")
            return
        self._run_bridge_operation(f"reset context {bot_id}", lambda: resetter(bot_id))

    def _apply_live_settings_to_selected_bot(self):
        if not self.save_settings():
            return
        bot_id = self._selected_live_bot_id()
        if not bot_id:
            self._show_warning("Discord Voice Bridge", "Choose a running bot instance first.")
            return
        applier = getattr(self.addon, "apply_live_settings", None)
        if not callable(applier):
            self._show_warning("Discord Voice Bridge", "This addon build does not expose live settings reload.")
            return
        self._run_bridge_operation(
            f"apply selected bot live settings {bot_id}",
            lambda: applier(bot_id, load_settings()),
        )

    def _apply_global_live_settings(self):
        if not self.save_settings():
            return
        applier = getattr(self.addon, "apply_live_settings", None)
        if not callable(applier):
            self._show_warning("Discord Voice Bridge", "This addon build does not expose live settings reload.")
            return
        self._run_bridge_operation(
            "apply global live settings",
            lambda: applier(None, load_settings(), sections=("room_router", "playback", "capture", "cleanup")),
        )

    def _schedule_global_live_settings_apply(self):
        if self._global_live_apply_timer is not None:
            self._global_live_apply_timer.start()

    def _auto_apply_global_live_settings(self):
        if self._operation_running:
            self._schedule_global_live_settings_apply()
            return
        applier = getattr(self.addon, "apply_live_settings", None)
        if not callable(applier) or not self.save_settings():
            return
        self._run_bridge_operation(
            "auto apply global live settings",
            lambda: applier(None, load_settings(), sections=("room_router", "playback", "capture", "cleanup")),
        )

    def _apply_all_live_settings(self):
        if not self.save_settings():
            return
        applier = getattr(self.addon, "apply_live_settings", None)
        if not callable(applier):
            self._show_warning("Discord Voice Bridge", "This addon build does not expose live settings reload.")
            return
        self._run_bridge_operation(
            "apply all live settings",
            lambda: applier(None, load_settings()),
        )

    def _restart_with_test_tone(self):
        self._set_checked("discord_play_test_tone_checkbox", True)
        self._one_shot_test_tone_pending = True
        self._run_bridge_operation("restart", self.addon.restart_bridge_instances)

    def _open_logs_folder(self):
        path = ADDON_DIR / "runtime_logs"
        path.mkdir(parents=True, exist_ok=True)
        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path))):
            self._show_warning("Discord Voice Bridge", f"Could not open logs folder: {path}")

    def _validate_settings_clicked(self):
        if not self.save_settings():
            return
        ok, text = self._validate_saved_settings()
        self._refresh_validation_summary()
        self._set_status(text)
        if not ok:
            self._show_warning("Discord Voice Bridge Settings", text)

    def _install_node_dependencies(self):
        installer = getattr(self.addon, "install_node_bridge_dependencies", None)
        if not callable(installer):
            self._show_warning("Discord Voice Bridge", "This addon build does not expose Node dependency installation.")
            return
        self._run_bridge_operation("install node deps", installer)

    def _schedule_node_dependency_prompt(self):
        if self._node_dependency_prompt_scheduled or self._node_dependency_prompt_shown:
            return
        self._node_dependency_prompt_scheduled = True
        QtCore.QTimer.singleShot(250, self._maybe_prompt_node_bridge_dependencies)

    def _node_bridge_validation_issues(self) -> list[dict[str, str]]:
        validator = getattr(self.addon, "validate_settings", None)
        if not callable(validator):
            return []
        try:
            return [
                dict(item)
                for item in list(validator(force=True) or [])
                if str(item.get("scope") or "") == "node_bridge"
            ]
        except Exception:
            return []

    def _maybe_prompt_node_bridge_dependencies(self):
        self._node_dependency_prompt_scheduled = False
        if self._node_dependency_prompt_shown or self._operation_running:
            return
        issues = self._node_bridge_validation_issues()
        if not issues:
            return
        messages = [str(item.get("message") or "") for item in issues]
        joined = "\n".join(messages).lower()
        needs_node = "node.js was not found" in joined or not shutil.which("npm")
        needs_deps = "dependencies are not installed" in joined or "dependencies are incomplete" in joined
        if not (needs_node or needs_deps):
            return
        self._node_dependency_prompt_shown = True
        if needs_node:
            response = QtWidgets.QMessageBox.question(
                self.widget,
                "Discord Voice Bridge",
                "This addon requires Node.js/npm before its Node bridge dependencies can be installed.\n\n"
                "Would you like to open the Node.js download page?",
            )
            if response == QtWidgets.QMessageBox.Yes:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://nodejs.org/en/download"))
            return
        response = QtWidgets.QMessageBox.question(
            self.widget,
            "Discord Voice Bridge",
            "This addon requires Node bridge dependencies.\n\n"
            "Would you like to install them now? This runs npm install only inside the bundled Discord Voice Bridge node_bridge folder.",
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        installer = getattr(self.addon, "install_node_bridge_dependencies", None)
        if not callable(installer):
            self._show_warning("Discord Voice Bridge", "This addon build does not expose Node dependency installation.")
            return
        self._run_bridge_operation("install node deps", installer)

    def _validate_saved_settings(self) -> tuple[bool, str]:
        validator = getattr(self.addon, "validate_settings", None)
        if not callable(validator):
            return True, "Settings saved. No addon validator is available."
        try:
            issues = list(validator(force=True) or [])
        except Exception as exc:
            return False, f"Settings validation failed: {exc}"
        errors = [item for item in issues if item.get("severity") == "error"]
        warnings = [item for item in issues if item.get("severity") != "error"]
        if errors:
            return False, "Settings validation found errors:\n" + "\n".join(f"- {item.get('message', '')}" for item in errors[:8])
        if warnings:
            return True, "Settings validation passed with warnings:\n" + "\n".join(f"- {item.get('message', '')}" for item in warnings[:8])
        return True, "Settings validation passed."

    def _refresh_validation_summary(self):
        label = self._control("discord_validation_summary_label", QtWidgets.QLabel)
        if label is None:
            return
        validator = getattr(self.addon, "validate_settings", None)
        if not callable(validator):
            label.setText("No addon validator is available.")
            return
        try:
            issues = list(validator(force=True) or [])
        except Exception as exc:
            label.setText(f"Validation failed: {exc}")
            return
        errors = [item for item in issues if item.get("severity") == "error"]
        warnings = [item for item in issues if item.get("severity") != "error"]
        if errors:
            lines = ["Errors block bridge start:"] + [f"- {item.get('message', '')}" for item in errors[:6]]
            if len(errors) > 6:
                lines.append(f"- ...and {len(errors) - 6} more error(s).")
            label.setText("\n".join(lines))
            return
        if warnings:
            lines = ["Ready with warnings:"] + [f"- {item.get('message', '')}" for item in warnings[:6]]
            if len(warnings) > 6:
                lines.append(f"- ...and {len(warnings) - 6} more warning(s).")
            label.setText("\n".join(lines))
            return
        label.setText("Ready: saved settings passed validation.")

    def _copy_diagnostics(self):
        try:
            self.save_settings()
            status = self.addon.status_snapshot() if hasattr(self.addon, "status_snapshot") else {}
        except Exception as exc:
            status = {"status": "error", "error": str(exc)}
        try:
            issues = list(self.addon.validate_settings(force=True) or []) if hasattr(self.addon, "validate_settings") else []
        except Exception as exc:
            issues = [{"severity": "error", "message": f"Validation failed: {exc}"}]
        payload = {
            "addon": "discord_voice_bridge",
            "status": redacted_settings(status if isinstance(status, dict) else {}),
            "validation": issues,
            "recent_logs": self._recent_log_text(),
        }
        text = _redact_text(json.dumps(payload, indent=2, ensure_ascii=True))
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            self._set_status("Copied redacted Discord Voice Bridge diagnostics to clipboard.")

    def _collect_settings(self) -> dict[str, Any]:
        if not self._apply_current_bot_to_model(show_errors=False):
            raise ValueError("Bot ID is required.")
        bots = copy.deepcopy(self._bots_model)
        port = int(self._spin_value("discord_runtime_port_spin", 8768))
        host = self._text("discord_runtime_host_edit", "127.0.0.1") or "127.0.0.1"
        low_info = [
            item.strip()
            for item in re.split(r"[,\n]+", self._text("discord_low_information_transcripts_edit", ""))
            if item.strip()
        ]
        discord_settings = {
            "token_env_var": self._text("discord_token_env_edit", "DISCORD_TOKEN") or "DISCORD_TOKEN",
            "guild_id": self._text("discord_guild_id_edit", ""),
            "voice_channel_id": self._text("discord_voice_channel_id_edit", ""),
            "allowed_user_id": self._text("discord_allowed_user_id_edit", ""),
            "answer_mode": self._combo_value("discord_answer_mode_combo", "allowed_user_only"),
        }
        local_token = self._text("discord_local_token_edit", "")
        if local_token:
            discord_settings["token"] = local_token
            self._set_text("discord_local_token_edit", "")
        return {
            "enabled": self._checked("discord_enabled_checkbox"),
            "start_on_nc_launch": self._checked("discord_start_on_launch_checkbox"),
            "auto_start_bridge": self._checked("discord_auto_start_checkbox"),
            "bridge_mode": self._combo_value("discord_bridge_mode_combo", "mock"),
            "tiny_mvp": {
                "url": self._text("discord_tiny_mvp_url_edit", "http://127.0.0.1:8788") or "http://127.0.0.1:8788",
                "start_with_gui": self._checked("discord_tiny_mvp_start_with_gui_checkbox"),
                "bridge_script": self._text("discord_tiny_mvp_bridge_script_edit", ""),
                "poll_seconds": float(self._spin_value("discord_tiny_mvp_poll_seconds_spin", 0.25)),
                "capture_mic": self._checked("discord_tiny_mvp_capture_mic_checkbox"),
                "route_protected_mic_speech": self._checked("discord_route_protected_mic_speech_checkbox"),
                "mic_user_id": self._text("discord_tiny_mvp_mic_user_id_edit", "rakila") or "rakila",
                "mic_user_name": self._text("discord_tiny_mvp_mic_user_name_edit", "Rakila") or "Rakila",
                "mic_seconds": float(self._spin_value("discord_tiny_mvp_mic_seconds_spin", 6.0)),
                "mic_sample_rate": int(self._spin_value("discord_tiny_mvp_mic_sample_rate_spin", 16000)),
                "mic_device": self._text("discord_tiny_mvp_mic_device_edit", ""),
            },
            "discord": discord_settings,
            "chat": {
                "context_entries": int(self._spin_value("discord_context_entries_spin", 20)),
                "use_selected_rag_context": self._checked("discord_use_rag_context_checkbox"),
                "persist_room_context_between_restarts": self._checked("discord_persist_room_context_checkbox"),
            },
            "capture": {
                "silence_ms": int(self._spin_value("discord_silence_ms_spin", 900)),
                "min_turn_seconds": float(self._spin_value("discord_min_turn_seconds_spin", 0.6)),
                "max_turn_seconds": int(self._spin_value("discord_max_turn_seconds_spin", 30)),
                "bot_max_turn_seconds": int(self._spin_value("discord_bot_max_turn_seconds_spin", 120)),
                "bot_idle_finalize_ms": int(self._spin_value("discord_bot_idle_finalize_ms_spin", 4500)),
                "ignore_low_information_transcripts": self._checked("discord_ignore_low_information_checkbox"),
                "low_information_max_seconds": float(self._spin_value("discord_low_information_max_seconds_spin", 2.0)),
                "low_information_transcripts": low_info,
                "wav_sample_rate": int(self._combo_value("discord_wav_sample_rate_combo", "16000")),
                "wav_channels": int(self._combo_value("discord_wav_channels_combo", "1")),
                "save_captures": self._checked("discord_save_captures_checkbox"),
                "shared_capture_owner_enabled": self._checked("discord_shared_capture_owner_checkbox"),
                "owner_ttl_seconds": float(self._spin_value("discord_capture_owner_ttl_spin", 8.0)),
            },
            "playback": {
                "play_test_tone_on_join": self._checked("discord_play_test_tone_checkbox"),
                "queue_replies": self._checked("discord_queue_replies_checkbox"),
                "interrupt_reply_on_user_speech": self._checked("discord_interrupt_reply_checkbox"),
                "interrupt_after_seconds": float(self._spin_value("discord_interrupt_after_seconds_spin", 4.0)),
                "reply_immunity_seconds": float(self._spin_value("discord_reply_immunity_seconds_spin", 4.0)),
                "discard_bot_speech_on_human_intervention": self._checked("discord_discard_bot_speech_checkbox"),
                "coordinate_bot_replies": self._checked("discord_coordinate_bot_replies_checkbox"),
                "reply_floor_stale_seconds": float(self._spin_value("discord_reply_floor_stale_seconds_spin", 180.0)),
                "initial_buffer_chunks": int(self._spin_value("discord_initial_buffer_chunks_spin", 2)),
                "route_protected_mic_speech": self._checked("discord_route_protected_mic_speech_checkbox"),
            },
            "response_filter": {
                "enabled": False,
            },
            "room_router": {
                "enabled": self._checked("discord_room_router_enabled_checkbox"),
                "mode": self._combo_value("discord_room_router_mode_combo", "llm_router"),
                "default_when_uncertain": self._checked("discord_room_router_uncertain_checkbox"),
                "human_to_bot_routing": self._checked("discord_room_router_human_to_bot_checkbox"),
                "bot_to_bot_routing": self._checked("discord_room_router_bot_to_bot_checkbox"),
                "exclude_speaker_from_targets": self._checked("discord_room_router_exclude_speaker_checkbox"),
                "allow_group_invitation_routing": self._checked("discord_room_router_group_invite_checkbox"),
                "allow_open_room_invitation_routing": self._checked("discord_room_router_open_room_checkbox"),
                "self_route_policy": self._combo_value("discord_room_router_self_route_combo", "ignore"),
                "uncertain_fallback_target": self._combo_value("discord_room_router_uncertain_target_combo", "self"),
                "decision_timeout_seconds": float(self._spin_value("discord_room_router_decision_timeout_spin", 20.0)),
                "decision_max_tokens": int(self._spin_value("discord_room_router_decision_tokens_spin", 2048)),
                "route_window_ms": int(self._spin_value("discord_room_router_route_window_spin", 4000)),
                "route_bot_replies_from_text": self._checked("discord_room_router_text_routing_checkbox"),
                "prepare_bot_replies_ahead": self._checked("discord_room_router_prebuffer_checkbox"),
                "competing_bot_reply_policy": self._combo_value("discord_room_router_competing_policy_combo", "first_ready_wins"),
                "reply_floor_mode": self._combo_value("discord_room_router_floor_mode_combo", "first_ready_wins"),
                "dead_air_recovery": {
                    "enabled": self._checked("discord_dead_air_enabled_checkbox"),
                    "cooldown_seconds": float(self._spin_value("discord_dead_air_cooldown_spin", 0.0)),
                    "silence_timeout_seconds": float(self._spin_value("discord_dead_air_silence_timeout_spin", 10.0)),
                    "trigger_mode": self._combo_value("discord_dead_air_trigger_combo", "no_route_after_bot_speech"),
                    "action_mode": self._combo_value("discord_dead_air_action_combo", "moderator_speaks_and_calls_next"),
                    "next_speaker_strategy": self._combo_value("discord_dead_air_strategy_combo", "llm_choose"),
                    "selected_fallback_target": self._combo_text("discord_dead_air_fallback_target_combo", "").strip(),
                },
                "routed_text_poll_ms": int(self._spin_value("discord_room_router_poll_ms_spin", 250)),
                "routed_text_max_age_seconds": float(self._spin_value("discord_room_router_text_age_spin", 30.0)),
                "router_rules_prompt": self._plain_text("discord_room_router_rules_prompt_edit", "").strip(),
            },
            "persona": {
                "system_prompt": self._plain_text("discord_persona_prompt_edit", ""),
                "replace_nc_system_prompt": self._checked("discord_replace_nc_prompt_checkbox"),
                "voice_clone_wav": self._text("discord_voice_clone_wav_edit", ""),
            },
            "bots": bots,
            "nc_runtime": {
                "host": host,
                "port": port,
                "http_endpoint": f"http://{host}:{port}/turn",
                "endpoint": f"ws://{host}:{port}/discord-voice",
                "allow_non_localhost": self._checked("discord_allow_non_localhost_checkbox"),
                "session_mode": "isolated_discord",
                "use_selected_stt": self._checked("discord_use_selected_stt_checkbox"),
                "use_selected_chat_provider": self._checked("discord_use_selected_chat_checkbox"),
                "use_selected_tts": self._checked("discord_use_selected_tts_checkbox"),
            },
            "cleanup": {
                "wav_max_age_minutes": float(self._spin_value("discord_wav_max_age_minutes_spin", 60.0)),
                "interval_minutes": float(self._spin_value("discord_cleanup_interval_minutes_spin", 10.0)),
            },
        }

    def _parse_bots_json(self) -> list[dict[str, Any]]:
        raw = self._plain_text("discord_bots_json_edit", "").strip()
        if not raw:
            return []
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("Bot instances must be a JSON array.")
        for item in parsed:
            if not isinstance(item, dict):
                raise ValueError("Each bot instance must be a JSON object.")
            _drop_redacted_secret_values(item)
        return parsed

    def _load_bots_from_json_editor(self):
        try:
            self._bots_model = self._parse_bots_json()
            self._current_bot_index = -1
            self._refresh_bot_list()
            self._sync_bots_json_editor()
            self._set_status("Loaded bot instances from advanced JSON.")
        except Exception as exc:
            self._show_warning("Discord Voice Bridge", f"Bot JSON is invalid: {exc}")

    def _sync_bots_json_editor(self):
        display = redacted_settings({"bots": self._bots_model})
        self._set_plain_text("discord_bots_json_edit", json.dumps(display.get("bots", []), indent=2, ensure_ascii=True))

    def _refresh_bot_list(self):
        bot_list = self._control("discord_bot_list", QtWidgets.QListWidget)
        if bot_list is None:
            return
        previous = bot_list.currentRow()
        bot_list.blockSignals(True)
        bot_list.clear()
        for index, bot in enumerate(self._bots_model):
            label = str(bot.get("name") or bot.get("id") or f"bot_{index + 1}")
            suffix = "" if bot.get("enabled", True) else " (disabled)"
            bot_list.addItem(f"{label}{suffix}")
        bot_list.blockSignals(False)
        if self._bots_model:
            row = min(max(previous, 0), len(self._bots_model) - 1)
            bot_list.setCurrentRow(row)
            self._on_bot_selected(row)
        else:
            self._current_bot_index = -1
            self._clear_bot_fields()

    def _on_bot_selected(self, row: int):
        self._current_bot_index = int(row)
        if row < 0 or row >= len(self._bots_model):
            self._clear_bot_fields()
            return
        self._load_bot_fields(self._bots_model[row])

    def _clear_bot_fields(self):
        self._loading_bot_fields = True
        try:
            self._set_checked("discord_bot_enabled_checkbox", False)
            for name in (
                "discord_bot_id_edit",
                "discord_bot_display_name_edit",
                "discord_bot_token_env_edit",
                "discord_bot_local_token_edit",
                "discord_bot_guild_id_edit",
                "discord_bot_voice_channel_id_edit",
                "discord_bot_call_names_edit",
                "discord_bot_voice_clone_wav_edit",
            ):
                self._set_text(name, "")
            self._set_spin("discord_bot_runtime_port_spin", 8768)
            self._set_spin("discord_bot_context_entries_spin", 20)
            self._set_checked("discord_bot_use_global_chat_model_checkbox", True)
            self._set_combo("discord_bot_chat_provider_combo", "lmstudio")
            self._set_combo_text("discord_bot_chat_model_combo", "")
            self._refresh_bot_chat_runtime_controls()
            self._set_checked("discord_bot_replace_nc_prompt_checkbox", False)
            self._set_plain_text("discord_bot_persona_prompt_edit", "")
        finally:
            self._loading_bot_fields = False

    def _load_bot_fields(self, bot: dict[str, Any]):
        self._loading_bot_fields = True
        try:
            self._set_checked("discord_bot_enabled_checkbox", bot.get("enabled", True))
            self._set_text("discord_bot_id_edit", bot.get("id", ""))
            self._set_text("discord_bot_display_name_edit", bot.get("name", ""))
            self._set_text("discord_bot_token_env_edit", _get(bot, "discord.token_env_var", ""))
            self._set_text("discord_bot_local_token_edit", "")
            self._set_text("discord_bot_guild_id_edit", _get(bot, "discord.guild_id", ""))
            self._set_text("discord_bot_voice_channel_id_edit", _get(bot, "discord.voice_channel_id", ""))
            self._set_spin("discord_bot_runtime_port_spin", _get(bot, "nc_runtime.port", 8768))
            self._set_spin("discord_bot_context_entries_spin", _get(bot, "chat.context_entries", 20))
            self._set_checked("discord_bot_use_global_chat_model_checkbox", _get(bot, "chat.use_global_model", True))
            self._set_combo("discord_bot_chat_provider_combo", _get(bot, "chat.provider", "lmstudio"))
            self._set_combo_text("discord_bot_chat_model_combo", _get(bot, "chat.model_name", ""))
            self._refresh_bot_chat_runtime_controls()
            self._set_text("discord_bot_call_names_edit", _get(bot, "call_names", _get(bot, "response_filter.bot_names", "")))
            self._set_text("discord_bot_voice_clone_wav_edit", _get(bot, "persona.voice_clone_wav", ""))
            self._set_checked("discord_bot_replace_nc_prompt_checkbox", _get(bot, "persona.replace_nc_system_prompt", False))
            self._set_plain_text("discord_bot_persona_prompt_edit", _get(bot, "persona.system_prompt", ""))
        finally:
            self._loading_bot_fields = False

    def _apply_current_bot_to_model(self, *, show_errors: bool) -> bool:
        if self._loading_bot_fields or self._current_bot_index < 0 or self._current_bot_index >= len(self._bots_model):
            return True
        bot_id = self._text("discord_bot_id_edit", "")
        if not bot_id:
            if show_errors:
                self._show_warning("Discord Voice Bridge", "Bot ID is required.")
            return False
        bot = copy.deepcopy(self._bots_model[self._current_bot_index])
        bot["id"] = bot_id
        name = self._text("discord_bot_display_name_edit", "")
        if name:
            bot["name"] = name
        else:
            bot.pop("name", None)
        bot["enabled"] = self._checked("discord_bot_enabled_checkbox")
        bot.setdefault("discord", {})
        bot["discord"]["token_env_var"] = self._text("discord_bot_token_env_edit", "") or f"DISCORD_TOKEN_{bot_id.upper()}"
        local_token = self._text("discord_bot_local_token_edit", "")
        if local_token:
            bot["discord"]["token"] = local_token
            self._set_text("discord_bot_local_token_edit", "")
        _set_or_drop(bot["discord"], "guild_id", self._text("discord_bot_guild_id_edit", ""))
        _set_or_drop(bot["discord"], "voice_channel_id", self._text("discord_bot_voice_channel_id_edit", ""))
        bot.setdefault("nc_runtime", {})
        bot["nc_runtime"]["port"] = int(self._spin_value("discord_bot_runtime_port_spin", 8768))
        bot.setdefault("chat", {})
        bot["chat"]["context_entries"] = int(self._spin_value("discord_bot_context_entries_spin", 20))
        bot["chat"]["use_global_model"] = self._checked("discord_bot_use_global_chat_model_checkbox")
        _set_or_drop(bot["chat"], "provider", self._combo_value("discord_bot_chat_provider_combo", ""))
        _set_or_drop(bot["chat"], "model_name", self._combo_text("discord_bot_chat_model_combo", ""))
        _set_or_drop(bot, "call_names", self._text("discord_bot_call_names_edit", ""))
        legacy_filter = bot.get("response_filter")
        if isinstance(legacy_filter, dict):
            legacy_filter.pop("bot_names", None)
            if not legacy_filter:
                bot.pop("response_filter", None)
        bot.setdefault("persona", {})
        bot["persona"]["system_prompt"] = self._plain_text("discord_bot_persona_prompt_edit", "").strip()
        bot["persona"]["replace_nc_system_prompt"] = self._checked("discord_bot_replace_nc_prompt_checkbox")
        _set_or_drop(bot["persona"], "voice_clone_wav", self._text("discord_bot_voice_clone_wav_edit", ""))
        self._bots_model[self._current_bot_index] = bot
        self._refresh_bot_list()
        self._sync_bots_json_editor()
        if show_errors:
            self._set_status(f"Applied bot settings for {bot_id}.")
        return True

    def _unique_bot_id(self, base: str) -> str:
        stem = re.sub(r"[^a-zA-Z0-9_]+", "_", str(base or "").strip().lower()).strip("_") or "bot"
        existing = {str(bot.get("id") or "").strip().lower() for bot in self._bots_model if isinstance(bot, dict)}
        candidate = stem
        suffix = 2
        while candidate.lower() in existing:
            candidate = f"{stem}_{suffix}"
            suffix += 1
        return candidate

    def _next_bot_port(self) -> int:
        used_ports = set()
        for bot in self._bots_model:
            if not isinstance(bot, dict):
                continue
            port = _get(bot, "nc_runtime.port", None)
            try:
                used_ports.add(int(port))
            except (TypeError, ValueError):
                continue
        port = 8768
        while port in used_ports and port < 65535:
            port += 1
        return port

    def _add_structured_bot(self):
        if not self._apply_current_bot_to_model(show_errors=False):
            return
        index = len(self._bots_model) + 1
        bot_id = self._unique_bot_id(f"bot_{index}")
        display_name = f"Bot {index}"
        self._bots_model.append(
            {
                "id": bot_id,
                "name": display_name,
                "enabled": True,
                "discord": {"token_env_var": f"DISCORD_TOKEN_{bot_id.upper()}"},
                "nc_runtime": {"port": self._next_bot_port()},
                "chat": {
                    "context_entries": int(self._spin_value("discord_context_entries_spin", 20)),
                    "use_global_model": True,
                    "provider": "",
                    "model_name": "",
                },
                "call_names": display_name,
                "persona": {
                    "system_prompt": f"You are {display_name}, a Discord voice companion.",
                    "replace_nc_system_prompt": True,
                    "voice_clone_wav": "",
                },
            }
        )
        self._sync_bots_json_editor()
        self._refresh_bot_list()
        bot_list = self._control("discord_bot_list", QtWidgets.QListWidget)
        if bot_list is not None:
            bot_list.setCurrentRow(len(self._bots_model) - 1)

    def _duplicate_structured_bot(self):
        if not self._apply_current_bot_to_model(show_errors=False):
            return
        if self._current_bot_index < 0 or self._current_bot_index >= len(self._bots_model):
            self._add_structured_bot()
            return
        source = copy.deepcopy(self._bots_model[self._current_bot_index])
        source_id = str(source.get("id") or "bot")
        source_name = str(source.get("name") or source_id)
        bot_id = self._unique_bot_id(f"{source_id}_copy")
        display_name = f"{source_name} Copy"
        source["id"] = bot_id
        source["name"] = display_name
        source["enabled"] = True
        source.setdefault("discord", {})
        source["discord"]["token_env_var"] = f"DISCORD_TOKEN_{bot_id.upper()}"
        source["discord"].pop("token", None)
        source.setdefault("nc_runtime", {})
        source["nc_runtime"]["port"] = self._next_bot_port()
        source["call_names"] = display_name
        self._bots_model.append(source)
        self._sync_bots_json_editor()
        self._refresh_bot_list()
        bot_list = self._control("discord_bot_list", QtWidgets.QListWidget)
        if bot_list is not None:
            bot_list.setCurrentRow(len(self._bots_model) - 1)

    def _remove_selected_bot(self):
        row = self._current_bot_index
        if row < 0 or row >= len(self._bots_model):
            return
        bot = self._bots_model[row]
        label = str(bot.get("name") or bot.get("id") or f"bot {row + 1}")
        parent = self.widget if isinstance(self.widget, QtWidgets.QWidget) else None
        if QtWidgets.QMessageBox.question(parent, "Remove Bot", f"Remove bot instance '{label}'?") != QtWidgets.QMessageBox.Yes:
            return
        eraser = getattr(self.addon, "erase_instance_context", None)
        if callable(eraser):
            try:
                eraser(str(bot.get("id") or label))
            except Exception as exc:
                self._show_warning("Discord Voice Bridge", f"Bot was not removed because its context could not be erased: {exc}")
                return
        self._bots_model.pop(row)
        self._current_bot_index = -1
        self._sync_bots_json_editor()
        self._refresh_bot_list()

    def _remove_all_bot_context(self):
        parent = self.widget if isinstance(self.widget, QtWidgets.QWidget) else None
        message = "Remove persisted Discord context for all configured bot instances? This cannot be undone."
        if QtWidgets.QMessageBox.question(parent, "Remove All Bot Context", message) != QtWidgets.QMessageBox.Yes:
            return
        eraser = getattr(self.addon, "erase_all_instance_contexts", None)
        if not callable(eraser):
            self._show_warning("Discord Voice Bridge", "This addon build does not expose bot context removal.")
            return
        self._run_bridge_operation("remove all bot context", eraser)

    def _format_bots_json(self):
        try:
            self._load_bots_from_json_editor()
        except Exception as exc:
            self._show_warning("Discord Voice Bridge", f"Bot JSON is invalid: {exc}")

    def _run_bridge_operation(self, label: str, operation):
        if self._operation_running:
            return
        label_key = str(label or "").strip().lower()
        if label_key in {"start", "restart"} or label_key.startswith("start ") or label_key.startswith("restart "):
            if not self.save_settings():
                if self._one_shot_test_tone_pending:
                    self._one_shot_test_tone_pending = False
                    self._set_checked("discord_play_test_tone_checkbox", False)
                return
            ok, text = self._validate_saved_settings()
            if not ok:
                if self._one_shot_test_tone_pending:
                    self._one_shot_test_tone_pending = False
                    self._set_checked("discord_play_test_tone_checkbox", False)
                    try:
                        save_local_settings(self._collect_settings(), allow_secret_updates=True)
                    except Exception:
                        pass
                self._set_status(text)
                self._show_warning("Discord Voice Bridge Settings", text)
                return
        self._operation_running = True
        self._set_buttons_enabled(False)
        self._set_status(f"{self._operation_display_name(label)} running...")

        def _worker():
            try:
                result = operation()
                detail = self._operation_success_detail(result)
                self.operation_finished.emit(label, True, detail)
            except Exception as exc:
                self.operation_finished.emit(label, False, str(exc))

        threading.Thread(target=_worker, name=f"DiscordVoiceBridge-{label}", daemon=True).start()

    def _on_operation_finished(self, label: str, ok: bool, error: str):
        self._operation_running = False
        self._set_buttons_enabled(True)
        if ok:
            message = f"{self._operation_display_name(label)} finished."
            if error:
                message = f"{message} {error}"
            self._set_status(message)
        else:
            self._set_status(f"{self._operation_display_name(label)} failed: {error}")
            self._show_warning("Discord Voice Bridge", error)
        if self._one_shot_test_tone_pending:
            self._one_shot_test_tone_pending = False
            self._set_checked("discord_play_test_tone_checkbox", False)
            try:
                save_local_settings(self._collect_settings(), allow_secret_updates=True)
            except Exception:
                pass
        self.refresh_status()

    def _operation_display_name(self, label: str) -> str:
        names = {
            "start": "Start bridge operation",
            "stop": "Stop bridge operation",
            "restart": "Restart bridge operation",
            "install node deps": "Install/update Node dependencies",
        }
        return names.get(str(label or ""), f"{str(label or 'Bridge').title()} operation")

    def _operation_success_detail(self, result: Any) -> str:
        if isinstance(result, dict):
            log_path = str(result.get("log_path") or "").strip()
            if log_path:
                return f"Log: {log_path}"
        return ""

    def _refresh_instances_table(self, instances: list[dict[str, Any]]):
        table = self._control("discord_instances_table", QtWidgets.QTableWidget)
        if table is None:
            return
        headers = [
            "ID", "Name", "Node", "Endpoint", "Discord", "Speaking", "Listening", "Queued",
            "Last Transcript", "Last Route", "Last Error", "Bot Tag", "Channel", "Port", "PID", "URL",
        ]
        vertical_bar = table.verticalScrollBar()
        horizontal_bar = table.horizontalScrollBar()
        vertical_value = vertical_bar.value() if vertical_bar is not None else 0
        horizontal_value = horizontal_bar.value() if horizontal_bar is not None else 0
        current_row = table.currentRow()
        current_col = table.currentColumn()
        column_widths = [table.columnWidth(col) for col in range(table.columnCount())]

        table.setUpdatesEnabled(False)
        try:
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setRowCount(len(instances))
            for row, item in enumerate(instances):
                node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
                runtime_status = item.get("runtime_status") if isinstance(item.get("runtime_status"), dict) else {}
                route_decision = node_status.get("last_route_decision") if isinstance(node_status.get("last_route_decision"), dict) else {}
                route_text = _route_decision_text(route_decision)
                values = [
                    str(item.get("id") or ""),
                    str(item.get("name") or ""),
                    "running" if item.get("runtime_connected") else "stopped",
                    "running" if item.get("endpoint_running") else "stopped",
                    str(node_status.get("state") or ""),
                    "yes" if node_status.get("speaking") else "no",
                    "yes" if node_status.get("listening") else "no",
                    str(node_status.get("queued_audio") or "0"),
                    str(node_status.get("last_transcript") or runtime_status.get("last_transcript") or "")[:220],
                    route_text[:220],
                    str(node_status.get("last_error") or "")[:220],
                    str(item.get("discord_bot_tag") or ""),
                    str(item.get("voice_channel_name") or item.get("voice_channel_id") or ""),
                    str(item.get("runtime_port") or ""),
                    str(item.get("pid") or ""),
                    str(item.get("endpoint_url") or ""),
                ]
                for col, value in enumerate(values):
                    table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
            if not self._instances_table_columns_sized:
                table.resizeColumnsToContents()
                self._instances_table_columns_sized = True
            else:
                for col, width in enumerate(column_widths[: table.columnCount()]):
                    table.setColumnWidth(col, width)
            header = table.horizontalHeader()
            if header is not None and table.columnCount() >= 4:
                header.setStretchLastSection(True)
            if 0 <= current_row < table.rowCount() and 0 <= current_col < table.columnCount():
                table.setCurrentCell(current_row, current_col)
            if vertical_bar is not None:
                vertical_bar.setValue(min(vertical_value, vertical_bar.maximum()))
            if horizontal_bar is not None:
                horizontal_bar.setValue(min(horizontal_value, horizontal_bar.maximum()))
        finally:
            table.setUpdatesEnabled(True)

    def _build_status_progress_controls(self):
        tab = self.controls.get("discord_bridge_status_tab")
        if not isinstance(tab, QtWidgets.QWidget):
            return
        if tab.findChild(QtWidgets.QWidget, "discord_buffer_progress_group") is not None:
            return
        layout = tab.layout()
        if not isinstance(layout, QtWidgets.QVBoxLayout):
            return
        group = QtWidgets.QGroupBox("Buffer Race", tab)
        group.setObjectName("discord_buffer_progress_group")
        group.setToolTip("Shows Discord reply audio preparation and playback progress for the active or selected bot.")
        outer = QtWidgets.QVBoxLayout(group)
        outer.setContentsMargins(10, 10, 10, 10)
        label = QtWidgets.QLabel("Telemetry appears during Discord reply generation and playback.", group)
        label.setObjectName("discord_buffer_progress_label")
        outer.addWidget(label)
        ready_bar = QtWidgets.QProgressBar(group)
        ready_bar.setObjectName("discord_render_ready_bar")
        ready_bar.setTextVisible(True)
        ready_bar.setRange(0, 1)
        ready_bar.setValue(0)
        ready_bar.setFormat("Render Ready: 0/0")
        outer.addWidget(ready_bar)
        playback_bar = QtWidgets.QProgressBar(group)
        playback_bar.setObjectName("discord_preview_playback_bar")
        playback_bar.setTextVisible(True)
        playback_bar.setRange(0, 1)
        playback_bar.setValue(0)
        playback_bar.setFormat("Preview / Playback: 0/0")
        outer.addWidget(playback_bar)
        layout.insertWidget(0, group)

    def _refresh_status_progress(self, instances: list[dict[str, Any]]):
        selected_id = self._selected_live_bot_id()
        active = None
        for item in instances:
            node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
            if bool(node_status.get("speaking")):
                active = item
                break
        if active is None and selected_id:
            active = next((item for item in instances if str(item.get("id") or "") == selected_id), None)
        if active is None and instances:
            active = instances[0]

        node_status = active.get("node_status") if isinstance(active, dict) and isinstance(active.get("node_status"), dict) else {}
        bot_name = str(active.get("name") or active.get("id") or "No bot") if isinstance(active, dict) else "No bot"
        label = self._control("discord_buffer_progress_label", QtWidgets.QLabel)
        if label is not None:
            if node_status:
                floor_owner = str(node_status.get("reply_floor_owner_bot") or node_status.get("reply_floor_owner") or "").strip()
                suffix = f" | floor: {floor_owner}" if floor_owner else ""
                label.setText(f"Active telemetry: {bot_name}{suffix}")
            else:
                label.setText("Telemetry appears during Discord reply generation and playback.")

        self._set_progress_bar(
            "discord_render_ready_bar",
            "Render Ready",
            int(node_status.get("render_ready_chunks") or 0),
            int(node_status.get("render_total_chunks") or 0),
        )
        self._set_progress_bar(
            "discord_preview_playback_bar",
            "Preview / Playback",
            int(node_status.get("playback_completed_chunks") or 0),
            int(node_status.get("playback_total_chunks") or 0),
        )

    def _set_progress_bar(self, name: str, title: str, value: int, total: int):
        bar = self._control(name, QtWidgets.QProgressBar)
        if bar is None:
            return
        value = max(0, int(value or 0))
        total = max(0, int(total or 0))
        if total <= 0:
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setFormat(f"{title}: 0/0")
            return
        bar.setRange(0, total)
        bar.setValue(min(value, total))
        bar.setFormat(f"{title}: {min(value, total)}/{total}")

    def _refresh_live_bot_combo(self, instances: list[dict[str, Any]]):
        combo = self._control("discord_live_bot_combo", QtWidgets.QComboBox)
        if combo is None:
            return
        current = self._selected_live_bot_id()
        seen: set[str] = set()
        combo.blockSignals(True)
        combo.clear()
        for item in instances:
            instance_id = _safe_bot_id(item.get("id") or "")
            if not instance_id:
                continue
            seen.add(instance_id)
            status = "running" if item.get("runtime_connected") else "stopped"
            name = str(item.get("name") or instance_id)
            combo.addItem(f"{name} ({instance_id}, {status})", instance_id)
        for bot in self._bots_model:
            if not isinstance(bot, dict) or bot.get("enabled") is False:
                continue
            instance_id = _safe_bot_id(bot.get("id") or bot.get("name") or "")
            if not instance_id or instance_id in seen:
                continue
            name = str(bot.get("name") or instance_id)
            combo.addItem(f"{name} ({instance_id}, stopped)", instance_id)
            seen.add(instance_id)
        if not seen:
            combo.addItem("default (stopped)", "default")
        if current:
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self._refresh_live_bot_state_label()

    def _refresh_moderator_controls(self, instances: list[dict[str, Any]]):
        combo = self._control("discord_moderator_target_combo", QtWidgets.QComboBox)
        if combo is not None:
            current = self._selected_moderator_bot_id()
            combo.blockSignals(True)
            combo.clear()
            for item in instances:
                instance_id = _safe_bot_id(item.get("id") or "")
                if not instance_id:
                    continue
                status = "connected" if (item.get("node_status") or {}).get("state") == "connected" else (
                    "running" if item.get("runtime_connected") else "stopped"
                )
                name = str(item.get("name") or instance_id)
                combo.addItem(f"{name} ({instance_id}, {status})", instance_id)
            if combo.count() == 0:
                for bot in self._bots_model:
                    if not isinstance(bot, dict) or bot.get("enabled") is False:
                        continue
                    instance_id = _safe_bot_id(bot.get("id") or bot.get("name") or "")
                    if instance_id:
                        combo.addItem(f"{bot.get('name') or instance_id} ({instance_id}, stopped)", instance_id)
            if combo.count() == 0:
                combo.addItem("No bot target available", "")
            if current:
                index = combo.findData(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)

        label = self._control("discord_moderator_state_label", QtWidgets.QLabel)
        if label is None:
            return
        moderator_state = self._latest_moderator_state(instances)
        if not moderator_state:
            self._last_moderator_state = {}
            label.setText("Moderator state appears after a bot is running.")
            enforce_checkbox = self._control("discord_moderator_enforce_mute_checkbox", QtWidgets.QCheckBox)
            if enforce_checkbox is not None:
                enforce_checkbox.blockSignals(True)
                enforce_checkbox.setChecked(False)
                enforce_checkbox.blockSignals(False)
        else:
            self._last_moderator_state = dict(moderator_state)
            pending = _safe_bot_id(_get(moderator_state, "pending_route.target_bot_id", "") or "")
            pending_human = str(
                _get(moderator_state, "pending_human_route.speaker_name", "")
                or _get(moderator_state, "pending_human_route.speaker_user_id", "")
                or ""
            ).strip()
            current_human = str(
                _get(moderator_state, "current_human_route.speaker_name", "")
                or _get(moderator_state, "current_human_route.speaker_user_id", "")
                or ""
            ).strip()
            current_bot_id = _safe_bot_id(moderator_state.get("current_bot_id") or "")
            current_bot = str(moderator_state.get("current_bot_name") or current_bot_id).strip() if current_bot_id else ""
            floor = _safe_bot_id(moderator_state.get("floor_target_bot_id") or "")
            human_floor = str(moderator_state.get("floor_speaker_name") or moderator_state.get("floor_speaker_user_id") or "").strip()
            last_call = str(moderator_state.get("last_call_on_bot_id") or "").strip()
            muted_items = [str(item) for item in moderator_state.get("muted_bot_ids") or [] if str(item).strip()]
            muted_human_items = [str(item) for item in moderator_state.get("muted_speaker_user_ids") or [] if str(item).strip()]
            only_items = [str(item) for item in moderator_state.get("only_bot_ids") or [] if str(item).strip()]
            muted_all = muted_items + [f"human:{item}" for item in muted_human_items]
            muted = ", ".join(muted_all) or "none"
            only = ", ".join(only_items) or "none"
            error = str(moderator_state.get("last_error") or "").strip()
            enforcer = str(moderator_state.get("enforcer_bot_name") or moderator_state.get("enforcer_bot_id") or "").strip()
            enforce_mute = bool(moderator_state.get("enforce_discord_mute"))
            pending_label = pending or pending_human or "none"
            active = bool(pending or pending_human or current_human or current_bot or floor or human_floor or muted_items or muted_human_items or only_items)
            current_label = current_human or current_bot or "auto"
            parts = [
                "moderator=active" if active else "moderator=inactive",
                f"hard moderator={enforcer or 'none'}",
                f"discord mute={'on' if enforce_mute else 'off'}",
                f"current={current_label}",
                f"pending={pending_label}",
                f"interrupts={'allowed' if moderator_state.get('allow_current_interruption') else 'blocked'}",
                f"allowed bot={floor or 'auto'}",
                f"speaker lock={human_floor or floor or 'none'}",
                f"last call={last_call or 'none'}",
                f"muted={muted}",
                f"only={only}",
            ]
            if error:
                parts.append(f"last error={error}")
            label.setText(" | ".join(parts))
            interrupt_checkbox = self._control("discord_moderator_allow_interrupt_current_checkbox", QtWidgets.QCheckBox)
            if interrupt_checkbox is not None:
                interrupt_checkbox.blockSignals(True)
                interrupt_checkbox.setChecked(bool(moderator_state.get("allow_current_interruption")))
                interrupt_checkbox.blockSignals(False)
            enforce_checkbox = self._control("discord_moderator_enforce_mute_checkbox", QtWidgets.QCheckBox)
            if enforce_checkbox is not None:
                enforce_checkbox.blockSignals(True)
                enforce_checkbox.setChecked(enforce_mute)
                enforce_checkbox.blockSignals(False)
        self._refresh_moderator_flow_labels(instances, moderator_state)
        self._refresh_moderator_route_flow(moderator_state)
        self._refresh_dead_air_status(moderator_state)
        self._refresh_dead_air_fallback_choices(instances)
        self._refresh_moderator_shortcuts(instances)

        table = self._control("discord_moderator_instances_table", QtWidgets.QTableWidget)
        if table is None:
            return
        table_state = _capture_table_refresh_state(table)
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(instances))
            current_bot = _safe_bot_id(moderator_state.get("current_bot_id") or "")
            pending = _safe_bot_id(_get(moderator_state, "pending_route.target_bot_id", "") or "")
            floor = _safe_bot_id(moderator_state.get("floor_target_bot_id") or "")
            muted = {_safe_bot_id(item) for item in moderator_state.get("muted_bot_ids") or []}
            for row, item in enumerate(instances):
                node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
                route_decision = node_status.get("last_route_decision") if isinstance(node_status.get("last_route_decision"), dict) else {}
                instance_id = _safe_bot_id(item.get("id") or "")
                values = [
                    str(instance_id or item.get("id") or ""),
                    str(item.get("name") or ""),
                    str(node_status.get("state") or ""),
                    "yes" if node_status.get("speaking") else "no",
                    "yes" if node_status.get("listening") else "no",
                    str(node_status.get("queued_audio") or "0"),
                    _progress_text(node_status.get("render_ready_chunks"), node_status.get("render_total_chunks")),
                    _progress_text(node_status.get("playback_completed_chunks"), node_status.get("playback_total_chunks")),
                    _route_decision_text(route_decision)[:180],
                ]
                background = None
                tooltip = ""
                if instance_id and instance_id == current_bot:
                    background = QtGui.QColor("#244f35")
                    tooltip = "This bot currently owns the moderator floor."
                elif instance_id and instance_id == pending:
                    background = QtGui.QColor("#334b73")
                    tooltip = "A moderator route is queued for this bot."
                elif instance_id and instance_id == floor:
                    background = QtGui.QColor("#4b3d68")
                    tooltip = "This bot is the active allowed speaker."
                elif instance_id and instance_id in muted:
                    background = QtGui.QColor("#423b42")
                    tooltip = "This bot is muted by the moderator."
                for col, value in enumerate(values):
                    cell = QtWidgets.QTableWidgetItem(value)
                    if background is not None:
                        cell.setBackground(background)
                    if tooltip:
                        cell.setToolTip(tooltip)
                    table.setItem(row, col, cell)
            _restore_table_refresh_state(table, table_state)
        finally:
            table.setUpdatesEnabled(True)
        self._refresh_moderator_participants_table(instances)
        self._refresh_moderator_action_buttons()

    def _latest_moderator_state(self, instances: list[dict[str, Any]]) -> dict[str, Any]:
        best_state: dict[str, Any] = {}
        best_updated = -1
        for item in instances:
            if not item.get("runtime_connected") and not item.get("endpoint_running"):
                continue
            node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
            state = node_status.get("moderator_state")
            if not isinstance(state, dict) or not state:
                continue
            try:
                updated = int(state.get("updated_at_ms") or 0)
            except (TypeError, ValueError):
                updated = 0
            if updated >= best_updated:
                best_state = state
                best_updated = updated
        return dict(best_state)

    def _refresh_moderator_participants_table(self, instances: list[dict[str, Any]]):
        table = self._control("discord_moderator_participants_table", QtWidgets.QTableWidget)
        if table is None:
            return
        participants_by_key: dict[str, dict[str, Any]] = {}
        capture_owner = ""
        moderator_state: dict[str, Any] = self._latest_moderator_state(instances)
        pending = ""
        pending_human_id = ""
        pending_human_name = ""
        current_human_id = ""
        current_human_name = ""
        current_bot = ""
        bot_lock = ""
        muted_bots: set[str] = set()
        only_bots: set[str] = set()
        for item in instances:
            instance_id = _safe_bot_id(item.get("id") or "")
            node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
            if not capture_owner:
                capture_owner = str(node_status.get("capture_owner") or "").strip()
            if instance_id:
                participants_by_key[f"bot:{instance_id}"] = {
                    "id": instance_id,
                    "name": str(item.get("name") or instance_id).strip(),
                    "kind": "bot",
                    "connected": "yes" if node_status.get("state") == "connected" else ("running" if item.get("runtime_connected") else "no"),
                    "speaking": "yes" if node_status.get("speaking") else "no",
                    "listening": "yes" if node_status.get("listening") else "no",
                    "queued": str(node_status.get("queued_audio") or "0"),
                }
            for participant in node_status.get("participants") or []:
                if not isinstance(participant, dict):
                    continue
                participant_id = str(participant.get("id") or "").strip()
                name = str(participant.get("name") or participant_id).strip()
                if not participant_id and not name:
                    continue
                kind = "bot" if participant.get("is_bot") else "human"
                if kind == "bot":
                    bot_id = self._bot_id_for_participant({"id": participant_id, "name": name, "kind": kind})
                    key = f"bot:{bot_id or _safe_bot_id(name) or participant_id}"
                    existing = participants_by_key.get(key, {})
                    participants_by_key[key] = {
                        **existing,
                        "id": bot_id or existing.get("id") or _safe_bot_id(name) or participant_id,
                        "name": existing.get("name") or name,
                        "kind": "bot",
                        "connected": "yes",
                    }
                else:
                    participants_by_key[f"human:{participant_id or name}"] = {
                        "id": participant_id,
                        "name": name,
                        "kind": "human",
                        "connected": "yes",
                        "speaking": "",
                        "listening": "",
                        "queued": "",
                        "name_conflict": bool(participant.get("display_name_conflict")),
                        "name_conflict_reason": str(participant.get("name_conflict_reason") or "").strip(),
                    }
        if moderator_state:
            pending = _safe_bot_id(_get(moderator_state, "pending_route.target_bot_id", "") or "")
            pending_human_id = str(
                _get(moderator_state, "pending_human_route.speaker_user_id", "")
                or ""
            ).strip()
            pending_human_name = str(
                _get(moderator_state, "pending_human_route.speaker_name", "")
                or ""
            ).strip()
            current_human_id = str(
                _get(moderator_state, "current_human_route.speaker_user_id", "")
                or ""
            ).strip()
            current_human_name = str(
                _get(moderator_state, "current_human_route.speaker_name", "")
                or ""
            ).strip()
            current_bot = _safe_bot_id(moderator_state.get("current_bot_id") or "")
            bot_lock = _safe_bot_id(moderator_state.get("floor_target_bot_id") or "")
            muted_bots = {_safe_bot_id(item) for item in moderator_state.get("muted_bot_ids") or []}
            only_bots = {_safe_bot_id(item) for item in moderator_state.get("only_bot_ids") or []}
        rows = sorted(participants_by_key.values(), key=lambda item: item["name"].lower())
        table_state = _capture_table_refresh_state(table)
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(rows))
            floor_user_id = str(moderator_state.get("floor_speaker_user_id") or "").strip()
            floor_name = str(moderator_state.get("floor_speaker_name") or "").strip()
            muted_humans = {str(item).strip() for item in moderator_state.get("muted_speaker_user_ids") or [] if str(item).strip()}
            for row, item in enumerate(rows):
                is_owner = "yes" if capture_owner and (item["id"] in capture_owner or item["name"] in capture_owner) else ""
                is_human_lock = (
                    item["kind"] == "human"
                    and (
                        (floor_user_id and item["id"] == floor_user_id)
                        or (floor_name and item["name"] == floor_name)
                    )
                )
                item_id = _safe_bot_id(item["id"]) if item["kind"] == "bot" else str(item["id"] or "").strip()
                state_bits: list[str] = []
                if item["kind"] == "bot" and current_bot and item_id == current_bot:
                    state_bits.append("current")
                if item["kind"] == "human" and (
                    (current_human_id and item_id == current_human_id)
                    or (current_human_name and item["name"] == current_human_name)
                ):
                    state_bits.append("current")
                if item["kind"] == "bot" and item_id == pending:
                    state_bits.append("next")
                if item["kind"] == "human" and (
                    (pending_human_id and item_id == pending_human_id)
                    or (pending_human_name and item["name"] == pending_human_name)
                ):
                    state_bits.append("next")
                if item["kind"] == "bot" and item_id == bot_lock:
                    state_bits.append("allowed")
                if item["kind"] == "bot" and item_id in muted_bots:
                    state_bits.append("muted")
                if item["kind"] == "bot" and item_id in only_bots:
                    state_bits.append("only")
                if item["kind"] == "human" and is_human_lock:
                    state_bits.append("accepted")
                if item["kind"] == "human" and item_id in muted_humans:
                    state_bits.append("muted")
                if item.get("name_conflict"):
                    state_bits.append("name conflict")
                if is_owner:
                    state_bits.append("capture owner")
                values = [
                    item["id"],
                    item["name"],
                    item["kind"],
                    item.get("connected", ""),
                    item.get("speaking", ""),
                    item.get("listening", ""),
                    item.get("queued", ""),
                    ", ".join(state_bits),
                ]
                for col, value in enumerate(values):
                    cell = QtWidgets.QTableWidgetItem(str(value or ""))
                    if "name conflict" in state_bits:
                        cell.setBackground(QtGui.QColor("#5a3f25"))
                        cell.setToolTip(item.get("name_conflict_reason") or "Duplicate display name. Rename or alias this participant before routing.")
                    elif "muted" in state_bits:
                        cell.setBackground(QtGui.QColor("#423b42"))
                        cell.setToolTip("This participant is muted by the moderator.")
                    elif "current" in state_bits:
                        cell.setBackground(QtGui.QColor("#244f35"))
                        cell.setToolTip("This participant currently has the floor.")
                    elif "accepted" in state_bits or "allowed" in state_bits:
                        cell.setBackground(QtGui.QColor("#4b3d68"))
                        cell.setToolTip("This participant is the active allowed speaker.")
                    elif "next" in state_bits:
                        cell.setBackground(QtGui.QColor("#334b73"))
                        cell.setToolTip("This participant is queued as the next routed speaker.")
                    elif is_owner:
                        cell.setBackground(QtGui.QColor("#334b73"))
                        cell.setToolTip("This bot process currently owns shared audio capture.")
                    table.setItem(row, col, cell)
            _restore_table_refresh_state(table, table_state)
        finally:
            table.setUpdatesEnabled(True)
        self._refresh_moderator_action_buttons()

    def _refresh_moderator_action_buttons(self):
        running = bool(self._running_instance_ids())
        running_ids = set(self._running_instance_ids())
        participant = self._selected_moderator_participant()
        participant_selected = bool(participant)
        participant_name_conflict = "name conflict" in str(participant.get("moderator_state") or "").lower()
        bot_selected = bool(self._selected_moderator_bot_or_participant_bot_id())
        selected_bot = self._selected_moderator_bot_id()
        moderator_state = self._last_moderator_state if isinstance(self._last_moderator_state, dict) else {}
        enforcer = _safe_bot_id(moderator_state.get("enforcer_bot_id") or "")
        enabled = running and not self._operation_running
        for name in (
            "discord_moderator_route_next_button",
            "discord_moderator_give_floor_button",
            "discord_moderator_mute_button",
            "discord_moderator_unmute_button",
        ):
            control = self.controls.get(name)
            if control is not None:
                control.setEnabled(bool(enabled and (participant_selected or bot_selected)))
                if participant_name_conflict:
                    control.setEnabled(False)
                    control.setToolTip("This participant has a duplicate display name. Rename or alias the participant before routing.")
        announce_control = self.controls.get("discord_moderator_announce_button")
        if announce_control is not None:
            announce_control.setEnabled(bool(enabled and bot_selected))
        call_control = self.controls.get("discord_moderator_call_on_button")
        if call_control is not None:
            call_control.setEnabled(bool(enabled and bot_selected and not self._moderator_has_speaking_bot()))
        for name in (
            "discord_moderator_clear_pending_button",
            "discord_moderator_clear_floor_button",
            "discord_moderator_clear_button",
            "discord_moderator_stop_all_button",
            "discord_moderator_clear_all_queues_button",
            "discord_moderator_allow_interrupt_current_checkbox",
        ):
            control = self.controls.get(name)
            if control is not None:
                control.setEnabled(bool(enabled))
        set_enforcer = self.controls.get("discord_moderator_set_enforcer_button")
        if set_enforcer is not None:
            set_enforcer.setEnabled(bool(enabled and selected_bot and selected_bot in running_ids))
        clear_enforcer = self.controls.get("discord_moderator_clear_enforcer_button")
        if clear_enforcer is not None:
            clear_enforcer.setEnabled(bool(enabled and enforcer and enforcer in running_ids))
        enforce_checkbox = self.controls.get("discord_moderator_enforce_mute_checkbox")
        if enforce_checkbox is not None:
            enforce_checkbox.setEnabled(bool(enabled and enforcer and enforcer in running_ids))

    def _moderator_has_speaking_bot(self) -> bool:
        for item in self._last_instances:
            node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
            if node_status.get("speaking"):
                return True
        return False

    def _refresh_moderator_flow_labels(self, instances: list[dict[str, Any]], moderator_state: dict[str, Any]):
        speaking = []
        listening = False
        reply_floor_owner = ""
        queued = []
        last_route = ""
        for item in instances:
            name = str(item.get("name") or item.get("id") or "").strip()
            node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
            if node_status.get("speaking"):
                speaking.append(name)
            if node_status.get("listening"):
                listening = True
            if not reply_floor_owner:
                reply_floor_owner = str(node_status.get("reply_floor_owner_bot") or "").strip()
            queued_count = int(node_status.get("queued_audio") or 0)
            if queued_count > 0:
                queued.append(f"{name} ({queued_count})")
            route_decision = node_status.get("last_route_decision") if isinstance(node_status.get("last_route_decision"), dict) else {}
            route_text = _route_decision_text(route_decision)
            if route_text:
                last_route = f"{name}: {route_text}"

        pending = _safe_bot_id(_get(moderator_state, "pending_route.target_bot_id", "") or "")
        pending_human = str(
            _get(moderator_state, "pending_human_route.speaker_name", "")
            or _get(moderator_state, "pending_human_route.speaker_user_id", "")
            or ""
        ).strip()
        current_human = str(
            _get(moderator_state, "current_human_route.speaker_name", "")
            or _get(moderator_state, "current_human_route.speaker_user_id", "")
            or ""
        ).strip()
        current_bot_id = _safe_bot_id(moderator_state.get("current_bot_id") or "")
        current_bot = str(moderator_state.get("current_bot_name") or current_bot_id).strip() if current_bot_id else ""
        bot_floor = _safe_bot_id(moderator_state.get("floor_target_bot_id") or "")
        human_floor = str(moderator_state.get("floor_speaker_name") or moderator_state.get("floor_speaker_user_id") or "").strip()
        last_command = str(moderator_state.get("last_command") or "").strip()
        last_error = str(moderator_state.get("last_error") or "").strip()
        muted = [str(item) for item in moderator_state.get("muted_bot_ids") or [] if str(item).strip()]
        muted_humans = [str(item) for item in moderator_state.get("muted_speaker_user_ids") or [] if str(item).strip()]
        only = [str(item) for item in moderator_state.get("only_bot_ids") or [] if str(item).strip()]

        if current_bot:
            now = f"Current: {current_bot}"
        elif current_human:
            now = f"Current: {current_human}"
        elif listening:
            now = "Listening to Discord speech"
        else:
            now = "Room is quiet"

        if pending:
            next_text = f"Next: {pending}"
        elif pending_human:
            next_text = f"Next: {pending_human}"
        else:
            next_text = "Next: automatic"

        speaker_lock = bot_floor or human_floor or "automatic routing"
        bot_floor_text = f"Allowed speaker: {speaker_lock}"
        if reply_floor_owner:
            bot_floor_text += f" | currently vocalizing: {reply_floor_owner}"
        muted_all = muted + [f"human:{item}" for item in muted_humans]
        if muted_all:
            bot_floor_text += f" | muted: {', '.join(muted_all)}"
        if only:
            bot_floor_text += f" | only: {', '.join(only)}"

        human_floor_text = "Speaker type is handled internally; moderation uses participants."

        if pending:
            action = f"When the next accepted utterance arrives, it will route to {pending}."
        elif pending_human:
            if current_bot or current_human:
                action = f"{pending_human} is queued next. Routing waits until the current speaker finishes."
            else:
                action = f"{pending_human} is queued next. Only this participant's next speech is accepted."
        elif bot_floor:
            action = f"{bot_floor} is the persistent allowed bot speaker until cleared."
        elif human_floor:
            action = f"{human_floor} is the persistent allowed speaker until cleared."
        elif current_bot or current_human:
            action = "No manual next target. Click a Next button now to choose who answers after the current speaker finishes."
        else:
            action = "Room is quiet. Use Call Target Now or a Call-now shortcut to make a bot speak."

        badges: list[tuple[str, str]] = []
        if current_bot:
            badges.append(("current", current_bot))
        if current_human:
            badges.append(("current", current_human))
        if pending:
            badges.append(("next", pending))
        if pending_human:
            badges.append(("next", pending_human))
        if bot_floor:
            badges.append(("allowed bot", bot_floor))
        if human_floor:
            badges.append(("speaker lock", human_floor))
        if muted_all:
            badges.append(("muted", ", ".join(muted_all)))
        if only:
            badges.append(("only", ", ".join(only)))
        if queued:
            badges.append(("queued", ", ".join(queued)))
        badges_text = _moderator_badges_html(badges) if badges else "No active moderator locks or queues."

        self._set_text("discord_moderator_now_label", now)
        self._set_text("discord_moderator_next_label", next_text)
        self._set_text("discord_moderator_badges_label", badges_text)
        self._set_text("discord_moderator_bot_floor_label", bot_floor_text)
        self._set_text("discord_moderator_human_floor_label", human_floor_text)
        self._set_text("discord_moderator_last_command_label", last_command or "No manual command yet.")
        self._set_text("discord_moderator_last_route_label", last_route or "No route decision yet.")
        self._refresh_moderator_selected_action_label()
        self._set_text("discord_moderator_warning_label", _moderator_warning_text(last_error))
        self._set_text("discord_moderator_next_action_label", action)

    def _refresh_moderator_route_flow(self, moderator_state: dict[str, Any]):
        view = self._control("discord_moderator_route_flow_view", QtWidgets.QPlainTextEdit)
        if view is None:
            return
        route_flow = moderator_state.get("route_flow") if isinstance(moderator_state, dict) else []
        if not isinstance(route_flow, list) or not route_flow:
            self._route_flow_rendered_lines = []
            self._route_flow_rendered_keys.clear()
            _set_route_flow_text_preserving_scroll(view, ["No shared route flow yet."])
            return

        reported_entries: list[tuple[str, str]] = []
        for entry in route_flow:
            if not isinstance(entry, dict):
                continue
            line = _route_flow_line(entry)
            if not line:
                continue
            reported_entries.append((_route_flow_entry_key(entry, line), line))
        if not reported_entries:
            self._route_flow_rendered_lines = []
            self._route_flow_rendered_keys.clear()
            _set_route_flow_text_preserving_scroll(view, ["No shared route flow yet."])
            return

        if view.toPlainText().strip() == "No shared route flow yet.":
            self._route_flow_rendered_lines = []
            self._route_flow_rendered_keys.clear()
        if not self._route_flow_rendered_lines:
            self._route_flow_rendered_lines = [line for _key, line in reported_entries]
            self._route_flow_rendered_keys = {key for key, _line in reported_entries}
            _set_route_flow_text_preserving_scroll(view, self._route_flow_rendered_lines)
            return

        added_lines: list[str] = []
        for key, line in reported_entries:
            if key in self._route_flow_rendered_keys:
                continue
            self._route_flow_rendered_keys.add(key)
            added_lines.append(line)
        if not added_lines:
            return
        _append_route_flow_text_preserving_scroll(view, added_lines)
        self._route_flow_rendered_lines.extend(added_lines)

    def _refresh_dead_air_status(self, moderator_state: dict[str, Any]):
        label = self._control("discord_dead_air_status_label", QtWidgets.QLabel)
        if label is None:
            return
        recovery = moderator_state.get("dead_air_recovery") if isinstance(moderator_state, dict) else {}
        if not isinstance(recovery, dict) or not recovery:
            if self._checked("discord_dead_air_enabled_checkbox"):
                label.setText("on | no recovery activity yet | waiting for running bridge report")
            else:
                label.setText("off | no recovery activity yet")
            return
        recovery_enabled = bool(recovery.get("enabled"))
        enabled = "on" if recovery_enabled else "off"
        reason = str(recovery.get("last_reason") or "none").strip()
        next_target = str(recovery.get("last_next_target_bot_id") or "none").strip() if recovery_enabled else "none"
        cooldown_ms = int(float(recovery.get("cooldown_remaining_ms") or 0))
        error = str(recovery.get("last_error") or "").strip()
        parts = [enabled, f"reason={reason}", f"next={next_target}"]
        if cooldown_ms > 0:
            parts.append(f"cooldown={cooldown_ms / 1000:.1f}s")
        if error:
            parts.append(f"error={error}")
        label.setText(" | ".join(parts))

    def _refresh_dead_air_fallback_choices(self, instances: list[dict[str, Any]]):
        combo = self._control("discord_dead_air_fallback_target_combo", QtWidgets.QComboBox)
        if combo is None:
            return
        current = combo.currentText().strip()
        values = [""]
        seen: set[str] = set()
        for bot in self._bots_model:
            bot_id = str(bot.get("id") or "").strip()
            key = bot_id.lower()
            if bot_id and key not in seen:
                values.append(bot_id)
                seen.add(key)
        for instance in instances:
            bot_id = str(instance.get("id") or "").strip()
            key = bot_id.lower()
            if bot_id and key not in seen:
                values.append(bot_id)
                seen.add(key)
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(values)
        combo.setEditText(current)
        combo.blockSignals(False)

    def _refresh_moderator_shortcuts(self, instances: list[dict[str, Any]]):
        container = self._control("discord_moderator_shortcuts_container", QtWidgets.QWidget)
        hint = self._control("discord_moderator_shortcuts_hint_label", QtWidgets.QLabel)
        if container is None or not isinstance(container.layout(), QtWidgets.QGridLayout):
            return
        layout = container.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        bot_rows: list[tuple[str, str]] = []
        participants: dict[str, dict[str, str]] = {}
        for item in instances:
            instance_id = _safe_bot_id(item.get("id") or "")
            if instance_id and item.get("runtime_connected"):
                bot_rows.append((instance_id, str(item.get("name") or instance_id)))
            node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
            for participant in node_status.get("participants") or []:
                if not isinstance(participant, dict):
                    continue
                participant_id = str(participant.get("id") or "").strip()
                name = str(participant.get("name") or participant_id).strip()
                if not participant_id or not name or participant.get("is_bot"):
                    continue
                participants[participant_id] = {"id": participant_id, "name": name}

        row = 0
        shortcuts_enabled = bool(self._running_instance_ids()) and not self._operation_running
        room_quiet = not self._moderator_has_speaking_bot()
        if bot_rows or participants:
            next_title = QtWidgets.QLabel("After current speech ends, route next turn to:", container)
            next_title.setToolTip("Safe queue: these choices do not interrupt current vocalization.")
            layout.addWidget(next_title, row, 0, 1, 2)
            row += 1
        for bot_id, name in bot_rows:
            next_button = QtWidgets.QPushButton(f"Next: {name}", container)
            next_button.setToolTip("Route the next eligible Discord utterance to this bot. Passive: waits for the next utterance.")
            next_button.setEnabled(shortcuts_enabled)
            next_button.clicked.connect(lambda _checked=False, target=bot_id: self._send_moderator_command_to("moderator_route_next", target))
            layout.addWidget(next_button, row, 0, 1, 2)
            row += 1
        for participant in sorted(participants.values(), key=lambda item: item["name"].lower()):
            human_button = QtWidgets.QPushButton(f"Next: {participant['name']}", container)
            human_button.setToolTip("Make this participant the next speaker.")
            human_button.setEnabled(shortcuts_enabled)
            human_button.clicked.connect(
                lambda _checked=False, p=participant: self._send_moderator_human_next_for(p["id"], p["name"])
            )
            layout.addWidget(human_button, row, 0, 1, 2)
            row += 1

        if bot_rows:
            call_title = QtWidgets.QLabel("Room quiet: make a bot speak now:", container)
            call_title.setToolTip("Active call: disabled while another bot is speaking to avoid accidental overlap.")
            layout.addWidget(call_title, row, 0, 1, 2)
            row += 1
        for bot_id, name in bot_rows:
            call_button = QtWidgets.QPushButton(f"Call now: {name}", container)
            call_button.setToolTip("Ask this bot to generate and speak now. Active: only enabled while no bot is currently speaking.")
            call_button.setEnabled(bool(shortcuts_enabled and room_quiet))
            call_button.clicked.connect(lambda _checked=False, target=bot_id: self._send_moderator_call_on_to(target))
            layout.addWidget(call_button, row, 0, 1, 2)
            row += 1

        if hint is not None:
            if bot_rows or participants:
                hint.setText(
                    "Use Next buttons while someone is speaking. Call-now buttons become available when no bot is speaking."
                )
            else:
                hint.setText("Start the bridge to show safe next-speaker choices and quiet-room call buttons.")

    def _refresh_moderator_selected_action_label(self):
        target = self._selected_moderator_bot_id()
        participant = self._selected_moderator_participant()
        speaking = self._moderator_has_speaking_bot()
        if participant.get("kind") == "human":
            name = participant.get("name") or participant.get("id") or "selected human"
            text = f"Selected participant: {name} (human). Set Next Speaker makes this human the next accepted speaker and pauses bot routing until they speak; Allow Only This Speaker makes that lock persistent."
        elif target:
            if speaking:
                text = f"Selected participant: {target} (bot). Set Next Speaker is a safe one-shot route after the current speaker finishes; Allow Only This Speaker makes it persistent."
            else:
                text = f"Selected participant: {target} (bot). Call Target Now makes this bot speak immediately; Set Next Speaker queues one next route; Allow Only This Speaker keeps routing to it."
        else:
            text = "Select any room participant to see the available moderator action."
        self._set_text("discord_moderator_selected_action_label", text)

    def _refresh_live_bot_state_label(self):
        label = self._control("discord_live_bot_state_label", QtWidgets.QLabel)
        if label is None:
            return
        bot_id = self._selected_live_bot_id()
        item = next((candidate for candidate in self._last_instances if str(candidate.get("id") or "") == bot_id), None)
        if not item:
            label.setText("No bot selected. Start the bridge, then select a bot for live controls.")
            return
        node_status = item.get("node_status") if isinstance(item.get("node_status"), dict) else {}
        runtime_status = item.get("runtime_status") if isinstance(item.get("runtime_status"), dict) else {}
        route_decision = node_status.get("last_route_decision") if isinstance(node_status.get("last_route_decision"), dict) else {}
        parts = [
            f"node={'running' if item.get('runtime_connected') else 'stopped'}",
            f"endpoint={'running' if item.get('endpoint_running') else 'stopped'}",
            f"discord={node_status.get('state') or 'unknown'}",
            f"speaking={'yes' if node_status.get('speaking') else 'no'}",
            f"listening={'yes' if node_status.get('listening') else 'no'}",
            f"queued={node_status.get('queued_audio') or 0}",
        ]
        transcript = str(node_status.get("last_transcript") or runtime_status.get("last_transcript") or "").strip()
        route_text = _route_decision_text(route_decision)
        if transcript:
            parts.append(f"last transcript={transcript[:90]}")
        if route_text:
            parts.append(f"route={route_text[:90]}")
        label.setText(" | ".join(parts))

    def _refresh_logs(self):
        preview = self._control("discord_logs_preview", QtWidgets.QPlainTextEdit)
        if preview is None:
            return
        text = self._recent_log_text()
        _set_plain_text_preserving_scroll(preview, text)

    def _recent_log_text(self) -> str:
        log_dir = ADDON_DIR / "runtime_logs"
        if not log_dir.exists():
            return "No bridge logs found yet."
        files = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)[:3]
        blocks = []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
            except Exception as exc:
                lines = [f"Could not read log: {exc}"]
            blocks.append(f"--- {path.name} ---\n" + "\n".join(_redact_text(line) for line in lines))
        return "\n\n".join(blocks) if blocks else "No bridge logs found yet."

    def _apply_tooltips(self):
        tips = {
            "discord_bridge_save_button": "Save Discord Voice Bridge settings to ignored local settings. Direct token fields are preserved or written only to local settings.",
            "discord_bridge_start_button": "Validate settings, start the local NC endpoint, then launch the Discord Node bridge process.",
            "discord_bridge_stop_button": "Stop running Discord bridge processes and their local NC runtime endpoints.",
            "discord_bridge_restart_button": "Stop and start the bridge again after saving current settings.",
            "discord_bridge_refresh_button": "Refresh bridge status, per-bot process state, endpoint state, and recent logs.",
            "discord_enabled_checkbox": "Enables this addon configuration. Disabled settings remain saved but should not auto-launch.",
            "discord_start_on_launch_checkbox": "Start the Discord bridge automatically when Neural Companion launches and the addon initializes.",
            "discord_auto_start_checkbox": "Compatibility auto-start flag for local testing. Start on NC launch is the preferred user-facing switch.",
            "discord_bridge_mode_combo": "Bridge transport mode. HTTP / Discord launches the Node Discord bridge; TinyMVP local room launches the Python fake-room bridge for local testing without Discord.",
            "discord_tiny_mvp_group": "Settings used only when Bridge mode is TinyMVP.",
            "discord_tiny_mvp_url_edit": "TinyMVP fake voice-room server URL. Start Bridge will start the bundled TinyMVP room first when this URL is not already reachable.",
            "discord_tiny_mvp_start_with_gui_checkbox": "Open the TinyMVP passive monitor window when NC starts the bundled local room server.",
            "discord_tiny_mvp_bridge_script_edit": "Path to tiny_voice_bridge.py. Leave blank when TinyMVP is a sibling folder next to this NC repo.",
            "discord_tiny_mvp_poll_seconds_spin": "How often each local bridge bot polls TinyMVP room state.",
            "discord_tiny_mvp_capture_mic_checkbox": "Use NC's local microphone as the human speaker while TinyMVP mode is running. Accepted speech is routed through the normal Discord bridge runtime.",
            "discord_route_protected_mic_speech_checkbox": "When the moderator protects Current, still route microphone speech into context without interrupting playback or taking the floor.",
            "discord_tiny_mvp_mic_user_id_edit": "Fake human participant ID used when TinyMVP microphone speech is injected into the local room.",
            "discord_tiny_mvp_mic_user_name_edit": "Display name used when TinyMVP microphone speech is injected into the local room.",
            "discord_tiny_mvp_mic_seconds_spin": "Maximum phrase length for NC microphone input in TinyMVP mode.",
            "discord_tiny_mvp_mic_sample_rate_spin": "Sample rate for TinyMVP microphone WAV capture. 16000 Hz mono is usually enough for STT testing.",
            "discord_tiny_mvp_mic_device_edit": "Optional microphone name fragment or index. Leave blank to use the default microphone.",
            "discord_context_entries_spin": "Default number of isolated Discord history entries sent to the chat provider. Per-bot settings can override this.",
            "discord_token_env_edit": "Name of the environment variable that contains the Discord bot token. The token itself is not shown or saved by this UI.",
            "discord_local_token_edit": "Optional write-only local test token for single-bot setup. Leave blank to keep the existing ignored local token.",
            "discord_guild_id_edit": "Discord server/guild ID. Enable Discord Developer Mode and copy the server ID.",
            "discord_voice_channel_id_edit": "Discord voice channel ID the bot should join.",
            "discord_allowed_user_id_edit": "Optional comma/space separated Discord user IDs that may trigger replies when answer mode restricts speakers.",
            "discord_answer_mode_combo": "Controls which Discord speakers can trigger the bot. Use anyone for shared test rooms, or allowed users for private testing.",
            "discord_min_turn_seconds_spin": "Captured audio shorter than this is ignored before STT. Raise it if breaths/clicks trigger turns.",
            "discord_silence_ms_spin": "Silence duration required before a voice turn is finalized. Raise it if turns are split too early.",
            "discord_max_turn_seconds_spin": "Maximum human capture length in seconds. Use -1 for no hard cap.",
            "discord_bot_max_turn_seconds_spin": "Maximum bot-to-bot capture length in seconds. Use -1 for no hard cap when bots speak long turns.",
            "discord_bot_idle_finalize_ms_spin": "Silence duration used to finalize captured speech from other Discord bots.",
            "discord_ignore_low_information_checkbox": "Drops short STT hallucinations like 'and' or '1' before they reach the chat provider.",
            "discord_low_information_max_seconds_spin": "Only clips at or below this duration are checked against the low-information transcript list.",
            "discord_low_information_transcripts_edit": "Exact normalized short transcripts to ignore. Avoid adding real short answers like 'no'.",
            "discord_wav_sample_rate_combo": "Sample rate for saved/STT capture WAVs. 16000 Hz mono is recommended for speed and disk use.",
            "discord_wav_channels_combo": "Channel count for saved/STT capture WAVs. Mono is recommended for speech recognition.",
            "discord_save_captures_checkbox": "Save captured Discord speech WAVs for debugging. Cleanup settings remove old files.",
            "discord_shared_capture_owner_checkbox": "Use one active bot per voice channel to process human captures. Other local bots still monitor interruptions but skip STT/routing work.",
            "discord_capture_owner_ttl_spin": "How long a capture-owner heartbeat may be stale before another running bot takes over capture processing.",
            "discord_play_test_tone_checkbox": "Play a short test tone when the bot joins Discord. Prefer the one-shot test-tone restart button for normal checks.",
            "discord_queue_replies_checkbox": "Queue reply audio chunks so Discord playback stays serialized instead of overlapping.",
            "discord_interrupt_reply_checkbox": "Allow user speech to interrupt the current reply after immunity and decision rules allow it.",
            "discord_interrupt_after_seconds_spin": "Stops current reply audio after this much decoded user speech. The effective threshold is never lower than Min turn seconds.",
            "discord_reply_immunity_seconds_spin": "Protects the start of bot speech from immediate interruption.",
            "discord_discard_bot_speech_checkbox": "When a human intervenes, discard partial captures from other bots to prevent cascading bot-to-bot replies.",
            "discord_coordinate_bot_replies_checkbox": "When multiple NC bots respond, let the first bot with playable audio speak and discard later simultaneous replies.",
            "discord_reply_floor_stale_seconds_spin": "How long a bot can hold the shared playback claim before another bot treats the claim as stale.",
            "discord_initial_buffer_chunks_spin": "How many rendered TTS chunks to buffer before playback starts. Lower values reduce latency; higher values reduce stutter risk.",
            "discord_filter_enabled_checkbox": "Enable response gating so Discord room talk can be stored in context without always making the bot answer.",
            "discord_filter_mode_combo": "Choose how the addon decides whether to answer: sentinel reply, separate LLM judge, or local mention/question rules.",
            "discord_bot_names_edit": "Default comma-separated names/call words that mean the Discord utterance is directed at the bot.",
            "discord_answer_uncertain_checkbox": "If the response filter cannot confidently decide, answer instead of staying silent.",
            "discord_persist_room_context_checkbox": "Keep the shared Discord room context JSON across NC/bridge restarts. Leave off to start each launch with clean room context.",
            "discord_room_router_enabled_checkbox": "Enable the shared router that decides which configured bot should answer each Discord room utterance.",
            "discord_room_router_mode_combo": "Choose whether routing is decided by the selected chat provider or by local mention/name matching.",
            "discord_room_router_human_to_bot_checkbox": "Allow human speech to be routed to configured Discord bot instances.",
            "discord_room_router_bot_to_bot_checkbox": "Allow completed bot replies to be routed to other configured bot instances.",
            "discord_room_router_exclude_speaker_checkbox": "Remove the speaking bot from eligible targets before routing, which prevents most self-reply loops.",
            "discord_room_router_group_invite_checkbox": "Allow invitations to multiple named bots or the bot group to select one best target.",
            "discord_room_router_open_room_checkbox": "Allow open invitations to the room or all participants to select one eligible bot.",
            "discord_room_router_self_route_combo": "Controls what happens if routing selects the same bot that spoke.",
            "discord_room_router_uncertain_checkbox": "Allow fallback routing when the router cannot make a clear decision.",
            "discord_room_router_uncertain_target_combo": "Choose which target is used when uncertainty fallback is enabled.",
            "discord_room_router_decision_timeout_spin": "How long non-owner bot instances wait for a shared route decision.",
            "discord_room_router_decision_tokens_spin": "Output token budget for the router JSON decision. Reasoning models may need extra budget.",
            "discord_room_router_route_window_spin": "Time bucket used to group the same utterance captured by multiple bot instances.",
            "discord_room_router_text_routing_checkbox": "Route known completed bot reply text directly instead of waiting for Discord audio capture and STT.",
            "discord_room_router_prebuffer_checkbox": "With LLM router, direct text routing, and reply-floor coordination enabled, let the next selected bot generate/TTS while the current bot is still speaking. Playback still waits for the floor.",
            "discord_room_router_competing_policy_combo": "Policy label for simultaneous bot replies. The current bridge uses first-ready-wins behavior.",
            "discord_room_router_floor_mode_combo": "Shared playback coordination behavior for multi-bot rooms.",
            "discord_dead_air_enabled_checkbox": "Let the selected active Moderator bot recover when a completed turn selects no next speaker.",
            "discord_dead_air_cooldown_spin": "Minimum seconds between automatic Moderator recovery turns. Zero means no cooldown.",
            "discord_dead_air_silence_timeout_spin": "Quiet-room grace period before automatic Moderator recovery runs. Set to 0 only when you want immediate recovery after a no-route turn.",
            "discord_dead_air_trigger_combo": "Choose whether recovery triggers only after bot speech or also after unrouted human speech.",
            "discord_dead_air_action_combo": "Choose whether the Moderator speaks, calls the next bot, or silently calls the next bot.",
            "discord_dead_air_strategy_combo": "Choose how the recovery system selects the next speaker after dead air.",
            "discord_dead_air_fallback_target_combo": "Optional bot id used when the selected-fallback strategy is active.",
            "discord_dead_air_status_label": "Live recovery status reported by the running bridge: enabled state, latest reason, next target, cooldown, and errors.",
            "discord_room_router_poll_ms_spin": "How often bot processes check for routed text addressed to them.",
            "discord_room_router_text_age_spin": "Discard routed text handoffs older than this many seconds.",
            "discord_room_router_rules_prompt_edit": "Optional editable LLM router instructions. Leave blank for the built-in default rules.",
            "discord_replace_nc_prompt_checkbox": "Use the Discord persona prompt instead of the selected NC persona prompt for top-level single-bot mode.",
            "discord_persona_prompt_edit": "Discord-only persona/system instructions. Keep them speech-friendly and avoid exposing bridge mechanics.",
            "discord_bots_json_edit": "Advanced multi-bot overrides. Tokens should use token_env_var rather than direct token fields.",
            "discord_format_bots_button": "Format and reload the advanced bots JSON into the structured bot editor.",
            "discord_voice_clone_wav_edit": "Optional WAV filename from the root voices folder. Leave blank to use the selected NC Persona voice. Validation warns if the file is missing.",
            "discord_runtime_host_edit": "Local host for the addon runtime endpoint. Keep this on 127.0.0.1, localhost, or ::1 for safety.",
            "discord_runtime_port_spin": "Default local runtime port. Each enabled bot instance must use a unique port.",
            "discord_session_mode_combo": "Discord context mode. Isolated Discord history is the supported safe mode for this addon.",
            "discord_runtime_http_endpoint_edit": "Generated read-only HTTP endpoint derived from host and port.",
            "discord_runtime_ws_endpoint_edit": "Generated read-only bridge endpoint derived from host and port.",
            "discord_use_selected_stt_checkbox": "Use the STT provider currently selected in Neural Companion for Discord speech transcription.",
            "discord_use_selected_chat_checkbox": "Use the chat provider currently selected in Neural Companion for Discord replies.",
            "discord_use_selected_tts_checkbox": "Use the TTS provider currently selected in Neural Companion for Discord reply audio.",
            "discord_allow_non_localhost_checkbox": "Advanced and normally off. Allows binding the addon runtime endpoint to a non-localhost address. Only enable on a trusted private network after understanding the security risk.",
            "discord_use_rag_context_checkbox": "Allow Discord turns to request context from NC's active RAG Context addon. Disable this for Discord-only sessions that should ignore the selected local RAG database.",
            "discord_rag_status_label": "RAG injection only happens when this checkbox is enabled, the RAG Context addon is enabled globally, and matching chunks are found.",
            "discord_wav_max_age_minutes_spin": "Delete old capture/reply WAV files after this many minutes. Use 0 only when debugging cleanup.",
            "discord_cleanup_interval_minutes_spin": "Minimum interval between automatic cleanup passes for capture and reply WAV folders.",
            "discord_bot_list": "Configured Discord bot instances. Each enabled bot can join a Discord voice channel with its own persona and voice.",
            "discord_bot_enabled_checkbox": "Enable or disable this bot instance without deleting its saved settings.",
            "discord_bot_id_edit": "Stable local ID for this bot instance. Used for status, logs, and preserving local secrets.",
            "discord_bot_display_name_edit": "Human-readable label for the UI and logs. This does not rename the Discord application.",
            "discord_bot_token_env_edit": "Environment variable containing this bot token. Prefer this over direct local token entry.",
            "discord_bot_local_token_edit": "Optional local test token. Leave blank to keep the existing token. Tokens are stored only in ignored local settings.",
            "discord_bot_guild_id_edit": "Optional server/guild override for this bot. Leave blank to inherit the global Discord setting.",
            "discord_bot_voice_channel_id_edit": "Optional voice channel override for this bot. Leave blank to inherit the global Discord setting.",
            "discord_bot_runtime_port_spin": "Localhost runtime port for this bot. Each running bot instance needs a unique port.",
            "discord_bot_context_entries_spin": "Number of isolated Discord history entries sent to the chat provider for this bot.",
            "discord_bot_call_names_edit": "Comma-separated names or call words that the shared room router treats as addressing this bot.",
            "discord_bot_voice_clone_wav_edit": "Optional WAV filename from the root voices folder for this bot. Missing files fall back to the selected NC Persona voice.",
            "discord_bot_use_global_chat_model_checkbox": "Use the globally selected NC chat provider/model for this bot. Uncheck to choose a per-bot provider and model.",
            "discord_bot_chat_provider_combo": "Optional per-bot chat provider used for this bot's actual replies. The shared room router still uses the global chat model.",
            "discord_bot_chat_model_combo": "Optional per-bot LLM model name. You can type a model manually or refresh the provider model list.",
            "discord_bot_chat_model_refresh_button": "Refresh this bot's model dropdown for the selected provider without changing the global NC model selection.",
            "discord_bot_replace_nc_prompt_checkbox": "Use this bot persona prompt instead of appending it to the selected NC persona prompt.",
            "discord_bot_persona_prompt_edit": "Per-bot system/persona prompt. Keep it speech-friendly and avoid hidden bridge details.",
            "discord_bot_add_button": "Add a new enabled bot instance to the structured editor and advanced JSON.",
            "discord_bot_duplicate_button": "Duplicate the selected bot's settings into a new enabled bot with a fresh ID, token environment variable, and runtime port. With no selection, this adds a new bot.",
            "discord_bot_remove_button": "Remove the selected bot instance from the local settings model and erase that bot's persisted context.",
            "discord_bot_remove_all_context_button": "Erase persisted Discord context for all configured bot instances. This keeps the bot settings themselves.",
            "discord_bot_load_json_button": "Reload the advanced bots JSON back into the structured editor. Normal bot field edits sync automatically.",
            "discord_test_tone_restart_button": "Saves settings with test tone enabled and restarts the bridge. Use this to verify Discord playback without sending a chat turn.",
            "discord_validate_settings_button": "Checks saved effective bot settings before launch: unique bot IDs, token source, unique ports, localhost runtime host, Node.js, and installed Node bridge dependencies.",
            "discord_install_node_deps_button": "Run npm install in the bundled node_bridge folder. Stop running bridge instances first. This is surgical to the Discord addon and does not reinstall NC Python packages.",
            "discord_copy_diagnostics_button": "Copies redacted status, validation output, and recent logs to the clipboard for support/debugging.",
            "discord_open_logs_button": "Open the addon runtime log folder. Logs are redacted in the UI but may still contain local paths.",
            "discord_validation_summary_label": "Live summary of validation results for saved settings. Use Save Settings before relying on this after edits.",
            "discord_live_bot_combo": "Select which configured Discord bot instance the live commands should target.",
            "discord_live_bot_state_label": "Compact live status for the selected bot: process, endpoint, Discord connection, speech/listen state, queue, latest transcript, and latest route decision.",
            "discord_live_start_button": "Start only the selected bot instance using saved settings. Token, port, guild, and channel changes require this kind of restart.",
            "discord_live_stop_button": "Stop only the selected bot instance and its local endpoint.",
            "discord_live_restart_button": "Restart only the selected bot instance after saving current settings.",
            "discord_live_disconnect_button": "Ask the running Node bridge to leave/disconnect from the current Discord voice connection without stopping the local endpoint.",
            "discord_live_reconnect_button": "Ask the running Node bridge to reconnect/rejoin the configured Discord voice channel.",
            "discord_live_stop_speech_button": "Immediately stop current Discord reply playback for the selected bot and abort the active reply request where possible.",
            "discord_live_clear_queue_button": "Clear queued reply audio chunks for the selected bot without stopping the process.",
            "discord_live_reset_context_button": "Clear the selected bot's isolated Discord conversation context and shared room context file.",
            "discord_live_apply_selected_button": "Save and push full live-safe settings to the selected running bot. Use this for persona, voice, call names, and per-bot context changes.",
            "discord_live_apply_global_button": "Save and push shared live settings to all running bots: routing, playback/interruption, capture, and cleanup.",
            "discord_live_apply_all_button": "Save and push every live-safe setting to all running bots, including per-bot persona, voice, context, and shared settings.",
            "discord_live_message_edit": "Text to synthesize through the selected bot without sending it through STT or the chat model.",
            "discord_live_send_message_button": "Generate TTS for the message and play it through the selected bot's Discord voice connection.",
            "discord_live_restart_hint_label": "Explains which settings are live-safe and which settings need restart or reconnect.",
            "discord_moderator_target_combo": "Selected bot target for participant-aware moderator commands that can only be performed by bots.",
            "discord_moderator_state_label": "Shared moderator state seen by the running bots in this Discord voice channel.",
            "discord_moderator_badges_label": "Compact active-state badges: current speaker, pending next target, speaker locks, mutes, and queued audio.",
            "discord_moderator_last_route_label": "Most recent route decision reported by a running bot, including target and reason when available.",
            "discord_moderator_selected_action_label": "Plain-language explanation of what the selected bot or human row can do right now.",
            "discord_moderator_warning_label": "Plain-language warning from the latest moderator command failure, with the next corrective action where possible.",
            "discord_moderator_instances_table": "Moderator-facing view of active bot state, current speaking/listening status, queue depth, and latest routing decision.",
            "discord_moderator_participants_table": "Unified room participants. Select a bot or human, then use the participant-aware action buttons.",
            "discord_moderator_route_next_button": "Choose the next speaker. Bots receive the next eligible route; humans become the next accepted speaker and pause bot routing until they speak.",
            "discord_moderator_give_floor_button": "Persistent speaker lock for the selected participant until moderator speaker controls are cleared or changed.",
            "discord_moderator_mute_button": "Mute the selected participant. Bot mutes remove it from routing; human mutes ignore their speech.",
            "discord_moderator_unmute_button": "Remove the selected participant from the moderator mute list.",
            "discord_moderator_clear_pending_button": "Clear only the queued next-speaker decision. Existing speaker locks and mutes remain active.",
            "discord_moderator_clear_floor_button": "Clear persistent speaker locks. Pending route and normal mutes remain active.",
            "discord_moderator_clear_button": "Clear all moderator routing, speaker locks, only-speaker, and mute state for this Discord voice channel.",
            "discord_moderator_stop_all_button": "Stop current speech and abort active reply requests on all running bots.",
            "discord_moderator_clear_all_queues_button": "Clear queued reply audio on all running bots.",
            "discord_moderator_set_enforcer_button": "Appoint the selected running bot as the Discord hard moderator. Only this bot may apply server mute enforcement.",
            "discord_moderator_clear_enforcer_button": "Clear the appointed Discord hard moderator and release mutes applied by that moderator bot.",
            "discord_moderator_enforce_mute_checkbox": "Use the appointed moderator bot's Discord Mute Members permission to server-mute everyone except the Current speaker. Requires an active appointed moderator bot.",
            "discord_moderator_allow_interrupt_current_checkbox": "When off, normal speech detection cannot interrupt the moderator Current speaker. Turn on only when the moderator wants participants to be able to cut in.",
            "discord_moderator_announcement_edit": "Text for the selected bot to vocalize as a moderator announcement.",
            "discord_moderator_announce_button": "Speak the announcement through the selected target bot.",
            "discord_moderator_call_on_button": "Ask the selected bot to generate and speak now. The announcement text is used as an optional moderator instruction.",
            "discord_moderator_note_label": "Explains how participant-aware moderator routing waits for completed vocalization before bot-to-bot handoff.",
            "discord_instances_table": "Per-bot runtime status, including configured targets, actual Discord bot/channel identity when connected, token environment variable, localhost port, process ID, and endpoint state.",
            "discord_logs_preview": "Recent bridge logs with token-like values redacted. Use this for diagnostics before opening raw logs.",
        }
        for name, tip in tips.items():
            control = self.controls.get(name)
            if control is not None:
                control.setToolTip(tip)
            label = self.controls.get(f"{name}_label")
            if label is not None:
                label.setToolTip(tip)

    def _set_buttons_enabled(self, enabled: bool):
        for name in (
            "discord_bridge_save_button",
            "discord_bridge_start_button",
            "discord_bridge_stop_button",
            "discord_bridge_restart_button",
            "discord_bridge_refresh_button",
            "discord_test_tone_restart_button",
            "discord_validate_settings_button",
            "discord_install_node_deps_button",
            "discord_copy_diagnostics_button",
            "discord_open_logs_button",
            "discord_live_start_button",
            "discord_live_stop_button",
            "discord_live_restart_button",
            "discord_live_disconnect_button",
            "discord_live_reconnect_button",
            "discord_live_stop_speech_button",
            "discord_live_clear_queue_button",
            "discord_live_reset_context_button",
            "discord_live_apply_selected_button",
            "discord_live_apply_global_button",
            "discord_live_apply_all_button",
            "discord_live_message_edit",
            "discord_live_send_message_button",
            "discord_moderator_route_next_button",
            "discord_moderator_give_floor_button",
            "discord_moderator_mute_button",
            "discord_moderator_unmute_button",
            "discord_moderator_clear_pending_button",
            "discord_moderator_clear_floor_button",
            "discord_moderator_clear_button",
            "discord_moderator_stop_all_button",
            "discord_moderator_clear_all_queues_button",
            "discord_moderator_set_enforcer_button",
            "discord_moderator_clear_enforcer_button",
            "discord_moderator_enforce_mute_checkbox",
            "discord_moderator_allow_interrupt_current_checkbox",
            "discord_moderator_announcement_edit",
            "discord_moderator_announce_button",
            "discord_moderator_call_on_button",
            "discord_bot_chat_model_refresh_button",
        ):
            control = self.controls.get(name)
            if control is not None:
                control.setEnabled(bool(enabled))
        self._refresh_bot_chat_runtime_controls()

    def _button(self, name: str, handler):
        button = self._control(name, QtWidgets.QAbstractButton)
        if button is not None:
            button.clicked.connect(handler)

    def _combo_items(self, name: str, items: list[tuple[str, str]]):
        combo = self._control(name, QtWidgets.QComboBox)
        if combo is None:
            return
        combo.clear()
        for label, value in items:
            combo.addItem(label, value)

    def _control(self, name: str, kind):
        control = self.controls.get(name)
        return control if isinstance(control, kind) else None

    def _set_status(self, text: str):
        label = self._control("discord_bridge_status_label", QtWidgets.QLabel)
        if label is not None:
            label.setText(str(text or ""))

    def _show_warning(self, title: str, message: str):
        parent = self.widget if isinstance(self.widget, QtWidgets.QWidget) else None
        QtWidgets.QMessageBox.warning(parent, str(title or "Discord Voice Bridge"), str(message or "Unknown error."))

    def _set_checked(self, name: str, value: Any):
        control = self._control(name, QtWidgets.QCheckBox)
        if control is not None:
            control.setChecked(bool(value))

    def _checked(self, name: str) -> bool:
        control = self._control(name, QtWidgets.QCheckBox)
        return bool(control.isChecked()) if control is not None else False

    def _set_text(self, name: str, value: Any):
        control = self._control(name, QtWidgets.QLineEdit)
        if control is not None:
            control.setText(str(value or ""))
            return
        label = self._control(name, QtWidgets.QLabel)
        if label is not None:
            label.setText(str(value or ""))

    def _text(self, name: str, default: str = "") -> str:
        control = self._control(name, QtWidgets.QLineEdit)
        return str(control.text() if control is not None else default).strip()

    def _set_plain_text(self, name: str, value: Any):
        control = self._control(name, QtWidgets.QPlainTextEdit)
        if control is not None:
            control.setPlainText(str(value or ""))

    def _plain_text(self, name: str, default: str = "") -> str:
        control = self._control(name, QtWidgets.QPlainTextEdit)
        return str(control.toPlainText() if control is not None else default)

    def _set_combo(self, name: str, value: Any):
        combo = self._control(name, QtWidgets.QComboBox)
        if combo is None:
            return
        target = str(value)
        index = combo.findData(target)
        if index < 0:
            index = combo.findText(target)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_combo_text(self, name: str, value: Any):
        combo = self._control(name, QtWidgets.QComboBox)
        if combo is None:
            return
        target = str(value or "")
        index = combo.findText(target)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif combo.isEditable():
            combo.setEditText(target)

    def _combo_value(self, name: str, default: str = "") -> str:
        combo = self._control(name, QtWidgets.QComboBox)
        if combo is None:
            return default
        value = combo.currentData()
        return str(value if value is not None else combo.currentText())

    def _combo_text(self, name: str, default: str = "") -> str:
        combo = self._control(name, QtWidgets.QComboBox)
        return str(combo.currentText() if combo is not None else default).strip()

    def _set_spin(self, name: str, value: Any):
        control = self.controls.get(name)
        if hasattr(control, "setValue"):
            try:
                control.setValue(float(value) if isinstance(control, QtWidgets.QDoubleSpinBox) else int(value))
            except Exception:
                pass

    def _spin_value(self, name: str, default: float) -> float:
        control = self.controls.get(name)
        if hasattr(control, "value"):
            return control.value()
        return default


def _get(payload: dict[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for key in str(dotted or "").split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _set_or_drop(payload: dict[str, Any], key: str, value: Any) -> None:
    text = str(value or "").strip()
    if text:
        payload[key] = text
    else:
        payload.pop(key, None)


def _safe_bot_id(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip()).strip("._-")
    return text.lower()


def _drop_redacted_secret_values(value: Any) -> None:
    if isinstance(value, dict):
        for key in list(value.keys()):
            if str(key).lower() in {"token", "discord_token", "api_key", "secret"} and str(value.get(key)) == "<redacted>":
                value.pop(key, None)
            else:
                _drop_redacted_secret_values(value[key])
    elif isinstance(value, list):
        for child in value:
            _drop_redacted_secret_values(child)


def _route_decision_text(decision: dict[str, Any]) -> str:
    if not isinstance(decision, dict) or not decision:
        return ""
    target = str(decision.get("target_bot_id") or decision.get("target") or "").strip()
    answer = decision.get("answer")
    reason = str(decision.get("reason") or "").strip()
    prefix = "answer=yes" if bool(answer) else "answer=no"
    if target:
        prefix = f"{prefix} target={target}"
    if reason:
        return f"{prefix} reason={reason}"
    return prefix


def _route_flow_line(entry: dict[str, Any]) -> str:
    if not isinstance(entry, dict):
        return ""
    try:
        at_ms = int(entry.get("at_ms") or 0)
    except (TypeError, ValueError):
        at_ms = 0
    if at_ms > 0:
        stamp = datetime.fromtimestamp(at_ms / 1000).strftime("%H:%M:%S")
    else:
        stamp = str(entry.get("captured_at") or "").replace("T", " ")[:19] or "--:--:--"
    speaker = str(entry.get("speaker_name") or entry.get("speaker_bot_id") or "unknown").strip()
    target = str(entry.get("target_name") or entry.get("target_bot_id") or "").strip()
    answer = bool(entry.get("answer"))
    reason = str(entry.get("reason") or "").strip()
    source = str(entry.get("source") or "").strip()
    arrow = f"{speaker} -> {target}" if answer and target else f"{speaker} -> no route"
    suffix = f" | {reason}" if reason else ""
    source_text = f" [{source}]" if source else ""
    return f"{stamp}  {arrow}{source_text}{suffix}"


def _progress_text(value: Any, total: Any) -> str:
    try:
        current = max(0, int(value or 0))
        maximum = max(0, int(total or 0))
    except Exception:
        return "0/0"
    return f"{min(current, maximum)}/{maximum}" if maximum > 0 else "0/0"


def _moderator_badges_html(badges: list[tuple[str, str]]) -> str:
    chips = []
    for label, value in badges:
        chips.append(
            '<span style="background-color:#27496d; color:#ffffff; border-radius:4px; '
            'padding:2px 6px; margin-right:4px;">'
            f"{escape(str(label or '').strip())}: {escape(str(value or '').strip())}"
            "</span>"
        )
    return " ".join(chips)


def _moderator_warning_text(error: str) -> str:
    text = str(error or "").strip()
    if not text:
        return "No moderator warning."
    lowered = text.lower()
    if "not connected" in lowered or "not live" in lowered:
        return f"Warning: {text}. Choose a connected participant, reconnect the target, or clear the pending speaker-control state."
    if "default" in lowered:
        return f"Warning: {text}. Select a real bot or human participant before sending the command."
    return f"Warning: {text}"


def _redact_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"([A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.)[A-Za-z0-9_-]{20,}", r"\1<redacted>", value)
    value = re.sub(r'("token"\s*:\s*")[^"]+', r'\1<redacted>', value, flags=re.IGNORECASE)
    return value
