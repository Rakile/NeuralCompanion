"""Desktop plans from exact retained audio and its MuseTalk render sidecar.

This source does not grant playback or infer finality. The ordering binding owns
authentication and the reply reservation. No glob-based WAV identity discovery.
"""
import hashlib
import json
from pathlib import Path
import wave

from .idle_loop_catalog import _confined
from .dev_musetalk_live import load_delivery_metadata, idle_frames, _failure_diagnostic


class OrderedSpeechSource:
    def __init__(self, runtime_root, media):
        self.root = Path(runtime_root).resolve(strict=True)
        self.renders = self.root/'MuseTalk/runtime/rendered_chunks'
        self.media = media
        self._progress_identity = None

    def render_chunk_for_audio(self, reply_id, audio_id):
        """Private observation identity only; never inspect files or grant output."""
        known = self._progress_identity
        if known is not None and known[:2] == (reply_id, audio_id):
            return known[2]
        try:
            item = self.media.ordered_speech_source(reply_id, 0)
        except ValueError:
            return None  # Retired/cancelled audio is not new progress evidence.
        if item is None or item['audioId'] != audio_id:
            return None
        self._progress_identity = (reply_id, audio_id, item['chunkId'])
        return item['chunkId']

    def plan(self, frontier, sequence):
        try:
            return self._plan(frontier, sequence)
        except FileNotFoundError as error:
            # Missing source paths were becoming an unclassified bridge 404.
            # Retain only bounded code locations, never paths/exception text.
            try:
                from core.diagnostics.plan_trace import PlanTrace
                trace = PlanTrace(component='desktop')
                detail = _failure_diagnostic(error)
                values = {key: value for key, value in detail.items() if key != 'frames'}
                values.update(sequence_index=sequence, generation=frontier.generation,
                              expected_ordinal=frontier.next_ordinal)
                for index, frame in enumerate(detail['frames']):
                    values.update({f'origin_{index}_{key}': value for key, value in frame.items()})
                for condition, value in values.items():
                    trace.observe(frontier.stream_id, 'desktop.plan.output.reject', condition, None, value)
            except Exception:
                pass  # Observation cannot hide the terminal source failure.
            raise ValueError('ordered_speech_resource_missing') from None

    def _plan(self, frontier, sequence):
        if frontier.reply_id is None or type(sequence) is not int or not 0 <= sequence <= 63:
            raise ValueError('ordered_speech_identity')
        item = self.media.ordered_speech_source(frontier.reply_id, sequence)
        if item is None: return dict(state='waiting', stage='audio', sequenceIndex=sequence)
        if sequence == 0:
            # Keep only identity metadata after exact audio/render lookup. A very
            # short first segment may retire before its UI report arrives.
            self._progress_identity = (frontier.reply_id, item['audioId'], item['chunkId'])
        wav = Path(item['wav'])
        try:
            wav = _confined(wav, (self.root,))
            if not wav.is_file(): raise FileNotFoundError()
        except FileNotFoundError:
            raise ValueError('ordered_speech_audio_missing') from None
        source = self.renders/item['chunkId']
        if not source.exists(): return dict(state='waiting', stage='render', sequenceIndex=sequence)
        source = _confined(source, (self.renders,))
        from addons.musetalk_avatar.delivery_metadata import FAILURE_SIDECAR_NAME, validate_failure
        failure_path = source/FAILURE_SIDECAR_NAME
        if failure_path.exists():
            failure_path = _confined(failure_path,(source,))
            if not 0 < failure_path.stat().st_size <= 4096:
                raise ValueError('ordered_speech_failure_invalid')
            failure = validate_failure(json.loads(failure_path.read_text('utf-8')),item['chunkId'])
            identity = failure['remoteSource']
            if identity['replyId'] != frontier.reply_id or identity['sequenceIndex'] != sequence:
                raise ValueError('ordered_speech_identity_mismatch')
            if not 0 < wav.stat().st_size <= 4*1024*1024:
                raise ValueError('ordered_speech_audio_size')
            if hashlib.sha256(wav.read_bytes()).hexdigest() != identity['wavSha256']:
                raise ValueError('ordered_speech_audio_mismatch')
            raise ValueError('ordered_speech_failed_'+failure['stage'])
        # An atomic final sidecar is the render-completion signal. Initial
        # metadata is useful diagnostics but cannot prove completed frame files.
        if not (source/'phone-delivery.json').exists():
            return dict(state='waiting', stage='render', sequenceIndex=sequence)
        metadata = load_delivery_metadata(source, self.renders, self.root)
        if not metadata['final']: return dict(state='waiting', stage='render', sequenceIndex=sequence)
        identity = metadata.get('remoteSource')
        if (identity is None or identity['replyId'] != frontier.reply_id or identity['sequenceIndex'] != sequence):
            raise ValueError('ordered_speech_identity_mismatch')
        if not 0 < wav.stat().st_size <= 4*1024*1024:
            raise ValueError('ordered_speech_audio_size')
        if hashlib.sha256(wav.read_bytes()).hexdigest() != identity['wavSha256']:
            raise ValueError('ordered_speech_audio_mismatch')
        with wave.open(str(wav),'rb') as audio:
            if audio.getframerate() not in (24000,48000) or audio.getnchannels()!=1 or audio.getsampwidth()!=2:
                raise ValueError('ordered_speech_audio_format')
            samples=audio.getnframes()*(48000//audio.getframerate())
        timeline = metadata.get('sourceTimeline')
        spans=metadata.get('sourceSpans')
        if spans is None and timeline is None: raise ValueError('ordered_speech_timeline_missing')
        timelines=[span['timeline'] for span in spans] if spans is not None else [timeline]
        provenance=[dict(sourceId=t['motionId'],frame=index,sourceFrameCount=t['sourceFrameCount'])
                    for t in timelines for index in t['sourceIndices']]
        if sequence == 0:
            start = metadata.get('orderedOutput')
            if start is None: raise ValueError('ordered_speech_start_plan_missing')
            if (start['streamId'] != frontier.stream_id or start['generation'] != frontier.generation
                    or start['replyId'] != frontier.reply_id or start['firstOrdinal'] != frontier.next_ordinal
                    or start['reservationRevision'] != frontier.revision):
                raise ValueError('ordered_speech_start_plan_stale')
        frames = idle_frames(source); trim=metadata['trimStartFrames']; count=metadata['frameCount']
        if len(frames) != trim+count or not 1 <= count <= 720 or abs(samples-count*2000)>=2000:
            raise ValueError('ordered_speech_frames_mismatch')
        # Output authority/receipts bind the public retained audio identity.
        # The private render basename above selects pixels only, never a grant.
        source_id=item['audioId']
        if len(source_id)>128: raise ValueError('ordered_speech_source_id')
        plan=dict(kind='speech', sourceId=source_id,
            mediaId=hashlib.sha256((frontier.stream_id+str(frontier.generation)+source_id).encode()).hexdigest()[:32],
            samples=samples, wav=str(wav), replyId=frontier.reply_id, sequenceIndex=sequence,
            frames=[dict(path=str(path), provenance=frame) for path,frame in zip(frames[trim:],provenance)])
        return dict(state='ready', plan=plan)
