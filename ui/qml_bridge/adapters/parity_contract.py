"""Helpers for rendering reviewed legacy-parity inventories as native controls."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind, choices


_KINDS = {kind.value: kind for kind in NativeControlKind}


def controls_from_specs(specs: Iterable[Mapping[str, Any]]) -> tuple[NativeControl, ...]:
    controls: list[NativeControl] = []
    for raw in specs:
        spec = dict(raw)
        control_id = str(spec.get("id") or "").strip()
        kind = _KINDS[str(spec.get("kind") or "text")]
        option_values = tuple(spec.get("choices") or ())
        if kind is NativeControlKind.CHOICE and not option_values:
            option_values = ((spec.get("default"), "No options available"),)
        metadata = dict(spec.get("metadata") or {})
        if bool(spec.get("read_only")):
            metadata["readOnly"] = True
        if kind is NativeControlKind.MULTILINE:
            metadata.setdefault("rows", 8)
        controls.append(
            NativeControl(
                id=control_id,
                label=str(spec.get("label") or control_id),
                kind=kind,
                section=str(spec.get("section") or "Overview"),
                default_value=spec.get("default"),
                enabled=not bool(spec.get("read_only")),
                secret=bool(spec.get("secret")),
                minimum=spec.get("minimum"),
                maximum=spec.get("maximum"),
                step=spec.get("step"),
                choices=choices(option_values),
                metadata=metadata,
            )
        )
    return tuple(controls)


def sections_from_specs(specs: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(spec.get("section") or "Overview") for spec in specs))


__all__ = ["controls_from_specs", "sections_from_specs"]
