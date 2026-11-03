"""Select a small transcript window without copying canonical message payloads."""

from collections.abc import Mapping

from core.visual_reply_history import VISUAL_REPLY_IMAGE_FIELDS

DEFAULT_VISUAL_BATCH_SIZE = 200


def _has_visual_reply_image(metadata: Mapping) -> bool:
    nested = metadata.get("metadata")
    for source in (metadata, nested if isinstance(nested, Mapping) else {}):
        for field in VISUAL_REPLY_IMAGE_FIELDS:
            value = source.get(field)
            values = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
            if any(str(path or "").strip() for path in values):
                return True
    return False


def normalize_visual_batch_size(value):
    try:
        size = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_VISUAL_BATCH_SIZE
    return size if size == -1 or 0 < size <= 2147483647 else DEFAULT_VISUAL_BATCH_SIZE


class ConversationVisualWindow:
    def __init__(self):
        self.reset()

    def reset(self):
        self.batch_size = DEFAULT_VISUAL_BATCH_SIZE
        self.generation = None
        self.cleared_through_id = ""
        self.indexes = ()
        self._ids = ()
        self._focus = None
        self.following_latest = True
        self.total = 0
        self.has_older = False
        self.has_newer = False

    def update(self, snapshot, batch_size, *, protected=False, show_visual_replies: bool = True):
        messages = snapshot.messages
        size = normalize_visual_batch_size(batch_size)
        generation = snapshot.session_generation
        previous_ids = set(self._ids)
        replaced = previous_ids and not any(item.message_id in previous_ids for item in messages)
        if generation != self.generation or replaced:
            self.reset()
            self.generation = generation
        if size != self.batch_size:
            self.jump_to_latest()
        self.batch_size = size
        floor = 0
        if self.cleared_through_id:
            floor = next((index + 1 for index, item in enumerate(messages)
                          if item.message_id == self.cleared_through_id), 0)
            if not floor:
                self.cleared_through_id = ""
        # Only lightweight indexes are scanned; message payloads stay in the
        # canonical snapshot. Retained IDs and decorated rows remain bounded.
        displayable = []
        wanted = set(self._ids) | set(self._focus or ())
        positions = {}
        for index in range(floor, len(messages)):
            item = messages[index]
            if (item.content.strip() or item.metadata.get("attachment_image_path")
                    or (item.metadata.get("metadata") or {}).get("attachment_image_path")
                    or (show_visual_replies and _has_visual_reply_image(item.metadata))):
                if item.message_id in wanted:
                    positions[item.message_id] = len(displayable)
                displayable.append(index)
        self.total = len(displayable)
        focus_start = positions.get(self._focus[0]) if self._focus else None
        focus_end = positions.get(self._focus[1]) if self._focus else None
        if protected and self._ids:
            selected = [displayable[positions[key]] for key in self._ids if key in positions]
        elif size == -1:
            selected = displayable
        elif self.following_latest or focus_start is None or focus_end is None:
            span = max(1, focus_end - focus_start + 1) if focus_start is not None and focus_end is not None else 1
            selected = displayable[-max(size, span):]
            self.following_latest = True
        else:
            start, end = sorted((focus_start, focus_end))
            selected = displayable[max(0, start - size):end + size + 1]
        self.indexes = tuple(selected)
        self._ids = tuple(messages[index].message_id for index in selected)
        self.has_older = bool(selected and selected[0] != displayable[0])
        self.has_newer = bool(selected and selected[-1] != displayable[-1])
        return self.indexes

    def expand(self):
        if self.has_older and self.batch_size != -1:
            self.set_viewport(self._ids[0], self._ids[min(self.batch_size, len(self._ids)) - 1], False)

    def set_viewport(self, first_id, last_id, following_latest):
        self._focus = (str(first_id), str(last_id))
        self.following_latest = bool(following_latest)

    def remap_edited_message(self, previous_id, replacement_id):
        """Retain visual custody after an accepted, same-row message edit."""
        self._ids = tuple(replacement_id if key == previous_id else key for key in self._ids)
        if self._focus:
            self._focus = tuple(replacement_id if key == previous_id else key for key in self._focus)
        if self.cleared_through_id == previous_id:
            self.cleared_through_id = replacement_id

    def jump_to_latest(self):
        self._focus = None
        self.following_latest = True

    def clear(self, snapshot):
        self.update(snapshot, self.batch_size)
        self.cleared_through_id = snapshot.messages[-1].message_id if snapshot.messages else ""
        self.update(snapshot, self.batch_size)
