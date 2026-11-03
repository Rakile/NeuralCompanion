import type {NativeAV} from '../relay/av';
import {RetainedHandoffSession} from '../relay/retainedHandoff';
import type {HandoffScope,HandoffDescriptor} from '../relay/retainedHandoff';
import {SpeechOpeningSession} from '../relay/speechOpening';
import type {OpeningMedia} from '../relay/speechOpening';
import {parseSourceTimeline} from '../relay/frameHandoff';
import type {SourceTimeline} from '../relay/frameHandoff';
import {parseAnticipationStatus} from '../dev/museTalkLiveTrial';
import type {NativeIdleChunkFile} from './idleChunkNativeReader';
import type {NativeIdleChunkAPI} from './idleChunkNativeReader';
import {supportsIdleChunkNative} from './idleChunkNativeReader';
import {validateChunkVisualSource} from './idleChunkVisualSource';

export type BufferedVisualSource={motionId:string;sourceFrameCount:number;sourceIndices:number[];
  idleGeneration:string;idleId:string;idleUri:string;idleSha:string;startFrame:number;fadeMs:number;
  idleChunks?:{mediaId:string;files:NativeIdleChunkFile[]}};

type Native=Pick<NativeAV,'ncAVOpeningBegin'|'ncAVOpeningPrepare'|'ncAVOpeningDetachBegin'|'ncAVOpeningDetachWait'
  |'ncAVHandoffBegin'|'ncAVHandoffAppend'|'ncAVHandoffArm'|'ncAVHandoffNext'|'ncBufferedHandoffSource'> & NativeIdleChunkAPI;
type Dependencies={scope:HandoffScope;native:Native;live:()=>boolean;
  source:{avatarId:string;motionId:string;sourceFrameCount:number};media:OpeningMedia;
  claim:(plan:HandoffDescriptor['plan'])=>boolean;
  request(method:'POST',path:string,body:Record<string,unknown>):Promise<unknown>;
  diagnose(event:string,fields:Record<string,number|string>):void};

/** Reconnects the existing retained-loop and decoded-opening sessions to local
 * file playback. No new choreography, audio player, or delivery acknowledgement. */
export class BufferedCachedTransition {
  private closed=false;
  private revision=0;
  private retained:RetainedHandoffSession|null=null;
  private opening:SpeechOpeningSession|null=null;
  private retention:Promise<void>|null=null;
  private detached:Promise<boolean>|null=null;
  private closing:Promise<boolean>|null=null;
  constructor(private readonly deps:Dependencies){}
  private live=()=>!this.closed&&this.deps.live();
  private check(){if(!this.live())throw Error('Buffered handoff owner ended.');}
  private detach=():Promise<boolean>=>{
    if(!this.detached){
      const {native,scope}=this.deps;
      const ticket=this.revision?native.ncAVOpeningDetachBegin!(scope.handle,scope.key):null;
      this.detached=this.revision?(ticket?native.ncAVOpeningDetachWait!(ticket):Promise.resolve(false)):Promise.resolve(true);
    }
    return this.detached;
  };
  retain(value:HandoffDescriptor):Promise<void>{
    if(this.retention)return this.retention;
    this.retention=this.begin(value).catch(error=>{void this.close();throw error;});
    return this.retention;
  }
  private async begin(value:HandoffDescriptor){
    this.check();
    const {native,scope,source,media}=this.deps,plan=parseAnticipationStatus(value.plan);
    if(plan.avatarId!==source.avatarId||plan.sourceFrameCount!==source.sourceFrameCount||!this.deps.claim(plan))
      throw Error('Buffered handoff source or mobile agreement changed.');
    this.revision=native.ncAVOpeningBegin!(scope.handle,scope.key);
    if(!Number.isSafeInteger(this.revision)||this.revision<=0)throw Error('Buffered handoff native revision unavailable.');
    if(!await native.ncAVHandoffBegin!(scope.handle,scope.key,this.revision,scope.generation,plan.planId,
      plan.sourceFrameCount,plan.sourceIndices))throw Error('Buffered handoff native preparation unavailable.');
    this.check();
    this.retained=new RetainedHandoffSession({...media,live:this.live,request:this.deps.request,
      onSegment:async(index,file)=>{
        this.check();
        if(!await native.ncAVHandoffAppend!(scope.handle,scope.key,this.revision,index,file.uri))
          throw Error('Buffered handoff append unavailable.');
        this.check();
      },detach:async()=>{if(!await this.detach())throw Error('Buffered handoff detach unavailable.');},diagnose:this.deps.diagnose});
    await this.retained.start(scope,value);this.check();
  }
  private timeline(value:SourceTimeline){
    const timeline=parseSourceTimeline(value),source=this.deps.source;
    if(timeline.motionId!==source.motionId||timeline.sourceFrameCount!==source.sourceFrameCount)
      throw Error('Buffered handoff source changed.');
    return timeline;
  }
  private async configure(key:number,timeline:SourceTimeline,source:BufferedVisualSource){
    if(source.motionId!==timeline.motionId||source.sourceFrameCount!==timeline.sourceFrameCount
      ||JSON.stringify(source.sourceIndices)!==JSON.stringify(timeline.sourceIndices)
      ||!source.idleUri.startsWith('file://')||!/^[a-f0-9]{64}$/.test(source.idleId)
      ||!Number.isSafeInteger(source.startFrame)||source.startFrame<0||source.startFrame>=timeline.sourceFrameCount
      ||!Number.isSafeInteger(source.fadeMs)||source.fadeMs<0||source.fadeMs>5000)
      throw Error('Buffered visual source mismatch.');
    const {scope,native}=this.deps;
    if(source.idleChunks){
      if(!supportsIdleChunkNative(native))throw Error('Update NC Remote for native idle chunks.');
      validateChunkVisualSource(source,timeline);
      source={...source,sourceIndices:[...source.sourceIndices],idleChunks:{mediaId:source.idleChunks.mediaId,
        files:source.idleChunks.files.map(file=>({...file,sourceIndices:[...file.sourceIndices]}))}};
    }
    if(!await native.ncBufferedHandoffSource?.(scope.handle,scope.key,this.revision,key,source))
      throw Error('Buffered visual source preparation unavailable.');
    this.check();
  }
  async prepare(descriptor:unknown,value:SourceTimeline,source?:BufferedVisualSource):Promise<void>{
    this.check();const timeline=this.timeline(value);
    if(!this.revision||!this.retained||this.opening)throw Error('Buffered opening state unavailable.');
    const {native,scope}=this.deps;
    if(source)await this.configure(scope.key,timeline,source);
    this.opening=new SpeechOpeningSession({...this.deps.media,live:this.live,detach:this.detach,
      prepare:async(s,file,opening)=>{
        this.check();
        return await native.ncAVOpeningPrepare!(s.handle,s.key,this.revision,s.generation,opening.mediaId,
          file.uri,timeline.sourceFrameCount,timeline.sourceIndices);
      }});
    await this.opening.start(scope,descriptor,timeline);this.check();
  }
  async arm():Promise<number>{
    if(!this.live()||!this.opening?.ready)return 0;
    const {scope,native}=this.deps;
    const delay=await native.ncAVHandoffArm!(scope.handle,scope.key,this.revision);
    return this.live()&&Number.isFinite(delay)&&delay>=0&&delay<=2000?delay:0;
  }
  async next(key:number,value:SourceTimeline,source?:BufferedVisualSource):Promise<void>{
    this.check();const timeline=source?parseSourceTimeline(value):this.timeline(value),{scope,native}=this.deps;
    if(source){
      if(!this.opening?.ready||!Number.isSafeInteger(key)||key<=scope.key||key>0x7fffffff)throw Error('Buffered visual successor unavailable.');
      await this.configure(key,timeline,source);return;
    }
    if(!this.opening?.ready||!Number.isSafeInteger(key)||key<=scope.key||key>0x7fffffff
      ||!await native.ncAVHandoffNext!(scope.handle,scope.key,this.revision,key,timeline.sourceFrameCount,timeline.sourceIndices))
      throw Error('Buffered visual successor unavailable.');
    this.check();
  }
  close():Promise<boolean>{
    if(this.closing)return this.closing;
    this.retained?.close('cancelled');this.closed=true;
    this.closing=this.opening?.close()??this.detach();
    return this.closing;
  }
}
