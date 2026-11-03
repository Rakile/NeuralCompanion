"""Recover paid dialogue bytes locally without overwriting recovery evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .library import inspect_wav


def _binding(row: dict) -> dict:
    return {key: row[key] for key in ('id', 'account', 'voice_id', 'text', 'model')}


def _recovery_error(path: Path) -> ValueError:
    return ValueError(f'Dialogue recovery artifact is damaged or does not match: {path}. '
                      'It was left untouched. Restore it or explicitly reset the dialogue before continuing.')


def _write_exclusive(path: Path, data: bytes) -> None:
    # Retain even an incomplete write: never erase the only surviving paid bytes.
    with path.open('xb') as output:
        if output.write(data) != len(data):
            raise OSError('Incomplete dialogue recovery write; the artifact was retained.')
        output.flush()
        os.fsync(output.fileno())


def retain_response(stage: Path, row: dict, data: bytes) -> None:
    header = {'schema': 1, 'binding': _binding(row), 'length': len(data),
              'sha256': hashlib.sha256(data).hexdigest()}
    payload = json.dumps(header, ensure_ascii=True, sort_keys=True).encode('ascii') + b'\n' + data
    _write_exclusive(stage.with_suffix('.response'), payload)


def _read_response(path: Path, row: dict) -> bytes:
    try:
        if path.is_symlink():
            raise ValueError('Symlink recovery artifact')
        encoded, data = path.read_bytes().split(b'\n', 1)
        header = json.loads(encoded)
        if (header.get('schema') != 1 or header.get('binding') != _binding(row)
                or header.get('length') != len(data)
                or header.get('sha256') != hashlib.sha256(data).hexdigest()):
            raise ValueError('Recovery verification failed')
        return data
    except (ValueError, AttributeError, OSError) as error:
        raise _recovery_error(path) from error


def _read_wav(path: Path) -> bytes:
    try:
        if path.is_symlink():
            raise ValueError('Symlink recovery artifact')
        data = path.read_bytes()
        inspect_wav(data)
        return data
    except (ValueError, OSError) as error:
        raise _recovery_error(path) from error


def recover_stage(stage: Path, row: dict, convert) -> Path | None:
    """Only a verified local artifact can resolve a synthesis intent."""
    response = stage.with_suffix('.response')
    pending = stage.with_suffix('.wav.pending')
    data = _read_response(response, row) if response.exists() or response.is_symlink() else None
    converted = convert(data) if data is not None else None
    if converted is not None:
        inspect_wav(converted)
    final_data = _read_wav(stage) if stage.exists() or stage.is_symlink() else None
    pending_data = _read_wav(pending) if pending.exists() or pending.is_symlink() else None
    # A valid WAV is insufficient when the captured paid response is available:
    # it must contain that response's audio before publication or cloud cleanup.
    for path, surviving in ((stage, final_data), (pending, pending_data)):
        if converted is not None and surviving is not None and surviving != converted:
            raise _recovery_error(path)
    if final_data is not None:
        if pending_data is not None and pending_data != final_data:
            raise _recovery_error(pending)
        return stage
    if pending_data is None:
        if data is None:
            return None
        # Conversion and validation happen before any final WAV can exist.
        _write_exclusive(pending, converted)
        if _read_wav(pending) != converted:
            raise _recovery_error(pending)
    else:
        # A previous fsync may have failed after a complete write.
        with pending.open('r+b') as source:
            os.fsync(source.fileno())
    # Publish complete bytes atomically; never replace an existing artifact.
    os.link(pending, stage)
    _read_wav(stage)
    return stage
