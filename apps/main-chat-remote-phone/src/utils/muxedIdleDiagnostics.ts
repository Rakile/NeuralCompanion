import {recordPhoneDebug} from './phoneDebugBridge';
import {diagnosticErrorOrigin} from './diagnosticErrorOrigin';

export type MuxedIdleOperation='position'|'prune'|'queue'|'release'|'status'|'retain'|'append'|'cursor_ack';
type ErrorClass='Error'|'TypeError'|'RangeError'|'opaque';

/** Last attempted call only, not proof of a uniquely attributed native cause.
 * Recorder failures and pending work never join playback or lease closure. */
export function reportMuxedIdleFailure(operation:MuxedIdleOperation,error:unknown,retainedFiles:number,releasedThrough:number):void {
  try{
    let errorClass:ErrorClass='opaque',message:unknown;
    try{
      if(error instanceof Error){
        const name=error.name;
        if(name==='Error'||name==='TypeError'||name==='RangeError')errorClass=name;
      }
    }catch{}
    try{if(error instanceof Error)message=error.message;}catch{}
    let failureKind='other';
    switch(message){
      case 'NC peer request timed out.':failureKind='peer_timeout';break;
      case 'NC peer request cancelled.':failureKind='peer_cancelled';break;
      case 'NC media peer unavailable.':
      case 'Buffered media peer reconnecting.':
      case 'Muxed peer reconnecting.':
      case 'Internet peer disconnected.':failureKind='peer_unavailable';break;
      case 'Idle chunk return identity changed.':failureKind='return_identity_changed';break;
      case 'Idle chunk return source changed.':failureKind='return_source_changed';break;
      case 'Buffered reply revoked.':failureKind='reply_revoked';break;
      case 'Buffered media cleanup remains unconfirmed.':failureKind='cleanup_unconfirmed';break;
      case 'Continuous muxed owner ended.':failureKind='continuous_owner_ended';break;
      case 'Continuous visual scope ended.':failureKind='visual_scope_ended';break;
      case 'Continuous visual native tail changed.':failureKind='visual_tail_changed';break;
      case 'Continuous visual append unconfirmed.':failureKind='visual_append_unconfirmed';break;
      case 'Invalid continuous visual stage.':failureKind='visual_stage_invalid';break;
      case 'Continuous visual range changed.':failureKind='visual_range_changed';break;
      case 'Continuous visual epoch changed.':failureKind='visual_epoch_changed';break;
      case 'Idle chunk native append unavailable.':failureKind='idle_append_rejected';break;
    }
    void recordPhoneDebug('warning','muxed_idle_failure',{operation,failure_kind:failureKind,error_class:errorClass,error_origin:diagnosticErrorOrigin(error),
      retained_files:Number.isSafeInteger(retainedFiles)?Math.max(0,Math.min(6,retainedFiles)):0,
      released_through:Number.isSafeInteger(releasedThrough)&&releasedThrough>=0?releasedThrough:0}).catch(()=>undefined);
  }catch{}
}
