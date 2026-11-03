"""Scoped memory reconciliation in a caller-owned SQLite transaction.

No file operations, global orphan sweeps, or commits belong here. NULL ranges
mean deliberately detached/unknown provenance, never the next message's source.
"""
from __future__ import annotations

import sqlite3
import json
import os
import tempfile
from pathlib import Path
from core.memory_asset_metadata import image_link_metadata, remove_unreferenced_images, image_candidates_from_turns


class DeletionRecoveryError(RuntimeError):
    """History remains intact but memory storage requires recovery."""


def _replace_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name, delete=False) as handle:
            staged = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if staged is not None and staged.exists():
            staged.unlink()


def delete_message_memories(*, database_path: Path, summary_path: Path | None,
                           memory_id: str, source_chat_id: str, message_index: int,
                           history_count: int, remove_memories: bool,
                           retained_asset_ids=(), removed_image_turns=(), retained_image_turns=()) -> dict[str, int]:
    """Existing bound store only. Caller has drained all session effects.

    No automatic creation of a memory database for an unsaved chat. The summary
    is reversible until SQLite commits; the caller publishes history afterward.
    """
    if not source_chat_id or not 1 <= message_index <= history_count:
        raise ValueError('A source chat and current message position are required.')
    from core import continuity_memory
    previous = summary_path.read_bytes() if summary_path is not None and summary_path.is_file() else None
    connection = None
    changed_summary = False
    try:
        if database_path.is_file():
            connection = sqlite3.connect(database_path.resolve().as_uri() + '?mode=rw', uri=True)
            connection.execute('BEGIN IMMEDIATE')
        if remove_memories and summary_path is not None and previous is not None:
            payload = continuity_memory.memory_payload(memory_id=memory_id, source_turn_count=0)
            _replace_bytes(summary_path, json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            changed_summary = True
        result = (reconcile_deleted_message(connection, source_chat_id=source_chat_id,
                    message_index=message_index, history_count=history_count,
                    remove_memories=remove_memories, retained_asset_ids=retained_asset_ids,
                    removed_image_turns=removed_image_turns, retained_image_turns=retained_image_turns)
                  if connection is not None else dict(records_deleted=0, chunks_deleted=0,
                    embeddings_deleted=0, asset_links_deleted=0, assets_deleted=0,
                    detached_targets=0, unknown_provenance=0, shared_assets_preserved=0))
        if connection is not None:
            connection.commit()
        result['summary_cleared'] = int(changed_summary)
        return result
    except BaseException:
        recovery_error = None
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.Error as rollback_error:
                recovery_error = rollback_error
            except OSError as rollback_error:
                recovery_error = rollback_error
        if changed_summary:
            try:
                _replace_bytes(summary_path, previous)
            except OSError as rollback_error:
                recovery_error = rollback_error
        if recovery_error is not None:
            raise DeletionRecoveryError('Message kept, but memory cleanup could not be fully rolled back. '
                                        'Retry this same deletion with memory cleanup enabled before continuing.') from recovery_error
        raise
    finally:
        if connection is not None:
            connection.close()


def reconcile_deleted_message(
    connection: sqlite3.Connection, *, source_chat_id: str, message_index: int,
    history_count: int, remove_memories: bool, retained_asset_ids=(),
    removed_image_turns=(), retained_image_turns=(),
) -> dict[str, int]:
    if not source_chat_id or not 1 <= message_index <= history_count:
        raise ValueError('A source chat and current message position are required.')
    result = dict(records_deleted=0, chunks_deleted=0, embeddings_deleted=0,
                  asset_links_deleted=0, assets_deleted=0, detached_targets=0,
                  unknown_provenance=0, shared_assets_preserved=0)
    candidates = {row[0] for row in connection.execute(
        'SELECT asset_id FROM long_term_memory_asset_links WHERE source_chat_id=? AND source_message_index=?',
        (source_chat_id, message_index))}
    candidates.update(image_candidates_from_turns(connection, removed_image_turns))
    for table, kind, counter in (
        ('long_term_memory', 'record', 'records_deleted'),
        ('long_term_memory_chunks', 'chunk', 'chunks_deleted'),
    ):
        rows = connection.execute(
            f'SELECT id, source_message_start, source_message_end FROM {table} '
            'WHERE source_chat_id = ?', (source_chat_id,)).fetchall()
        for identity, start, end in rows:
            if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= history_count:
                result['unknown_provenance'] += 1
                continue
            if start <= message_index <= end:
                if not remove_memories:
                    connection.execute(
                        f'UPDATE {table} SET source_message_start=NULL, source_message_end=NULL WHERE id=?',
                        (identity,))
                    result['detached_targets'] += 1
                    continue
                candidates.update(row[0] for row in connection.execute(
                    'SELECT asset_id FROM long_term_memory_asset_links '
                    'WHERE target_kind=? AND target_id=? AND source_chat_id=? AND source_message_index=?',
                    (kind, identity, source_chat_id, message_index)))
                result['asset_links_deleted'] += connection.execute(
                    'DELETE FROM long_term_memory_asset_links WHERE target_kind=? AND target_id=?',
                    (kind, identity)).rowcount
                result['embeddings_deleted'] += connection.execute(
                    'DELETE FROM long_term_memory_embeddings WHERE target_kind=? AND target_id=?',
                    (kind, identity)).rowcount
                if kind == 'chunk':
                    # substr avoids interpreting wildcard characters in target IDs.
                    result['embeddings_deleted'] += connection.execute(
                        "DELETE FROM long_term_memory_embeddings WHERE target_kind='chunk_slice' "
                        "AND substr(target_id,1,?)=?",
                        (len(identity) + 2, identity + '_s')).rowcount
                connection.execute(f'DELETE FROM {table} WHERE id=?', (identity,))
                result[counter] += 1
            elif start > message_index:
                connection.execute(
                    f'UPDATE {table} SET source_message_start=?, source_message_end=? WHERE id=?',
                    (start - 1, end - 1, identity))

    # Link IDs encode the old index. Reinsert after deleting the old IDs so the
    # UNIQUE index cannot collide during rebasing or create duplicate future links.
    links = connection.execute(
        'SELECT id, asset_id, target_kind, target_id, source_message_index, role, relation, metadata_json, created_at '
        'FROM long_term_memory_asset_links WHERE source_chat_id=? AND source_message_index>=?',
        (source_chat_id, message_index)).fetchall()
    if links:
        from core.long_term_memory import _asset_link_id
        connection.executemany('DELETE FROM long_term_memory_asset_links WHERE id=?', [(row[0],) for row in links])
        for _, asset, kind, target, index, role, relation, metadata, created in links:
            if index == message_index:
                result['asset_links_deleted'] += 1
                continue
            # Keep unknown target links rather than guessing which content to erase.
            new_index = index - 1
            connection.execute(
                'INSERT OR IGNORE INTO long_term_memory_asset_links '
                '(id,asset_id,target_kind,target_id,source_chat_id,source_message_index,role,relation,metadata_json,created_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (_asset_link_id(asset, kind, target, new_index, relation), asset, kind, target,
                 source_chat_id, new_index, role, relation,
                 json.dumps(image_link_metadata(metadata, new_index), sort_keys=True), created))

    result.update(remove_unreferenced_images(connection, candidates, retained_asset_ids=retained_asset_ids,
                                            retained_turns=retained_image_turns))
    return result
