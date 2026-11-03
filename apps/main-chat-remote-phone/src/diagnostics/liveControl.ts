import {PlanTransactionTrace} from './planTransaction';
const reasons=new Set(['arm_identity_invalid','idle_mode_invalid','muxed_mode_invalid','arm_cancelled',
  'arm_mode_changed','arm_inactive','arm_history_full','producer_busy','producer_busy_or_closed',
  'avatar_not_musetalk','runtime_not_listening','pipeline_pending','runtime_not_ready','validation_unclassified']);
let trace:PlanTransactionTrace|undefined;
export function liveControlReason(body:unknown):string{
  try{
    const reason=body&&typeof body==='object'?Object.getOwnPropertyDescriptor(body,'diagnosticReason')?.value:undefined;
    return typeof reason==='string'&&reasons.has(reason)?reason:'reason_unavailable';
  }catch{return 'reason_unavailable';}
}
export function recordLiveControlRejection(reason:string,status:number):void{
  try{
    trace??=new PlanTransactionTrace('phone-live-control');
    trace.decision('phone.live_control.reject','rejection_reason',null,reasons.has(reason)?reason:'reason_unavailable');
    trace.decision('phone.live_control.reject','http_status',200,status);
  }catch{}
}
