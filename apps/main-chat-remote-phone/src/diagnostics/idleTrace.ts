import {DiagnosticEmitter} from './emitter';
import type {DiagnosticEventV1} from './contract';
import {enqueueDiagnostic,emergencyDiagnostic} from './bridgeSink';
import {siteEnabled} from './policy';
import type {HandoffClaimObservation} from '../utils/phonePresentation';
const positionReasons=new Set(['ownership_unavailable','sealing','source_missing','native_position_missing',
  'native_not_playing','native_position_invalid','chunk_not_retained','frame_metadata_missing','native_position_read_threw']);

/** Observational migration only: never forwards legacy arbitrary detail objects. */
export class IdleDiagnosticTrace{
  private readonly emitter:DiagnosticEmitter;
  constructor(enqueue:(event:DiagnosticEventV1)=>unknown=enqueueDiagnostic){
    this.emitter=new DiagnosticEmitter({component:'phone.js',build_id:null,build_unavailable_reason:'not_available',
      clock_id:'phone-performance',enqueue,emergency:emergencyDiagnostic});
  }
  claimRejected(row:HandoffClaimObservation):void{
    try{
      const id=this.emitter.producerId;
      this.emitter.emit({level:'warning',event_name:'transaction.operation',trace_id:id,operation_id:id+':claim',
        parent_operation_id:null,phase:'snapshot',outcome:'observed',basis:'observed',links:[],context:{},
        data:{site:'muxed_idle.claim',state_after:'rejected',condition:row.reason,expected:row.expected,actual:row.actual}});
    }catch{}
  }
  handoffObserved(row:HandoffClaimObservation):void{
    try{
      if(!siteEnabled('muxed_idle.handoff','debug','observed',{condition:row.reason,expected:row.expected,actual:row.actual}))return;
      const id=this.emitter.producerId;
      this.emitter.emit({level:'debug',event_name:'transaction.operation',trace_id:id,operation_id:id+':handoff',
        parent_operation_id:null,phase:'snapshot',outcome:'observed',basis:'observed',links:[],context:{},
        data:{site:'muxed_idle.handoff',condition:row.reason,expected:row.expected,actual:row.actual}});
    }catch{}
  }
  observe(step:string,details:Record<string,unknown>):void{
    try{
      if(!siteEnabled('muxed_idle.'+step))return;
      const data:Record<string,unknown>={site:'muxed_idle.'+step};
      if(Number.isSafeInteger(details.retained_files)&&Number(details.retained_files)>=0)data.queue_depth=details.retained_files;
      if(Number.isSafeInteger(details.released_through)&&Number(details.released_through)>=0)data.cursor=details.released_through;
      const context:Record<string,string>={};
      if(typeof details.player_id==='string'&&/^[a-f0-9-]{36}$/i.test(details.player_id))context.session_id=details.player_id;
      if(step==='position_unavailable')Object.assign(data,{condition:typeof details.reason==='string'&&positionReasons.has(details.reason)?details.reason:'unclassified_position_failure',expected:true,actual:false});
      if(Number.isSafeInteger(details.chunk_index)&&Number(details.chunk_index)>=0)context.chunk_id=String(details.chunk_index);
      const id=this.emitter.producerId;
      const trace=typeof details.trial_id==='string'&&/^[a-f0-9]{32}$/.test(details.trial_id)?details.trial_id:id;
      this.emitter.emit({level:'debug',event_name:'transaction.operation',trace_id:trace,operation_id:id+':idle',
        parent_operation_id:null,phase:'snapshot',outcome:'observed',basis:'observed',links:[],context,data});
    }catch{}
  }
}
