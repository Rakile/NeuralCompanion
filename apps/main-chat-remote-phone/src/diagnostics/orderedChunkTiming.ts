import {DiagnosticEmitter} from './emitter';
import {enqueueDiagnostic,emergencyDiagnostic} from './bridgeSink';
import {siteEnabled} from './policy';

const stages=new Set(['announced','acquiring','retained','acquisition_wait','failed','release_begin','released',
  'open_begin','opened','authority_wait','startup_buffer_wait','stage_begin','stage_blocked','staged','append_begin','append_blocked','appended']);
/** Observations only. No media, file paths, authority or polling snapshots.
 * One bounded last-value slot per milestone suppresses retries of the same
 * ordinal without retaining an ever-growing chunk history. */
export class OrderedChunkTiming{
  private emitter?:DiagnosticEmitter;
  private readonly last=new Map<string,string>();
  constructor(private readonly streamId:string,private readonly generation:number){}
  record(stage:string,ordinal:number,count=1,runRevision:number|null=null):void{
    try{
      if(!siteEnabled('phone.media.ordered'))return;
      if(!stages.has(stage)||!Number.isSafeInteger(ordinal)||ordinal<0
        ||!Number.isSafeInteger(count)||count<1||count>6
        ||runRevision!==null&&(!Number.isSafeInteger(runRevision)||runRevision<0))return;
      const key=`${ordinal}:${count}:${runRevision}`;
      if(this.last.get(stage)===key)return;
      this.emitter??=new DiagnosticEmitter({component:'phone.js',build_id:null,build_unavailable_reason:'not_available',
        clock_id:'phone-performance',enqueue:enqueueDiagnostic,emergency:emergencyDiagnostic});
      this.emitter.emit({event_name:'transaction.operation',trace_id:this.streamId,
        operation_id:`${this.emitter.producerId}:chunk:${this.generation}:${ordinal}`,parent_operation_id:null,
        level:'debug',phase:'decision',outcome:'observed',basis:'observed',links:[],
        context:{session_id:this.streamId,generation:this.generation,chunk_id:String(ordinal)},
        data:{site:'phone.media.ordered',condition:stage,actual:runRevision,part_index:ordinal,part_count:count}});
      this.last.set(stage,key);
    }catch{ /* Diagnostic failure must not change chunk custody or playback. */ }
  }
}
