import type {PhoneReplyAuth} from '../api/types';
import type {OrderedRun} from './desktopOrderedProtocol';
import type {ContinuationAdapter} from '../utils/continuationRecovery';
import {PeerTransportUnavailableError} from '../relay/peer';

export type OrderedContinuationSnapshot=Readonly<{version:1;checkpointId:string;streamId:string;generation:number;
  run:OrderedRun;recoveryEpoch:number;state:'buffered'|'paused'|'resumed'|'cancelled';
  position:Readonly<{ordinal:number;frameOffset:number;consumedSamples:number}>|null;
  publishedCursor:number;acknowledgedCursor:number}>;
export type OrderedReattachRequest=Readonly<{version:1;auth:Readonly<Pick<PhoneReplyAuth,'client_key'|'connection_epoch'>>;
  streamId:string;generation:number;operationId:string;recoveryEpoch:number;capability:string;afterOrdinal:number}>;
export type OrderedReattachResult=Readonly<{version:1;state:'reattached';streamId:string;generation:number;
  operationId:string;recoveryEpoch:number}>;
type NativeScope=Readonly<{ticket:string;streamId:string;generation:number;run:OrderedRun}>;
type Checkpoint={native:OrderedContinuationSnapshot;scope:NativeScope;request:OrderedReattachRequest};
export type OrderedContinuationCheckpoint=Checkpoint;
const integer=(value:unknown,low=0):value is number=>Number.isSafeInteger(value)&&(value as number)>=low;
const hex=(value:unknown,n:number):value is string=>typeof value==='string'&&new RegExp(`^[a-f0-9]{${n}}$`).test(value);
function fields(value:unknown,keys:readonly string[]):Record<string,unknown>{
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==keys.length
    ||keys.some(key=>!Object.prototype.hasOwnProperty.call(value,key)))throw Error('ordered.continuation_fields');
  return value as Record<string,unknown>;
}
export function parseOrderedContinuation(value:unknown):OrderedContinuationSnapshot{
  const row=fields(value,['version','checkpointId','streamId','generation','run','recoveryEpoch','state','position','publishedCursor','acknowledgedCursor']);
  const run=fields(row.run,['id','revision']);
  if(row.version!==1||!hex(row.checkpointId,32)||!hex(row.streamId,32)||!integer(row.generation)
    ||!integer(row.recoveryEpoch,1)||typeof run.id!=='string'||!/^[A-Za-z0-9_.-]{1,128}$/.test(run.id)
    ||!integer(run.revision,1)||!integer(row.publishedCursor)||!integer(row.acknowledgedCursor)
    ||row.acknowledgedCursor>row.publishedCursor||!['buffered','paused','resumed','cancelled'].includes(row.state as string))
    throw Error('ordered.continuation_shape');
  let position:OrderedContinuationSnapshot['position']=null;
  if(row.position!==null){
    const p=fields(row.position,['ordinal','frameOffset','consumedSamples']);
    if(!integer(p.ordinal)||!integer(p.frameOffset)||p.frameOffset>11||!integer(p.consumedSamples))
      throw Error('ordered.continuation_position');
    position=Object.freeze({ordinal:p.ordinal,frameOffset:p.frameOffset,consumedSamples:p.consumedSamples});
  }
  if(row.state==='paused'&&!position||row.state==='buffered'&&position)throw Error('ordered.continuation_position');
  return Object.freeze({version:1,checkpointId:row.checkpointId,streamId:row.streamId,generation:row.generation,
    run:Object.freeze({id:run.id,revision:run.revision}),recoveryEpoch:row.recoveryEpoch,
    state:row.state as OrderedContinuationSnapshot['state'],position,
    publishedCursor:row.publishedCursor,acknowledgedCursor:row.acknowledgedCursor});
}
export function parseOrderedReattach(value:unknown,expected:OrderedReattachRequest):OrderedReattachResult{
  const row=fields(value,['version','state','streamId','generation','operationId','recoveryEpoch']);
  if(row.version!==1||row.state!=='reattached'||row.streamId!==expected.streamId||row.generation!==expected.generation
    ||row.operationId!==expected.operationId||row.recoveryEpoch!==expected.recoveryEpoch)throw Error('ordered.continuation_reattach');
  return Object.freeze({...row}) as OrderedReattachResult;
}
export function orderedTransportInterrupted(error:unknown):boolean{
  const value=error as Error&{orderedTransport?:{condition?:string}};
  return error instanceof PeerTransportUnavailableError||value?.message==='NC peer request timed out.'
    ||value?.message==='ordered.transport_peer_changed'||value?.message==='ordered.transport_paused'
    ||value?.message==='ordered.transport_owner'&&['missing_peer','closed_peer'].includes(value.orderedTransport?.condition??'');
}
type Dependencies={auth:PhoneReplyAuth;capability:string;scope():NativeScope|null;afterOrdinal():number;operationId():string;
  current():boolean;pauseDelivery():Promise<void>;resumeDelivery():Promise<void>;
  native(method:string,request:Record<string,unknown>):Promise<unknown>;
  capabilities(signal:AbortSignal):Promise<boolean>;reattach(request:OrderedReattachRequest,signal:AbortSignal):Promise<OrderedReattachResult>;
  cancel(reason:string,error?:unknown):Promise<void>;observe(stage:string,epoch:number,outcome:string,details:Record<string,unknown>):void;
  schedule(retry:()=>void):()=>void};
/** Shared-supervisor adapter only: all positions and output effects stay native. */
export class OrderedContinuationAdapter implements ContinuationAdapter<Checkpoint>{
  private epoch=0;private failure:unknown;private evidence?:Checkpoint;
  constructor(private readonly deps:Dependencies){}
  private current(signal:AbortSignal){if(signal.aborted||!this.deps.current())throw Error('ordered.continuation_superseded');}
  private request(scope:NativeScope,epoch:number,checkpointId?:string){
    return {...scope,recoveryEpoch:epoch,...(checkpointId?{checkpointId}:{})};
  }
  private checkNative(raw:unknown,scope:NativeScope,epoch:number,id?:string){
    const value=parseOrderedContinuation(raw);
    if(value.streamId!==scope.streamId||value.generation!==scope.generation||value.recoveryEpoch!==epoch
      ||value.run.id!==scope.run.id||value.run.revision!==scope.run.revision||id&&value.checkpointId!==id
      ||value.state==='cancelled')throw Error('ordered.continuation_native_scope');
    return value;
  }
  async suspend(epoch:number,signal:AbortSignal):Promise<Checkpoint>{
    this.epoch=epoch;this.failure=undefined;this.evidence=undefined;
    try {
    this.current(signal);const scope=this.deps.scope();if(!scope)throw Error('ordered.continuation_not_open');
    const paused=this.deps.pauseDelivery();
    void paused.catch(()=>undefined);
    const native=this.checkNative(await this.deps.native('ncSuspendOrderedTransport',this.request(scope,epoch)),scope,epoch);
    await paused;this.current(signal);
    const operationId=this.deps.operationId(),afterOrdinal=this.deps.afterOrdinal();
    if(!hex(operationId,32)||!hex(this.deps.capability,64)||!integer(afterOrdinal,-1))throw Error('ordered.continuation_proof');
    return this.evidence={native,scope,request:Object.freeze({version:1,auth:Object.freeze({client_key:this.deps.auth.client_key,
      connection_epoch:this.deps.auth.connection_epoch}),streamId:scope.streamId,generation:scope.generation,
      operationId,recoveryEpoch:epoch,capability:this.deps.capability,afterOrdinal})};
    } catch(error){if(this.epoch===epoch&&!signal.aborted)this.failure=error;throw error;}
  }
  async validate(checkpoint:Checkpoint,epoch:number,signal:AbortSignal):Promise<void>{
    try {
    this.current(signal);
    if(epoch!==checkpoint.request.recoveryEpoch)throw Error('ordered.continuation_superseded');
    if(!await this.deps.capabilities(signal))throw Error('ordered.continuation_unsupported');
    this.current(signal);
    await this.deps.reattach(checkpoint.request,signal);this.current(signal);
    checkpoint.native=this.checkNative(await this.deps.native('ncReadOrderedContinuation',
      this.request(checkpoint.scope,epoch,checkpoint.native.checkpointId)),checkpoint.scope,epoch,checkpoint.native.checkpointId);
    this.current(signal);
    } catch(error){if(this.epoch===epoch&&!signal.aborted)this.failure=error;throw error;}
  }
  async resume(checkpoint:Checkpoint,epoch:number,signal:AbortSignal):Promise<void>{
    try {
    this.current(signal);
    const value=this.checkNative(await this.deps.native('ncResumeOrderedTransport',
      this.request(checkpoint.scope,epoch,checkpoint.native.checkpointId)),checkpoint.scope,epoch,checkpoint.native.checkpointId);
    this.current(signal);if(value.state!=='resumed')throw Error('ordered.continuation_resume');
    checkpoint.native=value;
    await this.deps.resumeDelivery();this.current(signal);
    } catch(error){if(this.epoch===epoch&&!signal.aborted)this.failure=error;throw error;}
  }
  cancel=(reason:string)=>this.deps.cancel(reason,this.failure);
  observe=(stage:string,epoch:number,outcome:string)=>{
    const checkpoint=this.evidence?.request.recoveryEpoch===epoch?this.evidence:undefined;
    const scope=checkpoint?.scope??this.deps.scope(),native=checkpoint?.native;
    this.deps.observe(stage,epoch,outcome,{stream_id:scope?.streamId,generation:scope?.generation,run_id:scope?.run.id,
      checkpoint_id:native?.checkpointId,native_state:native?.state,published_cursor:native?.publishedCursor,
      acknowledged_cursor:native?.acknowledgedCursor,after_ordinal:checkpoint?.request.afterOrdinal,
      operation_id:checkpoint?.request.operationId,ordinal:native?.position?.ordinal,
      frame_offset:native?.position?.frameOffset,consumed_samples:native?.position?.consumedSamples,
      reason:this.epoch===epoch?(this.failure as Error)?.message:undefined});
  };
  retryable=(error:unknown)=>orderedTransportInterrupted(error)||(error as {httpStatus?:number})?.httpStatus===503;
  schedule=(retry:()=>void)=>this.deps.schedule(retry);
}
import type {RemoteClient} from '../api/client';

/** Inventory owns verified bytes across peer replacement, not a captured HTTP
 * wrapper. Preserve its scope through a gap; never transfer on an unverified
 * or different Desktop, and never manufacture availability for partial files. */
export function orderedInventoryTransport(client:()=>RemoteClient,current:()=>boolean){
  const scope=client().idleCacheScope;
  const selected=()=>{
    const target=client();
    if(!current()||!scope||target.idleCacheScope!==scope)throw Error('ordered.inventory_transport');
    return target;
  };
  return {
    get idleCacheScope(){const now=client().idleCacheScope;return current()&&(!now||now===scope)?scope:'';},
    async idleCacheManifest(...args:Parameters<RemoteClient['idleCacheManifest']>){return selected().idleCacheManifest(...args);},
    async idleCacheRange(...args:Parameters<RemoteClient['idleCacheRange']>){return selected().idleCacheRange(...args);},
  };
}

