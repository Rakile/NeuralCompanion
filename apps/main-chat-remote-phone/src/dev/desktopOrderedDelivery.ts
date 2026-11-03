import {BufferedMediaCapacityError,BufferedMediaCleanupError} from '../relay/bufferedMedia';
import type {BufferedMediaScope,BufferedMediaLease} from '../relay/bufferedMedia';
import type {OrderedChunkStore} from './orderedChunkStore';
import {parseOrderedAnnouncement,parseOrderedNativeSnapshot,parseOrderedStoppedOutput} from './desktopOrderedProtocol';
import type {OrderedAnnouncement,OrderedChunk,OrderedNativeSnapshot,OrderedStoppedOutput} from './desktopOrderedProtocol';
import type {MuxedTrialFile} from './muxedTrialDelivery';
import {OrderedProgress} from './desktopOrderedProgress';

type Dependencies={streamId:string;generation:number;store:Pick<OrderedChunkStore,'acquire'|'owns'>;
  scope(chunk:OrderedChunk):BufferedMediaScope|null;limits?:{maxFiles:number;maxBytes:number};
  retryable?(error:unknown):boolean;onReleased(ordinal:number):Promise<void>;
  onChange?():void;onEvent?(event:{phase:string;generation:number;ordinal:number}):void};
type Entry={announcement:OrderedAnnouncement;scope:BufferedMediaScope;identity:string;state:'queued'|'acquiring'|'waiting'|'retained';
  lease?:BufferedMediaLease;task?:Promise<void>;release?:Promise<void>;cleanupUnconfirmed?:boolean};
export type OrderedRetained=Readonly<{chunk:OrderedChunk;source:OrderedAnnouncement['source'];file:Readonly<MuxedTrialFile>}>;

/** Acquires independently of native staging/playback, with explicit byte/file
 * backpressure. The only playable prefix is contiguous Desktop order. Native
 * reader joins, not submitted/played ordinals, authorize cache-file release.
 * Native RPC calls and authenticated announcement transport live in the session. */
export class DesktopOrderedDelivery {
  private readonly rows=new Map<number,Entry>();
  private readonly abort=new AbortController();
  private readonly maxFiles:number;private readonly maxBytes:number;
  private bytes=0;private running=0;private nextOrdinal=0;private releasedThrough=-1;
  private native:OrderedNativeSnapshot|null=null;
  private readonly progress=new OrderedProgress();
  private closedEvidence:string|null=null;
  private stopped=false;private failure:unknown=null;private failurePresent=false;
  private control:Promise<void>=Promise.resolve();
  private releaseTarget=-1;private releasing?:Promise<void>;
  private releaseWaiting=false;
  constructor(private readonly deps:Dependencies){
    if(!/^[a-f0-9]{32}$/.test(deps.streamId)||!Number.isSafeInteger(deps.generation)||deps.generation<0)throw Error('ordered.session');
    this.maxFiles=deps.limits?.maxFiles??64;this.maxBytes=deps.limits?.maxBytes??128*1024*1024;
    if(!Number.isSafeInteger(this.maxFiles)||this.maxFiles<1||this.maxFiles>64
      ||!Number.isSafeInteger(this.maxBytes)||this.maxBytes<1||this.maxBytes>128*1024*1024)throw Error('ordered.capacity_config');
  }
  private notify(){try{this.deps.onChange?.();}catch{}}
  private event(phase:string,ordinal:number){try{this.deps.onEvent?.({phase,generation:this.deps.generation,ordinal});}catch{}}
  private fail(error:unknown){if(!this.failurePresent){this.failurePresent=true;this.failure=error;this.event('failed',this.nextOrdinal);}
    this.stopped=true;this.abort.abort();this.notify();}
  private check(){if(this.failurePresent)throw this.failure;if(this.stopped)throw Error('ordered.cancelled');}
  private scopeIdentity(scope:BufferedMediaScope){return JSON.stringify([scope.owner,scope.replyId,scope.expiresAt]);}
  private current(row:Entry){const scope=this.deps.scope(row.announcement.chunk);
    if(!scope||scope.expiresAt<=Date.now()||this.scopeIdentity(scope)!==this.scopeIdentity(row.scope))throw Error('ordered.custody_authority_changed');}
  /** False means backpressure: retry the same immutable announcement later. */
  announce(values:readonly unknown[]):boolean{
    this.check();
    try{
      if(!Array.isArray(values)||values.length>64)throw Error('ordered.announcement_batch');
      const pending=new Map<number,Entry>();let addedBytes=0;
      for(const value of values){
        const announcement=parseOrderedAnnouncement(value),c=announcement.chunk;
        if(c.streamId!==this.deps.streamId||c.generation!==this.deps.generation)throw Error('ordered.generation');
        if(c.ordinal<=this.releasedThrough)throw Error('ordered.released_ordinal');
        const identity=JSON.stringify(announcement),existing=this.rows.get(c.ordinal)??pending.get(c.ordinal);
        if(existing){if(existing.identity!==identity)throw Error('ordered.descriptor_changed');continue;}
        const scope=this.deps.scope(c);
        if(!scope||!scope.owner||!scope.replyId||!Number.isSafeInteger(scope.expiresAt)||scope.expiresAt<=Date.now())throw Error('ordered.custody_authority_unavailable');
        const sourceIdentity=JSON.stringify(announcement.source);
        for(const other of [...this.rows.values(),...pending.values()])if(other.announcement.source.sourceId===announcement.source.sourceId
          &&JSON.stringify(other.announcement.source)!==sourceIdentity)throw Error('ordered.source_changed');
        pending.set(c.ordinal,{announcement,scope:Object.freeze({...scope}),identity,state:'queued'});addedBytes+=c.byteLength;
      }
      if(this.rows.size+pending.size>this.maxFiles||this.bytes+addedBytes>this.maxBytes
        ||[...pending.keys()].some(ordinal=>ordinal-this.nextOrdinal>=this.maxFiles))return false;
      for(const [ordinal,row] of [...pending].sort(([a],[b])=>a-b)){this.rows.set(ordinal,row);this.bytes+=row.announcement.chunk.byteLength;this.event('announced',ordinal);}
      this.pump();this.notify();return true;
    }catch(error){this.fail(error);throw error;}
  }
  private pump(){
    if(this.stopped)return;
    for(const [ordinal,row] of [...this.rows].sort(([a],[b])=>a-b)){
      if(this.running>=2)break;if(row.state!=='queued')continue;
      row.state='acquiring';this.running++;
      row.task=this.acquire(row).catch(error=>{
        if(error instanceof BufferedMediaCleanupError){row.cleanupUnconfirmed=true;this.fail(error);return;}
        if(this.stopped)return;
        if(error instanceof BufferedMediaCapacityError||this.deps.retryable?.(error)){
          row.state='waiting';this.event('acquisition_wait',ordinal);
        }else this.fail(error);
      }).finally(()=>{this.running--;this.pump();this.notify();});
    }
  }
  /** Called on transport/capacity changes, not by playback-preparation demand. */
  resumeAcquisition(){this.check();for(const row of this.rows.values())if(row.state==='waiting')row.state='queued';
    this.releaseWaiting=false;this.queueRelease(this.releaseTarget);this.pump();}
  private async acquire(row:Entry){
    this.check();this.current(row);const {chunk}=row.announcement;
    this.event('acquiring',chunk.ordinal);
    const lease=await this.deps.store.acquire(row.scope,row.announcement,this.abort.signal);
    // Retain even if cancellation won at acquisition completion. Retirement,
    // including uncertain native RPC outcomes, must account for every pin.
    row.lease=lease;row.state='retained';this.current(row);
    if(lease.bytes!==chunk.byteLength||!this.deps.store.owns(row.scope,lease.uri))throw Error('ordered.retained_file_mismatch');
    this.event('retained',chunk.ordinal);
  }
  prefix(max=6):readonly OrderedRetained[]{
    this.check();if(!Number.isSafeInteger(max)||max<1||max>6)throw Error('ordered.prefix_limit');
    const result:OrderedRetained[]=[];let source:string|undefined;
    try{for(let ordinal=this.nextOrdinal;result.length<max;ordinal++){
      const row=this.rows.get(ordinal);if(!row||row.state!=='retained'||!row.lease)break;
      if(source!==undefined&&row.announcement.source.sourceId!==source)break;
      this.current(row);if(!this.deps.store.owns(row.scope,row.lease.uri))throw Error('ordered.retained_file_unowned');
      source=row.announcement.source.sourceId;const {path:_,...file}=row.announcement.file;
      result.push(Object.freeze({chunk:row.announcement.chunk,source:row.announcement.source,
        file:Object.freeze({...file,uri:row.lease.uri,bytes:row.lease.bytes})}));
    }}catch(error){this.fail(error);throw error;}
    return Object.freeze(result);
  }
  private serialize(work:()=>Promise<void>):Promise<void>{
    const task=this.control.then(work);this.control=task.catch(()=>undefined);return task;
  }
  private validateSnapshot(value:unknown):OrderedNativeSnapshot{
    const s=parseOrderedNativeSnapshot(value),prior=this.native;
    if(s.streamId!==this.deps.streamId||s.generation!==this.deps.generation
      ||prior&&(s.run.id!==prior.run.id||s.run.revision!==prior.run.revision))throw Error('ordered.native_scope');
    if(s.nextOrdinal<this.nextOrdinal||prior&&(s.mutationRevision<prior.mutationRevision
      ||s.readersClosedThrough<prior.readersClosedThrough||s.publishedCursor<prior.publishedCursor
      ||s.acknowledgedCursor<prior.acknowledgedCursor))throw Error('ordered.native_regressed');
    for(let ordinal=this.nextOrdinal;ordinal<s.nextOrdinal;ordinal++){
      const row=this.rows.get(ordinal);if(!row?.lease||row.state!=='retained')throw Error('ordered.native_unretained');
    }
    return s;
  }
  /** Input is ONLY the owned native RPC's response, never Desktop metadata. */
  observeNative(value:unknown):Promise<void>{return this.serialize(async()=>{
    this.check();try{
      const s=this.validateSnapshot(value),changed=s.nextOrdinal!==this.nextOrdinal;
      this.progress.observe([...this.rows.values()].filter(row=>row.announcement.chunk.ordinal>=this.nextOrdinal
        &&row.announcement.chunk.ordinal<s.nextOrdinal).map(row=>row.announcement),s);
      this.native=s;this.nextOrdinal=s.nextOrdinal;
      if(s.state!=='open'||s.failure!==null)throw Error('ordered.native_'+(s.failure??s.state));
      this.queueRelease(s.readersClosedThrough);if(changed)this.notify();
    }catch(error){this.fail(error);throw error;}
  });}
  private queueRelease(through:number){
    this.releaseTarget=Math.max(this.releaseTarget,through);
    if(this.releasing||this.releaseWaiting||this.releaseTarget<=this.releasedThrough)return;
    // Native has already joined these readers. Remote deletion ACKs must not
    // serialize subsequent native observations, start receipts, or appends.
    // Keep every row and its capacity charged until its exact ACK completes.
    this.releasing=(async()=>{
      while(!this.stopped&&this.releasedThrough<this.releaseTarget)await this.releaseThrough(this.releaseTarget);
    })().catch(error=>{
      if(this.deps.retryable?.(error))this.releaseWaiting=true;else this.fail(error);
    }).finally(()=>{
      this.releasing=undefined;
      if(!this.stopped&&!this.releaseWaiting&&this.releasedThrough<this.releaseTarget)this.queueRelease(this.releaseTarget);
    });
  }
  private async releaseThrough(through:number){
    for(let ordinal=this.releasedThrough+1;ordinal<=through;ordinal++){
      const row=this.rows.get(ordinal);if(!row?.lease)throw Error('ordered.release_unretained');
      this.event('release_begin',ordinal);
      await(row.release??=row.lease.release());await this.deps.onReleased(ordinal);
      this.rows.delete(ordinal);this.bytes-=row.announcement.chunk.byteLength;this.releasedThrough=ordinal;this.event('released',ordinal);this.notify();
    }
  }
  /** Does not unlink retained files or turn cancellation into whole-source END. */
  stop(){this.stopped=true;this.abort.abort();this.notify();}
  /** Used only for the same registered player's whole-owner native close (also
   * covers an unpublished/open-failed queue). No inferred idle/END certificate. */
  closeAfterOwner(closeOwned:()=>Promise<unknown>,beforeRelease?:()=>Promise<void>,onJoined?:()=>void):Promise<void>{
    this.stop();return this.serialize(async()=>{
      await Promise.all([...this.rows.values()].map(row=>row.task));
      if(await closeOwned()!==true)throw Error('ordered.native_owner_close_unconfirmed');
      onJoined?.();
      await beforeRelease?.();
      await this.releasing;
      await this.releaseAllClosed();this.notify();
    });
  }
  private async releaseAllClosed(){
    if([...this.rows.values()].some(row=>row.cleanupUnconfirmed))throw Error('ordered.cleanup_unconfirmed');
    for(const [ordinal,row] of [...this.rows].sort(([a],[b])=>a-b)){
      if(row.lease)await(row.release??=row.lease.release());
      await this.deps.onReleased(ordinal);this.rows.delete(ordinal);this.bytes-=row.announcement.chunk.byteLength;
    }
  }
  closeAfterNative(value:unknown,beforeRelease?:(receipt:OrderedStoppedOutput)=>Promise<void>,onJoined?:()=>void):Promise<void>{
    this.stop();return this.serialize(async()=>{
      await Promise.all([...this.rows.values()].map(row=>row.task));
      const r=value as {version?:unknown;kind?:unknown;snapshot?:unknown;stoppedOutput?:unknown};
      if(!r||r.version!==1||r.kind!=='closed'||Object.keys(r).length!==4)throw Error('ordered.native_close_unconfirmed');
      const s=parseOrderedNativeSnapshot(r.snapshot);
      if(s.state!=='retired'||!this.native)throw Error('ordered.native_close_unconfirmed');
      const receipt=parseOrderedStoppedOutput(r.stoppedOutput);
      if(receipt.streamId!==s.streamId||receipt.generation!==s.generation
        ||receipt.known&&receipt.ordinal>=s.nextOrdinal)throw Error('ordered.stopped_scope');
      const evidence=JSON.stringify({snapshot:s,receipt});
      if(this.closedEvidence!==null){
        if(evidence!==this.closedEvidence)throw Error('ordered.native_close_changed');
      }else{
        this.validateSnapshot(s);
        if(receipt.known){
          const row=this.rows.get(receipt.ordinal);
          if(!row||receipt.frameOffset>=row.announcement.chunk.frameCount)throw Error('ordered.stopped_frame_unretained');
        }
        // Seal actual native evidence before any remote ACK. A transport retry
        // must not demand frame custody that a prior successful ACK released.
        this.closedEvidence=evidence;
      }
      onJoined?.(); // Validated native closure, independent of remote deletion.
      // Desktop resolves its own frame provenance before joined ACKs may discard
      // that descriptor. Failed feedback keeps exact custody for a safe retry.
      await beforeRelease?.(receipt);
      await this.releasing;
      // closeOrdered confirms every staged/unopened reader and physical output
      // settled too; these files may never have acquired an admitted ordinal.
      await this.releaseAllClosed();
      this.native=s;this.notify();
    });
  }
  /** Only an actively acquiring successor can justify a startup pair.
   * Unannounced, queued or capacity-waiting files must never block admission. */
  hasAcquiringSuccessor(chunk:OrderedChunk):boolean{
    const row=this.rows.get(chunk.ordinal+1),next=row?.announcement.chunk;
    return Boolean(row?.state==='acquiring'&&next&&next.sourceId===chunk.sourceId&&next.mediaId===chunk.mediaId
      &&next.sourceRange.start===chunk.sourceRange.start+chunk.frameCount);
  }
  progressSnapshot(){return this.stopped?null:this.progress.snapshot();}
  snapshot(){return Object.freeze({nextOrdinal:this.nextOrdinal,releasedThrough:this.releasedThrough,retainedFiles:this.rows.size,
    retainedBytes:this.bytes,running:this.running,closed:this.stopped,failure:this.failurePresent?this.failure:null});}
}
