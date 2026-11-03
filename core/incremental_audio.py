"""Typed incremental signed-16-bit PCM and event-driven logical audio ownership.

One source belongs to one speech segment. Retained immutable pieces allow an
unstarted playback epoch to transfer without regenerating/reordering speech.
The playback owner closes the source after final DAC drain or cancellation.
No model, Qt, numpy or device dependency is imported here.
"""
from __future__ import annotations
from dataclasses import dataclass
import logging
import math
import threading
import wave
from collections.abc import Callable
from core.runtime.contracts import CancellationToken

@dataclass(frozen=True, slots=True)
class PCMBlock:
    data: bytes
    sample_rate: int = 24000
    channels: int = 1
    sequence: int = 0

    @property
    def frame_count(self) -> int:
        return len(self.data) // (2 * self.channels)

class IncrementalAudioSource:
    def __init__(self, sample_rate=24000, channels=1, startup_seconds=1.,
                 estimated_duration_seconds=0., output_directory=None):
        if isinstance(sample_rate,bool) or not isinstance(sample_rate,int) or sample_rate<=0:
            raise ValueError('PCM sample rate must be a positive integer')
        if isinstance(channels,bool) or not isinstance(channels,int) or channels not in (1,2):
            raise ValueError('PCM supports one or two channels')
        startup_seconds=float(startup_seconds)
        if not math.isfinite(startup_seconds) or startup_seconds<0:
            raise ValueError('Startup buffer must be a nonnegative sound duration')
        self.sample_rate=sample_rate;self.channels=channels
        self.startup_seconds=startup_seconds
        self.estimated_duration_seconds=max(0.,float(estimated_duration_seconds))
        self.output_directory=output_directory
        self.token=CancellationToken()
        self._condition=threading.Condition(threading.RLock())
        self._blocks=[];self._frames=0;self._next_sequence=0
        self._finished=False;self._closed=False;self._error=None
        self._playback_owned=False
        self._subscribers={};self._next_subscriber=0
        self._unsubscribe_cancel=self.token.subscribe(self._on_cancel)

    def _on_cancel(self):
        with self._condition:
            self._finished=True
            if self._error is None:self._error=InterruptedError(self.token.reason or 'Speech cancelled')
            self._condition.notify_all()
        self._notify()

    def _notify(self):
        with self._condition:callbacks=tuple(self._subscribers.values())
        for callback in callbacks:
            try:callback()
            except Exception:logging.getLogger(__name__).exception('PCM subscriber failed')

    def subscribe(self, callback: Callable[[],None]) -> Callable[[],None]:
        if not callable(callback):raise TypeError('PCM subscriber must be callable')
        with self._condition:
            key=self._next_subscriber;self._next_subscriber+=1
            if not self._closed:self._subscribers[key]=callback
        callback()
        def unsubscribe():
            with self._condition:self._subscribers.pop(key,None)
        return unsubscribe

    @property
    def frame_count(self):
        with self._condition:return self._frames
    @property
    def duration_seconds(self):
        with self._condition:return self._frames/self.sample_rate
    @property
    def retained_bytes(self):
        with self._condition:return sum(len(data) for _,data in self._blocks)
    @property
    def ready(self):
        with self._condition:
            return self._frames>0 and (self._finished or self._frames>=math.ceil(self.startup_seconds*self.sample_rate))
    @property
    def finished(self):
        with self._condition:return self._finished
    @property
    def cancelled(self):return self.token.cancelled
    @property
    def closed(self):
        with self._condition:return self._closed
    @property
    def error(self):
        with self._condition:return self._error
    @property
    def succeeded(self):
        with self._condition:return self._finished and self._error is None and not self.token.cancelled

    @property
    def playback_owned(self):
        with self._condition:return self._playback_owned

    def handoff(self) -> bool:
        """Irreversibly transfer a usable source to exact playback admission."""
        with self._condition:
            if self._closed or self._error is not None or self.token.cancelled:return False
            self._playback_owned=True
            return True

    def append(self, block: PCMBlock):
        if not isinstance(block,PCMBlock):raise TypeError('PCM producer must yield PCMBlock')
        if not isinstance(block.data,bytes) or not block.data or len(block.data)%(2*self.channels):
            raise ValueError('PCM data must contain complete s16le frames')
        if (isinstance(block.sample_rate,bool) or not isinstance(block.sample_rate,int)
                or isinstance(block.channels,bool) or not isinstance(block.channels,int)
                or block.sample_rate!=self.sample_rate or block.channels!=self.channels):
            raise ValueError('PCM format changed within a speech segment')
        with self._condition:
            if self._closed or self._finished:raise RuntimeError('PCM source is no longer accepting data')
            if isinstance(block.sequence,bool) or not isinstance(block.sequence,int) or block.sequence!=self._next_sequence:
                raise ValueError('PCM sequence must be contiguous and start at zero')
            self._blocks.append((self._frames,block.data));self._frames+=block.frame_count
            self._next_sequence+=1;self._condition.notify_all()
        self._notify()

    def finish(self):
        with self._condition:
            if self._closed or self._finished:return
            if not self._frames:raise ValueError('Speech generation produced no PCM')
            self._finished=True;self._condition.notify_all()
        self._notify()

    def fail(self,error):
        with self._condition:
            if self._closed:return
            if self._error is None:self._error=error if isinstance(error,BaseException) else RuntimeError(str(error))
            self._finished=True;self._condition.notify_all()
        self._notify()

    def cancel(self,reason='speech_cancelled'):self.token.cancel(reason)

    def wait_ready(self):
        with self._condition:
            self._condition.wait_for(lambda:self.ready or self._finished or self._closed)
            if self._error:raise self._error
            if self._closed:raise InterruptedError('PCM source closed')
            return self.ready

    def wait_finished(self):
        with self._condition:
            self._condition.wait_for(lambda:self._finished or self._closed)
            if self._error:raise self._error
            if self._closed:raise InterruptedError('PCM source closed')

    def read_frames(self,offset,max_frames=24000):
        if isinstance(offset,bool) or not isinstance(offset,int) or offset<0:raise ValueError('Invalid PCM cursor')
        if isinstance(max_frames,bool) or not isinstance(max_frames,int) or max_frames<=0:raise ValueError('Invalid PCM read size')
        with self._condition:
            if self._closed:raise InterruptedError('PCM source closed')
            stop=min(self._frames,offset+max_frames);pieces=[]
            if stop<=offset:return b''
            width=2*self.channels
            for start,data in self._blocks:
                end=start+len(data)//width
                if end<=offset:continue
                if start>=stop:break
                pieces.append(data[max(0,offset-start)*width:(min(end,stop)-start)*width])
            return b''.join(pieces)

    def write_wav(self,path):
        self.wait_finished()
        with wave.open(str(path),'wb') as output:
            output.setnchannels(self.channels);output.setsampwidth(2);output.setframerate(self.sample_rate)
            cursor=0
            while cursor<self.frame_count:
                data=self.read_frames(cursor);output.writeframesraw(data);cursor+=len(data)//(2*self.channels)

    def close(self):
        if not self.finished:self.cancel('speech_source_closed')
        with self._condition:
            if self._closed:return
            self._closed=True;self._blocks.clear();self._condition.notify_all()
        self._notify()
        with self._condition:self._subscribers.clear()
        self._unsubscribe_cancel()
