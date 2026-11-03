import {validateDiagnosticEvent} from './contract';
import type {DiagnosticEventV1,ValidationIssue} from './contract';
import {policy,siteEnabled} from './policy';
export type DiagnosticInput=Pick<DiagnosticEventV1,'level'|'event_name'|'trace_id'|'operation_id'|'parent_operation_id'|'phase'|'outcome'|'basis'|'links'|'context'|'data'>;
type Options={component:string;build_id:string|null;build_unavailable_reason:string|null;clock_id:string;
  enqueue:(event:DiagnosticEventV1)=>unknown;emergency:(event:DiagnosticEventV1)=>void;
  wallClock?:()=>string;monotonicClock?:()=>number};
const fields=new Set(['level','event_name','trace_id','operation_id','parent_operation_id','phase','outcome','basis','links','context','data']);
let instance=0;
export class DiagnosticEmitter{
  readonly producerId=`js-${Date.now().toString(36)}-${++instance}-${Math.random().toString(36).slice(2)}`;
  private sequence=0;private noticeSequence=0;private busy=false;private notifying=false;
  private readonly options:Options;
  constructor(options:Options){this.options={...options};}
  private notice(reason:string,related:string|null=null,issues?:ValidationIssue[]):void{
    if(this.notifying)return;this.notifying=true;
    try{
      const producer=this.producerId+'-notice',sequence=++this.noticeSequence,event_id=producer+':'+sequence;
      this.options.emergency({schema_version:1,event_id,producer_id:producer,sequence,component:'diagnostics',
        build_id:null,build_unavailable_reason:'emergency_path',wall_time_utc:new Date().toISOString(),
        monotonic_ms:performance.now(),clock_id:producer,level:'error',
        event_name:issues?'diagnostics.validation_failed':'diagnostics.sink_failed',
        trace_id:related??producer,operation_id:event_id,parent_operation_id:null,phase:'snapshot',outcome:'observed',basis:'observed',links:[],context:{},
        data:issues?{site:'diagnostics.emit',issues}:{site:'diagnostics.emit',reason,related_event_id:related}});
    }catch{try{console.error('[NC diagnostics] emergency sink failed');}catch{}}
    finally{this.notifying=false;}
  }
  emitLazy(category:string,verbosity:string,build:()=>DiagnosticInput,mandatory=false):string|null{
    if(!policy.enabled(category,verbosity,mandatory))return null;
    try{return this.emit(build(),true);}catch{this.notice('input_invalid');return null;}
  }
  emit(input:DiagnosticInput,selected=false):string|null{
    if(this.busy||this.notifying){this.notice('reentrant_emit');return null;}this.busy=true;
    try{
      if(!input||typeof input!=='object'||Object.keys(input).some(k=>!fields.has(k))){
        this.notice('input_invalid',null,[{path:'$',rule:'input_fields'}]);return null;}
      if(!selected&&input.data&&typeof input.data==='object'&&!siteEnabled(
        String(input.data.site??input.event_name),input.level,input.outcome,input.data))return null;
      if(this.sequence>=Number.MAX_SAFE_INTEGER){this.notice('sequence_exhausted');return null;}
      const sequence=++this.sequence,event_id=this.producerId+':'+sequence;
      let event:DiagnosticEventV1;
      try{event={...input,schema_version:1,event_id,producer_id:this.producerId,sequence,
        component:this.options.component,build_id:this.options.build_id,build_unavailable_reason:this.options.build_unavailable_reason,
        clock_id:this.options.clock_id,wall_time_utc:(this.options.wallClock??(()=>new Date().toISOString()))(),
        monotonic_ms:(this.options.monotonicClock??(()=>performance.now()))()};}
      catch{this.notice('clock_failed',event_id);return null;}
      const issues=validateDiagnosticEvent(event);
      if(issues.length){this.notice('input_invalid',event_id,issues);return null;}
      try{
        const result=this.options.enqueue(JSON.parse(JSON.stringify(event)));
        if(result===false){this.notice('enqueue_rejected',event_id);return null;}
        if(result&&typeof (result as Promise<unknown>).then==='function')
          void Promise.resolve(result).then(value=>{if(value===false)this.notice('enqueue_rejected',event_id);},()=>this.notice('enqueue_rejected',event_id));
      }catch{this.notice('enqueue_threw',event_id);return null;}
      return event_id;
    }catch{this.notice('input_invalid');return null;}
    finally{this.busy=false;}
  }
}
