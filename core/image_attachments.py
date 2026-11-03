"""Ordered user-image paths, including the legacy single-image representation."""
from collections.abc import Mapping


def image_paths(turn):
    if not isinstance(turn, Mapping):
        return []
    raw = turn.get('attachment_image_paths')
    values = list(raw) if isinstance(raw, (list, tuple)) else []
    first = str(turn.get('attachment_image_path') or '').strip()
    if first and first not in values:
        values.insert(0, first)
    paths = []
    for value in values:
        if not isinstance(value, str):
            continue
        path = value.strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def set_image_paths(turn, paths):
    """Retain the first-image alias for older clients and single-image sources."""
    paths = image_paths({'attachment_image_paths': paths})
    if paths:
        turn['attachment_image_path'] = paths[0]
    else:
        turn.pop('attachment_image_path', None)
    if len(paths) > 1:
        turn['attachment_image_paths'] = paths
    else:
        turn.pop('attachment_image_paths', None)
