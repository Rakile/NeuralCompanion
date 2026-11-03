"""Automatic, separate checkpoint for the phone's current shared story."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .chat_context_io import load_chat_context, write_chat_context


class StoryCheckpointStore:
    def __init__(self, application: Any, app_root: Path) -> None:
        self._application = application
        self.path = app_root / "runtime" / "main_chat_remote" / "story_checkpoint.json"
        self.manual_path = app_root / "runtime" / "chat_context_quick_save.json"

    def has_messages(self) -> bool:
        return bool(self._application.chat.snapshot().messages)

    def has_named_context(self) -> bool:
        config = getattr(self._application, 'config', None)
        return bool(config is not None and str(
            config.snapshot().values.get('active_chat_context_path', '') or '').strip())

    def save(self) -> str:
        # An empty export is intentional: reset-chat must not revive an old story.
        return write_chat_context(self._application, self.path)

    def restore_if_empty(self) -> bool:
        # The desktop restores this file through its normal named-chat loader.
        # A checkpoint must not fill the empty history first and suppress it.
        if self.has_named_context() or self.has_messages() or not self.path.is_file():
            return False
        # An empty checkpoint is a reset tombstone, not a story to load.
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not payload.get("conversation_history"):
            return False
        if self.has_named_context() or self.has_messages():
            return False
        load_chat_context(self._application, self.path)
        return True
