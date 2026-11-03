import type {IdleChunkReturn,IdleChunkStatus,IdleChunkRow} from '../dev/idleChunkProtocol';
import {parseIdleChunkReturn} from '../dev/idleChunkProtocol';
import type {SourceTimeline} from '../relay/frameHandoff';
import {parseSourceTimeline} from '../relay/frameHandoff';
import type {BufferedVisualSource} from './bufferedHandoff';
import type {BufferedPresentation,PresentationChunkReader} from './bufferedPresentation';
import {IdleChunkQueue} from './idleChunkQueue';
import type {IdleChunkLease} from './idleChunkQueue';
import {makeChunkVisualSource} from './idleChunkVisualSource';

type Dependencies={trialId:string;requestId:string;returnSource:IdleChunkReturn;timeline:SourceTimeline;fadeMs:number;
  output:Pick<BufferedPresentation,'createIdleChunkReader'>;current():boolean;
  retryable?(error:unknown):boolean;
  request(path:string,body:Record<string,unknown>,signal:AbortSignal):Promise<unknown>;
  retain(status:IdleChunkStatus,row:IdleChunkRow,signal:AbortSignal):Promise<IdleChunkLease>};

/** Six retained silent return files. The existing native transition alone may
 * select them at heard natural completion; delivery never calls select(). */
export class IdleChunkContinuation {
  private closed=false;
  private readonly queue:IdleChunkQueue;
  private readonly timeline:SourceTimeline;
  private reader:PresentationChunkReader|null=null;
  private retaining:Promise<void>|null=null;
  private nativeTransferred=false;
  constructor(private readonly deps:Dependencies){
    this.timeline=parseSourceTimeline(deps.timeline);
    const source=parseIdleChunkReturn(deps.returnSource,deps.returnSource.mediaId,deps.returnSource.audio,this.timeline);
    if(!Number.isSafeInteger(deps.fadeMs)||deps.fadeMs<0||deps.fadeMs>5000)throw Error('Invalid idle chunk return fade.');
    this.queue=new IdleChunkQueue({trialId:deps.trialId,requestId:deps.requestId,startFrame:source.startFrame,
      returnSource:source,returnPrefetch:true,current:()=>this.live(),request:deps.request,retain:deps.retain,retryable:deps.retryable,
      prepare:async()=>{throw Error('Idle chunk return cannot prepare on delivery.');},
      append:async(status,row,file)=>this.reader?this.reader.append(status,row,file):false,
      select:async()=>{throw Error('Idle chunk return cannot select on delivery.');},
      position:()=>this.reader?.position()??null,detach:()=>this.reader?.close()??Promise.resolve(true)});
  }
  private live(){return !this.closed&&this.deps.current();}
  get configured(){return Boolean(this.reader);}
  get displayed(){return this.live()&&this.reader?.position()!==null&&Boolean(this.reader);}
  /** Publication can be incremental; retain all six before making the audio
   * key's prospective return available. This grants no audio deadline/lifetime. */
  retain(signal:AbortSignal):Promise<void>{
    if(this.retaining)return this.retaining;
    const work=(async()=>{
      const deadline=performance.now()+15000;
      for(;;){
        if(!this.live()||signal.aborted)throw Error('Idle chunk return owner ended.');
        await this.queue.pump();
        if(!this.live()||signal.aborted)throw Error('Idle chunk return owner ended.');
        if(this.queue.retainedWindow())return;
        if(performance.now()>=deadline)throw Error('Idle chunk return lookahead timed out.');
        await new Promise(resolve=>setTimeout(resolve,20));
      }
    })().catch(error=>{if(this.retaining===work&&this.deps.retryable?.(error))this.retaining=null;throw error;});
    this.retaining=work;return work;
  }
  configure(action:(source:BufferedVisualSource)=>Promise<void>):Promise<void>{
    return this.queue.admitReturn(async window=>{
      const source=makeChunkVisualSource(window,this.timeline,this.deps.fadeMs);
      const reader=await this.deps.output.createIdleChunkReader(window.status,this.deps.fadeMs,
        ()=>this.deps.current()&&(!this.closed||this.nativeTransferred));
      this.reader=reader;
      return reader.configure(window.status,async()=>{await action(source);return true;});
    });
  }
  pump(){return this.queue.pump();}
  async handover(){
    if(!this.displayed||!this.reader)throw Error('Idle chunk return is not displayed.');
    const boundary=await this.queue.drain();
    if(!this.displayed||!boundary.source)throw Error('Idle chunk return owner ended.');
    // The consumed delivery epoch can close later without revoking the shared
    // visual reader. Its authenticated presentation owner still must be live;
    // this transfers no audio authority or receipt capability.
    this.nativeTransferred=true;
    return {...boundary,reader:this.reader};
  }
  get drained(){return this.queue.drained;}
  close():Promise<void>{this.closed=true;return this.queue.close();}
}
