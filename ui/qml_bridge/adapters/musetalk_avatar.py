"""Native QML surface for the MuseTalk avatar runtime provider."""

from __future__ import annotations

import json
import hashlib
import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable

from addons.musetalk_avatar.pack_runtime import normalize_enabled_pack_emotions
from ui.qml_bridge.adapters.avatar_package_actions import can_maintain_packages, package_maintenance
from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)


class MuseTalkAvatarNativeAdapter(RuntimeConfigNativeAdapter):
    _DISPLAY_IDS = {
        "musetalk_runtime_summary",
        "musetalk_runtime_status",
        "musetalk_pack_status",
        "musetalk_pack_default_avatar",
        "musetalk_pack_emotions_status",
    }

    def __init__(self, *args, **kwargs) -> None:
        self._focus_request = kwargs.pop("focus_request", None)
        super().__init__(*args, **kwargs)
        self._last_action = ""
        self._pack_catalog: dict[str, dict[str, object]] = {}
        self._pack_error = ""
        self._emotion_bindings: dict[str, tuple[str, str]] = {}
        self._refresh_pack_catalog()

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id, capability, dict(payload or {})
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "MuseTalk is unavailable."))
            )
        return result.value

    def _refresh_pack_catalog(self) -> None:
        try:
            raw = self._invoke("runtime.discover_avatar_packs")
            self._pack_catalog = {
                str(item.get("id")): dict(item)
                for item in (raw or ())
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            }
            self._pack_error = ""
        except BaseException as exc:
            self._pack_catalog = {}
            self._pack_error = str(exc).strip() or "Avatar pack discovery failed."

    def snapshot(self) -> NativeSurface:
        self._refresh_pack_catalog()
        surface = super().snapshot()
        config = dict(self._application.config.snapshot().values)
        pack_id = str(config.get("musetalk_avatar_pack_id") or "").strip()
        pack = self._pack_catalog.get(pack_id, {})
        avatar_id = str(pack.get("default_avatar_id") or "Unavailable")
        choice_items = [NativeChoice("", "Choose a discovered MuseTalk pack...")]
        for discovered_id, discovered_pack in self._pack_catalog.items():
            label = str(discovered_pack.get("display_name") or discovered_id)
            choice_items.append(NativeChoice(discovered_id, label))
        if pack_id and pack_id not in self._pack_catalog:
            choice_items.append(NativeChoice(pack_id, f"Unavailable: {pack_id}"))

        if self._pack_error:
            pack_status = f"Pack discovery error: {self._pack_error}"
        elif not self._pack_catalog:
            pack_status = "No prepared MuseTalk avatar packs were found."
        elif not pack_id:
            pack_status = (
                f"{len(self._pack_catalog)} pack(s) available. Choose a prepared pack."
            )
        elif pack_id not in self._pack_catalog:
            pack_status = (
                f"Selected pack '{pack_id}' is unavailable. Refresh or choose another pack."
            )
        else:
            pack = self._pack_catalog[pack_id]
            pack_status = "Selected: " + str(pack.get("display_name") or pack_id)

        values = {
            "musetalk_runtime_summary": (
                "MuseTalk renders the selected prepared avatar and uses the "
                "shared preprocessing workspace for source, mask, and cache tools."
            ),
            "musetalk_runtime_status": (
                f"Pack: {pack_id or 'not selected'} - Avatar: {avatar_id}"
                + (f" - {self._last_action}" if self._last_action else "")
            ),
            "musetalk_pack_status": pack_status,
            "musetalk_pack_default_avatar": avatar_id,
        }
        controls = []
        for control in surface.controls:
            if control.id in values:
                control = replace(control, value=values[control.id])
            elif control.id == "musetalk_avatar_pack_id":
                control = replace(
                    control,
                    value=pack_id,
                    choices=tuple(choice_items),
                )
            controls.append(control)
        name = str(pack.get("display_name") or pack_id)
        controls.append(NativeControl(
            "musetalk_delete_package", "Delete package permanently", NativeControlKind.ACTION, "Avatar",
            enabled=bool(pack_id and pack.get("delete_token") and can_maintain_packages(self._application)),
            description="Permanently delete the selected prepared package. External source media is preserved.",
            metadata={"execution": "worker", "destructive": True,
                      "confirmationTitle": "Delete MuseTalk package permanently?",
                      "confirmationText": f'Permanently delete "{name}"? This cannot be undone. External source media is preserved. Unload the MuseTalk worker first.',
                      "confirmationAcceptText": "Delete permanently",
                      "confirmationPayload": {"pack_id": pack_id, "token": str(pack.get("delete_token") or ""), "confirmed": True}},
        ))
        controls.extend(self._emotion_controls(pack_id, pack))
        return replace(
            surface,
            controls=apply_card_layout(tuple(controls)),
            revision=self._revision,
        )

    def _saved_enabled_emotions(self) -> dict[str, list[str]]:
        # RuntimeConfigCommands.get() returns immutable public values, including
        # MappingProxyType. The legacy normalizer accepts dicts and tuple tags.
        value = self._application.config.get("musetalk_enabled_pack_emotions", {})
        return normalize_enabled_pack_emotions(dict(value) if isinstance(value, Mapping) else value)

    def _emotion_controls(self, pack_id: str, pack: dict) -> list[NativeControl]:
        mapping = dict(pack.get("emotion_avatar_map") or {})
        stored = self._saved_enabled_emotions()
        enabled = set(stored.get(pack_id, mapping))
        self._emotion_bindings = {}
        controls = []
        for tag, avatar_id in sorted(mapping.items()):
            digest = hashlib.sha256(f"{pack_id}\0{tag}".encode("utf-8")).hexdigest()[:16]
            control_id = f"musetalk_runtime_emotion_{digest}"
            self._emotion_bindings[control_id] = (pack_id, tag)
            locked = avatar_id == pack.get("default_avatar_id")
            controls.append(NativeControl(
                control_id, str(tag).replace("_", " ").title(),
                NativeControlKind.BOOLEAN, "Pack emotions",
                value=locked or tag in enabled, enabled=not locked,
                description=f"{avatar_id}" + (" — base avatar; always enabled." if locked else ""),
                metadata={"groupKey": "pack_emotions", "groupTitle": "Pack emotions", "groupColumnSpan": 2},
            ))
        if not controls:
            controls.append(NativeControl(
                "musetalk_pack_emotions_status", "Pack emotions", NativeControlKind.DISPLAY,
                "Pack emotions", value=("No emotion tags are mapped in this pack." if pack
                                        else "Choose an available prepared pack to view its emotions."),
            ))
        return controls

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key in self._DISPLAY_IDS:
            raise KeyError(f"MuseTalk display '{control_id}' is read-only.")
        if key in self._emotion_bindings:
            pack_id, tag = self._emotion_bindings[key]
            if not isinstance(value, bool):
                raise TypeError("Emotion toggle value must be boolean.")
            self._refresh_pack_catalog()
            pack = self._pack_catalog.get(pack_id)
            selected = str(self._application.config.get("musetalk_avatar_pack_id", "") or "").strip()
            if selected != pack_id or pack is None:
                raise ValueError("The emotion toggle belongs to an unavailable or different pack.")
            mapping = dict(pack.get("emotion_avatar_map") or {})
            if tag not in mapping:
                raise KeyError("This emotion is no longer mapped in the selected pack.")
            locked = {name for name, avatar in mapping.items() if avatar == pack.get("default_avatar_id")}
            if tag in locked and not value:
                raise ValueError("Base avatar emotions are locked on.")
            stored = self._saved_enabled_emotions()
            enabled = set(stored.get(pack_id, mapping)) | locked
            if value:
                enabled.add(tag)
            else:
                enabled.discard(tag)
            stored[pack_id] = sorted(enabled)
            result = self._application.config.update("musetalk_enabled_pack_emotions", stored)
            if not result.accepted:
                failure = getattr(result, "failure", None)
                raise RuntimeError(str(getattr(failure, "message", "Could not save pack emotions.")))
            self._revision += 1
            if callable(self._persist):
                self._persist()
            self.changed.emit()
            return
        if key == "musetalk_enabled_pack_emotions_json":
            try:
                parsed = json.loads(str(value or "{}"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Emotion map must be valid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError("Emotion map must be a JSON object.")
            result = self._application.config.update(
                "musetalk_enabled_pack_emotions", parsed
            )
            if not result.accepted:
                failure = getattr(result, "failure", None)
                raise RuntimeError(
                    str(getattr(failure, "message", "Could not save emotion map."))
                )
            self._revision += 1
            if callable(self._persist):
                self._persist()
            self.changed.emit()
            return
        if key == "musetalk_avatar_pack_id":
            selected = str(value or "").strip()
            if selected and selected not in self._pack_catalog:
                raise ValueError(
                    f"MuseTalk avatar pack '{selected}' is not currently available."
                )
            result = self._application.config.update(key, selected)
            if not result.accepted:
                failure = getattr(result, "failure", None)
                raise RuntimeError(
                    str(getattr(failure, "message", "Could not save MuseTalk pack."))
                )
            self._revision += 1
            if callable(self._persist):
                self._persist()
            self.changed.emit()
            return
        if key == "musetalk_progressive_buffer_seconds":
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("Progressive animation buffer must be a finite number.")
        super().set_value(key, value)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        if str(control_id or "").strip() != "musetalk_delete_package":
            self.trigger(control_id)
            return
        data = dict(payload) if isinstance(payload, Mapping) else {}
        if data.get("confirmed") is not True or not data.get("pack_id") or not data.get("token"):
            raise ValueError("Confirm the selected MuseTalk package before deleting it.")
        with package_maintenance(self._application):
            result = self._invoke("runtime.delete_package", data)
            if not isinstance(result, Mapping) or result.get("deleted") is not True:
                message = result.get("error") if isinstance(result, Mapping) else None
                raise RuntimeError(str(message or "Package deletion was not confirmed by MuseTalk. Refresh and try again."))
            if callable(self._persist):
                self._persist()
            self._refresh_pack_catalog()
            self._last_action = "Avatar package permanently deleted"
            self._revision += 1
            self.changed.emit()

    def trigger(self, control_id: str) -> None:
        action = str(control_id or "").strip()
        if action == "musetalk_reset_preview_zoom":
            self._invoke("runtime.preview.reset_zoom")
            self._last_action = "Preview zoom reset"
        elif action == "musetalk_toggle_avatar_focus":
            if not callable(self._focus_request):
                raise RuntimeError("The native avatar focus window is unavailable.")
            self._focus_request("MuseTalk")
            self._last_action = "Avatar focus toggled"
        elif action == "musetalk_refresh_avatar_packs":
            self._refresh_pack_catalog()
            self._last_action = "Avatar packs refreshed"
        else:
            raise KeyError(f"Unknown MuseTalk action '{control_id}'.")
        self._revision += 1
        self.changed.emit()


def build_musetalk_avatar_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
    focus_request: Callable[[str], object] | None = None,
) -> MuseTalkAvatarNativeAdapter:
    surface = NativeSurface(
        id="musetalk_avatar_tab",
        title="MuseTalk",
        addon_id="nc.musetalk_avatar",
        sections=("Overview", "Avatar", "Pack emotions", "Performance"),
        description="MuseTalk prepared avatar packs, enabled emotions, and runtime tuning.",
        controls=(
            NativeControl("musetalk_runtime_summary", "MuseTalk avatar runtime", NativeControlKind.DISPLAY, "Overview"),
            NativeControl("musetalk_runtime_status", "Current selection", NativeControlKind.DISPLAY, "Overview"),
            NativeControl("musetalk_pack_status", "Pack availability", NativeControlKind.DISPLAY, "Avatar"),
            NativeControl(
                "musetalk_avatar_pack_id",
                "Avatar pack",
                NativeControlKind.CHOICE,
                "Avatar",
                choices=(NativeChoice("", "Choose a discovered MuseTalk pack..."),),
            ),
            NativeControl(
                "musetalk_refresh_avatar_packs",
                "Refresh avatar packs",
                NativeControlKind.ACTION,
                "Avatar",
                metadata={"execution": "ui"},
            ),
            NativeControl("musetalk_pack_default_avatar", "Pack default avatar", NativeControlKind.DISPLAY, "Avatar"),
            NativeControl("musetalk_fps", "Render FPS", NativeControlKind.INTEGER, "Performance", default_value=24, minimum=1, maximum=120, step=1),
            NativeControl("musetalk_vram_mode", "VRAM mode", NativeControlKind.CHOICE, "Performance", default_value="balanced", choices=choices((("quality", "Quality"), ("balanced", "Balanced"), ("low", "Low VRAM"), ("very_low", "Very Low VRAM")))),
            NativeControl("musetalk_loop_fade_ms", "Loop fade (ms)", NativeControlKind.INTEGER, "Performance", default_value=180, minimum=0, maximum=5000, step=10),
            NativeControl(
                "musetalk_progressive_buffer_seconds",
                "Progressive animation buffer (seconds)",
                NativeControlKind.NUMBER,
                "Performance",
                default_value=2.0,
                minimum=0.5,
                maximum=4.0,
                step=0.5,
                description="Smaller buffers start sooner but can increase pauses and rendering overhead.",
                metadata={"toolTip": (
                    "Sets the first render segment and minimum ready-animation lead at startup "
                    "and after an underrun. Smaller buffers start sooner but can increase pauses "
                    "and rendering overhead. Changes apply to the next speech chunk; "
                    "later render segments remain 2 seconds. Rounded up to supported timing steps "
                    "(0.5 seconds at 24 FPS). The LiquidAI audio startup buffer remains a minimum. "
                    "Applies only to progressive local audio. Avatar pose transitions that need a complete "
                    "audio chunk still wait for it to finish generating."
                )},
            ),
            NativeControl("ua_companion_orb_send_musetalk_face_mask", "Send MuseTalk face mask to Companion Orb", NativeControlKind.BOOLEAN, "Performance", default_value=False),
        ),
    )
    return MuseTalkAvatarNativeAdapter(
        application_facade,
        surface,
        persist=persist,
        focus_request=focus_request,
    )


__all__ = ["MuseTalkAvatarNativeAdapter", "build_musetalk_avatar_adapter"]
