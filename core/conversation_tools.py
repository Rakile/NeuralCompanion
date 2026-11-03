"""Explicit opt-in tool-round protocol, separate from ordinary provider text."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
import math

TOOL_OPTION = 'nc_conversation_tools_v1'


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolRound:
    text: str
    calls: tuple[ToolCall, ...]
    output: tuple[dict, ...]


@dataclass(frozen=True)
class ToolOutcome:
    call_id: str
    ok: bool
    content: dict
    receipt: str = ''
    # Set by the trusted bridge only after a completed MCP isError response.
    server_reported_error: bool = False


def plain_json(value):
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise ValueError('JSON object keys must be strings.')
        return {k: plain_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_json(v) for v in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError('Unsupported JSON value.')


def strict_arguments(raw: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate argument: {key}')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError(f'Nonfinite JSON value: {value}')
    if not isinstance(raw, str):
        raise ValueError('Tool arguments must be JSON text.')
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError('Tool arguments must be an object.')
    return value


def encode_tool_round(value: ToolRound) -> str:
    return json.dumps(dict(version=1, text=value.text,
        calls=[asdict(c) for c in value.calls], output=plain_json(value.output)), ensure_ascii=False, allow_nan=False)


def decode_tool_round(raw: str) -> ToolRound:
    value = strict_arguments(raw)
    if (set(value) != {'version', 'text', 'calls', 'output'} or type(value['version']) is not int
            or value['version'] != 1 or not isinstance(value['text'], str)
            or not isinstance(value['calls'], list) or not isinstance(value['output'], list)):
        raise ValueError('Invalid tool-round envelope.')
    calls, seen = [], set()
    for call in value['calls']:
        if (not isinstance(call, dict) or set(call) != {'call_id', 'name', 'arguments'}
                or any(not isinstance(call[k], str) for k in call)
                or not call['call_id'] or not call['name'] or call['call_id'] in seen):
            raise ValueError('Invalid tool call identity.')
        seen.add(call['call_id'])
        calls.append(ToolCall(**call))
    if any(not isinstance(item, dict) for item in value['output']):
        raise ValueError('Invalid native output items.')
    return ToolRound(value['text'], tuple(calls), tuple(value['output']))
