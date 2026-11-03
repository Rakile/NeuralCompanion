import {recordPhoneDebug} from './phoneDebugBridge';

const STAGES=['run_retire_start','run_retire_done','source_joins_done','closure_ack_done',
  'return_callback_start','return_callback_done','return_housekeeping_start','return_housekeeping_done',
  'return_prefill_start','return_prefill_done','return_join_start','return_join_done',
  'return_activate_start','return_activate_done','idle_open_start','idle_open_done','idle_play_issued','idle_tick_done',
  'idle_epoch_start','idle_epoch_done','idle_native_prepare_start','idle_native_prepare_done'] as const;

/** Passive call-boundary timing, never a readiness/presentation receipt.
 * No media/owner IDs, paths or raw failures; recorder work cannot gate output. */
export function reportMuxedReturn(stage:typeof STAGES[number],sequenceIndex?:number):void {
  try{
    const monotonic=performance.now();
    if(!STAGES.includes(stage)||!Number.isFinite(monotonic)||monotonic<0)return;
    void recordPhoneDebug('info','muxed_return_boundary',{stage,monotonic_ms:monotonic,
      ...(Number.isSafeInteger(sequenceIndex)&&sequenceIndex!>=0&&sequenceIndex!<=63?{sequence_index:sequenceIndex}:{})})
      .catch(()=>undefined);
  }catch{}
}
