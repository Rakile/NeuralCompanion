import {DiagnosticEmitter} from './emitter';
import type {DiagnosticEventV1} from './contract';
import {enqueueDiagnostic,emergencyDiagnostic} from './bridgeSink';
import {siteEnabled} from './policy';

export type DiagnosticLink={trace_id:string;operation_id:string;event_id:string|null};
let acquisitionEmitter:DiagnosticEmitter|undefined;
export function mediaAcquisition(link:DiagnosticLink|undefined,kind:'shared_pending'|'retained'|'cache_hit'|'persistent_hit',owner?:DiagnosticLink):void{
  try{
    if(!siteEnabled('phone.media.acquire'))return;
    const safe=preparationDiagnosticLink({trialId:link?.trace_id,diagnosticLink:link});if(!safe)return;
    const prior=preparationDiagnosticLink({trialId:owner?.trace_id,diagnosticLink:owner});
    acquisitionEmitter??=new DiagnosticEmitter({component:'phone.js',build_id:null,build_unavailable_reason:'not_available',
      clock_id:'phone-performance',enqueue:enqueueDiagnostic,emergency:emergencyDiagnostic});
    acquisitionEmitter.emit({event_name:'transaction.operation',trace_id:safe.trace_id,operation_id:safe.operation_id,
      parent_operation_id:null,basis:'observed',level:'debug',phase:'decision',outcome:'observed',
      links:[safe,...(prior?[prior]:[])].map(value=>({relation:'part_of',event_id:value.event_id,operation_id:value.operation_id})),
      context:{session_id:safe.trace_id},data:{site:'phone.media.acquire',condition:'acquisition_kind',expected:null,actual:kind}});
  }catch{}
}
/** Metadata is correlation only. Never invoke accessors or export arbitrary labels. */
export function preparationDiagnosticLink(body:unknown):DiagnosticLink|undefined{
  try{
    if(!body||typeof body!=='object')return;
    const trial=Object.getOwnPropertyDescriptor(body,'trialId')?.value;
    const link=Object.getOwnPropertyDescriptor(body,'diagnosticLink')?.value;
    if(typeof trial!=='string'||! /^[a-f0-9]{32}$/.test(trial)||!link||typeof link!=='object')return;
    if(Object.keys(link).sort().join(',')!=='event_id,operation_id,trace_id')return;
    const trace=Object.getOwnPropertyDescriptor(link,'trace_id')?.value;
    const operation=Object.getOwnPropertyDescriptor(link,'operation_id')?.value;
    const event=Object.getOwnPropertyDescriptor(link,'event_id')?.value;
    if(trace!==trial||typeof operation!=='string'||operation.length>128)return;
    const match=/^(js-[a-z0-9]+-[0-9]+-[a-z0-9]+):request:[0-9]+$/.exec(operation);
    if(!match||!(event===null||(typeof event==='string'&&event.length<=128&&
      event.startsWith(match[1]+':')&&/^[0-9]+$/.test(event.slice(match[1]!.length+1)))))return;
    return {trace_id:trace,operation_id:operation,event_id:event};
  }catch{return;}
}

/** Correlate existing requests; never add a request, retry or authority read. */
export class PlanTransactionTrace{
  private readonly emitter:DiagnosticEmitter;
  private serial=0;
  constructor(private readonly trialId:string,enqueue:(event:DiagnosticEventV1)=>unknown=enqueueDiagnostic){
    this.emitter=new DiagnosticEmitter({component:'phone.js',build_id:null,build_unavailable_reason:'not_available',
      clock_id:'phone-performance',enqueue,emergency:emergencyDiagnostic});
  }
  decision(site:string,condition:string,expected:string|number|boolean|null,actual:string|number|boolean|null,level:'debug'|'warning'='debug'):void{
    if(!siteEnabled(site,level,'observed',{condition,expected,actual}))return;
    this.emitter.emit({event_name:'transaction.operation',trace_id:this.trialId,
      operation_id:this.emitter.producerId+':decision:'+ ++this.serial,parent_operation_id:null,
      level,phase:'decision',outcome:'observed',basis:'observed',links:[],context:{session_id:this.trialId},
      data:{site,condition,expected,actual}});
  }
  async operation<T>(site:string,work:()=>Promise<T>,context:{segment_id?:string;chunk_id?:string}={}):Promise<T>{
    const operation=this.emitter.producerId+':operation:'+ ++this.serial;
    const base={event_name:'transaction.operation',trace_id:this.trialId,operation_id:operation,parent_operation_id:null,
      basis:'observed',context:{session_id:this.trialId,...context}} as const;
    const beginSuppressed=!siteEnabled(site);
    const begin=!beginSuppressed?this.emitter.emit({...base,level:'debug',phase:'begin',outcome:'pending',links:[],data:{site}}):null;
    const links=begin?[{relation:'part_of' as const,event_id:begin,operation_id:operation}]:[];
    try{
      const result=await work();
      if(begin||siteEnabled(site))this.emitter.emit({...base,level:'debug',phase:'end',outcome:'success',links,data:{site,...(begin?{begin_recorded:true}:{}),...(beginSuppressed?{begin_suppressed:true}:{})}});
      return result;
    }catch(error){
      const origin=begin??this.emitter.emit({...base,level:'warning',phase:'decision',outcome:'observed',links,
        data:{site,failure_kind:'operation_failed',condition:'operation_resolved',expected:true,actual:false}})??'diagnostic-origin-unavailable';
      this.emitter.emit({...base,level:'warning',phase:'end',outcome:'failed',links,
        data:{site,failure_kind:'operation_failed',condition:'operation_resolved',expected:true,actual:false,
          origin_event_id:origin,...(beginSuppressed?{begin_suppressed:true}:{})}});
      throw error;
    }
  }
  /** Attach observations without replacing the native promise or adding an awaited hop. */
  observeCall<T>(site:string,work:(link:DiagnosticLink)=>Promise<T>,parent?:DiagnosticLink):Promise<T>{
    const operation=this.emitter.producerId+':native:'+ ++this.serial;
    const base={event_name:'transaction.operation',trace_id:this.trialId,operation_id:operation,parent_operation_id:parent?.operation_id??null,
      basis:'observed',context:{session_id:this.trialId}} as const;
    const parentLinks=parent?.event_id?[{relation:'part_of' as const,event_id:parent.event_id,operation_id:parent.operation_id}]:[];
    const beginSuppressed=!siteEnabled(site);
    const begin=!beginSuppressed?this.emitter.emit({...base,level:'debug',phase:'begin',outcome:'pending',links:parentLinks,data:{site}}):null;
    const links=[...parentLinks,...(begin?[{relation:'part_of' as const,event_id:begin,operation_id:operation}]:[])];
    const finish=(ok:boolean)=>{
      if(ok&&!begin&&!siteEnabled(site))return;
      const origin=ok?null:begin??this.emitter.emit({...base,level:'warning',phase:'decision',outcome:'observed',links,
        data:{site,failure_kind:'native_call_failed',condition:'call_resolved',expected:true,actual:false}})??'diagnostic-origin-unavailable';
      this.emitter.emit({...base,level:ok?'debug':'warning',phase:'end',outcome:ok?'success':'failed',links,
        data:{site,...(begin?{begin_recorded:true}:{}),...(beginSuppressed?{begin_suppressed:true}:{}),...(!ok?{failure_kind:'native_call_failed',condition:'call_resolved',expected:true,actual:false,origin_event_id:origin}:{})}});
    };
    const response=(value:unknown)=>{
      const emit=(condition:string,actual:string|boolean,failed=false)=>siteEnabled(site,failed?'warning':'debug','observed',{condition,actual})&&this.emitter.emit({...base,level:failed?'warning':'debug',phase:'decision',outcome:'observed',links,
        data:{site,condition,expected:null,actual}});
      try{
        if(typeof value==='boolean')emit('response_boolean',value,!value);
        else if(value&&typeof value==='object'){
          // Read data properties only; never invoke response accessors or export arbitrary strings.
          const kind=Object.getOwnPropertyDescriptor(value,'kind')?.value;
          if(kind!==undefined)emit('response_kind',['blocked','staged','admitted','closed','sealed','pending'].includes(kind)?kind:'unclassified',kind==='blocked');
          const reason=Object.getOwnPropertyDescriptor(value,'reason')?.value;
          if(reason!==undefined)emit('response_reason',['capacity','tail_changed','future_occupied'].includes(reason)?reason:'unclassified',kind==='blocked');
        }
      }catch{emit('response_observable',false,true);}
    };
    try{const pending=work({trace_id:this.trialId,operation_id:operation,event_id:begin});void pending.then(value=>{response(value);finish(true);},()=>finish(false));return pending;}
    catch(error){finish(false);throw error;}
  }
  async request<T>(kind:'prepare'|'wait_ready'|'status'|'download',work:(link:{trace_id:string;operation_id:string;event_id:string|null})=>Promise<T>,context:{segment_id?:string;chunk_id?:string}={}):Promise<T>{
    const operation=this.emitter.producerId+':request:'+ ++this.serial,site='phone.plan.'+kind;
    const base={event_name:'transaction.operation',trace_id:this.trialId,operation_id:operation,parent_operation_id:null,
      basis:'observed',context:{session_id:this.trialId,...context}} as const;
    const beginSuppressed=!siteEnabled(site);
    const begin=!beginSuppressed?this.emitter.emit({...base,level:'debug',phase:'begin',outcome:'pending',links:[],data:{site}}):null;
    const links=begin?[{relation:'part_of' as const,event_id:begin,operation_id:operation}]:[];
    try{
      const result=await work({trace_id:this.trialId,operation_id:operation,event_id:begin});
      // These are presence observations only: the existing parsers still own validation.
      const value=result as Record<string,unknown>|null;
      for(const [field,condition] of (kind==='download'?[]:[['anticipation','anticipation_present'],['sourceTimeline','timeline_present']] as const)){
        try{
          const present=!!value&&value[field]!==undefined;
          if(siteEnabled(site,'debug','observed',{condition,expected:true,actual:present}))this.emitter.emit({...base,level:'debug',phase:'decision',outcome:'observed',links,
            data:{site,condition,expected:true,actual:present}});
        }catch{
          this.emitter.emit({...base,level:'warning',phase:'decision',outcome:'observed',links,
            data:{site,condition:field+'_observable',expected:true,actual:false}});
        }
      }
      if(begin||siteEnabled(site))this.emitter.emit({...base,level:'debug',phase:'end',outcome:'success',links,data:{site,...(begin?{begin_recorded:true}:{}),...(beginSuppressed?{begin_suppressed:true}:{})}});
      return result;
    }catch(error){
      const origin=begin??this.emitter.emit({...base,level:'warning',phase:'decision',outcome:'observed',links,
        data:{site,failure_kind:'request_failed',condition:'request_resolved',expected:true,actual:false}})??'diagnostic-origin-unavailable';
      this.emitter.emit({...base,level:'warning',phase:'end',outcome:'failed',links,
        data:{site,failure_kind:'request_failed',condition:'request_resolved',expected:true,actual:false,
          origin_event_id:origin,...(beginSuppressed?{begin_suppressed:true}:{})}});
      throw error;
    }
  }
}
