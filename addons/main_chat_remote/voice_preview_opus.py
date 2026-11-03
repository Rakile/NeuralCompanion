"""Encode saved character voice samples for authenticated phone previews.

The bridge calls this on its request worker, never on the Qt thread. Voice
Studio keeps the original WAV; only the temporary Ogg/Opus copy is sent.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import threading

import av

from .relay.opus_files import encode_opus_file


class VoicePreviewOpusCache:
    def __init__(self) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix="nc-voice-preview-opus-")
        self._lock = threading.Lock()

    def path_for(self, source: Path) -> Path:
        source = Path(source)
        if source.suffix.lower() != ".wav" or not source.is_file():
            raise ValueError("Voice preview requires a saved WAV sample.")
        stat = source.stat()
        if stat.st_size > 32 * 1024 * 1024:
            raise ValueError("Voice sample is too large to preview.")
        identity = f"{source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
        target = Path(self._directory.name) / (hashlib.sha256(identity.encode()).hexdigest() + ".ogg")
        with self._lock:
            if target.is_file():
                return target
            with av.open(str(source), options={"enable_drefs": "0"}) as audio:
                stream = next((item for item in audio.streams if item.type == "audio"), None)
                if stream is None:
                    raise ValueError("Voice sample has no audio track.")
                encode_opus_file(audio.decode(stream), target, container="ogg", bitrate=32000)
            return target

    def close(self) -> None:
        with self._lock:
            self._directory.cleanup()
