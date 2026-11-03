import type {PhoneReplyAuth} from '../api/types';
import {observeOrderedControlWait as observeWait} from '../diagnostics/orderedControlWait';
import type {PeerTransport} from '../relay/peer';
import {PeerTransportUnavailableError} from '../relay/peer';
import {BufferedMediaStore} from '../relay/bufferedMedia';
import type {BufferedMediaScope} from '../relay/bufferedMedia';
import {DesktopOrderedDelivery} from './desktopOrderedDelivery';
import {DesktopOrderedSession} from './desktopOrderedSession';
import type {OrderedSessionScope} from './desktopOrderedSession';
import {DesktopOrderedTransport} from './desktopOrderedTransport';
import {OrderedChunkTiming} from '../diagnostics/orderedChunkTiming';
import {OrderedChunkStore} from './orderedChunkStore';
import type {OrderedCachePolicy,OrderedCacheEvent} from './orderedChunkStore';
import type {OrderedIdleCacheIO} from '../native/orderedIdleCacheIO';
import {OrderedCachedIdle} from './orderedCachedIdle';
import {ContinuationRecovery} from '../utils/continuationRecovery';
import type {RecoveryObservation} from '../utils/continuationRecovery';
import {OrderedContinuationAdapter,orderedTransportInterrupted} from './orderedContinuation';
import type {OrderedContinuationCheckpoint} from './orderedContinuation';

type SessionDependencies=ConstructorParameters<typeof DesktopOrderedSession>[0];
type Retained=readonly Readonly<{generation:number;ordinal:number}>[];
type Dependencies={session:Omit<OrderedSessionScope,'generation'>;auth:PhoneReplyAuth;
  continuation?:Pick<ConstructorParameters<typeof OrderedContinuationAdapter>[0],'operationId'|'schedule'|'observe'>&{ownerKey:string};
  recovery?:ConstructorParameters<typeof DesktopOrderedTransport>[0]['recovery'];
  idleCache?:{io:OrderedIdleCacheIO|null;policy():OrderedCachePolicy;onEvent?(event:OrderedCacheEvent):void};
  fullIdle?:Pick<ConstructorParameters<typeof OrderedCachedIdle>[0],'inventory'|'policy'|'onRecovery'|'onDiagnostic'>;
  peer():PeerTransport|null;current():boolean;native():SessionDependencies['native'];
  authority:SessionDependencies['authority'];finalSequence:SessionDependencies['finalSequence'];
  beforeSpeech?:SessionDependencies['beforeSpeech'];
  onEvents:SessionDependencies['onEvents'];onReplyCompleted?:SessionDependencies['onReplyCompleted'];
  onReplyAdmitted?:SessionDependencies['onReplyAdmitted'];
  onInterruption?:SessionDependencies['onInterruption'];
  onOpened():void|Promise<void>;onOwnerClosed():Promise<void>;onFailure(error:unknown):void;onChange?():void};
type Epoch={generation:number;delivery:DesktopOrderedDelivery;session:DesktopOrderedSession;
  recovery?:ContinuationRecovery<OrderedContinuationCheckpoint>;
  cached?:OrderedCachedIdle;
  syncCache():Promise<void>;
  transport:DesktopOrderedTransport;replacing:boolean;released:Set<number>;
  confirmed?:Promise<void>;replacement?:{generation:number;retained:Retained};successorCleanup?:DesktopOrderedTransport;
  localClosing?:Promise<void>};

/** Connects the three independent workers. Only capacity and explicit lifecycle
 * events couple acquisition to native preparation/playback. Native journal
 * evidence, not downloads or status flags, drives the caller's receipt observer.
 * The caller owns the registered player and authenticated reply cancellation. */
export class DesktopOrderedStream {
  private epoch:Epoch;
  private opening?:Promise<void>;private interrupting?:Promise<void>;private closing?:Promise<void>;
  private closed=false;private failure:unknown=null;
  private connection?:RecoveryObservation;private connectionRevision=0;
  private connectionPeer?:PeerTransport|null;private externalRevision=0;
  private waiting?:{promise:Promise<void>;resolve():void;reject(error:unknown):void};
  constructor(private readonly deps:Dependencies){this.connectionPeer=deps.peer();this.epoch=this.create(0);}
  private changed(){try{this.deps.onChange?.();}catch{}}
  private check(){if(this.failure)throw this.failure;if(this.closed||!this.deps.current())throw Error('ordered.stream_owner');}
  private fail(error:unknown,terminal=false){
    if(this.closed||this.failure)return;
    if(!terminal&&this.recoverTransport(error))return;
    this.failure=error;this.epoch.transport.stop();void this.epoch.session.stop('failure').catch(()=>undefined);
    this.changed();try{this.deps.onFailure(error);}catch{}
    void this.close().catch(()=>undefined); // Never replaces the original cause.
  }
  private create(generation:number):Epoch{
    const session=Object.freeze({...this.deps.session,generation});
    const timing=new OrderedChunkTiming(session.streamId,generation);
    const scope=Object.freeze({owner:session.owner,replyId:`ordered-${session.streamId}-${generation}`,expiresAt:session.expiresAtMs});
    let epoch:Epoch;
    const current=()=>!this.closed&&this.deps.current()&&this.epoch===epoch&&!epoch.replacing;
    const ownsScope=(value:BufferedMediaScope)=>current()&&value.owner===scope.owner
      &&value.replyId===scope.replyId&&value.expiresAt===scope.expiresAt;
    const download=new BufferedMediaStore(this.deps.peer,ownsScope,{maxFiles:64,maxBytes:128*1024*1024});
    const store=new OrderedChunkStore({download,cache:this.deps.idleCache?.io??null,current:ownsScope,
      policy:()=>this.deps.fullIdle?{mode:'off',epoch:this.deps.fullIdle.policy().epoch}:this.deps.idleCache?.policy()??{mode:'off',epoch:0},
      onEvent:this.deps.fullIdle?undefined:this.deps.idleCache?.onEvent,
      onFailure:error=>this.fail(error)});
    const released=new Set<number>();
    const transport=new DesktopOrderedTransport({peer:this.deps.peer,owner:session.owner,auth:this.deps.auth,
      recovery:generation===0?this.deps.recovery:undefined,
      openCapability:this.deps.recovery?.intent.kind==='open'?this.deps.recovery.intent.capability
        :this.deps.recovery?.intent.recovery.capability,
      streamId:session.streamId,generation,current,onAvailable:rows=>epoch.delivery.announce(rows),onFailure:error=>this.fail(error),
      onInterruption:error=>this.recoverTransport(error)});
    const delivery=new DesktopOrderedDelivery({streamId:session.streamId,generation,store,
      retryable:error=>{
        if(this.recoverTransport(error))return true;
        const peer=this.deps.peer();
        return current()&&!!peer&&!peer.closed&&peer.cacheScope===session.owner
          &&(error instanceof PeerTransportUnavailableError||(error as Error)?.message==='NC peer request timed out.');
      },
      onEvent:event=>timing.record(event.phase,event.ordinal),
      scope:()=>current()?scope:null,onReleased:async ordinal=>{
        try{await transport.release(ordinal);}catch(error){this.recoverTransport(error);throw error;}
        released.add(ordinal);
        // Recent exact ACKs only; a run has at most 60 retained Desktop files.
        if(released.size>64)released.delete(released.values().next().value!);
      },onChange:()=>{
        this.changed();if(!current())return;
        const failure=delivery.snapshot().failure;if(failure){this.fail(failure);return;}
        transport.wake();void epoch.session.pump().catch(error=>{if(current())this.fail(error);});
      }});
    const native=new DesktopOrderedSession({session,native:this.deps.native(),delivery,
      authority:this.deps.authority,finalSequence:this.deps.finalSequence,
      beforeSpeech:this.deps.beforeSpeech,
      onInterruption:receipt=>{if(current())this.deps.onInterruption?.(receipt);},
      onOpened:async()=>{if(!current())throw Error('ordered.stream_open_cancelled');await this.deps.onOpened();
        if(this.connection)this.observeConnection(this.connection);this.changed();},
      onEvents:async events=>{
        await this.deps.onEvents(events);
        if(current())for(const event of events)if(event.kind==='visual_started'&&event.source.kind==='idle')
          transport.idleStarted(event.source.firstOrdinal);
      },onReplyCompleted:this.deps.onReplyCompleted,
      onReplyAdmitted:this.deps.onReplyAdmitted,
      onStoppedOutput:async stopped=>{
        if(!epoch.replacing||this.closed)return;
        await epoch.confirmed; // Immediate native Stop already happened.
        if(!this.closed){
          epoch.replacement=await transport.restart(stopped);
          // A disconnect may win while the restart ACK is in flight. No new
          // native queue exists yet, but the server already owns a producer.
          if(this.closed)await this.unopenedSuccessor(epoch)?.halt();
        }
      }});
    epoch={generation,delivery,session:native,transport,replacing:false,released,
      syncCache:()=>store.syncPolicy(scope)};
    const continuation=this.deps.continuation;
    const capability=this.deps.recovery?.intent.kind==='open'?this.deps.recovery.intent.capability
      :this.deps.recovery?.intent.recovery.capability;
    if(continuation&&capability){
      const adapter=new OrderedContinuationAdapter({...continuation,auth:this.deps.auth,capability,current,
        scope:()=>native.continuationScope(),afterOrdinal:()=>transport.snapshot().afterOrdinal,
        pauseDelivery:()=>{native.pauseTransport(true);return transport.suspend();},
        resumeDelivery:async()=>{native.pauseTransport(false);transport.resume();delivery.resumeAcquisition();
          void native.pump().catch(error=>this.fail(error));},
        native:(method,request)=>native.continuationNative(method,request),
        capabilities:signal=>transport.continuationCapabilities(signal),reattach:(request,signal)=>transport.reattach(request,signal),
        cancel:async(reason,error)=>{
          if(reason.endsWith('_failed'))this.fail(error??Error('ordered.continuation_'+reason),true);
        },
        observe:(stage,recoveryEpoch,outcome,details)=>{
          continuation.observe(stage,recoveryEpoch,outcome,details);
          if(stage==='suspend'&&outcome==='requested'&&!this.waiting){
            let resolve!:()=>void,reject!:(error:unknown)=>void;
            const promise=new Promise<void>((a,b)=>{resolve=a;reject=b;});void promise.catch(()=>undefined);
            this.waiting={promise,resolve,reject};
          }
          if(stage==='resume'&&outcome==='completed'){this.waiting?.resolve();this.waiting=undefined;}
          this.changed();
        }});
      epoch.recovery=new ContinuationRecovery(adapter);
      // A replacement generation opens on the already-current transport.
      // Its predecessor's accumulated revision is not a new outage.
      epoch.recovery.observe({ownerKey:continuation.ownerKey,transportRevision:this.connectionRevision,
        connected:true,freshState:true,locked:false,enabled:true});
    }
    if(this.deps.fullIdle)epoch.cached=new OrderedCachedIdle({...this.deps.fullIdle,native:this.deps.native(),current,
      session:()=>{const run=native.snapshot().run;return run?{run,streamId:session.streamId,generation}:null;},
      call:request=>transport.cached(request),onFailure:error=>{if(current())this.fail(error);}});
    return epoch;
  }
  private recoverTransport(error:unknown):boolean{
    const epoch=this.epoch,recovery=epoch?.recovery;
    if(!recovery||this.closed||epoch.replacing||!this.deps.current()||!orderedTransportInterrupted(error)
      ||!epoch.session.continuationScope()||recovery.snapshot().phase==='terminal')return false;
    if(recovery.snapshot().phase==='waiting')return true;
    const peer=this.deps.peer(),state=this.connection;
    recovery.observe({ownerKey:state?.ownerKey??this.deps.continuation!.ownerKey,
      transportRevision:++this.connectionRevision,connected:!!peer&&!peer.closed&&state?.connected!==false,
      freshState:state?.freshState!==false,locked:state?.locked===true,enabled:true});
    this.changed();return true;
  }
  observeConnection(state:RecoveryObservation):void{
    const peer=this.deps.peer();
    if(!this.epoch.session.continuationScope()){
      this.connectionPeer=peer;this.externalRevision=state.transportRevision;this.connection=state;return;
    }
    if(peer!==this.connectionPeer||state.transportRevision!==this.externalRevision){
      this.connectionPeer=peer;this.externalRevision=state.transportRevision;this.connectionRevision++;
    }
    this.connection=state;
    this.epoch.recovery?.observe({...state,transportRevision:this.connectionRevision});
  }
  whenTransportReady():Promise<void>{return this.waiting?.promise??Promise.resolve();}
  get recovering(){const phase=this.epoch.recovery?.snapshot().phase;return !!phase&&phase!=='active'&&phase!=='terminal';}
  start():Promise<void>{return this.opening??=(async()=>{
    this.check();await this.epoch.transport.start();this.check();
  })().catch(error=>{this.fail(error);throw error;});}
  async tick(){
    this.check();if(this.epoch.replacing)return;
    const epoch=this.epoch;
    try{if(!this.recovering){await epoch.syncCache();epoch.delivery.resumeAcquisition();}
      await epoch.session.pump();
      const progress=epoch.delivery.progressSnapshot();
      if(progress){const final=this.deps.finalSequence(progress.replyId);
        epoch.transport.reportProgress({...progress,finalSegments:final===null?null:final+1});}
      if(!this.recovering)void epoch.cached?.tick();this.changed();}
    catch(error){if(!epoch.replacing&&!this.closed)this.fail(error);throw error;}
  }
  private async releaseRemainder(epoch:Epoch,retained:Retained){
    // Caller reached here only after whole native closure and acquisition joins.
    // Also covers committed files whose announcement never reached the phone.
    for(const row of retained){
      if(row.generation!==epoch.generation)throw Error('ordered.stream_cleanup_generation');
      if(!epoch.released.has(row.ordinal)){await epoch.transport.release(row.ordinal);epoch.released.add(row.ordinal);}
    }
  }
  private unopenedSuccessor(epoch:Epoch):DesktopOrderedTransport|undefined{
    if(!epoch.replacement)return;
    return epoch.successorCleanup??=new DesktopOrderedTransport({peer:this.deps.peer,owner:this.deps.session.owner,
      auth:this.deps.auth,streamId:this.deps.session.streamId,generation:epoch.replacement.generation,
      current:()=>false,onAvailable:()=>false,onFailure:()=>{}});
  }
  interrupt(confirmDesktopStop:()=>Promise<void>):Promise<void>{
    if(this.interrupting)return this.interrupting;
    try{this.check();}catch(error){return Promise.reject(error);}
    const epoch=this.epoch;epoch.replacing=true;
    // Fence invokes native synchronously, not behind a HTTP read, download,
    // preparation operation, or the server cancellation acknowledgement.
    const stopped=epoch.session.stop('replacement');
    void epoch.recovery?.cancel('replacement').catch(()=>undefined);
    this.waiting?.reject(Error('ordered.continuation_replaced'));this.waiting=undefined;
    const halted=observeWait('replacement.halt',epoch.transport.halt());
    epoch.confirmed=observeWait('replacement.admission',epoch.session.reconcileStoppedAdmission()).then(confirmDesktopStop);void epoch.confirmed.catch(()=>undefined);
    const work=(async()=>{
      await Promise.all([stopped,halted,epoch.confirmed,epoch.cached?.close()]);
      await observeWait('replacement.close',epoch.session.close());
      const retained=epoch.replacement?.retained??await epoch.transport.close();
      await this.releaseRemainder(epoch,retained);
      if(!epoch.session.snapshot().native)await this.deps.onOwnerClosed();
      if(this.closed)return;
      if(!epoch.replacement)throw Error('ordered.stream_replacement_unconfirmed');
      this.check();this.epoch=this.create(epoch.replacement.generation);
      await observeWait('replacement.start',this.epoch.transport.start());this.check();this.changed();
    })().catch(error=>{this.fail(error);throw error;}).finally(()=>{this.interrupting=undefined;});
    this.interrupting=work;return work;
  }
  private settleEpochLocal(epoch:Epoch):Promise<void>{
    return epoch.localClosing??=(async()=>{
      // The cached worker may still be awaiting an in-flight prepare/state RPC.
      // Join its JS work AND native readers before session settlement can allow
      // the runtime to release the shared player. Keep this independent of ACKs.
      await epoch.cached?.close();
      await epoch.session.settleLocalForRecovery();
    })();
  }
  close():Promise<void>{
    if(this.closing)return this.closing;
    this.closed=true;const epoch=this.epoch;
    epoch.transport.stop();const stopped=epoch.session.stop('stop');
    void epoch.recovery?.cancel('close').catch(()=>undefined);
    this.waiting?.reject(Error('ordered.continuation_closed'));this.waiting=undefined;
    const halted=this.unopenedSuccessor(epoch)?.halt();void halted?.catch(()=>undefined);
    // Begin local settlement now, independent of replacement remote feedback.
    // Its cached-worker join must precede native owner settlement/release.
    const local=this.settleEpochLocal(epoch);void local.catch(()=>undefined);
    return this.closing=(async()=>{
      await local;
      if(this.interrupting)await observeWait('stream.interruption',this.interrupting.catch(()=>undefined));
      await observeWait('stream.native_stop',stopped);
      const successor=this.unopenedSuccessor(epoch);await(halted??successor?.halt());
      const closing=epoch.transport.close();void closing.catch(()=>undefined);
      await observeWait('stream.native_close',epoch.session.close());const retained=await closing;
      await this.releaseRemainder(epoch,retained);
      if(successor){
        // This generation never acquired a native reader. Prior readers are
        // joined above; exact server-retained output can now be acknowledged.
        for(const row of await successor.close())await successor.release(row.ordinal);
      }
      if(!epoch.session.snapshot().native)await this.deps.onOwnerClosed();
      this.changed();
    })().catch(error=>{this.closing=undefined;throw error;});
  }
  settleLocalForRecovery():Promise<void>{
    const epoch=this.epoch;
    void this.close().catch(()=>undefined);
    return this.settleEpochLocal(epoch);
  }
  pauseCachedIdle():Promise<void>{return this.epoch.cached?.pause()??Promise.resolve();}
  snapshot(){return Object.freeze({generation:this.epoch.generation,closed:this.closed,replacing:this.epoch.replacing,
    failure:this.failure,delivery:this.epoch.delivery.snapshot(),native:this.epoch.session.snapshot().native});}
}
