import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import type {PhoneReplyReceipt} from '../api/types';
import type {DesktopOrderedDelivery,OrderedRetained} from './desktopOrderedDelivery';
import {parseOrderedNativeSnapshot} from './desktopOrderedProtocol';
import type {OrderedNativeSnapshot,OrderedNativeSource,OrderedSource,OrderedRun,OrderedStoppedOutput} from './desktopOrderedProtocol';
import {PlanTransactionTrace} from '../diagnostics/planTransaction';
import {OrderedChunkTiming} from '../diagnostics/orderedChunkTiming';
import {observeOrderedControlWait as observeWait} from '../diagnostics/orderedControlWait';

export type OrderedSessionScope=Readonly<{ticket:string;owner:string;connectionEpoch:string;recoveryEpoch:number;
  streamId:string;generation:number;expiresAtMs:number}>;
type Native=Record<string,(request?:unknown)=>Promise<unknown>>;
type NativeEvent=Readonly<{cursor:number;kind:string;source:OrderedNativeSource}>;
type Dependencies={session:OrderedSessionScope;native:Native;delivery:DesktopOrderedDelivery;
  authority(source:OrderedSource):BufferedReplyAuthority|null;
  beforeSpeech?(source:OrderedSource):Promise<void>;
  finalSequence(replyId:string):number|null;
  onOpened():void|Promise<void>;onEvents(events:readonly NativeEvent[]):Promise<void>;
  onStoppedOutput?(receipt:OrderedStoppedOutput):Promise<void>;
  onReplyAdmitted?(replyId:string):void;
  onInterruption?(receipt:PhoneReplyReceipt):void;
  onReplyCompleted?(replyId:string):void|Promise<void>};
type Stage={id:string;batch:readonly OrderedRetained[]};
const methods=['ncOpenOrderedMuxed','ncStageOrderedMuxed','ncAppendOrderedMuxed','ncReadOrderedMuxed',
  'ncAcknowledgeOrderedMuxed','ncPruneOrderedMuxed','ncCompleteReplyOrderedMuxed','ncInvalidateOrderedMuxed',
  'ncDropOrderedMuxed','ncCloseOrderedMuxed','ncCloseMuxedTrial'];
function row(value:unknown,fields:readonly string[]):Record<string,unknown>{
  if(!value||typeof value!=='object'||Array.isArray(value))throw Error('ordered.rpc.object');
  const r=value as Record<string,unknown>;
  if(r.version!==1||Object.keys(r).length!==fields.length+1||fields.some(key=>!Object.prototype.hasOwnProperty.call(r,key)))throw Error('ordered.rpc.fields');
  return r;
}
const id=(value:unknown):value is string=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value);
const sameRun=(a:OrderedRun,b:OrderedRun)=>a.id===b.id&&a.revision===b.revision;
const journalResponse=(raw:unknown)=>row(raw,raw&&typeof raw==='object'&&Object.prototype.hasOwnProperty.call(raw,'interruption')
  ?['snapshot','events','interruption']:['snapshot','events']);

/** One ordered visual carrier, fresh authenticated speech grants. No mobile
 * frame planning, anticipation, idle injection, seek or source-END synthesis.
 * pump is driven by acquisition/native observation events; it never downloads.
 * The existing output owner supplies onOpened (guarded play), not this class. */
export class DesktopOrderedSession {
  private readonly session:OrderedSessionScope;
  private readonly native:Native;
  private readonly diagnostics?:PlanTransactionTrace;
  private readonly timing:OrderedChunkTiming;
  private run:OrderedRun|null=null;private observed:OrderedNativeSnapshot|null=null;
  private stage:Stage|null=null;private cursor=0;
  private transportPaused=false;
  private lastAppendedKind:OrderedSource['kind']|null=null;
  private readonly replies=new Map<string,{completed:Set<number>;finalized:boolean}>();
  private serial:Promise<void>=Promise.resolve();private pumping:Promise<void>|null=null;
  private pumpRequested=false;
  private stopping:Promise<void>|null=null;private closing:Promise<void>|null=null;
  private stopped=false;private failure:unknown=null;private failed=false;private openAttempted=false;
  private interruptionHandled=false;
  private nativeCloseResult:unknown;private nativeCloseConfirmed=false;
  private cachedReadersJoined=false;
  private resolveLocal!:()=>void;private rejectLocal!:(error:unknown)=>void;
  private readonly localClosed=new Promise<void>((resolve,reject)=>{this.resolveLocal=resolve;this.rejectLocal=reject;});
  constructor(private readonly deps:Dependencies){
    void this.localClosed.catch(()=>undefined);
    this.session=Object.freeze({...deps.session});this.native=deps.native;
    this.timing=new OrderedChunkTiming(this.session.streamId,this.session.generation);
    const s=this.session;
    if(Object.keys(s).length!==7||!id(s.ticket)||!s.owner||s.owner.length>2048||!s.connectionEpoch||s.connectionEpoch.length>256
      ||![s.recoveryEpoch,s.generation,s.expiresAtMs].every(Number.isSafeInteger)||s.recoveryEpoch<0||s.generation<0
      ||s.expiresAtMs<=Date.now()||!/^[a-f0-9]{32}$/.test(s.streamId))throw Error('ordered.session_scope');
    if(methods.some(method=>typeof this.native[method]!=='function'))throw Error('ordered.native_contract_unavailable');
    // Match the registered native player's observer identity. Correlation is
    // still supplied with logging OFF; absent links otherwise look like failed
    // validation and force a record on every successful read/prune operation.
    try{
      const playerId=(this.native as unknown as {id?:unknown}).id;
      if(typeof playerId==='string'&&/^[a-f0-9-]{36}$/i.test(playerId))this.diagnostics=new PlanTransactionTrace(playerId);
    }catch{ /* Diagnostic setup cannot change playback admission. */ }
  }
  private call(method:string,value:Record<string,unknown>){
    const invoke=(link?:{trace_id:string;operation_id:string;event_id:string|null})=>{
      const diagnosticLink=link?{trace_id:link.trace_id,operation_id:link.operation_id,
        ...(link.event_id!==null?{event_id:link.event_id}:{})}:undefined;
      const request={version:1,...value,...(diagnosticLink?{diagnosticLink}:{})};
      // Expo Any recursively treats null as an object. Preserve the immutable
      // nullable descriptor fields through a JSON boundary for media admission.
      const argument=method==='ncOpenOrderedMuxed'||method==='ncStageOrderedMuxed'?JSON.stringify(request):request;
      return this.native[method]!.call(this.native,argument);
    };
    const pending=this.diagnostics?this.diagnostics.observeCall('phone.native.'+method,invoke):invoke();
    return method==='ncInvalidateOrderedMuxed'?observeWait('native.invalidate',pending)
      :method==='ncCloseOrderedMuxed'||method==='ncCloseMuxedTrial'?observeWait('native.close',pending):pending;
  }
  private check(){if(this.failed)throw this.failure;if(this.stopped)throw Error('ordered.session_stopped');
    if(Date.now()>=this.session.expiresAtMs)throw Error('ordered.session_expired');}
  pauseTransport(paused:boolean){this.transportPaused=paused;}
  continuationScope(){return this.run?{ticket:this.session.ticket,streamId:this.session.streamId,
    generation:this.session.generation,run:this.run}:null;}
  continuationNative(method:string,request:Record<string,unknown>):Promise<unknown>{
    this.check();
    if(!['ncSuspendOrderedTransport','ncReadOrderedContinuation','ncResumeOrderedTransport','ncCancelOrderedContinuation'].includes(method)
      ||typeof this.native[method]!=='function')return Promise.reject(Error('ordered.continuation_unsupported'));
    return this.call(method,request);
  }
  private async observe(value:unknown){
    const snapshot=parseOrderedNativeSnapshot(value);
    if(snapshot.streamId!==this.session.streamId||snapshot.generation!==this.session.generation
      ||this.run&&!sameRun(this.run,snapshot.run))throw Error('ordered.native_scope');
    await this.deps.delivery.observeNative(snapshot);this.observed=snapshot;return snapshot;
  }
  private async opened(batch:readonly OrderedRetained[]){
    const first=batch[0]!;
    if(first.chunk.ordinal!==0||first.source.kind==='speech')throw Error('ordered.initial_visual_required');
    this.openAttempted=true;
    this.timing.record('open_begin',first.chunk.ordinal,batch.length);
    const response=row(await this.call('ncOpenOrderedMuxed',{session:this.session,
      descriptor:{...first.source,expiresAtMs:this.session.expiresAtMs},output:batch.map(b=>b.chunk),files:batch.map(b=>b.file)}),['run','sourceId','snapshot']);
    const snapshot=parseOrderedNativeSnapshot(response.snapshot);
    if(JSON.stringify(response.run)!==JSON.stringify(snapshot.run)||snapshot.nextOrdinal!==batch.length
      ||snapshot.mutationRevision!==1||!id(response.sourceId)
      ||!snapshot.sources.some(s=>s.id===response.sourceId&&s.sourceId===first.source.sourceId&&s.firstOrdinal===0))throw Error('ordered.open_ack');
    this.run=snapshot.run;
    this.lastAppendedKind=first.source.kind;
    this.timing.record('opened',first.chunk.ordinal,batch.length,this.run.revision);
    if(this.stopped){await this.fence('stop');return;}
    await this.observe(snapshot);this.check();await this.deps.onOpened();
  }
  private async read(){
    const raw=await this.call('ncReadOrderedMuxed',{run:this.run,cursor:this.cursor});
    const interrupted=Boolean(raw&&typeof raw==='object'&&Object.prototype.hasOwnProperty.call(raw,'interruption'));
    const response=journalResponse(raw);
    if(interrupted){
      const snapshot=parseOrderedNativeSnapshot(response.snapshot);
      const receipt=response.interruption as Partial<PhoneReplyReceipt>|null;
      if(snapshot.streamId!==this.session.streamId||snapshot.generation!==this.session.generation
        ||!this.run||!sameRun(this.run,snapshot.run)||snapshot.failure!=='ordered_owner_cancelled'
        ||!receipt||Object.keys(receipt).length!==3||!id(receipt.phone_request_id)||!id(receipt.interruption_id)
        ||!Array.isArray(receipt.started_chunk_ids)||receipt.started_chunk_ids.length>2048
        ||!receipt.started_chunk_ids.every(id)||new Set(receipt.started_chunk_ids).size!==receipt.started_chunk_ids.length
        ||!snapshot.sources.some(source=>source.kind==='speech'&&source.replyId===receipt.phone_request_id)
        ||!this.deps.onInterruption)throw Error('ordered.native_interruption_scope');
      const started=[...receipt.started_chunk_ids];Object.freeze(started);
      this.deps.onInterruption(Object.freeze({phone_request_id:receipt.phone_request_id,
        interruption_id:receipt.interruption_id,started_chunk_ids:started}));
      if(!this.stopped)throw Error('ordered.native_interruption_not_fenced');
      this.interruptionHandled=true;
      return;
    }
    const snapshot=await this.observe(response.snapshot);
    if(!Array.isArray(response.events)||response.events.length>256)throw Error('ordered.journal_events');
    let cursor=this.cursor;
    const events=response.events.map(value=>{
      if(!value||typeof value!=='object'||Array.isArray(value))throw Error('ordered.journal_event');
      const e=value as Record<string,unknown>;
      const source=snapshot.sources.find(s=>s.id===e.sourceId);
      if(Object.keys(e).length!==3||e.cursor!==++cursor||!source
        ||!['source_started','source_completed','source_readers_closed','visual_started','visual_readers_closed','visual_retired'].includes(e.kind as string))throw Error('ordered.journal_event');
      if((e.kind as string).startsWith('source_')!==(source.kind==='speech'))throw Error('ordered.journal_kind');
      if((e.kind==='source_started'||e.kind==='visual_started')&&!source.started)throw Error('ordered.journal_start');
      if(e.kind==='source_completed'&&(!source.started||!source.completed))throw Error('ordered.journal_completion');
      return Object.freeze({cursor,kind:e.kind as string,source});
    });
    if(cursor!==snapshot.publishedCursor||snapshot.acknowledgedCursor!==this.cursor)throw Error('ordered.journal_cursor');
    if(events.length){
      // Native already committed the receipts. Notification must not manufacture
      // them from enqueue/readiness or acknowledge evidence before it is handled.
      await this.deps.onEvents(events);this.check();
      for(const event of events)if(event.kind==='source_completed'){
        const reply=this.replies.get(event.source.replyId!);if(!reply)throw Error('ordered.journal_reply');
        reply.completed.add(event.source.sequenceIndex!);
      }
    }
    for(const [replyId,reply] of this.replies){
      const final=this.deps.finalSequence(replyId);
      if(!reply.finalized&&final!==null){
        if(!Number.isSafeInteger(final)||final<0||final>63)throw Error('ordered.reply_finality');
        if(reply.completed.size===final+1&&Array.from({length:final+1},(_,i)=>i).every(i=>reply.completed.has(i))
          &&await this.call('ncCompleteReplyOrderedMuxed',{run:this.run,replyId,finalSequenceIndex:final})===true){
          reply.finalized=true;await this.deps.onReplyCompleted?.(replyId);this.check();
        }
      }
    }
    if(events.length){if(await this.call('ncAcknowledgeOrderedMuxed',{run:this.run,cursor})!==true)throw Error('ordered.journal_ack');this.cursor=cursor;}
    // Only already-finalized, actually joined memberships can leave this bounded
    // local receipt summary. Native independently controls grant reclamation.
    for(const [replyId,reply] of this.replies)if(reply.finalized&&snapshot.sources.filter(s=>s.replyId===replyId).every(s=>s.readersClosed))this.replies.delete(replyId);
    return snapshot;
  }
  private async append(batch:readonly OrderedRetained[]){
    const first=batch[0]!,source=first.source;
    if(!this.stage){
      const prior=this.observed!.sources.find(s=>s.sourceId===source.sourceId);
      // A downloaded successor is not yet playable when the first range has
      // already been staged alone. Stage an announced startup pair together;
      // acquisition stays independent and no later speech segment waits here.
      if(!prior&&source.kind==='speech'&&this.lastAppendedKind!=='speech'&&batch.length===1
        &&this.deps.delivery.hasAcquiringSuccessor(first.chunk)){
        this.timing.record('startup_buffer_wait',first.chunk.ordinal,batch.length,this.run!.revision);return;
      }
      let descriptor:(OrderedSource&{expiresAtMs:number})|undefined;
      if(!prior){
        let expiresAtMs=this.session.expiresAtMs;
        if(source.kind==='speech'){
          let authority=this.deps.authority(source);
          // Acquisition has its own custody scope; media never grants speech.
          if(!authority){this.timing.record('authority_wait',first.chunk.ordinal,batch.length,this.run!.revision);return;}
          await this.deps.beforeSpeech?.(source);this.check();
          authority=this.deps.authority(source);if(!authority){this.timing.record('authority_wait',first.chunk.ordinal,batch.length,this.run!.revision);return;}
          if(authority.ticket!==this.session.ticket||authority.scope.owner!==this.session.owner
            ||authority.scope.replyId!==source.replyId||!Number.isSafeInteger(authority.scope.expiresAt)
            ||authority.scope.expiresAt<=Date.now())throw Error('ordered.reply_authority');
          expiresAtMs=Math.min(expiresAtMs,authority.scope.expiresAt);
        }
        descriptor={...source,expiresAtMs};
      }
      this.timing.record('stage_begin',first.chunk.ordinal,batch.length,this.run!.revision);
      const raw=await this.call('ncStageOrderedMuxed',{run:this.run,
        ...(prior?{sourceId:prior.id}:{descriptor}),output:batch.map(b=>b.chunk),files:batch.map(b=>b.file)});
      if(this.blocked(raw)){this.timing.record('stage_blocked',first.chunk.ordinal,batch.length,this.run!.revision);return;}
      const staged=row(raw,['kind','stageId']);if(staged.kind!=='staged'||!id(staged.stageId))throw Error('ordered.stage_ack');
      this.stage={id:staged.stageId,batch};
      this.timing.record('staged',first.chunk.ordinal,batch.length,this.run!.revision);
    }
    this.check();
    const stage=this.stage;
    this.timing.record('append_begin',stage.batch[0]!.chunk.ordinal,stage.batch.length,this.run!.revision);
    const raw=await this.call('ncAppendOrderedMuxed',{run:this.run,stageId:stage.id,
      expectedOrdinal:this.observed!.nextOrdinal,expectedRevision:this.observed!.mutationRevision});
    if(this.blocked(raw)){this.timing.record('append_blocked',stage.batch[0]!.chunk.ordinal,stage.batch.length,this.run!.revision);return;}
    const appended=row(raw,['kind','sourceId','snapshot']),snapshot=parseOrderedNativeSnapshot(appended.snapshot);
    const stagedSource=stage.batch[0]!.source;
    if(appended.kind!=='appended'||snapshot.nextOrdinal!==stage.batch.at(-1)!.chunk.ordinal+1
      ||snapshot.mutationRevision!==this.observed!.mutationRevision+1||!id(appended.sourceId)
      ||!snapshot.sources.some(s=>s.id===appended.sourceId&&s.sourceId===stagedSource.sourceId))throw Error('ordered.append_ack');
    this.stage=null;
    this.lastAppendedKind=stagedSource.kind;
    this.timing.record('appended',stage.batch[0]!.chunk.ordinal,stage.batch.length,this.run!.revision);
    if(stagedSource.replyId)this.deps.onReplyAdmitted?.(stagedSource.replyId);
    if(stagedSource.replyId&&!this.replies.has(stagedSource.replyId)){
      if(this.replies.size>=2)throw Error('ordered.reply_capacity');
      this.replies.set(stagedSource.replyId,{completed:new Set(),finalized:false});
    }
    if(!this.stopped)await this.observe(snapshot);
  }
  private blocked(value:unknown){
    if(!value||typeof value!=='object'||(value as {kind?:unknown}).kind!=='blocked')return false;
    const r=row(value,['kind','reason']);if(r.reason!=='capacity'&&r.reason!=='mutation_pending')throw Error('ordered.blocked_reason');return true;
  }
  pump():Promise<void>{
    this.pumpRequested=true;
    if(this.pumping)return this.pumping;
    const task=this.serial.then(async()=>{
      do{this.pumpRequested=false;await this.step();}while(this.pumpRequested&&!this.stopped);
    }).catch(async error=>{
      // Onset may win between read and append/prune. Consult this exact run's
      // native receipt once before classifying the rejected mutation as fatal.
      // No receipt (or any other native failure) retains the original error.
      if(!this.stopped&&this.run){try{await this.read();}catch{} }
      if(this.interruptionHandled)return;
      if(!this.stopped){this.failed=true;this.failure=error;await this.stop('failure').catch(()=>undefined);}throw error;
    }).finally(()=>{this.pumping=null;});
    // stop fences immediately; no callback waits on the task currently calling it.
    this.pumping=task;this.serial=task.catch(()=>undefined);return task;
  }
  private async step(){
    this.check();
    if(!this.run){const batch=this.deps.delivery.prefix();if(batch.length)await this.opened(batch);return;}
    await this.read();if(this.stopped||this.transportPaused)return;this.check();
    // Preparation/admission must not wait for old playlist reader joins.
    // Native still validates the current run and exact mutation revision;
    // a capacity-blocked batch remains retained and retries after pruning.
    const nextOrdinal=this.observed!.nextOrdinal;
    const batch=this.stage?.batch??this.deps.delivery.prefix();if(batch.length)await this.append(batch);
    if(this.stopped)return;this.check();
    if(this.observed!.nextOrdinal>1){
      const response=row(await this.call('ncPruneOrderedMuxed',{run:this.run,beforeOrdinal:this.observed!.nextOrdinal-1}),['kind','snapshot']);
      if(response.kind!=='joined'&&response.kind!=='pending')throw Error('ordered.prune_ack');
      await this.observe(response.snapshot);this.check();
    }
    if(batch.length&&this.observed!.nextOrdinal===nextOrdinal){
      // Acquisition can finish while prune yields. Keep an existing native
      // stage immutable, but refresh an unstaged prefix before retrying.
      const retry=this.stage?.batch??this.deps.delivery.prefix();if(retry.length)await this.append(retry);
    }
  }
  private async fence(reason:string){if(this.run&&await this.call('ncInvalidateOrderedMuxed',{run:this.run,reason})!==true)throw Error('ordered.fence_unconfirmed');}
  stop(reason:'stop'|'skip'|'replacement'|'expiry'|'recovery'|'failure'):Promise<void>{
    if(this.stopping)return this.stopping;
    this.stopped=true;const fenced=this.fence(reason);this.deps.delivery.stop();return this.stopping=fenced;
  }
  async reconcileStoppedAdmission():Promise<void>{
    if(!this.stopped)throw Error('ordered.admission_not_fenced');
    await this.stopping;await observeWait('native.serial',this.serial);
    if(!this.run)return;
    // Staging is file preparation, not a Guard grant. After the native fence
    // and in-flight mutation settle, the actual membership snapshot also proves
    // admission when an append ACK was lost. No new output is allowed here.
    const response=journalResponse(await observeWait('native.reconcile',this.call('ncReadOrderedMuxed',{run:this.run,cursor:this.cursor})));
    const snapshot=parseOrderedNativeSnapshot(response.snapshot);
    if(!sameRun(snapshot.run,this.run)||snapshot.streamId!==this.session.streamId
      ||snapshot.generation!==this.session.generation)throw Error('ordered.native_scope');
    for(const source of snapshot.sources)if(source.replyId)this.deps.onReplyAdmitted?.(source.replyId);
  }
  close():Promise<void>{
    return this.closing??=(async()=>{
      await this.stop('stop');await this.serial;
      // No cached prepare can be issued before this run's open ACK. Unpublished
      // output still uses the real whole-owner settlement in the branch below.
      if(this.run&&!this.cachedReadersJoined&&typeof this.native.ncCloseOrderedCached==='function'){
        if(await this.native.ncCloseOrderedCached.call(this.native,JSON.stringify({version:1,run:this.run}))!==true)
          throw Error('ordered.cached_reader_join_unconfirmed');
        this.cachedReadersJoined=true;
      }
      if(this.run&&this.observed){
        // A Stop during open fences again once that in-flight ACK reveals its run.
        // Remote cleanup may retry after the registered player is released.
        // Reuse only closure evidence already validated by delivery.
        if(!this.nativeCloseConfirmed)await this.fence('stop');
        const response=this.nativeCloseConfirmed?this.nativeCloseResult:await this.call('ncCloseOrderedMuxed',{run:this.run});
        await this.deps.delivery.closeAfterNative(response,this.deps.onStoppedOutput,()=>{
          this.nativeCloseResult=response;this.nativeCloseConfirmed=true;this.resolveLocal();
        });
      }else{
        // Includes a rejected or lost open ACK. Shared native cleanup confirms
        // unpublished queues, delegated readers and physical output settlement.
        await this.deps.delivery.closeAfterOwner(()=>this.nativeCloseConfirmed?Promise.resolve(true):this.native.ncCloseMuxedTrial!.call(this.native),async()=>{
          // No published native frame evidence survived this open. Only unknown
          // feedback is permitted, after whole-owner settlement, before ACKs.
          await this.deps.onStoppedOutput?.({version:1,streamId:this.session.streamId,
            generation:this.session.generation,known:false,reason:'no_rendered_frame'});
        },()=>{this.nativeCloseConfirmed=true;this.resolveLocal();});
      }
    })().catch(error=>{this.rejectLocal(error);this.closing=null;throw error;});
  }
  settleLocalForRecovery():Promise<void>{void this.close().catch(()=>undefined);return this.localClosed;}
  snapshot(){return Object.freeze({run:this.run,native:this.observed,stopped:this.stopped,failure:this.failure,openAttempted:this.openAttempted});}
}
