"""Phone-safe provider controls over NC's existing desktop TTS lifecycle."""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

_ID = re.compile(r"[a-z][a-z0-9_]{0,63}")
UNAVAILABLE = "TTS provider controls are unavailable. Update or restart NC desktop."
BUSY = "Finish or stop the current reply before changing TTS provider."
REJECTED = "TTS provider could not be changed. Check NC desktop."
_MESSAGES = frozenset({
    "", UNAVAILABLE, BUSY, REJECTED,
    "Loading the selected TTS provider…",
    "TTS provider could not start. Check its settings on NC desktop.",
    "TTS provider changed but its selection could not be saved. Check NC desktop.",
    "TTS provider is ready for new replies.",
    "That TTS provider is unavailable. Check NC desktop.",
    "That TTS provider is already selected.",
    "TTS selection saved for the next initialization.",
    "Check this provider's settings on NC desktop.",
})


def _message(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) and value in _MESSAGES else fallback


class TtsProviderGateway:
    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def _busy(self) -> bool:
        protocol = getattr(self.owner, "_phone_reply", None)
        if protocol is None:
            return False
        guard = getattr(protocol, "runtime_change_busy", None)
        if callable(guard) and guard():
            return True
        actions = protocol.conversation_actions_snapshot()
        # An uninitialized desktop may still save a provider choice for startup.
        return str(actions.get("disabled_reason") or "") not in {"", "runtime_stopped"}

    def _snapshot_main(self) -> dict[str, Any]:
        commands = getattr(self.owner, "remote_commands", None)
        callback = getattr(commands, "tts_provider_state", None)
        apply = getattr(commands, "tts_provider_apply", None)
        raw = callback() if callable(callback) else {}
        if not isinstance(raw, Mapping):
            raw = {}
        providers = []
        selected = raw.get("selected_provider_id")
        seen: set[str] = set()
        raw_providers = raw.get("providers")
        for item in raw_providers[:128] if isinstance(raw_providers, list) else []:
            if not isinstance(item, Mapping):
                continue
            identity = item.get("id")
            if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in seen:
                continue
            seen.add(identity)
            label = item.get("label")
            # Labels come from the installed catalog, never paths or config values.
            label = label if isinstance(label, str) and label.strip() else identity
            providers.append(dict(id=identity, label=label[:120], selected=identity == selected,
                available=item.get("available") is True,
                story_voices=item.get("story_voices") is True,
                progressive_audio=item.get("progressive_audio") is True,
                message=_message(item.get("message"))))
        available = raw.get("available") is True and callable(apply)
        loading = raw.get("loading") is True
        busy = raw.get("busy") is True or loading or self._busy()
        return dict(schema_version=1, available=available,
                    selected_provider_id=selected if isinstance(selected, str) and selected in seen else "",
                    loading=loading, busy=busy,
                    message=UNAVAILABLE if not available else BUSY if busy and not loading else _message(raw.get("message")),
                    providers=providers)

    def snapshot(self) -> dict[str, Any]:
        try:
            return self.owner._invoke_main(self._snapshot_main)
        except Exception:
            return dict(schema_version=1, available=False, selected_provider_id="", loading=False,
                        busy=True, message=UNAVAILABLE, providers=[])

    def select(self, provider_id: Any) -> dict[str, Any]:
        if not isinstance(provider_id, str) or not _ID.fullmatch(provider_id):
            raise ValueError("a valid provider_id from the TTS provider list is required")

        def apply() -> dict[str, Any]:
            state = self._snapshot_main()  # Recheck both ownership and host state on Qt's thread.
            if not state["available"]:
                return dict(accepted=False, message=UNAVAILABLE)
            if state["busy"] or state["loading"]:
                return dict(accepted=False, message=BUSY)
            choice = next((item for item in state["providers"] if item["id"] == provider_id), None)
            if choice is None or not choice["available"]:
                return dict(accepted=False, message="That TTS provider is unavailable. Check NC desktop.")
            result = self.owner.remote_commands.tts_provider_apply(provider_id)
            accepted = isinstance(result, Mapping) and result.get("accepted") is True
            return dict(accepted=accepted, message=_message(
                result.get("message") if isinstance(result, Mapping) else None,
                "Loading the selected TTS provider…" if accepted else REJECTED))

        try:
            return self.owner._invoke_main(apply)
        except Exception:
            return dict(accepted=False, message=REJECTED)
