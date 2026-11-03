"""Repair only archive ranges touched by an explicitly mapped history edit.

The caller drains session effects before entering. No inference, database
creation, file deletion, or guessing of duplicate message identities occurs.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core import continuity_memory, long_term_memory as ltm
from core.memory_message_deletion import DeletionRecoveryError, _replace_bytes
from core.memory_asset_metadata import image_link_metadata, remove_unreferenced_images, image_candidates_from_turns


def repair_history_memories(*, database_path: Path, summary_path: Path | None,
                           memory_id: str, source_chat_id: str, previous_history,
                           replacement_history, source_indices,
                           archive_batch_size: int = ltm.DEFAULT_EXTRACTION_TURNS,
                           retained_asset_ids=()) -> dict:
    """Indices are one-based original rows, in the replacement's exact order.

    Current editors change/remove rows; unsupported insertion/reordering fails
    before any writes rather than attributing memories to the wrong messages.
    """
    indices = list(source_indices)
    if (len(indices) != len(replacement_history)
            or any(type(n) is not int or not 1 <= n <= len(previous_history) for n in indices)
            or indices != sorted(set(indices))):
        raise ValueError('History repair requires unique, ordered original message positions.')
    result = dict(changed=False, chunks_rebuilt=0, chunks_deleted=0, records_deleted=0,
                  summary_cleared=0, unknown_provenance=0, rebuilt_chunk_ids=[],
                  embeddings_deleted=0, asset_links_deleted=0, assets_deleted=0,
                  shared_assets_preserved=0, detached_targets=0)
    if list(previous_history) == list(replacement_history):
        return result
    result['changed'] = True
    positions = {old: new for new, old in enumerate(indices, 1)}
    old_turns = {t['index']: t for t in ltm.sanitize_history_turns(list(previous_history))}
    new_turns = {t['index']: t for t in ltm.sanitize_history_turns(list(replacement_history))}
    def equivalent(old):
        before = dict(old_turns.get(old, {})); before.pop('index', None)
        after = dict(new_turns.get(positions.get(old), {})); after.pop('index', None)
        return before == after
    changed_rows = {n for n in range(1, len(previous_history)+1)
                    if n not in positions or not equivalent(n)}
    previous_summary = summary_path.read_bytes() if summary_path is not None and summary_path.is_file() else None
    connection = None
    summary_written = False
    try:
        if database_path.is_file():
            pending_ids = {chunk['id'] for chunk in ltm.pending_archive_chunks(
                batch_size=archive_batch_size, path=database_path)}
            connection = sqlite3.connect(database_path.resolve().as_uri() + '?mode=rw', uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute('BEGIN IMMEDIATE')
            pending_chunks, pending_links, detached_images = {}, [], set()
            detached_images.update(image_candidates_from_turns(connection,
                [previous_history[n-1] for n in changed_rows]))
            tables = [('long_term_memory_chunks', 'chunk'), ('long_term_memory', 'record')]
            rowsets = [(table, kind, connection.execute(
                f"SELECT * FROM {table} WHERE source_chat_id=? AND status='active'", (source_chat_id,)).fetchall())
                for table, kind in tables]
            original_links = {(kind, row['id']): connection.execute(
                'SELECT * FROM long_term_memory_asset_links WHERE target_kind=? AND target_id=?',
                (kind, row['id'])).fetchall() for _, kind, rows in rowsets for row in rows}
            for table, kind, rows in rowsets:
                for row in rows:
                    start, end = row['source_message_start'], row['source_message_end']
                    if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= len(previous_history):
                        result['unknown_provenance'] += 1
                        continue
                    members = [n for n in range(start, end+1) if n in positions]
                    touched = any(n in changed_rows for n in range(start, end+1))
                    identity = row['id']
                    tags = json.loads(row['tags_json'] or '[]') if kind == 'chunk' else []
                    if kind == 'chunk' and identity in pending_ids and 'batch_pending' not in tags:
                        tags.append('batch_pending')
                    target = identity
                    links = original_links[(kind, identity)]
                    if touched:
                        result['embeddings_deleted'] += connection.execute('DELETE FROM long_term_memory_embeddings WHERE target_kind=? AND target_id=?', (kind, identity)).rowcount
                        if kind == 'chunk':
                            result['embeddings_deleted'] += connection.execute("DELETE FROM long_term_memory_embeddings WHERE target_kind='chunk_slice' AND substr(target_id,1,?)=?",
                                               (len(identity)+2, identity+'_s')).rowcount
                        connection.execute(f'DELETE FROM {table} WHERE id=?', (identity,))
                        if kind == 'record':
                            result['records_deleted'] += 1
                            members = []  # Derived claims cannot be safely patched as raw text.
                        else:
                            result['chunks_deleted'] += 1
                    if members:
                        first, last = positions[members[0]], positions[members[-1]]
                        if kind == 'chunk':
                            selected = [new_turns[positions[n]] for n in members if positions[n] in new_turns]
                            text = ltm.format_history_segment(selected)
                            if touched and text:
                                target = ltm.chunk_id_for_segment(source_chat_id, first, last, text)
                                if 'batch_pending' not in tags and 'batch_complete' not in tags:
                                    tags.append('batch_complete')
                                pending_chunks[target] = (target, source_chat_id, first, last, text,
                                    json.dumps(tags), row['created_at'], ltm._now_iso(), row['status'])
                                if target not in result['rebuilt_chunk_ids']:
                                    result['chunks_rebuilt'] += 1
                                    result['rebuilt_chunk_ids'].append(target)
                            elif not touched:
                                # Keep the exact indexed text and slice boundaries.
                                # Only canonical source positions changed here.
                                connection.execute('UPDATE long_term_memory_chunks SET source_message_start=?,source_message_end=?,tags_json=? WHERE id=?',
                                                   (first, last, json.dumps(tags), identity))
                        else:
                            connection.execute(f'UPDATE {table} SET source_message_start=?,source_message_end=? WHERE id=?', (first, last, identity))
                    # Re-key source positions in links; retain the underlying images.
                    connection.execute('DELETE FROM long_term_memory_asset_links WHERE target_kind=? AND target_id=?', (kind, identity))
                    detached_images.update(link['asset_id'] for link in links)
                    for link in links if members else []:
                        old_index = link['source_message_index']
                        if old_index not in positions:
                            if touched:
                                continue
                            # Legacy links with unknown source positions still
                            # belong to an unchanged chunk; never discard them.
                            pending_links.append(tuple(link[key] for key in ('id', 'asset_id', 'target_kind',
                                'target_id', 'source_chat_id', 'source_message_index', 'role', 'relation',
                                'metadata_json', 'created_at')))
                            continue
                        old_assets = (old_turns.get(old_index) or {}).get('assets', [])
                        new_assets = (new_turns.get(positions[old_index]) or {}).get('assets', [])
                        if old_assets != new_assets:
                            continue
                        index = positions[old_index]
                        link_id = ltm._asset_link_id(link['asset_id'], kind, target, index, link['relation'])
                        pending_links.append((link_id, link['asset_id'], kind, target, source_chat_id, index,
                             link['role'], link['relation'], ltm._metadata_json(image_link_metadata(link['metadata_json'], index)), link['created_at']))
            # Apply rebuilt targets after all original rows are reconciled. An
            # overlapping source may have the same ID as a replacement target.
            connection.executemany('INSERT INTO long_term_memory_chunks '
                '(id,source_chat_id,source_message_start,source_message_end,text,tags_json,created_at,updated_at,status) '
                'VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING', pending_chunks.values())
            connection.executemany('INSERT OR IGNORE INTO long_term_memory_asset_links '
                '(id,asset_id,target_kind,target_id,source_chat_id,source_message_index,role,relation,metadata_json,created_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)', pending_links)
            result.update(remove_unreferenced_images(connection, detached_images,
                retained_turns=replacement_history, retained_asset_ids=retained_asset_ids))
        if previous_summary is not None:
            cleared = continuity_memory.memory_payload(memory_id=memory_id, source_turn_count=0)
            _replace_bytes(summary_path, json.dumps(cleared, ensure_ascii=False).encode('utf-8'))
            summary_written = True
            result['summary_cleared'] = 1
        if connection is not None:
            connection.commit()
        return result
    except BaseException:
        if connection is not None:
            connection.rollback()
        if summary_written:
            try:
                _replace_bytes(summary_path, previous_summary)
            except OSError as error:
                raise DeletionRecoveryError('Memory repair needs recovery; the edited history was not applied.') from error
        raise
    finally:
        if connection is not None:
            connection.close()
