"""Version 1 values only; consumers never need SDK objects or implementation imports."""
from __future__ import annotations

import json

SERVICE_NAME = 'mcp.core.v1'


def copy_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def result(status='ok', data=None):
    ok = status in {'ok', 'accepted', 'queued', 'running', 'pending', 'approved'}
    return {'ok': ok, 'status': status, 'error': None if ok else {'code': status},
            'data': copy_value(data)}
