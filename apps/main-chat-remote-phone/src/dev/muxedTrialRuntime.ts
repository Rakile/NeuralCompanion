import type {AudioPlayer} from 'expo-audio';
import {PlanTransactionTrace} from '../diagnostics/planTransaction';
import {MediaScopeTrace} from '../diagnostics/mediaScope';
import type {AudioChunk,PhoneReplyStatus} from '../api/types';
import type {RemoteClient} from '../api/client';
import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import {BufferedMediaStore} from '../relay/bufferedMedia';
import type {BufferedMediaScope,BufferedMediaLease} from '../relay/bufferedMedia';
import {PeerTransportUnavailableError} from '../relay/peer';
import {PeerMediaCapacityError} from '../relay/media';
import {idleChunkRequestId} from '../native/idleChunkPlayback';
import {MuxedTrialDelivery} from './muxedTrialDelivery';
import type {MuxedTrialPlan,MuxedRangePreparation} from './muxedTrialDelivery';
import {MuxedTrialAudioSession,muxedTrialAvailable,muxedChunkStreamAvailable,muxedSourceFenceAvailable,muxedContinuousAvailable} from './muxedTrialAudio';
import type {MuxedSourceStage} from './muxedTrialAudio';
import {compatibleMuxedPlans,sameRun,sameSource,sameVisual} from './muxedContinuousProtocol';
import type {ContinuousBufferedAudio,ContinuousMetadata,SourceEvent,SourceGrant,RunSnapshot,TailCursor,VisualEpoch,ReturnDescriptor} from './muxedContinuousProtocol';
import {MuxedTrialIdle} from './muxedTrialIdle';
import type {QueuedIdleBinding} from './muxedTrialIdle';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import {reportMuxedReturn} from '../utils/muxedReturnDiagnostics';
import {MuxedReplyFinality} from './muxedReplyFinality';
import type {MuxedFinalityDecision} from './muxedReplyFinality';
import type {PhonePresentationPosition} from '../utils/phonePresentation';

type Dependencies={client():RemoteClient;current():boolean;ticket:string;reply(chunk:AudioChunk):BufferedReplyAuthority|null;
  chunks?():readonly AudioChunk[];holdLastFrame?:boolean;
  claimWaitingPlan?(plan:NonNullable<MuxedTrialPlan['anticipation']>):boolean};
type Lookahead={chunk:AudioChunk;abort:AbortController;work:Promise<void>;lease?:BufferedMediaLease;plan?:MuxedTrialPlan;error?:unknown};
type ManifestSource={chunk:AudioChunk;authority:string;prefix?:boolean;lease?:BufferedMediaLease;preparation?:Promise<void>;prepared?:boolean;error?:unknown};
type ContinuationSource=Pick<Lookahead,'chunk'|'lease'|'plan'|'error'>;
type Phase='off'|'arming'|'idle'|'speech'|'waiting'|'failed';
type QueuedReturn={tail:TailCursor;source:SourceGrant;idle:MuxedTrialIdle;binding:QueuedIdleBinding;
  epoch?:VisualEpoch;admitted:boolean};
type HoldStage=MuxedSourceStage|'queue_acquire_start'|'queue_retained'|'lookahead_start'|'lookahead_retained'|'acquisition_start'|'acquisition_prefix'|'acquisition_complete'|'preparation_start'|'preparation_complete'|'native_staged'|'native_installed'|'natural_waiting'
  |'drain_observed'|'direct_return_close_start'|'direct_return_close_complete';
type PrefetchReason='missing_successor'|'unavailable_authority'|'ticket_mismatch'|'owner_mismatch'|'reply_mismatch'|'expired_authority'|'start'|'held';
type PrefetchCounts={replyChunks:number;successorCount:number};
const PREFIX='/api/dev/musetalk-live/';
const retryable=(error:unknown)=>error instanceof PeerTransportUnavailableError||error instanceof PeerMediaCapacityError;

/** Explicit one-reply development trial. The ordinary runtime/cache/compositor
 * is not used. Existing authenticated controls, carrier and guarded queue still
 * own admission; this coordinator never emits a heard/completion receipt. */
export class MuxedTrialRuntime {
  private readonly mediaScopeTrace=new MediaScopeTrace();
  private planDiagnostics?:PlanTransactionTrace;
  private planDecision(site:string,condition:string,expected:string|number|boolean|null,actual:string|number|boolean|null){
    (this.planDiagnostics??=new PlanTransactionTrace(this.trialId||this.armRequestId)).decision(site,condition,expected,actual);
  }
  phase:Phase='off';
  readonly holdsLastFrame:boolean;
  readonly streamsChunks:boolean;
  readonly continuousRequired:boolean;
  private continuousReturns:Promise<void>=Promise.resolve();
  private continuousInitialIdle?:MuxedTrialIdle;
  private readonly continuousSources=new Map<string,{chunk:AudioChunk;plan:MuxedTrialPlan;source:SourceGrant}>();
  private readonly independent:boolean;
  private readonly manifest=new Map<number,ManifestSource>();
  private acquisition?:Promise<void>;
  private acquisitionNext=0;
  private acquisitionError?:unknown;
  // Diagnostic-only enum: never export raw transport errors or owner strings.
  startupStage:'availability'|'peer'|'negotiate'|'quality'|'arm'|'arm-ack'|'idle'='availability';
  private readonly abort=new AbortController();
  private readonly listeners=new Set<()=>void>();
  private readonly store:BufferedMediaStore;
  private readonly session:MuxedTrialAudioSession;
  private readonly chunks=new Map<string,AudioChunk>();
  private delivery?:MuxedTrialDelivery;
  private idle?:MuxedTrialIdle;
  private idleTick?:{idle:MuxedTrialIdle;work:Promise<void>};
  private nextIdle?:{chunkId:string;requestId:string;idle:MuxedTrialIdle;work?:Promise<void>;cancelled:boolean};
  private queuedReturn?:QueuedReturn;
  private active?:{chunk:AudioChunk;plan:MuxedTrialPlan;player:AudioPlayer;detach:()=>Promise<void>;drained:boolean;continuing?:boolean};
  private lookahead?:Lookahead;
  private prefetchGate?:{chunkId:string;reason:PrefetchReason};
  private continuation?:{identity:string;plan:string};
  private reservedContinuation?:AudioChunk;
  private readonly discarding=new Map<MuxedTrialIdle,Promise<void>>();
  private returning:Promise<void>=Promise.resolve();
  private opening?:Promise<void>;
  private closing?:Promise<void>;
  private closed=false;
  private owner='';
  private trialId='';
  private readonly armRequestId=`mux-${idleChunkRequestId()}`;
  private readonly idleScopes=new Map<MuxedTrialIdle,BufferedMediaScope>();
  private planning=false;
  private replyId='';
  private replyFinalityObservation?:MuxedReplyFinality;
  private registered:AudioPlayer|null=null;
  private readonly startedAt=Date.now();
  private producerExpiresAt=Infinity;
  private producerStartedAt?:number;
  private readonly scopeStartedAt=new WeakMap<BufferedMediaScope,number>();
  private authorityHandover:'not_attempted'|'attempted'|'accepted'|'blocked'='not_attempted';
  private admittedReplyExpiresAt?:number;
  private finalVisualStarted=false;
  private waitingPlanId?:string;
  private waitingWork?:Promise<void>;
  readonly audio:{acquire:(chunk:AudioChunk,signal:AbortSignal)=>Promise<BufferedMediaLease>;
    owns:(chunk:AudioChunk,uri:string)=>boolean;
    createPlayer:(...args:Parameters<MuxedTrialAudioSession['createPlayer']>)=>Promise<Awaited<ReturnType<MuxedTrialAudioSession['createPlayer']>>&{continuous?:ContinuousMetadata}>;
    deferNativePreparation:true;continuousRequired:boolean;continuous?:ContinuousBufferedAudio};
  constructor(private readonly deps:Dependencies){
    this.holdsLastFrame=__DEV__&&deps.holdLastFrame===true;
    this.continuousRequired=!this.holdsLastFrame;
    this.streamsChunks=muxedChunkStreamAvailable();
    this.independent=this.streamsChunks;
    this.store=new BufferedMediaStore(()=>deps.client().bufferedPeer,scope=>this.scopeCurrent(scope));
    this.session=new MuxedTrialAudioSession({files:c=>this.requiredDelivery().files(c),
      owns:(c,uri)=>this.requiredDelivery().owns(c,uri),bindNative:(c,detach)=>this.requiredDelivery().bindNative(c,detach),
      continuousDescriptor:(c,p,t)=>this.requiredDelivery().continuousDescriptor(c,p,t)},
      (chunk,signal)=>this.beforeSpeech(chunk,signal),this.streamsChunks?{
        sourceTotals:chunk=>this.requiredDelivery().sourceTotals(chunk),
        waitForFiles:(chunk,first,signal)=>this.requiredDelivery().waitForFiles(chunk,first,signal)}:undefined,
      (stage,chunk)=>this.reportHold(stage,chunk));
    const continuous:ContinuousBufferedAudio={
      candidate:(tail,next)=>this.continuousCandidate(tail,next),
      finalReturn:tail=>this.prepareFinalReturn(tail),
      appendSource:async(tail,chunk,ticket,signal)=>{
        if(this.continuousCandidate(tail,chunk)!=='compatible')throw Error('Continuous muxed candidate changed.');
        const plan=this.requiredDelivery().prepared(chunk),result=await this.session.appendContinuousSource(tail,chunk,plan,ticket,signal);
        if(result.kind==='admitted')this.continuousSources.set(result.source.id,{chunk:{...chunk},plan,source:result.source});
        return result;
      },
      subscribe:(run,wake)=>{
        const player=this.registered,owner={id:run.id,revision:run.revision};let subscribed=true;
        const reconcile=()=>{
          if(!subscribed||!this.live()||this.abort.signal.aborted||this.registered!==player||!this.active)return;
          if([...this.continuousSources.values()].some(row=>row.chunk.id===this.active!.chunk.id&&sameRun(row.source.run,owner)))wake();
        };
        // Status is only a prompt to read the authoritative native journal.
        // Keep the existing bounded asynchronous reconciliation poll as well.
        const subscription=player?.addListener('playbackStatusUpdate',reconcile);
        const timer=setInterval(reconcile,100);
        return()=>{subscribed=false;clearInterval(timer);
          try{subscription?.remove();}catch { /* Already detached; timer and callback are fenced. */ }};
      },
      read:this.session.readContinuous,acknowledge:this.session.acknowledgeContinuous,
      onApplied:event=>this.applyContinuous(event),onDrained:snapshot=>this.continuousDrained(snapshot),
      sealTail:this.session.sealContinuous,retireSource:this.session.retireContinuousSource,
      retireRun:this.session.retireContinuousRun,invalidate:this.session.invalidateContinuous};
    this.audio={deferNativePreparation:true,continuousRequired:this.continuousRequired,
      ...(this.continuousRequired?{continuous}:{}),
      acquire:async(chunk,signal)=>{
        await this.start();this.check(signal);
        this.reportHold('queue_acquire_start',chunk);
        if(this.independent){
          this.update([chunk]);
          const row=this.manifest.get(chunk.sequence_index!)!;
          while(!row.prefix){this.checkManifest(row);if(row.error)throw row.error;
            if(this.acquisitionError)throw this.acquisitionError;await this.wait(signal);}
          this.checkManifest(row);
          // The queue borrows first; its cancellation cannot cancel the
          // runtime-owned download or another future source's reader.
          const lease=await this.requiredDelivery().acquireProgressive(chunk,signal);
          try{this.check(signal);this.checkManifest(row);await row.lease?.release();row.lease=undefined;
            this.reportHold('queue_retained',chunk);return lease;
          }catch(error){await lease.release();throw error;}
        }
        const authority=this.deps.reply(chunk);
        if(!authority||authority.ticket!==deps.ticket||authority.scope.owner!==this.owner
          ||!chunk.phone_request_id||this.replyId&&this.replyId!==chunk.phone_request_id)
          throw Error('Muxed reply owner ended.');
        this.replyId=chunk.phone_request_id;this.chunks.set(chunk.id,{...chunk});
        const pending=this.lookahead?.chunk.id===chunk.id?this.lookahead:undefined;
        if(pending&&this.chunkIdentity(pending.chunk)!==this.chunkIdentity(chunk))throw Error('Muxed source changed.');
        // Acquire the queue's reader before dropping lookahead's reader. Zero
        // readership retires the delivery row and its immutable retained files.
        const delivery=this.requiredDelivery();
        const lease=await (this.streamsChunks?delivery.acquireProgressive(chunk,signal):delivery.acquire(chunk,signal));
        try{
          if(pending){await pending.work;this.check(signal);await pending.lease?.release();
            if(this.lookahead===pending)this.lookahead=undefined;}
          this.check(signal);this.reportHold('queue_retained',chunk);return lease;
        }catch(error){await lease.release();throw error;}
      },owns:(chunk,uri)=>this.live()&&this.delivery?.owns(chunk,uri)===true,
      createPlayer:async(chunk,settings,ticket,signal)=>{
        await this.returning;this.check(signal);
        if(ticket!==deps.ticket)throw Error('Muxed ticket changed.');
        try{
          if(this.independent){const row=this.manifest.get(chunk.sequence_index!);
            if(!row||this.chunkIdentity(row.chunk)!==this.chunkIdentity(chunk))throw Error('Muxed source changed.');
            this.checkManifest(row);await row.preparation;this.check(signal);this.checkManifest(row);}
          const plan=this.requiredDelivery().prepared(chunk);
          const replyExpiresAt=this.continuousRequired
            ?this.requiredDelivery().continuousDescriptor(chunk,plan,ticket!).expiresAtMs:undefined;
          if(this.continuousRequired)this.observeHandover('attempted');
          const prepared:Awaited<ReturnType<MuxedTrialAudioSession['createPlayer']>>&{continuous?:ContinuousMetadata}=this.continuousRequired
            ?await this.session.createContinuousPlayer(chunk,plan,settings,ticket!,signal)
            :await this.session.createPlayer(chunk,settings,ticket,signal);
          if(this.continuousRequired&&this.continuousInitialIdle){
            const old=this.continuousInitialIdle;
            // Native open has certified this exact old idle reader join. Its
            // epoch detach is now harmless to the newer continuous queue.
            await old.close();this.idleScopes.delete(old);this.continuousInitialIdle=undefined;
          }
          // Unused retain-only local cleanup is not speech authority. Native
          // admission and the ordinary queue still own validation and play.
          this.check(signal);
          if(replyExpiresAt!==undefined){
            // Successful native admission replaces startup authority with the
            // existing immutable reply grant. Never extend either grant or
            // promote it while open/old-reader retirement is still pending.
            this.admittedReplyExpiresAt=replyExpiresAt;
            this.observeHandover('accepted');
            this.planDecision('phone.runtime.epoch_authority','admitted_reply_deadline',this.producerExpiresAt,replyExpiresAt);
          }
          this.registered=prepared.player;
          if(prepared.continuous)this.continuousSources.set(prepared.continuous.source.id,
            {chunk:{...chunk},plan,source:prepared.continuous.source});
          this.reservedContinuation=undefined;
          this.active={chunk:{...chunk},plan:this.requiredDelivery().prepared(chunk),player:prepared.player,detach:prepared.detach,drained:false};
          this.phase='speech';this.changed();this.reportHold('native_installed',chunk);this.prefetch();return prepared;
        }catch(error){
          this.observeHandover('blocked');
          this.phase='failed';this.changed();void this.close().catch(()=>undefined);throw error;}
      }};
  }
  get player(){return this.closed?null:this.registered;}
  readIdlePosition():PhonePresentationPosition|null{
    if(!this.live()||(this.phase!=='idle'&&this.phase!=='waiting'))return null;
    return this.idle?.readIdlePosition()??null;
  }
  proposeIdleWaitingBoundary(){return this.readIdlePosition()?this.idle?.proposeWaitingBoundary()??null:null;}
  abandonIdleWaitingBoundary(){this.idle?.abandonWaitingBoundary();}
  private async beginWaiting(chunk:AudioChunk,plan:NonNullable<MuxedTrialPlan['anticipation']>,signal:AbortSignal){
    this.check(signal);
    const idle=this.idle,boundary=idle?.waitingBoundary();
    const rejection=chunk.sequence_index!==0?'sequence_not_initial':!idle?'idle_missing':!boundary?'boundary_missing'
      :!this.idleScopes.has(idle)?'idle_scope_missing':!this.deps.claimWaitingPlan?'claim_unavailable'
      :!this.deps.claimWaitingPlan(plan)?'claim_rejected':null;
    if(rejection){
      this.planDecision('phone.runtime.waiting_admission',rejection,true,false);
      idle?.abandonWaitingBoundary('admission_rejected');throw Error(`Muxed desktop waiting agreement unavailable: ${rejection}.`);
    }
    this.planDecision('phone.runtime.waiting_admission','prerequisites',true,true);
    // The independent downloader keeps acquiring speech while native consumes
    // the outgoing prefix. beforeSpeech joins this admission, not acquisition.
    this.waitingWork=(async()=>{
      if(!await idle!.beginWaitingPlan(plan,boundary!,[],signal))throw Error('Muxed desktop waiting boundary missed.');
      this.check(signal);if(this.idle!==idle)throw Error('Muxed idle owner ended.');
      this.waitingPlanId=plan.planId;
    })();
    void this.waitingWork.catch(error=>{this.acquisitionError??=error;});
  }
  get epochState(){
    return {expiresAt:Math.min(this.admittedReplyExpiresAt??this.producerExpiresAt,...[...this.idleScopes.values()].map(scope=>scope.expiresAt)),
      speechDeparted:this.active?.drained===true&&this.queuedReturn?.admitted===true,
      finalVisualStarted:this.finalVisualStarted};
  }
  private observeHandover(state:'attempted'|'accepted'|'blocked'):void{
    this.authorityHandover=state;
    try{this.planDecision('phone.runtime.lifetime','handover',null,state);}catch{}
  }
  observeEpochExpiry(now:number,deadline:number):void{
    // No new authority/clock reads. All deadlines are immutable values already
    // held by this runtime; null explicitly means the creation time is unknown.
    try{
      const finite=(value:number|undefined)=>typeof value==='number'&&Number.isFinite(value)?value:null;
      const emit=(name:string,expected:string|number|boolean|null,actual:string|number|boolean|null)=>
        this.planDecision('phone.runtime.lifetime',name,expected,actual);
      emit('effective_deadline',finite(deadline),finite(now));
      emit('phase',null,this.phase);emit('handover',null,this.authorityHandover);
      emit('startup_begin_ms',null,finite(this.producerStartedAt));
      emit('startup_deadline',finite(this.producerExpiresAt),finite(now));
      emit('reply_deadline',finite(this.admittedReplyExpiresAt),finite(now));
      emit('reply_begin_ms',null,null);
      emit('waiting_plan_admitted',true,Boolean(this.waitingPlanId));
      emit('native_speech_installed',true,Boolean(this.active));
      emit('manifest_sources',null,this.manifest.size);
      emit('retained_prefixes',null,[...this.manifest.values()].filter(row=>row.prefix).length);
      emit('prepared_sources',null,[...this.manifest.values()].filter(row=>row.prepared).length);
      emit('final_visual_started',true,this.finalVisualStarted);
      for(const [idle,scope] of this.idleScopes){
        const kind=scope.replyId===`muxed-idle:${this.trialId}`?'initial_idle':'return_idle';
        emit(kind+'_begin_ms',null,finite(this.scopeStartedAt.get(scope)));
        emit(kind+'_deadline',finite(scope.expiresAt),finite(now));
        emit(kind+'_selected',true,this.idle===idle);
      }
    }catch{} // Keep the original expiry and retirement behavior if logging fails.
  }
  private continuousCandidate(tail:TailCursor,next:AudioChunk):'pending'|'compatible'|'incompatible'{
    this.check();const prior=this.continuousSources.get(tail.source.id),row=this.manifest.get(next.sequence_index!);
    if(!prior||prior.source.chunkId!==tail.source.chunkId||prior.source.run.id!==tail.source.run.id
      ||prior.source.run.revision!==tail.source.run.revision||next.phone_request_id!==prior.chunk.phone_request_id
      ||next.sequence_index!==prior.chunk.sequence_index!+1||(next.playback_recovery_epoch??0)!==(prior.chunk.playback_recovery_epoch??0))
      throw Error('Continuous muxed source authority changed.');
    const previous=this.manifest.get(prior.chunk.sequence_index!);if(!previous)throw Error('Continuous muxed source unavailable.');
    this.checkManifest(previous);
    if(!row)return 'pending';this.checkManifest(row);
    if(this.chunkIdentity(row.chunk)!==this.chunkIdentity(next))throw Error('Continuous muxed source changed.');
    if(row.error)throw row.error;if(!row.prefix)return 'pending';
    const delivery=this.requiredDelivery(),plan=delivery.prepared(next);
    // Read the retained authenticated descriptors as part of compatibility;
    // this never selects output or requests/replaces the producer RETURN lane.
    const a=delivery.continuousDescriptor(prior.chunk,prior.plan,this.deps.ticket),b=delivery.continuousDescriptor(next,plan,this.deps.ticket);
    if(a.owner!==b.owner||a.connectionEpoch!==b.connectionEpoch||a.recoveryEpoch!==b.recoveryEpoch||a.ticket!==b.ticket)
      throw Error('Continuous muxed source authority changed.');
    return compatibleMuxedPlans(prior.plan,plan)?'compatible':'incompatible';
  }
  private applyContinuous(event:SourceEvent){
    if(event.membership==='visual'){
      this.check();const queued=this.queuedReturn;
      if(!queued?.admitted||!queued.epoch||!sameVisual(event.source,queued.epoch))
        throw Error('Continuous visual epoch unavailable.');
      if(event.kind==='visual_started'){
        this.finalVisualStarted=true;
        this.idle=queued.idle;this.nextIdle=undefined;this.phase='idle';this.changed();
      }
      return;
    }
    this.check();const source=this.continuousSources.get(event.source.id);
    if(!source||source.source.chunkId!==event.source.chunkId)throw Error('Continuous muxed journal source unavailable.');
    if(event.kind==='speech_membership_completed'){
      if(!this.queuedReturn?.admitted||!sameSource(this.queuedReturn.source,event.source)
        ||this.active?.chunk.id!==source.chunk.id)throw Error('Continuous speech departure changed.');
      // Keep the same registered actor for visual observation and Stop.
      this.active.drained=true;return;
    }
    if(event.kind!=='source_started')return;
    const previous=this.active;
    this.active={chunk:source.chunk,plan:source.plan,player:this.registered!,
      detach:()=>this.session.retireContinuousSource(source.source),drained:false};
    this.phase='speech';this.changed();
    if(previous?.chunk.id===source.chunk.id)return;
    // Ownership moves at actual native start. Local RETURN housekeeping stays
    // outside journal reconciliation and cannot gate already-admitted speech.
    this.continuousReturns=this.continuousReturns.then(async()=>{
      reportMuxedReturn('return_housekeeping_start',source.chunk.sequence_index);
      this.check();const old=this.nextIdle;this.nextIdle=undefined;
      if(old){old.cancelled=true;const results=await Promise.allSettled([old.idle.close(),old.work]);
        const closed=results[0];if(closed?.status==='rejected')throw closed.reason;
        this.idleScopes.delete(old.idle);}
      this.check();
      reportMuxedReturn('return_housekeeping_done',source.chunk.sequence_index);
      // A delayed cleanup may outlive several actual source boundaries. Only
      // the current source owns a new RETURN window; completed speech leases
      // may already be retired, but its admitted immutable plan is retained.
      if(this.active?.chunk.id!==source.chunk.id)return;
      const row=this.manifest.get(source.chunk.sequence_index!);
      if(!row||this.chunkIdentity(row.chunk)!==this.chunkIdentity(source.chunk))throw Error('Continuous muxed source changed.');
      this.checkManifest(row);
      this.continuation={identity:this.chunkIdentity(source.chunk),plan:JSON.stringify(source.plan)};
      await this.beforeSpeech(source.chunk,this.abort.signal,source.plan);
    });
    void this.continuousReturns.catch(()=>{if(!this.closed){this.phase='failed';this.changed();void this.close(true).catch(()=>undefined);}});
  }
  private async continuousDrained(snapshot:RunSnapshot){
    if(snapshot.tail.kind==='visual')throw Error('Continuous mixed retirement unavailable.');
    reportMuxedReturn('return_join_start',snapshot.tail.source.sequenceIndex);
    this.check();await this.continuousReturns;this.check();
    const active=this.active,next=this.nextIdle;
    if(!active||active.chunk.id!==snapshot.tail.source.chunkId||next?.chunkId!==active.chunk.id||snapshot.state!=='drained')
      throw Error('Continuous muxed terminal return changed.');
    const finality=this.replyFinality(active.chunk);
    if(finality!=='nonfinal'){
      this.phase='failed';this.changed();
      throw Error(finality==='final'?'Continuous final RETURN unavailable: final speech tail already sealed.'
        :'Continuous nonfinal return status unavailable.');
    }
    this.phase='waiting';this.changed();await next.work;this.check();
    reportMuxedReturn('return_join_done',active.chunk.sequence_index);
    reportMuxedReturn('return_activate_start',active.chunk.sequence_index);
    await next.idle.activateReturn();this.check();
    reportMuxedReturn('return_activate_done',active.chunk.sequence_index);
    this.active=undefined;this.nextIdle=undefined;this.idle=next.idle;this.registered=next.idle.player;
    this.phase='idle';this.changed();
  }
  subscribe=(callback:()=>void)=>{this.listeners.add(callback);return()=>{this.listeners.delete(callback);};};
  private changed(){for(const callback of this.listeners)callback();}
  private reportHold(stage:HoldStage,chunk:AudioChunk){
    if(!this.holdsLastFrame&&!this.independent)return;
    // Cumulative boundary time, not a transfer duration: a queue acquire can
    // reuse files already retained by lookahead. No owner/source identifiers.
    try{
      let files:ReturnType<MuxedTrialDelivery['files']>=[];
      try{files=this.delivery?.files(chunk)??[];}catch{}
      const sequence=chunk.sequence_index;
      void recordPhoneDebug('info','muxed_hold_frame',{stage,
        sequence_index:Number.isSafeInteger(sequence)&&sequence!>=0&&sequence!<64?sequence:-1,
        elapsed_ms:Math.max(0,Date.now()-this.startedAt),retained_ranges:files.length,
        retained_frames:files.reduce((total,file)=>total+file.frameCount,0)}).catch(()=>undefined);
    }catch{} // Diagnostics must never gate source admission or retirement.
  }
  private reportPrefetch(chunk:AudioChunk,reason:PrefetchReason,counts?:PrefetchCounts){
    if(!this.holdsLastFrame)return;
    try{
      if(this.prefetchGate?.chunkId===chunk.id&&this.prefetchGate.reason===reason)return;
      this.prefetchGate={chunkId:chunk.id,reason};
      const sequence=chunk.sequence_index;
      void recordPhoneDebug('info','muxed_prefetch_gate',{reason,
        sequence_index:Number.isSafeInteger(sequence)&&sequence!>=0&&sequence!<64?sequence:-1,
        elapsed_ms:Math.max(0,Date.now()-this.startedAt),reply_chunks:counts?.replyChunks??-1,
        successor_count:counts?.successorCount??-1}).catch(()=>undefined);
    }catch{}
  }
  private live(){const peer=this.deps.client().bufferedPeer;return !this.closed&&this.deps.current()
    &&(!this.owner||!peer||peer.cacheScope===this.owner);}
  private check(signal?:AbortSignal){
    // Acquisition records its cause before closing the runtime. Preserve that
    // cause for waiting callers instead of replacing it with cleanup fallout.
    if(this.acquisitionError)throw this.acquisitionError;
    if(!this.live()||signal?.aborted||this.abort.signal.aborted)throw Error('Muxed runtime owner ended.');
  }
  private requiredDelivery(){if(!this.delivery)throw Error('Muxed trial not armed.');return this.delivery;}
  private chunkIdentity(chunk:AudioChunk){return JSON.stringify([chunk.id,chunk.phone_request_id,chunk.sequence_index,
    chunk.url_path,chunk.playback_recovery_epoch]);}
  private authorityIdentity(authority:BufferedReplyAuthority){return JSON.stringify([authority.scope,authority.ticket,authority.auth]);}
  private finalityScopeCurrent(row:ManifestSource):boolean {
    if(!this.live()||this.abort.signal.aborted)return false;
    const authority=this.deps.reply(row.chunk),owner=this.owner||this.deps.client().bufferedPeer?.cacheScope;
    return !!authority&&!!owner&&authority.ticket===this.deps.ticket&&authority.scope.owner===owner
      &&authority.scope.replyId===this.replyId&&authority.scope.expiresAt>Date.now()
      &&this.authorityIdentity(authority)===row.authority;
  }
  /** Knowledge from the existing owned status observer, never output authority.
   * Validate the copied admission even when observation precedes native opening. */
  observeReplyStatus(requestId:string,status:PhoneReplyStatus,pagesReconciled:boolean):boolean {
    if(!pagesReconciled||requestId!==this.replyId||status.phone_request_id!==requestId||!this.manifest.size
      ||![...this.manifest.values()].every(row=>this.finalityScopeCurrent(row)))return false;
    this.replyFinalityObservation??=new MuxedReplyFinality(this.replyId);
    const accepted=this.replyFinalityObservation.observe(status,true);
    if(accepted)this.changed();
    return accepted;
  }
  replyFinality(chunk:AudioChunk):MuxedFinalityDecision {
    const row=this.manifest.get(chunk.sequence_index!);
    if(!row||this.chunkIdentity(row.chunk)!==this.chunkIdentity(chunk)||!this.finalityScopeCurrent(row))return 'invalid';
    return this.replyFinalityObservation?.decision(chunk.sequence_index!)??'unknown';
  }
  private async prepareFinalReturn(tail:TailCursor):Promise<'pending'|'nonfinal'|'admitted'>{
    this.check();const source=this.continuousSources.get(tail.source.id);
    if(!source||!sameSource(source.source,tail.source))throw Error('Continuous RETURN source changed.');
    const decision=this.replyFinality(source.chunk);
    if(decision==='invalid'||decision==='cancelled')throw Error('Continuous RETURN finality ended.');
    if(decision==='unknown')return 'pending';
    if(decision==='nonfinal')return 'nonfinal';
    const previous=this.queuedReturn;
    if(previous){
      if(!sameSource(previous.source,tail.source))throw Error('Continuous RETURN reservation changed.');
      if(previous.admitted)return 'admitted';
    }
    const pending=this.nextIdle;
    // Actual speech-start housekeeping owns the producer's single RETURN lane.
    // Waiting for that prefix must not block native journal/receipt reconciliation.
    if(!pending||pending.chunkId!==source.chunk.id||pending.cancelled||!pending.idle.retainedReady)return 'pending';
    await pending.work;this.check();
    if(this.nextIdle!==pending||pending.cancelled||this.replyFinality(source.chunk)!=='final')
      throw Error('Continuous RETURN reservation ended.');
    let queued=previous;
    if(!queued){
      const scope=this.idleScopes.get(pending.idle),plan=source.plan.idleReturn;
      if(!scope)throw Error('Continuous RETURN scope unavailable.');
      const binding:QueuedIdleBinding={
        open:async(status,files,signal,owns)=>{
          this.check(signal);
          if(this.replyFinality(source.chunk)!=='final'||this.idleScopes.get(pending.idle)!==scope
            ||status.trialId!==this.trialId||status.requestId!==pending.requestId
            ||status.motionId!==plan.motionId||status.avatarId!==plan.avatarId
            ||status.sourceFrameCount!==plan.sourceFrameCount||status.startFrame!==plan.startFrame
            ||status.videoQuality.video_kbps!==plan.videoQuality.video_kbps
            ||status.videoQuality.video_width!==plan.videoQuality.video_width||status.fps!==24
            ||status.videoQuality.video_fps!==24||plan.videoQuality.video_fps!==24)
            throw Error('Continuous RETURN descriptor changed.');
          const descriptor:ReturnDescriptor={finalSequenceIndex:source.source.sequenceIndex,
            sourceId:plan.sourceId,requestId:pending.requestId,mediaId:status.mediaId,
            scopeIdentity:scope.replyId,motionId:plan.motionId,sourceFrameCount:plan.sourceFrameCount,
            avatarId:plan.avatarId,quality:{kbps:plan.videoQuality.video_kbps,width:plan.videoQuality.video_width,fps:24},
            startFrame:plan.startFrame,expiresAtMs:scope.expiresAt};
          const reader=await this.session.appendContinuousReturn(queued!.tail,descriptor,files,signal,owns);
          if(reader)queued!.epoch=reader.visual;
          return reader;
        },
        detach:async()=>{
          await this.session.invalidateContinuous(source.source.run,'stop');
          await this.session.retireContinuousRun(source.source.run);
        },
      };
      queued=this.queuedReturn={tail,source:source.source,idle:pending.idle,binding,admitted:false};
    }
    queued.tail=tail;
    const admitted=await pending.idle.activateQueuedReturn(queued.binding);this.check();
    if(admitted)queued.admitted=true;
    return admitted?'admitted':'pending';
  }
  private checkManifest(row:ManifestSource){
    this.check();const authority=this.deps.reply(row.chunk);
    if(!authority||authority.ticket!==this.deps.ticket||authority.scope.owner!==this.owner
      ||authority.scope.replyId!==this.replyId||authority.scope.expiresAt<=Date.now()
      ||this.authorityIdentity(authority)!==row.authority)throw Error('Muxed reply owner ended.');
  }
  /** Only authenticated continuation admission calls this. Public state is
   * never a manifest in the independent lane. Copies freeze scoped identities. */
  update(chunks:readonly AudioChunk[]):void{
    if(!this.independent||!chunks.length)return;
    try{this.admitManifest(chunks);}catch(error){
      if(!this.closed){this.acquisitionError=error;this.phase='failed';this.changed();void this.close(true).catch(()=>undefined);}
      throw error;
    }
  }
  private admitManifest(chunks:readonly AudioChunk[]):void{
    this.check();if(chunks.length>64)throw Error('Muxed source capacity reached.');
    const owner=this.owner||this.deps.client().bufferedPeer?.cacheScope;
    const accepted=new Map(this.manifest);let replyId=this.replyId;
    for(const chunk of chunks){
      const sequence=chunk.sequence_index,authority=this.deps.reply(chunk);
      if(!Number.isSafeInteger(sequence)||sequence!<0||sequence!>=64||!/^[A-Za-z0-9_.-]{1,128}$/.test(chunk.id)
        ||chunk.url_path!==`/api/audio/file/${chunk.id}`||!chunk.phone_request_id
        ||chunk.playback_recovery_epoch!==undefined&&(!Number.isSafeInteger(chunk.playback_recovery_epoch)||chunk.playback_recovery_epoch<0)
        ||!authority||authority.ticket!==this.deps.ticket||authority.scope.owner!==owner
        ||authority.scope.replyId!==chunk.phone_request_id||!Number.isFinite(authority.scope.expiresAt)
        ||authority.scope.expiresAt<=Date.now()||replyId&&replyId!==chunk.phone_request_id)
        throw Error('Invalid muxed reply authority.');
      replyId=chunk.phone_request_id;
      const prior=accepted.get(sequence!),identity=this.chunkIdentity(chunk),scope=this.authorityIdentity(authority);
      if(prior&&(this.chunkIdentity(prior.chunk)!==identity||prior.authority!==scope)
        ||[...accepted.values()].some(row=>row.chunk.id===chunk.id&&this.chunkIdentity(row.chunk)!==identity))
        throw Error('Muxed source changed.');
      if(!prior)accepted.set(sequence!,{chunk:{...chunk},authority:scope});
    }
    if(accepted.size>64)throw Error('Muxed source capacity reached.');
    this.replyId=replyId;
    for(const [sequence,row] of accepted){this.manifest.set(sequence,row);this.chunks.set(row.chunk.id,row.chunk);}
    this.startAcquisition();
  }
  private startAcquisition(){
    if(!this.independent||this.acquisition||this.closed||this.acquisitionError||!this.manifest.has(this.acquisitionNext))return;
    const work=(async()=>{
      await this.start();this.check();
      while(this.manifest.has(this.acquisitionNext)){
        const row=this.manifest.get(this.acquisitionNext)!;this.checkManifest(row);
        this.reportHold('acquisition_start',row.chunk);
        row.lease=await this.requiredDelivery().acquireProgressive(row.chunk,this.abort.signal);
        this.checkManifest(row);row.prefix=true;this.reportHold('acquisition_prefix',row.chunk);
        this.reportHold('preparation_start',row.chunk);
        // Preparation's bounded native slot may wait on an earlier source.
        // Neither that slot nor playback may gate full-source acquisition.
        row.preparation=(this.continuousRequired?Promise.resolve():this.session.prepareSource(row.chunk,{updateInterval:100},this.deps.ticket,this.abort.signal))
          .then(()=>{this.checkManifest(row);row.prepared=true;this.reportHold('preparation_complete',row.chunk);});
        void row.preparation.catch(error=>{row.error=error;
          if(!this.closed){this.acquisitionError=error;this.phase='failed';this.changed();void this.close().catch(()=>undefined);}});
        await this.requiredDelivery().waitComplete(row.chunk,this.abort.signal);this.checkManifest(row);
        this.reportHold('acquisition_complete',row.chunk);this.acquisitionNext++;
      }
    })().catch(error=>{
      if(!this.closed){this.acquisitionError=error;this.phase='failed';this.changed();void this.close().catch(()=>undefined);}
    }).finally(()=>{if(this.acquisition===work){this.acquisition=undefined;this.startAcquisition();}});
    this.acquisition=work;
  }
  private successor(chunk:AudioChunk,counts?:PrefetchCounts):AudioChunk|undefined{
    if(!Number.isSafeInteger(chunk.sequence_index)||chunk.sequence_index!<0||chunk.sequence_index!>=63)return;
    const rows=this.independent?[...this.manifest.values()].map(row=>row.chunk):this.deps.chunks?.()??[];
    const matches=rows.filter(row=>row.phone_request_id===chunk.phone_request_id
      &&row.sequence_index===chunk.sequence_index!+1);
    if(counts)try{counts.replyChunks=Math.min(64,rows.filter(row=>row.phone_request_id===chunk.phone_request_id).length);
      counts.successorCount=Math.min(64,matches.length);}catch{}
    const candidate=matches.length===1?matches[0]:undefined;
    return candidate&&candidate.id!==chunk.id?candidate:undefined;
  }
  private prefetch(){
    if(this.independent){this.startAcquisition();return;}
    if(!this.live()||!this.active)return;
    // An occupied lookahead slot does not inspect chunks/authority again. -1
    // counts distinguish that existing early return from a metadata decision.
    if(this.lookahead){this.reportPrefetch(this.active.chunk,'held');return;}
    const counts=this.holdsLastFrame?{replyChunks:-1,successorCount:-1}:undefined;
    const chunk=this.successor(this.active.chunk,counts);
    if(!chunk){this.reportPrefetch(this.active.chunk,'missing_successor',counts);return;}
    const authority=this.deps.reply(chunk);
    if(!authority){this.reportPrefetch(this.active.chunk,'unavailable_authority',counts);return;}
    if(authority.ticket!==this.deps.ticket){this.reportPrefetch(this.active.chunk,'ticket_mismatch',counts);return;}
    if(authority.scope.owner!==this.owner){this.reportPrefetch(this.active.chunk,'owner_mismatch',counts);return;}
    if(authority.scope.replyId!==this.replyId){this.reportPrefetch(this.active.chunk,'reply_mismatch',counts);return;}
    if(!Number.isFinite(authority.scope.expiresAt)||authority.scope.expiresAt<=Date.now()){
      this.reportPrefetch(this.active.chunk,'expired_authority',counts);return;}
    this.chunks.set(chunk.id,{...chunk});
    const pending:Lookahead={chunk:{...chunk},abort:new AbortController(),work:null!};this.lookahead=pending;
    this.reportPrefetch(this.active.chunk,'start',counts);
    this.reportHold('lookahead_start',chunk);
    // File-only: never stage/install a native source or emit a playback receipt.
    // Delivery serializes full speech promotion after the preceding download;
    // no successor RETURN request is made while the current lane is retained.
    pending.work=(async()=>{
      const delivery=this.requiredDelivery();
      pending.lease=await (this.streamsChunks?delivery.acquireProgressive(chunk,pending.abort.signal):delivery.acquire(chunk,pending.abort.signal));
      this.check(pending.abort.signal);pending.plan=this.requiredDelivery().prepared(chunk);
      this.reportHold('lookahead_retained',chunk);
    })().catch(async error=>{pending.error=error;await pending.lease?.release();pending.lease=undefined;throw error;});
    void pending.work.catch(()=>undefined);
  }
  private continuationSource(active:AudioChunk):ContinuationSource|undefined{
    if(!this.independent)return this.lookahead;
    const successor=this.successor(active),row=successor&&this.manifest.get(successor.sequence_index!);
    if(!row?.prefix||!row.prepared||row.error)return;
    try{this.checkManifest(row);return {chunk:row.chunk,plan:this.requiredDelivery().prepared(row.chunk),error:row.error};}
    catch{return;}
  }
  private canContinue(active:{chunk:AudioChunk;plan:MuxedTrialPlan;drained:boolean},pending:ContinuationSource|undefined):pending is ContinuationSource{
    if(!active.drained||!pending?.plan||!this.independent&&!pending.lease||pending.error)return false;
    const successor=this.successor(active.chunk);
    if(!successor||this.chunkIdentity(successor)!==this.chunkIdentity(pending.chunk))return false;
    try{
      const delivery=this.requiredDelivery(),files=delivery.files(pending.chunk),a=active.plan,b=delivery.prepared(pending.chunk);
      if(!files.length||files.some(file=>!delivery.owns(pending.chunk,file.uri))||JSON.stringify(b)!==JSON.stringify(pending.plan))return false;
      return compatibleMuxedPlans(a,b);
    }catch{return false;}
  }
  private scopeCurrent(scope:BufferedMediaScope){
    let now:number|undefined;
    const reason=!this.live()?'runtime_not_live':scope.owner!==this.owner?'runtime_owner_changed'
      :scope.expiresAt<=(now=Date.now())?'runtime_expired':null;
    if(reason){this.mediaScopeTrace.rejected('runtime',reason,scope,now);return false;}
    if([...this.idleScopes.values()].some(current=>JSON.stringify(scope)===JSON.stringify(current)))return true;
    const current=[...this.chunks.values()].some(chunk=>{
      const authority=this.deps.reply(chunk);return authority?.ticket===this.deps.ticket
        &&authority.scope.owner===scope.owner&&authority.scope.replyId===scope.replyId&&authority.scope.expiresAt===scope.expiresAt;
    });
    if(!current)this.mediaScopeTrace.rejected('runtime','runtime_scope_unregistered',scope,now);
    return current;
  }
  private request(method:'GET'|'POST',path:string,body?:Record<string,unknown>,signal=this.abort.signal,diagnosticLink?:import('../diagnostics/planTransaction').DiagnosticLink){
    this.check(signal);const peer=this.deps.client().bufferedPeer;
    if(!peer||peer.closed)throw new PeerTransportUnavailableError('Muxed peer reconnecting.');
    return this.deps.client().requestLiveVisual(method,path,body,signal,diagnosticLink);
  }
  private async wait(signal=this.abort.signal,delayMs=40){
    this.check(signal);await new Promise<void>(resolve=>{
      const done=()=>{clearTimeout(timer);signal.removeEventListener('abort',done);this.abort.signal.removeEventListener('abort',done);resolve();};
      const timer=setTimeout(done,delayMs);signal.addEventListener('abort',done,{once:true});this.abort.signal.addEventListener('abort',done,{once:true});
    });this.check(signal);
  }
  private async arm(){
    for(let attempt=0;;attempt++){
      try{return await this.request('POST',PREFIX+'arm',{armRequestId:this.armRequestId,idleChunks:true,muxedAudio:true});}
      catch(error){
        // Only the opt-in producer's explicit busy conflict is retryable. No
        // retry on validation/auth failure, lost ACK or incompatible mode.
        if((error as {httpStatus?:number})?.httpStatus!==409||attempt>=20)throw error;
        await this.wait(this.abort.signal,100);
      }
    }
  }
  start():Promise<void>{
    return this.opening??=(async()=>{
      this.check();if(!muxedTrialAvailable()||!this.deps.ticket)throw Error('Guarded muxed trial unavailable.');
      if(this.continuousRequired&&(!muxedContinuousAvailable()||!this.streamsChunks))
        throw Error('Update NC Remote for continuous muxed queue version2.');
      if(this.independent&&!this.holdsLastFrame&&!muxedSourceFenceAvailable())throw Error('Update NC Remote for confirmed muxed source retirement.');
      this.phase='arming';this.changed();this.startupStage='peer';const peer=this.deps.client().bufferedPeer;
      if(!peer||peer.closed||!peer.cacheScope)throw new PeerTransportUnavailableError('Muxed peer reconnecting.');
      this.owner=peer.cacheScope;this.startupStage='negotiate';const capability=await peer.negotiateBuffered();this.check();
      this.startupStage='quality';
      if(capability.video_quality.video_fps!==24)throw Error('Muxed trial requires 24 fps.');
      this.startupStage='arm';
      // The producer grants a fresh fixed 100-minute muxed arm. Starting this local
      // bound before the request is conservative across network/busy delays;
      // no ACK, speech completion or retry can extend this epoch's permission.
      this.producerStartedAt=Date.now();this.producerExpiresAt=this.producerStartedAt+6000000;
      const result=await this.arm() as
        {trialId?:string;idleChunks?:boolean;muxedAudio?:boolean;readyWaitVersion?:number};
      this.startupStage='arm-ack';
      if(/^[a-f0-9]{32}$/.test(result.trialId??''))this.trialId=result.trialId!;
      this.check();if(!this.trialId||result.idleChunks!==true||result.muxedAudio!==true||result.readyWaitVersion!==1)
        throw Error('Update NC Desktop for the current muxed ready-wait contract.');
      this.startupStage='idle';
      const scope={owner:this.owner,replyId:`muxed-idle:${this.trialId}`,expiresAt:this.producerExpiresAt};
      this.scopeStartedAt.set(scope,this.producerStartedAt);
      this.delivery=new MuxedTrialDelivery({trialId:this.trialId,store:this.store,
        ...(this.independent?{independent:true,limits:{maxFiles:64,maxBytes:128*1024*1024}}:{}),
        readyWait:true,
        ...(this.deps.claimWaitingPlan&&!this.holdsLastFrame?{onWaitingPlan:(chunk:AudioChunk,plan:NonNullable<MuxedTrialPlan['anticipation']>,signal:AbortSignal)=>this.beginWaiting(chunk,plan,signal)}:{}),
        authority:chunk=>this.live()?this.deps.reply(chunk):null,retryable,
        ...(this.holdsLastFrame?{onRangeRetained:(details:MuxedRangePreparation)=>{
          try{void recordPhoneDebug('info','muxed_range_preparation',details).catch(()=>undefined);}catch{}
        }}:{}),
        request:(method,path,body,signal,diagnosticLink)=>this.request(method,path,body,signal,diagnosticLink)});
      this.idle=new MuxedTrialIdle({trialId:this.trialId,requestId:idleChunkRequestId(),startFrame:0,
        ticket:this.deps.ticket,scope,settings:{updateInterval:100},store:this.store,audio:this.session,
        current:()=>this.live(),retryable,request:(path,body,signal)=>this.request('POST',path,body,signal)});
      this.idleScopes.set(this.idle,scope);
      await this.fill(this.idle,this.abort.signal);this.registered=this.idle.player;this.phase='idle';this.changed();
    })().catch(error=>{this.phase='failed';this.changed();throw error;});
  }
  private async fill(idle:MuxedTrialIdle,signal:AbortSignal,retainOnly=false,sequenceIndex?:number){
    if(retainOnly)reportMuxedReturn('return_prefill_start',sequenceIndex);
    const ready=()=>retainOnly?idle.retainedReady:idle.ready;
    while(!ready()){this.check(signal);await idle.tick();this.registered=idle.player??this.registered;this.changed();
      if(!ready())await this.wait(signal);}
    if(retainOnly)reportMuxedReturn('return_prefill_done',sequenceIndex);
  }
  tick=async()=>{
    if(this.reservedContinuation){
      try{
        const row=this.manifest.get(this.reservedContinuation.sequence_index!);
        if(!row||this.chunkIdentity(row.chunk)!==this.chunkIdentity(this.reservedContinuation))
          throw Error('Muxed continuation authority ended.');
        this.checkManifest(row);
      }catch(error){
        // Queue authorization may refuse activation before createPlayer runs.
        // The ordinary tick must then cancel/join the deferred old retirement.
        this.session.cancelContinuation();this.phase='failed';this.changed();
        void this.close(true).catch(()=>undefined);throw error;
      }
    }
    this.check();this.session.checkProgress();this.prefetch();
    const queued=this.queuedReturn;
    if(queued?.admitted&&queued.idle!==this.idle)await queued.idle.tick();
    if(this.phase==='idle'&&this.idle){
      const idle=this.idle,work=idle.tick();
      if(!this.holdsLastFrame&&!this.continuousRequired){await work;return;}
      const pending={idle,work};this.idleTick=pending;
      try{await work;}finally{if(this.idleTick===pending)this.idleTick=undefined;}
    }
  };
  private async beforeSpeech(chunk:AudioChunk,signal:AbortSignal,retainedPlan?:MuxedTrialPlan){
    this.check(signal);const delivery=this.requiredDelivery(),plan=retainedPlan??delivery.prepared(chunk),idle=this.idle;
    this.reportHold('native_staged',chunk);
    if(this.holdsLastFrame){
      if(this.nextIdle||this.planning)throw Error('Muxed source preparation already active.');
      this.planning=true;
      try{
        const files=delivery.files(chunk),authority=this.deps.reply(chunk),now=Date.now();
        if(!files.length||files.some(file=>!delivery.owns(chunk,file.uri)))throw Error('Muxed file authority ended.');
        if(!authority||authority.ticket!==this.deps.ticket||authority.scope.owner!==this.owner
          ||authority.scope.replyId!==chunk.phone_request_id||!Number.isFinite(authority.scope.expiresAt)
          ||authority.scope.expiresAt<=now)throw Error('Muxed reply owner ended.');
        // Initial desktop idle remains output until validated speech is ready.
        // Its native source retirement schedules stop; it does not prove that
        // Media3's old loader has exited. Keep its immutable scope/files pinned
        // for trial teardown while the session advances the source revision.
        if(idle){this.phase='waiting';this.changed();
          // A hook tick may already be retaining/appending initial output.
          // Join it before the session advances its native source revision.
          // No new idle ticks start in waiting; real failures still reject.
          const pending=this.idleTick;if(pending?.idle===idle)await pending.work;
          this.check(signal);if(this.idle===idle)this.idle=undefined;}
        this.check(signal);return;
      }finally{this.planning=false;}
    }
    const direct=this.continuation;
    if(direct&&(direct.identity!==this.chunkIdentity(chunk)||direct.plan!==JSON.stringify(plan)))throw Error('Muxed desktop continuation changed.');
    if((!direct&&(!idle||!this.idleScopes.has(idle)))||this.nextIdle||this.planning)throw Error('Muxed idle source unavailable.');
    this.planning=true;
    try{
      if(this.continuousRequired&&idle){this.phase='waiting';this.changed();
        const pending=this.idleTick;if(pending?.idle===idle)await pending.work;this.check(signal);}
      if(!direct){const files=delivery.anticipationFiles(chunk);
        const ownsPlan=()=>this.live()&&delivery.files(chunk).every(file=>delivery.owns(chunk,file.uri))
          &&files.every(file=>delivery.owns(chunk,file.uri));
        if(this.deps.claimWaitingPlan&&plan.anticipation){
          await this.waitingWork;this.check(signal);
          if(plan.anticipation.planId!==this.waitingPlanId)
            throw Error('Muxed desktop waiting agreement unavailable: admitted_plan_mismatch.');
          if(!await idle!.finishWaitingPlan(plan.anticipation.planId,files,signal,ownsPlan))
            throw Error('Muxed desktop waiting agreement unavailable: finish_rejected.');
        }else{
          idle!.abandonWaitingBoundary('speech_without_plan');
          // Only a different motion has no shared idle-frame coordinate. The
          // normal same-motion path must never scan an entire idle cycle.
          if(this.deps.claimWaitingPlan&&idle!.motionMatches(plan)){
            this.planDecision('phone.runtime.before_speech','same_motion_without_anticipation',false,true);
            throw Error('Muxed desktop waiting plan unavailable.');
          }
          await idle!.finishPlan(plan,files,signal,ownsPlan);
        }}
      this.check(signal);
      const authority=this.deps.reply(chunk),now=Date.now();
      if(!authority||authority.ticket!==this.deps.ticket||authority.scope.owner!==this.owner
        ||authority.scope.replyId!==chunk.phone_request_id||!Number.isFinite(authority.scope.expiresAt)
        ||authority.scope.expiresAt<=now)throw Error('Muxed reply owner ended.');
      // Each validated desktop return gets a new immutable silent epoch, not
      // the startup epoch's spent deadline. This never renews audio authority
      // or mutates retained leases, and starts only after the old actual END.
      const requestId=idleChunkRequestId(),scope={owner:this.owner,replyId:`muxed-idle:${this.trialId}:${requestId}`,
        expiresAt:Math.min(now+6000000,authority.scope.expiresAt)};
      this.scopeStartedAt.set(scope,now);
      const next=new MuxedTrialIdle({trialId:this.trialId,requestId,startFrame:plan.idleReturn.startFrame,
        ticket:this.deps.ticket,scope,settings:{updateInterval:100},store:this.store,audio:this.session,
        returnSource:plan.idleReturn,returnPrefetch:true,current:()=>this.live(),retryable,
        ...(this.continuousRequired?{returnPrefill:2 as const}:{}),
        request:(path,body,abort)=>this.request('POST',path,body,abort)});
      this.idleScopes.set(next,scope);const pending={chunkId:chunk.id,requestId,idle:next,work:undefined as Promise<void>|undefined,cancelled:false};
      this.nextIdle=pending;
      // The producer has one return lane. Only now may its next request replace
      // the old sealed lane. Legacy readers retain the whole return before
      // installation; the independent lane prepares it during speech instead.
      if(this.independent){
        // Retain-only return preparation can run while speech is output. Its
        // startup prefix never blocks installing an already prepared speech
        // prefix, and cannot replace the old return lane before actual END.
        const discarded=[...this.discarding.values()];
        // The single producer lane and shared storage must not acquire a new
        // return window until every unused predecessor actually cleaned up.
        pending.work=discarded.length?(async()=>{
          await Promise.all(discarded);if(pending.cancelled)return;
          this.check();await this.fill(next,this.abort.signal,true,chunk.sequence_index);
        })():this.fill(next,this.abort.signal,true,chunk.sequence_index);
        void pending.work.catch(error=>{
          if(!this.closed&&this.nextIdle===pending){this.phase='failed';this.changed();void this.close().catch(()=>undefined);}
        });
      }else await this.fill(next,signal,true,chunk.sequence_index);
      if(idle){
        if(this.continuousRequired)this.continuousInitialIdle=idle;
        else{await idle.close();this.idleScopes.delete(idle);}
        this.idle=undefined;
      }
      this.check(signal);this.continuation=undefined;
    }finally{this.planning=false;}
  }
  drained=(chunk:AudioChunk,player:AudioPlayer)=>{
    if(this.continuousRequired)return;
    const active=this.active;if(!this.live()||!active||active.chunk.id!==chunk.id||active.player!==player)return;
    const status=player.currentStatus;
    if(status.didJustFinish===true&&!status.playing&&!(status as {error?:unknown}).error){
      active.drained=true;
      this.reportHold('drain_observed',chunk);
      if(!this.holdsLastFrame){const next=this.continuationSource(active.chunk);
        if(this.canContinue(active,next)){
          active.continuing=this.session.reserveContinuation(active.chunk,next.chunk);
          if(active.continuing)this.reservedContinuation={...next.chunk};
        }}
    }
  };
  finished=(chunk:AudioChunk)=>{
    if(this.continuousRequired)return;
    const active=this.active,next=this.nextIdle;
    if(!active||active.chunk.id!==chunk.id)return;
    if(this.holdsLastFrame){
      this.active=undefined;
      this.returning=(async()=>{
        await active.detach();
        if(!active.drained||!this.live()){
          this.phase='failed';this.changed();void this.close().catch(()=>undefined);return;
        }
        // Keep the registered native player mounted across source retirement.
        // The queue still owns actual drain proof and per-source receipts.
        this.phase='waiting';this.changed();this.reportHold('natural_waiting',active.chunk);
      })().catch(error=>{this.phase='failed';this.changed();void this.close().catch(()=>undefined);throw error;});
      void this.returning.catch(()=>undefined);return;
    }
    if(next?.chunkId!==chunk.id)return;
    const candidate=this.continuationSource(active.chunk);
    const direct=this.canContinue(active,candidate)?candidate:undefined;
    this.active=undefined;this.nextIdle=undefined;
    this.returning=(async()=>{
      if(!direct||!active.continuing){this.reservedContinuation=undefined;this.session.cancelContinuation();await active.detach();}
      if(!active.drained||!this.live()){
        await next.idle.close();this.phase='failed';this.changed();void this.close().catch(()=>undefined);return;
      }
      if(direct&&this.canContinue(active,direct)){
        // The predecessor actually drained and the exact successor is already
        // retained. Keep the drained source open for a guarded native promotion
        // instead of stopping/repreparing the decoder. Older APKs retain the
        // existing detach/install path; no extra idle frames are inserted.
        this.reportHold('direct_return_close_start',active.chunk);
        if(active.continuing){
          // This return was never offered to native. Keep its scope and cleanup
          // owned while the exact, actually drained speech source promotes.
          next.cancelled=true;
          const work=Promise.allSettled([next.idle.close(),next.work]).then(results=>{
            const closed=results[0];if(closed.status==='rejected')throw closed.reason;
            this.reportHold('direct_return_close_complete',active.chunk);this.idleScopes.delete(next.idle);
            this.discarding.delete(next.idle);
          });
          this.discarding.set(next.idle,work);
          void work.catch(()=>{
            if(!this.closed){this.phase='failed';this.changed();void this.close(true).catch(()=>undefined);}
          });
        }else{
          await next.idle.close();this.reportHold('direct_return_close_complete',active.chunk);
          this.idleScopes.delete(next.idle);
        }
        this.check();
        this.continuation={identity:this.chunkIdentity(direct.chunk),plan:JSON.stringify(direct.plan)};
        this.phase='speech';this.changed();return;
      }
      this.reservedContinuation=undefined;this.session.cancelContinuation();await active.detach();
      this.phase='waiting';this.changed();
      await next.work;this.check();
      await next.idle.activateReturn();this.check();this.idle=next.idle;this.registered=next.idle.player;
      this.phase='idle';this.changed();
    })().catch(error=>{this.phase='failed';this.changed();void this.close().catch(()=>undefined);throw error;});
    void this.returning.catch(()=>undefined);
  };
  close(failed=false):Promise<void>{
    return this.closing??=(async()=>{
      this.closed=true;this.abort.abort();
      const continuousCleanup=this.continuousReturns.catch(()=>undefined);
      // Publish terminal ownership before native release. A still-selected
      // view must not read properties from a retired SharedObject while the
      // existing reader/file cleanup below is awaiting its exit barriers.
      this.registered=null;this.phase=failed||this.phase==='failed'?'failed':'off';this.changed();
      this.continuation=undefined;
      this.reservedContinuation=undefined;
      const pending=this.lookahead;this.lookahead=undefined;pending?.abort.abort();
      const returnPrefill=this.nextIdle;if(returnPrefill)returnPrefill.cancelled=true;
      // Fence output first; file readers/leases are joined, never force-deleted.
      // A returning epoch is still registered while activation awaits native,
      // even after finished() removes it from nextIdle. Join every owned epoch.
      // HOLD pins the dormant initial window through registered-player
      // teardown. A failed session close keeps these files pinned. This does
      // not add a native loader-exit guarantee to the existing close contract.
      if(this.independent){
        // Join acquisition even when native retirement fails. Quiescing stops
        // downloads without releasing the files an unconfirmed reader owns.
        const results=await Promise.allSettled([this.session.close(),this.delivery?.quiesce(),this.acquisition,
          Promise.allSettled([...this.manifest.values()].map(row=>row.preparation)),
          ...[...this.idleScopes.keys()].map(idle=>idle.quiesce()),...this.discarding.values(),
          returnPrefill?.work?.catch(()=>undefined),continuousCleanup]);
        const failed=results.find(result=>result.status==='rejected');
        if(failed?.status==='rejected')throw failed.reason;
        await Promise.all([...this.manifest.values()].map(row=>row.lease?.release()));
      }else if(this.holdsLastFrame)await this.session.close();
      await Promise.all([...(this.holdsLastFrame?[]:[this.session.close()]),...[...this.idleScopes.keys()].map(idle=>idle.close()),
        (async()=>{await pending?.work.catch(()=>undefined);await pending?.lease?.release();})()]);
      this.idleScopes.clear();
      this.discarding.clear();
      await this.opening?.catch(()=>undefined);await this.returning.catch(()=>undefined);await continuousCleanup;
      await this.delivery?.close();
      const peer=this.deps.client().bufferedPeer;
      if(peer&&!peer.closed&&peer.cacheScope===this.owner){
        await this.deps.client().requestLiveVisual('POST',PREFIX+'cancel',this.trialId?{trialId:this.trialId}:{armRequestId:this.armRequestId},
          new AbortController().signal).catch(()=>undefined);
      }
      this.registered=null;this.chunks.clear();this.manifest.clear();this.changed();
    })();
  }
}
