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


DROP_ANCHOR_HOVER_SECONDS = 18.0


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
        self.last_tick_at = 0.0
        self.move_start: QtCore.QPoint | None = None
        self.move_target: QtCore.QPoint | None = None
        self.move_started_at = 0.0
        self.move_duration = 0.0
        self.move_curve_sign = 1.0

        self.drift_timer = QtCore.QTimer(self)
        self.drift_timer.setInterval(16)
        self.drift_timer.timeout.connect(self._on_drift_tick)
        self.motion_timer = QtCore.QTimer(self)
        self.motion_timer.setInterval(16)
        self.motion_timer.timeout.connect(self._on_motion_tick)
        self.return_timer = QtCore.QTimer(self)
        self.return_timer.setSingleShot(True)
        self.return_timer.timeout.connect(lambda: self._return_home(animate=True))

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
        if msg_type == "modes":
            self.bridge.set_modes(
                edit_mode=message.get("edit_mode") if "edit_mode" in message else None,
                placement_mode=message.get("placement_mode") if "placement_mode" in message else None,
                click_through=message.get("click_through") if "click_through" in message else None,
            )
            self._apply_click_through(bool(self.bridge.clickThrough))
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
        self.settings = dict(settings or {})
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
        self.window = window
        self.quick = quick
        self._apply_window_settings()

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
        click_through = bool(self.settings.get("companion_orb_click_through_default", True))
        if self.bridge.editMode or self.bridge.placementMode:
            click_through = False
        self.bridge.set_modes(click_through=click_through)
        self._apply_click_through(click_through)
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
        enabled = bool(self.settings.get("companion_orb_enabled", False))
        mode = str(self.settings.get("companion_orb_display_mode", "off") or "off").strip().lower()
        if not enabled or mode == "off":
            window.hide()
            self.drift_timer.stop()
            self.motion_timer.stop()
            return
        active = self.bridge.aiState in {"listening", "thinking", "speaking"} or self.bridge.audioLevel > 0.025
        visible = mode in {"docked", "always"} or (mode == "interaction" and active) or self.bridge.editMode or self.bridge.placementMode
        if visible and not window.isVisible():
            window.show()
        elif not visible and window.isVisible():
            window.hide()
        self._sync_drift_timer()

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
            and (
                bool(self.settings.get("companion_orb_movement_enabled", True))
                or self._focus_ready()
                or bool(self.settings.get("companion_orb_mouse_near_fade", False))
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

    def _time_scaled_blend(self, blend: float, frame_scale: float) -> float:
        base = max(0.0, min(0.98, float(blend)))
        scale = max(0.10, min(6.0, float(frame_scale)))
        return max(0.0, min(0.98, 1.0 - pow(1.0 - base, scale)))

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
        if self._focus_ready():
            if self._focus_matches_drop_region():
                target = self._drop_anchor_target()
                target_x = target.x()
                target_y = target.y()
            else:
                left, top, width, height = self.focus_bounds
                target_x = float(left + width * 0.5 - window.width() * 0.5)
                target_y = float(top - window.height() * 0.62)
            smoothing = self._time_scaled_blend(0.14, frame_scale)
        else:
            amount = float(self._movement_range()) if bool(self.settings.get("companion_orb_movement_enabled", True)) else 0.0
            t = now * speed
            target_x = float(base.x()) + math.sin(t * 0.42) * amount + math.sin(t * 0.17 + 1.9) * amount * 0.34
            target_y = float(base.y()) + math.cos(t * 0.36 + 0.7) * amount * 0.58 + math.sin(t * 0.13 + 2.4) * amount * 0.26
            smoothing = self._time_scaled_blend(max(0.055, min(0.18, 0.055 + speed * 0.055)), frame_scale)
        current = self.current_point
        if current is None:
            current = QtCore.QPointF(float(window.x()), float(window.y()))
        next_x = current.x() + (target_x - current.x()) * smoothing
        next_y = current.y() + (target_y - current.y()) * smoothing
        self.current_point = QtCore.QPointF(next_x, next_y)
        window.move(QtCore.QPoint(int(round(next_x)), int(round(next_y))))

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

    def _apply_click_through(self, enabled: bool) -> None:
        for widget in (self.window, self.quick):
            if widget is None:
                continue
            try:
                widget.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, bool(enabled))
            except Exception:
                pass
        if sys.platform != "win32" or self.window is None:
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


def _read_stdin(relay: _MessageRelay) -> None:
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception as exc:
            print(f"Invalid Companion Orb external IPC payload: {exc}", flush=True)
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
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    runtime = ExternalCompanionOrb(app_root)
    relay = _MessageRelay()
    relay.message_received.connect(runtime.handle_message, QtCore.Qt.QueuedConnection)
    reader = threading.Thread(target=_read_stdin, args=(relay,), daemon=True, name="companion-orb-external-ipc")
    reader.start()
    print("Companion Orb external runtime ready.", flush=True)
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
