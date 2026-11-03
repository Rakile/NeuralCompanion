"""Developer-facing UI review notes for the native QML shell.

The controller is deliberately presentation-only.  It resolves Qt Quick items,
stores user-authored design notes, and exports a Codex-readable summary without
touching NeuralCompanion runtime, provider, or addon ownership.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtQuick


LOGGER = logging.getLogger(__name__)
_SCHEMA_VERSION = 1
_INTERACTIVE_TYPE_MARKERS = (
    "Button",
    "CheckBox",
    "ComboBox",
    "Dial",
    "MenuItem",
    "RadioButton",
    "Slider",
    "SpinBox",
    "Switch",
    "TextArea",
    "TextField",
)
_WORKSPACE_SOURCE_HINTS = {
    "runtime": "ui/qml/workspaces/RuntimeWorkspace.qml",
    "addons": "ui/qml/workspaces/AddonsWorkspace.qml",
    "conversation": "ui/qml/workspaces/ConversationWorkspace.qml",
    "visuals": "ui/qml/workspaces/VisualsWorkspace.qml",
    "musetalk": "ui/qml/workspaces/VisualsWorkspace.qml",
}


def _plain(value: Any) -> Any:
    """Convert QML/Qt values into JSON-safe Python values."""

    if hasattr(value, "toVariant"):
        try:
            value = value.toVariant()
        except (AttributeError, RuntimeError, TypeError):
            return None
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _short_text(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _qml_type(item: QtCore.QObject | None) -> str:
    if item is None:
        return "QQuickItem"
    name = str(item.metaObject().className() or "QQuickItem")
    for marker in ("_QMLTYPE_", "_QML_"):
        if marker in name:
            name = name.split(marker, 1)[0]
    return name.rsplit("::", 1)[-1]


class UiReviewNotesController(QtCore.QObject):
    """Resolve QML components and persist user-authored review instructions."""

    activeChanged = QtCore.Signal()
    notesChanged = QtCore.Signal()
    layoutChanged = QtCore.Signal()
    mainWindowControlsVisibleChanged = QtCore.Signal()
    targetRequested = QtCore.Signal("QVariantMap")
    hoverTargetChanged = QtCore.Signal("QVariantMap")

    def __init__(
        self,
        app_root: Path,
        *,
        install_event_filter: bool = True,
        layout_editing_enabled: bool = False,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_root = Path(app_root).resolve()
        self._notes_dir = self._app_root / "ui_review_notes"
        self._notes_path = self._notes_dir / "codex_ui_notes.json"
        self._markdown_path = self._notes_dir / "codex_ui_notes.md"
        self._layout_path = self._notes_dir / "ui_layout_overrides.json"
        self._active = False
        self._main_window_controls_visible = True
        self._notes: list[dict[str, Any]] = []
        self._layouts: dict[str, Any] = {}
        self._layout_revision = 0
        self._layout_undo: list[dict[str, Any]] = []
        # Retain the experimental implementation without exposing it in the
        # production UI.  Tests may opt in explicitly so the dormant path
        # remains verifiable and inexpensive to restore later.
        self._layout_editing_enabled = bool(layout_editing_enabled)
        self._hover_key: tuple[object, ...] = ()
        self._filter_installed = False
        self._load()
        self._load_layouts()
        app = QtCore.QCoreApplication.instance()
        if install_event_filter and app is not None:
            app.installEventFilter(self)
            self._filter_installed = True

    @QtCore.Property(bool, notify=activeChanged)
    def active(self) -> bool:
        return self._active

    @active.setter
    def active(self, value: bool) -> None:
        next_value = bool(value)
        if next_value == self._active:
            return
        self._active = next_value
        self._hover_key = ()
        self.activeChanged.emit()
        if not next_value:
            self.hoverTargetChanged.emit({})

    @QtCore.Property("QVariantList", notify=notesChanged)
    def notes(self) -> list[dict[str, Any]]:
        return [_plain(note) for note in self._notes]

    @QtCore.Property(bool, notify=mainWindowControlsVisibleChanged)
    def mainWindowControlsVisible(self) -> bool:
        return self._main_window_controls_visible

    @QtCore.Property(int, notify=notesChanged)
    def openCount(self) -> int:
        return sum(not bool(note.get("resolved")) for note in self._notes)

    @QtCore.Property(str, constant=True)
    def notesPath(self) -> str:
        return str(self._notes_path)

    @QtCore.Property(str, constant=True)
    def markdownPath(self) -> str:
        return str(self._markdown_path)

    @QtCore.Property(int, notify=layoutChanged)
    def layoutRevision(self) -> int:
        return self._layout_revision

    @QtCore.Property(bool, constant=True)
    def layoutEditingEnabled(self) -> bool:
        return self._layout_editing_enabled

    @QtCore.Property(bool, notify=layoutChanged)
    def canUndoLayout(self) -> bool:
        return self._layout_editing_enabled and bool(self._layout_undo)

    @QtCore.Slot(bool)
    def setActive(self, value: bool) -> None:
        self.active = value

    @QtCore.Slot(bool)
    def setMainWindowControlsVisible(self, visible: bool) -> None:
        next_value = bool(visible)
        if next_value == self._main_window_controls_visible:
            return
        self._main_window_controls_visible = next_value
        if not next_value:
            self.active = False
        self._persist()
        self.mainWindowControlsVisibleChanged.emit()

    @QtCore.Slot(str, "QVariantMap", "QVariantMap", result=str)
    def addNote(
        self,
        instruction: str,
        target: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> str:
        text = str(instruction or "").strip()
        if not text:
            return ""
        clean_target = dict(_plain(target) or {})
        clean_context = dict(_plain(context) or {})
        now = datetime.now(timezone.utc).isoformat()
        note_id = uuid4().hex
        workspace = str(clean_context.get("workspace") or "").strip()
        addon_id = str(clean_context.get("addonId") or "").strip()
        section = str(
            clean_target.get("section") or clean_context.get("section") or ""
        ).strip()
        source_hints = self._source_hints(workspace, addon_id, clean_target)
        note = {
            "id": note_id,
            "createdAt": now,
            "updatedAt": now,
            "resolved": False,
            "instruction": text,
            "workspace": workspace,
            "workspaceLabel": str(clean_context.get("workspaceLabel") or workspace),
            "addonId": addon_id,
            "addonLabel": str(clean_context.get("addonLabel") or ""),
            "section": section,
            "target": clean_target,
            "sourceHints": source_hints,
        }
        self._notes.insert(0, note)
        self._persist()
        self.notesChanged.emit()
        return note_id

    @QtCore.Slot(str, bool)
    def setResolved(self, note_id: str, resolved: bool) -> None:
        note = self._find(note_id)
        if note is None or bool(note.get("resolved")) == bool(resolved):
            return
        note["resolved"] = bool(resolved)
        note["updatedAt"] = datetime.now(timezone.utc).isoformat()
        self._persist()
        self.notesChanged.emit()

    @QtCore.Slot(str)
    def deleteNote(self, note_id: str) -> None:
        before = len(self._notes)
        self._notes = [note for note in self._notes if note.get("id") != note_id]
        if len(self._notes) == before:
            return
        self._persist()
        self.notesChanged.emit()

    @QtCore.Slot(result=str)
    def exportMarkdown(self) -> str:
        try:
            self._notes_dir.mkdir(parents=True, exist_ok=True)
            self._markdown_path.write_text(
                self._render_markdown(self._notes),
                encoding="utf-8",
            )
        except OSError as error:
            LOGGER.warning("Could not export UI review notes: %s", error)
            return ""
        return str(self._markdown_path)

    @QtCore.Slot(result=int)
    def copyOpenNotes(self) -> int:
        open_notes = [note for note in self._notes if not bool(note.get("resolved"))]
        text = self._render_markdown(open_notes)
        app = QtGui.QGuiApplication.instance()
        if app is not None and app.clipboard() is not None:
            app.clipboard().setText(text)
        return len(open_notes)

    @QtCore.Slot(str)
    def requestHighlight(self, note_id: str) -> None:
        note = self._find(note_id)
        if note is None:
            return
        locator = str(dict(note.get("target") or {}).get("locator") or "")
        window_name = str(
            dict(note.get("target") or {}).get("windowObjectName") or ""
        )

        def locate() -> None:
            descriptor = self._find_descriptor(locator, window_name)
            if descriptor:
                self._emit_hover(descriptor, force=True)

        for delay in (120, 420, 900):
            QtCore.QTimer.singleShot(delay, locate)

    @QtCore.Slot(str, str, result="QVariantMap")
    def layoutFor(self, surface_id: str, section: str) -> dict[str, Any]:
        if not self._layout_editing_enabled:
            return {}
        payload = self._layout_section(surface_id, section, create=False)
        return deepcopy(payload) if payload is not None else {}

    @QtCore.Slot(str, str, str, int, int, str, result=str)
    def createLayoutCard(
        self,
        surface_id: str,
        section: str,
        label: str,
        column_span: int,
        minimum_height: int,
        placement: str,
    ) -> str:
        if not self._layout_editing_enabled:
            return ""
        if not self._layout_key(surface_id) or not self._layout_key(section):
            return ""
        self._begin_layout_change()
        payload = self._layout_section(surface_id, section, create=True)
        if payload is None:
            return ""
        card_id = f"custom_{uuid4().hex[:10]}"
        cards = payload.setdefault("cards", {})
        cards[card_id] = {
            "custom": True,
            "label": str(label or "New card").strip() or "New card",
            "columnSpan": max(1, min(2, int(column_span or 2))),
            "minimumHeight": max(0, min(1600, int(minimum_height or 0))),
            "order": self._layout_order(cards, placement),
        }
        self._commit_layout_change()
        return card_id

    @QtCore.Slot(str, str, str, str, int, int, str)
    def updateLayoutCard(
        self,
        surface_id: str,
        section: str,
        card_id: str,
        label: str,
        column_span: int,
        minimum_height: int,
        placement: str,
    ) -> None:
        if not self._layout_editing_enabled:
            return
        if not self._layout_key(surface_id) or not self._layout_key(section):
            return
        card_key = self._layout_key(card_id)
        if not card_key:
            return
        self._begin_layout_change()
        payload = self._layout_section(surface_id, section, create=True)
        if payload is None:
            return
        cards = payload.setdefault("cards", {})
        existing = dict(cards.get(card_key) or {})
        updated: dict[str, Any] = {"custom": bool(existing.get("custom"))}
        clean_label = str(label or "").strip()
        if clean_label:
            updated["label"] = clean_label
        updated["columnSpan"] = max(1, min(2, int(column_span or 2)))
        updated["minimumHeight"] = max(0, min(1600, int(minimum_height or 0)))
        if placement in {"first", "last"}:
            updated["order"] = self._layout_order(cards, placement, exclude=card_key)
        elif "order" in existing:
            updated["order"] = existing["order"]
        cards[card_key] = updated
        self._commit_layout_change()

    @QtCore.Slot(str, str, str, str, str, str)
    def updateControlLayout(
        self,
        surface_id: str,
        section: str,
        control_id: str,
        label: str,
        card_id: str,
        placement: str,
    ) -> None:
        if not self._layout_editing_enabled:
            return
        if not self._layout_key(surface_id) or not self._layout_key(section):
            return
        control_key = self._layout_key(control_id)
        if not control_key:
            return
        self._begin_layout_change()
        payload = self._layout_section(surface_id, section, create=True)
        if payload is None:
            return
        controls = payload.setdefault("controls", {})
        existing = dict(controls.get(control_key) or {})
        clean_label = str(label or "").strip()
        if clean_label:
            existing["label"] = clean_label
        clean_card = self._layout_key(card_id)
        if clean_card:
            existing["groupKey"] = clean_card
        if placement in {"first", "last"}:
            existing["order"] = self._layout_order(
                controls,
                placement,
                exclude=control_key,
            )
        controls[control_key] = existing
        self._commit_layout_change()

    @QtCore.Slot(str, str, str, str, result=bool)
    def hasLayoutOverride(
        self,
        surface_id: str,
        section: str,
        layout_kind: str,
        target_id: str,
    ) -> bool:
        if not self._layout_editing_enabled:
            return False
        payload = self._layout_section(surface_id, section, create=False) or {}
        bucket = "cards" if str(layout_kind) == "card" else "controls"
        return self._layout_key(target_id) in dict(payload.get(bucket) or {})

    @QtCore.Slot(str, str, str, str)
    def resetLayoutTarget(
        self,
        surface_id: str,
        section: str,
        layout_kind: str,
        target_id: str,
    ) -> None:
        if not self._layout_editing_enabled:
            return
        payload = self._layout_section(surface_id, section, create=False)
        target_key = self._layout_key(target_id)
        if payload is None or not target_key:
            return
        bucket_name = "cards" if str(layout_kind) == "card" else "controls"
        bucket = dict(payload.get(bucket_name) or {})
        if target_key not in bucket:
            return
        self._begin_layout_change()
        removed = dict(bucket.pop(target_key) or {})
        payload[bucket_name] = bucket
        if bucket_name == "cards" and bool(removed.get("custom")):
            controls = dict(payload.get("controls") or {})
            for control_id, override in list(controls.items()):
                clean_override = dict(override or {})
                if clean_override.get("groupKey") != target_key:
                    continue
                clean_override.pop("groupKey", None)
                if clean_override:
                    controls[control_id] = clean_override
                else:
                    controls.pop(control_id, None)
            payload["controls"] = controls
        self._prune_layouts()
        self._commit_layout_change()

    @QtCore.Slot()
    def undoLayout(self) -> None:
        if not self._layout_editing_enabled or not self._layout_undo:
            return
        self._layouts = self._layout_undo.pop()
        self._persist_layouts()
        self._layout_revision += 1
        self.layoutChanged.emit()

    def close(self) -> None:
        if not self._filter_installed:
            return
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._filter_installed = False

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if not self._active:
            return False
        try:
            return self._handle_active_event(watched, event)
        except (RuntimeError, TypeError):
            # Qt may deliver a final event while QML items are being deleted
            # during window shutdown.  Note Mode must never disturb teardown.
            return False

    def _handle_active_event(
        self,
        watched: QtCore.QObject,
        event: QtCore.QEvent,
    ) -> bool:
        event_type = event.type()
        interesting = {
            QtCore.QEvent.Type.MouseMove,
            QtCore.QEvent.Type.HoverMove,
            QtCore.QEvent.Type.MouseButtonPress,
        }
        if event_type not in interesting:
            return False
        window = self._quick_window(watched)
        if window is None:
            return False
        position = self._event_scene_position(window, watched, event)
        if position is None:
            return False
        target = self._resolve_target(window, position)
        if event_type in {
            QtCore.QEvent.Type.MouseMove,
            QtCore.QEvent.Type.HoverMove,
        }:
            self._emit_hover(target)
            return False
        button = getattr(event, "button", lambda: QtCore.Qt.MouseButton.NoButton)()
        if button != QtCore.Qt.MouseButton.RightButton or not target:
            return False
        self._emit_hover(target, force=True)
        self.targetRequested.emit(target)
        event.accept()
        return True

    def _load(self) -> None:
        if not self._notes_path.is_file():
            return
        try:
            payload = json.loads(self._notes_path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                self._main_window_controls_visible = bool(
                    payload.get("mainWindowControlsVisible", True)
                )
            notes = payload.get("notes") if isinstance(payload, Mapping) else []
            if isinstance(notes, list):
                self._notes = [dict(note) for note in notes if isinstance(note, Mapping)]
        except (OSError, ValueError, TypeError) as error:
            LOGGER.warning("Could not read UI review notes: %s", error)

    def _load_layouts(self) -> None:
        if not self._layout_path.is_file():
            return
        try:
            payload = json.loads(self._layout_path.read_text(encoding="utf-8"))
            surfaces = payload.get("surfaces") if isinstance(payload, Mapping) else {}
            if isinstance(surfaces, Mapping):
                self._layouts = deepcopy(dict(surfaces))
        except (OSError, ValueError, TypeError) as error:
            LOGGER.warning("Could not read UI layout overrides: %s", error)

    def _persist(self) -> None:
        temporary = self._notes_path.with_suffix(".json.tmp")
        try:
            self._notes_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "schemaVersion": _SCHEMA_VERSION,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "mainWindowControlsVisible": self._main_window_controls_visible,
                "notes": self._notes,
            }
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self._notes_path)
        except OSError as error:
            LOGGER.warning("Could not persist UI review notes: %s", error)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _persist_layouts(self) -> None:
        temporary = self._layout_path.with_suffix(".json.tmp")
        try:
            if not self._layouts:
                self._layout_path.unlink(missing_ok=True)
                temporary.unlink(missing_ok=True)
                return
            self._notes_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "schemaVersion": _SCHEMA_VERSION,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "surfaces": self._layouts,
            }
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self._layout_path)
        except OSError as error:
            LOGGER.warning("Could not persist UI layout overrides: %s", error)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _layout_key(self, value: Any) -> str:
        return str(value or "").strip()

    def _layout_section(
        self,
        surface_id: str,
        section: str,
        *,
        create: bool,
    ) -> dict[str, Any] | None:
        surface_key = self._layout_key(surface_id)
        section_key = self._layout_key(section)
        if not surface_key or not section_key:
            return None
        if not create:
            surface = self._layouts.get(surface_key)
            if not isinstance(surface, Mapping):
                return None
            payload = surface.get(section_key)
            return payload if isinstance(payload, dict) else None
        surface = self._layouts.setdefault(surface_key, {})
        if not isinstance(surface, dict):
            surface = {}
            self._layouts[surface_key] = surface
        payload = surface.setdefault(section_key, {"cards": {}, "controls": {}})
        if not isinstance(payload, dict):
            payload = {"cards": {}, "controls": {}}
            surface[section_key] = payload
        return payload

    def _layout_order(
        self,
        bucket: Mapping[str, Any],
        placement: str,
        *,
        exclude: str = "",
    ) -> int:
        orders: list[int] = []
        for key, value in bucket.items():
            if str(key) == exclude or not isinstance(value, Mapping):
                continue
            raw_order = value.get("order")
            if raw_order is None:
                continue
            try:
                orders.append(int(raw_order))
            except (TypeError, ValueError):
                continue
        if placement == "first":
            return min(orders, default=-100_000) - 100
        return max(orders, default=100_000) + 100

    def _begin_layout_change(self) -> None:
        self._layout_undo.append(deepcopy(self._layouts))
        if len(self._layout_undo) > 50:
            del self._layout_undo[:-50]

    def _commit_layout_change(self) -> None:
        self._prune_layouts()
        self._persist_layouts()
        self._layout_revision += 1
        self.layoutChanged.emit()

    def _prune_layouts(self) -> None:
        for surface_id, surface in list(self._layouts.items()):
            if not isinstance(surface, dict):
                self._layouts.pop(surface_id, None)
                continue
            for section, payload in list(surface.items()):
                if not isinstance(payload, dict):
                    surface.pop(section, None)
                    continue
                cards = dict(payload.get("cards") or {})
                controls = dict(payload.get("controls") or {})
                payload["cards"] = cards
                payload["controls"] = controls
                if not cards and not controls:
                    surface.pop(section, None)
            if not surface:
                self._layouts.pop(surface_id, None)

    def _find(self, note_id: str) -> dict[str, Any] | None:
        key = str(note_id or "")
        return next((note for note in self._notes if note.get("id") == key), None)

    def _source_hints(
        self,
        workspace: str,
        addon_id: str,
        target: Mapping[str, Any],
    ) -> list[str]:
        hints: list[str] = []
        workspace_hint = _WORKSPACE_SOURCE_HINTS.get(workspace)
        if workspace_hint:
            hints.append(workspace_hint)
        control_id = str(target.get("controlId") or "")
        if workspace == "addons" and control_id:
            hints.append("ui/qml/components/NCLiveControlsGroup.qml")
        if addon_id.startswith("nc."):
            adapter_name = addon_id.removeprefix("nc.").replace("-", "_")
            hints.append(f"ui/qml_bridge/adapters/{adapter_name}.py")
        return list(dict.fromkeys(hints))

    def _render_markdown(self, notes: list[dict[str, Any]]) -> str:
        lines = [
            "# NeuralCompanion UI review notes",
            "",
            "These are user-authored design instructions. Resolve each note only after",
            "verifying the referenced native QML component and preserving runtime behavior.",
            "",
        ]
        if not notes:
            lines.extend(["No matching UI review notes.", ""])
            return "\n".join(lines)
        for index, note in enumerate(notes, start=1):
            target = dict(note.get("target") or {})
            status = "Resolved" if bool(note.get("resolved")) else "Open"
            location = " > ".join(
                value
                for value in (
                    str(note.get("workspaceLabel") or note.get("workspace") or ""),
                    str(note.get("addonLabel") or ""),
                    str(note.get("section") or ""),
                    str(target.get("groupTitle") or ""),
                )
                if value
            )
            lines.extend(
                [
                    f"## {index}. {_short_text(target.get('label') or target.get('identifier') or 'UI component')} [{status}]",
                    "",
                    f"- Note ID: `{note.get('id', '')}`",
                    f"- Location: {location or 'Unknown'}",
                    f"- Identifier: `{target.get('identifier', '')}`",
                    f"- Locator: `{target.get('locator', '')}`",
                    f"- QML type: `{target.get('type', '')}`",
                    f"- Source hints: {', '.join(f'`{value}`' for value in note.get('sourceHints') or []) or 'None'}",
                    "",
                    str(note.get("instruction") or "").strip(),
                    "",
                ]
            )
        return "\n".join(lines)

    def _quick_window(self, watched: QtCore.QObject) -> QtQuick.QQuickWindow | None:
        if isinstance(watched, QtQuick.QQuickWindow):
            return watched
        if isinstance(watched, QtQuick.QQuickItem):
            return watched.window()
        window = getattr(watched, "window", lambda: None)()
        return window if isinstance(window, QtQuick.QQuickWindow) else None

    def _event_scene_position(
        self,
        window: QtQuick.QQuickWindow,
        watched: QtCore.QObject,
        event: QtCore.QEvent,
    ) -> QtCore.QPointF | None:
        global_getter = getattr(event, "globalPosition", None)
        if global_getter is not None:
            try:
                global_position = QtCore.QPointF(global_getter())
                window_position = window.mapFromGlobal(global_position.toPoint())
                return QtCore.QPointF(window_position)
            except (RuntimeError, TypeError):
                pass
        position_getter = getattr(event, "position", None)
        if position_getter is None:
            return None
        try:
            position = QtCore.QPointF(position_getter())
        except (RuntimeError, TypeError):
            return None
        if isinstance(watched, QtQuick.QQuickItem):
            return watched.mapToScene(position)
        return position

    def _resolve_target(
        self,
        window: QtQuick.QQuickWindow,
        scene_position: QtCore.QPointF,
    ) -> dict[str, Any]:
        content = window.contentItem()
        if content is None:
            return {}
        ranked: list[
            tuple[int, int, int, QtQuick.QQuickItem, dict[str, Any]]
        ] = []
        for order, (item, depth) in enumerate(
            self._hit_items(content, scene_position)
        ):
            if item is content or self._item_ignored(item):
                continue
            field = self._mapping_property(item, "field")
            item_type = _qml_type(item)
            label = self._item_label(item)
            if field and (field.get("id") or field.get("objectName")):
                priority = 100
            elif any(marker in item_type for marker in _INTERACTIVE_TYPE_MARKERS):
                priority = 90
            elif label:
                priority = 70
            elif item.objectName():
                priority = 50
            else:
                continue
            ranked.append((priority, depth, -order, item, field))
        if not ranked:
            return {}
        _priority, _depth, _order, semantic, field = max(
            ranked,
            key=lambda candidate: candidate[:3],
        )
        return self._descriptor(window, semantic, field)

    def _hit_items(
        self,
        parent: QtQuick.QQuickItem,
        scene_position: QtCore.QPointF,
        *,
        depth: int = 0,
    ) -> list[tuple[QtQuick.QQuickItem, int]]:
        hits: list[tuple[QtQuick.QQuickItem, int]] = []
        children = list(parent.childItems())
        ordered = sorted(
            enumerate(children),
            key=lambda pair: (float(pair[1].z()), pair[0]),
            reverse=True,
        )
        for _index, child in ordered:
            if self._item_ignored(child) or not child.isVisible() or child.opacity() <= 0:
                continue
            try:
                contains = child.contains(child.mapFromScene(scene_position))
            except (RuntimeError, TypeError):
                continue
            if not contains:
                continue
            if _qml_type(child) != "QQuickOverlay":
                hits.append((child, depth + 1))
            hits.extend(
                self._hit_items(child, scene_position, depth=depth + 1)
            )
        return hits

    def _semantic_item(
        self,
        item: QtQuick.QQuickItem,
    ) -> tuple[QtQuick.QQuickItem | None, dict[str, Any]]:
        chain: list[QtQuick.QQuickItem] = []
        current: QtQuick.QQuickItem | None = item
        while current is not None:
            chain.append(current)
            parent = current.parentItem()
            current = parent if isinstance(parent, QtQuick.QQuickItem) else None
        for candidate in chain:
            field = self._mapping_property(candidate, "field")
            if field and (field.get("id") or field.get("objectName")):
                return candidate, field
        for candidate in chain:
            if any(marker in _qml_type(candidate) for marker in _INTERACTIVE_TYPE_MARKERS):
                return candidate, {}
        for candidate in chain:
            if candidate.objectName():
                return candidate, {}
        return item, {}

    def _descriptor(
        self,
        window: QtQuick.QQuickWindow,
        item: QtQuick.QQuickItem,
        field: Mapping[str, Any],
    ) -> dict[str, Any]:
        control_id = str(field.get("id") or field.get("objectName") or "").strip()
        object_name = str(item.objectName() or "").strip()
        item_type = _qml_type(item)
        label = _short_text(field.get("label") or self._item_label(item))
        identifier = control_id or object_name or label or item_type
        if control_id:
            locator = f"control:{control_id}"
        elif object_name:
            locator = f"object:{object_name}"
        else:
            locator = f"type:{item_type}|label:{label}"
        top_left = item.mapToScene(QtCore.QPointF(0, 0))
        bottom_right = item.mapToScene(QtCore.QPointF(item.width(), item.height()))
        ancestry = []
        current: QtQuick.QQuickItem | None = item
        while current is not None and len(ancestry) < 8:
            if current.objectName():
                ancestry.append(str(current.objectName()))
            parent = current.parentItem()
            current = parent if isinstance(parent, QtQuick.QQuickItem) else None
        return {
            "windowObjectName": str(window.objectName() or ""),
            "windowTitle": str(window.title() or ""),
            "identifier": identifier,
            "locator": locator,
            "controlId": control_id,
            "objectName": object_name,
            "type": item_type,
            "label": label,
            "section": str(field.get("section") or ""),
            "groupKey": str(field.get("groupKey") or ""),
            "groupTitle": str(field.get("groupTitle") or ""),
            "surfaceId": str(field.get("surfaceId") or ""),
            "layoutKind": str(field.get("layoutKind") or ""),
            "layoutId": str(field.get("layoutId") or control_id or ""),
            "layoutEditable": self._layout_editing_enabled
            and bool(field.get("layoutEditable")),
            "defaultLabel": str(field.get("defaultLabel") or ""),
            "defaultGroupKey": str(field.get("defaultGroupKey") or ""),
            "defaultGroupTitle": str(field.get("defaultGroupTitle") or ""),
            "layoutCards": _plain(field.get("layoutCards") or []),
            "layoutColumnSpan": int(field.get("layoutColumnSpan") or 0),
            "layoutMinimumHeight": int(field.get("layoutMinimumHeight") or 0),
            "layoutCustom": bool(field.get("layoutCustom")),
            "currentValue": _short_text(
                field.get("currentValue", field.get("value")),
                limit=300,
            ),
            "ancestry": ancestry,
            "x": float(min(top_left.x(), bottom_right.x())),
            "y": float(min(top_left.y(), bottom_right.y())),
            "width": float(abs(bottom_right.x() - top_left.x())),
            "height": float(abs(bottom_right.y() - top_left.y())),
        }

    def _mapping_property(
        self,
        item: QtCore.QObject,
        name: str,
    ) -> dict[str, Any]:
        try:
            value = _plain(item.property(name))
        except (RuntimeError, TypeError):
            return {}
        return dict(value) if isinstance(value, Mapping) else {}

    def _item_label(self, item: QtQuick.QQuickItem) -> str:
        current: QtQuick.QQuickItem | None = item
        for _depth in range(5):
            if current is None:
                break
            for name in ("text", "title", "label", "placeholderText", "currentText"):
                try:
                    value = current.property(name)
                except (RuntimeError, TypeError):
                    continue
                text = _short_text(value)
                if text:
                    return text
            parent = current.parentItem()
            current = parent if isinstance(parent, QtQuick.QQuickItem) else None
        return ""

    def _item_ignored(self, item: QtQuick.QQuickItem) -> bool:
        current: QtQuick.QQuickItem | None = item
        while current is not None:
            if str(current.objectName() or "").startswith("uiReview"):
                return True
            try:
                if bool(current.property("uiReviewIgnore")):
                    return True
            except (RuntimeError, TypeError):
                pass
            parent = current.parentItem()
            current = parent if isinstance(parent, QtQuick.QQuickItem) else None
        return False

    def _emit_hover(self, descriptor: Mapping[str, Any], *, force: bool = False) -> None:
        payload = dict(descriptor or {})
        key = (
            payload.get("windowObjectName"),
            payload.get("locator"),
            round(float(payload.get("x") or 0), 1),
            round(float(payload.get("y") or 0), 1),
            round(float(payload.get("width") or 0), 1),
            round(float(payload.get("height") or 0), 1),
        ) if payload else ()
        if not force and key == self._hover_key:
            return
        self._hover_key = key
        self.hoverTargetChanged.emit(payload)

    def _find_descriptor(self, locator: str, window_name: str) -> dict[str, Any]:
        app = QtGui.QGuiApplication.instance()
        if app is None or not locator:
            return {}
        for window in app.topLevelWindows():
            if not isinstance(window, QtQuick.QQuickWindow):
                continue
            if window_name and str(window.objectName() or "") != window_name:
                continue
            content = window.contentItem()
            if content is None:
                continue
            for item in self._walk_items(content):
                field = self._mapping_property(item, "field")
                if locator.startswith("control:"):
                    wanted = locator.removeprefix("control:")
                    actual = str(field.get("id") or field.get("objectName") or "")
                    if actual != wanted:
                        continue
                elif locator.startswith("object:"):
                    if str(item.objectName() or "") != locator.removeprefix("object:"):
                        continue
                else:
                    descriptor = self._descriptor(window, item, field)
                    if descriptor.get("locator") != locator:
                        continue
                    return descriptor
                if item.isVisible() and item.width() > 0 and item.height() > 0:
                    semantic, semantic_field = self._semantic_item(item)
                    if semantic is not None:
                        return self._descriptor(window, semantic, semantic_field or field)
        return {}

    def _walk_items(self, root: QtQuick.QQuickItem) -> list[QtQuick.QQuickItem]:
        items: list[QtQuick.QQuickItem] = []
        pending = [root]
        while pending:
            item = pending.pop()
            if self._item_ignored(item):
                continue
            items.append(item)
            pending.extend(item.childItems())
        return items
