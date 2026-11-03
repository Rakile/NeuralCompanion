"""Validated audio storage; never overwrites an existing voice reference."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import wave
from typing import Callable

from core.voice_references import local_voice_reference_files
from .models import VoiceRecord

MAX_AUDIO_BYTES = 100 * 1024 * 1024
VOICE_CATEGORIES = ('narrator', 'everyday', 'fantasy', 'sci-fi', 'royal-noble',
                    'warriors', 'villains', 'creatures', 'comedy', 'soft-soothing')
_metadata_lock = threading.RLock()


class VoiceMetadataConflict(Exception):
    """The editor must reload newer voice metadata before overwriting it."""


def voice_reference_id(path: str | Path) -> str:
    return 'voice_' + hashlib.sha256(Path(path).name.casefold().encode()).hexdigest()[:32]


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.voice-studio-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def inspect_wav(data: bytes) -> tuple[int, float]:
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError('Audio exceeds the 100 MiB limit.')
    try:
        with wave.open(io.BytesIO(data), 'rb') as source:
            frames, channels, width, rate = (source.getnframes(), source.getnchannels(), source.getsampwidth(), source.getframerate())
            if frames <= 0 or channels not in (1, 2) or width not in (1, 2, 3, 4) or not 8000 <= rate <= 192000:
                raise ValueError('Unsupported or empty PCM WAV.')
            if len(source.readframes(frames)) != frames * channels * width:
                raise ValueError('Truncated WAV recording.')
            return rate, frames / rate
    except (wave.Error, EOFError) as error:
        raise ValueError('Invalid PCM WAV recording.') from error


def pcm_wav(data: bytes) -> bytes:
    if data[:4] == b'RIFF':
        inspect_wav(data)
        return data
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError('Empty or oversized audio response.')
    try:
        import soundfile as sf
        samples, rate = sf.read(io.BytesIO(data), always_2d=True)
        if samples.size == 0 or samples.shape[1] not in (1, 2):
            raise ValueError('Empty or unsupported audio.')
        output = io.BytesIO()
        sf.write(output, samples, rate, format='WAV', subtype='PCM_16')
        result = output.getvalue()
        inspect_wav(result)
        return result
    except Exception as error:
        raise ValueError('Could not decode audio with the installed decoder.') from error


def safe_name(value: str) -> str:
    result = re.sub(r'[^\w -]', '_', value, flags=re.UNICODE).strip(' ._')[:64] or 'Voice'
    if result.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        result = 'Voice_' + result
    return result


class LibraryRepository:
    def __init__(self, app_root: Path, storage_root: Path):
        self.app_root = Path(app_root).resolve()
        self.root = self.app_root / 'voices'
        self.storage = Path(storage_root).resolve()

    def reference_path(self, path: Path) -> Path:
        path = Path(path)
        path = (path if path.is_absolute() else self.app_root / path).resolve()
        if path.parent != self.root.resolve() or path.suffix.lower() != '.wav':
            raise ValueError('Reference must be a WAV in NC voices.')
        return path

    def _metadata(self, path: Path) -> dict:
        value = read_json(self.storage / 'metadata' / (path.name + '.json'), {})
        return value if isinstance(value, dict) else {}

    def display_name(self, path: Path) -> str:
        path = self.reference_path(path)
        return str(self._metadata(path).get('name') or path.stem)

    def remove_recording(self, path: Path, commit: Callable[[], None]) -> None:
        """Remove one validated local WAV, restoring it if card persistence fails."""
        path = self.reference_path(path)
        if not path.is_file():
            raise ValueError('The recording is no longer available. Refresh the library.')
        fd, temporary = tempfile.mkstemp(prefix='.removed-voice-', dir=self.root)
        os.close(fd)
        staged = Path(temporary)
        try:
            os.replace(path, staged)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
        try:
            commit()
        except BaseException:
            # If restoration itself fails, retain the staged recording for recovery.
            os.replace(staged, path)
            raise
        staged.unlink(missing_ok=True)
        (self.storage / 'metadata' / (path.name + '.json')).unlink(missing_ok=True)

    @staticmethod
    def _user_fields(metadata: dict) -> dict:
        return {'description': str(metadata.get('description', metadata.get('voice_description', ''))),
                'notes': str(metadata.get('notes', '')), 'archived': metadata.get('archived') is True,
                'category': metadata.get('category') if metadata.get('category') in VOICE_CATEGORIES else '',
                'favorite': metadata.get('favorite') is True,
                'metadata_revision': metadata.get('metadata_revision', 0)}

    def organize(self, path: Path, patch: dict, revision: int, operation_id: str) -> None:
        if not isinstance(patch, dict) or not patch or set(patch) - {'category', 'favorite', 'description'}:
            raise ValueError('Choose category, favorite, or description to update.')
        if 'category' in patch and patch['category'] not in ('', *VOICE_CATEGORIES):
            raise ValueError('Choose a valid voice category.')
        if 'favorite' in patch and type(patch['favorite']) is not bool:
            raise ValueError('Favorite must be true or false.')
        if 'description' in patch and (not isinstance(patch['description'], str) or len(patch['description']) > 5000):
            raise ValueError('Voice description must be text up to 5000 characters.')
        path = self.reference_path(path)
        with _metadata_lock:
            if not path.is_file():
                raise KeyError('Voice no longer exists.')
            metadata = self._metadata(path)
            operation = {'id': operation_id, 'revision': revision, 'patch': patch}
            if metadata.get('organization_operation') == operation:
                return
            if type(revision) is not int or revision != metadata.get('metadata_revision', 0):
                raise VoiceMetadataConflict()
            atomic_json(self.storage / 'metadata' / (path.name + '.json'),
                {**metadata, **patch, 'metadata_revision': revision + 1, 'organization_operation': operation})

    def update_metadata(self, path: Path, *, description: str | None = None,
                        notes: str | None = None, archived: bool | None = None) -> None:
        with _metadata_lock:
            self._update_metadata(path, description=description, notes=notes, archived=archived)

    def _update_metadata(self, path: Path, *, description: str | None = None,
                         notes: str | None = None, archived: bool | None = None) -> None:
        path = self.reference_path(path)
        if not path.is_file():
            raise ValueError('The recording is no longer available. Refresh the library.')
        metadata = self._metadata(path)
        for key, value in (('description', description), ('notes', notes)):
            if value is not None:
                if not isinstance(value, str) or len(value) > 10000:
                    raise ValueError('Voice descriptions and notes must be text under 10,001 characters.')
                metadata[key] = value
        if archived is not None:
            metadata['archived'] = bool(archived)
        metadata['metadata_revision'] = metadata.get('metadata_revision', 0) + 1
        metadata.pop('organization_operation', None)
        atomic_json(self.storage / 'metadata' / (path.name + '.json'), metadata)

    def inspect(self, path: Path) -> VoiceRecord:
        path = self.reference_path(path)
        if path.stat().st_size > MAX_AUDIO_BYTES:
            raise ValueError('Voice recording is too large.')
        data = path.read_bytes()
        rate, duration = inspect_wav(data)
        metadata = self._metadata(path)
        return VoiceRecord(str(path), str(metadata.get('name') or path.stem), rate, duration,
                           hashlib.sha256(data).hexdigest(), str(metadata.get('provider') or 'Existing WAV'),
                           **self._user_fields(metadata))

    def scan(self) -> tuple[VoiceRecord, ...]:
        result = []
        for path in local_voice_reference_files(self.app_root):
            try:
                result.append(self.inspect(path))
            except (OSError, ValueError) as error:
                result.append(VoiceRecord(str(path), path.stem, valid=False, error=str(error),
                                          **self._user_fields(self._metadata(path))))
        return tuple(result)

    def publish_audio(self, data: bytes, name: str, identity: str, metadata: dict) -> VoiceRecord:
        data = pcm_wav(data)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', identity):
            raise ValueError('Invalid recording identity.')
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / (safe_name(name) + '_' + identity + '.wav')
        # Catch case-insensitive aliases even on development platforms that allow them.
        existing = next((p for p in self.root.iterdir() if p.name.lower() == target.name.lower()), None)
        if existing is not None:
            target = existing
            if target.is_symlink() or target.read_bytes() != data:
                raise ValueError('A different recording already owns this filename.')
        else:
            fd, staged = tempfile.mkstemp(prefix='.voice-studio-', dir=self.root)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                # An atomic link publishes complete bytes without replace/overwrite.
                os.link(staged, target)
            finally:
                Path(staged).unlink(missing_ok=True)
        record = self.inspect(target)
        if record.fingerprint != hashlib.sha256(data).hexdigest():
            raise ValueError('Saved WAV verification failed.')
        safe_metadata = {k: v for k, v in metadata.items() if k in {'provider', 'model_id', 'voice_description', 'preview_text', 'seed', 'instruction', 'created_at'}}
        with _metadata_lock:
            atomic_json(self.storage / 'metadata' / (target.name + '.json'),
                        {**self._metadata(target), **safe_metadata, 'schema': 1, 'name': name, 'fingerprint': record.fingerprint})
        return self.inspect(target)
