"""Exact-capability recovery; no native reader acknowledgements are inferred."""
import hashlib
import re
import threading
from dataclasses import dataclass


def _hex(value, length):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{%d}' % length, value):
        raise ValueError('ordered_recovery_shape')
    return value


def capability_digest(value):
    return hashlib.sha256(_hex(value, 64).encode('ascii')).digest()


def open_capability(value):
    if value is None: return None
    if type(value) is not dict or set(value) != {'version','capability'} or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('ordered_recovery_shape')
    return capability_digest(value['capability'])


@dataclass(frozen=True, repr=False)
class RecoveryIntent:
    operation: str
    previous: str
    stream: str
    previous_digest: bytes
    digest: bytes

    def result(self, state):
        return dict(version=1,state=state,operationId=self.operation,streamId=self.stream,generation=0)


def parse_recovery(stream, value):
    fields = {'version','operationId','previousStreamId','previousCapability','capability'}
    if type(value) is not dict or set(value) != fields or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('ordered_recovery_shape')
    intent = RecoveryIntent(_hex(value['operationId'],32),_hex(value['previousStreamId'],32),
                            _hex(stream,32),capability_digest(value['previousCapability']),capability_digest(value['capability']))
    if intent.previous == intent.stream: raise ValueError('ordered_recovery_shape')
    return intent


@dataclass(frozen=True, repr=False)
class ReattachIntent:
    stream: str
    generation: int
    operation: str
    epoch: int
    digest: bytes
    after: int

    def result(self):
        return dict(version=1, state='reattached', streamId=self.stream,
            generation=self.generation, operationId=self.operation, recoveryEpoch=self.epoch)


def parse_reattach(stream, generation, value):
    fields = {'version', 'operationId', 'recoveryEpoch', 'capability', 'afterOrdinal'}
    def integer(v, low=0): return type(v) is int and low <= v <= (1 << 53)-1
    if (type(value) is not dict or set(value) != fields
            or type(value['version']) is not int or value['version'] != 1
            or not integer(generation) or not integer(value['recoveryEpoch'], 1)
            or not integer(value['afterOrdinal'], -1)):
        raise ValueError('ordered_reattach_shape')
    return ReattachIntent(_hex(stream, 32), generation, _hex(value['operationId'], 32),
        value['recoveryEpoch'], capability_digest(value['capability']), value['afterOrdinal'])


@dataclass(repr=False)
class _Recovery:
    intent: RecoveryIntent
    previous: object
    replies: tuple
    ready: bool = False
    admitted: bool = False


class OrderedRecoveryRegistry:
    """Serializes recovery work separately from controller/encoder locks."""
    def __init__(self):
        self.lock = threading.RLock()
        self.operations = {}
        self.committing = None

    def check_open(self, stream):
        # Called under the controller lock, which also protects record changes.
        if any(not r.admitted for r in self.operations.values()) and self.committing != stream:
            raise ValueError('ordered_recovery_pending')

    def dispatch(self, controller, method, payload):
        if set(payload) != {'auth','streamId','recovery'}: raise ValueError('ordered_recovery_shape')
        intent = parse_recovery(payload['streamId'],payload['recovery'])
        # Authentication may renew; proof never grants ordinary playback rights.
        controller._phone_reply.authenticate(payload['auth'])
        with self.lock:
            with controller._ordered_output_lock:
                current = controller._ordered_output
                record = self.operations.get(intent.operation)
                if record is not None:
                    if record.intent != intent: raise ValueError('ordered_recovery_conflict')
                    if record.admitted:
                        if current is None or current.stream_id != intent.stream:
                            raise ValueError('ordered_recovery_stale')
                        # Historical admission is still provable after close;
                        # closed is evidence for journaling, never playback permission.
                        return intent.result('recovered' if current.active else 'closed')
                    if current is not record.previous: raise ValueError('ordered_recovery_stale')
                else:
                    if method != 'recover-prepare': raise ValueError('ordered_recovery_not_prepared')
                    if current is None or current.stream_id != intent.previous: raise ValueError('ordered_recovery_stale')
                    current.verify_recovery(intent.previous_digest)
                    if any(not r.admitted for r in self.operations.values()): raise ValueError('ordered_recovery_conflict')
                    # Retain the current outcome for lost-response retries, but
                    # completed older operations with no custody need no slot.
                    self.operations = {key:r for key,r in self.operations.items()
                        if r.intent.stream == current.stream_id or not r.previous.reclaimable}
                    controller._retired_ordered_outputs = {key:value for key,value in controller._retired_ordered_outputs.items()
                        if not value.reclaimable}
                    if len(self.operations) >= 64 or len(controller._retired_ordered_outputs) >= 64:
                        raise ValueError('ordered_recovery_retention_capacity')
                    record = _Recovery(intent,current,current.recovery_replies())
                    self.operations[intent.operation] = record
                    current.retire('disconnect')
            # Runtime callbacks and futures never run under the admission lock.
            if not record.ready:
                for reply_id in record.replies:
                    controller._phone_reply.stop_for_recovery(record.previous.owner_epoch,reply_id,intent.operation,
                                                             wait_for_stop=False)
                record.ready = True
            if method == 'recover-prepare': return intent.result('prepared')
            with controller._ordered_output_lock:
                if controller._ordered_output is not record.previous: raise ValueError('ordered_recovery_stale')
                # Ordinary open shares all existing binding setup/capability gates.
                self.committing = intent.stream
                try:
                    controller.remote_ordered_output('open',dict(auth=payload['auth'],streamId=intent.stream,
                        recovery=dict(version=1,capability=payload['recovery']['capability'])))
                finally: self.committing = None
                record.admitted = True
                return intent.result('recovered')
