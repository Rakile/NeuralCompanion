import {Buffer} from 'buffer';
import type {PhoneReplyAuth} from '../api/types';
import type {PeerTransport} from '../relay/peer';
import {PeerTransportUnavailableError} from '../relay/peer';
import {parseOrderedAnnouncement,parseOrderedStoppedOutput} from './desktopOrderedProtocol';
import type {OrderedAnnouncement} from './desktopOrderedProtocol';
import type {RecoveryIntent} from './desktopOrderedRecovery';
import type {OrderedProgressReport} from './desktopOrderedProgress';
import {parseOrderedReattach} from './orderedContinuation';
import type {OrderedReattachRequest,OrderedReattachResult} from './orderedContinuation';

type Dependencies={peer():PeerTransport|null;owner:string;auth:PhoneReplyAuth;streamId:string;generation:number;
  recovery?:{intent:RecoveryIntent;confirm(result:unknown):Promise<void>};
  openCapability?:string;
  current():boolean;onAvailable(rows:readonly OrderedAnnouncement[]):boolean;onFailure(error:unknown):void;
  onInterruption?(error:unknown):boolean};
type RetainedOutput=Readonly<{generation:number;ordinal:number}>;
type RestartedOutput=Readonly<{generation:number;retained:readonly RetainedOutput[]}>;
const object=(value:unknown):Record<string,unknown>=>{
  if(!value||typeof value!=='object'||Array.isArray(value))throw Error('ordered.transport_response');
  return value as Record<string,unknown>;
};
const fields=(value:Record<string,unknown>,keys:readonly string[])=>{
  if(value.version!==1||Object.keys(value).length!==keys.length+1||keys.some(key=>!(key in value)))
    throw Error('ordered.transport_fields');
};

/** Availability is held at the server until a commit or Stop wakes it.
 * File downloads use the existing independent BufferedMediaStore. Neither
 * player readiness nor segment preparation is a condition for requesting data.
 */
export class DesktopOrderedTransport {
  private readonly auth:Readonly<{client_key:string;connection_epoch:string}>;
  private abort=new AbortController();
  private after=-1;private stopped=false;private paused=false;private failure:unknown=null;
  private opening?:Promise<void>;private running?:Promise<void>;private closing?:Promise<readonly RetainedOutput[]>;
  private halting?:Promise<void>;private restarting?:Promise<RestartedOutput>;private restartIdentity?:string;
  private revision=0;private waiter?:()=>void;
  private startedOrdinal=-1;private sentStartedOrdinal=-1;private reportingStart?:Promise<void>;
  private reportingProgress=false;private lastProgressAt=-Infinity;
  constructor(private readonly deps:Dependencies){
    if(!/^[a-f0-9]{32}$/.test(deps.streamId)||!Number.isSafeInteger(deps.generation)||deps.generation<0
      ||!deps.owner||deps.owner.length>2048||!deps.auth.client_key||!deps.auth.connection_epoch)
      throw Error('ordered.transport_scope');
    this.auth=Object.freeze({client_key:deps.auth.client_key,connection_epoch:deps.auth.connection_epoch});
  }
  private peer(cleanup=false,operation='',stage='before_request'){
    const peer=this.deps.peer();
    const failure=!peer?'missing_peer':peer.closed?'closed_peer':peer.cacheScope!==this.deps.owner?'scope_changed'
      :!cleanup&&!this.deps.current()?'runtime_not_current':null;
    if(failure)throw Object.assign(Error('ordered.transport_owner'),{orderedTransport:{
      operation,stage,condition:failure,cleanup,peer_present:!!peer,peer_closed:peer?.closed===true,
      scope_matches:!!peer&&peer.cacheScope===this.deps.owner}});
    // A missing peer always throws above; keep the diagnostic predicate centralized.
    return peer!;
  }
  private async call(method:string,body:Record<string,unknown>={},signal?:AbortSignal,cleanup=false,timeout=15000,admissionReceipt=false){
    const peer=this.peer(cleanup,method,'before_request');
    const started=Date.now();
    const request={version:1,auth:this.auth,streamId:this.deps.streamId,...body};
    // Retry only reads and exact idempotent receipts on the SAME media owner.
    // Never replay user input, grants, Stop/replacement or uncertain admission.
    const retryableMethod=['wait','started','ack'].includes(method)
      ||method==='cached'&&(body.request as {action?:unknown})?.action==='state';
    let result:Awaited<ReturnType<PeerTransport['request']>>,retryAttempt=0;
    for(;;){
      try{result=await peer.request('POST','/api/remote-output/'+method,request,timeout,signal);break;}
      catch(error){
        // This exact peer error is thrown before a request is registered or
        // sent. Waiting for a free slot cannot replay a mutation or grant.
        const busy=(error as Error)?.message==='Internet peer is busy or disconnected.';
        if(signal?.aborted)throw error;
        if(busy&&Date.now()>=started+timeout)throw Error('ordered.peer_busy');
        if(!busy&&(!retryableMethod||retryAttempt>=2
          ||!((error as Error)?.message==='NC peer request timed out.'||error instanceof PeerTransportUnavailableError)))throw error;
        if(this.peer(cleanup,method,'before_request')!==peer)throw Error('ordered.transport_peer_changed');
        await new Promise<void>((resolve,reject)=>{
          const cancelled=()=>{clearTimeout(timer);signal?.removeEventListener('abort',cancelled);reject(Error('ordered.transport_stopped'));};
          const delay=busy?Math.min(25,Math.max(1,started+timeout-Date.now())):250*2**retryAttempt++;
          const timer=setTimeout(()=>{signal?.removeEventListener('abort',cancelled);resolve();},delay);
          signal?.addEventListener('abort',cancelled,{once:true});if(signal?.aborted)cancelled();
        });
        if(this.peer(cleanup,method,'before_request')!==peer)throw Error('ordered.transport_peer_changed');
      }
    }
    // Exact admission evidence is journaled even if UI ownership ended while
    // awaiting it. Peer identity remains mandatory; this permits no playback.
    if(this.peer(cleanup||admissionReceipt,method,'after_response')!==peer)throw Error('ordered.transport_peer_changed');
    if(!result.contentType.startsWith('application/json'))throw Error('ordered.transport_content_type');
    let raw=result.body;
    if(raw===undefined&&result.bytes){
      if(result.bytes.byteLength>512*1024)throw Error('ordered.transport_response_size');
      raw=JSON.parse(Buffer.from(result.bytes).toString('utf8'));
    }
    const value=object(raw);
    if(result.status!==200){
      const reason=value.diagnosticReason;
      const legacyMissing=method==='capabilities'&&result.status===403&&value.ok===false
        &&value.error==='AV controls only.'&&Object.keys(value).every(key=>key==='ok'||key==='error');
      const error=new Error(legacyMissing?'ordered.continuation_unsupported':typeof reason==='string'&&/^(?:ordered|output|phone_reply)_[a-z_]{1,80}$/.test(reason)
        ?reason:'ordered.transport_rejected');
      Object.assign(error,{httpStatus:result.status,orderedTransport:{operation:method,stage:'after_response',
        condition:'http_rejected',cleanup,http_status:result.status,elapsed_ms:Math.max(0,Date.now()-started),
        reason_state:reason===undefined?'missing':error.message===reason?'accepted':'filtered'}});throw error;
    }
    return value;
  }
  start():Promise<void>{
    return this.opening??=(async()=>{
      if(this.stopped)throw Error('ordered.transport_stopped');
      await this.peer().negotiateBuffered();
      if(this.stopped)return;
      // Do not abort an in-flight open: its ACK is needed for exact cleanup.
      const recovery=this.deps.recovery;
      const opened=recovery?await this.admitRecovery(recovery.intent):await this.call('open',
        this.deps.openCapability?{recovery:{version:1,capability:this.deps.openCapability}}:{});
      if(!recovery)fields(opened,['streamId','generation']);
      if(opened.streamId!==this.deps.streamId||opened.generation!==this.deps.generation)
        throw Error('ordered.transport_open_scope');
      if(recovery)await recovery.confirm(opened);
      if(opened.state==='closed')throw Error('ordered.recovery_closed');
      if(!this.stopped&&!this.deps.current())throw Error('ordered.recovery_owner');
      if(!this.stopped){this.running=this.receive();void this.running.catch(error=>this.fail(error));}
    })().catch(error=>{if(!this.stopped)this.fail(error);throw error;});
  }
  /** Also used to settle a persisted prior admission before a fresh runtime.
   * It never starts acquisition or creates native output. */
  async admitRecovery(intent:RecoveryIntent):Promise<Record<string,unknown>>{
    if(intent.streamId!==this.deps.streamId||this.deps.generation!==0)throw Error('ordered.recovery_scope');
    const deadline=Date.now()+30000;let attempt=0,result:Record<string,unknown>;
    for(;;){
      try{
        result=await this.call(intent.kind==='open'?'open':'recover',{
          recovery:intent.kind==='open'?{version:1,capability:intent.capability}:intent.recovery},undefined,false,
          Math.max(1,Math.min(15000,deadline-Date.now())),true);break;
      }catch(error){
        const reason=(error as Error)?.message;
        const retryable=reason==='ordered_recovery_join_pending'||reason==='ordered_recovery_stop_pending'
          ||reason==='NC peer request timed out.'||(error as {httpStatus?:number})?.httpStatus===503;
        if(!retryable||this.stopped||!this.deps.current())throw error;
        if(Date.now()>=deadline)throw Error(reason==='NC peer request timed out.'?'ordered_recovery_transport_pending':reason);
        await new Promise<void>(resolve=>setTimeout(resolve,Math.min(500*2**Math.min(attempt++,2),deadline-Date.now())));
        if(this.stopped||!this.deps.current())throw Error('ordered.recovery_owner');
      }
    }
    fields(result,intent.kind==='open'?['streamId','generation']:['streamId','generation','state','operationId']);
    if(result.streamId!==intent.streamId||result.generation!==0||intent.kind==='recover'
      &&(!['recovered','closed'].includes(result.state as string)||result.operationId!==intent.recovery.operationId))throw Error('ordered.recovery_response');
    return result;
  }
  private fail(error:unknown){
    if(this.stopped||this.paused)return;
    if(this.deps.onInterruption?.(error))return;
    this.failure=error;this.stop();
    try{this.deps.onFailure(error);}catch{} // Observation cannot replace first cause.
  }
  private async receive(){
    while(!this.stopped&&!this.paused){
      const response=await this.call('wait',{afterOrdinal:this.after,generation:this.deps.generation},this.abort.signal);
      if(this.stopped||this.paused)return;
      fields(response,['state','failure','announcements']);
      if(response.state!=='open'||response.failure!==null){
        const failure=response.failure?object(response.failure):null;
        const reason=failure?.reason;
        throw Error(typeof reason==='string'&&/^(?:ordered|output|phone_reply)_[a-z_]{1,80}$/.test(reason)
          ?reason:'ordered.transport_backend_closed');
      }
      if(!Array.isArray(response.announcements)||response.announcements.length>60)
        throw Error('ordered.transport_batch');
      const rows=Object.freeze(response.announcements.map(parseOrderedAnnouncement));
      let after=this.after;
      for(const {chunk} of rows){
        if(chunk.streamId!==this.deps.streamId||chunk.generation!==this.deps.generation)
          throw Error('ordered.transport_generation');
        if(chunk.ordinal!==++after)throw Error('ordered.transport_gap');
      }
      if(!rows.length)continue;
      while(!this.stopped&&!this.paused){
        const revision=this.revision;
        if(this.deps.onAvailable(rows)){this.after=after;break;}
        await new Promise<void>(resolve=>{
          if(this.stopped||this.revision!==revision)resolve();else this.waiter=resolve;
        });
      }
    }
  }
  wake(){this.revision++;const waiter=this.waiter;this.waiter=undefined;waiter?.();}
  /** Stop only transport workers. Keep admission, cursor and native custody. */
  async suspend():Promise<void>{
    if(this.stopped)return;
    this.paused=true;this.abort.abort();this.wake();
    await Promise.all([this.running?.catch(()=>undefined),this.reportingStart?.catch(()=>undefined)]);
  }
  resume():void{
    if(this.stopped)throw Error('ordered.transport_stopped');
    if(!this.paused)return;
    this.paused=false;this.abort=new AbortController();
    this.running=this.receive();void this.running.catch(error=>this.fail(error));
    if(this.startedOrdinal>this.sentStartedOrdinal)this.idleStarted(this.startedOrdinal);
  }
  async continuationCapabilities(signal:AbortSignal):Promise<boolean>{
    let value:Record<string,unknown>;
    try{value=await this.call('capabilities',{generation:this.deps.generation},signal);}
    catch(error){if((error as {httpStatus?:number})?.httpStatus===404
      ||(error as Error)?.message==='ordered.continuation_unsupported')return false;throw error;}
    fields(value,['orderedContinuationVersion']);
    if(!Number.isSafeInteger(value.orderedContinuationVersion)||(value.orderedContinuationVersion as number)<0)
      throw Error('ordered.continuation_capabilities');
    return value.orderedContinuationVersion===1;
  }
  async reattach(request:OrderedReattachRequest,signal?:AbortSignal):Promise<OrderedReattachResult>{
    if(request.version!==1||request.streamId!==this.deps.streamId||request.generation!==this.deps.generation
      ||request.auth.client_key!==this.auth.client_key||request.auth.connection_epoch!==this.auth.connection_epoch
      ||request.afterOrdinal!==this.after)throw Error('ordered.continuation_reattach_scope');
    const response=await this.call('reattach',{generation:request.generation,operationId:request.operationId,
      recoveryEpoch:request.recoveryEpoch,capability:request.capability,afterOrdinal:request.afterOrdinal},signal);
    if(signal?.aborted)throw Error('ordered.transport_paused');
    return parseOrderedReattach(response,request);
  }
  cached(request:Record<string,unknown>):Promise<unknown>{
    if(this.paused)return Promise.reject(Error('ordered.transport_paused'));
    return this.call('cached',{generation:this.deps.generation,request});
  }
  /** UI observation only. At most one request/second and one in flight, no backlog,
   * native RPC, retry timer, receipt or effect on acquisition/playback failure. */
  reportProgress(progress:OrderedProgressReport|null,now=Date.now()):void{
    if(!progress||this.stopped||this.paused||!this.deps.current()||this.reportingProgress||now-this.lastProgressAt<1000)return;
    this.lastProgressAt=now;this.reportingProgress=true;
    void this.call('progress',{generation:this.deps.generation,progress},this.abort.signal,false,2000)
      .catch(()=>undefined).finally(()=>{this.reportingProgress=false;});
  }
  /** Playback progress only: never download readiness, authority or custody.
   * Coalesce behind one request without blocking native pumping or Stop. */
  idleStarted(ordinal:number):void{
    if(this.stopped)return;
    if(!Number.isSafeInteger(ordinal)||ordinal<0||ordinal>this.after)throw Error('ordered.transport_progress');
    this.startedOrdinal=Math.max(this.startedOrdinal,ordinal);
    if(this.paused)return;
    if(this.reportingStart||this.startedOrdinal<=this.sentStartedOrdinal)return;
    this.reportingStart=(async()=>{
      while(!this.stopped&&!this.paused&&this.sentStartedOrdinal<this.startedOrdinal){
        const ordinal=this.startedOrdinal;
        const response=await this.call('started',{generation:this.deps.generation,ordinal},this.abort.signal);
        if(this.stopped||this.paused)return;
        fields(response,['accepted']);if(response.accepted!==true)throw Error('ordered.transport_progress_ack');
        this.sentStartedOrdinal=ordinal;
      }
    })().catch(error=>this.fail(error)).finally(()=>{
      this.reportingStart=undefined;
      if(!this.stopped&&!this.paused&&this.startedOrdinal>this.sentStartedOrdinal)this.idleStarted(this.startedOrdinal);
    });
  }
  async release(ordinal:number){
    if(!Number.isSafeInteger(ordinal)||ordinal<0)throw Error('ordered.transport_release');
    if(this.paused&&!this.stopped)throw Error('ordered.transport_paused');
    const result=await this.call('ack',{generation:this.deps.generation,ordinal,readersClosed:true},undefined,true);
    fields(result,['released']);if(result.released!==true)throw Error('ordered.transport_release_ack');
    this.wake();
  }
  stop(){this.stopped=true;this.abort.abort();this.wake();}
  halt():Promise<void>{
    return this.halting??=(async()=>{
      this.stop();await this.opening?.catch(()=>undefined);
      const response=await this.call('halt',{generation:this.deps.generation},undefined,true);
      fields(response,['state','generation']);
      if(response.state!=='halted'||response.generation!==this.deps.generation)
        throw Error('ordered.transport_halt_ack');
    })().catch(error=>{this.halting=undefined;throw error;});
  }
  restart(value:unknown):Promise<RestartedOutput>{
    try{
      const stopped=parseOrderedStoppedOutput(value);
      if(stopped.streamId!==this.deps.streamId||stopped.generation!==this.deps.generation
        ||stopped.known&&stopped.ordinal>this.after)throw Error('ordered.transport_stopped_scope');
      const identity=JSON.stringify(stopped);
      if(this.closing||this.restartIdentity!==undefined&&this.restartIdentity!==identity)
        throw Error('ordered.transport_restart_changed');
      this.restartIdentity=identity;
      return this.restarting??=(async()=>{
        await this.halt();await this.running?.catch(()=>undefined);
        const response=await this.call('restart',{stoppedOutput:stopped},undefined,true);
        fields(response,['state','streamId','generation','retained']);
        if(response.state!=='restarted'||response.streamId!==this.deps.streamId
          ||response.generation!==this.deps.generation+1||!Number.isSafeInteger(response.generation))
          throw Error('ordered.transport_restart_ack');
        return Object.freeze({generation:response.generation as number,retained:this.retained(response.retained)});
      })().catch(error=>{this.restarting=undefined;throw error;});
    }catch(error){return Promise.reject(error);}
  }
  private retained(value:unknown):readonly RetainedOutput[]{
    if(!Array.isArray(value)||value.length>60)throw Error('ordered.transport_close_ack');
    let ordinal=-1;
    return Object.freeze(value.map(value=>{
      const row=object(value);
      if(Object.keys(row).length!==2||row.generation!==this.deps.generation
        ||!Number.isSafeInteger(row.ordinal)||(row.ordinal as number)<=ordinal)
        throw Error('ordered.transport_close_custody');
      ordinal=row.ordinal as number;
      return Object.freeze({generation:this.deps.generation,ordinal});
    }));
  }
  close():Promise<readonly RetainedOutput[]>{
    return this.closing??=(async()=>{
      this.stop();await this.opening?.catch(()=>undefined);
      await this.running?.catch(()=>undefined);
      // Replacement has its own lifetime. Old cleanup only owns old custody.
      if(this.restarting)return (await this.restarting).retained;
      const response=await this.call('close',{generation:this.deps.generation},undefined,true);
      fields(response,['state','retained']);
      if(response.state!=='closed')throw Error('ordered.transport_close_ack');
      return this.retained(response.retained);
    })().catch(error=>{this.closing=undefined;throw error;});
  }
  snapshot(){return Object.freeze({afterOrdinal:this.after,stopped:this.stopped,paused:this.paused,failure:this.failure});}
}
