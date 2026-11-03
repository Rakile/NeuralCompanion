"""Bounded immutable idle bytes. No output ordinals, grants or reader ownership.

Occurrence files are copies: the producer's existing deletion rules stay intact.
The encoder already snapshots the source frames; keep their final digest, not a
second persistent PNG copy per half-second clip, and verify the supplied tail.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from types import MappingProxyType
import uuid

from core.dev_musetalk_live_readiness import complete_png
from .media_quality import video_quality


def _sha(body):
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True, slots=True)
class IdleAssetKey:
    digest: str
    tail_digest: str = ''

    def __post_init__(self):
        if any(type(v) is not str or re.fullmatch('[a-f0-9]{64}', v) is None
               for v in (self.digest, self.tail_digest)):
            raise ValueError('ordered_idle_asset_key')

    @classmethod
    def from_frames(cls, frames, quality, *, revision=1):
        if (not 1 <= len(frames) <= 12
                or any(type(body) is not bytes or not complete_png(body) for body in frames)):
            raise ValueError('ordered_idle_asset_frames')
        return cls.from_digests([_sha(body) for body in frames], quality, revision=revision)

    @classmethod
    def from_digests(cls, digests, quality, *, revision=1):
        quality = video_quality(quality)
        if (quality['video_fps'] != 24 or type(revision) is not int or revision < 1
                or not 1 <= len(digests) <= 12
                or any(type(v) is not str or re.fullmatch('[a-f0-9]{64}', v) is None for v in digests)):
            raise ValueError('ordered_idle_asset_frames')
        identity = dict(frames=digests, quality=quality, revision=revision,
                        audio='aac-48000-mono-silence', fps=24)
        return cls(_sha(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()), digests[-1])


@dataclass(frozen=True, slots=True)
class IdleAsset:
    file: Path
    trim: dict
    tail: bytes
    digest: str | None = None
    byte_length: int = 0


def _epoch(value):
    if type(value) is not int or not 0 <= value <= (1 << 53)-1:
        raise ValueError('ordered_idle_asset_epoch')


def _trim(value):
    if (set(value) != {'validSamples', 'delaySamples', 'paddingSamples', 'rawSamples', 'sampleRate'}
            or any(type(v) is not int for v in value.values())
            or value['sampleRate'] != 48000 or not 2000 <= value['validSamples'] <= 24000
            or value['validSamples'] % 2000 or not 0 <= value['delaySamples'] <= 2048
            or not 0 <= value['paddingSamples'] <= 1023 or not 1024 <= value['rawSamples'] <= 28672
            or value['rawSamples'] % 1024
            or value['rawSamples']-value['delaySamples']-value['paddingSamples'] != value['validSamples']):
        raise ValueError('ordered_idle_asset_trim')
    return dict(value)


class OrderedIdleAssets:
    def __init__(self, root, *, max_bytes=128*1024*1024, max_entries=1024):
        if (type(max_bytes) is not int or not 1 <= max_bytes <= 128*1024*1024
                or type(max_entries) is not int or not 1 <= max_entries <= 1024):
            raise ValueError('ordered_idle_asset_limits')
        self.root = Path(root).absolute()
        if self.root.resolve() != self.root: raise ValueError('ordered_idle_asset_root')
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self._lock = threading.RLock()
        self.reason = 'miss'
        self._epoch = None

    def _path(self, name):
        if re.fullmatch(r'(?:[a-f0-9]{64}\.(?:mp4|json)|[a-f0-9]{32}\.part|epoch)', name) is None:
            raise ValueError('ordered_idle_asset_path')
        path = self.root/name
        if self.root.resolve() != self.root or path.is_symlink() or path.resolve() != path:
            raise ValueError('ordered_idle_asset_path')
        return path

    def _files(self):
        # This is a flat, fixed-name namespace. Resolve its parent once, not
        # twice per retained file on every half-second insertion (costly on NTFS).
        if self.root.resolve() != self.root: raise ValueError('ordered_idle_asset_path')
        files = []
        with os.scandir(self.root) as entries:
            for entry in entries:
                if not re.fullmatch(r'(?:[a-f0-9]{64}\.(?:mp4|json)|[a-f0-9]{32}\.part)', entry.name):
                    continue
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    raise ValueError('ordered_idle_asset_path')
                files.append(self.root/entry.name)
        return files

    def _remove(self, digest):
        for suffix in ('json', 'mp4'): self._path(digest+'.'+suffix).unlink(missing_ok=True)

    def set_epoch(self, epoch):
        _epoch(epoch)
        with self._lock:
            if epoch == self._epoch: return
            saved = self._path('epoch')
            previous = saved.read_text('ascii') if saved.is_file() and saved.stat().st_size < 32 else None
            if previous != str(epoch):
                for path in self._files(): path.unlink()
                temporary = self._path(uuid.uuid4().hex+'.part')
                try:
                    temporary.write_text(str(epoch), encoding='ascii'); os.replace(temporary, saved)
                finally: temporary.unlink(missing_ok=True)
            else:
                for path in self._files():
                    if path.suffix == '.part': path.unlink()
            self._epoch = epoch

    def _live(self, epoch):
        if self._epoch is None: self.set_epoch(epoch)
        if epoch != self._epoch:
            self.reason = 'epoch_changed'; return False
        return True

    def lookup(self, key, *, tail, epoch):
        _epoch(epoch)
        if type(key) is not IdleAssetKey or type(tail) is not bytes or _sha(tail) != key.tail_digest:
            raise ValueError('ordered_idle_asset_tail')
        with self._lock:
            try:
                if not self._live(epoch): return None
                media, meta = self._path(key.digest+'.mp4'), self._path(key.digest+'.json')
                if not meta.exists(): self.reason = 'miss'; return None
                if not 0 < meta.stat().st_size <= 2048: raise ValueError('ordered_idle_asset_metadata')
                value = json.loads(meta.read_text('utf-8'))
                if (set(value) != {'bytes', 'sha256', 'tail', 'trim'}
                        or type(value['bytes']) is not int or not 0 < value['bytes'] <= 16*1024*1024
                        or value['tail'] != key.tail_digest or media.stat().st_size != value['bytes']):
                    raise ValueError('ordered_idle_asset_metadata')
                trim = _trim(value['trim'])
                with media.open('rb') as stream: body = stream.read(16*1024*1024+1)
                if len(body) != value['bytes'] or _sha(body) != value['sha256']:
                    raise ValueError('ordered_idle_asset_integrity')
                # A failed LRU hint is not evidence of corrupt media.
                try: os.utime(meta, None)
                except OSError: pass
                self.reason = 'hit'
                return IdleAsset(media, MappingProxyType(trim), tail, value['sha256'], value['bytes'])
            except (OSError, ValueError, TypeError, KeyError):
                self.reason = 'corrupt'
                # Only our exact object files; no recursive deletion or caller paths.
                try: self._remove(key.digest)
                except OSError: self.reason = 'storage_unavailable'
                return None

    def remember(self, key, asset, *, epoch):
        _epoch(epoch)
        if (type(key) is not IdleAssetKey or type(asset) is not IdleAsset
                or type(asset.tail) is not bytes or _sha(asset.tail) != key.tail_digest):
            raise ValueError('ordered_idle_asset_input')
        trim = _trim(asset.trim)
        with self._lock:
            temporary = None
            try:
                if not self._live(epoch): return False
                source = Path(asset.file)
                if source.is_symlink() or not 0 < source.stat().st_size <= 16*1024*1024:
                    raise ValueError('ordered_idle_asset_media')
                with source.open('rb') as stream: body = stream.read(16*1024*1024+1)
                if len(body) != source.stat().st_size or len(body) > 16*1024*1024:
                    raise ValueError('ordered_idle_asset_media')
                metadata = json.dumps(dict(bytes=len(body), sha256=_sha(body), tail=key.tail_digest, trim=trim),
                                      separators=(',', ':')).encode()
                required = len(body)+len(metadata)
                if required > self.max_bytes: self.reason = 'capacity'; return False
                self._remove(key.digest)
                files = self._files()
                names = {path.name for path in files}
                stats = {}
                # Orphan/partial writes carry no playable object after process restart.
                for path in files:
                    if path.suffix == '.part' or path.suffix == '.mp4' and path.stem+'.json' not in names:
                        path.unlink()
                    else:
                        stats[path.name] = path.stat()
                entries = sorted((name for name in stats if name.endswith('.json')),
                                 key=lambda name:stats[name].st_mtime_ns)
                used = sum(value.st_size for value in stats.values())
                while entries and (used+required > self.max_bytes or len(entries) >= self.max_entries):
                    oldest = entries.pop(0); digest = oldest[:-5]
                    self._remove(digest)
                    used -= sum(stats[name].st_size for name in (oldest, digest+'.mp4') if name in stats)
                if used+required > self.max_bytes: self.reason = 'capacity'; return False
                # The worker/lock serializes writers; reserve required before any write.
                temporary = self._path(uuid.uuid4().hex+'.part')
                temporary.write_bytes(body); os.replace(temporary, self._path(key.digest+'.mp4'))
                temporary.write_bytes(metadata); os.replace(temporary, self._path(key.digest+'.json'))
                self.reason = 'stored'; return True
            except OSError:
                self.reason = 'storage_unavailable'; return False
            finally:
                if temporary is not None:
                    try: temporary.unlink(missing_ok=True)
                    except OSError: pass

    def materialize(self, asset, occurrence_path):
        target = Path(occurrence_path)
        if target.exists() or target.is_symlink() or target.resolve() != target.absolute():
            raise ValueError('ordered_idle_asset_destination')
        with self._lock:
            source = self._path(Path(asset.file).name)
            if source != asset.file or source.suffix != '.mp4': raise ValueError('ordered_idle_asset_source')
            created = False
            try:
                digest = hashlib.sha256(); length = 0
                with source.open('rb') as incoming, target.open('xb') as output:
                    created = True
                    while body := incoming.read(65536):
                        length += len(body)
                        if length > asset.byte_length: raise OSError('ordered_idle_asset_changed')
                        digest.update(body); output.write(body)
                if length != asset.byte_length or digest.hexdigest() != asset.digest:
                    raise OSError('ordered_idle_asset_changed')
            except OSError:
                if created: target.unlink(missing_ok=True)
                raise
        return target
