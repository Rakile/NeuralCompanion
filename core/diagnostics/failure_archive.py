"""Verified, content-addressed failure archives. No automatic archive eviction.

Only finalized immutable captures are eligible. An OS lock serializes archivists
across processes; capture writers keep using atomic slot reservation independently.
All compression belongs on the maintenance worker, never the journal writer.
"""
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from core.diagnostics.retention import DEFAULT_RETENTION

BLOCK = 256 * 1024
IDENTIFIER = re.compile(r'[0-9a-f]{64}')
SLOT = re.compile(r'capture-\d{2}')
FINAL = {'captured', 'partial', 'failed'}


class ArchiveBusy(Exception):
    pass


class ArchiveCapacity(Exception):
    pass


def _plain(path, *, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
        raise ValueError('archive_redirected_path')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('archive_unexpected_file_type')


def _directory(path):
    path.mkdir(exist_ok=True)
    _plain(path, directory=True)


@contextmanager
def archive_lock(root):
    """Crash-released lock; the persistent lock file is not a stale reservation."""
    root = Path(root)
    _plain(root, directory=True)
    lock_path = root / '.archive.lock'
    if lock_path.exists():
        _plain(lock_path)
    with lock_path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ArchiveBusy() from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _digest(path):
    _plain(path)
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as incoming:
        for block in iter(lambda: incoming.read(BLOCK), b''):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _json(path):
    _plain(path)
    with path.open('rb') as handle:
        raw = handle.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('archive_metadata_oversized')
    return json.loads(raw)


def _verify_blob(path, digest, size, output=None):
    _plain(path)
    actual = hashlib.sha256()
    count = 0
    with gzip.open(path, 'rb') as incoming:
        while True:
            block = incoming.read(min(BLOCK, size - count + 1))
            if not block:
                break
            count += len(block)
            if count > size:
                raise ValueError('archive_size_mismatch')
            actual.update(block)
            if output is not None:
                output.write(block)
    if count != size or actual.hexdigest() != digest:
        raise ValueError('archive_checksum_mismatch')


def _archive_bytes(archive):
    total = 0
    for name in ('blobs', 'captures'):
        for path in (archive / name).iterdir():
            _plain(path)
            total += path.stat().st_size
    return total


class _BudgetWriter:
    def __init__(self, handle, remaining):
        self.handle = handle
        self.remaining = remaining

    def write(self, data):
        if len(data) > self.remaining:
            raise ArchiveCapacity()
        result = self.handle.write(data)
        self.remaining -= result
        return result


def _store_blob(source, archive, digest, size, limits):
    destination = archive / 'blobs' / (digest + '.gz')
    if not destination.exists():
        temporary = archive / 'blobs' / (digest + '.pending')
        # Only our known uncommitted temporary, under the exclusive archive lock.
        if temporary.exists():
            _plain(temporary)
            temporary.unlink()
        try:
            with temporary.open('xb') as outgoing:
                writer = _BudgetWriter(outgoing, limits.archive_bytes - _archive_bytes(archive))
                with gzip.GzipFile(filename='', fileobj=writer, mode='wb', compresslevel=1, mtime=0) as zipped:
                    with source.open('rb') as incoming:
                        for block in iter(lambda: incoming.read(BLOCK), b''):
                            zipped.write(block)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            _verify_blob(temporary, digest, size)
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    _verify_blob(destination, digest, size)


def _index(archive, identifier):
    if not IDENTIFIER.fullmatch(identifier):
        raise ValueError('archive_invalid_identifier')
    record = _json(archive / 'captures' / (identifier + '.json'))
    if record.get('version') != 1 or record.get('manifest_sha256') != identifier:
        raise ValueError('archive_invalid_index')
    files = record.get('files')
    if not isinstance(files, list) or not files or len(files) > 256:
        raise ValueError('archive_invalid_files')
    seen = set()
    for entry in files:
        name = entry['file']
        if (not isinstance(name, str) or not name or name in ('.', '..')
                or any(c in name for c in '/\\:') or name in seen
                or not IDENTIFIER.fullmatch(entry['sha256'])
                or type(entry['bytes']) is not int or entry['bytes'] < 0):
            raise ValueError('archive_invalid_entry')
        seen.add(name)
        _verify_blob(archive / 'blobs' / (entry['sha256'] + '.gz'), entry['sha256'], entry['bytes'])
    manifest = next((entry for entry in files if entry['file'] == 'manifest.json'), None)
    if manifest is None or manifest['sha256'] != identifier:
        raise ValueError('archive_missing_manifest')
    return record


def _retire(folder, archive, identifier):
    """Verify the committed archive and all remaining originals before removal.

    Rename frees the slot atomically only AFTER verification. Crash leftovers have
    an unambiguous archived-ID name, unlike a newly reserved empty capture slot.
    """
    record = _index(archive, identifier)
    expected = {entry['file']: entry for entry in record['files']}
    _plain(folder, directory=True)
    sources = list(folder.iterdir())
    for path in sources:
        entry = expected.get(path.name)
        if entry is None or _digest(path) != (entry['sha256'], entry['bytes']):
            raise ValueError('archive_original_changed')
    retired = folder.parent / ('archived-' + identifier)
    if folder != retired:
        if retired.exists():
            raise ValueError('archive_retirement_collision')
        folder.rename(retired)
    # No recursive deletion. Every file was checked against a verified blob.
    for source in sources:
        (retired / source.name).unlink()
    retired.rmdir()


def _archive_one(folder, archive, limits):
    manifest_path = folder / 'manifest.json'
    identifier, _ = _digest(manifest_path)
    destination = archive / 'captures' / (identifier + '.json')
    if not destination.exists():
        entries = []
        for path in sorted(folder.iterdir()):
            digest, size = _digest(path)
            _store_blob(path, archive, digest, size, limits)
            entries.append(dict(file=path.name, sha256=digest, bytes=size))
        record = dict(version=1, manifest_sha256=identifier, files=entries)
        encoded = json.dumps(record, separators=(',', ':')).encode('utf-8')
        temporary = destination.with_suffix('.pending')
        if temporary.exists():
            _plain(temporary)
            temporary.unlink()
        if _archive_bytes(archive) + len(encoded) > limits.archive_bytes:
            raise ArchiveCapacity()
        try:
            with temporary.open('xb') as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    _retire(folder, archive, identifier)


def _failure(report, stage, error):
    report['status'] = 'archive_failed'
    report['errors'] += 1
    report['last_error'] = dict(stage=stage, error_type=type(error).__name__,
                                errno=getattr(error, 'errno', None))
    if type(error) is ValueError and str(error).startswith('archive_'):
        report['last_error']['reason'] = str(error)


def archive_completed(root, *, keep_latest=0, before_ns=None, limits=DEFAULT_RETENTION):
    """Archive finalized snapshots; return sanitized status, never log contents."""
    if type(keep_latest) is not int or keep_latest < 0:
        raise ValueError('archive_invalid_keep_latest')
    root = Path(root)
    report = dict(status='ready', archived=0, skipped=0, errors=0, archive_bytes=0,
                  archive_limit_bytes=limits.archive_bytes, warning=False)
    if not root.exists():
        return report
    try:
        with archive_lock(root):
            archive = root / 'archive'
            _directory(archive)
            _directory(archive / 'blobs')
            _directory(archive / 'captures')
            for retired in root.glob('archived-*'):
                identifier = retired.name.removeprefix('archived-')
                if IDENTIFIER.fullmatch(identifier):
                    try:
                        _retire(retired, archive, identifier)
                        report['archived'] += 1
                    except Exception as error:
                        _failure(report, 'retired_cleanup', error)
            candidates = []
            for folder in root.iterdir():
                if not SLOT.fullmatch(folder.name):
                    continue
                try:
                    _plain(folder, directory=True)
                    manifest = folder / 'manifest.json'
                    if (_json(manifest).get('status') not in FINAL
                            or (before_ns is not None and manifest.stat().st_mtime_ns > before_ns)):
                        report['skipped'] += 1
                        continue
                    candidates.append((manifest.stat().st_mtime_ns, folder))
                except (OSError, ValueError, TypeError, AttributeError):
                    report['skipped'] += 1
            candidates.sort(key=lambda pair: (pair[0], pair[1].name))
            eligible = candidates[:-keep_latest] if keep_latest else candidates
            for _, folder in eligible:
                try:
                    _archive_one(folder, archive, limits)
                    report['archived'] += 1
                except ArchiveCapacity:
                    report['status'] = 'archive_capacity_reached'
                    break
                except Exception as error:
                    _failure(report, 'capture_archive', error)
            report['archive_bytes'] = _archive_bytes(archive)
            report['warning'] = report['archive_bytes'] >= limits.archive_bytes * limits.warn_fraction
            if report['warning'] and report['status'] == 'ready':
                report['status'] = 'archive_near_capacity'
    except ArchiveBusy:
        report['status'] = 'archive_busy'
    except Exception as error:
        _failure(report, 'archive_scan', error)
    return report


def restore_capture(root, archive_id, destination):
    """Materialize exact original files into a NEW directory for normal audit tools."""
    root, destination = Path(root), Path(destination)
    with archive_lock(root):
        archive = root / 'archive'
        _plain(archive, directory=True)
        _plain(archive / 'blobs', directory=True)
        _plain(archive / 'captures', directory=True)
        record = _index(archive, archive_id)
        destination.mkdir()  # Never overwrite a user's existing evidence.
        for entry in record['files']:
            with (destination / entry['file']).open('xb') as handle:
                _verify_blob(archive / 'blobs' / (entry['sha256'] + '.gz'),
                             entry['sha256'], entry['bytes'], output=handle)
                handle.flush()
                os.fsync(handle.fileno())
    return destination
