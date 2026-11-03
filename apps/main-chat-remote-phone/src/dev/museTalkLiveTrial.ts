// Development-only incremental transport. This class never commands audio playback.
import type {RemoteClient} from '../api/client';
import type {AudioChunk} from '../api/types';
import {AuthorizedMediaResolver} from '../utils/authorizedMedia';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import type {ProbeVideoSegment} from './museTalkMatchedSample';
import type {IdleVideo} from './museTalkSegmentSession';
import type {MuseTalkBufferedDelivery} from './museTalkBufferedDelivery';
import {parseSourceTimeline} from '../relay/frameHandoff';
import type {SourceTimeline} from '../relay/frameHandoff';
import {parseIdleChunkReturn} from './idleChunkProtocol';
import type {IdleChunkReturn} from './idleChunkProtocol';

type AudioIdentity = {id: string; phone_request_id: string; url_path: string};
type LiveRow = {index: number; startFrame: number; frameCount: number; state: 'pending' | 'ready' | 'unavailable'; uri?: string; bytes?: number;
  sourceReadyAfterClaimMs?: number; encodeMs?: number; publishedAfterClaimMs?: number};
type Status = {trialId: string; mediaId: string; state: string; audio: AudioIdentity; durationSeconds: number; frameCount: number; segments: LiveRow[];
  idleSourceId?: string;
  idleChunkReturn?:IdleChunkReturn;
  sourceTimeline?:SourceTimeline;
  loopFadeMs?:number;
  idle?: {mediaId?: string; motionId?:string; avatarId?: string; continuationReady?: boolean; uri: string; bytes: number; frameCount: number; fps: 24; startFrame: number};
  sourceState?: 'awaiting_identity' | 'matched'; failureStage?: '' | 'source_scan' | 'bridge_check' | 'encode';
  sourceStartIndex?: number | null; anticipation?: unknown};
type AnticipationRow = {index: number; startFrame: number; frameCount: number; state: 'pending' | 'ready' | 'ended' | 'unavailable'; uri?: string; bytes?: number;
  sampleRate?:48000;validSamples?:number;delaySamples?:number;paddingSamples?:number;rawSamples?:number};
export type AnticipationStatus = {version: 1; planId: string; avatarId: string; fps: 24; sourceFrameCount: number;
  syncWaitSeconds?: number;
  sourceIndices: number[]; speechEntryFrame: number; exitAfterFrame: number; repeat: boolean; cursor: number | null;
  state: 'available' | 'active' | 'ended' | 'unavailable'; mediaId: string; segments: AnticipationRow[];muxedAudio?:true};
type Snapshot = {phase: 'off' | 'arming' | 'armed' | 'preparing' | 'playing'; message: string;
  chunkedIdle?:boolean;
  muxedAudio?:true;
  trialId: string; chunk: AudioChunk | null; duration: number; segments: ProbeVideoSegment[];
  offsetSeconds: number; audioDuration: number; idle: IdleVideo | null; idleVerified?: boolean;
  anticipation: AnticipationStatus | null; anticipationPending: boolean};
type Request = (method: 'GET' | 'POST', path: string, body?: Record<string, unknown>) => Promise<unknown>;
const PREFIX = '/api/dev/musetalk-live/';
const MAX_BYTES = 16*1024*1024;
let runSequence = 0;
const STATUS_STAGES=['identity','segment_layout','segment_file','segment_timing','source_state','source_start',
  'chunk_return_timeline','chunk_return_conflict','chunk_return_length','chunk_return_descriptor',
  'loop_fade','idle','other'] as const;
type StatusStage=typeof STATUS_STAGES[number];
const fail = (liveStatusStage:StatusStage='other'): never => {
  throw Object.assign(new Error('Invalid live visual status'),{liveStatusStage});
};
export function liveStatusFailureStage(error:unknown):StatusStage {
  const stage=error&&typeof error==='object'?(error as {liveStatusStage?:unknown}).liveStatusStage:undefined;
  return STATUS_STAGES.includes(stage as StatusStage)?stage as StatusStage:'other';
}

// This is deliberately a wire parser rather than a local choreography builder.
// The producer owns source order, wrapping and repeat semantics.
export function parseAnticipationStatus(value: unknown,muxedAudio=false): AnticipationStatus {
  const data = value as AnticipationStatus;
  const keys = ['version','planId','avatarId','fps','sourceFrameCount','sourceIndices','speechEntryFrame','exitAfterFrame','repeat','cursor','state','mediaId','segments'];
  if(muxedAudio){keys.push('muxedAudio');if(data?.muxedAudio!==true)fail();}
  if (data && 'syncWaitSeconds' in data) {
    keys.push('syncWaitSeconds');
    if (typeof data.syncWaitSeconds !== 'number' || !Number.isFinite(data.syncWaitSeconds)
      || data.syncWaitSeconds < 0 || data.syncWaitSeconds > 2.5) fail();
  }
  if (!data || Object.keys(data).length !== keys.length || keys.some(key => !(key in data)) || data.version !== 1 || !/^[a-f0-9]{32}$/.test(data.planId)
    || typeof data.avatarId !== 'string' || !data.avatarId || data.fps !== 24
    || !Number.isInteger(data.sourceFrameCount) || data.sourceFrameCount < 1 || data.sourceFrameCount > 1440
    || !Array.isArray(data.sourceIndices) || !data.sourceIndices.length || data.sourceIndices.length > 1440
    || data.sourceIndices.some(index => !Number.isInteger(index) || index < 0 || index >= data.sourceFrameCount)
    || !Number.isInteger(data.speechEntryFrame) || data.speechEntryFrame < 0 || data.speechEntryFrame >= data.sourceFrameCount
    || !Number.isInteger(data.exitAfterFrame) || data.exitAfterFrame !== data.sourceIndices.length-1
    || typeof data.repeat !== 'boolean' || !/^[a-f0-9]{32}$/.test(data.mediaId)
    || !['available','active','ended','unavailable'].includes(data.state)
    || !(data.cursor === null || (Number.isInteger(data.cursor) && data.cursor >= 0 && data.cursor <= 10000))
    || !Array.isArray(data.segments) || data.segments.length !== Math.ceil(data.sourceIndices.length/12)) fail();
  const segments = data.segments.map((row,index): AnticipationRow => {
    if (!row || row.index !== index || row.startFrame !== index*12
      || row.frameCount !== Math.min(12,data.sourceIndices.length-index*12)
      || !['pending','ready','ended','unavailable'].includes(row.state)
      || Object.keys(row).length !== (row.state === 'ready' ? (muxedAudio?11:6) : 4)
      || ['index','startFrame','frameCount','state',...(row.state === 'ready' ? ['uri','bytes',
        ...(muxedAudio?['sampleRate','validSamples','delaySamples','paddingSamples','rawSamples']:[])] : [])].some(key => !(key in row))) fail();
    if (row.state === 'ready' && (row.uri !== `${PREFIX}anticipation/${data.mediaId}/${String(index).padStart(8,'0')}.mp4`
      || !Number.isSafeInteger(row.bytes) || row.bytes! <= 0 || row.bytes! > MAX_BYTES)) fail();
    if(muxedAudio&&row.state==='ready'&&(row.sampleRate!==48000||row.validSamples!==row.frameCount*2000
      ||!Number.isSafeInteger(row.delaySamples)||row.delaySamples!<0||row.delaySamples!>2048
      ||!Number.isSafeInteger(row.paddingSamples)||row.paddingSamples!<0||row.paddingSamples!>1023
      ||!Number.isSafeInteger(row.rawSamples)||row.rawSamples!%1024!==0||row.rawSamples!>28672
      ||Number(row.rawSamples)-Number(row.delaySamples)-Number(row.paddingSamples)!==row.validSamples))fail();
    return row.state === 'ready'
      ? {index,startFrame:row.startFrame,frameCount:row.frameCount,state:row.state,uri:row.uri,bytes:row.bytes,
        ...(muxedAudio?{sampleRate:row.sampleRate,validSamples:row.validSamples,delaySamples:row.delaySamples,
          paddingSamples:row.paddingSamples,rawSamples:row.rawSamples}:{})}
      : {index,startFrame:row.startFrame,frameCount:row.frameCount,state:row.state};
  });
  return {...data,sourceIndices:[...data.sourceIndices],segments};
}

export function parseLiveStatus(value: unknown, id: string, audio: AudioIdentity): Status {
  const data = value as Status;
  const mediaId = data?.mediaId;
  if (!data || !/^[a-f0-9]{32}$/.test(id) || data.trialId !== id || !data.audio
    || !/^[a-f0-9]{32}$/.test(mediaId)
    || !(['claimed','streaming','unavailable'] as unknown[]).includes(data.state)
    || Object.keys(audio).some(k => data.audio[k as keyof AudioIdentity] !== audio[k as keyof AudioIdentity])
    || !Number.isFinite(data.durationSeconds) || data.durationSeconds <= 0 || data.durationSeconds > 30
    || !Number.isInteger(data.frameCount) || data.frameCount < 1 || data.frameCount > 720
    || Math.abs(data.frameCount/24-data.durationSeconds) > 1/24+.00001
    || !Array.isArray(data.segments) || data.segments.length !== Math.ceil(data.frameCount/12)) fail('identity');
  const segments = data.segments.map((row, index): LiveRow => {
    if (!row || row.index !== index || row.startFrame !== index*12 || row.frameCount !== Math.min(12,data.frameCount-index*12)
      || !['pending','ready','unavailable'].includes(row.state)) fail('segment_layout');
    if (row.state === 'ready' && (row.uri !== `${PREFIX}segment/${mediaId}/${String(index).padStart(8,'0')}.mp4`
      || !Number.isSafeInteger(row.bytes) || row.bytes! <= 0 || row.bytes! > MAX_BYTES)) fail('segment_file');
    const timings: Partial<LiveRow> = {};
    for (const key of ['sourceReadyAfterClaimMs','encodeMs','publishedAfterClaimMs'] as const) {
      if (row[key] !== undefined) {
        if (!Number.isFinite(row[key]) || row[key]! < 0 || row[key]! > 120000) fail('segment_timing');
        timings[key] = row[key];
      }
    }
    return {index, startFrame: row.startFrame, frameCount: row.frameCount, state: row.state,
      ...(row.state === 'ready' ? {uri:row.uri, bytes:row.bytes,...timings} : {})};
  });
  if (data.sourceState !== undefined && !['awaiting_identity','matched'].includes(data.sourceState)) fail('source_state');
  if (data.failureStage !== undefined && !['','source_scan','bridge_check','encode'].includes(data.failureStage)) fail('source_state');
  if (data.sourceStartIndex !== undefined && data.sourceStartIndex !== null
    && (!Number.isSafeInteger(data.sourceStartIndex) || data.sourceStartIndex < 0)) fail('source_start');
  const idle = data.idle;
  let chunkReturn:IdleChunkReturn|undefined;
  let chunkTimeline:SourceTimeline|undefined;
  if(data.idleChunkReturn!==undefined){
    try{chunkTimeline=parseSourceTimeline((value as {sourceTimeline?:unknown}).sourceTimeline);}
    catch{fail('chunk_return_timeline');}
    if(idle!==undefined)fail('chunk_return_conflict');
    if(chunkTimeline!.sourceIndices.length!==data.frameCount)fail('chunk_return_length');
    try{
      chunkReturn=parseIdleChunkReturn(data.idleChunkReturn,mediaId,audio,chunkTimeline!);
    }catch{fail('chunk_return_descriptor');}
  }
  if(data.loopFadeMs!==undefined&&(!Number.isSafeInteger(data.loopFadeMs)||data.loopFadeMs<0||data.loopFadeMs>5000))fail('loop_fade');
  if(idle?.motionId!==undefined&&!/^[a-f0-9]{64}$/.test(idle.motionId))fail('idle');
  if (idle?.avatarId !== undefined && (typeof idle.avatarId !== 'string' || !idle.avatarId || idle.avatarId.length > 256)) fail('idle');
  if (data.idleSourceId !== undefined && !/^[a-f0-9]{32}$/.test(data.idleSourceId)) fail('idle');
  if (idle !== undefined && (idle === null || (idle.mediaId !== undefined && !/^[a-f0-9]{32}$/.test(idle.mediaId))
    || idle.uri !== `${PREFIX}idle/${idle.mediaId ?? mediaId}.mp4`
    || (data.idleSourceId !== undefined && idle.mediaId !== data.idleSourceId)
    || (idle.continuationReady !== undefined && typeof idle.continuationReady !== 'boolean')
    || idle.fps !== 24 || !Number.isSafeInteger(idle.bytes) || idle.bytes <= 0 || idle.bytes > MAX_BYTES
    || !Number.isSafeInteger(idle.frameCount) || idle.frameCount < 1 || idle.frameCount > 1440
    || !Number.isSafeInteger(idle.startFrame) || idle.startFrame < 0 || idle.startFrame >= idle.frameCount)) fail('idle');
  return {trialId:id,mediaId,state:data.state,audio:{...audio},durationSeconds:data.durationSeconds,frameCount:data.frameCount,segments,
    sourceState:data.sourceState,failureStage:data.failureStage,sourceStartIndex:data.sourceStartIndex,
    anticipation:data.anticipation,idleSourceId:data.idleSourceId,loopFadeMs:data.loopFadeMs,...(idle ? {idle:{...idle}} : {}),
    ...(chunkReturn?{idleChunkReturn:chunkReturn,sourceTimeline:chunkTimeline}:{})};
}

// Armed idle is a distinct status shape. Keep speech parsing strict and never
// treat an idle descriptor as an admitted reply.
export function parseArmedIdleStatus(value: unknown, id: string): IdleVideo | null {
  const data = value as {trialId?: unknown; mediaId?: unknown; state?: unknown; audio?: unknown; segments?: unknown; idle?: unknown};
  if (!data || data.trialId !== id || data.state !== 'armed' || data.audio !== null || !Array.isArray(data.segments) || data.segments.length !== 0) fail();
  if (data.idle === undefined) return null;
  const idle = data.idle as {mediaId?: unknown; avatarId?: unknown; uri?: unknown; bytes?: unknown; frameCount?: unknown; fps?: unknown; startFrame?: unknown};
  if (idle?.avatarId !== undefined && (typeof idle.avatarId !== 'string' || !idle.avatarId || idle.avatarId.length > 256)) fail();
  if (!/^[a-f0-9]{32}$/.test(String(data.mediaId))
    || (idle.mediaId !== undefined && !/^[a-f0-9]{32}$/.test(String(idle.mediaId)))
    || idle.uri !== `${PREFIX}idle/${idle.mediaId ?? data.mediaId}.mp4`
    || idle.fps !== 24 || !Number.isSafeInteger(idle.bytes) || Number(idle.bytes) <= 0 || Number(idle.bytes) > MAX_BYTES
    || !Number.isSafeInteger(idle.frameCount) || Number(idle.frameCount) < 1 || Number(idle.frameCount) > 1440
    || !Number.isSafeInteger(idle.startFrame) || Number(idle.startFrame) < 0 || Number(idle.startFrame) >= Number(idle.frameCount)) fail();
  return { index: -1, startFrame: 0, frameCount: Number(idle.frameCount), uri: String(idle.uri), bytes: Number(idle.bytes), entryFrame: Number(idle.startFrame),
    ...(idle.avatarId !== undefined ? {avatarId:String(idle.avatarId)} : {}),
    ...(idle.mediaId !== undefined ? {mediaId:String(idle.mediaId)} : {}) };
}

type ChunkContext = {chunk: AudioChunk; identity: AudioIdentity; rows: LiveRow[]; segments: ProbeVideoSegment[];
  baseIndex: number; baseFrame: number; duration: number; frameCount: number; current: number;
  polling: Promise<void> | null; promotion: Promise<void> | null; advancing: Promise<void> | null; reported: Set<number>; reportedSource: string;
  idle: IdleVideo | null; mediaId?: string; reportedPublication?: string};

export class MuseTalkLiveTrial {
  snapshot: Snapshot = {phase:'off',message:'Live delivery trial off',trialId:'',chunk:null,duration:0,segments:[],
    offsetSeconds:0,audioDuration:0,idle:null,anticipation:null,anticipationPending:false};
  private listeners = new Set<() => void>();
  private run = ++runSequence;
  private resolver: AuthorizedMediaResolver;
  private generation = 0;
  private network = new AbortController();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private gateResolve: (() => void) | undefined;
  private unbindAudio: (() => void) | undefined;
  private deadline = 0;
  private startupStarted = 0;
  private syncTimer: ReturnType<typeof setTimeout> | undefined;
  private speechReady = false;
  private displayedAnticipation: {planId: string; cursor: number; sourceFrame: number; planFrame: number; observedAt: number} | null = null;
  private frameTrace = {at:-Infinity,count:0};
  private active: ChunkContext | null = null;
  private next: ChunkContext | null = null;
  private request: Request;
  private refreshedAt = -Infinity;
  private armedIdle: IdleVideo | null = null;
  private armedIdleSequence = 0;
  private sourceIdleSequence = 0;
  private anticipationFence = 0;
  private anticipationActivating = false;
  private retainIdleOnCancel: boolean;
  private retainingIdle = false;
  private armRequestId: string | null = null;
  private armCleanup: {armRequestId:string; idleMediaId?:string|null} | null = null;
  private armCleanupPromise: Promise<boolean> | null = null;
  private buffered: MuseTalkBufferedDelivery | null = null;
  private detachBuffered: (() => void) | undefined;
  private readonly idleChunks:()=>boolean;
  private readonly muxedAudio:()=>boolean;
  private chunkedIdle=false;
  chunkIdleUnsupported=false;
  constructor(private client: RemoteClient, options: {request?: Request; retainIdleOnCancel?: boolean;idleChunks?:()=>boolean;muxedAudio?:()=>boolean} = {}) {
    this.retainIdleOnCancel = options.retainIdleOnCancel === true;
    this.resolver = new AuthorizedMediaResolver(client);
    this.request = options.request ?? ((method,path,body) => this.fetchJson(method,path,body));
    this.idleChunks=options.idleChunks??(()=>false);
    this.muxedAudio=options.muxedAudio??(()=>false);
  }
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  // Explicit buffered selection, never a fallback after failed RTP setup. The
  // caller owns delivery/files; this existing controller owns presentation only.
  attachBufferedDelivery(delivery: MuseTalkBufferedDelivery): void {
    if (this.snapshot.phase !== 'armed' || delivery.trialId !== this.snapshot.trialId || this.buffered) {
      throw Error('Buffered visual owner mismatch.');
    }
    this.buffered = delivery;
    this.detachBuffered = delivery.subscribe(() => this.refreshBuffered());
  }
  private refreshBuffered() {
    if (!this.buffered) return;
    if (this.buffered.error) { this.cancel('Buffered visuals unavailable','poll_failed'); return; }
    for (const ctx of [this.active,this.next]) if (ctx) {
      const local = this.buffered.prepared(ctx.chunk.id);
      if (!local) continue;
      const ready = new Map(local.segments.map(row => [row.index,row]));
      // Retired producer rows stay readable through their scoped local leases.
      // Do not replay producer anticipation or idle controls: the retained
      // native transition owner handles those independently of production.
      const status = {...local.status,anticipation:undefined,idle:undefined,idleSourceId:undefined,
        segments:local.status.segments.map(row => {
          const file=ready.get(row.index);
          return {index:row.index,startFrame:row.startFrame,frameCount:row.frameCount,
            state:file?'ready':'pending',...(file?{bytes:file.bytes,
              uri:PREFIX+'segment/'+local.status.mediaId+'/'+String(row.index).padStart(8,'0')+'.mp4'}:{})};
        })};
      this.accept(ctx,status);
    }
  }
  private changed() { for (const fn of this.listeners) fn(); }
  private report(phase: string, details: Record<string, unknown> = {}) {
    try { void recordPhoneDebug('info','musetalk_live_trial',{run:this.run,phase,...details,
      atMs:performance.now(),presentationMeasured:false}).catch(() => {}); }
    catch { /* Diagnostics must never change playback lifecycle. */ }
  }
  get busy() { return this.snapshot.phase !== 'off'; }
  get startupDeadlineMs() { return this.snapshot.phase === 'preparing' ? this.deadline : undefined; }
  private cancelBackend(trialId: string) {
    // Background arming may have prepared a desktop emotion the phone never
    // displayed. Preserve the phone-selected idle, not that unseen replacement.
    const body = {trialId,...(this.retainIdleOnCancel ? {idleMediaId:this.snapshot.idle?.mediaId ?? null} : {})};
    void this.fetchJson('POST',PREFIX+'cancel',body,new AbortController().signal).catch(() => {});
  }
  private valid(ctx: ChunkContext) { return this.busy && (ctx === this.active || ctx === this.next); }
  private flushArmCleanup(): Promise<boolean> {
    if (this.armCleanupPromise) return this.armCleanupPromise;
    const cleanup=this.armCleanup;
    if (!cleanup) return Promise.resolve(true);
    const pending=this.fetchJson('POST',PREFIX+'cancel',cleanup,new AbortController().signal).then(result=>{
      if ((result as {ok?:boolean})?.ok !== true) throw Error('Arm cleanup not acknowledged');
      if (this.armCleanup === cleanup) this.armCleanup=null;
      this.report('arm_cleanup_acknowledged');
      return true;
    }).catch(()=>{
      this.report('arm_cleanup_pending');
      return false;
    }).finally(()=>{if (this.armCleanupPromise === pending) this.armCleanupPromise=null;});
    this.armCleanupPromise=pending;
    return pending;
  }
  private async fetchJson(method: 'GET' | 'POST', path: string, body?: Record<string, unknown>, parent = this.network.signal) {
    const abort = new AbortController();
    const started = performance.now();
    const route = path.slice(PREFIX.length).split('/')[0] ?? 'other';
    const operation = ['arm','recover','prepare','prefetch','cancel','status'].includes(route) ? route : 'other';
    let failureKind = 'network', httpStatus: number | undefined, timedOut = false;
    const cancel = () => abort.abort(); parent.addEventListener('abort',cancel,{once:true});
    if (parent.aborted) abort.abort();
    const timeout = setTimeout(() => { timedOut = true; cancel(); },2000);
    try {
      if (this.client.isRelay || this.client.bufferedPeer) return await this.client.requestLiveVisual(method, path, body, abort.signal);
      const media = await this.resolver.resolve(path);
      if (abort.signal.aborted) throw Error('Cancelled');
      const response = await fetch(media.url,{method,signal:abort.signal,cache:'no-store',
        ...(body ? {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {})});
      httpStatus = response.status;
      if (!response.ok) { failureKind = 'http'; throw Object.assign(Error('Live trial request failed'),{httpStatus}); }
      failureKind = 'invalid_response';
      const text = await response.text();
      if (text.length > 512*1024) throw Error('Live status too large');
      return JSON.parse(text) as unknown;
    } catch (error) {
      this.report('request_failed',{operation,failureKind:parent.aborted ? 'cancelled' : timedOut ? 'timeout' : failureKind,
        ...(Number.isInteger(httpStatus) ? {httpStatus} : {}),elapsedMs:Math.max(0,performance.now()-started)});
      throw error;
    } finally { clearTimeout(timeout); parent.removeEventListener('abort',cancel); }
  }
  arm = async () => {
    if (this.busy || (this.client.auth.kind !== 'lan' && !this.client.bufferedPeer)) return;
    const generation = ++this.generation;
    const muxedAudio=this.muxedAudio()===true;
    const chunkedIdle=muxedAudio||this.idleChunks()===true;
    this.chunkedIdle=chunkedIdle;
    this.run = ++runSequence; this.network = new AbortController();
    this.snapshot = {...this.snapshot,phase:'arming',message:'Arming live delivery…'}; this.changed();
    try {
      // One unresolved attempt at a time. A cancelled HTTP request may already
      // have allocated a backend owner, even when its response never arrived.
      if (this.armCleanup && !await this.flushArmCleanup()) throw Error('Arm cleanup pending');
      if (generation !== this.generation) return;
      // Correlation only, not an authorization credential. Backend auth is unchanged.
      const armRequestId=`arm-${Date.now().toString(36)}-${this.run.toString(36)}-${Math.random().toString(36).slice(2)}`;
      this.armRequestId=armRequestId;
      const result = await this.request('POST',PREFIX+'arm',{armRequestId,...(chunkedIdle?{idleChunks:true}:{}),
        ...(muxedAudio?{muxedAudio:true}:{})}) as {trialId?: string;idleChunks?:boolean;muxedAudio?:boolean};
      if (!result || !/^[a-f0-9]{32}$/.test(result.trialId ?? '')) fail();
      if (this.armRequestId === armRequestId) this.armRequestId=null;
      if (generation !== this.generation) {
        this.cancelBackend(result.trialId!);
        return;
      }
      if(muxedAudio&&result.muxedAudio!==true){
        this.cancelBackend(result.trialId!);
        this.cancel('Update NC Desktop backend for the muxed trial','arm_failed');
        return;
      }
      if(chunkedIdle&&result.idleChunks!==true){
        this.chunkIdleUnsupported=true;
        this.report('chunk_mode_rejected',{operation:'arm'});
        this.cancelBackend(result.trialId!);
        this.cancel('Update NC Desktop backend for pre-rendered idle chunks','arm_failed');
        return;
      }
      if(chunkedIdle)this.chunkIdleUnsupported=false;
      this.chunkedIdle=chunkedIdle;
      this.snapshot = {...this.snapshot,phase:'armed',trialId:result.trialId!,chunkedIdle,
        ...(muxedAudio?{muxedAudio:true as const}:{}),message:'Armed — send one new message. One reply, including later speech chunks.'};
      this.timer = setTimeout(() => this.cancel('Live trial expired','arm_expired'),120000);
      this.report('armed'); this.changed();
    } catch (error) {
      if (generation === this.generation) {
        const status=(error as {httpStatus?:number})?.httpStatus;
        // A definite rejection allocated no owner. Only ambiguous outcomes
        // need reconciliation; normal busy retries must not fill tombstones.
        if (typeof status === 'number' && status >= 400 && status < 500) this.armRequestId=null;
        this.cancel('Live delivery backend unavailable','arm_failed');
      }
    }
  };
  // A successor already exists: reserve that exact audio identity instead of
  // taking another idle-time snapshot that would exclude it as old audio.
  recover = async (chunk: AudioChunk, signal: AbortSignal): Promise<boolean> => {
    // The legacy recovery route does not select or acknowledge embedded AAC.
    // Never silently downgrade an explicit muxed owner to separate audio.
    if(this.muxedAudio()===true||this.snapshot.muxedAudio===true)return false;
    // Recovery may precede a successful arm; keep the requested chunk mode even
    // when an incompatible backend rejected its first acknowledgement.
    this.chunkedIdle=this.chunkedIdle||this.idleChunks()===true;
    this.cancel('Recovering reply visuals');
    if (signal.aborted) return false;
    const generation = ++this.generation;
    this.run = ++runSequence; this.network = new AbortController();
    const network = this.network.signal;
    const cancel = () => { if (generation === this.generation) this.cancel(); };
    signal.addEventListener('abort',cancel,{once:true});
    this.snapshot = {...this.snapshot,phase:'arming',message:'Waiting for reply visual recovery…'};
    this.report('recovery_started'); this.changed();
    try {
      while (generation === this.generation && !signal.aborted) {
        const result = await this.request('POST',PREFIX+'recover',{audio:{id:chunk.id,
          phone_request_id:chunk.phone_request_id,url_path:chunk.url_path}}) as {state?: string; trialId?: string; reason?: string; idleChunks?:boolean};
        if (generation !== this.generation || signal.aborted) {
          if (/^[a-f0-9]{32}$/.test(result?.trialId ?? '')) {
            this.cancelBackend(result.trialId!);
          }
          return false;
        }
        if (result?.state === 'armed' && /^[a-f0-9]{32}$/.test(result.trialId ?? '')) {
          if(this.chunkedIdle&&result.idleChunks!==true){
            this.chunkIdleUnsupported=true;
            this.report('chunk_mode_rejected',{operation:'recover'});
            this.cancelBackend(result.trialId!);
            this.cancel('Update NC Desktop backend for pre-rendered idle chunks','recovery_failed');
            return false;
          }
          this.snapshot = {...this.snapshot,phase:'armed',trialId:result.trialId!,chunkedIdle:this.chunkedIdle,message:'Reply visuals recovered'};
          this.report('recovery_armed'); this.changed(); return true;
        }
        if (result?.state !== 'waiting' || result.reason !== 'worker_busy') fail();
        this.report('recovery_waiting',{reason:'worker_busy'});
        // Poll readiness, not a guessed startup deadline. Stop/disconnect aborts
        // the wait immediately; each HTTP operation retains its network timeout.
        await new Promise<void>(resolve => {
          const finish = () => { clearTimeout(timer); network.removeEventListener('abort',finish); resolve(); };
          const timer = setTimeout(finish,250);
          network.addEventListener('abort',finish,{once:true});
          if (network.aborted) finish();
        });
      }
    } catch {
      if (generation === this.generation) this.cancel('Live visual recovery unavailable — audio continues','recovery_failed');
    } finally { signal.removeEventListener('abort',cancel); }
    return false;
  };
  clearRetainedIdle = () => {
    this.retainingIdle = false;
    this.snapshot = {...this.snapshot,idle:null,idleVerified:false}; this.changed();
  };
  cancel = (message = 'Live delivery trial off', reason: 'owner_released' | 'arm_expired' | 'arm_failed' | 'handoff_failed'
    | 'prefetch_failed' | 'poll_failed' | 'advance_failed' | 'sequence_changed' | 'identity_unavailable' | 'reply_expired' | 'start_aborted'
    | 'anticipation_failed' | 'startup_video_failed' | 'recovery_failed' = 'owner_released') => {
    const id = this.snapshot.trialId;
    const armRequestId = this.armRequestId; this.armRequestId=null;
    const idle = this.retainIdleOnCancel && this.snapshot.idleVerified !== false ? this.snapshot.idle : null;
    this.retainingIdle = Boolean(idle);
    const sequenceIndex = this.active?.chunk.sequence_index;
    ++this.generation; this.network.abort(); clearTimeout(this.timer); clearTimeout(this.syncTimer);
    this.detachBuffered?.(); this.detachBuffered=undefined; this.buffered=null;
    this.speechReady = false; this.displayedAnticipation = null;
    this.unbindAudio?.(); this.unbindAudio = undefined;
    this.gateResolve?.(); this.gateResolve = undefined;
    ++this.anticipationFence; this.anticipationActivating = false;
    this.active = null; this.next = null; this.armedIdle = null;
    this.snapshot = {phase:'off',message,trialId:'',chunk:null,duration:0,segments:[],offsetSeconds:0,audioDuration:0,idle,idleVerified:Boolean(idle),anticipation:null,anticipationPending:false};
    if (armRequestId) {
      this.armCleanup={armRequestId,...(this.retainIdleOnCancel ? {idleMediaId:idle?.mediaId ?? null} : {})};
      this.report('arm_cancel_before_ack');
      void this.flushArmCleanup();
    }
    this.report('retired',{reason,sequenceIndex});
    this.changed();
    if (id) {
      this.cancelBackend(id);
    }
  };
  private context(chunk: AudioChunk): ChunkContext {
    const last = this.snapshot.segments.at(-1);
    return {chunk,identity:{id:chunk.id,phone_request_id:chunk.phone_request_id!,url_path:chunk.url_path},
      baseIndex:this.snapshot.segments.length,baseFrame:last ? last.startFrame+last.frameCount : 0,
      rows:[],segments:[],duration:0,frameCount:0,current:0,polling:null,promotion:null,advancing:null,reported:new Set(),reportedSource:'',idle:null};
  }
  prefetch = (chunk: AudioChunk | null | undefined) => {
    if (!chunk || !this.active?.rows.length || this.next
      || chunk.phone_request_id !== this.active.identity.phone_request_id
      || chunk.sequence_index !== this.active.chunk.sequence_index!+1) return;
    const ctx = this.context(chunk); this.next = ctx;
    this.report('prefetch_requested',{sequenceIndex:chunk.sequence_index});
    void this.poll(ctx).catch(() => { if (this.valid(ctx)) this.cancel('Live visuals unavailable — audio continues','prefetch_failed'); });
  };
  beforeStart = (chunk: AudioChunk, signal: AbortSignal, deadline: number): Promise<void> | void => {
    const first = this.snapshot.phase === 'armed';
    if (this.snapshot.phase === 'off' || this.snapshot.phase === 'arming' || !chunk.phone_request_id) return;
    if (!Number.isSafeInteger(chunk.sequence_index) || chunk.sequence_index! < 0 || (first && chunk.sequence_index !== 0 && !chunk.playback_recovery_epoch)) return;
    if (!first) {
      if (chunk.phone_request_id !== this.active?.identity.phone_request_id) { this.cancel(); return; }
      if (chunk.sequence_index! <= (this.active?.chunk.sequence_index ?? -1)) return;
      if (chunk.sequence_index !== this.active!.chunk.sequence_index!+1
        || (this.next && this.next.chunk.id !== chunk.id)) { this.cancel('Visual sequence changed — audio continues','sequence_changed'); return; }
      if (!this.active?.rows.length) { this.cancel('Previous visual identity unavailable — audio continues','identity_unavailable'); return; }
    }
    if (signal.aborted || (first && performance.now() >= deadline)) { this.cancel(undefined,'start_aborted'); return; }
    const ctx = this.next?.chunk.id === chunk.id ? this.next : this.context(chunk);
    const retainedIdle = ctx.idle?.mediaId && ctx.idle.mediaId === this.snapshot.idle?.mediaId
      ? this.snapshot.idle : ctx.idle ?? this.snapshot.idle;
    // Keep the reply-wide descriptors and loaded surfaces across promotion.
    this.active = ctx; this.next = null;
    this.unbindAudio?.(); this.gateResolve?.(); this.gateResolve = undefined;
    if (first) {
      this.startupStarted = performance.now();
      this.speechReady = false; this.displayedAnticipation = null; clearTimeout(this.syncTimer);
    }
    this.deadline = deadline; clearTimeout(this.timer);
    const cancel = () => this.cancel(); signal.addEventListener('abort',cancel,{once:true});
    this.unbindAudio = () => signal.removeEventListener('abort',cancel);
    this.snapshot = {...this.snapshot,phase:first ? 'preparing' : 'playing',chunk,
      offsetSeconds:ctx.baseFrame/24,audioDuration:ctx.duration,idle:retainedIdle,
      idleVerified:Boolean(ctx.idle),
      message:first ? 'Preparing live segments…' : 'Live delivery — continuous reply handoff'}; this.changed();
    const waiting = first ? new Promise<void>(resolve => { this.gateResolve = resolve; }) : undefined;
    // The audio owner's signal retires the reply, not elapsed reply duration.
    // Keep finite startup budgets; the backend separately expires stalled work.
    this.timer = first && deadline !== Infinity
      ? setTimeout(() => this.releaseGate(false),Math.max(0,deadline-performance.now())) : undefined;
    const generation = this.generation;
    const promotionStarted = performance.now();
    this.report('handoff_requested',{sequenceIndex:chunk.sequence_index});
    if (this.buffered) { this.refreshBuffered(); return waiting; }
    const promotion = this.request('POST',PREFIX+'prepare',{trialId:this.snapshot.trialId,audio:ctx.identity,currentIndex:0})
      .then(data => { if (generation === this.generation && this.valid(ctx)) {
        this.accept(ctx,data);
        this.report('handoff_confirmed',{sequenceIndex:chunk.sequence_index,elapsedMs:Math.max(0,performance.now()-promotionStarted)});
      } })
      .catch(() => { if (generation === this.generation && this.valid(ctx)) this.cancel('Live visuals unavailable — audio continues','handoff_failed'); })
      .finally(() => { if (ctx.promotion === promotion) ctx.promotion = null; });
    ctx.promotion = promotion;
    return waiting;
  };
  private accept(ctx: ChunkContext, value: unknown) {
    const status = parseLiveStatus(value,this.snapshot.trialId,ctx.identity);
    ctx.mediaId = status.mediaId;
    if (status.sourceState && status.sourceState !== ctx.reportedSource) {
      ctx.reportedSource = status.sourceState;
      this.report('source_state',{sourceState:status.sourceState,sequenceIndex:ctx.chunk.sequence_index});
    }
    if (status.state === 'unavailable') {
      this.report('producer_failure',{failureStage:status.failureStage || 'unknown',sequenceIndex:ctx.chunk.sequence_index});
      throw Error('Visual source unavailable');
    }
    this.beginAnticipation(ctx,status);
    if (ctx.segments.length && (ctx.duration !== status.durationSeconds || ctx.rows.length !== status.segments.length)) fail();
    // Reserving the successor can return the old third range to pending.
    // Readiness is revocable; never keep a URL merely because it was ready once.
    ctx.rows = status.segments;
    const publicationKey = JSON.stringify([ctx.current,ctx === this.next,ctx.rows.map(row => row.state)]);
    if (publicationKey !== ctx.reportedPublication) {
      ctx.reportedPublication = publicationKey;
      const published = ctx.rows.filter(row => row.state === 'ready');
      this.report('publication_buffer',{sequenceIndex:ctx.chunk.sequence_index,baseIndex:ctx.baseIndex,
        currentIndex:ctx.baseIndex+ctx.current,prefetched:ctx === this.next,plannedCount:ctx.rows.length,
        publishedCount:published.length,publishedSeconds:published.reduce((sum,row)=>sum+row.frameCount,0)/24,
        publishedIndices:published.slice(0,16).map(row=>ctx.baseIndex+row.index),
        publishedIndicesTruncated:published.length>16,
        pendingCount:ctx.rows.filter(row=>row.state === 'pending').length,
        unavailableCount:ctx.rows.filter(row=>row.state === 'unavailable').length});
    }
    if (status.idleSourceId && ctx.idle?.mediaId !== status.idleSourceId) ctx.idle = null;
    if (status.idle && (!ctx.idle || ctx.idle.uri !== status.idle.uri || ctx.idle.entryFrame !== status.idle.startFrame
      || ctx.idle.continuationReady !== status.idle.continuationReady)) {
      const index = ctx.idle?.uri === status.idle.uri ? ctx.idle.index : --this.sourceIdleSequence;
      ctx.idle = {index,startFrame:0,frameCount:status.idle.frameCount,
        uri:status.idle.uri,bytes:status.idle.bytes,entryFrame:status.idle.startFrame,
        mediaId:status.idle.mediaId,avatarId:status.idle.avatarId,
        continuationReady:status.idle.continuationReady,
        diagnosticEmotion:['neutral','angry','happy','sad','fear','surprise','disgust'].includes(ctx.chunk.emotion ?? '') ? ctx.chunk.emotion : 'other'};
    }
    if (ctx === this.active) {
      const previous = this.snapshot.idle;
      const sourceId = status.idleSourceId ?? ctx.idle?.mediaId;
      const sameSource = Boolean(sourceId && sourceId === previous?.mediaId);
      if (sameSource && ctx.idle && (ctx.idle.bytes !== previous!.bytes || ctx.idle.frameCount !== previous!.frameCount)) fail();
      // Keep the native/file buffer while identity is unknown, but never select
      // it for interruption until the backend verifies the new chunk's source.
      const idle = sameSource ? (ctx.idle && ctx.idle.continuationReady !== false && ctx.idle.entryFrame !== previous!.entryFrame
        ? {...ctx.idle,index:previous!.index} : previous) : ctx.idle ?? (sourceId ? null : previous);
      const verified = sameSource || Boolean(ctx.idle);
      if (idle !== previous || verified !== this.snapshot.idleVerified) {
        this.snapshot = {...this.snapshot,idle,idleVerified:verified};
        this.report('idle_source_verified',{sameSource,verified,hasBuffer:Boolean(idle),sequenceIndex:ctx.chunk.sequence_index});
        this.changed();
      }
    }
    if (!ctx.segments.length) {
      if (!Number.isSafeInteger(ctx.baseFrame+status.frameCount) || ctx.baseIndex !== this.snapshot.segments.length) fail();
      ctx.duration = status.durationSeconds; ctx.frameCount = status.frameCount;
      ctx.segments = status.segments.map(row => ({index:ctx.baseIndex+row.index,startFrame:ctx.baseFrame+row.startFrame,
        frameCount:row.frameCount,uri:PREFIX+'segment/'+status.mediaId+'/'+String(row.index).padStart(8,'0')+'.mp4',bytes:MAX_BYTES}));
      this.snapshot = {...this.snapshot,duration:(ctx.baseFrame+ctx.frameCount)/24,
        segments:[...this.snapshot.segments,...ctx.segments],
        audioDuration:this.active === ctx ? ctx.duration : this.snapshot.audioDuration};
      this.report('claimed',{segments:ctx.rows.length,sequenceIndex:ctx.chunk.sequence_index,prefetched:ctx === this.next,
        baseIndex:ctx.baseIndex,baseFrame:ctx.baseFrame,frameCount:ctx.frameCount,
        emotion:['neutral','angry','happy','sad','fear','surprise','disgust'].includes(ctx.chunk.emotion ?? '') ? ctx.chunk.emotion : 'other'});
      this.changed();
    }
  }
  private beginAnticipation(ctx: ChunkContext, status: Status) {
    if (this.snapshot.phase !== 'preparing' || ctx !== this.active || ctx.chunk.sequence_index !== 0 || this.anticipationActivating || status.anticipation === undefined) return;
    let plan: AnticipationStatus;
    try { plan = parseAnticipationStatus(status.anticipation); }
    catch { if (this.snapshot.anticipation) this.endAnticipation('failed'); this.report('anticipation_rejected',{reason:'invalid_plan'}); return; }
    const current = this.snapshot.anticipation;
    if (current) {
      if (plan.planId !== current.planId || plan.mediaId !== current.mediaId || plan.state !== 'active'
        || (status.sourceStartIndex != null && status.sourceStartIndex % plan.sourceFrameCount !== plan.speechEntryFrame)) {
        this.endAnticipation('failed'); return;
      }
      if (plan.cursor === current.cursor) { this.snapshot = {...this.snapshot,anticipation:plan}; this.changed(); }
      return;
    }
    if (plan.state !== 'available'
      || (status.sourceStartIndex !== undefined && status.sourceStartIndex !== null
        && status.sourceStartIndex % plan.sourceFrameCount !== plan.speechEntryFrame)) {
      this.report('anticipation_rejected',{planId:plan.planId,reason:plan.state === 'available' ? 'source_fence' : 'unavailable'});
      return;
    }
    const generation = this.generation, fence = ++this.anticipationFence, trialId = this.snapshot.trialId;
    this.frameTrace = {at:-Infinity,count:0};
    this.report('startup_plan',{planId:plan.planId,mediaId:plan.mediaId,target:plan.speechEntryFrame,
      sourceStartIndex:status.sourceStartIndex ?? null,frameCount:plan.sourceIndices.length,fps:plan.fps,
      cycleMs:plan.sourceIndices.length/plan.fps*1000,syncWaitMs:(plan.syncWaitSeconds ?? 0)*1000,
      elapsedMs:performance.now()-this.startupStarted,remainingMs:Math.max(0,this.deadline-performance.now())});
    this.anticipationActivating = true; this.snapshot = {...this.snapshot,anticipationPending:true}; this.changed();
    void this.request('POST',PREFIX+'anticipation-cursor',{trialId:this.snapshot.trialId,audio:ctx.identity,mediaId:status.mediaId,cursor:0})
      .then(value => {
        if (generation !== this.generation || fence !== this.anticipationFence || !this.valid(ctx) || this.snapshot.anticipation) {
          void this.request('POST',PREFIX+'anticipation-cursor',{trialId,audio:ctx.identity,mediaId:status.mediaId,cursor:null}).catch(() => {});
          return;
        }
        const reply = parseLiveStatus(value,this.snapshot.trialId,ctx.identity);
        const active = reply.anticipation === undefined ? null : parseAnticipationStatus(reply.anticipation);
        if (!active || active.planId !== plan.planId || active.mediaId !== plan.mediaId || active.state !== 'active' || active.cursor !== 0) {
          throw Error('Invalid anticipation activation');
        }
        this.anticipationActivating = false; this.snapshot = {...this.snapshot,anticipation:active,anticipationPending:false};
        this.report('anticipation_active',{planId:active.planId,cursor:0,role:'pre_audio'}); this.changed();
      }).catch(() => {
        void this.request('POST',PREFIX+'anticipation-cursor',{trialId,audio:ctx.identity,mediaId:status.mediaId,cursor:null}).catch(() => {});
        if (generation !== this.generation || fence !== this.anticipationFence) return;
        this.snapshot = {...this.snapshot,anticipationPending:false}; this.changed();
        this.report('anticipation_rejected',{planId:plan.planId,reason:'activation_failed'});
      })
      .finally(() => { if (fence === this.anticipationFence) this.anticipationActivating = false; });
  }
  endAnticipation(reason: 'ready' | 'deadline' | 'background' | 'cancelled' | 'failed' = 'cancelled') {
    if (reason === 'failed' && this.deadline === Infinity && this.snapshot.phase === 'preparing') {
      this.cancel('Live visuals unavailable — audio continues','anticipation_failed'); return;
    }
    const plan = this.snapshot.anticipation;
    const ctx = this.active;
    if (!plan || !ctx) { ++this.anticipationFence; this.anticipationActivating = false;
      if (this.snapshot.anticipationPending) { this.snapshot = {...this.snapshot,anticipationPending:false}; this.changed(); } return; }
    ++this.anticipationFence; this.anticipationActivating = false;
    this.snapshot = {...this.snapshot,anticipation:null,anticipationPending:false}; this.changed();
    this.report('anticipation_ended',{planId:plan.planId,cursor:plan.cursor,reason});
    if (!ctx.mediaId) return;
    void this.request('POST',PREFIX+'anticipation-cursor',{trialId:this.snapshot.trialId,audio:ctx.identity,
      mediaId:ctx.mediaId,cursor:null}).catch(() => {});
  }
  anticipationProgress = (cursor: number) => {
    const plan = this.snapshot.anticipation, ctx = this.active;
    if (!plan || !ctx || plan.state !== 'active' || plan.cursor === null || cursor <= plan.cursor) return;
    if (!plan.repeat && cursor >= plan.segments.length) { this.endAnticipation('failed'); return; }
    if (!ctx.mediaId) return;
    const generation = this.generation, fence = this.anticipationFence;
    const requestedAt = performance.now();
    this.report('anticipation_cursor_requested',{planId:plan.planId,cursor,previousCursor:plan.cursor,
      nextState:plan.segments[cursor % plan.segments.length]?.state,elapsedMs:requestedAt-this.startupStarted});
    void this.request('POST',PREFIX+'anticipation-cursor',{trialId:this.snapshot.trialId,audio:ctx.identity,
      mediaId:ctx.mediaId,cursor})
      .then(value => {
        if (generation !== this.generation || fence !== this.anticipationFence || !this.valid(ctx)
          || this.snapshot.phase !== 'preparing' || this.snapshot.anticipation?.cursor !== plan.cursor) return;
        const status = parseLiveStatus(value,this.snapshot.trialId,ctx.identity);
        const next = status.anticipation === undefined ? null : parseAnticipationStatus(status.anticipation);
        if (!next || next.planId !== plan.planId || next.mediaId !== plan.mediaId || next.state !== 'active' || next.cursor !== cursor) {
          this.endAnticipation('failed'); return;
        }
        this.snapshot = {...this.snapshot,anticipation:next};
        this.report('anticipation_cursor',{planId:next.planId,cursor,role:'pre_audio',
          requestMs:performance.now()-requestedAt,nextState:next.segments[cursor % next.segments.length]?.state}); this.changed();
      }).catch(() => { if (generation === this.generation && fence === this.anticipationFence) this.endAnticipation('failed'); });
  };
  suspendPresentation() {
    this.report('presentation_suspended',{sequenceIndex:this.snapshot.chunk?.sequence_index});
    // A hidden native surface cannot satisfy first-frame/anticipation gates.
    // Keep the speech identity but release that optional wait for the audio owner.
    this.releaseGate(false,'background');
  }
  private releaseGate(ready: boolean, reason: 'deadline' | 'background' = 'deadline') {
    if (this.snapshot.phase !== 'preparing') return;
    this.reportStartupPosition('startup_handoff',{ready});
    clearTimeout(this.timer); clearTimeout(this.syncTimer);
    this.endAnticipation(ready ? 'ready' : reason);
    this.snapshot = {...this.snapshot,phase:'playing',message:ready ? 'Live delivery — continuous reply handoff'
      : reason === 'background' ? 'Presentation hidden — audio continues' : 'Startup budget ended — audio continues'};
    this.report('startup_gate',{ready,elapsedMs:Math.max(0,performance.now()-this.startupStarted)});
    this.gateResolve?.(); this.gateResolve = undefined; this.changed();
  }
  // With no startup cutoff, a ready video waits for the actual return frame.
  // Finite callers retain their legacy deadline; cancellation remains separate.
  firstReady = () => {
    if (this.speechReady || this.snapshot.phase !== 'preparing' || performance.now() >= this.deadline) return;
    this.speechReady = true;
    this.reportStartupPosition('startup_speech_ready');
    const plan = this.snapshot.anticipation;
    if (plan?.syncWaitSeconds === undefined) { this.releaseGate(true); return; }
    const until = this.deadline === Infinity ? Infinity : Math.min(this.deadline,performance.now()+plan.syncWaitSeconds*1000);
    this.report('startup_sync',{reason:'waiting',planId:plan.planId,target:plan.speechEntryFrame,
      waitMs:until === Infinity ? null : until-performance.now()});
    if (until !== Infinity) this.syncTimer = setTimeout(() => {
      this.report('startup_sync',{reason:'deadline',planId:plan.planId,target:plan.speechEntryFrame});
      this.releaseGate(false);
    },Math.max(0,until-performance.now()));
    this.tryAlignedStart();
  };
  startupUnavailable = () => {
    if (this.deadline === Infinity && this.snapshot.phase === 'preparing')
      this.cancel('Live visuals unavailable — audio continues','startup_video_failed');
  };
  anticipationFrame = (planId: string, cursor: number, seconds: number) => {
    const plan = this.snapshot.anticipation;
    if (this.snapshot.phase !== 'preparing' || !plan || plan.planId !== planId || plan.cursor !== cursor
      || !Number.isFinite(seconds) || seconds < 0) return;
    const row = plan.segments[cursor % plan.segments.length];
    if (!row || row.state !== 'ready') return;
    const frame = Math.min(row.frameCount-1,Math.floor(seconds*plan.fps));
    const sourceFrame = plan.sourceIndices[row.startFrame+frame];
    if (sourceFrame === undefined) return;
    this.displayedAnticipation = {planId,cursor,sourceFrame,planFrame:row.startFrame+frame,observedAt:performance.now()};
    const now = performance.now();
    if (this.frameTrace.count < 80 && now-this.frameTrace.at >= 250) {
      this.frameTrace = {at:now,count:this.frameTrace.count+1};
      this.reportStartupPosition('startup_frame',{nativeSeconds:seconds});
    }
    this.tryAlignedStart();
  };
  private reportStartupPosition(phase: string, extra: Record<string,unknown> = {}) {
    const plan = this.snapshot.anticipation, seen = this.displayedAnticipation;
    const matching = Boolean(plan && seen && seen.planId === plan.planId);
    let framesUntilTarget: number | null = null;
    if (plan && seen && matching) {
      for (let step=0;step<plan.sourceIndices.length;step++) {
        if (plan.sourceIndices[(seen.planFrame+step)%plan.sourceIndices.length] === plan.speechEntryFrame) {
          framesUntilTarget=step;break;
        }
      }
    }
    this.report(phase,{planId:plan?.planId ?? null,cursor:plan?.cursor ?? null,
      sourceFrame:matching ? seen!.sourceFrame : null,observedCursor:matching ? seen!.cursor : null,
      sampleAgeMs:matching ? performance.now()-seen!.observedAt : null,target:plan?.speechEntryFrame ?? null,
      framesUntilTarget,speechReady:this.speechReady,elapsedMs:performance.now()-this.startupStarted,
      remainingMs:Math.max(0,this.deadline-performance.now()),...extra});
  }
  private tryAlignedStart() {
    const plan = this.snapshot.anticipation, displayed = this.displayedAnticipation;
    if (!this.speechReady || !plan || !displayed || displayed.planId !== plan.planId || displayed.cursor !== plan.cursor
      || performance.now()-displayed.observedAt > 100 || displayed.sourceFrame !== plan.speechEntryFrame) return;
    this.report('startup_sync',{reason:'aligned',planId:plan.planId,sourceFrame:displayed.sourceFrame});
    this.releaseGate(true);
  }
  refresh = () => {
    if (this.buffered) { this.refreshBuffered(); return; }
    const ctx = this.active;
    if (this.snapshot.phase === 'armed' && !ctx) {
      // The desktop may already show the next emotion. Until the next speech
      // source is validated, keep the idle source the phone actually displayed.
      if (this.retainingIdle && this.snapshot.idle) return;
      if (performance.now()-this.refreshedAt < 1000) return;
      this.refreshedAt = performance.now();
      const generation = this.generation;
      void this.request('GET', PREFIX+'status/'+this.snapshot.trialId).then(data => {
        // A first speech claim changes phase before this response arrives.
        if (generation !== this.generation || this.snapshot.phase !== 'armed') return;
        const parsedIdle = parseArmedIdleStatus(data, this.snapshot.trialId);
        const idle = parsedIdle && parsedIdle.uri !== this.armedIdle?.uri
          ? { ...parsedIdle, index: --this.armedIdleSequence } : parsedIdle;
        if ((idle?.uri ?? null) !== (this.armedIdle?.uri ?? null)) {
          this.armedIdle = idle;
          this.snapshot = {...this.snapshot, idle, idleVerified:Boolean(idle)}; this.changed();
        }
      }).catch(() => undefined);
      return;
    }
    // Ready idle metadata does not imply that the optional preparation plan or
    // its current/next encoded ranges have arrived yet.
    if (!ctx || (this.snapshot.phase !== 'preparing' && ctx.idle && ctx.idle.continuationReady !== false)
      || !this.busy || performance.now()-this.refreshedAt < 250) return;
    this.refreshedAt = performance.now();
    void this.poll(ctx).catch(() => { if (this.valid(ctx)) this.cancel('Live visuals unavailable — audio continues','poll_failed'); });
  };
  private poll(ctx: ChunkContext) {
    if (this.buffered) { this.refreshBuffered(); return Promise.resolve(); }
    if (ctx.promotion) return ctx.promotion;
    if (ctx.advancing) return ctx.advancing;
    if (ctx.polling) return ctx.polling;
    const generation = this.generation;
    // The backend still owns the previous chunk until promotion is confirmed.
    // Serialize only video lookahead; beforeStart still never waits for later audio.
    const promotion = ctx === this.next ? this.active?.promotion : null;
    const pending = (async () => {
      if (promotion) {
        this.report('prefetch_waiting',{sequenceIndex:ctx.chunk.sequence_index});
        await promotion;
      }
      if (generation !== this.generation || !this.valid(ctx)) return;
      const data = await (ctx === this.next
        ? this.request('POST',PREFIX+'prefetch',{trialId:this.snapshot.trialId,audio:ctx.identity})
        : this.request('GET',PREFIX+'status/'+this.snapshot.trialId));
        if (generation === this.generation && this.valid(ctx)) this.accept(ctx,data);
    })().finally(() => { if (ctx.polling === pending) ctx.polling = null; });
    ctx.polling = pending; return pending;
  }
  advance = (seconds: number | null): Promise<void> | void => {
    const ctx = this.active;
    if (seconds === null || !ctx || !Number.isFinite(seconds) || seconds < 0) return;
    if (ctx.promotion) {
      return ctx.promotion.then(() => { if (ctx === this.active) return this.advance(seconds); });
    }
    if (!ctx.rows.length) return;
    const index = Math.min(ctx.rows.length-1,Math.floor(seconds*2));
    if (this.buffered) { ctx.current=Math.max(ctx.current,index); return; }
    if (index <= ctx.current) return ctx.advancing ?? undefined;
    const inFlight = ctx.promotion ?? ctx.advancing ?? ctx.polling;
    if (inFlight) {
      return inFlight.then(() => { if (ctx === this.active) return this.advance(seconds); }).catch(() => {});
    }
    ctx.current = index;
    const generation = this.generation;
    const advancing = this.request('POST',PREFIX+'prepare',{trialId:this.snapshot.trialId,audio:ctx.identity,currentIndex:index})
      .then(data => { if (generation === this.generation && this.valid(ctx)) this.accept(ctx,data); })
      .catch(() => { if (generation === this.generation && this.valid(ctx)) this.cancel('Live visuals unavailable — audio continues','advance_failed'); })
      .finally(() => { if (ctx.advancing === advancing) ctx.advancing = null; });
    ctx.advancing = advancing;
    return advancing;
  };
  resolveSegment = async (uri: string, signal?: AbortSignal) => {
    const anticipation = this.snapshot.anticipation;
    if (anticipation) {
      const index = anticipation.segments.findIndex(row => row.uri === uri);
      const current = anticipation.cursor === null ? -1 : anticipation.cursor % anticipation.segments.length;
      const next = anticipation.cursor === null ? -1 : (anticipation.cursor+1) % anticipation.segments.length;
      if (index >= 0 && (index === current || index === next) && anticipation.segments[index]?.state === 'ready') {
        const generation = this.generation;
        const media = await this.resolver.resolve(uri);
        if (generation !== this.generation || this.snapshot.anticipation?.mediaId !== anticipation.mediaId
          || this.snapshot.anticipation?.cursor !== anticipation.cursor) throw Error('Retired anticipation segment');
        this.report('segment_published',{role:'pre_audio',planId:anticipation.planId,cursor:anticipation.cursor,
          index,bytes:anticipation.segments[index]!.bytes,
          sourceIndices:anticipation.sourceIndices.slice(anticipation.segments[index]!.startFrame,
            anticipation.segments[index]!.startFrame+anticipation.segments[index]!.frameCount)});
        return media.url;
      }
    }
    const idle = this.snapshot.idle ?? (this.snapshot.phase === 'armed' ? this.armedIdle : null);
    if (idle && uri === idle.uri) {
      const generation = this.generation;
      const media = await this.resolver.resolve(uri);
      if (uri !== this.snapshot.idle?.uri
        || (!this.retainIdleOnCancel && (generation !== this.generation || !this.busy))) throw Error('Retired idle video');
      this.report('idle_media_resolved',{role:'idle',index:idle.index,verified:this.snapshot.idleVerified ?? true,
        sourceEntryFrame:idle.entryFrame,sourceFrameCount:idle.frameCount,bytes:idle.bytes,
        sequenceIndex:this.snapshot.chunk?.sequence_index ?? null});
      return media.url;
    }
    const ctx = [this.active,this.next].find(candidate=>candidate?.segments.some(row=>row.uri === uri));
    if (!ctx) throw Error('Unadmitted segment');
    const index = ctx.segments.findIndex(row=>row.uri === uri);
    // Four speech slots can cross into the immediate successor's first three
    // ranges. Allow one child-selection step ahead of the parent cursor too.
    const maximum = ctx === this.next ? 2 : ctx.current+4;
    if (index < ctx.current || (index > maximum && (!this.buffered || ctx === this.next))) throw Error('Unadmitted segment');
    while (!signal?.aborted && this.valid(ctx) && index >= ctx.current) {
      if (ctx.advancing) { await ctx.advancing; continue; }
      // Child effects can request the heard successor before the parent's
      // advance effect moves its cursor. Keep the same admission window, but
      // wait instead of permanently failing the segment loader's one attempt.
      if (this.buffered && ctx !== this.next && index > ctx.current+4) {
        await new Promise<void>(resolve => setTimeout(resolve,75));continue;
      }
      const row = ctx.rows[index];
      if (this.buffered) {
        const local=this.buffered.prepared(ctx.chunk.id)?.segments.find(segment=>segment.index===index);
        if (local) {
          if (!this.buffered.ownsVideo(ctx.chunk.id,local.uri)) throw Error('Buffered video authority ended.');
          return local.uri;
        }
      }
      if (row?.state === 'unavailable') throw Error('Segment unavailable');
      if (row?.state === 'ready' && !this.buffered) {
        const media = await this.resolver.resolve(uri);
        if (!this.valid(ctx) || index < ctx.current) throw Error('Retired segment');
        if (!ctx.reported.has(index)) {
          ctx.reported.add(index);
          this.report('segment_published',{role:'speech',index,timelineIndex:ctx.baseIndex+index,
            sequenceIndex:ctx.chunk.sequence_index,bytes:row.bytes,
            sourceReadyAfterClaimMs:row.sourceReadyAfterClaimMs,encodeMs:row.encodeMs,
            videoBuildMs:row.encodeMs,publishedAfterClaimMs:row.publishedAfterClaimMs});
        }
        return media.url;
      }
      await this.poll(ctx);
      await new Promise<void>(resolve => setTimeout(resolve,75));
    }
    throw Error('Retired segment');
  };
}
