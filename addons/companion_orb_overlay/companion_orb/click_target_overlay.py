from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQuick


class _HighlightBridge(QtCore.QObject):
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


class ClickTargetHighlightOverlay(QtCore.QObject):
    """Native Qt Quick desktop overlay for transient click-target feedback."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_bounds = QtCore.QRect()
        self.target_label = ""
        self.candidate_bounds: dict[str, QtCore.QRect] = {}
        self.candidate_labels: dict[str, str] = {}
        self.active_id = ""
        self._theme: dict[str, str] = {}
        self._bridge = _HighlightBridge(self)
        self._view = QtQuick.QQuickView()
        self._view.setTitle("Companion Orb target highlight")
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
            "targetHighlightBridge",
            self._bridge,
        )
        source = Path(__file__).resolve().parent / "qml" / "ClickTargetOverlay.qml"
        self._view.setSource(QtCore.QUrl.fromLocalFile(str(source)))
        if self._view.status() == QtQuick.QQuickView.Error:
            errors = "; ".join(error.toString() for error in self._view.errors())
            raise RuntimeError(errors or "Click target overlay QML failed to load")

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
        self._bridge.set_items(())
        self.hide()

    def hide(self) -> None:
        self._view.hide()

    def deleteLater(self) -> None:
        self._view.close()
        self._view.deleteLater()
        super().deleteLater()

    @staticmethod
    def _rect_from_bounds(bounds: Sequence[int]) -> QtCore.QRect:
        values = list(bounds)[:4]
        if len(values) != 4:
            return QtCore.QRect()
        try:
            left, top, width, height = (
                int(round(float(value))) for value in values
            )
        except (TypeError, ValueError):
            return QtCore.QRect()
        return QtCore.QRect(left, top, max(0, width), max(0, height))

    @staticmethod
    def _normalize_theme(theme: Mapping[str, object] | None) -> dict[str, str]:
        values = dict(theme or {})
        return {
            "primary": ClickTargetHighlightOverlay._color(
                values.get("primary"),
                "#38bdf8",
            ),
            "accent": ClickTargetHighlightOverlay._color(
                values.get("accent"),
                "#a78bfa",
            ),
            "text": ClickTargetHighlightOverlay._color(
                values.get("text"),
                "#eef7ff",
            ),
            "surface": ClickTargetHighlightOverlay._color(
                values.get("surface"),
                "#101b2b",
            ),
        }

    @staticmethod
    def _color(value: object, fallback: str) -> str:
        color = QtGui.QColor(str(value or "").strip())
        return color.name(QtGui.QColor.HexArgb) if color.isValid() else fallback

    @staticmethod
    def _desktop_geometry() -> QtCore.QRect:
        screens = QtGui.QGuiApplication.screens()
        if not screens:
            return QtCore.QRect()
        geometry = QtCore.QRect(screens[0].geometry())
        for screen in screens[1:]:
            geometry = geometry.united(screen.geometry())
        return geometry

    def _show_for_current_screens(self) -> None:
        geometry = self._desktop_geometry()
        if geometry.isEmpty():
            self.hide()
            return
        self._view.setGeometry(geometry)
        items: list[dict[str, Any]] = []
        if not self.target_bounds.isEmpty():
            items.append(
                self._item(
                    self.target_bounds,
                    self.target_label,
                    active=True,
                    desktop=geometry,
                )
            )
        items.extend(
            self._item(
                bounds,
                self.candidate_labels.get(candidate_id, ""),
                active=candidate_id == self.active_id,
                desktop=geometry,
            )
            for candidate_id, bounds in self.candidate_bounds.items()
            if not bounds.isEmpty()
        )
        self._bridge.set_items(items)
        self._view.show()

    def _item(
        self,
        bounds: QtCore.QRect,
        label: str,
        *,
        active: bool,
        desktop: QtCore.QRect,
    ) -> dict[str, Any]:
        return {
            "x": bounds.x() - desktop.x(),
            "y": bounds.y() - desktop.y(),
            "width": bounds.width(),
            "height": bounds.height(),
            "label": str(label or ""),
            "active": bool(active),
            **self._theme,
        }

