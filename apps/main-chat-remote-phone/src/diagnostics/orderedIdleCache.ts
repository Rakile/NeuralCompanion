import {DiagnosticEmitter} from './emitter';
import {enqueueDiagnostic,emergencyDiagnostic} from './bridgeSink';
import {siteEnabled} from './policy';
import type {OrderedCacheEvent} from '../dev/orderedChunkStore';

export function orderedCacheFailure(error:unknown):string {
  return String(error).match(/\bordered_idle_cache_[a-z_]+\b/)?.[0]
    ??String(error).match(/\b(?:ENOSPC|EACCES|EIO)\b/)?.[0]??'native_io_failed';
}
/** Aggregate accounting stays cheap with detailed acquisition logs disabled. */
export class OrderedIdleCacheDiagnostics {
  private hits=0;private misses=0;private savedBytes=0;private emitter?:DiagnosticEmitter;
  record=(event:OrderedCacheEvent)=>{
    if(event.phase==='hit'){this.hits++;this.savedBytes=Math.min(Number.MAX_SAFE_INTEGER,this.savedBytes+event.bytes);}
    if(event.phase==='miss')this.misses++;
    const failed=event.phase.endsWith('_failed'),level=failed?'warning':'debug';
    if(!siteEnabled('phone.media.idle_cache',level))return;
    this.emitter??=new DiagnosticEmitter({component:'phone.js',build_id:null,build_unavailable_reason:'not_available',
      clock_id:'phone-performance',enqueue:enqueueDiagnostic,emergency:emergencyDiagnostic});
    this.emitter.emit({event_name:'transaction.operation',trace_id:event.streamId??this.emitter.producerId,
      operation_id:`${this.emitter.producerId}:cache:${event.generation??0}:${event.ordinal??0}`,
      parent_operation_id:null,level,phase:'decision',outcome:failed?'failed':'observed',basis:'observed',
      links:event.digest?[{relation:'part_of',event_id:null,operation_id:`sha256:${event.digest}`}]:[],
      context:{...event.streamId&&{session_id:event.streamId},...event.generation!==undefined&&{generation:event.generation},
        ...event.ordinal!==undefined&&{chunk_id:String(event.ordinal)},attempt:event.epoch},
      data:{site:'phone.media.idle_cache',condition:event.phase+'.'+event.reason,actual:event.bytes}});
  };
  snapshot(){return {hits:this.hits,misses:this.misses,savedBytes:this.savedBytes};}
}
