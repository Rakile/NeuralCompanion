"""Private, opt-in phone PCM production inside the existing synthesis gate."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
import wave

from core.incremental_audio import IncrementalAudioSource, PCMBlock
from core.runtime.contracts import CancellationToken


MAX_PHONE_PCM_FRAMES = 1_440_000


def progressive_phone_audio_allowed(
    metadata: Mapping[str, object], config: Mapping[str, object], adapter: object,
    sample_rate: int,
) -> bool:
    """Require the frozen negotiated route and the provider's own opt-in."""
    if (metadata.get('phone_progressive_audio') is not True
            or metadata.get('publish_tts_addon_events') is not True
            or metadata.get('phone_reply_control') is not True
            or not str(metadata.get('remote_capture_id') or '').strip()
            or str(config.get('avatar_mode', '')).strip().lower() != 'none'
            or str(config.get('tts_backend', '')).strip().lower() != 'liquidai'
            or sample_rate != 24000):
        return False
    supports = getattr(adapter, 'supports_incremental_audio', None)
    if not callable(supports) or not callable(getattr(adapter, 'generate_stream', None)):
        return False
    try:
        return bool(supports(config))
    except Exception:
        return False


def generate_progressive_phone_audio(
    adapter: Any, text: str, *, config: Mapping[str, object],
    kwargs: Mapping[str, object], prefix_path: Path,
    publish_prefix: Callable[[IncrementalAudioSource, Path], bool],
    cancel_tokens: Sequence[CancellationToken | None],
    delete_audio: Callable[[str], object],
) -> tuple[object, IncrementalAudioSource | None]:
    """Publish at the provider buffer threshold; retain one complete waveform.

    A declined prefix is never retried. The same inference then supplies the
    normal completed-file callback. Once admitted, any error stops the source.
    The gateway synchronously copies the prefix and owns an admitted source.
    """
    import numpy as np

    try:
        options_callback = getattr(adapter, 'incremental_audio_options', None)
        options = dict(options_callback(config) or {}) if callable(options_callback) else {}
        source = IncrementalAudioSource(sample_rate=24000, channels=1,
            startup_seconds=options.get('startup_buffer_seconds', 1.))
    except Exception:
        if any(token is not None and token.cancelled for token in cancel_tokens):
            raise InterruptedError('Phone speech cancelled')
        return adapter.generate(text, **dict(kwargs)), None
    subscriptions = [token.subscribe(lambda token=token: source.cancel(token.reason))
                     for token in cancel_tokens if token is not None]
    attempted = False
    admitted = False
    iterator = None

    def check_cancelled() -> None:
        if source.cancelled or source.closed:
            raise InterruptedError(source.token.reason or 'Phone speech cancelled')

    def publish() -> None:
        nonlocal attempted, admitted
        check_cancelled()
        attempted = True
        prefix_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(prefix_path), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(source.read_frames(0, source.frame_count))
        try:
            admitted = publish_prefix(source, prefix_path) is True
        finally:
            try:
                delete_audio(str(prefix_path))
            except Exception:
                pass
        if admitted and not source.handoff():
            raise InterruptedError('Phone PCM admission was retired')
        check_cancelled()

    try:
        check_cancelled()
        iterator = adapter.generate_stream(text, stop_event=source.token, **dict(kwargs))
        try:
            for block in iterator:
                check_cancelled()
                if not isinstance(block, PCMBlock):
                    raise TypeError('Phone PCM producer must yield PCMBlock')
                if source.frame_count + block.frame_count > MAX_PHONE_PCM_FRAMES:
                    raise ValueError('Phone PCM exceeds the 60 second source limit')
                source.append(block)
                if not attempted and source.ready:
                    publish()
        finally:
            close = getattr(iterator, 'close', None)
            if callable(close):
                close()
        check_cancelled()
        # Short successful utterances can finish below the startup threshold.
        source.finish()
        if not attempted:
            publish()
        check_cancelled()
        waveform = np.frombuffer(source.read_frames(0, source.frame_count), dtype='<i2').astype(np.float32)
        waveform /= 32768.0
        return waveform, source if admitted else None
    except BaseException as exc:
        source.fail(exc)
        if (isinstance(exc, Exception) and not isinstance(exc, InterruptedError)
                and not admitted and not source.cancelled
                and not any(token is not None and token.cancelled for token in cancel_tokens)):
            return adapter.generate(text, **dict(kwargs)), None
        raise
    finally:
        for unsubscribe in subscriptions:
            unsubscribe()
        if not admitted:
            source.close()
            try:
                delete_audio(str(prefix_path))
            except Exception:
                pass
