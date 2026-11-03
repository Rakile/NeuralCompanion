"""Only the bounded MuseTalk live protocol may cross to the local phone backend."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

PREFIX = '/api/dev/musetalk-live/'
MAX_BODY = 4096


def is_live_route(method, path):
    if path.startswith('/api/remote-output/'):
        if method == 'POST':
            return path in {'/api/remote-output/'+route for route in ('open','recover','wait','ack','close','halt','restart','started','cached','progress','capabilities','reattach')}
        return method == 'GET' and bool(re.fullmatch(
            r'/api/remote-output/media/[a-f0-9]{32}/[0-9]{1,16}/[0-9]{1,16}\.mp4',path))
    if method == 'POST':
        return path in {PREFIX + route for route in (
            'arm', 'recover', 'prepare', 'prefetch', 'cancel', 'anticipation-cursor', 'idle-chunks', 'idle-chunk-cursor', 'wait-ready')}
    return method == 'GET' and bool(re.fullmatch(
        re.escape(PREFIX) + r'(?:status/[a-f0-9]{32}|idle/[a-f0-9]{32}\.mp4|'
        r'(?:segment|anticipation|idle-chunk)/[a-f0-9]{32}/[0-9]{8}\.mp4)', path))


def forward_live(backend, method, path, body=None):
    if not is_live_route(method, path):
        raise ValueError('Live visual route not allowed')
    encoded = None if body is None else json.dumps(body).encode('utf-8')
    if (encoded is not None and (method != 'POST' or not isinstance(body, dict) or len(encoded) > MAX_BODY)):
        raise ValueError('Live visual payload too large')
    # Error-only provenance. Never serialize exceptions, addresses or credentials.
    ordered = path.startswith('/api/remote-output/')
    def unavailable(reason):
        result = {'ok':False, 'error':'Live visual backend unavailable'}
        if ordered: result['diagnosticReason'] = 'ordered_relay_' + reason
        return 503, json.dumps(result).encode('utf-8'), 'application/json'
    url = urllib.parse.urlsplit(str(backend.get('local_url', '')))
    if (not backend.get('running') or not backend.get('pairing_code') or url.scheme != 'http'
            or url.hostname not in {'127.0.0.1', '::1', 'localhost'} or url.username or url.password
            or url.path not in {'', '/'} or url.query or url.fragment):
        return unavailable('not_running' if not backend.get('running') else
                           'credentials_missing' if not backend.get('pairing_code') else 'address_invalid')
    from .auth import _NoRedirect
    request = urllib.request.Request(urllib.parse.urlunsplit((url.scheme, url.netloc, path, '', '')),
                                     data=encoded, method=method, headers={
                                         'X-NC-Phone-Code': str(backend['pairing_code']),
                                         'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            limit = 16 * 1024 * 1024 if path.endswith('.mp4') else 512 * 1024
            data = response.read(limit + 1)
            if len(data) > limit:
                return unavailable('response_size')
            return int(response.status), data, 'video/mp4' if path.endswith('.mp4') else 'application/json'
    except urllib.error.HTTPError as exc:
        # Never forward backend exception text, credentials, or redirect locations.
        from ..live_control_diagnostics import REASONS
        result = {'ok': False, 'error': 'Live visual request rejected'}
        if ordered: result['diagnosticReason'] = 'ordered_relay_http_rejected'
        try:
            raw = exc.read(MAX_BODY + 1)
            value = json.loads(raw) if len(raw) <= MAX_BODY else None
            reason = value.get('diagnosticReason') if isinstance(value, dict) else None
            if isinstance(reason, str) and (reason in REASONS or path.startswith('/api/remote-output/')
                    and re.fullmatch(r'(?:ordered|output|phone_reply)_[a-z_]{1,80}',reason)):
                result['diagnosticReason'] = reason
        except Exception:
            # Optional diagnostics must not replace the original HTTP rejection.
            pass
        return exc.code, json.dumps(result).encode('utf-8'), 'application/json'
    except (OSError, ValueError) as exc:
        cause = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        return unavailable('timeout' if isinstance(cause, TimeoutError) else
                           'connection_refused' if isinstance(cause, ConnectionRefusedError) else
                           'invalid_response' if isinstance(cause, ValueError) else 'io_failed')
