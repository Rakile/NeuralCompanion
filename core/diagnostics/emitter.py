"""Nonblocking diagnostic event construction; inject a queue, not disk IO."""
import copy
from datetime import datetime, timezone
import inspect
import threading
import time
import uuid
from core.diagnostics.contract import validate_event
from core.diagnostics.policy import policy, site_enabled

_FIELDS=frozenset(('level','event_name','trace_id','operation_id','parent_operation_id','phase','outcome','basis','links','context','data'))

def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

class DiagnosticEmitter:
    def __init__(self, *, component, build_id, build_unavailable_reason, clock_id, enqueue, emergency,
                 wall_clock=_utc, monotonic_clock=lambda:time.monotonic()*1000):
        self.producer_id=uuid.uuid4().hex
        self._identity=dict(component=component,build_id=build_id,build_unavailable_reason=build_unavailable_reason,clock_id=clock_id)
        self._enqueue=enqueue; self._emergency=emergency
        self._wall=wall_clock; self._mono=monotonic_clock
        self._sequence=0; self._notice_sequence=0; self._lock=threading.Lock(); self._local=threading.local()

    def _notice(self, reason, related=None, issues=None, sink=None):
        if getattr(self._local,'notice',False): return
        self._local.notice=True
        try:
            with self._lock:
                self._notice_sequence+=1; sequence=self._notice_sequence
            producer=self.producer_id+'-notice'; event_id=f'{producer}:{sequence}'
            data=({'site':'diagnostics.emit','issues':issues} if issues else
                  {'site':'diagnostics.emit','reason':reason,'related_event_id':related})
            if type(sink) is dict:
                for key,allowed in (
                    ('sink_stage',('validate','serialize','closed','enqueue','dispatch','mkdir',
                                   'stat','rotate','open','write','flush','close','post_write')),
                    ('sink_reason',('queue_full','journal_closed','invalid_event','permission_denied',
                                    'disk_full','io_error','other'))):
                    if type(sink.get(key)) is str and sink[key] in allowed:data[key]=sink[key]
                for key in ('errno','winerror','queue_depth','queue_capacity'):
                    value=sink.get(key)
                    if type(value) is int and 0<=value<=2147483647:data[key]=value
            self._emergency(dict(schema_version=1,event_id=event_id,producer_id=producer,sequence=sequence,
              component='diagnostics',build_id=None,build_unavailable_reason='emergency_path',
              wall_time_utc=_utc(),monotonic_ms=time.monotonic()*1000,clock_id=producer,
              level='error',event_name='diagnostics.validation_failed' if issues else 'diagnostics.sink_failed',
              trace_id=related or producer,operation_id=event_id,parent_operation_id=None,
              phase='snapshot',outcome='observed',basis='observed',links=[],context={},data=data))
        except Exception:
            # Last-resort output is fixed, never rejected input or exception text.
            try:
                import sys
                sys.stderr.write('[NC diagnostics] emergency sink failed\n')
            except Exception: pass
        finally: self._local.notice=False

    def emit_lazy(self, category, verbosity, build, mandatory=False):
        if not policy.enabled(category,verbosity,mandatory):return None
        try:return self.emit(build(),_selected=True)
        except Exception:self._notice('input_invalid');return None

    def emit(self, fields: dict, *, _selected=False) -> str | None:
        if getattr(self._local,'busy',False) or getattr(self._local,'notice',False):
            self._notice('reentrant_emit'); return None
        self._local.busy=True
        try:
            if type(fields) is not dict or set(fields)-_FIELDS:
                self._notice('input_invalid',issues=[{'path':'$','rule':'input_fields'}]);return None
            data=fields.get('data')
            if not _selected and type(data) is dict and not site_enabled(
                data.get('site',fields.get('event_name','')),fields.get('level'),fields.get('outcome'),data):return None
            with self._lock:
                if self._sequence>=9007199254740991:
                    exhausted=True
                else:
                    exhausted=False;self._sequence+=1;sequence=self._sequence
            if exhausted:self._notice('sequence_exhausted');return None
            event_id=f'{self.producer_id}:{sequence}'
            try:
                event=copy.deepcopy(fields)|self._identity|dict(schema_version=1,producer_id=self.producer_id,
                    sequence=sequence,event_id=event_id,wall_time_utc=self._wall(),monotonic_ms=self._mono())
            except Exception:self._notice('clock_failed',event_id);return None
            issues=validate_event(event)
            if issues:self._notice('input_invalid',event_id,issues);return None
            try:
                result=self._enqueue(event)
                if result is False:self._notice('enqueue_rejected',event_id);return None
                if hasattr(result,'add_done_callback'):
                    def completed(future):
                        try:
                            if future.result() is False:self._notice('enqueue_rejected',event_id)
                        except Exception:self._notice('enqueue_rejected',event_id,
                            sink=getattr(future,'diagnostic_failure',None))
                    result.add_done_callback(completed)
                elif inspect.isawaitable(result):
                    if inspect.iscoroutine(result):result.close()
                    self._notice('enqueue_rejected',event_id);return None
            except Exception:self._notice('enqueue_threw',event_id);return None
            return event_id
        except Exception:self._notice('input_invalid');return None
        finally:self._local.busy=False
