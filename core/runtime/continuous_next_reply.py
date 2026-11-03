"""Private, single-use normal-chat successor for Continuous Mode."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import threading

from core.runtime.contracts import CancellationToken


@dataclass(frozen=True, slots=True)
class ContinuousStageBinding:
    session_generation: int
    conversation_revision: int
    source_turn_id: str
    owner_id: str
    persona_id: str
    provider_id: str
    model_id: str
    settings_revision: int
    voice_fingerprint: str


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()
                if key not in {'normal_chat_transaction_id', 'request_id', 'lease'}}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError('Continuous stage request contains an unsupported value.')


def request_fingerprint(request: object) -> str:
    """Hash provider-visible data, excluding only transaction-local identifiers."""
    if hasattr(request, 'params_copy') and hasattr(request, 'additional_params_copy'):
        context = request.context
        value = {'provider': context.provider_name, 'model': context.model_name,
                 'params': request.params_copy(),
                 'additional_params': request.additional_params_copy()}
    elif isinstance(request, Mapping):
        value = request
    else:
        raise TypeError('Continuous stage requires a frozen provider request.')
    payload = json.dumps(_canonical(value), sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def voice_settings_fingerprint(config: Mapping[str, object]) -> str:
    """Bind a staged reply to the voice route selected for this conversation."""
    keys = ('tts_backend', 'voice_path', 'tts_use_cloned_voice',
            'liquidai_tts_voice', 'liquidai_tts_language',
            'tts_language', 'tts_seed', 'tts_temperature', 'tts_top_p',
            'tts_top_k', 'tts_repeat_penalty', 'tts_min_p',
            'tts_normalize_loudness', 'chat_character_conversation_id')
    payload = {key: config.get(key) for key in keys}
    return hashlib.sha256(json.dumps(_canonical(payload), sort_keys=True,
        separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def character_voice_fingerprint(context: object) -> str:
    """Capture the voice routing and guidance behind a structured reply."""
    if context is None:
        return ''
    characters = getattr(context, 'characters', ())
    cast = [
        (character.id, character.name, character.voice_path,
         character.voice_language, character.system_prompt)
        for character in characters
    ]
    payload = (bool(getattr(context, 'allow_new_characters', False)), cast)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()


@dataclass(slots=True)
class StagedAssistantReply:
    stage_id: str
    binding: ContinuousStageBinding
    text: str
    provider_request_fingerprint: str
    voice_segments: tuple[object, ...]
    private_audio: tuple[object, ...]
    token: CancellationToken
    created_at: float
    raw_response: str = ''
    character_voice_fingerprint: str = ''
    user_content: str = ''
    user_created_at: float | None = None
    _consumed: bool = field(default=False, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def consume(self, binding: ContinuousStageBinding, request: object, *, now: float) -> bool:
        with self._lock:
            if (self._consumed or self.token.cancelled or binding != self.binding
                    or now - self.created_at >= 300 or now < self.created_at
                    or request_fingerprint(request) != self.provider_request_fingerprint):
                return False
            self._consumed = True
            return True
