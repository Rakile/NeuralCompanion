"""Private Desktop ordering port and backend proxy; no public media authority.

Only the loopback bridge may expose dispatch. Phone transport must not forward
these internal routes. Authentication material is held privately and never logged.
"""
from collections import OrderedDict, deque
from dataclasses import replace
import threading
import re
import time

from .output_sequence import OutputChunk, OutputFrontier, FrameProvenance, OutputSequence, OutputRejected
from .ordered_cached_idle import CachedIdlePresentation


class OrderedBridgeRejected(ValueError):
    def __init__(self, method, status, reason):
        self.method = method
        self.http_status = status if type(status) is int and 100 <= status <= 599 else None
        self.rejection = (reason if type(reason) is str and re.fullmatch(
            r'(?:ordered|output|phone_reply)_[a-z_]{1,80}',reason) else 'unclassified_remote_error')
        super().__init__('ordered_bridge_rejected')


def frontier_wire(frontier):
    frame = frontier.last_frame
    return dict(version=1, streamId=frontier.stream_id, generation=frontier.generation,
        nextOrdinal=frontier.next_ordinal, revision=frontier.revision, replyId=frontier.reply_id,
        lastFrame=None if frame is None else dict(sourceId=frame.source_id, frame=frame.frame,
                                                 sourceFrameCount=frame.source_frame_count))


def parse_frontier(value):
    import re
    if (type(value) is not dict or set(value) != {'version', 'streamId', 'generation', 'nextOrdinal', 'revision', 'replyId', 'lastFrame'}
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['streamId'], str) or not re.fullmatch('[a-f0-9]{32}', value['streamId'])
            or any(type(value[k]) is not int or not 0 <= value[k] <= (1<<53)-1 for k in ('generation', 'nextOrdinal', 'revision'))
            or value['replyId'] is not None and (not isinstance(value['replyId'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['replyId']))):
        raise ValueError('ordered_bridge_frontier')
    frame = value['lastFrame']
    if frame is not None:
        if type(frame) is not dict or set(frame) != {'sourceId', 'frame', 'sourceFrameCount'}:
            raise ValueError('ordered_bridge_frontier')
        frame = FrameProvenance(frame['sourceId'], frame['frame'], frame['sourceFrameCount'])
    return OutputFrontier(value['streamId'], value['generation'], value['nextOrdinal'], value['revision'], frame, value['replyId'])


class DesktopOutputBinding:
    def __init__(self, protocol, auth, stream_id, *, observer=None, idle_source=None, speech_source=None, transition_ms=lambda:180, recovery_digest=None):
        self.protocol = protocol
        self.owner_epoch = protocol.authenticate(auth)
        self._auth = dict(auth)
        self.sequence = OutputSequence(stream_id, observer=observer)
        self._cached_idle = CachedIdlePresentation(self.sequence)
        self.stream_id = stream_id
        self._idle_source = idle_source
        self._speech_source = speech_source
        self._transition_ms = transition_ms
        self._last_kind = None
        self._return_idle_frames_needed = 0
        self._return_idle_fade_ms = None
        self._lock = threading.RLock()
        self._retired = False
        self._pending = deque()
        self._render_anchor = None
        self._preparation_observation = None
        self._progress_reply = None
        self._progress = None
        self._progress_at = None
        self._progress_identity = None
        self._desktop_progress = None
        self._retained = set()
        self._released = deque(maxlen=64)
        self._finished = OrderedDict()
        self._last_restart = None
        self._recovery_digest = recovery_digest
        # Playback obligations outlive both the producer cursor and retirement.
        # Pruned by authoritative receipts, not by the bounded plan retry cache.
        self._recovery_pending = ()
        self._source_preparation = None
        self._reattach_epoch = 0
        self._reattach_operations = OrderedDict()

    def verify_recovery(self, digest):
        import hmac
        if self._recovery_digest is None: raise ValueError('ordered_recovery_proof_missing')
        if digest is None or not hmac.compare_digest(self._recovery_digest,digest):
            raise ValueError('ordered_recovery_proof')

    def recovery_replies(self):
        with self._lock:
            self._recovery_pending = self.protocol.registry.pending_recovery_replies(
                self.owner_epoch, self._recovery_pending)
            return self._recovery_pending

    def _owner(self, auth, *, cleanup=False):
        # Desktop-only authority; the backend imports this module for its proxy.
        from .phone_reply_receipts import PhoneReplyRejected
        epoch = (self.protocol.registry.authenticate(auth) if cleanup else self.protocol.authenticate(auth))
        if epoch != self.owner_epoch: raise PhoneReplyRejected('ownership')

    def _active(self):
        if self._retired: raise ValueError('ordered_binding_retired')

    def registered(self, auth, reply_id):
        """Called after real reply registration, before its runtime dispatch."""
        from .phone_reply_receipts import PhoneReplyRejected
        self._owner(auth)
        self.protocol.registry.status(auth, reply_id)  # Proves ownership, not output permission.
        with self._lock:
            self._active()
            current = self.sequence.frontier()
            if (reply_id == current.reply_id or reply_id in self._pending
                    or self._render_anchor is not None and reply_id == self._render_anchor.reply_id): return
            if reply_id in self._finished: raise ValueError('ordered_reply_replayed')
            if len(self._pending) >= 32: raise PhoneReplyRejected('capacity')
            self._progress_reply = reply_id
            self._progress = None
            self._progress_at = None
            self._progress_identity = None
            self._desktop_progress = None
            self._recovery_pending = self.protocol.registry.pending_recovery_replies(
                self.owner_epoch, (*self._recovery_pending, reply_id))
            self._pending.append(reply_id)
            self._promote_pending()

    def _promote_pending(self):
        current = self.sequence.frontier()
        if current.reply_id is not None or current.next_ordinal == 0 or self._render_anchor is not None:
            return
        while self._pending:
            next_reply = self._pending.popleft()
            status = self.protocol.registry.status(self._auth, next_reply)
            if status['phase'] in ('cancelled', 'expired', 'superseded') or status.get('playback_stop_requested'):
                continue
            # Immutable render origin, not delivery admission. Initial idle may
            # keep advancing until the first speech source is actually ready.
            self._render_anchor = replace(current, reply_id=next_reply)
            self._observe_preparation('anchored', current)
            break

    def _observe_preparation(self, stage, current, sequence_index=0):
        anchor = self._render_anchor
        identity = (anchor, stage, sequence_index)
        if identity == self._preparation_observation:
            return
        self._preparation_observation = identity
        try:
            from core.diagnostics.plan_trace import PlanTrace
            trace = PlanTrace(component='desktop')
            for condition, value in (('preparation_stage', stage), ('generation', current.generation),
                                     ('sequence_index', sequence_index),
                                     ('render_anchor_ordinal', anchor.next_ordinal),
                                     ('expected_ordinal', current.next_ordinal)):
                trace.observe(self.stream_id, 'desktop.plan.output', condition, None, value,
                              chunk_id=anchor.reply_id)
        except Exception:
            pass  # Observation never grants admission or interrupts idle output.

    def _observe_publication(self, row, status):
        """Cumulative reply telemetry, never queue custody or playback authority."""
        if row.reply_id != self._progress_reply:
            return
        prior = self._desktop_progress or {}
        first_source = prior.get('firstSourceId', row.source_id)
        render_id = prior.get('firstRenderChunkId')
        if render_id is None:
            try:
                resolve = getattr(self._speech_source, 'render_chunk_for_audio', None)
                render_id = resolve(row.reply_id, first_source) if callable(resolve) else None
            except Exception:
                render_id = None  # Optional observation cannot reject a committed clip.
        self._desktop_progress = dict(replyId=row.reply_id, generation=row.generation,
            firstSourceId=first_source, firstRenderChunkId=render_id if type(render_id) is str
                and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', render_id) else None,
            readyChunks=prior.get('readyChunks', 0)+1,
            preparedUnits=row.sequence_index+row.source_range.end/row.source_range.total_frames,
            finalSegments=status['last_sequence_index']+1 if status['phase']=='complete'
                and status['last_sequence_index'] is not None else None)

    def presentation_snapshot(self, request=None):
        """Optional presentation query, atomic with retirement (not admission)."""
        from .phone_reply_receipts import PhoneReplyRejected
        with self._lock:
            if self._retired:
                return None
            if isinstance(request, dict) and set(request) == {'orderedReply'}:
                return self.presentation(request['orderedReply'])
            if request:
                raise ValueError('Ordered output does not accept phone handoff requests')
            try:
                snapshot = self.planning_snapshot()
            except PhoneReplyRejected as error:
                # Chat shutdown can withdraw availability before the binding
                # retires. A polled observation reports absence, not an addon
                # failure on every tick. Explicit reply plans and all admission
                # calls above/below retain their strict authentication checks.
                if error.reason != 'unavailable':
                    raise
                return {'phone_owns_presentation': False}
            return {'phone_owns_presentation': True, 'orderedOutput': snapshot,
                    'desktopProgress': dict(self._desktop_progress) if self._desktop_progress is not None else None,
                    'remoteProgress': dict(self._progress) if self._progress is not None else None,
                    'remoteProgressIdentity': dict(self._progress_identity) if self._progress_identity is not None else None,
                    'remoteProgressAgeSeconds': max(0, time.monotonic()-self._progress_at)
                        if self._progress_at is not None else None}

    def planning_snapshot(self, reply_id=None):
        """No reply selects delivery progress; a reply selects its fixed render origin."""
        self._owner(self._auth)
        with self._lock:
            self._active()
            result = self.sequence.planning_snapshot()
            if reply_id is not None and self._render_anchor is not None and self._render_anchor.reply_id == reply_id:
                return frontier_wire(self._render_anchor)
            if reply_id is not None and result['replyId'] != reply_id:
                raise ValueError('ordered_reply_not_current')
            return result

    def presentation(self, reply_id):
        self._owner(self._auth)
        with self._lock:
            self._active()
            if self._render_anchor is not None and reply_id == self._render_anchor.reply_id:
                return dict(phone_owns_presentation=True, orderedOutput=frontier_wire(self._render_anchor))
            current = self.sequence.planning_snapshot()
            if reply_id == current['replyId'] and reply_id is not None:
                return dict(phone_owns_presentation=True, orderedOutput=current)
            if reply_id in self._pending:
                return dict(phone_owns_presentation=True, orderedReplyPending=True, replyId=reply_id)
            raise ValueError('ordered_reply_unknown')

    def _transition_plan(self, plan, frontier, *, previous_kind=None):
        # Match Desktop's display boundary: same-motion speech successors do
        # not fade; idle/speech or avatar-motion changes do. Mobile never chooses.
        duration = self._transition_ms()
        if type(duration) is not int or not 0 <= duration <= 5000:
            raise ValueError('ordered_transition_duration')
        last = frontier.last_frame
        last_kind=self._last_kind if previous_kind is None else previous_kind
        changed = last is not None and (plan['kind'] != last_kind
            or plan['frames'][0]['provenance']['sourceId'] != last.source_id)
        if plan['kind'] == 'idle' and self._last_kind == 'speech' and self._return_idle_frames_needed:
            # Freeze this boundary's duration when its actual return plan is
            # assigned, not earlier while speech is still being published.
            if self._return_idle_fade_ms is None:
                self._return_idle_fade_ms = duration
                self._return_idle_frames_needed = max(1, (duration*24+999)//1000)
            duration = self._return_idle_fade_ms
        # The current cached picture is observed on the phone, not this older
        # encoded frontier. Desktop delegates only this entry fade to native;
        # never composite from an obsolete streamed idle image or wait a loop.
        if plan['kind'] == 'speech' and last_kind == 'idle' and self._cached_idle.active and self._cached_idle.suppresses_idle:
            return {**plan, 'entryFadeMs': 0}
        return {**plan, 'entryFadeMs': duration if changed else (0 if last is None else None)}

    def _admit_first_source(self,current,prepared):
        admitted=self.sequence.reserve_speech(self._render_anchor.reply_id,current)
        self._observe_preparation('admitted',admitted)
        return dict(state='admitted',frontier=frontier_wire(admitted),
            plan=self._transition_plan(prepared['plan'],admitted))

    def dispatch(self, method, payload):
        fields = {'frontier': set(), 'snapshot': {'afterOrdinal'}, 'commit': {'chunk', 'expected'},
                  'idle-plan': {'expected'}, 'next-plan': {'expected'},
                  'finish': {'replyId'}, 'close': set(), 'restart': {'stoppedOutput'}, 'publication': {'generation','ordinal'},
                  'cached': {'request'}, 'capabilities': {'generation'}, 'reattach': {'generation','request'},
                  'progress': {'generation', 'progress'},
                  'prepare-source': {'afterPlanId'}, 'release-prepared': {'planId','disposition'},
                  'ack': {'generation', 'ordinal', 'readersClosed'}}
        if type(payload) is not dict: raise ValueError('ordered_bridge_shape')
        self._owner(payload.get('auth'), cleanup=method in ('ack','publication','close'))
        if method not in fields or set(payload) != {'auth', 'streamId'} | fields[method]:
            raise ValueError('ordered_bridge_shape')
        if payload['streamId'] != self.stream_id: raise ValueError('ordered_bridge_stream')
        with self._lock:
            if method in ('capabilities', 'reattach'):
                self._active()
                generation = payload['generation']
                if type(generation) is not int or generation != self.sequence.frontier().generation:
                    raise ValueError('ordered_service_generation')
                if method == 'capabilities': return dict(version=1, orderedContinuationVersion=1)
                from .ordered_output_recovery import parse_reattach
                intent = parse_reattach(self.stream_id, generation, payload['request'])
                self.verify_recovery(intent.digest)
                previous = self._reattach_operations.get(intent.operation)
                if previous is not None and previous != intent: raise ValueError('ordered_reattach_conflict')
                if intent.epoch < self._reattach_epoch or previous is None and intent.epoch <= self._reattach_epoch:
                    raise ValueError('ordered_reattach_stale')
                if previous is None:
                    # New operations check retained delivery bounds, never
                    # reader joins. A settled retry remains idempotent after
                    # subsequent exact ACKs have advanced that same cursor.
                    self.sequence.snapshot(intent.after)
                    self._reattach_operations[intent.operation] = intent
                    self._reattach_epoch = intent.epoch
                    # Entries are settled synchronously under this lock. Keep
                    # the existing 64-operation recovery bound for lost ACKs.
                    while len(self._reattach_operations) > 64:
                        self._reattach_operations.popitem(last=False)
                return intent.result()
            if method == 'close':
                self.retire('disconnect')
                return True
            if method not in ('ack','publication'): self._active()
            if method in ('prepare-source','release-prepared'):
                if self._source_preparation is None:
                    from .ordered_source_preparation import DesktopSourcePreparation
                    self._source_preparation=DesktopSourcePreparation(self)
                if method=='prepare-source':return self._source_preparation.acquire(payload['afterPlanId'])
                self._source_preparation.release_private(payload['planId'],payload['disposition'])
                return True
            if method == 'progress':
                from .ordered_progress import validate_progress
                if type(payload['generation']) is not int or payload['generation'] != self.sequence.frontier().generation:
                    raise ValueError('ordered_progress_generation')
                progress = validate_progress(payload['progress'])
                status = self.protocol.registry.status(self._auth, progress['replyId'])
                if progress['replyId'] != self._progress_reply:
                    return dict(version=1, accepted=False)
                if status['phase'] == 'complete' and status['last_sequence_index'] is not None:
                    # Keep the authoritative final total after Mobile retires
                    # its completed reply manifest; never revert the label to '+'.
                    progress = validate_progress(dict(progress, finalSegments=status['last_sequence_index']+1))
                identity = self._progress_identity
                if identity is None or identity['audioId'] != progress['firstSourceId']:
                    resolve = getattr(self._speech_source, 'render_chunk_for_audio', None)
                    render_id = resolve(progress['replyId'], progress['firstSourceId']) if callable(resolve) else None
                    self._progress_identity = (dict(audioId=progress['firstSourceId'], renderChunkId=render_id)
                        if type(render_id) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', render_id) else None)
                self._progress, self._progress_at = progress, time.monotonic()
                return dict(version=1, accepted=True)
            if method == 'cached':
                request = payload['request']
                shapes = {'state': set(), 'reserve': {'expected','asset'}, 'reserve_current': {'asset'},
                          'activate': {'observed'}, 'observe': {'observed'}, 'revoke': {'activationRevision'}}
                action = request.get('action') if type(request) is dict else None
                if action not in shapes or set(request) != {'action'} | shapes[action]:
                    raise ValueError('ordered_cached_request_shape')
                if action == 'state':
                    return dict(version=1,frontier=frontier_wire(self.sequence.frontier()),
                                grant=self._cached_idle.grant,active=self._cached_idle.active)
                if action in ('reserve','reserve_current'):
                    current = self.sequence.frontier()
                    expected = current if action == 'reserve_current' else parse_frontier(request['expected'])
                    if action == 'reserve_current':
                        asset=request['asset'];last=current.last_frame
                        if (current.reply_id is not None or last is None or type(asset) is not dict
                                or last.source_id!=asset.get('motionId') or last.source_frame_count!=asset.get('sourceFrameCount')):
                            raise OutputRejected('frontier_changed',expected_ordinal=current.next_ordinal,actual_ordinal=current.next_ordinal)
                    if self._return_idle_frames_needed:
                        if expected != current:
                            raise OutputRejected('frontier_changed', expected_ordinal=current.next_ordinal, actual_ordinal=expected.next_ordinal)
                        raise ValueError('ordered_cached_return_pending')
                    return self._cached_idle.reserve(expected,request['asset'],self._transition_ms())
                if action == 'activate':
                    result = self._cached_idle.activate(request['observed'])
                    current = self.sequence.frontier()
                    if current.reply_id is None and current.next_ordinal == result['afterOrdinal']+1:
                        self._last_kind = 'idle'
                    return result
                if action == 'observe':
                    frame = self._cached_idle.observe(request['observed'])
                    return dict(sourceId=frame.source_id,frame=frame.frame,sourceFrameCount=frame.source_frame_count)
                self._cached_idle.revoke(request['activationRevision'])
                return dict(version=1,revoked=True)
            if method == 'restart':
                stopped = payload['stoppedOutput']
                if self._last_restart is not None and type(stopped) is dict:
                    prior, result = self._last_restart
                    if set(stopped) == set(prior) and all(type(stopped[k]) is type(v) and stopped[k] == v for k,v in prior.items()):
                        return frontier_wire(result)
                current = self.sequence.frontier()
                reply_id = current.reply_id if current.reply_id is not None else (
                    self._render_anchor.reply_id if self._render_anchor is not None else None)
                if reply_id is not None:
                    status = self.protocol.registry.status(self._auth, reply_id)
                    if status['phase'] not in ('complete','cancelled','expired','superseded') and not status.get('playback_stop_requested'):
                        raise ValueError('ordered_reply_stop_unconfirmed')
                result = self.sequence.restart_from_stop(stopped)
                # Recovery epochs belong to this generation's native carrier.
                # Its successor starts a new coordinator at epoch one; old
                # generation requests still fail the generation check above.
                self._reattach_epoch = 0
                self._reattach_operations.clear()
                self._progress = None
                self._progress_at = None
                self._progress_identity = None
                self._desktop_progress = None
                self._cached_idle.revoke()
                self._return_idle_frames_needed = 0
                self._return_idle_fade_ms = None
                self._render_anchor = None
                if self._source_preparation is not None:self._source_preparation.invalidate()
                self._last_kind = 'transition' if result.last_frame is not None else None
                self._last_restart = dict(stopped), result
                # Do not drop newer authenticated input that arrived during native
                # settlement. It remains pending until replacement visuals commit.
                return frontier_wire(result)
            if method == 'publication':
                row=self.sequence.retained_chunk(payload['generation'],payload['ordinal'])
                return None if row is None else row.to_wire()
            if method == 'frontier': return frontier_wire(self.sequence.frontier())
            if method == 'snapshot': return [r.to_wire() for r in self.sequence.snapshot(payload['afterOrdinal'])]
            if method in ('idle-plan', 'next-plan'):
                expected = parse_frontier(payload['expected']); current = self.sequence.frontier()
                if expected != current:
                    raise OutputRejected('frontier_changed', expected_ordinal=current.next_ordinal, actual_ordinal=expected.next_ordinal)
                if method == 'next-plan' and current.reply_id is None and self._render_anchor is not None:
                    reply_id = self._render_anchor.reply_id
                    status = self.protocol.registry.status(self._auth, reply_id)
                    if status['phase'] in ('cancelled', 'expired', 'superseded') or status.get('playback_stop_requested'):
                        raise ValueError('ordered_reply_cancelled')
                    if status['phase'] == 'complete' and status['last_sequence_index'] is None:
                        self._observe_preparation('empty', current)
                        self.sequence.reserve_speech(reply_id, current)
                        result = self.dispatch('finish', dict(auth=self._auth,streamId=self.stream_id,replyId=reply_id))
                        return dict(state='finished', frontier=result)
                    if self._speech_source is None: raise ValueError('ordered_speech_source_unavailable')
                    prepared = self._speech_source.plan(self._render_anchor, 0)
                    if prepared['state'] == 'ready':
                        # Close idle only now. The worker obtains a fresh frontier
                        # before encoding; any speculative idle loses its compare.
                        return self._admit_first_source(current,prepared)
                    if prepared['state'] != 'waiting': raise ValueError('ordered_speech_plan_state')
                    self._observe_preparation(prepared['stage'], current)
                if method == 'idle-plan' or current.reply_id is None:
                    if method == 'next-plan' and self._cached_idle.suppresses_idle:
                        return dict(state='waiting',stage='cached_idle',sequenceIndex=0)
                    if self._idle_source is None: raise ValueError('ordered_idle_source_unavailable')
                    plan = self._transition_plan(self._idle_source.plan(current), current)
                    return plan if method == 'idle-plan' else dict(state='ready', plan=plan)
                index = self.sequence.next_speech_sequence(current)
                status = self.protocol.registry.status(self._auth, current.reply_id)
                if status['phase'] in ('cancelled', 'expired', 'superseded') or status.get('playback_stop_requested'):
                    raise ValueError('ordered_reply_cancelled')
                if (status['phase'] == 'complete' and (
                        status['last_sequence_index'] is None and index == 0
                        or status['last_sequence_index'] is not None and index == status['last_sequence_index']+1)):
                    result = self.dispatch('finish', dict(auth=self._auth,streamId=self.stream_id,replyId=current.reply_id))
                    return dict(state='finished', frontier=result)
                if self._speech_source is None: raise ValueError('ordered_speech_source_unavailable')
                origin = self._render_anchor if index == 0 else current
                if origin is None or origin.reply_id != current.reply_id or origin.generation != current.generation:
                    raise ValueError('ordered_speech_render_anchor_missing')
                result = self._speech_source.plan(origin,index)
                # Reuse the initial preparation event for later source waits.
                # Deduplicate by immutable reply anchor, stage and sequence;
                # retries must not become a polling log or affect admission.
                if result['state'] in ('waiting','ready'):
                    self._observe_preparation(result['stage'] if result['state']=='waiting' else 'ready',current,index)
                return {**result,'plan':self._transition_plan(result['plan'],current)} if result['state']=='ready' else result
            if method == 'commit':
                row, expected = OutputChunk.from_wire(payload['chunk']), parse_frontier(payload['expected'])
                if row.kind == 'speech':
                    status = self.protocol.registry.status(self._auth, row.reply_id)
                    if status['phase'] in ('cancelled', 'expired', 'superseded') or status.get('playback_stop_requested'):
                        raise ValueError('ordered_reply_cancelled')
                elif row.kind == 'idle' and self._cached_idle.suppresses_idle:
                    current = self.sequence.frontier()
                    raise OutputRejected('frontier_changed',expected_ordinal=current.next_ordinal,actual_ordinal=row.ordinal)
                previous = self.sequence.frontier()
                frontier = self.sequence.commit(row, expected)
                if frontier.next_ordinal > previous.next_ordinal:
                    if row.kind == 'speech':
                        self._observe_publication(row, status)
                        self._return_idle_frames_needed = 1
                        self._return_idle_fade_ms = None
                    else:
                        self._return_idle_frames_needed = max(0, self._return_idle_frames_needed-row.frame_count)
                if row.ordinal == frontier.next_ordinal - 1:
                    self._last_kind = row.kind
                self._retained.add((row.generation, row.ordinal))
                self._promote_pending()
                return frontier_wire(self.sequence.frontier())
            if method == 'ack':
                key = payload['generation'], payload['ordinal']
                if (payload['readersClosed'] is True and all(type(i) is int for i in key)
                        and key in self._released):
                    return True
                self.sequence.acknowledge(*key, readers_closed=payload['readersClosed'])
                self._retained.remove(key); self._released.append(key)
                return True
            reply_id = payload['replyId']
            if type(reply_id) is not str: raise ValueError('ordered_bridge_reply')
            if reply_id in self._finished: return dict(self._finished[reply_id])
            status = self.protocol.registry.status(self._auth, reply_id)
            if status['phase'] != 'complete' or status.get('playback_stop_requested'):
                raise ValueError('output_reply_not_final')
            self.sequence.finish_reply(reply_id, status['last_sequence_index'])
            if self._desktop_progress is not None and self._desktop_progress['replyId'] == reply_id:
                self._desktop_progress = dict(self._desktop_progress,
                    finalSegments=status['last_sequence_index']+1 if status['last_sequence_index'] is not None else 0)
            self._render_anchor = None
            if self._source_preparation is not None:self._source_preparation.invalidate()
            self._promote_pending()
            result = frontier_wire(self.sequence.frontier())
            self._finished[reply_id] = result
            while len(self._finished) > 64: self._finished.popitem(last=False)
            return result

    def retire(self, cause):
        with self._lock:
            if not self._retired:
                self.sequence.invalidate(self.sequence.frontier().generation, cause)
                self._retired = True; self._pending.clear(); self._render_anchor = None
                self._cached_idle.revoke()
                if self._source_preparation is not None:self._source_preparation.invalidate()

    @property
    def reclaimable(self):
        with self._lock: return self._retired and not self._retained

    @property
    def active(self):
        with self._lock: return not self._retired


class BackendOutputSequence:
    """No independent backend ledger: all compare-and-commit is in Desktop."""
    def __init__(self, request, auth, stream_id):
        self._request, self._auth, self.stream_id = request, dict(auth), stream_id

    def _call(self, method, **body):
        response = self._request('POST', '/api/internal/ordered-output/' + method,
            dict(auth=dict(self._auth), streamId=self.stream_id, **body))
        if type(response) is not dict: raise ValueError('ordered_bridge_response')
        if response.get('ok') is not True or response.get('status', 200) != 200:
            rejection = response.get('outputRejection')
            if (type(rejection) is dict and set(rejection) == {'reason', 'expectedOrdinal', 'actualOrdinal'}
                    and rejection['reason'] in ('capacity', 'frontier_changed', 'generation_changed')):
                raise OutputRejected(rejection['reason'], expected_ordinal=rejection['expectedOrdinal'], actual_ordinal=rejection['actualOrdinal'])
            # Never forward raw server bodies (which could contain private paths).
            raise OrderedBridgeRejected(method,response.get('status'),response.get('error'))
        return response.get('result')

    def frontier(self): return parse_frontier(self._call('frontier'))
    def idle_plan(self, expected): return self._call('idle-plan', expected=frontier_wire(expected))
    def next_plan(self, expected): return self._call('next-plan', expected=frontier_wire(expected))
    def prepare_source(self, after_plan_id=None):return self._call('prepare-source',afterPlanId=after_plan_id)
    def release_prepared(self, plan_id, disposition):
        if self._call('release-prepared',planId=plan_id,disposition=disposition) is not True:
            raise ValueError('ordered_preparation_release')
    def retained_chunk(self, generation, ordinal):
        result=self._call('publication',generation=generation,ordinal=ordinal)
        return None if result is None else OutputChunk.from_wire(result)
    def commit(self, chunk, expected): return parse_frontier(self._call('commit', chunk=chunk.to_wire(), expected=frontier_wire(expected)))
    def snapshot(self, after_ordinal):
        result = self._call('snapshot', afterOrdinal=after_ordinal)
        if type(result) is not list or len(result) > 60: raise ValueError('ordered_bridge_snapshot')
        return tuple(OutputChunk.from_wire(r) for r in result)
    def acknowledge(self, generation, ordinal, *, readers_closed):
        if self._call('ack', generation=generation, ordinal=ordinal, readersClosed=readers_closed) is not True:
            raise ValueError('ordered_bridge_ack')
    def finish_reply(self, reply_id): return parse_frontier(self._call('finish', replyId=reply_id))
    def restart_from_stop(self, stopped): return parse_frontier(self._call('restart', stoppedOutput=stopped))
