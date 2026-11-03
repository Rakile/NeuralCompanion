"""Peer-owned compressed speech files. All methods run on a media worker.

Uses the existing authenticated retained WAV source; never changes TTS or
contacts signaling. File availability is not an audio playback acknowledgement.
"""
import json
from pathlib import Path
import re
import tempfile
import threading
import uuid

import av

from .opus_files import encode_opus_file
from .speech_source import load_speech, load_audio_file, retained_audio_file, _authorize


class BufferedMediaService:
    def __init__(self, forward, bitrate):
        self.forward, self.bitrate = forward, bitrate
        self.lock = threading.Lock()
        self.ended = threading.Event()
        self.directory = tempfile.TemporaryDirectory(prefix='nc-buffered-speech-')
        self.entries, self.identities = {}, {}
        self.bytes = 0

    def _check(self):
        if self.ended.is_set():
            raise ValueError('Buffered media peer ended')

    def prepare(self, body):
        if not isinstance(body, dict) or set(body) != {'auth', 'request_id', 'chunk_id', 'sequence_index', 'format'}:
            raise ValueError('Invalid buffered speech request')
        return self._prepare(body, replay=False)

    def prepare_replay(self, body):
        if not isinstance(body, dict) or set(body) != {'chunk_id', 'format'}:
            raise ValueError('Invalid buffered replay request')
        return self._prepare(body, replay=True)

    def _prepare(self, body, *, replay):
        if body['format'] != 'ogg-opus':
            raise ValueError('Unsupported buffered speech format')
        # A detached copy is essential: caller mutation cannot change retained
        # authorization or permit a different owner to reuse these bytes.
        identity = json.dumps(body, sort_keys=True, separators=(',', ':'))
        if len(identity) > 8192:
            raise ValueError('Buffered speech identity limit')
        body = json.loads(identity)
        with self.lock:
            self._check()
            old = self.identities.get(identity)
            if old:
                self._authorize(self.entries[old][0])
                return dict(self.entries[old][1])
            if len(self.entries) >= 96 or self.bytes >= 192*1024*1024:
                raise ValueError('Buffered speech capacity reached')
            source = (load_audio_file(self.forward, body['chunk_id'], cancelled=self.ended.is_set) if replay else
                      load_speech(self.forward, body['auth'], body['request_id'], body['chunk_id'],
                                  body['sequence_index'], cancelled=self.ended.is_set))
            token = uuid.uuid4().hex
            path = Path(self.directory.name) / (token+'.ogg')

            def frames():
                for offset in range(0, len(source.pcm), 1920):
                    self._check()
                    pcm = source.pcm[offset:offset+1920]
                    frame = av.AudioFrame(format='s16', layout='mono', samples=len(pcm)//2)
                    frame.sample_rate = 48000
                    frame.planes[0].update(pcm)
                    yield frame

            try:
                result = encode_opus_file(frames(), path, bitrate=self.bitrate(), container='ogg',
                                          cancelled=self.ended.is_set)
                self._check()
                self._authorize(body)
                if result['bytes'] > 16*1024*1024 or self.bytes+result['bytes'] > 192*1024*1024:
                    raise ValueError('Buffered speech capacity reached')
                descriptor = {'id': token, 'path': '/api/buffered/audio/'+token+'.ogg',
                              'bytes': result['bytes'], 'contentType': 'audio/ogg',
                              'sample_rate': 48000, 'valid_samples': result['valid_samples'], 'format': 'ogg-opus'}
                self.entries[token] = (body, descriptor, path)
                self.identities[identity] = token
                self.bytes += result['bytes']
                return dict(descriptor)
            except BaseException:
                path.unlink(missing_ok=True)
                raise

    def _authorize(self, body):
        self._check()
        if 'auth' in body:
            _authorize(self.forward, body['auth'], body['request_id'], body['chunk_id'], body['sequence_index'])
        else:
            # Explicit Replay has no old reply capability. Revalidate the same
            # authenticated bridge file read; peer closure revokes this service.
            retained_audio_file(self.forward, body['chunk_id'], cancelled=self.ended.is_set)
        self._check()

    def read(self, route):
        match = re.fullmatch(r'/api/buffered/audio/([a-f0-9]{32})\.ogg', route)
        with self.lock:
            self._check()
            entry = self.entries.get(match[1]) if match else None
            if not entry:
                raise ValueError('Buffered speech unavailable')
            self._authorize(entry[0])
            data = entry[2].read_bytes()
            self._check()
            return data

    def release(self, body):
        """Reclaim this peer's encoded copy, never stop/acknowledge TTS."""
        if (not isinstance(body, dict) or set(body) != {'id'}
                or not isinstance(body['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', body['id'])):
            raise ValueError('Invalid buffered release')
        with self.lock:
            self._check()
            entry = self.entries.get(body['id'])
            if entry is None:
                return False
            # read() holds the same lock until its bytes have been copied.
            # The transport owns those bytes independently of this disk file.
            entry[2].unlink(missing_ok=True)
            del self.entries[body['id']]
            identity = json.dumps(entry[0], sort_keys=True, separators=(',', ':'))
            self.identities.pop(identity, None)
            self.bytes -= entry[1]['bytes']
            return True

    def stop(self):
        self.ended.set()  # Nonblocking cancellation, safe on the network loop.

    def close(self):
        self.stop()
        with self.lock:
            self.entries.clear(); self.identities.clear()
            self.directory.cleanup()
