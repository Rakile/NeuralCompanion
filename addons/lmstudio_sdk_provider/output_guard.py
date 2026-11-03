"""Stop corrupt reserved-token runs before they enter NC's reply pipeline."""
from __future__ import annotations

import re


_TOKEN = r'<unused[0-9]{1,4}>'
# Bound whitespace lookahead as well as token lookahead. Ordinary text is
# released immediately; only a possible reserved-token run is held back.
_SEPARATOR = r'[ \t\r\n]{0,16}'
_LOOP = re.compile(r'(?:' + _TOKEN + _SEPARATOR + r'){4}')
_PENDING = re.compile(r'(?:' + _TOKEN + _SEPARATOR + r')+$')


class ReservedTokenLoopError(ValueError):
    """The inference runtime is producing reserved vocabulary instead of text."""


class ReservedTokenGuard:
    def __init__(self) -> None:
        self._pending = ''

    def feed(self, text: str) -> str:
        buffer = self._pending + text
        if _LOOP.search(buffer):
            raise ReservedTokenLoopError(
                'LM Studio returned a repeated reserved-token loop. Generation stopped. '
                'Reload the selected model in LM Studio, then regenerate the reply.'
            )
        boundary = len(buffer)
        start = buffer.rfind('<')
        if start >= 0:
            tail = buffer[start:]
            digits = tail[len('<unused'):]
            if '<unused'.startswith(tail) or (
                    tail.startswith('<unused') and 1 <= len(digits) <= 4
                    and digits.isascii() and digits.isdigit()):
                boundary = start
        pending = _PENDING.search(buffer[:boundary])
        if pending is not None:
            boundary = pending.start()
        self._pending = buffer[boundary:]
        return buffer[:boundary]

    def finish(self) -> str:
        text, self._pending = self._pending, ''
        return text
