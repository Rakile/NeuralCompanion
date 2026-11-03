"""ElevenLabs voice design; independent from NC's selected TTS voice."""
from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote
from .creation_provider import request_http, stage_candidate
from .models import DesignRequest, ProviderError, VoiceCandidate


class ElevenLabsDesignClient:
    endpoint = 'https://api.elevenlabs.io'

    def __init__(self, key: str, storage: Path, *, transport=request_http):
        self._key = key
        self.storage = storage
        self.transport = transport

    def call(self, method, path, *, body=None):
        if not self._key:
            raise ValueError('Configure an ElevenLabs API key in Settings.')
        return self.transport(method, self.endpoint + path, headers={'xi-api-key': self._key}, json_body=body)

    def account(self) -> str:
        payload = self.call('GET', '/v1/user').json()
        identity = str(payload.get('user_id') or '')
        if not identity:
            raise ProviderError('ElevenLabs did not return an account identity.')
        return identity

    def design(self, request: DesignRequest) -> tuple[VoiceCandidate, ...]:
        if request.provider != 'elevenlabs':
            raise ValueError('This job belongs to another creation provider.')
        if not 20 <= len(request.voice_description) <= 1000 or not 100 <= len(request.preview_text) <= 1000:
            raise ValueError('ElevenLabs needs a 20–1000 character description and 100–1000 character sample.')
        if request.model_id not in {'eleven_multilingual_ttv_v2', 'eleven_ttv_v3'}:
            raise ValueError('Select a supported ElevenLabs Voice Design model.')
        body = {'voice_description': request.voice_description, 'text': request.preview_text,
                'model_id': request.model_id, 'auto_generate_text': False}
        if request.seed is not None:
            body['seed'] = request.seed
        try:
            payload = self.call('POST', '/v1/text-to-voice/design', body=body).json()
        except ProviderError as error:
            if error.status is None: error.unknown = True
            raise
        if not isinstance(payload, dict):
            raise ProviderError('Unexpected design response. Check the provider before retrying.', unknown=True)
        previews = payload.get('previews')
        if not isinstance(previews, list) or not previews:
            raise ProviderError('No voice previews were returned.', unknown=True)
        result = []
        for row in previews:
            try:
                audio = base64.b64decode(row['audio_base_64'], validate=True)
                candidate = stage_candidate(self.storage, request, audio, str(row['generated_voice_id']))
                result.append(candidate)
            except (KeyError, TypeError, ValueError):
                continue
        if not result:
            raise ProviderError('Returned previews could not be decoded. The request may have consumed credits.', unknown=True)
        return tuple(result)

    def create_voice(self, candidate: VoiceCandidate, marker: str) -> str:
        if candidate.request.provider != 'elevenlabs' or not candidate.generated_voice_id:
            raise ValueError('Only an ElevenLabs candidate can be saved as a cloud voice.')
        payload = self.call('POST', '/v1/text-to-voice', body={
            'voice_name': 'NC ' + marker, 'voice_description': candidate.request.voice_description,
            'generated_voice_id': candidate.generated_voice_id}).json()
        identity = str(payload.get('voice_id') or '')
        if not identity:
            raise ProviderError('Cloud creation outcome is unknown.', unknown=True)
        return identity

    def synthesize(self, identity: str, text: str, model: str) -> bytes:
        if not text.strip():
            raise ValueError('Write dialogue first.')
        return self.call('POST', '/v1/text-to-speech/' + quote(identity, safe=''),
                         body={'text': text, 'model_id': model}).data

    def delete_voice(self, identity: str) -> None:
        try:
            self.call('DELETE', '/v1/voices/' + quote(identity, safe=''))
        except ProviderError as error:
            if error.status != 404: raise
