import type {VideoPlayer} from 'expo-video';
import type {RemoteClient} from '../api/client';
import type {AudioChunk} from '../api/types';
import {BufferedAudioDelivery} from '../relay/bufferedAudio';
import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import type {BufferedPresentation} from './bufferedPresentation';
import {MuseTalkBufferedDelivery} from '../dev/museTalkBufferedDelivery';
import type {MuseTalkLiveTrial} from '../dev/museTalkLiveTrial';
import type {BufferedCachedTransition} from './bufferedHandoff';
import type {BufferedVisualSource} from './bufferedHandoff';
import {peerMedia,isPeerMediaUrl,retainPeerMedia,PeerMediaCapacityError} from '../relay/media';
import {PeerTransportUnavailableError} from '../relay/peer';
import {downloadIdleFile} from '../dev/museTalkIdleFile';
import type {MuseTalkLiveSession} from '../dev/museTalkLiveSession';
import {IdleChunkPlayback} from './idleChunkPlayback';
import type {IdleChunkContinuation} from './idleChunkContinuation';

type VideoReader=Awaited<ReturnType<MuseTalkBufferedDelivery['acquireVideo']>>;
type ChunkIdleOwner={playback:IdleChunkPlayback;owner:string;output:BufferedPresentation;stop():Promise<void>};
type Dependencies={client():RemoteClient;current():boolean;reply(chunk:AudioChunk):BufferedReplyAuthority|null;
  replayAuthority?():{owner:string;ticket:string}|null;
  presentation():Promise<BufferedPresentation>;diagnose(event:string,fields:Record<string,number|string>):void;
  retainHandoff?(chunk:AudioChunk,status:unknown,signal:AbortSignal):Promise<void>};

/** Couples the existing guarded file players to the native cached compositor.
 * Neither this adapter nor delivery has permission to acknowledge playback. */
export class BufferedPlaybackRuntime {
  readonly audio:BufferedAudioDelivery;
  private closed=false;
  private readonly readers=new Set<()=>Promise<void>>();
  private closing:Promise<void>|null=null;
  private delivery:MuseTalkBufferedDelivery|null=null;
  private chunks:AudioChunk[]=[];
  private replyId='';
  private detachReply:(()=>void)|null=null;
  private detachDelivery:(()=>void)|null=null;
  private readonly finishedChunks=new Set<string>();
  private retiring:Promise<void>=Promise.resolve();
  private handoff:{chunk:AudioChunk;output:BufferedPresentation;transition:BufferedCachedTransition;signal:AbortSignal}|null=null;
  private readonly visualStarts=new Map<string,Promise<void>>();
  private readonly continuations=new Map<string,BufferedVisualSource>();
  private readonly chunkContinuations=new Map<string,IdleChunkContinuation>();
  private chunkIdle:ChunkIdleOwner|null=null;
  private chunkIdleDetached:Promise<void>=Promise.resolve();
  constructor(private readonly deps:Dependencies){
    this.audio=new BufferedAudioDelivery({peer:()=>deps.client().bufferedPeer,
      reply:chunk=>this.live()?deps.reply(chunk):null,replayAuthority:()=>this.live()?deps.replayAuthority?.()??null:null,
      presentation:deps.presentation,diagnose:deps.diagnose});
  }
  private live(){return !this.closed&&this.deps.current();}
  startIdleChunks(session:MuseTalkLiveSession,output:BufferedPresentation):{tick():Promise<void>;close():Promise<void>}{
    const peer=this.deps.client().bufferedPeer;
    if(!this.live()||this.chunkIdle||!peer||peer.closed||!peer.cacheScope)throw Error('Idle chunk playback owner unavailable.');
    const owner=peer.cacheScope,previousDetach=this.chunkIdleDetached;
    let holder:ChunkIdleOwner,stopping:Promise<void>|null=null;
    const current=()=>this.live()&&this.chunkIdle===holder
      &&(!this.deps.client().bufferedPeer||this.deps.client().bufferedPeer?.cacheScope===owner);
    const playback=new IdleChunkPlayback({session,output,current,
      request:(method,path,body,signal)=>{
        if(!current())return Promise.reject(Error('Idle chunk desktop owner ended.'));
        const now=this.deps.client().bufferedPeer;
        if(!now||now.closed)return Promise.reject(new PeerTransportUnavailableError('Idle chunk peer reconnecting.'));
        return this.deps.client().requestLiveVisual(method,path,body,signal);
      },retain:async(_status,row,signal)=>{
        const now=this.deps.client().bufferedPeer;
        if(!current()||!now||now.cacheScope!==owner)throw Error('Idle chunk desktop owner ended.');
        if(now.closed)throw new PeerTransportUnavailableError('Idle chunk peer reconnecting.');
        const file=await retainPeerMedia(now,row.uri!,{bytes:row.bytes!,contentType:'video/mp4'},signal);
        if(!current()||signal.aborted){await file.release();throw Error('Idle chunk desktop owner ended.');}
        return file;
      },retryable:error=>error instanceof PeerMediaCapacityError||error instanceof PeerTransportUnavailableError,
      diagnose:this.deps.diagnose});
    const stop=()=>{
      if(stopping)return stopping;
      if(this.chunkIdle===holder)this.chunkIdle=null;
      stopping=previousDetach.then(()=>output.endTransition()).then(()=>playback.close());
      this.chunkIdleDetached=stopping;return stopping;
    };
    holder={playback,owner,output,stop};this.chunkIdle=holder;
    return {tick:async()=>{await previousDetach;await playback.tick();},close:stop};
  }
  update(chunks:AudioChunk[]){
    this.chunks=chunks.map(chunk=>({...chunk}));
    this.delivery?.update(this.chunks.filter(chunk=>chunk.phone_request_id===this.replyId));
  }
  prepared(chunk:AudioChunk){return this.delivery?.prepared(chunk.id)??null;}
  prepareReply=async(trial:MuseTalkLiveTrial,chunk:AudioChunk,signal:AbortSignal):Promise<void>=>{
    if(!this.live()||signal.aborted)throw Error('Buffered reply owner ended.');
    if(this.delivery?.trialId===trial.snapshot.trialId&&this.replyId===chunk.phone_request_id)return;
    this.retireDelivery();await this.retiring;
    if(!this.live()||signal.aborted)throw Error('Buffered reply owner ended.');
    const scope=this.audio.scope(chunk);
    const delivery:MuseTalkBufferedDelivery=new MuseTalkBufferedDelivery({trialId:trial.snapshot.trialId,scope,store:this.audio.store,
      isCurrent:()=>this.live()&&this.delivery===delivery,
      request:(method,path,body,abort)=>this.deps.client().requestLiveVisual(method,path,body,abort),
      retainAudio:this.audio.acquire,retainHandoff:this.deps.retainHandoff??this.retainHandoff,
      retainContinuation:async(value,status,timeline,abort)=>{
        if(trial.snapshot.chunkedIdle&&!status.idleChunkReturn)throw Error('Buffered chunk continuation missing.');
        const output=await this.deps.presentation();
        if(status.idleChunkReturn){
          const owner=this.chunkIdle;
          if(!owner||owner.owner!==scope.owner||owner.output!==output||status.loopFadeMs===undefined)
            throw Error('Buffered chunk continuation owner unavailable.');
          let controller=this.chunkContinuations.get(value.id);
          if(!controller){
            controller=owner.playback.createReturn({trialId:delivery.trialId,returnSource:status.idleChunkReturn,timeline,fadeMs:status.loopFadeMs});
            this.chunkContinuations.set(value.id,controller);
          }
          await controller.retain(abort);
          if(!this.live()||abort.aborted||this.delivery!==delivery||this.chunkIdle!==owner)throw Error('Buffered idle owner ended.');
          return;
        }
        const idle=status.idle;if(!idle||status.loopFadeMs===undefined)throw Error('Buffered idle continuation missing.');
        const source=await output.retainContinuation(timeline,idle,status.loopFadeMs,async()=>{
          const peer=this.deps.client().bufferedPeer;
          if(!this.live()||abort.aborted||!peer||peer.cacheScope!==scope.owner)throw Error('Buffered idle owner ended.');
          const media=await peerMedia(peer,idle.uri,{},abort);
          return downloadIdleFile(media.url,idle.bytes,abort,uri=>isPeerMediaUrl(peer,uri));
        });
        if(!this.live()||abort.aborted||this.delivery!==delivery)throw Error('Buffered idle owner ended.');
        this.continuations.set(value.id,source);
      },diagnose:this.deps.diagnose});
    this.delivery=delivery;this.replyId=chunk.phone_request_id!;
    this.detachDelivery=delivery.subscribe(()=>this.releaseFinished());
    const stop=()=>{if(this.delivery===delivery)this.retireDelivery(signal.reason==='completed');};
    signal.addEventListener('abort',stop,{once:true});this.detachReply=()=>signal.removeEventListener('abort',stop);
    trial.attachBufferedDelivery(delivery);
    delivery.update([chunk,...this.chunks.filter(value=>value.phone_request_id===scope.replyId)]);
  };
  private retireDelivery(completed=false){
    this.detachReply?.();this.detachReply=null;
    this.detachDelivery?.();this.detachDelivery=null;this.finishedChunks.clear();
    const delivery=this.delivery;this.delivery=null;this.replyId='';
    this.visualStarts.clear();this.continuations.clear();
    const handoff=this.handoff;this.handoff=null;
    const chunkContinuations=Array.from(this.chunkContinuations.values());this.chunkContinuations.clear();
    const idleOwner=this.chunkIdle,previous=this.retiring;
    this.retiring=Promise.all([previous,delivery?.close(),handoff?.output.endTransition(completed)]).then(async()=>{
      // Prevent native fallback re-preparation before retiring any return pins.
      // Natural completion may transfer the actually selected silent reader;
      // the old reply/delivery itself still ends with its existing authority.
      if(idleOwner)await idleOwner.playback.finishReply(chunkContinuations,completed);
      else await Promise.all(chunkContinuations.map(controller=>controller.close()));
    });
  }
  retainHandoff=async(chunk:AudioChunk,status:unknown,signal:AbortSignal):Promise<void>=>{
    if(!this.live()||signal.aborted)throw Error('Buffered handoff owner unavailable.');
    const raw=status as {trialId:string;mediaId:string;anticipation:unknown};
    // Ordinary successor chunks have no anticipation plan. Their files may be
    // downloaded while the first chunk's retained transition remains active.
    if(raw.anticipation===undefined)return;
    if(this.handoff)throw Error('Buffered handoff already active.');
    const output=await this.deps.presentation(),authority=this.deps.reply(chunk);
    if(!this.live()||signal.aborted||!authority||!output.cachedSource)throw Error('Buffered cached handoff source unavailable.');
    const current=()=>this.live()&&!signal.aborted&&this.handoff?.chunk.id===chunk.id;
    const transition=output.beginTransition({scope:{handle:output.nativeHandle,generation:raw.trialId,
      ticket:authority.ticket,requestId:authority.scope.replyId,chunkId:chunk.id,key:this.audio.key(chunk)},current:()=>this.live()&&!signal.aborted,
      media:{resolve:async(path)=>{
        // Production may already be several chunks ahead. An opening is the
        // same immutable local segment that the normal speech player uses.
        for(const candidate of this.chunks){
          const ready=this.prepared(candidate);
          const segment=ready?.segments.find(row=>path===`/api/dev/musetalk-live/segment/${ready.status.mediaId}/${String(row.index).padStart(8,'0')}.mp4`);
          if(segment&&this.ownsLocalVideo(segment.uri))return {url:segment.uri};
        }
        const peer=this.deps.client().bufferedPeer;
        if(!current()||!peer||peer.cacheScope!==authority.scope.owner)throw Error('Buffered handoff transport owner ended.');
        return peerMedia(peer,path,{},signal);
      },owns:uri=>{
        if(current()&&this.ownsLocalVideo(uri))return true;
        const peer=this.deps.client().bufferedPeer;
        return Boolean(current()&&peer&&peer.cacheScope===authority.scope.owner&&isPeerMediaUrl(peer,uri));
      },copy:async(uri,bytes,abort,owns)=>{
        if(this.ownsLocalVideo(uri)){
          const reader=await this.delivery!.acquireVideo(uri);
          if(abort.aborted||!current()||reader.lease.bytes!==bytes){await reader.lease.release();throw Error('Buffered opening owner ended.');}
          return {uri:reader.lease.uri,release:()=>{void reader.lease.release();}};
        }
        return downloadIdleFile(uri,bytes,abort,owns);
      }},
      request:(method,path,body)=>this.deps.client().requestLiveVisual(method,path,body,signal),diagnose:this.deps.diagnose});
    this.handoff={chunk:{...chunk},output,transition,signal};
    await transition.retain({trialId:raw.trialId,mediaId:raw.mediaId,
      audio:{id:chunk.id,phone_request_id:authority.scope.replyId,url_path:chunk.url_path},plan:raw.anticipation as never});
    if(!current())throw Error('Buffered handoff owner ended.');
  };
  finished=(chunk:AudioChunk):void=>{
    this.audio.retire(chunk);
    if(!this.live()||chunk.phone_request_id!==this.replyId)return;
    this.finishedChunks.add(chunk.id);this.releaseFinished();
  };
  private releaseFinished(){
    const delivery=this.delivery;if(!delivery)return;
    for(const id of this.finishedChunks){
      if(!delivery.prepared(id)?.complete)continue;
      this.finishedChunks.delete(id);
      // Segment decoders/openings have their own pins. Releasing the delivery
      // backlog cannot unlink a file still read by native presentation.
      void delivery.release(id).catch(()=>this.deps.diagnose('buffered_completed_release_failed',{}));
    }
  }
  ownsLocalVideo=(uri:string):boolean=>this.live()&&this.chunks.some(chunk=>this.delivery?.ownsVideo(chunk.id,uri)===true);
  /** Called by the existing visual-start gate, after its silent audio binding
   * and the first local video decoder are ready, but before audio.play(). */
  beforePlayback=(chunk:AudioChunk,signal:AbortSignal):Promise<void>=>{
    const existing=this.visualStarts.get(chunk.id);if(existing)return existing;
    const delivery=this.delivery;let handoff=this.handoff;
    const live=()=>this.live()&&!signal.aborted&&Boolean(delivery)&&this.delivery===delivery
      &&(!handoff||!handoff.signal.aborted&&this.handoff===handoff);
    const check=()=>{
      if(!live())throw Error('Buffered visual start cancelled.');
      if(delivery?.error)throw delivery.error;
    };
    const wait=(ms:number)=>new Promise<void>((resolve,reject)=>{
      const done=()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);resolve();};
      const cancel=()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);reject(Error('Buffered visual start cancelled.'));};
      const timer=setTimeout(done,ms);signal.addEventListener('abort',cancel,{once:true});
      if(signal.aborted)cancel();
    });
    const work=(async()=>{
      check();const deadline=performance.now()+15000;
      let ready=this.prepared(chunk);
      // Ordinary successor chunks also need their own retained opening. Their
      // silent audio binding exists already, but is not permission to outrun
      // delivery and leave the next visual context without an identity.
      while(!ready?.segments.some(row=>row.index===0)){
        check();if(performance.now()>=deadline)throw Error('Buffered opening delivery timed out.');
        await wait(20);ready=this.prepared(chunk);
      }
      handoff=this.handoff;check();
      if(!handoff){
        if(this.chunkContinuations.has(chunk.id))throw Error('Buffered chunk handoff unavailable.');
        return;
      }
      const key=this.audio.key(chunk);
      const source=this.continuations.get(chunk.id),controller=this.chunkContinuations.get(chunk.id),owner=this.chunkIdle;
      if(!source&&!controller)throw Error('Buffered idle continuation unavailable.');
      const configure=async(action:(source:BufferedVisualSource)=>Promise<void>)=>{
        if(controller){
          if(!owner)throw Error('Buffered chunk continuation owner ended.');
          await controller.configure(action);check();await owner.playback.returnConfigured(controller);
        }else await action(source!);
        check();
      };
      if(chunk.id!==handoff.chunk.id){await configure(value=>handoff!.transition.next(key,ready!.timeline,value));check();return;}
      const segment=ready.segments.find(row=>row.index===0);
      if(!segment)throw Error('Buffered opening segment unavailable.');
      const opening={trialId:this.delivery!.trialId,mediaId:ready.status.mediaId,
        audio:{id:chunk.id,phone_request_id:chunk.phone_request_id,url_path:chunk.url_path},sourceTimeline:ready.timeline,
        segment:{...segment,index:0,startFrame:0,state:'ready',
          uri:`/api/dev/musetalk-live/segment/${ready.status.mediaId}/00000000.mp4`}};
      await configure(value=>handoff!.transition.prepare(opening,ready!.timeline,value));
      for(;;){
        check();if(performance.now()>=deadline)throw Error('Buffered native rendezvous timed out.');
        const began=performance.now(),delay=await handoff.transition.arm();check();
        const remaining=Math.floor(delay-(performance.now()-began));
        if(remaining>=500&&remaining<=2000){await wait(remaining);check();return;}
        await wait(20);
      }
    })().catch(error=>{
      // The optional visual caller deliberately releases audio on failure.
      // Preserve that contract, but expose this boundary without private text.
      const message=error instanceof Error?error.message:'';
      const stage=message==='Buffered chunk handoff unavailable.'?'chunk_handoff_missing'
        :message==='Buffered opening delivery timed out.'?'opening_timeout':'other';
      try{this.deps.diagnose('buffered_visual_start_failed',{stage});}catch{/* Diagnostics never replace the original failure. */}
      throw error;
    });
    this.visualStarts.set(chunk.id,work);return work;
  };
  retainLocalMedia=async(uri:string,signal:AbortSignal)=>{
    if(!this.live()||!this.delivery||signal.aborted)throw Error('Buffered video owner ended.');
    const reader=await this.delivery.acquireVideo(uri);
    if(!this.live()||signal.aborted){await reader.lease.release();throw Error('Buffered video owner ended.');}
    return reader.lease;
  };
  attachLocalVideo=async(player:VideoPlayer,_segment:unknown,uri:string)=>{
    if(!this.live()||!this.delivery)throw Error('Buffered video owner ended.');
    return this.bindVideoReader(player,await this.delivery.acquireVideo(uri));
  };
  async bindVideoReader(player:VideoPlayer,reader:VideoReader):Promise<()=>Promise<void>>{
    let nativeDetach:(()=>Promise<void>)|undefined,retirement:Promise<void>|null=null;
    let settled!:()=>void,unsafe=false;
    const attachment=new Promise<void>(resolve=>{settled=resolve;});
    const detach=()=>{
      if(!retirement)retirement=(async()=>{
        await attachment;
        if(unsafe)throw Error('Buffered video native reader is not detached.');
        await nativeDetach?.();
        // Clearing the actual decoder's source precedes unpinning its file.
        // The segment owner subsequently releases its ordinary player object.
        await player.replaceAsync(null);
        await reader.lease.release();this.readers.delete(detach);
      })();
      return retirement;
    };
    this.readers.add(detach);
    try{
      if(!this.live())throw Error('Buffered video owner ended.');
      const output=await this.deps.presentation(),key=this.audio.key(reader.chunk);
      const deadline=performance.now()+15000;
      while(!output.hasAudio(key)){
        if(!this.live()||performance.now()>=deadline)throw Error('Buffered video audio owner unavailable.');
        await new Promise(resolve=>setTimeout(resolve,20));
      }
      if(!this.live())throw Error('Buffered video owner ended.');
      nativeDetach=await output.attachVideo(player,key,reader.lease.uri,reader.segment.startFrame,reader.segment.frameCount);
      if(!this.live())throw Error('Buffered video owner ended.');
      settled();
      return detach;
    }catch(error){
      unsafe=(error as {nativeDetachPending?:boolean})?.nativeDetachPending===true;settled();
      if(unsafe)throw error;
      try{await detach();}catch{throw Object.assign(Error('Buffered video detachment unavailable.'),{nativeDetachPending:true});}
      throw error;
    }
  }
  close():Promise<void>{
    if(this.closing)return this.closing;
    this.closed=true;this.audio.close();this.retireDelivery();
    this.closing=Promise.all([this.retiring,...Array.from(this.readers,detach=>detach())])
      .then(async()=>{await this.chunkIdle?.stop();await this.chunkIdleDetached;});
    return this.closing;
  }
}
