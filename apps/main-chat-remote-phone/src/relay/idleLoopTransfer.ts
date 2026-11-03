import {IdleLoopCache,IDLE_CACHE_LIMIT,IDLE_WRITE_LIMIT,parseIdleManifest} from './idleLoopCache';
import type {IdleReadyEntry} from './idleLoopCache';
export type IdleRange = {generation:string;id:string;offset:number;length:number};
export type IdleSyncStatus = {complete:boolean;reason:string;files:number;requiredBytes:number};
type ReadRange = (range:IdleRange,signal:AbortSignal)=>Promise<Uint8Array>;
function check(signal:AbortSignal) { if(signal.aborted) throw new Error('Idle transfer cancelled.'); }
function pause(signal:AbortSignal) {
  check(signal);
  return new Promise<void>((resolve,reject)=>{
    const cancel=()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);reject(new Error('Idle transfer cancelled.'));};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},100);
    signal.addEventListener('abort',cancel,{once:true});
  });
}

/** One whole-loop request at a time, then bounded binary writes to the cache. */
export class IdleLoopTransfer {
  private running=false;
  constructor(private cache:IdleLoopCache,private read:ReadRange,private busy=()=>false,
              private yieldWork:(signal:AbortSignal)=>Promise<void>=pause,
              private ready:(entry:IdleReadyEntry)=>Promise<void>=async()=>{}) {}
  async sync(value:unknown,signal:AbortSignal):Promise<IdleSyncStatus> {
    check(signal);
    if(this.running) throw new Error('Idle transfer already running.');
    const manifest=parseIdleManifest(value);
    this.cache.setInventory(manifest);
    const entries=manifest.loops.filter((row):row is IdleReadyEntry=>row.status==='ready');
    entries.sort((a,b)=>Number(b.id===manifest.active_loop)-Number(a.id===manifest.active_loop));
    const requiredBytes=entries.reduce((n,row)=>n+row.bytes,0);
    let files=0;
    this.running=true;
    try {
      for(const entry of entries) {
        check(signal);
        const existing=await this.cache.get(entry.id);
        if(existing && existing.sha256===entry.sha256 && existing.bytes===entry.bytes) { files++; continue; }
        const usage=await this.cache.usage(); check(signal);
        if(usage.bytes+entry.bytes>IDLE_CACHE_LIMIT) return {complete:false,reason:'storage_limited',files,requiredBytes};
        await this.cache.put(entry,this.ranges(manifest.generation,entry,signal),signal);
        check(signal);await this.ready(entry);check(signal);
        files++;
      }
      check(signal);
      const complete=files===manifest.loops.length;
      return {complete,reason:complete?'ready':'incomplete_inventory',files,requiredBytes};
    } finally { this.running=false; }
  }
  private async *ranges(generation:string,entry:IdleReadyEntry,signal:AbortSignal) {
    check(signal);
    while(this.busy()) { await this.yieldWork(signal);check(signal); }
    // One file is bounded by IDLE_FILE_LIMIT. Do not add a network round trip
    // for each storage write or buffer the complete avatar pack.
    const bytes=await this.read({generation,id:entry.id,offset:0,length:entry.bytes},signal);
    check(signal);
    if(bytes.byteLength!==entry.bytes) throw new Error('Idle range length mismatch.');
    for(let offset=0;offset<bytes.byteLength;offset+=IDLE_WRITE_LIMIT) {
      check(signal);yield bytes.subarray(offset,Math.min(offset+IDLE_WRITE_LIMIT,bytes.byteLength));
    }
  }
}
