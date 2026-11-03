"""Bounded refiner context from public history; never reads staged successors."""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence


def extension_context(plan: Mapping[str, Any], history: Sequence[Mapping[str, Any]],
                      played_ids: set[str]) -> str:
    # Older turns form a compact continuity digest; retain the recent played
    # dialogue in more detail. The last assistant may still be speaking.
    turns = list(history)[-120:]
    last_assistant = next((i for i in range(len(turns)-1, -1, -1)
                           if turns[i].get('role') == 'assistant'), -1)
    rendered = []
    for index, turn in enumerate(turns):
        role = turn.get('role')
        if role not in {'user', 'assistant'}:
            continue
        if index == last_assistant and str(turn.get('id') or turn.get('turn_id') or '') not in played_ids:
            break
        text = str(turn.get('content') or '').strip()
        if text:
            limit = 1000 if index >= len(turns)-12 else 100
            rendered.append(f'{role}: {text[:limit]}')
    # Full original premise and constraints, but bounded prior outline for long
    # stories. Existing titles prevent retelling finished beats.
    beats = list(plan['beats'])
    outline = [{'title': b['title'], 'summary': b['summary'][:350]} for b in beats[-20:]]
    return json.dumps({'title': plan['title'], 'premise': plan['premise'],
        'constraints': plan['constraints'], 'current_beat': plan['current_beat'] + 1,
        'prior_outline': outline,
        'earlier_beat_titles': [b['title'] for b in beats[:-20]][-80:],
        'played_history_digest': '\n'.join(rendered)[-14000:],
        'history_note': 'Earlier dialogue is abbreviated. An unplayed final reply is excluded. '
                        'Preserve established characters, relationships and unresolved events.'}, ensure_ascii=False)
