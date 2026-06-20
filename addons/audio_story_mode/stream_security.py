from __future__ import annotations

import secrets
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


TOKEN_QUERY_KEY = "token"
TOKEN_HEADER = "X-Audio-Story-Token"


def new_stream_access_token() -> str:
    return secrets.token_urlsafe(24)


def stream_url_with_token(url: str, token: str) -> str:
    value = str(url or "").strip()
    token = str(token or "").strip()
    if not value or not token:
        return value
    parsed = urlparse(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query[TOKEN_QUERY_KEY] = [token]
    encoded = urlencode(query, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, encoded, parsed.fragment))


def is_stream_request_authorized(path: str, headers, token: str) -> bool:
    expected = str(token or "").strip()
    if not expected:
        return True
    parsed = urlparse(str(path or ""))
    query = parse_qs(parsed.query or "")
    query_token = str((query.get(TOKEN_QUERY_KEY) or [""])[0] or "").strip()
    if secrets.compare_digest(query_token, expected):
        return True
    try:
        header_token = str(headers.get(TOKEN_HEADER, "") or "").strip()
    except Exception:
        header_token = ""
    return secrets.compare_digest(header_token, expected)
