import type {PhoneReplyStatus} from '../api/types';

export type MuxedFinalityDecision='unknown'|'nonfinal'|'final'|'cancelled'|'invalid';
const phases=new Set(['pending','generating','complete','cancelled','superseded']);

/** One admitted reply's knowledge, not output permission. The owned App observer
 * supplies authenticated status only after its continuation pages and current
 * connection/reply checks complete. No additional poller, receipt or deadline.
 * Runtime must still validate its current ticket/source before using a decision.
 */
export class MuxedReplyFinality {
  private observation?:Readonly<PhoneReplyStatus>;
  private invalid=false;
  private cancelled=false;
  constructor(private readonly replyId:string) {
    if(!replyId||[...replyId].length>128)throw Error('Invalid muxed reply finality scope.');
  }
  observe(status:PhoneReplyStatus,pagesReconciled:boolean):boolean {
    if(this.invalid||this.cancelled||!pagesReconciled||status.phone_request_id!==this.replyId)return false;
    const last=status.last_sequence_index;
    if(!phases.has(status.phase)||(last!==null&&(!Number.isInteger(last)||last<0||last>63))
      ||(status.playback_stop_requested!==undefined&&typeof status.playback_stop_requested!=='boolean')
      ||(status.phase==='complete'&&last===null))return this.reject();
    if(status.playback_stop_requested===true||status.phase==='cancelled'||status.phase==='superseded') {
      this.cancelled=true;return true;
    }
    const prior=this.observation;
    if(prior&&(prior.phase==='complete'&&(status.phase!=='complete'||last!==prior.last_sequence_index)
      ||prior.last_sequence_index!==null&&(last===null||last<prior.last_sequence_index)))return this.reject();
    this.observation=Object.freeze({phone_request_id:this.replyId,phase:status.phase,last_sequence_index:last,
      ...(status.playback_stop_requested===undefined?{}:{playback_stop_requested:status.playback_stop_requested})});
    return true;
  }
  decision(nativeTailSequence:number):MuxedFinalityDecision {
    if(this.invalid||!Number.isInteger(nativeTailSequence)||nativeTailSequence<0||nativeTailSequence>63)return 'invalid';
    if(this.cancelled)return 'cancelled';
    const observed=this.observation;if(!observed)return 'unknown';
    if(observed.phase!=='complete')return 'nonfinal';
    const last=observed.last_sequence_index!;
    return last<nativeTailSequence?'invalid':last===nativeTailSequence?'final':'nonfinal';
  }
  private reject():false {this.invalid=true;return false;}
}
