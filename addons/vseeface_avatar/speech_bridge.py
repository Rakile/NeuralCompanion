"""File IPC for addon-configured VSeeFace lip sync; NC owns audible audio."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import threading
import time
import uuid
from collections.abc import Mapping

if os.name == 'nt':
    import ctypes
    _replace_file = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
    _replace_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                             ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    _replace_file.restype = ctypes.c_int


def _replace_snapshot(source, destination):
    """Match .NET File.Replace's Windows semantics with live delete-sharing readers."""
    if os.name != 'nt' or not destination.exists():
        os.replace(source, destination)
        return
    if not _replace_file(os.fspath(destination), os.fspath(source), None, 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


def _value(chunk, key, default=None):
    return chunk.get(key, default) if isinstance(chunk, Mapping) else getattr(chunk, key, default)


class SpeechBridge:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._client = uuid.uuid4().hex
        self._prepared = {}
        self._staging = {}
        self._retired = set()
        self._active = None
        self._fallback_started = None
        self._closed = False
        self._revision = 0
        self._state = dict(version=1, client=self._client, clip='', position=0.0, running=False)
        self._reported_error = False
        self._publish()
        print(f'[VSeeFace speech bridge] Enabled: {self.directory}; audible speech remains in NC.')

    @classmethod
    def from_environment(cls):
        directory = os.environ.get('NC_VSEEFACE_BRIDGE_DIR', '').strip()
        return cls(directory) if directory else None

    def _publish(self):
        self._revision += 1
        state = dict(self._state, revision=self._revision, updated=time.time())
        temporary = self.directory / (self._client + '.state.tmp')
        try:
            temporary.write_text(json.dumps(state, allow_nan=False), encoding='utf-8')
            _replace_snapshot(temporary, self.directory / 'state.json')
            self._reported_error = False
        except OSError as exc:
            if not self._reported_error:
                print(f'[VSeeFace speech bridge] Could not publish this update; the watchdog stops lip sync if updates remain unavailable: {exc}')
                self._reported_error = True

    def prepare(self, chunk):
        if dict(_value(chunk, 'source_metadata', {}) or {}).get('skip_local_playback'):
            return
        lease = _value(chunk, 'lease')
        key = (lease, _value(chunk, 'index'))
        with self._lock:
            if self._closed or lease in self._retired or key in self._prepared:
                return
            destination = self.directory / (self._client + '-' + uuid.uuid4().hex + '.wav')
            if key in self._staging:
                return
            self._staging[key] = destination
        # Disk I/O must never hold the cancellation lock. A cancelled copy cannot publish itself.
        try:
            shutil.copyfile(_value(chunk, 'audio_path'), destination)
        finally:
            with self._lock:
                self._staging.pop(key, None)
                if self._closed or lease in self._retired:
                    destination.unlink(missing_ok=True)
        with self._lock:
            if self._closed or lease in self._retired:
                destination.unlink(missing_ok=True)
                return
            self._prepared[key] = destination

    def start(self, chunk):
        with self._lock:
            key = (chunk.lease, chunk.index)
            path = self._prepared.get(key)
            if self._closed or path is None or chunk.lease in self._retired:
                return
            self._active = (chunk.lease, chunk.owner_generation, chunk.index)
            self._fallback_started = time.monotonic()
            self._state.update(clip=path.name, position=0.0, running=True)
            self._publish()
            for old_key in tuple(self._prepared):
                if old_key[0] == chunk.lease and old_key[1] < chunk.index:
                    self._remove(old_key)

    def progress(self, chunk, sample):
        with self._lock:
            identity = (chunk.lease, chunk.owner_generation, chunk.index)
            if identity != self._active:
                self.start(chunk)
            if identity != self._active:
                return
            position = float(sample.media_seconds)
            if not math.isfinite(position):
                return
            self._fallback_started = None  # A device clock takes precedence over elapsed time.
            self._state.update(position=max(0.0, position), running=bool(sample.running))
            self._publish()

    def tick(self):
        """Keep file playback alive when that device only reports start/finish."""
        with self._lock:
            if self._closed or self._active is None or self._fallback_started is None:
                return
            if self._state['running']:
                self._state['position'] = max(0.0, time.monotonic() - self._fallback_started)
            self._publish()

    def pause(self, owner):
        with self._lock:
            if self._active and self._active[:2] == (owner.lease, owner.generation):
                self._state['running'] = False
                self._publish()

    def _remove(self, key):
        path = self._prepared.pop(key, None)
        if path:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # A pending Unity load can briefly retain the file; close retries our files.

    def finish(self, receipt):
        owner = receipt.owner
        with self._lock:
            if owner is None:
                return
            self._retired.add(owner.lease)
            if self._active and self._active[:2] == (owner.lease, owner.generation):
                self._active = None
                self._fallback_started = None
                self._state.update(clip='', position=0.0, running=False)
                self._publish()
            for key in tuple(self._prepared):
                if key[0] == owner.lease:
                    self._remove(key)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._active = None
            self._fallback_started = None
            self._state.update(clip='', position=0.0, running=False)
            self._publish()
            for key in tuple(self._prepared):
                self._remove(key)
            for path in self.directory.glob(self._client + '-*.wav'):
                try:
                    path.unlink()
                except OSError:
                    pass
