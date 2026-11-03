"""Bounded visual metadata only; never an audio or presentation authority."""
import re
import copy
import math

_FIELDS = {'version', 'motionId', 'sourceFrameCount', 'sourceFps', 'sourceIndices'}
_MAX_INTEGER = (1 << 53) - 1


def validate_anticipation(value):
    """Existing desktop plan, copied without changing its order or boundaries."""
    fields = {'version', 'planId', 'avatarId', 'fps', 'sourceFrameCount', 'sourceIndices',
              'speechEntryFrame', 'exitAfterFrame', 'repeat', 'cursor', 'state', 'mediaId', 'segments'}
    if (not isinstance(value, dict) or set(value) not in (fields, fields | {'syncWaitSeconds'})
            or type(value['version']) is not int or value['version'] != 1
            or type(value['fps']) is not int or value['fps'] != 24
            or any(not isinstance(value[k], str) or not re.fullmatch('[a-f0-9]{32}', value[k])
                   for k in ('planId', 'mediaId'))
            or not isinstance(value['avatarId'], str) or not 0 < len(value['avatarId']) <= 160
            or not _integer(value['sourceFrameCount'], 1, 1440)
            or not isinstance(value['sourceIndices'], list) or not 1 <= len(value['sourceIndices']) <= 1440
            or any(not _integer(i, 0, value['sourceFrameCount']-1) for i in value['sourceIndices'])
            or not _integer(value['speechEntryFrame']) or value['speechEntryFrame'] != value['sourceIndices'][0]
            or not _integer(value['exitAfterFrame']) or value['exitAfterFrame'] != len(value['sourceIndices'])-1
            or value['repeat'] is not True or value['state'] not in {'available', 'active'}
            or value['cursor'] is not None and not _integer(value['cursor'], 0, 10000)):
        raise ValueError('Invalid anticipation plan')
    wait = value.get('syncWaitSeconds', 0)
    if type(wait) not in (int, float) or not math.isfinite(wait) or not 0 <= wait <= 2.5:
        raise ValueError('Invalid anticipation wait')
    rows, count = value['segments'], len(value['sourceIndices'])
    if not isinstance(rows, list) or len(rows) != (count+11)//12:
        raise ValueError('Invalid anticipation segments')
    total_bytes = 0
    for i, row in enumerate(rows):
        base = {'index', 'startFrame', 'frameCount', 'state'}
        if (not isinstance(row, dict) or row.get('state') not in {'pending', 'ready'}
                or set(row) != (base | {'uri','bytes'} if row['state'] == 'ready' else base)
                or type(row['index']) is not int or row['index'] != i
                or type(row['startFrame']) is not int or row['startFrame'] != i*12
                or type(row['frameCount']) is not int or row['frameCount'] != min(12, count-i*12)):
            raise ValueError('Invalid anticipation range')
        if row['state'] == 'ready':
            if (row['uri'] != f"/api/dev/musetalk-live/anticipation/{value['mediaId']}/{i:08d}.mp4"
                    or not _integer(row['bytes'], 1, 16*1024*1024)):
                raise ValueError('Invalid anticipation media')
            total_bytes += row['bytes']
    if total_bytes > 128*1024*1024:
        raise ValueError('Anticipation exceeds retained size bound')
    return copy.deepcopy(value)


def _integer(value, low=0, high=_MAX_INTEGER):
    return type(value) is int and low <= value <= high


def validate_timeline(value):
    if (not isinstance(value, dict) or set(value) != _FIELDS
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['motionId'], str)
            or re.fullmatch(r'[a-f0-9]{64}', value['motionId']) is None
            or not _integer(value['sourceFrameCount'], 1, 1440)
            or type(value['sourceFps']) is not int or value['sourceFps'] != 24
            or not isinstance(value['sourceIndices'], list)
            or not 1 <= len(value['sourceIndices']) <= 1440
            or any(not _integer(index, 0, value['sourceFrameCount']-1)
                   for index in value['sourceIndices'])):
        raise ValueError('Invalid source timeline')
    return {**value, 'sourceIndices': list(value['sourceIndices'])}


def source_frame(timeline, source_tick):
    value = validate_timeline(timeline)
    if not _integer(source_tick, 0, len(value['sourceIndices'])-1):
        raise ValueError('Source tick out of range')
    return value['sourceIndices'][source_tick]


def presented_source_frame(timeline, pts, timescale):
    """Map a confirmed, clip-relative encoded PTS, never a requested seek.

    A six-fps encoded frame at PTS 1/6 covers source tick 4, not tick 1.
    The caller owns proof of presentation and explicit loop/clip boundaries.
    """
    if not _integer(pts) or not _integer(timescale, 1):
        raise ValueError('Invalid presentation timestamp')
    # Codec PTS can be quantized to microseconds (1/6s -> 166666us).
    # Round to the nearest 24-fps source tick, never to an encoded ordinal.
    return source_frame(timeline, (pts * 48 + timescale) // (timescale * 2))
