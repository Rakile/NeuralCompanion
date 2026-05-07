class _UiShellChatReplayService:
    """Shell-safe replay facade for the Chat Player addon."""

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def _chat_context_service(self):
        from ui.runtime.qt_app_shell_service_factories import _ui_shell_chat_context_service

        return _ui_shell_chat_context_service(self._window)

    def snapshot_chat_session(self):
        return {
            "conversation_history": [],
            "shell_mode": True,
            "message": "Chat replay is not connected in shell preview.",
        }

    def replayable_assistant_entries(self):
        return []

    def replayable_assistant_messages(self):
        return []

    def is_engine_running(self) -> bool:
        return False

    def is_offline_replay_only(self) -> bool:
        return False

    def trigger_control_action(self, action: str) -> None:
        self._last_action = str(action or "").strip()

    def replay_latest_reply(self) -> None:
        self._last_action = "replay_latest_reply"

    def replay_chat_session(self) -> None:
        self._last_action = "replay_chat_session"

    def replay_chat_session_from_index(self, start_index: int) -> None:
        self._last_action = f"replay_chat_session_from_index:{int(start_index or 0)}"

    def load_chat_context(self) -> None:
        self._chat_context_service().load_chat_context()

    def quick_load_chat_context(self) -> None:
        self._chat_context_service().quick_load_chat_context()

    def save_chat_context(self) -> None:
        self._chat_context_service().save_chat_context()

    def quick_save_chat_context(self) -> None:
        self._chat_context_service().quick_save_chat_context()
