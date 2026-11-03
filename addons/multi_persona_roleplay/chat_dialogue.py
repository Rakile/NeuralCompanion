"""Dialogue-only routing with bounded attribution across consecutive speech chunks.

No audio/text is buffered: only an explicitly opened quote retains its captured
voice until its closing quote. New turns, stream gaps and expiry clear ownership.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
import threading
import time
from typing import Callable
from core.runtime.speech_routes import VoiceSegment, VoiceSegmentationRequest
from .chat_characters import ChatCharacterRecord, ChatCharacterService
from .voice_routing import VOICE_REFERENCE_BACKENDS, normalize_tts_backend

_START = re.compile(
    r'(?:^|(?<=[.!?\n”"])\s+)'
    r'(?P<name>[^\W\d_]\w*(?:[ -][^\W\d_]\w*){0,2})\s+'
    r'(?:said|asked|replied|whispered|shouted|exclaimed|answered|murmured|thought|wondered|reflected)'
    r'\s*[, :]\s*(?P<quote>“|")', re.UNICODE)


@dataclass(frozen=True)
class _OpenQuote:
    close: str
    voice: str
    language: str
    character_id: str
    next_index: int
    size: int
    timestamp: float


class ChatDialogueRouter:
    def __init__(self, store: ChatCharacterService,
                 resolve_voice: Callable[[ChatCharacterRecord, str], tuple[str, str]],
                 discovered: Callable[[ChatCharacterRecord, str], None] | None = None):
        self.store = store
        self.resolve_voice = resolve_voice
        self.discovered = discovered
        self._streams: OrderedDict[tuple[str, str], _OpenQuote] = OrderedDict()
        self._lock = threading.RLock()

    def route(self, request: VoiceSegmentationRequest) -> tuple[VoiceSegment, ...]:
        with self._lock:
            return self._route(request)

    def _route(self, request: VoiceSegmentationRequest) -> tuple[VoiceSegment, ...]:
        text = request.text
        conversation = str(request.source_metadata.get('chat_character_conversation_id', ''))
        origin = str(request.source_metadata.get('normal_chat_transaction_id', ''))[:160]
        if not conversation or not origin or len(text) > 100_000:
            return (VoiceSegment(text),)
        key = (conversation, origin)
        if not self.store.snapshot(conversation).allow_new_characters:
            self._streams.pop(key, None)
            return (VoiceSegment(text),)
        now = time.monotonic()
        for old_key, state in tuple(self._streams.items()):
            if now - state.timestamp > 120:
                self._streams.pop(old_key, None)
        state = self._streams.pop(key, None) if request.streaming else None
        if state and (request.stream_start or state.next_index != request.stream_source_index):
            state = None
        parts: list[VoiceSegment] = []
        position = 0

        def append_quote(start: int, opened: _OpenQuote, search_from: int) -> int:
            end = text.find(opened.close, search_from)
            newline = text.find('\n', search_from)
            boundary = newline if newline >= 0 and (end < 0 or newline < end) else -1
            stop = boundary if boundary >= 0 else end + 1 if end >= 0 else len(text)
            size = opened.size + stop - start
            supported = normalize_tts_backend(request.tts_backend) in VOICE_REFERENCE_BACKENDS
            voice = opened.voice if size <= 16000 and supported else ''
            if stop > start:
                parts.append(VoiceSegment(text[start:stop], voice_path=voice,
                    voice_language=opened.language if voice else '',
                    source_metadata={'chat_character_id': opened.character_id} if voice else {}))
            if end < 0 and boundary < 0 and request.streaming and size <= 16000:
                self._streams[key] = _OpenQuote(opened.close, opened.voice, opened.language,
                    opened.character_id, request.stream_source_index + 1, size, now)
                while len(self._streams) > 32:
                    self._streams.popitem(last=False)
            return stop

        if state:
            position = append_quote(0, state, 0)
        for match in _START.finditer(text, position):
            if match.start() < position:
                continue
            name = match['name']
            if not all(part[0].isupper() for part in re.split(r'[ -]', name)):
                continue
            start = match.start('quote')
            close = '”' if match['quote'] == '“' else '"'
            if not request.streaming and text.find(close, start + 1) < 0:
                continue
            card = self.store.ensure_speaker(conversation, name, origin)
            if card is None:
                continue
            if self.discovered is not None:
                self.discovered(card, text[max(0, match.start()-250):min(len(text), start+1000)])
            voice, language = ('', '')
            if normalize_tts_backend(request.tts_backend) in VOICE_REFERENCE_BACKENDS:
                voice, language = self.resolve_voice(card, request.tts_backend)
            if start > position:
                parts.append(VoiceSegment(text[position:start]))
            position = append_quote(start, _OpenQuote(close, voice, language, card.id, 0, 0, now), start + 1)
        if position < len(text) or not parts:
            parts.append(VoiceSegment(text[position:]))
        return tuple(parts)

    def clear(self) -> None:
        with self._lock:
            self._streams.clear()

    def retire(self, turn_id: str) -> None:
        with self._lock:
            for key in tuple(self._streams):
                if key[1] == turn_id:
                    self._streams.pop(key, None)
