"""Explicit sound/music API requests; credentials remain on the desktop."""
from __future__ import annotations

import math
from addons.voice_studio.creation_provider import request_http, HttpResponse
from addons.voice_studio.models import ProviderError
from .models import boolean
from .media import MAX_BYTES


def generation_request(value: object) -> dict:
    if not isinstance(value, dict) or set(value)-{'kind','prompt','duration_seconds','loop','instrumental'}:
        raise ValueError('Invalid sound generation request.')
    kind, prompt, duration = value.get('kind'), value.get('prompt'), value.get('duration_seconds')
    if kind not in ('ambience','music','effect') or not isinstance(prompt,str) or not prompt.strip() or len(prompt)>4100:
        raise ValueError('Choose a type and describe the sound in up to 4100 characters.')
    if type(duration) not in (int,float) or not math.isfinite(duration): raise ValueError('Choose a valid duration.')
    if kind=='music' and duration not in (30,60,120,180): raise ValueError('Choose 30, 60, 120 or 180 seconds.')
    if kind!='music' and not .5<=duration<=30: raise ValueError('Choose between 0.5 and 30 seconds.')
    return {'kind':kind,'prompt':prompt.strip(),'duration_seconds':duration,
            'loop':boolean(value.get('loop',False)),'instrumental':boolean(value.get('instrumental',True))}


class ElevenLabsSoundClient:
    def __init__(self, key: str, *, transport=request_http):
        if not isinstance(key,str) or not key.strip(): raise ValueError('Configure ElevenLabs on the desktop first.')
        self._key=key; self._transport=transport

    def generate(self, request: dict) -> HttpResponse:
        req=generation_request(request)
        if req['kind']=='music':
            path='music'; body={'prompt':req['prompt'],'music_length_ms':int(req['duration_seconds']*1000),
                              'force_instrumental':req['instrumental'],'model_id':'music_v1'}
        else:
            path='sound-generation'; body={'text':req['prompt'],'duration_seconds':req['duration_seconds'],
                         'loop':req['loop'],'model_id':'eleven_text_to_sound_v2','prompt_influence':.3}
        result=self._transport('POST','https://api.elevenlabs.io/v1/'+path+'?output_format=mp3_44100_128',
                               headers={'xi-api-key':self._key,'Content-Type':'application/json'},json_body=body,timeout=300)
        if result.status!=200:
            raise ProviderError('Sound provider rejected the request.',unknown=result.status>=500,status=result.status)
        content_type=next((v.lower() for k,v in result.headers.items() if k.lower()=='content-type'),'')
        if not content_type.startswith(('audio/','application/octet-stream')) or not 0<len(result.data)<=MAX_BYTES:
            raise ProviderError('Sound provider returned invalid audio.',unknown=True)
        return result
