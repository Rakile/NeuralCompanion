"""Authenticated backend lifecycle for independent Desktop-ordered production.

The outer LAN/peer gate authenticates transport. Controls additionally use the
existing reply-session credentials; random stream IDs scope media capabilities.
No constructor starts a worker. The Desktop capability gate remains authoritative.
"""
from collections import deque
import json
from pathlib import Path
import re
import secrets
import threading
import time

from .ordered_output_bridge import BackendOutputSequence, OrderedBridgeRejected, parse_frontier
from .ordered_output_encoding import OrderedOutputWorker, OrderedSourcePlan, OrderedSourceAdmission, decode_ordered_frame
from .ordered_output_producer import OrderedOutputProducer
from .ordered_output_pump import OrderedOutputPump
from .ordered_idle_assets import OrderedIdleAssets
from .ordered_output_diagnostics import OrderedLifecycleDiagnostics
from .ordered_output_recovery import open_capability, parse_recovery, parse_reattach

# Temporary user-requested A/B experiment (16 October 2026). Set False to
# restore the three per-clip ffprobe inspections. Native admission, AAC edits,
# idle encoding, custody, publication and error handling are not bypassed.
SKIP_SPEECH_CLIP_PROBES_EXPERIMENT = True


def _integer(value, low=0):
    return type(value) is int and low <= value <= (1 << 53)-1


def _auth_key(auth):
    if (type(auth) is not dict or set(auth) != {'client_key', 'connection_epoch'}
            or any(type(v) is not str or not 1 <= len(v) <= 256 for v in auth.values())):
        raise ValueError('ordered_service_auth')
    return json.dumps(auth, sort_keys=True, separators=(',', ':'))


def public_failure(error):
    code = str(error)
    safe = code if re.fullmatch(r'(?:ordered|output|phone_reply)_[a-z_]{1,80}', code) else 'ordered_service_production_failed'
    details = dict(reason=safe, errorType=type(error).__name__)
    if isinstance(error, OrderedBridgeRejected):
        details.update(reason=error.rejection, bridgeMethod=error.method, httpStatus=error.http_status)
    return details


class _Session:
    def __init__(self, auth, stream_id, sequence, producer):
        self.owner = _auth_key(auth)
        self.stream_id, self.sequence, self.producer = stream_id, sequence, producer
        self.condition = threading.Condition()
        self.revision = 0
        self.closed = False
        self.retired = False
        self.failure = None
        self.waiting = None
        self.pump = None
        self.released = deque(maxlen=64)
        self.pending_delete = {}
        self.generation = 0
        self.last_restart = None

    def notify(self, _frontier=None):
        with self.condition:
            self.revision += 1
            self.condition.notify_all()

    def failed(self, error):
        details = public_failure(error)
        with self.condition:
            if self.failure is None: self.failure = details
            self.revision += 1
            self.condition.notify_all()


class _Opening:
    """Exact custody while a Desktop open/close acknowledgement is uncertain."""
    def __init__(self, auth, stream_id, sequence, output, producer, recovery=None):
        self.owner, self.stream_id = _auth_key(auth), stream_id
        self.sequence, self.output, self.producer = sequence, output, producer
        self.retired = False
        self.recovery = recovery


class OrderedOutputService:
    def __init__(self, root, *, request, ffmpeg, source_roots, authorize, quality=None, idle_settings=None, idle_inventory=None):
        self.root = Path(root).resolve()
        self._request, self._ffmpeg = request, ffmpeg
        self._roots, self._authorize, self._quality = source_roots, authorize, quality
        self._control = threading.RLock()
        self._io = threading.RLock()
        self._session = None
        self._opening = None
        self._recovery_lock = threading.RLock()
        self._recoveries = {}
        self._retired_sessions = {}
        self._shutdown = False
        self._idle_settings = idle_settings or (lambda: dict(enabled=False, clear_generation=0))
        self._idle_inventory = idle_inventory
        self._idle_assets = None
        self._diagnostics = OrderedLifecycleDiagnostics()

    def _diagnostic_snapshot(self, body):
        """Best-effort local state, never additional authority/bridge queries."""
        body = body if type(body) is dict else {}
        stream = body.get('streamId')
        trace = stream if type(stream) is str and re.fullmatch('[a-f0-9]{32}',stream) else secrets.token_hex(16)
        identity = self._diagnostics.identity
        facts = {'trace_id':trace, 'request.stream':identity(stream)}
        try: facts['request.owner'] = identity(_auth_key(body.get('auth')))
        except ValueError: facts['request.owner'] = None
        for key in ('generation','ordinal','recoveryEpoch','afterOrdinal'):
            if _integer(body.get(key)): facts['request.'+key] = body[key]
        if body.get('afterOrdinal') == -1 and type(body.get('afterOrdinal')) is int:
            facts['request.afterOrdinal'] = -1
        operation = body.get('operationId')
        if type(operation) is str and re.fullmatch('[a-f0-9]{32}', operation):
            facts['request.operation'] = operation
        if type(body.get('readersClosed')) is bool: facts['request.readers_closed'] = body['readersClosed']
        if not self._control.acquire(blocking=False):
            return {**facts, 'control.state':'lock_busy'}
        try:
            facts.update({'control.state':'observed', 'service.shutdown':self._shutdown})
            facts['recovery.retained_sessions'] = len(self._retired_sessions)
            facts['recovery.operations'] = len(self._recoveries)
            recovery = body.get('recovery')
            operation = recovery.get('operationId') if type(recovery) is dict else None
            if type(operation) is str and re.fullmatch('[a-f0-9]{32}',operation):
                facts['recovery.operation'] = identity(operation)
                record = self._recoveries.get(operation)
                if record is not None:
                    facts['recovery.prepared'] = record['prepared']
                    facts['recovery.admitted'] = record['admitted']
            pending, session = self._opening, self._session
            for name, target in (('opening',pending), ('session',session)):
                facts[name+'.present'] = target is not None
                if target is None: continue
                facts.update({name+'.stream':identity(target.stream_id), name+'.owner':identity(target.owner),
                    name+'.retired':target.retired, name+'.owner_matches':facts['request.owner']==identity(target.owner)})
            if session is not None:
                facts.update({'session.closed':session.closed, 'session.generation':session.generation,
                    'session.first_failure':session.failure.get('reason') if session.failure else None,
                    'session.waiting':session.waiting is not None})
                facts.update(session.producer.diagnostic_custody())
                if session.pump is not None: facts.update(session.pump.diagnostic_state())
                if self._io.acquire(blocking=False):
                    try:
                        keys = sorted(session.pending_delete)
                        facts.update({'pending_delete.state':'observed', 'pending_delete.count':len(keys),
                            'pending_delete.keys':'/'.join(f'{g}:{o}' for g,o in keys[:3]) or None,
                            'pending_delete.truncated':len(keys)>3, 'released.recent_count':len(session.released),
                            'released.last':':'.join(map(str,session.released[-1])) if session.released else None})
                    finally: self._io.release()
                else: facts['pending_delete.state'] = 'lock_busy'
            elif pending is not None:
                facts.update(pending.producer.diagnostic_custody())
        finally: self._control.release()
        return facts

    def _reject(self, stage, reason):
        self._diagnostics.mark(stage)
        raise ValueError(reason)

    def _cache_policy(self):
        value = self._idle_settings()
        if (type(value) is not dict or type(value.get('enabled')) is not bool
                or not _integer(value.get('clear_generation'))):
            raise ValueError('ordered_idle_asset_policy')
        return value

    def _cache_epoch(self):
        epoch = self._cache_policy()['clear_generation']
        if self._idle_assets is not None:
            try: self._idle_assets.set_epoch(epoch)
            except OSError: self._idle_assets.reason = 'storage_unavailable'
        return epoch

    def _validate_cached_asset(self, asset):
        policy = self._cache_policy()
        if (type(asset) is not dict or not policy['enabled'] or type(asset.get('cacheEpoch')) is not int
                or asset['cacheEpoch'] != policy['clear_generation'] or self._idle_inventory is None):
            raise ValueError('ordered_cached_inventory')
        manifest = self._idle_inventory()
        if (type(manifest) is not dict or manifest.get('revision') != asset.get('inventoryRevision')
                or manifest.get('video_quality',{}).get('video_fps') != 24):
            raise ValueError('ordered_cached_inventory')
        ready = any(row.get('id') == asset.get('loopId') and row.get('status') == 'ready'
                    and row.get('fps') == 24 and row.get('frames') == asset.get('sourceFrameCount')
                    for row in manifest.get('loops',[]) if type(row) is dict)
        bound = any(row.get('motion_id') == asset.get('motionId') and row.get('loop_id') == asset.get('loopId')
                    and row.get('source_frame_count') == asset.get('sourceFrameCount')
                    for row in manifest.get('sources',[]) if type(row) is dict)
        if not ready or not bound: raise ValueError('ordered_cached_inventory')

    def _current(self):
        if not self._authorize():
            if self._session is not None: self._session.pump.stop()
            raise ValueError('ordered_service_desktop_changed')

    def _scope(self, auth, stream_id, *, cleanup=False):
        self._diagnostics.mark('scope.auth')
        key = _auth_key(auth)
        session = self._session
        if cleanup and (session is None or session.stream_id != stream_id):
            session = self._retired_sessions.get(stream_id)
        if session is None: self._reject('scope.session_absent', 'ordered_service_owner')
        if not secrets.compare_digest(key, session.owner):
            self._reject('scope.owner_mismatch', 'ordered_service_owner')
        if session.stream_id != stream_id: self._reject('scope.stream_mismatch', 'ordered_service_stream')
        return session

    def _open(self, auth, stream_id, recovery=None):
        self._diagnostics.mark('open.auth')
        owner = _auth_key(auth)
        digest = open_capability(recovery)
        if any(not r['admitted'] for r in self._recoveries.values()):
            raise ValueError('ordered_recovery_pending')
        pending = self._opening
        if pending is not None and not pending.retired:
            if not secrets.compare_digest(owner, pending.owner):
                self._reject('open.pending_owner_mismatch', 'ordered_service_owner')
            if pending.stream_id != stream_id: self._reject('open.pending_stream_mismatch', 'ordered_service_stream')
            if open_capability(pending.recovery) != digest: raise ValueError('ordered_recovery_conflict')
            return self._finish_open(auth, pending, uncertain=True)
        if pending is not None and pending.stream_id == stream_id:
            self._reject('open.pending_retired', 'ordered_service_closed')
        prior = self._session
        if prior is not None:
            if prior.stream_id == stream_id:
                if not secrets.compare_digest(owner, prior.owner):
                    self._reject('open.prior_owner_mismatch', 'ordered_service_owner')
                if prior.closed: self._reject('open.prior_closed', 'ordered_service_closed')
                if prior.recovery_digest != digest: raise ValueError('ordered_recovery_conflict')
                # Desktop authenticates a retry too; no second encoder is started.
                frontier = self._diagnostics.step('open.retry_frontier', prior.sequence.frontier)
                return dict(version=1, streamId=stream_id, generation=frontier.generation)
            # Preserve the original short-circuit and the single side-effecting
            # join call. Only the first actual rejecting predicate is recorded.
            if not prior.retired:
                self._reject('prior_not_retired', 'ordered_service_readers_pending')
            if not self._diagnostics.step('open.join_prior', prior.pump.close):
                self._reject('encoder_join_pending', 'ordered_service_readers_pending')
            if prior.pending_delete:
                self._reject('pending_file_delete', 'ordered_service_readers_pending')
            if prior.producer.has_retained_media:
                self._reject('retained_media', 'ordered_service_readers_pending')
        # Reply-session renewal issues fresh credentials on reconnect. Only a
        # fully joined retired stream may be replaced; Desktop authenticates
        # the new owner below. Old cleanup credentials never authorize new media.
        sequence = BackendOutputSequence(self._request, auth, stream_id)
        output = self.root / stream_id
        self._diagnostics.step('open.allocate', lambda: output.mkdir(parents=True, exist_ok=False))
        producer = OrderedOutputProducer(sequence, output)
        pending = _Opening(auth, stream_id, sequence, output, producer, recovery)
        self._opening = pending
        return self._finish_open(auth, pending, uncertain=False)

    def _finish_open(self, auth, pending, *, uncertain):
        try:
            fields = dict(recovery=pending.recovery) if pending.recovery is not None else {}
            opened = self._diagnostics.step('open.desktop_open', lambda: pending.sequence._call('open', **fields))
        except OrderedBridgeRejected as error:
            # A definitive first rejection created no Desktop owner. An earlier
            # lost response remains ambiguous: only an authenticated close can
            # settle it, never a different owner's open or a local timeout.
            if not uncertain and error.http_status is not None and 400 <= error.http_status < 500:
                self._diagnostics.step('open.rejected_empty_directory', pending.output.rmdir)
                self._opening = None
            self._diagnostics.mark('open.desktop_open_rejected')
            raise
        self._diagnostics.mark('open.validate_response')
        if type(opened) is not dict or opened.get('streamId') != pending.stream_id or opened.get('generation') != 0:
            raise ValueError('ordered_service_open_response')
        return self._install_open(auth, pending)

    def _install_open(self, auth, pending):
        session = _Session(auth, pending.stream_id, pending.sequence, pending.producer)
        session.recovery_digest = open_capability(pending.recovery)
        self._diagnostics.mark('open.cache_policy')
        policy = self._cache_policy()
        session.cache_enabled = policy['enabled']
        session.quality = self._quality() if callable(self._quality) else self._quality
        cache_root = self.root/'idle-assets-v1'
        if self._idle_assets is None and (session.cache_enabled or cache_root.exists()):
            try: self._idle_assets = OrderedIdleAssets(cache_root)
            except OSError:
                # Cache availability cannot turn an authenticated stream into a
                # terminal failure. The regular encoder/downloader still apply.
                from core.diagnostics.plan_trace import PlanTrace
                try: PlanTrace().observe(session.stream_id, 'backend.encode.ordered',
                                        'idle_cache', None, 'storage_unavailable')
                except Exception: pass
        self._cache_epoch()

        self._diagnostics.step('open.start_encoder', lambda: self._start_pump(session))
        self._session = session
        self._opening = None
        return dict(version=1, streamId=pending.stream_id, generation=0)

    def _recover(self, auth, stream_id, recovery):
        intent = parse_recovery(stream_id, recovery)
        _auth_key(auth)
        lookup = BackendOutputSequence(self._request, auth, stream_id)
        # Separate operation serialization: joins and Desktop requests must not
        # hold either state lock used by the encoder or its failure callbacks.
        with self._recovery_lock:
            with self._control:
                if self._shutdown: raise ValueError('ordered_service_shutdown')
                record = self._recoveries.get(intent.operation)
                if record is not None:
                    if record['intent'] != intent: raise ValueError('ordered_recovery_conflict')
                    if record['admitted'] and self._session is not record['successor']:
                        raise ValueError('ordered_recovery_stale')
                else:
                    prior = self._opening if self._opening is not None else self._session
                    if prior is not None and prior.stream_id != intent.previous: raise ValueError('ordered_recovery_stale')
                    if any(not r['admitted'] for r in self._recoveries.values()): raise ValueError('ordered_recovery_conflict')
                    self._retired_sessions = {key:s for key,s in self._retired_sessions.items()
                        if s.pending_delete or s.producer.has_retained_media}
                    self._recoveries = {key:r for key,r in self._recoveries.items()
                        if (prior is not None and r['intent'].stream == prior.stream_id)
                        or (r['previous'] is not None and r['previous'].stream_id in self._retired_sessions)}
                    if len(self._retired_sessions) >= 64 or len(self._recoveries) >= 64:
                        raise ValueError('ordered_recovery_retention_capacity')
                    record = dict(intent=intent, previous=prior, prepared=False, admitted=False, opening=None,
                                  initial_open=prior is not None and prior is self._opening)
                    self._recoveries[intent.operation] = record
            if record['admitted']:
                result = self._diagnostics.step('recover.outcome', lambda: lookup._call('recover-commit', recovery=recovery))
                if result not in (intent.result('recovered'), intent.result('closed')):
                    raise ValueError('ordered_recovery_response')
                return result
            if not record['prepared']:
                try:
                    result = self._diagnostics.step('recover.prepare', lambda: lookup._call('recover-prepare', recovery=recovery))
                except OrderedBridgeRejected as error:
                    # Only proof/shape/stale rejections certify no fence. Other
                    # failures may follow fencing/cancellation and retain custody.
                    if error.rejection in ('ordered_recovery_proof','ordered_recovery_proof_missing',
                                           'ordered_recovery_shape','ordered_recovery_stale'):
                        with self._control: del self._recoveries[intent.operation]
                    raise
                if result == intent.result('closed'):
                    # A restarted backend can query an already-admitted, closed
                    # Desktop successor. This is a receipt, never a new producer.
                    with self._control: del self._recoveries[intent.operation]
                    return result
                if result != intent.result('prepared'): raise ValueError('ordered_recovery_response')
                record['prepared'] = True
            prior = record['previous']
            initial_open = record['initial_open']
            with self._control:
                if (self._opening if initial_open else self._session) is not prior:
                    raise ValueError('ordered_recovery_stale')
                if prior is not None and not initial_open:
                    self._diagnostics.step('recover.stop', prior.pump.stop)
                    prior.closed = True
                    prior.notify()
            if prior is not None and not initial_open:
                if not self._diagnostics.step('recover.join', prior.pump.close):
                    raise ValueError('ordered_recovery_join_pending')
                self._diagnostics.step('recover.reconcile', prior.producer.reconcile_publications)
                self._diagnostics.step('recover.clear_uncommitted', prior.pump.cleanup)
            with self._control:
                if self._shutdown: raise ValueError('ordered_service_shutdown')
                if (self._opening if initial_open else self._session) is not prior:
                    raise ValueError('ordered_recovery_stale')
                if prior is None:
                    # Backend process memory may be gone. Desktop has verified
                    # the exact predecessor capability and fenced/cancelled it.
                    # Do not reconstruct, delete or acknowledge old reader files.
                    self._diagnostics.mark('recover.desktop_verified_absent_local_session', 'completed')
                elif initial_open:
                    # No pump or reader was ever created for an uncertain open.
                    # Desktop has now verified its proof and fenced that owner.
                    if not prior.retired:
                        self._diagnostics.step('recover.pending_empty_directory', prior.output.rmdir)
                else:
                    self._retired_sessions[prior.stream_id] = prior
                if prior is not None: prior.retired = True
                self._diagnostics.mark('recover.quarantined', 'completed')
                pending = record['opening']
                if pending is None:
                    output = self.root / stream_id
                    self._diagnostics.step('recover.allocate', lambda: output.mkdir(parents=True, exist_ok=False))
                    pending = _Opening(auth, stream_id, lookup, output, OrderedOutputProducer(lookup, output),
                                       dict(version=1, capability=recovery['capability']))
                    record['opening'] = pending
            result = self._diagnostics.step('recover.commit', lambda: lookup._call('recover-commit', recovery=recovery))
            if result == intent.result('closed'):
                with self._control:
                    if (self._opening if initial_open else self._session) is not prior:
                        raise ValueError('ordered_recovery_stale')
                    # Commit may have succeeded before a lost response, followed
                    # by Desktop retirement. No successor pump was installed.
                    # Release only its empty staging directory; old readers stay
                    # quarantined above until their own exact closure ACKs.
                    self._diagnostics.step('recover.closed_empty_directory', pending.output.rmdir)
                    pending.retired = True
                    if initial_open: self._opening = None
                    # An uncertain initial open may still have the older,
                    # fully joined/drained session admitted by _open's checks.
                    self._session = None
                    record['successor'] = None
                    record['admitted'] = True
                return result
            if result != intent.result('recovered'): raise ValueError('ordered_recovery_response')
            if pending.owner != _auth_key(auth):
                # A renewed caller may have committed a never-admitted pending
                # operation, OR merely queried an older owner's lost result.
                # Only Desktop's ordinary ownership check distinguishes these.
                try:
                    frontier = self._diagnostics.step('recover.verify_admitted_owner', lookup.frontier)
                except OrderedBridgeRejected as error:
                    if error.rejection != 'phone_reply_ownership': raise
                else:
                    if frontier.stream_id != stream_id or frontier.generation != 0:
                        raise ValueError('ordered_recovery_response')
                    pending.owner, pending.sequence = _auth_key(auth), lookup
                    pending.producer = OrderedOutputProducer(lookup, pending.output)
            with self._control:
                if self._shutdown: raise ValueError('ordered_service_shutdown')
                if (self._opening if initial_open else self._session) is not prior:
                    raise ValueError('ordered_recovery_stale')
                # The original admission's owner is never rebound by a retry.
                self._install_open(json.loads(pending.owner), pending)
                record['successor'] = self._session
                record['admitted'] = True
            return result

    def _close_opening(self, auth, stream_id, generation, *, halt):
        self._diagnostics.mark('close.pending_validation')
        pending = self._opening
        if not secrets.compare_digest(_auth_key(auth), pending.owner):
            self._reject('close.pending_owner_mismatch', 'ordered_service_owner')
        if pending.stream_id != stream_id: self._reject('close.pending_stream_mismatch', 'ordered_service_stream')
        if type(generation) is not int or generation != 0:
            raise ValueError('ordered_service_generation')
        if halt: return dict(version=1,state='halted',generation=0)
        if not pending.retired:
            if self._diagnostics.step('close.pending_desktop_close', lambda: pending.sequence._call('close')) is not True:
                raise ValueError('ordered_service_close_response')
            self._diagnostics.step('close.pending_empty_directory', pending.output.rmdir)
            pending.retired = True
        return dict(version=1,state='closed',retained=[])

    def _start_pump(self, session, *, initial_frame=None):
        sequence = session.sequence
        def supply(frontier):
            self._current()
            self._cache_epoch()  # Clear remains live even when captured mode is OFF.
            result = sequence.next_plan(frontier)
            if type(result) is not dict: raise ValueError('ordered_service_plan_response')
            if result.get('state') == 'ready' and set(result) == {'state', 'plan'}:
                return OrderedSourcePlan.from_wire(result['plan'])
            if result.get('state') == 'admitted' and set(result) == {'state', 'plan', 'frontier'}:
                return OrderedSourceAdmission(OrderedSourcePlan.from_wire(result['plan']),
                                              parse_frontier(result['frontier']))
            if result.get('state') == 'waiting' and set(result) == {'state', 'stage', 'sequenceIndex'}:
                return None
            if result.get('state') == 'finished' and set(result) == {'state', 'frontier'}:
                return None
            raise ValueError('ordered_service_plan_response')

        worker = OrderedOutputWorker(session.producer, ffmpeg=self._ffmpeg,
            source_roots=self._roots, supply=supply, quality=session.quality,
            initial_frame=initial_frame, initial_generation=session.generation,
            idle_assets=self._idle_assets if session.cache_enabled else None, cache_epoch=self._cache_epoch,
            verify_media=not SKIP_SPEECH_CLIP_PROBES_EXPERIMENT)
        def failed(error):
            session.failed(error)  # First business failure remains authoritative.
            def report():
                self._diagnostics.mark('producer.worker')
                raise error
            try:
                self._diagnostics.run('producer', report,
                    lambda: self._diagnostic_snapshot({'streamId':session.stream_id}), public_failure)
            except Exception: pass
        session.pump = OrderedOutputPump(worker, on_published=session.notify, on_failure=failed,
            acquire_source=sequence.prepare_source,release_source=sequence.release_prepared,
            finish_reply=sequence.finish_reply)
        session.pump.start()

    def request(self, method, body):
        return self._diagnostics.run(method, lambda: self._dispatch_request(method, body),
            lambda: self._diagnostic_snapshot(body), public_failure)

    def _continuation_session(self, auth, stream_id, generation):
        if self._shutdown: raise ValueError('ordered_service_shutdown')
        session = self._scope(auth, stream_id)
        if session.closed or session.retired: raise ValueError('ordered_service_closed')
        if not _integer(generation) or generation != session.generation:
            raise ValueError('ordered_service_generation')
        if session.failure is not None: raise ValueError('ordered_reattach_media_unavailable')
        return session

    def _reattach(self, auth, stream_id, generation, request):
        import hmac
        self._diagnostics.mark('reattach.validate')
        intent = parse_reattach(stream_id, generation, request)
        with self._control:
            session = self._continuation_session(auth, stream_id, generation)
            if session.recovery_digest is None: raise ValueError('ordered_recovery_proof_missing')
            if not hmac.compare_digest(session.recovery_digest, intent.digest):
                raise ValueError('ordered_recovery_proof')
        # No encoder/producer/state lock crosses a Desktop round trip. Stop,
        # Reset and ACK can settle meanwhile; recheck before granting a result.
        result = self._diagnostics.step('reattach.desktop',
            lambda: session.sequence._call('reattach', generation=generation, request=request))
        self._diagnostics.mark('reattach.retained_media')
        with self._io:
            # Use the existing immutable-file admission check. ACK/unlink shares
            # this lock; no joined file is mistaken for missing pending media.
            try:
                for retained_generation, ordinal in session.producer.retained_keys():
                    if retained_generation == generation:
                        session.producer.media_path(generation, ordinal)
            except (OSError, ValueError):
                raise ValueError('ordered_reattach_media_unavailable') from None
        with self._control:
            self._diagnostics.mark('reattach.recheck_owner')
            if self._continuation_session(auth, stream_id, generation) is not session:
                raise ValueError('ordered_reattach_stale')
            self._current()
            if type(result) is not dict or result != intent.result():
                raise ValueError('ordered_reattach_response')
        return result

    def _dispatch_request(self, method, body):
        fields = {'open': {'recovery'} if type(body) is dict and 'recovery' in body else set(),
                  'recover': {'recovery'}, 'wait': {'afterOrdinal','generation'}, 'close': {'generation'},
                  'halt': {'generation'}, 'restart': {'stoppedOutput'}, 'started': {'generation','ordinal'},
                  'ack': {'generation', 'ordinal', 'readersClosed'}, 'cached': {'generation','request'}}
        fields['progress'] = {'generation', 'progress'}
        fields['capabilities'] = {'generation'}
        fields['reattach'] = {'generation','operationId','recoveryEpoch','capability','afterOrdinal'}
        if (type(body) is not dict or method not in fields
                or set(body) != {'version', 'auth', 'streamId'} | fields[method]
                or type(body['version']) is not int or body['version'] != 1):
            raise ValueError('ordered_service_shape')
        if type(body['streamId']) is not str or not re.fullmatch('[a-f0-9]{32}', body['streamId']):
            raise ValueError('ordered_service_stream')
        self._diagnostics.step('request.desktop_authority', self._current)
        self._diagnostics.mark('request.admission')
        if method == 'recover': return self._recover(body['auth'], body['streamId'], body['recovery'])
        if method == 'reattach':
            request = {key:body[key] for key in ('version','operationId','recoveryEpoch','capability','afterOrdinal')}
            return self._reattach(body['auth'], body['streamId'], body['generation'], request)
        if method == 'capabilities':
            with self._control:
                session = self._continuation_session(body['auth'], body['streamId'], body['generation'])
            result = session.sequence._call('capabilities', generation=body['generation'])
            with self._control:
                if self._continuation_session(body['auth'], body['streamId'], body['generation']) is not session:
                    raise ValueError('ordered_reattach_stale')
                self._current()
            if result != dict(version=1, orderedContinuationVersion=1):
                raise ValueError('ordered_reattach_response')
            return result
        if method == 'progress':
            # Optional UI reporting must never hold the service/media lock
            # across a Desktop HTTP roundtrip. Desktop rechecks owner/generation.
            from .ordered_progress import validate_progress
            progress = validate_progress(body['progress'])
            with self._control:
                if self._shutdown: raise ValueError('ordered_service_shutdown')
                session = self._scope(body['auth'], body['streamId'])
                if session.closed or session.retired: raise ValueError('ordered_service_closed')
                if not _integer(body['generation']) or body['generation'] != session.generation:
                    raise ValueError('ordered_service_generation')
                generation, sequence = session.generation, session.sequence
            return sequence._call('progress', generation=generation, progress=progress)
        with self._control:
            if self._shutdown: raise ValueError('ordered_service_shutdown')
            if method == 'open': return self._open(body['auth'], body['streamId'], body.get('recovery'))
            if self._opening is not None and self._opening.stream_id == body['streamId'] and method in ('halt','close'):
                return self._close_opening(body['auth'],body['streamId'],body['generation'],halt=method=='halt')
            session = self._scope(body['auth'], body['streamId'], cleanup=method in ('ack','halt','close'))
            if method == 'cached':
                if session.closed or session.retired: raise ValueError('ordered_service_closed')
                if not _integer(body['generation']) or body['generation'] != session.generation:
                    raise ValueError('ordered_service_generation')
                request = body['request']
                if type(request) is not dict: raise ValueError('ordered_cached_request_shape')
                if request.get('action') in ('reserve','reserve_current'): self._validate_cached_asset(request.get('asset'))
                if request.get('action') == 'activate':
                    grant = session.sequence._call('cached',request=dict(action='state'))['grant']
                    if grant is None: raise ValueError('ordered_cached_activation_scope')
                    self._validate_cached_asset({k:grant[k] for k in (
                        'cacheEpoch','inventoryRevision','loopId','motionId','sourceFrameCount')})
                self._diagnostics.mark('cached.'+request['action'] if request.get('action') in
                    ('state','reserve','reserve_current','activate','observe','revoke') else 'cached.validate')
                result = session.sequence._call('cached',request=request)
                self._diagnostics.cached_control(body['streamId'], request.get('action'), result)
                session.pump.wake()
                return result
            if method == 'started':
                if session.closed or session.retired: raise ValueError('ordered_service_closed')
                if not _integer(body['generation']) or body['generation'] != session.generation:
                    raise ValueError('ordered_service_generation')
                if not _integer(body['ordinal']): raise ValueError('ordered_service_progress')
                # A delayed start receipt after exact joined release needs no
                # credit: the row is already absent from future lookahead.
                if (body['generation'],body['ordinal']) not in session.released:
                    session.producer.idle_started(body['generation'],body['ordinal'])
                session.pump.wake()
                return dict(version=1,accepted=True)
            if method == 'ack': return self._ack(session, body)
            if method == 'restart': return self._restart(session,body['stoppedOutput'])
            if method in ('halt', 'close'):
                self._diagnostics.mark(method+'.validate_generation')
                generation = body['generation']
                if not _integer(generation) or generation > session.generation:
                    raise ValueError('ordered_service_generation')
                if generation < session.generation:
                    if method == 'halt': return dict(version=1, state='halted', generation=generation)
                    return dict(version=1, state='closed', retained=[dict(generation=g,ordinal=o)
                        for g,o in session.producer.retained_keys() if g == generation])
                # Stop/notify first; unreachable Desktop cannot keep encoding or
                # make a held readiness request wait for the whole network timeout.
                self._diagnostics.step(method+'.stop_encoder', session.pump.stop)
                with session.condition:
                    session.closed = True
                    session.notify()
                self._diagnostics.mark(method+'.notify_closed', 'completed')
                if method == 'halt': return dict(version=1, state='halted', generation=generation)
            if method == 'close':
                self._diagnostics.step('close.desktop_close', lambda: session.sequence._call('close'))
                session.retired = True
                self._diagnostics.mark('close.retired', 'completed')
                if not self._diagnostics.step('close.join_encoder', session.pump.close):
                    self._reject('close.encoder_join_pending', 'ordered_service_encoder_join_pending')
                self._diagnostics.step('close.reconcile_publications', session.producer.reconcile_publications)
                self._diagnostics.step('close.clear_uncommitted', session.pump.cleanup)
                retained = self._diagnostics.step('close.retained_keys', session.producer.retained_keys)
                return dict(version=1, state='closed', retained=[dict(generation=g,ordinal=o)
                    for g,o in retained if g == generation])
        return self._wait(session, body['afterOrdinal'], body['generation'])

    def _restart(self, session, stopped):
        self._diagnostics.mark('restart.validate')
        if session.retired: raise ValueError('ordered_service_closed')
        identity = json.dumps(stopped,sort_keys=True,separators=(',',':'),allow_nan=False)
        if session.last_restart is not None and session.last_restart[0] == identity:
            return json.loads(session.last_restart[1])
        # Native already stopped output; cancel/join this exact producer before
        # Desktop commits the replacement frontier. No inference is requested.
        self._diagnostics.step('restart.stop_encoder', session.pump.stop)
        with session.condition:
            session.closed = True
            session.notify()
        if not self._diagnostics.step('restart.join_encoder', session.pump.close):
            self._reject('restart.encoder_join_pending', 'ordered_service_encoder_join_pending')
        self._diagnostics.step('restart.reconcile_publications', session.producer.reconcile_publications)
        self._diagnostics.step('restart.clear_uncommitted', session.pump.cleanup)
        frontier = self._diagnostics.step('restart.desktop_frontier', lambda: session.sequence.restart_from_stop(stopped))
        # Desktop validated the exact stopped descriptor above. Keep its actual
        # encoded pixels, including any in-progress fade, before old ACK/unlink.
        initial_frame = self._diagnostics.step('restart.decode_stopped_frame', lambda: decode_ordered_frame(self._ffmpeg,
            session.producer.media_bytes(stopped['generation'],stopped['ordinal']),stopped['frameOffset'])) if stopped['known'] else None
        retained = [dict(generation=g,ordinal=o) for g,o in session.producer.retained_keys()
                    if g == session.generation]
        result = dict(version=1,state='restarted',streamId=session.stream_id,generation=frontier.generation,retained=retained)
        with session.condition:
            session.generation = frontier.generation
            session.closed = False
            session.failure = None  # Fresh generation, not a replacement of its first failure.
            session.notify()
        self._diagnostics.step('restart.start_encoder', lambda: self._start_pump(session,initial_frame=initial_frame))
        session.last_restart = identity,json.dumps(result,separators=(',',':'))
        return result

    def _wait(self, session, after, generation):
        self._diagnostics.mark('wait.validate')
        if not _integer(after, -1): raise ValueError('ordered_service_cursor')
        if not _integer(generation) or generation>session.generation: raise ValueError('ordered_service_generation')
        # One outstanding availability request; this is a push wake, never a
        # playback/prepare request. Timeout fits the existing peer's 10s request.
        with session.condition:
            if generation != session.generation:
                return dict(version=1, state='closed', failure=None, announcements=[])
            if session.waiting is not None and session.waiting[0] == generation:
                raise ValueError('ordered_service_wait_pending')
            token = (generation, object())
            session.waiting = token
        deadline = time.monotonic()+5
        try:
            while True:
                with session.condition:
                    revision, closed = session.revision, session.closed or generation!=session.generation
                    failure = session.failure if generation == session.generation else None
                if closed or failure is not None:
                    return dict(version=1, state='closed' if closed else 'failed', failure=failure, announcements=[])
                try:
                    rows = self._diagnostics.step('wait.announcements', lambda: session.producer.announcements(after))
                except Exception:
                    # Close may retire Desktop during an in-flight snapshot.
                    # Only that confirmed local stop supersedes this read.
                    with session.condition:
                        if session.closed or generation!=session.generation: continue
                    raise
                self._diagnostics.step('wait.desktop_authority', self._current)
                with session.condition:
                    if session.closed or generation!=session.generation: continue
                if rows or time.monotonic() >= deadline:
                    return dict(version=1, state='open', failure=None, announcements=list(rows))
                with session.condition:
                    if session.revision == revision:
                        session.condition.wait(max(0, deadline-time.monotonic()))
        finally:
            with session.condition:
                if session.waiting is token: session.waiting = None

    def _ack(self, session, body):
        self._diagnostics.mark('ack.validate')
        if not _integer(body['generation']) or not _integer(body['ordinal']):
            raise ValueError('ordered_service_ack')
        if body['readersClosed'] is not True:
            self._reject('ack.reader_proof_missing', 'ordered_service_reader_not_closed')
        key = body['generation'], body['ordinal']
        with self._io:
            if key not in session.released:
                if key not in session.pending_delete:
                    session.pending_delete[key] = self._diagnostics.step('ack.desktop_release',
                        lambda: session.producer.acknowledge(*key, readers_closed=True))
                path = session.pending_delete[key]
                self._diagnostics.step('ack.file_unlink', lambda: path.unlink(missing_ok=True))
                session.producer.release_removed(*key)
                del session.pending_delete[key]
                session.released.append(key)
                # Joined old readers may release their last file before the
                # successor encoder is scheduled. Its active working root must
                # survive that empty interval; only terminal retirement owns it.
                parent = path.parent
                boundary = self.root if session.retired else session.producer.root
                while parent != boundary and parent != self.root and parent.is_relative_to(self.root):
                    try: parent.rmdir()
                    except OSError: break
                    parent = parent.parent
        session.pump.wake()
        return dict(version=1, released=True)

    def media(self, stream_id, generation, ordinal):
        self._current()
        if (type(stream_id) is not str or not re.fullmatch('[a-f0-9]{32}', stream_id)
                or not _integer(generation) or not _integer(ordinal)):
            raise ValueError('ordered_service_stream')
        with self._io:
            session = self._session
            if session is None or not secrets.compare_digest(stream_id, session.stream_id):
                raise ValueError('ordered_service_stream')
            data = session.producer.media_bytes(generation, ordinal)
        self._current()
        return data

    def shutdown(self):
        return self._diagnostics.run('shutdown', self._shutdown_session,
            lambda: self._diagnostic_snapshot({}), public_failure)

    def _shutdown_session(self):
        with self._control:
            self._shutdown = True
            session = self._session
            if session is None: return
            with session.condition:
                session.closed = True
                session.notify()
            self._diagnostics.step('shutdown.join_encoder', session.pump.close)
            # Process shutdown is not a native reader-joined receipt. Keep files.
