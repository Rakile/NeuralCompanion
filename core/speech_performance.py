"""Opt-in metadata-only speech timing capture; never a playback authority.

Enable/disable applies on the next NC restart. No polling or GPU synchronization.
Uses the established bounded background JSONL writer in its own log file.
"""
from __future__ import annotations
import argparse
from collections import Counter
import atexit
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import uuid
from core.tts_latency_diagnostics import TtsLatencyDiagnostics

FILENAME='speech_performance.jsonl'
EVENTS=frozenset(('tts_incremental_queued','tts_generation_start','tts_first_pcm',
    'tts_incremental_ready','tts_generation_end','speech_playback_start',
    'speech_playback_end','speech_clock_state','muse_window_start','muse_window_end'))
IDS=frozenset(('speech_id','trace_id','chunk_id'))
NUMBERS=frozenset(('sequence','elapsed_ms','startup_buffer_seconds','duration_ms','gate_wait_ms',
    'order_wait_ms','generation_gate_wait_ms','frame_count','frames','sample_rate',
    'audio_duration_seconds','window_start','fps','worker_render_ms','staging_ms','publication_ms','input_wait_ms','between_window_wait_ms',
    'media_seconds','scheduled_through_seconds','started_monotonic','sampled_monotonic',
    'audio_started_monotonic','ended_monotonic','monotonic_time','generation_ms',
    'pcm_ready_seconds','avatar_ready_seconds','required_lead_seconds'))
BOOLEANS=frozenset(('source_finished',))
ENUMS=frozenset(('engine_mode','avatar_mode','tts_backend','outcome','playback_reason','state','kind'))


def _console_line(event, fields):
    sequence = fields.get('sequence', 0)
    elapsed = fields.get('duration_ms', 0) / 1000.
    if event == 'tts_generation_end' and fields.get('tts_backend') == 'liquidai':
        audio = fields.get('audio_duration_seconds', 0)
        rate = audio / elapsed if elapsed > 0 else 0.
        return (f"[TTS Timing] LiquidAI progressive chunk={sequence}: audio={audio:.3f}s "
                f"generation={elapsed:.3f}s rate={rate:.2f}x "
                f"order_wait={fields.get('order_wait_ms', 0)/1000:.3f}s "
                f"generation_gate={fields.get('generation_gate_wait_ms', 0)/1000:.3f}s "
                f"outcome={fields.get('outcome', 'unknown')}")
    if event == 'muse_window_end':
        fps = fields.get('fps', 0)
        media = fields.get('frames', 0) / fps if fps > 0 else 0.
        rate = media / elapsed if elapsed > 0 else 0.
        input_wait = f"{fields['input_wait_ms']/1000:.3f}s" if 'input_wait_ms' in fields else 'n/a'
        between = f"{fields['between_window_wait_ms']/1000:.3f}s" if 'between_window_wait_ms' in fields else 'n/a'
        return (f"[TTS Timing] MuseTalk progressive chunk={sequence} window={fields.get('window_start', 0)}: "
                f"media={media:.3f}s job={elapsed:.3f}s rate={rate:.2f}x "
                f"input_wait={input_wait} between_windows={between} "
                f"worker={fields.get('worker_render_ms', 0)/1000:.3f}s "
                f"staging_publish={(fields.get('staging_ms', 0)+fields.get('publication_ms', 0))/1000:.3f}s "
                f"outcome={fields.get('outcome', 'unknown')}")
    return None


def capture_marker(root):return Path(root)/'runtime/diagnostics/speech-performance.enabled'

def enable_capture(root):
    path=capture_marker(root);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('Temporary metadata-only speech capture; applies at next restart.\n',encoding='utf-8')
    return path

def disable_capture(root):capture_marker(root).unlink(missing_ok=True)


class SpeechPerformanceCapture:
    def __init__(self,root):
        self.root=Path(root)
        self.path=self.root/'runtime/logs'/FILENAME
        self._lock=threading.Lock();self._checked=False;self._closed=False;self._writer=None
        self._capture_id=uuid.uuid4().hex
        self._console_enabled=False

    def record(self,event,**fields):
        if event not in EVENTS:return
        # Only stage boundaries call this. The marker is read once per process.
        try:
            with self._lock:
                if self._closed:return
                if not self._checked:
                    self._checked=True
                    self._console_enabled=str(os.environ.get('NC_TTS_TIMING', '')).strip().lower() in {'1','true','yes','on'}
                    if capture_marker(self.root).is_file():
                        self._console_enabled=True
                        self._writer=TtsLatencyDiagnostics(self.root,filename=FILENAME)
                        atexit.register(self.close)
                writer=self._writer
            if writer is None and not self._console_enabled:return
            selected={'capture_id':self._capture_id}
            for key,value in fields.items():
                if key in IDS and isinstance(value,str) and value:
                    selected[key]=hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]
                elif key in NUMBERS and type(value) in (int,float) and math.isfinite(value) and abs(value)<1e15:
                    selected[key]=value
                elif key in BOOLEANS and type(value) is bool:
                    selected[key]=value
                elif key in ENUMS and isinstance(value,str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,47}',value):
                    selected[key]=value
            if writer is not None:writer.record_event(event,**selected)
            if self._console_enabled:
                line=_console_line(event, selected)
                if line:print(line, flush=True)
        except Exception:
            return  # Diagnostics cannot change synthesis, rendering or playback.

    def flush(self):
        with self._lock:writer=self._writer
        return writer.flush() if writer is not None else True

    def close(self):
        with self._lock:
            if self._closed:return
            self._closed=True;writer,self._writer=self._writer,None
        if writer is not None:
            try:writer.close()
            except Exception:pass


_default=SpeechPerformanceCapture(Path(__file__).resolve().parents[1])

def record_event(event,**fields):_default.record(event,**fields)


def summarize(rows):
    groups={};dropped=0;uncorrelated=0
    for row in rows:
        dropped+=int(row.get('dropped_before',0) or 0)
        if row.get('event') not in EVENTS:continue
        source=row.get('speech_id')
        if not source:uncorrelated+=1;continue
        key=(row.get('capture_id','legacy'),source,row.get('sequence',0))
        groups.setdefault(key,[]).append(row)
    chunks=[]
    for (capture,source,sequence),events in groups.items():
        events.sort(key=lambda r:r.get('monotonic_ms',0))
        def first(name):return next((r for r in events if r['event']==name),None)
        queued=first('tts_incremental_queued');generation=first('tts_generation_start')
        pcm=first('tts_first_pcm');ready=first('tts_incremental_ready')
        start=first('speech_playback_start');end=first('speech_playback_end');generated=first('tts_generation_end')
        def event_ms(row):
            if row is start and 'started_monotonic' in row:return row['started_monotonic']*1000
            if row is end and 'ended_monotonic' in row:return row['ended_monotonic']*1000
            return row['monotonic_ms']
        def delta(a,b):return round(max(0.,event_ms(b)-event_ms(a)),3) if a and b else None
        item=dict(capture_id=capture,speech_id=source,sequence=sequence,
            input_ready_to_audio_ms=delta(queued,start),queue_to_generation_ms=delta(queued,generation),
            generation_to_first_pcm_ms=delta(generation,pcm),pcm_to_header_ms=delta(pcm,ready),
            header_to_audio_ms=delta(ready,start),playback_wall_ms=delta(start,end),
            complete=bool(start and end and end.get('playback_reason','completed')=='completed'),
            playback_reason=end.get('playback_reason') if end else None)
        for key in ('gate_wait_ms','order_wait_ms','generation_gate_wait_ms'):
            if generated and key in generated:item[key]=generated[key]
        if generated:
            item['tts_outcome']=generated.get('outcome')
            duration=generated.get('duration_ms',0);audio=generated.get('audio_duration_seconds',0)
            item['tts_audio_seconds_per_second']=round(audio*1000/duration,3) if duration>0 else None
            item['audio_duration_seconds']=audio
        item['render_outcomes']=dict(Counter(r.get('outcome','unknown') for r in events if r['event']=='muse_window_end'))
        windows=[r for r in events if r['event']=='muse_window_end' and r.get('outcome')=='ok']
        total_ms=sum(r.get('duration_ms',0) for r in windows)
        frames=sum(r.get('frames',0) for r in windows)
        item['render_delivery_fps']=round(frames*1000/total_ms,3) if total_ms>0 else None
        starts=[r for r in events if r['event']=='muse_window_start']
        span=(windows[-1]['monotonic_ms']-starts[0]['monotonic_ms']) if windows and starts else 0
        item['render_including_gaps_fps']=round(frames*1000/span,3) if span>0 else None
        item['input_wait_ms']=(round(sum(r['input_wait_ms'] for r in windows),3)
            if windows and all('input_wait_ms' in r for r in windows) else None)
        item['render_windows']=len(windows)
        item['rendered_frames']=frames
        item['target_fps']=windows[0].get('fps') if windows else None
        for field in ('worker_render_ms','staging_ms','publication_ms'):
            item[field]=round(sum(r.get(field,0) for r in windows),3)
        # Wall intervals are observed by the existing playback owner, never in the DAC callback.
        state='running';cursor=event_ms(start) if start else None
        totals={'buffering':0.,'paused':0.};buffer_count=0
        if start:
            for event in events:
                when=event.get('sampled_monotonic',event.get('monotonic_ms',0)/1000)*1000
                if event['event']!='speech_clock_state' or when<event_ms(start) or (end and when>event_ms(end)):continue
                if cursor is not None and state in totals:totals[state]+=max(0.,when-cursor)
                state=event.get('state','running');cursor=when
                if state=='buffering':buffer_count+=1
            if end and cursor is not None and state in totals:totals[state]+=max(0.,event_ms(end)-cursor)
        item.update(buffering_ms=round(totals['buffering'],3),paused_ms=round(totals['paused'],3),buffering_intervals=buffer_count)
        item['buffer_events']=[{key:r[key] for key in ('media_seconds','pcm_ready_seconds','avatar_ready_seconds',
            'required_lead_seconds','source_finished') if key in r} for r in events
            if r['event']=='speech_clock_state' and r.get('state')=='buffering']
        if not start:
            item['buffering_ms']=item['paused_ms']=None
        chunks.append(item)
    return dict(chunks=chunks,dropped_events=dropped,uncorrelated_events=uncorrelated,
        measurement='Host wall-clock stages; observed buffering excludes user pause. Not a GPU utilization benchmark.')


def load_report(root,all_captures=False):
    path=Path(root)/'runtime/logs'/FILENAME;rows=[]
    for candidate in (path.with_suffix(path.suffix+'.1'),path):
        if not candidate.is_file():continue
        for line in candidate.read_text(encoding='utf-8',errors='replace').splitlines():
            try:
                row=json.loads(line)
                if type(row) is dict:rows.append(row)
            except ValueError:pass
    if rows and not all_captures:
        latest=rows[-1].get('capture_id');rows=[row for row in rows if row.get('capture_id')==latest]
    return summarize(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('enable','disable','report'))
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--all',action='store_true',dest='all_captures')
    args=parser.parse_args()
    if args.action=='enable':
        enable_capture(args.root);print('Speech performance capture enabled for next NC restart.')
    elif args.action=='disable':
        disable_capture(args.root);print('Speech performance capture disabled for next NC restart.')
    else:print(json.dumps(load_report(args.root,args.all_captures),indent=2))

if __name__=='__main__':main()
