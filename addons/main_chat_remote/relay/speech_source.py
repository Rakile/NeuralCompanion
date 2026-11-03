"""Read only an existing, authenticated reply's retained WAV on a media worker.

The callback is the peer's existing local BridgeClient forwarding boundary, NOT
a relay/signaling API. There is deliberately no user-supplied URL or file path.
"""
from dataclasses import dataclass
import io
import json
import re

import av

from .media_clock import MAX_PCM_BYTES


@dataclass(frozen=True)
class SpeechSource:
    pcm: bytes
    total_samples: int
    offset_samples: int


def _check(cancelled):
    if cancelled():
        raise ValueError('Speech source lifetime ended')


def _authorize(forward, auth, request_id, chunk_id, sequence_index):
    status, data, ctype = forward({
        'method': 'POST', 'path': '/api/phone-reply/status',
        'body': {'auth': auth, 'phone_request_id': request_id,
                 'continuation': {'version': 1, 'cursor': sequence_index, 'completed_sequence_index': -1}},
    })
    if status != 200 or 'json' not in ctype or len(data) > 256 * 1024:
        raise ValueError('Speech owner unavailable')
    try:
        result = json.loads(data)['result']
        page = result['continuation']
        item = page['items'][0]
        valid = (result['phone_request_id'] == request_id
                 and result['phase'] in {'pending', 'generating', 'complete'}
                 and result.get('playback_stop_requested', False) is False
                 and page['version'] == 1 and page['available'] is True
                 and 0 < page['remaining_seconds'] <= 900
                 and item['phone_request_id'] == request_id and item['id'] == chunk_id
                 and type(item['sequence_index']) is int and item['sequence_index'] == sequence_index
                 and item['url_path'] == f'/api/audio/file/{chunk_id}')
    except (KeyError, IndexError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError('Speech owner or retained media unavailable')


def load_speech(forward, auth, request_id, chunk_id, sequence_index, *, offset_samples=0, cancelled=lambda: False):
    """Synchronous bounded network/decode work; caller must use a worker thread."""
    _check(cancelled)
    if (not isinstance(auth, dict) or auth.get('reply_continuation_version') != 1
            or not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', request_id)
            or not isinstance(chunk_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', chunk_id)
            or '..' in chunk_id
            or type(sequence_index) is not int or not 0 <= sequence_index < 2048
            or type(offset_samples) is not int or offset_samples < 0):
        raise ValueError('Invalid speech source identity')
    _authorize(forward, auth, request_id, chunk_id, sequence_index)
    _check(cancelled)
    source = load_audio_file(forward, chunk_id, offset_samples=offset_samples, cancelled=cancelled)
    _authorize(forward, auth, request_id, chunk_id, sequence_index)
    _check(cancelled)
    return source


def retained_audio_file(forward, chunk_id, *, cancelled=lambda: False):
    """The existing authenticated file-read permission, not reply permission."""
    _check(cancelled)
    if (not isinstance(chunk_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', chunk_id)
            or '..' in chunk_id):
        raise ValueError('Invalid retained audio identity')
    status, data, _ = forward({'method': 'GET', 'path': f'/api/audio/file/{chunk_id}'})
    _check(cancelled)
    if status != 200 or not 12 <= len(data) <= 64 * 1024 * 1024 or data[:4] not in (b'RIFF', b'RF64') or data[8:12] != b'WAVE':
        raise ValueError('Retained speech is not a supported bounded WAV')
    return data


def load_audio_file(forward, chunk_id, *, offset_samples=0, cancelled=lambda: False):
    """Worker-only decode shared by automatic replies and explicit Replay."""
    if type(offset_samples) is not int or offset_samples < 0:
        raise ValueError('Invalid retained audio offset')
    data = retained_audio_file(forward, chunk_id, cancelled=cancelled)
    pcm = bytearray()
    try:
        # Explicit WAV demuxing prevents a fetched playlist from opening URLs.
        with av.open(io.BytesIO(data), format='wav') as container:
            if len(container.streams.audio) != 1:
                raise ValueError('Speech WAV requires exactly one audio stream')
            resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)

            def append(frames):
                for frame in frames:
                    _check(cancelled)
                    size = frame.samples * 2
                    if len(pcm) + size > min(MAX_PCM_BYTES, 600 * 48000 * 2):
                        raise ValueError('Decoded speech exceeds playback limit')
                    pcm.extend(bytes(frame.planes[0])[:size])

            for frame in container.decode(audio=0):
                _check(cancelled)
                append(resampler.resample(frame))
            append(resampler.resample(None))
    except av.FFmpegError:
        raise ValueError('Retained speech WAV cannot be decoded') from None
    samples = len(pcm) // 2
    if offset_samples >= samples:
        raise ValueError('Speech resume offset is outside retained audio')
    _check(cancelled)
    return SpeechSource(bytes(pcm[offset_samples * 2:]), samples, offset_samples)
