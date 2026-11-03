"""Small immutable evidence windows for story assessment, never saved history."""
from collections.abc import Mapping, Sequence


def recent_story_replies(history: Sequence[Mapping[str, object]],
                         assistant_id: str) -> tuple[str, ...]:
    """Select earlier assistant evidence only when the observed boundary exists."""
    if not assistant_id:
        return ()
    boundary = next((i for i, turn in enumerate(history)
                     if str(turn.get('turn_id') or turn.get('id') or '') == assistant_id
                     and turn.get('role') == 'assistant'), None)
    if boundary is None:
        return ()
    recent: list[str] = []
    seen = {assistant_id}
    remaining = 6000
    for i in range(boundary - 1, -1, -1):
        turn = history[i]
        identity = str(turn.get('turn_id') or turn.get('id') or '')
        if (turn.get('role') != 'assistant' or identity in seen
                or turn.get('interrupted') or turn.get('hidden_proactive')):
            continue
        text = str(turn.get('content') or '').strip()
        if not text:
            continue
        if identity:
            seen.add(identity)
        text = text[-remaining:]
        recent.append(text)
        remaining -= len(text)
        if not remaining or len(recent) == 6:
            break
    return tuple(reversed(recent))
