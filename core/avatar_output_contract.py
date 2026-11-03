"""Pure shared wire validation for Desktop-owned remote output planning.

No addon instances, playback authority, filesystem reads or transition search.
"""
import hashlib
from pathlib import Path
import re

_MAX_SAFE = (1 << 53) - 1


def _integer(value, minimum=0, maximum=_MAX_SAFE):
    return type(value) is int and minimum <= value <= maximum


def validate_remote_source(value):
    if (type(value) is not dict or set(value) != {'version', 'replyId', 'sequenceIndex', 'wavSha256'}
            or type(value['version']) is not int or value['version'] != 1
            or type(value['replyId']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['replyId'])
            or not _integer(value['sequenceIndex'], 0, 2047)
            or type(value['wavSha256']) is not str or not re.fullmatch('[a-f0-9]{64}', value['wavSha256'])):
        raise ValueError('ordered_remote_source_invalid')
    return dict(value)


def validate_ordered_start(value):
    fields = {'version', 'streamId', 'generation', 'firstOrdinal', 'reservationRevision',
              'replyId', 'motionId', 'sourceFrameCount', 'startFrame'}
    if (type(value) is not dict or set(value) != fields
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['streamId'], str) or not re.fullmatch('[a-f0-9]{32}', value['streamId'])
            or any(not _integer(value[key]) for key in ('generation', 'firstOrdinal', 'reservationRevision'))
            or not isinstance(value['replyId'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value['replyId'])
            or not isinstance(value['motionId'], str) or not re.fullmatch('[a-f0-9]{64}', value['motionId'])
            or not _integer(value['sourceFrameCount'], 1, 1440)
            or not _integer(value['startFrame'], 0, value['sourceFrameCount'] - 1)):
        raise ValueError('ordered_output_plan_invalid')
    return dict(value)


def ordered_start_from_frontier(frontier, *, idle_frame_dir, source_frame_count, fps):
    fields = {'version', 'streamId', 'generation', 'nextOrdinal', 'revision', 'lastFrame', 'replyId'}
    if (type(frontier) is not dict or set(frontier) != fields or type(fps) is not int or fps != 24
            or not _integer(source_frame_count,1,1440)):
        raise ValueError('ordered_output_frontier_invalid')
    motion = hashlib.sha256(str(Path(idle_frame_dir).resolve()).encode()).hexdigest()
    last = frontier['lastFrame']
    if last is not None:
        if (type(last) is not dict or set(last) != {'sourceId', 'frame', 'sourceFrameCount'}
                or not _integer(last['sourceFrameCount'], 1, 1440)
                or not _integer(last['frame'], 0, last['sourceFrameCount'] - 1)):
            raise ValueError('ordered_output_frontier_invalid')
        if (type(last['sourceId']) is not str or not re.fullmatch('[a-f0-9]{64}',last['sourceId'])
                or last['sourceId'] == motion and last['sourceFrameCount'] != source_frame_count):
            raise ValueError('ordered_output_source_mismatch')
    return validate_ordered_start(dict(version=frontier['version'], streamId=frontier['streamId'],
        generation=frontier['generation'], firstOrdinal=frontier['nextOrdinal'],
        reservationRevision=frontier['revision'], replyId=frontier['replyId'], motionId=motion,
        sourceFrameCount=source_frame_count,
        # Another motion has no meaningful index correspondence. Desktop starts
        # its new source at zero and authors the pixel fade in the output plan;
        # the backend composites from its committed tail, never a phone cursor.
        startFrame=(last['frame'] + 1) % source_frame_count if last is not None and last['sourceId'] == motion else 0))


def validate_source_spans(value, frame_count):
    """Exact contiguous coverage of a merged Desktop render, not inferred IDs."""
    if (type(value) is not list or not 1 <= len(value) <= 16
            or not _integer(frame_count,1,1440)):
        raise ValueError('ordered_source_spans_invalid')
    end=0; result=[]
    for span in value:
        if type(span) is not dict or set(span)!={'startFrame','timeline'} or type(span['startFrame']) is not int or span['startFrame']!=end:
            raise ValueError('ordered_source_spans_gap')
        t=span['timeline']
        if (type(t) is not dict or set(t)!={'version','motionId','sourceFrameCount','sourceFps','sourceIndices'}
                or type(t['version']) is not int or t['version']!=1
                or type(t['motionId']) is not str or not re.fullmatch('[a-f0-9]{64}',t['motionId'])
                or not _integer(t['sourceFrameCount'],1,1440) or type(t['sourceFps']) is not int or t['sourceFps']!=24
                or type(t['sourceIndices']) is not list or not 1<=len(t['sourceIndices'])<=1440
                or any(not _integer(i,0,t['sourceFrameCount']-1) for i in t['sourceIndices'])):
            raise ValueError('ordered_source_spans_timeline')
        end+=len(t['sourceIndices'])
        if end>frame_count: raise ValueError('ordered_source_spans_count')
        result.append(dict(startFrame=span['startFrame'],timeline={**t,'sourceIndices':list(t['sourceIndices'])}))
    if end!=frame_count: raise ValueError('ordered_source_spans_count')
    return result


def validate_ordered_render(plan, timeline, frame_count, source_spans=None):
    """The requested entry is not evidence of the frames actually rendered."""
    plan = validate_ordered_start(plan)
    if source_spans is not None:
        spans=validate_source_spans(source_spans,frame_count)
        timeline=spans[0]['timeline']
        frame_count=len(timeline['sourceIndices'])
    if (type(timeline) is not dict or not _integer(frame_count, 1, 1440)
            or timeline.get('motionId') != plan['motionId']
            or timeline.get('sourceFrameCount') != plan['sourceFrameCount']
            or timeline.get('sourceFps') != 24
            or type(timeline.get('sourceIndices')) is not list
            or len(timeline['sourceIndices']) != frame_count
            or any(not _integer(i, 0, plan['sourceFrameCount'] - 1) for i in timeline['sourceIndices'])
            or timeline['sourceIndices'][0] != plan['startFrame']):
        raise ValueError('ordered_output_render_mismatch')
