"""Worker-side bounded cache reads. Caller must supply current authorization.

One instance belongs to one authenticated phone scope. Selection invalidation
is synchronous; scans/encoding publish only against the returned selection token.
This is not an HTTP server and grants no route or playback capability by itself.
"""
import copy
import re
import secrets
import threading
import concurrent.futures
import json
import hashlib
import importlib.util
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from .idle_loop_catalog import MAX_FILE, MAX_CACHE, _confined, _digest

MAX_RANGE = MAX_FILE
HEX = re.compile(r'[a-f0-9]{64}')


def _signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


class IdleLoopService:
    def __init__(self, cache_root, *, authorize):
        self.root = Path(cache_root).absolute()
        self.authorize = authorize
        self._lock = threading.RLock()
        self._owner = self._selected = self._token = ''
        self._manifest = None
        self._files = {}

    def _authorized(self, owner):
        if not isinstance(owner, str) or not owner or not self.authorize(owner):
            raise PermissionError('Idle cache authorization ended')

    def _live(self, owner, token=None):
        self._authorized(owner)
        if owner != self._owner or (token is not None and token != self._token):
            raise ValueError('Idle cache selection changed')

    def select(self, owner, selection):
        self._authorized(owner)
        if not isinstance(selection, str) or not selection or len(selection) > 1024:
            raise ValueError('Invalid idle selection')
        with self._lock:
            if owner != self._owner or selection != self._selected:
                self._owner, self._selected = owner, selection
                self._token = secrets.token_hex(16)
                self._manifest, self._files = None, {}
            return self._token

    def invalidate(self):
        with self._lock:
            self._owner = self._selected = self._token = ''
            self._manifest, self._files = None, {}

    def publish(self, owner, token, catalog):
        with self._lock:
            self._live(owner, token)
        manifest = copy.deepcopy(catalog.manifest)
        if (manifest.get('version') != 1 or not isinstance(manifest.get('loops'), list)
                or len(manifest['loops']) > 128 or any(not isinstance(manifest.get(k), str)
                or not HEX.fullmatch(manifest[k]) for k in ('generation', 'avatar', 'revision'))):
            raise ValueError('Invalid idle manifest')
        files, ids, total = {}, set(), 0
        for row in manifest['loops']:
            identity = row.get('id')
            if not isinstance(identity, str) or not HEX.fullmatch(identity) or identity in ids:
                raise ValueError('Invalid idle identity')
            ids.add(identity)
            if row.get('status') != 'ready':
                if row.get('status') not in {'pending','unavailable'}:
                    raise ValueError('Invalid idle state')
                continue
            if (type(row.get('bytes')) is not int or not 0 < row['bytes'] <= MAX_FILE
                    or not isinstance(row.get('sha256'), str) or not HEX.fullmatch(row['sha256'])):
                raise ValueError('Invalid idle file')
            path = _confined(catalog.files[identity], [self.root])
            before = _signature(path)
            if before[2] != row['bytes'] or _digest(path, lambda: False) != row['sha256'] or before != _signature(path):
                raise ValueError('Idle file changed')
            total += row['bytes']
            if total > MAX_CACHE:
                raise ValueError('Idle cache capacity')
            files[identity] = path, before, row['bytes']
        with self._lock:
            self._live(owner, token)
            self._manifest, self._files = manifest, files

    def manifest(self, owner):
        with self._lock:
            self._live(owner)
            if self._manifest is None:
                raise ValueError('Idle inventory pending')
            return copy.deepcopy(self._manifest)

    def read(self, *, owner, generation, identity, offset, length):
        with self._lock:
            self._live(owner)
            if (self._manifest is None or generation != self._manifest['generation']
                    or not isinstance(identity, str) or identity not in self._files
                    or type(offset) is not int or offset < 0
                    or type(length) is not int or not 0 < length <= MAX_RANGE):
                raise ValueError('Invalid idle range')
            path, expected, size = self._files[identity]
            if offset + length > size:
                raise ValueError('Invalid idle range')
            token = self._token
        _confined(path, [self.root])
        if _signature(path) != expected:
            raise ValueError('Idle file changed')
        with path.open('rb') as source:
            source.seek(offset)
            data = source.read(length)
        with self._lock:
            self._live(owner, token)
            if self._files.get(identity) != (path, expected, size) or len(data) != length or _signature(path) != expected:
                raise ValueError('Idle file changed')
        return data


class IdleLoopWorker:
    """One bounded encoder job in the phone-backend process, never on Qt."""
    def __init__(self, runtime_root, cache_root, *, selection, authorize, fixed_fps=None):
        if fixed_fps is not None and (type(fixed_fps) is not int or fixed_fps != 24):
            raise ValueError('Idle fixed frame rate must be 24')
        self.fixed_fps = fixed_fps
        self.runtime_root, self.root = Path(runtime_root), Path(cache_root)
        self.selection, self.authorize = selection, authorize
        self._lock = threading.RLock()
        self._closed, self._key, self._token = False, '', ''
        self._future, self._catalog, self._error = None, None, ''
        self._refresh = 0.
        self._trace = None
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-idle-cache')
        self.service = IdleLoopService(cache_root, authorize=lambda owner: not self._closed and authorize() and owner == 'desktop')

    def close(self):
        with self._lock:
            self._closed = True
            self.service.invalidate()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _check(self):
        if self._closed or not self.authorize():
            self.service.invalidate()
            raise PermissionError('Idle cache authorization ended')

    def _snapshot(self):
        self._check()
        state = self.selection()
        if not isinstance(state, dict) or not isinstance(state.get('config'), dict):
            raise ValueError('Idle selection unavailable')
        from .idle_cache_settings import load_settings
        from .media_quality import load_quality, video_quality
        settings=load_settings(self.root.parent)
        if not settings['enabled']:
            raise ValueError('Idle cache disabled')
        # The legacy cache preset is retained on disk only for schema stability.
        # Encoder quality comes from the same preferences as new media peers.
        quality = video_quality(load_quality(self.root.parent))
        if self.fixed_fps is not None:
            quality = {**quality, 'video_fps': self.fixed_fps}
        state={**state,'quality':quality,
               'cache_revision':settings['revision']}
        if self.fixed_fps==24:state['video_encoder']='h264_nvenc'
        encoded = json.dumps({k:v for k,v in state.items() if k != 'current_avatar'}, sort_keys=True)
        if len(encoded) > 65536:
            raise ValueError('Idle selection limit')
        return copy.deepcopy(state), hashlib.sha256(encoded.encode()).hexdigest()

    def _build(self, state, key, token):
        operation = uuid.uuid4().hex
        started = time.monotonic()
        stage = 'prune_previous'
        def observe(outcome='observed', reason=None, error=None):
            # Only job boundaries, never range/frame polling. This shares the
            # normal bounded journal; diagnostic failure cannot change readiness.
            try:
                from core.diagnostics.plan_trace import PlanTrace
                if self._trace is None: self._trace = PlanTrace()
                facts = dict(stage=stage,
                            elapsed_ms=round((time.monotonic()-started)*1000), ordered=self.fixed_fps == 24)
                if reason is not None: facts['reason'] = reason
                if error is not None:
                    facts['error_class'] = type(error).__name__
                    known = {'Idle encoding unavailable','Idle encode cancelled','Idle inventory limit',
                             'Idle selection unavailable','Idle cache authorization ended','Idle cache selection changed',
                             'Invalid idle manifest','Invalid idle file','Idle file changed',
                             'Idle encoder containment unavailable'}
                    facts['cause'] = str(error).replace(' ','_') if type(error) is ValueError and str(error) in known else 'filtered'
                facts['result'] = outcome
                for condition,actual in facts.items():
                    # Scalar observations use the shared contract, not private
                    # worker fields. Failure facts are mandatory warnings even
                    # with optional logging OFF; success remains optional.
                    level = ('error' if condition=='result' else 'warning') if outcome=='failed' else 'info'
                    self._trace.emitter.emit(dict(level=level,
                        event_name='transaction.operation', trace_id=key, operation_id=operation,
                        parent_operation_id=None, phase='decision', outcome='observed', basis='observed',
                        links=[], context={'session_id':key}, data=dict(site='backend.idle.inventory',
                            condition=condition,expected=None,actual=actual)))
            except Exception: pass
        def cancelled():
            return self._closed or key != self._key or not self.authorize()
        try:
            observe()
            with self._lock:
                # A process restart loses only the in-memory catalog, not the
                # verified content-addressed files. Validate/reuse them first;
                # obsolete owned outputs are reclaimed after publication.
                self._prune(set(),partial_only=True)
            stage = 'encode'; observe()
            catalog = self._encode_process(state, cancelled)
            stage = 'recheck_selection'; observe()
            if self._snapshot()[1] != key:
                observe('cancelled', 'selection_changed')
                return
            stage = 'publish'; observe()
            self.service.publish('desktop', token, catalog)
            stage = 'publish_ready'; observe()
            with self._lock:
                if not cancelled():
                    self._prune(set(catalog.files))
                    self._catalog, self._error = catalog, ''
                    observe('completed', 'ready')
                else: observe('cancelled', 'owner_or_selection_ended')
        except Exception as error:
            observe('failed', 'inventory_unavailable', error)
            with self._lock:
                if not cancelled(): self._error = 'inventory_unavailable'

    def _encode_process(self, state, cancelled):
        from .idle_loop_catalog import IdleCatalog
        executable = self.runtime_root/'.venvs/nc_relay'/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        if not executable.is_file():
            if importlib.util.find_spec('av') is None:
                raise ValueError('Media environment required')
            executable = Path(sys.executable)
        request = {**state, 'runtime_root':str(self.runtime_root), 'cache_root':str(self.root)}
        payload = json.dumps(request).encode()
        if len(payload) > 65536:
            raise ValueError('Idle input limit')
        process = subprocess.Popen([str(executable), '-m', 'addons.main_chat_remote.idle_loop_catalog'],
            cwd=Path(__file__).resolve().parents[2], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            **({'start_new_session':True} if sys.platform!='win32' else {}))
        try:
            deadline = time.monotonic()+180
            while True:
                if cancelled() or time.monotonic() > deadline:
                    raise ValueError('Idle encode cancelled')
                try:
                    output, errors = process.communicate(payload, timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    payload = None
            if process.returncode or len(output) > 128*1024:
                if errors.strip()==b'Idle encoder containment unavailable':
                    raise ValueError('Idle encoder containment unavailable')
                raise ValueError('Idle encoding unavailable')
            value = json.loads(output)
            if not isinstance(value.get('ids'), list) or len(value['ids']) > 128 or any(
                    not isinstance(identity, str) or not HEX.fullmatch(identity) for identity in value['ids']):
                raise ValueError('Invalid idle inventory')
            return IdleCatalog(value['manifest'], {identity:self.root/(identity+'.mp4') for identity in value['ids']},
                               value['avatar_loops'], value.get('source_bindings', {}))
        finally:
            if sys.platform!='win32':
                # The root may already have crashed. Its still-owned group can
                # contain an encoder even after the catalog PID exits.
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            if process.poll() is None:
                # The catalog now owns an FFmpeg child. Settle the exact owned
                # process tree before closing pipes inherited by descendants.
                if sys.platform=='win32':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream: stream.close()
            self._prune(set(), partial_only=True)

    def _prune(self, keep, *, partial_only=False):
        """Only this feature's exact content-addressed outputs; never sources."""
        if not self.root.is_dir():
            return
        _confined(self.root, [self.root.absolute()])
        for path in self.root.iterdir():
            match = re.fullmatch(r'([a-f0-9]{64})\.(mp4|sha256)', path.name)
            temporary = re.fullmatch(r'idle-[a-z0-9_]{8}\.partial\.(mp4|sha256)', path.name)
            if temporary or (not partial_only and match and match[1] not in keep):
                try:
                    _confined(path, [self.root.absolute()])
                    path.unlink()
                except (OSError, ValueError):
                    pass

    def request(self, path):
        from .idle_loop_http import parse_route
        bounds = parse_route('GET', path)
        from .idle_cache_settings import load_settings
        self._check()
        settings=load_settings(self.root.parent)
        if path=='/api/idle-cache/settings':
            return 200,json.dumps(settings).encode(),'application/json'
        if not settings['enabled']:
            return 409,b'{"status":"disabled"}','application/json'
        state, key = self._snapshot()
        with self._lock:
            if key != self._key:
                self._key, self._catalog, self._error = key, None, ''
                self._token = self.service.select('desktop', key)
                self._refresh = 0
            if (self._future is None or self._future.done()) and time.monotonic() >= self._refresh:
                self._refresh = time.monotonic()+30
                self._future = self._executor.submit(self._build, state, key, self._token)
            if self._catalog is None:
                if bounds: raise ValueError('Idle inventory pending')
                status = 503 if self._error else 202
                return status, json.dumps({'status':self._error or 'pending'}).encode(), 'application/json'
            if bounds:
                data = self.service.read(owner='desktop', **bounds)
                content_type = 'video/mp4'
            else:
                manifest = self.service.manifest('desktop')
                current = state.get('current_avatar')
                if current:
                    manifest['active_loop'] = self._catalog.avatar_loops.get(current)
                if path == '/api/idle-cache/manifest?frame_handoff=1':
                    # Opt-in compact binding: the legacy inventory stays byte-
                    # schema compatible. Content deduplication is not motion identity.
                    binding = self._catalog.source_bindings.get(current)
                    manifest['active_source'] = ({**binding, 'avatar_id': current,
                        'loop_id': manifest['active_loop']} if binding and manifest['active_loop'] else None)
                    ready = {row['id'] for row in manifest['loops'] if row['status'] == 'ready'}
                    manifest['sources'] = [{**source, 'avatar_id': avatar,
                        'loop_id': self._catalog.avatar_loops[avatar]}
                        for avatar, source in sorted(self._catalog.source_bindings.items())
                        if self._catalog.avatar_loops.get(avatar) in ready]
                data, content_type = json.dumps(manifest).encode(), 'application/json'
        # Re-fetch narrow trusted selection after IO. Never release old-avatar
        # bytes if a change or authorization loss happened while reading.
        if self._snapshot()[1] != key:
            raise ValueError('Idle selection changed')
        self._check()
        return 200, data, content_type
