"""Pure remapping of a saved chat into a fresh story conversation scope."""
from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any


_SCOPE_ID = re.compile(r'[0-9a-f]{32}\Z')
_CAST_FIELDS = {'chat_character_id', 'source_character_id', 'character_id', 'persona_id'}


def clone_chat_scope(payload: Mapping[str, object], conversation_id: str,
                     memory_id: str, card_ids: Mapping[str, str]) -> dict[str, object]:
    """Change internal identities without touching message text or turn IDs."""
    if not isinstance(payload, Mapping):
        raise ValueError('Saved chat context is invalid.')
    if not _SCOPE_ID.fullmatch(conversation_id) or not _SCOPE_ID.fullmatch(memory_id):
        raise ValueError('Fresh story scope identifiers are invalid.')
    if not isinstance(card_ids, Mapping) or any(
            not isinstance(old, str) or not isinstance(new, str)
            for old, new in card_ids.items()):
        raise ValueError('Story character identity map is invalid.')

    def remap(value: Any, field: str = '') -> Any:
        if isinstance(value, dict):
            return {key: remap(item, str(key)) for key, item in value.items()}
        if isinstance(value, list):
            return [remap(item, field) for item in value]
        if isinstance(value, str) and field in _CAST_FIELDS:
            if value in card_ids:
                return card_ids[value]
            if field == 'chat_character_id' and value.startswith('cc_'):
                raise ValueError('Saved chat references an unavailable character.')
        return copy.deepcopy(value)

    cloned = remap(dict(payload))
    cloned['chat_character_conversation_id'] = conversation_id
    cloned['continuity_memory_id'] = memory_id
    return cloned
