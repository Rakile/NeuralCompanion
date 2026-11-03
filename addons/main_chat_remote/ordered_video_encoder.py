"""One private NVENC context, progressively finalized half-second videos.

No publication, audio, frame selection, or playback authority lives here. The
caller supplies immutable validated PNG snapshots; normal mux admission still
checks each completed H.264 file before it can enter Desktop's ordered stream.
"""
import csv
import errno
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

from core.dev_musetalk_live_readiness import complete_png
from core.phone_media_tools import hidden
from .encoding_timing import timed


class OrderedNVENCVideo:
    def __init__(self, ffmpeg, root, frame_count, read_frame, *, quality, cancelled, measure_timings=False):
        if (type(frame_count) is not int or not 1 <= frame_count <= 720
                or type(quality) is not dict or set(quality) != {'video_kbps','video_width','video_fps'}
                or any(type(value) is not int for value in quality.values())
                or quality['video_fps'] != 24 or not 100 <= quality['video_kbps'] <= 2000
                or not 160 <= quality['video_width'] <= 448 or quality['video_width'] % 2):
            raise ValueError('ordered_video_input')
        if cancelled(): raise InterruptedError('ordered_encode_cancelled')
        self.frame_count, self.cancelled = frame_count, cancelled
        self._closed = threading.Event()
        self._failure = None
        self._lock = threading.Lock()
        self._timing_start = time.perf_counter_ns() if measure_timings else None
        self._timing_chunks = {}
        self._next = 0
        self._ready = queue.Queue(maxsize=61)
        self._scratch = tempfile.TemporaryDirectory(prefix='ordered-video-', dir=root)
        self.root = Path(self._scratch.name)
        width = quality['video_width']
        filters = (f"scale=w='min(iw,{width})':h='min(ih,{width*3//2})':"
                   "force_original_aspect_ratio=decrease:force_divisible_by=2:"
                   "in_range=full:out_range=tv:out_color_matrix=bt601,setsar=1")
        command = [str(ffmpeg),'-nostdin','-hide_banner','-v','error','-xerror','-n',
            '-f','image2pipe','-c:v','png','-framerate','24','-threads','1',
            '-probesize','32','-analyzeduration','0','-i','pipe:0',
            '-an','-map','0:v:0','-vf',filters,'-r','24','-frames:v',str(frame_count),
            '-c:v','h264_nvenc','-preset','p4','-profile:v','baseline',
            '-b:v',str(quality['video_kbps']*1000),'-bf','0','-g','12','-delay','0',
            '-pix_fmt','yuv420p','-colorspace','smpte170m','-color_range','tv',
            '-f','segment','-segment_time','0.5','-reset_timestamps','1',
            '-segment_list','pipe:1','-segment_list_type','csv',str(self.root/'video-%03d.mp4')]
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, **hidden())
        except Exception:
            self._scratch.cleanup()
            raise
        self._writer = threading.Thread(target=self._feed, args=(read_frame,),
            name='nc-ordered-video-input', daemon=True)
        self._reader = threading.Thread(target=self._collect,
            name='nc-ordered-video-output', daemon=True)
        self._writer.start(); self._reader.start()

    def _active(self):
        return not self._closed.is_set() and not self.cancelled()

    def _fail(self, error):
        with self._lock:
            if self._failure is None: self._failure = error
        if self._process.poll() is None: self._process.kill()

    def _feed(self, read_frame):
        measured = {} if self._timing_start is not None else None
        def write(body):
            self._process.stdin.write(body)
            self._process.stdin.flush()
        try:
            for index in range(self.frame_count):
                if not self._active(): raise InterruptedError('ordered_encode_cancelled')
                body = timed(measured,'feed_read_ms',read_frame,index)
                if type(body) is not bytes or not 0 < len(body) <= 8*1024*1024 or not complete_png(body):
                    raise ValueError('ordered_frame_changed')
                timed(measured,'feed_write_ms',write,body)
                if measured is not None and (index % 12 == 11 or index == self.frame_count-1):
                    with self._lock:
                        self._timing_chunks.setdefault(index//12,{}).update(measured,
                            feed_frames=index%12+1,feed_completed_elapsed_ms=(time.perf_counter_ns()-self._timing_start)/1000000)
                    measured = {}
            self._process.stdin.close()
        except Exception as error:
            if self._active(): self._fail(error)

    def _collect(self):
        count = 0; total = 0
        try:
            while True:
                line = self._process.stdout.readline(513)
                if not line: break
                if len(line) > 512 or count >= (self.frame_count+11)//12:
                    raise ValueError('ordered_video_output')
                row = next(csv.reader([line.decode('utf-8')]))
                path = self.root/f'video-{count:03d}.mp4'
                if (len(row) != 3 or row[0] not in (path.name, str(path))
                        or abs(float(row[1])-count/2) > .000002
                        or abs(float(row[2])-min((count+1)/2,self.frame_count/24)) > .000002):
                    raise ValueError('ordered_video_output')
                size = path.stat().st_size
                total += size
                if not 0 < size <= 16*1024*1024 or total > 128*1024*1024:
                    raise ValueError('ordered_video_capacity')
                if self._timing_start is not None:
                    with self._lock:
                        self._timing_chunks.setdefault(count,{})['video_ready_elapsed_ms'] = (time.perf_counter_ns()-self._timing_start)/1000000
                self._ready.put_nowait((count,path)); count += 1
            status = self._process.wait(timeout=5)
            if self._active() and (status != 0 or count != (self.frame_count+11)//12):
                raise ValueError('ordered_gpu_encode_failed')
        except Exception as error:
            if self._active(): self._fail(error)
        finally:
            self._ready.put_nowait((count,None))

    def timing_snapshot(self, start):
        if self._timing_start is None: return {}
        with self._lock:
            values = dict(self._timing_chunks.get(start//12,{}))
        return dict(values,feed_timing_known='feed_frames' in values)

    def next_chunk(self, start, count):
        if (type(start) is not int or type(count) is not int or start != self._next
                or start % 12 or not 0 <= start < self.frame_count
                or count != min(12,self.frame_count-start)):
            raise ValueError('ordered_video_range')
        deadline = time.monotonic()+30
        while True:
            if not self._active(): raise InterruptedError('ordered_encode_cancelled')
            with self._lock: failure = self._failure
            if failure is not None: raise failure
            if time.monotonic() >= deadline:
                self._fail(TimeoutError('ordered_video_timeout'))
                raise TimeoutError('ordered_video_timeout')
            try: index, path = self._ready.get(timeout=.02)
            except queue.Empty: continue
            if index != start//12 or path is None: raise ValueError('ordered_video_output')
            self._next += count
            return path

    def close(self):
        self._closed.set()
        if self._process.poll() is None: self._process.kill()
        self._process.wait(timeout=5)
        self._writer.join(timeout=5); self._reader.join(timeout=5)
        if self._writer.is_alive() or self._reader.is_alive():
            raise ValueError('ordered_video_reader_join_pending')
        try:
            self._process.stdin.close()
        except OSError as error:
            # The exited child cannot drain a buffered write after cancellation.
            # Both pipe users have joined before this final handle release.
            if error.errno not in (errno.EPIPE, errno.EINVAL): raise
        self._process.stdout.close()
        self._scratch.cleanup()
