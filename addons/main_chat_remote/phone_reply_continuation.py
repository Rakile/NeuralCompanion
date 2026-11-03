"""Bounded, memory-only pins for negotiated phone reply media.

Authentication belongs to the protocol. This owner never calls the registry or
runtime while holding its lock. The bridge drains released items for deletion.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
import threading


REPLY_BYTES = 64 * 1024 * 1024
TOTAL_BYTES = 192 * 1024 * 1024
LEASE_SECONDS = 900
MAX_CHUNKS = 2048


@dataclass
class _Pin:
    deadline: float
    items: list = field(default_factory=list)
    byte_length: int = 0
    completed: int = -1
    sizes: dict = field(default_factory=dict)


class ReplyMediaRetention:
    def __init__(self, clock):
        self._clock = clock
        self._lock = threading.RLock()
        self._pins = {}
        self._closed = OrderedDict()
        self._released = []
        self._expired = []

    @staticmethod
    def _request(request_id):
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            raise ValueError("Invalid reply ID")

    def _close(self, request_id, reason):
        pin = self._pins.pop(request_id, None)
        if pin is not None:
            self._released.extend(pin.items)
        self._closed[request_id] = reason
        while len(self._closed) > 256:
            self._closed.popitem(last=False)

    def _expire(self):
        for request_id, pin in tuple(self._pins.items()):
            if self._clock() >= pin.deadline:
                self._close(request_id, "expired")
                self._expired.append(request_id)

    def reserve(self, request_id):
        self._request(request_id)
        with self._lock:
            self._expire()
            if request_id in self._closed:
                return False
            if request_id in self._pins:
                return True
            if len(self._pins) * REPLY_BYTES >= TOTAL_BYTES:
                self._close(request_id, "capacity")
                return False
            self._pins[request_id] = _Pin(self._clock() + LEASE_SECONDS)
            return True

    def publish(self, request_id, item, byte_length):
        self._request(request_id)
        if type(byte_length) is not int or byte_length < 0:
            raise ValueError("Invalid media size")
        with self._lock:
            self._expire()
            pin = self._pins.get(request_id)
            if pin is None:
                return False
            sequence = item.get("sequence_index")
            if (type(sequence) is not int or sequence < 0 or sequence >= MAX_CHUNKS
                    or item.get("phone_request_id") != request_id or not item.get("id")):
                raise ValueError("Invalid media identity")
            if sequence < len(pin.items):
                if pin.items[sequence] != item:
                    raise ValueError("Conflicting media sequence")
                return True
            if sequence != len(pin.items):
                raise ValueError("Missing media sequence")
            if pin.byte_length + byte_length > REPLY_BYTES:
                self._close(request_id, "capacity")
                return False
            pin.items.append(dict(item))
            pin.byte_length += byte_length
            pin.sizes[sequence] = byte_length
            return True

    def replace_item(self, request_id, item, byte_length):
        """Promote a negotiated PCM prefix to its exact completed recording."""
        self._request(request_id)
        if type(byte_length) is not int or byte_length < 0:
            raise ValueError('Invalid media size')
        with self._lock:
            self._expire()
            pin = self._pins.get(request_id)
            sequence = item.get('sequence_index')
            if pin is None or type(sequence) is not int or not 0 <= sequence < len(pin.items):
                return False
            old = pin.items[sequence]
            if (old.get('id') != item.get('id') or item.get('phone_request_id') != request_id
                    or 'progressive_audio' not in old):
                raise ValueError('Conflicting media promotion')
            total = pin.byte_length - pin.sizes[sequence] + byte_length
            if total > REPLY_BYTES:
                self._close(request_id, 'capacity')
                return False
            pin.items[sequence] = dict(item)
            pin.sizes[sequence] = byte_length
            pin.byte_length = total
            return True

    def progress(self, request_id, completed_sequence):
        self._request(request_id)
        if type(completed_sequence) is not int or not -1 <= completed_sequence < MAX_CHUNKS:
            raise ValueError("Invalid completed sequence")
        with self._lock:
            self._expire()
            pin = self._pins.get(request_id)
            if pin is None:
                return
            if completed_sequence >= len(pin.items):
                raise ValueError("Unpublished completed sequence")
            if completed_sequence > pin.completed:
                pin.completed = completed_sequence
                pin.deadline = self._clock() + LEASE_SECONDS

    def page(self, request_id, cursor):
        self._request(request_id)
        if type(cursor) is not int or not 0 <= cursor <= MAX_CHUNKS:
            raise ValueError("Invalid continuation cursor")
        with self._lock:
            self._expire()
            pin = self._pins.get(request_id)
            if pin is not None and any(not Path(i["_file_path"]).is_file()
                                       for i in pin.items[max(pin.completed + 1, cursor):cursor + 64]):
                self._close(request_id, "media_missing")
                pin = None
            if pin is None:
                return {"version": 1, "available": False,
                        "reason": self._closed.get(request_id, "expired"),
                        "items": [], "next_cursor": None, "remaining_seconds": 0}
            return {"version": 1, "available": True,
                    "items": [{k: v for k, v in i.items() if not k.startswith("_")}
                              for i in pin.items[cursor:cursor + 64]],
                    "next_cursor": cursor + 64 if len(pin.items) > cursor + 64 else None,
                    # Same-tick renewal can round just above the wire limit.
                    "remaining_seconds": min(LEASE_SECONDS, max(0, pin.deadline - self._clock()))}

    def find_item(self, audio_id):
        with self._lock:
            for pin in self._pins.values():
                for item in pin.items:
                    if item["id"] == audio_id:
                        return dict(item)
        return None

    def release(self, request_id):
        self._request(request_id)
        with self._lock:
            self._close(request_id, "expired")

    def owns(self, request_id):
        with self._lock:
            return request_id in self._pins

    @property
    def maintenance_needed(self):
        with self._lock:
            return bool(self._pins or self._expired or self._released)

    def release_all(self):
        with self._lock:
            for request_id in tuple(self._pins):
                self._close(request_id, "expired")

    def maintain(self):
        with self._lock:
            self._expire()
            expired, self._expired = tuple(self._expired), []
            return expired

    def drain_released(self):
        with self._lock:
            items, self._released = self._released, []
            return items
