"""Immutable values shared by Voice Studio's UI and background operations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class VoiceRecord:
    path: str
    name: str
    sample_rate: int = 0
    duration: float = 0
    fingerprint: str = ''
    source: str = 'Existing WAV'
    valid: bool = True
    error: str = ''
    description: str = ''
    notes: str = ''
    archived: bool = False
    category: str = ''
    favorite: bool = False
    metadata_revision: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DesignRequest:
    character_id: str
    name: str
    voice_description: str
    preview_text: str
    provider: str = 'elevenlabs'
    model_id: str = 'eleven_ttv_v3'
    endpoint: str = ''
    instruction: str = ''
    seed: int | None = None
    language: str = 'en'


@dataclass(frozen=True)
class VoiceCandidate:
    id: str
    path: str
    request: DesignRequest
    generated_voice_id: str = ''


@dataclass(frozen=True)
class CharacterDraft:
    id: str
    name: str
    description: str
    voice_description: str
    preview_text: str


@dataclass(frozen=True)
class EngineCapabilities:
    id: str
    label: str
    instruction_mode: str
    vocabulary: tuple[str, ...] = ()
    ready: bool = False
    languages: tuple[str, ...] = ()


class ProviderError(RuntimeError):
    """Safe user-facing error; unknown=True forbids automatic replay."""
    def __init__(self, message: str, *, unknown: bool = False, status: int | None = None):
        super().__init__(message)
        self.unknown = unknown
        self.status = status
