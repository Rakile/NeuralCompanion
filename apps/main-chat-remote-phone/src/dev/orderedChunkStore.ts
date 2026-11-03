import {BufferedMediaCleanupError} from '../relay/bufferedMedia';
import type {BufferedMediaStore,BufferedMediaScope,BufferedMediaLease} from '../relay/bufferedMedia';
import type {OrderedIdleCacheIO} from '../native/orderedIdleCacheIO';
import type {OrderedAnnouncement} from './desktopOrderedProtocol';
import {orderedCacheFailure} from '../diagnostics/orderedIdleCache';

export type OrderedCachePolicy=Readonly<{mode:'on'|'off'|'unknown';epoch:number}>;
export type OrderedCacheEvent=Readonly<{phase:string;reason:string;streamId?:string;generation?:number;
  ordinal?:number;digest?:string;epoch:number;bytes:number}>;
type Dependencies={download:Pick<BufferedMediaStore,'acquire'|'owns'>;cache:OrderedIdleCacheIO|null;
  current(scope:BufferedMediaScope):boolean;policy():OrderedCachePolicy;
  onEvent?(event:OrderedCacheEvent):void;onFailure?(error:unknown):void};
const availableFailure=(error:unknown)=>/\b(?:ordered_idle_cache_(?:storage|closed|scope_capacity|finalize|cleanup|partial_cleanup)|ENOSPC|EACCES|EIO)\b/.test(String(error));

/** A verified reusable file substitutes bytes, never occurrence authority.
 * Delivery still owns each lease until its exact native readers have joined. */
export class OrderedChunkStore {
  private readonly pins=new Map<string,{scope:BufferedMediaScope;uri:string}>();
  private clearing?:{owner:string;epoch:number;task:Promise<void>};
  private importing?:Promise<void>;
  constructor(private readonly deps:Dependencies){}
  private key(scope:BufferedMediaScope){return JSON.stringify([scope.owner,scope.replyId,scope.expiresAt]);}
  private check(scope:BufferedMediaScope,signal?:AbortSignal){
    if(!scope.owner||!scope.replyId||!Number.isSafeInteger(scope.expiresAt)||scope.expiresAt<=Date.now()
      ||!this.deps.current(scope))throw Error('ordered.cache_authority_changed');
    if(signal?.aborted)throw Error('ordered.cache_acquisition_cancelled');
  }
  private policy(){
    const value=this.deps.policy();
    if(!['on','off','unknown'].includes(value.mode)||!Number.isSafeInteger(value.epoch)||value.epoch<0)
      throw Error('ordered.cache_policy');
    return value;
  }
  private event(phase:string,reason:string,epoch:number,row?:OrderedAnnouncement,bytes=0){
    try{this.deps.onEvent?.({phase,reason,epoch,bytes,...row&&{streamId:row.chunk.streamId,
      generation:row.chunk.generation,ordinal:row.chunk.ordinal,digest:row.chunk.sha256}});}catch{}
  }
  /** Also called while OFF: Desktop clear-generation is live, mode is not. */
  async syncPolicy(scope:BufferedMediaScope){
    this.check(scope);const policy=this.policy(),cache=this.deps.cache;
    if(!cache||policy.mode==='unknown')return;
    if(this.clearing?.owner===scope.owner&&this.clearing.epoch===policy.epoch)return this.clearing.task;
    const task=cache.clear(scope.owner,policy.epoch).then(()=>this.event('clear','applied',policy.epoch)).catch(error=>{
      if(this.clearing?.task===task)this.clearing=undefined;
      this.event('clear_failed',orderedCacheFailure(error),policy.epoch);if(!availableFailure(error))throw error;
    });
    this.clearing={owner:scope.owner,epoch:policy.epoch,task};return task;
  }
  async acquire(scope:BufferedMediaScope,row:OrderedAnnouncement,signal?:AbortSignal):Promise<BufferedMediaLease>{
    this.check(scope,signal);await this.syncPolicy(scope);this.check(scope,signal);
    const policy=this.policy(),cache=this.deps.cache,{chunk,file}=row;
    if(policy.mode==='unknown')throw Error('ordered.cache_policy_unresolved');
    const eligible=policy.mode==='on'&&chunk.kind==='idle'&&cache!==null;
    if(eligible){
      let hit;
      try{hit=await cache.acquire(scope.owner,chunk.sha256,chunk.byteLength,policy.epoch);}
      catch(error){this.event('lookup_failed',orderedCacheFailure(error),policy.epoch,row);if(!availableFailure(error))throw error;}
      if(hit){
        let releaseTask:Promise<void>|undefined;
        const release=()=>releaseTask??=(async()=>{await cache.release(hit.pin);this.pins.delete(hit.pin);
          this.event('release','reader_joined',policy.epoch,row);})();
        try{
          this.check(scope,signal);
          if(hit.bytes!==chunk.byteLength||!hit.pin||!/^file:\//.test(hit.uri)||this.pins.has(hit.pin))
            throw Error('ordered.cache_pin_invalid');
          if(this.policy().epoch===policy.epoch&&this.policy().mode==='on'){
            this.pins.set(hit.pin,{scope:{...scope},uri:hit.uri});
            this.event('hit','verified',policy.epoch,row,hit.bytes);
            return {uri:hit.uri,bytes:hit.bytes,release};
          }
          await release(); // Clear won before admission; use the authenticated route below.
        }catch(error){try{await release();}catch{throw new BufferedMediaCleanupError();}throw error;}
      }
      this.event('miss','not_retained',policy.epoch,row);
    }
    this.check(scope,signal);
    const descriptor={id:`ordered-${chunk.streamId}-${chunk.generation}-${chunk.ordinal}`,
      path:file.path,bytes:chunk.byteLength,contentType:'video/mp4'};
    const lease=await this.deps.download.acquire(scope,descriptor,signal);
    // BufferedMediaStore has already fenced pending cancellation and now holds
    // reader custody. Its lease stays with Delivery even if Stop wins next.
    if(eligible&&!this.importing&&this.deps.current(scope)&&!signal?.aborted){
      const epoch=this.policy().epoch;
      // Acquire another consumer before returning playback's consumer. The
      // same file/reservation stays charged until this bounded copy completes.
      const retained=this.deps.download.acquire(scope,descriptor,signal);
      this.importing=(async()=>{
        let source:BufferedMediaLease|undefined;
        try{
          source=await retained;this.check(scope,signal);
          if(this.policy().mode!=='on'||this.policy().epoch!==epoch)return;
          const stored=await cache!.importFile(scope.owner,chunk.sha256,chunk.byteLength,epoch,source.uri);
          this.event('import',stored?'stored':'not_stored',epoch,row);
        }catch(error){
          this.event('import_failed',orderedCacheFailure(error),epoch,row);
          // Optional disk unavailability cannot stop a valid occurrence.
          // Integrity/contract failures remain explicit, not successful imports.
          if(!availableFailure(error)&&this.deps.current(scope)&&!signal?.aborted)this.deps.onFailure?.(error);
        }finally{
          if(source)try{await source.release();}catch(error){this.deps.onFailure?.(error);}
        }
      })().finally(()=>{this.importing=undefined;});
    }
    return lease;
  }
  owns(scope:BufferedMediaScope,uri:string):boolean{
    try{this.check(scope);}catch{return false;}
    return [...this.pins.values()].some(pin=>pin.uri===uri&&this.key(pin.scope)===this.key(scope))
      ||this.deps.download.owns(scope,uri);
  }
}
