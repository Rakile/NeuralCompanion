"""Graph-owned adapters for finite desktop compatibility ports."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from core.runtime.config import RuntimeConfigService
from core.runtime.conversation import ConversationService
from core.runtime.sensory import SensoryService


class ProductionDesktopChatViewOwner:
    """Publish the console sentinel consumed by the Qt chat view."""

    __slots__ = ("_logger",)

    _REBUILD_SENTINEL = "[[CHAT_REBUILD]]"

    def __init__(self, logger: Callable[[str], object] = print) -> None:
        if not callable(logger):
            raise TypeError("Chat-view logger must be callable.")
        self._logger = logger

    def request_rebuild(self) -> object:
        return self._logger(self._REBUILD_SENTINEL)


class ProductionDesktopMemoryTriggerOwner:
    """Join memory scheduling to the graph-owned chat-session exporter."""

    __slots__ = ("_memory", "_session")

    def __init__(
        self,
        memory: object,
        session: object,
    ) -> None:
        if not callable(getattr(memory, "maybe_update_continuity", None)) or not callable(
            getattr(memory, "maybe_archive_long_term", None)
        ):
            raise TypeError("Desktop memory trigger owner is incomplete.")
        if not callable(getattr(session, "export_chat_session_state", None)):
            raise TypeError("Desktop chat-session exporter is incomplete.")
        self._memory = memory
        self._session = session

    def maybe_update_continuity(self) -> bool:
        return self._memory.maybe_update_continuity(
            self._session.export_chat_session_state
        )

    def maybe_archive_long_term(self) -> bool:
        return self._memory.maybe_archive_long_term()


class ProductionDesktopScreenCaptureOwner:
    """Capture one forced screen sensory record for user-turn attachment."""

    __slots__ = ("_config", "_conversation", "_sensory")

    def __init__(
        self,
        *,
        sensory: SensoryService,
        config: RuntimeConfigService,
        conversation: ConversationService,
    ) -> None:
        if not isinstance(sensory, SensoryService):
            raise TypeError("Desktop screen capture requires SensoryService.")
        if not isinstance(config, RuntimeConfigService):
            raise TypeError("Desktop screen capture requires RuntimeConfigService.")
        if not isinstance(conversation, ConversationService):
            raise TypeError("Desktop screen capture requires ConversationService.")
        self._sensory = sensory
        self._config = config
        self._conversation = conversation

    def capture(self) -> Mapping[str, object] | None:
        config = self._config.snapshot()
        lease = self._conversation.session_lease()
        started = self._sensory.begin_cycle(lease, config)
        if not started.accepted or started.value is None:
            return None
        captured = self._sensory.capture(
            lease,
            config,
            cycle=started.value,
            force=True,
            selected_sources=("screen",),
        )
        if not captured.accepted or captured.value is None:
            return None
        return next(
            (
                record
                for record in captured.value.mappings()
                if str(record.get("source", "") or "").strip().lower()
                == "screen"
            ),
            None,
        )


__all__ = [
    "ProductionDesktopChatViewOwner",
    "ProductionDesktopMemoryTriggerOwner",
    "ProductionDesktopScreenCaptureOwner",
]
