"""Native QML configuration for the Scenic Avatar provider."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)


def _file_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return Path(text).resolve().as_uri()
    except (OSError, ValueError):
        return ""


class ScenicAvatarNativeAdapter(RuntimeConfigNativeAdapter):
    _READ_ONLY_IDS = {
        "scenic_pack_status",
        "scenic_pack_preview",
        "scenic_pack_details",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._catalog: tuple[dict[str, object], ...] = ()
        self._catalog_error = ""
        self._refresh_catalog()

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id, capability, dict(payload or {})
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Scenic Avatar is unavailable."))
            )
        return result.value

    def _refresh_catalog(self) -> None:
        try:
            raw = self._invoke("runtime.discover_packs")
            self._catalog = tuple(
                dict(item)
                for item in (raw or ())
                if isinstance(item, Mapping) and str(item.get("id") or "").strip()
            )
            self._catalog_error = ""
        except BaseException as exc:
            self._catalog = ()
            self._catalog_error = str(exc).strip() or "Pack discovery failed."
        self._cache_rule_tags()

    def adopt_catalog(self, rows) -> None:
        self._catalog = tuple(dict(row) for row in rows if isinstance(row, Mapping))
        self._catalog_error = ""
        self._cache_rule_tags()
        self._revision += 1
        self.changed.emit()

    def _cache_rule_tags(self) -> None:
        catalog = {str(row['id']): list(row.get('tags', ())) for row in self._catalog}
        self._application.config.update('_scenic_rule_pack_catalog', catalog)

    def snapshot(self) -> NativeSurface:
        surface = super().snapshot()
        selected = str(self._application.config.get("scenic_pack_id", "") or "").strip()
        by_id = {str(item.get("id")): item for item in self._catalog}
        selected_item = by_id.get(selected)
        choice_items = [NativeChoice("", "Choose a discovered Scenic pack...")]
        choice_items.extend(
            NativeChoice(str(item["id"]), str(item.get("label") or item["id"]))
            for item in self._catalog
        )
        if selected and selected not in by_id:
            choice_items.append(NativeChoice(selected, f"Unavailable: {selected}"))

        if self._catalog_error:
            status = f"Pack discovery error: {self._catalog_error}"
        elif not self._catalog:
            status = "No Scenic packs found in ScenicPacks."
        elif not selected:
            status = f"{len(self._catalog)} pack(s) available. Choose one to activate it."
        elif selected_item is None:
            status = f"Selected pack '{selected}' is unavailable. Refresh or choose another pack."
        else:
            status = f"Selected: {selected_item.get('label') or selected}"

        preview = _file_url(
            selected_item.get("preview_path") if selected_item is not None else ""
        )
        details = ""
        if selected_item is not None:
            tags = ", ".join(str(tag) for tag in selected_item.get("tags", ()) if tag)
            details = (
                f"{int(selected_item.get('image_count', 0) or 0)} image(s)"
                + (f" - Tags: {tags}" if tags else " - No tagged images")
            )

        controls = []
        for control in surface.controls:
            if control.id == "scenic_pack_id":
                control = replace(control, value=selected, choices=tuple(choice_items))
            elif control.id == "scenic_pack_status":
                control = replace(control, value=status)
            elif control.id == "scenic_pack_preview":
                control = replace(control, value=preview)
            elif control.id == "scenic_pack_details":
                control = replace(control, value=details)
            controls.append(control)
        return replace(
            surface,
            controls=apply_card_layout(tuple(controls)),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key in self._READ_ONLY_IDS:
            raise KeyError(f"Scenic display '{key}' is read-only.")
        if key == "scenic_pack_id":
            selected = str(value or "").strip()
            known = {str(item.get("id")) for item in self._catalog}
            if selected and selected not in known:
                raise ValueError(f"Scenic pack '{selected}' is not currently available.")
            result = self._application.config.update(key, selected)
            if not result.accepted:
                failure = getattr(result, "failure", None)
                raise RuntimeError(
                    str(getattr(failure, "message", "Could not save Scenic pack."))
                )
            self._revision += 1
            if callable(self._persist):
                self._persist()
            self.changed.emit()
            return
        super().set_value(key, value)

    def trigger(self, control_id: str) -> None:
        if str(control_id or "").strip() != "scenic_refresh_packs":
            raise KeyError(f"Unknown Scenic action '{control_id}'.")
        self._refresh_catalog()
        self._revision += 1
        self.changed.emit()


def build_scenic_avatar_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> ScenicAvatarNativeAdapter:
    surface = NativeSurface(
        id="scenic_avatar_tab",
        title="Scenic Avatar",
        addon_id="nc.scenic_avatar",
        sections=("Overview", "Pack"),
        description="Select and preview a discovered tag-to-image Scenic pack.",
        controls=(
            NativeControl(
                "scenic_pack_status",
                "Pack availability",
                NativeControlKind.DISPLAY,
                "Overview",
            ),
            NativeControl(
                "scenic_pack_id",
                "Scenic pack",
                NativeControlKind.CHOICE,
                "Pack",
                choices=(NativeChoice("", "Choose a discovered Scenic pack..."),),
            ),
            NativeControl(
                "scenic_refresh_packs",
                "Refresh packs",
                NativeControlKind.ACTION,
                "Pack",
                metadata={},
            ),
            NativeControl(
                "scenic_pack_preview",
                "Selected pack preview",
                NativeControlKind.IMAGE,
                "Pack",
                metadata={
                    "imagePreferredWidth": 320,
                    "imagePreferredHeight": 240,
                    "imagePlaceholder": "The selected pack has no available preview image.",
                },
            ),
            NativeControl(
                "scenic_pack_details",
                "Pack contents",
                NativeControlKind.DISPLAY,
                "Pack",
            ),
        ),
    )
    return ScenicAvatarNativeAdapter(application_facade, surface, persist=persist)


__all__ = ["ScenicAvatarNativeAdapter", "build_scenic_avatar_adapter"]
