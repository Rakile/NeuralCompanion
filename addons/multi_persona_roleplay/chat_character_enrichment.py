"""Best-effort character notes on the addon's supervised worker owner."""
from __future__ import annotations

from collections import deque
import threading
from typing import Callable, Mapping
from .chat_characters import ChatCharacterRecord, ChatCharacterService


class CharacterEnrichment:
    def __init__(self, store: ChatCharacterService, spawn: Callable,
                 propose: Callable[[ChatCharacterRecord, str], Mapping[str, object]]):
        self.store, self.spawn, self.propose = store, spawn, propose
        self._lock = threading.RLock()
        self._closed = False
        self._seen: deque[str] = deque(maxlen=512)
        self._pending: set[str] = set()

    def submit(self, card: ChatCharacterRecord, context: str) -> None:
        with self._lock:
            if self._closed or card.id in self._seen or card.id in self._pending or len(self._pending) >= 4:
                return
            if card.description or card.voice_description:
                return
            self._seen.append(card.id)
            self._pending.add(card.id)

        def run(*_args) -> None:
            try:
                with self._lock:
                    if self._closed:
                        return
                proposal = self.propose(card, context[:3000])
                with self._lock:
                    if not self._closed:
                        self.store.enrich(card.id, card.revision, proposal)
            except Exception:
                # Enrichment is optional. The original usable card and narrator remain.
                pass
            finally:
                with self._lock:
                    self._pending.discard(card.id)
        try:
            self.spawn('chat-character-enrich:' + card.id, run)
        except Exception:
            with self._lock:
                self._pending.discard(card.id)

    def close(self) -> None:
        with self._lock:
            self._closed = True
