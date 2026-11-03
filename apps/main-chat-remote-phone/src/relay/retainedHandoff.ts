import {parseAnticipationStatus} from '../dev/museTalkLiveTrial';
import type {AnticipationStatus} from '../dev/museTalkLiveTrial';
import type {IdleFile} from '../dev/museTalkIdleFile';

export type HandoffScope={handle:string;generation:string;ticket:string;requestId:string;chunkId:string;key:number};
export type HandoffDescriptor={trialId:string;mediaId:string;
  audio:{id:string;phone_request_id:string;url_path:string};plan:AnticipationStatus};
type Row=AnticipationStatus['segments'][number];
type Dependencies={
  live(scope:HandoffScope):boolean;
  request(method:'POST',path:string,body:Record<string,unknown>):Promise<unknown>;
  resolve(path:string):Promise<{url:string}>;
  copy(url:string,bytes:number,signal:AbortSignal,owns:(url:string)=>boolean):Promise<IdleFile>;
  owns(url:string):boolean;
  onSegment(index:number,file:IdleFile,row:Row):Promise<void>;
  detach():Promise<void>;
  diagnose(event:string,fields:Record<string,number|string>):void;
};
const PREFIX='/api/dev/musetalk-live/';
const hex=(v:unknown):v is string=>typeof v==='string' && /^[a-f0-9]{32}$/.test(v);
const object=(v:unknown):Record<string,unknown>=>v && typeof v==='object'?v as Record<string,unknown>:{};
const identity=(plan:AnticipationStatus)=>JSON.stringify([plan.planId,plan.mediaId,plan.avatarId,plan.fps,
  plan.sourceFrameCount,plan.sourceIndices,plan.speechEntryFrame,plan.exitAfterFrame,plan.repeat]);

/** One short, visual-only plan. Retention is not a reply capability and cannot
 * produce heard/drained receipts. A new peer or reply needs a new session. */
export class RetainedHandoffSession {
  private scope:HandoffScope|null=null;
  private descriptor:HandoffDescriptor|null=null;
  private abort=new AbortController();
  private files=new Map<number,IdleFile>();
  private begun=false;
  private detached:Promise<void>|null=null;
  constructor(private deps:Dependencies){}
  private live(){return !this.abort.signal.aborted && !!this.scope && this.deps.live(this.scope);}
  private check(){if(!this.live())throw Error('Retained handoff lifetime ended');}
  private emit(event:string,fields:Record<string,number|string>={}){
    // Caller-controlled reason, ticket, file path and request text never enter telemetry.
    try { this.deps.diagnose(event,{key:this.scope?.key??0,...fields}); }
    catch { /* Diagnostics cannot skip detach, change presentation, or leak files. */ }
  }
  private async bounded<T>(work:Promise<T>,milliseconds=15000):Promise<T>{
    let timer:ReturnType<typeof setTimeout>|undefined;
    let cancel=()=>{};
    try {
      this.check();
      return await Promise.race([work,new Promise<never>((_,reject)=>{
        cancel=()=>reject(Error('Retained handoff cancelled'));
        this.abort.signal.addEventListener('abort',cancel,{once:true});
        timer=setTimeout(()=>reject(Error('Retained handoff deadline exceeded')),milliseconds);
      })]);
    } finally {clearTimeout(timer);this.abort.signal.removeEventListener('abort',cancel);}
  }
  async start(scope:HandoffScope,value:unknown):Promise<void>{
    if(this.begun || this.abort.signal.aborted)throw Error('Retained handoff already used');
    const raw=object(value),audio=object(raw.audio),plan=parseAnticipationStatus(raw.plan);
    if(!scope.handle || !hex(scope.generation) || !scope.ticket || !scope.requestId || !scope.chunkId
      || !Number.isSafeInteger(scope.key) || scope.key<1 || scope.key>0x7fffffff
      || !hex(raw.trialId) || !hex(raw.mediaId) || audio.id!==scope.chunkId
      || audio.phone_request_id!==scope.requestId || audio.url_path!==`/api/audio/file/${scope.chunkId}`
      || Object.keys(audio).length!==3 || plan.repeat!==true || plan.speechEntryFrame!==plan.sourceIndices[0]
      || !['available','active'].includes(plan.state))throw Error('Invalid retained handoff scope');
    this.begun=true;this.scope={...scope};
    this.descriptor={trialId:raw.trialId,mediaId:raw.mediaId,audio:{id:scope.chunkId,
      phone_request_id:scope.requestId,url_path:audio.url_path as string},plan};
    const stable=identity(plan),began=performance.now();let bytes=0;
    try {
      for(let index=0;index<plan.segments.length;index++){
        let row:Row;
        do {
          this.check();
          if(performance.now()-began>30000)throw Error('Retained handoff transfer timed out');
          const result=object(await this.bounded(this.deps.request('POST',PREFIX+'anticipation-cursor',
            {trialId:this.descriptor.trialId,mediaId:this.descriptor.mediaId,audio:{...this.descriptor.audio},cursor:index})));
          this.check();
          const returnedAudio=object(result.audio);
          if(result.trialId!==this.descriptor.trialId || result.mediaId!==this.descriptor.mediaId
            || Object.keys(this.descriptor.audio).some(k=>returnedAudio[k]!==this.descriptor!.audio[k as keyof HandoffDescriptor['audio']]))
            throw Error('Retained handoff owner changed');
          const current=parseAnticipationStatus(result.anticipation);
          if(identity(current)!==stable || current.state!=='active' || current.cursor!==index)
            throw Error('Retained handoff plan changed');
          const selected=current.segments[index];
          if(!selected)throw Error('Retained handoff range missing');
          row=selected;
          if(row.state==='pending')await this.bounded(new Promise<void>(resolve=>setTimeout(resolve,25)));
          else if(row.state!=='ready')throw Error('Retained handoff unavailable');
        } while(row.state!=='ready');
        if(bytes+row.bytes!>128*1024*1024)throw Error('Retained handoff size exceeded');
        const resolved=await this.bounded(this.deps.resolve(row.uri!));this.check();
        if(!resolved.url.startsWith('file:') || !this.deps.owns(resolved.url))throw Error('Unowned handoff file');
        // The copy can finish after cancellation even if the OS ignores abort.
        const copy=this.deps.copy(resolved.url,row.bytes!,this.abort.signal,this.deps.owns).then(file=>{
          if(!this.live()){file.release();throw Error('Retained handoff copy retired');}
          // Take ownership in the same job as the lifetime check. A stop or
          // peer replacement may run before bounded(copy)'s caller resumes.
          this.files.set(index,file);return file;
        });
        const file=await this.bounded(copy);this.check();
        bytes+=row.bytes!;
        await this.bounded(this.deps.onSegment(index,file,row));this.check();
        this.emit('handoff_chunk_retained',{index,bytes:row.bytes!,total_bytes:bytes});
      }
      this.emit('handoff_download_complete',{bytes,segments:this.files.size});
    } catch(error){this.close('failed');throw error;}
  }
  file(index:number):IdleFile|null{
    if(!this.live())return null;
    return this.files.get(index)??null;
  }
  close(_reason:string):void{
    if(this.abort.signal.aborted)return;
    const stillOwned=!!this.scope && this.deps.live(this.scope),descriptor=this.descriptor;
    this.abort.abort();
    this.emit('handoff_retired',{files:this.files.size});
    // This callback targets the original native handle. Do not unlink files
    // while a decoder still owns them, including during asynchronous clear.
    try { this.detached=this.deps.detach(); }
    catch { this.detached=Promise.reject(Error('Native detach unavailable')); }
    void this.detached.then(()=>{
      for(const file of this.files.values())file.release();this.files.clear();
    }).catch(()=>this.emit('handoff_detach_failed'));
    if(stillOwned && descriptor){
      void this.deps.request('POST',PREFIX+'anticipation-cursor',{trialId:descriptor.trialId,
        mediaId:descriptor.mediaId,audio:{...descriptor.audio},cursor:null}).catch(()=>undefined);
    }
  }
}
