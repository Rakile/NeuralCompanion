"""Internal dialogue attribution; never changes displayed text or buffers audio.

Runs on the existing speech preparation worker. Explicit routes take priority;
only unmatched quote spans may use semantic attribution to an existing voice.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
import threading
import re
import time
from typing import Callable
from core.runtime.speech_routes import VoiceSegment, VoiceSegmentationRequest
from .chat_characters import ChatCharacterService
from .voice_routing import VOICE_REFERENCE_BACKENDS, normalize_tts_backend

_ATTRIBUTION_VERBS = r'(?:said|asked|replied|whispered|shouted|exclaimed|answered|murmured|teased|thought|wondered|reflected)'

def _eligible_speakers(before: str, after: str, cards, excluded=()) -> set[str]:
    """A model guess cannot manufacture a speaker absent a local attribution cue."""
    before = before[-500:]
    after = after[:180]
    direct = set()
    for card in cards:
        for name in (card.name, *card.aliases):
            if not name or name.casefold() in {str(n).casefold() for n in excluded if n}:
                continue
            escaped = re.escape(name)
            if (re.search(r'(?<!\w)' + escaped + r'\s+' + _ATTRIBUTION_VERBS + r'\s*[, :]\s*$', before, re.I)
                    or re.match(r'\s*[,;]?\s*' + escaped + r'\s+' + _ATTRIBUTION_VERBS + r'\b', after, re.I)):
                direct.add(card.id)
    if direct:
        return direct if len(direct) == 1 else set()
    # Pronouns need one unambiguous named antecedent in nearby narration.
    pronoun = r'(?:she|he|they)\s+' + _ATTRIBUTION_VERBS
    if not (re.search(r'\b' + pronoun + r'\s*[, :]\s*$', before, re.I)
            or re.match(r'\s*[,;]?\s*' + pronoun + r'\b', after, re.I)):
        return set()
    narration = re.sub(r'[“"].*?[”"]|\*[^*]*\*', ' ', before, flags=re.S)[-300:]
    if any(name and re.search(r'(?<!\w)' + re.escape(str(name)) + r'(?!\w)', narration, re.I) for name in excluded):
        return set()
    mentioned = {card.id for card in cards for name in (card.name, *card.aliases)
                 if name and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', narration, re.I)}
    return mentioned if len(mentioned) == 1 else set()

@dataclass(frozen=True)
class _State:
    context: str
    close: str
    voice: str
    language: str
    character_id: str
    next_index: int
    timestamp: float

class ChatSpeakerAttribution:
    def __init__(self, store: ChatCharacterService, resolve: Callable, classify: Callable, excluded_names: Callable = lambda: ()):
        self.store, self.resolve, self.classify = store, resolve, classify
        self.excluded_names = excluded_names
        self._states: OrderedDict[tuple[str, str], _State] = OrderedDict()
        self._lock = threading.RLock()
        self._epoch = 0

    def clear(self):
        with self._lock:
            self._epoch += 1
            self._states.clear()

    def route(self, request: VoiceSegmentationRequest, explicit: tuple[VoiceSegment, ...]):
        text = request.text
        conversation = str(request.source_metadata.get('chat_character_conversation_id', ''))
        turn = str(request.source_metadata.get('normal_chat_transaction_id', ''))
        snapshot = self.store.snapshot(conversation)
        if not snapshot.allow_new_characters:
            self.clear()
            return (VoiceSegment(text),)
        if (not conversation or not turn or len(text) > 100000
                or normalize_tts_backend(request.tts_backend) not in VOICE_REFERENCE_BACKENDS):
            return explicit
        key = (conversation, turn)
        now = time.monotonic()
        with self._lock:
            epoch = self._epoch
            previous = self._states.pop(key, None) if request.streaming else None
        if previous and (request.stream_start or previous.next_index != request.stream_source_index
                         or now - previous.timestamp > 120):
            previous = None
        context = previous.context if previous else ''
        # Locate quoted speech candidates; classifier must reject actions/written quotes.
        spans = []
        cursor = 0
        close = previous.close if previous else ''
        continuing = bool(close)
        while cursor < len(text):
            start = cursor
            if not close:
                positions = [p for q in ('“', '"') if (p := text.find(q, cursor)) >= 0]
                italic = re.search(r'(?<!\*)\*(?!\*)', text[cursor:])
                if italic:
                    positions.append(cursor + italic.start())
                if not positions:
                    break
                start = min(positions)
                close = '”' if text[start] == '“' else text[start]
                search = start + 1
            else:
                search = cursor
            end = text.find(close, search)
            newline = text.find('\n', search)
            if newline >= 0 and (end < 0 or newline < end):
                stop, remains = newline, False
            elif end >= 0:
                stop, remains = end + 1, False
            else:
                stop, remains = len(text), request.streaming
                if not request.streaming:
                    break
            if stop > start:
                spans.append((start, stop, remains, close, continuing))
            cursor = max(stop, start + 1)
            continuing = False
            close = close if remains else ''
        known = {}
        for card in snapshot.characters:
            voice, language = self.resolve(card, request.tts_backend)
            if voice:
                known[card.id] = (card, voice, language)
        explicit_ranges = []
        offset = 0
        for part in explicit:
            if part.voice_path:
                explicit_ranges.append((offset, offset + len(part.text), part))
            offset += len(part.text)
        chosen = {}
        unresolved = {}
        eligible = {}
        for index, (start, end, remains, delimiter, continued) in enumerate(spans):
            prior = next((p for a, b, p in explicit_ranges if a <= start and b >= end), None)
            if prior:
                chosen[index] = (prior.voice_path, prior.voice_language, str(prior.source_metadata.get('chat_character_id', '')))
            elif continued and previous and previous.voice:
                chosen[index] = (previous.voice, previous.language, previous.character_id)
            elif known and len(unresolved) < 12:
                candidates = _eligible_speakers(context + text[:start], text[end:],
                                                snapshot.characters, self.excluded_names()) & known.keys()
                if candidates:
                    eligible[str(index)] = candidates
                    unresolved[str(index)] = text[start:min(end, start + 2000)]
        if unresolved:
            cast = [{'id': card.id, 'name': card.name, 'aliases': list(card.aliases),
                     'description': card.description[:500]} for card, _, _ in known.values()]
            try:
                result = self.classify((context + text)[-10000:], unresolved, cast)
                if isinstance(result, dict):
                    for index in unresolved:
                        identity = result.get(index)
                        if isinstance(identity, str) and identity in known and identity in eligible[index]:
                            _, voice, language = known[identity]
                            chosen[int(index)] = (voice, language, identity)
            except Exception:
                pass  # A failed optional classification must not stop playback.
        with self._lock:
            current = self.store.snapshot(conversation)
            if epoch != self._epoch or not current.allow_new_characters:
                return (VoiceSegment(text),)
            parts = []
            cursor = 0
            opened = ('', '', '', '')
            for index, (start, end, remains, delimiter, continued) in enumerate(spans):
                if start > cursor:
                    parts.append(VoiceSegment(text[cursor:start]))
                voice, language, identity = chosen.get(index, ('', '', ''))
                parts.append(VoiceSegment(text[start:end], voice_path=voice, voice_language=language,
                    source_metadata={'chat_character_id': identity} if voice else {}))
                cursor = end
                if remains:
                    opened = (delimiter, voice, language, identity)
            if cursor < len(text) or not parts:
                parts.append(VoiceSegment(text[cursor:]))
            if request.streaming:
                self._states[key] = _State((context + text + ' ')[-6000:], *opened,
                                          request.stream_source_index + 1, now)
                while len(self._states) > 32:
                    self._states.popitem(last=False)
            return tuple(parts)
