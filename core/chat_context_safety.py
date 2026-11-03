"""Content identity shared by chat saves and unsaved-history protection."""
import hashlib
import json
from collections.abc import Mapping


def history_signature(history):
    def plain(value):
        if isinstance(value, Mapping):
            return {str(k): plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [plain(v) for v in value]
        return value
    return hashlib.sha256(json.dumps(plain(list(history)), sort_keys=True,
        ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def export_session_with_history_receipt(chat):
    """Pair an export with its pre-save live-history identity when stable.

    Export sanitizes temporary metadata, so its rows cannot normally be compared
    with live rows. If history changes during export, callers instead use the
    exported rows' identity; an edit/undo must not bless a different saved file.
    """
    snapshot = getattr(chat, 'snapshot', None)
    before = snapshot() if snapshot is not None else None
    history = getattr(chat, 'history', None)
    signature = history_signature(history()) if history is not None else None
    result = chat.export_session()
    if before is not None:
        after = snapshot()
        if (before.session_generation, getattr(before, 'revision', None)) != (
                after.session_generation, getattr(after, 'revision', None)):
            signature = None
    return result, signature
