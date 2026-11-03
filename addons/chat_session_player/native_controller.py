"""Headless conversation replay state used by the native QML surface."""

from __future__ import annotations

from pathlib import Path


_SESSION_KEY = "chat_session_player"
_ROLE_VOICES_KEY = "role_voices"
_LEGACY_ROLE_VOICES_KEY = "chat_replay_role_voices"


class NativeChatSessionPlayer:
    def __init__(self, capabilities=None) -> None:
        self.replay_service = getattr(capabilities, "replay", None)
        self.runtime_config = getattr(capabilities, "runtime_config", None)
        self.shell = getattr(capabilities, "shell", None)
        self._selected_replay_index: int | None = None

    @staticmethod
    def _voice_files() -> list[str]:
        try:
            return sorted(
                (item.name for item in (Path.cwd() / "voices").glob("*.wav") if item.is_file()),
                key=str.lower,
            )
        except OSError:
            return []

    def _role_voice_settings(self) -> dict:
        if self.runtime_config is None:
            return {}
        payload = self.runtime_config.get(_LEGACY_ROLE_VOICES_KEY, {}) or {}
        return dict(payload) if isinstance(payload, dict) else {}

    def set_role_voice(self, role: str, path: str) -> dict:
        normalized = str(role or "").strip().lower()
        if normalized not in {"assistant", "user"}:
            raise ValueError(f"Unsupported replay voice role: {role}")
        settings = self._role_voice_settings()
        settings[normalized] = str(path or "").strip()
        if self.runtime_config is not None:
            self.runtime_config.update(_LEGACY_ROLE_VOICES_KEY, settings)
        if self.shell is not None:
            self.shell.notify_settings_changed()
        return settings

    def _snapshot(self) -> tuple[dict, list[dict]]:
        if self.replay_service is None:
            return {"conversation_history": []}, []
        payload = dict(self.replay_service.snapshot_chat_session() or {})
        getter = getattr(self.replay_service, "replayable_chat_entries", None)
        replayable = list(getter() or []) if callable(getter) else []
        return payload, [
            {
                "replay_index": int(entry.get("replay_index", 0) or 0),
                "preview": str(entry.get("preview", "") or ""),
                "content": str(entry.get("content", "") or ""),
            }
            for entry in replayable
            if isinstance(entry, dict)
        ]

    def snapshot(self) -> dict:
        payload, replayable = self._snapshot()
        history = list(payload.get("conversation_history") or [])
        indexes = [int(item["replay_index"]) for item in replayable if int(item["replay_index"]) > 0]
        if self._selected_replay_index not in indexes:
            self._selected_replay_index = indexes[-1] if indexes else None
        running = bool(self.replay_service and self.replay_service.is_engine_running())
        offline = bool(self.replay_service and self.replay_service.is_offline_replay_only())
        runtime_text = "offline replay runtime active" if offline else "live runtime active" if running else "runtime stopped"
        selected = self._selected_replay_index
        voices = self._role_voice_settings()
        return {
            "summary": (
                f"Conversation turns: {len(history)}\n"
                f"Assistant turns: {sum(1 for item in history if str((item or {}).get('role') or '') == 'assistant')}\n"
                f"Replayable messages: {len(replayable)}\n"
                f"Runtime state: {runtime_text}"
            ),
            "messages": [
                {"value": item["replay_index"], "label": f"#{item['replay_index']:02d}  {item['preview'].strip()}"}
                for item in replayable
            ],
            "selected_index": selected,
            "status": (
                f"Selected message #{selected}. Start replay from here or move between messages."
                if selected is not None
                else "Load a chat context or build up a conversation before replaying."
            ),
            "assistant_voice": str(voices.get("assistant") or ""),
            "user_voice": str(voices.get("user") or ""),
            "voice_options": [
                {"value": "", "label": "Use current TTS voice"},
                *({"value": f"voices/{name}", "label": name} for name in self._voice_files()),
            ],
            "has_messages": bool(replayable),
        }

    def select(self, replay_index) -> dict:
        requested = int(replay_index or 0)
        _payload, replayable = self._snapshot()
        valid = {int(item["replay_index"]) for item in replayable}
        self._selected_replay_index = requested if requested in valid else None
        return self.snapshot()

    def action(self, action: str) -> dict:
        name = str(action or "").strip().lower()
        service = self.replay_service
        if name == "load" and service is not None:
            service.load_chat_context()
        elif name == "quick_load" and service is not None:
            service.quick_load_chat_context()
        elif name in {"previous", "next"}:
            _payload, replayable = self._snapshot()
            indexes = [int(item["replay_index"]) for item in replayable]
            if indexes:
                position = indexes.index(self._selected_replay_index) if self._selected_replay_index in indexes else len(indexes) - 1
                delta = -1 if name == "previous" else 1
                self._selected_replay_index = indexes[max(0, min(len(indexes) - 1, position + delta))]
        elif name == "replay_selected" and service is not None and self._selected_replay_index:
            service.replay_chat_session_from_index(self._selected_replay_index)
        elif name == "replay_latest" and service is not None:
            service.replay_latest_reply()
        elif name == "replay_chat" and service is not None:
            service.replay_chat_session()
        elif name not in {"refresh", "refresh_voices"}:
            raise ValueError(f"Unsupported replay action: {action}")
        return self.snapshot()

    def export_session_state(self) -> dict:
        return {_SESSION_KEY: {_ROLE_VOICES_KEY: self._role_voice_settings()}}

    def import_session_state(self, session) -> None:
        source = dict(session or {})
        grouped = source.get(_SESSION_KEY, {})
        payload = grouped.get(_ROLE_VOICES_KEY, {}) if isinstance(grouped, dict) else {}
        if not isinstance(payload, dict):
            payload = source.get(_LEGACY_ROLE_VOICES_KEY, {})
        if isinstance(payload, dict) and self.runtime_config is not None:
            self.runtime_config.update(_LEGACY_ROLE_VOICES_KEY, payload)


__all__ = ["NativeChatSessionPlayer"]
