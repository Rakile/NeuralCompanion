"""Session-local Orb intent, evidence and delivery state (no IO or Qt)."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import json
import threading

from .watch_conditions import evaluate_condition


@dataclass(frozen=True)
class WatchIntent:
    operation: str
    mode: str = ''
    subject: str = ''
    instruction: str = ''
    question: str = ''


@dataclass(frozen=True)
class WatchEpoch:
    session_key: str
    revision: int


@dataclass(frozen=True)
class WatchReceipt:
    epoch: WatchEpoch
    status: str
    message: str


class OrbWatchState:
    def __init__(self):
        self._lock = threading.RLock()
        self._session = ''
        self._revision = 0
        self._task = {}
        self._receipts = OrderedDict()
        self._observation = {}
        self._latest_check = {}
        self._timestamp = -1.0
        self._event_number = 0
        self._event = {}
        self._delivered = ''
        self._available = False
        self._watches = OrderedDict()
        self._batch_receipts = {}
        self._tool_receipts = {}
        self._next_watch = 0
        self._collection_mode = False

    def _epoch(self):
        return WatchEpoch(self._session, self._revision)

    def sync_session(self, session_key: str) -> None:
        with self._lock:
            if self._session != session_key:
                self._session = session_key
                self.clear('conversation_changed')
                self._receipts.clear()
                self._batch_receipts.clear()
                self._tool_receipts.clear()

    def clear(self, reason: str) -> None:
        with self._lock:
            self._revision += 1
            self._task = {}
            self._observation = {}
            self._latest_check = {}
            self._timestamp = -1.0
            self._event = {}
            self._available = False
            self._delivered = ''
            self._watches.clear()

    def apply_batch(self, batch, *, session_key, turn_key, expected_collection_revision):
        """Validate against the initial collection, then commit all or none."""
        with self._lock:
            def receipt(status, message='', **changes):
                return dict(status=status, message=message, collection_revision=self._revision,
                    snapshot=self.snapshot(), **changes)
            if not session_key or session_key != self._session or not turn_key:
                return receipt('stale', 'The originating conversation changed.')
            if turn_key in self._batch_receipts:
                return deepcopy(self._batch_receipts[turn_key])
            if expected_collection_revision != self._revision:
                return receipt('stale', 'The watch collection changed during interpretation.')
            status = batch.get('status')
            if status in {'no_change', 'clarify'}:
                result = receipt(status, batch.get('question', ''))
            elif status != 'apply' or not isinstance(batch.get('operations'), list) or not batch['operations']:
                return receipt('rejected', 'Invalid watch operation batch.')
            else:
                staged = deepcopy(self._watches)
                added, updated, removed, touched = [], [], [], set()
                counter = self._next_watch
                try:
                    for op in batch['operations']:
                        kind, identity = op['operation'], op['watch_id']
                        revision = op['expected_revision']
                        if kind == 'remove_all':
                            if len(batch['operations']) != 1 or identity or revision or op['spec']:
                                raise ValueError('Conflicting remove-all operation.')
                            removed = list(staged)
                            staged.clear()
                            continue
                        if kind in {'update', 'remove'}:
                            if (identity in touched or identity not in self._watches or
                                    type(revision) is not int or self._watches[identity]['revision'] != revision):
                                raise ValueError('Unknown, conflicting or stale watch target.')
                            touched.add(identity)
                        elif kind != 'add' or identity or revision:
                            raise ValueError('Invalid watch operation.')
                        if kind == 'remove':
                            if op['spec']:
                                raise ValueError('Removal cannot carry a replacement instruction.')
                            del staged[identity]
                            removed.append(identity)
                            continue
                        value = op['spec']
                        from .watch_intent import validate_watch_spec
                        validate_watch_spec(value)
                        if kind == 'add':
                            counter += 1
                            identity, revision = f'watch-{counter}', 0
                            added.append(identity)
                        else:
                            updated.append(identity)
                        staged[identity] = dict(id=identity, revision=revision + 1,
                            spec=deepcopy(value), origin_turn=turn_key, status='watching',
                            latest_check={}, baseline={}, pending_event={}, last_sequence=-1,
                            last_captured_at=-1.0)
                except (KeyError, TypeError, ValueError) as exc:
                    return receipt('rejected', str(exc))
                self._watches = staged
                self._next_watch = counter
                self._collection_mode = True
                self._task = {}
                self._revision += 1
                result = receipt('applied', 'Watch changes committed.', added=added, updated=updated, removed=removed)
            self._batch_receipts[turn_key] = deepcopy(result)
            return result

    def apply_tool(self, name: str, arguments: dict, *, session_key: str, turn_key: str,
                   call_id: str, expected_collection_revision: int, original_request: str) -> dict:
        """Apply a conversational proposal through the same atomic state owner.

        Call identity protects against retries; collection revision protects
        against edits/cancellation while inference was running.
        """
        from .watch_tools import tool_operations
        with self._lock:
            def failed(message):
                return dict(ok=False, receipt=message, collection=self.snapshot(), watch_ids=[])
            if (not session_key or session_key != self._session or not isinstance(turn_key, str)
                    or not turn_key or not isinstance(call_id, str) or not call_id):
                return failed('No watch changes: the originating turn is unavailable.')
            key = (turn_key, call_id)
            try:
                signature = json.dumps([name, arguments, original_request], sort_keys=True, allow_nan=False)
            except (TypeError, ValueError):
                return failed('No watch changes: invalid arguments.')
            cached = self._tool_receipts.get(key)
            if cached:
                if cached['signature'] != signature:
                    return failed('No watch changes: conflicting repeated tool call.')
                if cached['revision'] != self._revision:
                    return failed('No watch changes: the collection changed after that action.')
                return deepcopy(cached['result'])
            if type(expected_collection_revision) is not int or expected_collection_revision != self._revision:
                return failed('No watch changes: the collection changed while this request was running.')
            if name == 'stop_watch':
                # A model can repeat a completed stop with a fresh protocol ID.
                # Acknowledge only this turn's proven result at this exact revision;
                # an unknown ID, later turn or edited collection is still rejected.
                prior = next((value for identity, value in self._tool_receipts.items()
                    if identity[0] == turn_key and value['signature'] == signature
                    and value['revision'] == self._revision and value['result']['ok']), None)
                if prior:
                    result = deepcopy(prior['result'])
                    result['receipt'] = f"Already stopped watch(s): {', '.join(result['watch_ids'])}."
                    self._tool_receipts[key] = dict(signature=signature, revision=self._revision, result=deepcopy(result))
                    return result
            try:
                operations, existing_ids = tool_operations(name, arguments, list(self._watches.values()), original_request)
            except (TypeError, ValueError) as exc:
                result = failed(f'No watch changes: {exc}')
            else:
                if operations:
                    # Tuple identity cannot collide with the legacy string turn key.
                    batch = self.apply_batch(dict(status='apply', question='', operations=operations),
                        session_key=session_key, turn_key=('tool', turn_key, call_id),
                        expected_collection_revision=expected_collection_revision)
                    if batch['status'] != 'applied':
                        result = failed(f"No watch changes: {batch['message']}")
                    else:
                        ids = existing_ids + batch['added'] + batch['updated'] + batch['removed']
                        verb = 'Stopped' if name == 'stop_watch' else 'Updated' if name == 'update_watch' else 'Registered'
                        result = dict(ok=True, receipt=f"{verb} watch(s): {', '.join(ids)}.",
                            collection=self.snapshot(), watch_ids=ids)
                else:
                    result = dict(ok=True, receipt=f"Already watching: {', '.join(existing_ids)}.",
                        collection=self.snapshot(), watch_ids=existing_ids)
            self._tool_receipts[key] = dict(signature=signature, revision=self._revision, result=deepcopy(result))
            return result

    def remove_watch(self, watch_id, expected_revision, *, session_key):
        with self._lock:
            row = self._watches.get(watch_id)
            if (session_key != self._session or not row or type(expected_revision) is not int or
                    row['revision'] != expected_revision):
                return False
            del self._watches[watch_id]
            self._revision += 1
            return True

    def apply(self, intent: WatchIntent, *, session_key: str, turn_key: str) -> WatchReceipt:
        with self._lock:
            if not session_key or self._session != session_key or not turn_key:
                return WatchReceipt(self._epoch(), 'stale', 'The originating conversation changed.')
            if turn_key in self._receipts:
                return self._receipts[turn_key]
            status, message = 'unchanged', ''
            if intent.operation == 'start_or_replace':
                if intent.mode not in {'visual_commentary', 'title_change'} or not intent.subject or not intent.instruction:
                    raise ValueError('Invalid Orb watch task.')
                self.clear('replaced')
                self._task = dict(mode=intent.mode, subject=intent.subject,
                    instruction=intent.instruction, origin_turn=turn_key)
                status, message = 'registered', 'The Orb watch is registered for this conversation.'
            elif intent.operation == 'cancel':
                self.clear('cancelled')
                status = 'cancelled'
                message = 'The watch is cancelled. Previously configured general Orb rules still apply.'
            elif intent.operation == 'clarify':
                status, message = 'clarify', intent.question
            elif intent.operation != 'no_change':
                raise ValueError('Unsupported Orb watch operation.')
            receipt = WatchReceipt(self._epoch(), status, message)
            self._receipts[turn_key] = receipt
            while len(self._receipts) > 512:
                self._receipts.popitem(last=False)
            return receipt

    def snapshot(self) -> dict:
        with self._lock:
            if self._collection_mode:
                return deepcopy(dict(schema_version=2, session_key=self._session,
                    collection_revision=self._revision,
                    active=any(w['status'] in {'watching', 'matched_pending'} for w in self._watches.values()),
                    watches=list(self._watches.values())))
            return deepcopy(dict(active=bool(self._task), **asdict(self._epoch()), **self._task,
                collection_revision=self._revision, watches=[],
                latest_check=self._latest_check,
                previous_observation=self._observation, event=self._event,
                eligible=bool(self._available and self._event and self._event['event_id'] != self._delivered)))

    def is_current(self, epoch: WatchEpoch) -> bool:
        with self._lock:
            return epoch == self._epoch()

    def observe(self, epoch: WatchEpoch, observation: dict, *, capture=None) -> dict:
        with self._lock:
            denied = {'eligible': False, 'reason': 'stale', 'event_id': ''}
            if epoch != self._epoch() or not self._task:
                return denied
            stamp = observation.get('captured_at')
            if not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp <= self._timestamp:
                return denied
            self._timestamp = stamp
            # UI evidence includes unknown checks; the comparison baseline stays confirmed-only.
            self._latest_check = deepcopy(dict(observation, capture=capture or {}))
            title = ' '.join(str(observation.get('title') or '').split())
            summary = ' '.join(str(observation.get('summary') or '').split())
            self._available = bool(observation.get('available') is True and
                observation.get('subject_confirmed') is True and
                (title if self._task['mode'] == 'title_change' else summary))
            if not self._available:
                return dict(denied, reason='unknown')
            previous = self._observation
            self._observation = deepcopy(dict(observation, title=title, summary=summary))
            title_mode = self._task['mode'] == 'title_change'
            old_value = str(previous.get('title' if title_mode else 'summary') or '')
            new_value = title if title_mode else summary
            changed = old_value != new_value
            due = bool(old_value and changed) if title_mode else bool(
                changed and (not previous or observation.get('meaningful_change') is True))
            if changed:
                self._event = {}
            if due:
                self._event_number += 1
                self._event = dict(event_id=f'{self._revision}:{self._event_number}',
                    previous_title=str(previous.get('title') or ''), title=title,
                    summary=summary, observation_id=str(observation.get('observation_id') or ''))
            eligible = bool(self._event and self._event['event_id'] != self._delivered)
            return deepcopy(dict(reason='changed' if eligible else 'unchanged', eligible=eligible,
                event_id='', **self._event)) if not self._event else deepcopy(
                dict(reason='changed' if eligible else 'unchanged', eligible=eligible, **self._event))

    def observe_batch(self, session_key, capture, results):
        with self._lock:
            if session_key != self._session:
                return self.pending_bundle()
            sequence, stamp = capture.get('sequence'), capture.get('captured_at')
            if (type(sequence) is not int or not isinstance(stamp, (float, int)) or
                    not math.isfinite(stamp)):
                return self.pending_bundle()
            for check in results:
                row = self._watches.get(check.get('watch_id'))
                if (not row or row['revision'] != check.get('revision') or row['status'] != 'watching' or
                        sequence <= row['last_sequence'] or stamp <= row['last_captured_at']):
                    continue
                row['last_sequence'], row['last_captured_at'] = sequence, stamp
                evidence = deepcopy(dict(check, captured_at=stamp, local_date=capture.get('local_date', ''), capture=capture))
                decision = evaluate_condition(row['spec'], row['baseline'], evidence)
                if decision['event_kind'] == 'title_change':
                    evidence['previous_title'] = row['baseline'].get('title', '')
                elif decision['event_kind'] == 'value_change':
                    evidence['previous_value'] = row['baseline'].get('value', '')
                row['latest_check'] = dict(evidence, decision=decision['reason'], available=decision['available'])
                row['baseline'] = decision['baseline']
                if decision['event_kind']:
                    self._event_number += 1
                    row['pending_event'] = dict(watch_id=row['id'], revision=row['revision'],
                        event_id=f'event-{self._event_number}', kind=decision['event_kind'],
                        spec=deepcopy(row['spec']), evidence=evidence, capture=deepcopy(capture))
                    if decision['event_kind'] in {'clock_match', 'clock_missed'} or row['spec'].get('once') is True:
                        row['status'] = 'matched_pending'
                elif not decision['available']:
                    # Recurring commentary is not spoken from stale/unreadable evidence.
                    row['pending_event'] = {}
            return self.pending_bundle()

    def pending_bundle(self):
        with self._lock:
            events = [w['pending_event'] for w in self._watches.values() if w['pending_event']]
            return deepcopy(dict(schema_version=2, session_key=self._session,
                active=bool(events), eligible=bool(events), events=events))

    def publish_tool_reply(self, session_key, revision, publish):
        """Commit prepared output atomically against manual watch edits."""
        with self._lock:
            if self._session != session_key or self._revision != revision:
                return None
            return publish()

    def publish_reply(self, bundle, publish):
        """Linearize visible publication and acknowledgement against mutations.

        The callback only commits prepared text; it must not perform inference or
        wait for speech/UI. All cancellation/replacement paths use this same lock.
        """
        from core.orb_watch_contract import watch_bundle_is_current
        with self._lock:
            if not watch_bundle_is_current(bundle,self.snapshot()):
                return None
            result=publish()
            if result is not None and result.accepted and result.value is not None:
                self.mark_delivered(dict(bundle))
            return result

    def mark_delivered(self, epoch, event_id=None) -> bool:
        with self._lock:
            if isinstance(epoch, dict):
                events = epoch.get('events', [])
                if epoch.get('session_key') != self._session or not events:
                    return False
                seen = set()
                for event in events:
                    row = self._watches.get(event.get('watch_id'))
                    if (not row or row['id'] in seen or row['revision'] != event.get('revision') or
                            not row['pending_event'] or row['pending_event']['event_id'] != event.get('event_id')):
                        return False
                    seen.add(row['id'])
                for event in events:
                    row = self._watches[event['watch_id']]
                    kind = row['pending_event']['kind']
                    row['pending_event'] = {}
                    row['status'] = ('missed' if kind == 'clock_missed' else 'completed'
                        if kind == 'clock_match' or row['spec'].get('once') is True else 'watching')
                return True
            if (epoch != self._epoch() or not event_id or not self._available or
                    self._event.get('event_id') != event_id):
                return False
            self._delivered = event_id
            return True
