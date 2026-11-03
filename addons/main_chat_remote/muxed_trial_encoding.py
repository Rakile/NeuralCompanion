"""Development-only muxed file encoding; no playback or reply authority."""
from pathlib import Path
import hashlib
import json
import subprocess
import wave
import time
from core.phone_media_tools import hidden, tools
from .encoding_timing import timed

MAX_BYTES = 16 * 1024 * 1024


def exact_segment_metadata(file, ffprobe, samples, video_samples, *, timings=None, verify_media=True):
    """Describe complete AAC packets and a sample-exact samples-sample edit.

    Only newly generated EOF-moov diagnostic files. Keep encoded packets and
    their offsets unchanged. The segment includes codec pre-roll, not a fade.
    """
    import struct
    def atom(kind,body):
        return struct.pack('>I',len(body)+8)+kind+body
    def children(data):
        cursor=0
        while cursor<len(data):
            size,kind=struct.unpack_from('>I4s',data,cursor)
            if size<8 or cursor+size>len(data): raise ValueError('Unsupported atom')
            yield kind,data[cursor+8:cursor+size]
            cursor+=size
    def replace(data,route,fn):
        out=[];found=0
        for kind,body in children(data):
            if kind==route[0]:
                found+=1
                body=replace(body,route[1:],fn) if len(route)>1 else fn(body)
            out.append(atom(kind,body))
        if found!=1: raise ValueError('Expected one metadata atom')
        return b''.join(out)
    # AVIO's explicit close flushes the complete JSON document. Windows live
    # stdout lost final delimiters after show_stream's last C-stdio fflush;
    # keep strict parsing and every packet/sample check, never repair the bytes.
    if verify_media:
        info=json.loads(timed(timings,'trim_probe_ms',subprocess.check_output,[ffprobe,'-v','error','-select_streams','a',
            '-show_packets','-of','json','-o','pipe:1',str(file)]))['packets']
        delay=-int(info[0]['pts']); packet_count=len(info)
        data=file.read_bytes()
    else:
        # Experimental no-probe path: read only the MP4 tables required to
        # construct the existing AAC edit. This is not a decoder/media scan.
        data=file.read_bytes()
        movie=next(body for kind,body in children(data) if kind==b'moov')
        audio=[]
        for kind,track in children(movie):
            if kind!=b'trak': continue
            mdia=next(body for kind,body in children(track) if kind==b'mdia')
            handler=next(body for kind,body in children(mdia) if kind==b'hdlr')
            if handler[8:12]==b'soun': audio.append((track,mdia))
        if len(audio)!=1: raise ValueError('Expected one audio track')
        track,mdia=audio[0]
        edts=next(body for kind,body in children(track) if kind==b'edts')
        edit_list=next(body for kind,body in children(edts) if kind==b'elst')
        if edit_list[0]!=0 or struct.unpack_from('>I',edit_list,4)[0]!=1:
            raise ValueError('Unexpected edit list')
        delay=struct.unpack_from('>i',edit_list,12)[0]
        minf=next(body for kind,body in children(mdia) if kind==b'minf')
        stbl=next(body for kind,body in children(minf) if kind==b'stbl')
        sizes=next(body for kind,body in children(stbl) if kind==b'stsz')
        packet_count=struct.unpack_from('>I',sizes,8)[0]
    raw=packet_count*1024; padding=raw-delay-samples
    if not (0<=delay<=2048 and 0<=padding<1024): raise ValueError('Unexpected trim')
    if list(children(data))[-1][0]!=b'moov': raise ValueError('EOF moov required')
    def mvhd(body):
        if body[0]!=0 or struct.unpack_from('>I',body,12)[0]!=1000:
            raise ValueError('Unexpected movie clock')
        return body[:12]+struct.pack('>II',48000,max(samples,video_samples))+body[20:]
    def edit(body):
        if body[0]!=0 or struct.unpack_from('>I',body,4)[0]!=1:
            raise ValueError('Unexpected edit list')
        if struct.unpack_from('>i',body,12)[0]!=delay:
            raise ValueError('Edit and packet pre-roll disagree')
        return body[:8]+struct.pack('>I',samples)+body[12:]
    def mdhd(body):
        if body[0]!=0 or struct.unpack_from('>I',body,12)[0]!=48000:
            raise ValueError('Unexpected audio clock')
        return body[:16]+struct.pack('>I',raw)+body[20:]
    def stts(body):
        entries=struct.unpack_from('>I',body,4)[0]
        rows=[struct.unpack_from('>II',body,8+i*8) for i in range(entries)]
        if sum(n for n,_ in rows)!=packet_count: raise ValueError('Packet count mismatch')
        return body[:8]+b''.join(struct.pack('>II',n,1024) for n,_ in rows)
    def tkhd(body, duration=samples):
        if body[0]!=0: raise ValueError('Unexpected track duration')
        return body[:20]+struct.pack('>I',duration)+body[24:]
    def moov(body):
        body=replace(body,[b'mvhd'],mvhd);out=[];count=0
        for kind,track in children(body):
            if kind==b'trak':
                mdia=next(b for k,b in children(track) if k==b'mdia')
                hdlr=next(b for k,b in children(mdia) if k==b'hdlr')
                if hdlr[8:12]==b'vide':
                    track=replace(track,[b'tkhd'],lambda body:tkhd(body,video_samples))
                    track=replace(track,[b'edts',b'elst'],lambda edit_body: edit_body[:8]+struct.pack('>I',video_samples)+edit_body[12:])
                if hdlr[8:12]==b'soun':
                    count+=1
                    track=replace(track,[b'edts',b'elst'],edit)
                    track=replace(track,[b'mdia',b'mdhd'],mdhd)
                    track=replace(track,[b'mdia',b'minf',b'stbl',b'stts'],stts)
                    track=replace(track,[b'tkhd'],tkhd)
            out.append(atom(kind,track))
        if count!=1: raise ValueError('Expected one audio track')
        return b''.join(out)
    before=[(p['pts'],p.get('size')) for p in info] if verify_media else None
    timed(timings,'trim_edit_ms',lambda: file.write_bytes(replace(data,[b'moov'],moov)))
    if verify_media:
        raw_probe=timed(timings,'trim_verify_ms',subprocess.check_output,[ffprobe,'-v','error','-select_streams','a',
            '-show_packets','-show_streams','-of','json','-o','pipe:1',str(file)])
        try:
            after=json.loads(raw_probe)
        except json.JSONDecodeError:
            file.with_suffix('.ffprobe-invalid-json.txt').write_bytes(raw_probe)
            raise
        if int(after['streams'][0]['duration_ts'])!=samples:
            raise ValueError('Presentation is not samples samples')
        if before!=[(p['pts'],p.get('size')) for p in after['packets']]:
            raise ValueError('Packet boundaries changed')
    return {'delaySamples':delay,'paddingSamples':padding,'rawSamples':raw}


class MuxedTrialEncoder:
    """One continuous AAC source; publish bounded video ranges incrementally."""
    def __init__(self, ffmpeg, wav, output_root, *, valid_samples, frame_count, cancelled, timings=None, verify_media=True):
        if type(verify_media) is not bool: raise ValueError('Invalid muxed validation selection')
        self.verify_media=verify_media
        if cancelled():
            raise InterruptedError('Muxed trial cancelled')
        if (type(valid_samples) is not int or type(frame_count) is not int
                or not 1 <= frame_count <= 1440 or not 1 <= valid_samples <= 2880000
                or abs(frame_count*2000-valid_samples)>=2000
                or valid_samples <= ((frame_count-1)//12)*24000):
            raise ValueError('Invalid exact source range')
        wav=Path(wav).resolve(strict=True)
        with wave.open(str(wav),'rb') as source:
            rate=source.getframerate()
            if (rate not in (24000,48000) or source.getnchannels()!=1 or source.getsampwidth()!=2
                    or source.getnframes()*(48000//rate)!=valid_samples):
                raise ValueError('Source WAV does not match exact resampled PCM range')
        self.ffmpeg=ffmpeg
        _,self.ffprobe=tools()
        self.root=Path(output_root)
        self.root.mkdir(parents=False,exist_ok=False)
        self.root=self.root.resolve(strict=True)
        self.valid_samples=valid_samples; self.frame_count=frame_count
        self.cancelled=cancelled; self.next_frame=0; self.bytes=0
        self.ranges={}
        self.audio=self.root/'continuous.m4a'
        timed(timings,'aac_encode_ms',self._run,['-i',wav,'-map','0:a:0','-c:a','aac','-b:a','128k','-ar','48000','-ac','1',self.audio])

    def _run(self,args):
        if self.cancelled():
            raise InterruptedError('Muxed trial cancelled')
        command=[str(self.ffmpeg),'-nostdin','-v','error','-n',*map(str,args)]
        process=subprocess.Popen(command,**hidden())
        deadline=time.monotonic()+30
        try:
            while process.poll() is None:
                if self.cancelled():
                    raise InterruptedError('Muxed trial cancelled')
                if time.monotonic()>=deadline:
                    raise TimeoutError('Muxed encode exceeded 30 seconds')
                time.sleep(.01)
            if self.cancelled():
                raise InterruptedError('Muxed trial cancelled')
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode,command)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def segment(self,video,start_frame,frame_count, *, timings=None):
        if self.cancelled():
            raise InterruptedError('Muxed trial cancelled')
        if (type(start_frame) is not int or type(frame_count) is not int
                or start_frame!=self.next_frame or start_frame%12
                or not 0<=start_frame<self.frame_count
                or frame_count!=min(12,self.frame_count-start_frame)):
            raise ValueError('Invalid next muxed source range')
        row=self._segment(video,start_frame,frame_count,start_frame//12,timings=timings)
        self.ranges[start_frame]=(frame_count,hashlib.sha256(Path(video).read_bytes()).digest())
        self.next_frame+=frame_count
        return row

    def rematerialize(self,video,start_frame,frame_count):
        """Recreate only an evicted, previously encoded range from the same AAC.

        Anticipation can evict speech lookahead without rewinding this source's
        monotonic encoder cursor. Exact video identity forbids substituting a
        new render; _segment still refuses existing files and keeps byte caps.
        """
        if self.cancelled():
            raise InterruptedError('Muxed trial cancelled')
        previous=self.ranges.get(start_frame)
        video=Path(video).resolve(strict=True)
        if (previous is None or previous[0]!=frame_count or start_frame>=self.next_frame
                or not 0<video.stat().st_size<=MAX_BYTES
                or previous[1]!=hashlib.sha256(video.read_bytes()).digest()):
            raise ValueError('Evicted muxed source range changed')
        return self._segment(video,start_frame,frame_count,start_frame//12)

    def _segment(self,video,start_frame,frame_count,index, *, timings=None):
        if self.cancelled():
            raise InterruptedError('Muxed trial cancelled')
        video=Path(video).resolve(strict=True)
        if not video.is_file() or not 0<video.stat().st_size<=MAX_BYTES:
            raise ValueError('Invalid source video')
        if self.verify_media:
            streams=json.loads(timed(timings,'video_probe_ms',subprocess.check_output,[self.ffprobe,'-v','error','-show_streams','-of','json',str(video)],timeout=10,**hidden()))['streams']
            if (len(streams)!=1 or streams[0]['codec_name']!='h264' or streams[0]['r_frame_rate']!='24/1'
                    or int(streams[0]['nb_frames'])!=frame_count):
                raise ValueError('Video does not match exact 24fps source range')
        start=start_frame*2000
        samples=frame_count*2000 if start_frame+frame_count<self.frame_count else self.valid_samples-start
        output=self.root/f'clip-{index:03d}.mp4'
        partial=self.root/f'clip-{index:03d}.partial.mp4'
        if output.exists() or partial.exists():
            raise FileExistsError('Refusing to overwrite a muxed segment')
        seek=max(0,start/48000-1024/48000)
        offset=0 if start_frame==0 else -1024/48000
        # A zero seek drops the first negative-PTS AAC priming packet.
        seek_args=[] if start_frame==0 else ['-ss',f'{seek:.12f}']
        try:
            timed(timings,'mux_copy_ms',self._run,[*seek_args,'-itsoffset',f'{offset:.12f}','-i',self.audio,'-i',video,
                '-map','1:v:0','-map','0:a:0','-c','copy','-t',f'{max(samples,frame_count*2000)/48000:.12f}',partial])
            if not 0<partial.stat().st_size<=MAX_BYTES or self.bytes+partial.stat().st_size>128*1024*1024:
                raise ValueError('Muxed segment exceeds byte cap')
            trim=exact_segment_metadata(partial,self.ffprobe,samples,frame_count*2000,timings=timings,verify_media=self.verify_media)
            if self.cancelled():
                raise InterruptedError('Muxed trial cancelled')
            partial.rename(output)
        finally:
            # This exact unpublished path was absent on entry. Join _run's
            # process before removing it; never delete an admitted clip.
            partial.unlink(missing_ok=True)
        size=output.stat().st_size
        self.bytes+=size
        return {'index':index,'startFrame':start_frame,'frameCount':frame_count,
                'file':output.name,'bytes':size,'validSamples':samples,**trim}


class MuxedTrialSilence:
    """One exact zero-sample AAC parent for a finite uncached idle epoch.

    Only silence repeats; speech always uses its continuous authenticated WAV.
    The caller supplies desktop-selected video ranges and owns final files.
    """
    def __init__(self,ffmpeg,output_root,*,cancelled):
        root=Path(output_root)
        wav=root.with_name(root.name+'.wav')
        if root.exists() or wav.exists():
            raise FileExistsError('Refusing to overwrite idle mux source')
        if cancelled():
            raise InterruptedError('Muxed idle cancelled')
        try:
            with wave.open(str(wav),'wb') as source:
                source.setnchannels(1);source.setsampwidth(2);source.setframerate(48000)
                source.writeframes(b'\0'*48000)
            self.encoder=MuxedTrialEncoder(ffmpeg,wav,root,valid_samples=24000,frame_count=12,cancelled=cancelled)
        finally:
            wav.unlink(missing_ok=True)

    def segment(self,video,index,*,frame_count=12):
        if (type(index) is not int or not 0<=index<=10005
                or type(frame_count) is not int or not 1<=frame_count<=12):
            raise ValueError('Invalid silent idle range')
        row=self.encoder._segment(video,0,frame_count,index)
        return {**row,'startFrame':index*12}


def encode_muxed_trial(ffmpeg,video_files,wav,output_root,*,valid_samples,cancelled):
    """Offline whole-set wrapper; live producer uses MuxedTrialEncoder directly."""
    if cancelled():
        raise InterruptedError('Muxed trial cancelled')
    if not 1<=len(video_files)<=120:
        raise ValueError('Invalid video segment count')
    _,ffprobe=tools()
    frames=[]
    for index,name in enumerate(video_files):
        info=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-of','json',str(name)],timeout=10,**hidden()))['streams']
        if len(info)!=1 or info[0]['codec_name']!='h264' or info[0]['r_frame_rate']!='24/1':
            raise ValueError('Source must be video-only H.264 at 24fps')
        count=int(info[0]['nb_frames'])
        if not 1<=count<=12 or (index<len(video_files)-1 and count!=12):
            raise ValueError('Invalid segment frame count')
        frames.append(count)
    output_root=Path(output_root)
    if output_root.exists():
        raise FileExistsError('Refusing to overwrite a trial')
    staging=output_root.with_name(output_root.name+'.partial')
    encoder=MuxedTrialEncoder(ffmpeg,wav,staging,valid_samples=valid_samples,frame_count=sum(frames),cancelled=cancelled)
    rows=[];start=0
    for video,count in zip(video_files,frames):
        rows.append(encoder.segment(video,start,count));start+=count
    if cancelled():
        raise InterruptedError('Muxed trial cancelled')
    staging.rename(output_root)
    return rows
