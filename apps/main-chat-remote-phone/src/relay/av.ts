import type { AudioChunk, PhoneReplyAuth } from '../api/types';
import type { PeerResponse } from './peer';
import {parseVideoQuality} from './idleLoopCache';
import type {IdleManifest,VerifiedLoop,VideoQuality} from './idleLoopCache';
import type {PhonePresentationPosition} from '../utils/phonePresentation';
import {declareHandoffRange,PhoneHandoffSession} from '../utils/phonePresentation';
import {SpeechOpeningSession} from './speechOpening';
import type {OpeningMedia} from './speechOpening';
import {parseSourceTimeline} from './frameHandoff';
import {RetainedHandoffSession} from './retainedHandoff';
import {parseAnticipationStatus} from '../dev/museTalkLiveTrial';
import type {NativeIdleChunkAPI} from '../native/idleChunkNativeReader';

export class AVCompatibilityError extends Error {
  readonly code = 'NC_AV_UPDATE_REQUIRED';
}

type Peer = { closed: boolean; request(method: 'GET' | 'POST', path: string, body?: Record<string, unknown>, timeoutMs?: number): Promise<PeerResponse> };
type Identity = { factory: string; peer: number; audio: string; video: string };
type Status = { started: boolean; completed: boolean; positionSeconds: number; failed: boolean; stopped: boolean;
  handoffState?:string;handoffFailure?:string;sourceFrame?:number;
  failureReason?: string; failureAtMs?: number; admissionReason?: string; chunkKey?: number; offsetSamples?: number };
export type AVObservation = (phase: 'play_requested' | 'native_stopped' | 'status_unavailable' | 'commit_failed' | 'admission_rejected' | 'prepare_superseded'
  | 'opening_requested' | 'opening_downloaded' | 'opening_decoded' | 'opening_failed' | 'opening_cancelled' | 'opening_skipped'
  | 'handoff_started' | 'handoff_retained' | 'handoff_failed' | 'handoff_scheduled' | 'handoff_sample'
  | 'handoff_declared' | 'handoff_confirmed' | 'handoff_rejected'
  | 'visual_visible' | 'visual_hidden' | 'visual_handle_changed' | 'visual_disabled' | 'visual_error' | 'visual_sample', status?: Status) => void;
// Only protocol-owned enums can cross the diagnostic boundary, never an OS
// error description, ticket, request identity, or native path.
export const admissionReasons = new Set(['invalid_descriptor', 'owner_not_open', 'queue_terminal', 'stale_key',
  'queue_capacity', 'duplicate_chunk', 'overlapping_range', 'stream_lease_unavailable', 'device_prepare_failed',
  'prepare_superseded', 'output_terminal', 'video_queue_capacity', 'duplicate_key', 'owner_mismatch',
  'handle_missing', 'attachment_not_ready', 'connection_paused', 'binding_not_current', 'binding_already_used',
  'binding_terminal', 'binding_capacity', 'binding_identity_mismatch', 'request_not_submitted',
  'request_outside_tail', 'item_missing', 'reply_capacity', 'reply_closed', 'chunk_capacity',
  'native_reason_unavailable', 'legacy_reason_unavailable']);
type NativeChunk = { key: number; ticket: string; requestId: string; chunkId: string; firstAudio: number;
  firstVideo: number; sampleCount: number; offsetSamples: number };
export type NativeAV = NativeIdleChunkAPI & {
  ncAVHandoffVersion?():number;
  ncAVHandoffBegin?(handle:string,key:number,revision:number,generation:string,plan:string,sourceCount:number,indices:number[]):Promise<boolean>;
  ncAVHandoffAppend?(handle:string,key:number,revision:number,index:number,uri:string):Promise<boolean>;
  ncAVHandoffArm?(handle:string,key:number,revision:number):Promise<number>;
  ncAVHandoffNext?(handle:string,key:number,revision:number,next:number,count:number,indices:number[]):Promise<boolean>;
  ncBufferedHandoffSource?(handle:string,key:number,revision:number,next:number,source:import('../native/bufferedHandoff').BufferedVisualSource):Promise<boolean>;
  ncAVHandoffStatus?(handle:string):unknown;
  ncAVOpeningVersion?():number;
  ncAVOpeningBegin?(handle:string,key:number):number;
  ncAVOpeningPrepare?(handle:string,key:number,revision:number,generation:string,media:string,uri:string,sourceCount:number,indices:number[]):Promise<boolean>;
  ncAVOpeningDetachBegin?(handle:string,key:number):string|null;
  ncAVOpeningDetachWait?(ticket:string):Promise<boolean>;
  ncIdleVideoVersion?():number;
  ncAVIdleBegin?(handle:string):number;
  ncAVIdlePrepare?(handle:string,generation:string,id:string,sha:string,fade:number,revision:number):Promise<boolean>;
  ncAVIdleSelect?(handle:string,generation:string,id:string):Promise<boolean>;
  ncAVIdleClear?(handle:string):void;
  ncAVIdleDetachBegin?(handle:string):string|null;
  ncAVIdleDetachWait?(ticket:string):Promise<boolean>;
  ncAVIdleClockVersion?():number;
  ncAVIdlePrepareFrame?(handle:string,generation:string,id:string,sha:string,fade:number,revision:number,sourceCount:number):Promise<boolean>;
  ncAVIdlePosition?(handle:string):unknown;
  ncAVReplyHandoffVersion?(): number;
  ncAVOpen(factory: string, peer: number, audio: string, video: string): string | null;
  ncAVReady(handle: string): boolean;
  ncAVVisual(handle: string, first: number, count: number, enabled: boolean): boolean;
  ncAVVisible(handle: string): boolean;
  ncAVPrepare(handle: string, chunk: NativeChunk): Promise<boolean>;
  ncAVPlay(handle: string, key: number): Promise<boolean>;
  ncAVStatus(handle: string, key: number): Status | null;
  ncAVSamples(handle: string, key: number): number[] | null;
  ncAVVolume(handle: string, value: number): void;
  ncAVStop(handle: string): void;
  ncAVRetire(handle: string, key: number): Promise<void>;
  ncAVClose(handle: string): void;
};
type Control = { generation: string; key: number; auth: PhoneReplyAuth; request_id: string; chunk_id: string; sequence_index: number; offset_samples: number };
type Descriptor = Control & { first_sample: number; first_rtp: number; video_first_rtp: number;
  sample_count: number; total_samples: number };
type PlaybackStatus = { currentTime: number; didJustFinish: boolean; playing: boolean; isLoaded: boolean;
  isBuffering: boolean; error?: string; nativeFailureReason?: string; playbackState: string; timeControlStatus: string };
const integer = (n: unknown, low: number, high: number): n is number => Number.isSafeInteger(n) && Number(n) >= low && Number(n) <= high;
const id = (n: unknown): n is string => typeof n === 'string' && n.length > 0 && n.length <= 128;
const object = (n: unknown): Record<string, unknown> => n && typeof n === 'object' ? n as Record<string, unknown> : {};
const wait = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

/** One authenticated peer, never persisted or transferred across reconnects.
 * This adapter schedules metadata. It has NO playback acknowledgement API:
 * existing native ownership/OS drain remains the only receipt authority.
 */
export class AVRemoteOutput {
  private handle = '';
  private closed = false;
  private revision = 0;
  private sequence = 0;
  private visualRevision = 0;
  private visualWanted = false;
  private scope = '';
  private peerScope = '';
  private entries = new Map<number, AVTrackPlayer>();
  private opening: Promise<void> | null = null;
  private retiring: Promise<unknown> = Promise.resolve();
  private idleRevision=0;
  private idlePrepared='';private idleSelected='';private idleManifest:IdleManifest|null=null;
  private idleNegotiated=false;
  private idleDetached:Promise<void>=Promise.resolve();
  private idleSelectedFile:VerifiedLoop|null=null;
  private videoQuality:VideoQuality|null=null;
  private handoffNegotiated=false;
  private speechOpenings=new Map<number,SpeechOpeningSession>();
  private visualRetiring:Promise<unknown>=Promise.resolve();
  private retainedHandoffs=new Map<number,RetainedHandoffSession>();
  private handoffLease:{handle:string;key:number;revision:number;requestId:string;motion:string;count:number}|null=null;
  private handoffObservation='';
  private phoneHandoff=new PhoneHandoffSession(()=>this.readIdlePosition(),state=>this.report(`handoff_${state}`));
  private preparing:Promise<void>=Promise.resolve();
  private constructor(private peer: Peer, readonly native: NativeAV, private identity: Identity,
    private generation: string, private audioOrigin: number, private videoOrigin: number,
    private observe?: AVObservation,private openingMedia?:OpeningMedia) {}

  static async connect(peer: Peer, native: NativeAV, identity: Identity | (() => Promise<Identity>), observe?: AVObservation,openingMedia?:OpeningMedia): Promise<AVRemoteOutput | null> {
    // The opening decoder alone is NOT the complete handoff capability. Native
    // modules do not advertise HandoffVersion until composition is accepted.
    const handoff=!!openingMedia && native.ncAVHandoffVersion?.()===1 && native.ncAVOpeningVersion?.()===1
      && typeof native.ncAVOpeningBegin==='function' && typeof native.ncAVOpeningPrepare==='function' && typeof native.ncAVOpeningDetachBegin==='function'
      && typeof native.ncAVOpeningDetachWait==='function'
      && ['ncAVHandoffBegin','ncAVHandoffAppend','ncAVHandoffArm','ncAVHandoffNext','ncAVHandoffStatus'].every(name=>typeof (native as any)[name]==='function');
    const response = await peer.request('POST', '/api/av/negotiate', { version: 1, native_audio: 1, native_video: 1, sparse_audio: 1,
      ...(handoff?{frame_handoff_version:1}:{}) }, 8000);
    if (peer.closed) throw new Error('NC media peer ended.');
    const value = object(response.body);
    if (response.status === 404 || (response.status === 200 && value.version === 0))
      throw new AVCompatibilityError('Update the NC desktop and enable its media runtime for Opus/H.264 playback.');
    if (value.sparse_audio !== 1)
      throw new AVCompatibilityError('Update NC desktop and NC Remote together for speech-only Opus playback.');
    const clocks = object(value.clocks), audio = object(clocks.audio), video = object(clocks.video);
    if (response.status !== 200 || value.version !== 1 || typeof value.generation !== 'string' || !/^[a-f0-9]{32}$/.test(value.generation)
      || value.audio !== 'opus' || value.video !== 'H264' || audio.clock_rate !== 48000 || video.clock_rate !== 90000
      || !integer(audio.origin, 0, 0xffffffff) || !integer(video.origin, 0, 0xffffffff)) throw new Error('Unsupported NC AV negotiation.');
    const tracks = typeof identity === 'function' ? await identity() : identity;
    if (!id(tracks.factory) || !id(tracks.audio) || !id(tracks.video) || !integer(tracks.peer, 0, 0x7fffffff) || peer.closed)
      throw new Error('NC remote media identity unavailable.');
    if(handoff && value.frame_handoff_version!==1)throw new AVCompatibilityError('Complete native handoff unavailable.');
    const output = new AVRemoteOutput(peer, native, tracks, value.generation, audio.origin, video.origin, observe,openingMedia);
    output.handoffNegotiated=handoff;
    output.idleNegotiated=value.idle_cache===1;
    if(value.video_quality!==undefined)output.videoQuality=parseVideoQuality(value.video_quality);
    try { await output.ensureOpen(); return output; }
    catch (error) { output.close(); throw error; }
  }
  get nativeHandle(): string { return this.handle; }
  handoffExchange(){return this.handoffNegotiated && this.presentationActive && this.idleSelectedFile
    ?this.phoneHandoff.exchange():null;}
  get idleSupported(){return this.idleNegotiated && this.native.ncIdleVideoVersion?.()===1 &&
    ['ncAVIdleBegin','ncAVIdlePrepare','ncAVIdleSelect','ncAVIdleClear'].every(key=>typeof (this.native as any)[key]==='function');}
  get idleBusy(){return this.entries.size>0;}
  get idleClockSupported(){return this.native.ncAVIdleClockVersion?.()===1 &&
    typeof this.native.ncAVIdlePrepareFrame==='function' && typeof this.native.ncAVIdlePosition==='function';}
  readIdlePosition():PhonePresentationPosition|null {
    if(!this.presentationActive || !this.idleClockSupported || !this.idleSelectedFile)return null;
    const binding=this.idleManifest?.active_source,file=this.idleSelectedFile;
    if(!binding || binding.loop_id!==file.id)return null;
    const value=object(this.native.ncAVIdlePosition?.(this.handle));
    if(value.generation!==file.generation || value.id!==file.id || value.sourceCount!==binding.source_frame_count
      || value.visible!==true || typeof value.paused!=='boolean' || typeof value.mediaId!=='string'
      || !/^[a-f0-9]{32}$/.test(value.mediaId) || !integer(value.sourceFrame,0,binding.source_frame_count-1)
      || typeof value.ageMs!=='number' || !Number.isFinite(value.ageMs) || value.ageMs<0 || value.ageMs>250)return null;
    const position:PhonePresentationPosition={avatarId:binding.avatar_id,mediaId:value.mediaId,sourceFrameCount:binding.source_frame_count,
      sourceFrame:value.sourceFrame,fps:24,playing:!value.paused};
    const handoffRange=this.handoffNegotiated?null:declareHandoffRange(position);
    return {...position,...(handoffRange?{handoffRange}:{})};
  }
  idleQualityMatches(manifest:IdleManifest):boolean {
    const quality=manifest.video_quality;
    return !quality || Boolean(this.videoQuality && quality.video_kbps===this.videoQuality.video_kbps
      && quality.video_width===this.videoQuality.video_width && quality.video_fps===this.videoQuality.video_fps);
  }
  private idleKey(file:VerifiedLoop,manifest:IdleManifest){return JSON.stringify([this.handle,file.generation,file.id,file.sha256,manifest.generation,manifest.active_source?.source_frame_count]);}
  async prepareIdle(file:VerifiedLoop,manifest:IdleManifest):Promise<boolean>{
    this.assertLive();
    if(!this.idleSupported || !this.visualWanted || file.id!==manifest.active_loop || !this.idleQualityMatches(manifest))return false;
    const revision=this.idleRevision,handle=this.handle;
    const nativeRevision=this.native.ncAVIdleBegin?.(handle);
    if(!nativeRevision || !Number.isSafeInteger(nativeRevision))return false;
    const source=manifest.active_source;
    const ready=source && this.idleClockSupported
      ? await this.native.ncAVIdlePrepareFrame?.(handle,file.generation,file.id,file.sha256,manifest.fade_ms,nativeRevision,source.source_frame_count)
      : await this.native.ncAVIdlePrepare?.(handle,file.generation,file.id,file.sha256,manifest.fade_ms,nativeRevision);
    if(revision!==this.idleRevision || handle!==this.handle || !this.presentationActive)return false;
    if(ready)this.idlePrepared=this.idleKey(file,manifest);
    return ready===true;
  }
  async selectIdle(file:VerifiedLoop,manifest:IdleManifest):Promise<boolean>{
    this.assertLive();const key=this.idleKey(file,manifest),revision=this.idleRevision;
    if(!this.visualWanted || key!==this.idlePrepared || !this.idleQualityMatches(manifest))return false;
    const ready=await this.native.ncAVIdleSelect?.(this.handle,file.generation,file.id);
    if(revision!==this.idleRevision || !this.presentationActive)return false;
    if(ready){
      if(this.idleSelected && (this.idleSelected!==key || JSON.stringify(this.idleManifest?.active_source)!==JSON.stringify(manifest.active_source)))this.clearSpeechOpenings();
      this.idleSelected=key;this.idleManifest=manifest;this.idleSelectedFile=file;
    }
    return ready===true;
  }
  async acknowledgeIdle(manifest:IdleManifest,ready:boolean):Promise<void>{
    this.assertLive();
    if(ready && (!this.idleSelected || !this.visualWanted || !this.idleQualityMatches(manifest) || this.idleManifest?.generation!==manifest.generation
      || this.idleManifest?.active_loop!==manifest.active_loop))throw new Error('Idle decoded selection unavailable.');
    const result=await this.peer.request('POST','/api/av/idle',{generation:this.generation,
      avatar_generation:manifest.generation,revision:manifest.revision,loop_id:manifest.active_loop,ready},8000);
    if(result.status!==200 || (result.body as any)?.ready!==ready)throw new Error('Idle presentation acknowledgement unavailable.');
  }
  clearIdle(){
    this.phoneHandoff.clear();
    this.clearSpeechOpenings();
    ++this.idleRevision;this.idlePrepared=this.idleSelected='';
    const manifest=this.idleManifest;this.idleManifest=null;this.idleSelectedFile=null;
    if(this.handle){
      if(this.native.ncAVIdleDetachBegin && this.native.ncAVIdleDetachWait){
        // Capture the native lifetime synchronously, before Stop removes handle.
        const ticket=this.native.ncAVIdleDetachBegin(this.handle);
        const next=ticket?this.native.ncAVIdleDetachWait(ticket):Promise.resolve(false);
        this.idleDetached=Promise.all([this.idleDetached,next]).then(([,safe])=>{
          if(!safe)throw new Error('Idle decoder detachment unavailable.');
        });
        void this.idleDetached.catch(()=>undefined);
      }else this.native.ncAVIdleClear?.(this.handle);
    }
    if(manifest && !this.closed && !this.peer.closed)void this.acknowledgeIdle(manifest,false).catch(()=>undefined);
    return this.idleDetached;
  }
  report(phase: Parameters<AVObservation>[0], status?: Status) {
    // Observability must never change playback, acknowledgement or retirement.
    try { this.observe?.(phase, status); } catch { /* diagnostic boundary only */ }
  }
  get presentationActive(): boolean { return !this.closed && !this.peer.closed && this.visualWanted; }
  get visible(): boolean { return Boolean(this.handle && this.native.ncAVVisible(this.handle)); }
  async present(enabled: boolean): Promise<void> {
    this.assertLive();
    const revision = this.revision, visualRevision = ++this.visualRevision;
    this.visualWanted = enabled;
    if(!enabled){this.clearIdle();this.clearSpeechOpenings();}
    // Hide synchronously, before a delayed data-channel acknowledgement.
    if (!enabled && this.handle) this.native.ncAVVisual(this.handle, 0, 0, false);
    if (enabled) await this.ensureOpen();
    this.assertLive(revision);
    if (visualRevision !== this.visualRevision) return;
    const handle = this.handle;
    const response = await this.peer.request('POST', '/api/av/visual', { generation: this.generation, enabled }, 8000);
    this.assertLive(revision);
    if (visualRevision !== this.visualRevision || handle !== this.handle) return;
    const d = object(response.body);
    if (response.status !== 200 || d.generation !== this.generation || d.enabled !== enabled
      || !integer(d.first_timestamp, 0, Number.MAX_SAFE_INTEGER) || !integer(d.first_rtp, 0, 0xffffffff)
      || d.first_rtp !== (this.videoOrigin + d.first_timestamp) % 0x100000000 || d.sample_count !== 28_800_000)
      throw new Error('Invalid NC avatar presentation descriptor.');
    if (enabled && !this.native.ncAVVisual(handle, d.first_rtp, d.sample_count as number, true))
      throw new Error('Native avatar presentation unavailable.');
  }
  private assertLive(revision = this.revision) {
    if (this.closed || this.peer.closed || revision !== this.revision) throw new Error('NC media lifetime ended.');
  }
  private async ensureOpen() {
    this.assertLive();
    if (this.opening) return this.opening;
    if (this.handle) {
      if (this.native.ncAVReady(this.handle)) return;
      this.stop();
      throw new Error('Native AV attachment ended.');
    }
    const revision = this.revision;
    const task = (async () => {
      const handle = this.native.ncAVOpen(this.identity.factory, this.identity.peer, this.identity.audio, this.identity.video);
      if (!handle) throw new Error('Native AV output unavailable.');
      this.handle = handle;
      const deadline = Date.now() + 5000;
      while (!this.native.ncAVReady(handle)) {
        this.assertLive(revision);
        if (Date.now() >= deadline) throw new Error('Native AV attachment timed out.');
        await wait(20);
      }
      this.assertLive(revision);
    })();
    this.opening = task;
    try { await task; }
    catch (error) { if (revision === this.revision) this.stop(); throw error; }
    finally { if (this.opening === task) this.opening = null; }
  }
  private async rpc(name: string, body: Control) {
    const result = await this.peer.request('POST', `/api/av/${name}`, body, 35000);
    if (result.status !== 200) throw new Error(`NC streamed audio ${name} failed.`);
    return object(result.body);
  }
  private clearSpeechOpenings(){
    this.handoffLease=null;this.handoffObservation='';
    for(const retained of this.retainedHandoffs.values())retained.close('cancelled');
    this.retainedHandoffs.clear();
    this.visualRetiring=Promise.all([this.visualRetiring,...[...this.speechOpenings.values()].map(opening=>opening.close())]);
    this.speechOpenings.clear();
  }
  sampleHandoff(){
    const lease=this.handoffLease;if(!lease)return;
    try{
      const value=object(this.native.ncAVHandoffStatus?.(lease.handle));
      const identity=JSON.stringify([value.key,value.state,value.failure]);
      if(identity===this.handoffObservation)return;this.handoffObservation=identity;
      this.report('handoff_sample',{started:false,completed:false,failed:false,stopped:false,positionSeconds:0,
        chunkKey:Number(value.key),handoffState:String(value.state),handoffFailure:String(value.failure),sourceFrame:Number(value.sourceFrame)});
    }catch{ /* Diagnostics never change playback ownership. */ }
  }
  private async prepareSpeechOpening(player:AVTrackPlayer){
    await this.visualRetiring;this.assertLive(player.revision);
    const lease=this.handoffLease;
    if(lease && lease.requestId===player.body.request_id && lease.key!==player.body.key){
      try{
      if(!await this.native.ncAVHandoffNext!(lease.handle,lease.key,lease.revision,player.body.key,lease.count,[]))
        throw Error('Native visual successor unavailable.');
      const deadline=Date.now()+30000;
      while(this.handoffLease===lease && this.visualWanted){
        const visual=await this.rpc('prepare-visual',player.body);this.assertLive(player.revision);
        if(visual.outcome==='ready'){
          const timeline=parseSourceTimeline(visual.source_timeline);
          if(timeline.motionId!==lease.motion || timeline.sourceFrameCount!==lease.count
            || !await this.native.ncAVHandoffNext!(lease.handle,lease.key,lease.revision,player.body.key,lease.count,timeline.sourceIndices))
            throw Error('Native visual successor mapping unavailable.');
          return;
        }
        if(!['anticipating','alignment_timeout'].includes(String(visual.outcome)) || Date.now()>=deadline)
          throw Error('Native visual successor preparation unavailable.');
        await wait(100);
      }
      this.assertLive(player.revision);return;
      }catch(error){
        this.assertLive(player.revision);this.report('handoff_failed');this.clearSpeechOpenings();return;
      }
    }
    if(!this.handoffNegotiated || !this.openingMedia || player.body.sequence_index!==0
      || player.body.offset_samples!==0 || !this.readIdlePosition())return;
    const visualRevision=this.visualRevision,idleSelection=this.idleSelected;
    const binding=this.idleManifest?.active_source,bindingKey=JSON.stringify(binding);
    const live=()=>!this.closed && !this.peer.closed && player.revision===this.revision
      && visualRevision===this.visualRevision && this.visualWanted && this.entries.get(player.body.key)===player
      && idleSelection===this.idleSelected && bindingKey===JSON.stringify(this.idleManifest?.active_source);
    const scope={handle:player.handle,generation:this.generation,ticket:player.ticketId,
      requestId:player.body.request_id,chunkId:player.body.chunk_id,key:player.body.key};
    // Before audio admission these fields describe the still-unstarted chunk;
    // only the phase reports visual preparation, never a heard/drained event.
    const observe=(phase:Parameters<AVObservation>[0])=>this.report(phase,{started:false,completed:false,failed:false,
      stopped:false,positionSeconds:player.body.offset_samples/48000,chunkKey:player.body.key,offsetSamples:player.body.offset_samples});
    const nativeRevision=this.native.ncAVOpeningBegin!(player.handle,player.body.key);
    if(!integer(nativeRevision,1,Number.MAX_SAFE_INTEGER))throw Error('Speech opening owner unavailable.');
    const opening=new SpeechOpeningSession({...this.openingMedia,live,
      prepare:async(s,file,value)=>{
        observe('opening_downloaded');
        return await this.native.ncAVOpeningPrepare!(s.handle,s.key,nativeRevision,s.generation,value.mediaId,file.uri,
          value.sourceTimeline.sourceFrameCount,value.sourceTimeline.sourceIndices);
      },
      detach:()=>{
        const ticket=this.native.ncAVOpeningDetachBegin!(player.handle,player.body.key);
        return ticket?this.native.ncAVOpeningDetachWait!(ticket):Promise.resolve(false);
      }});
    this.speechOpenings.set(player.body.key,opening);
    observe('opening_requested');
    try{
      let value:Record<string,unknown>;const deadline=Date.now()+30000;
      let retained:RetainedHandoffSession|undefined,retainedFailed=false;
      for(;;){
        value=await this.rpc('prepare-visual',player.body);this.assertLive(player.revision);
        if(!live())return;
        if(value.generation!==this.generation || value.key!==player.body.key)throw Error('Speech opening owner changed.');
        if(value.anticipation && !retained){
          const envelope=object(value.anticipation),plan=parseAnticipationStatus(envelope.plan);
          if(plan.avatarId!==binding?.avatar_id || plan.sourceFrameCount!==binding.source_frame_count)
            throw Error('Retained handoff source changed.');
          if(!this.phoneHandoff.claim(plan)){observe('handoff_rejected');throw Error('Retained handoff was not confirmed.');}
          if(!await this.native.ncAVHandoffBegin!(scope.handle,scope.key,nativeRevision,scope.generation,
            plan.planId,plan.sourceFrameCount,plan.sourceIndices))throw Error('Native retained handoff unavailable.');
          if(!live())return;
          retained=new RetainedHandoffSession({...this.openingMedia,
            live,request:async(method,path,body)=>{
              const result=await this.peer.request(method,path,body,15000);
              if(result.status!==200)throw Error('Retained handoff request unavailable.');return result.body;
            },onSegment:async(index,file)=>{
              if(!live() || !await this.native.ncAVHandoffAppend!(scope.handle,scope.key,nativeRevision,index,file.uri))
                throw Error('Retained handoff append unavailable.');
            },detach:()=>{
              const ticket=this.native.ncAVOpeningDetachBegin!(scope.handle,scope.key);
              return (ticket?this.native.ncAVOpeningDetachWait!(ticket):Promise.resolve(false)).then(safe=>{
                if(!safe)throw Error('Retained handoff detach unavailable.');
              });
            },diagnose:()=>{}});
          this.retainedHandoffs.set(scope.key,retained);observe('handoff_started');
          this.handoffLease={handle:scope.handle,key:scope.key,revision:nativeRevision,requestId:scope.requestId,
            motion:binding.motion_id,count:binding.source_frame_count};
          // Progressive native playback starts while later files and speech are
          // still being prepared; do not await the complete retained download.
          void retained.start(scope,envelope).then(()=>{if(live())observe('handoff_retained');},()=>{
            retainedFailed=true;if(live())observe('handoff_failed');
          });
        }
        if(value.outcome==='hidden' || value.outcome==='unmapped'){
          observe('opening_skipped');
          void opening.close();this.speechOpenings.delete(player.body.key);return;
        }
        if(value.outcome==='ready')break;
        if(!['anticipating','alignment_timeout'].includes(String(value.outcome)) || Date.now()>=deadline)
          throw Error('Speech opening preparation unavailable.');
        await wait(100);if(!live()){this.assertLive(player.revision);return;}
      }
      if(!value.opening)throw Error('Speech opening is not ready.');
      const timeline=parseSourceTimeline(value.source_timeline);
      if(timeline.motionId!==binding?.motion_id || timeline.sourceFrameCount!==binding.source_frame_count){
        // A real mood/motion switch uses the existing transition, not a false
        // same-source rendezvous. Valid speech remains independently authorized.
        observe('opening_skipped');void opening.close();this.speechOpenings.delete(player.body.key);return;
      }
      await opening.start(scope,value.opening,timeline);
      this.assertLive(player.revision);
      if(live())observe('opening_decoded');
      if(retained){
        for(;;){
          if(!live()){this.assertLive(player.revision);return;}
          if(retainedFailed || Date.now()>=deadline)throw Error('Native retained transition unavailable.');
          const requestedAt=performance.now();
          const delay=await this.native.ncAVHandoffArm!(scope.handle,scope.key,nativeRevision);
          const remaining=Math.floor(delay-(performance.now()-requestedAt));
          if(!live()){this.assertLive(player.revision);return;}
          if(remaining>=500 && remaining<=2000){observe('handoff_scheduled');return remaining;}
          await wait(20);
        }
      }
    }catch(error){
      observe(live()?'opening_failed':'opening_cancelled');
      if(this.closed || this.peer.closed || player.revision!==this.revision)throw error;
      this.clearSpeechOpenings();
      // Hiding does not make authorized background audio wait for a picture.
    }finally{
      if(!live()){
        this.retainedHandoffs.get(scope.key)?.close('cancelled');this.retainedHandoffs.delete(scope.key);
        void opening.close();this.speechOpenings.delete(player.body.key);
      }
    }
  }
  async prepare(chunk: AudioChunk, auth: PhoneReplyAuth, ticket: string, offsetSamples = 0): Promise<AVTrackPlayer> {
    this.assertLive();
    if (!id(ticket) || !id(chunk.phone_request_id) || !id(chunk.id) || !integer(chunk.sequence_index, 0, 2047)
      || !integer(offsetSamples, 0, 28_800_000) || !id(auth.client_key) || !id(auth.connection_epoch))
      throw new Error('Invalid NC reply identity.');
    const scope = JSON.stringify([ticket, auth.client_key, auth.connection_epoch]);
    const peerScope = JSON.stringify([auth.client_key, auth.connection_epoch]);
    const beforeRetirement = this.revision;
    await this.retiring; this.assertLive(beforeRetirement);
    if (this.scope && this.scope !== scope && !(this.peerScope === peerScope && this.entries.size === 0
        && this.native.ncAVReplyHandoffVersion?.() === 1)) this.stop();
    this.scope = scope;
    this.peerScope = peerScope;
    const revision = this.revision;
    await this.retiring; await this.ensureOpen(); this.assertLive(revision);
    if (this.entries.size >= 2 || [...this.entries.values()].some(p => p.body.request_id === chunk.phone_request_id && p.body.chunk_id === chunk.id))
      throw new Error('NC streamed audio queue is full.');
    const body: Control = { generation: this.generation, key: ++this.sequence, auth: { ...auth },
      request_id: chunk.phone_request_id, chunk_id: chunk.id, sequence_index: chunk.sequence_index, offset_samples: offsetSamples };
    const player = new AVTrackPlayer(this, this.handle, body, ticket, revision);
    if(this.handoffLease && this.handoffLease.requestId!==body.request_id)this.clearSpeechOpenings();
    this.entries.set(body.key, player);
    // An opening download can outlast the arrival of the next chunk. Preserve
    // reservation order without blocking Stop or a fresh peer lifetime.
    const previous=this.preparing;let releasePreparation=()=>{};
    if(this.handoffNegotiated)this.preparing=new Promise<void>(resolve=>{releasePreparation=resolve;});
    try {
      let visualDelay:number|undefined;
      if(this.handoffNegotiated){await previous;this.assertLive(revision);visualDelay=await this.prepareSpeechOpening(player);this.assertLive(revision);}
      const d = await this.rpc('prepare', {...body,...(visualDelay?{visual_start_delay_ms:visualDelay}:{})}); this.assertLive(revision);
      if (d.generation !== this.generation || d.key !== body.key || d.request_id !== body.request_id || d.chunk_id !== body.chunk_id
        || d.sequence_index !== body.sequence_index || d.offset_samples !== offsetSamples
        || !integer(d.first_sample, 0, Number.MAX_SAFE_INTEGER / 90000) || !integer(d.first_rtp, 0, 0xffffffff)
        || !integer(d.video_first_rtp, 0, 0xffffffff) || !integer(d.sample_count, 1, 28_800_000)
        || !integer(d.total_samples, 1, 28_800_000) || d.total_samples !== offsetSamples + d.sample_count
        || d.first_rtp !== (this.audioOrigin + d.first_sample) % 0x100000000
        || d.video_first_rtp !== (this.videoOrigin + Math.floor(d.first_sample * 90000 / 48000)) % 0x100000000)
        throw new Error('Invalid NC media descriptor.');
      let accepted: boolean;
      try {
        accepted = await this.native.ncAVPrepare(this.handle, { key: body.key, ticket,
          requestId: body.request_id, chunkId: body.chunk_id, firstAudio: d.first_rtp, firstVideo: d.video_first_rtp,
          sampleCount: d.sample_count, offsetSamples });
        if (!accepted) throw new Error('nc_av_admission:legacy_reason_unavailable');
      } catch (error) {
        this.assertLive(revision);
        const match = (error instanceof Error ? error.message : '').match(/nc_av_admission:([a-z_]+)(?![a-z_-])/);
        const candidateReason = match?.[1] ?? '';
        const reason = admissionReasons.has(candidateReason) ? candidateReason : 'native_reason_unavailable';
        this.report('admission_rejected', { started: false, completed: false, failed: true, stopped: false,
          positionSeconds: offsetSamples / 48000, admissionReason: reason, chunkKey: body.key, offsetSamples });
        throw new Error(`Native streamed reply admission rejected (${reason}).`);
      }
      this.assertLive(revision);
      player.prepared(d as Descriptor); return player;
    } catch (error) {
      // A retired prepare may settle after another explicit admission has
      // opened a fresh native handle. It owns neither that handle nor its queue.
      if (revision === this.revision) this.stop();
      else this.report('prepare_superseded', { started: false, completed: false, failed: false, stopped: true,
        positionSeconds: offsetSamples / 48000, chunkKey: body.key, offsetSamples });
      throw error;
    }finally{
      releasePreparation();
    }
  }
  async play(player: AVTrackPlayer) {
    this.assertLive(player.revision);
    this.report('play_requested');
    if (this.entries.get(player.body.key) !== player || !await this.native.ncAVPlay(player.handle, player.body.key))
      throw new Error('Native streamed playback unavailable.');
    this.assertLive(player.revision);
    const result = await this.rpc('commit', player.body); this.assertLive(player.revision);
    if (result.state !== 'admitted') throw new Error('Streamed reply commit rejected.');
  }
  retire(player: AVTrackPlayer) {
    if (this.entries.get(player.body.key) !== player) return;
    this.entries.delete(player.body.key);
    // Native completion has already occurred. Leave visual files alive while
    // the final mapped cached frame prepares; this wait emits no receipt and
    // cannot authorize/restart audio. A queued successor retains the same lease.
    if(this.entries.size===0){
      const lease=this.handoffLease;
      if(lease){
        void (async()=>{
          const deadline=Date.now()+3000;
          while(this.handoffLease===lease && this.entries.size===0 && Date.now()<deadline){
            this.sampleHandoff();
            const state=object(this.native.ncAVHandoffStatus?.(lease.handle)).state;
            if(['returned','ended','degraded'].includes(String(state)))break;
            await wait(20);
          }
          if(this.handoffLease===lease && this.entries.size===0)this.clearSpeechOpenings();
        })();
      }else this.clearSpeechOpenings();
    }
    const work = Promise.all([this.native.ncAVRetire(player.handle, player.body.key), this.rpc('retire', player.body)]);
    this.retiring = Promise.all([this.retiring, work]).catch(() => { this.stop(); });
  }
  stop() {
    this.clearSpeechOpenings();
    this.preparing=Promise.resolve();
    this.clearIdle();
    ++this.revision;
    ++this.visualRevision;
    if (this.visualWanted) {
      this.visualWanted = false;
      void this.peer.request('POST', '/api/av/visual', { generation: this.generation, enabled: false }, 8000).catch(() => undefined);
    }
    const handle = this.handle; this.handle = ''; this.opening = null;
    const players = [...this.entries.values()]; this.entries.clear();
    // A prefetched player's failure can retire the handle before the active
    // player's next poll. Preserve native causes/checkpoints before teardown.
    for (const player of players) player.snapshotBeforeStop();
    if (handle) { try { this.native.ncAVStop(handle); } finally { this.native.ncAVClose(handle); } }
    const retires = players.map(player => {
      player.invalidate();
      return this.rpc('retire', player.body).catch(() => undefined);
    });
    this.retiring = Promise.all([this.retiring, ...retires]);
  }
  close() { if (!this.closed) { this.closed = true; this.stop(); } }
}

/** Structural adapter for useAudioQueue. Status/samples are native observations,
 * not reconstructed from duration, delivery, a timer or current chat state.
 */
export class AVTrackPlayer {
  readonly ncAVPlayer = true;
  readonly isAudioSamplingSupported = true;
  private loaded = false;
  private removed = false;
  private error = '';
  private playing: Promise<void> | null = null;
  private level = 1;
  private sampling = false;
  private listeners = new Map<string, Set<(event: any) => void>>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private last: Status;
  constructor(private owner: AVRemoteOutput, readonly handle: string, readonly body: Control,
    private ticket: string, readonly revision: number) {
    this.last = { started: false, completed: false, stopped: false, failed: false, positionSeconds: body.offset_samples / 48000 };
  }
  get id() { return `nc-av-${this.body.key}`; }
  get ticketId(){return this.ticket;}
  get currentTime() { this.read(); return this.last.positionSeconds; }
  get isLoaded() { return this.loaded && !this.removed; }
  get volume() { return this.level; }
  set volume(value: number) {
    if (!Number.isFinite(value) || this.removed) return;
    this.level = Math.max(0, Math.min(1, value)); this.owner.native.ncAVVolume(this.handle, this.level);
  }
  prepared(_descriptor: Descriptor) { this.loaded = true; }
  ncBindPhoneReplyChunk(ticket: string, requestId: string, chunkId: string) {
    return this.loaded && !this.removed && ticket === this.ticket && requestId === this.body.request_id && chunkId === this.body.chunk_id;
  }
  async seekTo(seconds: number) {
    // Resume was already clipped by the source worker and bound natively. Never
    // mutate a running RTP clock, and never fall back to a second file player.
    if (this.playing || !Number.isFinite(seconds) || Math.abs(seconds - this.body.offset_samples / 48000) > 1 / 48000)
      throw new Error('Streamed audio position is fixed at admission.');
  }
  play() {
    if (this.removed || !this.loaded || this.playing) return;
    this.playing = this.owner.play(this).catch(() => {
      if (!this.removed) { this.owner.report('commit_failed'); this.error = 'Streamed reply playback failed.'; this.owner.stop(); }
    });
  }
  private read() {
    if (this.removed) return;
    const value = this.owner.native.ncAVStatus(this.handle, this.body.key);
    if (!value || !Number.isFinite(value.positionSeconds) || value.positionSeconds < this.body.offset_samples / 48000) {
      if (!this.error) this.owner.report('status_unavailable');
      this.error = 'Native streamed playback status unavailable.'; return;
    }
    this.last = value;
    if (value.failed || (value.stopped && !value.completed)) {
      if (!this.error) this.owner.report('native_stopped', value);
      this.error = 'Streamed reply playback stopped.';
    }
  }
  poll() {
    this.owner.sampleHandoff();
    this.read();
    const status: PlaybackStatus = { currentTime: this.last.positionSeconds, didJustFinish: this.last.completed,
      playing: this.last.started && !this.last.completed && !this.last.stopped && !this.error,
      isLoaded: this.isLoaded, isBuffering: !this.last.started && !this.error,
      ...(this.error ? { error: this.error } : {}), playbackState: this.error ? 'error' : 'ready',
      ...(this.error && this.last.failed ? { nativeFailureReason: this.last.failureReason } : {}),
      timeControlStatus: this.last.started && !this.last.completed && !this.error ? 'playing' : 'paused' };
    this.emit('playbackStatusUpdate', status);
    if (this.sampling && status.playing) {
      const frames = this.owner.native.ncAVSamples(this.handle, this.body.key);
      if (frames) this.emit('audioSampleUpdate', { channels: [{ frames }], timestamp: status.currentTime });
    }
  }
  private emit(name: string, event: unknown) {
    for (const callback of this.listeners.get(name) ?? []) {
      try { callback(event); }
      catch { console.warn('NC AV observer failed; playback lifetime cleanup continues.'); }
    }
  }
  setAudioSamplingEnabled(value: boolean) { this.sampling = value; }
  addListener(name: string, callback: (event: any) => void) {
    let set = this.listeners.get(name);
    if (!set) { set = new Set(); this.listeners.set(name, set); }
    set.add(callback);
    if (!this.timer) this.timer = setInterval(() => this.poll(), 100);
    return { remove: () => {
      set!.delete(callback);
      if (![...this.listeners.values()].some(value => value.size)) this.clearTimer();
    } };
  }
  private clearTimer() { if (this.timer) clearInterval(this.timer); this.timer = null; }
  snapshotBeforeStop() {
    try { this.read(); } catch { /* A missing native handle must not block Stop. */ }
  }
  invalidate() {
    this.removed = true; this.loaded = false; this.clearTimer();
    if (!this.last.completed) {
      this.error ||= 'NC media lifetime ended.';
      this.poll(); // Wake a waiting queue even if no more native/network events arrive.
    }
  }
  pause() { this.read(); if (!this.removed && !this.last.completed) this.owner.stop(); }
  remove() {
    if (this.removed) return;
    this.read();
    if (this.last.completed) { this.owner.retire(this); this.invalidate(); }
    else this.owner.stop();
    this.listeners.clear();
  }
  release() { this.remove(); }
}
