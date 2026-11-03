import {Platform} from 'react-native';
import {requireOptionalNativeModule} from 'expo';
import type {AudioPlayer} from 'expo-audio';
import {createPhoneAudioPlayer} from '../native/iosPlaybackGuard';
import type {AudioChunk} from '../api/types';
import type {MuxedTrialDelivery,MuxedTrialFile,MuxedTrialPlan} from './muxedTrialDelivery';
import {MuxedContinuousSession} from './muxedContinuousSession';
import type {RunHandle,SourceGrant,TailCursor,VisualEpoch,ReturnDescriptor,ContinuousBufferedAudio} from './muxedContinuousProtocol';
import type {QueuedIdleReader} from './muxedTrialIdle';
import {reportMuxedReturn} from '../utils/muxedReturnDiagnostics';

type MuxedPlayer=AudioPlayer&{
  ncPrepareMuxedTrial(files:MuxedTrialFile[],ticket:string,requestId:string,chunkId:string,frames:number,samples:number):Promise<boolean>;
  ncPrepareMuxedPresentationFixture?(files:MuxedTrialFile[],ticket:string,requestId:string,chunkId:string,
    frames:number,samples:number,groups:number[]):Promise<boolean>;
  ncCloseMuxedTrial():Promise<boolean>;
};
type SessionPlayer=MuxedPlayer&{
  ncEnableMuxedTrialSession():boolean;
  ncMuxedSourceRevision():number;
  ncRetireMuxedSource(revision:number):Promise<boolean>;
  ncPrepareMuxedEpoch(files:MuxedTrialFile[],ticket:string,requestId:string,chunkId:string,frames:number,samples:number,revision:number):Promise<boolean>;
  ncStageMuxedEpoch(files:MuxedTrialFile[],ticket:string,requestId:string,chunkId:string,frames:number,samples:number,revision:number):Promise<string|null>;
  ncStageMuxedStream(files:MuxedTrialFile[],ticket:string,requestId:string,chunkId:string,frames:number,samples:number,revision:number):Promise<string|null>;
  ncAppendMuxedStream(files:MuxedTrialFile[],first:number,revision:number):Promise<boolean>;
  ncDropMuxedEpoch(token:string):void;
  ncInstallMuxedEpoch(token:string,revision:number):Promise<boolean>;
  ncContinueMuxedEpoch(token:string,outgoingRevision:number):Promise<boolean>;
  ncPrepareMuxedIdle(files:MuxedTrialFile[],ticket:string,first:number,revision:number):Promise<boolean>;
  ncAppendMuxedIdle(files:MuxedTrialFile[],first:number,revision:number):Promise<boolean>;
  ncMuxedIdlePosition():{index:number;seconds:number}|null;
  ncPruneMuxedIdle(index:number,revision:number):Promise<boolean>;
  ncSealMuxedIdle(files:MuxedTrialFile[],target:number,frames:number,revision:number):Promise<boolean>;
  ncMuxedSilentEnded(revision:number):boolean;
};
type Epoch={revision:number;installed?:boolean;idleSealed?:boolean;closing?:Promise<void>;transfer?:Continuation;reads:Set<Promise<unknown>>;close:()=>Promise<void>};
type Continuation={from:Epoch;to:PreparedSource;started:boolean;finished:Promise<boolean>;
  resolve:(promoted:boolean)=>void;reject:(error:unknown)=>void};
type PlayerSettings=Parameters<typeof createPhoneAudioPlayer>[1];
type TrialAuthority=Pick<MuxedTrialDelivery,'files'|'owns'|'bindNative'>&Partial<Pick<MuxedTrialDelivery,'continuousDescriptor'>>;
type ProgressiveAuthority=Pick<MuxedTrialDelivery,'sourceTotals'|'waitForFiles'>;
export type MuxedSourceStage='continuation_reserved'|'continuation_unavailable'|'continuation_stale'
  |'native_continue_start'|'native_continue_complete'|'native_install_start'|'native_install_complete'|'source_activation_return';
type PreparedSource={files:MuxedTrialFile[];owns:()=>boolean;totals?:ReturnType<ProgressiveAuthority['sourceTotals']>;
  chunk:AudioChunk;identity:string;transferFailure?:unknown;
  ready:Promise<void>;token:string|null;targetRevision?:number;ended:boolean;epoch?:Epoch;pumpAbort:AbortController;
  restage:(epoch:Epoch)=>Promise<void>;
  detach:()=>Promise<void>;releaseSlot:()=>void;
  activation?:Promise<{player:AudioPlayer;detach:()=>Promise<void>;dispose:()=>void}>};
export function muxedTrialAvailable():boolean {
  if(Platform.OS!=='android')return false;
  try{return requireOptionalNativeModule<{ncMuxedTrialVersion?():number}>('ExpoAudio')?.ncMuxedTrialVersion?.()===2;}
  catch{return false;}
}
export function muxedChunkStreamAvailable():boolean {
  if(!muxedTrialAvailable())return false;
  try{return requireOptionalNativeModule<{ncMuxedChunkStreamVersion?():number}>('ExpoAudio')?.ncMuxedChunkStreamVersion?.()===1;}
  catch{return false;}
}
export function muxedSourceFenceAvailable():boolean {
  if(!muxedTrialAvailable())return false;
  try{return requireOptionalNativeModule<{ncMuxedSourceFenceVersion?():number}>('ExpoAudio')?.ncMuxedSourceFenceVersion?.()===1;}
  catch{return false;}
}
export function muxedContinuationAvailable():boolean {
  if(!muxedSourceFenceAvailable())return false;
  try{return requireOptionalNativeModule<{ncMuxedContinuationVersion?():number}>('ExpoAudio')?.ncMuxedContinuationVersion?.()===1;}
  catch{return false;}
}
export function muxedContinuousAvailable():boolean {
  if(Platform.OS!=='android')return false;
  try{return requireOptionalNativeModule<{ncContinuousMuxedQueueVersion?():number}>('ExpoAudio')?.ncContinuousMuxedQueueVersion?.()===2;}
  catch{return false;}
}

/** Factory for the existing queue only. No play, focus or receipt RPC here.
 * Native muxed preparation binds the exact reply once on a fresh null-source
 * registered AudioPlayer; a generic ticket bind would consume that attempt.
 */
export function createMuxedTrialAudio(delivery:Pick<MuxedTrialDelivery,'files'|'owns'|'bindNative'>) {
  return createMuxedAudioFactory(delivery);
}

/** Explicit inert diagnostic, never a live downgrade. The same registered
 * queue/guard owns all output and its whole-source receipt. Grouping changes
 * only shadow identity observation; it cannot mint per-source receipts.
 */
export function createMuxedPresentationProbeAudio(delivery:TrialAuthority,groups:readonly number[]) {
  if(groups.length<2||groups.length>64||groups.some(n=>!Number.isSafeInteger(n)||n<1||n>60))
    throw Error('Invalid presentation fixture grouping.');
  return createMuxedAudioFactory(delivery,[...groups]);
}

function createMuxedAudioFactory(delivery:TrialAuthority,groups?:number[]) {
  return async(chunk:AudioChunk,settings:Parameters<typeof createPhoneAudioPlayer>[1],ticket:string|null,
    signal:AbortSignal):Promise<{player:AudioPlayer;detach:()=>Promise<void>}>=>{
    if(!muxedTrialAvailable()||signal.aborted||!ticket||!chunk.phone_request_id)throw Error('Guarded muxed trial unavailable.');
    const files=delivery.files(chunk);
    if(!files.length||files.some(file=>!delivery.owns(chunk,file.uri)))throw Error('Muxed file authority ended.');
    const player=createPhoneAudioPlayer(null,settings,null) as MuxedPlayer;
    let closing:Promise<void>|undefined;
    let preparation:Promise<boolean>|undefined;
    const close=():Promise<void>=>closing??=(async()=>{
      player.pause();
      if(await player.ncCloseMuxedTrial()!==true)throw Error('Muxed native detach unconfirmed.');
      // Stop output immediately, then retain the files until the off-main
      // extractor validator has also relinquished its native reader.
      await preparation?.catch(()=>false);
    })();
    let detach=close;
    const cancel=()=>{void detach().catch(()=>undefined);};
    try {
      if(typeof player.ncPrepareMuxedTrial!=='function'||typeof player.ncCloseMuxedTrial!=='function')
        throw Error('Update NC Remote for guarded muxed trial.');
      if(groups&&(typeof player.ncPrepareMuxedPresentationFixture!=='function'
        ||requireOptionalNativeModule<{ncMuxedPresentationProbeVersion?():number}>('ExpoAudio')?.ncMuxedPresentationProbeVersion?.()!==1
        ||groups.reduce((n,count)=>n+count,0)!==files.length))throw Error('Update NC Remote for the guarded presentation fixture.');
      // Own the reader before asynchronous native validation. Closing a fresh
      // native player also retires it, so a late prepare cannot revive output.
      detach=delivery.bindNative(chunk,close);
      signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
      const frames=files.reduce((n,file)=>n+file.frameCount,0),samples=files.reduce((n,file)=>n+file.validSamples,0);
      if(signal.aborted)throw Error('Muxed native admission cancelled.');
      preparation=groups?player.ncPrepareMuxedPresentationFixture!(files,ticket,chunk.phone_request_id,chunk.id,frames,samples,[...groups])
        :player.ncPrepareMuxedTrial(files,ticket,chunk.phone_request_id,chunk.id,frames,samples);
      const ready=await preparation;
      if(ready!==true||signal.aborted||files.some(file=>!delivery.owns(chunk,file.uri)))throw Error('Muxed native admission ended.');
      return {player,detach};
    }catch(error){
      // Detach failure keeps the retained source pinned rather than unlinking
      // under a decoder. The delivery owner remains responsible for cleanup.
      if(typeof player.ncCloseMuxedTrial==='function')await detach();
      try{player.remove();}finally{player.release();}
      throw error;
    }finally{signal.removeEventListener('abort',cancel);}
  };
}

/** Development-only owner of one registered player across silent idle and
 * exact reply sources. Epoch retirement fences output before joining native
 * file readers. Queue disposal retires only its source, never this player. */
export class MuxedTrialAudioSession {
  private player?:SessionPlayer;
  private current?:Epoch;
  private serial:Promise<unknown>=Promise.resolve();
  private closed=false;
  private closing?:Promise<void>;
  private readonly pending=new Set<()=>Promise<void>>();
  private readonly sources=new Map<string,PreparedSource>();
  private readonly ownedRetirements=new Set<number>();
  private stagingSerial:Promise<void>=Promise.resolve();
  private nativeAdmissionSerial:Promise<void>=Promise.resolve();
  private progressiveFailure?:unknown;
  private continuation?:Continuation;
  private continuousOwner?:MuxedContinuousSession;
  private continuousOpening?:Promise<unknown>;
  constructor(private readonly delivery:TrialAuthority,private readonly beforeSpeech?:
    (chunk:AudioChunk,signal:AbortSignal)=>Promise<void>,private readonly progressive?:ProgressiveAuthority,
    private readonly observer?:(stage:MuxedSourceStage,chunk:AudioChunk)=>void){}

  private observe(stage:MuxedSourceStage,chunk:AudioChunk){
    try{this.observer?.(stage,chunk);}catch{} // Diagnostics cannot gate admission or cleanup.
  }

  checkProgress(){if(this.progressiveFailure)throw this.progressiveFailure;}
  private continuous():MuxedContinuousSession {
    if(!this.delivery.continuousDescriptor)throw Error('Update NC Remote for continuous retained authority.');
    return this.continuousOwner??=new MuxedContinuousSession(this.delivery as TrialAuthority&
      Pick<MuxedTrialDelivery,'continuousDescriptor'>,this.progressive);
  }
  createContinuousPlayer(chunk:AudioChunk,plan:MuxedTrialPlan,settings:PlayerSettings,ticket:string,signal:AbortSignal){
    const work=(async()=>{
      if(this.closed||signal.aborted||!muxedContinuousAvailable()||!this.progressive)
        throw Error('Update NC Remote for continuous muxed queue version2.');
      await this.beforeSpeech?.(chunk,signal);
      if(this.closed||signal.aborted)throw Error('Continuous muxed owner ended.');
      const player=this.ensurePlayer(settings),idle=this.current;
      if(idle&&(!idle.installed||!idle.idleSealed||idle.closing||player.ncMuxedSourceRevision()!==idle.revision
        ||player.ncMuxedSilentEnded(idle.revision)!==true))throw Error('Continuous initial idle certificate unavailable.');
      return this.continuous().open(player,chunk,plan,ticket,signal,async()=>{
        // The exact native open ACK positively joins the sealed idle's
        // delegated readers and settles its sink before enrolling this run.
        // Only that ACK may consume this current player's captured idle epoch.
        if(idle){if(this.current!==idle)throw Error('Continuous initial idle changed.');
          this.current=undefined;await idle.close();}
      });
    })();this.continuousOpening=work;void work.catch(()=>undefined);return work;
  }
  appendContinuousSource(tail:TailCursor,chunk:AudioChunk,plan:MuxedTrialPlan,ticket:string,signal:AbortSignal){
    return this.continuous().append(tail,chunk,plan,ticket,signal);
  }
  async appendContinuousReturn(tail:TailCursor,descriptor:ReturnDescriptor,files:MuxedTrialFile[],
    signal:AbortSignal,owns:()=>boolean):Promise<(QueuedIdleReader&{visual:VisualEpoch})|null>{
    if(this.closed||!this.player||!this.continuousOwner)throw Error('Continuous RETURN player unavailable.');
    const owner=this.continuousOwner,player=this.player;
    const admitted=await owner.appendFinalReturn(tail,descriptor,files,signal,owns);
    if(admitted.kind==='blocked')return null;
    if(this.closed||this.player!==player||this.continuousOwner!==owner||signal.aborted||!owns())
      throw Error('Continuous RETURN owner ended.');
    const epoch=admitted.visual;
    return {player,visual:epoch,append:(rows,first)=>owner.appendVisual(epoch,rows,first),
      position:()=>owner.visualPosition(epoch),prune:index=>owner.pruneVisual(epoch,index)};
  }
  readContinuous=(run:RunHandle,afterCursor:number)=>this.continuous().read(run,afterCursor);
  acknowledgeContinuous=(run:RunHandle,throughCursor:number)=>this.continuous().acknowledge(run,throughCursor);
  sealContinuous=(tail:TailCursor)=>this.continuous().sealTail(tail);
  retireContinuousSource=(source:SourceGrant)=>this.continuous().retireSource(source);
  retireContinuousRun=(run:RunHandle)=>this.continuous().retireRun(run);
  invalidateContinuous=(run:RunHandle,reason:Parameters<ContinuousBufferedAudio['invalidate']>[1])=>this.continuous().invalidate(run,reason);

  private ensurePlayer(settings:PlayerSettings):SessionPlayer{
    if(!this.player){
      const player=createPhoneAudioPlayer(null,settings,null) as SessionPlayer;
      try{
        if(typeof player.ncStageMuxedEpoch!=='function'||typeof player.ncInstallMuxedEpoch!=='function'
          ||typeof player.ncDropMuxedEpoch!=='function'||typeof player.ncMuxedSourceRevision!=='function'
          ||player.ncEnableMuxedTrialSession()!==true)throw Error('Update NC Remote for persistent muxed trial.');
      }catch(error){try{player.remove();}finally{player.release();}throw error;}
      this.player=player;
    }
    return this.player;
  }

  private sourceIdentity(chunk:AudioChunk){return JSON.stringify([chunk.id,chunk.phone_request_id,chunk.sequence_index,
    chunk.url_path,chunk.playback_recovery_epoch]);}

  /** Called synchronously from the actual-drain observer, before queue abort
   * starts old-source cleanup. This reserves no output permission. */
  reserveContinuation(from:AudioChunk,to:AudioChunk):boolean {
    if(this.closed||this.continuation||!muxedContinuationAvailable()||!this.current?.installed||this.current.closing
      ||typeof this.player?.ncContinueMuxedEpoch!=='function'){
      this.observe('continuation_unavailable',to);return false;
    }
    const previous=[...this.sources.values()].find(source=>source.epoch===this.current&&source.identity===this.sourceIdentity(from));
    const next=[...this.sources.values()].find(source=>source.identity===this.sourceIdentity(to)&&!source.ended);
    if(!previous||previous.ended||!next?.token||!next.owns()||next.targetRevision!==this.current.revision+1){
      this.observe('continuation_stale',to);return false;
    }
    let resolve!:(value:boolean)=>void,reject!:(error:unknown)=>void;
    const finished=new Promise<boolean>((yes,no)=>{resolve=yes;reject=no;});void finished.catch(()=>undefined);
    this.continuation={from:this.current,to:next,started:false,finished,resolve,reject};
    this.current.transfer=this.continuation;this.observe('continuation_reserved',to);return true;
  }
  cancelContinuation():void {
    const pending=this.continuation;if(!pending||pending.started)return;
    this.continuation=undefined;pending.resolve(false);
  }

  private epoch(player:SessionPlayer,revision:number):Epoch {
    const epoch:Epoch={revision,reads:new Set(),close:()=>epoch.closing??=(async()=>{
      try{
        // Successful transfer acknowledges old delegated readers, not just
        // timeline mutation. An old close must never pause its successor.
        if(epoch.transfer&&await epoch.transfer.finished)return;
        if(this.current!==epoch)return;
        player.pause();
        if(await player.ncRetireMuxedSource(revision)!==true)throw Error('Muxed source detach unconfirmed.');
        if(player.ncMuxedSourceRevision()===revision+1)this.ownedRetirements.add(revision);
      }finally{await Promise.allSettled([...epoch.reads]);}
      if(this.current===epoch)this.current=undefined;
    })()};return epoch;
  }

  private async begin(settings:PlayerSettings,ticket:string|null,signal:AbortSignal,source?:PreparedSource):Promise<Epoch>{
    const work=this.serial.then(async()=>{
      if(this.closed||signal.aborted||!ticket||!muxedTrialAvailable())throw Error('Muxed session authority ended.');
      const pending=this.continuation;
      if(pending&&pending.to===source){
        const player=this.player!,old=pending.from;
        if(this.current!==old||!source!.token||source!.ended||!source!.owns()
          ||source!.targetRevision!==old.revision+1||player.ncMuxedSourceRevision()!==old.revision){
          this.cancelContinuation();throw Error('Muxed continuation authority ended.');
        }
        pending.started=true;
        // Pin successor files even if Stop arrives during the native removal /
        // reader-close barrier, before its concrete epoch has been installed.
        const installing:Epoch={revision:old.revision+1,reads:new Set(),close:async()=>{
          if(await pending.finished&&source!.epoch!==installing)await source!.epoch?.close();
        }};
        source!.epoch=installing;
        try{
          const ready=await this.read(old,()=>this.nativeAdmission(()=>{
            this.observe('native_continue_start',source!.chunk);
            return player.ncContinueMuxedEpoch(source!.token!,old.revision);
          }));
          if(ready!==true||player.ncMuxedSourceRevision()!==old.revision+1)throw Error('Muxed continuation detach unconfirmed.');
          this.observe('native_continue_complete',source!.chunk);
          const admitted=this.epoch(player,old.revision+1);admitted.installed=true;
          this.current=admitted;source!.epoch=admitted;this.ownedRetirements.add(old.revision);
          this.continuation=undefined;pending.resolve(true);return admitted;
        }catch(error){
          // Native may already have mutated the playlist. Never free either
          // source or fall back to ordinary install on an unconfirmed result.
          source!.transferFailure=error;this.continuation=undefined;pending.reject(error);throw error;
        }
      }
      this.cancelContinuation();
      await this.current?.close();
      if(this.closed||signal.aborted)throw Error('Muxed source admission cancelled.');
      const player=this.ensurePlayer(settings),revision=player.ncMuxedSourceRevision();
      if(!Number.isSafeInteger(revision)||revision<0)throw Error('Muxed native owner retired.');
      const epoch=this.epoch(player,revision);
      this.current=epoch;return epoch;
    });
    this.serial=work.then(()=>undefined,()=>undefined);return work;
  }
  private admits(epoch:Epoch,signal:AbortSignal,owns:()=>boolean):boolean{
    return !this.closed&&!epoch.closing&&this.current===epoch&&!signal.aborted&&owns()
      &&this.player?.ncMuxedSourceRevision()===epoch.revision;
  }
  private read<T>(epoch:Epoch,operation:()=>Promise<T>):Promise<T>{
    const work=operation();epoch.reads.add(work);
    void work.then(()=>epoch.reads.delete(work),()=>epoch.reads.delete(work));return work;
  }
  private nativeAdmission<T>(operation:()=>Promise<T>):Promise<T>{
    const work=this.nativeAdmissionSerial.then(operation);
    this.nativeAdmissionSerial=work.then(()=>undefined,()=>undefined);return work;
  }

  private source(chunk:AudioChunk,settings:PlayerSettings,ticket:string|null,signal:AbortSignal):PreparedSource{
    if(!chunk.phone_request_id)throw Error('Muxed reply identity missing.');
    this.checkProgress();
    const files=this.progressive?this.delivery.files(chunk).slice(0,2):this.delivery.files(chunk);
    const totals=this.progressive?.sourceTotals(chunk);
    const frames=totals?.frameCount??files.reduce((n,file)=>n+file.frameCount,0);
    const samples=totals?.samples??files.reduce((n,file)=>n+file.validSamples,0);
    const owns=()=>files.length>0&&files.every(file=>this.delivery.owns(chunk,file.uri));
    if(!owns()||this.closed||signal.aborted||!ticket||!muxedTrialAvailable())throw Error('Muxed file authority ended.');
    const key=JSON.stringify([ticket,chunk.phone_request_id,chunk.id,files,totals]);
    const existing=this.sources.get(key);if(existing&&!existing.ended)return existing;
    const previous=this.stagingSerial;
    let releaseSlot!:()=>void;
    const slot=new Promise<void>(resolve=>{releaseSlot=resolve;});
    // A cancelled waiter cannot let its successor overtake the occupied slot.
    this.stagingSerial=previous.then(()=>slot);
    const pumpAbort=new AbortController();
    let staging:Promise<string|null>|undefined,closing:Promise<void>|undefined,player:SessionPlayer|undefined;
    const source:PreparedSource={files,owns,totals,chunk:{...chunk},identity:this.sourceIdentity(chunk),ready:Promise.resolve(),token:null,ended:false,pumpAbort,
      detach:()=>close(),releaseSlot,restage:async epoch=>{
        if(source.ended||!this.admits(epoch,signal,owns))throw Error('Muxed staged admission ended.');
        // Keep this source's original native reader and occupied future slot.
        // Only its exact stale token is dropped before validating the same files.
        player!.ncDropMuxedEpoch(source.token!);source.token=null;source.targetRevision=undefined;
        await this.read(epoch,()=>stage(epoch.revision));
        if(!source.token||source.targetRevision!==epoch.revision||source.ended||!this.admits(epoch,signal,owns))
          throw Error('Muxed staged admission ended.');
      }};
    const stage=(revision:number):Promise<string|null>=>{
      staging=this.nativeAdmission(async()=>{
        if(source.ended||this.closed||signal.aborted||!owns())throw Error('Muxed staged admission ended.');
        const owner=this.current;
        // Native creates the token after off-main validation. No source may
        // install until that response and its target capture both settle.
        // Retirement remains free to fence the outstanding validator.
        const value=await (totals?player!.ncStageMuxedStream(files,ticket!,chunk.phone_request_id!,chunk.id,frames,samples,revision)
          :player!.ncStageMuxedEpoch(files,ticket!,chunk.phone_request_id!,chunk.id,frames,samples,revision));
        source.token=value;
        const installed=owner?.revision===revision&&owner.installed;
        source.targetRevision=value?revision+(installed?1:0):undefined;return value;
      });
      return staging;
    };
    const close=():Promise<void>=>closing??=(async()=>{
      source.ended=true;pumpAbort.abort();
      if(this.continuation?.to===source)this.cancelContinuation();
      const detached=source.epoch?.close();
      // Own any detach rejection immediately while an extractor is pending.
      const confirmed=detached?Promise.allSettled([detached]):undefined;
      await staging?.catch(()=>null);
      const results=await confirmed;
      if(results?.[0]?.status==='rejected')throw results[0].reason;
      if(source.transferFailure)throw source.transferFailure;
      // An AsyncFunction can still be waiting to consume this token on the
      // native main thread. Join promotion/retirement before token cleanup.
      if(source.token)player!.ncDropMuxedEpoch(source.token);
      source.releaseSlot();this.pending.delete(source.detach);this.sources.delete(key);
      signal.removeEventListener('abort',cancel);
    })();
    const cancel=()=>{void source.detach().catch(()=>undefined);};
    try{
      source.detach=this.delivery.bindNative(chunk,close);
    }catch(error){releaseSlot();throw error;}
    this.pending.add(source.detach);this.sources.set(key,source);
    signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
    source.ready=(async()=>{
      let stop!:()=>void;
      const cancelled=new Promise<never>((_,reject)=>{stop=()=>reject(Error('Muxed preparation cancelled.'));
        pumpAbort.signal.addEventListener('abort',stop,{once:true});if(pumpAbort.signal.aborted)stop();});
      try{await Promise.race([previous,cancelled]);}
      finally{pumpAbort.signal.removeEventListener('abort',stop);}
      await this.serial;
      if(source.ended||this.closed||!owns()||signal.aborted)throw Error('Muxed native admission cancelled.');
      player=this.ensurePlayer(settings);
      let revision=player.ncMuxedSourceRevision();
      if(!Number.isSafeInteger(revision)||revision<0)throw Error('Muxed native owner retired.');
      if(totals&&(!muxedChunkStreamAvailable()||typeof player.ncStageMuxedStream!=='function'
        ||typeof player.ncAppendMuxedStream!=='function'))throw Error('Update NC Remote for guarded chunk playback.');
      while(true){
        await stage(revision);
        const next=player.ncMuxedSourceRevision();
        // Retirement can fence an off-main validator while current output is
        // ending. Retry only that confirmed revision change under this same
        // slot and reader pin; rejection at an unchanged revision stays fatal.
        if(source.token||source.ended||this.closed||signal.aborted||!owns()||next===revision||next<0)break;
        revision=next;
      }
      if(!source.token||source.ended||this.closed||signal.aborted||!owns())throw Error('Muxed staged admission ended.');
    })().catch(async error=>{await source.detach();throw error;});
    return source;
  }

  async prepareSource(chunk:AudioChunk,settings:PlayerSettings,ticket:string|null,signal:AbortSignal):Promise<void>{
    await this.source(chunk,settings,ticket,signal).ready;
  }

  readonly createPlayer=async(chunk:AudioChunk,settings:PlayerSettings,ticket:string|null,signal:AbortSignal):
      Promise<{player:AudioPlayer;detach:()=>Promise<void>;dispose:()=>void}>=>{
    const source=this.source(chunk,settings,ticket,signal);
    if(source.activation)return source.activation;
    const {files,owns,totals,pumpAbort,detach}=source;
    const cancel=()=>{void detach().catch(()=>undefined);};signal.addEventListener('abort',cancel,{once:true});
    source.activation=(async()=>{try{
      await source.ready;
      if(source.ended||this.closed||signal.aborted||!owns())throw Error('Muxed staged admission ended.');
      const player=this.player!;
      await this.beforeSpeech?.(chunk,signal);
      if(source.ended||this.closed||signal.aborted||!owns())throw Error('Muxed planned entry ended.');
      const admitted=source.epoch=await this.begin(settings,ticket,signal,source);
      if(source.ended){await admitted.close();throw Error('Muxed native admission cancelled.');}
      if(source.targetRevision!==admitted.revision){
        let revision=source.targetRevision;
        if(revision===undefined||revision>admitted.revision
          ||admitted.revision-revision>this.ownedRetirements.size)throw Error('Muxed staged admission ended.');
        while(revision<admitted.revision)
          if(!this.ownedRetirements.has(revision++))throw Error('Muxed staged admission ended.');
        // A return idle may consume the token's original continuation epoch.
        // Rebase once only across confirmed retirements owned by this session.
        await source.restage(admitted);
      }
      const ready=admitted.installed||await this.read(admitted,()=>this.nativeAdmission(async()=>{
        if(source.ended||!this.admits(admitted,signal,owns))return false;
        this.observe('native_install_start',chunk);
        const value=await player.ncInstallMuxedEpoch(source.token!,admitted.revision);
        if(value===true){admitted.installed=true;this.observe('native_install_complete',chunk);}return value;
      }));
      if(ready!==true||!this.admits(admitted,signal,owns))throw Error('Muxed native admission ended.');
      source.releaseSlot();
      if(totals){
        const stopPump=()=>pumpAbort.abort();signal.addEventListener('abort',stopPump,{once:true});
        if(signal.aborted)stopPump();
        const pump=this.read(admitted,async()=>{
          let first=files.length;
          while(first<totals.rangeCount){
            const rows=await this.progressive!.waitForFiles(chunk,first,pumpAbort.signal);
            if(!this.admits(admitted,signal,owns)||pumpAbort.signal.aborted)throw Error('Muxed stream owner ended.');
            const next=rows.slice(0,6),ownsNext=()=>owns()&&next.every(file=>this.delivery.owns(chunk,file.uri));
            if(!next.length||next.some((file,index)=>file.index!==first+index)||first+next.length>totals.rangeCount
              ||!ownsNext())throw Error('Muxed stream retained range ended.');
            const appended=await this.read(admitted,()=>player.ncAppendMuxedStream(next,first,admitted.revision));
            if(appended!==true||!this.admits(admitted,signal,ownsNext)||pumpAbort.signal.aborted)
              throw Error('Muxed stream append ended.');
            first+=next.length;
          }
        });
        void pump.catch(error=>{
          if(!source.ended&&!this.closed&&!pumpAbort.signal.aborted){
            this.progressiveFailure=error;void detach().catch(()=>undefined);
          }
        }).finally(()=>signal.removeEventListener('abort',stopPump));
      }
      this.observe('source_activation_return',chunk);
      return {player,detach,dispose:()=>undefined};
    }catch(error){await detach();throw error;}
    finally{signal.removeEventListener('abort',cancel);}})();
    return source.activation;
  };

  async openIdle(files:MuxedTrialFile[],settings:PlayerSettings,ticket:string|null,signal:AbortSignal,owns:()=>boolean){
    const first=files[0];if(!first||!owns())throw Error('Muxed idle files unavailable.');
    reportMuxedReturn('idle_epoch_start');
    const epoch=await this.begin(settings,ticket,signal),player=this.player!;
    reportMuxedReturn('idle_epoch_done');
    const cancel=()=>{void epoch.close().catch(()=>undefined);};signal.addEventListener('abort',cancel,{once:true});
    try{
      if(!this.admits(epoch,signal,owns))throw Error('Muxed idle admission cancelled.');
      reportMuxedReturn('idle_native_prepare_start');
      const prepared=await this.read(epoch,()=>this.nativeAdmission(async()=>{
        if(!this.admits(epoch,signal,owns))return false;
        const value=await player.ncPrepareMuxedIdle(files,ticket!,first.index,epoch.revision);
        if(value===true)epoch.installed=true;return value;
      }));
      if(prepared!==true)throw Error('Muxed idle native admission rejected.');
      if(!this.admits(epoch,signal,owns))throw Error('Muxed idle admission ended.');
      reportMuxedReturn('idle_native_prepare_done');
      return {player,detach:epoch.close,
        play:()=>{if(!this.admits(epoch,signal,owns))throw Error('Muxed idle owner ended.');player.play();},
        append:async(rows:MuxedTrialFile[],first:number)=>{
          if(!this.admits(epoch,signal,owns))return false;
          return await this.read(epoch,()=>player.ncAppendMuxedIdle(rows,first,epoch.revision))===true&&this.admits(epoch,signal,owns);
        },
        position:()=>this.admits(epoch,signal,owns)?player.ncMuxedIdlePosition():null,
        seal:async(rows:MuxedTrialFile[],target:number,frames:number,ownsPlan:()=>boolean)=>{
          if(!this.admits(epoch,signal,owns)||!ownsPlan())return false;
          const sealed=await this.read(epoch,()=>player.ncSealMuxedIdle(rows,target,frames,epoch.revision))===true
            &&this.admits(epoch,signal,owns)&&ownsPlan();
          if(sealed)epoch.idleSealed=true;return sealed;
        },
        silentEnded:()=>this.admits(epoch,signal,owns)&&player.ncMuxedSilentEnded(epoch.revision)===true,
        prune:async(index:number)=>this.admits(epoch,signal,owns)
          &&await player.ncPruneMuxedIdle(index,epoch.revision)===true&&this.admits(epoch,signal,owns)};
    }catch(error){await epoch.close();throw error;}
    finally{signal.removeEventListener('abort',cancel);}
  }

  close():Promise<void>{
    return this.closing??=(async()=>{
      this.closed=true;
      this.cancelContinuation();
      if(this.continuousOpening)await this.continuousOpening.catch(()=>undefined);
      if(this.continuousOwner)await this.continuousOwner.close();
      // Progressive epochs can be waiting for files that have not arrived.
      // Cancel those waits before the epoch joins its readers; otherwise Stop
      // would depend on the remote producer publishing the missing tail.
      {
        const pending=[...this.pending].map(close=>close());
        // Own all detach rejections immediately, including when retirement
        // itself fails. Unconfirmed detach must still keep its files pinned.
        const results=await Promise.allSettled([this.current?.close(),...pending]);
        const failed=results.find(result=>result.status==='rejected');
        if(failed?.status==='rejected')throw failed.reason;
      }
      await this.serial;
      const player=this.player;if(!player)return;
      if(await player.ncCloseMuxedTrial()!==true)throw Error('Muxed session detach unconfirmed.');
      try{player.remove();}finally{player.release();}
    })();
  }
}
