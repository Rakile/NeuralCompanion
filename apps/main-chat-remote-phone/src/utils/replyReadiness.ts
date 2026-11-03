import {recordPhoneDebug} from './phoneDebugBridge';
import {diagnosticErrorOrigin} from './diagnosticErrorOrigin';
import {captureControlTrail} from '../diagnostics/captureControlTrail';

const ownerFields=['selected','enabled','owner_changed','ticket_changed','client_changed',
  'peer_changed','auth_changed','recovery_changed','entry_retired','entry_failed'] as const;
type OwnerState=Partial<Record<typeof ownerFields[number],boolean>>;
type Gate={wait():Promise<void>;cancelled:Promise<never>;cancel(reason:'owner_removed'|'owner_replaced'):void;
  reason?:'owner_removed'|'owner_replaced';ownerState?:OwnerState;describeOwner?:()=>OwnerState};
const gates=new WeakMap<object,Gate>();
function ownerState(gate:Gate):OwnerState{
  const result:OwnerState={};
  try{const raw=gate.describeOwner?.();for(const key of ownerFields)if(typeof raw?.[key]==='boolean')result[key]=raw[key];}catch{}
  return result;
}

/** Only the selected muxed owner registers. Capture and control receipts are
 * independent; this gate delays submission, never grants reply authority. */
export function registerReplyReadiness(client:object,wait:()=>Promise<void>,describeOwner?:()=>OwnerState):()=>void{
  gates.get(client)?.cancel('owner_replaced');
  let rejectCancelled!:(error:Error)=>void;
  const cancelled=new Promise<never>((_,reject)=>{rejectCancelled=reject;});
  void cancelled.catch(()=>undefined);
  const gate:Gate={wait,cancelled,describeOwner,cancel:reason=>{
    if(!gate.reason){gate.reason=reason;gate.ownerState=ownerState(gate);}
    rejectCancelled(Error('Muxed submission owner ended.'));
  }};gates.set(client,gate);
  return()=>{gate.cancel('owner_removed');if(gates.get(client)===gate)gates.delete(client);};
}

export async function awaitReplyReadiness(client:object):Promise<void>{
  const gate=gates.get(client);if(!gate)return;
  const started=Date.now();
  try{
    await Promise.race([gate.wait(),gate.cancelled]);
    if(gates.get(client)!==gate)throw Error('Muxed submission owner ended.');
  }catch(error){
    // Failure-only evidence, before any HTTP/peer dispatch. Never retain audio,
    // text, IDs, credentials or arbitrary exception messages. Preserve rejection.
    try{
      const message=error instanceof Error?error.message:'';
      const failureCode=/^(?:ordered[._]|output_)[A-Za-z0-9_.]{1,140}$/.test(message)?message:'unclassified';
      void recordPhoneDebug('error','reply_readiness_failed',{
        reason:gate.reason??'wait_rejected',failure_code:failureCode,
        request_dispatched:false,wait_ms:Math.max(0,Date.now()-started),
        owner_state:gate.ownerState??ownerState(gate),capture_actions:captureControlTrail(),
        error_origin:diagnosticErrorOrigin(error),
      }).catch(()=>undefined);
    }catch{ /* Diagnostic failure must never change ownership or dispatch. */ }
    throw error;
  }
}
