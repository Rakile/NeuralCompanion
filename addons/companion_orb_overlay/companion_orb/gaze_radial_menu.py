from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Mapping, Sequence

from PySide6 import QtCore, QtGui, QtWidgets


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


class _RadialButton(QtWidgets.QPushButton):
    def __init__(self, action: RadialAction, parent=None):
        super().__init__(parent)
        self.action = action
        self._gaze_progress = 0.0
        self._theme: dict[str, QtGui.QColor] = {}
        self._preview = QtGui.QPixmap()
        self._visual_inspection = False
        self._preview_lens_mode = False
        preview_data = bytes(action.preview_png or b"")
        if preview_data:
            self._preview.loadFromData(QtCore.QByteArray(preview_data), "PNG")
        self.setCursor(QtCore.Qt.PointingHandCursor if action.enabled else QtCore.Qt.ArrowCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setFlat(True)
        self.setEnabled(bool(action.enabled))
        self.setAccessibleName(str(action.label or "").replace("\n", " "))
        if action.tooltip:
            self.setToolTip(action.tooltip)

    def set_theme(self, theme: Mapping[str, QtGui.QColor]) -> None:
        self._theme = dict(theme)
        self.update()

    def set_gaze_progress(self, progress: float) -> None:
        value = max(0.0, min(1.0, float(progress)))
        if abs(value - self._gaze_progress) < 0.002:
            return
        self._gaze_progress = value
        self.update()

    def set_visual_inspection(self, enabled: bool) -> None:
        self._visual_inspection = bool(enabled)
        self.update()

    def set_preview_lens_mode(self, enabled: bool) -> None:
        self._preview_lens_mode = bool(enabled)
        self.update()

    def label_content_bounds(self, bounds: QtCore.QRectF) -> QtCore.QRectF:
        area = QtCore.QRectF(bounds)
        if self._preview.isNull():
            return area.adjusted(12.0, 10.0, -12.0, -10.0)
        height = 46.0 if self._preview_lens_mode else max(26.0, min(38.0, area.height() * 0.34))
        return QtCore.QRectF(
            area.left() + 12.0,
            area.top() + 9.0,
            max(1.0, area.width() - 24.0),
            height,
        )

    def preview_content_bounds(self, bounds: QtCore.QRectF) -> QtCore.QRectF:
        area = QtCore.QRectF(bounds)
        if not self._preview_lens_mode:
            return area.adjusted(7.0, 7.0, -7.0, -7.0)
        label_bounds = self.label_content_bounds(area)
        top = label_bounds.bottom() + 4.0
        return QtCore.QRectF(
            area.left() + 10.0,
            top,
            max(1.0, area.width() - 20.0),
            max(1.0, area.bottom() - top - 8.0),
        )

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        bounds = QtCore.QRectF(self.rect()).adjusted(7.0, 7.0, -7.0, -7.0)
        surface = self._theme.get("surface", QtGui.QColor("#101b2b"))
        primary = self._theme.get("primary", QtGui.QColor("#38bdf8"))
        secondary = self._theme.get("secondary", QtGui.QColor("#22d3ee"))
        accent = self._theme.get("accent", QtGui.QColor("#a78bfa"))
        glow = self._theme.get("glow", QtGui.QColor("#67e8f9"))
        timer = self._theme.get("timer", QtGui.QColor("#facc15"))
        text = self._theme.get("text", QtGui.QColor("#eef7ff"))
        muted = self._theme.get("muted", QtGui.QColor("#91a4b8"))

        active_mix = 0.0 if self._preview_lens_mode else max(
            self._gaze_progress,
            0.18 if self.underMouse() else 0.0,
        )
        fill = _blend(surface, primary, active_mix * 0.42)
        if self.action.checked:
            fill = _blend(fill, secondary, 0.34)
        if not self.isEnabled():
            fill = _blend(surface, muted, 0.12)

        if self._gaze_progress > 0.0 and self.isEnabled() and not self._preview_lens_mode:
            glow_mix = _blend(timer, glow, 0.35)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(_with_alpha(glow_mix, int(34 + 72 * self._gaze_progress)))
            painter.drawEllipse(bounds.adjusted(-6.0, -6.0, 6.0, 6.0))
            painter.setBrush(_with_alpha(timer, int(24 + 54 * self._gaze_progress)))
            painter.drawEllipse(bounds.adjusted(-3.0, -3.0, 3.0, 3.0))

        glass_focus = QtCore.QPointF(
            bounds.left() + bounds.width() * 0.36,
            bounds.top() + bounds.height() * 0.24,
        )
        glass = QtGui.QRadialGradient(glass_focus, bounds.width() * 0.88, glass_focus)
        glass.setColorAt(0.0, _with_alpha(_blend(fill, text, 0.16), 246 if self.isEnabled() else 166))
        glass.setColorAt(0.42, _with_alpha(fill, 232 if self.isEnabled() else 150))
        glass.setColorAt(
            1.0,
            _with_alpha(
                _blend(fill, QtGui.QColor("#000000"), 0.34),
                238 if self.isEnabled() else 142,
            ),
        )
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(glass)
        painter.drawEllipse(bounds)

        if not self._preview.isNull():
            preview_bounds = self.preview_content_bounds(bounds)
            preview_fit_bounds = (
                preview_bounds
                if self._preview_lens_mode
                else ellipse_safe_preview_rect(preview_bounds)
            )
            scaled = self._preview.scaled(
                preview_raster_target_size(preview_fit_bounds),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            preview_draw_rect = QtCore.QRectF(QtCore.QPointF(), QtCore.QSizeF(scaled.size()))
            preview_draw_rect.moveCenter(preview_fit_bounds.center())
            preview_clip = QtGui.QPainterPath()
            preview_clip.addEllipse(bounds if self._preview_lens_mode else preview_bounds)
            painter.save()
            painter.setClipPath(preview_clip)
            painter.setOpacity(
                1.0
                if self._preview_lens_mode
                else (0.72 if self.isEnabled() else 0.38)
            )
            painter.drawPixmap(
                preview_draw_rect,
                scaled,
                QtCore.QRectF(scaled.rect()),
            )
            painter.setOpacity(1.0)
            if not self._preview_lens_mode:
                painter.fillRect(preview_bounds, QtGui.QColor(3, 10, 18, 92))
            painter.restore()

        if self._gaze_progress > 0.0 and self.isEnabled() and not self._preview_lens_mode:
            fill_path = QtGui.QPainterPath()
            fill_path.addEllipse(bounds)
            fill_height = bounds.height() * self._gaze_progress
            fill_rect = QtCore.QRectF(
                bounds.left(),
                bounds.bottom() - fill_height,
                bounds.width(),
                fill_height + 1.0,
            )
            gradient = QtGui.QLinearGradient(fill_rect.topLeft(), fill_rect.bottomLeft())
            gradient.setColorAt(0.0, _with_alpha(_blend(timer, glow, 0.45), 225))
            gradient.setColorAt(0.24, _with_alpha(timer, 178))
            gradient.setColorAt(1.0, _with_alpha(_blend(timer, primary, 0.45), 100))
            painter.save()
            painter.setClipPath(fill_path)
            painter.fillRect(fill_rect, gradient)
            fill_edge_y = fill_rect.top() + 1.0
            painter.setPen(
                QtGui.QPen(
                    _with_alpha(glow, int(74 + 112 * self._gaze_progress)),
                    8.0,
                    QtCore.Qt.SolidLine,
                    QtCore.Qt.RoundCap,
                )
            )
            painter.drawLine(
                QtCore.QPointF(bounds.left() + 8.0, fill_edge_y),
                QtCore.QPointF(bounds.right() - 8.0, fill_edge_y),
            )
            painter.setPen(
                QtGui.QPen(
                    _with_alpha(timer, 245),
                    2.0,
                    QtCore.Qt.SolidLine,
                    QtCore.Qt.RoundCap,
                )
            )
            painter.drawLine(
                QtCore.QPointF(bounds.left() + 10.0, fill_edge_y),
                QtCore.QPointF(bounds.right() - 10.0, fill_edge_y),
            )
            painter.restore()

        border_color = accent if self.action.checked else primary
        if self._gaze_progress > 0.0 and not self._preview_lens_mode:
            border_color = _blend(border_color, timer, self._gaze_progress)
        if not self.isEnabled():
            border_color = _blend(muted, surface, 0.28)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(
            QtGui.QPen(
                _with_alpha(border_color, 235 if self.isEnabled() else 145),
                2.0,
                QtCore.Qt.SolidLine if self.isEnabled() else QtCore.Qt.DashLine,
                QtCore.Qt.RoundCap,
            )
        )
        painter.drawEllipse(bounds)

        highlight_bounds = bounds.adjusted(8.0, 8.0, -8.0, -8.0)
        painter.setPen(
            QtGui.QPen(
                _with_alpha(text if self.isEnabled() else muted, 72 if self.isEnabled() else 34),
                1.2,
                QtCore.Qt.SolidLine,
                QtCore.Qt.RoundCap,
            )
        )
        painter.drawArc(highlight_bounds, 34 * 16, 112 * 16)

        if self._gaze_progress > 0.0:
            progress_bounds = bounds.adjusted(-2.0, -2.0, 2.0, 2.0)
            painter.setPen(
                QtGui.QPen(
                    _with_alpha(timer, 255),
                    4.0,
                    QtCore.Qt.SolidLine,
                    QtCore.Qt.RoundCap,
                )
            )
            painter.drawArc(
                progress_bounds,
                90 * 16,
                -int(round(360.0 * 16.0 * self._gaze_progress)),
            )

        center_action = self.action.action_id in {"__cancel__", "back"}
        label = str(self.action.label or "")
        if self.action.role and not center_action:
            label = f"{self.action.role}\n{label}"
        text_bounds = self.label_content_bounds(bounds)
        if center_action:
            icon_y = bounds.center().y() - 12.0
            painter.setPen(
                QtGui.QPen(
                    _with_alpha(text, 225),
                    2.0,
                    QtCore.Qt.SolidLine,
                    QtCore.Qt.RoundCap,
                )
            )
            if self.action.action_id == "__cancel__":
                painter.drawLine(
                    QtCore.QPointF(bounds.center().x() - 6.0, icon_y - 6.0),
                    QtCore.QPointF(bounds.center().x() + 6.0, icon_y + 6.0),
                )
                painter.drawLine(
                    QtCore.QPointF(bounds.center().x() + 6.0, icon_y - 6.0),
                    QtCore.QPointF(bounds.center().x() - 6.0, icon_y + 6.0),
                )
            else:
                painter.drawLine(
                    QtCore.QPointF(bounds.center().x() + 5.0, icon_y - 6.0),
                    QtCore.QPointF(bounds.center().x() - 3.0, icon_y),
                )
                painter.drawLine(
                    QtCore.QPointF(bounds.center().x() - 3.0, icon_y),
                    QtCore.QPointF(bounds.center().x() + 5.0, icon_y + 6.0),
                )
            text_bounds.setTop(bounds.center().y() + 2.0)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont)
        font.setBold(True)
        text_flags = QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap
        if not self._preview.isNull() and not center_action:
            text_flags = QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap
        target_rect = text_bounds.toAlignedRect()
        starting_pixel_size = 11 if center_action else (14 if self._preview_lens_mode else 12)
        for pixel_size in range(starting_pixel_size, 6, -1):
            font.setPixelSize(pixel_size)
            measured = QtGui.QFontMetrics(font).boundingRect(target_rect, int(text_flags), label)
            if measured.width() <= target_rect.width() and measured.height() <= target_rect.height():
                break
        painter.setFont(font)
        if not self._preview.isNull():
            shadow = QtGui.QColor(0, 0, 0, 210)
            painter.setPen(shadow)
            for offset in (
                QtCore.QPointF(-1.0, 0.0),
                QtCore.QPointF(1.0, 0.0),
                QtCore.QPointF(0.0, -1.0),
                QtCore.QPointF(0.0, 1.0),
            ):
                painter.drawText(text_bounds.translated(offset), text_flags, label)
        painter.setPen(text if self.isEnabled() else muted)
        painter.drawText(
            text_bounds,
            text_flags,
            label,
        )

        if self._visual_inspection and not self._preview.isNull():
            preview_bounds = self.preview_content_bounds(bounds)
            preview_fit_bounds = (
                preview_bounds
                if self._preview_lens_mode
                else ellipse_safe_preview_rect(preview_bounds)
            )
            scaled = self._preview.scaled(
                preview_raster_target_size(preview_fit_bounds),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            preview_draw_rect = QtCore.QRectF(QtCore.QPointF(), QtCore.QSizeF(scaled.size()))
            preview_draw_rect.moveCenter(preview_fit_bounds.center())
            _drawn, crosshair_center = preview_crosshair_geometry(
                scaled.size(),
                preview_draw_rect,
                self.action.crosshair_x,
                self.action.crosshair_y,
            )
            crosshair_color = _with_alpha(text, 235)
            painter.setPen(QtGui.QPen(crosshair_color, 1.6, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
            painter.drawLine(
                QtCore.QPointF(crosshair_center.x() - 11.0, crosshair_center.y()),
                QtCore.QPointF(crosshair_center.x() + 11.0, crosshair_center.y()),
            )
            painter.drawLine(
                QtCore.QPointF(crosshair_center.x(), crosshair_center.y() - 11.0),
                QtCore.QPointF(crosshair_center.x(), crosshair_center.y() + 11.0),
            )
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(crosshair_center, 5.0, 5.0)


class _FloatingPreviewLens(QtWidgets.QWidget):
    def __init__(self, parent=None):
        flags = (
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | getattr(QtCore.Qt, "WindowTransparentForInput", QtCore.Qt.WindowType(0))
            | getattr(QtCore.Qt, "NoDropShadowWindowHint", QtCore.Qt.WindowType(0))
        )
        super().__init__(parent, flags)
        self.setObjectName("companion_orb_gaze_preview_lens")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setAccessibleName("Gaze target preview")
        self._button: _RadialButton | None = None
        self._action_id = ""
        self._source_center = QtCore.QPointF()
        self._lens_center = QtCore.QPointF()
        self._theme: dict[str, QtGui.QColor] = {}

    @property
    def action_id(self) -> str:
        return self._action_id

    def show_action(
        self,
        action: RadialAction,
        *,
        source_rect: QtCore.QRect,
        lens_rect: QtCore.QRect,
        theme: Mapping[str, QtGui.QColor],
    ) -> None:
        self.clear()
        source_bounds = QtCore.QRect(source_rect)
        lens_bounds = QtCore.QRect(lens_rect)
        window_bounds = source_bounds.united(lens_bounds).adjusted(
            -FLOATING_PREVIEW_LENS_MARGIN,
            -FLOATING_PREVIEW_LENS_MARGIN,
            FLOATING_PREVIEW_LENS_MARGIN,
            FLOATING_PREVIEW_LENS_MARGIN,
        )
        self.setGeometry(window_bounds)
        self._action_id = str(action.action_id or "")
        self._theme = dict(theme)
        self._source_center = QtCore.QPointF(source_bounds.center() - window_bounds.topLeft())
        self._lens_center = QtCore.QPointF(lens_bounds.center() - window_bounds.topLeft())
        button = _RadialButton(action, self)
        button.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        button.setFixedSize(lens_bounds.size())
        button.set_theme(self._theme)
        button.set_visual_inspection(True)
        button.set_preview_lens_mode(True)
        button.move(lens_bounds.topLeft() - window_bounds.topLeft())
        button.show()
        self._button = button
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self.update()

    def set_progress(self, progress: float) -> None:
        if self._button is not None:
            self._button.set_gaze_progress(progress)
        self.update()

    def clear(self) -> None:
        button = self._button
        self._button = None
        self._action_id = ""
        if button is not None:
            button.hide()
            button.deleteLater()
        self.hide()

    def retains_global_point(self, point: QtCore.QPointF | QtCore.QPoint) -> bool:
        button = self._button
        if button is None or not self.isVisible() or not self._action_id:
            return False
        local = QtCore.QPointF(self.mapFromGlobal(QtCore.QPointF(point).toPoint()))
        lens_center = QtCore.QPointF(button.geometry().center())
        lens_radius = max(1.0, min(button.width(), button.height()) * 0.5)
        if QtCore.QLineF(local, lens_center).length() <= lens_radius:
            return True
        start = QtCore.QPointF(self._source_center)
        end = QtCore.QPointF(self._lens_center)
        segment_x = end.x() - start.x()
        segment_y = end.y() - start.y()
        segment_length_sq = segment_x * segment_x + segment_y * segment_y
        if segment_length_sq <= 0.001:
            return False
        projection = (
            (local.x() - start.x()) * segment_x
            + (local.y() - start.y()) * segment_y
        ) / segment_length_sq
        if projection < 0.0 or projection > 1.0:
            return False
        nearest = QtCore.QPointF(
            start.x() + segment_x * projection,
            start.y() + segment_y * projection,
        )
        return QtCore.QLineF(local, nearest).length() <= FLOATING_PREVIEW_TRANSFER_RADIUS

    def paintEvent(self, _event) -> None:
        if self._button is None:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        line = QtCore.QLineF(self._source_center, self._lens_center)
        if line.length() <= 1.0:
            return
        source_offset = min(0.42, 48.0 / line.length())
        lens_offset = max(source_offset, (line.length() - FLOATING_PREVIEW_LENS_SIZE * 0.5 + 5.0) / line.length())
        connector = QtCore.QLineF(line.pointAt(source_offset), line.pointAt(lens_offset))
        glow = self._theme.get("glow", QtGui.QColor("#67e8f9"))
        primary = self._theme.get("primary", QtGui.QColor("#38bdf8"))
        timer = self._theme.get("timer", QtGui.QColor("#facc15"))
        progress = max(0.0, min(1.0, float(self._button._gaze_progress)))
        painter.setPen(
            QtGui.QPen(
                _with_alpha(glow, int(round(52 + 62 * progress))),
                7.0,
                QtCore.Qt.SolidLine,
                QtCore.Qt.RoundCap,
            )
        )
        painter.drawLine(connector)
        gradient = QtGui.QLinearGradient(connector.p1(), connector.p2())
        gradient.setColorAt(0.0, _with_alpha(primary, 190))
        gradient.setColorAt(1.0, _with_alpha(timer, int(round(205 + 50 * progress))))
        painter.setPen(
            QtGui.QPen(
                QtGui.QBrush(gradient),
                2.0 + 2.0 * progress,
                QtCore.Qt.SolidLine,
                QtCore.Qt.RoundCap,
            )
        )
        painter.drawLine(connector)


class GazeRadialMenu(QtWidgets.QWidget):
    action_selected = QtCore.Signal(str)
    cancelled = QtCore.Signal()
    candidate_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        flags = (
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | getattr(QtCore.Qt, "NoDropShadowWindowHint", QtCore.Qt.WindowType(0))
        )
        super().__init__(parent, flags)
        self.setObjectName("companion_orb_gaze_radial_menu")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setFixedSize(RADIAL_MENU_SIZE, RADIAL_MENU_SIZE)
        self._buttons: dict[str, _RadialButton] = {}
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
        self._cancel_button = _RadialButton(RadialAction("__cancel__", "Close"), self)
        self._cancel_button.setFixedSize(92, 92)
        self._cancel_button.clicked.connect(self._emit_center_action)
        self._cancel_button.set_theme(self._theme)
        self._preview_lens = _FloatingPreviewLens(self)

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

    def set_menu_opacity(self, opacity: object) -> None:
        value = normalize_radial_menu_opacity(opacity)
        self._menu_opacity = value
        self.setWindowOpacity(value)

    def set_focus_beam_enabled(self, enabled: object) -> None:
        if isinstance(enabled, str):
            value = enabled.strip().lower() not in {"0", "false", "no", "off", ""}
        else:
            value = bool(enabled)
        self._focus_beam_enabled = value
        self.update()

    def _normalize_theme(self, theme: Mapping[str, object]) -> dict[str, QtGui.QColor]:
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
        self._hide_preview_lens()
        normalized_actions = tuple(
            action for action in actions if str(action.action_id or "").strip()
        )
        if self._selector.candidate_id:
            self._confirmation_action_id = ""
            self.candidate_changed.emit("")
        self._selector = GazeSelectionPolicy(dwell_ms=dwell_ms, sample_gap_seconds=0.5)
        self._theme = self._normalize_theme(dict(theme or {}))
        self.set_menu_opacity(opacity)
        self.set_focus_beam_enabled(focus_beam_enabled)
        self._page_title = str(title or "").strip()
        self._center_action_id = str(center_action_id or "__cancel__").strip() or "__cancel__"
        self._confirmation_lens = bool(confirmation_lens)
        self._enlarged_visual = bool(enlarged_visual)
        self._preview_lens_enabled = bool(
            self._confirmation_lens
            or self._enlarged_visual
            or any(bytes(action.preview_png or b"") for action in normalized_actions)
        )
        self._confirmation_action_id = ""
        self._anchor = QtCore.QPoint(anchor)
        self._clear_action_buttons()
        center = QtCore.QPointF(self.width() * 0.5, self.height() * 0.5)
        for action, button_size, position, visual_inspection in self._action_layouts(
            normalized_actions,
            center,
        ):
            button = _RadialButton(action, self)
            button.setFixedSize(button_size, button_size)
            button.set_theme(self._theme)
            button.set_visual_inspection(visual_inspection)
            button.move(
                int(round(position.x() - button_size * 0.5)),
                int(round(position.y() - button_size * 0.5)),
            )
            button.clicked.connect(
                lambda _checked=False, action_id=action.action_id: self._emit_action(action_id)
            )
            button.show()
            self._buttons[action.action_id] = button

        self._cancel_button.action = RadialAction(self._center_action_id, str(center_label or "Close"))
        self._cancel_button.setAccessibleName(str(center_label or "Close"))
        self._cancel_button.set_theme(self._theme)
        self._cancel_button.move(
            int(round(center.x() - self._cancel_button.width() * 0.5)),
            int(round(center.y() - self._cancel_button.height() * 0.5)),
        )
        self._cancel_button.show()
        self._move_around_anchor(self._anchor)
        self.show()
        self.raise_()
        self.update()

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
                        center.x() + math.cos(-math.pi * 0.5 + math.tau * index / max(1, len(actions))) * radius,
                        center.y() + math.sin(-math.pi * 0.5 + math.tau * index / max(1, len(actions))) * radius,
                    ),
                    False,
                )
                for index, action in enumerate(actions)
            )

        visual_actions = tuple(
            action for action in actions if bytes(action.preview_png or b"")
        )[:VISUAL_PREVIEW_LIMIT]
        visual_ids = {action.action_id for action in visual_actions}
        utility_actions = tuple(action for action in actions if action.action_id not in visual_ids)
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

    def _clear_action_buttons(self) -> None:
        self._hide_preview_lens()
        for button in self._buttons.values():
            button.hide()
            button.deleteLater()
        self._buttons.clear()

    @staticmethod
    def _global_widget_rect(widget: QtWidgets.QWidget) -> QtCore.QRect:
        return QtCore.QRect(widget.mapToGlobal(QtCore.QPoint(0, 0)), widget.size())

    def _hide_preview_lens(self) -> None:
        self._preview_lens.clear()

    def _sync_preview_lens(self, candidate_id: str | None, progress: float) -> None:
        normalized = str(candidate_id or "").strip()
        button = self._buttons.get(normalized)
        if (
            not self._preview_lens_enabled
            or button is None
            or not button.isEnabled()
            or not bytes(button.action.preview_png or b"")
        ):
            self._hide_preview_lens()
            return
        if self._preview_lens.action_id != normalized or not self._preview_lens.isVisible():
            source_rect = self._global_widget_rect(button)
            menu_rect = self._global_widget_rect(self)
            avoid_rects = tuple(
                self._global_widget_rect(item)
                for item in (*self._buttons.values(), self._cancel_button)
                if item.isVisible()
            )
            app = QtWidgets.QApplication.instance()
            screen = app.screenAt(source_rect.center()) if app is not None else None
            if screen is None and app is not None:
                screen = app.primaryScreen()
            screen_rect = screen.availableGeometry() if screen is not None else menu_rect
            lens_rect = floating_preview_lens_rect(
                menu_rect,
                source_rect,
                avoid_rects,
                screen_rect,
            )
            self._preview_lens.show_action(
                button.action,
                source_rect=source_rect,
                lens_rect=lens_rect,
                theme=self._theme,
            )
        self._preview_lens.set_progress(progress)

    def _move_around_anchor(self, anchor: QtCore.QPoint) -> None:
        top_left = QtCore.QPoint(
            int(round(anchor.x() - self.width() * 0.5)),
            int(round(anchor.y() - self.height() * 0.5)),
        )
        app = QtWidgets.QApplication.instance()
        screen = app.screenAt(anchor) if app is not None else None
        if screen is None and app is not None:
            screen = app.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            top_left.setX(max(available.left(), min(top_left.x(), available.right() - self.width() + 1)))
            top_left.setY(max(available.top(), min(top_left.y(), available.bottom() - self.height() + 1)))
        self.move(top_left)

    def feed_gaze(self, global_point: QtCore.QPointF | QtCore.QPoint, *, now: float | None = None) -> str | None:
        if not self.isVisible():
            return None
        point = QtCore.QPointF(global_point)
        action_id = self._action_at_global_point(point)
        previous = self._selector.candidate_id
        sample_at = time.monotonic() if now is None else float(now)
        progress, selected = self._selector.ingest(
            action_id,
            now=sample_at,
        )
        candidate_id = self._selector.candidate_id
        current = candidate_id or ""
        if current != (previous or ""):
            self._confirmation_action_id = current if self._confirmation_lens else ""
            self.candidate_changed.emit(current)
        for button_id, button in self._buttons.items():
            button.set_gaze_progress(progress if button_id == candidate_id else 0.0)
        self._cancel_button.set_gaze_progress(progress if candidate_id == self._center_action_id else 0.0)
        self._sync_preview_lens(candidate_id, progress)
        self.update()
        if selected == "__cancel__":
            self.cancel()
            return selected
        if selected:
            self._hide_preview_lens()
            self.action_selected.emit(selected)
        return selected

    def reset_gaze_selection(self) -> None:
        previous = self._selector.candidate_id
        self._selector.reset()
        self._confirmation_action_id = ""
        self._hide_preview_lens()
        for button in self._buttons.values():
            button.set_gaze_progress(0.0)
        self._cancel_button.set_gaze_progress(0.0)
        if previous:
            self.candidate_changed.emit("")
        self.update()

    def _action_at_global_point(self, point: QtCore.QPointF) -> str | None:
        local = self.mapFromGlobal(point.toPoint())
        action_id = radial_hit_test(
            (float(local.x()), float(local.y())),
            self._radial_hit_targets(),
            candidate_id=self._selector.candidate_id,
        )
        if action_id:
            return action_id
        candidate_id = str(self._selector.candidate_id or "").strip()
        if (
            candidate_id
            and candidate_id == self._preview_lens.action_id
            and self._preview_lens.retains_global_point(point)
        ):
            return candidate_id
        return None

    def _mouse_action_at_global_point(self, point: QtCore.QPointF) -> str | None:
        local = self.mapFromGlobal(point.toPoint())
        for action_id, button in (*self._buttons.items(), (self._center_action_id, self._cancel_button)):
            if button.isEnabled() and button.geometry().contains(local):
                return action_id
        return None

    def _is_over_button_global_point(self, point: QtCore.QPointF) -> bool:
        local = self.mapFromGlobal(point.toPoint())
        return any(
            button.geometry().contains(local)
            for button in (*self._buttons.values(), self._cancel_button)
        )

    def _radial_hit_targets(self) -> tuple[RadialHitTarget, ...]:
        targets: list[RadialHitTarget] = []
        for action_id, button in (*self._buttons.items(), (self._center_action_id, self._cancel_button)):
            center = QtCore.QPointF(button.geometry().center())
            targets.append(
                RadialHitTarget(
                    action_id=action_id,
                    center_x=center.x(),
                    center_y=center.y(),
                    diameter=float(min(button.width(), button.height())),
                    enabled=button.isEnabled(),
                )
            )
        return tuple(targets)

    def _emit_action(self, action_id: str) -> None:
        normalized = str(action_id or "").strip()
        if normalized:
            self.reset_gaze_selection()
            self.action_selected.emit(normalized)

    def _emit_center_action(self) -> None:
        if self._center_action_id == "__cancel__":
            self.cancel()
            return
        self._emit_action(self._center_action_id)

    @QtCore.Slot()
    def cancel(self) -> None:
        was_visible = self.isVisible()
        self.hide()
        self.reset_gaze_selection()
        if was_visible:
            self.cancelled.emit()

    def hideEvent(self, event) -> None:
        self._hide_preview_lens()
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        center = QtCore.QPointF(self.width() * 0.5, self.height() * 0.5)
        primary = self._theme["primary"]
        glow = self._theme["glow"]
        background = self._theme["background"]
        background_radius = radial_layout_radius(len(self._buttons)) + 36.0

        glass = QtGui.QRadialGradient(center, background_radius)
        glass.setColorAt(0.0, _with_alpha(background, 18))
        glass.setColorAt(0.58, _with_alpha(_blend(background, primary, 0.08), 24))
        glass.setColorAt(1.0, _with_alpha(background, 4))
        painter.setPen(QtGui.QPen(_with_alpha(primary, 72), 1.2))
        painter.setBrush(glass)
        painter.drawEllipse(center, background_radius, background_radius)

        orbit_radii = (
            (background_radius - 1.0, primary, 58, QtCore.Qt.SolidLine),
            (background_radius - 24.0, self._theme["timer"], 34, QtCore.Qt.DashLine),
            (background_radius - 62.0, glow, 30, QtCore.Qt.SolidLine),
        )
        painter.setBrush(QtCore.Qt.NoBrush)
        for radius, color, alpha, style in orbit_radii:
            painter.setPen(QtGui.QPen(_with_alpha(color, alpha), 1.0, style))
            painter.drawEllipse(center, radius, radius)

        candidate_id = self.selection_candidate_id
        for _action_id, button in self._buttons.items():
            color = glow if button.isEnabled() else self._theme["muted"]
            alpha = 44 if button.isEnabled() else 24
            style = QtCore.Qt.SolidLine if button.isEnabled() else QtCore.Qt.DashLine
            painter.setPen(QtGui.QPen(_with_alpha(color, alpha), 1.0, style))
            painter.drawLine(center, QtCore.QPointF(button.geometry().center()))

        candidate_button = self._buttons.get(str(candidate_id or ""))
        if self._focus_beam_enabled and candidate_button is not None and candidate_button.isEnabled():
            target = QtCore.QPointF(candidate_button.geometry().center())
            progress = max(0.0, min(1.0, self.selection_progress))
            red = QtGui.QColor("#ef4444")
            amber = QtGui.QColor("#f59e0b")
            yellow = QtGui.QColor("#facc15")
            beam_alpha = int(round(86 + 154 * progress))
            beam_width = 2.0 + 2.2 * progress
            painter.setPen(
                QtGui.QPen(
                    _with_alpha(amber, int(round(30 + 68 * progress))),
                    beam_width + 7.0,
                    QtCore.Qt.SolidLine,
                    QtCore.Qt.RoundCap,
                )
            )
            painter.drawLine(center, target)
            beam = QtGui.QLinearGradient(center, target)
            beam.setColorAt(0.0, _with_alpha(red, beam_alpha))
            beam.setColorAt(0.30, _with_alpha(red, beam_alpha))
            beam.setColorAt(0.64, _with_alpha(amber, min(255, beam_alpha + 10)))
            beam.setColorAt(1.0, _with_alpha(yellow, min(255, beam_alpha + 24)))
            painter.setPen(
                QtGui.QPen(
                    QtGui.QBrush(beam),
                    beam_width,
                    QtCore.Qt.SolidLine,
                    QtCore.Qt.RoundCap,
                )
            )
            painter.drawLine(center, target)

            pulse_line = QtCore.QLineF(center, target)
            pulse_position = 0.12 + 0.76 * ((time.monotonic() * 0.72) % 1.0)
            pulse = pulse_line.pointAt(pulse_position)
            pulse_radius = 3.0 + 2.5 * progress
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(_with_alpha(yellow, int(round(156 + 99 * progress))))
            painter.drawEllipse(pulse, pulse_radius, pulse_radius)
        if self._page_title:
            painter.setPen(_with_alpha(self._theme["text"], 225))
            font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont)
            font.setBold(True)
            font.setPixelSize(12)
            painter.setFont(font)
            painter.drawText(
                QtCore.QRectF(center.x() - 90.0, center.y() + 54.0, 180.0, 28.0),
                QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
                self._page_title,
            )

    def mousePressEvent(self, event) -> None:
        global_point = QtCore.QPointF(event.globalPosition())
        if self._mouse_action_at_global_point(global_point) is None:
            if self._is_over_button_global_point(global_point):
                event.accept()
                return
            self.cancel()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == QtCore.Qt.Key_Escape:
            self.cancel()
            event.accept()
            return
        super().keyPressEvent(event)
