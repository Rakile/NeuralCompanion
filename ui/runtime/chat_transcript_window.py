from __future__ import annotations

from difflib import SequenceMatcher

from core import conversation_history


DEFAULT_VISUAL_BATCH_SIZE = 200


def normalize_visual_batch_size(value, default=DEFAULT_VISUAL_BATCH_SIZE):
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return int(default)
    return normalized if normalized == -1 or normalized > 0 else int(default)


def _displayable(entry):
    if not isinstance(entry, dict):
        return False
    return bool(
        str(entry.get("content", "") or "").strip()
        or str(entry.get("attachment_image_path", "") or "").strip()
    )


def displayable_history_indexes(history):
    return tuple(
        index
        for index, entry in enumerate(list(history or []))
        if _displayable(entry)
    )


def initial_window(history, batch_size):
    indexes = displayable_history_indexes(history)
    limit = normalize_visual_batch_size(batch_size)
    selected = indexes if limit == -1 else indexes[-limit:]
    return tuple(selected), len(indexes)


def previous_batch(history, visible_indexes, batch_size):
    all_indexes = displayable_history_indexes(history)
    visible = tuple(int(index) for index in tuple(visible_indexes or ()))
    if not visible or not all_indexes or visible[0] == all_indexes[0]:
        return ()
    try:
        first_position = all_indexes.index(visible[0])
    except ValueError:
        return ()
    limit = normalize_visual_batch_size(batch_size)
    start = 0 if limit == -1 else max(0, first_position - limit)
    return tuple(all_indexes[start:first_position])


def _signature(item):
    entry = dict(item or {})
    return (
        str(entry.get("role", "") or "").strip().lower(),
        str(entry.get("origin", "") or "").strip().lower(),
        str(entry.get("content", "") or "").strip(),
    )


def merge_edited_window(
    history,
    *,
    visible_indexes,
    original_display_entries,
    edited_entries,
    created_at=None,
):
    full = [dict(entry) if isinstance(entry, dict) else entry for entry in list(history or [])]
    indexes = tuple(int(index) for index in tuple(visible_indexes or ()))
    if not indexes:
        return full
    if tuple(sorted(set(indexes))) != indexes:
        raise ValueError("Visible history indexes must be unique and sorted.")
    if indexes[0] < 0 or indexes[-1] >= len(full):
        raise IndexError("Visible history index is outside the conversation history.")

    originals = [full[index] for index in indexes]
    displayed = [dict(entry) for entry in list(original_display_entries or [])]
    edited = [dict(entry) for entry in list(edited_entries or [])]
    if len(displayed) != len(originals):
        raise ValueError("Visible history and display entry counts do not match.")

    merged_visible = conversation_history.merge_edited_history_metadata(
        originals,
        displayed,
        edited,
        created_at=created_at,
    )
    gaps_after = []
    for offset, history_index in enumerate(indexes):
        next_index = indexes[offset + 1] if offset + 1 < len(indexes) else history_index + 1
        gaps_after.append(full[history_index + 1:next_index])

    rebuilt = []
    matcher = SequenceMatcher(
        a=[_signature(entry) for entry in displayed],
        b=[_signature(entry) for entry in edited],
        autojunk=False,
    )
    for _tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        old_count = old_end - old_start
        new_count = new_end - new_start
        paired = min(old_count, new_count)
        for offset in range(paired):
            rebuilt.append(merged_visible[new_start + offset])
            rebuilt.extend(gaps_after[old_start + offset])
        rebuilt.extend(merged_visible[new_start + paired:new_end])
        for old_index in range(old_start + paired, old_end):
            rebuilt.extend(gaps_after[old_index])

    return full[:indexes[0]] + rebuilt + full[indexes[-1] + 1:]
