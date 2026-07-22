from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

try:
    from PySide6.QtQuickWidgets import QQuickWidget
except Exception:  # pragma: no cover
    QQuickWidget = None


def _bootstrap_imports(app_root: Path) -> None:
    root = str(app_root)
    if root not in sys.path:
        sys.path.insert(0, root)


class _MessageRelay(QtCore.QObject):
    message_received = QtCore.Signal(dict)


def _no_shadow_window_hint():
    return getattr(QtCore.Qt, "NoDropShadowWindowHint", QtCore.Qt.WindowType(0))


def _normalize_bounds(bounds) -> list[int]:
    try:
        values = [int(value) for value in list(bounds or [])[:4]]
    except Exception:
        return []
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        return []
    return values


def _interaction_settings():
    try:
        from addons.companion_orb_overlay.companion_orb import interaction_settings as module
    except Exception:
        import interaction_settings as module
    return module


def _pointer_clearance_module():
    try:
        from addons.companion_orb_overlay.companion_orb import pointer_clearance
    except Exception:
        import pointer_clearance
    return pointer_clearance


def _log(message: str) -> None:
    print(str(message or ""), file=sys.stderr, flush=True)


def _emit_event(payload: dict[str, Any]) -> None:
    try:
        sys.stdout.write(json.dumps(dict(payload or {}), ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    except Exception as exc:
        _log(f"Companion Orb external event emit failed: {exc}")


DROP_ANCHOR_HOVER_SECONDS = 18.0
POLL_DRAG_THRESHOLD_PX = 4.0
POINTER_SNAPSHOT_COOLDOWN_SECONDS = 10.0
PLAYFUL_NUDGE_EVENT_COOLDOWN_SECONDS = 18.0


class ExternalCompanionOrb(QtCore.QObject):
    def __init__(self, app_root: Path):
        super().__init__()
        from addons.companion_orb_overlay.companion_orb.companion_orb_bridge import CompanionOrbBridge

        self.app_root = Path(app_root)
        self.bridge = CompanionOrbBridge()
        self.settings: dict[str, Any] = {}
        self.window: QtWidgets.QWidget | None = None
        self.quick: QQuickWidget | None = None
        self.base_position: QtCore.QPoint | None = None
        self.current_point: QtCore.QPointF | None = None
        self.selected_target_bounds: list[int] = []
        self.focus_bounds: list[int] = []
        self.focus_until = 0.0
        self.drop_anchor_point: QtCore.QPoint | None = None
        self.drop_anchor_until = 0.0
        self.interaction_target_point: QtCore.QPointF | None = None
        self.interaction_target_until = 0.0
        self.last_tick_at = 0.0
        self.idle_pause_until = 0.0
        self.idle_next_pause_at = time.monotonic() + 3.0
        self.idle_pause_point: QtCore.QPointF | None = None
        self.move_start: QtCore.QPoint | None = None
        self.move_target: QtCore.QPoint | None = None
        self.move_started_at = 0.0
        self.move_duration = 0.0
        self.move_curve_sign = 1.0
        self.drag_offset: QtCore.QPoint | None = None
        self.drag_start_global_pos: QtCore.QPoint | None = None
        self.drag_moved = False
        self.direct_drag_mouse_grabbed = False
        self.poll_drag_start_pos: QtCore.QPoint | None = None
        self.poll_drag_offset: QtCore.QPoint | None = None
        self.poll_drag_button = ""
        self.poll_drag_active = False
        self.right_button_was_down = False
        self.left_button_was_down = False
        self.last_user_interaction_at = time.monotonic()
        self.last_pointer_snapshot_at = 0.0
        self.last_playful_nudge_at = 0.0
        self.playful_nudge_active = False
        self.cloaked = False
        self.visible_before_cloak = False
        pointer_clearance = _pointer_clearance_module()
        self.pointer_clearance_policy = (
            pointer_clearance.PointerClearancePolicy()
        )
        self.pointer_clearance_state = "clear"
        self.pointer_clearance_opacity = 1.0
        self.pointer_clearance_suspended = False

        self.drift_timer = QtCore.QTimer(self)
        self.drift_timer.setInterval(16)
        self.drift_timer.timeout.connect(self._on_drift_tick)
        self.motion_timer = QtCore.QTimer(self)
        self.motion_timer.setInterval(16)
        self.motion_timer.timeout.connect(self._on_motion_tick)
        self.return_timer = QtCore.QTimer(self)
        self.return_timer.setSingleShot(True)
        self.return_timer.timeout.connect(lambda: self._return_home(animate=True))
        self.poll_drag_timer = QtCore.QTimer(self)
        self.poll_drag_timer.setInterval(16)
        self.poll_drag_timer.timeout.connect(self._poll_pointer_drag)

        self._create_window()

    def handle_message(self, message: dict[str, Any]) -> None:
        msg_type = str((message or {}).get("type") or "").strip().lower()
        if msg_type == "shutdown":
            QtWidgets.QApplication.quit()
            return
        if msg_type == "settings":
            self.apply_settings(dict(message.get("settings") or {}))
            return
        if msg_type == "state":
            self.set_ai_state(message.get("state"))
            return
        if msg_type == "audio_level":
            self.bridge.setAudioLevel(message.get("level", 0.0))
            self._refresh_visibility()
            return
        if msg_type == "mood":
            self.bridge.setPresenceMood(message.get("mood", "neutral"))
            return
        if msg_type == "gaze_timer":
            self.bridge.setGazeTimerState(
                bool(message.get("active")),
                float(message.get("progress", 0.0) or 0.0),
                str(message.get("color") or ""),
            )
            return
        if msg_type == "modes":
            edit_mode = message.get("edit_mode") if "edit_mode" in message else None
            placement_mode = message.get("placement_mode") if "placement_mode" in message else None
            self.bridge.set_modes(
                edit_mode=edit_mode,
                placement_mode=placement_mode,
            )
            click_through = self._effective_click_through(
                message.get("click_through") if "click_through" in message else self.bridge.clickThrough
            )
            self.bridge.set_modes(click_through=click_through)
            self._apply_click_through(click_through)
            self._refresh_visibility()
            return
        if msg_type == "target_info":
            target = dict(message.get("target") or {})
            self.selected_target_bounds = _normalize_bounds(target.get("bounds"))
            self.bridge.set_target_info(target)
            return
        if msg_type == "comment_focus":
            self._set_comment_focus(dict(message.get("payload") or {}))
            return
        if msg_type == "drop_anchor":
            self._set_drop_anchor(message.get("point"), duration_seconds=message.get("duration_seconds", DROP_ANCHOR_HOVER_SECONDS))
            return
        if msg_type == "interaction_target":
            self.pointer_clearance_suspended = bool(
                message.get("pointer_clearance_suspended", False)
            )
            self._set_interaction_target(
                message.get("point"),
                duration_seconds=message.get("duration_seconds", 0.35),
            )
            return
        if msg_type == "interaction_target_clear":
            self._clear_interaction_target()
            return
        if msg_type == "pointer_clearance_guard":
            self.pointer_clearance_suspended = bool(
                message.get("suspended", False)
            )
            if self.pointer_clearance_suspended:
                self._reset_pointer_clearance()
            return
        if msg_type == "cloak":
            self._set_cloak(bool(message.get("enabled")))
            return
        if msg_type == "clear_target":
            self.selected_target_bounds = []
            self.bridge.set_target_info({})
            self._clear_focus()
            self._clear_drop_anchor()
            return
        if msg_type == "reset_position":
            self.settings["companion_orb_custom_position"] = []
            self._clear_drop_anchor()
            self.base_position = self._dock_position()
            self._return_home(animate=True)
            return

    def apply_settings(self, settings: dict[str, Any]) -> None:
        self.settings, _migrated = _interaction_settings().normalize_interaction_settings(dict(settings or {}))
        if not self._pointer_clearance_enabled():
            self._reset_pointer_clearance()
        self.bridge.apply_settings(self.settings)
        self._apply_timer_interval()
        self._apply_window_settings()
        self._refresh_visibility()
        self._sync_drift_timer()

    def set_ai_state(self, state) -> None:
        self.bridge.setAiState(state)
        self._refresh_visibility()
        if str(state or "").strip().lower() == "idle":
            try:
                delay_ms = int(float(self.settings.get("companion_orb_return_home_delay", 2.5) or 2.5) * 1000)
            except Exception:
                delay_ms = 2500
            self.return_timer.start(max(250, min(30000, delay_ms)))

    def _create_window(self) -> None:
        if QQuickWidget is None:
            print("QQuickWidget unavailable for Companion Orb external runtime.", flush=True)
            return
        window = QtWidgets.QWidget(None, self._window_flags())
        window.setObjectName("companion_orb_external_runtime_window")
        window.setWindowTitle("Companion Orb External Runtime")
        window.setFocusPolicy(QtCore.Qt.NoFocus)
        window.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        window.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        layout = QtWidgets.QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        quick = QQuickWidget(window)
        quick.setObjectName("companion_orb_external_runtime_quick")
        quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        quick.setClearColor(QtGui.QColor(0, 0, 0, 0))
        quick.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        quick.rootContext().setContextProperty("companionOrbBridge", self.bridge)
        quick.setSource(QtCore.QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "CompanionOrbOverlay.qml")))
        if quick.status() == QQuickWidget.Error:
            errors = "; ".join(str(error.toString()) for error in quick.errors())
            raise RuntimeError(errors or "Companion Orb external QML load failed")
        layout.addWidget(quick)
        for widget in (window, quick):
            widget.installEventFilter(self)
        self.window = window
        self.quick = quick
        self._apply_window_settings()

    def eventFilter(self, watched, event):
        try:
            if watched in (self.window, self.quick) and self.window is not None:
                return self._handle_window_event(event)
        except Exception as exc:
            print(f"Companion Orb external interaction failed: {exc}", flush=True)
        return super().eventFilter(watched, event)

    def _event_global_pos(self, event) -> QtCore.QPoint:
        try:
            return event.globalPosition().toPoint()
        except Exception:
            try:
                return event.globalPos()
            except Exception:
                return QtCore.QPoint(0, 0)

    def _handle_window_event(self, event) -> bool:
        window = self.window
        if window is None:
            return False
        if event.type() == QtCore.QEvent.MouseButtonPress:
            event_pos = self._event_global_pos(event)
            right_drag_focus = _interaction_settings().right_drag_focus_enabled(self.settings)
            if event.button() == QtCore.Qt.LeftButton and (self.bridge.editMode or not self.bridge.clickThrough):
                self._start_direct_drag(event_pos, button="left")
                return True
            if event.button() == QtCore.Qt.RightButton and (self.bridge.placementMode or right_drag_focus):
                self._start_direct_drag(event_pos, button="right")
                return True
            if event.button() == QtCore.Qt.RightButton:
                self._emit_menu_request(event_pos)
                return True
        if event.type() == QtCore.QEvent.MouseMove and self.drag_offset is not None:
            event_pos = self._event_global_pos(event)
            self._move_direct_drag(event_pos)
            return True
        if event.type() == QtCore.QEvent.MouseButtonRelease:
            if self.drag_offset is not None:
                event_pos = self._event_global_pos(event)
                self._move_direct_drag(event_pos)
                self._finish_direct_drag(global_pos=event_pos)
                return True
        return False

    def _start_direct_drag(self, global_pos: QtCore.QPoint, *, button: str) -> None:
        window = self.window
        if window is None:
            return
        self.drift_timer.stop()
        self.motion_timer.stop()
        self.return_timer.stop()
        self.drag_offset = global_pos - window.frameGeometry().topLeft()
        self.drag_start_global_pos = QtCore.QPoint(global_pos)
        self.drag_moved = False
        self.poll_drag_button = str(button or "left").strip().lower()
        self._apply_orb_cursor(click_through=False, dragging=True)
        self._grab_drag_mouse()

    def _grab_drag_mouse(self) -> None:
        window = self.window
        if window is None or self.direct_drag_mouse_grabbed:
            return
        try:
            window.grabMouse()
            self.direct_drag_mouse_grabbed = True
        except Exception as exc:
            _log(f"Companion Orb external mouse grab failed: {exc}")

    def _release_drag_mouse(self) -> None:
        window = self.window
        if window is None or not self.direct_drag_mouse_grabbed:
            self.direct_drag_mouse_grabbed = False
            return
        try:
            window.releaseMouse()
        except Exception as exc:
            _log(f"Companion Orb external mouse release failed: {exc}")
        self.direct_drag_mouse_grabbed = False

    def _clear_direct_drag(self) -> None:
        self._release_drag_mouse()
        self.drag_offset = None
        self.drag_start_global_pos = None
        self.drag_moved = False
        self.poll_drag_button = ""
        self._apply_orb_cursor(click_through=bool(self.bridge.clickThrough), dragging=False)

    def _move_direct_drag(self, global_pos: QtCore.QPoint) -> None:
        window = self.window
        if window is None or self.drag_offset is None:
            return
        if self.drag_start_global_pos is not None:
            dx = float(global_pos.x() - self.drag_start_global_pos.x())
            dy = float(global_pos.y() - self.drag_start_global_pos.y())
            if math.hypot(dx, dy) >= POLL_DRAG_THRESHOLD_PX:
                self.drag_moved = True
        point = global_pos - self.drag_offset
        self._move_to_drag_position(point)

    def _finish_direct_drag(self, *, global_pos: QtCore.QPoint) -> None:
        window = self.window
        if window is not None:
            self._record_drag_position(window.frameGeometry().topLeft())
        button = str(self.poll_drag_button or "left").strip().lower()
        moved = bool(self.drag_moved)
        if button == "right" and not moved:
            self._emit_menu_request(global_pos)
        else:
            self._emit_position_changed()
            self._emit_drop_event(button=button, reason=f"{button}_drag_drop")
        self._clear_direct_drag()
        self._sync_drift_timer()

    def _window_flags(self):
        flags = QtCore.Qt.Tool | QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowDoesNotAcceptFocus | _no_shadow_window_hint()
        if bool(self.settings.get("companion_orb_always_on_top", True)):
            flags |= QtCore.Qt.WindowStaysOnTopHint
        return flags

    def _apply_window_settings(self) -> None:
        window = self.window
        if window is None:
            return
        size = self._window_size()
        if window.width() != size or window.height() != size:
            window.resize(size, size)
        try:
            window.setWindowFlags(self._window_flags())
        except Exception:
            pass
        click_through = _interaction_settings().effective_click_through(
            self.settings,
            edit_mode=bool(self.bridge.editMode),
            placement_mode=bool(self.bridge.placementMode),
        )
        self.bridge.set_modes(click_through=click_through)
        self._apply_click_through(click_through)
        self._sync_drag_poll_timer()
        if self.base_position is None:
            self.base_position = self._home_position()
            window.move(self.base_position)
            self.current_point = QtCore.QPointF(float(self.base_position.x()), float(self.base_position.y()))

    def _window_size(self) -> int:
        try:
            orb_size = int(self.settings.get("companion_orb_size", 92) or 92)
        except Exception:
            orb_size = 92
        return max(96, int(orb_size * 2.25))

    def _refresh_visibility(self) -> None:
        window = self.window
        if window is None:
            return
        if self.cloaked:
            if window.isVisible():
                window.hide()
            self.drift_timer.stop()
            self.motion_timer.stop()
            self.poll_drag_timer.stop()
            return
        enabled = bool(self.settings.get("companion_orb_enabled", False))
        mode = str(self.settings.get("companion_orb_display_mode", "off") or "off").strip().lower()
        if not enabled or mode == "off":
            window.hide()
            self.drift_timer.stop()
            self.motion_timer.stop()
            self.poll_drag_timer.stop()
            self._clear_poll_drag()
            return
        active = self.bridge.aiState in {"listening", "thinking", "speaking"} or self.bridge.audioLevel > 0.025
        visible = mode in {"docked", "always"} or (mode == "interaction" and active) or self.bridge.editMode or self.bridge.placementMode
        if visible and not window.isVisible():
            window.show()
        elif not visible and window.isVisible():
            window.hide()
        self._sync_drift_timer()
        self._sync_drag_poll_timer()

    def _dock_position(self) -> QtCore.QPoint:
        size = self._window_size()
        screen = QtWidgets.QApplication.screenAt(QtGui.QCursor.pos()) or QtWidgets.QApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        margin = 28
        position = str(self.settings.get("companion_orb_position", "top-center") or "top-center").strip().lower()
        if position in {"top-center", "bottom-right"}:
            return QtCore.QPoint(geometry.center().x() - int(size / 2), geometry.top() + margin)
        if position == "bottom-left":
            return QtCore.QPoint(geometry.left() + margin, geometry.bottom() - size - margin)
        if position == "top-left":
            return QtCore.QPoint(geometry.left() + margin, geometry.top() + margin)
        if position == "top-right":
            return QtCore.QPoint(geometry.right() - size - margin, geometry.top() + margin)
        return QtCore.QPoint(geometry.center().x() - int(size / 2), geometry.top() + margin)

    def _home_position(self) -> QtCore.QPoint:
        custom = list(self.settings.get("companion_orb_custom_position", []) or [])
        if len(custom) == 2:
            try:
                return QtCore.QPoint(int(custom[0]), int(custom[1]))
            except Exception:
                pass
        return self._dock_position()

    def _return_home(self, *, animate: bool) -> None:
        point = self._home_position()
        self.base_position = QtCore.QPoint(point)
        self._clear_focus(expire_only=True)
        if animate and self.window is not None and self.window.isVisible():
            self._start_motion_to(point)
        elif self.window is not None:
            self.window.move(point)
            self.current_point = QtCore.QPointF(float(point.x()), float(point.y()))
            self._sync_drift_timer()

    def _frame_rate(self) -> int:
        try:
            fps = int(self.settings.get("companion_orb_frame_rate", 60) or 60)
        except Exception:
            fps = 60
        return min((30, 60, 90, 120), key=lambda candidate: abs(candidate - fps))

    def _timer_interval_ms(self) -> int:
        return max(8, min(33, int(1000 / max(30, self._frame_rate()))))

    def _apply_timer_interval(self) -> None:
        interval = self._timer_interval_ms()
        for timer in (self.drift_timer, self.motion_timer):
            if timer.interval() != interval:
                timer.setInterval(interval)

    def _sync_drift_timer(self) -> None:
        window = self.window
        should_run = bool(
            window is not None
            and window.isVisible()
            and not self.bridge.editMode
            and not self.bridge.placementMode
            and not self.motion_timer.isActive()
            and self.drag_offset is None
            and not self.poll_drag_active
            and (
                bool(self.settings.get("companion_orb_movement_enabled", True))
                or self._focus_ready()
                or self._interaction_target_ready()
                or bool(self.settings.get("companion_orb_mouse_near_fade", False))
                or bool(self.settings.get("companion_orb_avoid_mouse", False))
                or bool(self.settings.get("companion_orb_harassment_enabled", False))
            )
        )
        if should_run:
            if self.current_point is None and window is not None:
                top_left = window.frameGeometry().topLeft()
                self.current_point = QtCore.QPointF(float(top_left.x()), float(top_left.y()))
            if not self.drift_timer.isActive():
                self.last_tick_at = time.monotonic()
                self.drift_timer.start()
        else:
            self.last_tick_at = 0.0
            self.drift_timer.stop()
            self.playful_nudge_active = False
            self._apply_mouse_near_opacity(reset=True)

    def _set_comment_focus(self, payload: dict[str, Any]) -> None:
        target = payload.get("target")
        bounds = _normalize_bounds(payload.get("focus_bounds") or payload.get("bounds"))
        if not bounds and isinstance(target, dict):
            bounds = _normalize_bounds(target.get("bounds"))
        if not bounds:
            return
        try:
            duration = float(payload.get("duration_seconds", 14.0) or 14.0)
        except Exception:
            duration = 14.0
        if bool(payload.get("manual_drop", False)):
            self._set_drop_anchor(payload.get("drop_anchor"), duration_seconds=DROP_ANCHOR_HOVER_SECONDS)
        self.focus_bounds = list(bounds)
        self.focus_until = time.monotonic() + max(2.0, min(45.0, duration))
        self._sync_drift_timer()

    def _focus_ready(self) -> bool:
        if not self.focus_bounds:
            return False
        if time.monotonic() > self.focus_until:
            self._clear_focus()
            return False
        return True

    def _clear_focus(self, *, expire_only: bool = False) -> None:
        self.focus_bounds = []
        self.focus_until = 0.0
        if not expire_only:
            self._sync_drift_timer()

    def _set_drop_anchor(self, point, *, duration_seconds: float = DROP_ANCHOR_HOVER_SECONDS) -> None:
        try:
            values = [int(value) for value in list(point or [])[:2]]
        except Exception:
            return
        if len(values) != 2:
            return
        anchor = self._clamp_top_left_to_screen(QtCore.QPointF(float(values[0]), float(values[1])))
        self.drop_anchor_point = QtCore.QPoint(int(round(anchor.x())), int(round(anchor.y())))
        self.drop_anchor_until = time.monotonic() + max(2.0, min(60.0, float(duration_seconds)))
        self.base_position = QtCore.QPoint(self.drop_anchor_point)
        if self.current_point is None:
            self.current_point = QtCore.QPointF(float(self.drop_anchor_point.x()), float(self.drop_anchor_point.y()))
        self._sync_drift_timer()

    def _drop_anchor_ready(self) -> bool:
        if self.drop_anchor_point is None:
            return False
        if time.monotonic() <= float(self.drop_anchor_until or 0.0):
            return True
        self.drop_anchor_point = None
        self.drop_anchor_until = 0.0
        return False

    def _clear_drop_anchor(self) -> None:
        self.drop_anchor_point = None
        self.drop_anchor_until = 0.0

    def _set_interaction_target(self, point, *, duration_seconds: float) -> None:
        try:
            values = [float(value) for value in list(point or [])[:2]]
        except (TypeError, ValueError):
            return
        if len(values) != 2 or not all(math.isfinite(value) for value in values):
            return
        target = self._clamp_top_left_to_screen(QtCore.QPointF(values[0], values[1]))
        self.interaction_target_point = QtCore.QPointF(target)
        self.interaction_target_until = time.monotonic() + max(0.2, min(12.0, float(duration_seconds)))
        self.return_timer.stop()
        if self.motion_timer.isActive():
            self.motion_timer.stop()
            self.move_start = None
            self.move_target = None
        self._sync_drift_timer()

    def _interaction_target_ready(self) -> bool:
        if self.interaction_target_point is None:
            return False
        if time.monotonic() <= float(self.interaction_target_until or 0.0):
            return True
        self.interaction_target_point = None
        self.interaction_target_until = 0.0
        return False

    def _clear_interaction_target(self) -> None:
        self.interaction_target_point = None
        self.interaction_target_until = 0.0
        self._reset_pointer_clearance()
        self._sync_drift_timer()

    def _pointer_clearance_enabled(self) -> bool:
        return _interaction_settings().boolish(
            self.settings.get(
                "companion_orb_eye_tracking_pointer_clearance_enabled",
                False,
            ),
            default=False,
        )

    def _pointer_clearance_distance(self) -> float:
        try:
            value = float(
                self.settings.get(
                    "companion_orb_eye_tracking_pointer_clearance_distance_px",
                    160,
                )
                or 160
            )
        except (TypeError, ValueError):
            value = 160.0
        return max(40.0, min(400.0, value))

    def _pointer_clearance_timeout(self) -> float:
        try:
            value = float(
                self.settings.get(
                    "companion_orb_eye_tracking_pointer_clearance_timeout_seconds",
                    8,
                )
                or 8
            )
        except (TypeError, ValueError):
            value = 8.0
        return max(1.0, min(30.0, value))

    def _pointer_clearance_suspended(self) -> bool:
        return bool(
            self.pointer_clearance_suspended
            or self.bridge.editMode
            or self.bridge.placementMode
            or self.drag_offset is not None
            or self.poll_drag_active
            or self.cloaked
            or self.window is None
            or not self.window.isVisible()
        )

    def _pointer_clearance_screen_bounds(
        self,
        normal_target: QtCore.QPointF,
    ) -> tuple[float, float, float, float]:
        size = float(self.window.width()) if self.window is not None else 92.0
        center = QtCore.QPoint(
            int(round(normal_target.x() + size * 0.5)),
            int(round(normal_target.y() + size * 0.5)),
        )
        screen = (
            QtWidgets.QApplication.screenAt(center)
            or (self.window.screen() if self.window is not None else None)
            or QtWidgets.QApplication.primaryScreen()
        )
        geometry = (
            screen.availableGeometry()
            if screen is not None
            else QtCore.QRect(0, 0, 1280, 720)
        )
        return (
            float(geometry.x()),
            float(geometry.y()),
            float(geometry.width()),
            float(geometry.height()),
        )

    def _set_pointer_clearance_state(self, state: str) -> None:
        normalized = str(state or "clear").strip().lower()
        if normalized not in {"clear", "avoiding", "timeout"}:
            normalized = "clear"
        if normalized == self.pointer_clearance_state:
            return
        self.pointer_clearance_state = normalized
        _emit_event(
            {
                "type": "orb.pointer_clearance_state",
                "state": normalized,
            }
        )

    def _reset_pointer_clearance(self) -> None:
        self.pointer_clearance_policy.reset()
        self.pointer_clearance_opacity = 1.0
        self._set_pointer_clearance_state("clear")

    def _apply_pointer_clearance(
        self,
        normal_target: QtCore.QPointF,
        *,
        current_top_left: QtCore.QPointF,
        now: float,
    ) -> QtCore.QPointF:
        cursor = QtGui.QCursor.pos()
        size = float(self.window.width()) if self.window is not None else 92.0
        decision = self.pointer_clearance_policy.update(
            normal_target=(float(normal_target.x()), float(normal_target.y())),
            current_top_left=(
                float(current_top_left.x()),
                float(current_top_left.y()),
            ),
            pointer=(float(cursor.x()), float(cursor.y())),
            screen_bounds=self._pointer_clearance_screen_bounds(normal_target),
            orb_size=size,
            move_distance_px=self._pointer_clearance_distance(),
            timeout_seconds=self._pointer_clearance_timeout(),
            now=float(now),
            enabled=self._pointer_clearance_enabled(),
            suspended=self._pointer_clearance_suspended(),
        )
        self.pointer_clearance_opacity = float(decision.opacity)
        self._set_pointer_clearance_state(decision.state)
        return QtCore.QPointF(float(decision.target[0]), float(decision.target[1]))

    def _bounds_overlap_area(self, left_bounds, right_bounds) -> float:
        left = _normalize_bounds(left_bounds)
        right = _normalize_bounds(right_bounds)
        if not left or not right:
            return 0.0
        ax, ay, aw, ah = left
        bx, by, bw, bh = right
        overlap_w = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        overlap_h = max(0, min(ay + ah, by + bh) - max(ay, by))
        return float(overlap_w * overlap_h)

    def _focus_matches_drop_region(self) -> bool:
        if not self._drop_anchor_ready():
            return False
        focus = _normalize_bounds(self.focus_bounds)
        target = _normalize_bounds(self.selected_target_bounds)
        if not focus or not target:
            return False
        focus_area = max(1.0, float(focus[2]) * float(focus[3]))
        target_area = max(1.0, float(target[2]) * float(target[3]))
        overlap = self._bounds_overlap_area(focus, target)
        return bool(overlap / target_area >= 0.72 and focus_area >= target_area * 0.55)

    def _drop_anchor_target(self) -> QtCore.QPointF:
        anchor = self.drop_anchor_point
        if anchor is None:
            return self._clamp_top_left_to_screen(QtCore.QPointF(self._home_position()))
        amount = min(18.0, max(4.0, float(self._movement_range()) * 0.35))
        t = time.monotonic() * max(0.2, self._movement_speed())
        x = float(anchor.x()) + math.sin(t * 0.47) * amount + math.sin(t * 0.19 + 1.3) * amount * 0.35
        y = float(anchor.y()) + math.cos(t * 0.41 + 0.6) * amount * 0.55 + math.sin(t * 0.21 + 2.0) * amount * 0.25
        return self._clamp_top_left_to_screen(QtCore.QPointF(x, y))

    def _movement_speed(self) -> float:
        try:
            return max(0.10, min(1.75, float(self.settings.get("companion_orb_movement_speed", 0.65) or 0.65)))
        except Exception:
            return 0.65

    def _movement_range(self) -> int:
        try:
            return max(0, min(90, int(self.settings.get("companion_orb_movement_range", 18) or 0)))
        except Exception:
            return 18

    def _harassment_delay_seconds(self) -> float:
        try:
            return max(5.0, min(300.0, float(self.settings.get("companion_orb_harassment_timer_seconds", 45) or 45)))
        except Exception:
            return 45.0

    def _harassment_ready(self) -> bool:
        if not bool(self.settings.get("companion_orb_harassment_enabled", False)):
            self.playful_nudge_active = False
            return False
        if self.drag_offset is not None or self.poll_drag_active or self._focus_ready():
            return False
        return (time.monotonic() - self.last_user_interaction_at) >= self._harassment_delay_seconds()

    def _harassment_target(self) -> QtCore.QPointF:
        window = self.window
        cursor = QtGui.QCursor.pos()
        if window is None:
            return QtCore.QPointF(float(cursor.x()), float(cursor.y()))
        t = time.monotonic()
        orbit_x = math.sin(t * 0.82) * 68.0 + math.sin(t * 0.31 + 1.4) * 22.0
        orbit_y = math.cos(t * 0.70 + 0.8) * 46.0 + math.sin(t * 0.43) * 14.0
        target_x = float(cursor.x()) + orbit_x - window.width() * 0.5
        target_y = float(cursor.y()) + orbit_y - window.height() * 0.5
        return self._clamp_top_left_to_screen(QtCore.QPointF(target_x, target_y))

    def _mouse_fade_distance(self) -> float:
        try:
            return max(24.0, min(420.0, float(self.settings.get("companion_orb_mouse_near_fade_distance", 120) or 120)))
        except Exception:
            return 120.0

    def _apply_mouse_near_opacity(self, *, reset: bool = False) -> None:
        window = self.window
        if window is None:
            return
        opacity = (
            1.0
            if reset
            else max(
                0.0,
                min(1.0, float(self.pointer_clearance_opacity)),
            )
        )
        if (
            opacity > 0.0
            and not reset
            and bool(self.settings.get("companion_orb_mouse_near_fade", False))
        ):
            cursor = QtGui.QCursor.pos()
            center = window.frameGeometry().center()
            distance = math.hypot(float(center.x() - cursor.x()), float(center.y() - cursor.y()))
            fade_distance = self._mouse_fade_distance()
            try:
                near_opacity = max(0.05, min(1.0, float(self.settings.get("companion_orb_mouse_near_opacity", 0.28) or 0.28)))
            except Exception:
                near_opacity = 0.28
            if distance < fade_distance:
                mix = max(0.0, min(1.0, distance / fade_distance))
                opacity = min(
                    opacity,
                    near_opacity + (1.0 - near_opacity) * mix,
                )
        try:
            window.setWindowOpacity(opacity)
        except Exception:
            pass

    def _clamped_float_setting(self, key: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(self.settings.get(key, default))
        except Exception:
            value = float(default)
        return max(float(minimum), min(float(maximum), value))

    def _aware_motion_enabled(self) -> bool:
        return bool(self.settings.get("companion_orb_aware_motion_enabled", True))

    def _awareness_level(self) -> float:
        return self._clamped_float_setting("companion_orb_awareness", 0.55, 0.0, 1.0)

    def _focus_pull(self) -> float:
        return self._clamped_float_setting("companion_orb_focus_pull", 0.65, 0.0, 1.0)

    def _idle_pause_strength(self) -> float:
        return self._clamped_float_setting("companion_orb_idle_pause", 0.45, 0.0, 1.0)

    def _time_scaled_blend(self, blend: float, frame_scale: float) -> float:
        base = max(0.0, min(0.98, float(blend)))
        scale = max(0.10, min(6.0, float(frame_scale)))
        return max(0.0, min(0.98, 1.0 - pow(1.0 - base, scale)))

    def _aware_focus_hover_target(self, target: QtCore.QPointF, *, now: float, amount: float) -> QtCore.QPointF:
        if not self._aware_motion_enabled():
            return QtCore.QPointF(target)
        awareness = self._awareness_level()
        focus_pull = self._focus_pull()
        if awareness <= 0.0 or focus_pull <= 0.0:
            return QtCore.QPointF(target)
        hover = min(7.0, max(1.5, max(4.0, float(amount)) * 0.12)) * awareness * (0.45 + focus_pull * 0.55)
        x = target.x() + math.sin(now * 0.58 + 1.2) * hover
        y = target.y() + math.cos(now * 0.47 + 0.4) * hover * 0.62
        return self._clamp_top_left_to_screen(QtCore.QPointF(x, y))

    def _aware_idle_target(
        self,
        *,
        base: QtCore.QPoint,
        target_x: float,
        target_y: float,
        now: float,
        amount: float,
        speed: float,
    ) -> tuple[float, float, float]:
        if not self._aware_motion_enabled():
            return target_x, target_y, max(0.055, min(0.18, 0.055 + speed * 0.055))
        awareness = self._awareness_level()
        pause_strength = self._idle_pause_strength()
        if awareness <= 0.0 and pause_strength <= 0.0:
            return target_x, target_y, max(0.055, min(0.18, 0.055 + speed * 0.055))

        t = now * max(0.15, speed)
        calm_scale = 1.0 - pause_strength * 0.10
        target_x = float(base.x()) + (target_x - float(base.x())) * calm_scale
        target_y = float(base.y()) + (target_y - float(base.y())) * calm_scale
        target_x += math.sin(t * 0.09 + 2.1) * amount * 0.08 * awareness
        target_y += math.cos(t * 0.075 + 0.5) * amount * 0.055 * awareness

        current = self.current_point or QtCore.QPointF(target_x, target_y)
        if pause_strength > 0.0 and now >= self.idle_next_pause_at and now >= self.idle_pause_until:
            self.idle_pause_point = QtCore.QPointF(current)
            hold_seconds = 0.35 + pause_strength * (0.75 + awareness * 0.55)
            rest_seconds = 2.4 + (1.0 - pause_strength) * 2.4 + (1.0 - awareness) * 1.2
            self.idle_pause_until = now + hold_seconds
            self.idle_next_pause_at = self.idle_pause_until + rest_seconds

        smoothing = max(0.055, min(0.18, 0.055 + speed * 0.055))
        if pause_strength > 0.0 and now < self.idle_pause_until and self.idle_pause_point is not None:
            anchor = self.idle_pause_point
            observe = min(3.8, max(0.8, amount * 0.06)) * awareness
            target_x = anchor.x() + math.sin(now * 0.82) * observe
            target_y = anchor.y() + math.cos(now * 0.71 + 0.8) * observe * 0.55
            smoothing = 0.055 + awareness * 0.025
        else:
            smoothing = max(0.055, smoothing - pause_strength * 0.025)
        return target_x, target_y, smoothing

    def _on_drift_tick(self) -> None:
        window = self.window
        if window is None or not window.isVisible() or self.motion_timer.isActive():
            self.drift_timer.stop()
            self.last_tick_at = 0.0
            return
        now = time.monotonic()
        previous = self.last_tick_at or now
        elapsed = max(0.0, min(0.12, now - previous))
        self.last_tick_at = now
        frame_scale = max(0.25, min(5.0, elapsed / (1.0 / 60.0))) if elapsed > 0.0 else 1.0
        base = self.base_position or self._home_position()
        self.base_position = QtCore.QPoint(base)
        speed = self._movement_speed()
        interaction_target_ready = self._interaction_target_ready()
        if not interaction_target_ready:
            self._reset_pointer_clearance()
        harassment_ready = False if interaction_target_ready else self._harassment_ready()
        if interaction_target_ready:
            target = self.interaction_target_point or QtCore.QPointF(base)
            current_top_left = QtCore.QPointF(
                float(window.x()),
                float(window.y()),
            )
            cleared_target = self._apply_pointer_clearance(
                QtCore.QPointF(target),
                current_top_left=current_top_left,
                now=now,
            )
            target_x = cleared_target.x()
            target_y = cleared_target.y()
            smoothing = self._time_scaled_blend(0.16, frame_scale)
            self.playful_nudge_active = False
        elif self._focus_ready():
            if self._focus_matches_drop_region():
                target = self._drop_anchor_target()
                target_x = target.x()
                target_y = target.y()
            else:
                left, top, width, height = self.focus_bounds
                target_x = float(left + width * 0.5 - window.width() * 0.5)
                target_y = float(top - window.height() * 0.62)
            target = self._aware_focus_hover_target(
                self._clamp_top_left_to_screen(QtCore.QPointF(target_x, target_y)),
                now=now,
                amount=float(self._movement_range()),
            )
            target_x = target.x()
            target_y = target.y()
            focus_pull = self._focus_pull() if self._aware_motion_enabled() else 0.65
            smoothing = self._time_scaled_blend(0.11 + focus_pull * 0.05, frame_scale)
            self.playful_nudge_active = False
        elif harassment_ready:
            target = self._harassment_target()
            target_x = target.x()
            target_y = target.y()
            smoothing = self._time_scaled_blend(0.11, frame_scale)
            if not self.playful_nudge_active:
                self.playful_nudge_active = True
                self._emit_playful_nudge()
        else:
            if self.playful_nudge_active:
                self.playful_nudge_active = False
                self.return_timer.start(max(250, min(30000, int(float(self.settings.get("companion_orb_return_home_delay", 2.5) or 2.5) * 1000))))
            amount = float(self._movement_range()) if bool(self.settings.get("companion_orb_movement_enabled", True)) else 0.0
            t = now * speed
            target_x = float(base.x()) + math.sin(t * 0.42) * amount + math.sin(t * 0.17 + 1.9) * amount * 0.34
            target_y = float(base.y()) + math.cos(t * 0.36 + 0.7) * amount * 0.58 + math.sin(t * 0.13 + 2.4) * amount * 0.26
            target_x, target_y, smoothing = self._aware_idle_target(
                base=base,
                target_x=target_x,
                target_y=target_y,
                now=now,
                amount=amount,
                speed=speed,
            )
            smoothing = self._time_scaled_blend(smoothing, frame_scale)
        if (
            bool(self.settings.get("companion_orb_avoid_mouse", False))
            and not harassment_ready
            and not self._focus_ready()
            and not interaction_target_ready
        ):
            cursor = QtGui.QCursor.pos()
            center_x = target_x + window.width() * 0.5
            center_y = target_y + window.height() * 0.5
            dx = center_x - float(cursor.x())
            dy = center_y - float(cursor.y())
            distance = max(1.0, math.hypot(dx, dy))
            fade_distance = self._mouse_fade_distance()
            if distance < fade_distance:
                push = (fade_distance - distance) / fade_distance
                target_x += (dx / distance) * push * min(90.0, fade_distance * 0.32)
                target_y += (dy / distance) * push * min(90.0, fade_distance * 0.32)
        current = self.current_point
        if current is None:
            current = QtCore.QPointF(float(window.x()), float(window.y()))
        next_x = current.x() + (target_x - current.x()) * smoothing
        next_y = current.y() + (target_y - current.y()) * smoothing
        self.current_point = QtCore.QPointF(next_x, next_y)
        window.move(QtCore.QPoint(int(round(next_x)), int(round(next_y))))
        if harassment_ready:
            self._maybe_emit_pointer_reached()
        self._apply_mouse_near_opacity()

    def _start_motion_to(self, target: QtCore.QPoint) -> None:
        if self.window is None:
            return
        self.drift_timer.stop()
        start = self.window.frameGeometry().topLeft()
        self.move_start = QtCore.QPoint(start)
        self.move_target = QtCore.QPoint(target)
        self.move_started_at = time.monotonic()
        distance = math.hypot(float(target.x() - start.x()), float(target.y() - start.y()))
        self.move_duration = max(0.65, min(3.6, distance / max(120.0, 360.0 * self._movement_speed())))
        self.move_curve_sign = -1.0 if int(self.move_started_at * 1000) % 2 else 1.0
        self.motion_timer.start()

    def _on_motion_tick(self) -> None:
        if self.window is None or self.move_start is None or self.move_target is None:
            self.motion_timer.stop()
            self._sync_drift_timer()
            return
        start = self.move_start
        target = self.move_target
        elapsed = max(0.0, time.monotonic() - self.move_started_at)
        progress = min(1.0, elapsed / max(0.05, self.move_duration))
        eased = 1.0 - pow(1.0 - progress, 3.0)
        dx = float(target.x() - start.x())
        dy = float(target.y() - start.y())
        distance = max(1.0, math.hypot(dx, dy))
        curve = math.sin(progress * math.pi) * min(96.0, max(18.0, distance * 0.18)) * self.move_curve_sign
        x = start.x() + dx * eased + (-dy / distance) * curve
        y = start.y() + dy * eased + (dx / distance) * curve
        self.window.move(QtCore.QPoint(int(round(x)), int(round(y))))
        if progress >= 1.0:
            self.motion_timer.stop()
            self.window.move(target)
            self.base_position = QtCore.QPoint(target)
            self.current_point = QtCore.QPointF(float(target.x()), float(target.y()))
            self._sync_drift_timer()

    def _clamp_top_left_to_screen(self, point: QtCore.QPointF | QtCore.QPoint) -> QtCore.QPointF:
        window = self.window
        if window is None:
            return QtCore.QPointF(point)
        target_center = QtCore.QPoint(
            int(round(float(point.x()) + window.width() * 0.5)),
            int(round(float(point.y()) + window.height() * 0.5)),
        )
        target_top_left = QtCore.QPoint(int(round(float(point.x()))), int(round(float(point.y()))))
        screen = (
            QtWidgets.QApplication.screenAt(target_center)
            or QtWidgets.QApplication.screenAt(target_top_left)
            or window.screen()
            or QtWidgets.QApplication.screenAt(QtGui.QCursor.pos())
            or QtWidgets.QApplication.primaryScreen()
        )
        available = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        x = max(float(available.left()), min(float(point.x()), float(available.right() - window.width())))
        y = max(float(available.top()), min(float(point.y()), float(available.bottom() - window.height())))
        return QtCore.QPointF(x, y)

    def _sync_drag_poll_timer(self) -> None:
        window = self.window
        should_run = bool(window is not None and window.isVisible() and self.bridge.clickThrough)
        if should_run:
            if not self.poll_drag_timer.isActive():
                self.poll_drag_timer.start()
        elif self.poll_drag_timer.isActive():
            self.poll_drag_timer.stop()
            self._clear_poll_drag()

    def _poll_pointer_drag(self) -> None:
        window = self.window
        if window is None or not window.isVisible():
            self._clear_poll_drag()
            return
        if not self.bridge.clickThrough:
            self.right_button_was_down = False
            self.left_button_was_down = False
            self._clear_poll_drag()
            return

        right_down = self._mouse_button_down("right")
        left_down = self._mouse_button_down("left")
        cursor = QtGui.QCursor.pos()

        if self.poll_drag_active:
            drag_down = right_down if self.poll_drag_button == "right" else left_down
            if drag_down:
                self._move_poll_drag(cursor)
            else:
                self._finish_poll_drag()
            self.right_button_was_down = right_down
            self.left_button_was_down = left_down
            return

        if not right_down and not left_down:
            if self.poll_drag_start_pos is not None:
                button = str(self.poll_drag_button or "").strip().lower()
                point = QtCore.QPoint(cursor)
                self._clear_poll_drag()
                self.right_button_was_down = False
                self.left_button_was_down = False
                if button == "right":
                    self._emit_menu_request(point)
                return
            self._clear_poll_drag()
            self.right_button_was_down = False
            self.left_button_was_down = False
            return

        if not window.frameGeometry().contains(cursor):
            self.right_button_was_down = right_down
            self.left_button_was_down = left_down
            return

        if left_down and not self.left_button_was_down:
            self.poll_drag_start_pos = QtCore.QPoint(cursor)
            self.poll_drag_offset = cursor - window.frameGeometry().topLeft()
            self.poll_drag_button = "left"
        elif right_down and not self.right_button_was_down:
            self.poll_drag_start_pos = QtCore.QPoint(cursor)
            self.poll_drag_offset = cursor - window.frameGeometry().topLeft()
            self.poll_drag_button = "right"
        elif self.poll_drag_start_pos is not None:
            dx = float(cursor.x() - self.poll_drag_start_pos.x())
            dy = float(cursor.y() - self.poll_drag_start_pos.y())
            if math.hypot(dx, dy) >= POLL_DRAG_THRESHOLD_PX:
                self._start_poll_drag(cursor)

        self.right_button_was_down = right_down
        self.left_button_was_down = left_down

    def _start_poll_drag(self, cursor: QtCore.QPoint) -> None:
        window = self.window
        if window is None:
            return
        if self.poll_drag_offset is None:
            self.poll_drag_offset = cursor - window.frameGeometry().topLeft()
        self.poll_drag_active = True
        self.drift_timer.stop()
        self.motion_timer.stop()
        self.return_timer.stop()
        self._move_poll_drag(cursor)

    def _move_poll_drag(self, cursor: QtCore.QPoint) -> None:
        if self.window is None or self.poll_drag_offset is None:
            return
        point = cursor - self.poll_drag_offset
        self._move_to_drag_position(point)

    def _finish_poll_drag(self) -> None:
        window = self.window
        button = str(self.poll_drag_button or "").strip().lower()
        if window is not None:
            self._record_drag_position(window.frameGeometry().topLeft())
            self._emit_position_changed()
        self._clear_poll_drag()
        if button in {"left", "right"}:
            self._emit_drop_event(button=button, reason=f"{button}_drag_drop")
        self._sync_drift_timer()

    def _clear_poll_drag(self) -> None:
        self.poll_drag_start_pos = None
        self.poll_drag_offset = None
        self.poll_drag_button = ""
        self.poll_drag_active = False

    def _move_to_drag_position(self, point: QtCore.QPoint) -> None:
        window = self.window
        if window is None:
            return
        clamped = self._clamp_top_left_to_screen(QtCore.QPointF(point))
        target = QtCore.QPoint(int(round(clamped.x())), int(round(clamped.y())))
        window.move(target)
        self._record_drag_position(point)

    def _record_drag_position(self, point: QtCore.QPoint) -> None:
        clamped = self._clamp_top_left_to_screen(QtCore.QPointF(point))
        target = QtCore.QPoint(int(round(clamped.x())), int(round(clamped.y())))
        self.settings["companion_orb_custom_position"] = [int(target.x()), int(target.y())]
        self.base_position = QtCore.QPoint(target)
        self.current_point = QtCore.QPointF(float(target.x()), float(target.y()))
        self.move_start = None
        self.move_target = None
        self.last_user_interaction_at = time.monotonic()
        self.playful_nudge_active = False

    def _emit_position_changed(self) -> None:
        _emit_event(
            {
                "type": "orb.position_changed",
                "top_left": self._window_top_left_payload(),
                "center": self._window_center_payload(),
            }
        )

    def _emit_playful_nudge(self) -> None:
        now = time.monotonic()
        if now - self.last_playful_nudge_at < PLAYFUL_NUDGE_EVENT_COOLDOWN_SECONDS:
            return
        self.last_playful_nudge_at = now
        _emit_event(
            {
                "type": "orb.playful_nudge",
                "point": [int(QtGui.QCursor.pos().x()), int(QtGui.QCursor.pos().y())],
                "center": self._window_center_payload(),
                "top_left": self._window_top_left_payload(),
            }
        )

    def _maybe_emit_pointer_reached(self) -> None:
        if not bool(self.settings.get("companion_orb_snapshot_on_pointer_reached", False)):
            return
        window = self.window
        if window is None:
            return
        cursor = QtGui.QCursor.pos()
        center = window.frameGeometry().center()
        reach_distance = max(48.0, min(150.0, float(window.width()) * 0.36))
        distance = math.hypot(float(center.x() - cursor.x()), float(center.y() - cursor.y()))
        if distance > reach_distance:
            return
        now = time.monotonic()
        if now - self.last_pointer_snapshot_at < POINTER_SNAPSHOT_COOLDOWN_SECONDS:
            return
        self.last_pointer_snapshot_at = now
        _emit_event(
            {
                "type": "orb.pointer_reached",
                "point": [int(cursor.x()), int(cursor.y())],
                "center": self._window_center_payload(),
                "top_left": self._window_top_left_payload(),
            }
        )

    def _window_center_payload(self) -> list[int]:
        window = self.window
        if window is None:
            return []
        center = window.frameGeometry().center()
        return [int(center.x()), int(center.y())]

    def _window_top_left_payload(self) -> list[int]:
        window = self.window
        if window is None:
            return []
        point = window.frameGeometry().topLeft()
        return [int(point.x()), int(point.y())]

    def _emit_drop_event(self, *, button: str, reason: str) -> None:
        _emit_event(
            {
                "type": "orb.dropped",
                "button": str(button or ""),
                "reason": str(reason or "external_drag_drop"),
                "center": self._window_center_payload(),
                "top_left": self._window_top_left_payload(),
            }
        )

    def _emit_menu_request(self, global_pos: QtCore.QPoint) -> None:
        _emit_event(
            {
                "type": "orb.request_menu",
                "point": [int(global_pos.x()), int(global_pos.y())],
                "center": self._window_center_payload(),
                "top_left": self._window_top_left_payload(),
            }
        )

    def _set_cloak(self, enabled: bool) -> None:
        window = self.window
        enabled = bool(enabled)
        if window is None:
            self.cloaked = enabled
            return
        if enabled:
            if not self.cloaked:
                self.visible_before_cloak = bool(window.isVisible())
            self.cloaked = True
            self._clear_direct_drag()
            self._clear_poll_drag()
            if window.isVisible():
                window.hide()
            self.drift_timer.stop()
            self.motion_timer.stop()
            self.poll_drag_timer.stop()
            _emit_event({"type": "orb.cloak_changed", "enabled": True})
            return
        was_visible = bool(self.visible_before_cloak)
        self.cloaked = False
        self.visible_before_cloak = False
        if was_visible:
            self._refresh_visibility()
        else:
            self._sync_drag_poll_timer()
        _emit_event({"type": "orb.cloak_changed", "enabled": False})

    def _mouse_button_down(self, button: str) -> bool:
        normalized = str(button or "").strip().lower()
        if sys.platform == "win32":
            try:
                import ctypes

                vk_code = 0x02 if normalized == "right" else 0x01
                return bool(ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000)
            except Exception:
                pass
        try:
            qt_button = QtCore.Qt.RightButton if normalized == "right" else QtCore.Qt.LeftButton
            return bool(QtGui.QGuiApplication.mouseButtons() & qt_button)
        except Exception:
            return False

    def _effective_click_through(self, requested: Any = None) -> bool:
        click_through = _interaction_settings().effective_click_through(
            self.settings,
            edit_mode=bool(self.bridge.editMode),
            placement_mode=bool(self.bridge.placementMode),
        )
        if requested is not None and not bool(requested):
            return False
        return click_through

    def _apply_click_through(self, enabled: bool) -> None:
        enabled = self._effective_click_through(enabled)
        for widget in (self.window, self.quick):
            if widget is None:
                continue
            try:
                widget.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, bool(enabled))
            except Exception:
                pass
        if sys.platform != "win32" or self.window is None:
            self._apply_orb_cursor(click_through=bool(enabled))
            self._sync_drag_poll_timer()
            return
        try:
            import ctypes

            hwnd = int(self.window.winId())
            gwl_exstyle = -20
            ws_ex_transparent = 0x00000020
            ws_ex_layered = 0x00080000
            current = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_exstyle)
            next_style = current | ws_ex_layered
            if enabled:
                next_style |= ws_ex_transparent
            else:
                next_style &= ~ws_ex_transparent
            ctypes.windll.user32.SetWindowLongW(hwnd, gwl_exstyle, next_style)
        except Exception:
            pass
        self._apply_orb_cursor(click_through=bool(enabled))
        self._sync_drag_poll_timer()

    def _apply_orb_cursor(self, *, click_through: bool, dragging: bool = False) -> None:
        for widget in (self.window, self.quick):
            if widget is None:
                continue
            try:
                if bool(click_through):
                    widget.unsetCursor()
                else:
                    cursor_shape = QtCore.Qt.ClosedHandCursor if bool(dragging) else QtCore.Qt.OpenHandCursor
                    widget.setCursor(QtGui.QCursor(cursor_shape))
            except Exception:
                pass


def _read_stdin(relay: _MessageRelay) -> None:
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception as exc:
            _log(f"Invalid Companion Orb external IPC payload: {exc}")
            continue
        if isinstance(payload, dict):
            relay.message_received.emit(payload)
    relay.message_received.emit({"type": "shutdown"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Companion Orb external animation runtime")
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--check", action="store_true", help="Verify imports and assets without opening the overlay window.")
    args = parser.parse_args()
    app_root = Path(args.app_root).resolve()
    _bootstrap_imports(app_root)
    if args.check:
        from addons.companion_orb_overlay.companion_orb.companion_orb_bridge import CompanionOrbBridge

        qml_path = Path(__file__).parent / "qml" / "CompanionOrbOverlay.qml"
        if not qml_path.exists():
            print(f"Missing Companion Orb QML: {qml_path}", flush=True)
            return 2
        bridge = CompanionOrbBridge()
        bridge.apply_settings({"companion_orb_enabled": True, "companion_orb_display_mode": "docked"})
        print("Companion Orb external runtime check passed.", flush=True)
        return 0
    lock = None
    try:
        lock_path = app_root / "runtime" / "companion_orb" / "external_runtime.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = QtCore.QLockFile(str(lock_path))
        lock.setStaleLockTime(30000)
        if not lock.tryLock(100):
            _log("Companion Orb external runtime is already running for this app root.")
            return 0
    except Exception as exc:
        _log(f"Companion Orb external runtime lock unavailable: {exc}")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    runtime = ExternalCompanionOrb(app_root)
    relay = _MessageRelay()
    relay.message_received.connect(runtime.handle_message, QtCore.Qt.QueuedConnection)
    reader = threading.Thread(target=_read_stdin, args=(relay,), daemon=True, name="companion-orb-external-ipc")
    reader.start()
    _emit_event({"type": "orb.ready"})
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
