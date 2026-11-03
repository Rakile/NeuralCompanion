"""Bounded lifecycle breadcrumbs feeding the shared diagnostic journal.

Not a scheduler or recovery policy. No disk/bridge inspection; successful media
progress stays silent. Failure snapshots contain custody, not alleged native
reader counts. Diagnostics must never change the original return or exception.
"""
from collections import deque, OrderedDict
from contextvars import ContextVar
import hashlib
import threading
import time
import uuid

_active = ContextVar('ordered_lifecycle_diagnostic', default=None)


class OrderedLifecycleDiagnostics:
    def __init__(self):
        self._lock = threading.Lock()
        self._history = deque(maxlen=24)
        self._total = 0
        self._origins = OrderedDict()
        self._cached_controls = OrderedDict()
        self._trace = None
        self._salt = uuid.uuid4().hex

    def identity(self, value):
        return hashlib.sha256((self._salt + value).encode()).hexdigest()[:24] if type(value) is str else None

    def cached_control(self, stream, action, result):
        """Bounded control checkpoints, not per-frame or chunk trace snapshots.

        Download readiness is not presentation. Keep the first actual state and
        each authority transition even with optional tracing OFF; never retain
        the request/auth or arbitrary upstream payload alongside these scalars.
        """
        try:
            if action not in ('state','reserve','reserve_current','activate','observe','revoke') or type(result) is not dict: return
            data = dict(site='backend.ordered.cached.control', action=action)
            if action == 'state':
                frontier = result['frontier']
                frame = frontier.get('lastFrame') or {}
                grant = result.get('grant') or {}
                data.update(next_ordinal=frontier['nextOrdinal'], generation=frontier['generation'],
                    reply_active=frontier.get('replyId') is not None, active=result['active'],
                    grant_present=result.get('grant') is not None, activation_revision=grant.get('activationRevision'),
                    source_id=frame.get('sourceId'), source_frame=frame.get('frame'),
                    source_frame_count=frame.get('sourceFrameCount'))
                # Streamed frames/ordinals must not turn this into a polling log.
                signature = tuple(data[k] for k in ('generation','reply_active','active','grant_present',
                                                   'activation_revision','source_id','source_frame_count'))
            else:
                data.update(activation_revision=result.get('activationRevision'),
                    after_ordinal=result.get('afterOrdinal'), entry_frame=result.get('entryFrame'),
                    revoked=result.get('revoked'))
                signature = tuple(data.values())
            key = stream, action
            with self._lock:
                if self._cached_controls.get(key) == signature: return
                self._cached_controls[key] = signature
                self._cached_controls.move_to_end(key)
                while len(self._cached_controls)>64: self._cached_controls.popitem(last=False)
            from core.diagnostics.plan_trace import PlanTrace
            if self._trace is None: self._trace = PlanTrace()
            operation = uuid.uuid4().hex
            # Reuse the pinned scalar evidence contract; do not add ad hoc
            # fields that its validator would discard before reaching disk.
            for condition, actual in data.items():
                if condition == 'site': continue
                self._trace.emitter.emit(dict(level='warning', event_name='transaction.operation',
                    trace_id=stream, operation_id=operation, parent_operation_id=None,
                    phase='snapshot', outcome='observed', basis='observed', links=[],
                    context={'session_id':stream}, data=dict(site=data['site'],
                        condition=condition,expected=None,actual=actual)))
        except Exception: pass

    def mark(self, stage, outcome='pending'):
        try:
            active = _active.get()
            if active is None: return
            active['stage'] = stage
            if not active['retain']: return
            row = dict(operation=active['id'], method=active['method'], stage=stage,
                       outcome=outcome, elapsed_ms=round((time.monotonic()-active['start'])*1000))
            with self._lock:
                self._total += 1
                self._history.append(row)
        except Exception: pass

    def step(self, stage, work):
        self.mark(stage)
        result = work()
        self.mark(stage, 'completed')
        return result

    def run(self, method, work, snapshot, failure):
        # Only locally supplied method names enter the diagnostic contract.
        method = method if method in ('open','recover','close','halt','restart','ack','wait','started','cached','progress','producer','shutdown','capabilities','reattach') else 'invalid'
        active = dict(id=uuid.uuid4().hex, method=method, start=time.monotonic(),
                      stage='request.validate', retain=method not in ('ack','wait','started','progress'))
        token = _active.set(active)
        try:
            self.mark('request.begin')
            result = work()
            self.mark('request.completed', 'completed')
            return result
        except Exception as error:
            try:
                self.mark(active['stage'], 'failed')
                try: facts = snapshot()
                except Exception:
                    facts = {'trace_id':active['id'], 'snapshot.state':'unavailable'}
                self._emit(active, facts, failure(error))
            except Exception: pass
            raise
        finally:
            _active.reset(token)

    def _emit(self, active, facts, failure):
        from core.diagnostics.plan_trace import PlanTrace, current_operation
        if self._trace is None: self._trace = PlanTrace()
        trace_id = facts.pop('trace_id')
        retained = facts.get('session.stream') or facts.get('opening.stream') or facts.get('request.stream')
        with self._lock:
            history = list(self._history)
            dropped = max(0, self._total-len(history))
            origin = self._origins.get(retained)
        parent = current_operation()
        links = []
        # Prior failure is correlation, not proof of this rejection's cause.
        if origin: links.append(dict(relation='part_of', event_id=origin[0], operation_id=origin[1]))
        if parent and parent.get('event_id'):
            links.append(dict(relation='part_of', event_id=parent['event_id'], operation_id=parent['operation_id']))
        facts = {'failure.stage':active['stage'], 'request.method':active['method'],
                 'request.elapsed_ms':round((time.monotonic()-active['start'])*1000),
                 **{'failure.'+k:v for k,v in failure.items()}, **facts,
                 'history.dropped':dropped, 'history.count':len(history)}
        facts['native.reader_count'] = 'not_observable_in_backend'
        facts['upstream.operation'] = parent['operation_id'] if parent else None
        if origin:
            facts.update({'prior_failure.event':origin[0], 'prior_failure.stage':origin[2],
                          'prior_failure.reason':origin[3]})
        # Compact allowlisted scalars avoid flooding the bounded shared queue.
        # Format: operation/method/stage/outcome/elapsed_ms (no private text).
        for i, row in enumerate(history):
            facts[f'history.{i}'] = '/'.join(str(row[k]) for k in ('operation','method','stage','outcome','elapsed_ms'))
        first = None
        emitted = 0
        for key, value in facts.items():
            event = self._trace.emitter.emit(dict(level='info', event_name='transaction.operation',
                trace_id=trace_id, operation_id=active['id'], parent_operation_id=parent['operation_id'] if parent else None,
                phase='decision', outcome='observed', basis='observed', links=links,
                context={'session_id':trace_id}, data=dict(site='backend.ordered.lifecycle.failure',
                    condition=key, expected=None, actual=value)))
            first = first or event
            emitted += int(event is not None)
        # Error marker LAST: protected failure capture must include preceding
        # custody/history evidence, not fire on the first field of the snapshot.
        self._trace.emitter.emit(dict(level='error', event_name='transaction.operation',
            trace_id=trace_id, operation_id=active['id'], parent_operation_id=parent['operation_id'] if parent else None,
            phase='decision', outcome='observed', basis='observed', links=links,
            context={'session_id':trace_id}, data=dict(site='backend.ordered.lifecycle.failure',
                condition='evidence.fields', expected=len(facts), actual=emitted)))
        if first and retained:
            with self._lock:
                if retained not in self._origins:
                    self._origins[retained] = (first, active['id'], active['stage'], failure['reason'])
                    while len(self._origins)>16: self._origins.popitem(last=False)
