"""Bounded phrase boundaries for phone-owned speech, using the normal TTS route."""
from __future__ import annotations

import re


_BOUNDARY = re.compile(r'\[[^\]]*(?:\]|$)|[,;:，；：]["\'”’»)]*(?=\s|$)|[—–]|\s--?\s')
_WORDS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
_TAGS = re.compile(r'\[[^\]]*(?:\]|$)')


def split_phone_speech_clauses(text: str, *, tts_backend: str = '') -> list[str]:
    """Expose comma breaths without isolated words, altered tags or huge fan-out.

    Sentence splitting and length limits remain owned by the existing planner.
    Short lists stay together; numbers/times/URLs are not comma/colon boundaries.
    """
    if str(tts_backend or '').strip().lower() == 'liquidai':
        # Each LiquidAI synthesis is a separate utterance with its own quiet
        # edges. Extra comma splits break prosody and introduce mid-sentence
        # pauses; retain the existing planner's complete, bounded text segment.
        return [text.strip()] if text.strip() else []
    parts: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        if match.group().startswith('['):
            continue
        if (match.group().strip() in {'-', '--', '—', '–'}
                and text[:match.start()].rstrip()[-1:].isdigit()
                and text[match.end():].lstrip()[:1].isdigit()):
            continue
        candidate = text[start:match.end()].strip()
        remaining = text[match.end():].strip()
        sentence_tail = re.split(r'[.!?。！？]["\'”’»)]*\s+', _TAGS.sub('', candidate))[-1]
        if (len(_WORDS.findall(sentence_tail)) < 4
                or len(_WORDS.findall(_TAGS.sub('', remaining))) < 2):
            continue
        parts.append(candidate)
        start = match.end()
        if len(parts) >= 7:
            break
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts
