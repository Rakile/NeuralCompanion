import type {IdleChunkStatus,IdleChunkRow,IdleChunkReturn,IdleChunkWaitingAuthority} from '../dev/idleChunkProtocol';
import {parseIdleChunkStatus} from '../dev/idleChunkProtocol';
import {parseVideoQuality} from '../relay/idleLoopCache';
export type IdleChunkLease={uri:string;release():void|Promise<void>};
export type IdleChunkRetainedWindow={status:IdleChunkStatus;files:Array<{row:IdleChunkRow;uri:string}>};
type Dependencies={trialId:string;requestId:string;startFrame:number;current():boolean;
  returnSource?:IdleChunkReturn;
  returnPrefetch?:boolean;
  returnPrefill?:2|6;
  waitingAuthority?():IdleChunkWaitingAuthority|undefined;
  retryable?(error:unknown):boolean;
  canOffer?(status:IdleChunkStatus,row:IdleChunkRow):boolean;
  request(path:string,body:Record<string,unknown>,signal:AbortSignal):Promise<unknown>;
  retain(status:IdleChunkStatus,row:IdleChunkRow,signal:AbortSignal):Promise<IdleChunkLease>;
  prepare(status:IdleChunkStatus,row:IdleChunkRow,file:IdleChunkLease):Promise<boolean>;
  append(status:IdleChunkStatus,row:IdleChunkRow,file:IdleChunkLease):Promise<boolean|'blocked'>;
  select(status:IdleChunkStatus):Promise<boolean>;
  position():{mediaId:string;releasedThrough:number}|null;
  detach():Promise<boolean>};
/** Complete-file delivery and reader leases only. No audio/receipt permission. */
export class IdleChunkQueue {
  ready=false;
  private readonly abort=new AbortController();
  private readonly files=new Map<number,IdleChunkLease>();
  private readonly rows=new Map<number,IdleChunkRow>();
  private source:IdleChunkStatus|null=null;
  private next=0;
  private releasedThrough=0;
  private acknowledgedThrough=0;
  private waitingCursorCeiling?:number;
  private closed=false;
  private work:Promise<void>|null=null;
  private closing:Promise<void>|null=null;
  private failure:Error|null=null;
  private wireFailure:unknown=null;
  private readonly returnSource:IdleChunkReturn|null;
  private readonly returnPrefetch:boolean;
  private readonly returnPrefill:2|6;
  private returnAdmission:Promise<void>|null=null;
  private returnAttempt:Promise<boolean>|null=null;
  private pendingAppend:{status:IdleChunkStatus;row:IdleChunkRow;file:IdleChunkLease}|null=null;
  private returnOffered=false;
  private returnAccepted=false;
  private draining=false;
  private quiescing:Promise<void>|null=null;
  constructor(private readonly deps:Dependencies){
    if(!/^[a-f0-9]{32}$/.test(deps.trialId)||!/^[a-f0-9]{32}$/.test(deps.requestId)
      ||!Number.isSafeInteger(deps.startFrame)||deps.startFrame<0||deps.startFrame>=1440)throw Error('Invalid idle chunk owner.');
    const source=deps.returnSource;
    this.returnPrefetch=deps.returnPrefetch===true;
    if(this.returnPrefetch&&!source)throw Error('Missing idle chunk return owner.');
    if(deps.returnPrefill!==undefined&&(!this.returnPrefetch||![2,6].includes(deps.returnPrefill)))
      throw Error('Invalid idle chunk return prefill.');
    this.returnPrefill=deps.returnPrefill??6;
    this.returnSource=source?{...source,audio:{...source.audio},videoQuality:parseVideoQuality(source.videoQuality)}:null;
    if(source&&(!/^[a-f0-9]{32}$/.test(source.sourceId)||!/^[a-f0-9]{32}$/.test(source.mediaId)
      ||!/^[a-f0-9]{64}$/.test(source.motionId)||source.startFrame!==deps.startFrame
      ||!Number.isSafeInteger(source.sourceFrameCount)||source.sourceFrameCount<1||source.sourceFrameCount>1440
      ||source.startFrame>=source.sourceFrameCount))throw Error('Invalid idle chunk return owner.');
  }
  private check(){if(this.closed||this.abort.signal.aborted||!this.deps.current())throw Error('Idle chunk owner ended.');}
  get retainedThrough(){return this.next;}
  reserveWaitingBoundary():number{
    this.check();
    // Freeze publication, not native consumption. Existing published rows
    // remain playable; the producer cannot encode the reserved future cut.
    this.waitingCursorCeiling??=this.next;
    return this.waitingCursorCeiling+6;
  }
  releaseWaitingBoundary(){this.check();this.waitingCursorCeiling=undefined;}
  get drained(){return this.draining&&this.files.size===0&&this.releasedThrough===this.next;}
  /** Stop producing for this epoch, while keeping its leases until the native
   * shared reader has consumed them. This is visual-only renewal, not a TTL or
   * audio authority extension. The caller joins before choosing the boundary. */
  async drain():Promise<{end:number;source:IdleChunkStatus|null}>{
    this.draining=true;
    await this.work?.catch(error=>{if(error!==this.wireFailure)throw error;});this.check();
    const source=this.source;
    return {end:this.next,source:source?{...source,videoQuality:{...source.videoQuality},
      segments:source.segments.map(row=>({...row,sourceIndices:[...row.sourceIndices]}))}:null};
  }
  /** Cancel and join issued acquisition without releasing any native pins.
   * Full close still owns the reader-detach fence and local file unlink. */
  quiesce():Promise<void>{
    this.draining=true;this.abort.abort();
    return this.quiescing??=(async()=>{await this.work?.catch(()=>undefined);})();
  }
  /** Retained only: no reader selection or playback permission is implied. */
  retainedWindow():IdleChunkRetainedWindow|null {
    if(this.closed||!this.source||this.next!==this.returnPrefill||this.files.size!==this.returnPrefill
      ||this.acknowledgedThrough<this.returnPrefill)return null;
    const copy=(row:IdleChunkRow)=>({...row,sourceIndices:[...row.sourceIndices]});
    const files=Array.from({length:this.returnPrefill},(_,index)=>({row:copy(this.rows.get(index)!),uri:this.files.get(index)!.uri}));
    // The producer can publish/ack one file at a time. Reconstruct the initial
    // window from the individually validated retained rows, not its latest
    // cursor-relative six-row status (which may already start at index five).
    return {status:{...this.source,cursor:0,videoQuality:{...this.source.videoQuality},segments:files.map(file=>copy(file.row))},files};
  }
  /** Eligible native audio-key configuration, not download-paced selection.
   * Record the offer before calling native so false/timeout remains fenced. */
  admitReturn(prepare:(window:IdleChunkRetainedWindow)=>Promise<boolean>):Promise<void> {
    if(this.returnAdmission)return this.returnAdmission;
    this.returnAdmission=(async()=>{
      this.check();const window=this.retainedWindow();
      if(!this.returnPrefetch||!window)throw Error('Idle chunk return lookahead unavailable.');
      this.returnOffered=true;
      const accepted=await prepare(window);this.check();
      if(!accepted)throw Error('Idle chunk native return preparation unavailable.');
      this.returnAccepted=true;
    })().catch(error=>{if(!this.closed)this.failure=error instanceof Error?error:Error('Idle chunk return failed.');throw error;});
    return this.returnAdmission;
  }
  /** Same-player RETURN may hit native capacity before installation. Preserve
   * the exact prefix and issued reader ownership; never choose ordinary idle. */
  tryAdmitReturn(prepare:(window:IdleChunkRetainedWindow)=>Promise<boolean|'blocked'>):Promise<boolean> {
    if(this.returnAttempt)return this.returnAttempt;
    if(this.returnAccepted)return Promise.resolve(true);
    const work=(async()=>{
      this.check();const window=this.retainedWindow();
      if(this.returnAdmission||!this.returnPrefetch||!window)throw Error('Idle chunk queued return unavailable.');
      this.returnOffered=true;
      const accepted=await prepare(window);this.check();
      if(accepted==='blocked')return false;
      if(!accepted)throw Error('Idle chunk queued return rejected.');
      this.returnAccepted=true;this.ready=true;return true;
    })().catch(error=>{if(!this.closed)this.failure=error instanceof Error?error:Error('Idle chunk queued return failed.');throw error;})
      .finally(()=>{if(this.returnAttempt===work)this.returnAttempt=null;});
    this.returnAttempt=work;return work;
  }
  pump():Promise<void>{
    if(this.failure&&(!this.draining||this.failure!==this.wireFailure))return Promise.reject(this.failure);
    if(this.work)return this.work;
    const work=this.fill().catch(error=>{if(!this.closed&&!this.deps.retryable?.(error))
      this.failure=error instanceof Error?error:Error('Idle chunk delivery failed.');throw error;})
      .finally(()=>{if(this.work===work)this.work=null;});
    this.work=work;return work;
  }
  private async fill(){
    this.check();
    const position=this.deps.position();
    if(this.source&&position?.mediaId===this.source.mediaId&&(!this.returnPrefetch||this.returnAccepted)){
      if(!Number.isSafeInteger(position.releasedThrough)||position.releasedThrough<this.releasedThrough
        ||position.releasedThrough>this.next&&!this.draining)throw Error('Invalid idle decoder release cursor.');
      const releasedThrough=Math.min(position.releasedThrough,this.next);
      for(const [index,file] of this.files)if(index<releasedThrough){await file.release();this.files.delete(index);this.rows.delete(index);}
      this.releasedThrough=releasedThrough;this.check();
      if(this.returnPrefetch)this.ready=true;
    }
    if(this.draining)return;
    if(this.pendingAppend){
      const pending=this.pendingAppend;
      const accepted=await this.deps.append(pending.status,pending.row,pending.file);this.check();
      if(accepted==='blocked')return;
      if(!accepted)throw Error('Idle chunk native append unavailable.');
      this.pendingAppend=null;this.next++;await this.acknowledgeAndSelect();
    }
    // A prospective RETURN retains only its startup prefix. It cannot grow
    // or offer successors until that exact prefix's native ACK is confirmed.
    if(this.returnPrefetch&&!this.returnAccepted&&this.next>=this.returnPrefill){await this.acknowledgeAndSelect();return;}
    if(this.files.size>=6){await this.acknowledgeAndSelect();return;}
    const source=this.returnSource;
    const raw=await this.request('/api/dev/musetalk-live/idle-chunks',
      {trialId:this.deps.trialId,requestId:this.deps.requestId,startFrame:this.deps.startFrame,
        ...(source?{purpose:'return',sourceId:source.sourceId}:{})});
    this.check();
    const owner=raw as {purpose?:unknown;sourceId?:unknown}|null;
    if(!owner||(source?(owner.purpose!=='return'||owner.sourceId!==source.sourceId)
      :owner.purpose!==undefined||owner.sourceId!==undefined))throw Error('Idle chunk return identity changed.');
    const status=parseIdleChunkStatus(raw,this.deps.trialId,this.deps.requestId,this.deps.waitingAuthority?.());if(!status)return;
    if(source&&(status.motionId!==source.motionId||status.avatarId!==source.avatarId
      ||status.sourceFrameCount!==source.sourceFrameCount||status.startFrame!==source.startFrame
      ||JSON.stringify(status.videoQuality)!==JSON.stringify(source.videoQuality)))throw Error('Idle chunk return source changed.');
    if(status.startFrame!==this.deps.startFrame||status.cursor>this.next)throw Error('Idle chunk producer cursor changed.');
    const identity=(value:IdleChunkStatus)=>JSON.stringify([value.mediaId,value.motionId,value.avatarId,value.sourceFrameCount,value.startFrame,value.videoQuality]);
    if(this.source&&identity(this.source)!==identity(status))throw Error('Idle chunk source changed within its owner.');
    this.source=status;
    while(this.files.size<6&&this.next<this.releasedThrough+6
      &&(!this.returnPrefetch||this.returnAccepted||this.next<this.returnPrefill)){
      const row=status.segments.find(row=>row.index===this.next);if(row?.state!=='ready')break;
      if(this.draining||this.deps.canOffer&&!this.deps.canOffer(status,row))break;
      const file=await this.deps.retain(status,row,this.abort.signal);
      try{this.check();}catch(error){await file.release();throw error;}
      // Native false/timeout can still leave a late reader. Record the lease
      // before offering it, and release only through the explicit detach fence.
      this.files.set(row.index,file);
      this.rows.set(row.index,{...row,sourceIndices:[...row.sourceIndices]});
      if(!this.returnPrefetch||this.returnAccepted){
        const accepted=await (row.index===0?this.deps.prepare(status,row,file):this.deps.append(status,row,file));
        this.check();
        if(accepted==='blocked'){
          this.pendingAppend={status,row,file};await this.acknowledgeAndSelect();return;
        }
        if(!accepted)throw Error('Idle chunk native prepare/append unavailable.');
      }
      this.next++;
    }
    this.acknowledgedThrough=Math.max(this.acknowledgedThrough,status.cursor);
    await this.acknowledgeAndSelect();
  }
  private async acknowledgeAndSelect(){
    const status=this.source;if(!status)return;
    const cursor=Math.min(this.next,this.waitingCursorCeiling??this.next);
    if(cursor>this.acknowledgedThrough){
      const ack=await this.request('/api/dev/musetalk-live/idle-chunk-cursor',
        {trialId:this.deps.trialId,mediaId:status.mediaId,cursor});this.check();
      const value=ack as {ok?:boolean;mediaId?:string;cursor?:number}|null;
      if(!value||value.ok!==true||value.mediaId!==status.mediaId||value.cursor!==cursor)
        throw Error('Invalid idle chunk cursor acknowledgement.');
      this.acknowledgedThrough=cursor;
    }
    if(!this.returnPrefetch&&!this.ready&&this.files.size===6){
      const selected=await this.deps.select(status);this.check();
      if(!selected)throw Error('Idle chunk native selection unavailable.');
      this.ready=true;
    }
  }
  private async request(path:string,body:Record<string,unknown>){
    try{return await this.deps.request(path,body,this.abort.signal);}
    catch(error){this.wireFailure=error;throw error;}
  }
  close():Promise<void>{
    if(this.closing)return this.closing;
    this.closed=true;this.ready=false;this.abort.abort();
    this.closing=(async()=>{
      await this.work?.catch(()=>undefined);
      await this.returnAdmission?.catch(()=>undefined);
      await this.returnAttempt?.catch(()=>undefined);
      if(!this.drained&&(!this.returnPrefetch||this.returnOffered)&&!await this.deps.detach())throw Error('Idle chunk native detach unavailable.');
      for(const file of this.files.values())await file.release();this.files.clear();this.rows.clear();
      this.pendingAppend=null;
    })();
    return this.closing;
  }
}
