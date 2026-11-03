import {IdleLoopCache,parseIdleManifest} from '../relay/idleLoopCache';
import type {IdleManifest,IdleReadyEntry,IdleSourceBinding,VerifiedLoop} from '../relay/idleLoopCache';
import {IdleLoopTransfer} from '../relay/idleLoopTransfer';
import type {IdleRange} from '../relay/idleLoopTransfer';

export type ReadyIdleLoop=Readonly<{file:VerifiedLoop;entry:IdleReadyEntry;
  binding:IdleSourceBinding;manifest:IdleManifest}>;
export type OrderedIdleInventoryStatus=Readonly<{complete:boolean;reason:string;files:number;
  totalFiles:number;bytes:number;requiredBytes:number}>;
type Dependencies={client:{readonly idleCacheScope:string;
  idleCacheRange(range:IdleRange,signal:AbortSignal,ordered:boolean):Promise<Uint8Array>};cache:IdleLoopCache;
  beforeStorageChange():Promise<void>;onChange?(status:OrderedIdleInventoryStatus):void;
  onReady?(value:ReadyIdleLoop):void|Promise<void>;onFailure?(error:unknown):void};

/** Owns verified bytes, not presentation authority. In particular neither
 * speech preparation nor a pending native handoff gates emotion downloads. */
export class OrderedIdleInventory {
  private work:Promise<void>=Promise.resolve();
  private controller?:AbortController;
  private manifest?:IdleManifest;
  private readonly verified=new Map<string,VerifiedLoop>();
  private readonly notified=new Set<string>();
  private selection='';private selected='';private revision='';private owner='';
  private epoch=0;private closed=false;private retry=false;private partialBytes=0;
  private clearing?:Promise<void>;
  private closing?:Promise<void>;
  private statusSignature='';
  status:OrderedIdleInventoryStatus={complete:false,reason:'inventory_pending',files:0,totalFiles:0,bytes:0,requiredBytes:0};
  constructor(private readonly deps:Dependencies){}
  settled(){return this.work;}
  private publish(reason:string){
    const rows=this.manifest?.loops??[];
    if(reason==='incomplete_inventory'&&rows.some(row=>row.status==='unavailable'
      &&['gpu_encoder_unavailable','gpu_encode_failed'].includes(row.reason)))reason='gpu_encoder_unavailable';
    const ready=rows.filter((row):row is IdleReadyEntry=>row.status==='ready');
    const retained=ready.filter(row=>{
      const file=this.verified.get(row.id);return file?.sha256===row.sha256&&file.bytes===row.bytes;
    });
    this.status=Object.freeze({complete:reason==='ready'&&retained.length===rows.length,
      reason,files:retained.length,totalFiles:rows.length,
      bytes:retained.reduce((n,row)=>n+row.bytes,0)+this.partialBytes,
      requiredBytes:ready.reduce((n,row)=>n+row.bytes,0)});
    // Bytes remain available for explicit diagnostics. The ordinary UI updates
    // only at file/state boundaries, not each 24-KiB network/native write.
    const signature=JSON.stringify([this.status.reason,this.status.files,this.status.totalFiles,
      this.status.requiredBytes,this.status.complete]);
    if(signature!==this.statusSignature){
      this.statusSignature=signature;
      try{this.deps.onChange?.(this.status);}catch{} // Observation cannot break transfer.
    }
  }
  private report(error:unknown){try{this.deps.onFailure?.(error);}catch{}}
  private notify(){
    const manifest=this.manifest;if(!manifest)return;
    for(const binding of manifest.sources??[]){
      const value=this.find(binding.motion_id);if(!value)continue;
      const key=JSON.stringify([manifest.revision,binding.motion_id,value.file.generation,value.file.sha256]);
      if(this.notified.has(key))continue;this.notified.add(key);
      // A UI/native consumer can schedule preparation, but must independently
      // fence its own owner. This callback is never awaited by acquisition.
      try{void Promise.resolve(this.deps.onReady?.(value)).catch(error=>{
        if(!this.closed&&this.manifest?.revision===manifest.revision)this.report(error);
      });}catch(error){this.report(error);}
    }
  }
  find(motionId:string):ReadyIdleLoop|null{
    if(this.closed||this.clearing||!this.manifest||!this.owner||this.deps.client.idleCacheScope!==this.owner)return null;
    const manifest=this.manifest,binding=manifest.sources?.find(row=>row.motion_id===motionId);
    if(!binding)return null;
    const entry=manifest.loops.find((row):row is IdleReadyEntry=>row.id===binding.loop_id&&row.status==='ready');
    const file=this.verified.get(binding.loop_id);
    if(!entry||!file||entry.sha256!==file.sha256||entry.bytes!==file.bytes)return null;
    return Object.freeze({file,entry,binding,manifest});
  }
  update(value:unknown,clearGeneration:number):void{
    if(this.closed)throw Error('ordered.idle_inventory_closed');
    if(this.clearing)return;
    if(!Number.isSafeInteger(clearGeneration)||clearGeneration<0)throw Error('ordered.idle_inventory_clear_epoch');
    const manifest=parseIdleManifest(value),scope=this.deps.client.idleCacheScope;
    if(!scope)throw Error('ordered.idle_inventory_owner');
    if(!manifest.video_quality||manifest.video_quality.video_fps!==24||!manifest.sources
      ||manifest.loops.some(row=>row.status==='ready'&&(row.fps!==24
        ||!manifest.sources!.some(binding=>binding.loop_id===row.id&&binding.source_frame_count===row.frames)))
      ||manifest.active_loop!==null&&!manifest.active_source)
      throw Error('ordered.idle_inventory_source_binding');
    const storageScope=JSON.stringify([scope,clearGeneration,manifest.video_quality]);
    const selection=JSON.stringify([storageScope,manifest.generation]);
    const changed=selection!==this.selection;
    // A mood selection changes only the desired presentation, not the pack's
    // download identity. Its active file never restarts an in-flight transfer.
    this.manifest=manifest;
    if(!changed&&this.revision===manifest.revision&&!this.retry){this.notify();return;}
    this.controller?.abort();const controller=new AbortController(),epoch=++this.epoch;
    this.controller=controller;this.retry=false;this.partialBytes=0;
    if(changed){this.verified.clear();this.notified.clear();}
    this.selection=selection;this.owner=scope;this.revision=manifest.revision;this.publish('downloading');
    const live=()=>!this.closed&&!controller.signal.aborted&&this.epoch===epoch
      &&this.deps.client.idleCacheScope===scope;
    const previous=this.work;
    this.work=previous.catch(()=>undefined).then(async()=>{
      if(!live())return;
      if(this.selected!==selection){
        // Native select may purge old-pack files. Real presentation retirement
        // and reader join must complete before it can touch storage.
        await this.deps.beforeStorageChange();if(!live())return;
        await this.deps.cache.select(storageScope,manifest.generation);if(!live())return;
        this.selected=selection;
      }
      this.deps.cache.setInventory(manifest);
      for(const row of manifest.loops){
        if(row.status!=='ready')continue;
        const file=await this.deps.cache.get(row.id);if(!live())return;
        if(file&&file.sha256===row.sha256&&file.bytes===row.bytes)this.verified.set(row.id,file);
        else this.verified.delete(row.id);
      }
      this.publish('downloading');this.notify();
      const transfer=new IdleLoopTransfer(this.deps.cache,async(range,signal)=>{
        if(!live())throw Error('ordered.idle_inventory_owner');
        const bytes=await this.deps.client.idleCacheRange(range,signal,true);
        if(!live())throw Error('ordered.idle_inventory_owner');
        this.partialBytes=range.offset+bytes.byteLength;this.publish('downloading');return bytes;
      },()=>false,undefined,async entry=>{
        const file=await this.deps.cache.get(entry.id);if(!live())return;
        if(!file||file.sha256!==entry.sha256||file.bytes!==entry.bytes)throw Error('ordered.idle_inventory_integrity');
        this.verified.set(entry.id,file);this.partialBytes=0;this.publish('downloading');this.notify();
      });
      const result=await transfer.sync(manifest,controller.signal);if(!live())return;
      this.partialBytes=0;this.publish(result.reason);
    }).catch(error=>{
      if(live()){
        this.retry=true;this.partialBytes=0;this.publish('failed');
        this.report(error);
        throw error;
      }
    });
    void this.work.catch(()=>undefined);
  }
  close():Promise<void>{
    if(this.closing)return this.closing;
    this.closed=true;++this.epoch;this.controller?.abort();this.verified.clear();this.notified.clear();
    this.partialBytes=0;this.publish('paused');
    return this.closing=this.work.catch(()=>undefined).then(()=>this.clearing).then(()=>this.deps.beforeStorageChange());
  }
  pause(reason='paused'):Promise<void>{
    if(this.closed)return this.work.catch(()=>undefined);
    if(!this.selection&&!this.verified.size&&this.controller?.signal.aborted){this.publish(reason);return this.work;}
    ++this.epoch;(this.controller??=new AbortController()).abort();this.verified.clear();this.notified.clear();this.partialBytes=0;
    this.selection='';this.selected='';this.revision='';this.owner='';this.publish(reason);
    const previous=this.work,clearing=this.clearing;
    this.work=previous.catch(()=>undefined).then(()=>clearing).then(()=>this.deps.beforeStorageChange());
    void this.work.catch(()=>undefined);return this.work;
  }
  clear():Promise<void>{
    if(this.closed)return Promise.reject(Error('ordered.idle_inventory_closed'));
    if(this.clearing)return this.clearing;
    ++this.epoch;this.controller?.abort();this.verified.clear();this.notified.clear();this.partialBytes=0;
    this.publish('cleared');
    return this.clearing=this.work.catch(()=>undefined).then(async()=>{
      await this.deps.beforeStorageChange();await this.deps.cache.clear();
      this.selected='';this.selection='';this.revision='';
    }).finally(()=>{this.clearing=undefined;});
  }
}
