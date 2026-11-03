"""Bounded RGB slots shared by the isolated Ditto worker and its NC host."""
from collections import deque
from multiprocessing import shared_memory
import os
import threading
import time

TRANSPORT = 'shared_rgb'


class _WindowsFrameMapping:
    """Attach one read-only view without older Python's leaking size probe."""
    def __init__(self, name, size):
        import _winapi
        import mmap
        # mmap can create a missing named section. Hold an existing handle until
        # attachment completes, including if the producer closes concurrently.
        handle = _winapi.OpenFileMapping(_winapi.FILE_MAP_READ, False, name)
        try:
            self.buf = mmap.mmap(-1, size, tagname=name, access=mmap.ACCESS_READ)
        finally:
            _winapi.CloseHandle(handle)
        self.size = len(self.buf)

    def close(self):
        self.buf.close()


def delivery_timing(count, span, buffer_wait):
    """Delivery includes upstream stalls; removing pool wait is not GPU profiling."""
    active_span = span-buffer_wait
    return dict(output_fps=(count-1)/span if span > 0 and count > 1 else 0.,
                output_buffer_wait_seconds=max(0., buffer_wait),
                delivery_fps_excluding_buffer_wait=(count-1)/active_span if active_span > 0 and count > 1 else 0.)


class FramePool:
    def __init__(self, width, height, session_id, budget_bytes=None):
        if budget_bytes is None:
            budget_bytes = width*height*3
        if any(type(v) is not int or v <= 0 for v in (width, height, budget_bytes)):
            raise ValueError('Invalid RGB pool dimensions or budget.')
        self.width, self.height, self.session_id = width, height, str(session_id)
        self.frame_bytes = width*height*3
        self.capacity = budget_bytes//self.frame_bytes
        if not self.capacity or not self.session_id:
            raise ValueError('RGB frame does not fit the memory budget.')
        self.memory = shared_memory.SharedMemory(create=True, size=self.capacity*self.frame_bytes)
        self.condition = threading.Condition()
        self.free = deque(range(self.capacity))
        self.generations = [0]*self.capacity
        self.busy = set()
        self.stopped = self.closed = False
        self.wait_seconds = self.copy_seconds = 0.
        self.high_water = 0
        self.produced = 0

    @property
    def descriptor(self):
        return dict(frame_transport=TRANSPORT, version=1, name=self.memory.name,
                    session_id=self.session_id, width=self.width, height=self.height,
                    capacity=self.capacity, size=self.capacity*self.frame_bytes)

    @property
    def occupied(self):
        with self.condition:
            return len(self.busy)

    def publish(self, pixels, chunk_id, index):
        if len(pixels) != self.frame_bytes or type(index) is not int or index < 0:
            raise ValueError('Invalid RGB frame bytes or index.')
        with self.condition:
            before = time.perf_counter()
            while not self.free and not self.stopped:
                self.condition.wait()
            self.wait_seconds += time.perf_counter()-before
            if self.stopped:
                raise RuntimeError('Frame pool stopped.')
            slot = self.free.popleft()
            self.generations[slot] += 1
            generation = self.generations[slot]
            self.busy.add(slot)
            self.high_water = max(self.high_water, len(self.busy))
            before = time.perf_counter()
            offset = slot*self.frame_bytes
            self.memory.buf[offset:offset+self.frame_bytes] = pixels
            self.copy_seconds += time.perf_counter()-before
            self.produced += 1
        return dict(frame_transport=TRANSPORT, session_id=self.session_id,
                    chunk_id=chunk_id, index=index, slot=slot, generation=generation)

    def release(self, slot, generation):
        with self.condition:
            if (type(slot) is not int or type(generation) is not int
                    or slot not in self.busy or self.generations[slot] != generation):
                return False
            self.busy.remove(slot)
            self.free.append(slot)
            self.condition.notify()
            return True

    def stop(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()

    def close(self):
        self.stop()
        if not self.closed:
            self.closed = True
            self.memory.close()
            self.memory.unlink()


def memory_availability():
    """Current physical and commit availability; queried only on reservation."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class Status(ctypes.Structure):
            _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD),
                *[(name, ctypes.c_ulonglong) for name in ('total_phys', 'avail_phys',
                  'total_commit', 'avail_commit', 'total_virtual', 'avail_virtual', 'extended')]]
        status = Status(); status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError()
        return int(status.avail_phys), int(status.avail_commit)
    import sys
    try:
        with open('/proc/meminfo', encoding='ascii') as stream:
            for line in stream:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1])*1024, sys.maxsize
    except FileNotFoundError:
        pass
    return int(os.sysconf('SC_AVPHYS_PAGES'))*int(os.sysconf('SC_PAGE_SIZE')), sys.maxsize


class ChunkFramePools:
    """Own chunk-sized shared mappings against actual system availability."""
    def __init__(self, width, height, session_id, *, available_memory=None):
        self.width, self.height, self.session_id = width, height, session_id
        self.bootstrap = FramePool(width, height, session_id)
        self.pools = {}
        self.bootstrap_chunk_id = None
        self.completed = set()
        self.retired = set()
        self.lock = threading.RLock()
        self.available_memory = available_memory or memory_availability
        self.stopped = self.closed = False
        self.occupied = self.high_water = 0
        self.capacity = self.bootstrap.capacity
        self._retired_wait = self._retired_copy = 0.

    @property
    def descriptor(self):
        return self.bootstrap.descriptor

    @property
    def wait_seconds(self):
        with self.lock:
            return self._retired_wait + self.bootstrap.wait_seconds + sum(p.wait_seconds for p in self.pools.values())

    @property
    def copy_seconds(self):
        with self.lock:
            return self._retired_copy + self.bootstrap.copy_seconds + sum(p.copy_seconds for p in self.pools.values())

    def reserve(self, chunk_id, count):
        if not isinstance(chunk_id, str) or not chunk_id or type(count) is not int or count < 1:
            raise ValueError('Invalid chunk RAM reservation.')
        with self.lock:
            if self.stopped:
                raise RuntimeError('Frame pools stopped.')
            if chunk_id in self.retired:
                raise ValueError('Chunk RAM reservation already retired.')
            if chunk_id in self.pools:
                pool = self.pools[chunk_id]
                if pool.capacity != count:
                    raise ValueError('Chunk RAM reservation changed size.')
                return {'frame_pool':pool.descriptor}
            physical, commit = self.available_memory()
            # A shared mapping reserves commit immediately, but untouched pixel
            # pages can still appear physically free. Do not promise them twice.
            unwritten = sum(p.frame_bytes*max(0, p.capacity-p.produced)
                            for p in (self.bootstrap, *self.pools.values()))
            available = max(0, min(physical-unwritten, commit))
            required = self.width*self.height*3*count
            if required > available:
                return dict(backpressure=True, memory_wait=True,
                            required_bytes=required, available_bytes=available)
            try:
                pool = FramePool(self.width, self.height, self.session_id, required)
            except OSError as error:
                if error.errno != 12 and getattr(error, 'winerror', None) not in (8, 14, 1455):
                    raise
                return dict(backpressure=True, memory_wait=True,
                            required_bytes=required, available_bytes=available)
            self.pools[chunk_id] = pool
            self.capacity = max(self.capacity, self.bootstrap.capacity + sum(p.capacity for p in self.pools.values()))
            return {'frame_pool':pool.descriptor}

    def publish(self, pixels, chunk_id, index):
        with self.lock:
            if self.stopped or chunk_id in self.retired:
                raise RuntimeError('Frame pool is no longer current.')
            pool = self.pools.get(chunk_id)
            if pool is None:
                if self.bootstrap_chunk_id not in (None, chunk_id):
                    raise ValueError('Chunk has no RAM reservation.')
                self.bootstrap_chunk_id = chunk_id
                pool = self.bootstrap
        event = pool.publish(pixels, chunk_id, index)
        with self.lock:
            self.occupied += 1
            self.high_water = max(self.high_water, self.occupied)
        return event

    def _retire(self, chunk_id, pool):
        self._retired_wait += pool.wait_seconds
        self._retired_copy += pool.copy_seconds
        pool.close()
        self.pools.pop(chunk_id)
        self.completed.discard(chunk_id)
        self.retired.add(chunk_id)

    def release(self, slot, generation, chunk_id=None):
        with self.lock:
            if self.closed or chunk_id in self.retired:
                return False
            if chunk_id not in self.pools and chunk_id not in (None, self.bootstrap_chunk_id):
                return False
            pool = self.pools.get(chunk_id, self.bootstrap)
            released = pool.release(slot, generation)
            if released:
                self.occupied -= 1
                if chunk_id in self.completed and pool.occupied == 0:
                    self._retire(chunk_id, pool)
            return released

    def mark_complete(self, chunk_id):
        with self.lock:
            pool = self.pools.get(chunk_id)
            if pool is not None:
                self.completed.add(chunk_id)
                if pool.occupied == 0:
                    self._retire(chunk_id, pool)

    def stop(self):
        with self.lock:
            self.stopped = True
            pools = (self.bootstrap, *self.pools.values())
        for pool in pools:
            pool.stop()

    def close(self):
        self.stop()
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for chunk_id, pool in list(self.pools.items()):
                self._retire(chunk_id, pool)
            self.bootstrap.close()
            self.occupied = 0


class FrameBuffer:
    """Retain descriptors, never copy queued pixels into an unbounded host list."""
    def __init__(self, descriptor, chunk_id, release_callback):
        if descriptor.get('frame_transport') != TRANSPORT or descriptor.get('version') != 1:
            raise ValueError('Unsupported RGB pool protocol.')
        self.width, self.height, self.capacity = (descriptor.get(k) for k in ('width', 'height', 'capacity'))
        if any(type(v) is not int or v <= 0 for v in (self.width, self.height, self.capacity)):
            raise ValueError('Invalid RGB pool geometry.')
        self.frame_bytes = self.width*self.height*3
        size = self.frame_bytes*self.capacity
        if type(descriptor.get('size')) is not int or descriptor['size'] != size:
            raise ValueError('Invalid RGB pool size.')
        name = descriptor.get('name')
        if not isinstance(name, str) or not name or '\0' in name or (os.name == 'nt' and not name.isascii()):
            # Older Windows mmap uses ANSI names, whereas OpenFileMapping uses
            # Unicode. Generated pool names are ASCII; reject ambiguous names.
            raise ValueError('Invalid RGB pool name.')
        session_id = descriptor.get('session_id')
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('Invalid RGB pool session.')
        self.memory = (_WindowsFrameMapping(name, size) if os.name == 'nt'
                       else shared_memory.SharedMemory(name=name))
        if self.memory.size < size:
            self.memory.close()
            raise ValueError('RGB mapping is too small.')
        self.session_id, self.chunk_id = session_id, chunk_id
        self.release_callback = release_callback
        self.frames = {}
        self.retired = 0
        self.closed = False
        self.lock = threading.RLock()

    def append(self, event):
        with self.lock:
            index, slot, generation = (event.get(k) for k in ('index', 'slot', 'generation'))
            if (self.closed or event.get('frame_transport') != TRANSPORT
                    or event.get('session_id') != self.session_id or event.get('chunk_id') != self.chunk_id
                    or type(index) is not int or index < self.retired or index in self.frames
                    or type(slot) is not int or not 0 <= slot < self.capacity
                    or type(generation) is not int or generation < 1
                    or any(value['slot'] == slot for value in self.frames.values())):
                raise ValueError('Stale, duplicate, or invalid RGB frame descriptor.')
            self.frames[index] = dict(event)

    @property
    def available_count(self):
        with self.lock:
            end = self.retired
            while end in self.frames:
                end += 1
            return end-self.retired

    def read(self, index):
        with self.lock:
            event = self.frames.get(index)
            if self.closed or event is None:
                return None
            offset = event['slot']*self.frame_bytes
            return bytes(self.memory.buf[offset:offset+self.frame_bytes])

    def retire_before(self, index):
        with self.lock:
            released = [self.frames.pop(i) for i in list(self.frames) if i < index]
            self.retired = max(self.retired, index)
        for event in released:
            self.release_callback(event)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            released = list(self.frames.values())
            self.frames.clear()
            self.memory.close()
        for event in released:
            self.release_callback(event)
