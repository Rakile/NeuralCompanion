import type {AudioPlayer} from 'expo-audio';
import type {AudioChunk,PhoneReplyAuth} from '../api/types';
import type {PeerTransport} from './peer';
import {PeerTransportUnavailableError} from './peer';
import {BufferedMediaStore} from './bufferedMedia';
import type {BufferedMediaDescriptor,BufferedMediaLease,BufferedMediaScope} from './bufferedMedia';
import type {BufferedPresentation} from '../native/bufferedPresentation';

export type BufferedReplyAuthority={scope:BufferedMediaScope;auth:PhoneReplyAuth;ticket:string};
type Descriptor=BufferedMediaDescriptor & {sample_rate:48000;valid_samples:number;format:'ogg-opus'};
type RecordEntry={chunk:AudioChunk;authority:BufferedReplyAuthority;descriptor:Promise<Descriptor>;key:number;replay?:boolean;detach?:()=>void;
  readers:number;finished?:boolean;peer?:PeerTransport;released?:boolean};
type Dependencies={peer():PeerTransport|null;reply(chunk:AudioChunk):BufferedReplyAuthority|null;
  replayAuthority?():{owner:string;ticket:string}|null;
  diagnose?(event:string,fields:Record<string,number|string>):void;
  presentation():Promise<BufferedPresentation>};

// A native presentation survives successive playback tickets. Never recycle
// one of its keys merely because a reply-file owner was replaced.
let nextPlaybackKey=0;

/** Downloads never grant playback permission. Native binding still goes through
 * the existing guarded audio player, with the current ticket and reply identity. */
export class BufferedAudioDelivery {
  readonly store:BufferedMediaStore;
  private readonly records=new Map<string,RecordEntry>();
  private closed=false;
  constructor(private readonly deps:Dependencies){
    this.store=new BufferedMediaStore(deps.peer,scope=>!this.closed&&Array.from(this.records.values()).some(row=>
      this.sameScope(row.authority.scope,scope)&&this.current(row)));
  }
  private sameScope(a:BufferedMediaScope,b:BufferedMediaScope){
    return a.owner===b.owner&&a.replyId===b.replyId&&a.expiresAt===b.expiresAt;
  }
  private current(row:RecordEntry){
    if(row.replay){
      const now=this.deps.replayAuthority?.();
      return !this.closed&&Boolean(now&&now.owner===row.authority.scope.owner&&now.ticket===row.authority.ticket
        &&row.authority.scope.expiresAt>Date.now());
    }
    const now=this.deps.reply(row.chunk);
    return !this.closed&&Boolean(now&&this.sameScope(now.scope,row.authority.scope)&&now.ticket===row.authority.ticket
      &&JSON.stringify(now.auth)===JSON.stringify(row.authority.auth)&&now.scope.expiresAt>Date.now());
  }
  private authority(chunk:AudioChunk):BufferedReplyAuthority {
    const value=this.deps.reply(chunk);
    if(this.closed||!value||!value.ticket||!value.scope.owner||value.scope.replyId!==chunk.phone_request_id
      ||value.scope.expiresAt<=Date.now())throw Error('Buffered reply authority unavailable.');
    if(!/^[A-Za-z0-9_.-]{1,256}$/.test(chunk.id)||chunk.url_path!==`/api/audio/file/${chunk.id}`
      ||!Number.isSafeInteger(chunk.sequence_index)||chunk.sequence_index!<0)throw Error('Invalid buffered audio identity.');
    return value;
  }
  private id(chunk:AudioChunk,authority:BufferedReplyAuthority){return JSON.stringify([authority.scope.owner,authority.scope.replyId,chunk.id]);}
  private async describe(row:RecordEntry):Promise<Descriptor>{
    const peer=this.deps.peer();
    if(!peer)throw new PeerTransportUnavailableError('Buffered audio peer reconnecting.');
    if(peer.cacheScope!==row.authority.scope.owner)throw Error('Buffered audio desktop changed.');
    row.peer=peer;
    await peer.negotiateBuffered();
    if(!this.current(row))throw Error('Buffered reply authority ended.');
    const result=await peer.request('POST',row.replay?'/api/buffered/replay':'/api/buffered/audio',row.replay?
      {chunk_id:row.chunk.id,format:'ogg-opus'}:{auth:row.authority.auth,
      request_id:row.chunk.phone_request_id!,chunk_id:row.chunk.id,sequence_index:row.chunk.sequence_index!,format:'ogg-opus'});
    const value=result.body as Descriptor|undefined;
    if(result.status!==200){
      const status=Number.isInteger(result.status)?result.status:0;
      try { this.deps.diagnose?.('buffered_audio_descriptor_rejected',{http_status:status,
        sequence_index:row.chunk.sequence_index??-1}); } catch { /* Diagnostics cannot mask playback failure. */ }
      // Server exception text can contain paths or credentials. Show only the
      // response status; typed server diagnostics explain the underlying cause.
      throw Error(`Desktop could not prepare this audio segment (HTTP ${status}). Open playback controls to replay the response.`);
    }
    if(!result.contentType.startsWith('application/json')||!value
      ||!/^[a-f0-9]{32}$/.test(value.id)||value.path!==`/api/buffered/audio/${value.id}.ogg`
      ||value.contentType!=='audio/ogg'||value.format!=='ogg-opus'||value.sample_rate!==48000
      ||!Number.isSafeInteger(value.valid_samples)||value.valid_samples<1||value.valid_samples>28800000
      ||!Number.isSafeInteger(value.bytes)||value.bytes<1||value.bytes>16*1024*1024)
      throw Error('Buffered audio descriptor unavailable or invalid.');
    if(!this.current(row))throw Error('Buffered reply authority ended.');
    return Object.freeze({...value});
  }
  private record(chunk:AudioChunk):RecordEntry {
    const authority=this.authority(chunk),id=this.id(chunk,authority);
    const existing=this.records.get(id);
    if(existing){if(!this.current(existing))throw Error('Buffered reply authority changed.');return existing;}
    for(const [key,row] of this.records)if(!row.detach&&!row.readers&&(!this.current(row)
      ||row.finished&&this.sameScope(row.authority.scope,authority.scope))){this.releaseEncoded(row);this.records.delete(key);}
    if(this.records.size>=96)throw Error('Buffered audio descriptor capacity reached.');
    const row:RecordEntry={chunk:{...chunk},authority,descriptor:null!,key:++nextPlaybackKey,readers:0};
    if(row.key>0x7fffffff)throw Error('Buffered audio key capacity reached.');
    this.records.set(id,row);
    row.descriptor=this.describe(row);
    const pending=row.descriptor;
    void pending.catch(()=>{if(this.records.get(id)===row&&row.descriptor===pending)this.records.delete(id);});
    return row;
  }
  acquire=async(chunk:AudioChunk,signal:AbortSignal):Promise<BufferedMediaLease>=>{
    if(signal.aborted)throw Error('Buffered audio cancelled.');
    return this.acquireRecord(this.record(chunk),signal);
  };
  private async acquireRecord(row:RecordEntry,signal:AbortSignal):Promise<BufferedMediaLease>{
    const peer=this.deps.peer();
    // Opaque encoded-file IDs belong to the peer which created them. If no
    // retained reader/native binding remains, renew only that descriptor on
    // the same authenticated desktop; keep the reserved playback key/ticket.
    // Existing local leases need neither this renewal nor any network traffic.
    if(!row.readers&&!row.detach&&peer&&peer!==row.peer){
      if(!this.current(row)||peer.cacheScope!==row.authority.scope.owner)
        throw Error('Buffered audio desktop or authority changed.');
      const previous=row.peer,descriptor=row.descriptor;
      if(previous&&!previous.closed)void descriptor.then(async value=>{
        if(!previous.closed)await previous.request('POST','/api/buffered/release',{id:value.id});
      }).catch(()=>this.deps.diagnose?.('buffered_encoded_release_failed',{}));
      row.released=false;
      row.descriptor=this.describe(row);
      const pending=row.descriptor;
      void pending.catch(()=>{if(row.descriptor===pending)row.peer=undefined;});
    }
    row.readers++;
    let released=false;
    const retire=()=>{if(!released){released=true;row.readers--;this.releaseEncoded(row);}};
    try{
      const lease=await this.store.acquire(row.authority.scope,await row.descriptor,signal);
      let task:Promise<void>|undefined;
      return {...lease,release:()=>task??=(async()=>{await lease.release();retire();})()};
    }catch(error){retire();throw error;}
  }
  private releaseEncoded(row:RecordEntry){
    if(row.released||row.detach||row.readers||(!row.finished&&!this.closed&&this.current(row)))return;
    row.released=true;
    void row.descriptor.then(async descriptor=>{
      // Never send an old capability to a replacement peer/account. Closed
      // peers reclaim their service themselves; this only releases disk data.
      const peer=row.peer;if(!peer||peer.closed)return;
      const result=await peer.request('POST','/api/buffered/release',{id:descriptor.id});
      if(result.status!==200)throw Error('Encoded media release rejected');
    }).catch(()=>this.deps.diagnose?.('buffered_encoded_release_failed',{}));
  }
  retire(chunk:AudioChunk){
    for(const row of this.records.values())if(!row.replay&&row.chunk.id===chunk.id&&row.chunk.phone_request_id===chunk.phone_request_id){
      row.finished=true;this.releaseEncoded(row);
    }
  }
  /** Explicit user playback uses the fresh local ticket, not the historical
   * reply capability. It cannot attach or acknowledge an automatic reply. */
  readonly replay={
    acquire:async(chunk:AudioChunk,signal:AbortSignal):Promise<BufferedMediaLease>=>{
      const authority=this.deps.replayAuthority?.();
      if(this.closed||signal.aborted||!authority?.owner||!authority.ticket)throw Error('Buffered replay authority unavailable.');
      if(!/^[A-Za-z0-9_.-]{1,128}$/.test(chunk.id)||chunk.id.includes('..')||chunk.url_path!==`/api/audio/file/${chunk.id}`)
        throw Error('Invalid buffered replay identity.');
      for(const [id,row] of this.records)if(!this.current(row)&&!row.detach&&!row.readers){this.releaseEncoded(row);this.records.delete(id);}
      if(this.records.size>=96)throw Error('Buffered audio descriptor capacity reached.');
      const key=++nextPlaybackKey;
      if(key>0x7fffffff)throw Error('Buffered audio key capacity reached.');
      const id=`replay-${key}`;
      const row:RecordEntry={chunk:{...chunk},replay:true,key,descriptor:null!,readers:0,authority:{auth:{} as PhoneReplyAuth,ticket:authority.ticket,
        scope:{owner:authority.owner,replyId:id,expiresAt:Date.now()+15*60*1000}}};
      this.records.set(id,row);row.descriptor=this.describe(row);
      try{
        const lease=await this.acquireRecord(row,signal);
        return {...lease,release:async()=>{row.finished=true;await lease.release();this.records.delete(id);}};
      }catch(error){row.finished=true;this.releaseEncoded(row);this.records.delete(id);throw error;}
    },
    owns:(chunk:AudioChunk,uri:string)=>Array.from(this.records.values()).some(row=>row.replay&&row.chunk.id===chunk.id
      &&this.current(row)&&this.store.owns(row.authority.scope,uri)),
  };
  owns=(chunk:AudioChunk,uri:string):boolean=>{
    try{const authority=this.authority(chunk);return this.store.owns(authority.scope,uri);}catch{return false;}
  };
  key(chunk:AudioChunk):number {return this.record(chunk).key;}
  scope(chunk:AudioChunk):BufferedMediaScope {return this.record(chunk).authority.scope;}
  attach=async(player:AudioPlayer,chunk:AudioChunk,ticket:string|null):Promise<()=>void>=>{
    const row=this.record(chunk);
    if(!ticket||ticket!==row.authority.ticket||row.detach)throw Error('Buffered native audio authority unavailable.');
    const descriptor=await row.descriptor,presentation=await this.deps.presentation();
    if(!this.current(row)||row.detach)throw Error('Buffered native audio authority ended.');
    const nativeDetach=await presentation.attachAudio(player,{key:row.key,ticket,requestId:row.authority.scope.replyId,
      chunkId:chunk.id,validSamples:descriptor.valid_samples});
    let removed=false;
    const detach=()=>{if(!removed){removed=true;nativeDetach();if(row.detach===detach)row.detach=undefined;this.releaseEncoded(row);}};
    row.detach=detach;
    if(!this.current(row)){detach();throw Error('Buffered native audio authority ended.');}
    return detach;
  };
  close(){this.closed=true;for(const row of this.records.values()){row.detach?.();this.releaseEncoded(row);}}
}
