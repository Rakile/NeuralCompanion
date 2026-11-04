"""Installer-only disk estimates and bounded private-cache housekeeping."""
from __future__ import annotations

import math
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import sys

GB = 1_000_000_000
# Rounded upward from the Windows cu128 installation measured 2026-11-03.
# Working/temp allowances are conservative estimates, not measured peak usage.
COMPONENTS = {
    'main': dict(label='Main runtime', final=7_500_000_000, work=18*GB, temp=12*GB),
    'liquidai': dict(label='LiquidAI TTS', final=9_500_000_000, work=10*GB, temp=8*GB),
    'musetalk': dict(label='MuseTalk', final=16*GB, work=10*GB, temp=10*GB),
    'ditto': dict(label='Ditto', final=10_500_000_000, work=10*GB, temp=10*GB),
    'pockettts': dict(label='PocketTTS', final=GB, work=2*GB, temp=2*GB),
    'echo': dict(label='Echo avatar pack', final=900_000_000, work=0, temp=GB),
    'eon': dict(label='Eon avatar pack', final=800_000_000, work=0, temp=GB),
}
class InsufficientDiskSpaceError(OSError):
    """Space failure/cancellation must never trigger a network retry."""


DISPOSABLE_CACHES = (
    'runtime/installer/cache/pip',
    'runtime/liquidai_tts/cache/pip',
    'runtime/liquidai_tts/cache/uv',
)


def volume_info(path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    return os.stat(path).st_dev, str(path.anchor), shutil.disk_usage(path).free


def storage_plan(root, selected, *, temp_root=None):
    selected = list(dict.fromkeys(selected))
    if any(key not in COMPONENTS for key in selected):
        raise ValueError('Unknown install component in space estimate.')
    rows = [COMPONENTS[key] for key in selected]
    final = sum(row['final'] for row in rows)
    runtime = any(key not in ('echo', 'eon') for key in selected)
    margin = max(2*GB if runtime else GB//4, math.ceil(final*.25)) if rows else 0
    target = final + margin + max((r['work'] for r in rows), default=0)
    temporary = max((r['temp'] for r in rows), default=0)
    volumes = {}
    for path, required, purpose in (
        (Path(root), target, 'installation and private package cache'),
        (Path(temp_root or tempfile.gettempdir()), temporary, 'temporary downloads/extraction'),
    ):
        if not required:
            continue
        device, name, free = volume_info(path)
        row = volumes.setdefault(device, dict(drive=name, path=str(path), required=0, free=free, purposes=[]))
        row['required'] += required
        row['free'] = min(row['free'], free)
        row['purposes'].append(purpose)
    return dict(final_bytes=final, target_required=target, temp_required=temporary,
                volumes=list(volumes.values()), selected=selected)


def format_storage(plan):
    if not plan['selected']:
        return 'Select components to see the disk-space estimate.'
    lines = [f"Selected components: about {plan['final_bytes']/GB:.1f} GB installed (after cache cleanup)."]
    for row in plan['volumes']:
        state = 'Enough space' if row['free'] >= row['required'] else 'NOT ENOUGH SPACE'
        lines.append(f"{row['drive']} {row['free']/GB:.1f} GB free; budget {row['required']/GB:.1f} GB — {state}")
    lines.append('Budgets include safety/working space. Windows CUDA estimates; first-use models are extra. Existing installs are budgeted conservatively.')
    return '\n'.join(lines)


def require_storage(plan):
    while any(row['free'] < row['required'] for row in plan['volumes']):
        message = 'Not enough free disk space for the selected components.\n' + format_storage(plan)
        if not wait_for_space(message):
            raise InsufficientDiskSpaceError(message)
        for row in plan['volumes']:
            row['free'] = volume_info(row.get('path', row['drive']))[2]


def require_free_space(path, required):
    while (free := shutil.disk_usage(path).free) < required:
        message = f'Not enough free space at {path}: {free/GB:.2f} GB available, {required/GB:.2f} GB needed for this operation and reserve.'
        if not wait_for_space(message):
            raise InsufficientDiskSpaceError(message)


def wait_for_space(message):
    """Event-driven retry: the GUI keeps running while this worker is paused."""
    if os.environ.get('NC_INSTALLER_GUI_PROGRESS') == '1':
        print('NC_INSTALL_SPACE ' + json.dumps(dict(message=message)), flush=True)
        return sys.stdin.readline().strip() == 'continue'
    if '--non-interactive' not in sys.argv and sys.stdin is not None and sys.stdin.isatty():
        print(message + '\nFree space, then press Enter to retry (or type cancel).', flush=True)
        try:
            return input().strip().lower() not in ('cancel', 'q')
        except (EOFError, OSError):
            return False
    return False


def write_with_space_check(handle, data, directory, remaining):
    # Check on actual write activity every 32 MiB; no idle disk polling.
    if remaining < len(data):
        require_free_space(directory, len(data) + 256*1024**2)
        remaining = 32*1024**2
    handle.write(data)
    return remaining-len(data)


def is_reparse(path):
    info = Path(path).lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def plain_path(path):
    """Reject redirected paths before installer writes or recursive cleanup."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            if is_reparse(part):
                raise ValueError(f'Installer path is redirected; preserved without changes: {part}')
    return path


def pip_environment(root):
    path = plain_path(Path(root)/DISPOSABLE_CACHES[0])
    return {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PIP_CACHE_DIR': str(path)}


def cleanup_setup_caches(root, *, caches=DISPOSABLE_CACHES, progress=print):
    root = Path(root).absolute()
    for relative in caches:
        if relative not in DISPOSABLE_CACHES:
            raise ValueError('Only disposable NC installer caches may be removed.')
        path = root/relative
        try:
            plain_path(path)
            if not path.exists():
                continue
            for folder, dirs, files in os.walk(path, followlinks=False):
                for name in (*dirs, *files):
                    if is_reparse(Path(folder)/name):
                        raise ValueError(f'Redirected cache entry preserved: {Path(folder)/name}')
            shutil.rmtree(path)
            progress(f'Removed disposable installer cache: {relative}')
        except (OSError, ValueError) as exc:
            progress(f'Cache cleanup skipped; installation remains valid: {exc}')


def prepare_component_environments(root, selected, *, build_python=None, validate_only=False, progress=print):
    """A selected component gets a fresh environment, never user models/data."""
    root = plain_path(root)
    relative_paths = {
        'main': ('.venv',),
        'liquidai': ('.venvs/liquidai_tts',),
        'musetalk': ('MuseTalk/.venv',),
        'ditto': ('Ditto/.venv',),
        'pockettts': ('.venvs/pockettts',),
    }
    paths = [plain_path(root/rel) for rel in relative_paths.get(selected, ())]
    executables = [Path(sys.executable).resolve()]
    if build_python:
        executables.append(Path(shutil.which(str(build_python)) or build_python).resolve())
    for path in paths:
        if any(executable == path or path in executable.parents for executable in executables):
            raise ValueError('The installer or selected build interpreter uses a component environment. Select system Python 3.11 and launch INSTALL_NEURAL_COMPANION.bat instead.')
        if path.exists() and not path.is_dir():
            raise ValueError(f'Expected a managed environment directory, preserved this file: {path}')
    if validate_only:
        return
    for path in paths:
        if path.exists():
            # Validate the exact absolute target immediately before deletion.
            plain_path(path)
            path.relative_to(root)
            progress(f'Removing previous component environment: {path.relative_to(root)}')
            shutil.rmtree(path)
