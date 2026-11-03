"""Typed presentation contracts for native QML surfaces.

These immutable descriptions are the only generic values consumed by the QML
control renderer.  Runtime work remains behind explicit adapter callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping


class NativeControlKind(str, Enum):
    ACTION = "action"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    DISPLAY = "display"
    IMAGE = "image"
    INTEGER = "integer"
    LIST = "list"
    MULTILINE = "multiline"
    NUMBER = "number"
    PROGRESS = "progress"
    SLIDER = "slider"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class NativeChoice:
    value: object
    label: str

    def to_qml(self) -> dict[str, object]:
        return {"value": self.value, "label": self.label}


@dataclass(frozen=True, slots=True)
class NativeControl:
    id: str
    label: str
    kind: NativeControlKind
    section: str = "Overview"
    description: str = ""
    value: object = None
    default_value: object = None
    enabled: bool = True
    secret: bool = False
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple[NativeChoice, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        control_id = str(self.id or "").strip()
        label = str(self.label or "").strip()
        section = str(self.section or "Overview").strip() or "Overview"
        if not control_id:
            raise ValueError("Native control id is required.")
        if not label:
            raise ValueError(f"Native control '{control_id}' requires a label.")
        if self.minimum is not None and self.maximum is not None:
            if float(self.minimum) > float(self.maximum):
                raise ValueError(
                    f"Native control '{control_id}' minimum exceeds its maximum."
                )
        if self.kind is NativeControlKind.CHOICE and not self.choices:
            raise ValueError(
                f"Native choice control '{control_id}' requires choices."
            )
        object.__setattr__(self, "id", control_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "section", section)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_qml(self, surface_id: str = "") -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "objectName": self.id,
            "label": self.label,
            "kind": self.kind.value,
            "type": self.kind.value,
            "section": self.section,
            "description": self.description,
            "value": self.value,
            "defaultValue": self.default_value,
            "enabled": self.enabled,
            "secret": self.secret,
            "options": [choice.to_qml() for choice in self.choices],
            "native": True,
            "groupKey": self.section.lower().replace(" ", "_"),
            "groupTitle": self.section,
            "groupColumnSpan": 2,
        }
        if self.minimum is not None:
            payload["minimum"] = self.minimum
        if self.maximum is not None:
            payload["maximum"] = self.maximum
        if self.step is not None:
            payload["step"] = self.step
        payload.update(dict(self.metadata))
        from ui.qml_bridge.settings_help import field_help
        help_text = field_help(payload, surface_id)
        if help_text:
            payload["toolTip"] = help_text
        return payload


@dataclass(frozen=True, slots=True)
class NativeSurface:
    id: str
    title: str
    addon_id: str
    sections: tuple[str, ...]
    controls: tuple[NativeControl, ...]
    description: str = ""
    revision: int = 0

    def __post_init__(self) -> None:
        surface_id = str(self.id or "").strip()
        addon_id = str(self.addon_id or "").strip()
        if not surface_id or not addon_id:
            raise ValueError("Native surfaces require surface and addon ids.")
        control_ids = [control.id for control in self.controls]
        if len(control_ids) != len(set(control_ids)):
            raise ValueError(f"Native surface '{surface_id}' has duplicate controls.")
        normalized_sections = tuple(
            dict.fromkeys(
                str(section or "Overview").strip() or "Overview"
                for section in self.sections
            )
        )
        object.__setattr__(self, "id", surface_id)
        object.__setattr__(self, "addon_id", addon_id)
        object.__setattr__(self, "sections", normalized_sections or ("Overview",))

    def to_qml_controls(self) -> list[dict[str, object]]:
        return [control.to_qml(self.id) for control in self.controls]


def choices(values: Iterable[tuple[object, str]]) -> tuple[NativeChoice, ...]:
    return tuple(NativeChoice(value=value, label=str(label)) for value, label in values)


__all__ = [
    "NativeChoice",
    "NativeControl",
    "NativeControlKind",
    "NativeSurface",
    "choices",
]
