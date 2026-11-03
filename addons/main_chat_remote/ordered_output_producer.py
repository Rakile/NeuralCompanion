"""Publish existing encoder results into Desktop order, not playback order.

The encoder still owns file creation/removal and source validation. No app,
encoder, network call or playback clock is started by this module. The bridge
owner must authenticate finality and native reader joins before invoking them.
"""
from dataclasses import dataclass, replace
from copy import deepcopy
import hashlib
from pathlib import Path
import threading

from .output_sequence import MAX_MEDIA_BYTES, OutputChunk, SourceRange, OutputRejected
from .encoding_timing import timed


@dataclass(frozen=True, slots=True)
class PreparedOutput:
    kind: str
    source_id: str
    source_range: SourceRange
    media_id: str
    sample_count: int
    reply_id: str | None
    sequence_index: int | None
    file: Path


def _signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


class OrderedOutputProducer:
    """Two future idle chunks; reader custody has independent byte/file limits."""
    def __init__(self, sequence, root):
        self.sequence = sequence
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('output_root_invalid')
        self._lock = threading.RLock()
        self._files = {}
        self._announcements = {}
        self._encoded_tail = None
        self._uncertain = {}
        self._idle_started = None
        self.budget = None
        self._credits = {}
        self._released_paths = {}

    def attach_budget(self, budget):
        """Import existing custody once; replacement generations share credit."""
        with self._lock:
            if self.budget is not None and self.budget is not budget:
                raise ValueError('ordered_prepared_budget_changed')
            self.budget = budget
            for state, rows in (('retained',self._files),('uncertain',self._uncertain)):
                for key,(row,_,_) in rows.items():
                    if key not in self._credits:
                        self._credits[key]=budget.retain(row.byte_length,state)

    def release_removed(self, generation, ordinal):
        """Called only after exact native ACK and successful file removal."""
        key=generation,ordinal
        with self._lock:
            path=self._released_paths.get(key)
            if path is None:return
            if path.exists():raise ValueError('ordered_prepared_file_still_owned')
            token=self._credits.pop(key)
            del self._released_paths[key]
        self.budget.release(token)

    def discard_private_clip(self,clip):
        key=clip.cursor.generation,clip.cursor.ordinal
        with self._lock:
            if key in self._files or key in self._uncertain:
                raise ValueError('ordered_prepared_still_reader_owned')
            if self._credits.get(key) is clip.reservation:self._credits.pop(key)
        clip.output.file.unlink(missing_ok=True)
        self.budget.release(clip.reservation)

    def diagnostic_custody(self):
        """Local, nonblocking custody evidence; never asks Desktop or touches files."""
        if not self._lock.acquire(blocking=False): return {'custody.state':'lock_busy'}
        try:
            result = {'custody.state':'observed', 'custody.awaiting':'exact_readers_closed_ack'}
            for name, rows in (('retained',self._files), ('uncertain',self._uncertain)):
                keys = sorted(rows)
                result.update({name+'.count':len(keys), name+'.keys':'/'.join(f'{g}:{o}' for g,o in keys[:3]) or None,
                               name+'.truncated':len(keys)>3})
            return result
        finally: self._lock.release()

    def frontier(self):
        return self.sequence.frontier()

    def reserve_speech(self, reply_id, expected_frontier):
        return self.sequence.reserve_speech(reply_id, expected_frontier)

    def can_prepare_idle(self):
        with self._lock:
            return self._can_prepare_idle(self.frontier())

    def _can_prepare_idle(self, frontier):
        # Caller holds the producer lock; use one Desktop snapshot throughout.
        started = (self._idle_started[1] if self._idle_started is not None
                   and self._idle_started[0] == frontier.generation else -1)
        return frontier.reply_id is None and sum(
            row.kind == 'idle' and row.generation == frontier.generation and row.ordinal > started
            for row, _, _ in self._files.values()) < 2

    def idle_started(self, generation, ordinal):
        """Authenticated native-start observation, NEVER a reader release ACK.

        A stale generation cannot advance the replacement's lookahead. Future
        ordinals and speech/transition sources cannot manufacture idle credit.
        Only the existing sequence's joined ACK may reclaim a retained file.
        """
        with self._lock:
            if (type(generation) is not int or type(ordinal) is not int
                    or generation != self.frontier().generation or not 0 <= ordinal < (1 << 53)):
                raise ValueError('output_idle_progress_scope')
            if self._idle_started is not None and self._idle_started[0] == generation and ordinal <= self._idle_started[1]:
                return
            retained = self._files.get((generation, ordinal))
            if retained is None or retained[0].kind != 'idle':
                raise ValueError('output_idle_progress_unknown')
            self._idle_started = generation, ordinal

    def _file_identity(self, file):
        candidate = Path(file)
        candidate.absolute().relative_to(self.root)
        if candidate.is_symlink():
            raise ValueError('output_file_invalid')
        file = candidate.resolve(strict=True)
        file.relative_to(self.root)
        before = _signature(file)
        if not file.is_file() or not 0 < before[2] <= MAX_MEDIA_BYTES:
            raise ValueError('output_file_invalid')
        with file.open('rb') as stream:
            body = stream.read(MAX_MEDIA_BYTES + 1)
        if len(body) != before[2] or _signature(file) != before:
            raise ValueError('output_file_changed')
        return file, before, hashlib.sha256(body).hexdigest()

    def publish(self, prepared, expected_frontier, *, timings=None, reservation=None, return_ack=False):
        """Commit once encoding completes; a stale encoder cannot rebase itself."""
        if type(prepared) is not PreparedOutput:
            raise ValueError('output_prepared_invalid')
        file, signature, digest = timed(timings,'publish_hash_ms',self._file_identity,prepared.file)
        row = OutputChunk(stream_id=expected_frontier.stream_id,
            generation=expected_frontier.generation, ordinal=expected_frontier.next_ordinal,
            predecessor=expected_frontier.next_ordinal - 1 if expected_frontier.next_ordinal else None,
            kind=prepared.kind, source_id=prepared.source_id, source_range=prepared.source_range,
            media_id=prepared.media_id, frame_count=len(prepared.source_range.frames), fps=24,
            sample_count=prepared.sample_count, reply_id=prepared.reply_id,
            sequence_index=prepared.sequence_index, sha256=digest, byte_length=signature[2])
        key = row.generation, row.ordinal
        with self._lock:
            # A lost bridge response can hide an already committed row. Never
            # start another transaction or delete its media based on that loss.
            if self._uncertain:
                raise ValueError('output_publication_unresolved')
            existing = self._files.get(key)
            if existing is not None and existing != (row, file, signature):
                raise ValueError('output_retained_media_conflict')
            # Preserve the more useful frontier/reservation error over a generic
            # lookahead error when speech or invalidation won during encoding.
            if prepared.kind == 'idle' and key not in self._files:
                current = self.frontier()
                if (expected_frontier == current and current.reply_id is None
                        and not self._can_prepare_idle(current)):
                    raise ValueError('output_idle_lookahead')
            try:
                if reservation is not None:
                    if self.budget is None:raise ValueError('ordered_prepared_budget_missing')
                    self.budget.resize(reservation,signature[2])
                    self.budget.transfer(reservation,'publishing')
                    self._credits[key]=reservation
                ack=timed(timings,'desktop_commit_ms',self.sequence.commit,row,expected_frontier)
                if return_ack and ack!=replace(expected_frontier,next_ordinal=row.ordinal+1,
                        revision=expected_frontier.revision+1,last_frame=row.source_range.frames[-1]):
                    raise ValueError('ordered_commit_ack_mismatch')
            except OutputRejected:
                if reservation is not None:self._credits.pop(key,None)
                raise  # Definitive compare/capacity rejection: not committed.
            except Exception:
                self._uncertain[key] = row, file, signature
                if reservation is not None:self.budget.transfer(reservation,'uncertain')
                raise
            self._files[key] = row, file, signature
            if reservation is not None:self.budget.transfer(reservation,'retained')
            return (row,ack) if return_ack else row

    def owns_file(self, file):
        target=Path(file).resolve()
        with self._lock:
            return any(path==target for _,path,_ in (*self._files.values(),*self._uncertain.values()))

    @property
    def has_retained_media(self):
        with self._lock:
            return bool(self._files or self._uncertain)

    def retained_keys(self):
        with self._lock:
            if self._uncertain: raise ValueError('output_publication_unresolved')
            return tuple(sorted(self._files))

    def media_bytes(self, generation, ordinal):
        with self._lock:
            retained = self._files.get((generation, ordinal))
            if retained is None: raise ValueError('output_retained_media_unknown')
            row, path, signature = retained
            try:
                if _signature(path) != signature: raise ValueError('output_retained_media_changed')
                with path.open('rb') as stream: body = stream.read(MAX_MEDIA_BYTES+1)
                if (_signature(path) != signature or len(body) != row.byte_length
                        or hashlib.sha256(body).hexdigest() != row.sha256):
                    raise ValueError('output_retained_media_changed')
            except OSError:
                raise ValueError('output_retained_media_changed') from None
            return body

    def reconcile_publications(self):
        """Explicit recovery/cleanup after an uncertain commit; never a retry loop.

        Inspection cannot release readers. A confirmed row still needs the exact
        joined ACK; an absent row returns custody to its original encoder owner.
        A failed inspection keeps all uncertain media pinned.
        """
        results=[]
        with self._lock:
            for key, retained in tuple(self._uncertain.items()):
                row, _, _ = retained
                actual=self.sequence.retained_chunk(*key)
                if actual is not None and actual!=row:
                    raise ValueError('output_publication_conflict')
                if actual is not None:
                    self._files[key]=retained
                    if key in self._credits:self.budget.transfer(self._credits[key],'retained')
                del self._uncertain[key]
                results.append((*key,actual is not None))
        return tuple(results)

    def finish_reply(self, reply_id, authenticated_status):
        """Status must come directly from PhoneReplyRegistry, never the phone."""
        status = authenticated_status
        if (type(status) is not dict or status.get('phone_request_id') != reply_id
                or status.get('phase') != 'complete' or status.get('playback_stop_requested') is True):
            raise ValueError('output_reply_not_final')
        return self.sequence.finish_reply(reply_id, status.get('last_sequence_index'))

    def publish_encoded(self, prepared, expected_frontier, *, source_samples, trim, timings=None,
                        reservation=None, return_ack=False):
        """Publish existing encoder output plus the exact native staging layout.

        No codec/timing guess: trims are the encoder's actual AAC result. File
        identity is hashed by publish; native still validates the actual MP4.
        """
        def integer(value, low, high):
            return type(value) is int and low <= value <= high
        if type(prepared) is not PreparedOutput:
            raise ValueError('output_encoded_prepared_invalid')
        source_range = prepared.source_range
        frames = len(source_range.frames)
        if (not integer(source_range.total_frames, 1, 720) or source_range.start % 12
                or not integer(source_samples, 1, 1441999)
                or abs(source_samples - source_range.total_frames * 2000) >= 2000
                or len(prepared.source_id) > 128
                or prepared.reply_id is not None and len(prepared.reply_id) > 128
                or prepared.kind == 'speech' and not integer(prepared.sequence_index, 0, 63)
                or prepared.kind != 'speech' and source_samples != source_range.total_frames * 2000):
            raise ValueError('output_encoded_source_invalid')
        index = source_range.start // 12
        samples = source_samples - index * 24000 if source_range.end == source_range.total_frames else 24000
        if (type(trim) is not dict or set(trim) != {'validSamples', 'delaySamples', 'paddingSamples', 'rawSamples', 'sampleRate'}
                or not integer(trim['validSamples'], 1, 25999) or trim['validSamples'] != samples
                or samples != prepared.sample_count
                or not integer(trim['delaySamples'], 0, 2048) or not integer(trim['paddingSamples'], 0, 1023)
                or not integer(trim['rawSamples'], 1024, 28672) or trim['rawSamples'] % 1024
                or trim['rawSamples'] - trim['delaySamples'] - trim['paddingSamples'] != samples
                or type(trim['sampleRate']) is not int or trim['sampleRate'] != 48000):
            raise ValueError('output_encoded_trim_invalid')
        source = dict(kind=prepared.kind, sourceId=prepared.source_id, replyId=prepared.reply_id,
            sequenceIndex=prepared.sequence_index, mediaId=prepared.media_id,
            plan=dict(frames=source_range.total_frames, samples=source_samples),
            firstOrdinal=expected_frontier.next_ordinal - index)
        if source['firstOrdinal'] < 0:
            raise ValueError('output_encoded_source_ordinal')
        key = expected_frontier.generation, expected_frontier.next_ordinal
        with self._lock:
            prior_sources = [a['source'] for k, a in self._announcements.items() if k[0] == key[0]]
            if self._encoded_tail is not None and self._encoded_tail[0] == key[0]:
                prior_sources.append(self._encoded_tail[1])
            if any(s['sourceId'] == source['sourceId'] and s != source for s in prior_sources):
                raise ValueError('output_encoded_source_changed')
            # Validate all metadata before committing an irreversible ordinal.
            file = dict(path=f'/api/remote-output/media/{expected_frontier.stream_id}/{key[0]}/{key[1]}.mp4',
                        index=index, startFrame=source_range.start, frameCount=frames, fps=24, **trim)
            prior = self._announcements.get(key)
            if prior is not None and (prior['source'] != source or prior['file'] != file):
                raise ValueError('output_encoded_descriptor_changed')
            value = self.publish(prepared, expected_frontier, timings=timings,
                reservation=reservation,return_ack=return_ack)
            chunk,ack=value if return_ack else (value,None)
            result = dict(chunk=chunk.to_wire(), source=source, file=file)
            self._announcements[key] = result
            self._encoded_tail = key[0], source
            return (deepcopy(result),ack) if return_ack else deepcopy(result)

    def commit_prepared(self, clip, expected):
        from .ordered_output_publication import PublicationAck
        from .encoding_timing import measure
        from core.diagnostics.policy import site_enabled
        cursor,plan,output=clip.cursor,clip.ticket.plan,clip.output
        if ((cursor.stream_id,cursor.generation,cursor.reply_id,cursor.ordinal,cursor.revision,cursor.predecessor_frame)
                !=(expected.stream_id,expected.generation,expected.reply_id,expected.next_ordinal,expected.revision,expected.last_frame)
                or output.kind!='speech' or output.source_id!=plan.source_id or output.reply_id!=plan.reply_id
                or output.sequence_index!=plan.sequence_index or output.media_id!=plan.media_id
                or output.source_range.total_frames!=len(plan.frames)
                or output.source_range.frames!=tuple(f.provenance for f in
                    plan.frames[output.source_range.start:output.source_range.end])):
            raise ValueError('ordered_prepared_publication_mismatch')
        timings={} if site_enabled('backend.encode.ordered') else None
        with measure(timings,'publication_ms'):
            announcement,ack=self.publish_encoded(output,expected,source_samples=plan.samples,trim=dict(clip.trim),
                timings=timings,reservation=clip.reservation,return_ack=True)
        # Exact reader ACKs can remove custody immediately after publication.
        # Return the immutable committed result, never reread the mutable ledger.
        return PublicationAck(OutputChunk.from_wire(announcement['chunk']),ack,
            {} if timings is None else {k:round(v,3) for k,v in timings.items()})

    def announcements(self, after_ordinal):
        with self._lock:
            rows = self.sequence.snapshot(after_ordinal)
            if any((row.generation, row.ordinal) not in self._announcements for row in rows):
                raise ValueError('output_encoded_metadata_unavailable')
            return tuple(deepcopy(self._announcements[(row.generation, row.ordinal)]) for row in rows)

    def acknowledge(self, generation, ordinal, *, readers_closed):
        with self._lock:
            self.sequence.acknowledge(generation, ordinal, readers_closed=readers_closed)
            self._announcements.pop((generation, ordinal), None)
            key=generation,ordinal
            path=self._files.pop(key)[1]
            if key in self._credits:self._released_paths[key]=path
            return path

    def media_path(self, generation, ordinal):
        with self._lock:
            retained = self._files.get((generation, ordinal))
        if retained is None:
            raise ValueError('output_retained_media_unknown')
        row, path, signature = retained
        try:
            actual_path, actual_signature, digest = self._file_identity(path)
        except (OSError, ValueError):
            raise ValueError('output_retained_media_changed') from None
        if actual_path != path or actual_signature != signature or digest != row.sha256:
            raise ValueError('output_retained_media_changed')
        return path
