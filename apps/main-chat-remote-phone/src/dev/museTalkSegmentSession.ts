// Dev-only bounded visual controller. Audio is an input clock, never a command target.
import type { VideoPlayer } from 'expo-video';
import type { ProbeVideoSegment } from './museTalkMatchedSample';
import { segmentAt } from './museTalkSegmentClock';
import { videoStep } from './museTalkProbeClock';
import type { PendingSeek } from './museTalkProbeClock';
import type { IdleFile } from './museTalkIdleFile';
import type {PhonePresentationPosition} from '../utils/phonePresentation';

export type SegmentArrival = 'available' | 'late' | 'missing';
type Entry = {segment: ProbeVideoSegment; player: VideoPlayer | null; ready: boolean; first: boolean;
  localBinding?:Promise<()=>Promise<void>>;localBound?:boolean;releasePending?:boolean;
  retired: boolean; pending: boolean; remove: () => void; started: number; seek: PendingSeek; terminalHeld: boolean; idlePrimed: boolean;
  progressSamples: number; playingSamples: number; diagnosticTimers: ReturnType<typeof setTimeout>[];
  loadAbort: AbortController; idleFile?: IdleFile; localLease?:{release():Promise<void>}};
export type SegmentBudget = Set<Entry>;
export type IdleVideo = ProbeVideoSegment & {entryFrame: number; diagnosticEmotion?: string; avatarId?: string; mediaId?: string; continuationReady?: boolean};
let surfaceSequence = 0;
type Options = {
  anticipationTrack?: boolean;
  liveReply?: boolean;
  keepIdleReady?: boolean;
  speechClips?: 2 | 4;
  budget?: SegmentBudget;
  segments: readonly ProbeVideoSegment[]; durationSeconds: number; arrival: SegmentArrival;
  resolveMedia: (uri: string, signal?: AbortSignal) => Promise<string>; createPlayer: () => VideoPlayer;
  attachLocalVideo?: (player:VideoPlayer,segment:ProbeVideoSegment,uri:string)=>Promise<()=>Promise<void>>;
  retainLocalMedia?: (uri:string,signal:AbortSignal)=>Promise<{release():Promise<void>}>;
  loadIdle?: (uri: string, bytes: number, signal: AbortSignal) => Promise<IdleFile>;
  now: () => number; changed: () => void; onPrepared: () => void; onUnavailable: () => void;
  onNativeProgress?: (index: number, seconds: number, terminal: boolean) => void;
  startupDeadline?: () => number | undefined;
  report: (event: string, data: Record<string, unknown>) => void;
};

export class SegmentSession {
  readonly surfaceKey = ++surfaceSequence;
  private held = false;
  private anticipationReserved = false;
  private retainedIdle = false;
  private slots = new Map<number, Entry>();
  private reservations: SegmentBudget;
  private missed = new Set<number>();
  private recovered = new Set<number>();
  private attempted = new Set<number>();
  private closed = false;
  private gateDone = false;
  private started: number;
  private seconds: number | null = null;
  private boundary = -1;
  private peakPlayers = 0;
  private peakDownloads = 0;
  private peakBytes = 0;
  private seeks = 0;
  private startupLayouts = new Set<number>();
  private startupCommits = new Set<number>();
  private idle: IdleVideo | null = null;
  private idleVerified = true;
  private idleSince: number | null = null;
  private lastSelection = '';
  private lastBuffer = '';
  selectedIndex: number | null = null;
  targetIndex: number | null = null;
  constructor(private options: Options) {
    this.started = options.now(); this.reservations = options.budget ?? new Set<Entry>();
  }
  get entries(): Entry[] { return [...this.slots.values()]; }
  private get speechClips(): number {
    return this.options.liveReply && !this.options.anticipationTrack && this.options.speechClips === 4 ? 4 : 2;
  }
  idlePosition(): PhonePresentationPosition | null {
    const idle = this.idle, entry = this.selectedIndex === null ? undefined : this.slots.get(this.selectedIndex);
    if (this.closed || !idle?.avatarId || !idle.mediaId || entry?.segment.index !== idle.index
      || entry.retired || entry.seek || !entry.ready || !entry.first || !entry.player) return null;
    try {
      const time = entry.player.currentTime;
      if (!Number.isFinite(time) || time < 0) return null;
      return {avatarId:idle.avatarId,mediaId:idle.mediaId,sourceFrameCount:idle.frameCount,
        sourceFrame:Math.floor(time*24)%idle.frameCount,fps:24,playing:entry.player.playing};
    } catch { return null; }
  }
  get retainedIdlePending(): boolean {
    return !this.closed && this.held && this.retainedIdle && this.selectedIndex !== this.idle?.index
      && Boolean(this.idle && this.slots.has(this.idle.index));
  }
  continueRetainedIdle() {
    if (!this.retainedIdlePending) return;
    // The reply clock has stopped, but its already admitted idle still owns its
    // file/player. Finish that native seek instead of discarding the emotion.
    this.prewarmIdle();
    if (this.idle && this.slots.get(this.idle.index)?.idlePrimed) this.showIdle();
  }
  reserveForAnticipation(enabled = true) {
    if (this.closed || this.anticipationReserved === enabled) return;
    this.anticipationReserved = enabled;
    if (!enabled) return;
    // Preserve the actually selected surface (including an outgoing idle) but
    // release speculative speech lookahead/idle reservations before the
    // supplied anticipation current range is admitted.
    for (const entry of this.entries) if (entry.segment.index !== this.selectedIndex && entry.segment.index !== 0) {
      this.retire(entry); this.attempted.delete(entry.segment.index);
    }
    this.report('anticipation_reservation',{selectedIndex:this.selectedIndex,retained:Boolean(this.selectedIndex !== null)});
    this.options.changed();
  }
  setIdle(idle: IdleVideo | null, verified = true) {
    if (this.idle?.uri !== idle?.uri) this.report('idle_identity_changed',{
      previousIndex:this.idle?.index ?? null,index:idle?.index ?? null,
      selectedIndex:this.selectedIndex,targetIndex:this.targetIndex,
      audioSeconds:this.seconds,previousVerified:this.idleVerified,verified,
    });
    if (this.idle?.uri !== idle?.uri) this.idleSince = null;
    if (idle && idle.uri === this.idle?.uri && idle.entryFrame !== this.idle.entryFrame) {
      const entry = this.slots.get(idle.index);
      if (entry) {
        entry.segment = idle;
        if (!entry.player?.loop) {entry.idlePrimed = false;entry.seek = null;}
      }
    }
    this.idle = idle;
    this.idleVerified = verified;
    this.traceBuffer();
  }
  setTimeline(segments: readonly ProbeVideoSegment[], durationSeconds: number) {
    if (this.closed || !this.options.liveReply || segments === this.options.segments) return;
    // Appending an admitted successor must not invalidate current native surfaces.
    if (segments.length < this.options.segments.length || this.options.segments.some((row,i) => row !== segments[i])) return;
    if (!this.options.segments.length && segments[0]?.index === 0) {
      // Idle can have been mounted for minutes before the first admitted reply.
      // Its expired probe/readiness timer is not that reply's startup deadline.
      this.started = this.options.now(); this.gateDone = false;
    }
    this.options.segments = segments;
    this.options.durationSeconds = durationSeconds;
    this.traceBuffer();
  }
  private report(event: string, data: Record<string, unknown>) {
    try { this.options.report(event, {...data,track:this.options.anticipationTrack ? 'anticipation' : 'reply',
      surfaceKey:this.surfaceKey,atMs:this.options.now(),presentationMeasured: false}); }
    catch { /* Diagnostic failures must not affect video or its audio clock. */ }
  }
  private traceSelection(paused: boolean, preparing: boolean, waiting: string) {
    this.traceBuffer();
    const entry = this.selectedIndex === null ? undefined : this.slots.get(this.selectedIndex);
    const role = !entry ? 'none' : entry.segment.index < 0 ? 'idle'
      : this.held || this.selectedIndex !== this.targetIndex ? 'held_speech' : 'speech';
    const target = this.targetIndex === null ? undefined : this.slots.get(this.targetIndex);
    const state = {role,selectedIndex:this.selectedIndex,targetIndex:this.targetIndex,
      paused,preparing,waiting,held:this.held,idleVerified:this.idleVerified,
      ready:Boolean(entry?.ready),firstFrame:Boolean(entry?.first),
      targetReady:Boolean(target?.ready),targetFirstFrame:Boolean(target?.first),targetPending:Boolean(target?.pending)};
    const key = JSON.stringify(state);
    if (key === this.lastSelection) return;
    this.lastSelection = key;
    let nativeSeconds: number | null = null;
    try { nativeSeconds = entry?.player?.currentTime ?? null; } catch { /* Released native surface. */ }
    this.report('visual_selection',{...state,audioSeconds:this.seconds,
      nativeSeconds,reservations:this.reservations.size});
  }
  private traceBuffer() {
    // Descriptor count is planned video, NOT downloaded/decoded video. Readiness
    // requires both native readyToPlay and a first-frame callback on a live slot.
    const entries = this.entries.filter(entry => !entry.retired);
    const nativeReady = (entry: Entry) => {
      try { return Boolean(entry.player && entry.ready && entry.player.status === 'readyToPlay'); }
      catch { return false; }
    };
    const nativeReadyIndices = new Set(entries.filter(nativeReady).map(entry => entry.segment.index));
    const ready = entries.filter(entry => nativeReadyIndices.has(entry.segment.index) && entry.first && !entry.seek);
    const readyIndices = new Set(ready.map(entry => entry.segment.index));
    const anchor = this.targetIndex !== null && this.targetIndex >= 0 ? this.targetIndex
      : this.selectedIndex !== null && this.selectedIndex >= 0 ? this.selectedIndex : -1;
    const ahead = this.options.segments.filter(row => row.index > anchor);
    let readyAheadCount = 0, readyAheadFrames = 0;
    let end = anchor < 0 ? 0 : (this.options.segments[anchor]?.startFrame ?? 0)
      + (this.options.segments[anchor]?.frameCount ?? 0);
    let firstNotReadyIndex: number | null = null;
    for (const row of ahead) {
      if (!readyIndices.has(row.index) || row.startFrame !== end) { firstNotReadyIndex = row.index; break; }
      readyAheadCount++; readyAheadFrames += row.frameCount; end += row.frameCount;
    }
    const clips = entries.filter(entry => entry.segment.index >= 0);
    const state = {selectedIndex:this.selectedIndex,targetIndex:this.targetIndex,closed:this.closed,held:this.held,
      knownAheadCount:ahead.length,readyAheadCount,readyAheadSeconds:readyAheadFrames/24,firstNotReadyIndex,
      currentReady:this.targetIndex !== null && readyIndices.has(this.targetIndex),
      readyCount:clips.filter(entry => readyIndices.has(entry.segment.index)).length,
      resolvingCount:clips.filter(entry => !entry.player).length,
      nativeLoadingCount:clips.filter(entry => entry.player && !nativeReadyIndices.has(entry.segment.index)).length,
      awaitingFirstFrameCount:clips.filter(entry => nativeReadyIndices.has(entry.segment.index) && !entry.first).length,
      seekingCount:clips.filter(entry => Boolean(entry.seek)).length,
      idleReadyCount:ready.filter(entry => entry.segment.index < 0).length,
      idleLoadingCount:entries.filter(entry => entry.segment.index < 0 && !readyIndices.has(entry.segment.index)).length,
      idleVerified:this.idleVerified,reservations:this.reservations.size};
    const key = JSON.stringify(state);
    if (key === this.lastBuffer) return;
    this.lastBuffer = key;
    let nativeSeconds: number | null = null;
    try { const value = this.selectedIndex === null ? undefined : this.slots.get(this.selectedIndex)?.player?.currentTime;
      if (typeof value === 'number' && Number.isFinite(value)) nativeSeconds = value;
    } catch { /* Diagnostic read must not affect playback. */ }
    this.report('buffer_readiness',{...state,audioSeconds:this.seconds,nativeSeconds});
  }
  private traceIdle(entry: Entry, phase: string, extra: Record<string, unknown> = {}) {
    if (entry.segment.index >= 0 || entry.retired || !entry.player) return;
    try {
      const emotion = (entry.segment as IdleVideo).diagnosticEmotion;
      this.report(phase,{index:entry.segment.index,selected:this.selectedIndex === entry.segment.index,
        requestedEmotion:emotion && ['neutral','angry','happy','sad','fear','surprise','disgust'].includes(emotion) ? emotion : 'other',
        sourceEntryFrame:(entry.segment as IdleVideo).entryFrame,sourceFrameCount:entry.segment.frameCount,
        lastSpeechSeconds:this.seconds,
        nativePlaying:entry.player.playing,loop:entry.player.loop,primed:entry.idlePrimed,
        nativeSeconds:Number.isFinite(entry.player.currentTime) ? entry.player.currentTime : null,
        nativeStatus:['idle','loading','readyToPlay','error'].includes(entry.player.status) ? entry.player.status : 'unknown',
        seekPending:Boolean(entry.seek),held:this.held,...extra});
    } catch { this.report('idle_native_unreadable',{index:entry.segment.index}); }
  }
  reportRetainedIdle() {
    const entry = this.selectedIndex === null ? undefined : this.slots.get(this.selectedIndex);
    if (entry) this.traceIdle(entry,'rearm_idle_preserved');
  }
  private traceSpeech(entry: Entry, phase: string) {
    if (entry.segment.index < 0 || entry.retired || !entry.player) return;
    try {
      this.report(phase,{index:entry.segment.index,selected:this.selectedIndex === entry.segment.index,
        targetIndex:this.targetIndex,audioSeconds:this.seconds,nativePlaying:entry.player.playing,
        nativeSeconds:Number.isFinite(entry.player.currentTime) ? entry.player.currentTime : null,
        seekPending:Boolean(entry.seek),held:this.held});
    } catch { this.report('speech_native_unreadable',{index:entry.segment.index}); }
  }
  private startupTiming(event: string, entry: Entry) {
    if (!this.closed && !entry.retired) this.traceLifecycle(event,entry);
  }
  private traceLifecycle(event: string, entry: Entry, extra: Record<string,unknown> = {}) {
    try {
      const player = entry.player;
      this.report(event,{index:entry.segment.index,startFrame:entry.segment.startFrame,frameCount:entry.segment.frameCount,
        elapsedMs:Math.max(0,this.options.now()-entry.started),selectedIndex:this.selectedIndex,targetIndex:this.targetIndex,
        audioSeconds:this.seconds,nativeSeconds:player && Number.isFinite(player.currentTime) ? player.currentTime : null,
        nativeStatus:player?.status ?? null,nativePlaying:player?.playing ?? false,
        bufferedSeconds:player && Number.isFinite(player.bufferedPosition) ? player.bufferedPosition : null,
        ready:entry.ready,firstFrame:entry.first,pending:entry.pending,retired:entry.retired,
        seekPending:Boolean(entry.seek),reservations:this.reservations.size,...extra});
    } catch { /* A disposed native getter must never affect playback. */ }
  }
  surfaceLayout(index: number, width: number, height: number) {
    const entry = this.slots.get(index);
    if (!entry || this.closed || entry.retired || index >= 2 || this.startupLayouts.has(index)
      || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return;
    this.startupLayouts.add(index);
    this.startupTiming('surface_layout',entry);
  }
  private gate(ready: boolean) {
    if (this.gateDone || this.closed) return;
    ready = ready && this.options.now() < this.startupDeadline();
    this.gateDone = true;
    if (!ready) this.missed.add(0);
    this.report('initial_gate', {ready, elapsedMs: this.options.now()-this.started});
    if (ready) this.options.onPrepared(); else this.options.onUnavailable();
  }
  private startupDeadline() {
    const supplied = this.options.startupDeadline?.();
    if (supplied === Infinity) return Infinity;
    return supplied !== undefined && Number.isFinite(supplied)
      ? Math.min(supplied,this.started+2500) : this.started+1000;
  }
  firstFrame(index: number) {
    const entry = this.slots.get(index);
    if (this.closed || !entry || entry.retired || entry.first) return;
    entry.first = true;
    this.traceBuffer();
    this.traceLifecycle('first_frame',entry);
    if (index === 0 && entry.ready) this.gate(true);
    this.options.changed();
  }
  private fail(entry: Entry, reason = 'control_failed') {
    if (this.closed || entry.retired) return;
    this.missed.add(entry.segment.index);
    this.report('unavailable', {index: entry.segment.index,role:entry.segment.index < 0 ? 'idle' : 'speech',
      reason,audioSeconds:this.seconds,targetIndex:this.targetIndex,selectedIndex:this.selectedIndex,
      ready:entry.ready,firstFrame:entry.first,seekPending:Boolean(entry.seek)});
    if (entry.segment.index === 0) this.gate(false);
    if (this.selectedIndex === entry.segment.index) this.selectedIndex = null;
    this.retire(entry);
    this.options.changed();
  }
  private retire(entry: Entry) {
    if (entry.retired) return;
    const disposalStarted = this.options.now();
    this.traceLifecycle('clip_retire_started',entry);
    const traceDisposal = entry.segment.index < 0;
    if (traceDisposal) this.report('idle_disposal_started',{index:entry.segment.index,
      selectedIndex:this.selectedIndex,targetIndex:this.targetIndex,audioSeconds:this.seconds});
    this.traceIdle(entry,'idle_released');
    entry.retired = true;
    entry.loadAbort.abort();
    for (const timer of entry.diagnosticTimers) clearTimeout(timer);
    entry.remove();
    // Removing listeners does not stop Expo's native Handler clock. Retired
    // players need no progress callbacks, even while a detach fence is pending.
    try { if (entry.player) entry.player.timeUpdateEventInterval = 0; } catch { /* Native resource may already have failed. */ }
    try { entry.player?.pause(); } catch { /* Native resource may already have failed. */ }
    const release=()=>{
      try { entry.player?.release(); } catch {
        entry.releasePending=true;
        this.report('local_video_release_failed',{index:entry.segment.index});
        // Keep the reservation and pin: native failure is not a detach fence.
        return;
      }
      if(entry.localLease){void entry.localLease.release().catch(()=>{});entry.localLease=undefined;}
      entry.player=null;entry.idleFile?.release();entry.idleFile=undefined;entry.releasePending=false;
      if(!entry.pending)this.reservations.delete(entry);
      if(!this.closed)this.options.changed();
    };
    if(entry.localBinding){
      entry.releasePending=true;
      void entry.localBinding.then(detach=>detach(),error=>{if(error?.nativeDetachPending)throw error;}).then(release,()=>{
        this.report('local_video_detach_failed',{index:entry.segment.index});
        // A failed native fence cannot authorize deleting a live reader.
      });
    } else release();
    this.slots.delete(entry.segment.index);
    // A disposed load still occupies its admission until its promise settles.
    if (!entry.pending && !entry.releasePending) this.reservations.delete(entry);
    this.traceBuffer();
    this.traceLifecycle('clip_retire_finished',entry,{disposalMs:Math.max(0,this.options.now()-disposalStarted)});
    if (traceDisposal) this.report('idle_disposal_finished',{index:entry.segment.index,
      elapsedMs:Math.max(0,this.options.now()-disposalStarted),reservations:this.reservations.size});
  }
  private admit(segment: ProbeVideoSegment) {
    if (this.anticipationReserved && segment.index !== 0) return;
    const expandedBudget = this.options.keepIdleReady || this.options.anticipationTrack;
    const playerLimit = this.speechClips + (expandedBudget ? 1 : 0);
    if (this.attempted.has(segment.index) || this.reservations.size >= playerLimit) return;
    if (!this.options.anticipationTrack && segment.index >= 0 && [...this.reservations].filter(entry => entry.segment.index >= 0).length >= this.speechClips) return;
    if (this.options.arrival === 'late' && segment.index === 2
      && (this.seconds === null || this.seconds < segment.startFrame/24 + .3)) return;
    const bytes = [...this.reservations].reduce((n, e) => n+e.segment.bytes, 0) + segment.bytes;
    if (segment.bytes <= 0 || segment.bytes > 16*1024*1024 || bytes > playerLimit*16*1024*1024) return;
    this.attempted.add(segment.index);
    if (this.options.arrival === 'missing' && segment.index === 2) {
      this.missed.add(2); this.report('unavailable', {index: 2, simulated: true}); return;
    }
    const entry: Entry = {segment, player: null, ready: false, first: false, retired: false,
      pending: true, remove() {}, started: this.options.now(), seek: null, terminalHeld: false, idlePrimed:false,
      progressSamples:0,playingSamples:0,diagnosticTimers:[],loadAbort:new AbortController()};
    this.slots.set(segment.index, entry); this.reservations.add(entry);
    this.traceLifecycle('clip_admitted',entry);
    this.peakDownloads = Math.max(this.peakDownloads, [...this.reservations].filter(e => e.pending).length);
    this.peakBytes = Math.max(this.peakBytes, bytes);
    void this.load(entry);
  }
  private async load(entry: Entry) {
    try {
      let uri = await this.options.resolveMedia(entry.segment.uri,entry.loadAbort.signal);
      if (this.closed || entry.retired) return;
      if(entry.segment.index>=0&&this.options.retainLocalMedia){
        const lease=await this.options.retainLocalMedia(uri,entry.loadAbort.signal);
        if(this.closed||entry.retired){await lease.release();return;}
        entry.localLease=lease;
      }
      if (entry.segment.index < 0 && this.options.loadIdle) {
        const file = await this.options.loadIdle(uri,entry.segment.bytes,entry.loadAbort.signal);
        if (this.closed || entry.retired) {file.release();return;}
        entry.idleFile = file;uri = file.uri;
        this.report('idle_file_ready',{index:entry.segment.index,bytes:entry.segment.bytes});
      }
      this.startupTiming('media_resolved',entry);
      const player = this.options.createPlayer(); entry.player = player;
      this.traceBuffer();
      player.muted = true; player.volume = 0; player.audioMixingMode = 'mixWithOthers';
      player.staysActiveInBackground = false; player.showNowPlayingNotification = false;
      player.allowsExternalPlayback = false; player.keepScreenOnWhilePlaying = false; player.loop = false;
      entry.localBound=!this.options.attachLocalVideo||entry.segment.index<0;
      const ready = () => {
        if (this.closed || entry.retired) return;
        if(!entry.localBound)return;
        const firstReady = !entry.ready;
        entry.ready = true;
        if (firstReady) this.startupTiming('native_ready',entry);
        this.traceBuffer();
        if (entry.segment.index === 0 && entry.first) this.gate(true);
        this.options.changed();
      };
      let diagnosticStatus: string | undefined;
      const status = player.addListener('statusChange', event => {
        if (!this.closed && !entry.retired && event.status !== diagnosticStatus) {
          diagnosticStatus = event.status;
          this.traceLifecycle('native_status',entry,{reportedStatus:event.status});
        }
        if (event.status === 'readyToPlay') ready();
        else if (event.status === 'error') this.fail(entry,'native_error');
      });
      entry.remove = () => status.remove();
      {
        player.timeUpdateEventInterval = entry.segment.index < 0 || entry.segment.index >= 2 ? 1 : .25;
        const playing = player.addListener('playingChange', event => {
          if (entry.playingSamples++ < 20) {
            if (entry.segment.index < 0) this.traceIdle(entry,'idle_native_playing',{isPlaying:event.isPlaying});
            else this.traceSpeech(entry,'speech_native_playing');
          }
        });
        const progress = player.addListener('timeUpdate', () => {
          if (entry.segment.index === this.selectedIndex && Number.isFinite(player.currentTime)) {
            this.options.onNativeProgress?.(entry.segment.index,Math.max(0,player.currentTime),false);
          }
          if ((entry.segment.index >= 0 || this.selectedIndex === entry.segment.index) && entry.progressSamples++ < (entry.segment.index >= 2 ? 3 : 12)) {
            if (entry.segment.index < 0) this.traceIdle(entry,'idle_native_progress');
            else this.traceSpeech(entry,'speech_native_progress');
          }
        });
        entry.remove = () => {status.remove();playing.remove();progress.remove();};
      }
      this.peakPlayers = Math.max(this.peakPlayers, this.entries.filter(e => e.player).length);
      // Mount the native surface before replacing its source so the first-frame
      // observer can see readiness even for a fast local response.
      this.options.changed();
      this.startupTiming('native_source_started',entry);
      await player.replaceAsync({uri});
      this.startupTiming('native_source_settled',entry);
      if(!this.closed&&!entry.retired&&this.options.attachLocalVideo&&entry.segment.index>=0){
        entry.localBinding=this.options.attachLocalVideo(player,entry.segment,uri);
        await entry.localBinding;entry.localBound=true;
        // This promise resolves only after the adapter has actual decoded pixels.
        // The old VideoView no longer owns the redirected output surface.
        this.firstFrame(entry.segment.index);
      }
      if (!this.closed && !entry.retired && player.status === 'readyToPlay') ready();
    } catch { this.fail(entry,'load_failed'); }
    finally {
      entry.pending = false;
      this.traceLifecycle('clip_load_finished',entry);
      if ((entry.retired || this.closed) && !entry.releasePending) this.reservations.delete(entry);
      this.traceBuffer();
      if (!this.closed) this.options.changed();
    }
  }
  update(seconds: number | null, paused: boolean, preparing: boolean, waiting: 'hold' | 'idle' = 'hold') {
    if (this.closed || this.held) return;
    this.seconds = seconds;
    if (!this.gateDone && this.options.now() >= this.startupDeadline()) this.gate(false);
    const previousSelected = this.selectedIndex;
    if (this.options.anticipationTrack && paused && !preparing) {
      // After the audio gate opens only the displayed silent surface is needed.
      // Release silent lookahead so a delayed audio clock can admit its actual
      // speech target without exceeding the shared three-player budget.
      for (const entry of this.entries) {
        if (entry.segment.index !== previousSelected) this.retire(entry);
        else try { entry.player?.pause(); } catch { this.fail(entry); }
      }
      this.traceSelection(paused,preparing,waiting);
      return;
    }
    const target = segmentAt(this.options.segments, seconds, this.options.durationSeconds, this.options.liveReply);
    this.targetIndex = target?.index ?? null;
    this.selectedIndex = null;
    if (!target) {
      if (this.options.liveReply) this.selectedIndex = previousSelected;
      for (const entry of this.entries) {
        if (waiting === 'idle' && entry.segment.index === this.idle?.index && entry.segment.index === previousSelected) continue;
        try { entry.player?.pause(); } catch { this.fail(entry); }
      }
      if (this.options.liveReply && waiting === 'idle' && !preparing) this.showIdle();
      this.traceSelection(paused,preparing,waiting);
      return; // Retain current/next while the same audio player's clock is stale.
    }
    this.idleSince = null;
    // An obsolete unshown load must not occupy the second slot forever while
    // the outgoing visible surface waits for a newer current target.
    for (const entry of this.entries) {
      const warmingIdle = entry.segment.index === this.idle?.index
        && (this.options.keepIdleReady || target.index === this.options.segments.length-1);
      if (entry.segment.index < target.index && entry.segment.index !== previousSelected && !warmingIdle) this.retire(entry);
    }
    // Outgoing surfaces remain valid until the view has committed the handoff.
    // Their reservations count toward the limit until display commit releases them.
    for (let index = target.index; index < target.index+this.speechClips; index++) {
      const segment = this.options.segments[index];
      if (segment) this.admit(segment);
    }
    const current = this.slots.get(target.index);
    if (!preparing && this.boundary !== target.index) {
      this.boundary = target.index;
      if (!current?.ready || !current.first) this.missed.add(target.index);
      this.report('boundary', {index: target.index, idle: this.missed.has(target.index),
        boundaryLatenessMs: Math.max(0, seconds! - this.options.segments[target.index]!.startFrame/24)*1000});
    }
    // Preload first-frame readiness predates any catch-up seek. Do not reveal
    // that player (or let displayCommitted retire its predecessor) until the
    // asynchronous seek has converged with the audio target.
    let positionReady = true;
    if (this.options.liveReply && !this.options.anticipationTrack && !preparing && !paused
      && current?.player && current.ready && current.first) {
      try {
        if (previousSelected === target.index && current.player.currentTime-target.localSeconds > .12) {
          // Never replay already displayed speech frames when audio observations
          // lag. Hold this picture until audio catches up; late video still seeks
          // forward through the normal recovery path below.
          positionReady = false;
        } else {
          if (this.missed.has(target.index) && !this.recovered.has(target.index) && !current.seek) {
            current.seek = {target:target.localSeconds,at:this.options.now()};
            current.player.pause(); current.player.currentTime = target.localSeconds; this.seeks++;
          }
          const decision = videoStep(target.localSeconds,current.player.currentTime,current.seek,this.options.now(),false);
          if (decision.kind === 'failed') { this.fail(current,'seek_failed'); positionReady = false; }
          else if (decision.kind === 'seek') {
            current.seek = {target:target.localSeconds,at:this.options.now()};
            current.player.pause(); current.player.currentTime = target.localSeconds; this.seeks++;
            positionReady = videoStep(target.localSeconds,current.player.currentTime,current.seek,this.options.now(),false).kind === 'play';
            if (positionReady) current.seek = null;
            else this.report('speech_seek_pending',{index:target.index,audioSeconds:seconds,selectedIndex:previousSelected});
          } else if (decision.kind === 'wait') positionReady = false;
          else current.seek = null;
        }
      } catch {
        this.fail(current,'control_failed'); positionReady = false;
      }
    }
    const previousEntry = previousSelected === null ? undefined : this.slots.get(previousSelected);
    const retainedSelection = previousEntry?.player && !previousEntry.retired ? previousSelected : null;
    if (current?.ready && current.first && !current.retired && (this.options.liveReply || !this.missed.has(target.index))) {
      this.selectedIndex = positionReady ? target.index : retainedSelection;
      if (this.options.liveReply && this.missed.has(target.index) && !this.recovered.has(target.index)) {
        this.recovered.add(target.index);
        this.report('late_recovery', {index:target.index, audioSeconds:seconds});
      }
    } else if (this.options.liveReply) {
      this.selectedIndex = retainedSelection;
    }
    for (const entry of this.entries) {
      const player = entry.player;
      if (!player || !entry.ready) continue;
      try {
        if (entry.segment.index !== this.selectedIndex || entry.segment.index !== target.index || preparing || paused) { player.pause(); continue; }
        if (this.options.anticipationTrack) {
          // This silent track owns its clock. Sparse progress callbacks select
          // ranges; they are not an audio clock to seek the same player against.
          const lastFrame = (entry.segment.frameCount-1)/24;
          if (player.currentTime >= lastFrame) {
            if (!entry.terminalHeld) {
              player.currentTime = lastFrame; entry.terminalHeld = true;
              this.options.onNativeProgress?.(entry.segment.index,lastFrame,true);
            }
            player.pause();
          } else if (!player.playing) player.play();
          continue;
        }
        if (!positionReady) { player.pause(); continue; }
        const decision = videoStep(target.localSeconds, player.currentTime, entry.seek, this.options.now(), false);
        if (decision.kind === 'failed') { this.fail(entry,'seek_failed'); continue; }
        if (decision.kind === 'wait') continue;
        if (decision.kind === 'seek') {
          entry.seek = {target: target.localSeconds, at: this.options.now()};
          player.currentTime = target.localSeconds; this.seeks++;
        } else entry.seek = null;
        const lastFrame = (entry.segment.frameCount-1)/24;
        if (target.localSeconds >= lastFrame) {
          if (!entry.terminalHeld) {
            player.currentTime = lastFrame; entry.terminalHeld = true;
            this.options.onNativeProgress?.(entry.segment.index,lastFrame,true);
          }
          player.pause();
        } else if (!player.playing) player.play();
      } catch {
        this.fail(entry);
      }
    }
    if (this.options.liveReply && this.selectedIndex === target.index
      && (this.options.keepIdleReady || (!paused && !preparing && target.index === this.options.segments.length-1))) this.prewarmIdle();
    this.traceSelection(paused,preparing,waiting);
  }
  private prewarmIdle() {
    const idle = this.idle;
    if (!idle || !this.idleVerified) return;
    // Speech/current lookahead is admitted first; idle can only use a free slot.
    this.admit(idle);
    const entry = this.slots.get(idle.index);
    if (!entry?.ready || !entry.first || !entry.player) return;
    try {
      if (entry.player.loop && this.options.keepIdleReady && this.selectedIndex !== null && this.selectedIndex >= 0) {
        entry.player.pause();entry.player.loop = false;entry.idlePrimed = false;entry.seek = null;
      }
      if (entry.player.loop || entry.idlePrimed) return;
      const target = idle.entryFrame/24;
      if (!entry.seek) { entry.seek = {target,at:this.options.now()}; entry.player.currentTime = target; this.seeks++; }
      const step = videoStep(target,entry.player.currentTime,entry.seek,this.options.now(),false);
      if (step.kind === 'failed') { this.fail(entry); return; }
      if (step.kind === 'wait') return;
      if (step.kind === 'seek') { entry.seek = {target,at:this.options.now()}; entry.player.currentTime = target; return; }
      entry.seek = null; entry.idlePrimed = true;
      this.traceIdle(entry,'idle_prewarmed');
    } catch { this.fail(entry); }
  }
  private showIdle() {
    if (this.idleSince === null) this.idleSince = this.options.now();
    const idle = this.idle;
    if (!idle || !this.idleVerified) return;
    this.targetIndex = idle.index;
    for (const entry of this.entries) {
      if (entry.segment.index !== this.selectedIndex && entry.segment.index !== idle.index) this.retire(entry);
    }
    this.admit(idle);
    const entry = this.slots.get(idle.index);
    if (!entry?.ready || !entry.first || !entry.player) return;
    const player = entry.player;
    try {
      if (this.selectedIndex !== idle.index && !entry.idlePrimed) {
        const seconds = (idle.entryFrame/24 + (this.options.now()-this.idleSince)/1000) % (idle.frameCount/24);
        if (!entry.seek) { entry.seek = {target:seconds,at:this.options.now()}; player.currentTime = seconds; this.seeks++; }
        const decision = videoStep(seconds,player.currentTime,entry.seek,this.options.now(),false);
        if (decision.kind === 'wait') return;
        if (decision.kind === 'failed') { this.fail(entry); return; }
        if (decision.kind === 'seek') { entry.seek = {target:seconds,at:this.options.now()}; player.currentTime = seconds; this.seeks++; return; }
        entry.seek = null;
      }
      player.loop = true;
      const newlySelected = this.selectedIndex !== idle.index;
      this.selectedIndex = idle.index;
      if (newlySelected) {
        entry.progressSamples = 0;
        this.traceIdle(entry,'idle_play_requested');
        for (const delay of [250,1000]) entry.diagnosticTimers.push(setTimeout(() => this.traceIdle(entry,'idle_play_check',{afterMs:delay}),delay));
      }
      if (!player.playing) player.play();
      if (newlySelected) this.traceIdle(entry,'idle_selected');
    } catch { this.fail(entry); }
  }
  displayCommitted(targetIndex: number | null, selectedIndex: number | null) {
    if (this.closed || (this.held && (targetIndex === null || targetIndex >= 0)) || targetIndex === null || targetIndex !== this.targetIndex
      || selectedIndex !== this.selectedIndex) return;
    if (this.options.liveReply && targetIndex !== selectedIndex) return;
    if (selectedIndex !== null && this.slots.get(selectedIndex)?.seek) return;
    if (selectedIndex !== null && selectedIndex >= 0 && !this.startupCommits.has(selectedIndex)) {
      this.startupCommits.add(selectedIndex);
      const entry = this.slots.get(selectedIndex);
      if (entry) this.traceSpeech(entry,'speech_surface_committed');
    }
    let retired = false;
    for (const entry of this.entries) {
      if (this.options.liveReply && targetIndex >= 0 && (this.options.keepIdleReady || targetIndex === this.options.segments.length-1)
        && entry.segment.index === this.idle?.index && (this.options.keepIdleReady || !entry.player?.loop)) continue;
      if (targetIndex < 0 ? entry.segment.index !== targetIndex
        : entry.segment.index < targetIndex || entry.segment.index >= targetIndex+this.speechClips) {
        this.retire(entry); retired = true;
      }
    }
    if (retired) {
      this.report('handoff_released', {index: targetIndex, selectedIndex});
      // Admit the new lookahead only after releasing the old player.
      for (let index = targetIndex; targetIndex >= 0 && index < targetIndex+this.speechClips; index++) {
        const segment = this.options.segments[index];
        if (segment) this.admit(segment);
      }
      this.options.changed();
    }
  }
  holdForReplacement(preferIdle = false): boolean {
    if (this.closed) return false;
    const previousSelected = this.selectedIndex;
    this.retainedIdle = Boolean(preferIdle && this.options.keepIdleReady && this.idleVerified && this.idle);
    if (this.retainedIdle) {
      this.prewarmIdle();
      if (this.idle && this.slots.get(this.idle.index)?.idlePrimed) this.showIdle();
    }
    const changedToIdle = this.selectedIndex !== previousSelected && this.selectedIndex === this.idle?.index;
    this.held = true;
    for (const entry of this.entries) {
      if (this.retainedIdle && entry.segment.index === this.idle?.index) continue;
      if (changedToIdle && entry.segment.index === previousSelected) {
        try { entry.player?.pause(); } catch { this.fail(entry); }
        continue;
      }
      if (entry.segment.index !== this.selectedIndex) this.retire(entry);
      else try {
        // A selected idle loop has no speech clock/ownership to preserve.
        // Keep it moving through normal re-arm and speech preparation.
        if (!(entry.segment.index < 0 && entry.player?.loop)) entry.player?.pause();
      } catch { this.fail(entry); }
    }
    const retained = this.entries.some(entry => entry.player && entry.segment.index === this.selectedIndex);
    if (retained) this.report('surface_retained', {index:this.selectedIndex});
    if (this.retainedIdlePending) this.report('interrupted_idle_pending', {index:this.idle?.index,
      requestedEmotion:this.idle?.diagnosticEmotion,selectedIndex:this.selectedIndex});
    if (retained && this.selectedIndex !== null) this.traceIdle(this.slots.get(this.selectedIndex)!,'idle_retained');
    this.traceSelection(true,false,'replacement');
    return retained;
  }
  close(reason: string) {
    if (this.closed) return;
    this.closed = true; this.selectedIndex = null;
    for (const entry of this.entries) this.retire(entry);
    this.report('summary', {reason, peakPlayers: this.peakPlayers, peakDownloads: this.peakDownloads,
      peakCompressedBytes: this.peakBytes, idleIntervals: this.missed.size, seekCorrections: this.seeks,
      arrival: this.options.arrival, nativeMemoryMeasured: false});
  }
}
