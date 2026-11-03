"""Recognize explicit questions about what is visible on the user's desktop."""

from __future__ import annotations

import re


_VISUAL_REFERENCE = re.compile(
    r"\b(?:on (?:my|the) (?:screen|desktop|monitor)|"
    r"(?:this|the|my) (?:screen|screenshot|window|page|tab)|"
    r"(?:youtube|video|clip|movie) (?:i am|i'm|we are|we're) watching|"
    r"(?:i am|i'm|we are|we're) watching|"
    r"(?:can you see|do you see|what do you see)|"
    r"(?:look at|read from) (?:my|the) (?:screen|desktop))\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(
    r"\b(?:what|which|where|who|how|can you|could you|do you|tell me|read|identify|"
    r"comment|describe|explain|summarize|look)\b",
    re.IGNORECASE,
)


def is_visual_question(text: object) -> bool:
    utterance = " ".join(str(text or "").split())
    return bool(utterance and _VISUAL_REFERENCE.search(utterance) and _QUESTION.search(utterance))


def needs_conversation_reference(target: str) -> bool:
    """A standalone location shortcut cannot resolve pronouns or compound requests."""
    return bool(re.search(r"\b(?:this|that|other|previous|first|second|it|them|and)\b", target, re.I))
