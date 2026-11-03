"""Private, bounded ownership lease for phone-rendered presentation."""
from __future__ import annotations

import threading
import time
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from addons.main_chat_remote.phone_reply_receipts import PhoneReplyRejected
from core.diagnostics.plan_trace import PlanTrace

_plan_diagnostics = PlanTrace()


_LEASE_SECONDS = 10.0
_TOMBSTONE_SECONDS = 15.0 * 60.0
_MAX_CLIENTS = 32
_MAX_SEQUENCE = (1 << 53) - 1
_POSITION_FRESH_SECONDS = 0.75
_MEDIA_ID = re.compile(r"[0-9a-f]{32}\Z")
_POSITION_KEYS = {
    "avatarId", "mediaId", "sourceFrameCount", "sourceFrame", "fps", "playing",
}
_MISSING = object()


@dataclass(slots=True)
class _Lease:
    sequence: int
    active: bool
    expires_at: float = 0.0
    retained_until: float = 0.0
    position: dict[str, object] | None = None
    position_at: float = 0.0
    handoff: bool = False


class PhonePresentationLedger:
    """Track authenticated phone presentation ownership without side effects."""

    def __init__(self, protocol, *, clock=time.monotonic,
                 logger: Callable[[bool], object] | None = None) -> None:
        self._protocol = protocol
        self._clock = clock
        self._logger = logger
        self._lock = threading.RLock()
        self._leases: dict[str, _Lease] = {}
        self._closed = False
        self._reported = False
        self._handoff: dict | None = None
        self._handoff_seen = deque(maxlen=32)

    @staticmethod
    def _valid_sequence(value: object) -> bool:
        return type(value) is int and 0 <= value <= _MAX_SEQUENCE

    def _now(self) -> float:
        return float(self._clock())

    @staticmethod
    def _validated_position(value: object) -> dict[str, object]:
        if not isinstance(value, dict) or set(value) not in (_POSITION_KEYS, _POSITION_KEYS | {'handoffRange'}):
            raise PhoneReplyRejected("invalid_request")
        avatar_id = value["avatarId"]
        media_id = value["mediaId"]
        source_frame_count = value["sourceFrameCount"]
        source_frame = value["sourceFrame"]
        if (
            not isinstance(avatar_id, str) or not 1 <= len(avatar_id) <= 256
            or not isinstance(media_id, str) or _MEDIA_ID.fullmatch(media_id) is None
            or type(source_frame_count) is not int or not 1 <= source_frame_count <= 1440
            or type(source_frame) is not int or not 0 <= source_frame < source_frame_count
            or value["fps"] != 24 or type(value["fps"]) is not int
            or type(value["playing"]) is not bool
        ):
            raise PhoneReplyRejected("invalid_request")
        result = dict(value)
        if 'handoffRange' in value:
            bounds = value['handoffRange']
            if (not isinstance(bounds, dict) or set(bounds) != {'startFrame', 'endFrame'}
                    or any(type(i) is not int or not 0 <= i < source_frame_count for i in bounds.values())):
                raise PhoneReplyRejected('invalid_request')
            span = (bounds['endFrame']-bounds['startFrame']) % source_frame_count
            if not 2 <= span <= 720 or span % 2:
                raise PhoneReplyRejected('invalid_request')
            result['handoffRange'] = dict(bounds)
        return result

    def _maintain_locked(self, now: float) -> bool:
        for epoch, lease in tuple(self._leases.items()):
            if lease.active and now >= lease.expires_at:
                lease.active = False
            if now >= lease.retained_until:
                del self._leases[epoch]
        request = self._handoff
        if request:
            active = [(epoch, lease) for epoch, lease in self._leases.items() if lease.active]
            if (len(active) != 1 or active[0][0] != request['epoch'] or now >= request['expires']
                    or not active[0][1].handoff or not self._matches(active[0][1].position, request)):
                if len(active) != 1:
                    reason = 'no_active_owner' if not active else 'multiple_active_owners'
                elif active[0][0] != request['epoch']:
                    reason = 'owner_changed'
                elif now >= request['expires']:
                    reason = 'request_expired'
                elif not active[0][1].handoff:
                    reason = 'capability_withdrawn'
                else:
                    reason = 'position_changed'
                self._observe(request['id'], 'backend.presentation.lifecycle', 'removal_reason', reason)
                self._observe(request['id'], 'backend.presentation.lifecycle', 'active_owner_count', len(active))
                self._observe(request['id'], 'backend.presentation.lifecycle', 'request_expired', now >= request['expires'])
                if len(active) == 1:
                    position = active[0][1].position
                    for key in ('avatarId', 'mediaId', 'sourceFrameCount'):
                        self._observe(request['id'], 'backend.presentation.lifecycle',
                                      'position_match.' + key, position is not None and position.get(key) == request[key])
                    self._observe(request['id'], 'backend.presentation.lifecycle', 'position_playing',
                                  position is not None and position.get('playing') is True)
                self._handoff = None
        return any(lease.active for lease in self._leases.values())

    @staticmethod
    def _observe(trace_id, site, condition, actual):
        try:
            _plan_diagnostics.observe(trace_id, site, condition, None, actual)
        except Exception:
            pass  # Diagnostic failure must not change ledger authority.

    @staticmethod
    def _matches(position, request):
        return (position is not None and position.get('playing') is True
                and all(position.get(k) == request[k] for k in ('avatarId','mediaId','sourceFrameCount')))

    def request_handoff(self, value):
        """Local planner poll; never waits or performs network/UI work here."""
        if (not isinstance(value, dict) or set(value) not in
                ({'id','avatarId','sourceFrameCount'}, {'id','avatarId','sourceFrameCount','cancel'})
                or not isinstance(value['id'], str) or _MEDIA_ID.fullmatch(value['id']) is None
                or not isinstance(value['avatarId'], str) or not 1 <= len(value['avatarId']) <= 256
                or type(value['sourceFrameCount']) is not int or not 3 <= value['sourceFrameCount'] <= 1440
                or ('cancel' in value and value['cancel'] is not True)):
            raise ValueError('Invalid handoff request')
        now = self._now()
        with self._lock:
            owned = False if self._closed else self._maintain_locked(now)
            result = {'phone_owns_presentation': owned}
            def observe(condition, expected, actual):
                _plan_diagnostics.observe(value['id'], 'backend.presentation.handoff', condition, expected, actual)
            observe('ledger_open', True, not self._closed)
            current = self._handoff
            if value.get('cancel'):
                observe('cancel_matches', True, bool(current and current['id'] == value['id']))
                if current and current['id'] == value['id']:
                    self._observe(current['id'], 'backend.presentation.lifecycle', 'removal_reason', 'explicit_cancel')
                    self._handoff = None
                return result
            active = [(epoch, lease) for epoch, lease in self._leases.items() if lease.active]
            observe('single_owner', True, owned and len(active) == 1)
            if not owned or len(active) != 1: return result
            epoch, lease = active[0]
            position = lease.position
            observe('handoff_capability', True, lease.handoff)
            observe('position_present', True, position is not None)
            if position is not None:
                observe('avatar_matches', True, position['avatarId'] == value['avatarId'])
                observe('frame_count_matches', True, position['sourceFrameCount'] == value['sourceFrameCount'])
                observe('position_playing', True, position['playing'])
            if (not lease.handoff or position is None
                    or position['avatarId'] != value['avatarId'] or position['sourceFrameCount'] != value['sourceFrameCount']
                    or not position['playing']): return result
            if (current is None or current['id'] != value['id']) and value['id'] in self._handoff_seen:
                observe('request_retired', False, True)
                return result
            observe('position_age_seconds', None, now-lease.position_at)
            observe('position_fresh', True, now-lease.position_at <= _POSITION_FRESH_SECONDS)
            if now-lease.position_at > _POSITION_FRESH_SECONDS:
                # A delayed heartbeat is not a rejected agreement. Keep the
                # planner's bounded poll alive, but never expose stale position
                # as confirmation or extend/create a request from that sample.
                return {**result, 'handoffPending': True}
            if current is None or current['id'] != value['id']:
                if current is not None:
                    self._observe(current['id'], 'backend.presentation.lifecycle', 'removal_reason', 'request_replaced')
                self._handoff_seen.append(value['id'])
                current = {**value, 'mediaId':position['mediaId'], 'epoch':epoch, 'expires':now+4, 'bounds':None}
                self._handoff = current
                self._observe(current['id'], 'backend.presentation.lifecycle', 'request_created', True)
            observe('request_matches', True, all(current[k] == value[k] for k in ('id','avatarId','sourceFrameCount')))
            if any(current[k] != value[k] for k in ('id','avatarId','sourceFrameCount')): return result
            observe('bounds_present', None, current['bounds'] is not None)
            if current['bounds'] is None: return {**result,'handoffPending':True}
            return {**result, 'position':{k:v for k,v in position.items() if k != 'handoffRange'} | {'ageSeconds':max(0,now-lease.position_at)},
                    'handoffRange':dict(current['bounds']), 'handoffId':current['id']}

    def _report(self, active: bool) -> None:
        with self._lock:
            if self._reported == active:
                return
            self._reported = active
        if self._logger is not None:
            try:
                self._logger(active)
            except BaseException:
                pass

    def update(self, auth, *, active: object, sequence: object,
               position: object = _MISSING, handoff: object = None) -> dict:
        if type(active) is not bool or not self._valid_sequence(sequence):
            raise PhoneReplyRejected("invalid_request")
        validated_position = (
            self._validated_position(position) if position is not _MISSING else None
        )
        declaration = None
        if handoff is not None:
            if (not isinstance(handoff, dict) or set(handoff) not in ({'version'},{'version','declaration'})
                    or type(handoff['version']) is not int or handoff['version'] != 1):
                raise PhoneReplyRejected('invalid_request')
            declaration = handoff.get('declaration')
            if declaration is not None:
                if (not isinstance(declaration, dict) or set(declaration) != {'id','startFrame','endFrame'}
                        or not isinstance(declaration['id'], str) or _MEDIA_ID.fullmatch(declaration['id']) is None
                        or validated_position is None): raise PhoneReplyRejected('invalid_request')
                self._validated_position({**validated_position,'handoffRange':{k:declaration[k] for k in ('startFrame','endFrame')}})
        epoch = self._protocol.authenticate(auth)
        now = self._now()
        with self._lock:
            if self._closed:
                raise PhoneReplyRejected("unavailable")
            # Bind this update to the request it can invalidate, before maintenance.
            trace_id = self._handoff['id'] if self._handoff else _plan_diagnostics.emitter.producer_id
            def observe(condition, actual):
                self._observe(trace_id, 'backend.presentation.update', condition, actual)
            observe('incoming_sequence', sequence)
            observe('incoming_active', active)
            observe('incoming_position', position is not _MISSING)
            observe('incoming_handoff', handoff is not None)
            observe('incoming_declaration', declaration is not None)
            owned = self._maintain_locked(now)
            lease = self._leases.get(epoch)
            if lease is None:
                if len(self._leases) >= _MAX_CLIENTS:
                    raise PhoneReplyRejected("capacity")
                lease = _Lease(-1, False, retained_until=now + _TOMBSTONE_SECONDS)
                self._leases[epoch] = lease
            observe('previous_sequence', lease.sequence)
            observe('previous_handoff', lease.handoff)
            observe('sequence_accepted', sequence > lease.sequence)
            if sequence > lease.sequence:
                request = self._handoff
                observe('request_present', request is not None)
                if declaration is not None:
                    observe('declaration_request_matches', bool(request and request['id'] == declaration['id']))
                    observe('declaration_owner_matches', bool(request and request['epoch'] == epoch))
                    observe('declaration_position_matches', bool(request and self._matches(validated_position, request)))
                if (request and declaration and request['epoch'] == epoch and request['id'] == declaration['id']
                        and active and self._matches(validated_position,request)):
                    bounds = {k:declaration[k] for k in ('startFrame','endFrame')}
                    observe('bounds_conflict', request['bounds'] is not None and request['bounds'] != bounds)
                    if request['bounds'] is not None and request['bounds'] != bounds:
                        raise PhoneReplyRejected('invalid_request')
                    request['bounds'] = bounds
                    request['expires'] = now+30
                    observe('bounds_installed', True)
                lease.sequence = sequence
                lease.active = active
                lease.expires_at = now + _LEASE_SECONDS if active else 0.0
                lease.retained_until = now + _TOMBSTONE_SECONDS
                lease.position = validated_position if active else None
                lease.position_at = now if active and validated_position is not None else 0.0
                lease.handoff = handoff is not None
            observe('result_handoff', lease.handoff)
            owned = self._maintain_locked(now)
            response = {"phone_owns_presentation": owned}
            request = self._handoff
            if request and request['epoch'] == epoch and active:
                response['handoff'] = {k:request[k] for k in ('id','avatarId','mediaId','sourceFrameCount')}
                response['handoff'].update(version=1,state='confirmed' if request['bounds'] is not None else 'requested')
                if request['bounds'] is not None: response['handoff'].update(request['bounds'])
            observe('response_handoff_present', 'handoff' in response)
            observe('response_handoff_state', response.get('handoff', {}).get('state', 'absent'))
        self._report(owned)
        return response

    def snapshot(self) -> dict[str, object]:
        now = self._now()
        with self._lock:
            owned = False if self._closed else self._maintain_locked(now)
            active = [lease for lease in self._leases.values() if lease.active]
            diagnostic_id = _plan_diagnostics.emitter.producer_id
            def observe(condition, expected, actual):
                _plan_diagnostics.observe(diagnostic_id, 'backend.presentation.snapshot', condition, expected, actual)
            observe('ledger_open', None, not self._closed)
            observe('active_owners', 1 if active else None, len(active))
            observe('position_present', True if active else None, len(active) == 1 and active[0].position is not None)
            result: dict[str, object] = {"phone_owns_presentation": owned}
            if len(active) == 1 and active[0].position is not None:
                if active[0].handoff: result['handoffRequestVersion'] = 1
                age = max(0.0, now - active[0].position_at)
                observe('position_age_seconds', None, age)
                observe('position_fresh', True, age <= _POSITION_FRESH_SECONDS)
                if age <= _POSITION_FRESH_SECONDS:
                    position = dict(active[0].position)
                    bounds = position.pop('handoffRange', None)
                    result["position"] = {**position, "ageSeconds": age}
                    if bounds is not None:
                        result['handoffRange'] = dict(bounds)
        self._report(owned)
        return result

    def close(self) -> None:
        with self._lock:
            if self._handoff is not None:
                self._observe(self._handoff['id'], 'backend.presentation.lifecycle', 'removal_reason', 'ledger_closed')
            self._closed = True
            self._leases.clear()
            self._handoff = None
            self._handoff_seen.clear()
        self._report(False)
