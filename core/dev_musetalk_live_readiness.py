"""Read-only source helpers shared by phone delivery and the offline observer.

Observe one new first speech chunk, then encode private timing artifacts offline.
No chat submission, replay, runtime patch, or server restart is performed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
import zlib
import uuid
from core.diagnostics.plan_trace import PlanTrace, current_operation

_read_diagnostics = PlanTrace()

from core.dev_musetalk_segments import encode_range, segment_ranges
from core.phone_media_tools import tools


def complete_png(body):
    if not body.startswith(b'\x89PNG\r\n\x1a\n'):
        return False
    offset, kinds = 8, []
    while offset + 12 <= len(body):
        size = struct.unpack_from('>I', body, offset)[0]
        end = offset + 12 + size
        if end > len(body):
            return False
        kind = body[offset+4:offset+8]
        if zlib.crc32(body[offset+4:end-4]) != struct.unpack_from('>I', body, end-4)[0]:
            return False
        kinds.append(kind)
        if kind == b'IEND':
            return end == len(body) and size == 0 and kinds[0] == b'IHDR' and b'IDAT' in kinds
        offset = end
    return False


def signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


class FrameObserver:
    def __init__(self, root, count):
        if type(count) is not int or not 1 <= count <= 720:
            raise ValueError('Invalid frame count')
        self.root, self.count = Path(root).resolve(), count
        self.times, self.signatures = [], []

    def poll(self, at):
        while len(self.times) < self.count:
            path = self.root / f'{len(self.times):08d}.png'
            try:
                path.resolve(strict=True).relative_to(self.root)
                before = signature(path)
                if not 0 < before[0] <= 8*1024*1024:
                    return
                body = path.read_bytes()
                if signature(path) != before or not complete_png(body):
                    return
            except (OSError, ValueError):
                return
            self.signatures.append(before)
            self.times.append(at)

    def unchanged(self):
        try:
            return all(signature(self.root/f'{index:08d}.png') == sig
                       for index, sig in enumerate(self.signatures))
        except OSError:
            return False


def wav_identity(body):
    try:
        with wave.open(io.BytesIO(body)) as audio:
            frames = audio.getnframes()
            duration = frames / audio.getframerate()
            if not 0 < duration <= 30 or len(audio.readframes(frames)) != frames*audio.getnchannels()*audio.getsampwidth():
                raise ValueError('Incomplete or oversized audio')
    except (EOFError, wave.Error) as exc:
        raise ValueError('Invalid audio') from exc
    return hashlib.sha256(body).hexdigest(), duration


def readiness_rows(times, size, audio_at):
    return [{'startFrame': start, 'frameCount': count,
             'sourceReadyAfterAudioMs': round(1000*(times[start+count-1]-audio_at), 3),
             'sourceSlackWithOneSecondMs': round(1000*(audio_at+1+start/24-times[start+count-1]), 3)}
            for start, count in segment_ranges(len(times), size)]


class BridgeReader:
    def __init__(self, runtime):
        self.info_path = runtime/'runtime/main_chat_remote/bridge_info.json'
        self.info = json.loads(self.info_path.read_text(encoding='utf-8'))
        url = urllib.parse.urlsplit(self.info['url'])
        if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username:
            raise ValueError('Expected local bridge')
        self.base = self.info['url'].rstrip('/')

    def get(self, path):
        current = json.loads(self.info_path.read_text(encoding='utf-8'))
        if any(current.get(key) != self.info.get(key) for key in ('url', 'token')):
            raise RuntimeError('Bridge identity changed')
        if path not in ('/api/state', '/api/audio') and not path.startswith('/api/audio/file/'):
            raise ValueError('Read-only endpoint not allowed')
        if urllib.parse.urlsplit(path).netloc or '..' in path:
            raise ValueError('Invalid endpoint')
        active=current_operation()
        trace_id=active['trace_id'] if active else uuid.uuid4().hex
        with _read_diagnostics.operation(trace_id,'backend.bridge.read') as link:
            headers={'X-NC-Bridge-Token':self.info['token'],'X-NC-Diagnostic-Trace':trace_id,
                     'X-NC-Diagnostic-Operation':link['operation_id']}
            if link['event_id']:headers['X-NC-Diagnostic-Event']=link['event_id']
            request=urllib.request.Request(self.base+path,headers=headers,method='GET')
            with urllib.request.urlopen(request, timeout=2) as response:
                body = response.read(16*1024*1024+1)
            _read_diagnostics.observe(trace_id,'backend.bridge.read','response_bytes',None,len(body))
        if len(body) > 16*1024*1024:
            raise ValueError('Response exceeded cap')
        return body

    def audio(self):
        return json.loads(self.get('/api/audio'))['audio'].get('items', [])






