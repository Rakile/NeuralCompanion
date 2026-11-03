"""Verified, private Python bootstrap for the explicit NC main installer only."""
from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

PYTHON_VERSION = '3.12.16'
PYTHON_URL = ('https://github.com/astral-sh/python-build-standalone/releases/download/20261026/'
              'cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz')
PYTHON_SIZE = 47113364
PYTHON_SHA256 = '590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5'
_MANIFEST = '.nc-python312.json'
_OWNER = 'NeuralCompanion LiquidAI Python'


def private_python312(app_root: Path) -> Path:
    return Path(app_root).resolve() / '.venvs' / 'liquidai_python312' / 'python.exe'


def _check_cancelled(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise RuntimeError('Private Python 3.12 installation cancelled.')


def _probe_python312(executable: Path, environment: dict[str, str]) -> bool:
    if not executable.is_file():
        return False
    try:
        result = subprocess.run([str(executable), '-I', '-B', '-c',
            'import sys,ssl,venv,ensurepip; assert sys.version_info[:2] == (3,12)'],
            capture_output=True, timeout=10, env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _check_location(root: Path, directory: Path) -> None:
    for path in (directory.parent, directory):
        if path.resolve() != path or not path.is_relative_to(root):
            raise RuntimeError(f'Private Python destination is redirected: {path}')


def _download(archive: Path, cancelled: Callable[[], bool], progress: Callable[[str], None]) -> None:
    progress('Downloading private Python 3.12 for LiquidAI…')
    _check_cancelled(cancelled)
    request = urllib.request.Request(PYTHON_URL, headers={'User-Agent': 'NeuralCompanion-LiquidAI-Setup'})
    digest = hashlib.sha256()
    received = 0
    last_percent = -1
    with urllib.request.urlopen(request, timeout=3) as response, archive.open('xb') as output:
        while True:
            _check_cancelled(cancelled)
            chunk = response.read1(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > PYTHON_SIZE:
                raise ValueError('Private Python archive exceeds the pinned size.')
            digest.update(chunk)
            output.write(chunk)
            percent = received * 100 // PYTHON_SIZE
            if percent != last_percent:
                progress(f'Downloading private Python 3.12: {percent}%')
                last_percent = percent
    _check_cancelled(cancelled)
    if received != PYTHON_SIZE:
        raise ValueError('Private Python archive size does not match the pinned release.')
    if digest.hexdigest() != PYTHON_SHA256:
        raise ValueError('Private Python archive SHA256 does not match the pinned release.')


def _extract(archive: Path, temporary: Path, cancelled: Callable[[], bool]) -> Path:
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}
    with tarfile.open(archive, 'r:gz') as source:
        seen = set()
        for member in source:
            _check_cancelled(cancelled)
            parts = PurePosixPath(member.name).parts
            key = '/'.join(parts).casefold()
            if (not parts or parts[0] != 'python' or key in seen
                    or not (member.isfile() or member.isdir()) or '\\' in member.name
                    or any(part in {'.', '..'} or part.endswith(('.', ' '))
                           or part.split('.', 1)[0].upper() in reserved
                           or any(char in part for char in ':<>"|?*\x00') for part in parts)):
                raise ValueError(f'Unsafe private Python archive path: {member.name!r}')
            seen.add(key)
            target = temporary.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as contents, target.open('xb') as output:
                    shutil.copyfileobj(contents, output)
    return temporary / 'python'


def ensure_python312(app_root: Path, cancelled: Callable[[], bool], progress: Callable[[str], None],
                     *, environment: dict[str, str]) -> str:
    """Install a relocatable interpreter without registry, PATH or .venv writes."""
    _check_cancelled(cancelled)
    if sys.platform != 'win32' or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise RuntimeError('Automatic Python 3.12 setup supports Windows x64. Install compatible Python 3.12 and retry.')
    root = Path(app_root).resolve()
    executable = private_python312(root)
    directory = executable.parent
    _check_location(root, directory)
    metadata = dict(schema_version=1, owner=_OWNER, version=PYTHON_VERSION,
                    url=PYTHON_URL, sha256=PYTHON_SHA256)
    if directory.exists():
        marker = directory / _MANIFEST
        try:
            intact = (marker.resolve() == marker and marker.stat().st_size < 4096
                      and json.loads(marker.read_text(encoding='utf-8')) == metadata)
        except (OSError, ValueError):
            intact = False
        if intact and _probe_python312(executable, environment):
            return str(executable)
        raise RuntimeError(f'Private Python has existing unrecognized or incomplete content; preserve it and repair this folder: {directory}')
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.liquidai-python312-', dir=directory.parent) as temporary:
        staging = Path(temporary)
        archive = staging / 'python312.tar.gz'
        _download(archive, cancelled, progress)
        progress('Verifying private Python 3.12, venv and pip support…')
        extracted = _extract(archive, staging, cancelled)
        if not _probe_python312(extracted / 'python.exe', environment):
            raise RuntimeError('Downloaded Python 3.12 interpreter failed its isolated runtime check.')
        (extracted / _MANIFEST).write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        _check_cancelled(cancelled)
        _check_location(root, directory)
        # Windows rename refuses an existing destination, including a concurrent
        # install. Never clear or replace an interpreter or an unknown folder.
        extracted.rename(directory)
    progress('Private Python 3.12 is ready for LiquidAI.')
    return str(executable)
