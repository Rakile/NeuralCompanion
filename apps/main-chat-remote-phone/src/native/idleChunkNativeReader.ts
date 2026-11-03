import type {IdleChunkRow,IdleChunkStatus} from '../dev/idleChunkProtocol';
import {parseIdleChunkStatus} from '../dev/idleChunkProtocol';
import type {IdleChunkLease} from './idleChunkQueue';

export type NativeIdleChunkFile={generation:string;motionId:string;mediaId:string;uri:string;sha256:string;
  sourceFrameCount:number;startFrame:number;index:number;sourceIndices:number[];fadeMs:number};
export type NativeIdleChunkAPI={
  ncBufferedIdleChunksVersion?():number;
  ncBufferedIdleChunkPrepare?(handle:string,revision:number,file:NativeIdleChunkFile):Promise<boolean>;
  ncBufferedIdleChunkAppend?(handle:string,revision:number,file:NativeIdleChunkFile):Promise<boolean>;
  ncBufferedIdleChunkSelect?(handle:string,revision:number,generation:string,motion:string,media:string):Promise<boolean>;
  ncBufferedIdleChunkDetachBegin?(handle:string,generation:string,media:string):string|null;
  ncBufferedIdleChunkDetachWait?(ticket:string):Promise<boolean>;
  ncAVIdlePosition?(handle:string):unknown;
};
export type IdleChunkRenewal={
  canOffer(row:IdleChunkRow):boolean;
  append(status:IdleChunkStatus,row:IdleChunkRow,file:IdleChunkLease):Promise<boolean>;
  position():{mediaId:string;releasedThrough:number}|null;
};
const identity=(value:IdleChunkStatus)=>JSON.stringify([value.trialId,value.requestId,value.mediaId,value.motionId,
  value.avatarId,value.sourceFrameCount,value.startFrame,value.videoQuality]);
export function isIdleChunkFileUri(value:unknown):value is string {
  return typeof value==='string'&&!value.includes('/../')&&!value.includes('/./')
    && (/^file:\/\/.+\/nc_musetalk_idle_[A-Za-z0-9_.-]+\.mp4$/.test(value)
      ||/^file:\/\/.+\/nc-relay\/[0-9]+-[0-9]+\.mp4$/.test(value));
}
export function supportsIdleChunkNative(native:NativeIdleChunkAPI):boolean {
  return native.ncBufferedIdleChunksVersion?.()===1 && ['ncBufferedIdleChunkPrepare','ncBufferedIdleChunkAppend',
    'ncBufferedIdleChunkSelect','ncBufferedIdleChunkDetachBegin','ncBufferedIdleChunkDetachWait','ncAVIdlePosition']
    .every(key=>typeof native[key as keyof NativeIdleChunkAPI]==='function');
}
/** One visual file-reader owner, never an audio/receipt authority. A presentation
 * supplies its revision; cleanup never calls the whole-presentation idle clear. */
export class IdleChunkNativeReader {
  private readonly native:Required<NativeIdleChunkAPI>;
  private source:IdleChunkStatus|null=null;
  private prepared=false;
  private offered=false;
  private closed=false;
  private readonly work=new Set<Promise<boolean>>();
  private closing:Promise<boolean>|null=null;
  private appendedThrough=0;
  private renewal:object|null=null;
  private latestWireTrial='';
  constructor(native:NativeIdleChunkAPI,private readonly handle:string,private readonly revision:number,
    private readonly current:()=>boolean,private readonly fadeMs:number){
    if(!supportsIdleChunkNative(native)||!handle||!Number.isSafeInteger(revision)||revision<1
      ||!Number.isSafeInteger(fadeMs)||fadeMs<0||fadeMs>5000)throw Error('Update NC Remote for native idle chunks.');
    this.native=native as Required<NativeIdleChunkAPI>;
  }
  private live(){return !this.closed&&this.current();}
  private fileSource(status:IdleChunkStatus,row:IdleChunkRow,file:IdleChunkLease){
    if(!this.live())throw Error('Idle chunk native owner ended.');
    const source=parseIdleChunkStatus({...status,state:'ready'},status.trialId,status.requestId);
    const segment=source?.segments.find(value=>value.index===row.index);
    if(!source||!segment||segment.state!=='ready'||row.state!=='ready'||segment.startFrame!==row.startFrame
      ||segment.frameCount!==row.frameCount||segment.uri!==row.uri||segment.bytes!==row.bytes||segment.sha256!==row.sha256
      ||JSON.stringify(segment.sourceIndices)!==JSON.stringify(row.sourceIndices)
      ||!isIdleChunkFileUri(file.uri))throw Error('Invalid idle chunk native file.');
    return {source,segment};
  }
  private descriptor(status:IdleChunkStatus,row:IdleChunkRow,file:IdleChunkLease):NativeIdleChunkFile {
    const {source,segment}=this.fileSource(status,row,file);
    if(this.source&&identity(this.source)!==identity(source))throw Error('Idle chunk native source changed.');
    this.source=source;
    return {generation:source.trialId,motionId:source.motionId,mediaId:source.mediaId,uri:file.uri,sha256:segment.sha256!,
      sourceFrameCount:source.sourceFrameCount,startFrame:source.startFrame,index:segment.index,
      sourceIndices:[...segment.sourceIndices],fadeMs:this.fadeMs};
  }
  private offer(action:()=>Promise<boolean>):Promise<boolean> {
    if(!this.live())return Promise.resolve(false);
    this.offered=true;
    let result:Promise<boolean>;
    try{result=Promise.resolve(action());}catch(error){result=Promise.reject(error);}
    const work=result.then(accepted=>accepted===true&&this.live()).finally(()=>this.work.delete(work));
    this.work.add(work);return work;
  }
  async prepare(status:IdleChunkStatus,row:IdleChunkRow,file:IdleChunkLease):Promise<boolean> {
    if(this.prepared||row.index!==0)throw Error('Invalid idle chunk native preparation.');
    const descriptor=this.descriptor(status,row,file);this.prepared=true;this.appendedThrough=1;
    return this.offer(()=>this.native.ncBufferedIdleChunkPrepare(this.handle,this.revision,descriptor));
  }
  /** The existing transition configures all six return files. Track that native
   * call as a reader offer too, including a false/timeout or late acceptance. */
  configure(status:IdleChunkStatus,action:()=>Promise<boolean>):Promise<boolean> {
    if(!this.live()||this.prepared)return Promise.reject(Error('Idle chunk native return owner unavailable.'));
    const source=parseIdleChunkStatus({...status,state:'ready'},status.trialId,status.requestId);
    if(!source||source.cursor!==0||source.segments.some(row=>row.state!=='ready'))
      return Promise.reject(Error('Idle chunk native return lookahead unavailable.'));
    this.source=source;this.prepared=true;this.appendedThrough=6;
    return this.offer(action);
  }
  async append(status:IdleChunkStatus,row:IdleChunkRow,file:IdleChunkLease):Promise<boolean> {
    if(!this.prepared||this.renewal||row.index!==this.appendedThrough)throw Error('Invalid idle chunk native append.');
    const descriptor=this.descriptor(status,row,file);
    this.appendedThrough++;
    return this.offer(()=>this.native.ncBufferedIdleChunkAppend(this.handle,this.revision,descriptor));
  }
  /** Bind a freshly armed visual-only producer to the next retained boundary.
   * Only an identical frozen source/quality may reuse this reader. Wire epochs
   * change; the native source sequence/clock/media identity do not. */
  renew(value:IdleChunkStatus,offset:number,isCurrent:()=>boolean):IdleChunkRenewal {
    const previous=this.source,source=parseIdleChunkStatus({...value,state:'ready'},value.trialId,value.requestId);
    if(!this.live()||!isCurrent()||!this.prepared||!previous||!source||source.cursor!==0
      ||!Number.isSafeInteger(offset)||offset!==this.appendedThrough||offset<1||offset>10000
      ||source.trialId===previous.trialId||source.trialId===this.latestWireTrial||source.mediaId===previous.mediaId
      ||source.motionId!==previous.motionId||source.avatarId!==previous.avatarId||source.sourceFrameCount!==previous.sourceFrameCount
      ||JSON.stringify(source.videoQuality)!==JSON.stringify(previous.videoQuality)
      ||source.startFrame!==(previous.startFrame+offset*12)%previous.sourceFrameCount)
      throw Error('Invalid idle chunk renewal boundary.');
    const token={};this.renewal=token;this.latestWireTrial=source.trialId;
    const canOffer=(row:IdleChunkRow)=>{
      const position=this.position(),index=offset+row.index;
      return this.live()&&isCurrent()&&this.renewal===token&&Boolean(position)&&index===this.appendedThrough
        &&index<=10005&&index<position!.releasedThrough+6;
    };
    return {
      canOffer,
      append:async(status,row,file)=>{
        if(this.renewal!==token||identity(status)!==identity(source)||!canOffer(row))throw Error('Idle chunk renewal owner unavailable.');
        const {segment}=this.fileSource(status,row,file),index=offset+segment.index;
        const descriptor:NativeIdleChunkFile={generation:previous.trialId,motionId:previous.motionId,mediaId:previous.mediaId,
          uri:file.uri,sha256:segment.sha256!,sourceFrameCount:previous.sourceFrameCount,startFrame:previous.startFrame,
          index,sourceIndices:[...segment.sourceIndices],fadeMs:this.fadeMs};
        this.appendedThrough++;
        return this.offer(()=>this.native.ncBufferedIdleChunkAppend(this.handle,this.revision,descriptor));
      },
      // Draining earlier epochs may still read this cursor after the next
      // binding replaces token; they never gain append permission again.
      position:()=>{const position=this.position();return position?
        {mediaId:source.mediaId,releasedThrough:Math.max(0,position.releasedThrough-offset)}:null;},
    };
  }
  select():Promise<boolean> {
    const source=this.source;
    if(!this.live()||!source||!this.prepared)return Promise.resolve(false);
    return this.offer(()=>this.native.ncBufferedIdleChunkSelect(this.handle,this.revision,source.trialId,source.motionId,source.mediaId));
  }
  position():{mediaId:string;releasedThrough:number}|null {
    const source=this.source;if(!this.live()||!source)return null;
    const value=this.native.ncAVIdlePosition(this.handle) as Record<string,unknown>|null;
    if(!value||value.generation!==source.trialId||value.id!==source.motionId||value.mediaId!==source.mediaId
      ||value.sourceCount!==source.sourceFrameCount||value.chunked!==true
      ||!Number.isSafeInteger(value.releasedThrough)||Number(value.releasedThrough)<0||Number(value.releasedThrough)>10006)return null;
    return {mediaId:source.mediaId,releasedThrough:Number(value.releasedThrough)};
  }
  close():Promise<boolean> {
    if(this.closing)return this.closing;
    this.closed=true;
    this.closing=(async()=>{
      await Promise.allSettled(Array.from(this.work));
      if(!this.offered||!this.source)return true;
      const ticket=this.native.ncBufferedIdleChunkDetachBegin(this.handle,this.source.trialId,this.source.mediaId);
      return Boolean(ticket)&&await this.native.ncBufferedIdleChunkDetachWait(ticket!);
    })().catch(()=>false);
    return this.closing;
  }
}
