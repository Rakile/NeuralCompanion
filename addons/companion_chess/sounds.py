"""Addon-owned sound assignments; source audio is copied, never modified."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

SOUND_KEYS=tuple(f'{event}_{color}' for color in ('white','black') for event in
    ('move_pawn','move_knight','move_bishop','move_rook','move_queen','move_king','capture','castle','check','checkmate','select'))+('illegal','start','end')


def update_sounds(directory: Path, current: dict, action: str, fields: dict) -> dict:
    assignments=dict(current)
    def assign(key, source):
        if key not in SOUND_KEYS: raise ValueError('Unknown sound slot.')
        path=Path(source).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in {'.wav','.mp3','.ogg','.flac','.m4a'}:
            raise ValueError('Choose an existing audio file.')
        if path.stat().st_size>50_000_000: raise ValueError('Choose an audio file smaller than 50 MB.')
        directory.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        destination=directory/(key+'-'+digest+path.suffix.lower())
        if path!=destination.resolve(): shutil.copyfile(path,destination)
        assignments[key]=str(destination)
    if action=='sound_import':
        path=Path(fields.get('path') or 'I:/chess/sound_settings.json').resolve()
        if path.stat().st_size>100_000: raise ValueError('Sound settings file is too large.')
        data=json.loads(path.read_text(encoding='utf-8')).get('files',{})
        if not isinstance(data,dict): raise ValueError('Invalid sound settings.')
        for key,value in data.items():
            if key in SOUND_KEYS and value:
                source=Path(value)
                assign(key,source if source.is_absolute() else path.parent/source)
    elif action=='sound_assign': assign(fields.get('key'),fields.get('path',''))
    elif action=='sound_clear':
        if fields.get('key') not in SOUND_KEYS: raise ValueError('Unknown sound slot.')
        assignments.pop(fields['key'],None)
    else: raise ValueError('Unknown sound action.')
    return assignments
