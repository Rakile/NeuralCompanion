"""Explicit device protocols; no MIDI imports, port enumeration or device I/O.

Each generation has its own documented layout/startup and LED protocol.
See README.md for Novation references and physical-device validation limits.
"""
from __future__ import annotations

from dataclasses import dataclass

PRO_HEADER = (0, 32, 41, 2, 16)


@dataclass(frozen=True)
class MidiProfile:
    key: str
    label: str
    rgb: bool = False
    device_id: int = 0x10
    rgb_7bit: bool = False
    mode_command: tuple[int, ...] = (0x21, 1)
    layout_command: tuple[int, ...] = (0x2c, 3)
    led_limit: int = 78
    legacy_setup: bool = False
    message_interval: float = 0.0
    description: str = ''

    @property
    def header(self) -> tuple[int, ...]:
        return (0, 32, 41, 2, self.device_id)

    @property
    def max_rgb(self) -> int:
        return 127 if self.rgb_7bit else 63

    @property
    def legacy_flags(self) -> int:
        return 12 if self.legacy_setup else 0

    def note(self, square: str, orientation: str) -> int:
        if len(square) != 2 or square[0] not in 'abcdefgh' or square[1] not in '12345678':
            raise ValueError('Invalid square.')
        col, row = ord(square[0])-97, int(square[1])-1
        if orientation == 'black': col, row = 7-col, 7-row
        return 11 + col + row*10 if self.rgb else col + (7-row)*16

    def square(self, note: int, orientation: str) -> str:
        if not 0 <= note <= 127: return ''
        if self.rgb:
            col, row = note % 10-1, note // 10-1
        else:
            col, row = note % 16, 7-note // 16
        if not 0 <= col < 8 or not 0 <= row < 8: return ''
        if orientation == 'black': col, row = 7-col, 7-row
        return 'abcdefgh'[col]+str(row+1)

    def startup(self) -> tuple[tuple[int, ...], ...]:
        if not self.rgb: return ()
        return tuple(self.header + command for command in (self.mode_command, self.layout_command) if command)

    def startup_controls(self) -> tuple[tuple[int, int], ...]:
        # Reset inherited buffers, then select XY on newly supported legacy units.
        return ((0, 0), (0, 1)) if self.legacy_setup else ()

    def shutdown(self) -> tuple[tuple[int, ...], ...]:
        # Modern units entered Programmer mode explicitly; release them to Live.
        return (self.header + (0x0e, 0),) if self.rgb_7bit else ()

    def rgb_packet(self, values: dict[int, tuple[int, int, int]]) -> tuple[int, ...]:
        if not self.rgb: raise ValueError('This model does not support RGB SysEx.')
        if len(values) > self.led_limit: raise ValueError('Too many RGB LED updates.')
        data = list(self.header + (0x03 if self.rgb_7bit else 0x0b,))
        for note, color in values.items():
            if not self.square(note, 'white') or len(color) != 3 or any(type(c) is not int or not 0 <= c <= self.max_rgb for c in color):
                raise ValueError('Invalid grid RGB colour/address.')
            if self.rgb_7bit: data.append(0x03)
            data.extend((note, *color))
        return tuple(data)


PROFILES = {
    'launchpad_s': MidiProfile('launchpad_s', 'Launchpad S',
        description='Launchpad S pad mapping and red/green LEDs.'),
    'launchpad_pro': MidiProfile('launchpad_pro', 'Launchpad Pro (original)', True,
        description='Select the Standalone USB input/output pair, not Live or DIN.'),
    'launchpad_mk1': MidiProfile('launchpad_mk1', 'Launchpad MK1 / Original (NOVLPD01)',
        legacy_setup=True, message_interval=1 / 400,
        description='Original red/green Launchpad. On Windows, install the Novation USB driver if NOVLPD01/Launchpad ports are missing.'),
    'launchpad_mk2': MidiProfile('launchpad_mk2', 'Launchpad MK2', True,
        device_id=0x18, mode_command=(), layout_command=(0x22, 0), led_limit=80,
        description='Uses Session grid layout with RGB LEDs. Select its matching USB input/output ports.'),
    'launchpad_mini_mk1': MidiProfile('launchpad_mini_mk1', 'Launchpad Mini MK1', legacy_setup=True,
        description='Original Mini XY grid and red/green LEDs. Select its matching USB input/output ports.'),
    'launchpad_mini_mk2': MidiProfile('launchpad_mini_mk2', 'Launchpad Mini MK2', legacy_setup=True,
        description='Mini MK2 XY grid and red/green LEDs. Select its matching USB input/output ports.'),
    'launchpad_mini_mk3': MidiProfile('launchpad_mini_mk3', 'Launchpad Mini MK3', True,
        device_id=0x0d, rgb_7bit=True, mode_command=(), layout_command=(0x0e, 1), led_limit=81,
        description='Select the USB MIDI pair (MIDIIN2/MIDIOUT2 on Windows), not the first DAW interface. Connect enters Programmer mode; disconnect returns to Live.'),
    'launchpad_x': MidiProfile('launchpad_x', 'Launchpad X', True,
        device_id=0x0c, rgb_7bit=True, mode_command=(), layout_command=(0x0e, 1), led_limit=81,
        description='Select the USB MIDI pair (MIDIIN2/MIDIOUT2 on Windows), not the first DAW interface. Connect enters Programmer mode; disconnect returns to Live.'),
    'launchpad_pro_mk3': MidiProfile('launchpad_pro_mk3', 'Launchpad Pro MK3', True,
        device_id=0x0e, rgb_7bit=True, mode_command=(), layout_command=(0x0e, 1), led_limit=106,
        description='Select the first USB MIDI pair, not DIN or DAW. Connect enters Programmer mode; disconnect returns to Live.'),
}


def profile_options() -> list[dict[str, str]]:
    return [dict(id=p.key, label=p.label, description=p.description) for p in PROFILES.values()]


def get_profile(key: str) -> MidiProfile:
    try: return PROFILES[key]
    except KeyError as exc: raise ValueError('Unsupported Launchpad model.') from exc
