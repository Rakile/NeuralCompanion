from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQuick


def _normalize_theme_preset(value: object) -> str:
    selected = str(value or "midnight").strip().lower().replace("-", "_")
    selected = "_".join(selected.split())
    return selected if selected in {"midnight", "dark_gray", "forest"} else "midnight"


class OrbPopupBridge(QtCore.QObject):
    changed = QtCore.Signal()
    closeRequested = QtCore.Signal()
    windowDragRequested = QtCore.Signal()
    mainWindowToggleRequested = QtCore.Signal()
    runtimeInitializeRequested = QtCore.Signal()
    runtimeTerminateRequested = QtCore.Signal()
    runtimeStateRefreshRequested = QtCore.Signal()
    workspaceActionRequested = QtCore.Signal(str, bool)
    menuResizeBeginRequested = QtCore.Signal()
    menuResizeUpdateRequested = QtCore.Signal()
    menuResizeEndRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "menu"
        self._title = ""
        self._placeholder = ""
        self._status = ""
        self._items: list[dict[str, Any]] = []
        self._compact_mode = False
        self._pinned = False
        self._reduced_effects = False
        self._theme_preset = "midnight"
        self._menu_width = 520
        self._runtime_running = False
        self._runtime_starting = False
        self._runtime_fault = False
        self._ai_state = "idle"
        self._idle_color = "#38bdf8"
        self._thinking_color = "#a78bfa"
        self._speaking_color = "#f472b6"
        self._activate: Callable[[str], None] | None = None
        self._submit: Callable[[str], tuple[bool, str]] | None = None
        self._set_compact_mode: Callable[[bool], None] | None = None
        self._set_pinned: Callable[[bool], None] | None = None
        self._set_menu_width: Callable[[int], None] | None = None

    @QtCore.Property(str, notify=changed)
    def mode(self) -> str:
        return self._mode

    @QtCore.Property(str, notify=changed)
    def title(self) -> str:
        return self._title

    @QtCore.Property(str, notify=changed)
    def placeholder(self) -> str:
        return self._placeholder

    @QtCore.Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @QtCore.Property("QVariantList", notify=changed)
    def items(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._items]

    @QtCore.Property(bool, notify=changed)
    def compactMode(self) -> bool:
        return self._compact_mode

    def update_menu_item(self, item_id: str, **values: Any) -> None:
        """Refresh a toggle in-place, including when the menu is pinned."""
        for item in self._items:
            if item.get('id') == item_id:
                item.update(values)
                self.changed.emit()
                return

    @QtCore.Property(bool, notify=changed)
    def pinned(self) -> bool:
        return self._pinned

    @QtCore.Property(bool, notify=changed)
    def reducedEffects(self) -> bool:
        return self._reduced_effects

    @QtCore.Property(str, notify=changed)
    def themePreset(self) -> str:
        return self._theme_preset

    @QtCore.Property(int, notify=changed)
    def menuWidth(self) -> int:
        return self._menu_width

    @QtCore.Property(bool, notify=changed)
    def runtimeRunning(self) -> bool:
        return self._runtime_running

    @QtCore.Property(bool, notify=changed)
    def runtimeStarting(self) -> bool:
        return self._runtime_starting

    @QtCore.Property(bool, notify=changed)
    def runtimeFault(self) -> bool:
        return self._runtime_fault

    @QtCore.Property(str, notify=changed)
    def aiState(self) -> str:
        return self._ai_state

    @QtCore.Property(str, notify=changed)
    def idleColor(self) -> str:
        return self._idle_color

    @QtCore.Property(str, notify=changed)
    def thinkingColor(self) -> str:
        return self._thinking_color

    @QtCore.Property(str, notify=changed)
    def speakingColor(self) -> str:
        return self._speaking_color

    def configure_menu(
        self,
        title: str,
        items: Sequence[dict[str, Any]],
        activate: Callable[[str], None],
        *,
        compact_mode: bool = False,
        set_compact_mode: Callable[[bool], None] | None = None,
        pinned: bool = False,
        set_pinned: Callable[[bool], None] | None = None,
        reduced_effects: bool = False,
        theme_preset: str = "midnight",
        menu_width: int = 520,
        set_menu_width: Callable[[int], None] | None = None,
    ) -> None:
        self._mode = "menu"
        self._title = str(title or "Companion Orb")
        self._placeholder = ""
        self._status = ""
        self._items = [dict(item) for item in items]
        self._pinned = bool(pinned)
        self._compact_mode = bool(compact_mode) or self._pinned
        self._reduced_effects = bool(reduced_effects)
        self._theme_preset = _normalize_theme_preset(theme_preset)
        self._menu_width = max(440, min(760, int(menu_width)))
        self._activate = activate
        self._submit = None
        self._set_compact_mode = set_compact_mode
        self._set_pinned = set_pinned
        self._set_menu_width = set_menu_width
        self.changed.emit()

    def configure_input(
        self,
        title: str,
        placeholder: str,
        submit: Callable[[str], tuple[bool, str]],
        *,
        theme_preset: str = "midnight",
    ) -> None:
        self._mode = "input"
        self._title = str(title or "Companion Orb Chat")
        self._placeholder = str(placeholder or "Type a message to NC...")
        self._status = ""
        self._items = []
        self._theme_preset = _normalize_theme_preset(theme_preset)
        self._activate = None
        self._submit = submit
        self._set_compact_mode = None
        self._set_menu_width = None
        self.changed.emit()

    @QtCore.Slot(int, bool)
    def setMenuWidth(self, width: int, persist: bool = False) -> None:
        value = max(440, min(760, int(width)))
        changed = value != self._menu_width
        self._menu_width = value
        if persist and self._set_menu_width is not None:
            self._set_menu_width(value)
        if changed:
            self.changed.emit()

    @QtCore.Slot()
    def beginMenuResize(self) -> None:
        self.menuResizeBeginRequested.emit()

    @QtCore.Slot()
    def updateMenuResize(self) -> None:
        self.menuResizeUpdateRequested.emit()

    @QtCore.Slot()
    def endMenuResize(self) -> None:
        self.menuResizeEndRequested.emit()

    @QtCore.Slot()
    def toggleCompactMode(self) -> None:
        if self._mode != "menu" or self._pinned:
            return
        self._compact_mode = not self._compact_mode
        callback = self._set_compact_mode
        if callback is not None:
            callback(self._compact_mode)
        self.changed.emit()

    @QtCore.Slot()
    def togglePinned(self) -> None:
        if self._mode != "menu":
            return
        self._pinned = not self._pinned
        if self._pinned and not self._compact_mode:
            self._compact_mode = True
            compact_callback = self._set_compact_mode
            if compact_callback is not None:
                compact_callback(True)
        callback = self._set_pinned
        if callback is not None:
            callback(self._pinned)
        self.changed.emit()

    @QtCore.Slot()
    def dismissAfterAction(self) -> None:
        if not self._pinned:
            self.closeRequested.emit()

    @QtCore.Slot(str)
    def activate(self, item_id: str) -> None:
        callback = self._activate
        if callback is not None:
            callback(str(item_id or ""))

    @QtCore.Slot(str)
    def submit(self, text: str) -> None:
        callback = self._submit
        if callback is None:
            return
        accepted, status = callback(str(text or ""))
        self._status = str(status or "")
        self.changed.emit()
        if accepted:
            self.closeRequested.emit()

    @QtCore.Slot()
    def close(self) -> None:
        if self._mode == "menu" and self._pinned:
            self._pinned = False
            callback = self._set_pinned
            if callback is not None:
                callback(False)
        self.closeRequested.emit()

    @QtCore.Slot()
    def startWindowDrag(self) -> None:
        self.windowDragRequested.emit()

    @QtCore.Slot()
    def toggleMainWindow(self) -> None:
        self.mainWindowToggleRequested.emit()

    @QtCore.Slot()
    def initializeRuntime(self) -> None:
        if self._runtime_running or self._runtime_starting:
            return
        self._runtime_starting = True
        self.changed.emit()
        self.runtimeInitializeRequested.emit()

    @QtCore.Slot()
    def toggleRuntime(self) -> None:
        if self._runtime_starting:
            return
        if self._runtime_running or self._runtime_fault:
            self.runtimeTerminateRequested.emit()
            return
        self._runtime_starting = True
        self.changed.emit()
        self.runtimeInitializeRequested.emit()

    @QtCore.Slot()
    def refreshRuntimeState(self) -> None:
        self.runtimeStateRefreshRequested.emit()

    def updateRuntimeState(
        self,
        running: bool,
        starting: bool,
        fault: bool = False,
    ) -> None:
        running_value = bool(running)
        starting_value = bool(starting) and not running_value
        fault_value = bool(fault) and not running_value
        if (
            self._runtime_running == running_value
            and self._runtime_starting == starting_value
            and self._runtime_fault == fault_value
        ):
            return
        self._runtime_running = running_value
        self._runtime_starting = starting_value
        self._runtime_fault = fault_value
        self.changed.emit()

    def updateVisualState(
        self,
        ai_state: str,
        idle_color: str,
        thinking_color: str,
        speaking_color: str,
    ) -> None:
        state = str(ai_state or "idle").strip().lower()
        if state not in {"idle", "listening", "thinking", "speaking"}:
            state = "idle"
        values = (
            state,
            str(idle_color or "#38bdf8"),
            str(thinking_color or "#a78bfa"),
            str(speaking_color or "#f472b6"),
        )
        if values == (
            self._ai_state,
            self._idle_color,
            self._thinking_color,
            self._speaking_color,
        ):
            return
        (
            self._ai_state,
            self._idle_color,
            self._thinking_color,
            self._speaking_color,
        ) = values
        self.changed.emit()

    def updateThemePreset(self, theme_preset: str) -> None:
        value = _normalize_theme_preset(theme_preset)
        if value == self._theme_preset:
            return
        self._theme_preset = value
        self.changed.emit()

    @QtCore.Slot(str, bool)
    def activateWorkspace(
        self,
        workspace_key: str,
        close_if_floating: bool,
    ) -> None:
        key = str(workspace_key or "").strip().lower()
        if key not in {"conversation", "musetalk"}:
            return
        self.workspaceActionRequested.emit(key, bool(close_if_floating))


class OrbPopupWindow(QtCore.QObject):
    closed = QtCore.Signal()

    def __init__(
        self,
        parent=None,
        *,
        toggle_main_window: Callable[[], object] | None = None,
        initialize_runtime: Callable[[], object] | None = None,
        terminate_runtime: Callable[[], object] | None = None,
        runtime_state: Callable[[], dict[str, Any]] | None = None,
        activate_workspace: Callable[[str, bool], object] | None = None,
        save_position: Callable[[list[int]], object] | None = None,
        save_menu_width: Callable[[int], object] | None = None,
    ):
        super().__init__(parent)
        self._toggle_main_window_callback = toggle_main_window
        self._initialize_runtime_callback = initialize_runtime
        self._terminate_runtime_callback = terminate_runtime
        self._runtime_state_callback = runtime_state
        self._activate_workspace_callback = activate_workspace
        self._save_position_callback = save_position
        self._save_menu_width_callback = save_menu_width
        self._resize_right_edge: int | None = None
        self.bridge = OrbPopupBridge(self)
        self.view = QtQuick.QQuickView()
        self.view.setTitle("Companion Orb")
        # Keep the native window transparent so the rounded QML card owns the
        # complete visible silhouette instead of sitting on a square backing.
        self.view.setColor(QtGui.QColor(0, 0, 0, 0))
        self.view.setFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
        )
        # The popup content owns its size. Menu items arrive after QML loads,
        # so forcing the root into the initial title-only view clips the list.
        self.view.setResizeMode(QtQuick.QQuickView.SizeViewToRootObject)
        self.view.rootContext().setContextProperty("orbPopupBridge", self.bridge)
        source = Path(__file__).resolve().parent / "qml" / "CompanionOrbPopup.qml"
        self.view.setSource(QtCore.QUrl.fromLocalFile(str(source)))
        if self.view.status() == QtQuick.QQuickView.Error:
            errors = "; ".join(error.toString() for error in self.view.errors())
            raise RuntimeError(errors or "Companion Orb popup QML failed to load")
        self.bridge.closeRequested.connect(self.close)
        self.bridge.windowDragRequested.connect(self._start_window_drag)
        self.bridge.mainWindowToggleRequested.connect(
            self._toggle_main_window
        )
        self.bridge.runtimeInitializeRequested.connect(
            self._initialize_runtime
        )
        self.bridge.runtimeTerminateRequested.connect(
            self._terminate_runtime
        )
        self.bridge.runtimeStateRefreshRequested.connect(
            self._refresh_runtime_state
        )
        self.bridge.workspaceActionRequested.connect(
            self._activate_workspace
        )
        self.bridge.menuResizeBeginRequested.connect(self._begin_menu_resize)
        self.bridge.menuResizeUpdateRequested.connect(self._update_menu_resize)
        self.bridge.menuResizeEndRequested.connect(self._end_menu_resize)
        self._position_save_timer = QtCore.QTimer(self)
        self._position_save_timer.setSingleShot(True)
        self._position_save_timer.setInterval(160)
        self._position_save_timer.timeout.connect(self._commit_position)
        self.view.xChanged.connect(self._schedule_position_save)
        self.view.yChanged.connect(self._schedule_position_save)

    @QtCore.Slot()
    def _start_window_drag(self) -> None:
        start_system_move = getattr(self.view, "startSystemMove", None)
        if callable(start_system_move):
            start_system_move()

    @staticmethod
    def _left_resize_geometry(right_edge: int, cursor_x: int) -> tuple[int, int]:
        width = max(440, min(760, int(right_edge) - int(cursor_x)))
        return int(right_edge) - width, width

    @QtCore.Slot()
    def _begin_menu_resize(self) -> None:
        if self.bridge.mode != "menu" or self.bridge.compactMode:
            return
        self._resize_right_edge = int(self.view.x() + self.view.width())

    @QtCore.Slot()
    def _update_menu_resize(self) -> None:
        if self._resize_right_edge is None:
            return
        x, width = self._left_resize_geometry(
            self._resize_right_edge,
            QtGui.QCursor.pos().x(),
        )
        self.bridge.setMenuWidth(width, False)
        self.view.setX(x)

    @QtCore.Slot()
    def _end_menu_resize(self) -> None:
        if self._resize_right_edge is None:
            return
        self._resize_right_edge = None
        self.bridge.setMenuWidth(self.bridge.menuWidth, True)

    @QtCore.Slot()
    def _toggle_main_window(self) -> None:
        callback = self._toggle_main_window_callback
        if callable(callback):
            callback()

    @QtCore.Slot()
    def _initialize_runtime(self) -> None:
        callback = self._initialize_runtime_callback
        if callable(callback):
            callback()
        self._refresh_runtime_state()

    @QtCore.Slot()
    def _terminate_runtime(self) -> None:
        callback = self._terminate_runtime_callback
        if callable(callback):
            callback()
        self._refresh_runtime_state()

    @QtCore.Slot()
    def _refresh_runtime_state(self) -> None:
        callback = self._runtime_state_callback
        if not callable(callback):
            return
        try:
            state = dict(callback() or {})
        except (RuntimeError, TypeError, ValueError):
            return
        self.bridge.updateRuntimeState(
            bool(state.get("running", False)),
            bool(state.get("starting", False)),
            bool(state.get("fault", False)),
        )
        self.bridge.updateVisualState(
            str(state.get("ai_state") or "idle"),
            str(state.get("idle_color") or "#38bdf8"),
            str(state.get("thinking_color") or "#a78bfa"),
            str(state.get("speaking_color") or "#f472b6"),
        )
        if "theme_preset" in state:
            self.bridge.updateThemePreset(
                str(state.get("theme_preset") or "midnight")
            )

    @QtCore.Slot(str, bool)
    def _activate_workspace(
        self,
        workspace_key: str,
        close_if_floating: bool,
    ) -> None:
        callback = self._activate_workspace_callback
        if callable(callback):
            callback(str(workspace_key or ""), bool(close_if_floating))

    @QtCore.Slot()
    def _schedule_position_save(self) -> None:
        if (
            self.view.isVisible()
            and self.bridge.mode == "menu"
            and self.bridge.pinned
        ):
            self._position_save_timer.start()

    @staticmethod
    def _clamped_position(
        point: QtCore.QPoint,
        size: QtCore.QSize,
    ) -> QtCore.QPoint:
        center = QtCore.QPoint(
            point.x() + max(1, size.width()) // 2,
            point.y() + max(1, size.height()) // 2,
        )
        screen = (
            QtGui.QGuiApplication.screenAt(center)
            or QtGui.QGuiApplication.primaryScreen()
        )
        available = (
            screen.availableGeometry()
            if screen is not None
            else QtCore.QRect(0, 0, 1280, 720)
        )
        margin = 8
        max_x = max(available.left() + margin, available.right() - size.width() - margin + 1)
        max_y = max(available.top() + margin, available.bottom() - size.height() - margin + 1)
        x = max(available.left() + margin, min(point.x(), max_x))
        y = max(available.top() + margin, min(point.y(), max_y))
        snap_distance = 24
        if abs(x - (available.left() + margin)) <= snap_distance:
            x = available.left() + margin
        elif abs(x - max_x) <= snap_distance:
            x = max_x
        if abs(y - (available.top() + margin)) <= snap_distance:
            y = available.top() + margin
        elif abs(y - max_y) <= snap_distance:
            y = max_y
        return QtCore.QPoint(x, y)

    @QtCore.Slot()
    def _commit_position(self) -> None:
        if self.bridge.mode != "menu" or not self.bridge.pinned:
            return
        point = self._clamped_position(self.view.position(), self.view.size())
        if point != self.view.position():
            self.view.setPosition(point)
        callback = self._save_position_callback
        if callable(callback):
            callback([int(point.x()), int(point.y())])

    def show_menu(
        self,
        point: QtCore.QPoint,
        items: Sequence[dict[str, Any]],
        activate: Callable[[str], None],
        *,
        compact_mode: bool = False,
        set_compact_mode: Callable[[bool], None] | None = None,
        pinned: bool = False,
        set_pinned: Callable[[bool], None] | None = None,
        pinned_position: Sequence[int] | None = None,
        reduced_effects: bool = False,
        theme_preset: str = "midnight",
        menu_width: int = 520,
        set_menu_width: Callable[[int], None] | None = None,
    ) -> None:
        self.bridge.configure_menu(
            "Companion Orb",
            items,
            activate,
            compact_mode=compact_mode,
            set_compact_mode=set_compact_mode,
            pinned=pinned,
            set_pinned=set_pinned,
            reduced_effects=reduced_effects,
            theme_preset=theme_preset,
            menu_width=menu_width,
            set_menu_width=set_menu_width or self._save_menu_width_callback,
        )
        self._refresh_runtime_state()
        preferred_position = None
        if pinned_position is not None:
            try:
                values = list(pinned_position)
                if len(values) >= 2:
                    preferred_position = QtCore.QPoint(int(values[0]), int(values[1]))
            except (TypeError, ValueError, OverflowError):
                preferred_position = None
        self._show_at(preferred_position or point)

    def show_input(
        self,
        point: QtCore.QPoint,
        *,
        title: str,
        placeholder: str,
        submit: Callable[[str], tuple[bool, str]],
        theme_preset: str = "midnight",
    ) -> None:
        self.bridge.configure_input(
            title,
            placeholder,
            submit,
            theme_preset=theme_preset,
        )
        self._show_at(point)

    def _show_at(self, point: QtCore.QPoint) -> None:
        self.view.show()
        QtCore.QCoreApplication.processEvents(
            QtCore.QEventLoop.ExcludeUserInputEvents
        )
        size = self.view.size()
        screen = (
            QtGui.QGuiApplication.screenAt(point)
            or QtGui.QGuiApplication.primaryScreen()
        )
        available = (
            screen.availableGeometry()
            if screen is not None
            else QtCore.QRect(0, 0, 1280, 720)
        )
        x = max(
            available.left() + 8,
            min(point.x(), available.right() - size.width() - 8),
        )
        y = max(
            available.top() + 8,
            min(point.y(), available.bottom() - size.height() - 8),
        )
        self.view.setPosition(QtCore.QPoint(x, y))
        self.view.requestActivate()

    @QtCore.Slot()
    def close(self) -> None:
        if self.view.isVisible():
            self.view.hide()
        self.closed.emit()
