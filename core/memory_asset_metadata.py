"""Image position metadata and scoped cleanup in caller-owned transactions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections.abc import Mapping


def image_link_metadata(value, message_index):
    if isinstance(value, dict):
        metadata = dict(value)
    else:
        try:
            metadata = json.loads(value or '{}')
        except (TypeError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
    if isinstance(message_index, int) and message_index > 0:
        metadata['turn_index'] = message_index
    else:
        metadata.pop('turn_index', None)
    return metadata


def normalize_image_position_metadata(connection):
    """One-time normalization; image identity is shared, positions live on links."""
    for identity, raw in connection.execute('SELECT id,metadata_json FROM long_term_memory_assets').fetchall():
        try:
            original = json.loads(raw or '{}')
        except (TypeError, ValueError):
            continue
        if not isinstance(original, dict):
            continue
        metadata = image_link_metadata(original, None)
        if metadata != original:
            connection.execute('UPDATE long_term_memory_assets SET metadata_json=? WHERE id=?',
                               (json.dumps(metadata, sort_keys=True), identity))
    for identity, index, raw in connection.execute(
            'SELECT id,source_message_index,metadata_json FROM long_term_memory_asset_links').fetchall():
        try:
            original = json.loads(raw or '{}')
        except (TypeError, ValueError):
            continue
        if not isinstance(original, dict):
            continue
        metadata = image_link_metadata(original, index)
        if metadata != original:
            connection.execute('UPDATE long_term_memory_asset_links SET metadata_json=? WHERE id=?',
                               (json.dumps(metadata, sort_keys=True), identity))


def _image_fingerprints(turns):
    from core import long_term_memory
    paths, hashes, unresolved = set(), set(), False
    for turn in turns:
        if not isinstance(turn, Mapping):
            continue
        nested = turn.get('metadata')
        raw = dict(nested) if isinstance(nested, Mapping) else {}
        raw.update(turn)
        assets = list(raw.get('assets') or ())
        # Do not use sanitize_history_turns: image-only generated replies can
        # legitimately have no text yet still retain the underlying image.
        assets.extend(long_term_memory._image_assets_from_turn(raw, str(raw.get('role') or 'user')))
        for asset in assets:
            if not isinstance(asset, Mapping):
                unresolved = True
                continue
            path = str(asset.get('path') or '')
            if not path or path in paths:
                continue
            paths.add(path)
            try:
                with Path(path).open('rb') as handle:
                    hashes.add(hashlib.file_digest(handle, 'sha256').hexdigest())
            except (OSError, ValueError):
                unresolved = True
    return paths, hashes, unresolved


def image_candidates_from_turns(connection, turns):
    """Find removed images even when their last message wasn't archived yet."""
    paths, hashes, _ = _image_fingerprints(turns)
    if not paths:
        return set()
    return {identity for identity, digest, metadata in connection.execute(
        'SELECT id,sha256,metadata_json FROM long_term_memory_assets')
        if digest in hashes or image_link_metadata(metadata, None).get('original_path') in paths}


def remove_unreferenced_images(connection, candidates, *, retained_turns=(), retained_asset_ids=()):
    """Only consider images detached by this edit; never sweep unrelated orphans.

    Live history can reference an image before that message is archived. A
    retained image that cannot be read makes deletion conservative.
    """
    candidates = set(candidates)
    if not candidates:
        return dict(assets_deleted=0, shared_assets_preserved=0)
    _, hashes, unresolved = _image_fingerprints(retained_turns)
    protected = set(retained_asset_ids)
    deleted = preserved = 0
    for identity in candidates:
        row = connection.execute('SELECT sha256 FROM long_term_memory_assets WHERE id=?', (identity,)).fetchone()
        if row is None:
            continue
        if (unresolved or identity in protected or row[0] in hashes or connection.execute(
                'SELECT 1 FROM long_term_memory_asset_links WHERE asset_id=? LIMIT 1', (identity,)).fetchone()):
            preserved += 1
        else:
            deleted += connection.execute('DELETE FROM long_term_memory_assets WHERE id=?', (identity,)).rowcount
    return dict(assets_deleted=deleted, shared_assets_preserved=preserved)
