"""Transactional default-avatar ZIP installation; no runtime dependencies."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import uuid
import zipfile
import zlib

from installer_storage import plain_path, require_free_space, write_with_space_check


def _members(archive, pack_id):
    members = []
    seen = set()
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}
    for item in archive.infolist():
        raw = item.filename
        path = PurePosixPath(raw)
        mode = stat.S_IFMT(item.external_attr >> 16)
        key = raw.rstrip('/').casefold()
        if (not path.parts or path.parts[0] != pack_id or path.is_absolute()
                or '\\' in raw or str(path) != raw.rstrip('/') or key in seen
                or any(p in ('.','..') or p.endswith(('.', ' ')) or ':' in p
                       or p.split('.')[0].upper() in reserved for p in path.parts)
                or mode not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1):
            raise ValueError(f'Unsafe or unsupported avatar archive entry: {raw!r}')
        seen.add(key)
        members.append(item)
    if not any(not item.is_dir() for item in members):
        raise ValueError('Avatar archive contains no files.')
    return members


def _matches(root, members):
    if not root.is_dir():
        return False
    for item in members:
        path = root.parent.joinpath(*PurePosixPath(item.filename).parts)
        plain_path(path)
        if item.is_dir():
            if not path.is_dir():
                return False
            continue
        if not path.is_file() or path.stat().st_size != item.file_size:
            return False
        crc = 0
        with path.open('rb') as handle:
            while chunk := handle.read(1024*1024):
                crc = zlib.crc32(chunk, crc)
        if crc != item.CRC:
            return False
    return True


def install_avatar_archive(archive_path, destination, *, progress=print):
    destination = plain_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        members = _members(archive, destination.name)
        progress(f'Checking {destination.name} avatar pack...')
        if _matches(destination, members):
            progress(f'{destination.name} avatar pack verified; already complete.')
            return dict(state='already_complete', backup='')
        total = sum(item.file_size for item in members)
        require_free_space(destination.parent, total + max(256*1024**2, total//20))
        backup = None
        # This staging directory shares the destination filesystem: publication
        # renames the complete pack instead of copying a half-installed folder.
        with tempfile.TemporaryDirectory(prefix=f'.{destination.name}.install-', dir=destination.parent) as temp:
            stage = Path(temp)
            copied = 0
            last_percent = -1
            remaining = 0
            progress(f'Extracting {destination.name}: 0%')
            for item in members:
                path = stage.joinpath(*PurePosixPath(item.filename).parts)
                if item.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, path.open('xb') as target:
                    while chunk := source.read(1024*1024):
                        remaining = write_with_space_check(target, chunk, stage, remaining)
                copied += item.file_size
                percent = min(100, copied*100//max(total,1))
                if percent >= last_percent+5 or percent == 100:
                    progress(f'Extracting {destination.name}: {percent}%')
                    last_percent = percent
            prepared = stage/destination.name
            if not _matches(prepared, members):
                raise ValueError('Extracted avatar pack failed its size/CRC validation.')
            plain_path(destination)
            if destination.exists():
                backups = plain_path(destination.parent/'.previous-installs')
                backups.mkdir(exist_ok=True)
                backup = backups/f'{destination.name}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}'
                destination.rename(backup)
            try:
                prepared.rename(destination)
            except BaseException:
                if backup is not None:
                    backup.rename(destination)
                raise
        if backup is not None:
            progress(f'Previous incomplete/different pack preserved at {backup}')
        return dict(state='installed', backup=str(backup) if backup else '')
