"""Immutable three-part Auto-Reply, shared by preparation and user speech."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from core.runtime.auto_reply_guidance import normalize_auto_reply_guidance
from core.runtime.speech_routes import VoiceSegment
from core.runtime.structured_character_voice import CharacterVoiceStream, VoiceContext


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Auto-Reply field")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class AutoReplyDraft:
    guidance: str
    example_response: str
    automated_user_response: str
    _voice_segments: tuple[VoiceSegment, ...] = ()

    def __post_init__(self) -> None:
        direction = normalize_auto_reply_guidance(self.guidance_metadata())
        text = self.automated_user_response
        if (direction is None or type(text) is not str or not 1 <= len(text.strip()) <= 8000
                or re.match(r"^(user|assistant|system)\s*:", text.strip(), re.I)):
            raise ValueError("Invalid Auto-Reply fields")
        for field, value in direction.items():
            object.__setattr__(self, field, value)
        object.__setattr__(self, "automated_user_response", text.strip())

    @classmethod
    def parse(cls, output: str, voice_context: VoiceContext | None = None) -> AutoReplyDraft:
        if type(output) is not str or not 1 <= len(output) <= 16000:
            raise ValueError("Invalid Auto-Reply output")
        text = output.strip()
        fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, re.S | re.I)
        if fence:
            text = fence.group(1)
        try:
            value = json.loads(text, object_pairs_hook=_unique_fields)
        except (ValueError, RecursionError) as error:
            raise ValueError("Invalid Auto-Reply JSON") from error
        if type(value) is not dict or set(value) != {"guidance", "example_response", "automated_user_response"}:
            raise ValueError("Auto-Reply requires all three fields")
        rows = value['automated_user_response']
        if type(rows) is str and rows.lstrip().startswith(('{', '[')):
            try:
                decoded = json.loads(rows, object_pairs_hook=_unique_fields)
            except (ValueError, RecursionError) as error:
                if '"speaker_id"' in rows:
                    raise ValueError('Invalid Auto-Reply segment') from error
            else:
                if type(decoded) is dict and 'speaker_id' in decoded:
                    rows = [decoded]
                elif type(decoded) is list and any(type(row) is dict and 'speaker_id' in row for row in decoded):
                    rows = decoded
                elif '"speaker_id"' in rows:
                    raise ValueError('Invalid Auto-Reply segment')
        if type(rows) is list:
            if voice_context is None or not 1 <= len(rows) <= 64:
                raise ValueError('Invalid Auto-Reply speakers')
            # Validate the entire response before the shared parser: a malformed
            # record must not silently remove words from the submitted user turn.
            for row in rows:
                if (type(row) is not dict or set(row) != {'speaker_id', 'speaker_name', 'kind', 'text'}
                        or (row['speaker_id'] is not None and type(row['speaker_id']) is not str)
                        or type(row['speaker_name']) is not str or not row['speaker_name'].strip()
                        or row['kind'] not in ('narration', 'dialogue', 'thought')
                        or type(row['text']) is not str or not row['text'].strip() or '\x00' in row['text']):
                    raise ValueError('Invalid Auto-Reply segment')
            stream = CharacterVoiceStream(voice_context)
            stream.feed(json.dumps({'segments': rows}, ensure_ascii=False))
            stream.finish()
            if stream.invalid_records or len(stream.parts) != len(rows):
                raise ValueError('Invalid Auto-Reply segments')
            value['automated_user_response'] = '\n\n'.join(
                f"{row['speaker_name']}: “{row['text'].strip()}”"
                if row['kind'] in ('dialogue', 'thought') and row['speaker_name'] not in ('__main__', '__narrator__', '__user__')
                else row['text'].strip() for row in rows)
            return cls(**value, _voice_segments=tuple(stream.parts))
        return cls(**value)

    def guidance_metadata(self) -> dict[str, str]:
        return {"guidance": self.guidance, "example_response": self.example_response}

    def speech_text(self, include_guidance: bool) -> str:
        if not include_guidance:
            return self.automated_user_response
        return (f"Guidance. {self.guidance}\n\n"
                f"Example response. {self.example_response}\n\n"
                f"Automated user response. {self.automated_user_response}")

    def speech_segments(self, include_guidance: bool) -> tuple[VoiceSegment, ...]:
        if not self._voice_segments:
            return (VoiceSegment(self.speech_text(include_guidance)),)
        prefix = (VoiceSegment(f'Guidance. {self.guidance}\n\n'
                              f'Example response. {self.example_response}\n\nAutomated user response.'),) if include_guidance else ()
        return prefix + self._voice_segments
