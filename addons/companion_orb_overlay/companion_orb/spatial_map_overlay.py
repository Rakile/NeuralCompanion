from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQuick

from addons.companion_orb_overlay.companion_orb.desktop_spatial_map import (
    SpatialRegion,
)


@dataclass(frozen=True, slots=True)
class SpatialOverlayState:
    candidate_id: str = ""
    locked_id: str = ""
    selection_progress: float = 0.0
    activation_progress: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", str(self.candidate_id or "").strip())
        object.__setattr__(self, "locked_id", str(self.locked_id or "").strip())
        for name in ("selection_progress", "activation_progress"):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError, OverflowError):
                value = 0.0
            if not math.isfinite(value):
                value = 0.0
            object.__setattr__(self, name, max(0.0, min(1.0, value)))


class _SpatialBridge(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []

    @QtCore.Property("QVariantList", notify=changed)
    def items(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._items]

    def set_items(self, items: Sequence[Mapping[str, Any]]) -> None:
        self._items = [dict(item) for item in items]
        self.changed.emit()


class SpatialMapOverlay(QtCore.QObject):
    """Click-through Qt Quick renderer for the shared desktop spatial map."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._regions: tuple[SpatialRegion, ...] = ()
        self._show_labels = True
        self._gaze_state = SpatialOverlayState()
        self._theme = self._normalize_theme({})
        self._bridge = _SpatialBridge(self)
        self._view = QtQuick.QQuickView()
        self._view.setTitle("Companion Orb spatial map")
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
        self._view.rootContext().setContextProperty("spatialOverlayBridge", self._bridge)
        source = Path(__file__).resolve().parent / "qml" / "SpatialMapOverlay.qml"
        self._view.setSource(QtCore.QUrl.fromLocalFile(str(source)))
        if self._view.status() == QtQuick.QQuickView.Error:
            errors = "; ".join(error.toString() for error in self._view.errors())
            raise RuntimeError(errors or "Spatial map overlay QML failed to load")

    @property
    def region_bounds(self) -> dict[str, QtCore.QRect]:
        return {
            region.region_id: QtCore.QRect(*region.screen_bounds)
            for region in self._regions
        }

    @property
    def show_labels(self) -> bool:
        return self._show_labels

    @property
    def theme(self) -> dict[str, object]:
        return dict(self._theme)

    def set_regions(
        self,
        regions: Sequence[SpatialRegion],
        *,
        show_labels: bool,
        maximum_visible: int,
        theme: Mapping[str, object] | None,
    ) -> None:
        try:
            limit = max(1, min(96, int(maximum_visible)))
        except (TypeError, ValueError, OverflowError):
            limit = 24
        normalized_theme = self._normalize_theme(theme)
        minimum_confidence = float(normalized_theme["minimum_confidence"])
        accepted: list[SpatialRegion] = []
        for region in regions if isinstance(regions, Sequence) else ():
            if len(accepted) >= limit:
                break
            if not isinstance(region, SpatialRegion):
                continue
            bounds = QtCore.QRect(*region.screen_bounds)
            if bounds.isEmpty() or region.confidence < minimum_confidence:
                continue
            accepted.append(region)
        self._regions = tuple(accepted)
        self._show_labels = bool(show_labels)
        self._theme = normalized_theme
        self._refresh()

    def set_gaze_state(self, state: SpatialOverlayState) -> None:
        self._gaze_state = (
            state if isinstance(state, SpatialOverlayState) else SpatialOverlayState()
        )
        self._refresh()

    def clear_regions(self) -> None:
        self._regions = ()
        self._gaze_state = SpatialOverlayState()
        self._bridge.set_items(())
        self.hide()

    def hide(self) -> None:
        self._view.hide()

    def deleteLater(self) -> None:
        self._view.close()
        self._view.deleteLater()
        super().deleteLater()

    @staticmethod
    def _color(value: object, fallback: str) -> str:
        color = QtGui.QColor(str(value or "").strip())
        return color.name(QtGui.QColor.HexArgb) if color.isValid() else fallback

    @classmethod
    def _normalize_theme(cls, theme: Mapping[str, object] | None) -> dict[str, object]:
        values = dict(theme or {})
        try:
            opacity = float(values.get("opacity", 0.70))
        except (TypeError, ValueError, OverflowError):
            opacity = 0.70
        try:
            width = float(values.get("width", 2.0))
        except (TypeError, ValueError, OverflowError):
            width = 2.0
        try:
            minimum_confidence = float(values.get("minimum_confidence", 0.55))
        except (TypeError, ValueError, OverflowError):
            minimum_confidence = 0.55
        return {
            "normal": cls._color(values.get("normal"), "#38bdf8"),
            "hover": cls._color(values.get("hover"), "#facc15"),
            "selected": cls._color(values.get("selected"), "#a78bfa"),
            "text": cls._color(values.get("text"), "#f8fafc"),
            "surface": cls._color(values.get("surface"), "#101b2b"),
            "opacity": max(0.05, min(1.0, opacity)),
            "width": max(1.0, min(8.0, width)),
            "minimum_confidence": max(0.0, min(1.0, minimum_confidence)),
        }

    @staticmethod
    def _desktop_geometry() -> QtCore.QRect:
        screens = QtGui.QGuiApplication.screens()
        if not screens:
            return QtCore.QRect()
        geometry = QtCore.QRect(screens[0].geometry())
        for screen in screens[1:]:
            geometry = geometry.united(screen.geometry())
        return geometry

    def _refresh(self) -> None:
        geometry = self._desktop_geometry()
        if not self._regions or geometry.isEmpty():
            self.hide()
            return
        state = self._gaze_state
        items: list[dict[str, Any]] = []
        for region in self._regions:
            bounds = QtCore.QRect(*region.screen_bounds)
            selected = region.region_id == state.locked_id
            hovered = region.region_id == state.candidate_id
            color_key = "selected" if selected else "hover" if hovered else "normal"
            progress = (
                state.activation_progress
                if selected
                else state.selection_progress if hovered else 0.0
            )
            items.append(
                {
                    "id": region.region_id,
                    "x": bounds.x() - geometry.x(),
                    "y": bounds.y() - geometry.y(),
                    "width": bounds.width(),
                    "height": bounds.height(),
                    "label": region.label if self._show_labels else "",
                    "color": self._theme[color_key],
                    "surface": self._theme["surface"],
                    "text": self._theme["text"],
                    "opacity": self._theme["opacity"],
                    "lineWidth": float(self._theme["width"])
                    + (1.0 if selected else 0.5 if hovered else 0.0),
                    "progress": progress,
                }
            )
        self._view.setGeometry(geometry)
        self._bridge.set_items(items)
        self._view.show()


__all__ = ["SpatialMapOverlay", "SpatialOverlayState"]

