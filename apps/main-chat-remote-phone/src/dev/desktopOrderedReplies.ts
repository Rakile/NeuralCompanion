import type {AudioChunk,PhoneReplyStatus} from '../api/types';
import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import type {OrderedNativeSource,OrderedSource} from './desktopOrderedProtocol';

type SourceIdentity=Pick<OrderedSource,'kind'|'sourceId'|'replyId'|'sequenceIndex'>;
type Event=Readonly<{kind:string;source:OrderedNativeSource}>;
type Reply={chunks:Map<number,Readonly<AudioChunk>>;started:Set<number>;completed:Set<number>;
  status?:Readonly<PhoneReplyStatus>;departed:boolean;suppressed:boolean;finished:boolean};
type Dependencies={authority(chunk:AudioChunk):BufferedReplyAuthority|null;finish(replyId:string):boolean;
  onCompleted?(chunk:AudioChunk):void};
const validId=(value:unknown):value is string=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value);
const sequence=(value:unknown):value is number=>Number.isSafeInteger(value)&&Number(value)>=0&&Number(value)<64;
const identity=(c:AudioChunk)=>JSON.stringify([c.id,c.phone_request_id,c.sequence_index,c.url_path,c.playback_recovery_epoch??0]);

/** Joins authenticated manifests/status to the actual native journal. This book
 * neither schedules media nor grants output nor derives heard receipts from
 * server completion. The App's existing owner check supplies each authority. */
export class DesktopOrderedReplies {
  private readonly replies=new Map<string,Reply>();
  private current:Readonly<AudioChunk>|null=null;
  private played=0;
  constructor(private readonly deps:Dependencies){}
  private record(id:string):Reply{
    if(!validId(id))throw Error('ordered.reply_id');
    let record=this.replies.get(id);
    if(!record){
      this.reclaim();
      if([...this.replies.values()].filter(r=>!r.finished).length>=32)throw Error('ordered.reply_capacity');
      record={chunks:new Map(),started:new Set(),completed:new Set(),departed:false,suppressed:false,finished:false};
      this.replies.set(id,record);
    }
    return record;
  }
  private reclaim(){
    for(const [id,r] of this.replies){
      if(this.replies.size<64)break;
      if(r.finished)this.replies.delete(id);
    }
  }
  append(id:string,chunks:readonly AudioChunk[]){
    if(chunks.length>64||chunks.some(c=>c.phone_request_id!==id||!validId(c.id)||!sequence(c.sequence_index)))
      throw Error('ordered.reply_manifest');
    const r=this.record(id);if(r.finished||r.suppressed)return;
    // Validate the whole batch before mutation, including conflicting duplicates
    // within this batch and a source ID reused at another sequence index.
    const next=new Map(r.chunks);
    for(const chunk of chunks){
      const index=chunk.sequence_index!,old=next.get(index);
      if(old&&identity(old)!==identity(chunk)
        ||[...next.values()].some(c=>c.id===chunk.id&&c.sequence_index!==index))throw Error('ordered.reply_manifest_changed');
      if(r.status?.phase==='complete'&&(r.status.last_sequence_index===null||index>r.status.last_sequence_index))
        throw Error('ordered.reply_manifest_after_final');
      next.set(index,Object.freeze({...chunk}));
    }
    r.chunks=next;
  }
  observe(id:string,status:PhoneReplyStatus,reconciled:boolean){
    if(status.phone_request_id!==id)throw Error('ordered.reply_status_scope');
    if(!['pending','generating','complete','cancelled','superseded'].includes(status.phase)
      ||status.last_sequence_index!==null&&!sequence(status.last_sequence_index)
      ||status.playback_stop_requested!==undefined&&typeof status.playback_stop_requested!=='boolean')throw Error('ordered.reply_status');
    const r=this.record(id);if(r.finished)return;
    // Cancellation requires authenticated status, not fully downloaded pages.
    if(status.playback_stop_requested||status.phase==='cancelled'||status.phase==='superseded'){this.suppress(id);return;}
    if(!reconciled||r.suppressed)return;
    const previous=r.status;
    if(previous&&(previous.phase==='complete'&&(status.phase!=='complete'||status.last_sequence_index!==previous.last_sequence_index)
      ||previous.last_sequence_index!==null&&(status.last_sequence_index===null||status.last_sequence_index<previous.last_sequence_index)))
      throw Error('ordered.reply_finality_changed');
    if(status.phase==='complete'&&[...r.chunks.keys()].some(i=>status.last_sequence_index===null||i>status.last_sequence_index))
      throw Error('ordered.reply_manifest_after_final');
    r.status=Object.freeze({...status});
  }
  private matching(source:SourceIdentity):Readonly<AudioChunk>|null{
    if(source.kind!=='speech'||!source.replyId||source.sequenceIndex===null)return null;
    const c=this.replies.get(source.replyId)?.chunks.get(source.sequenceIndex);
    return c?.id===source.sourceId?c:null;
  }
  authority(source:SourceIdentity):BufferedReplyAuthority|null{
    const r=source.replyId?this.replies.get(source.replyId):undefined,c=this.matching(source);
    return r&&!r.suppressed&&!r.finished&&c?this.deps.authority(c):null;
  }
  events(events:readonly Event[]){
    for(const event of events){
      if(!event.kind.startsWith('source_'))continue;
      const s=event.source,c=this.matching(s),r=s.replyId?this.replies.get(s.replyId):undefined;
      // Source reader closure is owned/validated by the native session; it may
      // follow reply completion after this book released the speech manifest.
      if(r?.finished&&event.kind==='source_readers_closed')continue;
      if(!r||!c)throw Error('ordered.reply_source');
      if(r.suppressed||r.finished)continue;
      const index=s.sequenceIndex!;
      if(event.kind==='source_started'){
        if(!s.started||r.completed.has(index))throw Error('ordered.reply_start');
        r.started.add(index);this.current=c;
      }else if(event.kind==='source_completed'){
        if(!s.started||!s.completed||!r.started.has(index))throw Error('ordered.reply_completion');
        if(!r.completed.has(index)){
          r.completed.add(index);this.played++;this.deps.onCompleted?.(c);
        }
        if(this.current?.id===c.id)this.current=null;
      }
    }
  }
  finalSequence(id:string):number|null{
    const r=this.replies.get(id),last=r?.status?.last_sequence_index;
    if(!r||r.suppressed||r.finished||r.status?.phase!=='complete'||last===null||last===undefined)return null;
    return Array.from({length:last+1},(_,i)=>i).every(i=>r.chunks.has(i))?last:null;
  }
  nativeCompleted(id:string){
    const r=this.replies.get(id),last=this.finalSequence(id);
    if(!r||last===null||this.completedSequence(id)!==last)throw Error('ordered.reply_departure');
    r.departed=true;
  }
  completedSequence(id:string):number{
    const r=this.replies.get(id);let last=-1;while(r?.completed.has(last+1))last++;return last;
  }
  drained(id:string,final:number|null):boolean{
    const r=this.replies.get(id);if(!r)return false;
    if(r.suppressed||r.finished)return true;
    if(r.status?.phase!=='complete'||r.status.last_sequence_index!==final)return false;
    return final===null?r.chunks.size===0:r.departed&&this.completedSequence(id)===final;
  }
  finish(id:string):boolean{
    const r=this.replies.get(id);if(!r)return false;if(r.finished)return true;
    if(!this.drained(id,r.status?.last_sequence_index??null)||!this.deps.finish(id))return false;
    r.finished=true;r.chunks.clear();this.reclaim();return true;
  }
  finished(id:string):boolean{return this.replies.get(id)?.finished===true;}
  suppressed(id:string):boolean{return this.replies.get(id)?.suppressed===true;}
  suppress(id:string){const r=this.record(id);r.suppressed=true;if(this.current?.phone_request_id===id)this.current=null;}
  get startedReplyId():string|null{
    if(this.current)return this.current.phone_request_id??null;
    for(const [id,r] of this.replies)if(!r.suppressed&&!r.finished&&!r.departed&&r.started.size)return id;
    return null;
  }
  get activeReplyId():string|null{
    const started=this.startedReplyId;if(started)return started;
    for(const [id,r] of this.replies)if(!r.suppressed&&!r.finished&&!r.departed)return id;
    return null;
  }
  get currentChunk(){return this.current;}
  get playedCount(){return this.played;}
  snapshot(){return Object.freeze({activeReplies:[...this.replies.values()].filter(r=>!r.finished).length,
    retainedReplies:this.replies.size});}
}
