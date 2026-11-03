import type {AudioPlayer} from 'expo-audio';
import type {PlaybackClock} from '../hooks/useAudioQueue';
import type {OrderedClockScope,OrderedClockObservation} from '../native/orderedPlaybackClock';
import type {AudioChunk,PhoneReplyAuth,PhoneReplyReceipt,PhoneReplyStatus} from '../api/types';
import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import type {PeerTransport} from '../relay/peer';
import {DesktopOrderedStream} from './desktopOrderedStream';
import {DesktopOrderedReplies} from './desktopOrderedReplies';
import type {OrderedSessionScope} from './desktopOrderedSession';
import {observeOrderedControlWait as observeWait} from '../diagnostics/orderedControlWait';
import type {RecoveryObservation} from '../utils/continuationRecovery';

type Native=ReturnType<ConstructorParameters<typeof DesktopOrderedStream>[0]['native']>;
export type OrderedPlayer=AudioPlayer&Native&{ncEnableMuxedTrialSession():boolean;ncCloseMuxedTrial():Promise<unknown>};
type Dependencies={session:Omit<OrderedSessionScope,'generation'>;auth:PhoneReplyAuth;
  continuation?:ConstructorParameters<typeof DesktopOrderedStream>[0]['continuation'];
  recovery?:ConstructorParameters<typeof DesktopOrderedStream>[0]['recovery'];
  idleCache?:ConstructorParameters<typeof DesktopOrderedStream>[0]['idleCache'];
  fullIdle?:ConstructorParameters<typeof DesktopOrderedStream>[0]['fullIdle'];
  peer():PeerTransport|null;current():boolean;createPlayer():OrderedPlayer;
  setUserPaused?(player:AudioPlayer,ticket:string,paused:boolean):Promise<void>;
  readPlaybackClock?(player:AudioPlayer,scope:OrderedClockScope):Promise<OrderedClockObservation|null>;
  authority(chunk:AudioChunk):BufferedReplyAuthority|null;finish(replyId:string,nativeAdmitted:boolean):boolean;
  freeze(replyId:string,interruptionId:string):PhoneReplyReceipt|null;skip(replyId:string,nativeAdmitted:boolean):boolean;
  onInterruption?(receipt:PhoneReplyReceipt):void;onSpeechStarted?(replyId:string):void;
  onFailure(error:unknown):void;ready?():Promise<void>;volume?():number;beforeSpeech?():Promise<void>};
type Gate={promise:Promise<void>;resolve():void;reject(error:unknown):void};
function gate():Gate{
  let resolve!:()=>void,reject!:(error:unknown)=>void;
  const promise=new Promise<void>((a,b)=>{resolve=a;reject=b;});void promise.catch(()=>undefined);
  return {promise,resolve,reject};
}

/** Normal ordered-mode coordinator. Playback status is UI observation only:
 * every heard source/finality decision comes from the native ordered journal.
 * One registered player survives replies; no per-reply acquire/player factory
 * is exposed to the ordinary audio queue. No handoff/position APIs exist here. */
export class DesktopOrderedRuntime {
  private readonly replies:DesktopOrderedReplies;
  private readonly listeners=new Set<()=>void>();
  private readonly cancellations=new Map<string,Gate>();
  private readonly startedReplies=new Set<string>();
  private readonly speechPreparations=new Map<string,Promise<void>>();
  private readonly nativeReplies=new Set<string>();
  private stream?:DesktopOrderedStream;
  private registered?:OrderedPlayer;
  private opened=gate();
  private opening?:Promise<void>;private closing?:Promise<void>;private replacing?:Promise<void>;
  private localClosing?:Promise<void>;
  private closed=false;private failure:unknown=null;private visual=false;private speechSeen=false;
  private sourceClock:({chunkId:string}&PlaybackClock)|null=null;
  private lastCompleted:{id:string;revision:number}|null=null;
  private pauseRevision=0;
  private paused=false;private pauseWork:Promise<void>=Promise.resolve();
  private readyNative=false;private settled=false;
  constructor(private readonly deps:Dependencies){
    this.replies=new DesktopOrderedReplies({onCompleted:chunk=>{this.lastCompleted={id:chunk.id,revision:(this.lastCompleted?.revision??0)+1};},authority:c=>this.current()?deps.authority(c):null,
      finish:id=>(!this.closed||this.settled)&&!this.cancellations.has(id)&&deps.finish(id,this.nativeReplies.has(id))});
  }
  private current(){return !this.closed&&!this.failure&&this.deps.current();}
  private check(){if(this.failure)throw this.failure;if(!this.current())throw Error('ordered.runtime_owner');}
  private changed(){for(const listener of this.listeners){try{listener();}catch{}}}
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
  private failed(error:unknown){
    if(this.closed||this.failure)return;
    this.failure=error;this.opened.reject(error);this.changed();
    try{this.deps.onFailure(error);}catch{}
    void this.close().catch(()=>undefined);
  }
  private playerForStream():OrderedPlayer{
    this.check();
    if(!this.registered){
      const player=this.deps.createPlayer();
      try{
        if(typeof player.ncEnableMuxedTrialSession!=='function'||player.ncEnableMuxedTrialSession()!==true)
          throw Error('ordered.runtime_native_session');
      }catch(error){try{player.remove();}finally{player.release();}throw error;}
      this.registered=player;
    }
    return this.registered;
  }
  private disposeJoinedPlayer(){
    // This is called only after ordered and whole-owner native settlement.
    const player=this.registered;this.registered=undefined;
    if(player){try{player.remove();}finally{player.release();}}
  }
  start():Promise<void>{
    return this.opening??=(async()=>{
      await this.deps.ready?.();this.check();
      this.stream=new DesktopOrderedStream({session:this.deps.session,auth:this.deps.auth,
        continuation:this.deps.continuation,
        recovery:this.deps.recovery,
        idleCache:this.deps.idleCache,
        fullIdle:this.deps.fullIdle,
        peer:this.deps.peer,current:()=>this.current(),native:()=>this.playerForStream(),
        authority:source=>this.replies.authority(source),finalSequence:id=>this.replies.finalSequence(id),
        beforeSpeech:source=>{
          const id=source.replyId;if(!id)throw Error('ordered.runtime_speech_reply');
          let work=this.speechPreparations.get(id);
          if(!work){work=Promise.resolve().then(()=>this.deps.beforeSpeech?.());this.speechPreparations.set(id,work);}
          return work;
        },
        onEvents:async events=>{
          this.replies.events(events);
          for(const event of events){
            if(event.kind==='visual_started')this.visual=true;
            if(event.kind==='source_started'){
              this.visual=false;this.speechSeen=true;
              const id=event.source.replyId;
              if(id&&!this.startedReplies.has(id)){
                this.startedReplies.add(id);
                if(this.startedReplies.size>64)this.startedReplies.delete(this.startedReplies.values().next().value!);
                try{this.deps.onSpeechStarted?.(id);}catch{ /* Optional onset work cannot fail speech. */ }
              }
            }
          }
          this.changed();
        },
        onReplyCompleted:id=>{this.replies.nativeCompleted(id);this.changed();},
        onReplyAdmitted:id=>{this.nativeReplies.add(id);},
        onInterruption:receipt=>{
          this.check();
          if(!this.nativeReplies.has(receipt.phone_request_id)||!this.deps.onInterruption)
            throw Error('ordered.runtime_interruption_owner');
          this.skipReply(receipt.phone_request_id);
          this.deps.onInterruption(receipt);
        },
        onOpened:()=>{
          this.check();const player=this.registered;if(!player)throw Error('ordered.runtime_player_missing');
          this.updateVolume();player.play();this.readyNative=true;this.opened.resolve();this.changed();
        },
        onOwnerClosed:async()=>{
          // Final runtime shutdown owns disposal until its whole-owner close
          // settles. Stream cleanup must not release that pending RPC's player.
          if(this.closed)return;
          this.disposeJoinedPlayer();this.changed();
        },
        onFailure:error=>this.failed(error),onChange:()=>this.changed()});
      await this.stream.start();this.check();this.changed();
    })().catch(error=>{this.failed(error);throw error;});
  }
  async beforeReply(){
    await observeWait('reply.start',this.start());
    if(this.replacing)await observeWait('reply.replacement',this.replacing);
    this.check();await observeWait('reply.opened',this.opened.promise);this.check();
    await this.stream?.whenTransportReady();this.check();
  }
  get userPaused(){return this.paused;}
  setUserPaused(paused:boolean):Promise<void>{
    this.pauseRevision++;
    const player=this.registered,generation=this.stream?.snapshot().generation;
    const work=this.pauseWork.catch(()=>undefined).then(async()=>{
      this.check();
      if(!player||this.registered!==player||this.stream?.snapshot().generation!==generation||!this.readyNative||!this.deps.setUserPaused)
        throw Error('Ordered playback pause is unavailable.');
      await this.deps.setUserPaused(player,this.deps.session.ticket,paused);
      this.check();
      if(this.registered!==player||this.stream?.snapshot().generation!==generation)throw Error('Ordered playback ownership changed.');
      this.paused=paused;this.changed();
    });
    this.pauseWork=work;return work;
  }
  getPlaybackClock(player:AudioPlayer,chunkId:string):PlaybackClock|null{
    return this.current()&&this.registered===player&&this.currentChunk?.id===chunkId&&this.sourceClock?.chunkId===chunkId
      ?this.sourceClock:null;
  }
  get sourcePositionSeconds(){return this.sourceClock?.chunkId===this.currentChunk?.id?this.sourceClock?.seconds??0:0;}
  private async samplePlaybackClock(){
    const player=this.registered,snapshot=this.stream?.snapshot().native,pauseRevision=this.pauseRevision;
    if(!player||!snapshot||!this.deps.readPlaybackClock||!this.current()){this.sourceClock=null;return;}
    const scope:OrderedClockScope={version:1,ticket:this.deps.session.ticket,run:snapshot.run,
      streamId:snapshot.streamId,generation:snapshot.generation};
    let observed:OrderedClockObservation|null;
    try{observed=await this.deps.readPlaybackClock(player,scope);}catch{observed=null;}
    const latest=this.stream?.snapshot().native;
    if(!this.current()||this.pauseRevision!==pauseRevision||this.registered!==player||latest?.run.id!==scope.run.id||latest.run.revision!==scope.run.revision
      ||latest.streamId!==scope.streamId||latest.generation!==scope.generation)return;
    const chunk=this.currentChunk;
    const clock=observed?.known&&chunk?.id===observed.sourceId&&chunk.phone_request_id===observed.replyId
      &&chunk.sequence_index===observed.sequenceIndex&&observed.seconds!==null
      ?{chunkId:chunk.id,seconds:observed.seconds,sampledAtMs:observed.sampledAtMs,
        playing:observed.playing&&!observed.userPaused,buffering:observed.buffering}:null;
    const changed=this.sourceClock?.chunkId!==clock?.chunkId||this.sourceClock?.seconds!==clock?.seconds
      ||this.sourceClock?.playing!==clock?.playing||this.sourceClock?.buffering!==clock?.buffering
      ||observed!==null&&this.paused!==observed.userPaused;
    this.sourceClock=clock;if(observed)this.paused=observed.userPaused;
    if(changed)this.changed();
  }
  observeConnection(state:RecoveryObservation){this.stream?.observeConnection(state);}
  get recovering(){return this.stream?.recovering===true;}
  async tick(){
    this.check();await this.start();
    try{await this.stream!.tick();if(this.current()){this.updateVolume();await this.samplePlaybackClock();}}catch(error){
      if(!this.closed&&!this.replacing){this.failed(error);throw error;}
    }
  }
  private updateVolume(){
    const volume=this.deps.volume?.()??1;
    if(!Number.isFinite(volume)||volume<0||volume>1)throw Error('ordered.runtime_volume');
    if(this.registered&&this.registered.volume!==volume)this.registered.volume=volume;
  }
  appendReplyMedia(id:string,chunks:readonly AudioChunk[]){
    this.check();this.replies.append(id,chunks);
    // Authority metadata wakes preparation, never gates the downloader.
    if(this.stream)void this.tick().catch(()=>undefined);
  }
  observeReplyStatus(id:string,status:PhoneReplyStatus,reconciled:boolean){
    if(!this.current())return;
    const stopped=status.playback_stop_requested||status.phase==='cancelled'||status.phase==='superseded';
    const replace=stopped&&!this.replies.suppressed(id)&&!this.replies.finished(id);
    // Validate scope/finality first. An invalid status must never stop another
    // reply; a valid cancellation must fence already-staged native media too.
    this.replies.observe(id,status,reconciled);
    if(replace)this.interruptReply(id);
    if(stopped)this.cancellations.get(id)?.resolve();
  }
  skipReply(id:string){
    this.check();if(this.cancellations.has(id)||this.replies.suppressed(id)||this.replies.finished(id))return;
    this.interruptReply(id);
  }
  private interruptReply(id:string){
    this.paused=false;this.sourceClock=null;
    const confirmation=gate();this.cancellations.set(id,confirmation);this.replies.suppress(id);
    this.readyNative=false;this.opened=gate();this.visual=false;
    if(!this.stream){const error=Error('ordered.runtime_not_started');confirmation.reject(error);this.failed(error);return;}
    // Native invalidation inside interrupt is synchronous, before either the
    // control receipt or the authenticated Desktop cancellation observation.
    const work=this.stream.interrupt(()=>{
      if(!this.deps.skip(id,this.nativeReplies.has(id)))confirmation.reject(Error('ordered.runtime_skip_rejected'));
      return observeWait('replacement.confirmation',confirmation.promise);
    });
    this.replacing=work.catch(error=>{this.failed(error);throw error;}).finally(()=>{
      this.cancellations.delete(id);this.speechPreparations.delete(id);this.replacing=undefined;this.changed();
    });void this.replacing.catch(()=>undefined);this.changed();
  }
  freezeReply(interruptionId:string):PhoneReplyReceipt|null{
    const id=this.replies.startedReplyId;if(!this.current()||!id)return null;
    const receipt=this.deps.freeze(id,interruptionId);
    if(receipt)this.skipReply(id);return receipt;
  }
  replyDrained=(id:string,final:number|null)=>(!this.closed||this.settled)&&!this.cancellations.has(id)&&this.replies.drained(id,final);
  finishReply=(id:string)=>{const result=this.replies.finish(id);
    if(result){this.speechPreparations.delete(id);this.nativeReplies.delete(id);this.changed();}return result;};
  replyFinished=(id:string)=>this.replies.finished(id);
  completedReplySequence=(id:string)=>this.replies.completedSequence(id);
  get currentChunk(){return this.replies.currentChunk;}
  get activeReplyId(){return this.replies.activeReplyId;}
  get lastCompletedChunk(){return this.lastCompleted;}
  get playedCount(){return this.replies.playedCount;}
  get player():AudioPlayer|null{return this.registered??null;}
  pauseCachedIdle():Promise<void>{return this.stream?.pauseCachedIdle()??Promise.resolve();}
  get startupStage(){return this.readyNative?'idle':this.stream?'opening':'availability';}
  get phase():'off'|'arming'|'idle'|'speech'|'waiting'|'failed'{
    if(this.failure)return 'failed';if(this.closed)return 'off';
    if(!this.readyNative)return this.replacing?'waiting':'arming';
    return this.currentChunk?'speech':this.visual||!this.speechSeen?'idle':'waiting';
  }
  close():Promise<void>{
    if(this.closing)return this.closing;
    const local=this.settleLocalForRecovery();
    return this.closing=(async()=>{
      await local;
      await this.stream?.close();
      await this.replacing?.catch(()=>undefined);
    })().catch(error=>{this.closing=undefined;throw error;});
  }
  settleLocalForRecovery():Promise<void>{
    if(this.localClosing)return this.localClosing;
    this.closed=true;const error=Error('ordered.runtime_closed');this.opened.reject(error);
    for(const cancellation of this.cancellations.values())cancellation.reject(error);
    this.changed();const streamClosing=this.stream?.close();void streamClosing?.catch(()=>undefined);
    return this.localClosing=(async()=>{
      await this.opening?.catch(()=>undefined);
      if(this.stream)await observeWait('runtime.local_close',this.stream.settleLocalForRecovery());
      // Ordered closure keeps a reusable player; final runtime disposal also
      // confirms the whole owner before releasing the registered player.
      if(this.registered&&await this.registered.ncCloseMuxedTrial()!==true)throw Error('ordered.runtime_owner_close');
      this.disposeJoinedPlayer();this.readyNative=false;this.settled=true;this.changed();
    })();
  }
  snapshot(){return Object.freeze({phase:this.phase,failure:this.failure,stream:this.stream?.snapshot(),replies:this.replies.snapshot()});}
}
