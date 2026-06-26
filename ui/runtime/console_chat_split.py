"""Shared split-view helper for the System Console and Chat runtime tabs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets


@dataclass
class _TabMeta:
    index: int
    title: str
    icon: QtGui.QIcon
    tooltip: str
    whats_this: str
    enabled: bool
    visible: bool


class ConsoleChatSplitController(QtCore.QObject):
    """Temporarily place the existing console and chat tab pages side by side."""

    def __init__(
        self,
        host: QtCore.QObject,
        *,
        tabs: QtWidgets.QTabWidget,
        system_tab: QtWidgets.QWidget,
        chat_tab: QtWidgets.QWidget,
        console_clear_button: QtWidgets.QPushButton | None,
        chat_clear_button: QtWidgets.QPushButton | None,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._tabs = tabs
        self._system_tab = system_tab
        self._chat_tab = chat_tab
        self._console_button = self._ensure_toggle_button(
            "console_chat_split_toggle_button",
            console_clear_button,
        )
        self._chat_button = self._ensure_toggle_button(
            "chat_console_split_toggle_button",
            chat_clear_button,
        )
        self._split_enabled = False
        self._splitter: QtWidgets.QSplitter | None = None
        self._system_placeholder: QtWidgets.QWidget | None = None
        self._chat_placeholder: QtWidgets.QWidget | None = None
        self._system_meta: _TabMeta | None = None
        self._chat_meta: _TabMeta | None = None
        self._last_source = "chat"
        self._updating_tabs = False
        self._connect_toggle(self._console_button, "console")
        self._connect_toggle(self._chat_button, "chat")
        self._tabs.currentChanged.connect(self._on_current_tab_changed)
        self._sync_buttons()

    def set_split_enabled(self, enabled: bool, *, source: str = "") -> None:
        if source in {"console", "chat"}:
            self._last_source = source
        enabled = bool(enabled)
        if enabled == self._split_enabled:
            self._sync_buttons()
            return
        self._updating_tabs = True
        try:
            changed = self._enable_split() if enabled else self._disable_split()
        finally:
            self._updating_tabs = False
        if not changed:
            self._sync_buttons()
            return
        self._split_enabled = enabled
        self._sync_buttons()

    def split_enabled(self) -> bool:
        return self._split_enabled

    def _connect_toggle(self, button: QtWidgets.QPushButton | None, source: str) -> None:
        if button is None:
            return
        if bool(button.property("_nc_console_chat_split_connected")):
            return
        button.clicked.connect(
            lambda checked=False, split_source=source: self.set_split_enabled(
                bool(checked),
                source=split_source,
            )
        )
        button.setProperty("_nc_console_chat_split_connected", True)

    def _ensure_toggle_button(
        self,
        object_name: str,
        clear_button: QtWidgets.QPushButton | None,
    ) -> QtWidgets.QPushButton | None:
        button = self._find_child(object_name, QtWidgets.QPushButton)
        if button is None:
            if clear_button is None:
                return None
            button = QtWidgets.QPushButton("Split: Off", clear_button.parentWidget())
            button.setObjectName(object_name)
            self._insert_button_after(clear_button, button)
        button.setCheckable(True)
        button.setMinimumWidth(0)
        button.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        button.setToolTip("Show System Console and Chat side by side.")
        try:
            setattr(self._host, object_name, button)
        except Exception:
            pass
        return button

    def _insert_button_after(
        self,
        clear_button: QtWidgets.QPushButton,
        button: QtWidgets.QPushButton,
    ) -> None:
        root = clear_button.window()
        layout = root.layout() if root is not None else None
        target = self._find_layout_item(layout, clear_button) if layout is not None else None
        if target is None:
            parent = clear_button.parentWidget()
            layout = parent.layout() if parent is not None else None
            target = self._find_layout_item(layout, clear_button) if layout is not None else None
        if target is None:
            return
        target_layout, index = target
        target_layout.insertWidget(index + 1, button)

    def _find_layout_item(
        self,
        layout: QtWidgets.QLayout | None,
        widget: QtWidgets.QWidget,
    ) -> tuple[QtWidgets.QLayout, int] | None:
        if layout is None:
            return None
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None:
                continue
            if item.widget() is widget:
                return layout, index
            nested = item.layout()
            if nested is not None:
                found = self._find_layout_item(nested, widget)
                if found is not None:
                    return found
        return None

    def _enable_split(self) -> bool:
        system_index = self._tabs.indexOf(self._system_tab)
        chat_index = self._tabs.indexOf(self._chat_tab)
        if system_index < 0 or chat_index < 0:
            return False
        self._system_meta = self._capture_meta(system_index)
        self._chat_meta = self._capture_meta(chat_index)
        for index in sorted((system_index, chat_index), reverse=True):
            self._tabs.removeTab(index)
        self._system_placeholder = self._ensure_placeholder(
            self._system_placeholder,
            "system_console_split_placeholder",
        )
        self._chat_placeholder = self._ensure_placeholder(
            self._chat_placeholder,
            "chat_runtime_split_placeholder",
        )
        placeholders = [
            (self._system_meta, self._system_placeholder, "console"),
            (self._chat_meta, self._chat_placeholder, "chat"),
        ]
        restored = {}
        for meta, placeholder, key in sorted(placeholders, key=lambda item: item[0].index):
            target_index = max(0, min(meta.index, self._tabs.count()))
            restored[key] = self._tabs.insertTab(target_index, placeholder, meta.icon, meta.title)
            self._restore_meta(restored[key], meta)
        target_key = self._last_source if self._last_source in restored else "chat"
        target_index = restored.get(target_key, restored.get("console", 0))
        self._tabs.setCurrentIndex(target_index)
        self._attach_splitter_to(self._tabs.widget(target_index))
        return True

    def _disable_split(self) -> bool:
        splitter = self._splitter
        if splitter is not None:
            parent = splitter.parentWidget()
            layout = parent.layout() if parent is not None else None
            if layout is not None:
                layout.removeWidget(splitter)
        for widget in (self._system_tab, self._chat_tab):
            try:
                widget.setParent(None)
            except Exception:
                pass
        for placeholder in (self._system_placeholder, self._chat_placeholder):
            if placeholder is None:
                continue
            index = self._tabs.indexOf(placeholder)
            if index >= 0:
                self._tabs.removeTab(index)
            placeholder.setParent(None)
        metas = [
            (self._system_meta or self._fallback_meta("System Console", 0), self._system_tab, "console"),
            (self._chat_meta or self._fallback_meta("Chat", 1), self._chat_tab, "chat"),
        ]
        restored = {}
        for meta, widget, key in sorted(metas, key=lambda item: item[0].index):
            target_index = max(0, min(meta.index, self._tabs.count()))
            restored[key] = self._tabs.insertTab(target_index, widget, meta.icon, meta.title)
            self._restore_meta(restored[key], meta)
        self._tabs.setCurrentIndex(restored.get(self._last_source, restored.get("chat", restored.get("console", 0))))
        if splitter is not None:
            splitter.setParent(None)
        return True

    def _ensure_placeholder(
        self,
        placeholder: QtWidgets.QWidget | None,
        object_name: str,
    ) -> QtWidgets.QWidget:
        if placeholder is None:
            placeholder = QtWidgets.QWidget(self._tabs)
            placeholder.setObjectName(object_name)
            placeholder.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            layout = QtWidgets.QVBoxLayout(placeholder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        return placeholder

    def _ensure_splitter(self) -> QtWidgets.QSplitter:
        if self._splitter is None:
            self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
            self._splitter.setObjectName("console_chat_splitter")
            self._splitter.setChildrenCollapsible(False)
        return self._splitter

    def _attach_splitter_to(self, placeholder: QtWidgets.QWidget | None) -> None:
        if placeholder is not self._system_placeholder and placeholder is not self._chat_placeholder:
            return
        if placeholder is self._system_placeholder:
            self._last_source = "console"
        elif placeholder is self._chat_placeholder:
            self._last_source = "chat"
        splitter = self._ensure_splitter()
        parent = splitter.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        if parent_layout is not None:
            parent_layout.removeWidget(splitter)
        layout = placeholder.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(placeholder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        splitter.setParent(placeholder)
        if layout.indexOf(splitter) < 0:
            layout.addWidget(splitter, 1)
        if splitter.indexOf(self._system_tab) < 0:
            splitter.insertWidget(0, self._system_tab)
        if splitter.indexOf(self._chat_tab) < 0:
            splitter.addWidget(self._chat_tab)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1, 1])
        self._system_tab.show()
        self._chat_tab.show()
        splitter.show()

    def _on_current_tab_changed(self, index: int) -> None:
        if self._updating_tabs or not self._split_enabled:
            return
        self._attach_splitter_to(self._tabs.widget(index))

    def _capture_meta(self, index: int) -> _TabMeta:
        visible = True
        if hasattr(self._tabs, "isTabVisible"):
            try:
                visible = bool(self._tabs.isTabVisible(index))
            except Exception:
                visible = True
        return _TabMeta(
            index=index,
            title=str(self._tabs.tabText(index) or ""),
            icon=self._tabs.tabIcon(index),
            tooltip=str(self._tabs.tabToolTip(index) or ""),
            whats_this=str(self._tabs.tabWhatsThis(index) or ""),
            enabled=bool(self._tabs.isTabEnabled(index)),
            visible=visible,
        )

    def _fallback_meta(self, title: str, index: int) -> _TabMeta:
        return _TabMeta(index, title, QtGui.QIcon(), "", "", True, True)

    def _restore_meta(self, index: int, meta: _TabMeta) -> None:
        self._tabs.setTabToolTip(index, meta.tooltip)
        self._tabs.setTabWhatsThis(index, meta.whats_this)
        self._tabs.setTabEnabled(index, meta.enabled)
        if hasattr(self._tabs, "setTabVisible"):
            try:
                self._tabs.setTabVisible(index, meta.visible)
            except Exception:
                pass

    def _sync_buttons(self) -> None:
        text = "Split: On" if self._split_enabled else "Split: Off"
        for button in (self._console_button, self._chat_button):
            if button is None:
                continue
            was_blocked = button.blockSignals(True)
            button.setChecked(self._split_enabled)
            button.setText(text)
            button.setToolTip(
                "Restore separate tabs."
                if self._split_enabled
                else "Show System Console and Chat side by side."
            )
            button.blockSignals(was_blocked)

    def _find_child(self, object_name: str, widget_type: type[QtWidgets.QWidget]) -> Any:
        direct = getattr(self._host, object_name, None)
        if isinstance(direct, widget_type):
            return direct
        if hasattr(self._host, "findChild"):
            return self._host.findChild(widget_type, object_name)
        return None


def install_console_chat_split(host: QtCore.QObject) -> ConsoleChatSplitController | None:
    existing = getattr(host, "_nc_console_chat_split_controller", None)
    if isinstance(existing, ConsoleChatSplitController):
        return existing
    tabs = _find_widget(host, "right_tabs", QtWidgets.QTabWidget)
    system_tab = _find_widget(host, "system_console_tab", QtWidgets.QWidget)
    chat_tab = _find_widget(host, "chat_runtime_tab", QtWidgets.QWidget)
    console_clear_button = _find_widget(host, "console_clear_button", QtWidgets.QPushButton)
    chat_clear_button = _find_widget(host, "chat_clear_button", QtWidgets.QPushButton)
    if tabs is None or system_tab is None or chat_tab is None:
        return None
    controller = ConsoleChatSplitController(
        host,
        tabs=tabs,
        system_tab=system_tab,
        chat_tab=chat_tab,
        console_clear_button=console_clear_button,
        chat_clear_button=chat_clear_button,
    )
    setattr(host, "_nc_console_chat_split_controller", controller)
    return controller


def _find_widget(
    host: QtCore.QObject,
    object_name: str,
    widget_type: type[QtWidgets.QWidget],
) -> Any:
    direct = getattr(host, object_name, None)
    if isinstance(direct, widget_type):
        return direct
    if hasattr(host, "findChild"):
        return host.findChild(widget_type, object_name)
    return None
