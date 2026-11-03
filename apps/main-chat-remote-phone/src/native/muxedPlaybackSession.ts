import type {AudioChunk,PhoneReplyStatus} from '../api/types';
import type {MuxedTrialRuntime} from '../dev/muxedTrialRuntime';
import type {ContinuousBufferedAudio,RunHandle} from '../dev/muxedContinuousProtocol';
import {PhoneHandoffSession} from '../utils/phonePresentation';
import type {PhonePresentationPosition,HandoffExchange} from '../utils/phonePresentation';
import {IdleDiagnosticTrace} from '../diagnostics/idleTrace';

export type MuxedEpochState={expiresAt:number;speechDeparted:boolean;finalVisualStarted:boolean};
type Runtime=Pick<MuxedTrialRuntime,'phase'|'player'|'startupStage'|'streamsChunks'|'audio'|'start'|'tick'
  |'subscribe'|'update'|'observeReplyStatus'|'close'|'finished'|'drained'|'readIdlePosition'|'proposeIdleWaitingBoundary'|'abandonIdleWaitingBoundary'>&{readonly epochState:MuxedEpochState;observeEpochExpiry?(now:number,deadline:number):void};
type Reply={id:string;chunks:Map<string,AudioChunk>;status?:{value:PhoneReplyStatus;reconciled:boolean}};
type Epoch={runtime:Runtime;reply?:Reply;retiring:boolean;started:boolean;unsubscribe:()=>void};
const sourceIdentity=(chunk:AudioChunk)=>JSON.stringify([chunk.id,chunk.phone_request_id,
  chunk.sequence_index,chunk.url_path,chunk.playback_recovery_epoch??0]);
type WaitingPlan=Parameters<PhoneHandoffSession['claim']>[0];
type Dependencies={current():boolean;createRuntime(context:{current():boolean;claimWaitingPlan(plan:WaitingPlan):boolean}):Runtime;
  canRetireReply(requestId:string):boolean;retireVisualCarrier():Promise<void>;now?():number;ready?():Promise<void>};

/** Normal session boundary. Native speech runs and their receipts are never
 * reused for another reply; only this facade survives confirmed retirement. */
export class MuxedPlaybackSession {
  private active?:Epoch;
  private closed=false;
  private failure?:unknown;
  private serial:Promise<void>=Promise.resolve();
  private opening?:Promise<void>;
  private closing?:Promise<void>;
  private readonly pending=new Map<string,Reply>();
  private readonly retired=new Set<string>();
  private readonly listeners=new Set<()=>void>();
  private readonly runs=new Map<string,Epoch>();
  private readonly claimDiagnostics=new IdleDiagnosticTrace();
  private readonly handoff=new PhoneHandoffSession(()=>this.readIdlePosition(),()=>{},
    ()=>this.active?.runtime.proposeIdleWaitingBoundary()??null,()=>this.active?.runtime.abandonIdleWaitingBoundary(),
    row=>this.claimDiagnostics.claimRejected(row),row=>this.claimDiagnostics.handoffObserved(row));
  readonly audio:MuxedTrialRuntime['audio'];
  constructor(private readonly deps:Dependencies){
    const run=(handle:RunHandle)=>{
      const epoch=this.runs.get(`${handle.id}:${handle.revision}`);
      if(!epoch)throw Error('Muxed run epoch unavailable.');
      return epoch.runtime.audio.continuous!;
    };
    const continuous:ContinuousBufferedAudio={
      candidate:(tail,next)=>run(tail.source.run).candidate(tail,next),
      finalReturn:tail=>run(tail.source.run).finalReturn(tail),
      appendSource:(tail,...args)=>run(tail.source.run).appendSource(tail,...args),
      subscribe:(handle,wake)=>run(handle).subscribe(handle,wake),
      read:(handle,cursor)=>run(handle).read(handle,cursor),
      acknowledge:(handle,cursor)=>run(handle).acknowledge(handle,cursor),
      onApplied:event=>run(event.run).onApplied(event),
      onDrained:snapshot=>run(snapshot.run).onDrained?.(snapshot)??Promise.resolve(),
      sealTail:tail=>run(tail.source.run).sealTail(tail),
      retireSource:source=>run(source.run).retireSource(source),
      retireRun:handle=>run(handle).retireRun(handle),
      invalidate:(handle,reason)=>run(handle).invalidate(handle,reason),
    };
    this.audio={deferNativePreparation:true,continuousRequired:true,continuous,
      acquire:async(chunk,signal)=>{
        this.appendReplyMedia(chunk.phone_request_id??'',[chunk]);
        const epoch=await this.waitForEpoch(chunk,signal);
        return epoch.runtime.audio.acquire(chunk,signal);
      },
      owns:(chunk,uri)=>this.epochFor(chunk)?.runtime.audio.owns(chunk,uri)===true,
      createPlayer:async(chunk,...args)=>{
        const signal=args[2],epoch=await this.waitForEpoch(chunk,signal);
        const result=await epoch.runtime.audio.createPlayer(chunk,...args);
        if(this.active!==epoch||epoch.retiring||!this.current())throw Error('Muxed source epoch ended.');
        if(!result.continuous)throw Error('Current continuous muxed source required.');
        const handle=result.continuous.run;
        this.runs.set(`${handle.id}:${handle.revision}`,epoch);return result;
      }};
  }
  get runtime(){return this.active?.runtime;}
  get phase(){return this.failure?'failed':this.runtime?.phase??'off';}
  readIdlePosition():PhonePresentationPosition|null{
    const epoch=this.active;
    return this.current()&&epoch&&!epoch.retiring?epoch.runtime.readIdlePosition():null;
  }
  handoffExchange():HandoffExchange|null{
    if(!this.readIdlePosition()){this.handoff.clear('position_missing');return null;}
    const epoch=this.active!,exchange=this.handoff.exchange();
    return {payload:exchange.payload,accept:response=>{
      const reason=!this.current()?'session_ended':this.active!==epoch?'epoch_changed'
        :epoch.retiring?'epoch_retiring':!this.readIdlePosition()?'accept_position_missing':null;
      if(reason)this.claimDiagnostics.handoffObserved({reason,expected:true,actual:false});
      else exchange.accept(response);
    }};
  }
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
  private changed(){for(const listener of this.listeners)listener();}
  private current(){return !this.closed&&!this.failure&&this.deps.current();}
  private check(){if(this.failure)throw this.failure;if(!this.current())throw Error('Muxed session owner ended.');}
  private enqueue(work:()=>Promise<void>):Promise<void>{
    const result=this.serial.then(work);
    this.serial=result.catch(error=>{
      // An explicit owner replacement/Stop cancels old work, not its reader
      // joins. Only a live epoch failure becomes a terminal session failure.
      if(!this.closed&&this.deps.current())this.failure??=error;
      this.changed();
    });return result;
  }
  start():Promise<void>{return this.opening??=this.enqueue(()=>this.pump());}
  beforeReply():Promise<void>{
    return new Promise((resolve,reject)=>{
      const wake=()=>{try{
        this.check();const epoch=this.active;
        if(epoch?.started&&!epoch.retiring&&!epoch.reply&&this.pending.size===0){unsubscribe();resolve();}
      }catch(error){unsubscribe();reject(error);}};
      const unsubscribe=this.subscribe(wake);
      // Use the same serialized retirement/startup chain as playback, not a
      // second owner or a readiness flag inferred from a completed reply.
      void this.enqueue(()=>this.pump()).then(wake,error=>{unsubscribe();reject(error);});
    });
  }
  private epochFor(chunk:AudioChunk):Epoch|undefined {
    const epoch=this.active;
    return epoch&&!epoch.retiring&&epoch.reply&&epoch.reply.id===chunk.phone_request_id
      &&epoch.reply.chunks.has(chunk.id)?epoch:undefined;
  }
  private waitForEpoch(chunk:AudioChunk,signal:AbortSignal):Promise<Epoch>{
    return new Promise((resolve,reject)=>{
      const done=()=>{unsubscribe();signal.removeEventListener('abort',wake);};
      const wake=()=>{try{
        this.check();if(signal.aborted)throw Error('Muxed acquisition cancelled.');
        if(this.retired.has(chunk.phone_request_id??''))throw Error('Muxed reply epoch retired.');
        const epoch=this.epochFor(chunk);if(epoch){done();resolve(epoch);}
      }catch(error){done();reject(error);}};
      const unsubscribe=this.subscribe(wake);signal.addEventListener('abort',wake);wake();
    });
  }
  appendReplyMedia(requestId:string,chunks:readonly AudioChunk[]):void {
    try{this.admitReplyMedia(requestId,chunks);}catch(error){
      this.failure??=error;this.changed();void this.close().catch(()=>undefined);throw error;
    }
  }
  private admitReplyMedia(requestId:string,chunks:readonly AudioChunk[]):void {
    this.check();
    if(!requestId||chunks.some(chunk=>chunk.phone_request_id!==requestId))throw Error('Invalid muxed reply manifest.');
    if(this.retired.has(requestId))return;
    let reply=this.active?.reply?.id===requestId?this.active.reply:this.pending.get(requestId);
    if(!reply){reply={id:requestId,chunks:new Map()};this.pending.set(requestId,reply);}
    const unique=new Set([...reply.chunks.keys(),...chunks.map(chunk=>chunk.id)]);
    const other=[...this.pending.values()].filter(row=>row!==reply).reduce((sum,row)=>sum+row.chunks.size,0);
    if(unique.size+other>64)throw Error('Muxed reply manifest capacity exceeded.');
    for(const chunk of chunks){
      const old=reply.chunks.get(chunk.id);
      if(old&&sourceIdentity(old)!==sourceIdentity(chunk))throw Error('Muxed reply source changed.');
      reply.chunks.set(chunk.id,{...chunk});
    }
    if(this.active?.reply===reply&&!this.active.retiring)this.active.runtime.update(chunks);
    void this.enqueue(()=>this.pump()).catch(()=>undefined);
  }
  restoreReplyMedia(requestId:string,chunks:readonly AudioChunk[]):void {
    if(chunks.length&&!chunks.some(chunk=>chunk.sequence_index===0))throw Error('Muxed recovery requires a fresh source epoch.');
    this.appendReplyMedia(requestId,chunks);
  }
  observeReplyStatus(requestId:string,status:PhoneReplyStatus,pagesReconciled:boolean):void {
    if(this.retired.has(requestId)||!this.current())return;
    const reply=this.active?.reply?.id===requestId?this.active.reply:this.pending.get(requestId);
    if(!reply||status.phone_request_id!==requestId)return;
    reply.status={value:status,reconciled:pagesReconciled};
    if(this.active?.reply===reply&&!this.active.retiring)this.active.runtime.observeReplyStatus(requestId,status,pagesReconciled);
  }
  private async retire(epoch:Epoch){
    epoch.retiring=true;this.changed();
    // The queue's actor/leases and the runtime's idle/source readers are two
    // distinct closure chains. Failure of either prevents successor creation.
    await this.deps.retireVisualCarrier();
    await epoch.runtime.close();epoch.unsubscribe();
    this.handoff.clear('epoch_retired');
    if(epoch.reply){this.retired.add(epoch.reply.id);if(this.retired.size>128)this.retired.delete(this.retired.values().next().value!);}
    for(const [id,row] of this.runs)if(row===epoch)this.runs.delete(id);
    if(this.active===epoch)this.active=undefined;
  }
  private async pump(){
    await this.deps.ready?.();this.check();let epoch=this.active;
    const now=this.deps.now?.()??Date.now(),state=epoch?.runtime.epochState;
    const completed=!!epoch?.reply&&state?.speechDeparted===true&&state.finalVisualStarted
      &&this.deps.canRetireReply(epoch.reply.id);
    const idle=!!epoch&&(!epoch.reply||completed);
    if(epoch&&state&&now>=state.expiresAt){
      try{epoch.runtime.observeEpochExpiry?.(now,state.expiresAt);}catch{} // Observation cannot replace the guard failure.
      throw Error('Muxed epoch authority expired.');
    }
    if(epoch&&idle&&(completed||state&&now>=state.expiresAt-2000)){
      await this.retire(epoch);this.check();epoch=undefined;
    }
    if(!epoch){
      const next:Epoch={runtime:null!,retiring:false,started:false,unsubscribe:()=>{}};
      const current=()=>this.current()&&this.active===next&&!next.retiring;
      next.runtime=this.deps.createRuntime({current,claimWaitingPlan:plan=>current()&&this.handoff.claim(plan)});
      this.active=epoch=next;next.unsubscribe=next.runtime.subscribe(()=>this.changed());
      await next.runtime.start();this.check();if(this.active!==next)throw Error('Muxed epoch startup ended.');
      next.started=true;
    }
    if(!epoch.reply&&this.pending.size){
      const reply=this.pending.values().next().value!;this.pending.delete(reply.id);epoch.reply=reply;
      epoch.runtime.update([...reply.chunks.values()]);
      if(reply.status)epoch.runtime.observeReplyStatus(reply.id,reply.status.value,reply.status.reconciled);
    }
    this.changed();
  }
  tick():Promise<void>{return this.enqueue(async()=>{await this.pump();this.check();await this.active!.runtime.tick();});}
  finished=(...args:Parameters<MuxedTrialRuntime['finished']>)=>{this.epochFor(args[0])?.runtime.finished(...args);};
  drained=(...args:Parameters<MuxedTrialRuntime['drained']>)=>{this.epochFor(args[0])?.runtime.drained(...args);};
  close():Promise<void>{
    if(this.closing)return this.closing;
    this.closed=true;this.changed();
    return this.closing=(async()=>{
      const epoch=this.active;
      if(epoch?.retiring){
        await this.serial;
        // A failed join cannot be converted into successful file release by
        // later teardown. Its still-retiring epoch retains its leases.
        if(this.failure)throw this.failure;
      }else if(epoch){
        // Start retirement now: runtime.close aborts an outstanding startup.
        // Waiting for serial first would make Stop depend on network readiness.
        await this.retire(epoch);
      }
      await this.serial;
      this.pending.clear();this.changed();
      if(this.failure)throw this.failure;
    })();
  }
}
