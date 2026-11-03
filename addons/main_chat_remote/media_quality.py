"""Desktop-only media preferences, sampled when a new authenticated peer opens."""
import json
import os
from pathlib import Path

PRESETS = {
    'low': dict(opus_kbps=24, video_kbps=200, video_width=256, video_fps=12),
    'balanced': dict(opus_kbps=32, video_kbps=500, video_width=448, video_fps=24),
    'high': dict(opus_kbps=64, video_kbps=1000, video_width=448, video_fps=24),
}
LIMITS = {'opus_kbps': (16, 96), 'video_kbps': (100, 2000), 'video_width': (160, 448), 'video_fps': (6, 24)}


def validate_quality(value):
    if not isinstance(value, dict) or set(value) != set(LIMITS) | {'preset'}:
        raise ValueError('Invalid media quality settings')
    if value['preset'] not in {*PRESETS, 'custom'}:
        raise ValueError('Unknown media preset')
    for key, (low, high) in LIMITS.items():
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError('Media quality outside supported bounds')
    if value['video_width'] % 2 or value['video_fps'] not in (6, 8, 12, 24):
        raise ValueError('Use an even width and 6, 8, 12 or 24 fps')
    return dict(value)


def load_quality(root):
    try:
        return validate_quality(json.loads((Path(root)/'media-quality.json').read_text('utf-8')))
    except (OSError, ValueError, TypeError):
        return dict(preset='balanced', **PRESETS['balanced'])


def video_quality(value):
    """Validated video-only identity; changing Opus never invalidates loops."""
    if isinstance(value, str):
        if value not in PRESETS:
            raise ValueError('Unknown media preset')
        value = PRESETS[value]
    if not isinstance(value, dict):
        raise ValueError('Invalid video quality')
    fields = ('video_kbps', 'video_width', 'video_fps')
    if not set(fields) <= set(value) or not set(value) <= set(LIMITS) | {'preset'}:
        raise ValueError('Invalid video quality')
    result = {key: value[key] for key in fields}
    validate_quality(dict(preset='custom', opus_kbps=32, **result))
    return result


def save_quality(root, patch):
    if not isinstance(patch, dict) or not set(patch) <= set(LIMITS) | {'preset'}:
        raise ValueError('Invalid media quality update')
    value = load_quality(root)
    if 'preset' in patch:
        if patch['preset'] not in PRESETS:
            raise ValueError('Unknown preset')
        value = dict(preset=patch['preset'], **PRESETS[patch['preset']])
    elif patch:
        value['preset'] = 'custom'
    value.update(patch)
    validate_quality(value)
    target = Path(root)/'media-quality.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, target)
    return value
