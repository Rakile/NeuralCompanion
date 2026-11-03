import type {NativeAV} from '../relay/av';
import type {AudioPlayer} from 'expo-audio';
import type {VideoPlayer} from 'expo-video';
import type {IdleManifest,VerifiedLoop,VideoQuality} from '../relay/idleLoopCache';
import type {IdlePresentation} from '../relay/idleLoopSession';
import {PhoneHandoffSession} from '../utils/phonePresentation';
import type {PhonePresentationPosition} from '../utils/phonePresentation';
import {BufferedCachedTransition} from './bufferedHandoff';
import type {HandoffScope} from '../relay/retainedHandoff';
import type {OpeningMedia} from '../relay/speechOpening';
import type {SourceTimeline} from '../relay/frameHandoff';
import type {BufferedVisualSource} from './bufferedHandoff';
import type {IdleFile} from '../dev/museTalkIdleFile';
import type {IdleChunkStatus} from '../dev/idleChunkProtocol';
import {parseIdleChunkStatus} from '../dev/idleChunkProtocol';
import {IdleChunkNativeReader,supportsIdleChunkNative} from './idleChunkNativeReader';

type IdleAPI=Pick<NativeAV,'ncIdleVideoVersion'|'ncAVIdleClockVersion'|'ncAVIdleBegin'|'ncAVIdlePrepareFrame'
  |'ncAVIdleSelect'|'ncAVIdleClear'|'ncAVIdleDetachBegin'|'ncAVIdleDetachWait'|'ncAVIdlePosition'
  |'ncBufferedIdleChunksVersion'|'ncBufferedIdleChunkPrepare'|'ncBufferedIdleChunkAppend'|'ncBufferedIdleChunkSelect'
  |'ncBufferedIdleChunkDetachBegin'|'ncBufferedIdleChunkDetachWait'
  |'ncAVOpeningBegin'|'ncAVOpeningPrepare'|'ncAVOpeningDetachBegin'|'ncAVOpeningDetachWait'
  |'ncAVHandoffBegin'|'ncAVHandoffAppend'|'ncAVHandoffArm'|'ncAVHandoffNext'|'ncAVHandoffStatus'|'ncAVVisible'|'ncBufferedHandoffSource'>;
export type NativeBufferedPresentation=IdleAPI & {
  ncBufferedIdlePrepare(handle:string,generation:string,id:string,uri:string,fade:number,revision:number,sourceCount:number):Promise<boolean>;
  ncBufferedPresentationVersion():number;
  ncBufferedPresentationOpen():string|null;
  ncBufferedPresentationVisible(handle:string,enabled:boolean):boolean;
  ncBufferedPresentationClose(handle:string):void;
  ncBufferedAudioBind(handle:string,key:number,player:AudioPlayer,ticket:string,request:string,chunk:string,samples:number):Promise<boolean>;
  ncBufferedAudioRetire(handle:string,key:number):void;
  ncBufferedVideoBind(handle:string,key:number,player:VideoPlayer,uri:string,start:number,frames:number):Promise<string|null>;
  ncBufferedVideoRetire(handle:string,token:string):Promise<void>;
  ncBufferedVideoReady(handle:string,token:string):Promise<boolean>;
};
export type BufferedAudioBinding={key:number;ticket:string;requestId:string;chunkId:string;validSamples:number};
export type TransientIdle={uri:string;generation:string;id:string;fadeMs:number;
  source:{avatar_id:string;motion_id:string;source_frame_count:number}};
type TransitionOptions={scope:HandoffScope;current:()=>boolean;media:OpeningMedia;
  request(method:'POST',path:string,body:Record<string,unknown>):Promise<unknown>;
  diagnose(event:string,fields:Record<string,number|string>):void};
export type PresentationChunkReader=Pick<IdleChunkNativeReader,'prepare'|'append'|'configure'|'select'|'position'|'close'|'renew'>;
type ChunkReaderOwner={status:IdleChunkStatus;reader:IdleChunkNativeReader};

/** The existing cache/presentation contract, without an RTP peer or audio owner.
 * The caller's scope survives transport replacement but not account/desktop
 * replacement. Native decoders are detached before cache leases may be deleted.
 */
export class BufferedPresentation implements IdlePresentation {
  private closed=false;
  private wanted=false;
  private revision=0;
  private prepared='';
  private selected='';
  private file:VerifiedLoop|null=null;
  private manifest:IdleManifest|null=null;
  private transient:TransientIdle|null=null;
  private detached:Promise<void>=Promise.resolve();
  private closing:Promise<void>|null=null;
  private readonly handoff=new PhoneHandoffSession(()=>this.readIdlePosition());
  private readonly audioBindings=new Map<number,()=>void>();
  private readonly videoBindings=new Set<()=>Promise<void>>();
  private transition:BufferedCachedTransition|null=null;
  private transitionDetach:Promise<void>|null=null;
  private lastTransitionKey=0;
  private readonly continuations=new Map<string,{value:BufferedVisualSource;source:TransientIdle['source'];bytes:number;release?:()=>void}>();
  private chunkNativeRevision=0;
  private readonly chunkReaders=new Map<string,ChunkReaderOwner>();
  private constructor(readonly nativeHandle:string,private readonly native:NativeBufferedPresentation,
    private readonly current:()=>boolean,private readonly quality:()=>VideoQuality|null,
    private readonly acknowledge:(manifest:IdleManifest,ready:boolean)=>Promise<void>,private readonly busy:()=>boolean,
    private readonly cachedFile:(id:string)=>Promise<VerifiedLoop|null>){}

  static open(native:NativeBufferedPresentation,current:()=>boolean,quality:()=>VideoQuality|null,
    acknowledge:(manifest:IdleManifest,ready:boolean)=>Promise<void>,busy:()=>boolean=()=>false,
    cachedFile:(id:string)=>Promise<VerifiedLoop|null>=async()=>null):BufferedPresentation {
    if(!current() || native.ncBufferedPresentationVersion?.()!==1 || native.ncIdleVideoVersion?.()!==1
      || native.ncAVIdleClockVersion?.()!==1 || !['ncBufferedPresentationOpen','ncBufferedPresentationVisible',
        'ncBufferedPresentationClose','ncAVIdleBegin','ncAVIdlePrepareFrame','ncAVIdleSelect',
        'ncAVIdleDetachBegin','ncAVIdleDetachWait','ncAVIdlePosition'].every(key=>typeof (native as any)[key]==='function'))
      throw Error('Update NC Remote for buffered native presentation.');
    const handle=native.ncBufferedPresentationOpen();
    if(!handle)throw Error('Buffered native presentation unavailable.');
    return new BufferedPresentation(handle,native,current,quality,acknowledge,busy,cachedFile);
  }
  private live(){return !this.closed&&this.current();}
  async attachAudio(player:AudioPlayer,binding:BufferedAudioBinding):Promise<()=>void> {
    if(!this.live())throw Error('Buffered presentation owner ended.');
    if(!Number.isSafeInteger(binding.key)||binding.key<1||binding.key>0x7fffffff
      ||!Number.isSafeInteger(binding.validSamples)||binding.validSamples<1||binding.validSamples>28800000
      ||[binding.ticket,binding.requestId,binding.chunkId].some(value=>!value||value.length>128)
      ||this.audioBindings.has(binding.key))throw Error('Invalid buffered audio binding.');
    let removed=false;
    const detach=()=>{
      if(removed)return;removed=true;
      this.audioBindings.delete(binding.key);
      this.native.ncBufferedAudioRetire(this.nativeHandle,binding.key);
    };
    this.audioBindings.set(binding.key,detach);
    try {
      const ready=await this.native.ncBufferedAudioBind(this.nativeHandle,binding.key,player,binding.ticket,
        binding.requestId,binding.chunkId,binding.validSamples);
      if(!ready||!this.live()||removed)throw Error('Buffered native audio observation unavailable.');
      return detach;
    } catch(error) { detach();throw error; }
  }
  get presentationActive(){return this.live()&&this.wanted;}
  get visible(){return this.presentationActive&&this.native.ncAVVisible?.(this.nativeHandle)===true;}
  private returnedIdle(){
    if(!this.presentationActive)return null;
    const position=this.native.ncAVIdlePosition!(this.nativeHandle) as {generation?:string;id?:string;sourceCount?:number}|null;
    return Array.from(this.continuations.values()).find(row=>position?.generation===row.value.idleGeneration
      &&position.id===row.value.idleId&&position.sourceCount===row.source.source_frame_count)??null;
  }
  private chunkQualityMatches(status:IdleChunkStatus){
    const quality=this.quality(),value=status.videoQuality;
    return Boolean(quality&&value.video_kbps===quality.video_kbps&&value.video_width===quality.video_width&&value.video_fps===quality.video_fps);
  }
  private displayedChunks():ChunkReaderOwner|null {
    if(!this.presentationActive)return null;
    // A return may already be retained/configured. Only an observed native
    // current identity, not this metadata map, makes it the displayed source.
    return Array.from(this.chunkReaders.values()).find(owner=>this.chunkQualityMatches(owner.status)&&owner.reader.position())??null;
  }
  get cachedSource(){
    if(!this.presentationActive)return null;
    const chunk=this.displayedChunks()?.status;
    return chunk?{avatar_id:chunk.avatarId,motion_id:chunk.motionId,source_frame_count:chunk.sourceFrameCount}
      :this.returnedIdle()?.source??this.transient?.source??(this.file?this.manifest?.active_source:null)??null;
  }
  get cachedGeneration(){return this.manifest?.generation??'';}
  get videoQuality(){return this.quality();}
  get idleChunksSupported(){return this.live()&&supportsIdleChunkNative(this.native);}
  async createIdleChunkReader(value:IdleChunkStatus,fadeMs:number,current:()=>boolean):Promise<PresentationChunkReader>{
    const status=parseIdleChunkStatus({...value,state:'ready'},value.trialId,value.requestId);
    if(!status||status.cursor!==0)throw Error('Invalid initial idle chunk reader.');
    if(!supportsIdleChunkNative(this.native))throw Error('Update NC Remote for native idle chunks.');
    if(!this.chunkQualityMatches(status))throw Error('Idle chunk quality changed.');
    const revision=this.revision;
    const check=()=>{
      if(!this.presentationActive||!current()||revision!==this.revision||this.file||this.manifest||this.transient)
        throw Error('Idle chunk presentation owner unavailable.');
      if(!this.chunkQualityMatches(status))throw Error('Idle chunk quality changed.');
    };
    check();await this.detached;check();
    if(this.chunkReaders.has(status.mediaId)||this.chunkReaders.size>=6)throw Error('Idle chunk reader capacity unavailable.');
    // Keep one presentation revision for displayed and prospective readers.
    // Calling idleBegin for every return would revoke the current append queue.
    if(!this.chunkNativeRevision){
      const nativeRevision=this.native.ncAVIdleBegin!(this.nativeHandle);
      if(!Number.isSafeInteger(nativeRevision)||nativeRevision<1)throw Error('Idle chunk native revision unavailable.');
      this.chunkNativeRevision=nativeRevision;
    }
    let owner:ChunkReaderOwner;
    const reader=new IdleChunkNativeReader(this.native,this.nativeHandle,this.chunkNativeRevision,
      ()=>this.presentationActive&&current()&&revision===this.revision&&this.chunkQualityMatches(status)
        &&this.chunkReaders.get(status.mediaId)===owner,fadeMs);
    owner={status,reader};this.chunkReaders.set(status.mediaId,owner);
    const identity=(source:IdleChunkStatus)=>JSON.stringify([source.trialId,source.requestId,source.mediaId,source.motionId,
      source.avatarId,source.sourceFrameCount,source.startFrame,source.videoQuality]);
    const same=(source:IdleChunkStatus)=>{
      if(identity(source)!==identity(status))throw Error('Idle chunk reader source changed.');
    };
    return {
      prepare:(source,row,file)=>{same(source);return reader.prepare(source,row,file);},
      append:(source,row,file)=>{same(source);return reader.append(source,row,file);},
      configure:(source,action)=>{same(source);return reader.configure(source,action);},
      renew:(source,offset,isCurrent)=>reader.renew(source,offset,isCurrent),
      select:()=>reader.select(),position:()=>reader.position(),
      close:async()=>{const safe=await reader.close();if(safe&&this.chunkReaders.get(status.mediaId)===owner)this.chunkReaders.delete(status.mediaId);return safe;},
    };
  }
  async retainContinuation(timeline:SourceTimeline,idle:{motionId?:string;avatarId?:string;frameCount:number;startFrame:number;continuationReady?:boolean;bytes:number},
    fadeMs:number,load:()=>Promise<IdleFile>):Promise<BufferedVisualSource>{
    const revision=this.revision,manifest=this.manifest;
    const check=()=>{if(!this.presentationActive||revision!==this.revision)throw Error('Buffered idle continuation owner ended.');};
    check();
    if(idle.motionId!==timeline.motionId||idle.frameCount!==timeline.sourceFrameCount||idle.continuationReady!==true
      ||!idle.avatarId||!Number.isSafeInteger(idle.startFrame)||idle.startFrame<0||idle.startFrame>=idle.frameCount
      ||!Number.isSafeInteger(fadeMs)||fadeMs<0||fadeMs>5000)throw Error('Invalid buffered idle continuation.');
    const key=JSON.stringify([manifest?.generation??this.transient?.generation,this.videoQuality,timeline.motionId]);
    let retained=this.continuations.get(key);
    if(retained&&retained.source.source_frame_count!==idle.frameCount)throw Error('Buffered idle source changed within its identity.');
    if(!retained){
      const binding=manifest?.sources?.find(row=>row.motion_id===timeline.motionId&&row.source_frame_count===idle.frameCount&&row.avatar_id===idle.avatarId)
        ??(manifest?.active_source?.motion_id===timeline.motionId&&manifest.active_source.source_frame_count===idle.frameCount
          &&manifest.active_source.avatar_id===idle.avatarId?manifest.active_source:null);
      let file=binding?(this.file?.id===binding.loop_id?this.file:await this.cachedFile(binding.loop_id)):null;check();
      const row=manifest?.loops?.find(row=>row.id===binding?.loop_id&&row.status==='ready');
      if(file&&(file.generation!==this.file?.generation||file.id!==binding?.loop_id||!row||row.status!=='ready'
        ||file.sha256!==row.sha256||file.bytes!==row.bytes))file=null;
      let release:(()=>void)|undefined,uri=file?.uri,generation=file?.generation,id=file?.id,sha=file?.sha256??'';
      if(!uri&&this.transient?.source.motion_id===timeline.motionId&&this.transient.source.source_frame_count===idle.frameCount){
        uri=this.transient.uri;generation=this.transient.generation;id=this.transient.id;
      }
      if(!uri){
        if(this.continuations.size>=96||Array.from(this.continuations.values()).reduce((n,row)=>n+row.bytes,0)+idle.bytes>192*1024*1024)
          throw Error('Buffered idle continuation capacity reached.');
        const downloaded=await load();
        try{check();}catch(error){downloaded.release();throw error;}
        uri=downloaded.uri;release=downloaded.release;generation=this.file?.generation??this.transient?.generation??'buffered';id=timeline.motionId;
      }
      retained={value:{motionId:timeline.motionId,sourceFrameCount:timeline.sourceFrameCount,sourceIndices:[],
        idleGeneration:generation!,idleId:id!,idleUri:uri,idleSha:sha,startFrame:idle.startFrame,fadeMs},
        source:{avatar_id:idle.avatarId,motion_id:timeline.motionId,source_frame_count:idle.frameCount},bytes:release?idle.bytes:0,release};
      this.continuations.set(key,retained);
    }
    return {...retained.value,sourceIndices:[...timeline.sourceIndices],startFrame:idle.startFrame,fadeMs};
  }
  hasAudio(key:number){return this.live()&&this.audioBindings.has(key);}
  async attachVideo(player:VideoPlayer,key:number,uri:string,start:number,frames:number):Promise<()=>Promise<void>> {
    if(!this.live()||!this.audioBindings.has(key))throw Error('Buffered video audio owner unavailable.');
    if(!uri.startsWith('file://')||!Number.isSafeInteger(start)||start<0||!Number.isSafeInteger(frames)
      ||frames<1||frames>1440||start+frames>14400)throw Error('Invalid buffered local video.');
    let token:string|null=null,retirement:Promise<void>|null=null;
    const attached=this.native.ncBufferedVideoBind(this.nativeHandle,key,player,uri,start,frames);
    const detach=():Promise<void>=>{
      if(!retirement)retirement=attached.then(value=>value?this.native.ncBufferedVideoRetire(this.nativeHandle,value):undefined,()=>undefined)
        .then(()=>{this.videoBindings.delete(detach);});
      return retirement;
    };
    this.videoBindings.add(detach);
    try {
      token=await attached;
      if(!token||!this.live()||!this.audioBindings.has(key)||retirement)throw Error('Buffered video owner ended.');
      const deadline=performance.now()+2500;
      while(!await this.native.ncBufferedVideoReady(this.nativeHandle,token)){
        if(!this.live()||!this.audioBindings.has(key)||retirement||performance.now()>=deadline)
          throw Error('Buffered video first decoded frame unavailable.');
        await new Promise(resolve=>setTimeout(resolve,20));
      }
      if(!this.live()||!this.audioBindings.has(key)||retirement)throw Error('Buffered video owner ended.');
      return detach;
    } catch(error) {
      try{await detach();}catch{throw Object.assign(Error('Buffered video detachment unavailable.'),{nativeDetachPending:true});}
      throw error;
    }
  }
  get idleSupported(){return this.live();}
  get idleClockSupported(){return this.live();}
  get qualityBusy(){return Boolean(this.transition||this.transitionDetach||this.audioBindings.size)||this.busy();}
  // A cold first reply may already have a silent audio binding while the
  // initial idle file is loading. Allow that first source to become ready;
  // protect an existing source from replacement throughout speech preparation.
  get idleBusy(){return Boolean(this.transition||this.transitionDetach||(this.cachedSource&&this.audioBindings.size))||this.busy();}
  beginTransition(options:TransitionOptions):BufferedCachedTransition {
    const source=this.cachedSource,manifest=this.manifest,transient=this.transient,chunk=this.displayedChunks(),revision=this.revision;
    if(!this.presentationActive||!options.current()||!source||(!chunk&&!transient&&(!manifest||!this.idleQualityMatches(manifest)))
      ||this.transition||this.transitionDetach||options.scope.handle!==this.nativeHandle
      ||!Number.isSafeInteger(options.scope.key)||options.scope.key<=this.lastTransitionKey)
      throw Error('Buffered cached transition unavailable.');
    const transition:BufferedCachedTransition=new BufferedCachedTransition({...options,native:this.native,
      source:{avatarId:source.avatar_id,motionId:source.motion_id,sourceFrameCount:source.source_frame_count},
      claim:plan=>this.handoff.claim(plan),
      live:()=>this.presentationActive&&options.current()&&this.transition===transition
        &&revision===this.revision&&this.transient===transient&&this.manifest===manifest
        &&(!manifest||this.idleQualityMatches(manifest))&&(!chunk||this.chunkQualityMatches(chunk.status))});
    this.lastTransitionKey=options.scope.key;
    this.transition=transition;return transition;
  }
  endTransition(completed=false):Promise<void>{
    if(this.transitionDetach)return this.transitionDetach;
    const transition=this.transition;
    if(!transition)return Promise.resolve();
    // Invalidate first, then wait for the same native fence used by both the
    // retained loop and opening. Never replace/delete the idle source under it.
    this.transition=null;
    const work=(async()=>{
      // Reuse the previous player's bounded visual-only return wait. Native
      // audio completion has already happened; this grants no audio lifetime.
      if(completed){
        const deadline=Date.now()+3000;
        while(this.presentationActive&&Date.now()<deadline){
          const status=this.native.ncAVHandoffStatus?.(this.nativeHandle) as {state?:string}|null;
          if(!status||['returned','ended','degraded'].includes(String(status.state)))break;
          await new Promise(resolve=>setTimeout(resolve,20));
        }
      }
      if(!await transition.close())throw Error('Buffered handoff detachment unavailable.');
    })();
    this.transitionDetach=work;
    void work.then(()=>{if(this.transitionDetach===work)this.transitionDetach=null;},()=>undefined);
    return work;
  }
  handoffExchange(){return this.cachedSource?this.handoff.exchange():null;}
  async prepareTransientIdle(value:TransientIdle):Promise<boolean>{
    if(!/^file:\/\/.+\/nc_musetalk_idle_[^/]+\.mp4$/.test(value.uri)||!value.generation
      ||!value.source.avatar_id||!/^[a-f0-9]{64}$/.test(value.id)||value.id!==value.source.motion_id
      ||!Number.isSafeInteger(value.source.source_frame_count)||value.source.source_frame_count<1||value.source.source_frame_count>1440
      ||!Number.isSafeInteger(value.fadeMs)||value.fadeMs<0||value.fadeMs>5000)throw Error('Invalid temporary idle source.');
    if(!this.presentationActive||this.idleBusy||this.chunkReaders.size)return false;
    await this.detached;
    if(!this.presentationActive||this.idleBusy||this.chunkReaders.size)return false;
    if(this.transient?.generation===value.generation&&this.transient.id===value.id)return true;
    const revision=++this.revision,nativeRevision=this.native.ncAVIdleBegin!(this.nativeHandle);
    if(!nativeRevision||!await this.native.ncBufferedIdlePrepare(this.nativeHandle,value.generation,value.id,value.uri,
      value.fadeMs,nativeRevision,value.source.source_frame_count)||revision!==this.revision||!this.presentationActive)return false;
    if(!await this.native.ncAVIdleSelect!(this.nativeHandle,value.generation,value.id)||revision!==this.revision||!this.presentationActive)return false;
    this.handoff.clear();this.file=null;this.manifest=null;this.prepared=this.selected='';
    this.transient={...value,source:{...value.source}};return true;
  }
  idleQualityMatches(manifest:IdleManifest):boolean {
    const value=manifest.video_quality,quality=this.quality();
    return !value||Boolean(quality&&value.video_kbps===quality.video_kbps&&value.video_width===quality.video_width&&value.video_fps===quality.video_fps);
  }
  private key(file:VerifiedLoop,manifest:IdleManifest){
    return JSON.stringify([this.nativeHandle,file.generation,file.id,file.sha256,manifest.generation,manifest.active_source]);
  }
  async present(enabled:boolean):Promise<void>{
    if(!this.live())throw Error('Buffered presentation owner ended.');
    this.wanted=enabled;
    if(!this.native.ncBufferedPresentationVisible(this.nativeHandle,enabled))throw Error('Buffered presentation unavailable.');
    if(!enabled)await this.clearIdle();
  }
  async prepareIdle(file:VerifiedLoop,manifest:IdleManifest):Promise<boolean>{
    if(!this.presentationActive||this.transition||this.transitionDetach||this.chunkReaders.size||file.id!==manifest.active_loop||!manifest.active_source||!this.idleQualityMatches(manifest))return false;
    this.prepared='';
    const revision=++this.revision,nativeRevision=this.native.ncAVIdleBegin!(this.nativeHandle);
    if(!Number.isSafeInteger(nativeRevision)||nativeRevision<=0)return false;
    const ready=await this.native.ncAVIdlePrepareFrame!(this.nativeHandle,file.generation,file.id,file.sha256,
      manifest.fade_ms,nativeRevision,manifest.active_source.source_frame_count);
    if(!this.presentationActive||revision!==this.revision)return false;
    if(ready)this.prepared=this.key(file,manifest);
    return ready===true;
  }
  async selectIdle(file:VerifiedLoop,manifest:IdleManifest):Promise<boolean>{
    const key=this.key(file,manifest),revision=this.revision;
    if(!this.presentationActive||this.prepared!==key||!this.idleQualityMatches(manifest))return false;
    if(this.selected===key)return true;
    if(this.transition||this.transitionDetach)return false;
    if(!await this.native.ncAVIdleSelect!(this.nativeHandle,file.generation,file.id)
      ||!this.presentationActive||revision!==this.revision)return false;
    this.handoff.clear();this.selected=key;this.file=file;this.manifest=manifest;this.transient=null;
    return true;
  }
  readIdlePosition():PhonePresentationPosition|null {
    const chunk=this.displayedChunks()?.status,returned=chunk?null:this.returnedIdle();
    const file=chunk?{generation:chunk.trialId,id:chunk.motionId}
      :returned?{generation:returned.value.idleGeneration,id:returned.value.idleId}:this.transient??this.file,binding=this.cachedSource;
    if(!this.presentationActive||!file||!binding)return null;
    const value=this.native.ncAVIdlePosition!(this.nativeHandle) as Record<string,unknown>|null;
    if(!value||value.generation!==file.generation||value.id!==file.id||value.sourceCount!==binding.source_frame_count
      ||chunk&&(value.mediaId!==chunk.mediaId||value.chunked!==true)
      ||value.visible!==true||typeof value.paused!=='boolean'||typeof value.mediaId!=='string'||!/^[a-f0-9]{32}$/.test(value.mediaId)
      ||!Number.isSafeInteger(value.sourceFrame)||Number(value.sourceFrame)<0||Number(value.sourceFrame)>=binding.source_frame_count
      ||typeof value.ageMs!=='number'||!Number.isFinite(value.ageMs)||value.ageMs<0||value.ageMs>250)return null;
    return {avatarId:binding.avatar_id,mediaId:value.mediaId,sourceFrameCount:binding.source_frame_count,
      sourceFrame:Number(value.sourceFrame),fps:24,playing:!value.paused};
  }
  async acknowledgeIdle(manifest:IdleManifest,ready:boolean):Promise<void>{
    if(!this.live())throw Error('Buffered presentation owner ended.');
    if(ready&&(!this.presentationActive||!this.selected||this.manifest?.generation!==manifest.generation
      ||this.manifest?.active_loop!==manifest.active_loop||!this.idleQualityMatches(manifest)))throw Error('Idle decoded selection unavailable.');
    await this.acknowledge(manifest,ready);
  }
  clearIdle():Promise<void>{
    this.handoff.clear();++this.revision;this.prepared=this.selected='';
    const manifest=this.manifest;this.file=null;this.manifest=null;this.transient=null;
    const transitionDetached=this.endTransition();
    const chunkReaders=Array.from(this.chunkReaders.values());
    const next=transitionDetached.then(async()=>{
      // End the transition first so it cannot re-prepare a return behind the
      // scoped clear. Reader.close joins all outstanding native offers.
      for(const owner of chunkReaders){
        if(!await owner.reader.close())throw Error('Idle chunk decoder detachment unavailable.');
        if(this.chunkReaders.get(owner.status.mediaId)===owner)this.chunkReaders.delete(owner.status.mediaId);
      }
      const ticket=this.native.ncAVIdleDetachBegin!(this.nativeHandle);
      const safe=ticket?await this.native.ncAVIdleDetachWait!(ticket):false;
      if(safe)this.chunkNativeRevision=0;
      return safe;
    });
    this.detached=Promise.all([this.detached,next]).then(([,safe])=>{if(!safe)throw Error('Idle decoder detachment unavailable.');});
    const retained=Array.from(this.continuations.values());this.continuations.clear();
    this.detached=this.detached.then(()=>{for(const row of retained)row.release?.();});
    void this.detached.catch(()=>undefined);
    if(manifest&&this.live())void this.acknowledge(manifest,false).catch(()=>undefined);
    return this.detached;
  }
  close():Promise<void>{
    if(this.closing)return this.closing;
    this.closed=true;this.wanted=false;this.native.ncBufferedPresentationVisible(this.nativeHandle,false);
    for(const detach of this.audioBindings.values())detach();
    this.closing=Promise.all([this.clearIdle(),...Array.from(this.videoBindings,detach=>detach())])
      .then(()=>{this.native.ncBufferedPresentationClose(this.nativeHandle);});
    return this.closing;
  }
}
