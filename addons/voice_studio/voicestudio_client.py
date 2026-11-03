"""Optional loopback-only connector. Never installs or starts VoiceStudio.

API inspected against upstream 0834c8be28460fc4e0518bdb31eb57c494b253b2.
The initial supported design engines are OmniVoice and VoxCPM2. A freeform
catalog field alone does not prove that an arbitrary engine supports design.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from .creation_provider import request_http, stage_candidate
from .models import DesignRequest, EngineCapabilities, ProviderError

TAG_GROUPS = (
    ('male', 'female'),
    ('child', 'teenager', 'young adult', 'middle-aged', 'elderly'),
    ('very low pitch', 'low pitch', 'moderate pitch', 'high pitch', 'very high pitch'),
    ('whisper',),
    tuple(x + ' accent' for x in ('american', 'british', 'australian', 'canadian', 'indian', 'chinese', 'korean', 'japanese', 'portuguese', 'russian')),
)
VOCABULARY = tuple(tag for group in TAG_GROUPS for tag in group)


class VoiceStudioClient:
    def __init__(self, endpoint: str, storage: Path, *, transport=request_http):
        parsed = urlsplit(endpoint.strip())
        if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('Use a loopback HTTP URL such as http://127.0.0.1:3900.')
        self.endpoint = endpoint.strip().rstrip('/')
        self.storage = storage
        self.transport = transport
        self.version = ''

    @staticmethod
    def validate_tags(instruction: str, language: str) -> str:
        tags = tuple(x.strip().lower() for x in instruction.split(',') if x.strip())
        unsupported = [tag for tag in tags if tag not in VOCABULARY]
        if unsupported:
            raise ValueError('Unsupported OmniVoice traits: ' + ', '.join(unsupported))
        if any(sum(tag in group for tag in tags) > 1 for group in TAG_GROUPS):
            raise ValueError('Choose one attribute per OmniVoice category.')
        if language.lower() not in ('en', 'english') and any(tag.endswith(' accent') for tag in tags):
            raise ValueError('OmniVoice English accent tags require English speech.')
        if not tags:
            raise ValueError('Enter at least one supported OmniVoice attribute.')
        return ', '.join(tags)

    def capabilities(self) -> tuple[EngineCapabilities, ...]:
        catalog = self.transport('GET', self.endpoint + '/engines/tts', timeout=15).json()
        loaded = self.transport('GET', self.endpoint + '/model/loaded', timeout=15).json()
        info = self.transport('GET', self.endpoint + '/system/info', timeout=15).json()
        if not isinstance(catalog, dict) or not isinstance(catalog.get('backends'), list) or not isinstance(loaded, dict) or not isinstance(loaded.get('models'), list) or not isinstance(info, dict) or not info.get('app_version'):
            raise ProviderError('Unsupported VoiceStudio API schema. Check your installed version.')
        self.version = str(info['app_version'])
        loaded_ids = {str(m.get('engine_id') or '') for m in loaded['models'] if isinstance(m, dict)}
        result = []
        for engine in catalog['backends']:
            if not isinstance(engine, dict):
                raise ProviderError('Unsupported VoiceStudio engine catalog.')
            identity = str(engine.get('id') or '')
            mode = engine.get('instruct_vocabulary')
            if identity not in {'omnivoice', 'omnivoice-subprocess', 'voxcpm2'} or mode not in {'tags', 'freeform'}:
                continue
            result.append(EngineCapabilities(identity, str(engine.get('display_name') or identity), mode,
                                             VOCABULARY if mode == 'tags' else (),
                                             bool(engine.get('available')) and identity in loaded_ids))
        return tuple(result)

    def design(self, request: DesignRequest):
        if request.provider != 'local':
            raise ValueError('This job belongs to another provider.')
        capabilities = next((e for e in self.capabilities() if e.id == request.model_id), None)
        if capabilities is None or not capabilities.ready:
            raise ProviderError('Install and load the selected supported engine in VoiceStudio first; then check connection.')
        instruction = request.instruction.strip() or request.voice_description
        if capabilities.instruction_mode == 'tags':
            instruction = self.validate_tags(instruction, request.language)
        if not instruction or not request.preview_text.strip() or len(request.preview_text) > 5000:
            raise ValueError('Enter an instruction and 1–5000 characters of sample text.')
        fields = {'text': request.preview_text, 'engine': request.model_id, 'instruct': instruction,
                  'language': request.language, 'wav_bits': '16', 'stream': 'false'}
        if request.seed is not None:
            fields['seed'] = request.seed
        response = self.transport('POST', self.endpoint + '/generate', fields=fields, timeout=300)
        headers = {k.lower(): str(v) for k, v in response.headers.items()}
        if headers.get('x-omnivoice-dropped-chunks', '0') != '0':
            raise ProviderError('VoiceStudio returned partial audio; it was not saved.', unknown=True)
        if headers.get('content-type', '').split(';')[0] not in {'audio/wav', 'audio/x-wav', 'audio/wave'}:
            raise ProviderError('VoiceStudio did not return a WAV response.', unknown=True)
        return (stage_candidate(self.storage, request, response.data),)
