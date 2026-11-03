from __future__ import annotations

import base64
from dataclasses import dataclass
import math
import time
from pathlib import Path
from typing import Mapping, Sequence

from PySide6 import QtCore, QtGui, QtQuick


@dataclass(frozen=True, slots=True)
class RadialAction:
    action_id: str
    label: str
    enabled: bool = True
    checked: bool = False
    tooltip: str = ""
    preview_png: bytes = b""
    role: str = ""
    crosshair_x: float = 0.5
    crosshair_y: float = 0.5


@dataclass(frozen=True, slots=True)
class RadialHitTarget:
    action_id: str
    center_x: float
    center_y: float
    diameter: float
    enabled: bool = True


RADIAL_ENTRY_RADIUS_RATIO = 0.62
RADIAL_STICKY_RADIUS_RATIO = 0.74
RADIAL_MENU_SIZE = 660
RADIAL_BUTTON_SIZE = 104
RADIAL_EXPANDED_RADIUS = 235.0
RADIAL_COMPACT_RADIUS = 217.5
RADIAL_MENU_DEFAULT_OPACITY = 0.90
RADIAL_MENU_MIN_OPACITY = 0.35
VISUAL_PREVIEW_LIMIT = 4
VISUAL_PREVIEW_BUTTON_SIZE = 148
VISUAL_UTILITY_BUTTON_SIZE = 72
FLOATING_PREVIEW_LENS_SIZE = 220
FLOATING_PREVIEW_LENS_GAP = 18
FLOATING_PREVIEW_LENS_MARGIN = 12
FLOATING_PREVIEW_TRANSFER_RADIUS = 44.0


def radial_layout_radius(action_count: int) -> float:
    return RADIAL_EXPANDED_RADIUS if int(action_count) >= 7 else RADIAL_COMPACT_RADIUS


def normalize_radial_menu_opacity(value: object, default: float = RADIAL_MENU_DEFAULT_OPACITY) -> float:
    try:
        opacity = float(value)
    except (TypeError, ValueError):
        opacity = float(default)
    return max(RADIAL_MENU_MIN_OPACITY, min(1.0, opacity))


def radial_hit_test(
    point: Sequence[float],
    targets: Sequence[RadialHitTarget],
    *,
    candidate_id: str | None = None,
) -> str | None:
    try:
        point_x, point_y = (float(value) for value in list(point)[:2])
    except (TypeError, ValueError):
        return None
    normalized_candidate = str(candidate_id or "").strip()
    if normalized_candidate:
        for target in targets:
            if target.action_id != normalized_candidate or not target.enabled:
                continue
            distance = math.hypot(point_x - target.center_x, point_y - target.center_y)
            if distance <= max(0.0, target.diameter) * RADIAL_STICKY_RADIUS_RATIO:
                return target.action_id
            break
    for target in targets:
        if not target.enabled:
            continue
        distance = math.hypot(point_x - target.center_x, point_y - target.center_y)
        if distance <= max(0.0, target.diameter) * RADIAL_ENTRY_RADIUS_RATIO:
            return target.action_id
    return None


MAIN_GAZE_ACTIONS: tuple[RadialAction, ...] = (
    RadialAction("react", "React"),
    RadialAction("describe", "Describe"),
    RadialAction("explain", "Explain"),
    RadialAction("summarize", "Summarize"),
    RadialAction("read_text", "Read\ntext"),
    RadialAction("voice", "Voice"),
    RadialAction("reply_style", "Reply\nstyle"),
    RadialAction("chat", "Chat"),
    RadialAction("scrolling", "Scrolling"),
    RadialAction(
        "action",
        "Action",
        enabled=False,
        tooltip="Enable the Action gaze button in Eye Tracking settings.",
    ),
)

SPATIAL_TARGET_ACTIONS: tuple[RadialAction, ...] = (
    RadialAction("spatial:react", "React"),
    RadialAction("spatial:describe", "Describe"),
    RadialAction("spatial:explain", "Explain"),
    RadialAction("spatial:summarize", "Summarize"),
    RadialAction("spatial:read", "Read"),
    RadialAction("spatial:ask", "Ask about"),
    RadialAction("spatial:move", "Move Orb"),
    RadialAction("spatial:interact", "Interact"),
)


class GazeSelectionPolicy:
    """Select one fixed menu action after a configurable uninterrupted gaze."""

    def __init__(self, *, dwell_ms: int = 650, sample_gap_seconds: float | None = None):
        self.dwell_seconds = max(0.05, min(10.0, float(dwell_ms) / 1000.0))
        self.sample_gap_seconds = (
            None
            if sample_gap_seconds is None
            else max(0.10, min(2.0, float(sample_gap_seconds)))
        )
        self._candidate_id: str | None = None
        self._candidate_started_at = 0.0
        self._selection_emitted = False
        self._progress = 0.0
        self._last_sample_at: float | None = None

    @property
    def candidate_id(self) -> str | None:
        return self._candidate_id

    @property
    def progress(self) -> float:
        return self._progress

    def reset(self) -> None:
        self._candidate_id = None
        self._candidate_started_at = 0.0
        self._selection_emitted = False
        self._progress = 0.0
        self._last_sample_at = None

    def ingest(self, action_id: str | None, *, now: float) -> tuple[float, str | None]:
        sample_at = float(now)
        if (
            self._last_sample_at is not None
            and self.sample_gap_seconds is not None
            and sample_at - self._last_sample_at > self.sample_gap_seconds
        ):
            self.reset()
        self._last_sample_at = sample_at
        normalized = str(action_id or "").strip() or None
        if normalized is None:
            self.reset()
            return 0.0, None
        if normalized != self._candidate_id:
            self._candidate_id = normalized
            self._candidate_started_at = sample_at
            self._selection_emitted = False
            self._progress = 0.0
            return 0.0, None
        elapsed = max(0.0, sample_at - self._candidate_started_at)
        complete = elapsed + 1e-9 >= self.dwell_seconds
        progress = 1.0 if complete else min(1.0, elapsed / self.dwell_seconds)
        self._progress = progress
        if complete and not self._selection_emitted:
            self._selection_emitted = True
            return 1.0, normalized
        return progress, None


def _normalized_color(value: object, fallback: str) -> QtGui.QColor:
    color = QtGui.QColor(str(value or "").strip())
    return color if color.isValid() else QtGui.QColor(fallback)


def _with_alpha(color: QtGui.QColor, alpha: int) -> QtGui.QColor:
    result = QtGui.QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result


def _blend(left: QtGui.QColor, right: QtGui.QColor, amount: float) -> QtGui.QColor:
    mix = max(0.0, min(1.0, float(amount)))
    return QtGui.QColor.fromRgbF(
        left.redF() * (1.0 - mix) + right.redF() * mix,
        left.greenF() * (1.0 - mix) + right.greenF() * mix,
        left.blueF() * (1.0 - mix) + right.blueF() * mix,
        left.alphaF() * (1.0 - mix) + right.alphaF() * mix,
    )


def _normalized_crosshair_ratio(value: object) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.5
    if not math.isfinite(ratio):
        return 0.5
    return max(0.0, min(1.0, ratio))


def preview_crosshair_geometry(
    source_size: QtCore.QSizeF | QtCore.QSize,
    target_rect: QtCore.QRectF,
    crosshair_x: object = 0.5,
    crosshair_y: object = 0.5,
) -> tuple[QtCore.QRectF, QtCore.QPointF]:
    target = QtCore.QRectF(target_rect)
    source_width = float(source_size.width())
    source_height = float(source_size.height())
    if (
        source_width <= 0.0
        or source_height <= 0.0
        or target.width() <= 0.0
        or target.height() <= 0.0
    ):
        return target, target.center()
    scale = min(target.width() / source_width, target.height() / source_height)
    drawn = QtCore.QRectF(
        0.0,
        0.0,
        source_width * scale,
        source_height * scale,
    )
    drawn.moveCenter(target.center())
    point = QtCore.QPointF(
        drawn.left() + drawn.width() * _normalized_crosshair_ratio(crosshair_x),
        drawn.top() + drawn.height() * _normalized_crosshair_ratio(crosshair_y),
    )
    return drawn, point


def ellipse_safe_preview_rect(ellipse_bounds: QtCore.QRectF) -> QtCore.QRectF:
    bounds = QtCore.QRectF(ellipse_bounds)
    if bounds.width() <= 0.0 or bounds.height() <= 0.0:
        return bounds
    side = min(bounds.width(), bounds.height()) / math.sqrt(2.0)
    safe = QtCore.QRectF(0.0, 0.0, side, side)
    safe.moveCenter(bounds.center())
    return safe


def preview_raster_target_size(target_rect: QtCore.QRectF) -> QtCore.QSize:
    rect = QtCore.QRectF(target_rect)
    return QtCore.QSize(
        max(1, int(math.floor(rect.width()))),
        max(1, int(math.floor(rect.height()))),
    )


def _rect_overlap_area(first: QtCore.QRect, second: QtCore.QRect) -> int:
    intersection = QtCore.QRect(first).intersected(QtCore.QRect(second))
    if intersection.isEmpty():
        return 0
    return max(0, intersection.width()) * max(0, intersection.height())


def _circle_intrusion(first: QtCore.QRect, second: QtCore.QRect, *, gap: float = 8.0) -> int:
    first_center = QtCore.QPointF(first.center())
    second_center = QtCore.QPointF(second.center())
    distance = QtCore.QLineF(first_center, second_center).length()
    required = min(first.width(), first.height()) * 0.5 + min(second.width(), second.height()) * 0.5 + gap
    return max(0, int(math.ceil((required - distance) * 100.0)))


def _clamp_rect_to_screen(rect: QtCore.QRect, screen_rect: QtCore.QRect) -> QtCore.QRect:
    candidate = QtCore.QRect(rect)
    available = QtCore.QRect(screen_rect)
    if available.isEmpty():
        return candidate
    maximum_x = available.left() + max(0, available.width() - candidate.width())
    maximum_y = available.top() + max(0, available.height() - candidate.height())
    candidate.moveLeft(max(available.left(), min(candidate.left(), maximum_x)))
    candidate.moveTop(max(available.top(), min(candidate.top(), maximum_y)))
    return candidate


def floating_preview_lens_rect(
    menu_rect: QtCore.QRect,
    source_rect: QtCore.QRect,
    avoid_rects: Sequence[QtCore.QRect],
    screen_rect: QtCore.QRect,
    *,
    diameter: int = FLOATING_PREVIEW_LENS_SIZE,
) -> QtCore.QRect:
    """Place an enlarged target preview beside its radial source control."""

    menu_bounds = QtCore.QRect(menu_rect)
    source_bounds = QtCore.QRect(source_rect)
    available = QtCore.QRect(screen_rect)
    side = max(1, int(diameter))
    source_center = QtCore.QPointF(source_bounds.center())
    menu_center = QtCore.QPointF(menu_bounds.center())
    offset_x = source_center.x() - menu_center.x()
    offset_y = source_center.y() - menu_center.y()
    length = math.hypot(offset_x, offset_y)
    if length <= 0.001:
        outward = QtCore.QPointF(1.0, 0.0)
    else:
        outward = QtCore.QPointF(offset_x / length, offset_y / length)
    base_angle = math.atan2(outward.y(), outward.x())
    angular_offsets = [0.0]
    for step in range(1, 8):
        offset = step * math.pi / 8.0
        angular_offsets.extend((offset, -offset))
    angular_offsets.append(math.pi)
    directions = tuple(
        QtCore.QPointF(math.cos(base_angle + offset), math.sin(base_angle + offset))
        for offset in angular_offsets
    )
    minimum_distance = (
        max(source_bounds.width(), source_bounds.height()) * 0.5
        + side * 0.5
        + FLOATING_PREVIEW_LENS_GAP
    )
    distances = (
        minimum_distance,
        minimum_distance + side * 0.5,
        minimum_distance + side,
    )
    protected = tuple(QtCore.QRect(item) for item in avoid_rects if QtCore.QRect(item) != source_bounds)
    ranked: list[tuple[tuple[int, int, int, int, int, int], QtCore.QRect]] = []
    for distance_index, distance in enumerate(distances):
        for direction_index, direction in enumerate(directions):
            center = QtCore.QPointF(
                source_center.x() + direction.x() * distance,
                source_center.y() + direction.y() * distance,
            )
            desired = QtCore.QRect(
                int(round(center.x() - side * 0.5)),
                int(round(center.y() - side * 0.5)),
                side,
                side,
            )
            placed = _clamp_rect_to_screen(desired, available)
            source_overlap = _circle_intrusion(placed, source_bounds)
            avoid_overlap = sum(_circle_intrusion(placed, item) for item in protected)
            menu_overlap = _rect_overlap_area(placed, menu_bounds)
            clamp_shift = abs(placed.left() - desired.left()) + abs(placed.top() - desired.top())
            ranked.append(
                (
                    (
                        source_overlap,
                        avoid_overlap,
                        menu_overlap,
                        clamp_shift,
                        distance_index,
                        direction_index,
                    ),
                    placed,
                )
            )
    return min(ranked, key=lambda item: item[0])[1]

class _RadialBridge(QtCore.QObject):
    changed = QtCore.Signal()
    activated = QtCore.Signal(str)
    cancel_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items_value: list[dict[str, object]] = []
        self.title_value = ""
        self.center_label_value = "Close"
        self.center_id_value = "__cancel__"
        self.candidate_value = ""
        self.progress_value = 0.0
        self.focus_beam_value = True
        self.theme_value: dict[str, str] = {}

    @QtCore.Property("QVariantList", notify=changed)
    def items(self):
        return [dict(item) for item in self.items_value]

    @QtCore.Property(str, notify=changed)
    def title(self) -> str:
        return self.title_value

    @QtCore.Property(str, notify=changed)
    def centerLabel(self) -> str:
        return self.center_label_value

    @QtCore.Property(str, notify=changed)
    def centerId(self) -> str:
        return self.center_id_value

    @QtCore.Property(str, notify=changed)
    def candidateId(self) -> str:
        return self.candidate_value

    @QtCore.Property(float, notify=changed)
    def progress(self) -> float:
        return self.progress_value

    @QtCore.Property(bool, notify=changed)
    def focusBeamEnabled(self) -> bool:
        return self.focus_beam_value

    @QtCore.Property("QVariantMap", notify=changed)
    def theme(self):
        return dict(self.theme_value)

    @QtCore.Slot(str)
    def activate(self, action_id: str) -> None:
        self.activated.emit(str(action_id or ""))

    @QtCore.Slot()
    def cancel(self) -> None:
        self.cancel_requested.emit()


class _PreviewLensBridge(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item_value: dict[str, object] = {}
        self.progress_value = 0.0
        self.theme_value: dict[str, str] = {}

    @QtCore.Property("QVariantMap", notify=changed)
    def item(self):
        return dict(self.item_value)

    @QtCore.Property(float, notify=changed)
    def progress(self) -> float:
        return self.progress_value

    @QtCore.Property("QVariantMap", notify=changed)
    def theme(self):
        return dict(self.theme_value)


class _PreviewLensWindow(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.action_id = ""
        self._geometry = QtCore.QRect()
        self._bridge = _PreviewLensBridge(self)
        self._view = QtQuick.QQuickView()
        self._view.setTitle("Companion Orb gaze preview")
        self._view.setColor(QtGui.QColor(0, 0, 0, 0))
        self._view.setFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.WindowTransparentForInput
            | getattr(
                QtCore.Qt,
                "NoDropShadowWindowHint",
                QtCore.Qt.WindowType(0),
            )
        )
        self._view.setResizeMode(QtQuick.QQuickView.SizeRootObjectToView)
        self._view.rootContext().setContextProperty(
            "gazePreviewBridge",
            self._bridge,
        )
        source = Path(__file__).resolve().parent / "qml" / "GazePreviewLens.qml"
        self._view.setSource(QtCore.QUrl.fromLocalFile(str(source)))
        if self._view.status() == QtQuick.QQuickView.Error:
            errors = "; ".join(error.toString() for error in self._view.errors())
            raise RuntimeError(errors or "Gaze preview lens QML failed to load")

    def show_action(
        self,
        action: RadialAction,
        *,
        lens_rect: QtCore.QRect,
        theme: Mapping[str, QtGui.QColor],
    ) -> None:
        preview = bytes(action.preview_png or b"")
        if not preview:
            self.clear()
            return
        self.action_id = action.action_id
        self._geometry = QtCore.QRect(lens_rect)
        self._bridge.item_value = {
            "label": action.label,
            "previewSource": (
                "data:image/png;base64,"
                + base64.b64encode(preview).decode("ascii")
            ),
            "crosshairX": _normalized_crosshair_ratio(action.crosshair_x),
            "crosshairY": _normalized_crosshair_ratio(action.crosshair_y),
        }
        self._bridge.theme_value = {
            key: value.name(QtGui.QColor.HexArgb)
            for key, value in theme.items()
        }
        self._bridge.changed.emit()
        self._view.setGeometry(self._geometry)
        self._view.setOpacity(1.0)
        self._view.show()

    def set_progress(self, progress: float) -> None:
        self._bridge.progress_value = max(0.0, min(1.0, float(progress)))
        self._bridge.changed.emit()

    def retains_global_point(self, point: QtCore.QPointF) -> bool:
        if not self._view.isVisible() or self._geometry.isEmpty():
            return False
        center = QtCore.QPointF(self._geometry.center())
        radius = min(self._geometry.width(), self._geometry.height()) * 0.5
        return QtCore.QLineF(center, point).length() <= radius

    def clear(self) -> None:
        self.action_id = ""
        self._geometry = QtCore.QRect()
        self._bridge.item_value = {}
        self._bridge.progress_value = 0.0
        self._bridge.changed.emit()
        self._view.hide()

    def isVisible(self) -> bool:
        return self._view.isVisible()

    def deleteLater(self) -> None:
        self.clear()
        self._view.close()
        self._view.deleteLater()
        super().deleteLater()


class GazeRadialMenu(QtCore.QObject):
    action_selected = QtCore.Signal(str)
    cancelled = QtCore.Signal()
    candidate_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selector = GazeSelectionPolicy()
        self._anchor = QtCore.QPoint()
        self._theme = self._normalize_theme({})
        self._menu_opacity = RADIAL_MENU_DEFAULT_OPACITY
        self._focus_beam_enabled = True
        self._page_title = ""
        self._center_action_id = "__cancel__"
        self._confirmation_lens = False
        self._enlarged_visual = False
        self._preview_lens_enabled = False
        self._confirmation_action_id = ""
        self._actions: dict[str, RadialAction] = {}
        self._layouts: dict[str, QtCore.QRect] = {}
        self._bridge = _RadialBridge(self)
        self._bridge.activated.connect(self._emit_action)
        self._bridge.cancel_requested.connect(self.cancel)
        self._view = QtQuick.QQuickView()
        self._view.setTitle("Companion Orb gaze menu")
        self._view.setColor(QtGui.QColor(0, 0, 0, 0))
        self._view.setFlags(
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | getattr(
                QtCore.Qt,
                "NoDropShadowWindowHint",
                QtCore.Qt.WindowType(0),
            )
        )
        self._view.setResizeMode(QtQuick.QQuickView.SizeRootObjectToView)
        self._view.rootContext().setContextProperty("gazeRadialBridge", self._bridge)
        source = Path(__file__).resolve().parent / "qml" / "GazeRadialMenu.qml"
        self._view.setSource(QtCore.QUrl.fromLocalFile(str(source)))
        if self._view.status() == QtQuick.QQuickView.Error:
            errors = "; ".join(error.toString() for error in self._view.errors())
            raise RuntimeError(errors or "Gaze radial menu QML failed to load")
        self._preview_lens = _PreviewLensWindow(self)

    @property
    def anchor(self) -> QtCore.QPoint:
        return QtCore.QPoint(self._anchor)

    @property
    def selection_candidate_id(self) -> str | None:
        return self._selector.candidate_id

    @property
    def selection_progress(self) -> float:
        return self._selector.progress

    @property
    def confirmation_action_id(self) -> str:
        return self._confirmation_action_id

    @property
    def menu_opacity(self) -> float:
        return self._menu_opacity

    @property
    def focus_beam_enabled(self) -> bool:
        return self._focus_beam_enabled

    def isVisible(self) -> bool:
        return self._view.isVisible()

    def hide(self) -> None:
        self._preview_lens.clear()
        self._view.hide()

    def deleteLater(self) -> None:
        self._preview_lens.deleteLater()
        self._view.close()
        self._view.deleteLater()
        super().deleteLater()

    def set_menu_opacity(self, opacity: object) -> None:
        self._menu_opacity = normalize_radial_menu_opacity(opacity)
        self._view.setOpacity(self._menu_opacity)

    def set_focus_beam_enabled(self, enabled: object) -> None:
        if isinstance(enabled, str):
            self._focus_beam_enabled = (
                enabled.strip().lower() not in {"0", "false", "no", "off", ""}
            )
        else:
            self._focus_beam_enabled = bool(enabled)
        self._bridge.focus_beam_value = self._focus_beam_enabled
        self._bridge.changed.emit()

    @staticmethod
    def _normalize_theme(theme: Mapping[str, object]) -> dict[str, QtGui.QColor]:
        return {
            "background": _normalized_color(theme.get("background"), "#07111f"),
            "surface": _normalized_color(theme.get("surface"), "#101b2b"),
            "text": _normalized_color(theme.get("text"), "#eef7ff"),
            "muted": _normalized_color(theme.get("muted"), "#91a4b8"),
            "primary": _normalized_color(theme.get("primary"), "#38bdf8"),
            "secondary": _normalized_color(theme.get("secondary"), "#22d3ee"),
            "accent": _normalized_color(theme.get("accent"), "#a78bfa"),
            "glow": _normalized_color(theme.get("glow"), "#67e8f9"),
            "timer": _normalized_color(theme.get("timer"), "#facc15"),
        }

    def show_actions(
        self,
        actions: Sequence[RadialAction],
        *,
        anchor: QtCore.QPoint,
        dwell_ms: int,
        theme: Mapping[str, object] | None = None,
        opacity: object = RADIAL_MENU_DEFAULT_OPACITY,
        focus_beam_enabled: object = True,
        title: str = "",
        center_label: str = "Close",
        center_action_id: str = "__cancel__",
        confirmation_lens: bool = False,
        enlarged_visual: bool = False,
    ) -> None:
        normalized_actions = tuple(
            action for action in actions if str(action.action_id or "").strip()
        )
        if self._selector.candidate_id:
            self._confirmation_action_id = ""
            self.candidate_changed.emit("")
        self._selector = GazeSelectionPolicy(
            dwell_ms=dwell_ms,
            sample_gap_seconds=0.5,
        )
        self._theme = self._normalize_theme(dict(theme or {}))
        self.set_menu_opacity(opacity)
        self._page_title = str(title or "").strip()
        self._center_action_id = (
            str(center_action_id or "__cancel__").strip() or "__cancel__"
        )
        self._confirmation_lens = bool(confirmation_lens)
        self._enlarged_visual = bool(enlarged_visual)
        self._preview_lens_enabled = bool(
            self._confirmation_lens
            or self._enlarged_visual
            or any(bytes(action.preview_png or b"") for action in normalized_actions)
        )
        self._confirmation_action_id = ""
        self._anchor = QtCore.QPoint(anchor)
        self._actions = {
            action.action_id: action for action in normalized_actions
        }
        center = QtCore.QPointF(RADIAL_MENU_SIZE * 0.5, RADIAL_MENU_SIZE * 0.5)
        layouts = self._action_layouts(normalized_actions, center)
        self._layouts = {
            action.action_id: QtCore.QRect(
                int(round(position.x() - button_size * 0.5)),
                int(round(position.y() - button_size * 0.5)),
                button_size,
                button_size,
            )
            for action, button_size, position, _visual in layouts
        }
        self._layouts[self._center_action_id] = QtCore.QRect(
            int(round(center.x() - 46)),
            int(round(center.y() - 46)),
            92,
            92,
        )
        self._bridge.items_value = [
            self._qml_item(action, self._layouts[action.action_id], visual)
            for action, _button_size, _position, visual in layouts
        ]
        self._bridge.title_value = self._page_title
        self._bridge.center_label_value = str(center_label or "Close")
        self._bridge.center_id_value = self._center_action_id
        self._bridge.candidate_value = ""
        self._bridge.progress_value = 0.0
        self._bridge.focus_beam_value = self._focus_beam_enabled
        self._bridge.theme_value = {
            key: value.name(QtGui.QColor.HexArgb)
            for key, value in self._theme.items()
        }
        self._bridge.changed.emit()
        self._preview_lens.clear()
        self.set_focus_beam_enabled(focus_beam_enabled)
        self._move_around_anchor(self._anchor)
        self._view.show()

    def _qml_item(
        self,
        action: RadialAction,
        rect: QtCore.QRect,
        visual_inspection: bool,
    ) -> dict[str, object]:
        preview = bytes(action.preview_png or b"")
        preview_source = (
            "data:image/png;base64," + base64.b64encode(preview).decode("ascii")
            if preview
            else ""
        )
        return {
            "id": action.action_id,
            "label": action.label,
            "enabled": action.enabled,
            "checked": action.checked,
            "tooltip": action.tooltip,
            "role": action.role,
            "x": rect.x(),
            "y": rect.y(),
            "width": rect.width(),
            "height": rect.height(),
            "previewSource": preview_source,
            "crosshairX": _normalized_crosshair_ratio(action.crosshair_x),
            "crosshairY": _normalized_crosshair_ratio(action.crosshair_y),
            "visualInspection": bool(visual_inspection),
        }

    def _action_layouts(
        self,
        actions: Sequence[RadialAction],
        center: QtCore.QPointF,
    ) -> tuple[tuple[RadialAction, int, QtCore.QPointF, bool], ...]:
        if not self._enlarged_visual:
            radius = radial_layout_radius(len(actions))
            return tuple(
                (
                    action,
                    RADIAL_BUTTON_SIZE,
                    QtCore.QPointF(
                        center.x()
                        + math.cos(
                            -math.pi * 0.5
                            + math.tau * index / max(1, len(actions))
                        )
                        * radius,
                        center.y()
                        + math.sin(
                            -math.pi * 0.5
                            + math.tau * index / max(1, len(actions))
                        )
                        * radius,
                    ),
                    False,
                )
                for index, action in enumerate(actions)
            )
        visual_actions = tuple(
            action for action in actions if bytes(action.preview_png or b"")
        )[:VISUAL_PREVIEW_LIMIT]
        visual_ids = {action.action_id for action in visual_actions}
        utility_actions = tuple(
            action for action in actions if action.action_id not in visual_ids
        )
        layouts: list[tuple[RadialAction, int, QtCore.QPointF, bool]] = []
        for index, action in enumerate(visual_actions):
            angle = -math.pi * 0.25 + math.tau * index / max(1, len(visual_actions))
            layouts.append(
                (
                    action,
                    VISUAL_PREVIEW_BUTTON_SIZE,
                    QtCore.QPointF(
                        center.x() + math.cos(angle) * 220.0,
                        center.y() + math.sin(angle) * 220.0,
                    ),
                    True,
                )
            )
        utility_angles = (-math.pi * 0.5, 0.0, math.pi * 0.5, math.pi)
        for index, action in enumerate(utility_actions):
            angle = utility_angles[index % len(utility_angles)]
            ring = 250.0 + 42.0 * (index // len(utility_angles))
            layouts.append(
                (
                    action,
                    VISUAL_UTILITY_BUTTON_SIZE,
                    QtCore.QPointF(
                        center.x() + math.cos(angle) * ring,
                        center.y() + math.sin(angle) * ring,
                    ),
                    False,
                )
            )
        return tuple(layouts)

    def _move_around_anchor(self, anchor: QtCore.QPoint) -> None:
        top_left = QtCore.QPoint(
            int(round(anchor.x() - RADIAL_MENU_SIZE * 0.5)),
            int(round(anchor.y() - RADIAL_MENU_SIZE * 0.5)),
        )
        screen = (
            QtGui.QGuiApplication.screenAt(anchor)
            or QtGui.QGuiApplication.primaryScreen()
        )
        if screen is not None:
            available = screen.availableGeometry()
            top_left.setX(
                max(
                    available.left(),
                    min(top_left.x(), available.right() - RADIAL_MENU_SIZE + 1),
                )
            )
            top_left.setY(
                max(
                    available.top(),
                    min(top_left.y(), available.bottom() - RADIAL_MENU_SIZE + 1),
                )
            )
        self._view.setGeometry(
            QtCore.QRect(
                top_left,
                QtCore.QSize(RADIAL_MENU_SIZE, RADIAL_MENU_SIZE),
            )
        )

    def feed_gaze(
        self,
        global_point: QtCore.QPointF | QtCore.QPoint,
        *,
        now: float | None = None,
    ) -> str | None:
        if not self.isVisible():
            return None
        action_id = self._action_at_global_point(QtCore.QPointF(global_point))
        previous = self._selector.candidate_id
        progress, selected = self._selector.ingest(
            action_id,
            now=time.monotonic() if now is None else float(now),
        )
        candidate_id = self._selector.candidate_id
        current = candidate_id or ""
        if current != (previous or ""):
            self._confirmation_action_id = (
                current if self._confirmation_lens else ""
            )
            self.candidate_changed.emit(current)
        self._bridge.candidate_value = current
        self._bridge.progress_value = progress
        self._bridge.changed.emit()
        self._sync_preview_lens(candidate_id, progress)
        if selected == "__cancel__":
            self.cancel()
            return selected
        if selected:
            self.action_selected.emit(selected)
        return selected

    def reset_gaze_selection(self) -> None:
        previous = self._selector.candidate_id
        self._selector.reset()
        self._confirmation_action_id = ""
        self._preview_lens.clear()
        self._bridge.candidate_value = ""
        self._bridge.progress_value = 0.0
        self._bridge.changed.emit()
        if previous:
            self.candidate_changed.emit("")

    def _action_at_global_point(self, point: QtCore.QPointF) -> str | None:
        local = point - QtCore.QPointF(self._view.position())
        action_id = radial_hit_test(
            (local.x(), local.y()),
            self._radial_hit_targets(),
            candidate_id=self._selector.candidate_id,
        )
        if action_id:
            return action_id
        candidate = str(self._selector.candidate_id or "").strip()
        if (
            candidate
            and candidate == self._preview_lens.action_id
            and self._preview_lens.retains_global_point(point)
        ):
            return candidate
        return None

    def _sync_preview_lens(
        self,
        candidate_id: str | None,
        progress: float,
    ) -> None:
        normalized = str(candidate_id or "").strip()
        action = self._actions.get(normalized)
        source_rect = self._layouts.get(normalized)
        if (
            not self._preview_lens_enabled
            or action is None
            or source_rect is None
            or not action.enabled
            or not bytes(action.preview_png or b"")
        ):
            self._preview_lens.clear()
            return
        menu_rect = self._view.geometry()
        global_source = QtCore.QRect(
            source_rect.translated(self._view.position())
        )
        avoid_rects = tuple(
            QtCore.QRect(rect.translated(self._view.position()))
            for rect in self._layouts.values()
        )
        screen = (
            QtGui.QGuiApplication.screenAt(global_source.center())
            or QtGui.QGuiApplication.primaryScreen()
        )
        screen_rect = (
            screen.availableGeometry()
            if screen is not None
            else menu_rect
        )
        lens_rect = floating_preview_lens_rect(
            menu_rect,
            global_source,
            avoid_rects,
            screen_rect,
        )
        if (
            self._preview_lens.action_id != normalized
            or not self._preview_lens.isVisible()
        ):
            self._preview_lens.show_action(
                action,
                lens_rect=lens_rect,
                theme=self._theme,
            )
        self._preview_lens.set_progress(progress)

    def _mouse_action_at_global_point(self, point: QtCore.QPointF) -> str | None:
        local = point - QtCore.QPointF(self._view.position())
        local_point = local.toPoint()
        for action_id, rect in self._layouts.items():
            action = self._actions.get(action_id)
            enabled = action.enabled if action is not None else True
            if enabled and rect.contains(local_point):
                return action_id
        return None

    def _is_over_button_global_point(self, point: QtCore.QPointF) -> bool:
        local = (point - QtCore.QPointF(self._view.position())).toPoint()
        return any(rect.contains(local) for rect in self._layouts.values())

    def _radial_hit_targets(self) -> tuple[RadialHitTarget, ...]:
        targets: list[RadialHitTarget] = []
        for action_id, rect in self._layouts.items():
            action = self._actions.get(action_id)
            targets.append(
                RadialHitTarget(
                    action_id=action_id,
                    center_x=float(rect.center().x()),
                    center_y=float(rect.center().y()),
                    diameter=float(min(rect.width(), rect.height())),
                    enabled=action.enabled if action is not None else True,
                )
            )
        return tuple(targets)

    @QtCore.Slot(str)
    def _emit_action(self, action_id: str) -> None:
        normalized = str(action_id or "").strip()
        if not normalized:
            return
        if normalized == self._center_action_id and normalized == "__cancel__":
            self.cancel()
            return
        action = self._actions.get(normalized)
        if action is not None and not action.enabled:
            return
        self.reset_gaze_selection()
        self.action_selected.emit(normalized)

    @QtCore.Slot()
    def cancel(self) -> None:
        was_visible = self.isVisible()
        self.hide()
        self.reset_gaze_selection()
        if was_visible:
            self.cancelled.emit()
