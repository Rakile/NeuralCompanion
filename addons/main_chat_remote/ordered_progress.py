"""Bounded phone-reported UI observation, never playback authority or receipts."""
import math
import re


def validate_progress(value):
    fields = {'version', 'replyId', 'firstSourceId', 'knownSegments', 'preparedUnits',
              'completedSegments', 'playingSequence', 'finalSegments'}
    if type(value) is not dict or set(value) != fields:
        raise ValueError('ordered_progress_shape')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('ordered_progress_version')
    for key in ('replyId', 'firstSourceId'):
        if type(value[key]) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value[key]):
            raise ValueError('ordered_progress_identity')
    count, prepared, completed = (value[k] for k in ('knownSegments', 'preparedUnits', 'completedSegments'))
    if (type(count) is not int or not 1 <= count <= 64 or type(prepared) not in (int, float)
            or not math.isfinite(prepared) or not 0 <= prepared <= count
            or type(completed) is not int or not 0 <= completed <= prepared):
        raise ValueError('ordered_progress_counts')
    playing, final = value['playingSequence'], value['finalSegments']
    if playing is not None and (type(playing) is not int or not completed <= playing < count):
        raise ValueError('ordered_progress_playing')
    if final is not None and (type(final) is not int or not count <= final <= 64):
        raise ValueError('ordered_progress_finality')
    return dict(value)
