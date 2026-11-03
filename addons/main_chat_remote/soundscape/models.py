"""Validated wire data; private media paths never belong in these contracts."""
from __future__ import annotations

import math
import re
from typing import Literal, TypedDict

SoundKind = Literal['ambience', 'music', 'effect']
LayerName = Literal['ambience', 'music']


class LayerSettings(TypedDict):
    asset_id: str | None
    follow_story: bool
    volume: float
    muted: bool


class SoundscapeState(TypedDict):
    version: int
    conversation_id: str
    revision: int
    enabled: bool
    paused: bool
    duck_speech: bool
    ambience: LayerSettings
    music: LayerSettings
    effects: dict


class MediaDescriptor(TypedDict):
    asset_id: str
    sha256: str
    source_hash: str
    profile: str
    byte_length: int
    duration_ms: int
    channels: int
    sample_rate: int
    content_type: str
    url_path: str


class SoundAsset(TypedDict):
    id: str
    revision: int
    title: str
    description: str
    kind: SoundKind
    category: str
    gain: float
    tags: list[str]
    duration_ms: int
    source: str
    loop: bool
    content_hash: str
    media: MediaDescriptor


def identity(value: object, *, asset: bool = False) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError('Invalid soundscape identity.')
    if asset and not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('Invalid sound asset identity.')
    return value


def boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError('Expected a boolean.')
    return value


def volume(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Volume must be between zero and one.')
    return float(value)


def metadata(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - {'title', 'description', 'kind', 'category', 'gain', 'tags', 'loop', 'discarded'}:
        raise ValueError('Invalid sound metadata.')
    result = {'title': value.get('title', ''), 'description': value.get('description', ''),
              'kind': value.get('kind'), 'category': value.get('category', 'Uncategorized'),
              'gain': value.get('gain', 1.0), 'tags': value.get('tags', []), 'loop': value.get('loop', False),
              'discarded': boolean(value.get('discarded', False))}
    for key, limit in [('title', 120), ('description', 2000)]:
        if not isinstance(result[key], str) or len(result[key]) > limit:
            raise ValueError('Sound text is too long or invalid.')
    if not result['title'].strip() or result['kind'] not in ('ambience', 'music', 'effect'):
        raise ValueError('Choose a sound title and kind.')
    category = result['category']
    if not isinstance(category, str) or not category.strip() or len(category.strip()) > 64:
        raise ValueError('Choose a category of up to 64 characters.')
    result['category'] = category.strip()
    result['gain'] = volume(result['gain'])
    tags = result['tags']
    if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t, str) or not t.strip() or len(t) > 32 for t in tags):
        raise ValueError('Invalid sound tags.')
    result['tags'] = list(dict.fromkeys(tags))
    result['loop'] = boolean(result['loop'])
    return result


def defaults(conversation_id: str) -> SoundscapeState:
    return {'version': 1, 'conversation_id': identity(conversation_id), 'revision': 0,
            'enabled': False, 'paused': True, 'duck_speech': True,
            'ambience': {'asset_id': None, 'follow_story': False, 'volume': .20, 'muted': False},
            'music': {'asset_id': None, 'follow_story': False, 'volume': .15, 'muted': False},
            'effects': {'enabled':False,'volume':.20,'muted':False}}


def apply_patch(state: dict, patch: object, *, manual: bool = True) -> None:
    if not isinstance(patch, dict) or set(patch) - {'enabled', 'paused', 'duck_speech', 'ambience', 'music', 'effects'}:
        raise ValueError('Invalid soundscape settings.')
    for key, value in patch.items():
        if key == 'effects':
            if not isinstance(value, dict) or set(value)-{'enabled','volume','muted'}:
                raise ValueError('Invalid sound effect settings.')
            for field,item in value.items():
                state['effects'][field] = volume(item) if field == 'volume' else boolean(item)
            continue
        if key not in ('ambience', 'music'):
            state[key] = boolean(value)
            continue
        if not isinstance(value, dict) or set(value) - {'asset_id', 'follow_story', 'volume', 'muted'}:
            raise ValueError('Invalid sound layer.')
        for field, item in value.items():
            state[key][field] = (None if item is None else identity(item, asset=True)) if field == 'asset_id' else volume(item) if field == 'volume' else boolean(item)
        if manual and 'asset_id' in value:
            state[key]['follow_story'] = False
