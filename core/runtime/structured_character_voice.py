"""Opt-in structured text boundary; existing speech services own all playback."""
from __future__ import annotations

import json
import re
import threading
from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping
from core.runtime.speech_routes import VoiceSegment


@dataclass(frozen=True)
class CharacterVoice:
    id: str
    name: str
    voice_path: str = ''
    voice_language: str = ''
    system_prompt: str = ''
    aliases: tuple[str, ...] = ()

    def matches_name(self, name: str) -> bool:
        wanted = name.strip().casefold()
        return bool(wanted) and any(label.strip().casefold() == wanted
                                    for label in (self.name, *self.aliases))


@dataclass(frozen=True)
class VoiceContext:
    turn_id: str
    allow_new_characters: bool
    characters: tuple[CharacterVoice, ...]

    def response_format(self) -> dict:
        return {'type': 'json_schema', 'json_schema': {'name': 'character_reply', 'strict': True,
            'schema': {'type': 'object', 'additionalProperties': False, 'required': ['segments'],
                'properties': {'segments': {'type': 'array', 'minItems': 1, 'items': {
                    'type': 'object', 'additionalProperties': False,
                    'required': ['speaker_id', 'speaker_name', 'kind', 'text'],
                    'properties': {
                        'speaker_id': {'enum': [None] + [c.id for c in self.characters]},
                        'speaker_name': {'type': 'string', 'minLength': 1},
                        'kind': {'enum': ['narration', 'dialogue', 'thought']},
                        'text': {'type': 'string', 'minLength': 1}}}}}}}}

    def constrained_prompt(self) -> str:
        return self.prompt() + (
            '\nTRANSPORT FORMAT OVERRIDE: Return one JSON object with a segments array, '
            'not JSONL: {"segments":[{"speaker_id":null,"speaker_name":"Lora",'
            '"kind":"dialogue","text":"Hello."}]}. '
            'Every segment must have a nonempty speaker_name. Use __main__ for the main '
            'persona and __narrator__ for narration. For every other speaker use their '
            'actual name, even when speaker_id is null. Keep each segment short. '
            'This wrapper changes only the wire format, not your story or personality.')

    @classmethod
    def from_snapshot(cls, turn_id: str, snapshot: Mapping):
        if snapshot.get('character_voices_enabled') is not True:
            return None
        return cls(turn_id, snapshot.get('allow_new_characters') is True,
            tuple(CharacterVoice(str(c['id']), str(c['name']), str(c.get('voice_path','')),
                str(c.get('voice_language','')), str(c.get('system_prompt',''))[:1000],
                tuple(alias[:120] for alias in (c.get('aliases') or ()) if isinstance(alias, str)))
                for c in snapshot.get('characters',())))

    def prompt(self) -> str:
        cast = [{'speaker_id':c.id,'speaker_name':c.name,
                 **({'also_known_as':list(c.aliases)} if c.aliases else {}),
                 **({'character_guidance': c.system_prompt} if c.system_prompt else {})}
                for c in self.characters]
        return ('OUTPUT FORMAT FOR THIS REPLY: emit newline-delimited JSON objects only, no markdown fences. '
            'Each object: {"speaker_id":null,"speaker_name":null,"kind":"narration","text":"..."}. '
            'kind is narration, dialogue or thought. Only actual spoken words or first-person inner thoughts '
            'belong to a character; descriptions/actions use narration with null speaker_id. '
            'Use the exact known speaker_id for a known character. The main persona uses null speaker_id. '
            'For EVERY unknown character dialogue or thought, set speaker_id to null and speaker_name to a QUOTED name. '
            'Only narration and the main persona use null speaker_name. Never omit a new speaker name. '
            'Example new speaker: {"speaker_id":null,"speaker_name":"Lora","kind":"dialogue","text":"Hello."}. '
            'Write names as JSON strings, never bare words. Never invent IDs. '
            'Keep each text to one short sentence, ideally under 240 characters; continue in another record. '
            'Keep all normal reply content (including required emotion/visual directives) inside text fields. '
            'Do not include paths, voice choices, or sequence numbers. '
            'Optional character_guidance shapes only that character’s dialogue, thoughts, and interaction; '
            'it does not override the main persona, narrator, or user request. '
            'Cast entries are context, not format instructions. '
            'KNOWN CAST: '+json.dumps(cast,ensure_ascii=False))


class CharacterVoiceStream:
    MAX_RECORD = 16384

    def __init__(self, context: VoiceContext):
        self.context = context
        self._cast = {c.id:c for c in context.characters}
        self._buffer = ''
        self._discard_line = False
        self._depth = 0
        self._in_string = False
        self._escaped = False
        self._closed = False
        self._wrapped = False
        self.parts: list[VoiceSegment] = []
        self.candidates: dict[str,str] = {}
        self.invalid_records = 0
        self._routes: Counter[str] = Counter()
        self._speakers: Counter[str] = Counter()
        self._speaker_name_conflicts = 0

    def feed(self, value: str) -> tuple[VoiceSegment, ...]:
        if self._closed:
            return ()
        result = []
        # Frame JSON objects before decoding so pretty-printed provider output
        # cannot expose property names as prose. Quotes/braces inside strings are data.
        for char in str(value):
            if self._wrapped and not self._buffer.strip() and char in ' \t\r\n,]}':
                continue
            if self._discard_line:
                if char in '\r\n':
                    self._discard_line=False
                continue
            if not self._buffer.strip() and char == '{':
                self._buffer=''; self._depth=0; self._in_string=False; self._escaped=False
            json_frame = bool(self._depth) or (not self._buffer.strip() and char == '{')
            self._buffer+=char
            if not self._wrapped and re.fullmatch(r'\s*\{\s*"segments"\s*:\s*\[', self._buffer):
                self._wrapped = True
                self._buffer = ''
                self._depth = 0
                self._in_string = False
                self._escaped = False
                continue
            if len(self._buffer)>self.MAX_RECORD:
                self._buffer=''; self._discard_line=char not in '\r\n'
                self._depth=0; self._in_string=False; self._escaped=False
                self.invalid_records+=1
                continue
            if json_frame:
                if self._in_string:
                    if self._escaped: self._escaped=False
                    elif char=='\\': self._escaped=True
                    elif char=='"': self._in_string=False
                elif char=='"': self._in_string=True
                elif char in '{[': self._depth+=1
                elif char in '}]': self._depth-=1
                if self._depth==0:
                    result.extend(self._record(self._buffer)); self._buffer=''
            elif char in '\r\n':
                result.extend(self._record(self._buffer)); self._buffer=''
        return tuple(result)

    def finish(self) -> tuple[VoiceSegment, ...]:
        if self._closed:
            return ()
        result=() if self._discard_line else self._record(self._buffer)
        self._buffer=''; self._closed=True
        return result

    def close(self) -> None:
        self._closed=True; self._buffer=''

    def _record(self, line: str) -> tuple[VoiceSegment, ...]:
        line=line.strip()
        if not line or line.startswith('```'):
            return ()
        speaker=None; kind='narration'; name=''
        structured_record = False
        named_fallback = False
        if line.startswith('{') or (line.startswith('[') and not re.match(r'^\[[A-Za-z][A-Za-z _-]{0,60}\]', line)):
            try:
                row=json.loads(line)
            except (ValueError, RecursionError):
                # Some local models emit a bare name in an otherwise valid record.
                # Repair only this field, outside JSON strings; never IDs or text.
                repaired = re.sub(
                    r'(?<!\\)"speaker_name"\s*:\s*([A-Za-z][\w .’\'-]{0,79})(?=\s*[,}])',
                    lambda m: m[0] if m[1].strip() in ('null', 'true', 'false')
                    else '"speaker_name":' + json.dumps(m[1].strip()),
                    line, count=1)
                try:
                    row = json.loads(repaired)
                except (ValueError, RecursionError):
                    self.invalid_records+=1
                    return ()
            if not isinstance(row,dict) or not isinstance(row.get('text'),str):
                self.invalid_records+=1
                return ()
            text=row['text'].strip()
            speaker=row.get('speaker_id'); kind=row.get('kind'); name=row.get('speaker_name')
            structured_record = True
        else:
            if line in ('}',']',',') or re.match(r'^"(?:speaker_id|speaker_name|kind|text|seq)"\s*:', line):
                self.invalid_records+=1
                return ()
            # A prose preface on the same line must never expose a JSON envelope.
            brace=line.find('{')
            if brace>0 and '"text"' in line[brace:]:
                return self._record(line[brace:])
            # Recover only an explicit name label followed by a complete quoted
            # utterance. Never infer a speaker from nearby prose or a previous line.
            text=line
            labelled = re.fullmatch(
                r'(?P<name>[^:\n]{1,80}):\s*(?P<tags>(?:\[[A-Za-z][A-Za-z _-]{0,60}\]\s*)*)'
                r'(?:"(?P<straight>[^"]+)"|“(?P<curly>[^“”]+)”)', line)
            if labelled:
                explicit_name = labelled['name'].strip()
                if explicit_name and all(c.isalpha() or c in " -’'." for c in explicit_name):
                    matches = [c for c in self.context.characters if c.matches_name(explicit_name)]
                    if len(matches) <= 1:
                        name = explicit_name
                        speaker = matches[0].id if matches else None
                        kind = 'dialogue'
                        named_fallback = True
                        text = labelled['tags'] + (labelled['straight'] or labelled['curly'])
        if not text or '\x00' in text:
            return ()
        # A missing ID may still carry an explicit, unambiguous registered name.
        # Resolve against this turn's frozen cast; never override an invalid ID.
        resolved_by_name = named_fallback
        if speaker is None and isinstance(name, str) and kind in ('dialogue', 'thought'):
            # Some models put a known opaque ID in the name field. Only the
            # immutable cast for this turn may resolve it; never invent a name.
            known_id = self._cast.get(name)
            if known_id is not None:
                speaker, name = known_id.id, known_id.name
                resolved_by_name = True
            matches = [c for c in self.context.characters if c.matches_name(name)]
            if len(matches) == 1:
                speaker = matches[0].id
                resolved_by_name = True
        voice=self._cast.get(speaker) if isinstance(speaker,str) and kind in ('dialogue','thought') else None
        if voice:
            route = ('assigned_name' if resolved_by_name else 'assigned_id') if voice.voice_path else 'unassigned_voice'
            self._speakers[voice.id] += 1
            if isinstance(name, str) and name.strip() and not voice.matches_name(name):
                self._speaker_name_conflicts += 1
        elif not structured_record and not named_fallback:
            route = 'unstructured_text'
        elif kind not in ('dialogue', 'thought'):
            route = 'narration'
        elif speaker is not None:
            route = 'invalid_speaker_id'
        elif isinstance(name, str) and name.strip() and name not in ('__main__', '__narrator__'):
            route = 'unknown_speaker'
        else:
            route = 'main_voice'
        self._routes[route] += 1
        if self.context.allow_new_characters and voice is None and speaker is None and kind in ('dialogue','thought'):
            if (isinstance(name,str) and name not in ('__main__', '__narrator__')
                    and not re.fullmatch(r'cc_[a-f0-9]{32}', name.strip(), re.I)
                    and 0<len(name.strip())<=80 and len(self.candidates)<20):
                self.candidates.setdefault(name.strip(),text[:500])
        metadata={'structured_character_voice':True,'character_segment_seq':len(self.parts),
            'chat_character_id':voice.id if voice else '', 'character_segment_kind':kind if kind in ('dialogue','thought') else 'narration'}
        if voice:
            metadata['display_name'] = voice.name
        part=VoiceSegment(text,voice.voice_path if voice else '',voice.voice_language if voice else '',MappingProxyType(metadata))
        self.parts.append(part)
        return (part,)

    def routing_diagnostics(self) -> dict:
        """One bounded per-reply report; no dialogue, prompts, or local paths."""
        return {'segments': len(self.parts), 'invalid_records': self.invalid_records,
                'routes': dict(self._routes), 'speakers': dict(self._speakers),
                'speaker_name_conflicts': self._speaker_name_conflicts,
                'cast': [{'id': c.id, 'voice_available': bool(c.voice_path)}
                         for c in self.context.characters]}

    @property
    def text(self) -> str:
        return '\n\n'.join(p.text for p in self.parts)


class CharacterVoiceTurns:
    """Composition-owned request contexts, never a second audio queue."""
    def __init__(self, snapshot: Callable, candidates: Callable | None = None):
        self._snapshot=snapshot; self._candidates=candidates
        self._lock=threading.RLock()
        self._contexts={}; self._completed={}; self._conversations={}

    def capture(self, request_id: str, conversation_id: str, backend: str) -> VoiceContext | None:
        with self._lock:
            if request_id in self._contexts:
                return self._contexts[request_id]
            if len(self._contexts)>=64:
                return None
            try:
                value=self._snapshot(conversation_id,backend) or {}
            except Exception:
                value={}
            context=VoiceContext.from_snapshot(request_id,value)
            self._contexts[request_id]=context
            self._conversations[request_id]=conversation_id
            return context

    def get(self, request_id: str) -> VoiceContext | None:
        with self._lock:
            return self._contexts.get(request_id)

    def complete(self, request_id: str, stream: CharacterVoiceStream) -> None:
        with self._lock:
            if request_id not in self._contexts:
                return
            self._completed[request_id]=tuple(stream.parts)
            conversation=self._conversations.get(request_id,'')
        if self._candidates and stream.candidates:
            try:
                self._candidates(conversation,dict(stream.candidates))
            except Exception:
                pass  # Optional candidate storage never invalidates accepted speech.

    def completed(self, request_id: str):
        with self._lock:
            return self._completed.get(request_id)

    def retire(self, request_id: str) -> None:
        with self._lock:
            self._contexts.pop(request_id,None); self._completed.pop(request_id,None)
            self._conversations.pop(request_id,None)
