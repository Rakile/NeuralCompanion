"""Content-free process counters. Never stores paths, peer IDs or credentials.

One writer per fixed source file. Reset uses a desktop-side baseline and never
mutates a connection or its counters. Payload and observed WebRTC transport
extra are distinct; these are not carrier/IP/TURN billing measurements.
"""
import json
import os
import threading
import time
from pathlib import Path

KINDS = ('audio', 'video', 'other', 'transport_extra')
SOURCES = ('internet', 'lan-media', 'lan-http')


def empty():
    return {k: {'sent': 0, 'received': 0} for k in KINDS}


def read(path):
    result = empty()
    try:
        raw = json.loads(path.read_text('utf-8'))
        for kind in KINDS:
            for direction in result[kind]:
                value = raw[kind][direction]
                if type(value) is int and value >= 0:
                    result[kind][direction] = value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


class TrafficTotals:
    def __init__(self, root, source, *, background=True):
        if source not in SOURCES:
            raise ValueError('Invalid traffic source')
        self.path = Path(root)/('traffic-'+source+'.json')
        self.values = read(self.path)
        self.lock = threading.Lock()
        self.dirty = False
        if background:
            threading.Thread(target=self._writer, name='nc-traffic-counters', daemon=True).start()

    def add(self, kind, direction, count):
        if kind not in KINDS or direction not in ('sent', 'received') or type(count) is not int or count < 0:
            return
        with self.lock:
            self.values[kind][direction] += count
            self.dirty = True

    def flush(self):
        with self.lock:
            if self.dirty:
                write(self.path, self.values)
                self.dirty = False

    def _writer(self):
        while True:
            time.sleep(2)
            try:
                self.flush()
            except OSError:
                pass  # Optional counters must never interrupt media.


def traffic_kind(path):
    path = str(path).split('?')[0]
    if path == '/api/stt' or path.startswith(('/api/audio/file/', '/api/buffered/audio/')):
        return 'audio'
    if path.startswith(('/api/dev/musetalk-live/segment/', '/api/dev/musetalk-live/idle/',
                        '/api/dev/musetalk-live/anticipation/', '/api/musetalk/frame/', '/api/idle-cache/file/')):
        return 'video'
    return 'other'


class TrafficDashboard:
    def __init__(self, root):
        self.root = Path(root)
        self.baseline = read(self.root/'traffic-reset.json')
        self.previous = None
        self.at = None
        self.rates = empty()

    def _totals(self):
        result = empty()
        for source in SOURCES:
            value = read(self.root/('traffic-'+source+'.json'))
            for kind in KINDS:
                for direction in result[kind]:
                    result[kind][direction] += value[kind][direction]
        return result

    def reset(self):
        self.baseline = self._totals()
        self.previous = self.baseline
        self.rates = empty()
        write(self.root/'traffic-reset.json', self.baseline)

    def snapshot(self, *, now=None):
        now = time.monotonic() if now is None else now
        totals = self._totals()
        result = empty()
        elapsed = now-self.at if self.at is not None else 0
        # The panel can refresh much faster than the worker's 2-second flush.
        # Keep a stable sampling window instead of dividing a flush by one UI tick.
        sample = self.previous is None or elapsed >= 2
        for kind in KINDS:
            for direction in ('sent', 'received'):
                result[kind][direction] = max(0, totals[kind][direction]-self.baseline[kind][direction])
                if sample:
                    self.rates[kind][direction] = (max(0, totals[kind][direction]-self.previous[kind][direction])/elapsed
                                                   if self.previous is not None and elapsed > 0 else 0)
                result[kind][direction+'_rate'] = self.rates[kind][direction]
        if sample:
            self.previous, self.at = totals, now
        return result
