import {DiagnosticEmitter} from './emitter';
import {enqueueDiagnostic,emergencyDiagnostic} from './bridgeSink';
type Reason='revoked'|'owner_missing'|'reply_missing'|'expiry_invalid'|'expired'|'scope_not_current'
  |'runtime_not_live'|'runtime_owner_changed'|'runtime_expired'|'runtime_scope_unregistered';
type Phase='acquire'|'acquire_complete'|'transfer'|'owns'|'runtime';
/** Observe only values already sampled by the guard; never read authority or the clock again. */
export class MediaScopeTrace{
  private emitter?:DiagnosticEmitter;
  rejected(phase:Phase,reason:Reason,scope:{replyId:string;expiresAt:number},now?:number):void{
    try{
      const emitter=this.emitter??=new DiagnosticEmitter({component:'phone.js',build_id:null,
        build_unavailable_reason:'not_available',clock_id:'phone-performance',enqueue:enqueueDiagnostic,emergency:emergencyDiagnostic});
      const id=emitter.producerId;
      emitter.emit({level:'warning',event_name:'transaction.operation',trace_id:id,operation_id:id+':scope',
        parent_operation_id:null,phase:'snapshot',outcome:'observed',basis:'observed',links:[],context:{},
        data:{site:'phone.media.scope.'+phase,condition:reason,state_after:'rejected',
          state_before:scope.replyId.startsWith('muxed-idle:')?'idle_scope':'reply_scope',
          expected:Number.isFinite(scope.expiresAt)?scope.expiresAt:null,
          actual:typeof now==='number'&&Number.isFinite(now)?now:null}});
    }catch{}
  }
}
