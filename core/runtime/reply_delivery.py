"""Ephemeral reply routing, independent of persisted input metadata."""
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ReplyDelivery:
    destination: Literal['local', 'phone'] = 'local'
    phone_request_id: str | None = None
    shared_queue: bool = False

    def __post_init__(self):
        if type(self.shared_queue) is not bool:
            raise ValueError('Invalid shared queue negotiation')
        if self.destination == 'local':
            if self.phone_request_id is not None or self.shared_queue:
                raise ValueError('Local delivery cannot hold phone authority')
        elif self.destination == 'phone':
            value = self.phone_request_id
            if (type(value) is not str or not 1 <= len(value) <= 96
                    or any(not (c.isascii() and (c.isalnum() or c in '_-')) for c in value)):
                raise ValueError('Phone delivery requires an admitted reply identity')
        else:
            raise ValueError('Unknown reply destination')


def apply_reply_delivery(context: Mapping[str, object], delivery: ReplyDelivery) -> dict[str, object]:
    result = dict(context)
    for key in ('remote_capture_id', 'phone_reply_control', 'phone_shared_queue'):
        result.pop(key, None)
    if delivery.destination == 'phone':
        result.update(remote_capture_id=delivery.phone_request_id,
                      phone_reply_control=True, phone_shared_queue=delivery.shared_queue)
    return result
