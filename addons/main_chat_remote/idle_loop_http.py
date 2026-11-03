"""Exact idle-cache routes shared by authenticated LAN and peer forwarding."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

PREFIX = '/api/idle-cache/'
ORDERED_PREFIX = PREFIX+'ordered/'
MAX_RANGE = 16*1024*1024


def parse_route(method, path):
    parsed = urllib.parse.urlsplit(path)
    if method != 'GET' or parsed.scheme or parsed.netloc or parsed.fragment or len(path) > 1024:
        raise ValueError('Invalid idle route')
    prefix = ORDERED_PREFIX if parsed.path.startswith(ORDERED_PREFIX) else PREFIX
    if parsed.path in {prefix+'manifest',prefix+'settings'} and not parsed.query:
        return None
    if path == prefix+'manifest?frame_handoff=1':
        return None
    match = re.fullmatch(re.escape(prefix)+r'file/([a-f0-9]{64})', parsed.path)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if (not match or set(query) != {'generation','offset','length'} or any(len(v) != 1 for v in query.values())
            or not re.fullmatch(r'[a-f0-9]{64}', query['generation'][0])
            or not re.fullmatch(r'[0-9]{1,8}', query['offset'][0])
            or not re.fullmatch(r'[0-9]{1,8}', query['length'][0])):
        raise ValueError('Invalid idle range')
    offset, length = int(query['offset'][0]), int(query['length'][0])
    if not 0 < length <= MAX_RANGE or offset+length > 16*1024*1024:
        raise ValueError('Invalid idle range')
    return dict(identity=match.group(1), generation=query['generation'][0], offset=offset, length=length)


def forward_idle(backend, method, path):
    limits = parse_route(method, path)
    unavailable = (503, b'{"error":"Idle cache backend unavailable"}', 'application/json')
    url = urllib.parse.urlsplit(str(backend.get('local_url', '')))
    if (not backend.get('running') or not backend.get('pairing_code') or url.scheme != 'http'
            or url.hostname not in {'127.0.0.1','::1','localhost'} or url.username or url.password
            or url.path not in {'','/'} or url.query or url.fragment):
        return unavailable
    from .relay.auth import _NoRedirect
    request = urllib.request.Request(urllib.parse.urlunsplit((url.scheme,url.netloc,'','',''))+path,
                                     headers={'X-NC-Phone-Code':str(backend['pairing_code'])})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=10) as response:
            limit = limits['length'] if limits else 128*1024
            data = response.read(limit+1)
            if len(data) > limit:
                return unavailable
            return response.status, data, 'video/mp4' if limits and response.status == 200 else 'application/json'
    except urllib.error.HTTPError as error:
        return error.code, b'{"error":"Idle cache request rejected"}', 'application/json'
    except (OSError, ValueError):
        return unavailable
