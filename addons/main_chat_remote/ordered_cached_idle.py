"""Desktop-authored silent presentation boundaries, separate from media custody.

The binding serializes this with ordinary publication. No file, native player,
speech receipt or reader acknowledgement is created here. The caller validates
the asset against the authenticated current complete-loop inventory first.
"""
import re

from .output_sequence import FrameProvenance, OutputFrontier


def _integer(value, low=0, high=(1 << 53)-1):
    return type(value) is int and low <= value <= high


def _hex(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}',value) is not None


class CachedIdlePresentation:
    def __init__(self, sequence):
        self.sequence = sequence
        self._grant = None
        self._expected = None
        self._revision = 0
        self.active = False

    @property
    def suppresses_idle(self):
        if self._grant is None:return False
        current = self.sequence.frontier()
        # Keep the old grant valid for delayed native activation receipts, but
        # it cannot block return publication once real speech has advanced it.
        return current.generation == self._grant['generation'] and current.next_ordinal <= self._grant['afterOrdinal']+1

    @property
    def grant(self):
        return None if self._grant is None else dict(self._grant)

    def reserve(self, expected, asset, fade_ms):
        if (type(asset) is not dict or set(asset) != {'cacheEpoch','inventoryRevision','loopId','motionId','sourceFrameCount'}
                or not _integer(asset['cacheEpoch']) or not all(_hex(asset[k]) for k in ('inventoryRevision','loopId','motionId'))
                or not _integer(asset['sourceFrameCount'],1,1440) or not _integer(fade_ms,0,5000)):
            raise ValueError('ordered_cached_asset')
        if (type(expected) is not OutputFrontier or expected.reply_id is not None or expected.next_ordinal == 0
                or expected.last_frame is None):
            raise ValueError('ordered_cached_idle_frontier')
        if (expected.last_frame.source_id != asset['motionId']
                or expected.last_frame.source_frame_count != asset['sourceFrameCount']):
            raise ValueError('ordered_cached_source_binding')
        if self._grant is not None:
            if ((expected == self._expected or expected == self.sequence.frontier()
                    and expected.generation == self._grant['generation']
                    and expected.next_ordinal == self._grant['afterOrdinal']+1)
                    and all(self._grant[k] == v for k,v in asset.items())):
                return dict(self._grant)
            if expected.next_ordinal <= self._grant['afterOrdinal']+1:
                raise ValueError('ordered_cached_reservation_conflict')
        # Advances only the compare revision. An encoder that captured the old
        # frontier must drop its speculative idle; no synthetic chunk is added.
        tail = self.sequence.retained_chunk(expected.generation,expected.next_ordinal-1)
        if tail is None: raise ValueError('ordered_cached_tail_unretained')
        # The open native playlist withholds its final period's EOF until a
        # real successor is selected. Suppressing publication at a speech tail
        # would prevent the very completion required to activate cached idle.
        # Keep Desktop's ordinary return clip flowing; reserve after that clip.
        if tail.kind == 'speech': raise ValueError('ordered_cached_return_pending')
        self.sequence.reserve_visual_boundary(expected)
        self._revision += 1
        self._expected = expected
        self._grant = dict(version=1,streamId=expected.stream_id,generation=expected.generation,
            activationRevision=self._revision,afterOrdinal=expected.next_ordinal-1,
            afterFrameCount=tail.frame_count,
            entryFrame=(expected.last_frame.frame+1)%asset['sourceFrameCount'],fps=24,fadeMs=fade_ms,**asset)
        self.active = False
        return dict(self._grant)

    def observe(self, observed):
        grant = self._grant
        if (grant is None or type(observed) is not dict or set(observed) != {
                'activationRevision','streamId','generation','loopId','sourceFrame','ageMs'}
                or any(type(observed[k]) is not type(grant[k]) or observed[k] != grant[k]
                       for k in ('activationRevision','streamId','generation','loopId'))
                or not _integer(observed['sourceFrame'],0,grant['sourceFrameCount']-1)
                or not _integer(observed['ageMs'],0,250)):
            raise ValueError('ordered_cached_activation_scope')
        if self.sequence.frontier().generation != grant['generation']:
            raise ValueError('ordered_cached_activation_scope')
        return FrameProvenance(grant['motionId'],observed['sourceFrame'],grant['sourceFrameCount'])

    def activate(self, observed):
        frame = self.observe(observed)
        if frame.frame != self._grant['entryFrame']:
            raise ValueError('ordered_cached_activation_entry')
        self.active = True
        return dict(self._grant)

    def revoke(self, activation_revision=None):
        if activation_revision is not None and (not _integer(activation_revision,1)
                or activation_revision != self._revision):
            raise ValueError('ordered_cached_activation_scope')
        self._grant = self._expected = None
        self.active = False
