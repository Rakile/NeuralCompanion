"""Desktop TTS prelude for Continuous Mode; never a character/assistant turn."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import secrets
import threading
import time
from core.runtime.speech_routes import VoiceSegment

from .media_bridge import MainChatMediaBridge


class _Publication:
    """MediaBridge publication callbacks, separate from assistant receipts."""

    def __init__(self):
        self.failed = False

    def add_chunk(self, request_id, chunk_id, sequence, text):
        pass

    def complete(self, request_id, sequence):
        pass

    def cancel(self, request_id):
        self.failed = True


class ContinuousUserSpeech:
    def __init__(self, directory: Path, resolve_voice):
        self.directory = directory
        self.resolve_voice = resolve_voice
        self.media = MainChatMediaBridge(directory / 'media', allow_auto_capture=False)
        self._lock = threading.RLock()
        self._jobs: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self._worker: threading.Thread | None = None
        self._closed = False

    def start(self, owner: str, prepared: dict, voice_id: str) -> dict:
        return self._start(owner, prepared, voice_id, released=True)

    def prefetch(self, owner: str, prepared: dict, voice_id: str) -> dict:
        return self._start(owner, prepared, voice_id, released=False)

    def _start(self, owner: str, prepared: dict, voice_id: str, *, released: bool) -> dict:
        key = owner, prepared['id']
        with self._lock:
            if self._closed or prepared['token'].cancelled:
                raise ValueError('User speech is no longer current.')
            if key in self._jobs:
                if released:
                    self._jobs[key]['released'] = True
                return self.status(*key)
            if self._worker is not None and self._worker.is_alive():
                raise ValueError('Previous desktop user speech is still stopping. Resume shortly.')
            self.media.clear()
            job = dict(owner=owner, prepared=prepared, capture=secrets.token_urlsafe(24),
                       done=False, error='', heard=False, released=released, started=time.monotonic())
            self._jobs[key] = job
            while len(self._jobs) > 8:
                self._jobs.popitem(last=False)
            self._worker = threading.Thread(target=self._generate, args=(job, voice_id),
                                            name='nc-continuous-user-tts', daemon=True)
            self._worker.start()
            return self.status(*key)

    def release(self, owner: str, identity: str) -> dict:
        with self._lock:
            job = self._job(owner, identity)
            if not self._current(job):
                raise ValueError('User speech is no longer current.')
            job['released'] = True
            return self.status(owner, identity)

    def _current(self, job: dict) -> bool:
        return not self._closed and not job['prepared']['token'].cancelled and time.monotonic()-job['started'] < 300

    def _generate(self, job: dict, voice_id: str) -> None:
        publication = _Publication()
        temporary = self.directory / (job['capture'] + '.wav')
        try:
            runtime, voice_path = self.resolve_voice(voice_id)
            settings = runtime.tts_settings_snapshot()
            kwargs = dict(runtime.tts_generation_kwargs())
            kwargs['audio_prompt_path'] = voice_path
            kwargs['use_cloned_voice'] = bool(voice_path)
            target, maximum = runtime.get_text_chunk_limits()
            prepared = job['prepared']
            segments = prepared.get('speech_segments') or (VoiceSegment(prepared.get('speech_text', prepared['text'])),)
            chunks = tuple((text, part) for part in segments
                           for text in runtime.intelligent_chunk_text(part.text, target, maximum))
            if not chunks or len(chunks) > 64:
                raise ValueError('User speech is empty or too long.')
            self.directory.mkdir(parents=True, exist_ok=True)
            self.media.register_phone_reply(job['capture'], publication)
            for index, (text, part) in enumerate(chunks):
                if not self._current(job): raise ValueError('User speech cancelled.')
                if runtime.tts_settings_snapshot() != settings:
                    raise ValueError('Desktop TTS settings changed.')
                segment_kwargs = dict(kwargs)
                if part.voice_path:
                    segment_kwargs.update(audio_prompt_path=part.voice_path, use_cloned_voice=True)
                    if part.voice_language and str(settings.get('backend', '')).casefold() in ('pockettts', 'pocket_tts', 'pockettts_multilingual'):
                        segment_kwargs['pocket_tts_language'] = part.voice_language
                wav = runtime.generate_tts(text, **segment_kwargs)
                if not self._current(job): raise ValueError('User speech cancelled.')
                if runtime.tts_settings_snapshot() != settings:
                    raise ValueError('Desktop TTS settings changed.')
                rate = runtime.tts_sample_rate()
                runtime.save_tts_wav(str(temporary), wav, rate)
                if temporary.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError('User speech chunk is too large.')
                self.media.handle_tts_audio_chunk_ready(dict(audio_path=str(temporary), text=text,
                    sequence_index=index, sample_rate=rate, tts_backend=settings.get('backend', ''),
                    source_meta={**part.source_metadata, 'remote_capture_id': job['capture'],
                                 'display_name': part.source_metadata.get('display_name') or 'User'}))
                if publication.failed: raise ValueError('User speech could not be streamed.')
            self.media.finish_phone_reply(job['capture'])
            with self._lock: job['done'] = True
        except Exception:
            self.media.finish_phone_reply(job['capture'], cancelled=True)
            with self._lock:
                job['error'] = 'Desktop user speech failed or was cancelled. Check the active TTS provider and selected voice.'
                job['done'] = True
        finally:
            temporary.unlink(missing_ok=True)

    def _job(self, owner: str, identity: str) -> dict:
        job = self._jobs.get((owner, identity))
        if job is None: raise ValueError('User speech is unavailable for this phone.')
        return job

    def status(self, owner: str, identity: str) -> dict:
        with self._lock:
            job = self._job(owner, identity)
            current = self._current(job)
            chunks = [dict(id=row['id'], url_path=row['url_path'], sequence_index=row['sequence_index'],
                           duration_seconds=row.get('duration_seconds', 0), text=row.get('text', ''))
                      for row in self.media.snapshot()['items'] if row.get('phone_request_id') == job['capture']]
            return dict(operation_id=identity, chunks=chunks if current and job['released'] else [], done=job['done'],
                        played=bool(job['heard'] and current and not job['error']),
                        error=job['error'] if current else 'User speech cancelled.')

    def acknowledge(self, owner: str, identity: str, chunk_count: int) -> None:
        with self._lock:
            job = self._job(owner, identity)
            state = self.status(owner, identity)
            if (not job['released'] or not state['done'] or state['error'] or type(chunk_count) is not int
                    or not state['chunks'] or len(state['chunks']) != chunk_count):
                raise ValueError('User speech has not finished playback.')
            job['heard'] = True

    def played(self, owner: str, identity: str) -> bool:
        with self._lock:
            job = self._jobs.get((owner, identity))
            return bool(job and job['heard'] and self._current(job) and not job['error'])

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.media.cleanup()
