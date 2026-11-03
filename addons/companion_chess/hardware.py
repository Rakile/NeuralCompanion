"""Lazy, profile-specific Launchpad transport; owned by the addon worker."""
from __future__ import annotations

from itertools import islice
import time
from typing import Any
from .midi_profiles import get_profile


class Hardware:
    def __init__(self) -> None:
        self.orientation='white'
        self._profile=get_profile('launchpad_s')
        self._midi=None
        self._input=None
        self._output=None
        self._leds={}
        self._next_message = 0.0
        self._state=dict(activated=False,connected=False,inputs=[],outputs=[],error='')

    def snapshot(self) -> dict:
        return dict(self._state,orientation=self.orientation,model=self._profile.key,rgb=self._profile.rgb)

    def set_model(self, model: str) -> None:
        profile=get_profile(model)
        if profile.key != self._profile.key and self._state['connected']:
            raise ValueError('Disconnect hardware before changing the Launchpad model.')
        self._profile=profile

    def activate(self) -> dict:
        # Activation persists in the UI even if optional dependencies are missing.
        self._state.update(activated=True,error='')
        try:
            import mido
            self._midi=mido
            self._state.update(inputs=list(mido.get_input_names()),outputs=list(mido.get_output_names()))
        except Exception:
            self._state.update(error='MIDI unavailable. Install the optional mido and python-rtmidi dependencies.')
        return self.snapshot()

    def connect(self, input_name: str, output_name: str) -> None:
        if not self._state['activated'] or self._midi is None:
            raise ValueError('Activate hardware integration first.')
        if input_name not in self._state['inputs'] or output_name not in self._state['outputs']:
            raise ValueError('Select the Launchpad input and output ports.')
        self.disconnect()
        try:
            self._output=self._midi.open_output(output_name)
            self._input=self._midi.open_input(input_name)
            for control, value in self._profile.startup_controls():
                self._send(self._midi.Message('control_change', control=control, value=value))
            for data in self._profile.startup():
                self._send(self._midi.Message('sysex',data=data))
            self._state.update(connected=True,error='')
            self.set_leds({})
        except Exception:
            self.disconnect()
            raise

    def _send(self, message: Any, *, port: Any = None) -> None:
        """Pace MK1 USB writes on the existing addon worker, never on Qt."""
        output = self._output if port is None else port
        if self._profile.message_interval:
            delay = self._next_message - time.monotonic()
            if delay > 0: time.sleep(delay)
        output.send(message)
        if self._profile.message_interval:
            self._next_message = time.monotonic() + self._profile.message_interval

    def disconnect(self) -> None:
        incoming,outgoing=self._input,self._output
        self._input=self._output=None
        self._state['connected']=False
        if outgoing is not None:
            try:
                if self._profile.rgb:
                    values={self.note(file+rank):(0,0,0) for file in 'abcdefgh' for rank in '12345678'}
                    self._send(self._midi.Message('sysex',data=self._profile.rgb_packet(values)), port=outgoing)
                    for data in self._profile.shutdown():
                        self._send(self._midi.Message('sysex', data=data), port=outgoing)
                else:
                    self._send(self._midi.Message('control_change',control=0,value=0), port=outgoing)
            except Exception: pass
        for port in (incoming,outgoing):
            if port is not None:
                try: port.close()
                except Exception: pass
        self._leds={}
        self._next_message = 0.0

    def square(self, note: int) -> str:
        return self._profile.square(note,self.orientation)

    def note(self, square: str) -> int:
        return self._profile.note(square,self.orientation)

    def poll(self) -> list[str]:
        if self._input is None: return []
        if getattr(self._input,'closed',False): raise OSError('Launchpad input disconnected.')
        # Bound messages consumed, including ignored MIDI clock/control traffic.
        return [square for msg in islice(self._input.iter_pending(),128)
                if msg.type=='note_on' and msg.velocity>0 and (square:=self.square(msg.note))]

    def set_leds(self, values: dict[str,int], *, force: bool=False) -> None:
        if self._output is None: return
        if getattr(self._output,'closed',False): raise OSError('Launchpad output disconnected.')
        wanted={self.note(square):int(value)&0x33 for square,value in values.items()}
        if self._profile.rgb:
            # Keep the chess controller's existing red/green intensity semantics;
            # translate them to Pro RGB, rather than treating S bytes as palette IDs.
            rgb={file+rank:(round((wanted.get(self.note(file+rank),0)&3)*self._profile.max_rgb/3),
                 round(((wanted.get(self.note(file+rank),0)>>4)&3)*self._profile.max_rgb/3),0)
                 for file in 'abcdefgh' for rank in '12345678'}
            self.set_rgb_leds(rgb,force=force)
            return
        for row in range(8):
            for col in range(8):
                note=col+16*row
                value=wanted.get(note,0)
                if force or self._leds.get(note)!=value:
                    self._send(self._midi.Message('note_on',note=note,velocity=value | self._profile.legacy_flags))
        self._leds=wanted

    def set_rgb_leds(self, values: dict[str,tuple[int,int,int]], *, force: bool=False) -> None:
        if not self._profile.rgb: raise ValueError('Selected Launchpad does not support RGB.')
        wanted={self.note(square):color for square,color in values.items()}
        self._profile.rgb_packet(wanted)  # Validate before touching the device.
        if self._output is None: return
        if getattr(self._output,'closed',False): raise OSError('Launchpad output disconnected.')
        changed={note:color for note,color in wanted.items() if force or self._leds.get(note)!=color}
        if changed:
            self._send(self._midi.Message('sysex',data=self._profile.rgb_packet(changed)))
            self._leds.update(changed)

    def set_color_leds(self, values: dict[str,tuple[int,int,int]], *, force: bool=False) -> None:
        """Accept 8-bit RGB; S approximates using its nearest red/green levels.

        S cannot emit blue. Exclude off for nonzero colors so even pure blue
        remains visible; ties favor green. RGB profiles select their channel depth.
        """
        for color in values.values():
            if len(color)!=3 or any(type(c) is not int or not 0<=c<=255 for c in color):
                raise ValueError('LED colors must be RGB integers from 0 to 255.')
        if self._profile.rgb:
            self.set_rgb_leds({square:tuple(round(c*self._profile.max_rgb/255) for c in color)
                              for square,color in values.items()},force=force)
            return
        levels=[(r,g) for r in range(4) for g in range(4)]
        mapped={file+rank:0 for file in 'abcdefgh' for rank in '12345678'}
        for square,(red,green,blue) in values.items():
            if red or green or blue:
                r,g=min(levels[1:],key=lambda pair:(red-pair[0]*85)**2+(green-pair[1]*85)**2+blue**2)
                mapped[square]=r+(g<<4)
            else: mapped[square]=0
        self.set_leds(mapped,force=force)

    close=disconnect
