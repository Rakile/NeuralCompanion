"""Chat shortcuts to existing native addon controls, independent of the open tab."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6 import QtCore

from ui.qml_bridge.native_contracts import NativeControl
from ui.qml_bridge.native_registry import NativeSurfaceAdapter, NativeSurfaceRegistry


# These are live feature switches, not addon registration/restart settings.
ADDON_SWITCHES = {
    "orb": ("Companion Orb", "nc.companion_orb_overlay", "companion_orb_enabled_checkbox"),
    "presence": ("AI Presence", "nc.ai_presence_mode", "ai_presence_enabled"),
    "websearch": ("Web Search", "nc.web_intelligence", "web_intelligence_mode"),
    "spotify": ("Spotify Sense", "nc.spotify_sense", "spotify_sense_enabled"),
    "buddy": ("Buddy Chat", "nc.buddy_chat", "buddy_enabled"),
    "roleplay": ("Multi Persona Roleplay", "nc.multi_persona_roleplay", "mprc_enabled_checkbox"),
}
AUDIO_ACTIONS = {"play": "Start or resume Audio Story playback",
                 "pause": "Pause Audio Story playback", "stop": "Stop Audio Story playback"}


class ConversationAddonCommands(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, owner: Any, message: Callable[[str], None]) -> None:
        super().__init__(owner)
        self._owner = owner
        self._message = message
        self._registry: NativeSurfaceRegistry | None = getattr(owner, "_native_surfaces", None)
        self._pending: dict[tuple[str, str], str] = {}
        self._closed = False
        if self._registry is not None:
            self._registry.surfacesChanged.connect(self.changed)
            self._registry.surfaceChanged.connect(self._surface_changed)
            self._registry.actionCompleted.connect(self._completed)

    @QtCore.Slot(str)
    def _surface_changed(self, _surface: str) -> None:
        self.changed.emit()

    def _control(self, addon: str, control_id: str) -> tuple[NativeSurfaceAdapter, NativeControl]:
        if self._closed or self._owner.applicationClosing:
            raise RuntimeError("NC is closing")
        adapter = self._registry.adapter_for_addon(addon) if self._registry is not None else None
        if adapter is None:
            raise RuntimeError("Addon is not loaded")
        control = next((item for item in adapter.snapshot().controls if item.id == control_id), None)
        if control is None or not control.enabled:
            raise RuntimeError("Control unavailable; check the addon settings")
        return adapter, control

    def choices(self, prefix: str) -> list[dict[str, Any]]:
        rows = []
        entries = [(key, label, addon, control) for key, (label, addon, control) in ADDON_SWITCHES.items()]
        entries += [(f"audiostory {key}", label, "nc.audio_story_mode", f"audio_story_{key}_button")
                    for key, label in AUDIO_ACTIONS.items()]
        for command, label, addon, control_id in entries:
            if not command.startswith(prefix):
                continue
            try:
                adapter, control = self._control(addon, control_id)
                if command.startswith("audiostory"):
                    pending = any(surface == adapter.surface_id for surface, _ in self._pending)
                    detail = "Action pending" if pending else "Use current story"
                    enabled = not pending
                else:
                    value = control.value != "off" if command == "websearch" else bool(control.value)
                    detail, enabled = ("On" if value else "Off"), True
            except (KeyError, RuntimeError, TypeError, ValueError) as error:
                detail, enabled = str(error), False
            rows.append({"command": "/" + command, "description": label, "detail": detail, "enabled": enabled})
        return rows

    def execute(self, command: str, argument: str) -> dict[str, Any]:
        try:
            if command == "audiostory":
                return self._audio(argument.lower())
            if argument.lower() not in {"", "on", "off"}:
                raise ValueError(f"Use /{command}, /{command} on or /{command} off.")
            label, addon, control_id = ADDON_SWITCHES[command]
            adapter, control = self._control(addon, control_id)
            current = control.value != "off" if command == "websearch" else bool(control.value)
            desired = not current if not argument else argument.lower() == "on"
            if command == "websearch":
                # This existing switch persists the mode and queues server work.
                result = self._owner.setConversationWebSearchEnabled(desired)
                if not result.get("accepted"):
                    reason = str(result.get("reason") or "unavailable").replace("_", " ")
                    raise RuntimeError(f"Web Search: {reason}. Check the Web Search addon settings.")
                self._message("Web Search: starting" if result.get("starting") else f"Web Search: {'On' if desired else 'Off'}")
            else:
                if current != desired:
                    adapter.set_value(control_id, desired)
                self._message(f"{label}: {'On' if desired else 'Off'}")
            return {"action": "local"}
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            message = str(error)
            self._message(message)
            return {"action": "error", "message": message}

    def _audio(self, action: str) -> dict[str, Any]:
        if not action:
            return {"action": "complete", "text": "/audiostory "}
        action = {"on": "play", "start": "play", "off": "stop"}.get(action, action)
        if action not in AUDIO_ACTIONS:
            raise ValueError("Use /audiostory play, /audiostory pause or /audiostory stop.")
        control_id = f"audio_story_{action}_button"
        adapter, _control = self._control("nc.audio_story_mode", control_id)
        if any(surface == adapter.surface_id for surface, _ in self._pending):
            raise RuntimeError("The previous Audio Story action is still finishing.")
        assert self._registry is not None
        key = (adapter.surface_id, control_id)
        if not self._registry.trigger_async(*key):
            raise RuntimeError("Audio Story action is already pending.")
        self._pending[key] = action
        self._message(f"Audio Story {action} requested")
        return {"action": "local"}

    @QtCore.Slot(str, str, bool, str)
    def _completed(self, surface: str, control: str, accepted: bool, error: str) -> None:
        action = self._pending.pop((surface, control), None)
        if action is not None and not self._closed:
            # Accepted means the button handler ran. Playback may still be
            # buffering or the addon may have displayed its own warning.
            self._message(f"Audio Story {action} requested" if accepted else f"Audio Story: {error or 'action failed'}")
            self.changed.emit()

    def close(self) -> None:
        self._closed = True
        self._pending.clear()
