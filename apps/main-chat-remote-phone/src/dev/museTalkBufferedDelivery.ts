import type {AudioChunk} from '../api/types';
import {parseLiveStatus,liveStatusFailureStage} from './museTalkLiveTrial';
import {parseSourceTimeline} from '../relay/frameHandoff';
import type {SourceTimeline} from '../relay/frameHandoff';
import type {BufferedMediaLease, BufferedMediaScope} from '../relay/bufferedMedia';
import {BufferedMediaStore, BufferedMediaCapacityError} from '../relay/bufferedMedia';
import {PeerTransportUnavailableError} from '../relay/peer';

type Status = ReturnType<typeof parseLiveStatus>;
type Segment = {index:number; startFrame:number; frameCount:number; uri:string; bytes:number};
export type BufferedChunk = {
  chunk:Readonly<AudioChunk>; audio:BufferedMediaLease; timeline:SourceTimeline;
  segments:ReadonlyArray<Segment>; complete:boolean; status:Status;
};
type Dependencies = {
  trialId:string; scope:BufferedMediaScope; store:BufferedMediaStore;
  isCurrent():boolean;
  request(method:'GET'|'POST',path:string,body?:Record<string,unknown>,signal?:AbortSignal):Promise<unknown>;
  retainAudio(chunk:AudioChunk,signal:AbortSignal):Promise<BufferedMediaLease>;
  // Existing retained handoff owner must confirm all its files are local before
  // the producer may retire them. This does not arm or finish audio playback.
  retainHandoff(chunk:AudioChunk,status:unknown,signal:AbortSignal):Promise<void>;
  retainContinuation?(chunk:AudioChunk,status:Status,timeline:SourceTimeline,signal:AbortSignal):Promise<void>;
  diagnose(event:string,fields:Record<string,number|string>):void;
};
type Retained = {
  chunk:AudioChunk; audio?:BufferedMediaLease; timeline?:SourceTimeline;
  status?:Status; raw?:unknown; leases:Map<number,BufferedMediaLease>;
  segments:Map<number,Segment>; complete:boolean; handoffRetained:boolean;continuationRetained?:boolean;
  reportedSource?:string;
};
const PREFIX='/api/dev/musetalk-live/';
const identity=(chunk:AudioChunk)=>({id:chunk.id,phone_request_id:chunk.phone_request_id!,url_path:chunk.url_path});

/** Delivery only. Uses the existing producer window and parsers, but never a
 * playback clock, player, native ticket, or heard/drained acknowledgement.
 */
export class MuseTalkBufferedDelivery {
  error:Error|null=null;
  private readonly abort=new AbortController();
  private readonly chunks=new Map<number,AudioChunk>();
  private readonly retained=new Map<string,Retained>();
  private readonly listeners=new Set<()=>void>();
  private work:Promise<void>|null=null;
  private closing:Promise<void>|null=null;
  private next=0;
  private prefetched=-1;
  private recoveryRevision=0;
  constructor(private readonly deps:Dependencies) {
    if(!/^[a-f0-9]{32}$/.test(deps.trialId))throw Error('Invalid buffered visual trial.');
  }
  get trialId():string {return this.deps.trialId;}
  ownsVideo(chunkId:string,uri:string):boolean {
    return !this.abort.signal.aborted && Array.from(this.retained.get(chunkId)?.segments.values() ?? []).some(row=>row.uri===uri)
      && this.deps.store.owns(this.deps.scope,uri);
  }
  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return()=>{this.listeners.delete(listener);};};
  private changed(){for(const listener of this.listeners)listener();}
  private check(){
    if(this.abort.signal.aborted)throw Error('Buffered visual delivery cancelled.');
    if(Date.now()>=this.deps.scope.expiresAt||!this.deps.isCurrent())throw Error('Buffered reply owner authority ended.');
  }
  private note(event:string,fields:Record<string,number|string>={}) {
    try{this.deps.diagnose(event,fields);}catch{/* Diagnostics do not own playback. */}
  }
  update(chunks:AudioChunk[]):void {
    if(this.abort.signal.aborted||this.error)return;
    for(const chunk of chunks) {
      if(chunk.phone_request_id!==this.deps.scope.replyId || !Number.isSafeInteger(chunk.sequence_index)
          || chunk.sequence_index!<0 || chunk.sequence_index!>=64 || !/^[A-Za-z0-9_.-]{1,256}$/.test(chunk.id)
          || chunk.url_path!==`/api/audio/file/${chunk.id}`)throw Error('Invalid buffered audio identity.');
      const prior=this.chunks.get(chunk.sequence_index!);
      if(prior && (prior.id!==chunk.id || prior.url_path!==chunk.url_path))throw Error('Buffered audio identity changed.');
      if(!prior)this.chunks.set(chunk.sequence_index!,{...chunk});
    }
    this.start();
  }
  private start() {
    if(this.work||this.abort.signal.aborted||this.error||!this.chunks.has(this.next))return;
    const work=this.run().catch(error=>{
      if(!this.abort.signal.aborted){this.error=error instanceof Error?error:Error('Buffered delivery failed.');
        const reason=this.error.message==='Invalid live visual status'?'invalid_status'
          :this.error.message==='Buffered source unavailable.'?'source_unavailable'
          :this.error.message==='Buffered idle source changed within its identity.'?'idle_identity_changed'
          :this.error.message==='Invalid buffered idle continuation.'?'invalid_continuation'
          :this.error.message==='Buffered media descriptor identity changed.'?'media_identity_changed'
          :this.error.message==='Buffered reply authority unavailable.'?'audio_authority_unavailable'
          :this.error.message==='Buffered source identity changed.'?'source_identity_changed'
          :this.error.message==='Buffered source timeline changed.'?'timeline_changed':'other';
        this.note('buffered_delivery_failed',{sequence:this.next,reason,
          ...(reason==='invalid_status'?{statusStage:liveStatusFailureStage(error)}:{})});this.changed();}
    }).finally(()=>{if(this.work===work){this.work=null;this.start();}});
    this.work=work;
  }
  private async wait(milliseconds=50) {
    this.check();
    await new Promise<void>(resolve=>{
      const done=()=>{clearTimeout(timer);this.abort.signal.removeEventListener('abort',done);resolve();};
      const timer=setTimeout(done,milliseconds);this.abort.signal.addEventListener('abort',done,{once:true});
    });
    this.check();
  }
  private async request(method:'GET'|'POST',route:string,body?:Record<string,unknown>) {
    this.check();
    const result=await this.network(()=>this.deps.request(method,PREFIX+route,body,this.abort.signal));
    this.check();return result;
  }
  private async network<T>(work:()=>Promise<T>):Promise<T>{
    let interrupted:number|null=null;
    for(;;){
      this.check();
      if(interrupted!==null&&performance.now()-interrupted>=90000)throw Error('Buffered delivery recovery deadline exceeded.');
      try{
        const result=await work();
        // Resource-returning callers release late leases after Stop. Do not
        // throw away their result here before they can detach/release it.
        if(interrupted!==null){this.recoveryRevision++;this.note('buffered_delivery_recovered',
          {sequence:this.next,waitMs:Math.round(performance.now()-interrupted)});}
        return result;
      }catch(error){
        this.check();
        if(!(error instanceof PeerTransportUnavailableError))throw error;
        if(interrupted===null){interrupted=performance.now();this.note('buffered_delivery_interrupted',{sequence:this.next});}
        await this.wait(250);
      }
    }
  }
  private accept(record:Retained,raw:unknown) {
    const status=parseLiveStatus(raw,this.deps.trialId,identity(record.chunk));
    if(record.status && (status.mediaId!==record.status.mediaId||status.frameCount!==record.status.frameCount)) {
      throw Error('Buffered source identity changed.');
    }
    if(record.status?.idleChunkReturn&&JSON.stringify(status.idleChunkReturn)!==JSON.stringify(record.status.idleChunkReturn))
      throw Error('Buffered idle source changed within its identity.');
    const source=(raw as {sourceTimeline?:unknown}).sourceTimeline;
    if(source!==undefined) {
      const timeline=parseSourceTimeline(source);
      if(timeline.sourceIndices.length!==status.frameCount)throw Error('Buffered source timeline length mismatch.');
      if(record.timeline && JSON.stringify(timeline)!==JSON.stringify(record.timeline))throw Error('Buffered source timeline changed.');
      record.timeline=timeline;
    }
    record.status=status;record.raw=raw;
    const state=status.sourceState==='matched'?'matched':'awaiting_identity';
    const continuation=status.idle?.continuationReady===true||status.idleChunkReturn?.continuationReady===true?1:0;
    const reportedSource=state+continuation;
    if(record.reportedSource!==reportedSource){
      record.reportedSource=reportedSource;
      this.note('buffered_source_state',{sequence:record.chunk.sequence_index!,state,continuation});
    }
    if(status.state==='unavailable'||status.failureStage)throw Error('Buffered source unavailable.');
  }
  private async run() {
    while(this.chunks.has(this.next)) {
      this.check();
      const chunk=this.chunks.get(this.next)!;
      let record=this.retained.get(chunk.id);
      if(!record) {
        record={chunk,leases:new Map(),segments:new Map(),complete:false,handoffRetained:false};
        this.retained.set(chunk.id,record);
        this.accept(record,await this.request('POST','prepare',{trialId:this.deps.trialId,audio:identity(chunk),currentIndex:0}));
      }
      let lastProgress=performance.now(),recovery=this.recoveryRevision;
      while(!record.complete) {
        this.check();
        if(recovery!==this.recoveryRevision){lastProgress=performance.now();recovery=this.recoveryRevision;}
        // Producer inactivity remains bounded independently of native playback.
        if(performance.now()-lastProgress>90000)throw Error('Buffered source deadline exceeded.');
        const status=record.status!;
        if(!record.handoffRetained && status.anticipation!==undefined) {
          // MuseTalk may be awaiting the rendezvous identity. Start the
          // existing progressive loop now, not after speech becomes ready.
          await this.deps.retainHandoff(chunk,record.raw,this.abort.signal);this.check();record.handoffRetained=true;
          lastProgress=performance.now();
        }
        if(status.sourceState==='awaiting_identity'||!record.timeline) {
          await this.wait();this.accept(record,await this.request('GET','status/'+this.deps.trialId));continue;
        }
        try {
          if(this.deps.retainContinuation&&!record.continuationRetained&&(status.idle?.continuationReady||status.idleChunkReturn?.continuationReady)){
            await this.network(()=>this.deps.retainContinuation!(chunk,status,record!.timeline!,this.abort.signal));this.check();
            record.continuationRetained=true;lastProgress=performance.now();
          }
          if(!record.audio) {
            const audio=await this.network(()=>this.deps.retainAudio(chunk,this.abort.signal));
            if(this.abort.signal.aborted){await audio.release();this.check();}
            record.audio=audio;
            lastProgress=performance.now();
            this.note('buffered_audio_downloaded',{sequence:this.next,bytes:audio.bytes});
          }
          const successor=this.chunks.get(this.next+1);
          if(successor && this.prefetched!==this.next+1) {
            await this.request('POST','prefetch',{trialId:this.deps.trialId,audio:identity(successor)});
            this.prefetched=this.next+1;
          }
          const available=status.segments.filter(row=>!record!.segments.has(row.index)&&row.state==='ready');
          // Use only the store's existing two bulk slots. Publish each retained
          // file immediately, but join both tasks before cursor advance/cleanup.
          for(let offset=0;offset<available.length;offset+=2) {
            const results=await Promise.allSettled(available.slice(offset,offset+2).map(async row=>{
              const downloadStarted=performance.now();
              const lease=await this.network(()=>this.deps.store.acquire(this.deps.scope,
                {id:`video-${status.mediaId}-${row.index}`,path:row.uri!,bytes:row.bytes!,contentType:'video/mp4'},this.abort.signal));
              if(this.abort.signal.aborted){await lease.release();this.check();}
              record.leases.set(row.index,lease);
              lastProgress=performance.now();
              record.segments.set(row.index,{index:row.index,startFrame:row.startFrame,frameCount:row.frameCount,uri:lease.uri,bytes:lease.bytes});
              this.note('buffered_video_downloaded',{sequence:this.next,index:row.index,bytes:lease.bytes,
                downloadMs:Math.min(120000,Math.max(0,Math.round(performance.now()-downloadStarted))),
                ...(row.encodeMs===undefined?{}:{videoBuildMs:row.encodeMs}),
                ...(row.publishedAfterClaimMs===undefined?{}:{publishedAfterClaimMs:row.publishedAfterClaimMs}),
                ...(row.sourceReadyAfterClaimMs===undefined?{}:{sourceReadyAfterClaimMs:row.sourceReadyAfterClaimMs})});this.changed();
            }));
            const rejected=results.filter((result):result is PromiseRejectedResult=>result.status==='rejected');
            const failed=rejected.find(result=>!(result.reason instanceof BufferedMediaCapacityError))??rejected[0];
            if(failed)throw failed.reason;
            if(offset+2<available.length&&(!this.deps.retainContinuation||record.continuationRetained)) {
              // Normal delivery has no anticipation branch to retain the
              // handoff. Finish that fence before reusing this first pair.
              if(!record.handoffRetained) {
                await this.deps.retainHandoff(chunk,record.raw,this.abort.signal);this.check();record.handoffRetained=true;
              }
              // Reuse producer slots as soon as their contiguous files are
              // local. Remaining downloads stay inside the new window.
              let retained=0;while(record.segments.has(retained))retained++;
              if(retained>0&&retained<status.segments.length)
                this.accept(record,await this.request('POST','prepare',
                  {trialId:this.deps.trialId,audio:identity(chunk),currentIndex:retained}));
            }
          }
        } catch(error) {
          if(!(error instanceof BufferedMediaCapacityError))throw error;
          await this.wait(100);lastProgress=performance.now();continue;
        }
        // Do not advance/retire the source while the existing handoff owner is
        // still progressively retaining its loop. Early segments remain usable.
        if(!record.handoffRetained) {
          await this.deps.retainHandoff(chunk,record.raw,this.abort.signal);this.check();record.handoffRetained=true;
        }
        let next=0;while(record.segments.has(next))next++;
        if(next===status.segments.length&&(!this.deps.retainContinuation||record.continuationRetained)) {record.complete=true;this.changed();break;}
        if(next===status.segments.length){await this.wait();this.accept(record,await this.request('GET','status/'+this.deps.trialId));continue;}
        if(status.segments[next]?.state==='unavailable')throw Error('Undelivered video retired by producer.');
        if(next>0 && status.segments[next-1]?.state==='ready') {
          this.accept(record,await this.request('POST','prepare',{trialId:this.deps.trialId,audio:identity(chunk),currentIndex:next}));
        } else {
          await this.wait();this.accept(record,await this.request('GET','status/'+this.deps.trialId));
        }
      }
      this.next++;
    }
  }
  prepared(chunkId:string):BufferedChunk|null {
    if(this.abort.signal.aborted)return null;
    const r=this.retained.get(chunkId);
    if(!r?.audio||!r.timeline||!r.status||!r.segments.size)return null;
    if(this.deps.retainContinuation&&!r.continuationRetained)return null;
    return {chunk:{...r.chunk},audio:r.audio,timeline:{...r.timeline,sourceIndices:[...r.timeline.sourceIndices]},
      segments:Array.from(r.segments.values()).map(row=>({...row})),complete:r.complete,
      status:{...r.status,audio:{...r.status.audio},segments:r.status.segments.map(row=>({...row}))}};
  }
  async acquireVideo(uri:string):Promise<{chunk:AudioChunk;segment:Segment;lease:BufferedMediaLease}> {
    this.check();
    for(const record of this.retained.values())for(const segment of record.segments.values())if(segment.uri===uri){
      const lease=await this.deps.store.acquire(this.deps.scope,{id:`video-${record.status!.mediaId}-${segment.index}`,
        path:`${PREFIX}segment/${record.status!.mediaId}/${String(segment.index).padStart(8,'0')}.mp4`,
        bytes:segment.bytes,contentType:'video/mp4'},this.abort.signal);
      return {chunk:{...record.chunk},segment:{...segment},lease};
    }
    throw Error('Buffered video reader source unavailable.');
  }
  /** Call only after the existing native players retire this chunk. */
  async release(chunkId:string):Promise<void> {
    const record=this.retained.get(chunkId);
    if(!record?.complete)throw Error('Cannot release a chunk still being delivered.');
    this.retained.delete(chunkId);
    await Promise.all([record.audio?.release(),...Array.from(record.leases.values(),lease=>lease.release())]);
  }
  /** Caller detaches native readers before closing their retained files. */
  close():Promise<void> {
    if(this.closing)return this.closing;
    this.abort.abort();
    this.closing=(async()=>{
      await this.work;
      const records=Array.from(this.retained.values());this.retained.clear();
      await Promise.all(records.flatMap(r=>[r.audio?.release(),...Array.from(r.leases.values(),lease=>lease.release())]));
      this.listeners.clear();
    })();
    return this.closing;
  }
}
