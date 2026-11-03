"""Bounded process-local JSONL journal, independent of logging configuration."""
from concurrent.futures import Future
import json
import errno
import os
from pathlib import Path
import queue
import threading
import atexit
import sys
from core.diagnostics.contract import validate_event
from core.diagnostics.failure_capture import capture_failure, capture_slots_full, is_failure
from core.diagnostics.retention import DEFAULT_RETENTION
from core.diagnostics.retention_worker import request_archive


class DiagnosticJournal:
    def __init__(self, path, *, capacity=256, max_bytes=4*1024*1024):
        if type(capacity) is not int or capacity<1 or type(max_bytes) is not int or max_bytes<1:
            raise ValueError('diagnostic_journal_invalid_limits')
        self.path=Path(path)
        self.max_bytes=max_bytes
        self.queue=queue.Queue(maxsize=capacity)
        self.lock=threading.Lock()
        self.closed=False
        self.written=0
        self.rotations=0
        self.rejected=0
        self.write_failures=0
        self.previous_unclean=False
        self.health_failed=False
        self.failure_capture_status='not_requested'
        self.failure_capture_incomplete=False
        self._captured_traces={}
        self.archive_future=None
        self._policies={}
        self.thread=threading.Thread(target=self._write,name='nc-diagnostic-journal',daemon=True)
        self.thread.start()

    def submit(self, event):
        future=Future()
        stage='validate'
        try:
            if validate_event(event):raise ValueError('diagnostic_contract_invalid')
            # Freeze before transfer; caller mutation cannot rewrite queued evidence.
            stage='serialize'
            body=json.dumps({'timestamp':event.get('wall_time_utc'),'event':'diagnostic_event',
                             'details':{'contract':event}},separators=(',',':'),ensure_ascii=True)+'\n'
            with self.lock:
                stage='closed'
                if self.closed:raise RuntimeError('diagnostic_journal_closed')
                stage='serialize'
                failure=json.loads(body)['details']['contract'] if is_failure(event) else None
                policy_record=json.loads(body)['details']['contract'] if event.get('event_name')=='diagnostics.policy' else None
                stage='enqueue'
                self.queue.put_nowait((body,future,failure,policy_record))
        except Exception as error:
            with self.lock:self.rejected+=1
            self._fail(future,error,stage)
        return future

    def _fail(self,future,error,stage):
        # Publish finite metadata before completing the Future. Preserve the
        # original exception for callers, but never export its text or paths.
        reason=('queue_full' if isinstance(error,queue.Full) else
                'journal_closed' if stage=='closed' else
                'invalid_event' if stage in ('validate','serialize') else
                'permission_denied' if isinstance(error,PermissionError) else
                'disk_full' if isinstance(error,OSError) and (error.errno==errno.ENOSPC or
                    getattr(error,'winerror',None) in (39,112)) else
                'io_error' if isinstance(error,OSError) else 'other')
        details=dict(sink_stage=stage,sink_reason=reason,
                     queue_depth=self.queue.qsize(),queue_capacity=self.queue.maxsize)
        for key in ('errno','winerror'):
            value=getattr(error,key,None)
            if type(value) is int and 0<=value<=2147483647:details[key]=value
        future.diagnostic_failure=details
        future.set_exception(error)

    def _health(self,state):
        """Worker-only metadata, never a claim of complete instrumentation."""
        try:
            target=self.path.with_suffix(self.path.suffix+'.health.json')
            target.parent.mkdir(parents=True,exist_ok=True)
            if state=='active':
                if target.exists():
                    try:
                        with target.open(encoding='utf-8') as handle:raw=handle.read(16385)
                        if len(raw)>16384:raise ValueError('oversized health')
                        previous=json.loads(raw)
                        self.previous_unclean=(type(previous) is not dict or
                            type(previous.get('version')) is not int or previous['version']!=1 or
                            previous.get('state')!='closed' or previous.get('previous_unclean') is not False or
                            any(type(previous.get(key)) is not int or previous[key]<0
                                for key in ('written','rotations','rejected','write_failures')) or
                            previous.get('rejected')!=0 or previous.get('write_failures')!=0)
                    except (ValueError,TypeError,AttributeError):self.previous_unclean=True
                elif self.path.exists():self.previous_unclean=True
            with self.lock:
                report=dict(version=1,state=state,written=self.written,rotations=self.rotations,
                            rejected=self.rejected,write_failures=self.write_failures,
                            previous_unclean=self.previous_unclean,coverage='not_proven',
                            archive_health_file='failures/archive-health.json',
                            failure_capture_status=self.failure_capture_status,diagnostic_policies=list(self._policies.values()))
            temporary=target.with_suffix(target.suffix+'.tmp')
            with temporary.open('w',encoding='utf-8') as handle:
                json.dump(report,handle,separators=(',',':'))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        except Exception:
            if not self.health_failed:
                self.health_failed=True
                try:sys.stderr.write('[NC diagnostics] capture health persistence failed\n')
                except Exception:pass

    def _write(self):
        self._health('active')
        self._request_archive(keep_latest=0)
        while True:
            try:body,future,failure,policy_record=self.queue.get(timeout=0.1)
            except queue.Empty:
                with self.lock:
                    closed=self.closed
                if closed:
                    self._health('incomplete' if self.write_failures or self.rejected or self.health_failed or self.failure_capture_incomplete else 'closed')
                    return
                continue
            stage='dispatch'
            try:
                notify=future.set_running_or_notify_cancel()
                stage='mkdir'
                self.path.parent.mkdir(parents=True,exist_ok=True)
                stage='stat'
                if self.path.exists() and self.path.stat().st_size+len(body)>self.max_bytes:
                    stage='rotate'
                    self.path.replace(self.path.with_suffix(self.path.suffix+'.1'))
                    self.rotations+=1
                stage='open'
                with self.path.open('a',encoding='utf-8',newline='\n') as handle:
                    stage='write'
                    handle.write(body)
                    stage='flush'
                    handle.flush()
                    stage='close'
                self.written+=1
                stage='post_write'
                if policy_record is not None:
                    with self.lock:
                        self._policies[policy_record['producer_id']]=policy_record
                        while len(self._policies)>32:self._policies.pop(next(iter(self._policies)))
                    self._health('active_snapshot')
                if failure is not None and failure['trace_id'] not in self._captured_traces:
                    try:
                        self.failure_capture_status=capture_failure(self.path,failure,list(self._policies.values()))
                    except Exception:
                        self.failure_capture_status='failed'
                    # Only successful reservations are deduplicated. A full store
                    # must be retryable in this same process once maintenance frees it.
                    if self.failure_capture_status in ('captured','partial'):
                        self._captured_traces[failure['trace_id']]=None
                        while len(self._captured_traces)>DEFAULT_RETENTION.capture_slots:
                            self._captured_traces.pop(next(iter(self._captured_traces)))
                    if self.failure_capture_status=='capacity_reached' or capture_slots_full(self.path):
                        self._request_archive(keep_latest=DEFAULT_RETENTION.pressure_keep_latest)
                    if self.failure_capture_status!='captured':
                        self.failure_capture_incomplete=True
                        try:sys.stderr.write('[NC diagnostics] failure capture '+self.failure_capture_status+'; retained evidence was not overwritten\n')
                        except Exception:pass
                    self._health('active_snapshot')
                if notify:future.set_result(True)
            except Exception as error:
                self.write_failures+=1
                if not future.done():self._fail(future,error,stage)
            finally:self.queue.task_done()

    def _request_archive(self, *, keep_latest):
        try:
            self.archive_future=request_archive(self.path.parent/'failures',keep_latest=keep_latest)
        except Exception:
            # Maintenance failure must not stop normal diagnostic writes.
            try:sys.stderr.write('[NC diagnostics] archive_schedule_failed; protected evidence retained\n')
            except Exception:pass

    def close(self):
        with self.lock:self.closed=True
        self.thread.join(timeout=2)


_lock=threading.Lock()
_journal=None
_desktop_journal=None


def _close_process_journal():
    if _journal is not None:_journal.close()
    if _desktop_journal is not None:_desktop_journal.close()


atexit.register(_close_process_journal)


def enqueue_diagnostic(event):
    global _journal, _desktop_journal
    with _lock:
        root=Path(__file__).resolve().parents[2]/'runtime'/'diagnostics'
        # Desktop planning is low-rate causal evidence. Presentation polling in
        # the same process must not rotate it away before speech admission fails.
        # Reuse the same bounded writer, validation, health and capture contract.
        if isinstance(event,dict) and event.get('component')=='desktop':
            if _desktop_journal is None:
                _desktop_journal=DiagnosticJournal(root/f'transactions-desktop-{os.getpid()}.jsonl')
            journal=_desktop_journal
        else:
            if _journal is None:
                _journal=DiagnosticJournal(root/f'transactions-{os.getpid()}.jsonl')
            journal=_journal
    return journal.submit(event)
