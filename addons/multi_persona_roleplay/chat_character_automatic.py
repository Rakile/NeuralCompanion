"""One supervised coordinator over the existing durable voice and portrait jobs."""
from __future__ import annotations

import logging
import threading
import time
import uuid

from .chat_characters import CharacterRevisionConflict

log = logging.getLogger(__name__)


class AutomaticCharacterWorker:
    def __init__(self, store, conversation_id, spawn, propose, prepare, lookup, finish, cancel=None):
        self.store, self.conversation_id, self.spawn = store, conversation_id, spawn
        self.propose, self.prepare, self.lookup, self.finish = propose, prepare, lookup, finish
        self.cancel = cancel
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._running = False
        self._requested = False

    def close(self):
        self._stop.set()

    def kick(self):
        with self._lock:
            if self._stop.is_set():
                return
            self._requested = True
            if self._running:
                return
            self._running = True
        try:
            self.spawn('chat-character-automatic', self._run)
        except Exception:
            with self._lock:
                self._running = False
            log.warning('Could not start automatic character worker')

    def retry(self, identity: str, revision: int, operation_id: str = ''):
        # Admission and receipt are one transaction. A lost HTTP acknowledgement
        # must not turn a second tap into another paid retry after a fast failure.
        with self.store._lock:
            card = self.store.get(identity)
            if operation_id and operation_id in card.automation.get('retry_receipts', []):
                return card
            card = self.store.automatic_current(identity, card.automation.get('id', ''))
            if card.revision != revision:
                raise CharacterRevisionConflict('Character changed. Refresh before retrying.')
            if card.automation.get('status') != 'failed':
                raise ValueError('Only a confirmed failed stage can be retried. Check uncertain provider outcomes first.')
            receipts = list(card.automation.get('retry_receipts', []))
            if operation_id:
                receipts.append(operation_id)
            patch = {'status': 'queued', 'error': '', 'retry_receipts': receipts}
            for kind in ('voice', 'portrait'):
                if card.automation.get(kind + '_status') == 'failed':
                    patch.update({kind + '_status': 'queued', kind + '_operation': '', kind + '_job': ''})
            result = self.store.automatic_progress(identity, card.automation['id'], **patch)
        self.kick()
        return result

    def _check(self, identity, operation):
        card = self.store.automatic_current(identity, operation)
        if self._stop.is_set() or card.conversation_id != self.conversation_id():
            raise CharacterRevisionConflict('Conversation changed. Automatic assignment cancelled.')
        return card

    def _run(self, *_args):
        try:
            while not self._stop.is_set():
                with self._lock:
                    self._requested = False
                cards = self.store.snapshot().characters
                for card in cards:
                    if card.automation.get('status') in {'queued', 'running'}:
                        self._process(card.id, card.automation['id'])
                with self._lock:
                    if not self._requested:
                        return
        finally:
            with self._lock:
                self._running = False
                again = self._requested
            if again and not self._stop.is_set():
                self.kick()

    def _stage(self, identity, operation, kind):
        card = self._check(identity, operation)
        state = card.automation
        if state.get(kind + '_status') in {'ready', 'failed', 'unknown', 'cancelled'}:
            return
        job_operation = state.get(kind + '_operation')
        if job_operation:
            job = self.lookup(kind, job_operation)
            if not job:
                self.store.automatic_progress(identity, operation,
                    **{kind + '_status': 'unknown', 'error': 'Provider submission could not be confirmed. Check before remaking.'})
                return
        else:
            job_operation = 'auto-' + uuid.uuid4().hex
            self.store.automatic_progress(identity, operation,
                **{kind + '_operation': job_operation, kind + '_status': 'submitting'})
            card = self._check(identity, operation)
            try:
                job = self.prepare(kind, card, job_operation)
            except ValueError as exc:
                # Adapter validation occurs before provider submission. Job-level
                # uncertain HTTP outcomes are handled by CharacterJobs itself.
                self.store.automatic_progress(identity, operation,
                    **{kind + '_status': 'failed', 'error': str(exc)[:240]})
                return
        self.store.automatic_progress(identity, operation, **{kind + '_job': job['id']})
        deadline = time.monotonic() + 900
        while job['status'] in {'queued', 'running'}:
            self._check(identity, operation)
            if time.monotonic() >= deadline:
                self.store.automatic_progress(identity, operation,
                    **{kind + '_status': 'unknown', 'error': 'Generation has not confirmed completion. Check the provider before remaking.'})
                return
            if self._stop.wait(.5):
                return
            job = self.lookup(kind, job_operation)
            if job is None:
                raise RuntimeError('Generation job disappeared')
        card = self._check(identity, operation)
        self.store.automatic_progress(identity, operation,
            **{kind + '_status': job['status'], 'error': job.get('error', '') or card.automation.get('error', '')})

    def _result(self, card, kind):
        job = self.lookup(kind, card.automation[kind + '_operation'])
        if not job or job['status'] != 'ready':
            raise ValueError('Generated media is no longer available.')
        return self.finish(kind, job, card)

    def _process(self, identity, operation):
        try:
            card = self._check(identity, operation)
            self.store.automatic_progress(identity, operation, status='running')
            if not card.automation.get('enriched'):
                proposal = self.propose(card, card.automation.get('excerpt', ''))
                self._check(identity, operation)
                card = self.store.automatic_enrich(identity, operation, proposal)
            results = {}
            for kind in ('voice', 'portrait'):
                self._stage(identity, operation, kind)
                card = self._check(identity, operation)
                if card.automation.get(kind + '_status') != 'ready':
                    continue
                try:
                    results[kind] = self._result(card, kind)
                except ValueError as exc:
                    self.store.automatic_progress(identity, operation,
                        **{kind + '_status': 'failed', 'error': str(exc)[:240]})
                    continue
                if card.automation.get('mode') == 'create' and not card.automation.get(kind + '_assigned'):
                    self._check(identity, operation)
                    self.store.automatic_commit(identity, operation, **{kind: results[kind]})
                    self.store.automatic_progress(identity, operation, **{kind + '_assigned': True})
            card = self._check(identity, operation)
            statuses = [card.automation.get(k + '_status') for k in ('voice', 'portrait')]
            if statuses == ['ready', 'ready']:
                if card.automation.get('mode') == 'remake':
                    self._check(identity, operation)
                    self.store.automatic_commit(identity, operation, voice=results['voice'], portrait=results['portrait'])
                self.store.automatic_progress(identity, operation, status='ready', error='')
            else:
                status = 'unknown' if 'unknown' in statuses else 'failed'
                self.store.automatic_progress(identity, operation, status=status)
        except (KeyError, CharacterRevisionConflict):
            self._cancel_jobs(identity, operation)
            try:
                self.store.automatic_progress(identity, operation, status='cancelled',
                    error='Setup superseded by a setting, conversation or character change. Current assets kept.')
            except KeyError:
                pass
        except Exception:
            log.warning('Automatic character setup stopped operation=%s', operation)
            try:
                self.store.automatic_progress(identity, operation, status='unknown',
                    error='Setup could not be confirmed. Current assets kept; inspect generation jobs before remaking.')
            except KeyError:
                pass

    def _cancel_jobs(self, identity, operation):
        if self.cancel is None:
            return
        try:
            card = self.store.get(identity)
            if card.automation.get('id') != operation:
                return
            for kind in ('voice', 'portrait'):
                job_operation = card.automation.get(kind + '_operation')
                job = self.lookup(kind, job_operation) if job_operation else None
                if job and job['status'] in {'queued', 'running'}:
                    # Existing job cancellation suppresses queued work/results.
                    # It cannot undo a provider request already in flight.
                    self.cancel(kind, job)
        except Exception:
            log.warning('Automatic child-job cancellation could not be confirmed operation=%s', operation)
