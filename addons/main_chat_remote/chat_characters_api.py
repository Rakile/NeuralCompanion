"""Finite character API shared by authenticated LAN and peer requests."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit
from addons.multi_persona_roleplay.chat_characters import CharacterRevisionConflict
from addons.voice_studio.library import VoiceMetadataConflict

MAX_BODY = 32 * 1024
_ID = r'[A-Za-z0-9_-]{1,120}'
_FIELDS = {
    'settings': {'conversation_id', 'enabled', 'max_characters', 'character_voices_enabled',
                 'automatic_add_enabled', 'automatic_add_sound'},
    'remake': {'conversation_id'}, 'retry-automatic': {'conversation_id'},
    'update': {'patch'}, 'dismiss-notice': set(), 'remove': set(),
    'add-to-chat': {'conversation_id'}, 'assign-existing': {'conversation_id', 'candidate_id'},
    'remove-from-chat': {'conversation_id'},
    'discard': {'conversation_id'},
    'voice-jobs': {'provider', 'model_id', 'voice_description', 'preview_text', 'instruction', 'language'},
    'voice': {'voice_id', 'job_id', 'candidate_id', 'language'},
    'portrait-jobs': {'prompt', 'style'}, 'portrait': {'job_id', 'candidate_id'},
    'accept-candidate': set(), 'persona-copy': set(), 'cancel-job': set(),
    'remove-voice': set(),
    'voice-metadata': {'patch'},
}


def parse_route(method: str, path: str) -> dict:
    path = urlsplit(path).path
    match = re.fullmatch(r'/api/chat-characters/voices/(voice_[a-f0-9]{32})/(removal|remove|metadata)', path)
    if match and (method, match[2]) in {('GET', 'removal'), ('POST', 'remove'), ('POST', 'metadata')}:
        return {'action': {'removal': 'voice-removal', 'remove': 'remove-voice', 'metadata': 'voice-metadata'}[match[2]], 'voice_id': match[1]}
    if method == 'GET':
        if path == '/api/chat-characters':
            return {'action': 'snapshot'}
        if path == '/api/chat-characters/voices':
            return {'action': 'voices'}
        match = re.fullmatch(r'/api/chat-characters/(jobs|media)/(' + _ID + ')', path)
        if match:
            return {'action': 'job' if match[1] == 'jobs' else 'media', 'job_id' if match[1] == 'jobs' else 'asset_id': match[2]}
        match = re.fullmatch(r'/api/chat-characters/(cc_[A-Za-z0-9_-]{1,100})', path)
        if match:
            return {'action': 'get', 'id': match[1]}
    if method == 'POST':
        if path == '/api/chat-characters/settings':
            return {'action': 'settings'}
        match = re.fullmatch(r'/api/chat-characters/jobs/(' + _ID + ')/cancel', path)
        if match:
            return {'action': 'cancel-job', 'job_id': match[1]}
        match = re.fullmatch(r'/api/chat-characters/(cc_[A-Za-z0-9_-]{1,100})/([a-z-]+)', path)
        if match and match[2] in _FIELDS and match[2] not in {'settings', 'cancel-job', 'remove-voice', 'voice-metadata'}:
            return {'action': match[2], 'id': match[1]}
    raise ValueError('Chat character route not allowed.')


def dispatch(service, method: str, path: str, body=None):
    try:
        request = parse_route(method, path)
        if service is None or not callable(getattr(service, 'chat_characters', None)):
            return 503, {'ok': False, 'error': 'Chat Character Library is unavailable. Update and restart NC desktop.'}
        if method == 'POST':
            if not isinstance(body, dict) or len(json.dumps(body).encode()) > MAX_BODY:
                raise ValueError('Character request is too large or invalid.')
            allowed = _FIELDS[request['action']] | {'expected_revision', 'operation_id'}
            if set(body) - allowed:
                raise ValueError('Unknown character request fields.')
            if type(body.get('expected_revision')) is not int or body['expected_revision'] < 0:
                raise ValueError('A valid character revision is required.')
            if not isinstance(body.get('operation_id'), str) or not re.fullmatch(_ID, body['operation_id']):
                raise ValueError('An operation identity is required.')
            if request['action'] in {'add-to-chat', 'assign-existing', 'remove-from-chat', 'discard', 'remake', 'retry-automatic'} and not isinstance(body.get('conversation_id'), str):
                raise ValueError('An active conversation is required.')
            if request['action'] == 'assign-existing' and not isinstance(body.get('candidate_id'), str):
                raise ValueError('A discovered character is required.')
            request.update(body)
            if request['action'] == 'dismiss-notice':
                request.update(action='update', patch={'notice_dismissed': True})
        query = parse_qs(urlsplit(path).query)
        if request['action'] == 'snapshot':
            request['all_conversations'] = query.get('all', ['0'])[0] == '1'
        result = service.chat_characters(request)
        if result.get('available') is False:
            return 503, {'ok': False, 'error': 'Chat Character Library is unavailable.'}
        if request['action'] == 'snapshot':
            limit = max(1, min(100, int(query.get('limit', ['30'])[0])))
            offset = max(0, int(query.get('offset', ['0'])[0]))
            cards = result['characters']
            result = {**result, 'characters': cards[offset:offset+limit], 'total': len(cards),
                      'next_offset': offset+limit if offset+limit < len(cards) else None}
        return 200, {'ok': True, 'result': result}
    except VoiceMetadataConflict:
        return 409, {'ok': False, 'error': 'Voice details changed. Reload voice details before saving.'}
    except CharacterRevisionConflict:
        return 409, {'ok': False, 'error': 'Character changed. Refresh before saving.'}
    except KeyError:
        return 404, {'ok': False, 'error': 'Character or generation job not found.'}
    except (TypeError, ValueError) as exc:
        return 400, {'ok': False, 'error': str(exc) if type(exc) is ValueError else 'Invalid character request.'}
    except Exception:
        return 503, {'ok': False, 'error': 'Character service is unavailable. Check NC desktop and retry.'}
