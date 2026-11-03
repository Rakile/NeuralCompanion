"""Complete typed native-QML adapter for Multi Persona Roleplay."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from PySide6 import QtCore, QtGui

from addons.multi_persona_roleplay.native_contract import MPRC_CONTROL_SPECS
from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.native_commands import NativeCommandRunner
from ui.qml_bridge.native_contracts import (
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter

_KIND_BY_NAME = {kind.value: kind for kind in NativeControlKind}
_SECTIONS = tuple(dict.fromkeys(str(spec[3]) for spec in MPRC_CONTROL_SPECS))
_ACTION_METADATA = {
    str(spec[0]): dict(spec[8])
    for spec in MPRC_CONTROL_SPECS
    if str(spec[2]) == NativeControlKind.ACTION.value
}

_RANGES: dict[str, tuple[float, float, float]] = {
    "mprc_visual_interval": (1, 100, 1),
    "mprc_visual_cooldown": (0, 86400, 1),
    "mprc_visual_max_auto": (0, 100, 1),
    "mprc_audiofx_volume": (0, 100, 1),
    "mprc_master_story_native_persona_count": (0, 24, 1),
    "mprc_master_story_max_created_characters": (1, 40, 1),
    "mprc_ar_tension": (0, 10, 1),
    "mprc_buffer_race_render_bar": (0, 100, 1),
    "mprc_buffer_race_playback_bar": (0, 100, 1),
    "mprc_chat_voice_volume_slider": (0, 100, 1),
    "mprc_chat_story_font_size_spin": (8, 48, 1),
    "mprc_chat_remote_port_spin": (1, 65535, 1),
    "mprc_chat_remote_code_spin": (100000, 999999, 1),
}


def _build_control(spec: tuple[object, ...]) -> NativeControl:
    control_id, label, kind_name, section, default, raw_choices, read_only, secret, raw_metadata = spec
    kind = _KIND_BY_NAME[str(kind_name)]
    metadata = dict(raw_metadata or {})
    if bool(read_only):
        metadata["readOnly"] = True
    if kind is NativeControlKind.MULTILINE:
        metadata.setdefault("rows", 8)
    minimum = maximum = step = None
    if str(control_id) in _RANGES:
        minimum, maximum, step = _RANGES[str(control_id)]
    return NativeControl(
        id=str(control_id),
        label=str(label),
        kind=kind,
        section=str(section),
        default_value=default,
        enabled=not bool(read_only),
        secret=bool(secret),
        minimum=minimum,
        maximum=maximum,
        step=step,
        choices=choices(tuple(raw_choices or ())),
        metadata=metadata,
    )


class MultiPersonaRoleplayNativeAdapter(NativeSurfaceAdapter):
    """Expose the reviewed MPRC surface without JSON flattening."""

    def __init__(self, application_facade: Any, parent=None) -> None:
        super().__init__("multi_persona_roleplay_tab", "nc.multi_persona_roleplay", parent)
        self._application = application_facade
        self._revision = 0
        self._last_action = ""
        self._state: dict[str, Any] | None = None
        self._last_refresh = 0.0
        self._refresh_worker = NativeCommandRunner(self, max_workers=1)
        self._refresh_worker.completed.connect(self._refresh_completed)
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._refresh_worker.close)
        self._surface = NativeSurface(
            id=self.surface_id,
            title="Multi Persona Roleplay",
            addon_id=self.addon_id,
            sections=_SECTIONS,
            description=(
                "Persona registry, roleplay session, voice routing, story images and "
                "sounds, Master Story, diagnostics, guide, and remote Play controls."
            ),
            controls=apply_card_layout(
                _build_control(spec) for spec in MPRC_CONTROL_SPECS
            ),
        )

    def _invoke(self, capability: str, payload: dict[str, Any] | None = None) -> Any:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(str(getattr(failure, "message", "MPRC is unavailable.")))
        return result.value

    def snapshot(self) -> NativeSurface:
        # An action may invalidate the shared cache from its registry worker.
        # Keep this read's dictionary stable across Qt submission/callbacks.
        state = self._state
        if state is None:
            # Preserve the existing bootstrap; subsequent view refreshes do all
            # storage/model work in the existing bounded Qt worker mechanism.
            state = dict(self._invoke("runtime.mprc.native_snapshot") or {})
            self._state = state
        elif time.monotonic() - self._last_refresh >= 0.25:
            self._last_refresh = time.monotonic()
            self._refresh_worker.submit("snapshot", lambda: self._invoke("runtime.mprc.native_snapshot"))
        controls_state = dict(state.get("controls") or {})
        values = dict(controls_state.get("values") or {})
        option_overrides = dict(controls_state.get("options") or {})
        enabled_overrides = dict(controls_state.get("enabled") or {})
        updated: list[NativeControl] = []
        for control in self._surface.controls:
            dynamic_choices = option_overrides.get(control.id)
            replacement_choices = (
                choices(tuple(tuple(item) for item in dynamic_choices))
                if isinstance(dynamic_choices, (list, tuple)) and dynamic_choices
                else control.choices
            )
            updated.append(
                replace(
                    control,
                    value=values.get(control.id, control.default_value),
                    choices=replacement_choices,
                    enabled=bool(enabled_overrides.get(control.id, control.enabled)),
                    metadata={**control.metadata, **({"chatAvatars": dict(state.get("presentation") or {}).get("chat_avatars", {})}
                              if control.id == "mprc_chat_transcript" else {}),
                              **({"scenarioBuilder": dict(state.get("presentation") or {}).get("scenario_builder", {})}
                                  if control.id == "mprc_scenario_builder" else {}),
                               **({"storyBrief": dict(state.get("presentation") or {}).get("story_brief", {})}
                                  if control.id == "mprc_story_brief" else {})},
                )
            )
        return replace(
            self._surface,
            controls=tuple(updated),
            revision=max(
                self._revision,
                int(dict(state.get("presentation") or {}).get("revision", 0) or 0),
            ),
        )

    @QtCore.Slot(str, bool, object, str)
    def _refresh_completed(self, _key: str, accepted: bool, result: object, _error: str) -> None:
        if accepted and isinstance(result, dict):
            if result != self._state:
                self._state = result
                self.changed.emit()
        elif self._state is not None:
            # A disconnected addon must not leave a stale "Speaking" indicator.
            presentation = dict(self._state.get("presentation") or {})
            chat = dict(presentation.get("chat_avatars") or {})
            if chat.get("speaker"):
                chat["speaker"] = {}
                self._state = {**self._state, "presentation": {**presentation, "chat_avatars": chat}}
                self.changed.emit()

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        self._refresh_worker.cancel("snapshot")
        result = self._invoke(
            "runtime.mprc.native_update_control",
            {"control_id": key, "value": value},
        )
        self._state = result if isinstance(result, dict) and "controls" in result else None
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        key = str(control_id or "").strip()
        if key not in _ACTION_METADATA:
            raise KeyError(f"Unknown MPRC action {control_id!r}.")
        metadata = _ACTION_METADATA[key]
        request: dict[str, Any] = {"payload": payload}
        if bool(metadata.get("destructive")):
            request["confirmed"] = True
        self._refresh_worker.cancel("snapshot")
        result = self._invoke(
            "runtime.mprc.native_action",
            {"action": key, "payload": request},
        )
        if key in {"mprc_scenario_builder", "mprc_scenario_play_panel"}:
            state = dict(self._state or {})
            state["presentation"] = {
                **dict(state.get("presentation") or {}),
                **dict((result or {}).get("presentation") or {}),
            }
            self._state = state
            self._last_refresh = 0.0
        elif key == "mprc_story_brief" and isinstance(result, dict) and "controls" in result:
            # This action already ran a complete snapshot on the command worker.
            # Retain it so GUI refresh does not repeat disk-backed bootstrap.
            self._state = result
            self._last_refresh = 0.0
        else:
            self._state = None
        if str(metadata.get("execution") or "") == "ui":
            presentation = (
                dict((result or {}).get("presentation") or {})
                if isinstance(result, dict)
                else {}
            )
            clipboard_text = str(presentation.get("clipboard_suggestion") or "")
            if clipboard_text:
                clipboard = QtGui.QGuiApplication.clipboard()
                if clipboard is None:
                    raise RuntimeError("The system clipboard is unavailable.")
                clipboard.setText(clipboard_text)
        self._last_action = key
        self._revision += 1
        self.changed.emit()


def build_multi_persona_roleplay_adapter(application_facade: Any) -> MultiPersonaRoleplayNativeAdapter:
    """Register UI without requiring the optional addon to be loaded."""
    return MultiPersonaRoleplayNativeAdapter(application_facade)


__all__ = ["MultiPersonaRoleplayNativeAdapter", "build_multi_persona_roleplay_adapter"]
