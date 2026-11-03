"""Allowlisted plan observations through the shared diagnostic contract.

Only call from existing control/producer work, not real-time audio callbacks.
The bounded shared journal owns persistence and rotation.
"""
import json
import asyncio
import sys
import hashlib
import uuid
import re
from contextlib import contextmanager
from contextvars import ContextVar
from core.diagnostics.emitter import DiagnosticEmitter
from core.diagnostics.journal import enqueue_diagnostic
from core.diagnostics.policy import site_enabled

_current_operation=ContextVar('nc_diagnostic_operation',default=None)

def current_operation():
    """Task-local correlation only; never an authorization or playback input."""
    value=_current_operation.get()
    return dict(value) if value else None


def _emergency(event):
    print(json.dumps({'event':'diagnostic_event','details':{'contract':event}},
                     separators=(',',':')),file=sys.stderr,flush=True)


class PlanTrace:
    def __init__(self, enqueue=enqueue_diagnostic, *, component='backend'):
        if enqueue is enqueue_diagnostic:
            from core.diagnostics.policy_config import ensure_policy_loader
            ensure_policy_loader()
        self.emitter=DiagnosticEmitter(component=component,build_id=None,
            build_unavailable_reason='not_available',clock_id='backend-monotonic',
            enqueue=enqueue,emergency=_emergency)

    @staticmethod
    def source_id(chunk_id):
        return hashlib.sha256(chunk_id.encode('utf-8')).hexdigest()

    def bind_operation(self, session_id, site, work, *, chunk_id=None):
        """Capture only diagnostic ancestry at submission, not application context."""
        parent=current_operation()
        def bound(*args, **kwargs):
            with self.operation(session_id,site,chunk_id=chunk_id,
                    parent_operation_id=parent['operation_id'] if parent else None,
                    parent_event_id=parent['event_id'] if parent else None):
                return work(*args,**kwargs)
        return bound

    def observe(self, session_id, site, condition, expected, actual, *, chunk_id=None):
        try:
            if not site_enabled(site,'info','observed',{'condition':condition,'expected':expected,'actual':actual}):return None
            active=current_operation()
            active=active if active and active['trace_id']==session_id else None
            context={'session_id':session_id}
            if isinstance(chunk_id,str):context['chunk_id']=self.source_id(chunk_id)
            return self.emitter.emit(dict(level='info',event_name='transaction.operation',
                trace_id=session_id,operation_id=active['operation_id'] if active else session_id+':'+site,
                parent_operation_id=None,phase='decision',outcome='observed',basis='observed',
                links=[{'relation':'part_of','event_id':active['event_id'],'operation_id':active['operation_id']}] if active and active['event_id'] else [],context=context,
                data={'site':site,'condition':condition,'expected':expected,'actual':actual}))
        except Exception:
            return None

    @contextmanager
    def operation(self, session_id, site, *, chunk_id=None, parent_operation_id=None, parent_event_id=None):
        """Observe synchronous work; completion is not media/output readiness."""
        operation_id=uuid.uuid4().hex
        active=current_operation()
        if parent_operation_id is None and active and active['trace_id']==session_id:
            parent_operation_id=active['operation_id'];parent_event_id=active['event_id']
        def emit(phase,outcome,data,links=None):
            try:
                if phase=='end' and begin:data={**data,'begin_recorded':True}
                level='error' if outcome=='failed' else 'info'
                if not site_enabled(site,level,outcome,data):return None
                context={'session_id':session_id}
                if isinstance(chunk_id,str):context['chunk_id']=self.source_id(chunk_id)
                return self.emitter.emit(dict(level='error' if outcome=='failed' else 'info',
                    event_name='transaction.operation',trace_id=session_id,operation_id=operation_id,
                    parent_operation_id=parent_operation_id,phase=phase,outcome=outcome,basis='observed',
                    links=(links or [])+([{'relation':'part_of','event_id':parent_event_id,
                                          'operation_id':parent_operation_id}] if parent_operation_id and parent_event_id else []),
                    context=context,data={'site':site,**data,**({'begin_suppressed':True} if phase=='end' and begin_suppressed and begin is None else {})}))
            except Exception:
                return None
        begin_suppressed=not site_enabled(site,'info','pending',{})
        begin=emit('begin','pending',{})
        link={'trace_id':session_id,'operation_id':operation_id,'event_id':begin}
        token=_current_operation.set(link)
        try:
            yield dict(link)
        except (Exception, asyncio.CancelledError) as error:
            cancelled=isinstance(error,(InterruptedError,asyncio.CancelledError))
            kind=('cancelled' if cancelled else 'timeout' if isinstance(error,TimeoutError)
                  else 'invalid_input' if isinstance(error,ValueError)
                  else 'io_error' if isinstance(error,OSError) else 'exception')
            details={'condition':'operation_completed','expected':True,'actual':False,
                     'failure_kind':kind}
            origin=emit('decision','observed',details)
            origin=origin or 'diagnostic-origin-unavailable'
            if cancelled:
                details={**details,'initiator':'unavailable','cause_event_id':origin}
            emit('end','cancelled' if cancelled else 'failed',
                 {**details,'origin_event_id':origin},
                 [{'relation':'caused_by','event_id':origin,'operation_id':operation_id}])
            raise
        else:
            emit('end','success',{'condition':'operation_completed','expected':True,'actual':True})
        finally:
            _current_operation.reset(token)

    def remote_call(self, body, site, work):
        """Diagnostic labels never participate in request admission or authority."""
        clean={key:value for key,value in body.items() if key!='diagnosticLink'}
        session=body.get('trialId')
        session=session if isinstance(session,str) and re.fullmatch(r'[a-f0-9]{32}',session) else uuid.uuid4().hex
        link=body.get('diagnosticLink');parent=None;event=None
        if type(link) is dict and set(link)=={'trace_id','operation_id','event_id'} and link.get('trace_id')==session:
            operation=link.get('operation_id')
            match=re.fullmatch(r'(js-[a-z0-9]+-[0-9]+-[a-z0-9]+):request:[0-9]+',operation) if isinstance(operation,str) and len(operation)<=128 else None
            candidate=link.get('event_id')
            if match and (candidate is None or (isinstance(candidate,str) and len(candidate)<=128 and
                         re.fullmatch(re.escape(match.group(1))+r':[0-9]+',candidate))):
                parent=operation;event=candidate
        with self.operation(session,site,parent_operation_id=parent,parent_event_id=event):
            self.observe(session,site,'remote_link_valid',True,parent is not None)
            return work(clean)
