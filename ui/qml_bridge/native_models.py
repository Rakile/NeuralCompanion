"""Qt list models for native QML surface/control contracts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from PySide6 import QtCore

from ui.qml_bridge.native_contracts import NativeControl


class NativeControlListModel(QtCore.QAbstractListModel):
    IdRole = QtCore.Qt.UserRole + 1
    LabelRole = IdRole + 1
    KindRole = LabelRole + 1
    SectionRole = KindRole + 1
    DescriptionRole = SectionRole + 1
    ValueRole = DescriptionRole + 1
    EnabledRole = ValueRole + 1
    PayloadRole = EnabledRole + 1

    _ROLE_NAMES = {
        IdRole: b"controlId",
        LabelRole: b"label",
        KindRole: b"kind",
        SectionRole: b"section",
        DescriptionRole: b"description",
        ValueRole: b"value",
        EnabledRole: b"enabled",
        PayloadRole: b"payload",
    }

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._controls: tuple[NativeControl, ...] = ()

    def roleNames(self) -> dict[int, bytes]:
        return dict(self._ROLE_NAMES)

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._controls)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._controls):
            return None
        control = self._controls[index.row()]
        payload = control.to_qml()
        values = {
            QtCore.Qt.DisplayRole: control.label,
            self.IdRole: control.id,
            self.LabelRole: control.label,
            self.KindRole: control.kind.value,
            self.SectionRole: control.section,
            self.DescriptionRole: control.description,
            self.ValueRole: control.value,
            self.EnabledRole: control.enabled,
            self.PayloadRole: payload,
        }
        return values.get(role)

    def replace(self, controls: Iterable[NativeControl]) -> None:
        normalized = tuple(controls)
        self.beginResetModel()
        self._controls = normalized
        self.endResetModel()

    def payloads(self) -> list[dict[str, object]]:
        return [control.to_qml() for control in self._controls]


__all__ = ["NativeControlListModel"]
