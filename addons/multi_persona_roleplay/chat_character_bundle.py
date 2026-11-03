"""Private, conversation-scoped cast bundles for Main Chat story saves."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from addons.voice_studio.library import LibraryRepository

from .chat_characters import ChatCharacterService


def _managed_file(value: str, root: Path) -> Path:
    path = Path(value).resolve()
    if not path.is_file() or not path.is_relative_to(root.resolve()):
        raise FileNotFoundError('Saved character media is unavailable.')
    return path


def _bundled_file(bundle_dir: Path, relative: str, kind: str) -> Path:
    parts = Path(relative).parts if isinstance(relative, str) else ()
    if (len(parts) != 3 or parts[:2] != ('assets', kind)
            or any(part in {'.', '..'} for part in parts)):
        raise ValueError('Saved character media path is invalid.')
    path = (bundle_dir / relative).resolve()
    if not path.is_relative_to(bundle_dir.resolve()) or not path.is_file():
        raise ValueError('Saved character media is missing or outside the story.')
    return path


def export_story_cast(service: ChatCharacterService, library: LibraryRepository,
                      portrait_root: Path, conversation_id: str, target_dir: Path) -> dict[str, Any]:
    """Copy the cast and all assigned media without mutating live cards."""
    target_dir = Path(target_dir)
    if target_dir.exists() and any(target_dir.iterdir()):
        raise ValueError('Story cast destination is not empty.')
    snapshot = service.export_story_snapshot(conversation_id)
    assets: list[tuple[Path, Path]] = []
    for row in snapshot['characters']:
        persona = row['persona']
        voice = persona['voice']
        if row.get('voice_id') or voice.get('enabled'):
            source = _managed_file(str(voice.get('sample_path') or ''), library.root)
            source = library.reference_path(source)
            library.inspect(source)
            relative = Path('assets/voice') / (hashlib.sha256(source.read_bytes()).hexdigest() + '.wav')
            voice['sample_path'] = relative.as_posix()
            assets.append((source, target_dir / relative))
        image_path = str(persona.get('character_image_path') or '')
        if row.get('portrait_asset_id') or image_path:
            source = _managed_file(image_path, portrait_root)
            if source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise ValueError('Saved character portrait format is invalid.')
            relative = Path('assets/portrait') / (hashlib.sha256(source.read_bytes()).hexdigest() + source.suffix.lower())
            persona['character_image_path'] = relative.as_posix()
            assets.append((source, target_dir / relative))
    target_dir.mkdir(parents=True, exist_ok=True)
    for source, destination in assets:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
    (target_dir / 'cast.json').write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
    return {'revision': snapshot['revision'],
            'character_names': [row['persona']['display_name'] for row in snapshot['characters']]}


def validate_story_cast(service: ChatCharacterService, bundle_dir: Path) -> tuple[dict[str, Any], list[tuple[dict[str, Any], Path | None, Path | None]]]:
    """Preflight the complete cast and its files without publishing media."""
    bundle_dir = Path(bundle_dir)
    snapshot = json.loads((bundle_dir / 'cast.json').read_text(encoding='utf-8'))
    service.validate_story_snapshot(snapshot)
    rows = snapshot['characters']
    # Resolve every source before publishing any managed media.
    sources: list[tuple[dict[str, Any], Path | None, Path | None]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('persona'), dict):
            raise ValueError('Saved story character is invalid.')
        persona = row['persona']
        voice = persona.get('voice')
        if not isinstance(voice, dict):
            raise ValueError('Saved story character voice is invalid.')
        voice_file = (_bundled_file(bundle_dir, voice['sample_path'], 'voice')
                      if row.get('voice_id') or voice.get('enabled') else None)
        image_file = (_bundled_file(bundle_dir, persona['character_image_path'], 'portrait')
                      if row.get('portrait_asset_id') or persona.get('character_image_path') else None)
        sources.append((row, voice_file, image_file))
    return snapshot, sources


def restore_story_cast(service: ChatCharacterService, library: LibraryRepository,
                       portrait_root: Path, bundle_dir: Path, conversation_id: str) -> dict[str, str]:
    """Restore bundled media into managed roots and clone cards atomically."""
    snapshot, sources = validate_story_cast(service, bundle_dir)
    for row, voice_file, image_file in sources:
        persona = row['persona']
        if voice_file is not None:
            data = voice_file.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            record = library.publish_audio(data, str(persona.get('display_name') or 'Story voice'),
                                           'story_' + digest[:24], {'provider': 'Story Library'})
            persona['voice']['sample_path'] = record.path
            row['voice_id'] = 'voice_' + hashlib.sha256(Path(record.path).name.casefold().encode()).hexdigest()[:32]
        if image_file is not None:
            data = image_file.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            destination = Path(portrait_root) / 'story-library-assets' / (digest + image_file.suffix.lower())
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.read_bytes() != data:
                    raise ValueError('Saved portrait conflicts with existing media.')
            else:
                destination.write_bytes(data)
            persona['character_image_path'] = str(destination)
    return service.restore_story_snapshot(snapshot, conversation_id)
