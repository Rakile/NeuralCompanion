"""Local recording playback and explicit Chatterbox reference auditions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import uuid

from .library import LibraryRepository, inspect_wav


@dataclass(frozen=True)
class AuditionResult:
    path: str
    reference: str
    fingerprint: str
    text: str
    revision: int


class AuditionService:
    def __init__(self, library: LibraryRepository, services, runtime_config=None):
        self.library = library
        self.services = services
        self.runtime_config = runtime_config

    def loaded_backend(self):
        """Use the selected loaded Chatterbox provider, without model startup."""
        providers = {'chatterbox': 'Chatterbox', 'chatterbox_multilingual': 'Chatterbox Multilingual'}
        selected = self.runtime_config.get('tts_backend', '') if self.runtime_config is not None else ''
        order = ([selected] if selected in providers else []) + [key for key in providers if key != selected]
        for key in order:
            backend = self.services.get(key)
            if bool(getattr(backend, 'audition_ready', False)) and callable(getattr(backend, 'generate_reference', None)):
                return providers[key], backend
        return '', None

    def generate(self, reference: str, text: str, revision: int, cancel: threading.Event) -> AuditionResult:
        if not text.strip():
            raise ValueError('Write text to speak first.')
        record = self.library.inspect(Path(reference))
        _, backend = self.loaded_backend()
        if backend is None:
            raise RuntimeError('Load Chatterbox or Chatterbox Multilingual in NC before testing a voice.')
        wav = backend.generate_reference(text, record.path, cancel)
        if cancel.is_set():
            raise InterruptedError('Audition cancelled; recording not published.')
        if self.library.inspect(Path(reference)).fingerprint != record.fingerprint:
            raise ValueError('Reference changed during generation. Generate a new test.')
        import numpy as np
        import soundfile as sf
        if hasattr(wav, 'detach'):
            wav = wav.detach().cpu().numpy()
        samples = np.asarray(wav).squeeze()
        if samples.ndim != 1 or not np.isfinite(samples).all():
            raise ValueError('Chatterbox returned invalid mono audio.')
        directory = self.library.storage / 'auditions'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (uuid.uuid4().hex + '.wav')
        sf.write(str(path), samples, int(backend.sr), subtype='PCM_16')
        inspect_wav(path.read_bytes())
        return AuditionResult(str(path), record.path, record.fingerprint, text, revision)

    @staticmethod
    def play(path: str, cancel: threading.Event) -> None:
        import sounddevice as sd
        import soundfile as sf
        from core.audio_playback import play_audio_file
        # play_audio_file owns the shared output guard. Do not acquire it twice
        # or call sd.stop() outside that owner. A waiting cancelled call is inert.
        play_audio_file(path, soundfile_module=sf, sounddevice_module=sd,
                        stop_event=cancel, audio_playing_event=threading.Event(), logger=lambda _: None)
