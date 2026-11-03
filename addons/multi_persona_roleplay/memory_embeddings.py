from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


DEFAULT_DIMENSIONS = 128

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "can",
    "did",
    "for",
    "from",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "like",
    "not",
    "of",
    "on",
    "or",
    "that",
    "the",
    "then",
    "there",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "with",
    "you",
    "your",
}

_ALIASES = {
    "archive": ("library", "records", "vault"),
    "battle": ("combat", "fight", "clash"),
    "corridor": ("hall", "hallway", "passage"),
    "door": ("gate", "portal", "entrance"),
    "friend": ("ally", "companion"),
    "garden": ("grove", "courtyard"),
    "key": ("lock", "unlock"),
    "lamp": ("lantern", "light"),
    "lantern": ("lamp", "light"),
    "magic": ("arcane", "spell"),
    "moon": ("lunar", "silver"),
    "silver": ("moon", "lunar"),
    "story": ("scene", "chapter"),
}


def tokenize(text: Any) -> list[str]:
    value = str(text or "").lower()
    raw_tokens = re.findall(r"[a-z0-9_']+", value)
    tokens: list[str] = []
    for raw in raw_tokens:
        token = _stem(raw.strip("'_"))
        if len(token) <= 2 or token in _STOP_WORDS:
            continue
        tokens.append(token)
        for alias in _ALIASES.get(token, ()):
            if alias not in _STOP_WORDS:
                tokens.append(alias)
    return tokens


def keyword_set(text: Any) -> set[str]:
    return set(tokenize(text))


def embed_text(text: Any, *, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    size = max(16, int(dimensions or DEFAULT_DIMENSIONS))
    vector = [0.0] * size
    tokens = tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % size
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vector[bucket] += sign
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= 0:
        return vector
    return [value / magnitude for value in vector]


def cosine_similarity(left: list[float] | tuple[float, ...], right: list[float] | tuple[float, ...]) -> float:
    if not left or not right:
        return 0.0
    count = min(len(left), len(right))
    dot = sum(float(left[index]) * float(right[index]) for index in range(count))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left[:count]))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right[:count]))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def serialize_embedding(vector: list[float] | tuple[float, ...]) -> str:
    return json.dumps([round(float(value), 6) for value in vector], separators=(",", ":"))


def deserialize_embedding(payload: Any, *, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    if isinstance(payload, (list, tuple)):
        values = list(payload)
    else:
        try:
            values = json.loads(str(payload or "[]"))
        except Exception:
            values = []
    result = []
    for item in values[: max(16, int(dimensions or DEFAULT_DIMENSIONS))]:
        try:
            result.append(float(item))
        except Exception:
            result.append(0.0)
    if len(result) < max(16, int(dimensions or DEFAULT_DIMENSIONS)):
        result.extend([0.0] * (max(16, int(dimensions or DEFAULT_DIMENSIONS)) - len(result)))
    return result


def text_fingerprint(text: Any) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8", errors="replace")).hexdigest()


def _stem(token: str) -> str:
    value = str(token or "").strip().lower()
    if len(value) > 5 and value.endswith("ies"):
        return value[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if len(value) > len(suffix) + 4 and value.endswith(suffix):
            return value[: -len(suffix)]
    return value
