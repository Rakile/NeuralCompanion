"""Native QML adapter for the addon-owned User Identity profile."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping

from PySide6 import QtCore

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_PROFILE_AND_PORTRAIT_SECTION = "Profile & portrait"
_USER_IDENTITY_CARD_LAYOUT: dict[str, tuple[str, str, int]] = {
    "user_identity_overview": (
        "user_identity_overview",
        "How this profile is used",
        2,
    ),
    **{
        control_id: ("user_identity_profile", "Profile", 1)
        for control_id in (
            "user_identity_enabled",
            "user_identity_name",
            "user_identity_preferred_address",
            "user_identity_short_bio",
            "user_identity_interaction_notes",
        )
    },
    **{
        control_id: ("user_identity_portrait", "Portrait", 1)
        for control_id in (
            "user_identity_avatar_preview",
            "user_identity_choose_portrait",
            "user_identity_generate_portrait",
            "user_identity_clear_portrait",
            "user_identity_visual_prompt",
            "user_identity_refine_prompt",
            "user_identity_transparent_portrait",
            "user_identity_generation_status",
        )
    },
}


def _apply_user_identity_layout(
    controls: list[NativeControl] | tuple[NativeControl, ...],
) -> tuple[NativeControl, ...]:
    """Keep profile and portrait as separate half-width cards on one tab."""

    rendered = apply_card_layout(controls, overrides=_USER_IDENTITY_CARD_LAYOUT)
    compact_groups = {"user_identity_profile", "user_identity_portrait"}
    return tuple(
        replace(
            control,
            metadata={**dict(control.metadata), "groupColumnSpan": 1},
        )
        if str(control.metadata.get("groupKey") or "") in compact_groups
        else control
        for control in rendered
    )


def _local_path(payload: object) -> str:
    values = list(payload or []) if isinstance(payload, (list, tuple)) else [payload]
    text = str(values[0] if values else "").strip()
    url = QtCore.QUrl(text)
    return url.toLocalFile() if url.isLocalFile() else text


def _local_url(path: object) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    candidate = Path(text).expanduser()
    if not candidate.is_file():
        return ""
    return QtCore.QUrl.fromLocalFile(str(candidate.resolve())).toString()


def _bounded_strength(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


class UserIdentityNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._persist = persist
        self._revision = 0
        self._generation_lock = threading.RLock()
        self._pending_request_id = ""
        self._generation_started_at = 0.0
        self._generation_status = "Ready to import or generate a user portrait."

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "User Identity is unavailable."))
            )
        return result.value

    def _snapshot_payload(self) -> dict[str, object]:
        value = self._invoke("runtime.user_identity.snapshot")
        if not isinstance(value, Mapping):
            raise RuntimeError("User Identity snapshot is unavailable.")
        return dict(value)

    def snapshot(self) -> NativeSurface:
        payload = self._snapshot_payload()
        with self._generation_lock:
            pending = bool(self._pending_request_id)
            status = self._generation_status
        values: dict[str, object] = {
            "user_identity_overview": (
                "This local profile helps the active persona address the user naturally. "
                "It is attached to each LLM request as temporary addon context; it is not "
                "written into chat history, continuity memory, or Long-Term Memory."
            ),
            "user_identity_enabled": bool(payload.get("enabled", True)),
            "user_identity_name": str(payload.get("name") or ""),
            "user_identity_preferred_address": str(
                payload.get("preferred_address") or ""
            ),
            "user_identity_short_bio": str(payload.get("short_bio") or ""),
            "user_identity_interaction_notes": str(
                payload.get("interaction_notes") or ""
            ),
            "user_identity_avatar_preview": _local_url(payload.get("avatar_path")),
            "user_identity_visual_prompt": str(
                payload.get("visual_identity_prompt") or ""
            ),
            "user_identity_show_avatar": bool(
                payload.get("show_avatar_in_conversation", True)
            ),
            "user_identity_include_context": bool(
                payload.get("include_request_context", True)
            ),
            "user_identity_visual_reference": bool(
                payload.get("visual_reference_enabled", True)
            ),
            "user_identity_visual_policy": str(
                payload.get("visual_policy") or "requested"
            ),
            "user_identity_reference_strength": _bounded_strength(
                payload.get("reference_strength"), 0.52
            ),
            "user_identity_transparent_portrait": bool(
                payload.get("transparent_portrait", False)
            ),
            "user_identity_generation_status": status,
        }
        controls = []
        for control in self._surface.controls:
            updates: dict[str, object] = {
                "value": values.get(control.id, control.default_value)
            }
            if control.id == "user_identity_generate_portrait":
                updates["enabled"] = not pending
                updates["label"] = "Generating portrait..." if pending else control.label
            elif control.id in {
                "user_identity_clear_portrait",
                "user_identity_refine_prompt",
            }:
                updates["enabled"] = not pending and (
                    bool(payload.get("avatar_ready", False))
                    if control.id == "user_identity_clear_portrait"
                    else True
                )
            controls.append(replace(control, **updates))
        return replace(
            self._surface,
            controls=_apply_user_identity_layout(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        fields = {
            "user_identity_enabled": "enabled",
            "user_identity_name": "name",
            "user_identity_preferred_address": "preferred_address",
            "user_identity_short_bio": "short_bio",
            "user_identity_interaction_notes": "interaction_notes",
            "user_identity_visual_prompt": "visual_identity_prompt",
            "user_identity_show_avatar": "show_avatar_in_conversation",
            "user_identity_include_context": "include_request_context",
            "user_identity_visual_reference": "visual_reference_enabled",
            "user_identity_visual_policy": "visual_policy",
            "user_identity_reference_strength": "reference_strength",
            "user_identity_transparent_portrait": "transparent_portrait",
        }
        profile_key = fields.get(key)
        if profile_key is None:
            raise KeyError(f"Unknown User Identity setting '{control_id}'.")
        self._invoke(
            "runtime.user_identity.update",
            {"patch": {profile_key: value}},
        )
        if callable(self._persist):
            self._persist()
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        action = str(control_id or "").strip()
        if action == "user_identity_choose_portrait":
            path = _local_path(payload)
            if not path:
                return
            self._invoke("runtime.user_identity.import_avatar", {"path": path})
            self._set_generation_status("User portrait imported and ready.")
        elif action == "user_identity_clear_portrait":
            self._invoke("runtime.user_identity.clear_avatar")
            self._set_generation_status("User portrait cleared.")
        elif action == "user_identity_refine_prompt":
            self._invoke("runtime.user_identity.refine_prompt")
            self._set_generation_status("User visual identity prompt refined.")
        elif action == "user_identity_generate_portrait":
            value = self._invoke("runtime.user_identity.generate_portrait")
            result = dict(value) if isinstance(value, Mapping) else {}
            request_id = str(result.get("request_id") or "").strip()
            if not bool(result.get("accepted", False)) or not request_id:
                raise RuntimeError("Visual Reply did not return a portrait request id.")
            with self._generation_lock:
                self._pending_request_id = request_id
                self._generation_started_at = time.monotonic()
                self._generation_status = "Generating the user identity portrait..."
        else:
            raise KeyError(f"Unknown User Identity action '{control_id}'.")
        self._revision += 1
        self.changed.emit()

    def poll_generation(self) -> bool:
        with self._generation_lock:
            request_id = self._pending_request_id
            started_at = self._generation_started_at
        if not request_id:
            return False
        if time.monotonic() - started_at > 240.0:
            self._finish_generation("User portrait generation timed out.")
            return True
        result = self._application.addons.invoke_addon_capability(
            "nc.visual_reply",
            "runtime.current_state",
            {},
        )
        if not result.accepted or not isinstance(result.value, Mapping):
            return False
        state = dict(result.value)
        if str(state.get("request_id") or "").strip() != request_id:
            return False
        status = str(state.get("status") or "").strip().lower()
        if status in {"error", "failed"}:
            self._finish_generation(
                str(state.get("detail_text") or "User portrait generation failed.")
            )
            return True
        image_path = str(state.get("image_path") or "").strip()
        if status != "ready" or not image_path:
            return False
        try:
            self._invoke("runtime.user_identity.import_avatar", {"path": image_path})
        except (RuntimeError, TypeError, ValueError) as error:
            self._finish_generation(f"Could not save the generated portrait: {error}")
        else:
            self._finish_generation("Generated user portrait saved and ready.")
        return True

    def generation_pending(self) -> bool:
        with self._generation_lock:
            return bool(self._pending_request_id)

    def _set_generation_status(self, status: str) -> None:
        with self._generation_lock:
            self._generation_status = str(status or "")

    def _finish_generation(self, status: str) -> None:
        with self._generation_lock:
            self._pending_request_id = ""
            self._generation_started_at = 0.0
            self._generation_status = str(status or "")
        self._revision += 1
        self.changed.emit()


def build_user_identity_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> UserIdentityNativeAdapter:
    surface = NativeSurface(
        id="user_identity_tab",
        title="User Identity",
        addon_id="nc.user_identity",
        sections=(_PROFILE_AND_PORTRAIT_SECTION, "Visual Replies", "Privacy"),
        description=(
            "A local identity reference for the human user. The profile remains "
            "separate from persona and memory storage."
        ),
        controls=(
            NativeControl(
                "user_identity_overview",
                "How this profile is used",
                NativeControlKind.DISPLAY,
                _PROFILE_AND_PORTRAIT_SECTION,
                metadata={"groupColumnSpan": 2},
            ),
            NativeControl(
                "user_identity_enabled",
                "Enable User Identity",
                NativeControlKind.BOOLEAN,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="Master switch for profile context, user avatar, and user image references.",
                default_value=True,
            ),
            NativeControl(
                "user_identity_name",
                "Name",
                NativeControlKind.TEXT,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="The name the companion should associate with the human user.",
            ),
            NativeControl(
                "user_identity_preferred_address",
                "Preferred form of address",
                NativeControlKind.TEXT,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="Optional nickname, title, or form of address.",
            ),
            NativeControl(
                "user_identity_short_bio",
                "Short bio",
                NativeControlKind.MULTILINE,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="Compact background information useful in normal conversation.",
                metadata={"editorPreferredHeight": 108, "scrollable": True},
            ),
            NativeControl(
                "user_identity_interaction_notes",
                "Interaction notes",
                NativeControlKind.MULTILINE,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="Preferences the companion should know when speaking with the user.",
                metadata={"editorPreferredHeight": 108, "scrollable": True},
            ),
            NativeControl(
                "user_identity_avatar_preview",
                "Accepted user portrait",
                NativeControlKind.IMAGE,
                _PROFILE_AND_PORTRAIT_SECTION,
                metadata={
                    "readOnly": True,
                    "imagePreferredWidth": 300,
                    "imagePreferredHeight": 300,
                    "imagePlaceholder": "Import or generate a portrait to establish the user's visual identity.",
                    "groupColumnSpan": 1,
                },
            ),
            NativeControl(
                "user_identity_choose_portrait",
                "Choose portrait",
                NativeControlKind.ACTION,
                _PROFILE_AND_PORTRAIT_SECTION,
                metadata={
                    "execution": "ui",
                    "filePicker": True,
                    "dialogTitle": "Choose the user identity portrait",
                    "nameFilters": [
                        "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
                        "All files (*)",
                    ],
                },
            ),
            NativeControl(
                "user_identity_generate_portrait",
                "Generate portrait",
                NativeControlKind.ACTION,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="Use the configured Visual Reply provider without changing its saved provider selection.",
            ),
            NativeControl(
                "user_identity_clear_portrait",
                "Clear portrait",
                NativeControlKind.ACTION,
                _PROFILE_AND_PORTRAIT_SECTION,
                metadata={"destructive": True},
            ),
            NativeControl(
                "user_identity_visual_prompt",
                "Stable visual identity prompt",
                NativeControlKind.MULTILINE,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="Describe only stable appearance and style, not a scene or temporary pose.",
                metadata={"editorPreferredHeight": 132, "groupColumnSpan": 2},
            ),
            NativeControl(
                "user_identity_refine_prompt",
                "Refine identity prompt",
                NativeControlKind.ACTION,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="Ask the active LLM to keep only stable visual traits.",
            ),
            NativeControl(
                "user_identity_transparent_portrait",
                "Request transparent portrait background",
                NativeControlKind.BOOLEAN,
                _PROFILE_AND_PORTRAIT_SECTION,
                description="Requests real PNG alpha for newly generated portraits; imported images are left unchanged.",
                default_value=False,
            ),
            NativeControl(
                "user_identity_generation_status",
                "Portrait status",
                NativeControlKind.DISPLAY,
                _PROFILE_AND_PORTRAIT_SECTION,
                metadata={"readOnly": True},
            ),
            NativeControl(
                "user_identity_show_avatar",
                "Show the user avatar on user messages",
                NativeControlKind.BOOLEAN,
                "Visual Replies",
                default_value=True,
            ),
            NativeControl(
                "user_identity_visual_reference",
                "Allow Visual Replies to use the user portrait",
                NativeControlKind.BOOLEAN,
                "Visual Replies",
                default_value=True,
            ),
            NativeControl(
                "user_identity_visual_policy",
                "When the user may appear",
                NativeControlKind.CHOICE,
                "Visual Replies",
                default_value="requested",
                choices=(
                    NativeChoice("requested", "Include user when asked"),
                    NativeChoice("allowed", "LLM may include user"),
                    NativeChoice("never", "Never include user"),
                ),
            ),
            NativeControl(
                "user_identity_reference_strength",
                "User reference strength",
                NativeControlKind.SLIDER,
                "Visual Replies",
                default_value=0.52,
                minimum=0.0,
                maximum=1.0,
                step=0.01,
            ),
            NativeControl(
                "user_identity_include_context",
                "Include name and bio in current LLM requests",
                NativeControlKind.BOOLEAN,
                "Privacy",
                description="Request-only prompt context; it is not appended to canonical history or memory.",
                default_value=True,
            ),
        ),
    )
    return UserIdentityNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["UserIdentityNativeAdapter", "build_user_identity_adapter"]
