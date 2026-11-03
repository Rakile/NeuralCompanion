"""Native QML surface for Conversation Replay."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


class ChatReplayNativeAdapter(NativeSurfaceAdapter):
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
        self._controls = {control.id: control for control in surface.controls}
        self._persist = persist
        self._revision = 0

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Conversation Replay is unavailable."))
            )
        return result.value

    def snapshot(self) -> NativeSurface:
        state_value = self._invoke("runtime.chat_replay.snapshot")
        state = dict(state_value or {})
        messages = tuple(
            NativeChoice(
                value=dict(item or {}).get("value"),
                label=str(dict(item or {}).get("label") or "Message"),
            )
            for item in list(state.get("messages") or [])
        )
        voices = tuple(
            NativeChoice(
                value=str(dict(item or {}).get("value") or ""),
                label=str(dict(item or {}).get("label") or "Voice"),
            )
            for item in list(state.get("voice_options") or [])
        ) or (NativeChoice(value="", label="Use current TTS voice"),)
        has_messages = bool(state.get("has_messages"))
        values = {
            "chat_replay_intro": (
                "Load a saved conversation and replay individual messages or the full chat."
            ),
            "chat_replay_summary": str(state.get("summary") or "No conversation loaded."),
            "chat_replay_session_help": (
                "Load opens a saved context; Quick Load uses NeuralCompanion's quick-save context."
            ),
            "chat_replay_messages_help": (
                "Select a message to start replay at that point."
            ),
            "chat_replay_status": str(state.get("status") or "Conversation Replay ready."),
        }
        controls = []
        for control in self._surface.controls:
            if control.id in values:
                control = replace(control, value=values[control.id])
            elif control.id == "chat_replay_messages":
                control = replace(
                    control,
                    value=state.get("selected_index"),
                    choices=messages,
                )
            elif control.id == "chat_replay_assistant_voice":
                control = replace(
                    control,
                    value=str(state.get("assistant_voice") or ""),
                    choices=voices,
                )
            elif control.id == "chat_replay_user_voice":
                control = replace(
                    control,
                    value=str(state.get("user_voice") or ""),
                    choices=voices,
                )
            elif control.id in {
                "chat_replay_previous",
                "chat_replay_next",
                "chat_replay_selected",
                "chat_replay_latest",
                "chat_replay_chat",
            }:
                control = replace(control, enabled=has_messages)
            controls.append(control)
        return replace(
            self._surface,
            controls=apply_card_layout(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key == "chat_replay_messages":
            self._invoke(
                "runtime.chat_replay.select",
                {"replay_index": int(value or 0)},
            )
        elif key in {"chat_replay_assistant_voice", "chat_replay_user_voice"}:
            self._invoke(
                "runtime.chat_replay.set_voice",
                {
                    "role": "assistant" if "assistant" in key else "user",
                    "path": str(value or ""),
                },
            )
            if callable(self._persist):
                self._persist()
        else:
            raise KeyError(f"Unknown Conversation Replay setting '{control_id}'.")
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        action_map = {
            "chat_replay_load": "load",
            "chat_replay_quick_load": "quick_load",
            "chat_replay_refresh": "refresh",
            "chat_replay_previous": "previous",
            "chat_replay_next": "next",
            "chat_replay_selected": "replay_selected",
            "chat_replay_latest": "replay_latest",
            "chat_replay_chat": "replay_chat",
            "chat_replay_refresh_voices": "refresh_voices",
        }
        action = action_map.get(str(control_id or "").strip())
        if action is None:
            raise KeyError(f"Unknown Conversation Replay action '{control_id}'.")
        self._invoke("runtime.chat_replay.action", {"action": action})
        self._revision += 1
        self.changed.emit()


def build_chat_replay_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> ChatReplayNativeAdapter:
    ui_action = {"execution": "ui"}
    surface = NativeSurface(
        id="chat_session_player_tab",
        title="Conversation Replay",
        addon_id="nc.chat_session_player",
        sections=("Overview", "Session", "Messages", "Replay voices"),
        description="Load and replay saved NeuralCompanion conversations.",
        controls=(
            NativeControl("chat_replay_intro", "Conversation Replay", NativeControlKind.DISPLAY, "Overview"),
            NativeControl("chat_replay_summary", "Session summary", NativeControlKind.DISPLAY, "Overview"),
            NativeControl("chat_replay_session_help", "Session loading", NativeControlKind.DISPLAY, "Session"),
            NativeControl("chat_replay_load", "Load chat context", NativeControlKind.ACTION, "Session", metadata=ui_action),
            NativeControl("chat_replay_quick_load", "Quick Load", NativeControlKind.ACTION, "Session", metadata=ui_action),
            NativeControl("chat_replay_refresh", "Refresh", NativeControlKind.ACTION, "Session"),
            NativeControl("chat_replay_messages_help", "Replayable messages", NativeControlKind.DISPLAY, "Messages"),
            NativeControl("chat_replay_messages", "Messages", NativeControlKind.LIST, "Messages", choices=(NativeChoice(value=0, label="No messages"),)),
            NativeControl("chat_replay_previous", "Previous", NativeControlKind.ACTION, "Messages", metadata=ui_action),
            NativeControl("chat_replay_next", "Next", NativeControlKind.ACTION, "Messages", metadata=ui_action),
            NativeControl("chat_replay_selected", "Replay from selected", NativeControlKind.ACTION, "Messages", metadata=ui_action),
            NativeControl("chat_replay_latest", "Replay latest reply", NativeControlKind.ACTION, "Messages", metadata=ui_action),
            NativeControl("chat_replay_chat", "Replay complete chat", NativeControlKind.ACTION, "Messages", metadata=ui_action),
            NativeControl("chat_replay_status", "Replay status", NativeControlKind.DISPLAY, "Messages"),
            NativeControl("chat_replay_assistant_voice", "Assistant voice", NativeControlKind.CHOICE, "Replay voices", choices=(NativeChoice(value="", label="Use current TTS voice"),)),
            NativeControl("chat_replay_user_voice", "User voice", NativeControlKind.CHOICE, "Replay voices", choices=(NativeChoice(value="", label="Use current TTS voice"),)),
            NativeControl("chat_replay_refresh_voices", "Refresh voices", NativeControlKind.ACTION, "Replay voices"),
        ),
    )
    return ChatReplayNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["ChatReplayNativeAdapter", "build_chat_replay_adapter"]
