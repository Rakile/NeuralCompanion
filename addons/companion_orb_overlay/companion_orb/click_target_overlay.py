from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6 import QtCore, QtGui, QtWidgets


class ClickTargetHighlightOverlay(QtWidgets.QWidget):
    """A single click-through desktop overlay for transient click-target feedback."""

    def __init__(self, parent=None):
        flags = (
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | getattr(QtCore.Qt, "NoDropShadowWindowHint", QtCore.Qt.WindowType(0))
        )
        transparent_input = getattr(QtCore.Qt, "WindowTransparentForInput", QtCore.Qt.WindowType(0))
        super().__init__(parent, flags | transparent_input)
        self.setObjectName("companion_orb_click_target_highlight")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.target_bounds = QtCore.QRect()
        self.target_label = ""
        self.candidate_bounds: dict[str, QtCore.QRect] = {}
        self.candidate_labels: dict[str, str] = {}
        self.active_id = ""
        self._theme: dict[str, QtGui.QColor] = {}

    def show_target(
        self,
        bounds: Sequence[int],
        label: str,
        theme: Mapping[str, object] | None = None,
    ) -> None:
        self.target_bounds = self._rect_from_bounds(bounds)
        self.target_label = str(label or "").strip()
        self.candidate_bounds.clear()
        self.candidate_labels.clear()
        self.active_id = ""
        self._theme = self._normalize_theme(theme)
        self._show_for_current_screens()

    def show_candidates(
        self,
        candidates: Sequence[tuple[str, Sequence[int], str]],
        *,
        active_id: str,
        theme: Mapping[str, object] | None = None,
    ) -> None:
        self.target_bounds = QtCore.QRect()
        self.target_label = ""
        self.candidate_bounds = {
            str(candidate_id): self._rect_from_bounds(bounds)
            for candidate_id, bounds, _marker in candidates
            if str(candidate_id).strip()
        }
        self.candidate_labels = {
            str(candidate_id): str(marker or "").strip()
            for candidate_id, _bounds, marker in candidates
            if str(candidate_id).strip()
        }
        self.active_id = str(active_id or "").strip()
        self._theme = self._normalize_theme(theme)
        self._show_for_current_screens()

    def clear_target(self) -> None:
        self.target_bounds = QtCore.QRect()
        self.target_label = ""
        self.candidate_bounds.clear()
        self.candidate_labels.clear()
        self.active_id = ""
        self.hide()

    @staticmethod
    def _rect_from_bounds(bounds: Sequence[int]) -> QtCore.QRect:
        values = list(bounds)[:4]
        if len(values) != 4:
            return QtCore.QRect()
        try:
            left, top, width, height = (int(round(float(value))) for value in values)
        except (TypeError, ValueError):
            return QtCore.QRect()
        return QtCore.QRect(left, top, max(0, width), max(0, height))

    @staticmethod
    def _normalize_theme(theme: Mapping[str, object] | None) -> dict[str, QtGui.QColor]:
        values = dict(theme or {})
        return {
            "primary": ClickTargetHighlightOverlay._color(values.get("primary"), "#38bdf8"),
            "accent": ClickTargetHighlightOverlay._color(values.get("accent"), "#a78bfa"),
            "text": ClickTargetHighlightOverlay._color(values.get("text"), "#eef7ff"),
            "surface": ClickTargetHighlightOverlay._color(values.get("surface"), "#101b2b"),
        }

    @staticmethod
    def _color(value: object, fallback: str) -> QtGui.QColor:
        color = QtGui.QColor(str(value or "").strip())
        return color if color.isValid() else QtGui.QColor(fallback)

    def _show_for_current_screens(self) -> None:
        geometry = self._desktop_geometry()
        if geometry.isEmpty():
            self.hide()
            return
        self.setGeometry(geometry)
        self.show()
        self.raise_()
        self.update()

    @staticmethod
    def _desktop_geometry() -> QtCore.QRect:
        screens = QtGui.QGuiApplication.screens()
        if not screens:
            return QtCore.QRect()
        geometry = QtCore.QRect(screens[0].geometry())
        for screen in screens[1:]:
            geometry = geometry.united(screen.geometry())
        return geometry

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        if not self.target_bounds.isEmpty():
            self._paint_target(painter, self.target_bounds, self.target_label, active=True)
        for candidate_id, bounds in self.candidate_bounds.items():
            self._paint_target(
                painter,
                bounds,
                self.candidate_labels.get(candidate_id, ""),
                active=candidate_id == self.active_id,
            )

    def _paint_target(
        self,
        painter: QtGui.QPainter,
        global_bounds: QtCore.QRect,
        label: str,
        *,
        active: bool,
    ) -> None:
        if global_bounds.isEmpty():
            return
        bounds = global_bounds.translated(-self.x(), -self.y()).adjusted(1, 1, -1, -1)
        primary = self._theme["primary"]
        accent = self._theme["accent"]
        text = self._theme["text"]
        surface = self._theme["surface"]
        color = accent if active else primary
        width = 3.2 if active else 2.0
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(color, width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        painter.drawRoundedRect(QtCore.QRectF(bounds), 4.0, 4.0)

        bracket = max(10.0, min(22.0, min(bounds.width(), bounds.height()) * 0.45))
        painter.setPen(QtGui.QPen(text if active else color, 2.0, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        for point, horizontal, vertical in (
            (bounds.topLeft(), 1.0, 1.0),
            (bounds.topRight(), -1.0, 1.0),
            (bounds.bottomLeft(), 1.0, -1.0),
            (bounds.bottomRight(), -1.0, -1.0),
        ):
            corner = QtCore.QPointF(point)
            painter.drawLine(corner, corner + QtCore.QPointF(bracket * horizontal, 0.0))
            painter.drawLine(corner, corner + QtCore.QPointF(0.0, bracket * vertical))

        if not label:
            return
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont)
        font.setBold(True)
        font.setPixelSize(12)
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        compact_label = metrics.elidedText(label, QtCore.Qt.ElideRight, 220)
        label_rect = QtCore.QRectF(bounds.left(), bounds.bottom() + 6.0, metrics.horizontalAdvance(compact_label) + 18.0, 24.0)
        if label_rect.bottom() > self.height() - 4.0:
            label_rect.moveBottom(bounds.top() - 6.0)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(surface.red(), surface.green(), surface.blue(), 224))
        painter.drawRoundedRect(label_rect, 4.0, 4.0)
        painter.setPen(text)
        painter.drawText(label_rect.adjusted(9.0, 0.0, -9.0, 0.0), QtCore.Qt.AlignVCenter, compact_label)
