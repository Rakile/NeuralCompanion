"""Small creation boundary and bounded HTTP transport (no automatic retries)."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Protocol
import uuid

from .library import MAX_AUDIO_BYTES, pcm_wav
from .models import DesignRequest, ProviderError, VoiceCandidate


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict
    data: bytes

    def json(self):
        try:
            return json.loads(self.data)
        except ValueError as error:
            raise ProviderError('Service returned invalid JSON.') from error


def request_http(method: str, url: str, *, headers=None, json_body=None, fields=None, timeout=180) -> HttpResponse:
    import requests
    deadline = time.monotonic() + timeout
    try:
        with requests.Session() as session:
            session.trust_env = False
            # files=(None, value) forces multipart form data without an upload.
            with session.request(method, url, headers=headers, json=json_body,
                                 files={k: (None, str(v)) for k, v in fields.items()} if fields is not None else None,
                                 stream=True, timeout=(8, timeout), allow_redirects=False) as response:
                if 300 <= response.status_code < 400:
                    raise ProviderError('Service redirect rejected. Check the configured address.')
                if response.status_code >= 400:
                    hints = {401: 'Check credentials.', 403: 'Check API permissions.', 409: 'Model or operation is unavailable.',
                             422: 'Check text and engine instructions.', 429: 'Rate limit or quota reached.'}
                    raise ProviderError(f'Service HTTP {response.status_code}. {hints.get(response.status_code, "Try again after checking service status.")}',
                                        unknown=method == 'POST' and response.status_code >= 500, status=response.status_code)
                chunks = bytearray()
                for chunk in response.iter_content(65536):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_AUDIO_BYTES or time.monotonic() > deadline:
                        raise ProviderError('Response exceeded its size/time limit.', unknown=method == 'POST')
                return HttpResponse(response.status_code, dict(response.headers), bytes(chunks))
    except requests.RequestException as error:
        raise ProviderError('Could not reach the service. A submitted generation may still be running.', unknown=method == 'POST') from error


class CreationProvider(Protocol):
    def design(self, request: DesignRequest) -> tuple[VoiceCandidate, ...]: ...


def stage_candidate(storage: Path, request: DesignRequest, data: bytes, generated_id='') -> VoiceCandidate:
    data = pcm_wav(data)
    folder = storage / 'candidates'
    folder.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    path = folder / (identity + '.wav')
    with path.open('xb') as output:
        output.write(data)
    return VoiceCandidate(identity, str(path), request, generated_id)
