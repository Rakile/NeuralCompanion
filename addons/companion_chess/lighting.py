"""Pure semantic board lighting shared by the two independent MIDI workers."""
from __future__ import annotations

import math
import re

PALETTE = dict(dark='#243847', light='#88b4c6', white='#51cce8', black='#f5aa60',
               target='#7d9b70', pending='#dca44a', selected='#9dba69', path='#6a88ad')


def validate_palette(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        key not in PALETTE or not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color)
        for key, color in value.items()
    ):
        raise ValueError('Use known palette roles and #RRGGBB colors.')
    return {key: color.lower() for key, color in value.items()}


def _valid(square: str) -> bool:
    return isinstance(square, str) and len(square) == 2 and square[0] in 'abcdefgh' and square[1] in '12345678'


def _route(source: str, target: str) -> list[str]:
    if not _valid(source) or not _valid(target):
        return []
    dx, dy = ord(target[0])-ord(source[0]), int(target[1])-int(source[1])
    if dx and dy and abs(dx) != abs(dy):
        return [source, target]
    sx, sy = (dx > 0)-(dx < 0), (dy > 0)-(dy < 0)
    return [chr(ord(source[0])+sx*i)+str(int(source[1])+sy*i) for i in range(max(abs(dx), abs(dy))+1)]


def ordered_route(game: dict) -> list[str]:
    pending = game.get('pending') or {}
    moves = game.get('moves') or []
    uci = pending.get('uci') or (moves[-1] if moves else '')
    return _route(uci[:2], uci[2:4]) if isinstance(uci, str) and re.fullmatch(r'[a-h][1-8][a-h][1-8][qrbn]?', uci) else []


def physical_route(pending: dict) -> set[str]:
    route = set(ordered_route({'pending': pending}))
    pickup = ''
    for step in pending.get('steps', []):
        square = step.get('square', '')
        if _valid(square):
            route.add(square)
        if step.get('kind') == 'pickup':
            pickup = square
        elif step.get('kind') == 'place' and pickup:
            route.update(_route(pickup, square))
            pickup = ''
    return route


def palette_frame(game: dict, selected: str, targets: list[str], light: dict, now: float) -> dict[str, tuple[int, int, int]]:
    palette = dict(PALETTE, **validate_palette(light.get('palette', {})))
    colors = {key: tuple(int(color[i:i+2], 16) for i in (1,3,5)) for key, color in palette.items()}
    roles = {file+rank: ('dark' if (ord(file)-97+int(rank)-1) % 2 == 0 else 'light')
             for file in 'abcdefgh' for rank in '12345678'}
    for piece in game.get('pieces', []):
        if piece.get('square') in roles and piece.get('color') in ('white', 'black'):
            roles[piece['square']] = piece['color']
    route = ordered_route(game) if light.get('flowing_path', False) and (not game.get('hardware') or game.get('pending')) else []
    for square in route:
        roles[square] = 'path'
    pending = game.get('pending') or {}
    if pending and game.get('hardware'):
        for square in physical_route(pending):
            roles[square] = 'path'
    for square in targets:
        if square in roles:
            roles[square] = 'target'
    if pending and game.get('hardware'):
        steps, index = pending.get('steps', []), pending.get('step', 0)
        if isinstance(index, int) and 0 <= index < len(steps) and steps[index].get('square') in roles:
            roles[steps[index]['square']] = 'pending'
    if selected in roles:
        roles[selected] = 'selected'
    brightness = max(0., min(1., float(light.get('led_brightness', .55))))
    result = {}
    for square, role in roles.items():
        strength = brightness
        if role == 'path' and square in route:
            strength *= .55+.45*(.5+.5*math.cos(2*math.pi*(now/3-route.index(square)/len(route))))
        result[square] = tuple(round(channel*strength) for channel in colors[role])
    return result
