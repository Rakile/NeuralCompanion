"""Pure text formatters safe for presentation-layer imports."""

from __future__ import annotations


def format_archive_progress(
    *,
    archived_through: int,
    total_messages: int,
    archive_interval: int,
    auto_archive_enabled: bool,
    saved_pending_messages: int = 0,
) -> str:
    total = max(0, int(total_messages or 0))
    archived = max(0, min(int(archived_through or 0), total))
    pending = max(0, total - archived)
    interval = max(1, int(archive_interval or 1))
    waiting = pending + max(0, int(saved_pending_messages))
    if not auto_archive_enabled:
        progress = "Messages until next archive: Long-Term Memory archiving is off."
    elif waiting >= interval:
        progress = "Messages until next archive: 0 (eligible on the next completed reply)."
    else:
        progress = f"Messages until next archive: {interval - waiting}"
    return (
        f"Archived messages: {archived}/{total}. "
        f"Unarchived messages: {pending}. {progress}"
    )


__all__ = ["format_archive_progress"]
