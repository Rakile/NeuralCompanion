import {parseSourceTimeline} from './frameHandoff';
import type {SourceTimeline} from './frameHandoff';
import type {HandoffScope} from './retainedHandoff';
import type {IdleFile} from '../dev/museTalkIdleFile';

export type OpeningDescriptor={trialId:string;mediaId:string;sourceTimeline:SourceTimeline;
  audio:{id:string;phone_request_id:string;url_path:string};
  segment:{index:0;startFrame:0;frameCount:number;state:'ready';bytes:number;uri:string}};
export type OpeningMedia={resolve(path:string):Promise<{url:string}>;
  owns(url:string):boolean;
  copy(url:string,bytes:number,signal:AbortSignal,owns:(url:string)=>boolean):Promise<IdleFile>};
type Dependencies=OpeningMedia & {live(scope:HandoffScope):boolean;
  prepare(scope:HandoffScope,file:IdleFile,value:OpeningDescriptor):Promise<boolean>;
  detach():Promise<boolean>};
const object=(v:unknown):Record<string,unknown>=>v && typeof v==='object' && !Array.isArray(v)?v as Record<string,unknown>:{};
const hex=(v:unknown):v is string=>typeof v==='string' && /^[a-f0-9]{32}$/.test(v);

export function parseSpeechOpening(value:unknown,scope:HandoffScope,expected:SourceTimeline):OpeningDescriptor {
  const v=object(value),a=object(v.audio),s=object(v.segment),timeline=parseSourceTimeline(v.sourceTimeline);
  if(!scope.handle || !scope.ticket || !scope.requestId || !scope.chunkId || !hex(scope.generation)
    || !Number.isSafeInteger(scope.key) || scope.key<1 || scope.key>0x7fffffff
    || !hex(v.trialId) || !hex(v.mediaId) || a.id!==scope.chunkId || a.phone_request_id!==scope.requestId
    || a.url_path!==`/api/audio/file/${scope.chunkId}` || Object.keys(a).length!==3
    || s.index!==0 || s.startFrame!==0 || s.state!=='ready' || timeline.sourceIndices.length>720
    || s.frameCount!==Math.min(12,timeline.sourceIndices.length)
    || !Number.isSafeInteger(s.bytes) || Number(s.bytes)<1 || Number(s.bytes)>16*1024*1024
    || s.uri!==`/api/dev/musetalk-live/segment/${v.mediaId}/00000000.mp4`
    || JSON.stringify(timeline)!==JSON.stringify(parseSourceTimeline(expected)))throw Error('Invalid speech opening');
  return {trialId:v.trialId,mediaId:v.mediaId,sourceTimeline:timeline,
    audio:{id:scope.chunkId,phone_request_id:scope.requestId,url_path:a.url_path as string},
    segment:{index:0,startFrame:0,state:'ready',frameCount:s.frameCount as number,bytes:s.bytes as number,uri:s.uri as string}};
}

/** A silent, temporary opening. Ready means the native decoder prepared pixels,
 * never that audio was heard or that the incoming picture became visible. */
export class SpeechOpeningSession {
  private scope:HandoffScope|null=null;
  private abort=new AbortController();
  private file:IdleFile|null=null;
  private decoded=false;
  private closing:Promise<boolean>|null=null;
  constructor(private deps:Dependencies){}
  private live(){return !!this.scope && !this.abort.signal.aborted && this.deps.live(this.scope);}
  private check(){if(!this.live())throw Error('Speech opening lifetime ended');}
  get ready(){return this.decoded && this.live();}
  private async bounded<T>(work:Promise<T>):Promise<T>{
    let timer:ReturnType<typeof setTimeout>|undefined,cancel=()=>{};
    try{
      this.check();
      return await Promise.race([work,new Promise<never>((_,reject)=>{
        cancel=()=>reject(Error('Speech opening cancelled'));
        this.abort.signal.addEventListener('abort',cancel,{once:true});
        timer=setTimeout(()=>reject(Error('Speech opening timed out')),15000);
      })]);
    }finally{clearTimeout(timer);this.abort.signal.removeEventListener('abort',cancel);}
  }
  async start(scope:HandoffScope,value:unknown,timeline:SourceTimeline):Promise<void>{
    if(this.scope || this.abort.signal.aborted)throw Error('Speech opening already used');
    const descriptor=parseSpeechOpening(value,scope,timeline);this.scope={...scope};
    try{
      this.check();
      const resolved=await this.bounded(this.deps.resolve(descriptor.segment.uri));this.check();
      if(!resolved.url.startsWith('file:') || !this.deps.owns(resolved.url))throw Error('Unowned speech opening');
      const copied=this.deps.copy(resolved.url,descriptor.segment.bytes,this.abort.signal,this.deps.owns).then(file=>{
        if(!this.live()){file.release();throw Error('Speech opening copy retired');}
        this.file=file;return file;
      });
      const file=await this.bounded(copied);this.check();
      const ready=await this.bounded(this.deps.prepare(this.scope,file,descriptor));this.check();
      if(!ready)throw Error('Speech opening decode unavailable');
      this.decoded=true;
    }catch(error){void this.close();throw error;}
  }
  close():Promise<boolean>{
    if(this.closing)return this.closing;
    this.abort.abort();this.decoded=false;
    // Capture detachment now, before AVRemoteOutput removes the native handle.
    let detached:Promise<boolean>;
    try{detached=this.deps.detach();}catch{detached=Promise.resolve(false);}
    this.closing=Promise.resolve(detached).catch(()=>false).then(safe=>{
      if(safe){this.file?.release();this.file=null;}return safe;
    });
    return this.closing;
  }
}
