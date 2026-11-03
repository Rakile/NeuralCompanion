import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import {captureControlTrail} from './captureControlTrail';

const stages=new Set(['capture.release','capture.upload','reply.start','reply.replacement','reply.opened',
  'replacement.halt','replacement.admission','replacement.confirmation','replacement.close','replacement.start',
  'runtime.close','runtime.local_close','stream.interruption','stream.native_stop','stream.native_close',
  'native.invalidate','native.close','native.reconcile','native.serial']);
let sequence=0;
/** Same recovery producer as legacy Live, but output-only: no capture session,
 * credentials, capability or transcript. One call per coordinator transition. */
export function recordOrderedContinuation(stage:string,epoch:number,outcome:string,details:Record<string,unknown>){
  const safe:Record<string,string|number>={};
  for(const key of ['generation','published_cursor','acknowledged_cursor','after_ordinal','ordinal','frame_offset','consumed_samples']){
    const value=details[key];if(typeof value==='number'&&Number.isSafeInteger(value)&&value>=-1)safe[key]=value;
  }
  for(const key of ['stream_id','checkpoint_id','operation_id']){
    const value=details[key];if(typeof value==='string'&&/^[a-f0-9]{32}$/.test(value))safe[key]=value;
  }
  for(const key of ['run_id','native_state','reason']){
    const value=details[key];if(typeof value==='string'&&/^[A-Za-z0-9_.:-]{1,128}$/.test(value))safe[key]=value;
  }
  try{void recordPhoneDebug(outcome==='failed'?'error':'info','live_recovery',{
    source:'ordered_output',stage,recovery_attempt:epoch,outcome,monotonic_ms:performance.now(),...safe}).catch(()=>undefined);}catch{}
}
/** One observation after a slow CONTROL wait, never a timeout or a playback
 * snapshot. No timers in chunk reads/staging/append; return the original promise
 * so diagnostics cannot settle, retry, cancel or grant the operation. */
export function observeOrderedControlWait<T>(stage:string,pending:Promise<T>):Promise<T>{
  if(!stages.has(stage))return pending;
  const waitId=++sequence,started=Date.now();let reported=false,settled=false;
  const emit=(state:'pending'|'resolved'|'rejected')=>{
    try{void recordPhoneDebug('warning','ordered_control_wait',{stage,state,wait_id:waitId,
      wait_ms:Math.max(0,Date.now()-started),capture_actions:captureControlTrail()}).catch(()=>undefined);}catch{}
  };
  try{
    const timer=setTimeout(()=>{if(!settled&&!reported){reported=true;emit('pending');}},5000);
    const finish=(state:'resolved'|'rejected')=>{
      settled=true;try{clearTimeout(timer);}catch{}if(reported)emit(state);
    };
    void pending.then(()=>finish('resolved'),()=>finish('rejected'));
  }catch{ /* Diagnostics cannot replace the original control operation. */ }
  return pending;
}
